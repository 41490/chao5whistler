#!/usr/bin/env python3

from __future__ import annotations

import argparse
import hashlib
import json
import shlex
import shutil
import subprocess
import tempfile
import wave
from math import ceil
from pathlib import Path

from stage7_bridge_profile import (
    DEFAULT_BRIDGE_PROFILE_PATH,
    validate_bridge_profile_payload,
)


REQUIRED_AUDIO_FILES = {
    "artifact_summary.json",
    "render_request.json",
    "stream_loop_plan.json",
    "m1_validation_report.json",
    "offline_audio.wav",
}
REQUIRED_VIDEO_FILES = {
    "video_render_manifest.json",
    "stage6_render_validation_report.json",
    "offline_preview.mp4",
    "visual_scene_profile.json",
}
LOOP_MODE_ENV = "MUSIKALISCHES_STAGE7_LOOP_MODE"
MAX_RUNTIME_ENV = "MUSIKALISCHES_STAGE7_MAX_RUNTIME_SECONDS"
LOG_DIR_NAME = "logs"
STDERR_LOG_FILE = "stage7_bridge_latest.stderr.log"
EXIT_REPORT_FILE = "stage7_bridge_exit_report.json"
PREFLIGHT_LOG_FILE = "stage7_bridge_preflight.stderr.log"
PREFLIGHT_REPORT_FILE = "stage7_bridge_preflight_report.json"
RUNTIME_REPORT_FILE = "stage7_bridge_runtime_report.json"
ATTEMPT_LOG_PATTERN = "stage7_bridge_attempt_{attempt:03d}.stderr.log"
ATTEMPT_REPORT_PATTERN = "stage7_bridge_attempt_{attempt:03d}.exit_report.json"
FAILURE_TAXONOMY_FILE = "stage7_failure_taxonomy.json"
SOAK_PLAN_FILE = "stage7_soak_plan.json"
SOAK_VALIDATION_REPORT_FILE = "stage7_soak_validation_report.json"
CLASSIFIER_TOOL_PATH = Path(__file__).resolve().parent / "classify_stage7_bridge_failure.py"
RUNTIME_TOOL_PATH = Path(__file__).resolve().parent / "run_stage7_stream_bridge_runtime.py"
LOOP_MODE_SPECS = {
    "once": {
        "stream_loop": None,
        "description": "run the finite stage5/stage6 source pair once and exit at EOF",
    },
    "infinite": {
        "stream_loop": -1,
        "description": "loop the aligned stage5/stage6 source pair continuously for live bridge/soak runs",
    },
}
SOAK_MIN_RUNTIME_HOURS = 8
DRIFT_TOLERANCE_SECONDS_PER_HOUR = 0.25
RECONNECT_BACKOFF_SECONDS = [1, 5, 15]


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: dict) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=True, indent=2) + "\n",
        encoding="utf-8",
    )


def write_text(path: Path, payload: str) -> None:
    path.write_text(payload, encoding="utf-8")


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


def round6(value: float) -> float:
    return round(value, 6)


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


def resolve_bridge_profile(profile_path: Path) -> dict:
    if not profile_path.exists():
        raise SystemExit(f"bridge profile does not exist: {profile_path}")

    profile = load_json(profile_path)
    input_errors = validate_bridge_profile_payload(profile, allow_output_metadata=False)
    if input_errors:
        raise SystemExit(
            "bridge profile validation failed:\n- " + "\n- ".join(input_errors)
        )

    resolved = json.loads(json.dumps(profile))
    resolved["source"] = (
        "repo_default"
        if profile_path.resolve() == DEFAULT_BRIDGE_PROFILE_PATH.resolve()
        else "cli"
    )
    resolved["source_path"] = str(profile_path.resolve())
    resolved_errors = validate_bridge_profile_payload(resolved, allow_output_metadata=True)
    if resolved_errors:
        raise SystemExit(
            "resolved bridge profile validation failed:\n- " + "\n- ".join(resolved_errors)
        )
    return resolved


def inspect_wav(path: Path) -> dict:
    with wave.open(str(path), "rb") as handle:
        sample_rate = handle.getframerate()
        channels = handle.getnchannels()
        sample_width = handle.getsampwidth()
        frames = handle.getnframes()
    duration_seconds = frames / sample_rate if sample_rate else 0.0
    return {
        "sample_rate_hz": sample_rate,
        "channels": channels,
        "sample_width_bytes": sample_width,
        "frames": frames,
        "duration_seconds": round6(duration_seconds),
    }


def probe_keyframes(
    path: Path,
    ffprobe_bin: str | None,
    fps: float | None,
) -> dict | None:
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
        round6(float(frame["best_effort_timestamp_time"]))
        for frame in payload.get("frames", [])
        if frame.get("best_effort_timestamp_time") not in {None, ""}
    ]
    intervals = [
        round6(timestamps[index + 1] - timestamps[index])
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
        "max_interval_seconds": round6(max_interval_seconds)
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


def probe_media(path: Path, ffprobe_bin: str | None) -> dict | None:
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


def build_live_args(
    profile: dict,
    video_path: Path,
    audio_path: Path,
    *,
    ffmpeg_bin: str = "ffmpeg",
    loop_mode: str,
    output_target: str | None,
) -> list[str]:
    ingest = profile["ingest"]
    video = profile["video"]
    audio = profile["audio"]
    spec = LOOP_MODE_SPECS[loop_mode]
    args = [ffmpeg_bin]
    if spec["stream_loop"] is not None:
        args.extend(["-stream_loop", str(spec["stream_loop"])])
    args.extend(["-re", "-i", str(video_path)])
    if spec["stream_loop"] is not None:
        args.extend(["-stream_loop", str(spec["stream_loop"])])
    args.extend(
        [
            "-re",
            "-i",
            str(audio_path),
            "-map",
            "0:v:0",
            "-map",
            "1:a:0",
            "-c:v",
            video["encoder"],
            "-preset",
            video["preset"],
            "-pix_fmt",
            video["pixel_format"],
            "-r",
            str(video["fps"]),
            "-g",
            str(video["keyframe_interval_frames"]),
            "-keyint_min",
            str(video["keyframe_interval_frames"]),
            "-sc_threshold",
            "0",
            "-b:v",
            f"{video['bitrate_kbps']}k",
            "-maxrate",
            f"{video['maxrate_kbps']}k",
            "-bufsize",
            f"{video['bufsize_kbps']}k",
            "-vf",
            f"scale={video['width']}:{video['height']}:flags=lanczos,setsar=1",
            "-c:a",
            audio["codec"],
            "-b:a",
            f"{audio['bitrate_kbps']}k",
            "-ar",
            str(audio["sample_rate_hz"]),
            "-ac",
            str(audio["channels"]),
            "-f",
            ingest["container"],
        ]
    )
    if output_target is not None:
        args.append(output_target)
    return args


def build_smoke_args(
    ffmpeg_bin: str,
    profile: dict,
    video_path: Path,
    audio_path: Path,
    smoke_output_path: Path,
) -> list[str]:
    ingest = profile["ingest"]
    video = profile["video"]
    audio = profile["audio"]
    return [
        ffmpeg_bin,
        "-y",
        "-i",
        str(video_path),
        "-i",
        str(audio_path),
        "-map",
        "0:v:0",
        "-map",
        "1:a:0",
        "-shortest",
        "-c:v",
        video["encoder"],
        "-preset",
        video["preset"],
        "-pix_fmt",
        video["pixel_format"],
        "-r",
        str(video["fps"]),
        "-g",
        str(video["keyframe_interval_frames"]),
        "-keyint_min",
        str(video["keyframe_interval_frames"]),
        "-sc_threshold",
        "0",
        "-b:v",
        f"{video['bitrate_kbps']}k",
        "-maxrate",
        f"{video['maxrate_kbps']}k",
        "-bufsize",
        f"{video['bufsize_kbps']}k",
        "-vf",
        f"scale={video['width']}:{video['height']}:flags=lanczos,setsar=1",
        "-c:a",
        audio["codec"],
        "-b:a",
        f"{audio['bitrate_kbps']}k",
        "-ar",
        str(audio["sample_rate_hz"]),
        "-ac",
        str(audio["channels"]),
        "-f",
        ingest["container"],
        str(smoke_output_path),
    ]


def build_failure_taxonomy(url_env_var: str) -> dict:
    return {
        "taxonomy_id": "stage7_rtmps_failure_taxonomy_v1",
        "description": (
            "Stage7 RTMPS bridge runtime exit classification and retry hints. "
            f"Logs are sanitized against {url_env_var} before persistence."
        ),
        "default_class_id": "unknown_failure",
        "classes": [
            {
                "class_id": "clean_exit",
                "description": "ffmpeg exited with code 0",
                "retryable": False,
                "match_any": [],
                "match_exit_codes": [0],
            },
            {
                "class_id": "runtime_limit_reached",
                "description": "wrapper stopped the bridge after the requested max runtime",
                "retryable": False,
                "match_any": [],
                "match_exit_codes": [124],
            },
            {
                "class_id": "interrupted",
                "description": "operator interrupt or termination signal",
                "retryable": False,
                "match_any": [],
                "match_exit_codes": [130, 143],
            },
            {
                "class_id": "handshake_failure",
                "description": "TLS/SSL or session handshake failed before publish start",
                "retryable": False,
                "match_any": [
                    "handshake failed",
                    "tls",
                    "ssl",
                    "certificate",
                ],
                "match_exit_codes": [],
            },
            {
                "class_id": "auth_failure",
                "description": "stream publish rejected by credentials, policy, or stream key",
                "retryable": False,
                "match_any": [
                    "403 forbidden",
                    "401 unauthorized",
                    "authentication failed",
                    "authorization failed",
                    "invalid stream key",
                    "permission denied",
                    "publishing not permitted",
                ],
                "match_exit_codes": [],
            },
            {
                "class_id": "ingest_configuration_failure",
                "description": "bridge host or ffmpeg build is missing the required RTMP/RTMPS output capability",
                "retryable": False,
                "match_any": [
                    "protocol not found",
                    "unknown protocol",
                    "option not found",
                    "unknown encoder",
                    "encoder not found",
                ],
                "match_exit_codes": [],
            },
            {
                "class_id": "network_jitter",
                "description": "local network instability or routing failure during publish",
                "retryable": True,
                "match_any": [
                    "timed out",
                    "network is unreachable",
                    "temporary failure in name resolution",
                    "name or service not known",
                    "nodename nor servname provided",
                    "no address associated with hostname",
                    "connection refused",
                    "resource temporarily unavailable",
                ],
                "match_exit_codes": [],
            },
            {
                "class_id": "remote_disconnect",
                "description": "remote endpoint closed or reset an established publishing session",
                "retryable": True,
                "match_any": [
                    "end of file",
                    "server closed the connection",
                    "connection reset by peer",
                    "broken pipe",
                ],
                "match_exit_codes": [],
            },
            {
                "class_id": "unknown_failure",
                "description": "non-zero exit without a more specific RTMPS classification",
                "retryable": False,
                "match_any": [],
                "match_exit_codes": [],
            },
        ],
    }


def build_soak_plan(
    bridge_profile: dict,
    audio_loop_plan: dict,
    duration_audio: float,
    failure_taxonomy: dict,
) -> dict:
    cycle_duration_seconds = audio_loop_plan.get("cycle_duration_seconds")
    minimum_runtime_seconds = SOAK_MIN_RUNTIME_HOURS * 3600
    source_loop_iterations = ceil(minimum_runtime_seconds / duration_audio)
    cycle_boundary_count = (
        ceil(minimum_runtime_seconds / cycle_duration_seconds)
        if cycle_duration_seconds
        else None
    )
    retryable_classes = [
        entry["class_id"] for entry in failure_taxonomy["classes"] if entry["retryable"]
    ]
    non_retryable_classes = [
        entry["class_id"] for entry in failure_taxonomy["classes"] if not entry["retryable"]
    ]
    return {
        "stage": "stage7_pre_stage8_soak",
        "status": "ready",
        "bridge_profile_id": bridge_profile["profile_id"],
        "minimum_runtime_hours": SOAK_MIN_RUNTIME_HOURS,
        "minimum_runtime_seconds": minimum_runtime_seconds,
        "source_duration_seconds": duration_audio,
        "source_cycle_duration_seconds": cycle_duration_seconds,
        "expected_source_loop_iterations": source_loop_iterations,
        "expected_cycle_boundaries": cycle_boundary_count,
        "drift_budget": {
            "max_abs_drift_seconds_per_hour": DRIFT_TOLERANCE_SECONDS_PER_HOUR,
            "measurement_basis": "compare live loop boundary cadence against frozen source duration",
        },
        "preflight_policy": {
            "required_checks": [
                "protocol_support",
                "dns_resolution",
                "tcp_connectivity",
                "publish_probe",
            ],
            "failure_class_hints": {
                "protocol_support": "ingest_configuration_failure",
                "dns_resolution": "network_jitter",
                "tcp_connectivity": "network_jitter",
                "publish_probe": "auth_failure",
            },
        },
        "reconnect_policy": {
            "retryable_classes": retryable_classes,
            "non_retryable_classes": non_retryable_classes,
            "max_consecutive_retryable_failures": len(RECONNECT_BACKOFF_SECONDS),
            "backoff_seconds": RECONNECT_BACKOFF_SECONDS,
        },
        "required_runtime_files": [
            f"{LOG_DIR_NAME}/{PREFLIGHT_LOG_FILE}",
            f"{LOG_DIR_NAME}/{PREFLIGHT_REPORT_FILE}",
            f"{LOG_DIR_NAME}/{STDERR_LOG_FILE}",
            f"{LOG_DIR_NAME}/{EXIT_REPORT_FILE}",
            f"{LOG_DIR_NAME}/{RUNTIME_REPORT_FILE}",
        ],
        "exit_classification_coverage": [
            entry["class_id"] for entry in failure_taxonomy["classes"]
        ],
    }


def build_shell_array(name: str, values: list[str]) -> list[str]:
    lines = [f"{name}=("]
    for value in values:
        lines.append(f"  {shlex.quote(value)}")
    lines.append(")")
    return lines


def build_runtime_script(
    *,
    env_var: str,
    runtime_tool_path: Path,
) -> str:
    lines = [
        "#!/usr/bin/env bash",
        "set -euo pipefail",
        "",
        'SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"',
        f'LOOP_MODE="${{{LOOP_MODE_ENV}:-infinite}}"',
        f'MAX_RUNTIME_SECONDS="${{{MAX_RUNTIME_ENV}:-}}"',
        "",
        f'if [[ -z "${{{env_var}:-}}" ]]; then',
        f'  printf "%s\\n" "missing {env_var}: export {env_var}=..." >&2',
        "  exit 1",
        "fi",
        "",
        f'PYTHON_BIN="${{PYTHON:-python3}}"',
        f'RUNNER={shlex.quote(str(runtime_tool_path))}',
        'CMD=("${PYTHON_BIN}" "${RUNNER}"',
        '  --artifact-dir "${SCRIPT_DIR}"',
        f'  --stream-url-env {env_var}',
        '  --loop-mode "${LOOP_MODE}"',
        '  --max-runtime-seconds "${MAX_RUNTIME_SECONDS:-0}"',
        ')',
        "",
        'if [[ -n "${MAX_RUNTIME_SECONDS}" && "${MAX_RUNTIME_SECONDS}" != "0" ]]; then',
        '  printf "%s\\n" "stage7 wrapper note: MUSIKALISCHES_STAGE7_MAX_RUNTIME_SECONDS is an overall runtime budget; omit it for unattended LOOP_MODE=infinite." >&2',
        "fi",
        "",
        "set +e",
        '"${CMD[@]}"',
        'EXIT_CODE="$?"',
        "set -e",
        "",
        'if [[ "${EXIT_CODE}" -ne 0 ]]; then',
        '  printf "%s\\n" "stage7 wrapper exit: code=${EXIT_CODE}; check ${SCRIPT_DIR}/logs/stage7_bridge_preflight_report.json first, then ${SCRIPT_DIR}/logs/stage7_bridge_runtime_report.json and ${SCRIPT_DIR}/logs/stage7_bridge_latest.stderr.log" >&2',
        "fi",
        "",
        'exit "${EXIT_CODE}"',
        "",
    ]
    return "\n".join(lines)


def run_ffmpeg(args: list[str]) -> None:
    with tempfile.TemporaryFile(mode="w+b") as stderr_handle:
        process = subprocess.Popen(
            args,
            stdout=subprocess.DEVNULL,
            stderr=stderr_handle,
            text=False,
        )
        exit_code = process.wait()
        if exit_code != 0:
            stderr_handle.seek(0)
            stderr = stderr_handle.read().decode("utf-8", errors="replace").strip()
            raise SystemExit(f"ffmpeg failed with exit code {exit_code}:\n{stderr}")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Freeze stage7 FFmpeg bridge contract and produce a local FLV smoke artifact."
    )
    parser.add_argument(
        "audio_artifact_dir",
        nargs="?",
        default="ops/out/stream-demo",
        help="stage5 artifact directory containing offline_audio.wav",
    )
    parser.add_argument(
        "video_artifact_dir",
        nargs="?",
        default="ops/out/video-render",
        help="stage6 render artifact directory containing offline_preview.mp4",
    )
    parser.add_argument(
        "output_dir",
        nargs="?",
        default="ops/out/stream-bridge",
        help="output directory for stage7 bridge artifacts",
    )
    parser.add_argument(
        "--bridge-profile",
        default=str(DEFAULT_BRIDGE_PROFILE_PATH),
        help="stage7 bridge profile JSON path",
    )
    parser.add_argument(
        "--ffmpeg-bin",
        default="ffmpeg",
        help="ffmpeg binary used for local bridge smoke generation",
    )
    parser.add_argument(
        "--ffprobe-bin",
        default="ffprobe",
        help="ffprobe binary used to probe local smoke output",
    )
    parser.add_argument(
        "--skip-smoke",
        action="store_true",
        help="only freeze the bridge contract, do not render the local FLV smoke artifact",
    )
    args = parser.parse_args()

    audio_dir = Path(args.audio_artifact_dir).resolve()
    video_dir = Path(args.video_artifact_dir).resolve()
    output_dir = Path(args.output_dir).resolve()

    if not audio_dir.exists():
        raise SystemExit(f"audio artifact directory does not exist: {audio_dir}")
    if not video_dir.exists():
        raise SystemExit(f"video artifact directory does not exist: {video_dir}")

    audio_file_names = {path.name for path in audio_dir.iterdir() if path.is_file()}
    missing_audio = sorted(REQUIRED_AUDIO_FILES - audio_file_names)
    if missing_audio:
        raise SystemExit(
            f"audio artifact directory missing files: {', '.join(missing_audio)}"
        )
    video_file_names = {path.name for path in video_dir.iterdir() if path.is_file()}
    missing_video = sorted(REQUIRED_VIDEO_FILES - video_file_names)
    if missing_video:
        raise SystemExit(
            f"video artifact directory missing files: {', '.join(missing_video)}"
        )

    bridge_profile = resolve_bridge_profile(Path(args.bridge_profile).resolve())
    audio_summary = load_json(audio_dir / "artifact_summary.json")
    audio_loop_plan = load_json(audio_dir / "stream_loop_plan.json")
    audio_report = load_json(audio_dir / "m1_validation_report.json")
    video_manifest = load_json(video_dir / "video_render_manifest.json")
    video_report = load_json(video_dir / "stage6_render_validation_report.json")
    audio_path = audio_dir / "offline_audio.wav"
    video_path = video_dir / "offline_preview.mp4"
    wav_metadata = inspect_wav(audio_path)
    stage6_probe = video_manifest.get("mp4_generation", {}).get("probe", {})

    if audio_report.get("status") != "passed":
        raise SystemExit("stage5 audio validation report must have status=passed")
    if video_report.get("status") != "passed":
        raise SystemExit("stage6 video validation report must have status=passed")
    if audio_summary.get("work_id") != video_manifest.get("work_id"):
        raise SystemExit("stage5/stage6 work_id mismatch")

    profile_video = bridge_profile["video"]
    profile_audio = bridge_profile["audio"]
    duration_audio = wav_metadata["duration_seconds"]
    duration_video = stage6_probe.get(
        "duration_seconds",
        video_manifest.get("mp4_generation", {}).get("expected_duration_seconds"),
    )
    if duration_video is None:
        raise SystemExit("stage6 manifest is missing expected/probed video duration")
    duration_delta = abs(duration_audio - duration_video)
    if duration_delta > 0.05:
        raise SystemExit(
            "stage5 audio duration and stage6 video duration must remain aligned"
        )

    expected_width = stage6_probe.get("width")
    expected_height = stage6_probe.get("height")
    expected_fps = stage6_probe.get(
        "avg_frame_rate_value",
        video_manifest.get("mp4_generation", {}).get("expected_fps"),
    )
    if expected_width != profile_video["width"] or expected_height != profile_video["height"]:
        raise SystemExit("stage6 preview canvas does not match stage7 bridge profile")
    if expected_fps is None or abs(expected_fps - profile_video["fps"]) > 0.01:
        raise SystemExit("stage6 preview fps does not match stage7 bridge profile")
    if wav_metadata["sample_rate_hz"] != profile_audio["sample_rate_hz"]:
        raise SystemExit("stage5 audio sample rate does not match stage7 bridge profile")
    if wav_metadata["channels"] != profile_audio["channels"]:
        raise SystemExit("stage5 audio channel count does not match stage7 bridge profile")

    ffmpeg_path = None if args.skip_smoke else shutil.which(args.ffmpeg_bin)
    ffprobe_path = shutil.which(args.ffprobe_bin)
    resolved_ffmpeg_path = shutil.which(args.ffmpeg_bin) or args.ffmpeg_bin
    if not args.skip_smoke and not ffmpeg_path:
        raise SystemExit(f"ffmpeg binary not found: {args.ffmpeg_bin}")

    output_dir.mkdir(parents=True, exist_ok=True)
    log_dir = output_dir / LOG_DIR_NAME
    log_dir.mkdir(exist_ok=True)
    smoke_output_path = output_dir / bridge_profile["smoke"]["output_file"]
    if smoke_output_path.exists():
        smoke_output_path.unlink()

    url_placeholder = f"${{{bridge_profile['ingest']['stream_url_env']}}}"
    live_args_once_redacted = build_live_args(
        bridge_profile,
        video_path,
        audio_path,
        ffmpeg_bin="ffmpeg",
        loop_mode="once",
        output_target=url_placeholder,
    )
    live_args_infinite_redacted = build_live_args(
        bridge_profile,
        video_path,
        audio_path,
        ffmpeg_bin="ffmpeg",
        loop_mode="infinite",
        output_target=url_placeholder,
    )
    live_args_once_runtime = build_live_args(
        bridge_profile,
        video_path,
        audio_path,
        ffmpeg_bin=resolved_ffmpeg_path,
        loop_mode="once",
        output_target=None,
    )
    live_args_infinite_runtime = build_live_args(
        bridge_profile,
        video_path,
        audio_path,
        ffmpeg_bin=resolved_ffmpeg_path,
        loop_mode="infinite",
        output_target=None,
    )
    smoke_args = (
        build_smoke_args(ffmpeg_path, bridge_profile, video_path, audio_path, smoke_output_path)
        if ffmpeg_path
        else []
    )
    smoke_generated = False
    smoke_reason = "skipped_by_flag" if args.skip_smoke else "encoded_with_ffmpeg"
    smoke_probe = None
    if ffmpeg_path:
        run_ffmpeg(smoke_args)
        smoke_generated = True
        smoke_probe = probe_media(smoke_output_path, ffprobe_path)

    failure_taxonomy = build_failure_taxonomy(bridge_profile["ingest"]["stream_url_env"])
    soak_plan = build_soak_plan(
        bridge_profile,
        audio_loop_plan,
        duration_audio,
        failure_taxonomy,
    )

    loop_bridge = {
        "default_loop_mode": "infinite",
        "loop_control_env": LOOP_MODE_ENV,
        "max_runtime_env": MAX_RUNTIME_ENV,
        "supported_loop_modes": {
            mode: {
                "ffmpeg_stream_loop": LOOP_MODE_SPECS[mode]["stream_loop"],
                "description": LOOP_MODE_SPECS[mode]["description"],
            }
            for mode in ("once", "infinite")
        },
        "source_cycle_duration_seconds": audio_loop_plan.get("cycle_duration_seconds"),
        "source_cycle_duration_frames": audio_loop_plan.get("cycle_duration_frames"),
        "source_cycle_count": len(audio_loop_plan.get("cycles", [])),
        "source_render_loop_count": audio_loop_plan.get("loop_count"),
        "source_render_duration_seconds": duration_audio,
        "video_render_duration_seconds": round6(duration_video),
        "source_duration_delta_seconds": round6(duration_delta),
        "continuous_alignment_mode": "repeat_full_source_pair",
    }
    runtime_observability = {
        "log_dir": LOG_DIR_NAME,
        "stderr_log_file": STDERR_LOG_FILE,
        "exit_report_file": EXIT_REPORT_FILE,
        "preflight_log_file": PREFLIGHT_LOG_FILE,
        "preflight_report_file": PREFLIGHT_REPORT_FILE,
        "runtime_report_file": RUNTIME_REPORT_FILE,
        "attempt_log_pattern": ATTEMPT_LOG_PATTERN,
        "attempt_report_pattern": ATTEMPT_REPORT_PATTERN,
        "redact_env_vars": [bridge_profile["ingest"]["stream_url_env"]],
        "classifier_tool_path": str(CLASSIFIER_TOOL_PATH),
        "runtime_tool_path": str(RUNTIME_TOOL_PATH),
    }
    preflight = {
        "required_checks": soak_plan["preflight_policy"]["required_checks"],
        "failure_class_hints": soak_plan["preflight_policy"]["failure_class_hints"],
        "preflight_log_file": PREFLIGHT_LOG_FILE,
        "preflight_report_file": PREFLIGHT_REPORT_FILE,
        "publish_probe_mode": "ffmpeg_lightweight_publish",
        "publish_probe_timeout_seconds": 15,
        "tcp_connect_timeout_seconds": 5,
    }
    runtime_executor = {
        "tool_path": str(RUNTIME_TOOL_PATH),
        "runtime_report_file": RUNTIME_REPORT_FILE,
        "attempt_log_pattern": ATTEMPT_LOG_PATTERN,
        "attempt_report_pattern": ATTEMPT_REPORT_PATTERN,
        "backoff_seconds": soak_plan["reconnect_policy"]["backoff_seconds"],
        "max_consecutive_retryable_failures": soak_plan["reconnect_policy"][
            "max_consecutive_retryable_failures"
        ],
    }

    write_json(output_dir / "stage7_bridge_profile.json", bridge_profile)
    write_json(output_dir / FAILURE_TAXONOMY_FILE, failure_taxonomy)
    write_json(output_dir / SOAK_PLAN_FILE, soak_plan)
    write_json(
        output_dir / "stream_bridge_ffmpeg_args.json",
        {
            "stage": "stage7_stream_bridge",
            "profile_id": bridge_profile["profile_id"],
            "url_env_var": bridge_profile["ingest"]["stream_url_env"],
            "loop_control_env": LOOP_MODE_ENV,
            "max_runtime_env": MAX_RUNTIME_ENV,
            "default_loop_mode": loop_bridge["default_loop_mode"],
            "runtime_ffmpeg_bin": resolved_ffmpeg_path,
            "live_redacted_argv": live_args_infinite_redacted,
            "live_redacted_shell": shlex.join(live_args_infinite_redacted),
            "live_redacted_argv_by_mode": {
                "once": live_args_once_redacted,
                "infinite": live_args_infinite_redacted,
            },
            "live_redacted_shell_by_mode": {
                "once": shlex.join(live_args_once_redacted),
                "infinite": shlex.join(live_args_infinite_redacted),
            },
            "live_runtime_argv_without_target_by_mode": {
                "once": live_args_once_runtime,
                "infinite": live_args_infinite_runtime,
            },
            "smoke_argv": smoke_args,
            "smoke_shell": shlex.join(smoke_args) if smoke_args else None,
        },
    )
    write_text(
        output_dir / "run_stage7_stream_bridge.sh",
        build_runtime_script(
            env_var=bridge_profile["ingest"]["stream_url_env"],
            runtime_tool_path=RUNTIME_TOOL_PATH,
        ),
    )
    (output_dir / "run_stage7_stream_bridge.sh").chmod(0o755)
    artifact_integrity = {
        path.name: build_file_integrity(path)
        for path in [
            output_dir / "stage7_bridge_profile.json",
            output_dir / FAILURE_TAXONOMY_FILE,
            output_dir / SOAK_PLAN_FILE,
            output_dir / "stream_bridge_ffmpeg_args.json",
            output_dir / "run_stage7_stream_bridge.sh",
        ]
    }
    if smoke_generated:
        artifact_integrity[smoke_output_path.name] = build_file_integrity(smoke_output_path)
    stage6_artifact_integrity = (
        video_manifest.get("artifact_integrity", {}).get(video_path.name)
        if isinstance(video_manifest.get("artifact_integrity"), dict)
        else None
    )
    if stage6_artifact_integrity is None and video_path.exists():
        stage6_artifact_integrity = build_file_integrity(video_path)
    source_video_contract = {
        "expected_frame_count": video_manifest.get("mp4_generation", {}).get("expected_frame_count"),
        "frame_count_tolerance": video_manifest.get("mp4_generation", {}).get(
            "frame_count_tolerance"
        ),
        "expected_fps": video_manifest.get("mp4_generation", {}).get("expected_fps"),
        "fps_tolerance": video_manifest.get("mp4_generation", {}).get("fps_tolerance"),
        "expected_duration_seconds": video_manifest.get("mp4_generation", {}).get(
            "expected_duration_seconds"
        ),
        "duration_tolerance_seconds": video_manifest.get("mp4_generation", {}).get(
            "duration_tolerance_seconds"
        ),
        "expected_keyframe_interval_frames": video_manifest.get("mp4_generation", {}).get(
            "expected_keyframe_interval_frames"
        ),
        "keyframe_interval_tolerance_frames": video_manifest.get("mp4_generation", {}).get(
            "keyframe_interval_tolerance_frames"
        ),
        "expected_stream_layout": video_manifest.get("mp4_generation", {}).get(
            "expected_stream_layout"
        ),
    }

    manifest = {
        "stage": "stage7_stream_bridge",
        "description": "Frozen FFmpeg bridge contract derived from stage5 audio artifacts and stage6 preview video artifacts.",
        "work_id": audio_summary["work_id"],
        "source_audio_artifact_dir": str(audio_dir),
        "source_video_artifact_dir": str(video_dir),
        "source_audio_stage": audio_report.get("stage"),
        "source_video_stage": video_manifest.get("stage"),
        "bridge_profile_id": bridge_profile["profile_id"],
        "bridge_profile_source": bridge_profile["source"],
        "bridge_profile_path": bridge_profile["source_path"],
        "input_files": {
            "audio": sorted(REQUIRED_AUDIO_FILES),
            "video": sorted(REQUIRED_VIDEO_FILES),
        },
        "artifacts": {
            "bridge_profile_file": "stage7_bridge_profile.json",
            "ffmpeg_args_file": "stream_bridge_ffmpeg_args.json",
            "run_script_file": "run_stage7_stream_bridge.sh",
            "failure_taxonomy_file": FAILURE_TAXONOMY_FILE,
            "soak_plan_file": SOAK_PLAN_FILE,
            "smoke_output_file": bridge_profile["smoke"]["output_file"],
            "validation_report_file": "stage7_bridge_validation_report.json",
            "soak_validation_report_file": SOAK_VALIDATION_REPORT_FILE,
        },
        "artifact_integrity": artifact_integrity,
        "bridge_summary": {
            "loop_count": audio_loop_plan.get("loop_count"),
            "duration_seconds": duration_audio,
            "default_loop_mode": loop_bridge["default_loop_mode"],
            "video_width": profile_video["width"],
            "video_height": profile_video["height"],
            "video_fps": profile_video["fps"],
            "video_codec": profile_video["codec"],
            "video_encoder": profile_video["encoder"],
            "video_preset": profile_video["preset"],
            "video_pixel_format": profile_video["pixel_format"],
            "video_bitrate_kbps": profile_video["bitrate_kbps"],
            "video_maxrate_kbps": profile_video["maxrate_kbps"],
            "video_bufsize_kbps": profile_video["bufsize_kbps"],
            "video_keyframe_interval_frames": profile_video["keyframe_interval_frames"],
            "video_gop_seconds": profile_video["gop_seconds"],
            "audio_codec": profile_audio["codec"],
            "audio_sample_rate_hz": profile_audio["sample_rate_hz"],
            "audio_channels": profile_audio["channels"],
            "audio_bitrate_kbps": profile_audio["bitrate_kbps"],
            "ingest_protocol": bridge_profile["ingest"]["protocol"],
            "ingest_container": bridge_profile["ingest"]["container"],
            "ingest_url_env": bridge_profile["ingest"]["stream_url_env"],
        },
        "loop_bridge": loop_bridge,
        "runtime_observability": runtime_observability,
        "preflight": preflight,
        "runtime_executor": runtime_executor,
        "failure_policy": {
            "taxonomy_id": failure_taxonomy["taxonomy_id"],
            "default_class_id": failure_taxonomy["default_class_id"],
            "retryable_classes": [
                entry["class_id"] for entry in failure_taxonomy["classes"] if entry["retryable"]
            ],
            "non_retryable_classes": [
                entry["class_id"] for entry in failure_taxonomy["classes"] if not entry["retryable"]
            ],
        },
        "soak_plan_summary": {
            "minimum_runtime_hours": soak_plan["minimum_runtime_hours"],
            "expected_source_loop_iterations": soak_plan["expected_source_loop_iterations"],
            "expected_cycle_boundaries": soak_plan["expected_cycle_boundaries"],
            "drift_budget": soak_plan["drift_budget"],
        },
        "audio_input": {
            "path": str(audio_path),
            "sample_rate_hz": wav_metadata["sample_rate_hz"],
            "channels": wav_metadata["channels"],
            "frames": wav_metadata["frames"],
            "duration_seconds": wav_metadata["duration_seconds"],
            "render_backend": audio_summary.get("audio", {}).get("render_backend"),
        },
        "video_input": {
            "path": str(video_path),
            "duration_seconds": duration_video,
            "width": expected_width,
            "height": expected_height,
            "fps": expected_fps,
            "codec_name": stage6_probe.get("video_codec_name", profile_video["codec"]),
            "source_manifest_codec": video_manifest.get("mp4_generation", {}).get("video_codec"),
            "artifact_integrity": stage6_artifact_integrity,
            "source_contract": source_video_contract,
        },
        "live_command": {
            "ffmpeg_bin": resolved_ffmpeg_path,
            "url_env_var": bridge_profile["ingest"]["stream_url_env"],
            "loop_control_env": LOOP_MODE_ENV,
            "max_runtime_env": MAX_RUNTIME_ENV,
            "default_loop_mode": loop_bridge["default_loop_mode"],
            "argv_redacted": live_args_infinite_redacted,
            "argv_redacted_shell": shlex.join(live_args_infinite_redacted),
            "argv_redacted_by_mode": {
                "once": live_args_once_redacted,
                "infinite": live_args_infinite_redacted,
            },
            "runtime_argv_without_target_by_mode": {
                "once": live_args_once_runtime,
                "infinite": live_args_infinite_runtime,
            },
            "secrets_embedded": False,
        },
        "smoke_generation": {
            "requested": not args.skip_smoke,
            "generated": smoke_generated,
            "reason": smoke_reason,
            "ffmpeg_bin": ffmpeg_path,
            "ffprobe_bin": ffprobe_path,
            "output_file": bridge_profile["smoke"]["output_file"],
            "expected_frame_count": round(duration_audio * profile_video["fps"]),
            "frame_count_tolerance": 1,
            "expected_fps": profile_video["fps"],
            "fps_tolerance": 0.01,
            "expected_duration_seconds": duration_audio,
            "duration_tolerance_seconds": max(0.1, 2.0 / profile_video["fps"]),
            "expected_keyframe_interval_frames": profile_video["keyframe_interval_frames"],
            "keyframe_interval_tolerance_frames": 1,
            "expected_stream_layout": {
                "video_stream_count": 1,
                "audio_stream_count": 1,
            },
            "video_codec": profile_video["codec"],
            "video_encoder": profile_video["encoder"],
            "video_preset": profile_video["preset"],
            "pixel_format": profile_video["pixel_format"],
            "audio_codec": profile_audio["codec"],
            "scene_cut_disabled": True,
            "probe": smoke_probe,
        },
    }
    write_json(output_dir / "stream_bridge_manifest.json", manifest)

    print("stage7 stream bridge built")
    print(f"artifact_dir: {output_dir}")
    print(f"profile_id: {bridge_profile['profile_id']}")
    print(f"duration_seconds: {duration_audio}")
    print(
        "bridge_target: "
        f"{profile_video['width']}x{profile_video['height']}@{profile_video['fps']} "
        f"{profile_video['codec']}/{profile_audio['codec']}"
    )
    print(f"default_loop_mode: {loop_bridge['default_loop_mode']}")
    print(f"smoke_output_file: {smoke_output_path if smoke_generated else 'skipped'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
