use std::cmp::Ordering;
use std::collections::{BTreeMap, HashMap, VecDeque};
use std::fs;
use std::path::{Path, PathBuf};
use std::time::SystemTime;

use anyhow::{bail, Context, Result};
use chrono::{Duration, NaiveDate};
use serde::Serialize;
use sha2::{Digest, Sha256};

use crate::archive;
use crate::archive::index::MinuteOffsetsIndex;
use crate::archive::manifest::DayPackManifest;
use crate::config::schema::{Config, DensitySource, ReplaySelectionKey, RuntimeMode};
use crate::model::normalized_event::NormalizedEvent;
use crate::model::runtime_event::{RuntimeEvent, RuntimeEventSource};

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
    source: ReplaySourceState,
    dedupe: DedupeState,
}

enum ReplaySourceState {
    Archive(ArchiveReplayState),
    Fallback(FallbackReplayState),
}

struct ArchiveReplayState {
    current_second_of_day: u32,
    current_day: LoadedDayPack,
    buffered_minute: Option<u32>,
    buffered_events: BTreeMap<u32, Vec<NormalizedEvent>>,
    exhausted: bool,
}

struct FallbackReplayState {
    current_day: NaiveDate,
    current_second_of_day: u32,
    density_profile: FallbackDensityProfile,
    density_scale: f64,
    seed: u64,
    repo_prefix: String,
    actor_prefix: String,
    hash_len: usize,
    event_specs: Vec<FallbackEventSpec>,
}

struct FallbackDensityProfile {
    minute_counts: Vec<u64>,
    peak_count: u64,
}

struct FallbackEventSpec {
    event_type: String,
    weight: u8,
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
        let source = open_replay_source(config, &archive_root, start_day, start_second)?;

        Ok(Self {
            archive_root,
            max_events_per_second: config.replay.max_events_per_second as usize,
            dedupe_window_secs: config.replay.dedupe_window_secs,
            selection_order: config.replay.selection_order.clone(),
            replay_second: 0,
            source,
            dedupe: DedupeState::default(),
        })
    }

    pub fn archive_root(&self) -> &Path {
        &self.archive_root
    }

    pub fn next_tick(&mut self) -> Result<Option<ReplayTick>> {
        let tick = match &mut self.source {
            ReplaySourceState::Archive(state) => {
                if state.exhausted {
                    return Ok(None);
                }

                ensure_archive_minute_buffer(&self.archive_root, state)?;

                let source_day = state.current_day.day.clone();
                let second_of_day = state.current_second_of_day;
                let events = state
                    .buffered_events
                    .remove(&state.current_second_of_day)
                    .unwrap_or_default();

                let tick = build_tick(
                    self.replay_second,
                    source_day,
                    second_of_day,
                    events,
                    RuntimeEventSource::ArchiveReplay,
                    self.max_events_per_second,
                    self.dedupe_window_secs,
                    &self.selection_order,
                    &mut self.dedupe,
                );

                advance_archive_cursor(&self.archive_root, state)?;
                tick
            }
            ReplaySourceState::Fallback(state) => {
                let tick = state.build_tick(
                    self.replay_second,
                    self.max_events_per_second,
                    self.dedupe_window_secs,
                    &self.selection_order,
                    &mut self.dedupe,
                );
                state.advance_cursor();
                tick
            }
        };

        self.replay_second += 1;
        Ok(Some(tick))
    }
}

fn open_replay_source(
    config: &Config,
    archive_root: &Path,
    start_day: &str,
    start_second: u32,
) -> Result<ReplaySourceState> {
    if config.runtime.mode == RuntimeMode::RandomFallback {
        return Ok(ReplaySourceState::Fallback(FallbackReplayState::open(
            config,
            archive_root,
            start_day,
            start_second,
        )?));
    }

    let layout = archive::DayPackLayout::new(archive_root.to_path_buf(), start_day.to_string());
    let archive_missing = !layout.manifest_path.exists() || !layout.minute_offsets_path.exists();
    if archive_missing && config.fallback.enabled {
        return Ok(ReplaySourceState::Fallback(FallbackReplayState::open(
            config,
            archive_root,
            start_day,
            start_second,
        )?));
    }

    let current_day = LoadedDayPack::load(archive_root, start_day)?;
    Ok(ReplaySourceState::Archive(ArchiveReplayState {
        current_second_of_day: start_second,
        current_day,
        buffered_minute: None,
        buffered_events: BTreeMap::new(),
        exhausted: false,
    }))
}

fn ensure_archive_minute_buffer(archive_root: &Path, state: &mut ArchiveReplayState) -> Result<()> {
    let minute = state.current_second_of_day / 60;
    if state.buffered_minute == Some(minute) {
        return Ok(());
    }

    let minute_start = minute * 60;
    let minute_end = (minute_start + 60).min(86_400);
    state.buffered_events = load_events_by_second(
        archive_root,
        &state.current_day.manifest,
        &state.current_day.minute_offsets,
        minute_start,
        minute_end,
    )?;
    state.buffered_minute = Some(minute);
    Ok(())
}

fn advance_archive_cursor(archive_root: &Path, state: &mut ArchiveReplayState) -> Result<()> {
    if state.current_second_of_day + 1 < 86_400 {
        state.current_second_of_day += 1;
        return Ok(());
    }

    if let Some(next_day) = find_next_complete_day(archive_root, &state.current_day.day)? {
        state.current_day = LoadedDayPack::load(archive_root, &next_day)?;
        state.current_second_of_day = 0;
        state.buffered_minute = None;
        state.buffered_events.clear();
    } else {
        state.exhausted = true;
    }

    Ok(())
}

fn find_next_complete_day(archive_root: &Path, current_day: &str) -> Result<Option<String>> {
    let mut candidate_days = fs::read_dir(archive_root)
        .with_context(|| format!("failed to read {}", archive_root.display()))?
        .filter_map(|entry| {
            let entry = entry.ok()?;
            let file_type = entry.file_type().ok()?;
            if !file_type.is_dir() {
                return None;
            }
            let name = entry.file_name().to_string_lossy().to_string();
            if archive::validate_day(&name).is_ok() && name.as_str() > current_day {
                Some(name)
            } else {
                None
            }
        })
        .collect::<Vec<_>>();
    candidate_days.sort();

    for day in candidate_days {
        let layout = archive::DayPackLayout::new(archive_root.to_path_buf(), day.clone());
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
    source: RuntimeEventSource,
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
        emitted_events.push(RuntimeEvent::from_normalized_with_source(event, source));
    }

    ReplayTick {
        replay_second,
        source_day,
        second_of_day,
        source_event_count: events.len() as u64,
        emitted_event_count: emitted_events.len() as u64,
        deduped_count,
        overflow_count,
        is_fallback: source == RuntimeEventSource::FallbackSynthetic,
        events: emitted_events,
    }
}

impl FallbackReplayState {
    fn open(
        config: &Config,
        archive_root: &Path,
        start_day: &str,
        start_second: u32,
    ) -> Result<Self> {
        let current_day = NaiveDate::parse_from_str(start_day, "%Y-%m-%d")
            .with_context(|| format!("invalid fallback start day: {start_day}"))?;
        let density_profile = match config.fallback.density_source {
            DensitySource::HistoryIfAvailable => load_history_density_profile(archive_root)?
                .unwrap_or_else(builtin_density_profile),
            DensitySource::BuiltinOnly => builtin_density_profile(),
        };
        let seed = if config.fallback.seed == 0 {
            hashed_u64(start_day, "fallback-randomized-seed")
                ^ hashed_u64(&format!("{:?}", SystemTime::now()), "startup")
        } else {
            config.fallback.seed
        };
        let event_specs = config
            .events
            .primary_types
            .iter()
            .map(|event_type| FallbackEventSpec {
                event_type: event_type.as_str().to_string(),
                weight: *config.events.weights.get(event_type).unwrap_or(&1),
            })
            .collect::<Vec<_>>();

        Ok(Self {
            current_day,
            current_second_of_day: start_second,
            density_profile,
            density_scale: config.fallback.density_scale,
            seed,
            repo_prefix: config.fallback.synthetic_repo_prefix.clone(),
            actor_prefix: config.fallback.synthetic_actor_prefix.clone(),
            hash_len: config.events.hash_len_default as usize,
            event_specs,
        })
    }

    fn build_tick(
        &self,
        replay_second: u64,
        max_events_per_second: usize,
        dedupe_window_secs: u32,
        selection_order: &[ReplaySelectionKey],
        dedupe: &mut DedupeState,
    ) -> ReplayTick {
        let source_day = self.current_day.format("%F").to_string();
        let second_of_day = self.current_second_of_day;
        let minute_index = (second_of_day / 60) as usize;
        let minute_count = self
            .density_profile
            .minute_counts
            .get(minute_index)
            .copied()
            .unwrap_or(0);
        let peak_count = self.density_profile.peak_count.max(1);
        let density_ratio = minute_count as f64 / peak_count as f64;
        let expected_events =
            (density_ratio * self.density_scale * max_events_per_second as f64)
                .clamp(0.0, max_events_per_second as f64);
        let whole_events = expected_events.floor() as usize;
        let fractional_event = expected_events - whole_events as f64;
        let fraction_ticket = self.hash_unit(replay_second, usize::MAX, "event-fraction");
        let event_count = (whole_events
            + usize::from(
                fraction_ticket < fractional_event && whole_events < max_events_per_second,
            ))
        .min(max_events_per_second);

        let mut events = Vec::with_capacity(event_count);
        for slot in 0..event_count {
            events.push(self.synthetic_event(replay_second, slot));
        }

        build_tick(
            replay_second,
            source_day,
            second_of_day,
            events,
            RuntimeEventSource::FallbackSynthetic,
            max_events_per_second,
            dedupe_window_secs,
            selection_order,
            dedupe,
        )
    }

    fn advance_cursor(&mut self) {
        if self.current_second_of_day + 1 < 86_400 {
            self.current_second_of_day += 1;
            return;
        }

        self.current_second_of_day = 0;
        self.current_day = self
            .current_day
            .checked_add_signed(Duration::days(1))
            .expect("fallback day rollover");
    }

    fn synthetic_event(&self, replay_second: u64, slot: usize) -> NormalizedEvent {
        let second_of_day = self.current_second_of_day;
        let source_day = self.current_day.format("%F").to_string();
        let event_spec = self.select_event_spec(replay_second, slot);
        let hour = (second_of_day / 3600) as u8;
        let minute = (second_of_day % 3600) / 60;
        let second = second_of_day % 60;
        let created_at_utc = format!("{source_day}T{hour:02}:{minute:02}:{second:02}Z");
        let display_hash = self.display_hash(replay_second, slot);
        let repo_full_name = self.synthetic_repo_name(replay_second, slot);
        let actor_login = self.synthetic_actor_login(replay_second, slot);
        let event_id = format!(
            "fallback-{}-{second_of_day:05}-{slot:02}-{}",
            source_day.replace('-', ""),
            display_hash
        );
        let text_fields = build_text_fields(
            &repo_full_name,
            &actor_login,
            &event_spec.event_type,
            &event_id,
            &display_hash,
            event_spec.weight,
            second_of_day,
        );

        NormalizedEvent {
            event_id,
            source_day: source_day.clone(),
            source_hour: hour,
            created_at_utc,
            second_of_day,
            event_type: event_spec.event_type.clone(),
            weight: event_spec.weight,
            repo_full_name,
            actor_login,
            display_hash,
            text_fields,
            audio_class: event_spec.event_type.clone(),
            visual_class: event_spec.event_type.clone(),
            raw_ref: format!("fallback://{source_day}/{second_of_day:05}/{slot:02}"),
        }
    }

    fn select_event_spec(&self, replay_second: u64, slot: usize) -> &FallbackEventSpec {
        let total_weight = self
            .event_specs
            .iter()
            .map(|spec| spec.weight as u64)
            .sum::<u64>()
            .max(1);
        let ticket = self.hash_u64(replay_second, slot, "event-type-ticket") % total_weight;
        let mut cursor = 0_u64;
        for spec in &self.event_specs {
            cursor += spec.weight as u64;
            if ticket < cursor {
                return spec;
            }
        }
        self.event_specs.last().expect("fallback event specs")
    }

    fn synthetic_repo_name(&self, replay_second: u64, slot: usize) -> String {
        let owner_suffix = self.hash_u64(replay_second, slot, "repo-owner") % 64;
        let repo_suffix = self.hash_u64(replay_second, slot, "repo-name") % 512;
        if let Some((owner_prefix, repo_prefix)) = self.repo_prefix.split_once('/') {
            format!("{owner_prefix}-{owner_suffix:02}/{repo_prefix}-{repo_suffix:03}")
        } else {
            format!("{}-{owner_suffix:02}/repo-{repo_suffix:03}", self.repo_prefix)
        }
    }

    fn synthetic_actor_login(&self, replay_second: u64, slot: usize) -> String {
        format!(
            "{}-{:03}",
            self.actor_prefix,
            self.hash_u64(replay_second, slot, "actor-login") % 512
        )
    }

    fn display_hash(&self, replay_second: u64, slot: usize) -> String {
        let digest = hex::encode(Sha256::digest(
            self.synthetic_key(replay_second, slot, "display-hash")
                .as_bytes(),
        ));
        let width = self.hash_len.max(4).min(digest.len());
        digest[..width].to_string()
    }

    fn hash_u64(&self, replay_second: u64, slot: usize, salt: &str) -> u64 {
        hashed_u64(&self.synthetic_key(replay_second, slot, salt), salt)
    }

    fn hash_unit(&self, replay_second: u64, slot: usize, salt: &str) -> f64 {
        self.hash_u64(replay_second, slot, salt) as f64 / u64::MAX as f64
    }

    fn synthetic_key(&self, replay_second: u64, slot: usize, salt: &str) -> String {
        format!(
            "{}:{:05}:{replay_second}:{slot}:{salt}:{}",
            self.current_day.format("%F"),
            self.current_second_of_day,
            self.seed
        )
    }
}

fn build_text_fields(
    repo_full_name: &str,
    actor_login: &str,
    event_type: &str,
    event_id: &str,
    display_hash: &str,
    weight: u8,
    second_of_day: u32,
) -> BTreeMap<String, String> {
    let (repo_owner, repo_name) = repo_full_name
        .split_once('/')
        .map(|(owner, name)| (owner.to_string(), name.to_string()))
        .unwrap_or_else(|| (repo_full_name.to_string(), String::new()));
    let hour = second_of_day / 3600;
    let minute = (second_of_day % 3600) / 60;
    let second = second_of_day % 60;

    let mut fields = BTreeMap::new();
    fields.insert("repo".to_string(), repo_full_name.to_string());
    fields.insert("repo_owner".to_string(), repo_owner);
    fields.insert("repo_name".to_string(), repo_name);
    fields.insert("type".to_string(), event_type.to_string());
    fields.insert("actor".to_string(), actor_login.to_string());
    fields.insert("hash".to_string(), display_hash.to_string());
    fields.insert("id".to_string(), event_id.to_string());
    fields.insert("weight".to_string(), weight.to_string());
    fields.insert("hour".to_string(), format!("{hour:02}"));
    fields.insert("minute".to_string(), format!("{minute:02}"));
    fields.insert("second".to_string(), format!("{second:02}"));
    fields
}

fn load_history_density_profile(archive_root: &Path) -> Result<Option<FallbackDensityProfile>> {
    if !archive_root.exists() {
        return Ok(None);
    }

    let mut sums = vec![0_u64; 1_440];
    let mut sample_count = 0_u64;
    for entry in fs::read_dir(archive_root)
        .with_context(|| format!("failed to read {}", archive_root.display()))?
    {
        let entry = entry?;
        if !entry.file_type()?.is_dir() {
            continue;
        }
        let day = entry.file_name().to_string_lossy().to_string();
        if archive::validate_day(&day).is_err() {
            continue;
        }

        let loaded = match LoadedDayPack::load(archive_root, &day) {
            Ok(loaded) => loaded,
            Err(_) => continue,
        };
        for hour in &loaded.minute_offsets.hours {
            for minute in &hour.minute_offsets {
                let minute_index = hour.hour as usize * 60 + minute.minute as usize;
                if let Some(slot) = sums.get_mut(minute_index) {
                    *slot += minute.event_count;
                }
            }
        }
        sample_count += 1;
    }

    if sample_count == 0 {
        return Ok(None);
    }

    let minute_counts = sums
        .into_iter()
        .map(|count| count / sample_count)
        .collect::<Vec<_>>();
    let peak_count = minute_counts.iter().copied().max().unwrap_or(1).max(1);
    Ok(Some(FallbackDensityProfile {
        minute_counts,
        peak_count,
    }))
}

fn builtin_density_profile() -> FallbackDensityProfile {
    let minute_counts = (0..1_440)
        .map(|minute| {
            let phase = minute as f64 / 1_440.0;
            let diurnal = ((phase * std::f64::consts::TAU) - std::f64::consts::FRAC_PI_2).sin();
            let burst = (phase * std::f64::consts::TAU * 3.0).sin();
            (8.0 + (diurnal + 1.0) * 18.0 + (burst + 1.0) * 6.0).round() as u64
        })
        .collect::<Vec<_>>();
    let peak_count = minute_counts.iter().copied().max().unwrap_or(1).max(1);
    FallbackDensityProfile {
        minute_counts,
        peak_count,
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

fn hashed_u64(value: &str, salt: &str) -> u64 {
    let digest = Sha256::digest(format!("{value}:{salt}").as_bytes());
    u64::from_be_bytes(digest[..8].try_into().expect("8 bytes"))
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
            RuntimeEventSource::ArchiveReplay,
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
            RuntimeEventSource::ArchiveReplay,
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

    #[test]
    fn engine_refreshes_buffer_when_crossing_minute_boundary() {
        let temp = tempdir().expect("tempdir");
        let archive_root = temp.path().join("archive");
        let day = "2026-03-19";

        archive::seed_fixture_raw(&archive_root, day, true).expect("seed fixture");

        let mut config = Config::default();
        config.archive.root_dir = archive_root.display().to_string();
        archive::prepare_day_pack(&config, day, Some(&archive_root), true, true).expect("prepare");

        let mut engine = ReplayEngine::open(&config, day, Some(&archive_root), 779).expect("open");

        let ReplaySourceState::Archive(state) = &engine.source else {
            panic!("expected archive replay source");
        };
        assert_eq!(state.buffered_minute, None);

        let tick_before_boundary = engine.next_tick().expect("tick").expect("tick exists");
        assert_eq!(tick_before_boundary.second_of_day, 779);

        let ReplaySourceState::Archive(state) = &engine.source else {
            panic!("expected archive replay source");
        };
        assert_eq!(state.buffered_minute, Some(12));

        let tick_after_boundary = engine.next_tick().expect("tick").expect("tick exists");
        assert_eq!(tick_after_boundary.second_of_day, 780);

        let ReplaySourceState::Archive(state) = &engine.source else {
            panic!("expected archive replay source");
        };
        assert_eq!(state.buffered_minute, Some(13));
    }

    #[test]
    fn engine_uses_random_fallback_without_archive() {
        let temp = tempdir().expect("tempdir");
        let archive_root = temp.path().join("archive");
        let mut config = Config::default();
        config.archive.root_dir = archive_root.display().to_string();
        config.runtime.mode = RuntimeMode::RandomFallback;
        config.fallback.seed = 7;
        config.fallback.density_scale = 1.0;

        let mut engine =
            ReplayEngine::open(&config, "2026-03-19", Some(&archive_root), 43_200).expect("open");
        let tick = engine.next_tick().expect("tick").expect("tick exists");

        assert!(tick.is_fallback);
        assert!(tick.emitted_event_count > 0);
        assert!(tick.events.iter().all(|event| {
            event.source == RuntimeEventSource::FallbackSynthetic
                && event.raw_ref.starts_with("fallback://")
        }));
    }

    #[test]
    fn engine_falls_back_when_archive_pack_is_missing() {
        let temp = tempdir().expect("tempdir");
        let archive_root = temp.path().join("archive");
        let mut config = Config::default();
        config.archive.root_dir = archive_root.display().to_string();
        config.fallback.seed = 11;
        config.fallback.density_scale = 1.0;

        let mut engine =
            ReplayEngine::open(&config, "2026-03-19", Some(&archive_root), 43_200).expect("open");
        let tick = engine.next_tick().expect("tick").expect("tick exists");

        assert!(tick.is_fallback);
        assert!(tick.emitted_event_count > 0);
        assert_eq!(tick.source_day, "2026-03-19");
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
