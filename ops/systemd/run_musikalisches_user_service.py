#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
import os
import signal
import shutil
import subprocess
import sys
import tomllib
from pathlib import Path
from urllib.parse import urlparse


def load_toml(path: Path) -> dict:
    with path.open("rb") as handle:
        return tomllib.load(handle)


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def resolve_path(base_dir: Path, raw_path: str) -> Path:
    path = Path(raw_path).expanduser()
    return path if path.is_absolute() else (base_dir / path).resolve()


def validate_config(config: dict, mode: str) -> tuple[dict, dict, dict]:
    service = config.get("service")
    modes = config.get("modes")
    install = config.get("install", {})
    if not isinstance(service, dict):
        raise SystemExit("musikalisches systemd config missing [service] table")
    if not isinstance(modes, dict):
        raise SystemExit("musikalisches systemd config missing [modes] table")
    mode_config = modes.get(mode)
    if not isinstance(mode_config, dict):
        raise SystemExit(f"musikalisches systemd config missing [modes.{mode}] table")
    return service, mode_config, install


def sanitize_target(url: str) -> str:
    parsed = urlparse(url)
    default_port = 443 if parsed.scheme == "rtmps" else 1935
    host = parsed.hostname or "<missing-host>"
    port = parsed.port or default_port
    return f"{parsed.scheme or 'rtmps'}://{host}:{port}/<redacted>"


def emit(message: str, *, stream: object = sys.stdout) -> None:
    print(message, file=stream, flush=True)


def ensure_readiness_passed(readiness_path: Path) -> None:
    if not readiness_path.exists():
        raise SystemExit(f"missing readiness report: {readiness_path}")
    payload = load_json(readiness_path)
    if payload.get("status") != "passed":
        raise SystemExit(
            f"readiness report must have status=passed before systemd live start: {readiness_path}"
        )


def summarize_report(label: str, path: Path) -> None:
    if not path.exists():
        emit(f"[musikalisches-systemd] missing {label} report: {path}", stream=sys.stderr)
        return
    payload = load_json(path)
    summary = {
        "stage": payload.get("stage"),
        "status": payload.get("status"),
        "failed_check_id": payload.get("failed_check_id"),
        "exit_class_id": payload.get("exit_class_id"),
        "exit_code": payload.get("exit_code"),
        "elapsed_seconds": payload.get("elapsed_seconds"),
        "attempts_total": payload.get("attempts_total"),
        "final_exit_class_id": payload.get("final_exit_class_id"),
        "file": str(path),
    }
    emit(
        f"[musikalisches-systemd] {label} "
        f"{json.dumps(summary, ensure_ascii=True, sort_keys=True)}"
    )


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run Musikalisches stage7 live streaming from a systemd --user unit config."
    )
    parser.add_argument("--config", required=True, help="path to ops/systemd TOML config")
    parser.add_argument("--mode", required=True, help="mode key from the TOML [modes] table")
    args = parser.parse_args()

    config_path = Path(args.config).expanduser().resolve()
    config = load_toml(config_path)
    service, mode_config, _ = validate_config(config, args.mode)

    config_dir = config_path.parent
    working_directory = resolve_path(config_dir, service.get("working_directory", "../.."))
    artifact_dir = resolve_path(config_dir, service.get("artifact_dir", "../out/stream-bridge"))
    readiness_path = artifact_dir / "stage8_ops_readiness_report.json"
    manifest_path = artifact_dir / "stream_bridge_manifest.json"
    args_payload_path = artifact_dir / "stream_bridge_ffmpeg_args.json"

    if not manifest_path.exists():
        raise SystemExit(f"missing stream bridge manifest: {manifest_path}")
    if not args_payload_path.exists():
        raise SystemExit(f"missing stream bridge args payload: {args_payload_path}")

    if service.get("require_readiness_passed", True):
        ensure_readiness_passed(readiness_path)

    manifest = load_json(manifest_path)
    args_payload = load_json(args_payload_path)
    runtime_observability = manifest.get("runtime_observability", {})
    live_command = manifest.get("live_command", {})

    runtime_tool_path = Path(runtime_observability.get("runtime_tool_path", "")).resolve()
    if not runtime_tool_path.exists():
        raise SystemExit(f"missing runtime tool: {runtime_tool_path}")

    stream_url = str(service.get("stream_url", "")).strip()
    if not stream_url or "<stream-key>" in stream_url:
        raise SystemExit("service.stream_url must be set to a real RTMPS ingest URL before start")

    configured_python_bin = str(service.get("python_bin", sys.executable)).strip() or sys.executable
    python_bin = shutil.which(configured_python_bin) or configured_python_bin
    loop_mode = str(mode_config.get("loop_mode", service.get("loop_mode", "infinite"))).strip()
    max_runtime_seconds = int(mode_config.get("max_runtime_seconds", 0) or 0)
    mirror_child_stderr = bool(service.get("mirror_child_stderr", True))
    url_env_var = str(args_payload.get("url_env_var", "")).strip()
    if not url_env_var:
        raise SystemExit("stream_bridge_ffmpeg_args.json missing url_env_var")

    loop_env_var = str(live_command.get("loop_control_env", "MUSIKALISCHES_STAGE7_LOOP_MODE"))
    budget_env_var = str(
        live_command.get("max_runtime_env", "MUSIKALISCHES_STAGE7_MAX_RUNTIME_SECONDS")
    )

    log_dir = artifact_dir / runtime_observability.get("log_dir", "logs")
    preflight_report_path = log_dir / runtime_observability.get(
        "preflight_report_file",
        "stage7_bridge_preflight_report.json",
    )
    runtime_report_path = log_dir / runtime_observability.get(
        "runtime_report_file",
        "stage7_bridge_runtime_report.json",
    )
    exit_report_path = log_dir / runtime_observability.get(
        "exit_report_file",
        "stage7_bridge_exit_report.json",
    )

    env = os.environ.copy()
    env["PYTHONUNBUFFERED"] = "1"
    env[url_env_var] = stream_url
    env[loop_env_var] = loop_mode
    if max_runtime_seconds > 0:
        env[budget_env_var] = str(max_runtime_seconds)
    else:
        env.pop(budget_env_var, None)

    command = [
        python_bin,
        str(runtime_tool_path),
        "--artifact-dir",
        str(artifact_dir),
        "--stream-url-env",
        url_env_var,
        "--loop-mode",
        loop_mode,
        "--max-runtime-seconds",
        str(max_runtime_seconds),
    ]
    if mirror_child_stderr:
        command.append("--mirror-child-stderr")

    emit(
        "[musikalisches-systemd] start "
        + json.dumps(
            {
                "mode": args.mode,
                "working_directory": str(working_directory),
                "artifact_dir": str(artifact_dir),
                "target": sanitize_target(stream_url),
                "loop_mode": loop_mode,
                "max_runtime_seconds": max_runtime_seconds,
                "readiness_report": str(readiness_path),
                "runtime_tool": str(runtime_tool_path),
            },
            ensure_ascii=True,
            sort_keys=True,
        )
    )
    emit(
        "[musikalisches-systemd] reports "
        + json.dumps(
            {
                "preflight_report": str(preflight_report_path),
                "runtime_report": str(runtime_report_path),
                "exit_report": str(exit_report_path),
            },
            ensure_ascii=True,
            sort_keys=True,
        )
    )

    child: subprocess.Popen[str] | None = None

    def forward_signal(signum: int, _frame: object) -> None:
        if child is not None and child.poll() is None:
            child.send_signal(signum)

    signal.signal(signal.SIGINT, forward_signal)
    signal.signal(signal.SIGTERM, forward_signal)

    child = subprocess.Popen(
        command,
        cwd=str(working_directory),
        env=env,
    )
    exit_code = child.wait()

    summarize_report("preflight", preflight_report_path)
    summarize_report("runtime", runtime_report_path)
    summarize_report("exit", exit_report_path)
    emit(f"[musikalisches-systemd] finished mode={args.mode} exit_code={exit_code}")
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
