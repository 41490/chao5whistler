//! Weaver-owned asset ledger and state machine.
//!
//! This file is deliberately separate from
//! `ops/out/state/musikalisches/stage5_stream_sf2_combination_ledger.json`.
//! The stage5 ledger stays the single source of truth for *which combinations
//! were allocated* (written by `build_stage5_unique_stream.py`); the weaver
//! ledger records *what happened to the asset* for each combination:
//!
//! ```text
//! reserved -> rendering -> published -> consumed -> checkpointed
//!                └-> failed (retryable)
//! ```
//!
//! Every mutation is persisted with a temp-file + rename, so a crash can only
//! lose the latest transition, never leave a half-written state file.

use std::collections::BTreeSet;
use std::path::{Path, PathBuf};
use std::sync::atomic::{AtomicU64, Ordering};

use anyhow::{anyhow, bail, Context, Result};
use chrono::Utc;
use serde::{Deserialize, Serialize};

use super::jsonio;

pub const LEDGER_STAGE: &str = "weaver_asset_ledger_v1";
pub const LEDGER_SCHEMA: &str = "weaver_asset_record_v1";
pub const DEFAULT_RESERVATION_TIMEOUT_SECONDS: i64 = 1800;

static RECORD_COUNTER: AtomicU64 = AtomicU64::new(0);

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum AssetState {
    Reserved,
    Rendering,
    Published,
    Consumed,
    Checkpointed,
    Failed,
}

impl AssetState {
    pub fn as_str(self) -> &'static str {
        match self {
            Self::Reserved => "reserved",
            Self::Rendering => "rendering",
            Self::Published => "published",
            Self::Consumed => "consumed",
            Self::Checkpointed => "checkpointed",
            Self::Failed => "failed",
        }
    }

    /// True once the bridge has taken the asset: such a record is never handed
    /// to the bridge again.
    pub fn is_bridge_settled(self) -> bool {
        matches!(self, Self::Consumed | Self::Checkpointed)
    }

    pub fn is_in_flight(self) -> bool {
        matches!(self, Self::Reserved | Self::Rendering)
    }
}

impl std::fmt::Display for AssetState {
    fn fmt(&self, formatter: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        formatter.write_str(self.as_str())
    }
}

/// The full transition table. Anything else is a programming error, not a
/// runtime condition, and is rejected loudly.
pub fn transition_allowed(from: AssetState, to: AssetState) -> bool {
    matches!(
        (from, to),
        (AssetState::Reserved, AssetState::Rendering)
            | (AssetState::Reserved, AssetState::Failed)
            | (AssetState::Rendering, AssetState::Published)
            | (AssetState::Rendering, AssetState::Failed)
            | (AssetState::Published, AssetState::Consumed)
            | (AssetState::Published, AssetState::Failed)
            | (AssetState::Consumed, AssetState::Checkpointed)
            | (AssetState::Failed, AssetState::Reserved)
    )
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct FailureInfo {
    pub kind: String,
    pub message: String,
    pub at: String,
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct AssetRecord {
    pub record_id: String,
    pub state: AssetState,
    #[serde(default)]
    pub combination_id: Option<String>,
    #[serde(default)]
    pub retryable: bool,
    #[serde(default)]
    pub asset_id: Option<String>,
    #[serde(default)]
    pub asset_dir: Option<String>,
    #[serde(default)]
    pub duration_seconds: Option<f64>,
    #[serde(default)]
    pub attempts: u32,
    #[serde(default)]
    pub bridge_attempts: u32,
    pub reserved_at: String,
    pub updated_at: String,
    #[serde(default)]
    pub published_at: Option<String>,
    #[serde(default)]
    pub consumed_at: Option<String>,
    #[serde(default)]
    pub checkpointed_at: Option<String>,
    #[serde(default)]
    pub recovered_from: Option<String>,
    #[serde(default)]
    pub failure: Option<FailureInfo>,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct FailureSummary {
    pub record_id: String,
    pub combination_id: Option<String>,
    pub state: AssetState,
    pub retryable: bool,
    pub kind: String,
    pub message: String,
}

#[derive(Debug, Clone, Default, PartialEq, Eq, Serialize, Deserialize)]
pub struct RecoveryReport {
    pub recovered_timeouts: usize,
    pub promoted_consumed: usize,
    pub dropped_missing_assets: usize,
}

impl RecoveryReport {
    pub fn total(&self) -> usize {
        self.recovered_timeouts + self.promoted_consumed + self.dropped_missing_assets
    }
}

#[derive(Debug, Clone, Serialize, Deserialize)]
struct LedgerFile {
    stage: String,
    schema: String,
    work_id: String,
    updated_at: String,
    #[serde(default)]
    records: Vec<AssetRecord>,
}

pub struct Ledger {
    path: PathBuf,
    file: LedgerFile,
}

impl Ledger {
    pub fn load_or_init(path: &Path, work_id: &str) -> Result<Self> {
        if path.exists() {
            let file: LedgerFile = jsonio::read_json(path)
                .with_context(|| format!("load weaver ledger {}", path.display()))?;
            if file.stage != LEDGER_STAGE {
                bail!(
                    "unsupported weaver ledger stage {:?} in {}",
                    file.stage,
                    path.display()
                );
            }
            if file.work_id != work_id {
                bail!(
                    "weaver ledger work_id mismatch: requested {work_id}, ledger has {}",
                    file.work_id
                );
            }
            Ok(Self {
                path: path.to_path_buf(),
                file,
            })
        } else {
            Ok(Self {
                path: path.to_path_buf(),
                file: LedgerFile {
                    stage: LEDGER_STAGE.to_string(),
                    schema: LEDGER_SCHEMA.to_string(),
                    work_id: work_id.to_string(),
                    updated_at: jsonio::utc_now(),
                    records: Vec::new(),
                },
            })
        }
    }

    pub fn path(&self) -> &Path {
        &self.path
    }

    pub fn work_id(&self) -> &str {
        &self.file.work_id
    }

    pub fn records(&self) -> &[AssetRecord] {
        &self.file.records
    }

    pub fn record(&self, record_id: &str) -> Option<&AssetRecord> {
        self.file.records.iter().find(|item| item.record_id == record_id)
    }

    /// Published-but-not-yet-consumed assets, oldest first: this *is* the buffer.
    pub fn published(&self) -> Vec<AssetRecord> {
        let mut records = self
            .file
            .records
            .iter()
            .filter(|item| item.state == AssetState::Published)
            .cloned()
            .collect::<Vec<_>>();
        records.sort_by(|left, right| {
            left.published_at
                .cmp(&right.published_at)
                .then_with(|| left.record_id.cmp(&right.record_id))
        });
        records
    }

    pub fn oldest_published(&self) -> Option<AssetRecord> {
        self.published().into_iter().next()
    }

    pub fn depth(&self) -> usize {
        self.file
            .records
            .iter()
            .filter(|item| item.state == AssetState::Published)
            .count()
    }

    pub fn checkpointed_combination_ids(&self) -> BTreeSet<String> {
        self.file
            .records
            .iter()
            .filter(|item| item.state == AssetState::Checkpointed)
            .filter_map(|item| item.combination_id.clone())
            .collect()
    }

    pub fn combination_in_use(&self, combination_id: &str, exclude_record_id: &str) -> bool {
        self.file.records.iter().any(|item| {
            item.record_id != exclude_record_id
                && item.combination_id.as_deref() == Some(combination_id)
                && item.state != AssetState::Failed
        })
    }

    pub fn failure_summaries(&self) -> Vec<FailureSummary> {
        self.file
            .records
            .iter()
            .filter(|item| item.state == AssetState::Failed)
            .map(|item| FailureSummary {
                record_id: item.record_id.clone(),
                combination_id: item.combination_id.clone(),
                state: item.state,
                retryable: item.retryable,
                kind: item
                    .failure
                    .as_ref()
                    .map(|failure| failure.kind.clone())
                    .unwrap_or_else(|| "unknown".to_string()),
                message: item
                    .failure
                    .as_ref()
                    .map(|failure| failure.message.clone())
                    .unwrap_or_default(),
            })
            .collect()
    }

    pub fn save(&mut self) -> Result<()> {
        self.file.updated_at = jsonio::utc_now();
        jsonio::write_json_atomic(&self.path, &self.file)
    }

    /// Startup recovery:
    /// * `reserved` / `rendering` older than the timeout become retryable `failed`;
    /// * `consumed` is promoted to `checkpointed` — the bridge already accepted
    ///   the asset, so re-consuming it would duplicate playback;
    /// * `checkpointed` records are untouched and can never be re-generated.
    pub fn recover_stale(&mut self, timeout_seconds: i64) -> Result<RecoveryReport> {
        let now = Utc::now();
        let mut report = RecoveryReport::default();
        let mut changed = false;

        for record in &mut self.file.records {
            if record.state.is_in_flight() {
                let age = jsonio::age_seconds(&record.updated_at, now).unwrap_or(i64::MAX);
                if age > timeout_seconds {
                    let previous = record.state;
                    record.state = AssetState::Failed;
                    record.retryable = true;
                    record.recovered_from = Some(previous.as_str().to_string());
                    record.updated_at = jsonio::utc_now();
                    record.failure = Some(FailureInfo {
                        kind: "recovered_stale_reservation".to_string(),
                        message: format!(
                            "{previous} record exceeded the {timeout_seconds}s reservation timeout"
                        ),
                        at: record.updated_at.clone(),
                    });
                    report.recovered_timeouts += 1;
                    changed = true;
                }
                continue;
            }
            if record.state == AssetState::Consumed {
                record.state = AssetState::Checkpointed;
                record.checkpointed_at = Some(jsonio::utc_now());
                record.updated_at = jsonio::utc_now();
                report.promoted_consumed += 1;
                changed = true;
            }
        }

        if changed {
            self.save()?;
        }
        Ok(report)
    }

    /// A `published` record whose asset directory vanished cannot be replayed
    /// safely: mark it retryable so the slot is re-rendered with a fresh
    /// combination instead of silently stalling the buffer.
    pub fn drop_missing_assets(&mut self) -> Result<usize> {
        let mut dropped = 0;
        let mut changed = false;
        for record in &mut self.file.records {
            if record.state != AssetState::Published {
                continue;
            }
            let Some(asset_dir) = record.asset_dir.clone() else {
                continue;
            };
            if Path::new(&asset_dir).is_dir() {
                continue;
            }
            record.state = AssetState::Failed;
            record.retryable = true;
            record.recovered_from = Some(AssetState::Published.as_str().to_string());
            record.updated_at = jsonio::utc_now();
            record.failure = Some(FailureInfo {
                kind: "asset_dir_missing".to_string(),
                message: format!("published asset directory is gone: {asset_dir}"),
                at: record.updated_at.clone(),
            });
            dropped += 1;
            changed = true;
        }
        if changed {
            self.save()?;
        }
        Ok(dropped)
    }

    /// Reserve a slot: reuse the oldest retryable `failed` record, else append.
    /// Persisted before any work starts so a crash leaves a visible reservation.
    pub fn begin_reservation(&mut self) -> Result<String> {
        let now = jsonio::utc_now();
        if let Some(record) = self
            .file
            .records
            .iter_mut()
            .find(|item| item.state == AssetState::Failed && item.retryable)
        {
            let record_id = record.record_id.clone();
            record.state = AssetState::Reserved;
            record.combination_id = None;
            record.asset_id = None;
            record.asset_dir = None;
            record.duration_seconds = None;
            record.bridge_attempts = 0;
            record.retryable = false;
            record.failure = None;
            record.attempts += 1;
            record.reserved_at = now.clone();
            record.updated_at = now;
            self.save()?;
            return Ok(record_id);
        }

        let record_id = new_record_id();
        self.file.records.push(AssetRecord {
            record_id: record_id.clone(),
            state: AssetState::Reserved,
            combination_id: None,
            retryable: false,
            asset_id: None,
            asset_dir: None,
            duration_seconds: None,
            attempts: 1,
            bridge_attempts: 0,
            reserved_at: now.clone(),
            updated_at: now,
            published_at: None,
            consumed_at: None,
            checkpointed_at: None,
            recovered_from: None,
            failure: None,
        });
        self.save()?;
        Ok(record_id)
    }

    /// Bind the combination the stage5 tool allocated and enter `rendering`.
    pub fn mark_rendering(&mut self, record_id: &str, combination_id: &str) -> Result<()> {
        if combination_id.trim().is_empty() {
            bail!("refusing to bind an empty combination_id to {record_id}");
        }
        if self.combination_in_use(combination_id, record_id) {
            bail!("combination {combination_id} is already tracked by another weaver record");
        }
        self.transition(record_id, AssetState::Rendering, |record| {
            record.combination_id = Some(combination_id.to_string());
        })
    }

    pub fn mark_published(
        &mut self,
        record_id: &str,
        asset_id: &str,
        asset_dir: &Path,
        duration_seconds: f64,
    ) -> Result<()> {
        let now = jsonio::utc_now();
        let asset_dir_text = asset_dir.display().to_string();
        self.transition(record_id, AssetState::Published, |record| {
            record.asset_id = Some(asset_id.to_string());
            record.asset_dir = Some(asset_dir_text);
            record.duration_seconds = Some(duration_seconds);
            record.published_at = Some(now);
        })
    }

    pub fn mark_consumed(&mut self, record_id: &str) -> Result<()> {
        let now = jsonio::utc_now();
        self.transition(record_id, AssetState::Consumed, |record| {
            record.consumed_at = Some(now);
            record.retryable = false;
        })
    }

    pub fn mark_checkpointed(&mut self, record_id: &str) -> Result<()> {
        let now = jsonio::utc_now();
        self.transition(record_id, AssetState::Checkpointed, |record| {
            record.checkpointed_at = Some(now);
        })
    }

    pub fn mark_failed(
        &mut self,
        record_id: &str,
        kind: &str,
        message: &str,
        retryable: bool,
    ) -> Result<()> {
        self.transition(record_id, AssetState::Failed, |record| {
            record.retryable = retryable;
            record.failure = Some(FailureInfo {
                kind: kind.to_string(),
                message: message.to_string(),
                at: jsonio::utc_now(),
            });
        })
    }

    pub fn record_bridge_attempt(&mut self, record_id: &str) -> Result<u32> {
        let now = jsonio::utc_now();
        let record = self
            .file
            .records
            .iter_mut()
            .find(|item| item.record_id == record_id)
            .ok_or_else(|| anyhow!("unknown weaver record {record_id}"))?;
        record.bridge_attempts += 1;
        record.updated_at = now;
        let attempts = record.bridge_attempts;
        self.save()?;
        Ok(attempts)
    }

    fn transition<F>(&mut self, record_id: &str, to: AssetState, mutate: F) -> Result<()>
    where
        F: FnOnce(&mut AssetRecord),
    {
        let record = self
            .file
            .records
            .iter_mut()
            .find(|item| item.record_id == record_id)
            .ok_or_else(|| anyhow!("unknown weaver record {record_id}"))?;
        if !transition_allowed(record.state, to) {
            bail!(
                "illegal weaver ledger transition for {record_id}: {} -> {}",
                record.state,
                to
            );
        }
        record.state = to;
        record.updated_at = jsonio::utc_now();
        mutate(record);
        self.save()
    }
}

fn new_record_id() -> String {
    let counter = RECORD_COUNTER.fetch_add(1, Ordering::SeqCst);
    format!(
        "rec-{}-{}-{counter}",
        Utc::now().timestamp_millis(),
        std::process::id()
    )
}

#[cfg(test)]
mod tests {
    use super::*;

    fn scratch(tag: &str) -> PathBuf {
        let dir = std::env::temp_dir().join(format!(
            "weaver-ledger-{tag}-{}-{}",
            std::process::id(),
            RECORD_COUNTER.fetch_add(1, Ordering::SeqCst)
        ));
        let _ = std::fs::remove_dir_all(&dir);
        std::fs::create_dir_all(&dir).unwrap();
        dir
    }

    fn ledger_in(dir: &Path) -> Ledger {
        Ledger::load_or_init(&dir.join("ledger.json"), "mozart_dicegame_print_1790s").unwrap()
    }

    fn publish_record(ledger: &mut Ledger, dir: &Path, combination_id: &str) -> (String, PathBuf) {
        let record_id = ledger.begin_reservation().unwrap();
        ledger.mark_rendering(&record_id, combination_id).unwrap();
        let asset_dir = dir.join("buffer").join(combination_id.replace(',', "-"));
        std::fs::create_dir_all(&asset_dir).unwrap();
        ledger
            .mark_published(&record_id, combination_id, &asset_dir, 12.5)
            .unwrap();
        (record_id, asset_dir)
    }

    #[test]
    fn transition_table_is_closed() {
        assert!(transition_allowed(AssetState::Reserved, AssetState::Rendering));
        assert!(transition_allowed(AssetState::Rendering, AssetState::Published));
        assert!(transition_allowed(AssetState::Published, AssetState::Consumed));
        assert!(transition_allowed(AssetState::Consumed, AssetState::Checkpointed));
        assert!(transition_allowed(AssetState::Failed, AssetState::Reserved));
        assert!(!transition_allowed(AssetState::Checkpointed, AssetState::Consumed));
        assert!(!transition_allowed(AssetState::Reserved, AssetState::Published));
        assert!(!transition_allowed(AssetState::Consumed, AssetState::Failed));
    }

    #[test]
    fn illegal_transition_is_rejected() {
        let dir = scratch("illegal");
        let mut ledger = ledger_in(&dir);
        let record_id = ledger.begin_reservation().unwrap();
        let error = ledger.mark_published(&record_id, "x", &dir, 1.0).unwrap_err();
        assert!(error.to_string().contains("illegal weaver ledger transition"));
        std::fs::remove_dir_all(&dir).unwrap();
    }

    #[test]
    fn state_survives_reload_and_is_never_half_written() {
        let dir = scratch("reload");
        let mut ledger = ledger_in(&dir);
        let (record_id, asset_dir) = publish_record(&mut ledger, &dir, "1,2,3");
        ledger.mark_consumed(&record_id).unwrap();
        ledger.mark_checkpointed(&record_id).unwrap();
        drop(ledger);

        let reloaded = ledger_in(&dir);
        let record = reloaded.record(&record_id).unwrap();
        assert_eq!(record.state, AssetState::Checkpointed);
        assert_eq!(record.combination_id.as_deref(), Some("1,2,3"));
        assert_eq!(record.asset_dir.as_deref(), Some(asset_dir.display().to_string().as_str()));
        // no temp files left behind
        let leftovers = std::fs::read_dir(&dir)
            .unwrap()
            .filter_map(|entry| entry.ok())
            .filter(|entry| entry.file_name().to_string_lossy().contains(".tmp-"))
            .count();
        assert_eq!(leftovers, 0);
        std::fs::remove_dir_all(&dir).unwrap();
    }

    #[test]
    fn stale_reservations_are_recovered_as_retryable_failures() {
        let dir = scratch("stale");
        let mut ledger = ledger_in(&dir);
        let record_id = ledger.begin_reservation().unwrap();
        ledger.mark_rendering(&record_id, "4,5,6").unwrap();
        // backdate the record beyond the timeout
        ledger.file.records[0].updated_at = "2000-01-01T00:00:00Z".to_string();
        ledger.save().unwrap();

        let report = ledger.recover_stale(1800).unwrap();
        assert_eq!(report.recovered_timeouts, 1);
        let record = ledger.record(&record_id).unwrap();
        assert_eq!(record.state, AssetState::Failed);
        assert!(record.retryable);
        assert_eq!(record.recovered_from.as_deref(), Some("rendering"));
        assert_eq!(
            record.failure.as_ref().unwrap().kind,
            "recovered_stale_reservation"
        );

        // the recovered record is what the next reservation reuses
        let reused = ledger.begin_reservation().unwrap();
        assert_eq!(reused, record_id);
        assert_eq!(ledger.record(&record_id).unwrap().attempts, 2);
        assert_eq!(ledger.record(&record_id).unwrap().state, AssetState::Reserved);
        std::fs::remove_dir_all(&dir).unwrap();
    }

    #[test]
    fn fresh_reservations_are_not_recovered() {
        let dir = scratch("fresh");
        let mut ledger = ledger_in(&dir);
        let record_id = ledger.begin_reservation().unwrap();
        ledger.mark_rendering(&record_id, "7,8,9").unwrap();
        let report = ledger.recover_stale(1800).unwrap();
        assert_eq!(report.total(), 0);
        assert_eq!(ledger.record(&record_id).unwrap().state, AssetState::Rendering);
        std::fs::remove_dir_all(&dir).unwrap();
    }

    #[test]
    fn consumed_records_are_checkpointed_on_restart_not_replayed() {
        let dir = scratch("consumed");
        let mut ledger = ledger_in(&dir);
        let (record_id, _asset_dir) = publish_record(&mut ledger, &dir, "1,1,1");
        ledger.mark_consumed(&record_id).unwrap();
        drop(ledger);

        let mut reloaded = ledger_in(&dir);
        let report = reloaded.recover_stale(1800).unwrap();
        assert_eq!(report.promoted_consumed, 1);
        assert_eq!(
            reloaded.record(&record_id).unwrap().state,
            AssetState::Checkpointed
        );
        assert!(reloaded.published().is_empty());
        assert!(reloaded
            .checkpointed_combination_ids()
            .contains("1,1,1"));
        std::fs::remove_dir_all(&dir).unwrap();
    }

    #[test]
    fn published_assets_with_missing_dirs_become_retryable() {
        let dir = scratch("missing");
        let mut ledger = ledger_in(&dir);
        let (record_id, asset_dir) = publish_record(&mut ledger, &dir, "2,2,2");
        std::fs::remove_dir_all(&asset_dir).unwrap();
        let dropped = ledger.drop_missing_assets().unwrap();
        assert_eq!(dropped, 1);
        let record = ledger.record(&record_id).unwrap();
        assert_eq!(record.state, AssetState::Failed);
        assert_eq!(record.failure.as_ref().unwrap().kind, "asset_dir_missing");
        std::fs::remove_dir_all(&dir).unwrap();
    }

    #[test]
    fn duplicate_combination_ids_are_rejected() {
        let dir = scratch("dupe");
        let mut ledger = ledger_in(&dir);
        let (_first, _asset_dir) = publish_record(&mut ledger, &dir, "3,3,3");
        let second = ledger.begin_reservation().unwrap();
        let error = ledger.mark_rendering(&second, "3,3,3").unwrap_err();
        assert!(error.to_string().contains("already tracked"));
        std::fs::remove_dir_all(&dir).unwrap();
    }

    #[test]
    fn buffer_depth_counts_only_published_records() {
        let dir = scratch("depth");
        let mut ledger = ledger_in(&dir);
        let (first, _) = publish_record(&mut ledger, &dir, "1,0,0");
        let (second, _) = publish_record(&mut ledger, &dir, "2,0,0");
        assert_eq!(ledger.depth(), 2);
        assert_eq!(ledger.oldest_published().unwrap().record_id, first);
        ledger.mark_consumed(&first).unwrap();
        ledger.mark_checkpointed(&first).unwrap();
        assert_eq!(ledger.depth(), 1);
        assert_eq!(ledger.oldest_published().unwrap().record_id, second);
        std::fs::remove_dir_all(&dir).unwrap();
    }

    #[test]
    fn bridge_attempts_are_counted_without_losing_the_asset() {
        let dir = scratch("bridge");
        let mut ledger = ledger_in(&dir);
        let (record_id, _) = publish_record(&mut ledger, &dir, "9,9,9");
        assert_eq!(ledger.record_bridge_attempt(&record_id).unwrap(), 1);
        assert_eq!(ledger.record_bridge_attempt(&record_id).unwrap(), 2);
        let record = ledger.record(&record_id).unwrap();
        assert_eq!(record.state, AssetState::Published);
        assert_eq!(record.bridge_attempts, 2);
        std::fs::remove_dir_all(&dir).unwrap();
    }
}
