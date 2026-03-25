#!/usr/bin/env python3

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
from math import ceil
from pathlib import Path

from stage7_bridge_profile import validate_bridge_profile_payload


REPO_ROOT = Path(__file__).resolve().parents[3]
STAGE8_GUIDE_PATH = REPO_ROOT / "docs" / "plans" / "260324-stage8-real-soak-ops-guide.md"
REQUIRED_FILES = {
    "stage7_bridge_profile.json",
    "stream_bridge_manifest.json",
    "stream_bridge_ffmpeg_args.json",
    "run_stage7_stream_bridge.sh",
    "stage7_failure_taxonomy.json",
    "stage7_soak_plan.json",
}
REQUIRED_FAILURE_CLASSES = {
    "clean_exit",
    "runtime_limit_reached",
    "interrupted",
    "handshake_failure",
    "auth_failure",
    "network_jitter",
    "remote_disconnect",
    "unknown_failure",
}
REQUIRED_PREFLIGHT_CHECKS = {
    "protocol_support",
    "dns_resolution",
    "tcp_connectivity",
    "publish_probe",
}


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


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


def build_check(check_id: str, passed: bool, details: dict) -> dict:
    return {
        "check_id": check_id,
        "status": "passed" if passed else "failed",
        "details": details,
    }


def fail(errors: list[str]) -> int:
    print("stage7 stream bridge validation failed:")
    for error in errors:
        print(f"- {error}")
    return 1


def write_report(output_dir: Path, manifest: dict, checks: list[dict]) -> dict:
    failed = [check for check in checks if check["status"] == "failed"]
    report = {
        "stage": "stage7_stream_bridge",
        "status": "passed" if not failed else "failed",
        "summary": {
            "checks_total": len(checks),
            "checks_failed": len(failed),
            "work_id": manifest.get("work_id"),
            "duration_seconds": manifest.get("bridge_summary", {}).get("duration_seconds"),
            "video_fps": manifest.get("bridge_summary", {}).get("video_fps"),
            "default_loop_mode": manifest.get("bridge_summary", {}).get("default_loop_mode"),
            "soak_runtime_hours": manifest.get("soak_plan_summary", {}).get("minimum_runtime_hours"),
            "smoke_generated": manifest.get("smoke_generation", {}).get("generated", False),
        },
        "checks": checks,
    }
    (output_dir / "stage7_bridge_validation_report.json").write_text(
        json.dumps(report, ensure_ascii=True, indent=2) + "\n",
        encoding="utf-8",
    )
    return report


def parse_rate(value: str | None) -> float | None:
    if not value:
        return None
    if "/" in value:
        numerator, denominator = value.split("/", 1)
        try:
            numerator_value = float(numerator)
            denominator_value = float(denominator)
        except ValueError:
            return None
        if denominator_value == 0:
            return None
        return numerator_value / denominator_value
    try:
        return float(value)
    except ValueError:
        return None


def float_close(left: float | None, right: float | None, tolerance: float) -> bool:
    if left is None or right is None:
        return False
    return abs(left - right) <= tolerance


def int_close(left: int | None, right: int | None, tolerance: int) -> bool:
    if left is None or right is None:
        return False
    return abs(left - right) <= tolerance


def probe_keyframes(path: Path, ffprobe_bin: str | None, fps: float | None) -> dict | None:
    if not ffprobe_bin or not path.exists():
        return None
    result = subprocess.run(
        [
            ffprobe_bin,
            "-v",
            "error",
            "-skip_frame",
            "nokey",
            "-select_streams",
            "v:0",
            "-show_entries",
            "frame=best_effort_timestamp_time",
            "-of",
            "json",
            str(path),
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return None
    payload = json.loads(result.stdout)
    timestamps = [
        round(float(frame["best_effort_timestamp_time"]), 6)
        for frame in payload.get("frames", [])
        if frame.get("best_effort_timestamp_time") not in {None, ""}
    ]
    intervals = [
        round(timestamps[index + 1] - timestamps[index], 6)
        for index in range(len(timestamps) - 1)
    ]
    max_interval_seconds = max(intervals) if intervals else None
    max_interval_frames = (
        round(max_interval_seconds * fps)
        if max_interval_seconds is not None and fps is not None
        else None
    )
    return {
        "status": "ok",
        "count": len(timestamps),
        "timestamps_seconds": timestamps,
        "first_timestamp_seconds": timestamps[0] if timestamps else None,
        "last_timestamp_seconds": timestamps[-1] if timestamps else None,
        "max_interval_seconds": round(max_interval_seconds, 6)
        if max_interval_seconds is not None
        else None,
        "max_interval_frames": max_interval_frames,
    }


def count_video_frames(path: Path, ffprobe_bin: str | None) -> tuple[str | None, int | None]:
    if not ffprobe_bin or not path.exists():
        return None, None
    result = subprocess.run(
        [
            ffprobe_bin,
            "-v",
            "error",
            "-count_frames",
            "-select_streams",
            "v:0",
            "-show_entries",
            "stream=nb_read_frames",
            "-of",
            "json",
            str(path),
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return None, None
    payload = json.loads(result.stdout)
    stream = payload.get("streams", [{}])[0]
    nb_read_frames = stream.get("nb_read_frames")
    return (
        nb_read_frames,
        int(nb_read_frames) if str(nb_read_frames or "").isdigit() else None,
    )


def probe_media(path: Path) -> dict | None:
    ffprobe_bin = shutil.which("ffprobe")
    if not ffprobe_bin or not path.exists():
        return None
    result = subprocess.run(
        [
            ffprobe_bin,
            "-v",
            "error",
            "-show_entries",
            "stream=index,codec_type,codec_name,width,height,avg_frame_rate,r_frame_rate,nb_frames,sample_rate,channels",
            "-show_entries",
            "format=format_name,duration,size",
            "-of",
            "json",
            str(path),
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return None
    payload = json.loads(result.stdout)
    streams = payload.get("streams", [])
    video_stream = next((stream for stream in streams if stream.get("codec_type") == "video"), {})
    audio_stream = next((stream for stream in streams if stream.get("codec_type") == "audio"), {})
    avg_frame_rate_value = parse_rate(video_stream.get("avg_frame_rate"))
    counted_frames, counted_frames_value = count_video_frames(path, ffprobe_bin)
    keyframes = probe_keyframes(path, ffprobe_bin, avg_frame_rate_value)
    return {
        "status": "ok",
        "stream_count": len(streams),
        "video_stream_count": sum(1 for stream in streams if stream.get("codec_type") == "video"),
        "audio_stream_count": sum(1 for stream in streams if stream.get("codec_type") == "audio"),
        "format_name": payload.get("format", {}).get("format_name"),
        "duration_seconds": parse_rate(payload.get("format", {}).get("duration")),
        "file_size_bytes": int(payload.get("format", {}).get("size", 0) or 0),
        "video_codec_name": video_stream.get("codec_name"),
        "width": video_stream.get("width"),
        "height": video_stream.get("height"),
        "pix_fmt": video_stream.get("pix_fmt"),
        "avg_frame_rate": video_stream.get("avg_frame_rate"),
        "avg_frame_rate_value": avg_frame_rate_value,
        "r_frame_rate": video_stream.get("r_frame_rate"),
        "r_frame_rate_value": parse_rate(video_stream.get("r_frame_rate")),
        "video_nb_frames": video_stream.get("nb_frames"),
        "video_nb_frames_value": (
            int(video_stream["nb_frames"])
            if str(video_stream.get("nb_frames", "")).isdigit()
            else counted_frames_value
        ),
        "video_nb_read_frames": counted_frames,
        "audio_codec_name": audio_stream.get("codec_name"),
        "audio_sample_rate_hz": int(audio_stream.get("sample_rate", 0) or 0),
        "audio_channels": audio_stream.get("channels"),
        "audio_channel_layout": audio_stream.get("channel_layout"),
        "streams": [
            {
                "index": stream.get("index"),
                "codec_type": stream.get("codec_type"),
                "codec_name": stream.get("codec_name"),
                "pix_fmt": stream.get("pix_fmt"),
                "width": stream.get("width"),
                "height": stream.get("height"),
                "avg_frame_rate": stream.get("avg_frame_rate"),
                "avg_frame_rate_value": parse_rate(stream.get("avg_frame_rate")),
                "r_frame_rate": stream.get("r_frame_rate"),
                "r_frame_rate_value": parse_rate(stream.get("r_frame_rate")),
                "nb_frames": stream.get("nb_frames"),
                "nb_frames_value": (
                    int(stream["nb_frames"])
                    if str(stream.get("nb_frames", "")).isdigit()
                    else None
                ),
                "sample_rate": stream.get("sample_rate"),
                "sample_rate_value": int(stream.get("sample_rate", 0) or 0)
                if str(stream.get("sample_rate", "")).isdigit()
                else None,
                "channels": stream.get("channels"),
                "channel_layout": stream.get("channel_layout"),
            }
            for stream in streams
        ],
        "container": {
            "format_name": payload.get("format", {}).get("format_name"),
            "duration_seconds": parse_rate(payload.get("format", {}).get("duration")),
            "file_size_bytes": int(payload.get("format", {}).get("size", 0) or 0),
        },
        "keyframes": keyframes,
    }


def build_probe_summary(probe: dict | None) -> dict | None:
    if not isinstance(probe, dict) or probe.get("status") != "ok":
        return None
    keyframes = probe.get("keyframes") if isinstance(probe.get("keyframes"), dict) else {}
    container = probe.get("container") if isinstance(probe.get("container"), dict) else {}
    streams = probe.get("streams") if isinstance(probe.get("streams"), list) else []
    video_stream = next(
        (
            stream
            for stream in streams
            if isinstance(stream, dict) and stream.get("codec_type") == "video"
        ),
        {},
    )
    return {
        "width": probe.get("width"),
        "height": probe.get("height"),
        "video_codec_name": probe.get("video_codec_name", video_stream.get("codec_name")),
        "avg_frame_rate_value": probe.get("avg_frame_rate_value"),
        "video_nb_frames_value": probe.get(
            "video_nb_frames_value",
            probe.get("nb_frames_value", video_stream.get("nb_frames_value")),
        ),
        "duration_seconds": probe.get("duration_seconds"),
        "video_stream_count": probe.get("video_stream_count"),
        "audio_stream_count": probe.get("audio_stream_count"),
        "container_format_name": container.get("format_name", probe.get("format_name")),
        "keyframe_interval_frames": keyframes.get("max_interval_frames"),
    }


def validate_failure_taxonomy_payload(payload: object) -> list[str]:
    if not isinstance(payload, dict):
        return ["failure taxonomy must be a JSON object"]

    errors: list[str] = []
    if not isinstance(payload.get("taxonomy_id"), str) or not payload["taxonomy_id"].strip():
        errors.append("failure taxonomy taxonomy_id must be a non-empty string")
    if not isinstance(payload.get("default_class_id"), str) or not payload["default_class_id"].strip():
        errors.append("failure taxonomy default_class_id must be a non-empty string")
    classes = payload.get("classes")
    if not isinstance(classes, list) or not classes:
        errors.append("failure taxonomy classes must be a non-empty list")
        return errors

    class_ids: list[str] = []
    for index, entry in enumerate(classes):
        if not isinstance(entry, dict):
            errors.append(f"failure taxonomy classes[{index}] must be an object")
            continue
        class_id = entry.get("class_id")
        if not isinstance(class_id, str) or not class_id.strip():
            errors.append(f"failure taxonomy classes[{index}].class_id must be a non-empty string")
        else:
            class_ids.append(class_id)
        if not isinstance(entry.get("description"), str) or not entry["description"].strip():
            errors.append(f"failure taxonomy classes[{index}].description must be a non-empty string")
        if not isinstance(entry.get("retryable"), bool):
            errors.append(f"failure taxonomy classes[{index}].retryable must be a boolean")
        if not isinstance(entry.get("match_any"), list):
            errors.append(f"failure taxonomy classes[{index}].match_any must be a list")
        if not isinstance(entry.get("match_exit_codes"), list):
            errors.append(f"failure taxonomy classes[{index}].match_exit_codes must be a list")

    if len(class_ids) != len(set(class_ids)):
        errors.append("failure taxonomy class_id values must be unique")
    if payload.get("default_class_id") not in class_ids:
        errors.append("failure taxonomy default_class_id must match one declared class_id")
    return errors


def validate_soak_plan_payload(payload: object) -> list[str]:
    if not isinstance(payload, dict):
        return ["soak plan must be a JSON object"]

    errors: list[str] = []
    if payload.get("stage") != "stage7_pre_stage8_soak":
        errors.append("soak plan stage must equal stage7_pre_stage8_soak")
    if payload.get("status") != "ready":
        errors.append("soak plan status must equal ready")
    if not isinstance(payload.get("bridge_profile_id"), str) or not payload["bridge_profile_id"].strip():
        errors.append("soak plan bridge_profile_id must be a non-empty string")
    minimum_runtime_hours = payload.get("minimum_runtime_hours")
    minimum_runtime_seconds = payload.get("minimum_runtime_seconds")
    if not isinstance(minimum_runtime_hours, int) or minimum_runtime_hours <= 0:
        errors.append("soak plan minimum_runtime_hours must be a positive integer")
    if (
        not isinstance(minimum_runtime_seconds, int)
        or minimum_runtime_seconds <= 0
        or (
            isinstance(minimum_runtime_hours, int)
            and minimum_runtime_seconds != minimum_runtime_hours * 3600
        )
    ):
        errors.append("soak plan minimum_runtime_seconds must equal minimum_runtime_hours * 3600")
    source_duration_seconds = payload.get("source_duration_seconds")
    if not isinstance(source_duration_seconds, (int, float)) or source_duration_seconds <= 0:
        errors.append("soak plan source_duration_seconds must be positive")
    if not isinstance(payload.get("expected_source_loop_iterations"), int) or payload.get(
        "expected_source_loop_iterations"
    ) <= 0:
        errors.append("soak plan expected_source_loop_iterations must be a positive integer")
    drift_budget = payload.get("drift_budget")
    if not isinstance(drift_budget, dict):
        errors.append("soak plan drift_budget must be an object")
    else:
        drift_per_hour = drift_budget.get("max_abs_drift_seconds_per_hour")
        if not isinstance(drift_per_hour, (int, float)) or drift_per_hour <= 0:
            errors.append("soak plan drift_budget.max_abs_drift_seconds_per_hour must be positive")
        if not isinstance(drift_budget.get("measurement_basis"), str) or not drift_budget[
            "measurement_basis"
        ].strip():
            errors.append("soak plan drift_budget.measurement_basis must be a non-empty string")
    reconnect_policy = payload.get("reconnect_policy")
    preflight_policy = payload.get("preflight_policy")
    if not isinstance(preflight_policy, dict):
        errors.append("soak plan preflight_policy must be an object")
    else:
        if set(preflight_policy.get("required_checks", [])) != REQUIRED_PREFLIGHT_CHECKS:
            errors.append("soak plan preflight_policy.required_checks must match the frozen preflight checks")
        if not isinstance(preflight_policy.get("failure_class_hints"), dict):
            errors.append("soak plan preflight_policy.failure_class_hints must be an object")
        elif set(preflight_policy["failure_class_hints"]) != REQUIRED_PREFLIGHT_CHECKS:
            errors.append("soak plan preflight_policy.failure_class_hints keys must match required_checks")
    if not isinstance(reconnect_policy, dict):
        errors.append("soak plan reconnect_policy must be an object")
    else:
        if not isinstance(reconnect_policy.get("retryable_classes"), list):
            errors.append("soak plan reconnect_policy.retryable_classes must be a list")
        if not isinstance(reconnect_policy.get("non_retryable_classes"), list):
            errors.append("soak plan reconnect_policy.non_retryable_classes must be a list")
        if not isinstance(reconnect_policy.get("max_consecutive_retryable_failures"), int) or reconnect_policy.get(
            "max_consecutive_retryable_failures"
        ) <= 0:
            errors.append(
                "soak plan reconnect_policy.max_consecutive_retryable_failures must be a positive integer"
            )
        if not isinstance(reconnect_policy.get("backoff_seconds"), list) or not reconnect_policy.get(
            "backoff_seconds"
        ):
            errors.append("soak plan reconnect_policy.backoff_seconds must be a non-empty list")
    if not isinstance(payload.get("required_runtime_files"), list) or not payload.get(
        "required_runtime_files"
    ):
        errors.append("soak plan required_runtime_files must be a non-empty list")
    if not isinstance(payload.get("exit_classification_coverage"), list) or not payload.get(
        "exit_classification_coverage"
    ):
        errors.append("soak plan exit_classification_coverage must be a non-empty list")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Validate a stage7 stream bridge artifact directory."
    )
    parser.add_argument(
        "artifact_dir",
        nargs="?",
        default="ops/out/stream-bridge",
        help="stage7 bridge artifact directory containing stream_bridge_manifest.json",
    )
    args = parser.parse_args()

    artifact_dir = Path(args.artifact_dir).resolve()
    if not artifact_dir.exists():
        return fail([f"artifact directory does not exist: {artifact_dir}"])

    file_names = {path.name for path in artifact_dir.iterdir() if path.is_file()}
    missing = sorted(REQUIRED_FILES - file_names)
    if missing:
        return fail([f"missing files: {', '.join(missing)}"])

    profile = load_json(artifact_dir / "stage7_bridge_profile.json")
    manifest = load_json(artifact_dir / "stream_bridge_manifest.json")
    args_payload = load_json(artifact_dir / "stream_bridge_ffmpeg_args.json")
    failure_taxonomy = load_json(artifact_dir / "stage7_failure_taxonomy.json")
    soak_plan = load_json(artifact_dir / "stage7_soak_plan.json")
    run_script = (artifact_dir / "run_stage7_stream_bridge.sh").read_text(encoding="utf-8")
    checks: list[dict] = []

    profile_errors = validate_bridge_profile_payload(profile, allow_output_metadata=True)
    failure_taxonomy_errors = validate_failure_taxonomy_payload(failure_taxonomy)
    soak_plan_errors = validate_soak_plan_payload(soak_plan)
    bridge_summary = manifest.get("bridge_summary", {})
    loop_bridge = manifest.get("loop_bridge", {})
    runtime_observability = manifest.get("runtime_observability", {})
    preflight = manifest.get("preflight", {})
    runtime_executor = manifest.get("runtime_executor", {})
    smoke_generation = manifest.get("smoke_generation", {})
    smoke_output_path = artifact_dir / smoke_generation.get("output_file", "")
    smoke_generated = smoke_generation.get("generated", False)
    smoke_expected = smoke_generation.get("requested", False)
    local_probe = probe_media(smoke_output_path) if smoke_generation.get("generated") else None
    manifest_probe = smoke_generation.get("probe")
    smoke_probe = local_probe or manifest_probe
    probe_source = (
        "local_ffprobe"
        if local_probe is not None
        else "manifest"
        if manifest_probe is not None
        else "none"
    )
    expected_duration = smoke_generation.get(
        "expected_duration_seconds",
        bridge_summary.get("duration_seconds"),
    )
    expected_fps = smoke_generation.get("expected_fps", bridge_summary.get("video_fps"))
    expected_frame_count = smoke_generation.get("expected_frame_count")
    frame_count_tolerance = smoke_generation.get("frame_count_tolerance", 0)
    fps_tolerance = smoke_generation.get("fps_tolerance", 0.01)
    duration_tolerance = smoke_generation.get("duration_tolerance_seconds", 0.1)
    expected_keyframe_interval_frames = smoke_generation.get(
        "expected_keyframe_interval_frames"
    )
    keyframe_interval_tolerance = smoke_generation.get(
        "keyframe_interval_tolerance_frames", 0
    )
    expected_stream_layout = smoke_generation.get("expected_stream_layout", {})
    artifact_integrity = manifest.get("artifact_integrity", {})
    required_integrity_files = {
        "stage7_bridge_profile.json",
        "stream_bridge_ffmpeg_args.json",
        "run_stage7_stream_bridge.sh",
        "stage7_failure_taxonomy.json",
        "stage7_soak_plan.json",
    }
    if smoke_generation.get("generated"):
        required_integrity_files.add(smoke_generation.get("output_file", ""))
    video_manifest_path = Path(manifest.get("source_video_artifact_dir", "")) / "video_render_manifest.json"
    stage6_manifest = load_json(video_manifest_path) if video_manifest_path.exists() else {}
    video_input = manifest.get("video_input", {})
    source_video_path = Path(video_input.get("path", ""))
    source_video_contract = video_input.get("source_contract", {})
    source_video_integrity = video_input.get("artifact_integrity")
    source_video_actual_integrity = (
        build_file_integrity(source_video_path)
        if source_video_path.exists() and source_video_path.is_file()
        else None
    )
    source_probe = probe_media(source_video_path) if source_video_path.exists() else None
    if source_probe is None:
        source_probe = stage6_manifest.get("mp4_generation", {}).get("probe")
    source_probe_summary = build_probe_summary(source_probe)
    bridge_consistency = manifest.get("bridge_consistency", {})
    stage8_ops = manifest.get("stage8_ops", {})
    expected_bridge_tolerance = {
        "fps": round(
            (source_video_contract.get("fps_tolerance") or 0)
            + (smoke_generation.get("fps_tolerance") or 0),
            6,
        ),
        "frame_count": (source_video_contract.get("frame_count_tolerance") or 0)
        + (smoke_generation.get("frame_count_tolerance") or 0),
        "duration_seconds": round(
            (source_video_contract.get("duration_tolerance_seconds") or 0)
            + (smoke_generation.get("duration_tolerance_seconds") or 0),
            6,
        ),
        "keyframe_interval_frames": (
            source_video_contract.get("keyframe_interval_tolerance_frames") or 0
        )
        + (smoke_generation.get("keyframe_interval_tolerance_frames") or 0),
    }
    expected_bridge_matches = {
        "width": (source_probe_summary or {}).get("width"),
        "height": (source_probe_summary or {}).get("height"),
        "video_codec_name": (source_probe_summary or {}).get("video_codec_name"),
        "avg_frame_rate_value": (source_probe_summary or {}).get("avg_frame_rate_value"),
        "video_nb_frames_value": (source_probe_summary or {}).get("video_nb_frames_value"),
        "duration_seconds": (source_probe_summary or {}).get("duration_seconds"),
        "keyframe_interval_frames": (source_probe_summary or {}).get(
            "keyframe_interval_frames"
        ),
    }
    expected_stage8_ops = {
        "guide_file": str(STAGE8_GUIDE_PATH),
        "entry_script_file": "run_stage7_stream_bridge.sh",
        "required_env_vars": [profile.get("ingest", {}).get("stream_url_env")],
        "supported_loop_modes": ["once", "infinite"],
        "recommended_loop_mode": loop_bridge.get("default_loop_mode"),
        "formal_soak_runtime_budget_policy": "unset_for_formal_soak",
        "preflight_runtime_budget_example_seconds": 120,
        "background_files": {
            "console_log_file": f"{runtime_observability.get('log_dir')}/stage8_soak_console.log",
            "pid_file": f"{runtime_observability.get('log_dir')}/stage8_soak.pid",
        },
        "required_validation_reports": [
            "stage7_bridge_validation_report.json",
            "stage7_soak_validation_report.json",
        ],
        "required_runtime_reports": [
            f"{runtime_observability.get('log_dir')}/{runtime_observability.get('preflight_report_file')}",
            f"{runtime_observability.get('log_dir')}/{runtime_observability.get('runtime_report_file')}",
            f"{runtime_observability.get('log_dir')}/{runtime_observability.get('exit_report_file')}",
        ],
        "readiness_report_file": "stage8_ops_readiness_report.json",
    }

    failure_classes = failure_taxonomy.get("classes", [])
    failure_class_ids = [
        entry.get("class_id") for entry in failure_classes if isinstance(entry, dict)
    ]
    retryable_failure_class_ids = [
        entry.get("class_id")
        for entry in failure_classes
        if isinstance(entry, dict) and entry.get("retryable") is True
    ]
    non_retryable_failure_class_ids = [
        entry.get("class_id")
        for entry in failure_classes
        if isinstance(entry, dict) and entry.get("retryable") is False
    ]
    log_dir = artifact_dir / runtime_observability.get("log_dir", "")
    source_cycle_duration = loop_bridge.get("source_cycle_duration_seconds")
    source_cycle_count = loop_bridge.get("source_cycle_count")

    checks.append(
        build_check(
            "artifact_integrity_manifest",
            isinstance(artifact_integrity, dict)
            and set(artifact_integrity) == required_integrity_files,
            {
                "artifact_integrity_files": sorted(artifact_integrity),
                "required_files": sorted(required_integrity_files),
            },
        )
    )
    checks.append(
        build_check(
            "artifact_integrity",
            isinstance(artifact_integrity, dict)
            and all(
                artifact_integrity.get(path.name) == build_file_integrity(path)
                for path in [
                    artifact_dir / "stage7_bridge_profile.json",
                    artifact_dir / "stream_bridge_ffmpeg_args.json",
                    artifact_dir / "run_stage7_stream_bridge.sh",
                    artifact_dir / "stage7_failure_taxonomy.json",
                    artifact_dir / "stage7_soak_plan.json",
                ]
            )
            and (
                not smoke_generation.get("generated")
                or artifact_integrity.get(smoke_output_path.name)
                == build_file_integrity(smoke_output_path)
            ),
            {
                "artifact_integrity": artifact_integrity,
                "smoke_output_file": str(smoke_output_path),
            },
        )
    )
    checks.append(
        build_check(
            "stage",
            manifest.get("stage") == "stage7_stream_bridge"
            and args_payload.get("stage") == "stage7_stream_bridge",
            {
                "manifest_stage": manifest.get("stage"),
                "args_stage": args_payload.get("stage"),
            },
        )
    )
    checks.append(
        build_check(
            "profile_contract",
            not profile_errors,
            {
                "error_count": len(profile_errors),
                "errors": profile_errors,
            },
        )
    )
    checks.append(
        build_check(
            "profile_identity",
            manifest.get("bridge_profile_id") == profile.get("profile_id")
            and manifest.get("bridge_profile_source") == profile.get("source")
            and manifest.get("bridge_profile_path") == profile.get("source_path"),
            {
                "manifest_profile_id": manifest.get("bridge_profile_id"),
                "profile_id": profile.get("profile_id"),
                "manifest_profile_source": manifest.get("bridge_profile_source"),
                "profile_source": profile.get("source"),
                "manifest_profile_path": manifest.get("bridge_profile_path"),
                "profile_path": profile.get("source_path"),
            },
        )
    )
    checks.append(
        build_check(
            "source_status",
            manifest.get("source_audio_stage") == "stage5_m1_runtime"
            and manifest.get("source_video_stage") == "stage6_video_render",
            {
                "source_audio_stage": manifest.get("source_audio_stage"),
                "source_video_stage": manifest.get("source_video_stage"),
            },
        )
    )
    checks.append(
        build_check(
            "source_video_contract",
            video_manifest_path.exists()
            and source_video_integrity
            == stage6_manifest.get("artifact_integrity", {}).get("offline_preview.mp4")
            and source_video_contract.get("expected_frame_count")
            == stage6_manifest.get("mp4_generation", {}).get("expected_frame_count")
            and source_video_contract.get("frame_count_tolerance")
            == stage6_manifest.get("mp4_generation", {}).get("frame_count_tolerance")
            and source_video_contract.get("expected_fps")
            == stage6_manifest.get("mp4_generation", {}).get("expected_fps")
            and source_video_contract.get("fps_tolerance")
            == stage6_manifest.get("mp4_generation", {}).get("fps_tolerance")
            and source_video_contract.get("expected_duration_seconds")
            == stage6_manifest.get("mp4_generation", {}).get("expected_duration_seconds")
            and source_video_contract.get("duration_tolerance_seconds")
            == stage6_manifest.get("mp4_generation", {}).get("duration_tolerance_seconds")
            and source_video_contract.get("expected_keyframe_interval_frames")
            == stage6_manifest.get("mp4_generation", {}).get(
                "expected_keyframe_interval_frames"
            )
            and source_video_contract.get("keyframe_interval_tolerance_frames")
            == stage6_manifest.get("mp4_generation", {}).get(
                "keyframe_interval_tolerance_frames"
            )
            and source_video_contract.get("expected_stream_layout")
            == stage6_manifest.get("mp4_generation", {}).get("expected_stream_layout"),
            {
                "source_video_manifest": str(video_manifest_path),
                "source_video_integrity": source_video_integrity,
                "source_video_contract": source_video_contract,
            },
        )
    )
    checks.append(
        build_check(
            "bridge_consistency",
            not smoke_generated
            or (
                isinstance(bridge_consistency, dict)
                and bridge_consistency.get("source_manifest_path") == str(video_manifest_path)
                and bridge_consistency.get("source_video_file") == source_video_path.name
                and bridge_consistency.get("source_video_sha256")
                == (source_video_integrity or {}).get("sha256")
                and bridge_consistency.get("source_video_integrity") == source_video_integrity
                and source_video_actual_integrity == source_video_integrity
                and bridge_consistency.get("source_probe_summary") == source_probe_summary
                and bridge_consistency.get("smoke_output_file") == smoke_generation.get("output_file")
                and bridge_consistency.get("smoke_probe_path") == "smoke_generation.probe"
                and bridge_consistency.get("comparison_tolerance") == expected_bridge_tolerance
                and bridge_consistency.get("expected_stream_delta")
                == {
                    "video_stream_count": 0,
                    "audio_stream_count": 1,
                }
                and bridge_consistency.get("expected_matches") == expected_bridge_matches
                and isinstance(smoke_probe, dict)
                and source_probe_summary is not None
                and smoke_probe.get("width") == source_probe_summary.get("width")
                and smoke_probe.get("height") == source_probe_summary.get("height")
                and smoke_probe.get("video_codec_name")
                == source_probe_summary.get("video_codec_name")
                and float_close(
                    smoke_probe.get("avg_frame_rate_value"),
                    source_probe_summary.get("avg_frame_rate_value"),
                    expected_bridge_tolerance["fps"],
                )
                and int_close(
                    smoke_probe.get("video_nb_frames_value"),
                    source_probe_summary.get("video_nb_frames_value"),
                    expected_bridge_tolerance["frame_count"],
                )
                and float_close(
                    smoke_probe.get("duration_seconds"),
                    source_probe_summary.get("duration_seconds"),
                    expected_bridge_tolerance["duration_seconds"],
                )
                and int_close(
                    (smoke_probe.get("keyframes") or {}).get("max_interval_frames"),
                    source_probe_summary.get("keyframe_interval_frames"),
                    expected_bridge_tolerance["keyframe_interval_frames"],
                )
                and smoke_probe.get("video_stream_count") - source_probe_summary.get("video_stream_count")
                == bridge_consistency.get("expected_stream_delta", {}).get("video_stream_count")
                and smoke_probe.get("audio_stream_count") - source_probe_summary.get("audio_stream_count")
                == bridge_consistency.get("expected_stream_delta", {}).get("audio_stream_count")
            ),
            {
                "source_video_path": str(source_video_path),
                "source_video_integrity": source_video_integrity,
                "source_video_actual_integrity": source_video_actual_integrity,
                "source_probe_summary": source_probe_summary,
                "bridge_consistency": bridge_consistency,
                "smoke_probe": smoke_probe,
            },
        )
    )
    checks.append(
        build_check(
            "stage8_ops_contract",
            isinstance(stage8_ops, dict)
            and stage8_ops == expected_stage8_ops
            and Path(stage8_ops.get("guide_file", "")).exists(),
            {
                "stage8_ops": stage8_ops,
                "expected_stage8_ops": expected_stage8_ops,
            },
        )
    )
    checks.append(
        build_check(
            "bridge_freeze",
            bridge_summary.get("video_width") == profile.get("video", {}).get("width")
            and bridge_summary.get("video_height") == profile.get("video", {}).get("height")
            and bridge_summary.get("video_fps") == profile.get("video", {}).get("fps")
            and bridge_summary.get("video_codec") == profile.get("video", {}).get("codec")
            and bridge_summary.get("video_encoder") == profile.get("video", {}).get("encoder")
            and bridge_summary.get("video_preset") == profile.get("video", {}).get("preset")
            and bridge_summary.get("video_pixel_format") == profile.get("video", {}).get("pixel_format")
            and bridge_summary.get("audio_codec") == profile.get("audio", {}).get("codec")
            and bridge_summary.get("audio_bitrate_kbps") == profile.get("audio", {}).get("bitrate_kbps")
            and bridge_summary.get("audio_sample_rate_hz") == profile.get("audio", {}).get("sample_rate_hz")
            and bridge_summary.get("audio_channels") == profile.get("audio", {}).get("channels")
            and bridge_summary.get("ingest_protocol") == profile.get("ingest", {}).get("protocol")
            and bridge_summary.get("ingest_container") == profile.get("ingest", {}).get("container"),
            {
                "bridge_summary": bridge_summary,
            },
        )
    )
    checks.append(
        build_check(
            "loop_bridge_contract",
            loop_bridge.get("default_loop_mode") == "infinite"
            and loop_bridge.get("loop_control_env") == args_payload.get("loop_control_env")
            and loop_bridge.get("max_runtime_env") == args_payload.get("max_runtime_env")
            and set((loop_bridge.get("supported_loop_modes") or {}).keys()) == {"once", "infinite"}
            and (loop_bridge.get("supported_loop_modes") or {}).get("infinite", {}).get("ffmpeg_stream_loop") == -1
            and (loop_bridge.get("supported_loop_modes") or {}).get("once", {}).get("ffmpeg_stream_loop") is None
            and float_close(
                loop_bridge.get("source_render_duration_seconds"),
                manifest.get("audio_input", {}).get("duration_seconds"),
                0.001,
            )
            and float_close(
                loop_bridge.get("video_render_duration_seconds"),
                manifest.get("video_input", {}).get("duration_seconds"),
                0.05,
            )
            and (
                source_cycle_duration is None
                or source_cycle_count is None
                or float_close(
                    source_cycle_duration * source_cycle_count,
                    loop_bridge.get("source_render_duration_seconds"),
                    0.05,
                )
            )
            and "-stream_loop -1" not in args_payload.get("live_redacted_shell_by_mode", {}).get("once", "")
            and "-stream_loop -1" in args_payload.get("live_redacted_shell_by_mode", {}).get("infinite", ""),
            {
                "loop_bridge": loop_bridge,
                "live_redacted_shell_by_mode": args_payload.get("live_redacted_shell_by_mode"),
            },
        )
    )
    checks.append(
        build_check(
            "live_command_redaction",
            manifest.get("live_command", {}).get("secrets_embedded") is False
            and args_payload.get("url_env_var") == profile.get("ingest", {}).get("stream_url_env")
            and "${" + profile.get("ingest", {}).get("stream_url_env", "") + "}" in args_payload.get(
                "live_redacted_shell", ""
            )
            and "${" + profile.get("ingest", {}).get("stream_url_env", "") + "}" in args_payload.get(
                "live_redacted_shell_by_mode", {}
            ).get("once", "")
            and f"--stream-url-env {profile.get('ingest', {}).get('stream_url_env', '')}" in run_script
            and "missing " + profile.get("ingest", {}).get("stream_url_env", "") in run_script
            and args_payload.get("loop_control_env", "") in run_script
            and args_payload.get("max_runtime_env", "") in run_script
            and "check ${SCRIPT_DIR}/logs/stage7_bridge_preflight_report.json first" in run_script
            and "stage7_bridge_runtime_report.json" in run_script
            and "stage7_bridge_latest.stderr.log" in run_script,
            {
                "url_env_var": args_payload.get("url_env_var"),
                "loop_control_env": args_payload.get("loop_control_env"),
                "max_runtime_env": args_payload.get("max_runtime_env"),
                "live_redacted_shell": args_payload.get("live_redacted_shell"),
            },
        )
    )
    checks.append(
        build_check(
            "runtime_observability",
            runtime_observability.get("log_dir")
            and runtime_observability.get("stderr_log_file")
            and runtime_observability.get("exit_report_file")
            and runtime_observability.get("preflight_log_file")
            and runtime_observability.get("preflight_report_file")
            and runtime_observability.get("runtime_report_file")
            and runtime_observability.get("attempt_log_pattern")
            and runtime_observability.get("attempt_report_pattern")
            and log_dir.exists()
            and Path(runtime_observability.get("runtime_tool_path", "")).name in run_script,
            {
                "runtime_observability": runtime_observability,
                "log_dir_exists": log_dir.exists(),
            },
        )
    )
    checks.append(
        build_check(
            "preflight_contract",
            set(preflight.get("required_checks", [])) == REQUIRED_PREFLIGHT_CHECKS
            and preflight.get("preflight_log_file") == runtime_observability.get("preflight_log_file")
            and preflight.get("preflight_report_file") == runtime_observability.get("preflight_report_file")
            and preflight.get("publish_probe_mode") == "ffmpeg_lightweight_publish"
            and isinstance(preflight.get("publish_probe_timeout_seconds"), int)
            and preflight.get("publish_probe_timeout_seconds") > 0
            and isinstance(preflight.get("tcp_connect_timeout_seconds"), int)
            and preflight.get("tcp_connect_timeout_seconds") > 0,
            {
                "preflight": preflight,
            },
        )
    )
    checks.append(
        build_check(
            "runtime_executor",
            runtime_executor.get("runtime_report_file") == runtime_observability.get("runtime_report_file")
            and runtime_executor.get("attempt_log_pattern") == runtime_observability.get("attempt_log_pattern")
            and runtime_executor.get("attempt_report_pattern")
            == runtime_observability.get("attempt_report_pattern")
            and runtime_executor.get("backoff_seconds")
            == soak_plan.get("reconnect_policy", {}).get("backoff_seconds")
            and runtime_executor.get("max_consecutive_retryable_failures")
            == soak_plan.get("reconnect_policy", {}).get("max_consecutive_retryable_failures"),
            {
                "runtime_executor": runtime_executor,
            },
        )
    )
    checks.append(
        build_check(
            "failure_taxonomy",
            not failure_taxonomy_errors
            and REQUIRED_FAILURE_CLASSES.issubset(set(failure_class_ids))
            and manifest.get("failure_policy", {}).get("taxonomy_id") == failure_taxonomy.get("taxonomy_id")
            and manifest.get("failure_policy", {}).get("default_class_id") == failure_taxonomy.get("default_class_id")
            and set(manifest.get("failure_policy", {}).get("retryable_classes", [])) == set(retryable_failure_class_ids)
            and set(manifest.get("failure_policy", {}).get("non_retryable_classes", []))
            == set(non_retryable_failure_class_ids),
            {
                "error_count": len(failure_taxonomy_errors),
                "errors": failure_taxonomy_errors,
                "failure_class_ids": failure_class_ids,
                "failure_policy": manifest.get("failure_policy"),
            },
        )
    )
    expected_source_loop_iterations = None
    if soak_plan.get("minimum_runtime_seconds") and soak_plan.get("source_duration_seconds"):
        expected_source_loop_iterations = ceil(
            soak_plan["minimum_runtime_seconds"] / soak_plan["source_duration_seconds"]
        )
    checks.append(
        build_check(
            "soak_plan_contract",
            not soak_plan_errors
            and soak_plan.get("bridge_profile_id") == manifest.get("bridge_profile_id")
            and soak_plan.get("minimum_runtime_hours", 0) >= 8
            and soak_plan.get("expected_source_loop_iterations") == expected_source_loop_iterations
            and set(soak_plan.get("preflight_policy", {}).get("required_checks", []))
            == REQUIRED_PREFLIGHT_CHECKS
            and set(soak_plan.get("reconnect_policy", {}).get("retryable_classes", []))
            == set(manifest.get("failure_policy", {}).get("retryable_classes", []))
            and set(soak_plan.get("required_runtime_files", []))
            == {
                f"{runtime_observability.get('log_dir')}/{runtime_observability.get('preflight_log_file')}",
                f"{runtime_observability.get('log_dir')}/{runtime_observability.get('preflight_report_file')}",
                f"{runtime_observability.get('log_dir')}/{runtime_observability.get('stderr_log_file')}",
                f"{runtime_observability.get('log_dir')}/{runtime_observability.get('exit_report_file')}",
                f"{runtime_observability.get('log_dir')}/{runtime_observability.get('runtime_report_file')}",
            },
            {
                "error_count": len(soak_plan_errors),
                "errors": soak_plan_errors,
                "soak_plan": soak_plan,
            },
        )
    )

    checks.append(
        build_check(
            "smoke_generation",
            (not smoke_expected and not smoke_generated)
            or (
                smoke_expected
                and smoke_generated
                and smoke_output_path.exists()
                and isinstance(smoke_probe, dict)
                and smoke_probe.get("width") == profile.get("video", {}).get("width")
                and smoke_probe.get("height") == profile.get("video", {}).get("height")
                and float_close(
                    smoke_probe.get("avg_frame_rate_value"),
                    expected_fps,
                    fps_tolerance,
                )
                and float_close(
                    smoke_probe.get("duration_seconds"),
                    expected_duration,
                    duration_tolerance,
                )
                and int_close(
                    smoke_probe.get("video_nb_frames_value"),
                    expected_frame_count,
                    frame_count_tolerance,
                )
            ),
            {
                "smoke_requested": smoke_expected,
                "smoke_generated": smoke_generated,
                "smoke_output_file": str(smoke_output_path),
                "probe_source": probe_source,
                "smoke_probe": smoke_probe,
                "expected_frame_count": expected_frame_count,
                "frame_count_tolerance": frame_count_tolerance,
                "expected_fps": expected_fps,
                "fps_tolerance": fps_tolerance,
                "expected_duration_seconds": expected_duration,
                "duration_tolerance_seconds": duration_tolerance,
            },
        )
    )

    if smoke_generated:
        checks.append(
            build_check(
                "smoke_stream_layout",
                isinstance(smoke_probe, dict)
                and smoke_probe.get("video_codec_name") == profile.get("video", {}).get("codec")
                and smoke_probe.get("video_codec_name") == smoke_generation.get("video_codec")
                and smoke_probe.get("audio_codec_name") == profile.get("audio", {}).get("codec")
                and smoke_probe.get("audio_codec_name") == smoke_generation.get("audio_codec")
                and smoke_probe.get("pix_fmt") in {None, smoke_generation.get("pixel_format")}
                and smoke_probe.get("video_stream_count")
                == expected_stream_layout.get("video_stream_count")
                and smoke_probe.get("audio_stream_count")
                == expected_stream_layout.get("audio_stream_count")
                and smoke_probe.get("audio_sample_rate_hz") == profile.get("audio", {}).get("sample_rate_hz")
                and smoke_probe.get("audio_channels") == profile.get("audio", {}).get("channels")
                and "flv" in (smoke_probe.get("format_name") or ""),
                {
                    "probe_source": probe_source,
                    "smoke_probe": smoke_probe,
                    "expected_stream_layout": expected_stream_layout,
                },
            )
        )
        checks.append(
            build_check(
                "smoke_keyframe_contract",
                isinstance(smoke_probe, dict)
                and isinstance(smoke_probe.get("keyframes"), dict)
                and smoke_probe["keyframes"].get("status") == "ok"
                and int_close(
                    smoke_probe["keyframes"].get("max_interval_frames"),
                    expected_keyframe_interval_frames,
                    keyframe_interval_tolerance,
                ),
                {
                    "probe_source": probe_source,
                    "keyframes": smoke_probe.get("keyframes"),
                    "expected_keyframe_interval_frames": expected_keyframe_interval_frames,
                    "keyframe_interval_tolerance_frames": keyframe_interval_tolerance,
                },
            )
        )

    report = write_report(artifact_dir, manifest, checks)
    failed = [check for check in report["checks"] if check["status"] == "failed"]
    if failed:
        return fail([f"{check['check_id']}: {check['details']}" for check in failed])

    print("stage7 stream bridge validation passed")
    print(f"artifact_dir: {artifact_dir}")
    print(f"work_id: {manifest.get('work_id')}")
    print(
        "bridge_target: "
        f"{bridge_summary.get('video_width')}x{bridge_summary.get('video_height')}"
        f"@{bridge_summary.get('video_fps')} "
        f"{bridge_summary.get('video_codec')}/{bridge_summary.get('audio_codec')}"
    )
    print(f"default_loop_mode: {loop_bridge.get('default_loop_mode')}")
    print(f"smoke_output_file: {smoke_output_path if smoke_generated else 'skipped'}")
    print(f"report_file: {artifact_dir / 'stage7_bridge_validation_report.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
