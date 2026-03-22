use std::cmp::Ordering;
use std::collections::{BTreeMap, HashMap, VecDeque};
use std::fs;
use std::path::{Path, PathBuf};

use anyhow::{bail, Context, Result};
use serde::Serialize;

use crate::archive::index::MinuteOffsetsIndex;
use crate::archive::manifest::{config_fingerprint, DayPackManifest};
use crate::archive::materialize::{self, VisitControl};
use crate::archive::{self, DayPackLayout};
use crate::config::schema::{Config, ReplaySelectionKey};
use crate::model::normalized_event::NormalizedEvent;

#[derive(Debug, Clone, Serialize)]
pub struct ReplaySampleReport {
    pub schema_version: String,
    pub archive_root: PathBuf,
    pub source_day: String,
    pub start_second: u32,
    pub duration_secs: u32,
    pub source_event_count: u64,
    pub emitted_event_count: u64,
    pub deduped_event_count: u64,
    pub overflow_event_count: u64,
    pub seconds_with_source_events: u64,
    pub seconds_with_emission: u64,
    pub config_fingerprint: String,
    pub seconds: Vec<ReplaySecondBucket>,
}

#[derive(Debug, Clone, Serialize)]
pub struct ReplaySecondBucket {
    pub second_of_day: u32,
    pub source_event_count: u64,
    pub emitted_event_count: u64,
    pub deduped_event_count: u64,
    pub overflow_event_count: u64,
    pub emitted_events: Vec<ReplayEmittedEvent>,
}

#[derive(Debug, Clone, Serialize, PartialEq, Eq)]
pub struct ReplayEmittedEvent {
    pub event_id: String,
    pub event_type: String,
    pub weight: u8,
    pub created_at_utc: String,
    pub repo_full_name: String,
    pub actor_login: String,
    pub display_hash: String,
    pub raw_ref: String,
}

pub fn sample_day_pack(
    config: &Config,
    day: &str,
    archive_root_override: Option<&Path>,
    start_second: u32,
    duration_secs: u32,
) -> Result<ReplaySampleReport> {
    archive::validate_day(day)?;
    if start_second >= 86_400 {
        bail!("--start-second must be within 0..86400");
    }
    if duration_secs == 0 {
        bail!("--duration-secs must be >= 1");
    }

    let archive_root = archive::resolve_archive_root(config, archive_root_override);
    let layout = DayPackLayout::new(archive_root.clone(), day.to_string());
    let manifest = load_manifest(&layout)?;
    let minute_offsets = load_minute_offsets(&layout)?;
    if !manifest.complete {
        bail!("manifest marks day-pack as incomplete");
    }
    if minute_offsets.hours.len() != 24 {
        bail!("minute_offsets.json must declare 24 hours");
    }

    let end_second = start_second.saturating_add(duration_secs).min(86_400);
    let actual_duration_secs = end_second - start_second;
    let events_by_second = load_events_by_second(
        &archive_root,
        &manifest,
        &minute_offsets,
        start_second,
        end_second,
    )?;

    let mut dedupe = DedupeState::default();
    let mut seconds = Vec::new();
    let mut source_event_count = 0_u64;
    let mut emitted_event_count = 0_u64;
    let mut deduped_event_count = 0_u64;
    let mut overflow_event_count = 0_u64;
    let mut seconds_with_source_events = 0_u64;
    let mut seconds_with_emission = 0_u64;
    let mut events_by_second = events_by_second;

    for second in start_second..end_second {
        let events = events_by_second.remove(&second).unwrap_or_default();
        if !events.is_empty() {
            seconds_with_source_events += 1;
        }
        let bucket = select_second_events(
            second,
            events,
            config.replay.max_events_per_second as usize,
            config.replay.dedupe_window_secs,
            &config.replay.selection_order,
            &mut dedupe,
        );
        source_event_count += bucket.source_event_count;
        emitted_event_count += bucket.emitted_event_count;
        deduped_event_count += bucket.deduped_event_count;
        overflow_event_count += bucket.overflow_event_count;
        if bucket.emitted_event_count > 0 {
            seconds_with_emission += 1;
        }
        if bucket.source_event_count > 0 {
            seconds.push(bucket);
        }
    }

    Ok(ReplaySampleReport {
        schema_version: "stage3.replay_sample.v1".to_string(),
        archive_root,
        source_day: day.to_string(),
        start_second,
        duration_secs: actual_duration_secs,
        source_event_count,
        emitted_event_count,
        deduped_event_count,
        overflow_event_count,
        seconds_with_source_events,
        seconds_with_emission,
        config_fingerprint: config_fingerprint(config)?,
        seconds,
    })
}

fn load_manifest(layout: &DayPackLayout) -> Result<DayPackManifest> {
    toml::from_str(
        &fs::read_to_string(&layout.manifest_path)
            .with_context(|| format!("failed to read {}", layout.manifest_path.display()))?,
    )
    .with_context(|| format!("failed to parse {}", layout.manifest_path.display()))
}

fn load_minute_offsets(layout: &DayPackLayout) -> Result<MinuteOffsetsIndex> {
    serde_json::from_str(
        &fs::read_to_string(&layout.minute_offsets_path)
            .with_context(|| format!("failed to read {}", layout.minute_offsets_path.display()))?,
    )
    .with_context(|| format!("failed to parse {}", layout.minute_offsets_path.display()))
}

fn load_events_by_second(
    archive_root: &Path,
    manifest: &DayPackManifest,
    minute_offsets: &MinuteOffsetsIndex,
    start_second: u32,
    end_second: u32,
) -> Result<BTreeMap<u32, Vec<NormalizedEvent>>> {
    let mut events_by_second = BTreeMap::<u32, Vec<NormalizedEvent>>::new();
    let start_hour = start_second / 3600;
    let end_hour = (end_second.saturating_sub(1)) / 3600;

    for hour in start_hour..=end_hour {
        let hour_index = minute_offsets
            .hours
            .get(hour as usize)
            .ok_or_else(|| anyhow::anyhow!("missing minute_offsets hour {hour}"))?;
        if hour_index.hour as u32 != hour {
            bail!(
                "minute_offsets hour slot {} points at {}",
                hour,
                hour_index.hour
            );
        }
        if hour_index.minute_offsets.len() != 60 {
            bail!(
                "minute_offsets hour {} must declare 60 minute entries",
                hour
            );
        }

        let hour_start = hour * 3600;
        let segment_start = start_second.max(hour_start);
        let segment_end = end_second.min(hour_start + 3600);
        if segment_start >= segment_end {
            continue;
        }

        let start_minute = ((segment_start - hour_start) / 60) as usize;
        let end_minute = ((segment_end - 1 - hour_start) / 60) as usize;
        let start_index = hour_index.minute_offsets[start_minute].event_index_offset;
        let end_index = if end_minute == 59 {
            normalized_event_count_for_hour(manifest, hour as u8)?
        } else {
            hour_index.minute_offsets[end_minute + 1].event_index_offset
        };

        if start_index == end_index {
            continue;
        }

        let normalized_path = archive_root.join(&hour_index.normalized_relative_path);
        materialize::visit_encoded_lines(&normalized_path, |line_index, line| {
            if line_index < start_index {
                return Ok(VisitControl::Continue);
            }
            if line_index >= end_index {
                return Ok(VisitControl::Break);
            }

            let event: NormalizedEvent = serde_json::from_str(line).with_context(|| {
                format!(
                    "failed to parse normalized event in {}",
                    normalized_path.display()
                )
            })?;
            if event.second_of_day >= segment_start && event.second_of_day < segment_end {
                events_by_second
                    .entry(event.second_of_day)
                    .or_default()
                    .push(event);
            }
            Ok(VisitControl::Continue)
        })?;
    }

    Ok(events_by_second)
}

fn normalized_event_count_for_hour(manifest: &DayPackManifest, hour: u8) -> Result<u64> {
    manifest
        .normalized_hours
        .iter()
        .find(|entry| entry.hour == hour)
        .map(|entry| entry.event_count)
        .ok_or_else(|| anyhow::anyhow!("manifest missing normalized hour {hour:02}"))
}

fn select_second_events(
    second_of_day: u32,
    mut events: Vec<NormalizedEvent>,
    max_events_per_second: usize,
    dedupe_window_secs: u32,
    selection_order: &[ReplaySelectionKey],
    dedupe: &mut DedupeState,
) -> ReplaySecondBucket {
    dedupe.prune(second_of_day, dedupe_window_secs);
    events.sort_by(|left, right| compare_events(left, right, selection_order));

    let mut emitted_events = Vec::new();
    let mut deduped_event_count = 0_u64;
    let mut overflow_event_count = 0_u64;

    for event in &events {
        if dedupe.contains(&event.event_id) {
            deduped_event_count += 1;
            continue;
        }
        if emitted_events.len() >= max_events_per_second {
            overflow_event_count += 1;
            continue;
        }
        dedupe.record(second_of_day, &event.event_id);
        emitted_events.push(ReplayEmittedEvent::from(event));
    }

    ReplaySecondBucket {
        second_of_day,
        source_event_count: events.len() as u64,
        emitted_event_count: emitted_events.len() as u64,
        deduped_event_count,
        overflow_event_count,
        emitted_events,
    }
}

fn compare_events(
    left: &NormalizedEvent,
    right: &NormalizedEvent,
    selection_order: &[ReplaySelectionKey],
) -> Ordering {
    for key in selection_order {
        let ordering = match key {
            ReplaySelectionKey::WeightDesc => right.weight.cmp(&left.weight),
            ReplaySelectionKey::CreatedAtAsc => left.created_at_utc.cmp(&right.created_at_utc),
            ReplaySelectionKey::EventIdAsc => left.event_id.cmp(&right.event_id),
        };
        if ordering != Ordering::Equal {
            return ordering;
        }
    }
    Ordering::Equal
}

#[derive(Debug, Default)]
struct DedupeState {
    order: VecDeque<(u32, String)>,
    emitted_at: HashMap<String, u32>,
}

impl DedupeState {
    fn prune(&mut self, second_of_day: u32, dedupe_window_secs: u32) {
        while let Some((emitted_second, event_id)) = self.order.front() {
            if second_of_day.saturating_sub(*emitted_second) < dedupe_window_secs {
                break;
            }
            let event_id = event_id.clone();
            self.order.pop_front();
            self.emitted_at.remove(&event_id);
        }
    }

    fn contains(&self, event_id: &str) -> bool {
        self.emitted_at.contains_key(event_id)
    }

    fn record(&mut self, second_of_day: u32, event_id: &str) {
        let event_id = event_id.to_string();
        self.emitted_at.insert(event_id.clone(), second_of_day);
        self.order.push_back((second_of_day, event_id));
    }
}

impl From<&NormalizedEvent> for ReplayEmittedEvent {
    fn from(value: &NormalizedEvent) -> Self {
        Self {
            event_id: value.event_id.clone(),
            event_type: value.event_type.clone(),
            weight: value.weight,
            created_at_utc: value.created_at_utc.clone(),
            repo_full_name: value.repo_full_name.clone(),
            actor_login: value.actor_login.clone(),
            display_hash: value.display_hash.clone(),
            raw_ref: value.raw_ref.clone(),
        }
    }
}

#[cfg(test)]
mod tests {
    use std::collections::BTreeMap;

    use tempfile::tempdir;

    use super::*;
    use crate::archive;
    use crate::config::schema::Config;

    #[test]
    fn replay_sample_uses_fixture_day_pack() {
        let temp = tempdir().expect("tempdir");
        let archive_root = temp.path().join("archive");
        let day = "2026-03-19";

        archive::seed_fixture_raw(&archive_root, day, true).expect("seed fixture");

        let mut config = Config::default();
        config.archive.root_dir = archive_root.display().to_string();
        archive::prepare_day_pack(&config, day, Some(&archive_root), true, true).expect("prepare");

        let report = sample_day_pack(&config, day, Some(&archive_root), 0, 7_200).expect("sample");
        assert_eq!(report.source_event_count, 2);
        assert_eq!(report.emitted_event_count, 2);
        assert_eq!(report.seconds_with_source_events, 2);
        assert_eq!(report.seconds.len(), 2);
        assert_eq!(report.seconds[0].second_of_day, 754);
        assert_eq!(
            report.seconds[0].emitted_events[0].event_id,
            "2026-03-19-00-primary"
        );
        assert_eq!(report.seconds[1].second_of_day, 4_354);
        assert_eq!(
            report.seconds[1].emitted_events[0].event_id,
            "2026-03-19-01-primary"
        );
    }

    #[test]
    fn selection_applies_dedupe_before_overflow() {
        let mut dedupe = DedupeState::default();
        dedupe.record(5, "dup");

        let bucket = select_second_events(
            100,
            vec![
                sample_event("dup", 100, "2026-03-19T00:01:40Z"),
                sample_event("e2", 90, "2026-03-19T00:01:40Z"),
                sample_event("e3", 80, "2026-03-19T00:01:40Z"),
                sample_event("e4", 70, "2026-03-19T00:01:40Z"),
                sample_event("e5", 60, "2026-03-19T00:01:40Z"),
                sample_event("e6", 50, "2026-03-19T00:01:40Z"),
            ],
            4,
            600,
            &[
                ReplaySelectionKey::WeightDesc,
                ReplaySelectionKey::CreatedAtAsc,
                ReplaySelectionKey::EventIdAsc,
            ],
            &mut dedupe,
        );

        assert_eq!(bucket.source_event_count, 6);
        assert_eq!(bucket.emitted_event_count, 4);
        assert_eq!(bucket.deduped_event_count, 1);
        assert_eq!(bucket.overflow_event_count, 1);
        assert_eq!(
            bucket
                .emitted_events
                .iter()
                .map(|event| event.event_id.as_str())
                .collect::<Vec<_>>(),
            vec!["e2", "e3", "e4", "e5"]
        );
    }

    fn sample_event(event_id: &str, weight: u8, created_at_utc: &str) -> NormalizedEvent {
        let mut text_fields = BTreeMap::new();
        text_fields.insert("repo".to_string(), "fixture/repo".to_string());
        NormalizedEvent {
            event_id: event_id.to_string(),
            source_day: "2026-03-19".to_string(),
            source_hour: 0,
            created_at_utc: created_at_utc.to_string(),
            second_of_day: 100,
            event_type: "PushEvent".to_string(),
            weight,
            repo_full_name: "fixture/repo".to_string(),
            actor_login: "fixture_actor".to_string(),
            display_hash: "deadbeef".to_string(),
            text_fields,
            audio_class: "PushEvent".to_string(),
            visual_class: "PushEvent".to_string(),
            raw_ref: "2026-03-19/raw/00.json.gz#line:1".to_string(),
        }
    }
}
