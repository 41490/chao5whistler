#!/usr/bin/env python3

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import wave
from pathlib import Path


REQUIRED_PREFLIGHT_CHECKS = {
    "protocol_support",
    "dns_resolution",
    "tcp_connectivity",
    "publish_probe",
}


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: dict) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=True, indent=2) + "\n",
        encoding="utf-8",
    )


def build_check(check_id: str, passed: bool, details: dict) -> dict:
    return {
        "check_id": check_id,
        "status": "passed" if passed else "failed",
        "details": details,
    }


def fail(errors: list[str]) -> int:
    print("stage8 ops readiness validation failed:")
    for error in errors:
        print(f"- {error}")
    return 1


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def build_file_integrity(path: Path) -> dict:
    return {
        "file": path.name,
        "size_bytes": path.stat().st_size,
        "sha256": sha256_file(path),
    }


def inspect_wav(path: Path) -> dict | None:
    if not path.exists():
        return None
    with wave.open(str(path), "rb") as handle:
        sample_rate = handle.getframerate()
        channels = handle.getnchannels()
        frames = handle.getnframes()
    return {
        "sample_rate_hz": sample_rate,
        "channels": channels,
        "frames": frames,
        "duration_seconds": round(frames / sample_rate if sample_rate else 0.0, 6),
    }


def run(args: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        args,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )


def parse_protocols(output: str) -> dict[str, set[str]]:
    sections = {"Input": set(), "Output": set()}
    current: str | None = None
    for raw_line in output.splitlines():
        line = raw_line.strip()
        if line == "Input:":
            current = "Input"
            continue
        if line == "Output:":
            current = "Output"
            continue
        if not line or current is None or line.endswith(":"):
            continue
        sections[current].add(line)
    return sections


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Validate stage8 live ops readiness from a frozen stage7 bridge artifact directory."
    )
    parser.add_argument(
        "artifact_dir",
        nargs="?",
        default="ops/out/stream-bridge",
        help="stage7 bridge artifact directory",
    )
    parser.add_argument("--ffmpeg-bin", default="", help="override ffmpeg binary")
    parser.add_argument("--ffprobe-bin", default="", help="override ffprobe binary")
    args = parser.parse_args()

    artifact_dir = Path(args.artifact_dir).resolve()
    if not artifact_dir.exists():
        return fail([f"artifact directory does not exist: {artifact_dir}"])

    manifest_path = artifact_dir / "stream_bridge_manifest.json"
    bridge_report_path = artifact_dir / "stage7_bridge_validation_report.json"
    soak_report_path = artifact_dir / "stage7_soak_validation_report.json"
    run_script_path = artifact_dir / "run_stage7_stream_bridge.sh"
    args_path = artifact_dir / "stream_bridge_ffmpeg_args.json"
    if not manifest_path.exists() or not bridge_report_path.exists() or not soak_report_path.exists():
        return fail(
            [
                "missing required stage8 readiness files: stream_bridge_manifest.json, "
                "stage7_bridge_validation_report.json, stage7_soak_validation_report.json"
            ]
        )

    manifest = load_json(manifest_path)
    bridge_report = load_json(bridge_report_path)
    soak_report = load_json(soak_report_path)
    args_payload = load_json(args_path) if args_path.exists() else {}
    stage8_ops = manifest.get("stage8_ops", {})
    sample_retention = stage8_ops.get("sample_retention", {})
    bridge_consistency = manifest.get("bridge_consistency", {})
    audio_input = manifest.get("audio_input", {})
    video_input = manifest.get("video_input", {})
    runtime_observability = manifest.get("runtime_observability", {})
    preflight = manifest.get("preflight", {})
    runtime_executor = manifest.get("runtime_executor", {})
    log_dir = artifact_dir / runtime_observability.get("log_dir", "")
    readiness_report_path = artifact_dir / stage8_ops.get(
        "readiness_report_file",
        "stage8_ops_readiness_report.json",
    )

    audio_path = Path(audio_input.get("path", ""))
    video_path = Path(video_input.get("path", ""))
    wav_metadata = inspect_wav(audio_path)
    source_video_integrity = (
        build_file_integrity(video_path) if video_path.exists() and video_path.is_file() else None
    )

    live_ffmpeg_bin = args.ffmpeg_bin or manifest.get("live_command", {}).get("ffmpeg_bin", "")
    smoke_ffprobe_bin = args.ffprobe_bin or manifest.get("smoke_generation", {}).get("ffprobe_bin", "")
    ffmpeg_bin = shutil.which(live_ffmpeg_bin) or live_ffmpeg_bin
    ffprobe_bin = shutil.which(smoke_ffprobe_bin) or smoke_ffprobe_bin
    ffmpeg_version = run([ffmpeg_bin, "-version"]) if ffmpeg_bin else None
    ffprobe_version = run([ffprobe_bin, "-version"]) if ffprobe_bin else None
    protocols_run = run([ffmpeg_bin, "-protocols"]) if ffmpeg_bin else None
    protocol_sections = (
        parse_protocols((protocols_run.stdout or "") + "\n" + (protocols_run.stderr or ""))
        if protocols_run is not None
        else {"Input": set(), "Output": set()}
    )
    configure_line = ""
    if ffmpeg_version is not None:
        configure_line = next(
            (line for line in ffmpeg_version.stdout.splitlines() if line.startswith("configuration:")),
            "",
        )

    checks: list[dict] = []
    checks.append(
        build_check(
            "stage8_ops_contract",
            isinstance(stage8_ops, dict)
            and Path(stage8_ops.get("guide_file", "")).exists()
            and stage8_ops.get("entry_script_file") == run_script_path.name
            and stage8_ops.get("recommended_loop_mode")
            == manifest.get("loop_bridge", {}).get("default_loop_mode")
            and stage8_ops.get("formal_soak_runtime_budget_policy")
            == "unset_for_formal_soak"
            and isinstance(stage8_ops.get("required_env_vars"), list)
            and bool(stage8_ops.get("required_env_vars"))
            and stage8_ops.get("readiness_report_file") == readiness_report_path.name
            and isinstance(sample_retention, dict)
            and Path(sample_retention.get("tool_path", "")).exists()
            and sample_retention.get("samples_dir") == "stage8-samples"
            and sample_retention.get("operator_summary_template_file")
            == "operator_summary_template.md"
            and sample_retention.get("attempt_log_index_file") == "attempt_log_index.json"
            and sample_retention.get("runtime_artifact_digest_file")
            == "runtime_artifact_digest.json"
            and sample_retention.get("retention_report_file")
            == "stage8_sample_retention_report.json",
            {
                "stage8_ops": stage8_ops,
                "sample_retention": sample_retention,
                "run_script_file": run_script_path.name,
                "readiness_report_file": readiness_report_path.name,
            },
        )
    )
    checks.append(
        build_check(
            "validation_reports",
            bridge_report.get("status") == "passed" and soak_report.get("status") == "passed",
            {
                "bridge_report_status": bridge_report.get("status"),
                "soak_report_status": soak_report.get("status"),
            },
        )
    )
    checks.append(
        build_check(
            "source_inputs",
            wav_metadata is not None
            and wav_metadata.get("sample_rate_hz") == audio_input.get("sample_rate_hz")
            and wav_metadata.get("channels") == audio_input.get("channels")
            and wav_metadata.get("frames") == audio_input.get("frames")
            and wav_metadata.get("duration_seconds") == audio_input.get("duration_seconds")
            and source_video_integrity is not None
            and source_video_integrity == bridge_consistency.get("source_video_integrity")
            and bridge_consistency.get("source_video_sha256") == source_video_integrity.get("sha256"),
            {
                "audio_path": str(audio_path),
                "audio_manifest": audio_input,
                "audio_actual": wav_metadata,
                "video_path": str(video_path),
                "video_actual_integrity": source_video_integrity,
                "bridge_consistency": bridge_consistency,
            },
        )
    )
    checks.append(
        build_check(
            "bridge_preflight_reuse",
            isinstance(bridge_consistency, dict)
            and isinstance(preflight, dict)
            and set(preflight.get("required_checks", [])) == REQUIRED_PREFLIGHT_CHECKS
            and runtime_executor.get("backoff_seconds")
            == manifest.get("runtime_executor", {}).get("backoff_seconds")
            and set(stage8_ops.get("required_runtime_reports", []))
            == {
                f"{runtime_observability.get('log_dir')}/{runtime_observability.get('preflight_report_file')}",
                f"{runtime_observability.get('log_dir')}/{runtime_observability.get('runtime_report_file')}",
                f"{runtime_observability.get('log_dir')}/{runtime_observability.get('exit_report_file')}",
            },
            {
                "bridge_consistency": bridge_consistency,
                "preflight": preflight,
                "runtime_executor": runtime_executor,
                "required_runtime_reports": stage8_ops.get("required_runtime_reports"),
            },
        )
    )
    checks.append(
        build_check(
            "repo_toolchain",
            ffmpeg_version is not None
            and ffmpeg_version.returncode == 0
            and ffprobe_version is not None
            and ffprobe_version.returncode == 0
            and protocols_run is not None
            and protocols_run.returncode == 0
            and "rtmps" in protocol_sections["Output"]
            and "--enable-openssl" in configure_line
            and "--enable-libx264" in configure_line
            and Path(ffmpeg_bin) == Path(manifest.get("live_command", {}).get("ffmpeg_bin", ""))
            and Path(ffprobe_bin) == Path(manifest.get("smoke_generation", {}).get("ffprobe_bin", "")),
            {
                "ffmpeg_bin": ffmpeg_bin,
                "ffprobe_bin": ffprobe_bin,
                "expected_ffmpeg_bin": manifest.get("live_command", {}).get("ffmpeg_bin"),
                "expected_ffprobe_bin": manifest.get("smoke_generation", {}).get("ffprobe_bin"),
                "output_protocols": sorted(protocol_sections["Output"]),
                "configure_line": configure_line,
            },
        )
    )
    checks.append(
        build_check(
            "runtime_entry",
            run_script_path.exists()
            and run_script_path.stat().st_mode & 0o111 != 0
            and Path(runtime_observability.get("runtime_tool_path", "")).exists()
            and Path(runtime_observability.get("classifier_tool_path", "")).exists()
            and args_payload.get("url_env_var") in stage8_ops.get("required_env_vars", [])
            and log_dir.exists()
            and Path(sample_retention.get("tool_path", "")).exists(),
            {
                "run_script_path": str(run_script_path),
                "runtime_tool_path": runtime_observability.get("runtime_tool_path"),
                "classifier_tool_path": runtime_observability.get("classifier_tool_path"),
                "sample_retention_tool_path": sample_retention.get("tool_path"),
                "log_dir": str(log_dir),
                "required_env_vars": stage8_ops.get("required_env_vars"),
            },
        )
    )

    failed = [check for check in checks if check["status"] == "failed"]
    env_var = (stage8_ops.get("required_env_vars") or ["MUSIKALISCHES_RTMP_URL"])[0]
    loop_env = manifest.get("live_command", {}).get("loop_control_env", "MUSIKALISCHES_STAGE7_LOOP_MODE")
    budget_env = manifest.get("live_command", {}).get(
        "max_runtime_env",
        "MUSIKALISCHES_STAGE7_MAX_RUNTIME_SECONDS",
    )
    report = {
        "stage": "stage8_ops_readiness",
        "status": "passed" if not failed else "failed",
        "summary": {
            "checks_total": len(checks),
            "checks_failed": len(failed),
            "work_id": manifest.get("work_id"),
            "entry_script_file": run_script_path.name,
            "required_env_var": env_var,
            "recommended_loop_mode": stage8_ops.get("recommended_loop_mode"),
        },
        "checks": checks,
        "ops_entry": {
            "guide_file": stage8_ops.get("guide_file"),
            "foreground_preflight_example": (
                f"export {env_var}='rtmps://...'; export {loop_env}=infinite; "
                f"export {budget_env}=120; {run_script_path}"
            ),
            "foreground_soak_example": (
                f"export {env_var}='rtmps://...'; export {loop_env}=infinite; {run_script_path}"
            ),
            "sample_retention_example": (
                "make -C src/musikalisches stage8-sample-retain "
                "STAGE8_RUN_LABEL=<label>"
            ),
            "background_files": stage8_ops.get("background_files"),
            "required_runtime_reports": stage8_ops.get("required_runtime_reports"),
            "sample_retention": sample_retention,
        },
    }
    write_json(readiness_report_path, report)

    if failed:
        return fail([f"{check['check_id']}: {check['details']}" for check in failed])

    print("stage8 ops readiness validation passed")
    print(f"artifact_dir: {artifact_dir}")
    print(f"entry_script: {run_script_path}")
    print(f"required_env_var: {env_var}")
    print(f"report_file: {readiness_report_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
