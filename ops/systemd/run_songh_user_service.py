#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
import os
import shutil
import signal
import subprocess
import sys
import time
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


def validate_config(config: dict, mode: str) -> tuple[dict, dict, dict, dict]:
    service = config.get("service")
    modes = config.get("modes")
    prepare = config.get("prepare", {})
    install = config.get("install", {})
    if not isinstance(service, dict):
        raise SystemExit("songh systemd config missing [service] table")
    if not isinstance(modes, dict):
        raise SystemExit("songh systemd config missing [modes] table")
    mode_config = modes.get(mode)
    if not isinstance(mode_config, dict):
        raise SystemExit(f"songh systemd config missing [modes.{mode}] table")
    if not isinstance(prepare, dict):
        raise SystemExit("songh systemd config [prepare] must be a TOML table")
    if not isinstance(install, dict):
        raise SystemExit("songh systemd config [install] must be a TOML table")
    return service, mode_config, prepare, install


def sanitize_target(url: str) -> str:
    parsed = urlparse(url)
    default_port = 443 if parsed.scheme == "rtmps" else 1935
    host = parsed.hostname or "<missing-host>"
    port = parsed.port or default_port
    return f"{parsed.scheme or 'rtmps'}://{host}:{port}/<redacted>"


def emit(message: str, *, stream: object = sys.stdout) -> None:
    print(message, file=stream, flush=True)


def summarize_report(label: str, path: Path, *, min_mtime: float | None = None) -> None:
    if not path.exists():
        emit(f"[songh-systemd] missing {label} report: {path}", stream=sys.stderr)
        return
    if min_mtime is not None and path.stat().st_mtime < min_mtime:
        emit(
            f"[songh-systemd] {label} report predates this run (stale) — "
            f"songh exited before writing a new report; check stderr/journald for the real error: {path}",
            stream=sys.stderr,
        )
        return
    payload = load_json(path)
    summary = {
        "stage": payload.get("stage"),
        "status": payload.get("status"),
        "failed_check_id": payload.get("failed_check_id"),
        "final_exit_class_id": payload.get("final_exit_class_id"),
        "final_exit_code": payload.get("final_exit_code"),
        "attempts_total": payload.get("attempts_total"),
        "loop_mode": payload.get("loop_mode"),
        "max_runtime_seconds": payload.get("max_runtime_seconds"),
        "file": str(path),
    }
    emit(f"[songh-systemd] {label} " + json.dumps(summary, ensure_ascii=True, sort_keys=True))


def require_status(path: Path, expected_status: str, label: str) -> dict:
    if not path.exists():
        raise SystemExit(f"missing {label}: {path}")
    payload = load_json(path)
    if payload.get("status") != expected_status:
        raise SystemExit(
            f"{label} must have status={expected_status}: {path}"
        )
    return payload


def resolve_songh_command(
    *,
    repo_root: Path,
    service: dict,
) -> list[str]:
    songh_bin = resolve_path(
        repo_root,
        str(service.get("songh_bin", "src/songh/target/debug/songh")),
    )
    if songh_bin.exists():
        return [str(songh_bin)]

    cargo_bin_name = str(service.get("cargo_bin", "cargo")).strip() or "cargo"
    cargo_bin = shutil.which(cargo_bin_name) or cargo_bin_name
    cargo_manifest = resolve_path(
        repo_root,
        str(service.get("cargo_manifest", "src/songh/Cargo.toml")),
    )
    return [cargo_bin, "run", "--manifest-path", str(cargo_manifest), "--"]


def run_prepare_mode(
    *,
    repo_root: Path,
    working_directory: Path,
    artifact_dir: Path,
    service: dict,
    prepare: dict,
) -> int:
    output_dir = resolve_path(repo_root, str(prepare.get("output_dir", str(artifact_dir))))
    command = resolve_songh_command(repo_root=repo_root, service=service)
    command.extend(
        [
            "build-stream-bridge",
            "--config",
            str(resolve_path(repo_root, str(prepare.get("config_path", "docs/plans/260321-songh-template.toml")))),
            "--archive-root",
            str(resolve_path(repo_root, str(prepare.get("archive_root", "ops/out/songh-stage2-archive")))),
            "--output-dir",
            str(output_dir),
            "--day",
            str(prepare.get("day", "2026-03-19")),
            "--start-second",
            str(int(prepare.get("start_second", 750))),
            "--duration-secs",
            str(int(prepare.get("duration_secs", 8))),
        ]
    )
    motion_mode = str(prepare.get("motion_mode", "")).strip()
    if motion_mode:
        command.extend(["--motion-mode", motion_mode])
    angle_deg = prepare.get("angle_deg")
    if angle_deg is not None:
        command.extend(["--angle-deg", str(angle_deg)])

    emit(
        "[songh-systemd] prepare "
        + json.dumps(
            {
                "working_directory": str(working_directory),
                "output_dir": str(output_dir),
                "command": command,
            },
            ensure_ascii=True,
            sort_keys=True,
        )
    )

    result = subprocess.run(command, cwd=str(working_directory), check=False)
    if result.returncode != 0:
        return result.returncode

    validation_path = output_dir / "stage7_bridge_validation_report.json"
    manifest_path = output_dir / "stream_bridge_manifest.json"
    validation = require_status(validation_path, "passed", "stage7 validation report")
    if not manifest_path.exists():
        raise SystemExit(f"missing stage7 manifest: {manifest_path}")
    manifest = load_json(manifest_path)
    emit(
        "[songh-systemd] prepare-summary "
        + json.dumps(
            {
                "manifest": str(manifest_path),
                "schema_version": manifest.get("schema_version"),
                "generator_mode": manifest.get("live_runtime", {}).get("generator_mode"),
                "source_day": manifest.get("source_day"),
                "validation_status": validation.get("status"),
            },
            ensure_ascii=True,
            sort_keys=True,
        )
    )
    return 0


def run_live_mode(
    *,
    mode: str,
    repo_root: Path,
    working_directory: Path,
    artifact_dir: Path,
    service: dict,
    mode_config: dict,
) -> int:
    validation_path = artifact_dir / "stage7_bridge_validation_report.json"
    if service.get("require_validation_passed", True):
        require_status(validation_path, "passed", "stage7 validation report")

    manifest_path = artifact_dir / "stream_bridge_manifest.json"
    if not manifest_path.exists():
        raise SystemExit(f"missing stream bridge manifest: {manifest_path}")
    manifest = load_json(manifest_path)
    runtime_observability = manifest.get("runtime_observability", {})
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

    stream_url = str(service.get("stream_url", "")).strip()
    if not stream_url or "<stream-key>" in stream_url:
        raise SystemExit("service.stream_url must be set to a real RTMP/RTMPS ingest URL before start")

    loop_mode = str(mode_config.get("loop_mode", service.get("loop_mode", "infinite"))).strip()
    if loop_mode not in {"once", "infinite"}:
        raise SystemExit(f"unsupported loop_mode in systemd config: {loop_mode}")
    max_runtime_seconds = int(mode_config.get("max_runtime_seconds", 0) or 0)

    env = os.environ.copy()
    env["PYTHONUNBUFFERED"] = "1"
    env["SONGH_RTMP_URL"] = stream_url
    env["SONGH_STAGE7_LOOP_MODE"] = loop_mode
    if max_runtime_seconds > 0:
        env["SONGH_STAGE7_MAX_RUNTIME_SECONDS"] = str(max_runtime_seconds)
    else:
        env.pop("SONGH_STAGE7_MAX_RUNTIME_SECONDS", None)

    command = resolve_songh_command(repo_root=repo_root, service=service)
    command.extend(
        [
            "run-stream-bridge",
            "--artifact-dir",
            str(artifact_dir),
            "--loop-mode",
            loop_mode,
            "--max-runtime-secs",
            str(max_runtime_seconds),
        ]
    )

    emit(
        "[songh-systemd] start "
        + json.dumps(
            {
                "mode": mode,
                "working_directory": str(working_directory),
                "artifact_dir": str(artifact_dir),
                "target": sanitize_target(stream_url),
                "loop_mode": loop_mode,
                "max_runtime_seconds": max_runtime_seconds,
                "command": command,
            },
            ensure_ascii=True,
            sort_keys=True,
        )
    )
    emit(
        "[songh-systemd] reports "
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

    launch_time = time.time()
    child = subprocess.Popen(command, cwd=str(working_directory), env=env)
    exit_code = child.wait()

    summarize_report("preflight", preflight_report_path, min_mtime=launch_time)
    summarize_report("runtime", runtime_report_path, min_mtime=launch_time)
    summarize_report("exit", exit_report_path, min_mtime=launch_time)
    emit(f"[songh-systemd] finished mode={mode} exit_code={exit_code}")
    return exit_code


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run songh stage7 prepare/live modes from a systemd --user config."
    )
    parser.add_argument("--config", required=True, help="path to ops/systemd TOML config")
    parser.add_argument("--mode", required=True, help="mode key from the TOML [modes] table")
    args = parser.parse_args()

    config_path = Path(args.config).expanduser().resolve()
    config = load_toml(config_path)
    service, mode_config, prepare, _ = validate_config(config, args.mode)

    repo_root = Path(__file__).resolve().parent.parent.parent
    working_directory = resolve_path(repo_root, str(service.get("working_directory", ".")))
    artifact_dir = resolve_path(repo_root, str(service.get("artifact_dir", "ops/out/songh-stage7-stream-bridge")))
    action = str(mode_config.get("action", "run")).strip() or "run"

    if action == "prepare":
        return run_prepare_mode(
            repo_root=repo_root,
            working_directory=working_directory,
            artifact_dir=artifact_dir,
            service=service,
            prepare=prepare,
        )
    if action == "run":
        return run_live_mode(
            mode=args.mode,
            repo_root=repo_root,
            working_directory=working_directory,
            artifact_dir=artifact_dir,
            service=service,
            mode_config=mode_config,
        )
    raise SystemExit(f"unsupported songh systemd action: {action}")


if __name__ == "__main__":
    raise SystemExit(main())
