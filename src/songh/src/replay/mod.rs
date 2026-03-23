mod engine;

use std::collections::BTreeMap;
use std::fs;
use std::path::{Path, PathBuf};

use anyhow::{bail, Context, Result};
use serde::Serialize;

use crate::archive::index::MinuteOffsetsIndex;
use crate::archive::manifest::{config_fingerprint, DayPackManifest};
use crate::archive::materialize::{self, VisitControl};
use crate::archive::{self, DayPackLayout};
use crate::config::schema::Config;
use crate::model::normalized_event::NormalizedEvent;

pub use engine::{ReplayEngine, ReplayTick};

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
pub struct ReplayDryRunReport {
    pub schema_version: String,
    pub archive_root: PathBuf,
    pub source_day: String,
    pub start_second: u32,
    pub duration_secs: u32,
    pub ticks: Vec<ReplayTick>,
}

#[derive(Debug, Clone, Serialize)]
pub struct ReplaySecondBucket {
    pub source_day: String,
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

    let mut engine = ReplayEngine::open(config, day, archive_root_override, start_second)?;
    let archive_root = engine.archive_root().to_path_buf();

    let mut seconds = Vec::new();
    let mut source_event_count = 0_u64;
    let mut emitted_event_count = 0_u64;
    let mut deduped_event_count = 0_u64;
    let mut overflow_event_count = 0_u64;
    let mut seconds_with_source_events = 0_u64;
    let mut seconds_with_emission = 0_u64;
    let mut actual_duration_secs = 0_u32;

    for _ in 0..duration_secs {
        let Some(tick) = engine.next_tick()? else {
            break;
        };
        actual_duration_secs += 1;
        source_event_count += tick.source_event_count;
        emitted_event_count += tick.emitted_event_count;
        deduped_event_count += tick.deduped_count;
        overflow_event_count += tick.overflow_count;
        if tick.source_event_count > 0 {
            seconds_with_source_events += 1;
        }
        if tick.emitted_event_count > 0 {
            seconds_with_emission += 1;
        }
        if tick.source_event_count > 0 {
            seconds.push(ReplaySecondBucket::from_tick(&tick));
        }
    }

    Ok(ReplaySampleReport {
        schema_version: "stage3.replay_sample.v2".to_string(),
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

pub fn dry_run_day_pack(
    config: &Config,
    day: &str,
    archive_root_override: Option<&Path>,
    start_second: u32,
    duration_secs: u32,
) -> Result<ReplayDryRunReport> {
    archive::validate_day(day)?;
    if start_second >= 86_400 {
        bail!("--start-second must be within 0..86400");
    }
    if duration_secs == 0 {
        bail!("--duration-secs must be >= 1");
    }

    let mut engine = ReplayEngine::open(config, day, archive_root_override, start_second)?;
    let archive_root = engine.archive_root().to_path_buf();
    let mut ticks = Vec::new();

    for _ in 0..duration_secs {
        let Some(tick) = engine.next_tick()? else {
            break;
        };
        ticks.push(tick);
    }

    Ok(ReplayDryRunReport {
        schema_version: "stage3.replay_dry_run.v1".to_string(),
        archive_root,
        source_day: day.to_string(),
        start_second,
        duration_secs: ticks.len() as u32,
        ticks,
    })
}

impl ReplaySecondBucket {
    fn from_tick(tick: &ReplayTick) -> Self {
        Self {
            source_day: tick.source_day.clone(),
            second_of_day: tick.second_of_day,
            source_event_count: tick.source_event_count,
            emitted_event_count: tick.emitted_event_count,
            deduped_event_count: tick.deduped_count,
            overflow_event_count: tick.overflow_count,
            emitted_events: tick.events.iter().map(ReplayEmittedEvent::from).collect(),
        }
    }
}

impl From<&crate::model::runtime_event::RuntimeEvent> for ReplayEmittedEvent {
    fn from(value: &crate::model::runtime_event::RuntimeEvent) -> Self {
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

#[cfg(test)]
mod tests {
    use tempfile::tempdir;

    use super::*;
    use crate::archive;

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
        assert_eq!(report.seconds[0].source_day, day);
        assert_eq!(report.seconds[0].second_of_day, 754);
        assert_eq!(
            report.seconds[0].emitted_events[0].event_id,
            "2026-03-19-00-primary"
        );
        assert_eq!(report.seconds[1].source_day, day);
        assert_eq!(report.seconds[1].second_of_day, 4_354);
        assert_eq!(
            report.seconds[1].emitted_events[0].event_id,
            "2026-03-19-01-primary"
        );
    }

    #[test]
    fn replay_sample_rolls_over_to_next_day_pack() {
        let temp = tempdir().expect("tempdir");
        let archive_root = temp.path().join("archive");
        let first_day = "2026-03-19";
        let second_day = "2026-03-20";

        archive::seed_fixture_raw(&archive_root, first_day, true).expect("seed first fixture");
        archive::seed_fixture_raw(&archive_root, second_day, true).expect("seed second fixture");

        let mut config = Config::default();
        config.archive.root_dir = archive_root.display().to_string();
        archive::prepare_day_pack(&config, first_day, Some(&archive_root), true, true)
            .expect("prepare first day");
        archive::prepare_day_pack(&config, second_day, Some(&archive_root), true, true)
            .expect("prepare second day");

        let report = sample_day_pack(&config, first_day, Some(&archive_root), 86_000, 1_200)
            .expect("sample across midnight");

        assert_eq!(report.duration_secs, 1_200);
        assert_eq!(report.seconds.len(), 1);
        assert_eq!(report.seconds[0].source_day, second_day);
        assert_eq!(report.seconds[0].second_of_day, 754);
        assert_eq!(
            report.seconds[0].emitted_events[0].event_id,
            "2026-03-20-00-primary"
        );
    }

    #[test]
    fn replay_dry_run_reports_both_days_across_midnight() {
        let temp = tempdir().expect("tempdir");
        let archive_root = temp.path().join("archive");
        let first_day = "2026-03-19";
        let second_day = "2026-03-20";

        archive::seed_fixture_raw(&archive_root, first_day, true).expect("seed first fixture");
        archive::seed_fixture_raw(&archive_root, second_day, true).expect("seed second fixture");

        let mut config = Config::default();
        config.archive.root_dir = archive_root.display().to_string();
        archive::prepare_day_pack(&config, first_day, Some(&archive_root), true, true)
            .expect("prepare first day");
        archive::prepare_day_pack(&config, second_day, Some(&archive_root), true, true)
            .expect("prepare second day");

        let report = dry_run_day_pack(&config, first_day, Some(&archive_root), 86_390, 20)
            .expect("dry run across midnight");

        assert_eq!(report.duration_secs, 20);
        assert_eq!(
            report.ticks.first().expect("first tick").source_day,
            first_day
        );
        assert_eq!(report.ticks[10].source_day, second_day);
        assert_eq!(report.ticks[10].second_of_day, 0);
        assert_eq!(
            report.ticks.last().expect("last tick").source_day,
            second_day
        );
        assert_eq!(report.ticks.last().expect("last tick").second_of_day, 9);
    }
}
