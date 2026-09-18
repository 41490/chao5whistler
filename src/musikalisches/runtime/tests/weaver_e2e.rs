//! End-to-end acceptance tests for `musikalisches-weaver` (issue #62).
//!
//! These drive the real binary through the real adapter/publish/ledger paths,
//! with the stage5/stage6 tools and the bridge replaced by the repo's local
//! fakes. No YouTube key, no RTMPS URL, no network.
//!
//! The three assertions the issue demands:
//! 1. at least three *different* `combination_id`s are consumed in a row, and
//!    `once` mode still behaves as a single pass;
//! 2. after a restart, checkpointed combinations are not confirmed twice and
//!    published-but-unconsumed assets are not lost;
//! 3. the throughput report exists and carries generation throughput, playback
//!    throughput and buffer depth min/max.

use std::collections::BTreeSet;
use std::fs;
use std::path::{Path, PathBuf};
use std::process::Command;

use serde::Deserialize;
use serde_json::{json, Value};

const MANIFEST_DIR: &str = env!("CARGO_MANIFEST_DIR");
/// Index 0 of the fake allocator: sixteen `2`s.
const FIRST_FAKE_COMBINATION_ID: &str = "2,2,2,2,2,2,2,2,2,2,2,2,2,2,2,2";

fn weaver_bin() -> &'static str {
    env!("CARGO_BIN_EXE_musikalisches-weaver")
}

fn tools_dir() -> PathBuf {
    Path::new(MANIFEST_DIR).join("src/musikalisches/tools")
}

fn scratch(name: &str) -> PathBuf {
    let root = std::env::temp_dir().join(format!("weaver-e2e-{name}-{}", std::process::id()));
    let _ = fs::remove_dir_all(&root);
    fs::create_dir_all(&root).expect("create scratch dir");
    // Hermetic stage5 soundfont: the repo bundles none (`ops/assets/**` is
    // gitignored), and the fakes never read the file.
    fs::write(root.join("dummy.sf2"), b"sf2").expect("write soundfont stub");
    root
}

#[derive(Debug, Clone)]
struct RunResult {
    code: i32,
    stdout: String,
    stderr: String,
}

impl RunResult {
    fn context(&self) -> String {
        format!(
            "exit={} stdout={} stderr={}",
            self.code, self.stdout, self.stderr
        )
    }
}

fn run_weaver(args: &[String]) -> RunResult {
    let output = Command::new(weaver_bin())
        .args(args)
        .current_dir(MANIFEST_DIR)
        .output()
        .expect("spawn musikalisches-weaver");
    RunResult {
        code: output.status.code().unwrap_or(-1),
        stdout: String::from_utf8_lossy(&output.stdout).to_string(),
        stderr: String::from_utf8_lossy(&output.stderr).to_string(),
    }
}

/// Adapter JSON pointing the pipeline at the local fakes.
fn write_adapter(
    root: &Path,
    name: &str,
    duration_seconds: f64,
    stage6_sleep_seconds: f64,
    play_seconds: f64,
    bridge_fail_on: &[&str],
) -> PathBuf {
    let tools = tools_dir();
    let render = tools.join("fake_weaver_render.py").display().to_string();
    let bridge = tools.join("fake_weaver_bridge.py").display().to_string();
    let mut stage6_args = vec![
        json!(render),
        json!("--stage"),
        json!("stage6"),
        json!("--output-dir"),
        json!("{video_dir}"),
        json!("--duration-seconds"),
        json!(duration_seconds.to_string()),
    ];
    if stage6_sleep_seconds > 0.0 {
        stage6_args.push(json!("--sleep-seconds"));
        stage6_args.push(json!(stage6_sleep_seconds.to_string()));
    }
    let mut bridge_args = vec![
        json!(bridge),
        json!("--asset-dir"),
        json!("{asset_dir}"),
        json!("--journal"),
        json!("{bridge_journal}"),
        json!("--play-seconds"),
        json!(play_seconds.to_string()),
    ];
    for combination_id in bridge_fail_on {
        bridge_args.push(json!("--fail-on"));
        bridge_args.push(json!(*combination_id));
        bridge_args.push(json!("--fail-times"));
        bridge_args.push(json!("1000"));
    }

    let adapter = json!({
        "adapter_id": "weaver_e2e_fake",
        "steps": {
            "stage5_audio": {
                "program": "python3",
                "args": [
                    render,
                    "--stage", "stage5",
                    "--output-dir", "{audio_dir}",
                    "--combination-ledger", "{stage5_ledger}",
                    "--duration-seconds", duration_seconds.to_string()
                ]
            },
            "stage6_video": {"program": "python3", "args": stage6_args},
            "bridge_run": {"program": "python3", "args": bridge_args}
        }
    });
    let path = root.join(format!("adapter-{name}.json"));
    fs::write(&path, format!("{adapter}\n")).expect("write adapter config");
    path
}

/// Adapter whose stage6 step always fails, for the production-failure class.
fn write_failing_adapter(root: &Path) -> PathBuf {
    let tools = tools_dir();
    let render = tools.join("fake_weaver_render.py").display().to_string();
    let bridge = tools.join("fake_weaver_bridge.py").display().to_string();
    let adapter = json!({
        "adapter_id": "weaver_e2e_broken",
        "steps": {
            "stage5_audio": {
                "program": "python3",
                "args": [
                    render,
                    "--stage", "stage5",
                    "--output-dir", "{audio_dir}",
                    "--combination-ledger", "{stage5_ledger}",
                    "--duration-seconds", "0.2"
                ]
            },
            "stage6_video": {"program": "sh", "args": ["-c", "exit 9"]},
            "bridge_run": {
                "program": "python3",
                "args": [bridge, "--asset-dir", "{asset_dir}", "--journal", "{bridge_journal}"]
            }
        }
    });
    let path = root.join("adapter-broken.json");
    fs::write(&path, format!("{adapter}\n")).expect("write broken adapter config");
    path
}

fn base_args(root: &Path, adapter: &Path) -> Vec<String> {
    [
        "--repo-root",
        &root.display().to_string(),
        "--adapter-config",
        &adapter.display().to_string(),
        "--state-dir",
        &root.join("state").display().to_string(),
        "--buffer-dir",
        &root.join("buffer").display().to_string(),
        "--work-dir",
        &root.join("work").display().to_string(),
        "--stage5-ledger",
        &root.join("stage5_ledger.json").display().to_string(),
        "--soundfont",
        &root.join("dummy.sf2").display().to_string(),
    ]
    .iter()
    .map(|value| (*value).to_string())
    .collect()
}

fn with_flags(base: &[String], extra: &[&str]) -> Vec<String> {
    let mut args = base.to_vec();
    args.extend(extra.iter().map(|value| (*value).to_string()));
    args
}

/// Point the stage5 step at a fake that fails its first `fail_first` attempts.
fn with_stage5_failures(adapter: &Path, root: &Path, fail_first: u32) -> PathBuf {
    let mut config = read_json(adapter);
    let args = config["steps"]["stage5_audio"]["args"]
        .as_array_mut()
        .expect("stage5 args");
    args.push(json!("--fail-first"));
    args.push(json!(fail_first.to_string()));
    args.push(json!("--fail-state"));
    args.push(json!(
        root.join("stage5_fail_state.txt").display().to_string()
    ));
    let path = root.join("adapter-flaky.json");
    fs::write(&path, format!("{config}\n")).expect("write flaky adapter config");
    path
}

fn read_json(path: &Path) -> Value {
    let raw = fs::read_to_string(path).unwrap_or_else(|error| {
        panic!("read {}: {error}", path.display());
    });
    serde_json::from_str(&raw).unwrap_or_else(|error| panic!("parse {}: {error}", path.display()))
}

#[derive(Debug, Deserialize)]
struct LedgerRecord {
    record_id: String,
    state: String,
    #[serde(default)]
    combination_id: Option<String>,
    #[serde(default)]
    asset_dir: Option<String>,
    #[serde(default)]
    attempts: u32,
    #[serde(default)]
    bridge_attempts: u32,
    #[serde(default)]
    retryable: bool,
}

#[derive(Debug, Deserialize)]
struct LedgerFile {
    #[serde(default)]
    records: Vec<LedgerRecord>,
}

impl LedgerFile {
    fn of_state(&self, state: &str) -> Vec<&LedgerRecord> {
        self.records
            .iter()
            .filter(|record| record.state == state)
            .collect()
    }
}

fn ledger(root: &Path) -> LedgerFile {
    read_json_file(&root.join("state/weaver_asset_ledger.json"))
}

fn read_json_file<T: for<'de> Deserialize<'de>>(path: &Path) -> T {
    let raw = fs::read_to_string(path).unwrap_or_else(|error| {
        panic!("read {}: {error}", path.display());
    });
    serde_json::from_str(&raw).unwrap_or_else(|error| panic!("parse {}: {error}", path.display()))
}

#[derive(Debug, Deserialize)]
struct JournalEntry {
    combination_id: String,
    #[serde(default)]
    failed: bool,
    #[serde(default)]
    sha256_verified: bool,
}

fn journal(root: &Path) -> Vec<JournalEntry> {
    let path = root.join("state/bridge_journal.jsonl");
    if !path.exists() {
        return Vec::new();
    }
    fs::read_to_string(&path)
        .expect("read journal")
        .lines()
        .filter(|line| !line.trim().is_empty())
        .map(|line| serde_json::from_str(line).expect("parse journal line"))
        .collect()
}

fn accepted(root: &Path) -> Vec<JournalEntry> {
    journal(root)
        .into_iter()
        .filter(|entry| !entry.failed)
        .collect()
}

fn accepted_ids(root: &Path) -> BTreeSet<String> {
    accepted(root)
        .into_iter()
        .map(|entry| entry.combination_id)
        .collect()
}

fn throughput_report(root: &Path) -> Value {
    read_json(&root.join("state/weaver_throughput_report.json"))
}

fn exit_report(root: &Path) -> Value {
    read_json(&root.join("state/weaver_exit_report.json"))
}

/// Acceptance 1: three different combinations in a row, with a real report.
#[test]
fn consumes_three_distinct_combinations_and_reports_throughput() {
    let root = scratch("three");
    let adapter = write_adapter(&root, "ok", 0.5, 0.0, 0.5, &[]);
    let run = run_weaver(&with_flags(
        &base_args(&root, &adapter),
        &[
            "--consume-count",
            "3",
            "--buffer-depth",
            "3",
            "--low-water",
            "2",
        ],
    ));
    assert_eq!(run.code, 0, "{}", run.context());

    let entries = accepted(&root);
    assert_eq!(entries.len(), 3, "expected 3 consumptions: {:?}", entries);
    assert!(
        entries.iter().all(|entry| entry.sha256_verified),
        "the fake bridge must have verified every published digest"
    );
    let ids = accepted_ids(&root);
    assert_eq!(ids.len(), 3, "expected 3 distinct combination ids: {ids:?}");

    let ledger = ledger(&root);
    assert_eq!(ledger.of_state("checkpointed").len(), 3);
    assert!(ledger.of_state("failed").is_empty());
    let checkpointed_ids = ledger
        .of_state("checkpointed")
        .iter()
        .filter_map(|record| record.combination_id.clone())
        .collect::<BTreeSet<_>>();
    assert_eq!(checkpointed_ids, ids);

    // Acceptance 3: the throughput report carries all three required numbers.
    let report = throughput_report(&root);
    assert_eq!(report["stage"], "weaver_throughput_report_v1");
    assert_eq!(report["consumed_assets"], 3);
    assert!(
        report["generated_assets"].as_u64().unwrap_or(0) >= 3,
        "report={report}"
    );
    assert!(report["generation_assets_per_minute"].as_f64().unwrap() > 0.0);
    assert!(report["playback_assets_per_minute"].as_f64().unwrap() > 0.0);
    assert!(report["generation_seconds"].as_f64().unwrap() > 0.0);
    assert!(report["playback_seconds"].as_f64().unwrap() > 0.0);
    assert!(report["buffer_depth_min"].is_number());
    assert!(report["buffer_depth_max"].as_u64().unwrap() >= 1);
    assert_eq!(report["buffer_depth_target"], 3);
    assert_eq!(report["low_water"], 2);
    assert_eq!(
        report["distinct_consumed_combination_ids"]
            .as_array()
            .unwrap()
            .len(),
        3
    );
    assert_eq!(report["sustainable_live"], true, "report={report}");
    assert_eq!(report["verdict"], "can_sustain_live");
    assert_eq!(exit_report(&root)["exit_class"], "ok");
    assert_eq!(exit_report(&root)["exit_code"], 0);
}

/// Acceptance 1 (second half): `once` mode is still a single finite pass.
#[test]
fn once_mode_consumes_exactly_one_asset() {
    let root = scratch("once");
    let adapter = write_adapter(&root, "ok", 0.5, 0.0, 0.5, &[]);
    let run = run_weaver(&with_flags(
        &base_args(&root, &adapter),
        &["--once", "--buffer-depth", "3", "--low-water", "2"],
    ));
    assert_eq!(run.code, 0, "{}", run.context());
    assert_eq!(accepted(&root).len(), 1);
    assert_eq!(throughput_report(&root)["consumed_assets"], 1);
    assert_eq!(ledger(&root).of_state("checkpointed").len(), 1);

    // The default adapter still drives the existing stage7 runtime in `once`
    // loop mode, so the pre-weaver single-pass behaviour is unchanged.
    let default_adapter = read_json(
        &Path::new(MANIFEST_DIR)
            .join("src/musikalisches/runtime/config/weaver_default_adapter.json"),
    );
    let bridge_run = &default_adapter["steps"]["bridge_run"]["args"];
    let bridge_run = bridge_run.as_array().expect("bridge_run args");
    let has_once = bridge_run
        .windows(2)
        .any(|pair| pair[0] == "--loop-mode" && pair[1] == "once");
    assert!(has_once, "default adapter must keep --loop-mode once: {bridge_run:?}");
}

/// Acceptance 2: restart never re-confirms a checkpointed combination and never
/// loses a published-but-unconsumed asset.
#[test]
fn restart_keeps_published_assets_and_never_reconfirms_checkpointed() {
    let root = scratch("restart");
    let adapter = write_adapter(&root, "ok", 0.5, 0.0, 0.5, &[]);
    let base = with_flags(
        &base_args(&root, &adapter),
        &["--buffer-depth", "3", "--low-water", "2"],
    );

    let first_run = run_weaver(&with_flags(&base, &["--consume-count", "1"]));
    assert_eq!(first_run.code, 0, "{}", first_run.context());
    let first_ids = accepted_ids(&root);
    assert_eq!(first_ids.len(), 1, "run 1 must consume exactly one asset");
    let first_combination = first_ids.iter().next().unwrap().clone();

    let ledger_after_first = ledger(&root);
    assert_eq!(ledger_after_first.of_state("checkpointed").len(), 1);
    let published_dirs = ledger_after_first
        .of_state("published")
        .iter()
        .filter_map(|record| record.asset_dir.clone())
        .collect::<Vec<_>>();
    assert!(
        !published_dirs.is_empty(),
        "run 1 should leave published assets in the pool"
    );
    for dir in &published_dirs {
        assert!(Path::new(dir).is_dir(), "published asset missing: {dir}");
    }

    // Restart: same state/buffer dirs, fresh process.
    let second_run = run_weaver(&with_flags(&base, &["--consume-count", "1"]));
    assert_eq!(second_run.code, 0, "{}", second_run.context());

    let entries = accepted(&root);
    assert_eq!(entries.len(), 2, "one accepted asset per run: {entries:?}");
    let ids = accepted_ids(&root);
    assert_eq!(ids.len(), 2, "restart must not re-confirm: {ids:?}");
    assert!(
        ids.contains(&first_combination),
        "the run-1 combination must still be represented"
    );
    assert_eq!(
        entries
            .iter()
            .filter(|entry| entry.combination_id == first_combination)
            .count(),
        1,
        "a checkpointed combination must never be confirmed twice"
    );

    // Nothing published in run 1 was destroyed by the restart.
    for dir in &published_dirs {
        assert!(
            Path::new(dir).is_dir(),
            "published-but-unconsumed asset was lost: {dir}"
        );
    }
    let ledger_after_second = ledger(&root);
    assert!(ledger_after_second.of_state("checkpointed").len() >= 2);
    assert!(ledger_after_second
        .records
        .iter()
        .filter(|record| record.state == "checkpointed")
        .all(|record| record.combination_id.is_some()));
}

/// Failure class 1: production failure gets its own code and report class, and
/// never disturbs records that were already consumed.
#[test]
fn production_failure_exits_3_and_preserves_checkpointed_records() {
    let root = scratch("production");
    let good_adapter = write_adapter(&root, "ok", 0.5, 0.0, 0.5, &[]);
    let first = run_weaver(&with_flags(
        &base_args(&root, &good_adapter),
        &["--consume-count", "1", "--buffer-depth", "1", "--low-water", "1"],
    ));
    assert_eq!(first.code, 0, "{}", first.context());
    let checkpointed_before = ledger(&root)
        .of_state("checkpointed")
        .iter()
        .filter_map(|record| record.combination_id.clone())
        .collect::<BTreeSet<_>>();
    assert_eq!(checkpointed_before.len(), 1);

    let broken_adapter = write_failing_adapter(&root);
    let second = run_weaver(&with_flags(
        &base_args(&root, &broken_adapter),
        &["--max-generation-failures", "2", "--buffer-depth", "3"],
    ));
    assert_eq!(second.code, 3, "{}", second.context());

    let ledger_after = ledger(&root);
    let checkpointed_after = ledger_after
        .of_state("checkpointed")
        .iter()
        .filter_map(|record| record.combination_id.clone())
        .collect::<BTreeSet<_>>();
    assert!(
        checkpointed_before.is_subset(&checkpointed_after),
        "a render failure must not disturb already consumed records: before={checkpointed_before:?} after={checkpointed_after:?}"
    );
    let failed = ledger_after.of_state("failed");
    assert!(!failed.is_empty(), "the failed attempt must be recorded");
    assert!(failed.iter().all(|record| record.retryable));

    let report = exit_report(&root);
    assert_eq!(report["exit_class"], "production_failure");
    assert_eq!(report["exit_code"], 3);
    assert!(!report["failed_records"].as_array().unwrap().is_empty());
}

/// Failure class 2: buffer exhaustion is distinct from production failure and
/// never repeats an already played combination.
#[test]
fn buffer_exhaustion_exits_4_with_its_own_class() {
    let root = scratch("exhausted");
    let adapter = write_adapter(&root, "ok", 0.5, 0.0, 0.0, &[]);
    let run = run_weaver(&with_flags(
        &base_args(&root, &adapter),
        &[
            "--consume-count",
            "1",
            "--buffer-depth",
            "0",
            "--low-water",
            "0",
        ],
    ));
    assert_eq!(run.code, 4, "{}", run.context());
    assert!(accepted(&root).is_empty());
    let report = exit_report(&root);
    assert_eq!(report["exit_class"], "buffer_exhausted");
    assert_eq!(report["exit_code"], 4);
    assert!(report["message"]
        .as_str()
        .unwrap()
        .contains("refusing to repeat an already played combination"));
}

/// Failure class 3: bridge reconnect exhaustion gets its own code, and the
/// asset stays published so it is never lost.
#[test]
fn bridge_failure_exits_5_with_its_own_class() {
    let root = scratch("bridge");
    let adapter = write_adapter(&root, "bridge-fail", 0.5, 0.0, 0.0, &[FIRST_FAKE_COMBINATION_ID]);
    let run = run_weaver(&with_flags(
        &base_args(&root, &adapter),
        &[
            "--consume-count",
            "1",
            "--buffer-depth",
            "1",
            "--low-water",
            "1",
            "--max-bridge-attempts",
            "2",
        ],
    ));
    assert_eq!(run.code, 5, "{}", run.context());

    let ledger_after = ledger(&root);
    let published = ledger_after.of_state("published");
    assert_eq!(published.len(), 1, "the asset must not be lost");
    assert_eq!(published[0].bridge_attempts, 2);
    assert!(accepted(&root).is_empty());

    let report = exit_report(&root);
    assert_eq!(report["exit_class"], "bridge_failure");
    assert_eq!(report["exit_code"], 5);
    assert!(report["message"]
        .as_str()
        .unwrap()
        .contains("bridge reconnect exhausted"));
}

/// A missing SoundFont is a usage/config error before any rendering starts.
#[test]
fn missing_soundfont_is_a_usage_error_not_a_render_failure() {
    let root = scratch("no-soundfont");
    let adapter = write_adapter(&root, "ok", 0.5, 0.0, 0.0, &[]);
    let run = run_weaver(&with_flags(
        &base_args(&root, &adapter),
        &["--soundfont", "/nonexistent/weaver.sf2", "--once"],
    ));
    assert_eq!(run.code, 2, "{}", run.context());
    assert!(
        run.stderr.contains("soundfont path does not exist"),
        "{}",
        run.stderr
    );
    assert!(
        !root.join("state").exists(),
        "a config error must not create state"
    );
}

/// Issue #62 decision 7: when generation cannot keep up, the report says so.
#[test]
fn slow_generation_marks_cannot_sustain_live() {
    let root = scratch("unsustainable");
    let adapter = write_adapter(&root, "slow", 0.5, 1.0, 0.05, &[]);
    let run = run_weaver(&with_flags(
        &base_args(&root, &adapter),
        &[
            "--consume-count",
            "2",
            "--buffer-depth",
            "1",
            "--low-water",
            "1",
        ],
    ));
    assert_eq!(run.code, 0, "{}", run.context());

    let report = throughput_report(&root);
    assert_eq!(report["sustainable_live"], false, "report={report}");
    assert_eq!(report["verdict"], "cannot_sustain_live");
    let generation = report["generation_assets_per_minute"].as_f64().unwrap();
    let playback = report["playback_assets_per_minute"].as_f64().unwrap();
    assert!(
        generation < playback,
        "generation={generation} playback={playback}"
    );
    assert!(report["notes"]
        .as_array()
        .unwrap()
        .iter()
        .any(|note| note.as_str().unwrap().contains("cannot sustain live")));
    assert!(
        run.stderr.contains("cannot sustain live"),
        "the verdict must be visible on stderr: {}",
        run.stderr
    );
}

/// Fix A: a retried record must keep every attempt's step log.
#[test]
fn retry_archives_previous_step_logs_instead_of_truncating_them() {
    let root = scratch("attempt-logs");
    let adapter = write_adapter(&root, "flaky", 0.5, 0.0, 0.5, &[]);
    let adapter = with_stage5_failures(&adapter, &root, 2);
    let run = run_weaver(&with_flags(
        &base_args(&root, &adapter),
        &[
            "--consume-count",
            "1",
            "--buffer-depth",
            "1",
            "--low-water",
            "1",
            "--max-generation-failures",
            "3",
        ],
    ));
    assert_eq!(run.code, 0, "{}", run.context());

    let ledger = ledger(&root);
    let consumed = ledger.of_state("checkpointed");
    assert_eq!(consumed.len(), 1, "the retried record must end consumed");
    let record = consumed[0];
    assert_eq!(record.attempts, 3, "two failures then a success");

    // The three attempts are three files: the archived failures plus the
    // current attempt. Truncating on retry would leave only the last one.
    let log_dir = root.join("state/logs").join(&record.record_id);
    for name in [
        "stage5_audio.attempt-1.log",
        "stage5_audio.attempt-2.log",
        "stage5_audio.log",
    ] {
        let path = log_dir.join(name);
        assert!(path.is_file(), "missing {name} in {}", log_dir.display());
        assert!(
            fs::metadata(&path).expect("stat log").len() > 0,
            "archived log must not be empty: {}",
            path.display()
        );
    }
    let stage5_logs = fs::read_dir(&log_dir)
        .expect("read log dir")
        .filter_map(|entry| entry.ok())
        .filter(|entry| entry.file_name().to_string_lossy().starts_with("stage5_audio"))
        .count();
    assert_eq!(stage5_logs, 3, "one log file per attempt, no strays");
}

/// Fix B: a bounded run must not generate anything after the target is met.
#[test]
fn bounded_run_stops_generating_once_the_target_is_met() {
    let root = scratch("bounded");
    let adapter = write_adapter(&root, "ok", 0.5, 0.0, 0.5, &[]);
    let run = run_weaver(&with_flags(
        &base_args(&root, &adapter),
        &[
            "--consume-count",
            "2",
            "--buffer-depth",
            "3",
            "--low-water",
            "2",
        ],
    ));
    assert_eq!(run.code, 0, "{}", run.context());

    // Three to fill the pool plus one to top it up after the first consume.
    // Refilling again after the second consume would leave a fifth asset that
    // nothing ever plays.
    let ledger = ledger(&root);
    assert_eq!(ledger.of_state("checkpointed").len(), 2);
    assert_eq!(ledger.of_state("published").len(), 2);
    assert_eq!(
        ledger.records.len(),
        4,
        "no record may be reserved after the target is met"
    );
    assert!(ledger.of_state("reserved").is_empty());
    assert!(ledger.of_state("rendering").is_empty());

    let report = throughput_report(&root);
    assert_eq!(report["consumed_assets"], 2);
    assert_eq!(report["generated_assets"], 4);
    assert_eq!(exit_report(&root)["exit_class"], "ok");
    assert_eq!(exit_report(&root)["exit_code"], 0);
}
