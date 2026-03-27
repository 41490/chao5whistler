use std::collections::BTreeMap;
use std::env;
use std::fs;
use std::io::{ErrorKind, Write};
use std::net::{TcpStream, ToSocketAddrs};
use std::path::{Path, PathBuf};
use std::process::{Command, Stdio};
use std::thread;
use std::time::{Duration, Instant};

use anyhow::{anyhow, bail, Context, Result};
use chrono::{Local, Utc};
use reqwest::Url;
use serde::{Deserialize, Serialize};
use serde_json::json;

use crate::audio::LiveAudioRenderer;
use crate::av::{self, AvProbeSummary, AvRenderReport};
use crate::config::schema::{Config, MotionMode, StartPolicy};
use crate::config::RTMP_URL_ENV_VAR;
use crate::replay::ReplayEngine;
use crate::video::LiveVideoRenderer;

const FFMPEG_BIN_ENV_VAR: &str = "SONGH_FFMPEG_BIN";
const FFPROBE_BIN_ENV_VAR: &str = "SONGH_FFPROBE_BIN";
pub const LOOP_MODE_ENV_VAR: &str = "SONGH_STAGE7_LOOP_MODE";
pub const MAX_RUNTIME_ENV_VAR: &str = "SONGH_STAGE7_MAX_RUNTIME_SECONDS";

const MANIFEST_FILE: &str = "stream_bridge_manifest.json";
const FFMPEG_ARGS_FILE: &str = "stream_bridge_ffmpeg_args.json";
const SMOKE_FILE: &str = "stage7_bridge_smoke.flv";
const SMOKE_PROBE_FILE: &str = "stage7_bridge_smoke_ffprobe.json";
const FAILURE_TAXONOMY_FILE: &str = "stage7_failure_taxonomy.json";
const VALIDATION_REPORT_FILE: &str = "stage7_bridge_validation_report.json";
const WRAPPER_SCRIPT_FILE: &str = "run_stage7_stream_bridge.sh";
const PREFLIGHT_REPORT_FILE: &str = "stage7_bridge_preflight_report.json";
const PREFLIGHT_LOG_FILE: &str = "stage7_bridge_preflight.stderr.log";
const RUNTIME_REPORT_FILE: &str = "stage7_bridge_runtime_report.json";
const EXIT_REPORT_FILE: &str = "stage7_bridge_exit_report.json";
const LATEST_LOG_FILE: &str = "stage7_bridge_latest.stderr.log";
const LOG_DIR_NAME: &str = "logs";
const DURATION_TOLERANCE_SECS: f64 = 0.35;

fn apply_runtime_overrides(
    config: &Config,
    motion_mode_override: Option<MotionMode>,
    angle_deg_override: Option<f64>,
) -> Config {
    let mut effective = config.clone();
    if let Some(mode) = motion_mode_override {
        effective.video.motion.mode = mode;
    }
    if let Some(angle_deg) = angle_deg_override {
        effective.video.motion.angle_deg = angle_deg;
    }
    effective
}

#[derive(Debug, Clone, Serialize)]
pub struct Stage7BuildReport {
    pub schema_version: String,
    pub output_dir: PathBuf,
    pub source_preview_mp4_path: PathBuf,
    pub smoke_flv_path: PathBuf,
    pub manifest_path: PathBuf,
    pub ffmpeg_args_path: PathBuf,
    pub failure_taxonomy_path: PathBuf,
    pub validation_report_path: PathBuf,
    pub wrapper_script_path: PathBuf,
    pub ffmpeg_bin: PathBuf,
    pub ffprobe_bin: Option<PathBuf>,
    pub smoke_ffmpeg_args: Vec<String>,
    pub source: AvRenderReport,
    pub smoke_probe: Option<AvProbeSummary>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Stage7RuntimeReport {
    pub status: String,
    pub artifact_dir: PathBuf,
    pub preflight_report_path: PathBuf,
    pub runtime_report_path: PathBuf,
    pub latest_log_path: PathBuf,
    pub latest_exit_report_path: PathBuf,
    pub attempts_total: usize,
    pub final_exit_class_id: String,
    pub final_exit_code: i32,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
struct StreamBridgeManifest {
    schema_version: String,
    work_id: String,
    output_dir: PathBuf,
    source_day: String,
    config_label: String,
    ffmpeg_bin: PathBuf,
    ffprobe_bin: Option<PathBuf>,
    video_input: VideoInputContract,
    smoke_generation: SmokeGenerationContract,
    live_runtime: LiveRuntimeContract,
    live_bridge: LiveBridgeContract,
    preflight: PreflightContract,
    runtime_executor: RuntimeExecutorContract,
    runtime_observability: RuntimeObservabilityContract,
    failure_taxonomy_file: String,
    ffmpeg_args_file: String,
    validation_report_file: String,
    wrapper_script_file: String,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
struct VideoInputContract {
    preview_mp4_path: PathBuf,
    render_manifest_path: PathBuf,
    sha256: String,
    expected_fps: u32,
    expected_frame_count: u64,
    expected_duration_seconds: f64,
    probe: Option<AvProbeSummary>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
struct SmokeGenerationContract {
    smoke_flv_path: PathBuf,
    smoke_probe_path: Option<PathBuf>,
    generated: bool,
    duration_tolerance_seconds: f64,
    probe: Option<AvProbeSummary>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
struct LiveRuntimeContract {
    generator_mode: String,
    effective_config: Config,
    start_second: u32,
    once_duration_seconds: u32,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
struct LiveBridgeContract {
    stream_url_env_var: String,
    supported_schemes: Vec<String>,
    default_loop_mode: String,
    remote_output_default_enabled: bool,
    local_record_enabled: bool,
    local_record_path_template: String,
    record_label: String,
    dual_output_supported: bool,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
struct PreflightContract {
    checks: Vec<String>,
    tcp_connect_timeout_seconds: u64,
    publish_probe_timeout_seconds: u64,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
struct RuntimeExecutorContract {
    max_attempts: u32,
    backoff_seconds: Vec<u64>,
    retryable_class_ids: Vec<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
struct RuntimeObservabilityContract {
    log_dir: String,
    preflight_report_file: String,
    preflight_log_file: String,
    runtime_report_file: String,
    exit_report_file: String,
    latest_stderr_log_file: String,
    attempt_log_pattern: String,
    attempt_report_pattern: String,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
struct StreamBridgeArgsFile {
    smoke_argv: Vec<String>,
    live_argv_with_placeholders_by_mode: BTreeMap<String, Vec<String>>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
struct FailureTaxonomy {
    taxonomy_id: String,
    default_class_id: String,
    classes: Vec<FailureClass>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
struct FailureClass {
    class_id: String,
    retryable: bool,
    match_exit_codes: Vec<i32>,
    match_any: Vec<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
struct RuntimeAttempt {
    attempt_index: u32,
    status: String,
    exit_code: i32,
    exit_class_id: String,
    retryable: bool,
    elapsed_seconds: f64,
    log_file: String,
    exit_report_file: String,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
struct RuntimeTarget {
    scheme: String,
    host: String,
    port: u16,
    path_redacted: bool,
}

#[derive(Debug, Clone, Deserialize)]
struct RawProbeOutput {
    #[serde(default)]
    format: Option<RawProbeFormat>,
    #[serde(default)]
    streams: Vec<RawProbeStream>,
}

#[derive(Debug, Clone, Deserialize)]
struct RawProbeFormat {
    #[serde(default)]
    format_name: Option<String>,
    #[serde(default)]
    duration: Option<String>,
    #[serde(default)]
    size: Option<String>,
}

#[derive(Debug, Clone, Deserialize)]
struct RawProbeStream {
    #[serde(default)]
    index: Option<u32>,
    #[serde(default)]
    codec_type: String,
    #[serde(default)]
    codec_name: Option<String>,
    #[serde(default)]
    width: Option<u32>,
    #[serde(default)]
    height: Option<u32>,
    #[serde(default)]
    sample_rate: Option<String>,
    #[serde(default)]
    channels: Option<u32>,
    #[serde(default)]
    avg_frame_rate: Option<String>,
    #[serde(default)]
    nb_frames: Option<String>,
    #[serde(default)]
    duration: Option<String>,
}

pub fn build_day_pack(
    config: &Config,
    day: &str,
    archive_root_override: Option<&Path>,
    output_dir: &Path,
    start_second: u32,
    duration_secs: u32,
    motion_mode_override: Option<MotionMode>,
    angle_deg_override: Option<f64>,
) -> Result<Stage7BuildReport> {
    fs::create_dir_all(output_dir)
        .with_context(|| format!("create stage7 output dir {}", output_dir.display()))?;

    let effective_config =
        apply_runtime_overrides(config, motion_mode_override, angle_deg_override);
    let source = av::render_day_pack(
        &effective_config,
        day,
        archive_root_override,
        output_dir,
        start_second,
        duration_secs,
        None,
        None,
    )?;

    let ffmpeg_bin = resolve_binary(FFMPEG_BIN_ENV_VAR, "ffmpeg");
    let smoke_flv_path = output_dir.join(SMOKE_FILE);
    let smoke_ffmpeg_args = build_smoke_ffmpeg_args(&source.preview_mp4_path, &smoke_flv_path);
    run_command(&ffmpeg_bin, &smoke_ffmpeg_args)
        .with_context(|| format!("render stage7 smoke {}", smoke_flv_path.display()))?;

    let smoke_probe_path = output_dir.join(SMOKE_PROBE_FILE);
    let (resolved_ffprobe_bin, actual_smoke_probe_path, smoke_probe) =
        probe_media(&smoke_flv_path, Some(&smoke_probe_path))?;
    if let Some(probe) = &smoke_probe {
        validate_smoke_probe(&source, probe)?;
    }

    let manifest_path = output_dir.join(MANIFEST_FILE);
    let ffmpeg_args_path = output_dir.join(FFMPEG_ARGS_FILE);
    let failure_taxonomy_path = output_dir.join(FAILURE_TAXONOMY_FILE);
    let validation_report_path = output_dir.join(VALIDATION_REPORT_FILE);
    let wrapper_script_path = output_dir.join(WRAPPER_SCRIPT_FILE);

    let manifest = build_manifest(
        &effective_config,
        day,
        output_dir,
        &source,
        &smoke_flv_path,
        actual_smoke_probe_path,
        smoke_probe.clone(),
        &ffmpeg_bin,
        resolved_ffprobe_bin.clone(),
        start_second,
        duration_secs,
    )?;
    let args_file = build_args_file(&manifest);
    let taxonomy = default_failure_taxonomy();
    let validation_report = build_validation_report(&manifest, &smoke_flv_path);

    write_json(&manifest_path, &manifest)?;
    write_json(&ffmpeg_args_path, &args_file)?;
    write_json(&failure_taxonomy_path, &taxonomy)?;
    write_json(&validation_report_path, &validation_report)?;
    write_wrapper_script(&wrapper_script_path, output_dir)?;

    Ok(Stage7BuildReport {
        schema_version: manifest.schema_version,
        output_dir: output_dir.to_path_buf(),
        source_preview_mp4_path: source.preview_mp4_path.clone(),
        smoke_flv_path,
        manifest_path,
        ffmpeg_args_path,
        failure_taxonomy_path,
        validation_report_path,
        wrapper_script_path,
        ffmpeg_bin,
        ffprobe_bin: resolved_ffprobe_bin,
        smoke_ffmpeg_args,
        source,
        smoke_probe,
    })
}

pub fn run_runtime(
    artifact_dir: &Path,
    loop_mode: &str,
    max_runtime_seconds: Option<u64>,
) -> Result<Stage7RuntimeReport> {
    let manifest: StreamBridgeManifest = load_json(&artifact_dir.join(MANIFEST_FILE))?;
    let taxonomy: FailureTaxonomy = load_json(&artifact_dir.join(FAILURE_TAXONOMY_FILE))?;

    let output_log_dir = artifact_dir.join(&manifest.runtime_observability.log_dir);
    fs::create_dir_all(&output_log_dir)
        .with_context(|| format!("create stage7 log dir {}", output_log_dir.display()))?;

    let preflight_report_path =
        output_log_dir.join(&manifest.runtime_observability.preflight_report_file);
    let preflight_log_path =
        output_log_dir.join(&manifest.runtime_observability.preflight_log_file);
    let runtime_report_path =
        output_log_dir.join(&manifest.runtime_observability.runtime_report_file);
    let latest_exit_report_path =
        output_log_dir.join(&manifest.runtime_observability.exit_report_file);
    let latest_log_path =
        output_log_dir.join(&manifest.runtime_observability.latest_stderr_log_file);

    let target_url = env::var(&manifest.live_bridge.stream_url_env_var).unwrap_or_default();
    if target_url.trim().is_empty() {
        let payload = json!({
            "stage": "stage7_stream_bridge_preflight",
            "status": "preflight_failed",
            "failed_check_id": "target_presence",
            "message": format!("missing {}: export {}=rtmp(s)://...", manifest.live_bridge.stream_url_env_var, manifest.live_bridge.stream_url_env_var),
        });
        write_json(&preflight_report_path, &payload)?;
        fs::write(&preflight_log_path, b"missing target stream url\n")?;
        fs::copy(&preflight_log_path, &latest_log_path).ok();
        write_json(&latest_exit_report_path, &payload)?;
        write_json(
            &runtime_report_path,
            &json!({
                "stage": "stage7_stream_bridge_runtime",
                "status": "preflight_failed",
                "loop_mode": loop_mode,
                "max_runtime_seconds": max_runtime_seconds.unwrap_or(0),
                "attempts_total": 0,
                "final_exit_class_id": "configuration_failure",
                "final_exit_code": 1,
                "preflight_report_file": preflight_report_path,
            }),
        )?;
        bail!(
            "preflight failed: target_presence; see {} and {}",
            preflight_report_path.display(),
            preflight_log_path.display()
        );
    }

    let target = sanitize_target(&target_url)?;
    if !manifest
        .live_bridge
        .supported_schemes
        .contains(&target.scheme)
    {
        let payload = json!({
            "stage": "stage7_stream_bridge_preflight",
            "status": "preflight_failed",
            "failed_check_id": "target_scheme",
            "target": target,
            "supported_schemes": manifest.live_bridge.supported_schemes,
        });
        write_json(&preflight_report_path, &payload)?;
        fs::write(&preflight_log_path, b"unsupported target scheme\n")?;
        fs::copy(&preflight_log_path, &latest_log_path).ok();
        write_json(&latest_exit_report_path, &payload)?;
        write_json(
            &runtime_report_path,
            &json!({
                "stage": "stage7_stream_bridge_runtime",
                "status": "preflight_failed",
                "loop_mode": loop_mode,
                "max_runtime_seconds": max_runtime_seconds.unwrap_or(0),
                "attempts_total": 0,
                "final_exit_class_id": "configuration_failure",
                "final_exit_code": 1,
                "preflight_report_file": preflight_report_path,
            }),
        )?;
        bail!(
            "preflight failed: target_scheme; see {} and {}",
            preflight_report_path.display(),
            preflight_log_path.display()
        );
    }

    let mut preflight_checks = Vec::new();

    let protocols_output =
        command_output_strings(&manifest.ffmpeg_bin, &[String::from("-protocols")])?;
    let protocols_combined = format!("{}\n{}", protocols_output.stdout, protocols_output.stderr);
    let protocol_supported = protocols_combined
        .lines()
        .any(|line| line.trim().eq_ignore_ascii_case(&target.scheme));
    preflight_checks.push(json!({
        "check_id": "protocol_support",
        "status": if protocol_supported { "passed" } else { "failed" },
        "details": {
            "ffmpeg_bin": manifest.ffmpeg_bin,
            "protocol": target.scheme,
        }
    }));
    if !protocol_supported {
        persist_preflight_failure(
            &preflight_report_path,
            &preflight_log_path,
            &runtime_report_path,
            &latest_exit_report_path,
            &latest_log_path,
            loop_mode,
            max_runtime_seconds,
            "protocol_support",
            "protocol support missing",
            &target,
            &preflight_checks,
        )?;
        bail!(
            "preflight failed: protocol_support; see {} and {}",
            preflight_report_path.display(),
            preflight_log_path.display()
        );
    }

    let resolved_addresses = match resolve_dns(&target.host, target.port) {
        Ok(values) => values,
        Err(error) => {
            preflight_checks.push(json!({
                "check_id": "dns_resolution",
                "status": "failed",
                "details": {
                    "host": target.host,
                    "port": target.port,
                    "error": error.to_string(),
                }
            }));
            persist_preflight_failure(
                &preflight_report_path,
                &preflight_log_path,
                &runtime_report_path,
                &latest_exit_report_path,
                &latest_log_path,
                loop_mode,
                max_runtime_seconds,
                "dns_resolution",
                &error.to_string(),
                &target,
                &preflight_checks,
            )?;
            return Err(error);
        }
    };
    preflight_checks.push(json!({
        "check_id": "dns_resolution",
        "status": "passed",
        "details": {
            "host": target.host,
            "port": target.port,
            "resolved_addresses": resolved_addresses,
        }
    }));

    let tcp_timeout = Duration::from_secs(manifest.preflight.tcp_connect_timeout_seconds);
    if let Err(error) = probe_tcp_connectivity(&target.host, target.port, tcp_timeout) {
        preflight_checks.push(json!({
            "check_id": "tcp_connectivity",
            "status": "failed",
            "details": {
                "host": target.host,
                "port": target.port,
                "timeout_seconds": manifest.preflight.tcp_connect_timeout_seconds,
                "error": error.to_string(),
            }
        }));
        persist_preflight_failure(
            &preflight_report_path,
            &preflight_log_path,
            &runtime_report_path,
            &latest_exit_report_path,
            &latest_log_path,
            loop_mode,
            max_runtime_seconds,
            "tcp_connectivity",
            &error.to_string(),
            &target,
            &preflight_checks,
        )?;
        return Err(error);
    }
    preflight_checks.push(json!({
        "check_id": "tcp_connectivity",
        "status": "passed",
        "details": {
            "host": target.host,
            "port": target.port,
            "timeout_seconds": manifest.preflight.tcp_connect_timeout_seconds,
        }
    }));

    let publish_probe_args = build_publish_probe_args(&manifest.ffmpeg_bin, &target_url);
    let publish_probe_output =
        match command_output_strings(&manifest.ffmpeg_bin, &publish_probe_args[1..]) {
            Ok(output) => output,
            Err(error) => {
                preflight_checks.push(json!({
                    "check_id": "publish_probe",
                    "status": "failed",
                    "details": {
                        "error": error.to_string(),
                        "timeout_seconds": manifest.preflight.publish_probe_timeout_seconds,
                    }
                }));
                persist_preflight_failure(
                    &preflight_report_path,
                    &preflight_log_path,
                    &runtime_report_path,
                    &latest_exit_report_path,
                    &latest_log_path,
                    loop_mode,
                    max_runtime_seconds,
                    "publish_probe",
                    &error.to_string(),
                    &target,
                    &preflight_checks,
                )?;
                return Err(error);
            }
        };
    let publish_probe_exit_code = publish_probe_output.exit_code;
    let publish_probe_stderr = redact_text(&publish_probe_output.stderr, &target_url);
    preflight_checks.push(json!({
        "check_id": "publish_probe",
        "status": if publish_probe_exit_code == 0 { "passed" } else { "failed" },
        "details": {
            "exit_code": publish_probe_exit_code,
            "timeout_seconds": manifest.preflight.publish_probe_timeout_seconds,
        }
    }));
    fs::write(&preflight_log_path, publish_probe_stderr.as_bytes())
        .with_context(|| format!("write preflight log {}", preflight_log_path.display()))?;
    let preflight_status = if publish_probe_exit_code == 0 {
        "preflight_passed"
    } else {
        "preflight_failed"
    };
    let preflight_report = json!({
        "stage": "stage7_stream_bridge_preflight",
        "status": preflight_status,
        "failed_check_id": if publish_probe_exit_code == 0 { serde_json::Value::Null } else { json!("publish_probe") },
        "target": target,
        "checks": preflight_checks,
        "command_shell": build_redacted_publish_probe_shell(&manifest.ffmpeg_bin, &manifest.live_bridge.stream_url_env_var),
    });
    write_json(&preflight_report_path, &preflight_report)?;
    fs::copy(&preflight_log_path, &latest_log_path).ok();
    write_json(&latest_exit_report_path, &preflight_report)?;
    if publish_probe_exit_code != 0 {
        write_json(
            &runtime_report_path,
            &json!({
                "stage": "stage7_stream_bridge_runtime",
                "status": "preflight_failed",
                "loop_mode": loop_mode,
                "max_runtime_seconds": max_runtime_seconds.unwrap_or(0),
                "attempts_total": 0,
                "final_exit_class_id": classify_failure(&publish_probe_stderr, publish_probe_exit_code, &taxonomy).class_id,
                "final_exit_code": publish_probe_exit_code,
                "preflight_report_file": preflight_report_path,
            }),
        )?;
        bail!(
            "preflight failed: publish_probe; see {} and {}",
            preflight_report_path.display(),
            preflight_log_path.display()
        );
    }

    let started_at = Utc::now().to_rfc3339();
    let start = Instant::now();
    let mut attempts = Vec::new();
    let mut final_exit_code = 0_i32;
    let mut final_exit_class = String::from("clean_exit");
    let mut final_status = String::from("clean_exit");
    let requested_runtime_seconds =
        resolve_requested_runtime_seconds(&manifest, loop_mode, max_runtime_seconds)?;

    for attempt_index in 1..=manifest.runtime_executor.max_attempts {
        let attempt_log_path = output_log_dir.join(format!(
            "stage7_bridge_attempt_{attempt_index:03}.stderr.log"
        ));
        let attempt_report_path = output_log_dir.join(format!(
            "stage7_bridge_attempt_{attempt_index:03}.exit_report.json"
        ));
        let live_result = run_live_generation_attempt(
            &manifest,
            loop_mode,
            requested_runtime_seconds,
            &target_url,
            resolve_local_record_path(&manifest.live_bridge)?,
            artifact_dir,
        )?;
        let live_output = live_result.output;
        let stderr = redact_text(&live_output.stderr, &target_url);
        fs::write(&attempt_log_path, stderr.as_bytes())
            .with_context(|| format!("write attempt log {}", attempt_log_path.display()))?;

        let mut classified = classify_failure(&stderr, live_output.exit_code, &taxonomy);
        if live_output.exit_code == 0 && live_result.stopped_by_requested_limit {
            classified.class_id = "runtime_limit_reached".to_string();
            classified.retryable = false;
        }
        let attempt_status = if live_output.exit_code == 0 {
            classified.class_id.clone()
        } else if classified.retryable {
            "retryable_failure".to_string()
        } else {
            "terminal_failure".to_string()
        };
        let attempt_payload = json!({
            "stage": "stage7_stream_bridge_runtime",
            "status": attempt_status,
            "exit_code": live_output.exit_code,
            "exit_class_id": classified.class_id,
            "retryable": classified.retryable,
            "matched_tokens": classified.matched_tokens,
            "log_file": attempt_log_path,
            "seconds_generated": live_result.seconds_generated,
            "command_shell": build_redacted_live_shell(&manifest, loop_mode, requested_runtime_seconds),
        });
        write_json(&attempt_report_path, &attempt_payload)?;
        fs::copy(&attempt_log_path, &latest_log_path).ok();
        write_json(&latest_exit_report_path, &attempt_payload)?;

        final_exit_code = live_output.exit_code;
        final_exit_class = attempt_payload["exit_class_id"]
            .as_str()
            .unwrap_or("unknown_failure")
            .to_string();
        final_status = attempt_payload["status"]
            .as_str()
            .unwrap_or("terminal_failure")
            .to_string();

        attempts.push(RuntimeAttempt {
            attempt_index,
            status: final_status.clone(),
            exit_code: final_exit_code,
            exit_class_id: final_exit_class.clone(),
            retryable: classified.retryable,
            elapsed_seconds: round4(start.elapsed().as_secs_f64()),
            log_file: attempt_log_path.display().to_string(),
            exit_report_file: attempt_report_path.display().to_string(),
        });

        if live_output.exit_code == 0 {
            break;
        }
        if !classified.retryable || attempt_index == manifest.runtime_executor.max_attempts {
            break;
        }
        let backoff = manifest
            .runtime_executor
            .backoff_seconds
            .get((attempt_index.saturating_sub(1)) as usize)
            .copied()
            .unwrap_or(1);
        thread::sleep(Duration::from_secs(backoff));
    }

    let finished_at = Utc::now().to_rfc3339();
    let runtime_payload = json!({
        "stage": "stage7_stream_bridge_runtime",
        "status": final_status,
        "loop_mode": loop_mode,
        "max_runtime_seconds": max_runtime_seconds.unwrap_or(0),
        "started_at": started_at,
        "finished_at": finished_at,
        "elapsed_seconds": round4(start.elapsed().as_secs_f64()),
        "target": target,
        "preflight_report_file": preflight_report_path,
        "attempts_total": attempts.len(),
        "attempts": attempts,
        "final_exit_class_id": final_exit_class,
        "final_exit_code": final_exit_code,
        "retry_policy": manifest.runtime_executor,
    });
    write_json(&runtime_report_path, &runtime_payload)?;

    if final_exit_code != 0 {
        bail!(
            "stage7 bridge failed with {}; see {} and {}",
            runtime_payload["final_exit_class_id"]
                .as_str()
                .unwrap_or("unknown_failure"),
            runtime_report_path.display(),
            latest_log_path.display()
        );
    }

    Ok(Stage7RuntimeReport {
        status: runtime_payload["status"]
            .as_str()
            .unwrap_or("clean_exit")
            .to_string(),
        artifact_dir: artifact_dir.to_path_buf(),
        preflight_report_path,
        runtime_report_path,
        latest_log_path,
        latest_exit_report_path,
        attempts_total: runtime_payload["attempts_total"].as_u64().unwrap_or(0) as usize,
        final_exit_class_id: runtime_payload["final_exit_class_id"]
            .as_str()
            .unwrap_or("clean_exit")
            .to_string(),
        final_exit_code: runtime_payload["final_exit_code"].as_i64().unwrap_or(0) as i32,
    })
}

fn build_manifest(
    config: &Config,
    day: &str,
    output_dir: &Path,
    source: &AvRenderReport,
    smoke_flv_path: &Path,
    smoke_probe_path: Option<PathBuf>,
    smoke_probe: Option<AvProbeSummary>,
    ffmpeg_bin: &Path,
    ffprobe_bin: Option<PathBuf>,
    start_second: u32,
    duration_secs: u32,
) -> Result<StreamBridgeManifest> {
    Ok(StreamBridgeManifest {
        schema_version: "stage7.stream_bridge.v2".to_string(),
        work_id: format!("songh-stage7-{}", config.meta.label),
        output_dir: output_dir.to_path_buf(),
        source_day: day.to_string(),
        config_label: config.meta.label.clone(),
        ffmpeg_bin: ffmpeg_bin.to_path_buf(),
        ffprobe_bin,
        video_input: VideoInputContract {
            preview_mp4_path: source.preview_mp4_path.clone(),
            render_manifest_path: source.manifest_path.clone(),
            sha256: sha256_file(&source.preview_mp4_path)?,
            expected_fps: source.expected_fps,
            expected_frame_count: source.expected_frame_count,
            expected_duration_seconds: source.expected_duration_seconds,
            probe: source.probe.clone(),
        },
        smoke_generation: SmokeGenerationContract {
            smoke_flv_path: smoke_flv_path.to_path_buf(),
            smoke_probe_path,
            generated: true,
            duration_tolerance_seconds: DURATION_TOLERANCE_SECS,
            probe: smoke_probe,
        },
        live_runtime: LiveRuntimeContract {
            generator_mode: "tick_live_generator".to_string(),
            effective_config: config.clone(),
            start_second,
            once_duration_seconds: duration_secs,
        },
        live_bridge: LiveBridgeContract {
            stream_url_env_var: RTMP_URL_ENV_VAR.to_string(),
            supported_schemes: vec!["rtmp".to_string(), "rtmps".to_string()],
            default_loop_mode: "infinite".to_string(),
            remote_output_default_enabled: config.outputs.enable_rtmp,
            local_record_enabled: config.outputs.enable_local_record
                && config.outputs.record.enabled,
            local_record_path_template: config.outputs.record.path.clone(),
            record_label: config.meta.label.clone(),
            dual_output_supported: true,
        },
        preflight: PreflightContract {
            checks: vec![
                "target_scheme".to_string(),
                "protocol_support".to_string(),
                "dns_resolution".to_string(),
                "tcp_connectivity".to_string(),
                "publish_probe".to_string(),
            ],
            tcp_connect_timeout_seconds: 3,
            publish_probe_timeout_seconds: 8,
        },
        runtime_executor: RuntimeExecutorContract {
            max_attempts: 4,
            backoff_seconds: vec![1, 3, 10],
            retryable_class_ids: vec![
                "network_jitter".to_string(),
                "remote_disconnect".to_string(),
                "handshake_failure".to_string(),
            ],
        },
        runtime_observability: RuntimeObservabilityContract {
            log_dir: LOG_DIR_NAME.to_string(),
            preflight_report_file: PREFLIGHT_REPORT_FILE.to_string(),
            preflight_log_file: PREFLIGHT_LOG_FILE.to_string(),
            runtime_report_file: RUNTIME_REPORT_FILE.to_string(),
            exit_report_file: EXIT_REPORT_FILE.to_string(),
            latest_stderr_log_file: LATEST_LOG_FILE.to_string(),
            attempt_log_pattern: "stage7_bridge_attempt_{attempt:03}.stderr.log".to_string(),
            attempt_report_pattern: "stage7_bridge_attempt_{attempt:03}.exit_report.json"
                .to_string(),
        },
        failure_taxonomy_file: FAILURE_TAXONOMY_FILE.to_string(),
        ffmpeg_args_file: FFMPEG_ARGS_FILE.to_string(),
        validation_report_file: VALIDATION_REPORT_FILE.to_string(),
        wrapper_script_file: WRAPPER_SCRIPT_FILE.to_string(),
    })
}

fn build_args_file(manifest: &StreamBridgeManifest) -> StreamBridgeArgsFile {
    let mut by_mode = BTreeMap::new();
    by_mode.insert(
        "once".to_string(),
        live_args_with_placeholders(manifest, "once"),
    );
    by_mode.insert(
        "infinite".to_string(),
        live_args_with_placeholders(manifest, "infinite"),
    );
    StreamBridgeArgsFile {
        smoke_argv: build_smoke_ffmpeg_args(
            &manifest.video_input.preview_mp4_path,
            &manifest.smoke_generation.smoke_flv_path,
        ),
        live_argv_with_placeholders_by_mode: by_mode,
    }
}

fn build_validation_report(
    manifest: &StreamBridgeManifest,
    smoke_flv_path: &Path,
) -> serde_json::Value {
    let mut checks = Vec::new();
    checks.push(json!({
        "check_id": "preview_mp4_present",
        "status": if manifest.video_input.preview_mp4_path.exists() { "passed" } else { "failed" },
        "details": { "path": manifest.video_input.preview_mp4_path }
    }));
    checks.push(json!({
        "check_id": "smoke_flv_present",
        "status": if smoke_flv_path.exists() { "passed" } else { "failed" },
        "details": { "path": smoke_flv_path }
    }));
    checks.push(json!({
        "check_id": "smoke_probe_available",
        "status": if manifest.smoke_generation.probe.is_some() { "passed" } else { "failed" },
        "details": { "probe_path": manifest.smoke_generation.smoke_probe_path }
    }));
    let failed = checks
        .iter()
        .filter(|check| check["status"].as_str() == Some("failed"))
        .count();
    json!({
        "stage": "stage7_stream_bridge",
        "status": if failed == 0 { "passed" } else { "failed" },
        "summary": {
            "checks_total": checks.len(),
            "checks_failed": failed,
            "work_id": manifest.work_id,
            "default_loop_mode": manifest.live_bridge.default_loop_mode,
            "stream_url_env_var": manifest.live_bridge.stream_url_env_var,
        },
        "checks": checks,
    })
}

fn write_wrapper_script(path: &Path, artifact_dir: &Path) -> Result<()> {
    let repo_root = PathBuf::from(env!("CARGO_MANIFEST_DIR"))
        .parent()
        .and_then(|parent| parent.parent())
        .ok_or_else(|| anyhow!("resolve repo root"))?
        .to_path_buf();
    let manifest_path = PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("Cargo.toml");
    let script = format!(
        "#!/usr/bin/env bash\nset -euo pipefail\nLOOP_MODE=\"${{{}: -infinite}}\"\nMAX_RUNTIME=\"${{{}: -0}}\"\ncd \"{}\"\n\"${{CARGO:-cargo}}\" run --manifest-path \"{}\" -- run-stream-bridge --artifact-dir \"{}\" --loop-mode \"$LOOP_MODE\" --max-runtime-secs \"$MAX_RUNTIME\"\n",
        LOOP_MODE_ENV_VAR,
        MAX_RUNTIME_ENV_VAR,
        repo_root.display(),
        manifest_path.display(),
        artifact_dir.display(),
    )
    .replace("${SONGH_STAGE7_LOOP_MODE: -infinite}", "${SONGH_STAGE7_LOOP_MODE:-infinite}")
    .replace("${SONGH_STAGE7_MAX_RUNTIME_SECONDS: -0}", "${SONGH_STAGE7_MAX_RUNTIME_SECONDS:-0}");
    fs::write(path, script).with_context(|| format!("write wrapper script {}", path.display()))?;
    #[cfg(unix)]
    {
        use std::os::unix::fs::PermissionsExt;
        let mut permissions = fs::metadata(path)?.permissions();
        permissions.set_mode(0o755);
        fs::set_permissions(path, permissions)?;
    }
    Ok(())
}

fn build_smoke_ffmpeg_args(input_path: &Path, output_path: &Path) -> Vec<String> {
    vec![
        "ffmpeg".to_string(),
        "-y".to_string(),
        "-loglevel".to_string(),
        "error".to_string(),
        "-i".to_string(),
        input_path.display().to_string(),
        "-c".to_string(),
        "copy".to_string(),
        "-f".to_string(),
        "flv".to_string(),
        output_path.display().to_string(),
    ]
}

fn build_publish_probe_args(ffmpeg_bin: &Path, target_url: &str) -> Vec<String> {
    vec![
        ffmpeg_bin.display().to_string(),
        "-hide_banner".to_string(),
        "-nostats".to_string(),
        "-loglevel".to_string(),
        "error".to_string(),
        "-f".to_string(),
        "lavfi".to_string(),
        "-i".to_string(),
        "testsrc=size=16x16:rate=1".to_string(),
        "-f".to_string(),
        "lavfi".to_string(),
        "-i".to_string(),
        "anullsrc=r=48000:cl=stereo".to_string(),
        "-t".to_string(),
        "1".to_string(),
        "-map".to_string(),
        "0:v:0".to_string(),
        "-map".to_string(),
        "1:a:0".to_string(),
        "-c:v".to_string(),
        "libx264".to_string(),
        "-preset".to_string(),
        "ultrafast".to_string(),
        "-g".to_string(),
        "1".to_string(),
        "-pix_fmt".to_string(),
        "yuv420p".to_string(),
        "-c:a".to_string(),
        "aac".to_string(),
        "-b:a".to_string(),
        "64k".to_string(),
        "-f".to_string(),
        "flv".to_string(),
        target_url.to_string(),
    ]
}

fn live_args_with_placeholders(manifest: &StreamBridgeManifest, loop_mode: &str) -> Vec<String> {
    let requested_runtime_seconds = if loop_mode == "once" {
        Some(manifest.live_runtime.once_duration_seconds as u64)
    } else {
        None
    };
    build_live_ffmpeg_args_with_limit(
        manifest,
        Path::new("<VIDEO_PIPE>"),
        Path::new("<AUDIO_PIPE>"),
        "<TARGET_URL>",
        manifest
            .live_bridge
            .local_record_enabled
            .then(|| PathBuf::from("<LOCAL_RECORD_PATH>")),
        requested_runtime_seconds,
    )
    .unwrap_or_default()
}

fn build_live_ffmpeg_args_with_limit(
    manifest: &StreamBridgeManifest,
    video_pipe_path: &Path,
    audio_pipe_path: &Path,
    target_url: &str,
    local_record_path: Option<PathBuf>,
    requested_runtime_seconds: Option<u64>,
) -> Result<Vec<String>> {
    let mut args = vec![
        manifest.ffmpeg_bin.display().to_string(),
        "-hide_banner".to_string(),
        "-nostats".to_string(),
        "-loglevel".to_string(),
        "error".to_string(),
        "-f".to_string(),
        "rawvideo".to_string(),
        "-pix_fmt".to_string(),
        "rgba".to_string(),
        "-s".to_string(),
        format!(
            "{}x{}",
            manifest.live_runtime.effective_config.video.canvas.width,
            manifest.live_runtime.effective_config.video.canvas.height
        ),
        "-r".to_string(),
        manifest
            .live_runtime
            .effective_config
            .video
            .canvas
            .fps
            .to_string(),
    ];
    args.push("-i".to_string());
    args.push(video_pipe_path.display().to_string());
    args.push("-f".to_string());
    args.push("s16le".to_string());
    args.push("-ar".to_string());
    args.push(
        manifest
            .live_runtime
            .effective_config
            .audio
            .sample_rate
            .to_string(),
    );
    args.push("-ac".to_string());
    args.push(
        manifest
            .live_runtime
            .effective_config
            .audio
            .channels
            .to_string(),
    );
    args.push("-i".to_string());
    args.push(audio_pipe_path.display().to_string());
    if let Some(seconds) = requested_runtime_seconds.filter(|value| *value > 0) {
        args.push("-t".to_string());
        args.push(seconds.to_string());
    }
    args.push("-map".to_string());
    args.push("0:v:0".to_string());
    args.push("-map".to_string());
    args.push("1:a:0".to_string());
    args.push("-c:v".to_string());
    args.push("libx264".to_string());
    args.push("-preset".to_string());
    args.push(
        manifest
            .live_runtime
            .effective_config
            .outputs
            .encode
            .video_preset
            .clone(),
    );
    args.push("-pix_fmt".to_string());
    args.push("yuv420p".to_string());
    args.push("-c:a".to_string());
    args.push("aac".to_string());
    args.push("-b:a".to_string());
    args.push(format!(
        "{}k",
        manifest
            .live_runtime
            .effective_config
            .outputs
            .encode
            .audio_bitrate_kbps
    ));
    args.push("-f".to_string());
    args.push("flv".to_string());
    args.push(target_url.to_string());
    if let Some(path) = local_record_path {
        if let Some(parent) = path.parent() {
            fs::create_dir_all(parent)
                .with_context(|| format!("create local record dir {}", parent.display()))?;
        }
        args.push("-map".to_string());
        args.push("0:v:0".to_string());
        args.push("-map".to_string());
        args.push("1:a:0".to_string());
        args.push("-c:v".to_string());
        args.push("libx264".to_string());
        args.push("-preset".to_string());
        args.push(
            manifest
                .live_runtime
                .effective_config
                .outputs
                .encode
                .video_preset
                .clone(),
        );
        args.push("-pix_fmt".to_string());
        args.push("yuv420p".to_string());
        args.push("-c:a".to_string());
        args.push("aac".to_string());
        args.push("-b:a".to_string());
        args.push(format!(
            "{}k",
            manifest
                .live_runtime
                .effective_config
                .outputs
                .encode
                .audio_bitrate_kbps
        ));
        args.push("-f".to_string());
        args.push("flv".to_string());
        args.push(path.display().to_string());
    }
    Ok(args)
}

#[derive(Debug)]
struct LiveAttemptResult {
    output: CommandOutput,
    seconds_generated: u64,
    stopped_by_requested_limit: bool,
}

fn resolve_requested_runtime_seconds(
    manifest: &StreamBridgeManifest,
    loop_mode: &str,
    max_runtime_seconds: Option<u64>,
) -> Result<Option<u64>> {
    if loop_mode != "once" && loop_mode != "infinite" {
        bail!("unsupported loop mode: {loop_mode}");
    }

    let override_limit = max_runtime_seconds.filter(|value| *value > 0);
    if loop_mode == "once" {
        Ok(Some(override_limit.unwrap_or(
            manifest.live_runtime.once_duration_seconds as u64,
        )))
    } else {
        Ok(override_limit)
    }
}

fn run_live_generation_attempt(
    manifest: &StreamBridgeManifest,
    loop_mode: &str,
    requested_runtime_seconds: Option<u64>,
    target_url: &str,
    local_record_path: Option<PathBuf>,
    artifact_dir: &Path,
) -> Result<LiveAttemptResult> {
    if loop_mode != "once" && loop_mode != "infinite" {
        bail!("unsupported loop mode: {loop_mode}");
    }
    #[cfg(not(unix))]
    {
        let _ = (
            manifest,
            requested_runtime_seconds,
            target_url,
            local_record_path,
            artifact_dir,
        );
        bail!("stage7 live runtime currently requires unix named pipes");
    }
    #[cfg(unix)]
    {
        let pipe_dir = artifact_dir.join("live_runtime");
        fs::create_dir_all(&pipe_dir)
            .with_context(|| format!("create live runtime dir {}", pipe_dir.display()))?;
        let video_pipe_path = pipe_dir.join("video.rgba.pipe");
        let audio_pipe_path = pipe_dir.join("audio.s16le.pipe");
        recreate_named_pipe(&video_pipe_path)?;
        recreate_named_pipe(&audio_pipe_path)?;

        let ffmpeg_args = build_live_ffmpeg_args_with_limit(
            manifest,
            &video_pipe_path,
            &audio_pipe_path,
            target_url,
            local_record_path,
            requested_runtime_seconds,
        )?;
        let child = Command::new(&manifest.ffmpeg_bin)
            .args(&ffmpeg_args[1..])
            .stdin(Stdio::null())
            .stdout(Stdio::piped())
            .stderr(Stdio::piped())
            .spawn()
            .with_context(|| format!("spawn ffmpeg {}", manifest.ffmpeg_bin.display()))?;

        let mut video_writer = fs::OpenOptions::new()
            .write(true)
            .open(&video_pipe_path)
            .with_context(|| format!("open live video pipe {}", video_pipe_path.display()))?;
        let mut audio_writer = fs::OpenOptions::new()
            .write(true)
            .open(&audio_pipe_path)
            .with_context(|| format!("open live audio pipe {}", audio_pipe_path.display()))?;

        let mut engine = ReplayEngine::open(
            &manifest.live_runtime.effective_config,
            &manifest.source_day,
            None,
            manifest.live_runtime.start_second,
        )?;
        let mut video_renderer =
            LiveVideoRenderer::new(&manifest.live_runtime.effective_config, None, None)?;
        let mut audio_renderer = LiveAudioRenderer::new(&manifest.live_runtime.effective_config)?;

        if manifest.live_runtime.effective_config.runtime.start_policy
            == StartPolicy::AlignToNextSecond
        {
            align_to_next_second();
        }

        let pacing_origin = Instant::now();
        let mut seconds_generated = 0_u64;
        let mut stopped_by_requested_limit = false;
        let generation_result = (|| -> Result<()> {
            loop {
                if requested_runtime_seconds
                    .map(|seconds| seconds_generated >= seconds)
                    .unwrap_or(false)
                {
                    stopped_by_requested_limit = true;
                    break;
                }

                let Some(tick) = engine.next_tick()? else {
                    break;
                };

                let frames = video_renderer.render_tick(&tick)?;
                let audio_bytes = audio_renderer.render_tick(&tick)?;
                for frame in frames {
                    video_writer
                        .write_all(frame.as_raw())
                        .with_context(|| "write live video frame to pipe")?;
                }
                audio_writer
                    .write_all(&audio_bytes)
                    .with_context(|| "write live audio chunk to pipe")?;
                video_writer.flush().ok();
                audio_writer.flush().ok();

                seconds_generated += 1;
                pace_live_tick(
                    &manifest.live_runtime.effective_config,
                    &pacing_origin,
                    seconds_generated,
                );
            }
            Ok(())
        })();

        drop(video_writer);
        drop(audio_writer);
        let output = child
            .wait_with_output()
            .with_context(|| format!("wait ffmpeg {}", manifest.ffmpeg_bin.display()))?;
        fs::remove_file(&video_pipe_path).ok();
        fs::remove_file(&audio_pipe_path).ok();

        let command_output = CommandOutput {
            exit_code: output.status.code().unwrap_or(1),
            stdout: String::from_utf8_lossy(&output.stdout).into_owned(),
            stderr: String::from_utf8_lossy(&output.stderr).into_owned(),
        };
        if let Err(error) = generation_result {
            if command_output.exit_code == 0 {
                return Err(error);
            }
        }

        Ok(LiveAttemptResult {
            output: command_output,
            seconds_generated,
            stopped_by_requested_limit,
        })
    }
}

#[cfg(unix)]
fn recreate_named_pipe(path: &Path) -> Result<()> {
    if path.exists() {
        fs::remove_file(path).with_context(|| format!("remove stale pipe {}", path.display()))?;
    }
    let output = Command::new("mkfifo")
        .arg(path)
        .output()
        .with_context(|| format!("spawn mkfifo for {}", path.display()))?;
    if !output.status.success() {
        bail!(
            "mkfifo {} exited with {}: {}",
            path.display(),
            output.status,
            String::from_utf8_lossy(&output.stderr).trim()
        );
    }
    Ok(())
}

fn align_to_next_second() {
    use std::time::UNIX_EPOCH;

    let now = std::time::SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap_or_else(|_| Duration::from_secs(0));
    let nanos = now.subsec_nanos();
    if nanos > 0 {
        thread::sleep(Duration::from_nanos(
            1_000_000_000_u64.saturating_sub(nanos as u64),
        ));
    }
}

fn pace_live_tick(config: &Config, pacing_origin: &Instant, seconds_generated: u64) {
    if !matches!(
        config.runtime.clock,
        crate::config::schema::RuntimeClock::RealtimeDay
    ) {
        return;
    }

    let target_elapsed = Duration::from_secs(seconds_generated);
    let elapsed = pacing_origin.elapsed();
    if elapsed < target_elapsed {
        thread::sleep(target_elapsed - elapsed);
    }
}

fn resolve_local_record_path(contract: &LiveBridgeContract) -> Result<Option<PathBuf>> {
    if !contract.local_record_enabled {
        return Ok(None);
    }
    let date = Local::now().format("%Y-%m-%d").to_string();
    let path = contract
        .local_record_path_template
        .replace("{date}", &date)
        .replace("{label}", &contract.record_label);
    Ok(Some(PathBuf::from(path)))
}

fn sanitize_target(target_url: &str) -> Result<RuntimeTarget> {
    let parsed = Url::parse(target_url).with_context(|| "parse stream url")?;
    let host = parsed
        .host_str()
        .ok_or_else(|| anyhow!("stream url is missing host"))?;
    let port = parsed
        .port_or_known_default()
        .or_else(|| match parsed.scheme() {
            "rtmp" => Some(1935),
            "rtmps" => Some(443),
            _ => None,
        })
        .ok_or_else(|| anyhow!("stream url is missing port"))?;
    Ok(RuntimeTarget {
        scheme: parsed.scheme().to_string(),
        host: host.to_string(),
        port,
        path_redacted: true,
    })
}

fn resolve_dns(host: &str, port: u16) -> Result<Vec<String>> {
    let addrs = (host, port)
        .to_socket_addrs()
        .with_context(|| format!("resolve dns for {host}:{port}"))?;
    let mut values = addrs.map(|addr| addr.ip().to_string()).collect::<Vec<_>>();
    values.sort();
    values.dedup();
    if values.is_empty() {
        bail!("dns returned no addresses for {host}:{port}");
    }
    Ok(values)
}

fn probe_tcp_connectivity(host: &str, port: u16, timeout: Duration) -> Result<()> {
    let addrs = (host, port)
        .to_socket_addrs()
        .with_context(|| format!("resolve tcp target {host}:{port}"))?;
    let mut last_error = None;
    for addr in addrs {
        match TcpStream::connect_timeout(&addr, timeout) {
            Ok(stream) => {
                drop(stream);
                return Ok(());
            }
            Err(error) => last_error = Some(error),
        }
    }
    match last_error {
        Some(error) => Err(error).with_context(|| format!("tcp connect {host}:{port}")),
        None => bail!("no tcp address candidates for {host}:{port}"),
    }
}

fn default_failure_taxonomy() -> FailureTaxonomy {
    FailureTaxonomy {
        taxonomy_id: "songh.stage7.failure_taxonomy.v1".to_string(),
        default_class_id: "unknown_failure".to_string(),
        classes: vec![
            FailureClass {
                class_id: "clean_exit".to_string(),
                retryable: false,
                match_exit_codes: vec![0],
                match_any: vec![],
            },
            FailureClass {
                class_id: "interrupted".to_string(),
                retryable: false,
                match_exit_codes: vec![130],
                match_any: vec!["immediate exit requested".to_string()],
            },
            FailureClass {
                class_id: "runtime_limit_reached".to_string(),
                retryable: false,
                match_exit_codes: vec![],
                match_any: vec![],
            },
            FailureClass {
                class_id: "auth_failure".to_string(),
                retryable: false,
                match_exit_codes: vec![],
                match_any: vec![
                    "403 forbidden".to_string(),
                    "forbidden".to_string(),
                    "authorization failed".to_string(),
                    "authentication failed".to_string(),
                    "invalid key".to_string(),
                ],
            },
            FailureClass {
                class_id: "handshake_failure".to_string(),
                retryable: true,
                match_exit_codes: vec![],
                match_any: vec![
                    "handshake".to_string(),
                    "tls".to_string(),
                    "ssl".to_string(),
                    "server returned 4".to_string(),
                ],
            },
            FailureClass {
                class_id: "network_jitter".to_string(),
                retryable: true,
                match_exit_codes: vec![],
                match_any: vec![
                    "connection reset".to_string(),
                    "timed out".to_string(),
                    "broken pipe".to_string(),
                    "network is unreachable".to_string(),
                ],
            },
            FailureClass {
                class_id: "remote_disconnect".to_string(),
                retryable: true,
                match_exit_codes: vec![],
                match_any: vec![
                    "end of file".to_string(),
                    "connection closed".to_string(),
                    "server disconnected".to_string(),
                ],
            },
            FailureClass {
                class_id: "configuration_failure".to_string(),
                retryable: false,
                match_exit_codes: vec![],
                match_any: vec![
                    "invalid argument".to_string(),
                    "protocol not found".to_string(),
                    "no such file or directory".to_string(),
                ],
            },
            FailureClass {
                class_id: "unknown_failure".to_string(),
                retryable: false,
                match_exit_codes: vec![],
                match_any: vec![],
            },
        ],
    }
}

#[derive(Debug)]
struct ClassifiedFailure {
    class_id: String,
    retryable: bool,
    matched_tokens: Vec<String>,
}

fn classify_failure(stderr: &str, exit_code: i32, taxonomy: &FailureTaxonomy) -> ClassifiedFailure {
    for class in &taxonomy.classes {
        if class.match_exit_codes.contains(&exit_code) {
            return ClassifiedFailure {
                class_id: class.class_id.clone(),
                retryable: class.retryable,
                matched_tokens: Vec::new(),
            };
        }
    }
    let lowered = stderr.to_ascii_lowercase();
    for class in &taxonomy.classes {
        let matched_tokens = class
            .match_any
            .iter()
            .filter(|token| lowered.contains(&token.to_ascii_lowercase()))
            .cloned()
            .collect::<Vec<_>>();
        if !matched_tokens.is_empty() {
            return ClassifiedFailure {
                class_id: class.class_id.clone(),
                retryable: class.retryable,
                matched_tokens,
            };
        }
    }
    ClassifiedFailure {
        class_id: taxonomy.default_class_id.clone(),
        retryable: false,
        matched_tokens: Vec::new(),
    }
}

fn persist_preflight_failure(
    preflight_report_path: &Path,
    preflight_log_path: &Path,
    runtime_report_path: &Path,
    latest_exit_report_path: &Path,
    latest_log_path: &Path,
    loop_mode: &str,
    max_runtime_seconds: Option<u64>,
    failed_check_id: &str,
    message: &str,
    target: &RuntimeTarget,
    checks: &[serde_json::Value],
) -> Result<()> {
    fs::write(preflight_log_path, format!("{message}\n"))?;
    let payload = json!({
        "stage": "stage7_stream_bridge_preflight",
        "status": "preflight_failed",
        "failed_check_id": failed_check_id,
        "target": target,
        "checks": checks,
    });
    write_json(preflight_report_path, &payload)?;
    fs::copy(preflight_log_path, latest_log_path).ok();
    write_json(latest_exit_report_path, &payload)?;
    write_json(
        runtime_report_path,
        &json!({
            "stage": "stage7_stream_bridge_runtime",
            "status": "preflight_failed",
            "loop_mode": loop_mode,
            "max_runtime_seconds": max_runtime_seconds.unwrap_or(0),
            "attempts_total": 0,
            "final_exit_class_id": "configuration_failure",
            "final_exit_code": 1,
            "preflight_report_file": preflight_report_path,
        }),
    )?;
    Ok(())
}

fn build_redacted_publish_probe_shell(ffmpeg_bin: &Path, stream_env_var: &str) -> String {
    format!(
        "{} -hide_banner -nostats -loglevel error -f lavfi -i testsrc=size=16x16:rate=1 -f lavfi -i anullsrc=r=48000:cl=stereo -t 1 -map 0:v:0 -map 1:a:0 -c:v libx264 -preset ultrafast -g 1 -pix_fmt yuv420p -c:a aac -b:a 64k -f flv ${{{stream_env_var}}}",
        ffmpeg_bin.display()
    )
}

fn build_redacted_live_shell(
    manifest: &StreamBridgeManifest,
    loop_mode: &str,
    requested_runtime_seconds: Option<u64>,
) -> String {
    let mut parts = vec![
        manifest.ffmpeg_bin.display().to_string(),
        "-hide_banner".to_string(),
        "-nostats".to_string(),
        "-loglevel error".to_string(),
        "-f rawvideo -pix_fmt rgba".to_string(),
        format!(
            "-s {}x{}",
            manifest.live_runtime.effective_config.video.canvas.width,
            manifest.live_runtime.effective_config.video.canvas.height
        ),
        format!(
            "-r {}",
            manifest.live_runtime.effective_config.video.canvas.fps
        ),
        "-i <VIDEO_PIPE>".to_string(),
        "-f s16le".to_string(),
        format!(
            "-ar {}",
            manifest.live_runtime.effective_config.audio.sample_rate
        ),
        format!(
            "-ac {}",
            manifest.live_runtime.effective_config.audio.channels
        ),
        "-i <AUDIO_PIPE>".to_string(),
    ];
    if let Some(seconds) = requested_runtime_seconds.filter(|value| *value > 0) {
        parts.push(format!("-t {seconds}"));
    }
    parts.push(format!(
        "# generator_mode={} loop_mode={loop_mode}",
        manifest.live_runtime.generator_mode
    ));
    parts.push(format!(
        "-map 0:v:0 -map 1:a:0 -c:v libx264 -preset {} -pix_fmt yuv420p -c:a aac -b:a {}k -f flv ${{SONGH_RTMP_URL}}",
        manifest.live_runtime.effective_config.outputs.encode.video_preset,
        manifest.live_runtime.effective_config.outputs.encode.audio_bitrate_kbps,
    ));
    if manifest.live_bridge.local_record_enabled {
        parts.push(format!(
            "-map 0:v:0 -map 1:a:0 -c:v libx264 -preset {} -pix_fmt yuv420p -c:a aac -b:a {}k -f flv <LOCAL_RECORD_PATH>",
            manifest.live_runtime.effective_config.outputs.encode.video_preset,
            manifest.live_runtime.effective_config.outputs.encode.audio_bitrate_kbps,
        ));
    }
    parts.join(" ")
}

fn probe_media(
    input_path: &Path,
    probe_output_path: Option<&Path>,
) -> Result<(Option<PathBuf>, Option<PathBuf>, Option<AvProbeSummary>)> {
    let ffprobe_bin = resolve_optional_binary(FFPROBE_BIN_ENV_VAR, "ffprobe");
    let Some(ffprobe_bin) = ffprobe_bin else {
        return Ok((None, None, None));
    };
    let args = vec![
        "-v".to_string(),
        "error".to_string(),
        "-show_entries".to_string(),
        "format=format_name,duration,size:stream=index,codec_type,codec_name,width,height,sample_rate,channels,avg_frame_rate,nb_frames,duration".to_string(),
        "-of".to_string(),
        "json".to_string(),
        input_path.display().to_string(),
    ];
    let output = match Command::new(&ffprobe_bin).args(&args).output() {
        Ok(output) => output,
        Err(error) if error.kind() == ErrorKind::NotFound => return Ok((None, None, None)),
        Err(error) => {
            return Err(anyhow!(error))
                .with_context(|| format!("spawn ffprobe {}", ffprobe_bin.display()))
        }
    };
    if !output.status.success() {
        let stderr = String::from_utf8_lossy(&output.stderr);
        bail!("ffprobe exited with {}: {}", output.status, stderr.trim());
    }
    let path = probe_output_path.map(Path::to_path_buf);
    if let Some(path) = &path {
        fs::write(path, &output.stdout)
            .with_context(|| format!("write ffprobe output {}", path.display()))?;
    }
    let raw: RawProbeOutput = serde_json::from_slice(&output.stdout)?;
    Ok((Some(ffprobe_bin), path, Some(convert_probe(raw)?)))
}

fn validate_smoke_probe(source: &AvRenderReport, probe: &AvProbeSummary) -> Result<()> {
    let video_stream = probe
        .streams
        .iter()
        .find(|stream| stream.codec_type == "video")
        .ok_or_else(|| anyhow!("smoke probe missing video stream"))?;
    let audio_stream = probe
        .streams
        .iter()
        .find(|stream| stream.codec_type == "audio")
        .ok_or_else(|| anyhow!("smoke probe missing audio stream"))?;
    if video_stream.codec_name.as_deref() != Some("h264") {
        bail!("smoke probe video codec must remain h264");
    }
    if audio_stream.codec_name.as_deref() != Some("aac") {
        bail!("smoke probe audio codec must remain aac");
    }
    if video_stream.width != Some(source.video.frame_plan.canvas_width) {
        bail!("smoke probe width mismatch");
    }
    if video_stream.height != Some(source.video.frame_plan.canvas_height) {
        bail!("smoke probe height mismatch");
    }
    if let Some(duration) = probe.duration_seconds {
        if (duration - source.expected_duration_seconds).abs() > DURATION_TOLERANCE_SECS {
            bail!("smoke probe duration drifted beyond tolerance");
        }
    }
    Ok(())
}

fn convert_probe(raw: RawProbeOutput) -> Result<AvProbeSummary> {
    let streams = raw
        .streams
        .into_iter()
        .map(|stream| {
            Ok(crate::av::AvProbeStreamSummary {
                index: stream.index.unwrap_or(0),
                codec_type: stream.codec_type,
                codec_name: stream.codec_name,
                width: stream.width,
                height: stream.height,
                sample_rate: parse_optional_u32(stream.sample_rate.as_deref(), "sample_rate")?,
                channels: stream.channels,
                avg_frame_rate: stream.avg_frame_rate,
                nb_frames: parse_optional_u64(stream.nb_frames.as_deref(), "nb_frames")?,
                duration_seconds: parse_optional_f64(stream.duration.as_deref(), "duration")?,
            })
        })
        .collect::<Result<Vec<_>>>()?;
    Ok(AvProbeSummary {
        format_name: raw
            .format
            .as_ref()
            .and_then(|entry| entry.format_name.clone()),
        duration_seconds: parse_optional_f64(
            raw.format
                .as_ref()
                .and_then(|entry| entry.duration.as_deref()),
            "format.duration",
        )?,
        size_bytes: parse_optional_u64(
            raw.format.as_ref().and_then(|entry| entry.size.as_deref()),
            "format.size",
        )?,
        streams,
    })
}

fn command_output_strings(bin: &Path, args: &[String]) -> Result<CommandOutput> {
    let output = Command::new(bin).args(args).output().map_err(|error| {
        if error.kind() == ErrorKind::NotFound {
            anyhow!("binary not found: {}", bin.display())
        } else {
            anyhow!(error)
        }
    })?;
    Ok(CommandOutput {
        exit_code: output.status.code().unwrap_or(1),
        stdout: String::from_utf8_lossy(&output.stdout).into_owned(),
        stderr: String::from_utf8_lossy(&output.stderr).into_owned(),
    })
}

fn run_command(bin: &Path, args: &[String]) -> Result<()> {
    let output = command_output_strings(bin, &args[1..])?;
    if output.exit_code == 0 {
        return Ok(());
    }
    bail!(
        "{} exited with {}: {}",
        bin.display(),
        output.exit_code,
        output.stderr.trim()
    );
}

#[derive(Debug)]
struct CommandOutput {
    exit_code: i32,
    stdout: String,
    stderr: String,
}

fn redact_text(text: &str, secret: &str) -> String {
    if secret.is_empty() {
        return text.to_string();
    }
    text.replace(secret, "<redacted:SONGH_RTMP_URL>")
}

fn resolve_binary(env_var: &str, default_bin: &str) -> PathBuf {
    match env::var(env_var) {
        Ok(value) if !value.trim().is_empty() => PathBuf::from(value),
        _ => PathBuf::from(default_bin),
    }
}

fn resolve_optional_binary(env_var: &str, default_bin: &str) -> Option<PathBuf> {
    let bin = resolve_binary(env_var, default_bin);
    if bin.as_os_str().is_empty() {
        return None;
    }
    Some(bin)
}

fn sha256_file(path: &Path) -> Result<String> {
    use sha2::{Digest, Sha256};

    let mut digest = Sha256::new();
    let bytes = fs::read(path).with_context(|| format!("read {}", path.display()))?;
    digest.update(bytes);
    Ok(format!("{:x}", digest.finalize()))
}

fn write_json<T: Serialize>(path: &Path, payload: &T) -> Result<()> {
    fs::write(path, serde_json::to_vec_pretty(payload)?)
        .with_context(|| format!("write json {}", path.display()))?;
    Ok(())
}

fn load_json<T: for<'de> Deserialize<'de>>(path: &Path) -> Result<T> {
    let bytes = fs::read(path).with_context(|| format!("read json {}", path.display()))?;
    Ok(serde_json::from_slice(&bytes)?)
}

fn parse_optional_f64(raw: Option<&str>, field_name: &str) -> Result<Option<f64>> {
    raw.map(|value| {
        value
            .parse::<f64>()
            .with_context(|| format!("parse ffprobe {field_name}={value}"))
    })
    .transpose()
}

fn parse_optional_u32(raw: Option<&str>, field_name: &str) -> Result<Option<u32>> {
    raw.map(|value| {
        value
            .parse::<u32>()
            .with_context(|| format!("parse ffprobe {field_name}={value}"))
    })
    .transpose()
}

fn parse_optional_u64(raw: Option<&str>, field_name: &str) -> Result<Option<u64>> {
    raw.map(|value| {
        value
            .parse::<u64>()
            .with_context(|| format!("parse ffprobe {field_name}={value}"))
    })
    .transpose()
}

fn round4(value: f64) -> f64 {
    (value * 10_000.0).round() / 10_000.0
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::archive;
    use crate::test_support;
    use tempfile::tempdir;

    #[cfg(unix)]
    use std::os::unix::fs::PermissionsExt;

    #[derive(Debug)]
    struct EnvVarGuard {
        key: &'static str,
        previous: Option<String>,
    }

    impl EnvVarGuard {
        fn set(key: &'static str, value: impl AsRef<std::ffi::OsStr>) -> Self {
            let previous = env::var(key).ok();
            env::set_var(key, value);
            Self { key, previous }
        }
    }

    impl Drop for EnvVarGuard {
        fn drop(&mut self) {
            match &self.previous {
                Some(value) => env::set_var(self.key, value),
                None => env::remove_var(self.key),
            }
        }
    }

    fn write_executable(path: &Path, body: &str) {
        fs::write(path, body).expect("write script");
        #[cfg(unix)]
        {
            let mut permissions = fs::metadata(path).expect("metadata").permissions();
            permissions.set_mode(0o755);
            fs::set_permissions(path, permissions).expect("chmod");
        }
    }

    #[test]
    fn build_day_pack_writes_stage7_artifacts() {
        let _guard = test_support::env_lock().lock().expect("env lock");
        let temp = tempdir().expect("tempdir");
        let archive_root = temp.path().join("archive");
        let output_dir = temp.path().join("stage7");
        let ffmpeg_bin = temp.path().join("fake-ffmpeg.sh");
        let ffprobe_bin = temp.path().join("fake-ffprobe.sh");
        let ffprobe_fixture = temp.path().join("ffprobe.json.fixture");
        let day = "2026-03-19";

        write_executable(
            &ffmpeg_bin,
            r#"#!/bin/sh
set -eu
last=""
for arg in "$@"; do
  last="$arg"
done
printf 'fake-media' > "$last"
"#,
        );
        write_executable(
            &ffprobe_bin,
            r#"#!/bin/sh
set -eu
cat "$SONGH_TEST_FFPROBE_FIXTURE"
"#,
        );
        fs::write(
            &ffprobe_fixture,
            r#"{
  "format": {
    "format_name": "flv",
    "duration": "8.000000",
    "size": "12345"
  },
  "streams": [
    {
      "index": 0,
      "codec_type": "video",
      "codec_name": "h264",
      "width": 160,
      "height": 90,
      "avg_frame_rate": "4/1",
      "nb_frames": "32",
      "duration": "8.000000"
    },
    {
      "index": 1,
      "codec_type": "audio",
      "codec_name": "aac",
      "sample_rate": "48000",
      "channels": 2,
      "duration": "8.000000"
    }
  ]
}"#,
        )
        .expect("write fixture");

        let _ffmpeg_bin = EnvVarGuard::set(FFMPEG_BIN_ENV_VAR, &ffmpeg_bin);
        let _ffprobe_bin = EnvVarGuard::set(FFPROBE_BIN_ENV_VAR, &ffprobe_bin);
        let _ffprobe_fixture = EnvVarGuard::set("SONGH_TEST_FFPROBE_FIXTURE", &ffprobe_fixture);

        archive::seed_fixture_raw(&archive_root, day, true).expect("seed fixture");
        let mut config = Config::default();
        config.archive.root_dir = archive_root.display().to_string();
        config.video.canvas.width = 160;
        config.video.canvas.height = 90;
        config.video.canvas.fps = 4;
        config.video.text.stroke_width = 1;
        archive::prepare_day_pack(&config, day, Some(&archive_root), true, true).expect("prepare");

        let report = build_day_pack(
            &config,
            day,
            Some(&archive_root),
            &output_dir,
            750,
            8,
            Some(MotionMode::Vertical),
            None,
        )
        .expect("build stage7");

        assert!(report.smoke_flv_path.exists());
        assert!(report.manifest_path.exists());
        assert!(report.wrapper_script_path.exists());
        assert!(report.validation_report_path.exists());
        assert_eq!(report.schema_version, "stage7.stream_bridge.v2");
    }

    #[test]
    fn classify_auth_failure_from_stderr() {
        let taxonomy = default_failure_taxonomy();
        let classified = classify_failure("Server returned 403 Forbidden", 1, &taxonomy);
        assert_eq!(classified.class_id, "auth_failure");
        assert!(!classified.retryable);
    }

    #[test]
    fn live_args_placeholder_uses_fifo_inputs() {
        let manifest = StreamBridgeManifest {
            schema_version: "stage7.stream_bridge.v2".to_string(),
            work_id: "songh-stage7-test".to_string(),
            output_dir: PathBuf::from("/tmp/songh-stage7"),
            source_day: "2026-03-19".to_string(),
            config_label: "songh".to_string(),
            ffmpeg_bin: PathBuf::from("ffmpeg"),
            ffprobe_bin: None,
            video_input: VideoInputContract {
                preview_mp4_path: PathBuf::from("/tmp/offline_preview.mp4"),
                render_manifest_path: PathBuf::from("/tmp/render-manifest.json"),
                sha256: "deadbeef".to_string(),
                expected_fps: 30,
                expected_frame_count: 240,
                expected_duration_seconds: 8.0,
                probe: None,
            },
            smoke_generation: SmokeGenerationContract {
                smoke_flv_path: PathBuf::from("/tmp/stage7_bridge_smoke.flv"),
                smoke_probe_path: None,
                generated: true,
                duration_tolerance_seconds: DURATION_TOLERANCE_SECS,
                probe: None,
            },
            live_runtime: LiveRuntimeContract {
                generator_mode: "tick_live_generator".to_string(),
                effective_config: Config::default(),
                start_second: 750,
                once_duration_seconds: 8,
            },
            live_bridge: LiveBridgeContract {
                stream_url_env_var: RTMP_URL_ENV_VAR.to_string(),
                supported_schemes: vec!["rtmp".to_string(), "rtmps".to_string()],
                default_loop_mode: "infinite".to_string(),
                remote_output_default_enabled: true,
                local_record_enabled: true,
                local_record_path_template: "/tmp/{date}/{label}.flv".to_string(),
                record_label: "songh".to_string(),
                dual_output_supported: true,
            },
            preflight: PreflightContract {
                checks: vec![],
                tcp_connect_timeout_seconds: 3,
                publish_probe_timeout_seconds: 8,
            },
            runtime_executor: RuntimeExecutorContract {
                max_attempts: 1,
                backoff_seconds: vec![],
                retryable_class_ids: vec![],
            },
            runtime_observability: RuntimeObservabilityContract {
                log_dir: LOG_DIR_NAME.to_string(),
                preflight_report_file: PREFLIGHT_REPORT_FILE.to_string(),
                preflight_log_file: PREFLIGHT_LOG_FILE.to_string(),
                runtime_report_file: RUNTIME_REPORT_FILE.to_string(),
                exit_report_file: EXIT_REPORT_FILE.to_string(),
                latest_stderr_log_file: LATEST_LOG_FILE.to_string(),
                attempt_log_pattern: "a".to_string(),
                attempt_report_pattern: "b".to_string(),
            },
            failure_taxonomy_file: FAILURE_TAXONOMY_FILE.to_string(),
            ffmpeg_args_file: FFMPEG_ARGS_FILE.to_string(),
            validation_report_file: VALIDATION_REPORT_FILE.to_string(),
            wrapper_script_file: WRAPPER_SCRIPT_FILE.to_string(),
        };

        let args = live_args_with_placeholders(&manifest, "once");
        assert!(args.iter().any(|arg| arg == "rawvideo"));
        assert!(args.iter().any(|arg| arg == "<VIDEO_PIPE>"));
        assert!(args.iter().any(|arg| arg == "<AUDIO_PIPE>"));
    }

    #[test]
    fn sanitize_target_rtmps_no_port_defaults_to_443() {
        let target =
            sanitize_target("rtmps://a.rtmps.youtube.com/live2/xxxx-xxxx").expect("parse");
        assert_eq!(target.scheme, "rtmps");
        assert_eq!(target.host, "a.rtmps.youtube.com");
        assert_eq!(target.port, 443);
    }

    #[test]
    fn sanitize_target_rtmp_no_port_defaults_to_1935() {
        let target =
            sanitize_target("rtmp://live-push.bilivideo.com/live/xxxx").expect("parse");
        assert_eq!(target.scheme, "rtmp");
        assert_eq!(target.host, "live-push.bilivideo.com");
        assert_eq!(target.port, 1935);
    }

    #[test]
    fn sanitize_target_explicit_port_not_overridden() {
        let target =
            sanitize_target("rtmps://ingest.example.com:8443/live/key").expect("parse");
        assert_eq!(target.scheme, "rtmps");
        assert_eq!(target.port, 8443);
    }

    #[test]
    fn sanitize_target_unknown_scheme_missing_port_errors() {
        let err = sanitize_target("custom://host.example.com/path").unwrap_err();
        assert!(err.to_string().contains("missing port"));
    }
}
