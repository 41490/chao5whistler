use std::env;
use std::fs;
use std::io::{ErrorKind, Read};
use std::net::{SocketAddr, TcpStream, ToSocketAddrs};
use std::path::{Path, PathBuf};
use std::process::{Command, Stdio};
use std::thread;
use std::time::{Duration, Instant};

use anyhow::{anyhow, bail, Context, Result};
use chrono::{SecondsFormat, Utc};
use serde_json::{json, Value};
use url::Url;

fn main() {
    if let Err(error) = run_cli(env::args().skip(1).collect()) {
        eprintln!("{error:#}");
        std::process::exit(1);
    }
}

#[derive(Debug)]
struct CliArgs {
    artifact_dir: PathBuf,
    stream_url_env: String,
    loop_mode: String,
    max_runtime_seconds: Option<f64>,
}

#[derive(Debug)]
struct ProcessOutput {
    exit_code: i32,
    stderr: String,
    timed_out: bool,
}

fn run_cli(args: Vec<String>) -> Result<()> {
    let cli = parse_args(&args)?;
    let exit_code = run_runtime(&cli)?;
    std::process::exit(exit_code);
}

fn parse_args(args: &[String]) -> Result<CliArgs> {
    let mut artifact_dir = None;
    let mut stream_url_env = None;
    let mut loop_mode = String::from("infinite");
    let mut max_runtime_seconds = None;
    let mut index = 0;

    while index < args.len() {
        match args[index].as_str() {
            "--artifact-dir" => {
                let value = args
                    .get(index + 1)
                    .ok_or_else(|| anyhow!("--artifact-dir requires a value"))?;
                artifact_dir = Some(PathBuf::from(value));
                index += 2;
            }
            "--stream-url-env" => {
                let value = args
                    .get(index + 1)
                    .ok_or_else(|| anyhow!("--stream-url-env requires a value"))?;
                stream_url_env = Some(value.clone());
                index += 2;
            }
            "--loop-mode" => {
                let value = args
                    .get(index + 1)
                    .ok_or_else(|| anyhow!("--loop-mode requires a value"))?;
                loop_mode = value.clone();
                index += 2;
            }
            "--max-runtime-seconds" => {
                let value = args
                    .get(index + 1)
                    .ok_or_else(|| anyhow!("--max-runtime-seconds requires a value"))?;
                max_runtime_seconds = parse_max_runtime(value)?;
                index += 2;
            }
            other => bail!("unknown flag: {other}"),
        }
    }

    Ok(CliArgs {
        artifact_dir: artifact_dir.ok_or_else(|| anyhow!("missing --artifact-dir"))?,
        stream_url_env: stream_url_env.ok_or_else(|| anyhow!("missing --stream-url-env"))?,
        loop_mode,
        max_runtime_seconds,
    })
}

fn parse_max_runtime(value: &str) -> Result<Option<f64>> {
    if value.is_empty() || value == "0" {
        return Ok(None);
    }
    let parsed = value
        .parse::<f64>()
        .with_context(|| format!("invalid --max-runtime-seconds: {value}"))?;
    if parsed <= 0.0 {
        bail!("--max-runtime-seconds must be > 0 when provided");
    }
    Ok(Some(parsed))
}

fn load_json(path: &Path) -> Result<Value> {
    let raw =
        fs::read_to_string(path).with_context(|| format!("read json file {}", path.display()))?;
    serde_json::from_str(&raw).with_context(|| format!("parse json file {}", path.display()))
}

fn write_json(path: &Path, payload: &Value) -> Result<()> {
    let serialized = serde_json::to_string_pretty(payload)?;
    fs::write(path, format!("{serialized}\n"))
        .with_context(|| format!("write json file {}", path.display()))
}

fn utc_now() -> String {
    Utc::now().to_rfc3339_opts(SecondsFormat::Secs, true)
}

fn round6(value: f64) -> f64 {
    (value * 1_000_000.0).round() / 1_000_000.0
}

fn elapsed_seconds(start: Instant) -> f64 {
    round6(start.elapsed().as_secs_f64())
}

fn sanitize_target(target_url: &str) -> Result<Value> {
    let parsed = Url::parse(target_url).with_context(|| "invalid stream url".to_string())?;
    let scheme = parsed.scheme().to_string();
    let host = parsed
        .host_str()
        .ok_or_else(|| anyhow!("stream url is missing a hostname"))?
        .to_string();
    let default_port = if scheme == "rtmps" { 443 } else { 1935 };
    Ok(json!({
        "scheme": scheme,
        "host": host,
        "port": parsed.port().unwrap_or(default_port),
        "path_redacted": true,
    }))
}

fn build_attempt_file_name(pattern: &str, attempt_index: usize) -> String {
    pattern.replace("{attempt:03d}", &format!("{attempt_index:03}"))
}

fn copy_file(source: &Path, destination: &Path) -> Result<()> {
    let content = fs::read_to_string(source)
        .with_context(|| format!("read log file {}", source.display()))?;
    fs::write(destination, content)
        .with_context(|| format!("write log file {}", destination.display()))
}

fn redact_text(raw_text: &str, env_vars: &[String]) -> (String, Vec<String>) {
    let mut redacted = raw_text.to_string();
    let mut applied = Vec::new();
    for env_var in env_vars {
        let value = env::var(env_var).unwrap_or_default();
        if !value.is_empty() && redacted.contains(&value) {
            redacted = redacted.replace(&value, &format!("<redacted:{env_var}>"));
            applied.push(env_var.clone());
        }
    }
    applied.sort();
    applied.dedup();
    (redacted, applied)
}

fn classify_exit(raw_text: &str, exit_code: i32, taxonomy: &Value) -> Result<(Value, Vec<String>)> {
    let lowered = raw_text.to_lowercase();
    let classes = taxonomy
        .get("classes")
        .and_then(Value::as_array)
        .ok_or_else(|| anyhow!("failure taxonomy is missing classes"))?;

    for entry in classes {
        let codes = entry
            .get("match_exit_codes")
            .and_then(Value::as_array)
            .into_iter()
            .flatten();
        for matched_code in codes {
            if matched_code.as_i64() == Some(i64::from(exit_code)) {
                return Ok((entry.clone(), Vec::new()));
            }
        }
    }

    for entry in classes {
        let matches = entry
            .get("match_any")
            .and_then(Value::as_array)
            .into_iter()
            .flatten()
            .filter_map(Value::as_str)
            .filter(|token| lowered.contains(&token.to_lowercase()))
            .map(str::to_string)
            .collect::<Vec<_>>();
        if !matches.is_empty() {
            return Ok((entry.clone(), matches));
        }
    }

    let default_class_id = taxonomy
        .get("default_class_id")
        .and_then(Value::as_str)
        .ok_or_else(|| anyhow!("failure taxonomy is missing default_class_id"))?;
    let default_entry = classes
        .iter()
        .find(|entry| entry.get("class_id").and_then(Value::as_str) == Some(default_class_id))
        .cloned()
        .ok_or_else(|| anyhow!("failure taxonomy default_class_id is missing from classes"))?;
    Ok((default_entry, Vec::new()))
}

fn classify_status(class_id: &str, retryable: bool) -> &'static str {
    match class_id {
        "clean_exit" => "clean_exit",
        "runtime_limit_reached" => "runtime_limit_reached",
        "interrupted" => "interrupted",
        _ if retryable => "retryable_failure",
        _ => "terminal_failure",
    }
}

fn build_runtime_report_payload(
    raw_text: &str,
    exit_code: i32,
    taxonomy: &Value,
    loop_mode: &str,
    max_runtime_seconds: f64,
    command_shell: &str,
    redact_env_vars: &[String],
    stage: &str,
    extra_fields: Value,
) -> Result<(String, Value)> {
    let (redacted_text, mut applied_redactions) = redact_text(raw_text, redact_env_vars);
    let (redacted_command_shell, command_redactions) = redact_text(command_shell, redact_env_vars);
    applied_redactions.extend(command_redactions);
    applied_redactions.sort();
    applied_redactions.dedup();

    let (matched_class, matched_tokens) = classify_exit(raw_text, exit_code, taxonomy)?;
    let class_id = matched_class
        .get("class_id")
        .and_then(Value::as_str)
        .unwrap_or("unknown_failure");
    let retryable = matched_class
        .get("retryable")
        .and_then(Value::as_bool)
        .unwrap_or(false);

    let mut report = json!({
        "stage": stage,
        "status": classify_status(class_id, retryable),
        "exit_code": exit_code,
        "exit_class_id": class_id,
        "retryable": retryable,
        "matched_tokens": matched_tokens,
        "loop_mode": loop_mode,
        "max_runtime_seconds": max_runtime_seconds,
        "command_shell": redacted_command_shell,
        "taxonomy_id": taxonomy.get("taxonomy_id").cloned().unwrap_or(Value::Null),
        "log_line_count": redacted_text.lines().count(),
        "redacted_env_vars_requested": redact_env_vars,
        "redacted_env_vars_applied": applied_redactions,
    });
    if let Some(report_object) = report.as_object_mut() {
        if let Some(extra_object) = extra_fields.as_object() {
            for (key, value) in extra_object {
                report_object.insert(key.clone(), value.clone());
            }
        }
    }
    Ok((redacted_text, report))
}

fn write_report_and_log(
    raw_text: &str,
    exit_code: i32,
    taxonomy: &Value,
    loop_mode: &str,
    max_runtime_seconds: f64,
    command_shell: &str,
    redact_env_vars: &[String],
    output_log: &Path,
    output_report: &Path,
    stage: &str,
    extra_fields: Value,
) -> Result<Value> {
    let (redacted_text, report) = build_runtime_report_payload(
        raw_text,
        exit_code,
        taxonomy,
        loop_mode,
        max_runtime_seconds,
        command_shell,
        redact_env_vars,
        stage,
        extra_fields,
    )?;
    if let Some(parent) = output_log.parent() {
        fs::create_dir_all(parent)
            .with_context(|| format!("create log dir {}", parent.display()))?;
    }
    if let Some(parent) = output_report.parent() {
        fs::create_dir_all(parent)
            .with_context(|| format!("create report dir {}", parent.display()))?;
    }
    fs::write(output_log, redacted_text)
        .with_context(|| format!("write log file {}", output_log.display()))?;
    write_json(output_report, &report)?;
    Ok(report)
}

fn run_command(args: &[String], timeout_seconds: Option<f64>) -> Result<ProcessOutput> {
    let mut command = Command::new(
        args.first()
            .ok_or_else(|| anyhow!("cannot run an empty command"))?,
    );
    command.args(&args[1..]);
    command.stdout(Stdio::null());
    command.stderr(Stdio::piped());
    let mut child = command.spawn().with_context(|| format!("spawn {}", args[0]))?;
    let start = Instant::now();
    let mut timed_out = false;

    loop {
        if let Some(status) = child.try_wait().with_context(|| format!("wait for {}", args[0]))? {
            let mut stderr = String::new();
            if let Some(mut handle) = child.stderr.take() {
                handle.read_to_string(&mut stderr)?;
            }
            return Ok(ProcessOutput {
                exit_code: status.code().unwrap_or(1),
                stderr,
                timed_out,
            });
        }
        if let Some(limit) = timeout_seconds {
            if start.elapsed().as_secs_f64() >= limit {
                timed_out = true;
                let _ = child.kill();
                let status = child.wait()?;
                let mut stderr = String::new();
                if let Some(mut handle) = child.stderr.take() {
                    handle.read_to_string(&mut stderr)?;
                }
                return Ok(ProcessOutput {
                    exit_code: status.code().unwrap_or(124),
                    stderr,
                    timed_out,
                });
            }
        }
        thread::sleep(Duration::from_millis(100));
    }
}

fn resolve_protocol_support(ffmpeg_bin: &str, protocol: &str) -> Result<(bool, String)> {
    let output = Command::new(ffmpeg_bin)
        .arg("-protocols")
        .output()
        .with_context(|| format!("run {ffmpeg_bin} -protocols"))?;
    let stdout = String::from_utf8_lossy(&output.stdout);
    let stderr = String::from_utf8_lossy(&output.stderr);
    let combined = if stdout.is_empty() {
        stderr.to_string()
    } else if stderr.is_empty() {
        stdout.to_string()
    } else {
        format!("{stdout}\n{stderr}")
    };
    let supported = output.status.success()
        && combined.lines().any(|line| line.trim().eq_ignore_ascii_case(protocol));
    Ok((supported, combined.trim().to_string()))
}

fn resolve_dns(host: &str, port: u16) -> Result<Vec<String>> {
    let addrs = (host, port)
        .to_socket_addrs()
        .with_context(|| format!("resolve {host}:{port}"))?;
    let mut values = addrs.map(|addr| addr.ip().to_string()).collect::<Vec<_>>();
    values.sort();
    values.dedup();
    Ok(values)
}

fn probe_tcp_connectivity(host: &str, port: u16, timeout_seconds: f64) -> Result<()> {
    let timeout = Duration::from_secs_f64(timeout_seconds);
    let addrs = (host, port)
        .to_socket_addrs()
        .with_context(|| format!("resolve tcp target {host}:{port}"))?
        .collect::<Vec<SocketAddr>>();
    let mut last_error = None;
    for addr in addrs {
        match TcpStream::connect_timeout(&addr, timeout) {
            Ok(_) => return Ok(()),
            Err(error) => last_error = Some(error),
        }
    }
    let error = last_error
        .unwrap_or_else(|| std::io::Error::new(ErrorKind::Other, "no socket addresses resolved"));
    Err(anyhow!(error).context(format!("unable to reach {host}:{port}")))
}

fn build_publish_probe_args(ffmpeg_bin: &str, target_url: &str) -> Vec<String> {
    vec![
        ffmpeg_bin.to_string(),
        "-hide_banner".to_string(),
        "-nostats".to_string(),
        "-f".to_string(),
        "lavfi".to_string(),
        "-i".to_string(),
        "testsrc=size=16x16:rate=1".to_string(),
        "-f".to_string(),
        "lavfi".to_string(),
        "-i".to_string(),
        "anullsrc=r=44100:cl=stereo".to_string(),
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
        "-pix_fmt".to_string(),
        "yuv420p".to_string(),
        "-r".to_string(),
        "1".to_string(),
        "-g".to_string(),
        "1".to_string(),
        "-keyint_min".to_string(),
        "1".to_string(),
        "-sc_threshold".to_string(),
        "0".to_string(),
        "-b:v".to_string(),
        "150k".to_string(),
        "-maxrate".to_string(),
        "150k".to_string(),
        "-bufsize".to_string(),
        "150k".to_string(),
        "-vf".to_string(),
        "scale=16:16:flags=fast_bilinear,setsar=1".to_string(),
        "-c:a".to_string(),
        "aac".to_string(),
        "-b:a".to_string(),
        "64k".to_string(),
        "-ar".to_string(),
        "44100".to_string(),
        "-ac".to_string(),
        "2".to_string(),
        "-f".to_string(),
        "flv".to_string(),
        target_url.to_string(),
    ]
}

fn shell_escape(value: &str) -> String {
    if !value.is_empty()
        && value
            .bytes()
            .all(|byte| byte.is_ascii_alphanumeric() || b"-_./:=@${}".contains(&byte))
    {
        value.to_string()
    } else {
        format!("'{}'", value.replace('\'', "'\"'\"'"))
    }
}

fn shell_join(values: &[String]) -> String {
    values
        .iter()
        .map(|value| shell_escape(value))
        .collect::<Vec<_>>()
        .join(" ")
}

fn iso_elapsed_seconds(started_at: &str, finished_at: &str) -> Result<f64> {
    let started = chrono::DateTime::parse_from_rfc3339(started_at)
        .with_context(|| format!("parse timestamp {started_at}"))?;
    let finished = chrono::DateTime::parse_from_rfc3339(finished_at)
        .with_context(|| format!("parse timestamp {finished_at}"))?;
    Ok(round6(
        (finished.timestamp_millis() - started.timestamp_millis()) as f64 / 1000.0,
    ))
}

fn emit_console_summary(
    message: &str,
    preflight_report_path: &Path,
    preflight_log_path: &Path,
    runtime_report_path: &Path,
    exit_report_path: &Path,
    latest_log_path: &Path,
) {
    eprintln!("stage7 summary: {message}");
    eprintln!("preflight_report: {}", preflight_report_path.display());
    eprintln!("preflight_log: {}", preflight_log_path.display());
    eprintln!("runtime_report: {}", runtime_report_path.display());
    eprintln!("latest_exit_report: {}", exit_report_path.display());
    eprintln!("latest_stderr_log: {}", latest_log_path.display());
}

fn emit_preflight_failure_summary(
    failed_check_id: &str,
    message: &str,
    preflight_report_path: &Path,
    preflight_log_path: &Path,
    runtime_report_path: &Path,
    exit_report_path: &Path,
    latest_log_path: &Path,
) {
    eprintln!(
        "preflight failed: {failed_check_id}; see {} and {}",
        preflight_report_path.display(),
        preflight_log_path.display()
    );
    emit_console_summary(
        message,
        preflight_report_path,
        preflight_log_path,
        runtime_report_path,
        exit_report_path,
        latest_log_path,
    );
}

fn required_string<'a>(payload: &'a Value, key: &str) -> Result<&'a str> {
    payload
        .get(key)
        .and_then(Value::as_str)
        .ok_or_else(|| anyhow!("missing string field: {key}"))
}

fn run_runtime(cli: &CliArgs) -> Result<i32> {
    let artifact_dir = cli
        .artifact_dir
        .canonicalize()
        .unwrap_or_else(|_| cli.artifact_dir.clone());
    let manifest = load_json(&artifact_dir.join("stream_bridge_manifest.json"))?;
    let args_payload = load_json(&artifact_dir.join("stream_bridge_ffmpeg_args.json"))?;
    let taxonomy = load_json(&artifact_dir.join("stage7_failure_taxonomy.json"))?;
    let soak_plan = load_json(&artifact_dir.join("stage7_soak_plan.json"))?;
    let profile = load_json(&artifact_dir.join("stage7_bridge_profile.json"))?;

    let url_env_var = required_string(&args_payload, "url_env_var")?;
    if cli.stream_url_env != url_env_var {
        bail!(
            "stream url env mismatch: script requested {}, artifact expects {}",
            cli.stream_url_env,
            url_env_var
        );
    }
    let target_url = env::var(url_env_var).unwrap_or_default();
    if target_url.is_empty() {
        bail!("missing {url_env_var}: export {url_env_var}=...");
    }

    let runtime_args_by_mode = args_payload
        .get("live_runtime_argv_without_target_by_mode")
        .and_then(Value::as_object)
        .ok_or_else(|| anyhow!("stream_bridge_ffmpeg_args.json missing live runtime argv"))?;
    let runtime_args = runtime_args_by_mode
        .get(&cli.loop_mode)
        .and_then(Value::as_array)
        .ok_or_else(|| anyhow!("unsupported loop mode: {}", cli.loop_mode))?
        .iter()
        .map(|value| {
            value
                .as_str()
                .map(str::to_string)
                .ok_or_else(|| anyhow!("non-string runtime arg"))
        })
        .collect::<Result<Vec<_>>>()?;

    let runtime_observability = manifest
        .get("runtime_observability")
        .cloned()
        .ok_or_else(|| anyhow!("manifest missing runtime_observability"))?;
    let preflight_contract = manifest
        .get("preflight")
        .cloned()
        .ok_or_else(|| anyhow!("manifest missing preflight"))?;
    let runtime_executor = manifest
        .get("runtime_executor")
        .cloned()
        .ok_or_else(|| anyhow!("manifest missing runtime_executor"))?;
    let log_dir = artifact_dir.join(required_string(&runtime_observability, "log_dir")?);
    fs::create_dir_all(&log_dir).with_context(|| format!("create log dir {}", log_dir.display()))?;

    let latest_log_path = log_dir.join(required_string(&runtime_observability, "stderr_log_file")?);
    let exit_report_path = log_dir.join(required_string(&runtime_observability, "exit_report_file")?);
    let preflight_log_path = log_dir.join(required_string(&runtime_observability, "preflight_log_file")?);
    let preflight_report_path = log_dir.join(required_string(&runtime_observability, "preflight_report_file")?);
    let runtime_report_path = log_dir.join(required_string(&runtime_observability, "runtime_report_file")?);
    let attempt_log_pattern = required_string(&runtime_observability, "attempt_log_pattern")?;
    let attempt_report_pattern = required_string(&runtime_observability, "attempt_report_pattern")?;
    let redact_env_vars = runtime_observability
        .get("redact_env_vars")
        .and_then(Value::as_array)
        .map(|values| {
            values
                .iter()
                .filter_map(Value::as_str)
                .map(str::to_string)
                .collect::<Vec<_>>()
        })
        .filter(|values| !values.is_empty())
        .unwrap_or_else(|| vec![url_env_var.to_string()]);

    let ffmpeg_bin = required_string(&args_payload, "runtime_ffmpeg_bin")?;
    let protocol = profile
        .get("ingest")
        .and_then(|value| value.get("protocol"))
        .and_then(Value::as_str)
        .ok_or_else(|| anyhow!("profile missing ingest.protocol"))?;
    let target = sanitize_target(&target_url)?;
    let parsed_target = Url::parse(&target_url).with_context(|| "invalid target url".to_string())?;
    let expected_port = target
        .get("port")
        .and_then(Value::as_u64)
        .ok_or_else(|| anyhow!("target is missing port"))? as u16;

    if parsed_target.scheme() != protocol {
        let preflight_report = write_report_and_log(
            &format!(
                "protocol not found: expected {protocol}:// but received {}://",
                parsed_target.scheme()
            ),
            1,
            &taxonomy,
            &cli.loop_mode,
            cli.max_runtime_seconds.unwrap_or(0.0),
            &format!("<env:{url_env_var}>"),
            &redact_env_vars,
            &preflight_log_path,
            &preflight_report_path,
            "stage7_stream_bridge_preflight",
            json!({
                "status": "preflight_failed",
                "failed_check_id": "target_scheme",
                "target": target,
                "checks": [],
            }),
        )?;
        write_json(
            &runtime_report_path,
            &json!({
                "stage": "stage7_stream_bridge_runtime",
                "status": "preflight_failed",
                "loop_mode": cli.loop_mode,
                "max_runtime_seconds": cli.max_runtime_seconds.unwrap_or(0.0),
                "preflight_report_file": preflight_report_path.display().to_string(),
                "target": target,
                "attempts_total": 0,
                "attempts": [],
                "final_exit_class_id": preflight_report.get("exit_class_id").cloned().unwrap_or(Value::Null),
                "final_exit_code": preflight_report.get("exit_code").cloned().unwrap_or(json!(1)),
                "retry_policy": runtime_executor,
            }),
        )?;
        copy_file(&preflight_log_path, &latest_log_path)?;
        write_json(&exit_report_path, &preflight_report)?;
        emit_preflight_failure_summary(
            "target_scheme",
            &format!(
                "preflight failed at target_scheme; expected {protocol}://; received {}://",
                parsed_target.scheme()
            ),
            &preflight_report_path,
            &preflight_log_path,
            &runtime_report_path,
            &exit_report_path,
            &latest_log_path,
        );
        return Ok(1);
    }

    let start_monotonic = Instant::now();
    let started_at = utc_now();
    let mut preflight_checks = Vec::new();
    let preflight_command_shell = format!("ffmpeg-preflight {url_env_var}=${{{url_env_var}}}");

    let (supported, protocol_output) = resolve_protocol_support(ffmpeg_bin, protocol)?;
    preflight_checks.push(json!({
        "check_id": "protocol_support",
        "status": if supported { "passed" } else { "failed" },
        "details": {
            "ffmpeg_bin": ffmpeg_bin,
            "protocol": protocol,
        }
    }));
    if !supported {
        let preflight_report = write_report_and_log(
            &format!("protocol not found: required {protocol} output support missing\n{protocol_output}"),
            1,
            &taxonomy,
            &cli.loop_mode,
            cli.max_runtime_seconds.unwrap_or(0.0),
            &preflight_command_shell,
            &redact_env_vars,
            &preflight_log_path,
            &preflight_report_path,
            "stage7_stream_bridge_preflight",
            json!({
                "status": "preflight_failed",
                "failed_check_id": "protocol_support",
                "target": target,
                "checks": preflight_checks,
            }),
        )?;
        copy_file(&preflight_log_path, &latest_log_path)?;
        write_json(&exit_report_path, &preflight_report)?;
        write_json(
            &runtime_report_path,
            &json!({
                "stage": "stage7_stream_bridge_runtime",
                "status": "preflight_failed",
                "started_at": started_at,
                "finished_at": utc_now(),
                "elapsed_seconds": elapsed_seconds(start_monotonic),
                "loop_mode": cli.loop_mode,
                "max_runtime_seconds": cli.max_runtime_seconds.unwrap_or(0.0),
                "preflight_report_file": preflight_report_path.display().to_string(),
                "target": target,
                "attempts_total": 0,
                "attempts": [],
                "final_exit_class_id": preflight_report.get("exit_class_id").cloned().unwrap_or(Value::Null),
                "final_exit_code": preflight_report.get("exit_code").cloned().unwrap_or(json!(1)),
                "retry_policy": runtime_executor,
            }),
        )?;
        emit_preflight_failure_summary(
            "protocol_support",
            "preflight failed at protocol_support; ffmpeg is missing required RTMPS output support",
            &preflight_report_path,
            &preflight_log_path,
            &runtime_report_path,
            &exit_report_path,
            &latest_log_path,
        );
        return Ok(1);
    }

    let host = parsed_target
        .host_str()
        .ok_or_else(|| anyhow!("{url_env_var} must include a hostname"))?;
    let resolved_addresses = match resolve_dns(host, expected_port) {
        Ok(values) => values,
        Err(error) => {
            let error_text = error.to_string();
            preflight_checks.push(json!({
                "check_id": "dns_resolution",
                "status": "failed",
                "details": {
                    "host": host,
                    "port": expected_port,
                    "resolved_addresses": [],
                    "error": error_text,
                }
            }));
            let preflight_report = write_report_and_log(
                &format!("temporary failure in name resolution: {error_text}"),
                1,
                &taxonomy,
                &cli.loop_mode,
                cli.max_runtime_seconds.unwrap_or(0.0),
                &preflight_command_shell,
                &redact_env_vars,
                &preflight_log_path,
                &preflight_report_path,
                "stage7_stream_bridge_preflight",
                json!({
                    "status": "preflight_failed",
                    "failed_check_id": "dns_resolution",
                    "target": target,
                    "checks": preflight_checks,
                }),
            )?;
            copy_file(&preflight_log_path, &latest_log_path)?;
            write_json(&exit_report_path, &preflight_report)?;
            write_json(
                &runtime_report_path,
                &json!({
                    "stage": "stage7_stream_bridge_runtime",
                    "status": "preflight_failed",
                    "started_at": started_at,
                    "finished_at": utc_now(),
                    "elapsed_seconds": elapsed_seconds(start_monotonic),
                    "loop_mode": cli.loop_mode,
                    "max_runtime_seconds": cli.max_runtime_seconds.unwrap_or(0.0),
                    "preflight_report_file": preflight_report_path.display().to_string(),
                    "target": target,
                    "attempts_total": 0,
                    "attempts": [],
                    "final_exit_class_id": preflight_report.get("exit_class_id").cloned().unwrap_or(Value::Null),
                    "final_exit_code": preflight_report.get("exit_code").cloned().unwrap_or(json!(1)),
                    "retry_policy": runtime_executor,
                }),
            )?;
            emit_preflight_failure_summary(
                "dns_resolution",
                &format!("preflight failed at dns_resolution; unable to resolve host {host}"),
                &preflight_report_path,
                &preflight_log_path,
                &runtime_report_path,
                &exit_report_path,
                &latest_log_path,
            );
            return Ok(1);
        }
    };
    preflight_checks.push(json!({
        "check_id": "dns_resolution",
        "status": "passed",
        "details": {
            "host": host,
            "port": expected_port,
            "resolved_addresses": resolved_addresses.iter().take(4).cloned().collect::<Vec<_>>(),
            "error": Value::Null,
        }
    }));

    let tcp_timeout = preflight_contract
        .get("tcp_connect_timeout_seconds")
        .and_then(Value::as_f64)
        .ok_or_else(|| anyhow!("preflight missing tcp_connect_timeout_seconds"))?;
    if let Err(error) = probe_tcp_connectivity(host, expected_port, tcp_timeout) {
        let error_text = error.to_string();
        preflight_checks.push(json!({
            "check_id": "tcp_connectivity",
            "status": "failed",
            "details": {
                "host": host,
                "port": expected_port,
                "timeout_seconds": tcp_timeout,
                "error": error_text,
            }
        }));
        let preflight_report = write_report_and_log(
            &format!("connection refused: unable to reach {host}:{expected_port}: {error_text}"),
            1,
            &taxonomy,
            &cli.loop_mode,
            cli.max_runtime_seconds.unwrap_or(0.0),
            &preflight_command_shell,
            &redact_env_vars,
            &preflight_log_path,
            &preflight_report_path,
            "stage7_stream_bridge_preflight",
            json!({
                "status": "preflight_failed",
                "failed_check_id": "tcp_connectivity",
                "target": target,
                "checks": preflight_checks,
            }),
        )?;
        copy_file(&preflight_log_path, &latest_log_path)?;
        write_json(&exit_report_path, &preflight_report)?;
        write_json(
            &runtime_report_path,
            &json!({
                "stage": "stage7_stream_bridge_runtime",
                "status": "preflight_failed",
                "started_at": started_at,
                "finished_at": utc_now(),
                "elapsed_seconds": elapsed_seconds(start_monotonic),
                "loop_mode": cli.loop_mode,
                "max_runtime_seconds": cli.max_runtime_seconds.unwrap_or(0.0),
                "preflight_report_file": preflight_report_path.display().to_string(),
                "target": target,
                "attempts_total": 0,
                "attempts": [],
                "final_exit_class_id": preflight_report.get("exit_class_id").cloned().unwrap_or(Value::Null),
                "final_exit_code": preflight_report.get("exit_code").cloned().unwrap_or(json!(1)),
                "retry_policy": runtime_executor,
            }),
        )?;
        emit_preflight_failure_summary(
            "tcp_connectivity",
            &format!("preflight failed at tcp_connectivity; unable to reach {host}:{expected_port}"),
            &preflight_report_path,
            &preflight_log_path,
            &runtime_report_path,
            &exit_report_path,
            &latest_log_path,
        );
        return Ok(1);
    }
    preflight_checks.push(json!({
        "check_id": "tcp_connectivity",
        "status": "passed",
        "details": {
            "host": host,
            "port": expected_port,
            "timeout_seconds": tcp_timeout,
            "error": Value::Null,
        }
    }));

    let publish_probe_args = build_publish_probe_args(ffmpeg_bin, &target_url);
    let publish_probe_redacted_shell =
        shell_join(&build_publish_probe_args(ffmpeg_bin, &format!("${{{url_env_var}}}")));
    let probe_timeout = preflight_contract
        .get("publish_probe_timeout_seconds")
        .and_then(Value::as_f64)
        .ok_or_else(|| anyhow!("preflight missing publish_probe_timeout_seconds"))?;
    let probe_output = run_command(&publish_probe_args, Some(probe_timeout))?;
    let mut probe_checks = preflight_checks.clone();
    probe_checks.push(json!({
        "check_id": "publish_probe",
        "status": if probe_output.exit_code == 0 && !probe_output.timed_out { "passed" } else { "failed" },
        "details": {
            "probe_timeout_seconds": probe_timeout,
            "exit_code": if probe_output.timed_out { 124 } else { probe_output.exit_code },
        }
    }));
    let probe_report = write_report_and_log(
        &probe_output.stderr,
        if probe_output.timed_out { 124 } else { probe_output.exit_code },
        &taxonomy,
        &cli.loop_mode,
        cli.max_runtime_seconds.unwrap_or(0.0),
        &publish_probe_redacted_shell,
        &redact_env_vars,
        &preflight_log_path,
        &preflight_report_path,
        "stage7_stream_bridge_preflight",
        json!({
            "status": if probe_output.exit_code == 0 && !probe_output.timed_out { "preflight_passed" } else { "preflight_failed" },
            "failed_check_id": if probe_output.exit_code == 0 && !probe_output.timed_out { Value::Null } else { json!("publish_probe") },
            "target": target,
            "checks": probe_checks,
            "probe_mode": preflight_contract.get("publish_probe_mode").cloned().unwrap_or(Value::Null),
        }),
    )?;
    copy_file(&preflight_log_path, &latest_log_path)?;
    write_json(&exit_report_path, &probe_report)?;
    if probe_output.exit_code != 0 || probe_output.timed_out {
        write_json(
            &runtime_report_path,
            &json!({
                "stage": "stage7_stream_bridge_runtime",
                "status": "preflight_failed",
                "started_at": started_at,
                "finished_at": utc_now(),
                "elapsed_seconds": elapsed_seconds(start_monotonic),
                "loop_mode": cli.loop_mode,
                "max_runtime_seconds": cli.max_runtime_seconds.unwrap_or(0.0),
                "preflight_report_file": preflight_report_path.display().to_string(),
                "target": target,
                "attempts_total": 0,
                "attempts": [],
                "final_exit_class_id": probe_report.get("exit_class_id").cloned().unwrap_or(Value::Null),
                "final_exit_code": probe_report.get("exit_code").cloned().unwrap_or(json!(1)),
                "retry_policy": runtime_executor,
            }),
        )?;
        emit_preflight_failure_summary(
            "publish_probe",
            &format!(
                "preflight failed at publish_probe; exit_class_id={}; exit_code={}",
                probe_report
                    .get("exit_class_id")
                    .and_then(Value::as_str)
                    .unwrap_or("unknown_failure"),
                probe_report.get("exit_code").and_then(Value::as_i64).unwrap_or(1),
            ),
            &preflight_report_path,
            &preflight_log_path,
            &runtime_report_path,
            &exit_report_path,
            &latest_log_path,
        );
        return Ok(if probe_output.timed_out {
            124
        } else {
            probe_output.exit_code.max(1)
        });
    }

    let mut attempts = Vec::new();
    let mut consecutive_retryable_failures = 0_usize;
    let backoff_seconds = soak_plan
        .get("reconnect_policy")
        .and_then(|value| value.get("backoff_seconds"))
        .and_then(Value::as_array)
        .ok_or_else(|| anyhow!("soak plan missing reconnect backoff"))?
        .iter()
        .map(|value| {
            value
                .as_u64()
                .ok_or_else(|| anyhow!("invalid backoff second"))
        })
        .collect::<Result<Vec<_>>>()?;
    let max_consecutive_retryable_failures = soak_plan
        .get("reconnect_policy")
        .and_then(|value| value.get("max_consecutive_retryable_failures"))
        .and_then(Value::as_u64)
        .ok_or_else(|| anyhow!("soak plan missing max_consecutive_retryable_failures"))?
        as usize;
    let runtime_command_shell = args_payload
        .get("live_redacted_shell_by_mode")
        .and_then(|value| value.get(&cli.loop_mode))
        .and_then(Value::as_str)
        .ok_or_else(|| anyhow!("missing live redacted shell"))?;
    let mut final_report = probe_report.clone();
    let final_status: String;
    let mut exit_code: i32;

    loop {
        let remaining = cli
            .max_runtime_seconds
            .map(|limit| limit - start_monotonic.elapsed().as_secs_f64());
        if let Some(value) = remaining {
            if value <= 0.0 {
                final_status = String::from("runtime_limit_reached");
                exit_code = 124;
                break;
            }
        }

        let attempt_index = attempts.len() + 1;
        let attempt_started_at = utc_now();
        let attempt_log_path =
            log_dir.join(build_attempt_file_name(attempt_log_pattern, attempt_index));
        let attempt_report_path =
            log_dir.join(build_attempt_file_name(attempt_report_pattern, attempt_index));
        let mut command_args = runtime_args.clone();
        command_args.push(target_url.clone());
        let run_output = run_command(&command_args, remaining)?;
        let attempt_finished_at = utc_now();
        let run_exit_code = if run_output.timed_out { 124 } else { run_output.exit_code };
        let attempt_report = write_report_and_log(
            &run_output.stderr,
            run_exit_code,
            &taxonomy,
            &cli.loop_mode,
            cli.max_runtime_seconds.unwrap_or(0.0),
            runtime_command_shell,
            &redact_env_vars,
            &attempt_log_path,
            &attempt_report_path,
            "stage7_stream_bridge_runtime_attempt",
            json!({
                "attempt_index": attempt_index,
                "started_at": attempt_started_at,
                "finished_at": attempt_finished_at,
                "timed_out": run_output.timed_out,
            }),
        )?;
        copy_file(&attempt_log_path, &latest_log_path)?;
        write_json(&exit_report_path, &attempt_report)?;

        let status = attempt_report
            .get("status")
            .and_then(Value::as_str)
            .unwrap_or("terminal_failure")
            .to_string();
        let retryable = attempt_report
            .get("retryable")
            .and_then(Value::as_bool)
            .unwrap_or(false);
        let mut attempt_summary = json!({
            "attempt_index": attempt_index,
            "started_at": attempt_started_at,
            "finished_at": attempt_finished_at,
            "elapsed_seconds": iso_elapsed_seconds(&attempt_started_at, &attempt_finished_at)?,
            "status": status,
            "exit_code": attempt_report.get("exit_code").cloned().unwrap_or(json!(run_exit_code)),
            "exit_class_id": attempt_report.get("exit_class_id").cloned().unwrap_or(Value::Null),
            "retryable": retryable,
            "stderr_log_file": attempt_log_path.display().to_string(),
            "exit_report_file": attempt_report_path.display().to_string(),
        });

        final_report = attempt_report;
        exit_code = run_exit_code;
        if status == "clean_exit" {
            final_status = String::from("completed");
            attempts.push(attempt_summary);
            break;
        }
        if status == "runtime_limit_reached" {
            final_status = String::from("runtime_limit_reached");
            attempts.push(attempt_summary);
            break;
        }
        if status == "interrupted" {
            final_status = String::from("interrupted");
            attempts.push(attempt_summary);
            break;
        }
        if retryable {
            consecutive_retryable_failures += 1;
            if consecutive_retryable_failures >= max_consecutive_retryable_failures {
                final_status = String::from("retry_exhausted");
                attempt_summary["backoff_seconds_before_next"] = Value::Null;
                attempts.push(attempt_summary);
                break;
            }
            let sleep_seconds = backoff_seconds
                .get(consecutive_retryable_failures - 1)
                .copied()
                .unwrap_or(1);
            attempt_summary["backoff_seconds_before_next"] = json!(sleep_seconds);
            attempts.push(attempt_summary);
            if let Some(limit) = cli.max_runtime_seconds {
                let remaining_after_attempt = limit - start_monotonic.elapsed().as_secs_f64();
                if remaining_after_attempt <= sleep_seconds as f64 {
                    final_status = String::from("retry_exhausted");
                    break;
                }
            }
            thread::sleep(Duration::from_secs(sleep_seconds));
            continue;
        }

        attempts.push(attempt_summary);
        final_status = String::from("terminal_failure");
        break;
    }

    let runtime_report = json!({
        "stage": "stage7_stream_bridge_runtime",
        "status": final_status,
        "started_at": started_at,
        "finished_at": utc_now(),
        "elapsed_seconds": elapsed_seconds(start_monotonic),
        "loop_mode": cli.loop_mode,
        "max_runtime_seconds": cli.max_runtime_seconds.unwrap_or(0.0),
        "preflight_report_file": preflight_report_path.display().to_string(),
        "latest_exit_report_file": exit_report_path.display().to_string(),
        "target": target,
        "attempts_total": attempts.len(),
        "attempts": attempts,
        "final_exit_class_id": final_report.get("exit_class_id").cloned().unwrap_or(Value::Null),
        "final_exit_code": exit_code,
        "retry_policy": {
            "backoff_seconds": backoff_seconds,
            "max_consecutive_retryable_failures": max_consecutive_retryable_failures,
        },
    });
    write_json(&runtime_report_path, &runtime_report)?;

    if final_status == "completed" {
        return Ok(0);
    }
    if final_status == "runtime_limit_reached" {
        emit_console_summary(
            "runtime budget reached; MUSIKALISCHES_STAGE7_MAX_RUNTIME_SECONDS is an overall wrapper runtime budget; omit it for unattended LOOP_MODE=infinite",
            &preflight_report_path,
            &preflight_log_path,
            &runtime_report_path,
            &exit_report_path,
            &latest_log_path,
        );
    } else {
        emit_console_summary(
            &format!(
                "runtime ended with status={final_status}; exit_class_id={}; exit_code={exit_code}",
                final_report
                    .get("exit_class_id")
                    .and_then(Value::as_str)
                    .unwrap_or("unknown_failure"),
            ),
            &preflight_report_path,
            &preflight_log_path,
            &runtime_report_path,
            &exit_report_path,
            &latest_log_path,
        );
    }
    Ok(exit_code.max(1))
}
