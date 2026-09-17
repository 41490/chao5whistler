//! `musikalisches-weaver`: a resident supervisor that keeps a pool of
//! pre-generated stage5/stage6 assets ahead of the bridge.
//!
//! Responsibilities (issue #62):
//! * allocate new combinations through the existing stage5 ledger tool;
//! * render audio + video through a configurable adapter;
//! * publish each asset atomically into a buffer pool;
//! * hand whole assets to the bridge and checkpoint only after it accepted them;
//! * stay recoverable across crashes and honest about throughput limits.
//!
//! The orchestration lives here; the moving parts live in the sibling modules.

pub mod adapter;
pub mod asset;
pub mod buffer;
pub mod hash;
pub mod jsonio;
pub mod ledger;
pub mod report;
pub mod soundfont;

use std::collections::BTreeMap;
use std::fs;
use std::path::{Path, PathBuf};
use std::time::Instant;

use anyhow::{anyhow, bail, Context, Result};

use adapter::{
    Adapter, STEP_BRIDGE_BUILD, STEP_BRIDGE_RUN, STEP_STAGE5_AUDIO, STEP_STAGE6_STUB,
    STEP_STAGE6_STUB_CHECK, STEP_STAGE6_VIDEO, STEP_STAGE6_VIDEO_CHECK,
};
use buffer::{Buffer, DEFAULT_DEPTH_TARGET, DEFAULT_LOW_WATER};
use ledger::{AssetRecord, Ledger, RecoveryReport};

pub const DEFAULT_WORK_ID: &str = "mozart_dicegame_print_1790s";
pub const DEFAULT_ADAPTER_CONFIG: &str =
    "src/musikalisches/runtime/config/weaver_default_adapter.json";
pub const DEFAULT_STATE_DIR: &str = "ops/out/state/musikalisches/weaver";
pub const DEFAULT_BUFFER_DIR: &str = "ops/out/weaver-buffer";
pub const DEFAULT_WORK_DIR: &str = "ops/out/weaver-work";
pub const DEFAULT_STAGE5_LEDGER: &str =
    "ops/out/state/musikalisches/stage5_stream_sf2_combination_ledger.json";
pub const DEFAULT_SOUNDSCAPE_PROFILE: &str =
    "src/musikalisches/runtime/config/stage5_default_soundscape_profile.json";
pub const DEFAULT_LOOP_COUNT: u32 = 4;
pub const DEFAULT_MAX_GENERATION_FAILURES: u32 = 3;
pub const DEFAULT_MAX_BRIDGE_ATTEMPTS: u32 = 3;

pub const EXIT_OK: i32 = 0;
pub const EXIT_INTERNAL_ERROR: i32 = 1;
pub const EXIT_USAGE: i32 = 2;
pub const EXIT_PRODUCTION_FAILURE: i32 = 3;
pub const EXIT_BUFFER_EXHAUSTED: i32 = 4;
pub const EXIT_BRIDGE_FAILURE: i32 = 5;

pub const EXIT_CLASS_OK: &str = "ok";
pub const EXIT_CLASS_INTERNAL_ERROR: &str = "internal_error";
pub const EXIT_CLASS_USAGE_ERROR: &str = "usage_error";
pub const EXIT_CLASS_PRODUCTION_FAILURE: &str = "production_failure";
pub const EXIT_CLASS_BUFFER_EXHAUSTED: &str = "buffer_exhausted";
pub const EXIT_CLASS_BRIDGE_FAILURE: &str = "bridge_failure";

#[derive(Debug, Clone)]
pub struct WeaverConfig {
    pub work_id: String,
    pub repo_root: PathBuf,
    pub adapter_config: PathBuf,
    pub state_dir: PathBuf,
    pub buffer_dir: PathBuf,
    pub work_dir: PathBuf,
    pub report_path: PathBuf,
    pub exit_report_path: PathBuf,
    pub ledger_path: PathBuf,
    pub stage5_ledger: PathBuf,
    pub soundfont: String,
    /// Which soundfont candidate won: `explicit`, `env`, `repo_default` or `system`.
    pub soundfont_source: String,
    pub soundscape_profile: String,
    pub loop_count: u32,
    pub buffer_depth: usize,
    pub low_water: usize,
    pub reservation_timeout_seconds: i64,
    pub step_timeout_seconds: Option<f64>,
    pub max_generation_failures: u32,
    pub max_bridge_attempts: u32,
    pub consume_count: Option<u64>,
    pub play_seconds: f64,
    pub bridge_journal: PathBuf,
    pub sha256sum_bin: String,
    pub required_asset_files: Vec<String>,
}

#[derive(Debug)]
pub enum ParsedCommand {
    Run(Box<WeaverConfig>),
    Help,
}

#[derive(Debug, Clone)]
pub struct RunOutcome {
    pub exit_code: i32,
    pub exit_class: String,
    pub message: String,
    pub report_path: PathBuf,
    pub exit_report_path: PathBuf,
}

pub fn usage() -> String {
    [
        "musikalisches-weaver — buffered stage5/stage6 asset supervisor",
        "",
        "Usage: musikalisches-weaver [options]",
        "",
        "Run control:",
        "  --once                        consume exactly one published asset, then exit",
        "  --consume-count <n>           consume n assets, then exit (default: run until stopped)",
        "  --buffer-depth <n>            pool depth to keep ahead of the bridge (default 3)",
        "  --low-water <n>               refill threshold; must be <= --buffer-depth (default 2)",
        "  --max-generation-failures <n> consecutive render failures before exit 3 (default 3)",
        "  --max-bridge-attempts <n>     consecutive bridge failures before exit 5 (default 3)",
        "  --reservation-timeout-seconds <s>  reclaim stale reserved/rendering records (default 1800)",
        "  --step-timeout-seconds <s>    per adapter step budget; 0 disables (default 1800)",
        "",
        "Paths:",
        "  --repo-root <dir>             working directory for adapter steps (default: cwd)",
        "  --adapter-config <path>       adapter JSON (default src/musikalisches/runtime/config/weaver_default_adapter.json)",
        "  --state-dir <dir>             weaver state + logs (default ops/out/state/musikalisches/weaver)",
        "  --buffer-dir <dir>            published asset pool (default ops/out/weaver-buffer)",
        "  --work-dir <dir>              in-progress renders (default ops/out/weaver-work)",
        "  --ledger <path>               weaver ledger (default <state-dir>/weaver_asset_ledger.json)",
        "  --report <path>               throughput report (default <state-dir>/weaver_throughput_report.json)",
        "  --exit-report <path>          failure-class report (default <state-dir>/weaver_exit_report.json)",
        "  --bridge-journal <path>       fake-bridge consumption journal (default <state-dir>/bridge_journal.jsonl)",
        "",
        "Adapter variables:",
        "  --work-id <id>                canonical work id (default mozart_dicegame_print_1790s)",
        "  --stage5-ledger <path>        existing stage5 combination ledger",
        "  --soundfont <path>            SoundFont for stage5 (default: $MUSIKALISCHES_SOUNDFONT, then",
        "                                ops/assets/soundfonts/default.sf2, then a system GM soundfont)",
        "  --soundscape-profile <path>   stage5 soundscape profile",
        "  --loop-count <n>              stage5 hold cycles (default 4)",
        "  --play-seconds <s>            simulated playback seconds per asset (fake bridge)",
        "  --sha256sum-bin <bin>         digest tool (default sha256sum)",
        "  --required-asset-file <name>  repeatable; overrides the required publish contract",
        "",
        "  -h, --help                    print this help",
        "",
        "Exit codes: 0 ok | 1 internal error | 2 usage/config | 3 production failure |",
        "            4 buffer exhausted | 5 bridge failure",
    ]
    .join("\n")
}

fn next_value(args: &[String], index: &mut usize, flag: &str) -> Result<String> {
    let value = args
        .get(*index + 1)
        .ok_or_else(|| anyhow!("{flag} requires a value"))?;
    *index += 2;
    Ok(value.clone())
}

fn parse_usize(value: &str, flag: &str) -> Result<usize> {
    value
        .parse::<usize>()
        .with_context(|| format!("invalid {flag}: {value}"))
}

fn parse_u32(value: &str, flag: &str) -> Result<u32> {
    value
        .parse::<u32>()
        .with_context(|| format!("invalid {flag}: {value}"))
}

fn parse_f64(value: &str, flag: &str) -> Result<f64> {
    let parsed = value
        .parse::<f64>()
        .with_context(|| format!("invalid {flag}: {value}"))?;
    if !parsed.is_finite() || parsed < 0.0 {
        bail!("{flag} must be a finite value >= 0");
    }
    Ok(parsed)
}

fn resolve_path(repo_root: &Path, raw: &str) -> PathBuf {
    let candidate = PathBuf::from(raw);
    if candidate.is_absolute() {
        candidate
    } else {
        repo_root.join(candidate)
    }
}

pub fn parse_args(args: &[String]) -> Result<ParsedCommand> {
    let mut work_id = DEFAULT_WORK_ID.to_string();
    let mut repo_root: Option<PathBuf> = None;
    let mut adapter_config = DEFAULT_ADAPTER_CONFIG.to_string();
    let mut state_dir = DEFAULT_STATE_DIR.to_string();
    let mut buffer_dir = DEFAULT_BUFFER_DIR.to_string();
    let mut work_dir = DEFAULT_WORK_DIR.to_string();
    let mut report_path: Option<String> = None;
    let mut exit_report_path: Option<String> = None;
    let mut ledger_path: Option<String> = None;
    let mut stage5_ledger = DEFAULT_STAGE5_LEDGER.to_string();
    let mut soundfont: Option<String> = None;
    let mut soundscape_profile = DEFAULT_SOUNDSCAPE_PROFILE.to_string();
    let mut loop_count = DEFAULT_LOOP_COUNT;
    let mut buffer_depth = DEFAULT_DEPTH_TARGET;
    let mut low_water = DEFAULT_LOW_WATER;
    let mut reservation_timeout_seconds = ledger::DEFAULT_RESERVATION_TIMEOUT_SECONDS;
    let mut step_timeout_seconds = Some(1800.0_f64);
    let mut max_generation_failures = DEFAULT_MAX_GENERATION_FAILURES;
    let mut max_bridge_attempts = DEFAULT_MAX_BRIDGE_ATTEMPTS;
    let mut consume_count: Option<u64> = None;
    let mut once = false;
    let mut play_seconds = 0.0_f64;
    let mut bridge_journal: Option<String> = None;
    let mut sha256sum_bin = hash::DEFAULT_SHA256SUM_BIN.to_string();
    let mut required_asset_files: Option<Vec<String>> = None;

    let mut index = 0;
    while index < args.len() {
        match args[index].as_str() {
            "-h" | "--help" => return Ok(ParsedCommand::Help),
            "--work-id" => work_id = next_value(args, &mut index, "--work-id")?,
            "--repo-root" => {
                repo_root = Some(PathBuf::from(next_value(args, &mut index, "--repo-root")?))
            }
            "--adapter-config" => {
                adapter_config = next_value(args, &mut index, "--adapter-config")?
            }
            "--state-dir" => state_dir = next_value(args, &mut index, "--state-dir")?,
            "--buffer-dir" => buffer_dir = next_value(args, &mut index, "--buffer-dir")?,
            "--work-dir" => work_dir = next_value(args, &mut index, "--work-dir")?,
            "--report" => report_path = Some(next_value(args, &mut index, "--report")?),
            "--exit-report" => {
                exit_report_path = Some(next_value(args, &mut index, "--exit-report")?)
            }
            "--ledger" => ledger_path = Some(next_value(args, &mut index, "--ledger")?),
            "--stage5-ledger" => stage5_ledger = next_value(args, &mut index, "--stage5-ledger")?,
            "--soundfont" => soundfont = Some(next_value(args, &mut index, "--soundfont")?),
            "--soundscape-profile" => {
                soundscape_profile = next_value(args, &mut index, "--soundscape-profile")?
            }
            "--loop-count" => {
                loop_count = parse_u32(&next_value(args, &mut index, "--loop-count")?, "--loop-count")?
            }
            "--buffer-depth" => {
                buffer_depth =
                    parse_usize(&next_value(args, &mut index, "--buffer-depth")?, "--buffer-depth")?
            }
            "--low-water" => {
                low_water = parse_usize(&next_value(args, &mut index, "--low-water")?, "--low-water")?
            }
            "--reservation-timeout-seconds" => {
                let raw = next_value(args, &mut index, "--reservation-timeout-seconds")?;
                let parsed = raw
                    .parse::<i64>()
                    .with_context(|| format!("invalid --reservation-timeout-seconds: {raw}"))?;
                if parsed <= 0 {
                    bail!("--reservation-timeout-seconds must be > 0");
                }
                reservation_timeout_seconds = parsed;
            }
            "--step-timeout-seconds" => {
                let parsed = parse_f64(
                    &next_value(args, &mut index, "--step-timeout-seconds")?,
                    "--step-timeout-seconds",
                )?;
                step_timeout_seconds = if parsed == 0.0 { None } else { Some(parsed) };
            }
            "--max-generation-failures" => {
                max_generation_failures = parse_u32(
                    &next_value(args, &mut index, "--max-generation-failures")?,
                    "--max-generation-failures",
                )?;
                if max_generation_failures == 0 {
                    bail!("--max-generation-failures must be >= 1");
                }
            }
            "--max-bridge-attempts" => {
                max_bridge_attempts = parse_u32(
                    &next_value(args, &mut index, "--max-bridge-attempts")?,
                    "--max-bridge-attempts",
                )?;
                if max_bridge_attempts == 0 {
                    bail!("--max-bridge-attempts must be >= 1");
                }
            }
            "--consume-count" => {
                let parsed = next_value(args, &mut index, "--consume-count")?
                    .parse::<u64>()
                    .context("invalid --consume-count")?;
                if parsed == 0 {
                    bail!("--consume-count must be >= 1 (omit the flag to run until stopped)");
                }
                consume_count = Some(parsed);
            }
            "--once" => {
                once = true;
                index += 1;
            }
            "--play-seconds" => {
                play_seconds = parse_f64(
                    &next_value(args, &mut index, "--play-seconds")?,
                    "--play-seconds",
                )?
            }
            "--bridge-journal" => {
                bridge_journal = Some(next_value(args, &mut index, "--bridge-journal")?)
            }
            "--sha256sum-bin" => {
                sha256sum_bin = next_value(args, &mut index, "--sha256sum-bin")?
            }
            "--required-asset-file" => {
                let value = next_value(args, &mut index, "--required-asset-file")?;
                required_asset_files
                    .get_or_insert_with(Vec::new)
                    .push(value);
            }
            other => bail!("unknown flag: {other}"),
        }
    }

    if once && consume_count.is_some() {
        bail!("--once and --consume-count are mutually exclusive");
    }
    if once {
        consume_count = Some(1);
    }

    let repo_root = match repo_root {
        Some(path) => path,
        None => std::env::current_dir().context("resolve current directory")?,
    };
    let state_dir_path = resolve_path(&repo_root, &state_dir);
    let report_path = report_path
        .map(|raw| resolve_path(&repo_root, &raw))
        .unwrap_or_else(|| state_dir_path.join("weaver_throughput_report.json"));
    let exit_report_path = exit_report_path
        .map(|raw| resolve_path(&repo_root, &raw))
        .unwrap_or_else(|| state_dir_path.join("weaver_exit_report.json"));
    let ledger_path = ledger_path
        .map(|raw| resolve_path(&repo_root, &raw))
        .unwrap_or_else(|| state_dir_path.join("weaver_asset_ledger.json"));
    let bridge_journal = bridge_journal
        .map(|raw| resolve_path(&repo_root, &raw))
        .unwrap_or_else(|| state_dir_path.join("bridge_journal.jsonl"));

    // The repo bundles no SoundFont (`ops/assets/**` is gitignored), so resolve
    // the same chain `make stage5-sf2` resolves instead of assuming a path.
    let soundfont = soundfont::resolve_soundfont(&repo_root, soundfont.as_deref())?;

    Ok(ParsedCommand::Run(Box::new(WeaverConfig {
        work_id,
        repo_root: repo_root.clone(),
        adapter_config: resolve_path(&repo_root, &adapter_config),
        state_dir: state_dir_path,
        buffer_dir: resolve_path(&repo_root, &buffer_dir),
        work_dir: resolve_path(&repo_root, &work_dir),
        report_path,
        exit_report_path,
        ledger_path,
        stage5_ledger: resolve_path(&repo_root, &stage5_ledger),
        soundfont: soundfont.path.display().to_string(),
        soundfont_source: soundfont.source,
        soundscape_profile: resolve_path(&repo_root, &soundscape_profile)
            .display()
            .to_string(),
        loop_count,
        buffer_depth,
        low_water,
        reservation_timeout_seconds,
        step_timeout_seconds,
        max_generation_failures,
        max_bridge_attempts,
        consume_count,
        play_seconds,
        bridge_journal,
        sha256sum_bin,
        required_asset_files: required_asset_files.unwrap_or_else(|| {
            asset::DEFAULT_REQUIRED_ASSET_FILES
                .iter()
                .map(|name| (*name).to_string())
                .collect()
        }),
    })))
}

#[derive(Debug, Clone, Default)]
struct RunState {
    generated_assets: u64,
    generation_seconds: f64,
    consumed_assets: u64,
    playback_seconds: f64,
    consumed_duration_seconds: f64,
    distinct_consumed: Vec<String>,
    recovered_records: usize,
    consecutive_generation_failures: u32,
    consecutive_bridge_failures: u32,
}

#[derive(Debug, Clone, PartialEq, Eq)]
enum RefillStatus {
    Filled,
    ProductionFailed,
}

#[derive(Debug, Clone, PartialEq, Eq)]
enum GenOutcome {
    Published,
    Failed { kind: String, message: String },
}

#[derive(Debug, Clone, PartialEq, Eq)]
enum ConsumeOutcome {
    Consumed,
    BridgeFailed { message: String },
}

fn apply_adapter_vars(adapter: &mut Adapter, config: &WeaverConfig) -> Result<()> {
    let vars: BTreeMap<&str, String> = BTreeMap::from([
        ("work_id", config.work_id.clone()),
        ("repo_root", config.repo_root.display().to_string()),
        ("state_dir", config.state_dir.display().to_string()),
        ("buffer_dir", config.buffer_dir.display().to_string()),
        ("work_dir", config.work_dir.display().to_string()),
        ("stage5_ledger", config.stage5_ledger.display().to_string()),
        ("soundfont", config.soundfont.clone()),
        ("soundscape_profile", config.soundscape_profile.clone()),
        ("loop_count", config.loop_count.to_string()),
        ("play_seconds", config.play_seconds.to_string()),
        ("bridge_journal", config.bridge_journal.display().to_string()),
        ("report_path", config.report_path.display().to_string()),
        ("exit_report_path", config.exit_report_path.display().to_string()),
    ]);
    for (key, value) in vars {
        adapter.set_var(key, value);
    }
    for required in [STEP_STAGE5_AUDIO, STEP_STAGE6_VIDEO, STEP_BRIDGE_RUN] {
        if !adapter.has_step(required) {
            bail!(
                "adapter {} is missing required step {required}; available steps: {}",
                config.adapter_config.display(),
                adapter.step_names().join(", ")
            );
        }
    }
    Ok(())
}

fn mark_generation_failure(
    ledger: &mut Ledger,
    record_id: &str,
    kind: &str,
    message: &str,
) -> Result<GenOutcome> {
    eprintln!("weaver: generation failure [{kind}] on {record_id}: {message}");
    ledger.mark_failed(record_id, kind, message, true)?;
    Ok(GenOutcome::Failed {
        kind: kind.to_string(),
        message: message.to_string(),
    })
}

fn generate_asset(
    config: &WeaverConfig,
    ledger: &mut Ledger,
    adapter: &mut Adapter,
    state: &mut RunState,
    log_dir: &Path,
) -> Result<GenOutcome> {
    let record_id = ledger.begin_reservation()?;
    let record_work_dir = config.work_dir.join(&record_id);
    // Never resume from a partially written work dir: stage5 re-allocates a
    // fresh combination, so a stale directory is a hazard, not a head start.
    if record_work_dir.exists() {
        fs::remove_dir_all(&record_work_dir)
            .with_context(|| format!("clear stale work dir {}", record_work_dir.display()))?;
    }
    let audio_dir = record_work_dir.join("audio");
    let stub_dir = record_work_dir.join("stub");
    let video_dir = record_work_dir.join("video");
    adapter.set_var("record_id", record_id.clone());
    adapter.set_var("audio_dir", audio_dir.display().to_string());
    adapter.set_var("stub_dir", stub_dir.display().to_string());
    adapter.set_var("video_dir", video_dir.display().to_string());
    let record_log_dir = log_dir.join(&record_id);
    let started = Instant::now();

    let audio_step = adapter.run_step(STEP_STAGE5_AUDIO, &record_log_dir)?;
    if !audio_step.succeeded() {
        return mark_generation_failure(
            ledger,
            &record_id,
            STEP_STAGE5_AUDIO,
            &format!(
                "stage5 audio step failed (exit {}, timed_out={}, log {})",
                audio_step.exit_code, audio_step.timed_out, audio_step.log_path
            ),
        );
    }

    let combination_id = match asset::read_combination_id(&audio_dir) {
        Ok(value) => value,
        Err(error) => {
            return mark_generation_failure(ledger, &record_id, "stage5_selection", &error.to_string())
        }
    };
    ledger.mark_rendering(&record_id, &combination_id)?;

    if let Some(stub_step) = adapter.run_optional_step(STEP_STAGE6_STUB, &record_log_dir)? {
        if !stub_step.succeeded() {
            return mark_generation_failure(
                ledger,
                &record_id,
                STEP_STAGE6_STUB,
                &format!(
                    "stage6 stub step failed (exit {}, log {})",
                    stub_step.exit_code, stub_step.log_path
                ),
            );
        }
    }
    // The Makefile runs the stub validator before the render because the render
    // reads its report; keep the same order when the adapter defines the step.
    if let Some(check_step) = adapter.run_optional_step(STEP_STAGE6_STUB_CHECK, &record_log_dir)? {
        if !check_step.succeeded() {
            return mark_generation_failure(
                ledger,
                &record_id,
                STEP_STAGE6_STUB_CHECK,
                &format!(
                    "stage6 stub validation failed (exit {}, log {})",
                    check_step.exit_code, check_step.log_path
                ),
            );
        }
    }

    let video_step = adapter.run_step(STEP_STAGE6_VIDEO, &record_log_dir)?;
    if !video_step.succeeded() {
        return mark_generation_failure(
            ledger,
            &record_id,
            STEP_STAGE6_VIDEO,
            &format!(
                "stage6 video step failed (exit {}, timed_out={}, log {})",
                video_step.exit_code, video_step.timed_out, video_step.log_path
            ),
        );
    }
    // Same reason: the bridge builder requires the render validation report.
    if let Some(check_step) = adapter.run_optional_step(STEP_STAGE6_VIDEO_CHECK, &record_log_dir)? {
        if !check_step.succeeded() {
            return mark_generation_failure(
                ledger,
                &record_id,
                STEP_STAGE6_VIDEO_CHECK,
                &format!(
                    "stage6 render validation failed (exit {}, log {})",
                    check_step.exit_code, check_step.log_path
                ),
            );
        }
    }

    let required = config
        .required_asset_files
        .iter()
        .map(String::as_str)
        .collect::<Vec<_>>();
    let published = match asset::publish_asset(
        &config.sha256sum_bin,
        &config.buffer_dir,
        &audio_dir,
        &video_dir,
        &config.work_id,
        &record_id,
        &required,
    ) {
        Ok(outcome) => outcome,
        Err(error) => {
            return mark_generation_failure(ledger, &record_id, "publish", &error.to_string())
        }
    };

    ledger.mark_published(
        &record_id,
        &published.asset_id,
        &published.asset_dir,
        published.duration_seconds,
    )?;
    state.generated_assets += 1;
    state.generation_seconds += started.elapsed().as_secs_f64();
    state.consecutive_generation_failures = 0;
    eprintln!(
        "weaver: published {} ({}s) -> {}",
        published.combination_id,
        published.duration_seconds,
        published.asset_dir.display()
    );
    Ok(GenOutcome::Published)
}

fn refill(
    config: &WeaverConfig,
    ledger: &mut Ledger,
    adapter: &mut Adapter,
    state: &mut RunState,
    log_dir: &Path,
) -> Result<RefillStatus> {
    while ledger.depth() < config.buffer_depth {
        match generate_asset(config, ledger, adapter, state, log_dir)? {
            GenOutcome::Published => {}
            GenOutcome::Failed { kind, message } => {
                state.consecutive_generation_failures += 1;
                if state.consecutive_generation_failures >= config.max_generation_failures {
                    eprintln!(
                        "weaver: giving up after {} consecutive generation failures (last: {kind}: {message})",
                        state.consecutive_generation_failures
                    );
                    return Ok(RefillStatus::ProductionFailed);
                }
            }
        }
    }
    Ok(RefillStatus::Filled)
}

fn consume_asset(
    config: &WeaverConfig,
    ledger: &mut Ledger,
    adapter: &mut Adapter,
    state: &mut RunState,
    log_dir: &Path,
    record: &AssetRecord,
) -> Result<ConsumeOutcome> {
    let asset_dir = record.asset_dir.clone().ok_or_else(|| {
        anyhow!(
            "published record {} has no asset_dir; ledger is inconsistent",
            record.record_id
        )
    })?;
    let combination_id = record.combination_id.clone().unwrap_or_default();
    let bridge_dir = config.work_dir.join(&record.record_id).join("bridge");
    adapter.set_var("record_id", record.record_id.clone());
    adapter.set_var("asset_dir", asset_dir.clone());
    adapter.set_var("combination_id", combination_id.clone());
    adapter.set_var("bridge_dir", bridge_dir.display().to_string());
    let record_log_dir = log_dir.join(&record.record_id);

    let bridge_build = adapter.run_optional_step(STEP_BRIDGE_BUILD, &record_log_dir)?;
    if let Some(step) = &bridge_build {
        if !step.succeeded() {
            return bridge_failure(
                ledger,
                state,
                record,
                &format!(
                    "bridge_build step failed (exit {}, log {})",
                    step.exit_code, step.log_path
                ),
            );
        }
    }

    let bridge_run = adapter.run_step(STEP_BRIDGE_RUN, &record_log_dir)?;
    if !bridge_run.succeeded() {
        return bridge_failure(
            ledger,
            state,
            record,
            &format!(
                "bridge_run step failed (exit {}, timed_out={}, log {})",
                bridge_run.exit_code, bridge_run.timed_out, bridge_run.log_path
            ),
        );
    }

    ledger.mark_consumed(&record.record_id)?;
    ledger.mark_checkpointed(&record.record_id)?;
    state.consumed_assets += 1;
    state.playback_seconds += bridge_run.duration_seconds;
    state.consumed_duration_seconds += record.duration_seconds.unwrap_or(0.0);
    if !state.distinct_consumed.contains(&combination_id) {
        state.distinct_consumed.push(combination_id.clone());
    }
    state.consecutive_bridge_failures = 0;
    eprintln!(
        "weaver: consumed {combination_id} ({}s playback) -> checkpointed",
        bridge_run.duration_seconds
    );
    Ok(ConsumeOutcome::Consumed)
}

fn bridge_failure(
    ledger: &mut Ledger,
    state: &mut RunState,
    record: &AssetRecord,
    message: &str,
) -> Result<ConsumeOutcome> {
    let attempts = ledger.record_bridge_attempt(&record.record_id)?;
    state.consecutive_bridge_failures += 1;
    eprintln!(
        "weaver: bridge failure on {} (attempt {attempts}): {message}",
        record.combination_id.clone().unwrap_or_default()
    );
    Ok(ConsumeOutcome::BridgeFailed {
        message: message.to_string(),
    })
}

fn exit_code_for(exit_class: &str) -> i32 {
    match exit_class {
        EXIT_CLASS_PRODUCTION_FAILURE => EXIT_PRODUCTION_FAILURE,
        EXIT_CLASS_BUFFER_EXHAUSTED => EXIT_BUFFER_EXHAUSTED,
        EXIT_CLASS_BRIDGE_FAILURE => EXIT_BRIDGE_FAILURE,
        EXIT_CLASS_USAGE_ERROR => EXIT_USAGE,
        EXIT_CLASS_INTERNAL_ERROR => EXIT_INTERNAL_ERROR,
        _ => EXIT_OK,
    }
}

fn write_reports(
    config: &WeaverConfig,
    ledger: &Ledger,
    adapter: &Adapter,
    state: &RunState,
    buffer: &Buffer,
    exit_class: &str,
    message: &str,
) -> Result<RunOutcome> {
    let report = report::build_throughput_report(report::ThroughputInput {
        work_id: config.work_id.clone(),
        adapter_id: adapter.adapter_id().to_string(),
        generated_assets: state.generated_assets,
        generation_seconds: state.generation_seconds,
        consumed_assets: state.consumed_assets,
        playback_seconds: state.playback_seconds,
        consumed_asset_duration_seconds: state.consumed_duration_seconds,
        stats: buffer.stats().clone(),
        distinct_consumed_combination_ids: state.distinct_consumed.clone(),
        checkpointed_records: ledger.checkpointed_combination_ids().len(),
        failed_records: ledger.failure_summaries().len(),
        recovered_records: state.recovered_records,
    });
    report::write_throughput_report(&config.report_path, &report)?;

    let exit_report = report::ExitReport {
        stage: report::EXIT_REPORT_STAGE.to_string(),
        work_id: config.work_id.clone(),
        adapter_id: adapter.adapter_id().to_string(),
        adapter_steps: adapter.step_names(),
        exit_class: exit_class.to_string(),
        exit_code: exit_code_for(exit_class),
        message: message.to_string(),
        recorded_at: jsonio::utc_now(),
        throughput_report_path: config.report_path.display().to_string(),
        buffer_depth: ledger.depth(),
        generated_assets: state.generated_assets,
        consumed_assets: state.consumed_assets,
        recovered_records: state.recovered_records,
        failed_records: ledger.failure_summaries(),
    };
    report::write_exit_report(&config.exit_report_path, &exit_report)?;

    if !report.sustainable_live {
        for note in &report.notes {
            eprintln!("weaver: {note}");
        }
    }

    Ok(RunOutcome {
        exit_code: exit_code_for(exit_class),
        exit_class: exit_class.to_string(),
        message: message.to_string(),
        report_path: config.report_path.clone(),
        exit_report_path: config.exit_report_path.clone(),
    })
}

/// Run the supervisor to completion (bounded by `--once` / `--consume-count`).
pub fn run(config: &WeaverConfig) -> Result<RunOutcome> {
    for dir in [&config.state_dir, &config.buffer_dir, &config.work_dir] {
        fs::create_dir_all(dir).with_context(|| format!("create dir {}", dir.display()))?;
    }
    let log_dir = config.state_dir.join("logs");
    fs::create_dir_all(&log_dir).with_context(|| format!("create log dir {}", log_dir.display()))?;

    let mut ledger = Ledger::load_or_init(&config.ledger_path, &config.work_id)?;
    let mut recovery: RecoveryReport = ledger.recover_stale(config.reservation_timeout_seconds)?;
    recovery.dropped_missing_assets = ledger.drop_missing_assets()?;
    if recovery.total() > 0 {
        eprintln!(
            "weaver: startup recovery — stale reservations {}, consumed promoted to checkpointed {}, \
             missing published assets dropped {}",
            recovery.recovered_timeouts, recovery.promoted_consumed, recovery.dropped_missing_assets
        );
    }
    let stale_temp_dirs = asset::cleanup_temp_publish_dirs(&config.buffer_dir)?;
    if stale_temp_dirs > 0 {
        eprintln!("weaver: removed {stale_temp_dirs} incomplete temp publish dir(s)");
    }
    eprintln!(
        "weaver: stage5 soundfont {} (source: {})",
        config.soundfont, config.soundfont_source
    );

    let mut adapter = Adapter::load(&config.adapter_config)?;
    adapter.set_repo_root(&config.repo_root);
    adapter.set_default_timeout(config.step_timeout_seconds);
    apply_adapter_vars(&mut adapter, config)?;

    let mut buffer = Buffer::new(config.buffer_depth, config.low_water)?;
    let mut state = RunState {
        recovered_records: recovery.total(),
        ..RunState::default()
    };

    let mut exit_class = EXIT_CLASS_OK.to_string();
    let mut message = String::from("weaver stopped after the requested number of assets");

    loop {
        if let Some(target) = config.consume_count {
            if state.consumed_assets >= target {
                break;
            }
        }

        let depth = ledger.depth();
        buffer.observe(depth);
        if depth == 0 {
            match refill(config, &mut ledger, &mut adapter, &mut state, &log_dir)? {
                RefillStatus::ProductionFailed => {
                    exit_class = EXIT_CLASS_PRODUCTION_FAILURE.to_string();
                    message = format!(
                        "generation failed {} consecutive times; the pool could not be filled",
                        state.consecutive_generation_failures
                    );
                    break;
                }
                RefillStatus::Filled => {}
            }
            let depth_after = ledger.depth();
            buffer.observe(depth_after);
            if depth_after == 0 {
                exit_class = EXIT_CLASS_BUFFER_EXHAUSTED.to_string();
                message = String::from(
                    "buffer exhausted: no published asset is available and the pool could not be \
                     refilled; refusing to repeat an already played combination",
                );
                break;
            }
        }

        let Some(record) = ledger.oldest_published() else {
            exit_class = EXIT_CLASS_BUFFER_EXHAUSTED.to_string();
            message = String::from("buffer exhausted: no published asset is available");
            break;
        };

        match consume_asset(config, &mut ledger, &mut adapter, &mut state, &log_dir, &record)? {
            ConsumeOutcome::Consumed => {}
            ConsumeOutcome::BridgeFailed { message: failure } => {
                if state.consecutive_bridge_failures >= config.max_bridge_attempts {
                    exit_class = EXIT_CLASS_BRIDGE_FAILURE.to_string();
                    message = format!(
                        "bridge reconnect exhausted after {} consecutive failures: {failure}",
                        state.consecutive_bridge_failures
                    );
                    break;
                }
                continue;
            }
        }

        let depth = ledger.depth();
        buffer.observe(depth);
        if buffer.needs_refill(depth) {
            if buffer.is_low(depth) {
                eprintln!("weaver: backpressure — buffer depth {depth} is below low-water {}", buffer.low_water());
            }
            match refill(config, &mut ledger, &mut adapter, &mut state, &log_dir)? {
                RefillStatus::ProductionFailed => {
                    exit_class = EXIT_CLASS_PRODUCTION_FAILURE.to_string();
                    message = format!(
                        "generation failed {} consecutive times while refilling the pool",
                        state.consecutive_generation_failures
                    );
                    break;
                }
                RefillStatus::Filled => {}
            }
        }
    }

    write_reports(
        config,
        &ledger,
        &adapter,
        &state,
        &buffer,
        &exit_class,
        &message,
    )
}

/// Best-effort failure report for errors raised before the supervisor loop.
fn write_fatal_exit_report(config: &WeaverConfig, exit_class: &str, message: &str) {
    let payload = report::ExitReport {
        stage: report::EXIT_REPORT_STAGE.to_string(),
        work_id: config.work_id.clone(),
        adapter_id: config.adapter_config.display().to_string(),
        adapter_steps: Vec::new(),
        exit_class: exit_class.to_string(),
        exit_code: exit_code_for(exit_class),
        message: message.to_string(),
        recorded_at: jsonio::utc_now(),
        throughput_report_path: config.report_path.display().to_string(),
        buffer_depth: 0,
        generated_assets: 0,
        consumed_assets: 0,
        recovered_records: 0,
        failed_records: Vec::new(),
    };
    if let Err(error) = report::write_exit_report(&config.exit_report_path, &payload) {
        eprintln!(
            "weaver: could not write exit report {}: {error:#}",
            config.exit_report_path.display()
        );
    }
}

/// CLI entry point. Returns the process exit code instead of exiting, so tests
/// can drive the supervisor in-process.
pub fn run_cli(args: Vec<String>) -> i32 {
    let command = match parse_args(&args) {
        Ok(command) => command,
        Err(error) => {
            eprintln!("weaver: {error:#}");
            eprintln!("weaver: run `musikalisches-weaver --help` for usage");
            return EXIT_USAGE;
        }
    };

    match command {
        ParsedCommand::Help => {
            println!("{}", usage());
            EXIT_OK
        }
        ParsedCommand::Run(config) => match run(&config) {
            Ok(outcome) => {
                eprintln!(
                    "weaver: exit_class={} exit_code={} — {}",
                    outcome.exit_class, outcome.exit_code, outcome.message
                );
                eprintln!("weaver: throughput_report={}", outcome.report_path.display());
                eprintln!("weaver: exit_report={}", outcome.exit_report_path.display());
                outcome.exit_code
            }
            Err(error) => {
                let message = format!("{error:#}");
                eprintln!("weaver: {message}");
                write_fatal_exit_report(&config, EXIT_CLASS_INTERNAL_ERROR, &message);
                EXIT_INTERNAL_ERROR
            }
        },
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    /// A real (stub) file so soundfont resolution never depends on the host.
    fn soundfont_stub() -> std::path::PathBuf {
        let path = std::env::temp_dir().join(format!("weaver-sf2-stub-{}.sf2", std::process::id()));
        if !path.exists() {
            std::fs::write(&path, b"sf2").expect("write soundfont stub");
        }
        path
    }

    fn args(list: &[&str]) -> Vec<String> {
        let mut values = list
            .iter()
            .map(|value| (*value).to_string())
            .collect::<Vec<_>>();
        if !values.iter().any(|value| value == "--soundfont") {
            values.push("--soundfont".to_string());
            values.push(soundfont_stub().display().to_string());
        }
        values
    }

    fn config_from(list: &[&str]) -> WeaverConfig {
        match parse_args(&args(list)).unwrap() {
            ParsedCommand::Run(config) => *config,
            ParsedCommand::Help => panic!("expected run config"),
        }
    }

    #[test]
    fn defaults_match_the_approved_decisions() {
        let config = config_from(&[]);
        assert_eq!(config.work_id, DEFAULT_WORK_ID);
        assert_eq!(config.buffer_depth, 3);
        assert_eq!(config.low_water, 2);
        assert_eq!(config.reservation_timeout_seconds, 1800);
        assert_eq!(config.consume_count, None);
        assert_eq!(
            config.required_asset_files,
            asset::DEFAULT_REQUIRED_ASSET_FILES
                .iter()
                .map(|name| (*name).to_string())
                .collect::<Vec<_>>()
        );
        assert!(config.adapter_config.ends_with(DEFAULT_ADAPTER_CONFIG));
        assert_eq!(config.soundfont_source, "explicit");
        assert!(config.soundfont.ends_with(".sf2"));
    }

    #[test]
    fn soundfont_failures_are_config_errors_and_explicit_wins() {
        // Explicit path that does not exist is a usage/config error, not a panic.
        assert!(parse_args(&args(&["--soundfont", "/nonexistent/weaver.sf2"])).is_err());

        let stub = soundfont_stub();
        let config = config_from(&["--soundfont", stub.to_str().unwrap()]);
        assert_eq!(config.soundfont_source, "explicit");
        assert_eq!(config.soundfont, stub.display().to_string());
    }

    #[test]
    fn once_mode_is_exactly_one_consumed_asset() {
        let config = config_from(&["--once"]);
        assert_eq!(config.consume_count, Some(1));
        assert!(parse_args(&args(&["--once", "--consume-count", "3"])).is_err());
    }

    #[test]
    fn help_is_not_an_error() {
        assert!(matches!(
            parse_args(&args(&["--help"])).unwrap(),
            ParsedCommand::Help
        ));
    }

    #[test]
    fn rejects_nonsense_thresholds() {
        assert!(parse_args(&args(&["--buffer-depth", "1", "--low-water", "2"])).is_ok());
        assert!(parse_args(&args(&["--consume-count", "0"])).is_err());
        assert!(parse_args(&args(&["--reservation-timeout-seconds", "0"])).is_err());
        assert!(parse_args(&args(&["--unknown"])).is_err());
        assert!(parse_args(&args(&["--play-seconds", "-1"])).is_err());
    }

    #[test]
    fn exit_codes_are_distinguishable() {
        let codes = [
            exit_code_for(EXIT_CLASS_OK),
            exit_code_for(EXIT_CLASS_INTERNAL_ERROR),
            exit_code_for(EXIT_CLASS_USAGE_ERROR),
            exit_code_for(EXIT_CLASS_PRODUCTION_FAILURE),
            exit_code_for(EXIT_CLASS_BUFFER_EXHAUSTED),
            exit_code_for(EXIT_CLASS_BRIDGE_FAILURE),
        ];
        let mut unique = codes.to_vec();
        unique.sort_unstable();
        unique.dedup();
        assert_eq!(unique.len(), codes.len());
    }

    #[test]
    fn low_water_above_depth_is_rejected_at_runtime() {
        let config = config_from(&["--buffer-depth", "1", "--low-water", "2"]);
        assert!(Buffer::new(config.buffer_depth, config.low_water).is_err());
    }
}
