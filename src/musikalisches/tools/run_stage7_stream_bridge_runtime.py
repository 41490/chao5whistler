#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
import shlex
import signal
import socket
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

from classify_stage7_bridge_failure import build_runtime_report_payload


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: dict) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=True, indent=2) + "\n",
        encoding="utf-8",
    )


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def round6(value: float) -> float:
    return round(value, 6)


def parse_max_runtime(value: str) -> float | None:
    if value in {"", "0"}:
        return None
    try:
        parsed = float(value)
    except ValueError as exc:
        raise SystemExit(f"invalid --max-runtime-seconds: {value}") from exc
    if parsed <= 0:
        raise SystemExit("--max-runtime-seconds must be > 0 when provided")
    return parsed


def sanitize_target(url: str) -> dict:
    parsed = urlparse(url)
    default_port = 443 if parsed.scheme == "rtmps" else 1935
    return {
        "scheme": parsed.scheme,
        "host": parsed.hostname,
        "port": parsed.port or default_port,
        "path_redacted": True,
    }


def build_attempt_file_name(pattern: str, attempt_index: int) -> str:
    return pattern.format(attempt=attempt_index)


def copy_file(source: Path, destination: Path) -> None:
    destination.write_text(source.read_text(encoding="utf-8"), encoding="utf-8")


def run_command(args: list[str], timeout_seconds: float | None = None) -> tuple[int, str, bool]:
    process = subprocess.Popen(
        args,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    timed_out = False
    try:
        _, stderr = process.communicate(timeout=timeout_seconds)
        return process.returncode, stderr, timed_out
    except subprocess.TimeoutExpired:
        timed_out = True
        process.send_signal(signal.SIGINT)
        try:
            _, stderr = process.communicate(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
            _, stderr = process.communicate()
        return 124, stderr, timed_out


def write_report_and_log(
    *,
    raw_text: str,
    exit_code: int,
    taxonomy: dict,
    loop_mode: str,
    max_runtime_seconds: float,
    command_shell: str,
    redact_env_vars: list[str],
    output_log: Path,
    output_report: Path,
    stage: str,
    extra_fields: dict | None = None,
) -> dict:
    redacted_text, report = build_runtime_report_payload(
        raw_text=raw_text,
        exit_code=exit_code,
        taxonomy=taxonomy,
        loop_mode=loop_mode,
        max_runtime_seconds=max_runtime_seconds,
        command_shell=command_shell,
        redact_env_vars=redact_env_vars,
        stage=stage,
        extra_fields={
            "log_file": str(output_log),
            **(extra_fields or {}),
        },
    )
    output_log.parent.mkdir(parents=True, exist_ok=True)
    output_report.parent.mkdir(parents=True, exist_ok=True)
    output_log.write_text(redacted_text, encoding="utf-8")
    write_json(output_report, report)
    return report


def resolve_protocol_support(ffmpeg_bin: str, protocol: str) -> tuple[bool, str]:
    result = subprocess.run(
        [ffmpeg_bin, "-protocols"],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    output = (result.stdout or "") + ("\n" if result.stdout and result.stderr else "") + (result.stderr or "")
    supported = protocol.lower() in {
        line.strip().lower()
        for line in output.splitlines()
        if line.strip() and line.strip().endswith(":") is False
    }
    return supported and result.returncode == 0, output.strip()


def resolve_dns(host: str, port: int) -> tuple[list[str], str | None]:
    try:
        infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except socket.gaierror as exc:
        return [], str(exc)
    addresses = sorted({item[4][0] for item in infos if item[4]})
    return addresses, None


def probe_tcp_connectivity(host: str, port: int, timeout_seconds: float) -> tuple[bool, str]:
    try:
        with socket.create_connection((host, port), timeout=timeout_seconds):
            return True, ""
    except OSError as exc:
        return False, str(exc)


def build_publish_probe_args(ffmpeg_bin: str, target_url: str) -> list[str]:
    return [
        ffmpeg_bin,
        "-hide_banner",
        "-nostats",
        "-f",
        "lavfi",
        "-i",
        "testsrc=size=16x16:rate=1",
        "-f",
        "lavfi",
        "-i",
        "anullsrc=r=44100:cl=stereo",
        "-t",
        "1",
        "-map",
        "0:v:0",
        "-map",
        "1:a:0",
        "-c:v",
        "libx264",
        "-preset",
        "ultrafast",
        "-pix_fmt",
        "yuv420p",
        "-r",
        "1",
        "-g",
        "1",
        "-keyint_min",
        "1",
        "-sc_threshold",
        "0",
        "-b:v",
        "150k",
        "-maxrate",
        "150k",
        "-bufsize",
        "150k",
        "-vf",
        "scale=16:16:flags=fast_bilinear,setsar=1",
        "-c:a",
        "aac",
        "-b:a",
        "64k",
        "-ar",
        "44100",
        "-ac",
        "2",
        "-f",
        "flv",
        target_url,
    ]


def elapsed_seconds(start_monotonic: float) -> float:
    return round6(time.monotonic() - start_monotonic)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Execute the stage7 RTMPS runtime wrapper with preflight and reconnect policy enforcement."
    )
    parser.add_argument("--artifact-dir", required=True, help="stage7 bridge artifact directory")
    parser.add_argument("--stream-url-env", required=True, help="environment variable carrying the RTMPS URL")
    parser.add_argument("--loop-mode", default="infinite", help="stage7 loop mode: once|infinite")
    parser.add_argument(
        "--max-runtime-seconds",
        default="0",
        help="overall wrapper runtime budget in seconds, or 0 when unset",
    )
    args = parser.parse_args()

    artifact_dir = Path(args.artifact_dir).resolve()
    manifest = load_json(artifact_dir / "stream_bridge_manifest.json")
    args_payload = load_json(artifact_dir / "stream_bridge_ffmpeg_args.json")
    taxonomy = load_json(artifact_dir / "stage7_failure_taxonomy.json")
    soak_plan = load_json(artifact_dir / "stage7_soak_plan.json")
    profile = load_json(artifact_dir / "stage7_bridge_profile.json")

    url_env_var = args_payload.get("url_env_var")
    if args.stream_url_env != url_env_var:
        raise SystemExit(
            f"stream url env mismatch: script requested {args.stream_url_env}, artifact expects {url_env_var}"
        )
    target_url = __import__("os").environ.get(url_env_var, "")
    if not target_url:
        raise SystemExit(f"missing {url_env_var}: export {url_env_var}=...")

    loop_mode = args.loop_mode
    runtime_args_by_mode = args_payload.get("live_runtime_argv_without_target_by_mode", {})
    if loop_mode not in runtime_args_by_mode:
        raise SystemExit(f"unsupported loop mode: {loop_mode}")

    max_runtime_seconds = parse_max_runtime(args.max_runtime_seconds)
    runtime_observability = manifest.get("runtime_observability", {})
    preflight_contract = manifest.get("preflight", {})
    runtime_executor = manifest.get("runtime_executor", {})
    log_dir = artifact_dir / runtime_observability["log_dir"]
    log_dir.mkdir(parents=True, exist_ok=True)

    latest_log_path = log_dir / runtime_observability["stderr_log_file"]
    exit_report_path = log_dir / runtime_observability["exit_report_file"]
    preflight_log_path = log_dir / runtime_observability["preflight_log_file"]
    preflight_report_path = log_dir / runtime_observability["preflight_report_file"]
    runtime_report_path = log_dir / runtime_observability["runtime_report_file"]
    attempt_log_pattern = runtime_observability["attempt_log_pattern"]
    attempt_report_pattern = runtime_observability["attempt_report_pattern"]
    redact_env_vars = runtime_observability.get("redact_env_vars", [url_env_var])

    ffmpeg_bin = args_payload.get("runtime_ffmpeg_bin")
    protocol = profile.get("ingest", {}).get("protocol")
    target = sanitize_target(target_url)
    parsed_target = urlparse(target_url)
    expected_port = target["port"]
    if parsed_target.scheme != protocol:
        preflight_report = write_report_and_log(
            raw_text=f"protocol not found: expected {protocol}:// but received {parsed_target.scheme or '<missing>'}://",
            exit_code=1,
            taxonomy=taxonomy,
            loop_mode=loop_mode,
            max_runtime_seconds=max_runtime_seconds or 0,
            command_shell=f"<env:{url_env_var}>",
            redact_env_vars=redact_env_vars,
            output_log=preflight_log_path,
            output_report=preflight_report_path,
            stage="stage7_stream_bridge_preflight",
            extra_fields={
                "status": "preflight_failed",
                "failed_check_id": "target_scheme",
                "target": target,
                "checks": [],
            },
        )
        write_json(
            runtime_report_path,
            {
                "stage": "stage7_stream_bridge_runtime",
                "status": "preflight_failed",
                "loop_mode": loop_mode,
                "max_runtime_seconds": max_runtime_seconds or 0,
                "preflight_report_file": str(preflight_report_path),
                "target": target,
                "attempts_total": 0,
                "attempts": [],
                "final_exit_class_id": preflight_report["exit_class_id"],
                "final_exit_code": preflight_report["exit_code"],
                "retry_policy": runtime_executor,
            },
        )
        copy_file(preflight_log_path, latest_log_path)
        write_json(exit_report_path, preflight_report)
        return 1

    start_monotonic = time.monotonic()
    started_at = utc_now()
    preflight_checks: list[dict] = []
    preflight_command_shell = f"ffmpeg-preflight {url_env_var}=${{{url_env_var}}}"

    supported, protocol_output = resolve_protocol_support(ffmpeg_bin, protocol)
    preflight_checks.append(
        {
            "check_id": "protocol_support",
            "status": "passed" if supported else "failed",
            "details": {
                "ffmpeg_bin": ffmpeg_bin,
                "protocol": protocol,
            },
        }
    )
    if not supported:
        preflight_report = write_report_and_log(
            raw_text=f"protocol not found: required {protocol} output support missing\n{protocol_output}",
            exit_code=1,
            taxonomy=taxonomy,
            loop_mode=loop_mode,
            max_runtime_seconds=max_runtime_seconds or 0,
            command_shell=preflight_command_shell,
            redact_env_vars=redact_env_vars,
            output_log=preflight_log_path,
            output_report=preflight_report_path,
            stage="stage7_stream_bridge_preflight",
            extra_fields={
                "status": "preflight_failed",
                "failed_check_id": "protocol_support",
                "target": target,
                "checks": preflight_checks,
            },
        )
        copy_file(preflight_log_path, latest_log_path)
        write_json(exit_report_path, preflight_report)
        write_json(
            runtime_report_path,
            {
                "stage": "stage7_stream_bridge_runtime",
                "status": "preflight_failed",
                "started_at": started_at,
                "finished_at": utc_now(),
                "elapsed_seconds": elapsed_seconds(start_monotonic),
                "loop_mode": loop_mode,
                "max_runtime_seconds": max_runtime_seconds or 0,
                "preflight_report_file": str(preflight_report_path),
                "target": target,
                "attempts_total": 0,
                "attempts": [],
                "final_exit_class_id": preflight_report["exit_class_id"],
                "final_exit_code": preflight_report["exit_code"],
                "retry_policy": runtime_executor,
            },
        )
        return 1

    host = parsed_target.hostname
    if not host:
        raise SystemExit(f"{url_env_var} must include a hostname")
    resolved_addresses, dns_error = resolve_dns(host, expected_port)
    preflight_checks.append(
        {
            "check_id": "dns_resolution",
            "status": "passed" if dns_error is None else "failed",
            "details": {
                "host": host,
                "port": expected_port,
                "resolved_addresses": resolved_addresses[:4],
                "error": dns_error,
            },
        }
    )
    if dns_error is not None:
        preflight_report = write_report_and_log(
            raw_text=f"temporary failure in name resolution: {dns_error}",
            exit_code=1,
            taxonomy=taxonomy,
            loop_mode=loop_mode,
            max_runtime_seconds=max_runtime_seconds or 0,
            command_shell=preflight_command_shell,
            redact_env_vars=redact_env_vars,
            output_log=preflight_log_path,
            output_report=preflight_report_path,
            stage="stage7_stream_bridge_preflight",
            extra_fields={
                "status": "preflight_failed",
                "failed_check_id": "dns_resolution",
                "target": target,
                "checks": preflight_checks,
            },
        )
        copy_file(preflight_log_path, latest_log_path)
        write_json(exit_report_path, preflight_report)
        write_json(
            runtime_report_path,
            {
                "stage": "stage7_stream_bridge_runtime",
                "status": "preflight_failed",
                "started_at": started_at,
                "finished_at": utc_now(),
                "elapsed_seconds": elapsed_seconds(start_monotonic),
                "loop_mode": loop_mode,
                "max_runtime_seconds": max_runtime_seconds or 0,
                "preflight_report_file": str(preflight_report_path),
                "target": target,
                "attempts_total": 0,
                "attempts": [],
                "final_exit_class_id": preflight_report["exit_class_id"],
                "final_exit_code": preflight_report["exit_code"],
                "retry_policy": runtime_executor,
            },
        )
        return 1

    tcp_ok, tcp_error = probe_tcp_connectivity(host, expected_port, preflight_contract["tcp_connect_timeout_seconds"])
    preflight_checks.append(
        {
            "check_id": "tcp_connectivity",
            "status": "passed" if tcp_ok else "failed",
            "details": {
                "host": host,
                "port": expected_port,
                "timeout_seconds": preflight_contract["tcp_connect_timeout_seconds"],
                "error": tcp_error or None,
            },
        }
    )
    if not tcp_ok:
        preflight_report = write_report_and_log(
            raw_text=f"connection refused: unable to reach {host}:{expected_port}: {tcp_error}",
            exit_code=1,
            taxonomy=taxonomy,
            loop_mode=loop_mode,
            max_runtime_seconds=max_runtime_seconds or 0,
            command_shell=preflight_command_shell,
            redact_env_vars=redact_env_vars,
            output_log=preflight_log_path,
            output_report=preflight_report_path,
            stage="stage7_stream_bridge_preflight",
            extra_fields={
                "status": "preflight_failed",
                "failed_check_id": "tcp_connectivity",
                "target": target,
                "checks": preflight_checks,
            },
        )
        copy_file(preflight_log_path, latest_log_path)
        write_json(exit_report_path, preflight_report)
        write_json(
            runtime_report_path,
            {
                "stage": "stage7_stream_bridge_runtime",
                "status": "preflight_failed",
                "started_at": started_at,
                "finished_at": utc_now(),
                "elapsed_seconds": elapsed_seconds(start_monotonic),
                "loop_mode": loop_mode,
                "max_runtime_seconds": max_runtime_seconds or 0,
                "preflight_report_file": str(preflight_report_path),
                "target": target,
                "attempts_total": 0,
                "attempts": [],
                "final_exit_class_id": preflight_report["exit_class_id"],
                "final_exit_code": preflight_report["exit_code"],
                "retry_policy": runtime_executor,
            },
        )
        return 1

    publish_probe_args = build_publish_probe_args(ffmpeg_bin, target_url)
    publish_probe_redacted_shell = shlex.join(build_publish_probe_args(ffmpeg_bin, f"${{{url_env_var}}}"))
    probe_exit_code, probe_stderr, _ = run_command(
        publish_probe_args,
        timeout_seconds=preflight_contract["publish_probe_timeout_seconds"],
    )
    probe_report = write_report_and_log(
        raw_text=probe_stderr,
        exit_code=probe_exit_code,
        taxonomy=taxonomy,
        loop_mode=loop_mode,
        max_runtime_seconds=max_runtime_seconds or 0,
        command_shell=publish_probe_redacted_shell,
        redact_env_vars=redact_env_vars,
        output_log=preflight_log_path,
        output_report=preflight_report_path,
        stage="stage7_stream_bridge_preflight",
        extra_fields={
            "status": "preflight_passed" if probe_exit_code == 0 else "preflight_failed",
            "failed_check_id": None if probe_exit_code == 0 else "publish_probe",
            "target": target,
            "checks": preflight_checks
            + [
                {
                    "check_id": "publish_probe",
                    "status": "passed" if probe_exit_code == 0 else "failed",
                    "details": {
                        "probe_timeout_seconds": preflight_contract["publish_probe_timeout_seconds"],
                        "exit_code": probe_exit_code,
                    },
                }
            ],
            "probe_mode": preflight_contract["publish_probe_mode"],
        },
    )
    copy_file(preflight_log_path, latest_log_path)
    write_json(exit_report_path, probe_report)
    if probe_exit_code != 0:
        write_json(
            runtime_report_path,
            {
                "stage": "stage7_stream_bridge_runtime",
                "status": "preflight_failed",
                "started_at": started_at,
                "finished_at": utc_now(),
                "elapsed_seconds": elapsed_seconds(start_monotonic),
                "loop_mode": loop_mode,
                "max_runtime_seconds": max_runtime_seconds or 0,
                "preflight_report_file": str(preflight_report_path),
                "target": target,
                "attempts_total": 0,
                "attempts": [],
                "final_exit_class_id": probe_report["exit_class_id"],
                "final_exit_code": probe_report["exit_code"],
                "retry_policy": runtime_executor,
            },
        )
        return probe_exit_code or 1

    attempts: list[dict] = []
    consecutive_retryable_failures = 0
    backoff_seconds = soak_plan["reconnect_policy"]["backoff_seconds"]
    max_consecutive_retryable_failures = soak_plan["reconnect_policy"]["max_consecutive_retryable_failures"]
    runtime_args = runtime_args_by_mode[loop_mode]
    runtime_command_shell = args_payload["live_redacted_shell_by_mode"][loop_mode]
    final_report = probe_report
    final_status = "completed"
    exit_code = 0

    while True:
        if max_runtime_seconds is not None:
            remaining = max_runtime_seconds - (time.monotonic() - start_monotonic)
            if remaining <= 0:
                final_status = "runtime_limit_reached"
                exit_code = 124
                break
        else:
            remaining = None

        attempt_index = len(attempts) + 1
        attempt_started_at = utc_now()
        attempt_log_path = log_dir / build_attempt_file_name(attempt_log_pattern, attempt_index)
        attempt_report_path = log_dir / build_attempt_file_name(attempt_report_pattern, attempt_index)
        run_exit_code, run_stderr, timed_out = run_command(
            [*runtime_args, target_url],
            timeout_seconds=remaining,
        )
        if timed_out:
            run_exit_code = 124
        attempt_finished_at = utc_now()
        attempt_report = write_report_and_log(
            raw_text=run_stderr,
            exit_code=run_exit_code,
            taxonomy=taxonomy,
            loop_mode=loop_mode,
            max_runtime_seconds=max_runtime_seconds or 0,
            command_shell=runtime_command_shell,
            redact_env_vars=redact_env_vars,
            output_log=attempt_log_path,
            output_report=attempt_report_path,
            stage="stage7_stream_bridge_runtime_attempt",
            extra_fields={
                "attempt_index": attempt_index,
                "started_at": attempt_started_at,
                "finished_at": attempt_finished_at,
                "timed_out": timed_out,
            },
        )
        copy_file(attempt_log_path, latest_log_path)
        write_json(exit_report_path, attempt_report)

        attempt_summary = {
            "attempt_index": attempt_index,
            "started_at": attempt_started_at,
            "finished_at": attempt_finished_at,
            "elapsed_seconds": round6(
                datetime.fromisoformat(attempt_finished_at.replace("Z", "+00:00")).timestamp()
                - datetime.fromisoformat(attempt_started_at.replace("Z", "+00:00")).timestamp()
            ),
            "status": attempt_report["status"],
            "exit_code": attempt_report["exit_code"],
            "exit_class_id": attempt_report["exit_class_id"],
            "retryable": attempt_report["retryable"],
            "stderr_log_file": str(attempt_log_path),
            "exit_report_file": str(attempt_report_path),
        }

        final_report = attempt_report
        exit_code = run_exit_code
        if attempt_report["status"] == "clean_exit":
            final_status = "completed"
            attempts.append(attempt_summary)
            break
        if attempt_report["status"] == "runtime_limit_reached":
            final_status = "runtime_limit_reached"
            attempts.append(attempt_summary)
            break
        if attempt_report["status"] == "interrupted":
            final_status = "interrupted"
            attempts.append(attempt_summary)
            break
        if attempt_report["retryable"]:
            consecutive_retryable_failures += 1
            if consecutive_retryable_failures >= max_consecutive_retryable_failures:
                final_status = "retry_exhausted"
                attempt_summary["backoff_seconds_before_next"] = None
                attempts.append(attempt_summary)
                break
            sleep_seconds = backoff_seconds[consecutive_retryable_failures - 1]
            attempt_summary["backoff_seconds_before_next"] = sleep_seconds
            attempts.append(attempt_summary)
            if max_runtime_seconds is not None:
                remaining_after_attempt = max_runtime_seconds - (time.monotonic() - start_monotonic)
                if remaining_after_attempt <= sleep_seconds:
                    final_status = "retry_exhausted"
                    break
            time.sleep(sleep_seconds)
            continue

        consecutive_retryable_failures = 0
        attempts.append(attempt_summary)
        final_status = "terminal_failure"
        break

    runtime_report = {
        "stage": "stage7_stream_bridge_runtime",
        "status": final_status,
        "started_at": started_at,
        "finished_at": utc_now(),
        "elapsed_seconds": elapsed_seconds(start_monotonic),
        "loop_mode": loop_mode,
        "max_runtime_seconds": max_runtime_seconds or 0,
        "preflight_report_file": str(preflight_report_path),
        "latest_exit_report_file": str(exit_report_path),
        "target": target,
        "attempts_total": len(attempts),
        "attempts": attempts,
        "final_exit_class_id": final_report.get("exit_class_id"),
        "final_exit_code": exit_code,
        "retry_policy": {
            "backoff_seconds": backoff_seconds,
            "max_consecutive_retryable_failures": max_consecutive_retryable_failures,
        },
    }
    write_json(runtime_report_path, runtime_report)

    if final_status == "completed":
        return 0
    return exit_code or 1


if __name__ == "__main__":
    raise SystemExit(main())
