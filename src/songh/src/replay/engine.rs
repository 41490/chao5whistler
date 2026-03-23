use std::cmp::Ordering;
use std::collections::{BTreeMap, HashMap, VecDeque};
use std::fs;
use std::path::{Path, PathBuf};

use anyhow::{bail, Context, Result};
use serde::Serialize;

use crate::archive;
use crate::archive::index::MinuteOffsetsIndex;
use crate::archive::manifest::DayPackManifest;
use crate::config::schema::{Config, ReplaySelectionKey};
use crate::model::normalized_event::NormalizedEvent;
use crate::model::runtime_event::RuntimeEvent;

use super::{load_events_by_second, load_manifest, load_minute_offsets};

#[derive(Debug, Clone, Serialize, PartialEq, Eq)]
pub struct ReplayTick {
    pub replay_second: u64,
    pub source_day: String,
    pub second_of_day: u32,
    pub source_event_count: u64,
    pub emitted_event_count: u64,
    pub deduped_count: u64,
    pub overflow_count: u64,
    pub is_fallback: bool,
    pub events: Vec<RuntimeEvent>,
}

pub struct ReplayEngine {
    archive_root: PathBuf,
    max_events_per_second: usize,
    dedupe_window_secs: u32,
    selection_order: Vec<ReplaySelectionKey>,
    replay_second: u64,
    current_second_of_day: u32,
    current_day: LoadedDayPack,
    dedupe: DedupeState,
    buffered_hour: Option<u32>,
    buffered_events: BTreeMap<u32, Vec<NormalizedEvent>>,
    exhausted: bool,
}

impl ReplayEngine {
    pub fn open(
        config: &Config,
        start_day: &str,
        archive_root_override: Option<&Path>,
        start_second: u32,
    ) -> Result<Self> {
        archive::validate_day(start_day)?;
        if start_second >= 86_400 {
            bail!("--start-second must be within 0..86400");
        }

        let archive_root = archive::resolve_archive_root(config, archive_root_override);
        let current_day = LoadedDayPack::load(&archive_root, start_day)?;

        Ok(Self {
            archive_root,
            max_events_per_second: config.replay.max_events_per_second as usize,
            dedupe_window_secs: config.replay.dedupe_window_secs,
            selection_order: config.replay.selection_order.clone(),
            replay_second: 0,
            current_second_of_day: start_second,
            current_day,
            dedupe: DedupeState::default(),
            buffered_hour: None,
            buffered_events: BTreeMap::new(),
            exhausted: false,
        })
    }

    pub fn archive_root(&self) -> &Path {
        &self.archive_root
    }

    pub fn next_tick(&mut self) -> Result<Option<ReplayTick>> {
        if self.exhausted {
            return Ok(None);
        }

        self.ensure_hour_buffer()?;

        let source_day = self.current_day.day.clone();
        let second_of_day = self.current_second_of_day;
        let events = self
            .buffered_events
            .remove(&self.current_second_of_day)
            .unwrap_or_default();

        let tick = build_tick(
            self.replay_second,
            source_day,
            second_of_day,
            events,
            self.max_events_per_second,
            self.dedupe_window_secs,
            &self.selection_order,
            &mut self.dedupe,
        );

        self.advance_cursor()?;
        self.replay_second += 1;

        Ok(Some(tick))
    }

    fn ensure_hour_buffer(&mut self) -> Result<()> {
        let hour = self.current_second_of_day / 3600;
        if self.buffered_hour == Some(hour) {
            return Ok(());
        }

        let hour_start = hour * 3600;
        let hour_end = (hour_start + 3600).min(86_400);
        self.buffered_events = load_events_by_second(
            &self.archive_root,
            &self.current_day.manifest,
            &self.current_day.minute_offsets,
            hour_start,
            hour_end,
        )?;
        self.buffered_hour = Some(hour);
        Ok(())
    }

    fn advance_cursor(&mut self) -> Result<()> {
        if self.current_second_of_day + 1 < 86_400 {
            self.current_second_of_day += 1;
            return Ok(());
        }

        if let Some(next_day) = self.find_next_complete_day()? {
            self.current_day = LoadedDayPack::load(&self.archive_root, &next_day)?;
            self.current_second_of_day = 0;
            self.buffered_hour = None;
            self.buffered_events.clear();
        } else {
            self.exhausted = true;
        }

        Ok(())
    }

    fn find_next_complete_day(&self) -> Result<Option<String>> {
        let mut candidate_days = fs::read_dir(&self.archive_root)
            .with_context(|| format!("failed to read {}", self.archive_root.display()))?
            .filter_map(|entry| {
                let entry = entry.ok()?;
                let file_type = entry.file_type().ok()?;
                if !file_type.is_dir() {
                    return None;
                }
                let name = entry.file_name().to_string_lossy().to_string();
                if archive::validate_day(&name).is_ok() && name > self.current_day.day {
                    Some(name)
                } else {
                    None
                }
            })
            .collect::<Vec<_>>();
        candidate_days.sort();

        for day in candidate_days {
            let layout = archive::DayPackLayout::new(self.archive_root.clone(), day.clone());
            if !layout.manifest_path.exists() || !layout.minute_offsets_path.exists() {
                continue;
            }
            if let Ok(manifest) = load_manifest(&layout) {
                if manifest.complete {
                    return Ok(Some(day));
                }
            }
        }

        Ok(None)
    }
}

#[derive(Debug, Clone)]
struct LoadedDayPack {
    day: String,
    manifest: DayPackManifest,
    minute_offsets: MinuteOffsetsIndex,
}

impl LoadedDayPack {
    fn load(archive_root: &Path, day: &str) -> Result<Self> {
        let layout = archive::DayPackLayout::new(archive_root.to_path_buf(), day.to_string());
        let manifest = load_manifest(&layout)?;
        let minute_offsets = load_minute_offsets(&layout)?;

        if !manifest.complete {
            bail!("manifest marks day-pack as incomplete");
        }
        if minute_offsets.hours.len() != 24 {
            bail!("minute_offsets.json must declare 24 hours");
        }

        Ok(Self {
            day: day.to_string(),
            manifest,
            minute_offsets,
        })
    }
}

fn build_tick(
    replay_second: u64,
    source_day: String,
    second_of_day: u32,
    mut events: Vec<NormalizedEvent>,
    max_events_per_second: usize,
    dedupe_window_secs: u32,
    selection_order: &[ReplaySelectionKey],
    dedupe: &mut DedupeState,
) -> ReplayTick {
    dedupe.prune(replay_second, dedupe_window_secs);
    events.sort_by(|left, right| compare_events(left, right, selection_order));

    let mut emitted_events = Vec::new();
    let mut deduped_count = 0_u64;
    let mut overflow_count = 0_u64;

    for event in &events {
        if dedupe.contains(&event.event_id) {
            deduped_count += 1;
            continue;
        }
        if emitted_events.len() >= max_events_per_second {
            overflow_count += 1;
            continue;
        }
        dedupe.record(replay_second, &event.event_id);
        emitted_events.push(RuntimeEvent::from(event));
    }

    ReplayTick {
        replay_second,
        source_day,
        second_of_day,
        source_event_count: events.len() as u64,
        emitted_event_count: emitted_events.len() as u64,
        deduped_count,
        overflow_count,
        is_fallback: false,
        events: emitted_events,
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
    order: VecDeque<(u64, String)>,
    emitted_at: HashMap<String, u64>,
}

impl DedupeState {
    fn prune(&mut self, replay_second: u64, dedupe_window_secs: u32) {
        let dedupe_window_secs = dedupe_window_secs as u64;
        while let Some((emitted_second, event_id)) = self.order.front() {
            if replay_second.saturating_sub(*emitted_second) < dedupe_window_secs {
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

    fn record(&mut self, replay_second: u64, event_id: &str) {
        let event_id = event_id.to_string();
        self.emitted_at.insert(event_id.clone(), replay_second);
        self.order.push_back((replay_second, event_id));
    }
}

#[cfg(test)]
mod tests {
    use std::collections::BTreeMap;

    use tempfile::tempdir;

    use super::*;
    use crate::archive;

    #[test]
    fn tick_selection_uses_replay_seconds_for_dedupe_expiry() {
        let mut dedupe = DedupeState::default();

        let first_tick = build_tick(
            0,
            "2026-03-19".to_string(),
            86_399,
            vec![sample_event("dup", "2026-03-19", 86_399, 100)],
            4,
            600,
            &[
                ReplaySelectionKey::WeightDesc,
                ReplaySelectionKey::EventIdAsc,
            ],
            &mut dedupe,
        );
        assert_eq!(first_tick.emitted_event_count, 1);

        let second_tick = build_tick(
            600,
            "2026-03-20".to_string(),
            0,
            vec![sample_event("dup", "2026-03-20", 0, 100)],
            4,
            600,
            &[
                ReplaySelectionKey::WeightDesc,
                ReplaySelectionKey::EventIdAsc,
            ],
            &mut dedupe,
        );

        assert_eq!(second_tick.emitted_event_count, 1);
        assert_eq!(second_tick.deduped_count, 0);
    }

    #[test]
    fn engine_rolls_over_to_next_complete_day_pack() {
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

        let mut engine =
            ReplayEngine::open(&config, first_day, Some(&archive_root), 86_399).expect("engine");
        let last_tick = engine.next_tick().expect("tick").expect("tick exists");
        let next_tick = engine.next_tick().expect("tick").expect("tick exists");

        assert_eq!(last_tick.source_day, first_day);
        assert_eq!(last_tick.second_of_day, 86_399);
        assert_eq!(next_tick.source_day, second_day);
        assert_eq!(next_tick.second_of_day, 0);
    }

    fn sample_event(
        event_id: &str,
        source_day: &str,
        second_of_day: u32,
        weight: u8,
    ) -> NormalizedEvent {
        let mut text_fields = BTreeMap::new();
        text_fields.insert("repo".to_string(), "fixture/repo".to_string());
        NormalizedEvent {
            event_id: event_id.to_string(),
            source_day: source_day.to_string(),
            source_hour: (second_of_day / 3600) as u8,
            created_at_utc: format!("{source_day}T00:00:00Z"),
            second_of_day,
            event_type: "PushEvent".to_string(),
            weight,
            repo_full_name: "fixture/repo".to_string(),
            actor_login: "fixture_actor".to_string(),
            display_hash: "deadbeef".to_string(),
            text_fields,
            audio_class: "PushEvent".to_string(),
            visual_class: "PushEvent".to_string(),
            raw_ref: format!("{source_day}/raw/00.json.gz#line:1"),
        }
    }
}
