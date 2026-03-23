from __future__ import annotations

import json
import re
from pathlib import Path


DEFAULT_BRIDGE_PROFILE_PATH = (
    Path(__file__).resolve().parent.parent
    / "runtime"
    / "config"
    / "stage7_default_bridge_profile.json"
)

TOP_LEVEL_REQUIRED_KEYS = {
    "profile_id",
    "description",
    "ingest",
    "video",
    "audio",
    "smoke",
}
TOP_LEVEL_OPTIONAL_KEYS = {"source", "source_path"}
INGEST_KEYS = {"protocol", "container", "stream_url_env", "stream_url_example"}
VIDEO_KEYS = {
    "width",
    "height",
    "fps",
    "codec",
    "encoder",
    "preset",
    "pixel_format",
    "bitrate_kbps",
    "maxrate_kbps",
    "bufsize_kbps",
    "gop_seconds",
    "keyframe_interval_frames",
    "pixel_aspect_ratio",
    "scan_mode",
}
AUDIO_KEYS = {"codec", "sample_rate_hz", "channels", "bitrate_kbps"}
SMOKE_KEYS = {"enabled", "container", "muxer", "output_file"}
ENV_VAR_RE = re.compile(r"^[A-Z][A-Z0-9_]*$")


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _is_nonempty_string(value: object) -> bool:
    return isinstance(value, str) and value.strip() != ""


def _is_integer(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _check_exact_keys(
    payload: dict,
    *,
    label: str,
    required: set[str],
    optional: set[str] | None = None,
) -> list[str]:
    optional = optional or set()
    errors: list[str] = []
    keys = set(payload)
    missing = sorted(required - keys)
    unexpected = sorted(keys - required - optional)
    if missing:
        errors.append(f"{label} missing keys: {', '.join(missing)}")
    if unexpected:
        errors.append(f"{label} contains unexpected keys: {', '.join(unexpected)}")
    return errors


def validate_bridge_profile_payload(
    profile: object,
    *,
    allow_output_metadata: bool = True,
) -> list[str]:
    if not isinstance(profile, dict):
        return ["bridge profile root must be a JSON object"]

    errors: list[str] = []
    errors.extend(
        _check_exact_keys(
            profile,
            label="bridge profile",
            required=TOP_LEVEL_REQUIRED_KEYS,
            optional=TOP_LEVEL_OPTIONAL_KEYS if allow_output_metadata else set(),
        )
    )

    if not _is_nonempty_string(profile.get("profile_id")):
        errors.append("bridge profile profile_id must be a non-empty string")
    if not _is_nonempty_string(profile.get("description")):
        errors.append("bridge profile description must be a non-empty string")

    if "source" in profile or "source_path" in profile:
        if not allow_output_metadata:
            errors.append("bridge profile source/source_path are not allowed in input profiles")
        else:
            if profile.get("source") not in {"repo_default", "cli"}:
                errors.append("bridge profile source must be one of: repo_default, cli")
            if not _is_nonempty_string(profile.get("source_path")):
                errors.append("bridge profile source_path must be a non-empty string")

    ingest = profile.get("ingest")
    if not isinstance(ingest, dict):
        errors.append("bridge profile ingest must be an object")
    else:
        errors.extend(_check_exact_keys(ingest, label="bridge profile ingest", required=INGEST_KEYS))
        protocol = ingest.get("protocol")
        if protocol not in {"rtmp", "rtmps"}:
            errors.append("bridge profile ingest.protocol must be rtmp or rtmps")
        if ingest.get("container") != "flv":
            errors.append("bridge profile ingest.container must be flv")
        stream_url_env = ingest.get("stream_url_env")
        if not isinstance(stream_url_env, str) or not ENV_VAR_RE.match(stream_url_env):
            errors.append(
                "bridge profile ingest.stream_url_env must be an uppercase environment variable name"
            )
        example = ingest.get("stream_url_example")
        if not _is_nonempty_string(example):
            errors.append("bridge profile ingest.stream_url_example must be a non-empty string")
        elif protocol == "rtmps" and not example.startswith("rtmps://"):
            errors.append(
                "bridge profile ingest.stream_url_example must start with rtmps:// when protocol=rtmps"
            )

    video = profile.get("video")
    if not isinstance(video, dict):
        errors.append("bridge profile video must be an object")
    else:
        errors.extend(_check_exact_keys(video, label="bridge profile video", required=VIDEO_KEYS))
        for field_name, lower_bound in (
            ("width", 320),
            ("height", 240),
            ("fps", 1),
            ("bitrate_kbps", 1),
            ("maxrate_kbps", 1),
            ("bufsize_kbps", 1),
            ("gop_seconds", 1),
            ("keyframe_interval_frames", 1),
        ):
            value = video.get(field_name)
            if not _is_integer(value) or value < lower_bound:
                errors.append(f"bridge profile video.{field_name} must be an integer >= {lower_bound}")
        for field_name in ("codec", "encoder", "preset", "pixel_format", "pixel_aspect_ratio", "scan_mode"):
            if not _is_nonempty_string(video.get(field_name)):
                errors.append(f"bridge profile video.{field_name} must be a non-empty string")
        if video.get("codec") != "h264":
            errors.append("bridge profile video.codec must be h264")
        if video.get("pixel_aspect_ratio") != "1:1":
            errors.append("bridge profile video.pixel_aspect_ratio must be 1:1")
        if video.get("scan_mode") != "progressive":
            errors.append("bridge profile video.scan_mode must be progressive")
        bitrate_kbps = video.get("bitrate_kbps")
        maxrate_kbps = video.get("maxrate_kbps")
        bufsize_kbps = video.get("bufsize_kbps")
        fps = video.get("fps")
        gop_seconds = video.get("gop_seconds")
        keyframe_interval_frames = video.get("keyframe_interval_frames")
        if (
            _is_integer(bitrate_kbps)
            and _is_integer(maxrate_kbps)
            and bitrate_kbps != maxrate_kbps
        ):
            errors.append("bridge profile video.bitrate_kbps must equal maxrate_kbps for CBR freeze")
        if (
            _is_integer(maxrate_kbps)
            and _is_integer(bufsize_kbps)
            and bufsize_kbps < maxrate_kbps
        ):
            errors.append("bridge profile video.bufsize_kbps must be >= maxrate_kbps")
        if (
            _is_integer(fps)
            and _is_integer(gop_seconds)
            and _is_integer(keyframe_interval_frames)
            and keyframe_interval_frames != fps * gop_seconds
        ):
            errors.append(
                "bridge profile video.keyframe_interval_frames must equal fps * gop_seconds"
            )

    audio = profile.get("audio")
    if not isinstance(audio, dict):
        errors.append("bridge profile audio must be an object")
    else:
        errors.extend(_check_exact_keys(audio, label="bridge profile audio", required=AUDIO_KEYS))
        if audio.get("codec") != "aac":
            errors.append("bridge profile audio.codec must be aac")
        sample_rate_hz = audio.get("sample_rate_hz")
        if not _is_integer(sample_rate_hz) or sample_rate_hz <= 0:
            errors.append("bridge profile audio.sample_rate_hz must be a positive integer")
        if audio.get("channels") != 2:
            errors.append("bridge profile audio.channels must equal 2 for stereo freeze")
        bitrate_kbps = audio.get("bitrate_kbps")
        if not _is_integer(bitrate_kbps) or bitrate_kbps <= 0:
            errors.append("bridge profile audio.bitrate_kbps must be a positive integer")
        if sample_rate_hz != 44100:
            errors.append("bridge profile audio.sample_rate_hz must equal 44100 for stereo freeze")

    smoke = profile.get("smoke")
    if not isinstance(smoke, dict):
        errors.append("bridge profile smoke must be an object")
    else:
        errors.extend(_check_exact_keys(smoke, label="bridge profile smoke", required=SMOKE_KEYS))
        if not isinstance(smoke.get("enabled"), bool):
            errors.append("bridge profile smoke.enabled must be a boolean")
        if smoke.get("container") != "flv":
            errors.append("bridge profile smoke.container must be flv")
        if smoke.get("muxer") != "flv":
            errors.append("bridge profile smoke.muxer must be flv")
        output_file = smoke.get("output_file")
        if not _is_nonempty_string(output_file):
            errors.append("bridge profile smoke.output_file must be a non-empty string")
        elif not output_file.endswith(".flv"):
            errors.append("bridge profile smoke.output_file must end with .flv")

    return errors
