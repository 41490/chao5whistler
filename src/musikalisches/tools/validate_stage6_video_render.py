#!/usr/bin/env python3

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
from pathlib import Path

from stage6_scene_profile import SCENE_PROFILE_SCHEMA_PATH, validate_scene_profile_payload


REQUIRED_FILES = {
    "visual_scene_profile.json",
    "video_render_manifest.json",
    "offline_frame_sequence.json",
    "video_render_poster.ppm",
}
EXPECTED_STAGE6_VIDEO_CODEC = "h264"
EXPECTED_STAGE6_VIDEO_ENCODER = "libx264"
EXPECTED_STAGE6_VIDEO_PRESET = "ultrafast"
EXPECTED_STAGE6_PIXEL_FORMAT = "yuv420p"


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


def build_file_fingerprint(path: Path) -> dict:
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
    print("stage6 video render validation failed:")
    for error in errors:
        print(f"- {error}")
    return 1


def write_report(output_dir: Path, frame_sequence: dict, checks: list[dict]) -> dict:
    failed = [check for check in checks if check["status"] == "failed"]
    report = {
        "stage": "stage6_video_render",
        "status": "passed" if not failed else "failed",
        "summary": {
            "checks_total": len(checks),
            "checks_failed": len(failed),
            "frame_count": frame_sequence.get("summary", {}).get("frame_count", 0),
            "cycle_count": frame_sequence.get("summary", {}).get("cycle_count", 0),
            "lane_count": frame_sequence.get("summary", {}).get("lane_count", 0),
            "render_duration_seconds": frame_sequence.get("summary", {}).get(
                "render_duration_seconds"
            ),
            "total_duration_seconds": frame_sequence.get("summary", {}).get(
                "total_duration_seconds"
            ),
        },
        "checks": checks,
    }
    (output_dir / "stage6_render_validation_report.json").write_text(
        json.dumps(report, ensure_ascii=True, indent=2) + "\n",
        encoding="utf-8",
    )
    return report


def probe_mp4(path: Path) -> dict | None:
    ffprobe = shutil.which("ffprobe")
    if not ffprobe or not path.exists():
        return None
    result = subprocess.run(
        [
            ffprobe,
            "-v",
            "error",
            "-show_entries",
            "stream=index,codec_type,codec_name,profile,pix_fmt,width,height,"
            "avg_frame_rate,r_frame_rate,nb_frames,sample_rate,channels,"
            "channel_layout,bit_rate",
            "-show_entries",
            "format=format_name,format_long_name,duration,size,bit_rate",
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
    raw_probe = json.loads(result.stdout)
    streams = raw_probe.get("streams", [])
    video_streams = [stream for stream in streams if stream.get("codec_type") == "video"]
    audio_streams = [stream for stream in streams if stream.get("codec_type") == "audio"]
    primary_video_stream = video_streams[0] if video_streams else {}
    keyframe_result = subprocess.run(
        [
            ffprobe,
            "-v",
            "error",
            "-select_streams",
            "v:0",
            "-skip_frame",
            "nokey",
            "-show_entries",
            "frame=best_effort_timestamp_time,pkt_dts_time,pict_type",
            "-of",
            "json",
            str(path),
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    keyframes = {
        "status": "unavailable",
        "count": 0,
        "timestamps_seconds": [],
        "first_timestamp_seconds": None,
        "last_timestamp_seconds": None,
        "max_interval_seconds": None,
        "max_interval_frames": None,
    }
    if keyframe_result.returncode == 0:
        raw_keyframes = json.loads(keyframe_result.stdout).get("frames", [])
        timestamps: list[float] = []
        for frame in raw_keyframes:
            timestamp = parse_rate(frame.get("best_effort_timestamp_time"))
            if timestamp is None:
                timestamp = parse_rate(frame.get("pkt_dts_time"))
            if timestamp is not None:
                timestamps.append(round(timestamp, 6))
        max_interval_seconds = None
        avg_frame_rate = parse_rate(primary_video_stream.get("avg_frame_rate"))
        if len(timestamps) >= 2:
            max_interval_seconds = max(
                round(timestamps[index + 1] - timestamps[index], 6)
                for index in range(len(timestamps) - 1)
            )
        keyframes = {
            "status": "ok",
            "count": len(timestamps),
            "timestamps_seconds": timestamps,
            "first_timestamp_seconds": timestamps[0] if timestamps else None,
            "last_timestamp_seconds": timestamps[-1] if timestamps else None,
            "max_interval_seconds": max_interval_seconds,
            "max_interval_frames": (
                int(round(max_interval_seconds * avg_frame_rate))
                if max_interval_seconds is not None and avg_frame_rate is not None
                else None
            ),
        }
    elif keyframe_result.stderr.strip():
        keyframes["stderr"] = keyframe_result.stderr.strip()

    def normalize_stream(stream: dict) -> dict:
        return {
            "index": stream.get("index"),
            "codec_type": stream.get("codec_type"),
            "codec_name": stream.get("codec_name"),
            "profile": stream.get("profile"),
            "pix_fmt": stream.get("pix_fmt"),
            "width": stream.get("width"),
            "height": stream.get("height"),
            "avg_frame_rate": stream.get("avg_frame_rate"),
            "avg_frame_rate_value": parse_rate(stream.get("avg_frame_rate")),
            "r_frame_rate": stream.get("r_frame_rate"),
            "r_frame_rate_value": parse_rate(stream.get("r_frame_rate")),
            "nb_frames": stream.get("nb_frames"),
            "nb_frames_value": int(stream["nb_frames"])
            if str(stream.get("nb_frames", "")).isdigit()
            else None,
            "sample_rate": stream.get("sample_rate"),
            "sample_rate_value": int(stream["sample_rate"])
            if str(stream.get("sample_rate", "")).isdigit()
            else None,
            "channels": stream.get("channels"),
            "channel_layout": stream.get("channel_layout"),
            "bit_rate": stream.get("bit_rate"),
            "bit_rate_value": int(stream["bit_rate"])
            if str(stream.get("bit_rate", "")).isdigit()
            else None,
        }

    normalized_streams = [normalize_stream(stream) for stream in streams]
    primary_video = next(
        (stream for stream in normalized_streams if stream.get("codec_type") == "video"),
        {},
    )
    format_payload = raw_probe.get("format", {})
    container = {
        "format_name": format_payload.get("format_name"),
        "format_long_name": format_payload.get("format_long_name"),
        "duration_seconds": parse_rate(format_payload.get("duration")),
        "file_size_bytes": int(format_payload["size"])
        if str(format_payload.get("size", "")).isdigit()
        else None,
        "bit_rate_value": int(format_payload["bit_rate"])
        if str(format_payload.get("bit_rate", "")).isdigit()
        else None,
    }
    return {
        "status": "ok",
        "width": primary_video.get("width"),
        "height": primary_video.get("height"),
        "avg_frame_rate": primary_video.get("avg_frame_rate"),
        "avg_frame_rate_value": primary_video.get("avg_frame_rate_value"),
        "r_frame_rate": primary_video.get("r_frame_rate"),
        "r_frame_rate_value": primary_video.get("r_frame_rate_value"),
        "nb_frames": primary_video.get("nb_frames"),
        "nb_frames_value": primary_video.get("nb_frames_value"),
        "duration_seconds": container["duration_seconds"],
        "file_size_bytes": container["file_size_bytes"],
        "stream_count": len(normalized_streams),
        "video_stream_count": len(video_streams),
        "audio_stream_count": len(audio_streams),
        "streams": normalized_streams,
        "container": container,
        "keyframes": keyframes,
    }


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


def ppm_header(path: Path) -> tuple[str, int, int, int] | None:
    with path.open("rb") as handle:
        magic = handle.readline().decode("ascii", errors="replace").strip()
        dimensions = handle.readline().decode("ascii", errors="replace").strip().split()
        max_value = handle.readline().decode("ascii", errors="replace").strip()
    if len(dimensions) != 2:
        return None
    return magic, int(dimensions[0]), int(dimensions[1]), int(max_value)


def rect_within_canvas(rect: dict, canvas: dict) -> bool:
    required = ("x", "y", "width", "height")
    if any(not isinstance(rect.get(field), int) for field in required):
        return False
    return (
        rect["x"] >= 0
        and rect["y"] >= 0
        and rect["width"] > 0
        and rect["height"] > 0
        and rect["x"] + rect["width"] <= canvas.get("width", 0)
        and rect["y"] + rect["height"] <= canvas.get("height", 0)
    )


def rect_within_rect(inner: dict, outer: dict) -> bool:
    return (
        inner.get("x", 0) >= outer.get("x", 0)
        and inner.get("y", 0) >= outer.get("y", 0)
        and inner.get("x", 0) + inner.get("width", 0)
        <= outer.get("x", 0) + outer.get("width", 0)
        and inner.get("y", 0) + inner.get("height", 0)
        <= outer.get("y", 0) + outer.get("height", 0)
    )


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Validate stage6 render-video skeleton artifacts."
    )
    parser.add_argument(
        "artifact_dir",
        nargs="?",
        default="ops/out/video-render",
        help="stage6 render artifact directory containing video_render_manifest.json",
    )
    args = parser.parse_args()

    artifact_dir = Path(args.artifact_dir).resolve()
    if not artifact_dir.exists():
        return fail([f"artifact directory does not exist: {artifact_dir}"])

    file_names = {path.name for path in artifact_dir.iterdir() if path.is_file()}
    missing = sorted(REQUIRED_FILES - file_names)
    if missing:
        return fail([f"missing files: {', '.join(missing)}"])

    scene_profile = load_json(artifact_dir / "visual_scene_profile.json")
    manifest = load_json(artifact_dir / "video_render_manifest.json")
    frame_sequence = load_json(artifact_dir / "offline_frame_sequence.json")
    poster_header = ppm_header(artifact_dir / "video_render_poster.ppm")
    source_dir = Path(manifest.get("source_artifact_dir", ""))
    source_scene_path = source_dir / manifest.get("source_scene_file", "")
    source_scene = load_json(source_scene_path) if source_scene_path.exists() else {}
    checks: list[dict] = []

    scene_profile_errors = validate_scene_profile_payload(
        scene_profile,
        allow_output_metadata=True,
    )
    frames = frame_sequence.get("frames", [])
    canvas = frame_sequence.get("canvas", {})
    title_area = frame_sequence.get("title_area", {})
    soundscape_badges = frame_sequence.get("soundscape_badges", {})
    footer_progress_area = frame_sequence.get("footer_progress_area", {})
    selector_label_sprites = frame_sequence.get("selector_label_sprites", {})
    spectrum_trails = frame_sequence.get("spectrum_trails", {})
    short_safe_layout = frame_sequence.get("short_safe_layout", {})
    text_overrides = frame_sequence.get("text_overrides", {})
    mp4_generated = manifest.get("mp4_generation", {}).get("generated", False)
    mp4_path = artifact_dir / "offline_preview.mp4"
    manifest_probe = manifest.get("mp4_generation", {}).get("probe")
    local_probe = probe_mp4(mp4_path) if mp4_generated else None
    mp4_probe = local_probe or manifest_probe
    probe_source = (
        "local_ffprobe"
        if local_probe is not None
        else "manifest"
        if manifest_probe is not None
        else "none"
    )
    expected_frame_count = manifest.get("mp4_generation", {}).get(
        "expected_frame_count",
        frame_sequence.get("summary", {}).get("frame_count"),
    )
    expected_fps = manifest.get("mp4_generation", {}).get(
        "expected_fps",
        canvas.get("fps"),
    )
    expected_duration = manifest.get("mp4_generation", {}).get(
        "expected_duration_seconds",
        frame_sequence.get("summary", {}).get("render_duration_seconds"),
    )
    duration_tolerance = manifest.get("mp4_generation", {}).get(
        "duration_tolerance_seconds",
        max(0.05, 1.5 / canvas.get("fps", 1)) if canvas.get("fps") else 0.05,
    )
    fps_tolerance = manifest.get("mp4_generation", {}).get("fps_tolerance", 0.01)
    frame_count_tolerance = manifest.get("mp4_generation", {}).get("frame_count_tolerance", 0)
    expected_keyframe_interval = manifest.get("mp4_generation", {}).get(
        "expected_keyframe_interval_frames"
    )
    keyframe_interval_tolerance = manifest.get("mp4_generation", {}).get(
        "keyframe_interval_tolerance_frames",
        0,
    )
    expected_stream_layout = manifest.get("mp4_generation", {}).get("expected_stream_layout", {})
    artifact_integrity = manifest.get("artifact_integrity", {})
    probed_stream = (
        mp4_probe.get("streams", [{}])[0]
        if isinstance(mp4_probe, dict) and "streams" in mp4_probe
        else {}
    )
    if isinstance(mp4_probe, dict) and mp4_probe.get("status") == "ok":
        mp4_width = mp4_probe.get("width")
        mp4_height = mp4_probe.get("height")
        mp4_avg_fps = mp4_probe.get("avg_frame_rate_value")
        mp4_duration = mp4_probe.get("duration_seconds")
        mp4_nb_frames = mp4_probe.get("nb_frames_value")
        mp4_video_stream_count = mp4_probe.get("video_stream_count")
        mp4_audio_stream_count = mp4_probe.get("audio_stream_count")
        mp4_keyframes = mp4_probe.get("keyframes", {})
    else:
        mp4_width = probed_stream.get("width")
        mp4_height = probed_stream.get("height")
        mp4_avg_fps = parse_rate(probed_stream.get("avg_frame_rate"))
        mp4_nb_frames = (
            int(probed_stream["nb_frames"])
            if str(probed_stream.get("nb_frames", "")).isdigit()
            else None
        )
        mp4_video_stream_count = None
        mp4_audio_stream_count = None
        mp4_keyframes = {}
        mp4_duration = parse_rate(
            mp4_probe.get("format", {}).get("duration")
            if isinstance(mp4_probe, dict)
            else None
        )

    checks.append(
        build_check(
            "stage",
            manifest.get("stage") == "stage6_video_render"
            and frame_sequence.get("stage") == "stage6_video_render",
            {
                "manifest_stage": manifest.get("stage"),
                "frame_sequence_stage": frame_sequence.get("stage"),
            },
        )
    )
    checks.append(
        build_check(
            "scene_profile_contract",
            not scene_profile_errors,
            {
                "schema_file": str(SCENE_PROFILE_SCHEMA_PATH),
                "error_count": len(scene_profile_errors),
                "errors": scene_profile_errors,
            },
        )
    )
    checks.append(
        build_check(
            "scene_profile_identity",
            manifest.get("visual_scene_profile_id") == scene_profile.get("profile_id")
            and frame_sequence.get("visual_scene_profile_id") == scene_profile.get("profile_id")
            and manifest.get("visual_scene_profile_source") == scene_profile.get("source")
            and frame_sequence.get("visual_scene_profile_source") == scene_profile.get("source")
            and manifest.get("visual_scene_profile_path") == scene_profile.get("source_path")
            and frame_sequence.get("visual_scene_profile_path") == scene_profile.get("source_path"),
            {
                "manifest_profile_id": manifest.get("visual_scene_profile_id"),
                "frame_sequence_profile_id": frame_sequence.get("visual_scene_profile_id"),
                "profile_id": scene_profile.get("profile_id"),
                "manifest_profile_source": manifest.get("visual_scene_profile_source"),
                "frame_sequence_profile_source": frame_sequence.get("visual_scene_profile_source"),
                "profile_source": scene_profile.get("source"),
                "manifest_profile_path": manifest.get("visual_scene_profile_path"),
                "frame_sequence_profile_path": frame_sequence.get("visual_scene_profile_path"),
                "profile_path": scene_profile.get("source_path"),
            },
        )
    )
    checks.append(
        build_check(
            "source_scene",
            source_dir.exists() and source_scene_path.exists(),
            {
                "source_artifact_dir": str(source_dir),
                "source_scene_file": str(source_scene_path),
            },
        )
    )
    checks.append(
        build_check(
            "scene_contract_blocks",
            frame_sequence.get("title_area") == source_scene.get("title_area")
            and frame_sequence.get("soundscape_badges") == source_scene.get("soundscape_badges")
            and frame_sequence.get("footer_progress_area")
            == source_scene.get("footer_progress_area")
            and frame_sequence.get("selector_label_sprites")
            == source_scene.get("selector_label_sprites")
            and frame_sequence.get("spectrum_trails") == source_scene.get("spectrum_trails")
            and frame_sequence.get("short_safe_layout") == source_scene.get("short_safe_layout")
            and frame_sequence.get("text_overrides") == source_scene.get("text_overrides"),
            {
                "frame_sequence_contract_keys": sorted(
                    key
                    for key in (
                        "title_area",
                        "soundscape_badges",
                        "footer_progress_area",
                        "selector_label_sprites",
                        "spectrum_trails",
                        "short_safe_layout",
                        "text_overrides",
                    )
                    if key in frame_sequence
                ),
                "source_scene_present": bool(source_scene),
            },
        )
    )
    checks.append(
        build_check(
            "canvas",
            canvas.get("width") == scene_profile.get("canvas", {}).get("width")
            and canvas.get("height") == scene_profile.get("canvas", {}).get("height")
            and canvas.get("fps") == scene_profile.get("canvas", {}).get("fps"),
            {
                "frame_canvas": canvas,
                "profile_canvas": scene_profile.get("canvas", {}),
            },
        )
    )
    checks.append(
        build_check(
            "render_duration_contract",
            frame_sequence.get("summary", {}).get("render_duration_seconds")
            == round(
                frame_sequence.get("summary", {}).get("frame_count", 0)
                / max(1, canvas.get("fps", 1)),
                6,
            ),
            {
                "summary_render_duration_seconds": frame_sequence.get("summary", {}).get(
                    "render_duration_seconds"
                ),
                "expected_render_duration_seconds": round(
                    frame_sequence.get("summary", {}).get("frame_count", 0)
                    / max(1, canvas.get("fps", 1)),
                    6,
                ),
            },
        )
    )
    checks.append(
        build_check(
            "mp4_expectation_contract",
            expected_frame_count == frame_sequence.get("summary", {}).get("frame_count")
            and expected_fps == canvas.get("fps")
            and expected_duration == frame_sequence.get("summary", {}).get(
                "render_duration_seconds"
            ),
            {
                "expected_frame_count": expected_frame_count,
                "summary_frame_count": frame_sequence.get("summary", {}).get("frame_count"),
                "expected_fps": expected_fps,
                "canvas_fps": canvas.get("fps"),
                "expected_duration_seconds": expected_duration,
                "summary_render_duration_seconds": frame_sequence.get("summary", {}).get(
                    "render_duration_seconds"
                ),
            },
        )
    )
    required_integrity_files = {
        "visual_scene_profile.json",
        "offline_frame_sequence.json",
        "video_render_poster.ppm",
    }
    if mp4_generated:
        required_integrity_files.add("offline_preview.mp4")
    checks.append(
        build_check(
            "artifact_integrity_manifest",
            required_integrity_files.issubset(set(artifact_integrity.keys())),
            {
                "required_files": sorted(required_integrity_files),
                "manifest_files": sorted(artifact_integrity.keys()),
            },
        )
    )
    actual_integrity = {
        file_name: build_file_fingerprint(artifact_dir / file_name)
        for file_name in sorted(required_integrity_files)
        if (artifact_dir / file_name).exists()
    }
    checks.append(
        build_check(
            "artifact_integrity",
            all(
                artifact_integrity.get(file_name) == actual_integrity.get(file_name)
                for file_name in required_integrity_files
            ),
            {
                "manifest_integrity": {
                    file_name: artifact_integrity.get(file_name)
                    for file_name in sorted(required_integrity_files)
                },
                "actual_integrity": actual_integrity,
            },
        )
    )
    checks.append(
        build_check(
            "mp4_profile_contract",
            manifest.get("mp4_generation", {}).get("video_codec") == EXPECTED_STAGE6_VIDEO_CODEC
            and manifest.get("mp4_generation", {}).get("video_encoder")
            == EXPECTED_STAGE6_VIDEO_ENCODER
            and manifest.get("mp4_generation", {}).get("video_preset")
            == EXPECTED_STAGE6_VIDEO_PRESET
            and manifest.get("mp4_generation", {}).get("pixel_format")
            == EXPECTED_STAGE6_PIXEL_FORMAT
            and manifest.get("mp4_generation", {}).get("scene_cut_disabled") is True,
            {
                "video_codec": manifest.get("mp4_generation", {}).get("video_codec"),
                "video_encoder": manifest.get("mp4_generation", {}).get("video_encoder"),
                "video_preset": manifest.get("mp4_generation", {}).get("video_preset"),
                "pixel_format": manifest.get("mp4_generation", {}).get("pixel_format"),
                "scene_cut_disabled": manifest.get("mp4_generation", {}).get(
                    "scene_cut_disabled"
                ),
                "movflags": manifest.get("mp4_generation", {}).get("movflags"),
            },
        )
    )
    checks.append(
        build_check(
            "frame_count",
            frame_sequence.get("summary", {}).get("frame_count") == len(frames) and len(frames) > 0,
            {
                "summary_frame_count": frame_sequence.get("summary", {}).get("frame_count"),
                "actual_frame_count": len(frames),
            },
        )
    )
    checks.append(
        build_check(
            "title_area_contract",
            rect_within_canvas(title_area, canvas)
            and rect_within_rect(title_area, short_safe_layout)
            and title_area.get("line_count") == len(title_area.get("text_lines", []))
            and title_area.get("line_count")
            == frame_sequence.get("summary", {}).get("title_line_count")
            and title_area.get("text_lines")
            == text_overrides.get("resolved_title_lines"),
            {
                "title_area": title_area,
                "short_safe_layout": short_safe_layout,
                "summary_title_line_count": frame_sequence.get("summary", {}).get(
                    "title_line_count"
                ),
                "resolved_title_lines": text_overrides.get("resolved_title_lines"),
            },
        )
    )
    checks.append(
        build_check(
            "soundscape_badges_contract",
            rect_within_canvas(soundscape_badges, canvas)
            and rect_within_rect(soundscape_badges, short_safe_layout)
            and soundscape_badges.get("badge_count")
            == len(soundscape_badges.get("badges", []))
            and soundscape_badges.get("badge_count")
            == frame_sequence.get("summary", {}).get("soundscape_badge_count")
            and isinstance(soundscape_badges.get("registration_label"), str)
            and soundscape_badges.get("registration_label", "").strip() != ""
            and isinstance(soundscape_badges.get("ambient_label"), str)
            and soundscape_badges.get("ambient_label", "").strip() != ""
            and soundscape_badges.get("combination_hold_progress", {}).get("total_cycles", 0) > 0,
            {
                "soundscape_badges": soundscape_badges,
                "summary_soundscape_badge_count": frame_sequence.get("summary", {}).get(
                    "soundscape_badge_count"
                ),
            },
        )
    )
    checks.append(
        build_check(
            "footer_progress_contract",
            rect_within_canvas(footer_progress_area, canvas)
            and rect_within_rect(footer_progress_area, short_safe_layout)
            and isinstance(footer_progress_area.get("text"), str)
            and footer_progress_area.get("text", "").strip() != "",
            {
                "footer_progress_area": footer_progress_area,
                "short_safe_layout": short_safe_layout,
            },
        )
    )
    checks.append(
        build_check(
            "soundscape_badge_ids",
            [badge.get("badge_id") for badge in soundscape_badges.get("badges", [])]
            == [
                "registration_label",
                "ambient_label",
                "combination_hold_progress",
            ]
            and all(
                isinstance(badge.get("value"), str) and badge.get("value", "").strip() != ""
                for badge in soundscape_badges.get("badges", [])
            ),
            {
                "badge_ids": [badge.get("badge_id") for badge in soundscape_badges.get("badges", [])],
            },
        )
    )
    checks.append(
        build_check(
            "selector_contract",
            rect_within_canvas(selector_label_sprites, canvas)
            and rect_within_rect(selector_label_sprites, short_safe_layout)
            and selector_label_sprites.get("sprite_count")
            == len(selector_label_sprites.get("sprites", []))
            and selector_label_sprites.get("sprite_count")
            == frame_sequence.get("summary", {}).get("selector_label_count"),
            {
                "selector_label_sprites": selector_label_sprites,
                "summary_selector_label_count": frame_sequence.get("summary", {}).get(
                    "selector_label_count"
                ),
            },
        )
    )
    checks.append(
        build_check(
            "selector_sprite_visibility",
            all(
                rect_within_rect(
                    {
                        "x": int(sprite.get("x", 0)),
                        "y": int(sprite.get("y", 0)),
                        "width": int(sprite.get("width", 0)),
                        "height": int(sprite.get("height", 0)),
                    },
                    short_safe_layout,
                )
                and isinstance(sprite.get("text"), str)
                and sprite.get("text", "").strip() != ""
                and sprite.get("idle_motion", {}).get("drift_px", 0)
                <= selector_label_sprites.get("label_padding_px", 0)
                for sprite in selector_label_sprites.get("sprites", [])
            ),
            {
                "short_safe_layout": short_safe_layout,
                "sprite_layout": {
                    sprite.get("sprite_id"): {
                        "x": sprite.get("x"),
                        "y": sprite.get("y"),
                        "width": sprite.get("width"),
                        "height": sprite.get("height"),
                        "drift_px": sprite.get("idle_motion", {}).get("drift_px"),
                    }
                    for sprite in selector_label_sprites.get("sprites", [])
                },
            },
        )
    )
    checks.append(
        build_check(
            "selector_activity_timeline",
            all(
                sum(
                    1
                    for sprite in selector_label_sprites.get("sprites", [])
                    if any(
                        window.get("start_seconds", 0.0)
                        <= frame.get("clock_seconds", 0.0)
                        < window.get("end_seconds", 0.0)
                        for window in sprite.get("active_windows", [])
                    )
                )
                <= 1
                for frame in frames
            )
            and {
                frame.get("active_selector_sprite_id")
                for frame in frames
                if frame.get("active_selector_sprite_id")
            }
            == {
                sprite.get("sprite_id")
                for sprite in selector_label_sprites.get("sprites", [])
                if sprite.get("sprite_id")
            },
            {
                "active_sprite_ids_in_frames": sorted(
                    {
                        frame.get("active_selector_sprite_id")
                        for frame in frames
                        if frame.get("active_selector_sprite_id")
                    }
                ),
                "expected_sprite_ids": sorted(
                    sprite.get("sprite_id")
                    for sprite in selector_label_sprites.get("sprites", [])
                    if sprite.get("sprite_id")
                ),
            },
        )
    )
    checks.append(
        build_check(
            "spectrum_contract",
            rect_within_canvas(spectrum_trails, canvas)
            and rect_within_rect(spectrum_trails, short_safe_layout)
            and spectrum_trails.get("sampled_point_count")
            == len(spectrum_trails.get("sampled_points", []))
            and spectrum_trails.get("sampled_point_count")
            == frame_sequence.get("summary", {}).get("spectrum_sampled_point_count"),
            {
                "spectrum_trails": spectrum_trails,
                "summary_spectrum_sampled_point_count": frame_sequence.get("summary", {}).get(
                    "spectrum_sampled_point_count"
                ),
            },
        )
    )
    checks.append(
        build_check(
            "spectrum_point_bounds",
            all(
                spectrum_trails.get("y", 0)
                <= point.get("trail_y_px", -1)
                <= spectrum_trails.get("y", 0) + spectrum_trails.get("height", 0)
                for point in spectrum_trails.get("sampled_points", [])
            )
            and all(
                point.get("clock_seconds", 0.0) >= 0.0
                for point in spectrum_trails.get("sampled_points", [])
            )
            and all(
                frame.get("spectrum_active_point_index") is None
                or 0
                <= int(frame.get("spectrum_active_point_index"))
                < spectrum_trails.get("sampled_point_count", 0)
                for frame in frames
            ),
            {
                "sampled_point_count": spectrum_trails.get("sampled_point_count"),
                "first_point": spectrum_trails.get("sampled_points", [None])[0],
                "last_point": spectrum_trails.get("sampled_points", [None])[-1]
                if spectrum_trails.get("sampled_points")
                else None,
            },
        )
    )
    checks.append(
        build_check(
            "frame_clock_monotonic",
            all(
                frames[index].get("clock_seconds", 0.0)
                <= frames[index + 1].get("clock_seconds", 0.0)
                for index in range(len(frames) - 1)
            ),
            {
                "first_clock_seconds": frames[0].get("clock_seconds") if frames else None,
                "last_clock_seconds": frames[-1].get("clock_seconds") if frames else None,
            },
        )
    )
    checks.append(
        build_check(
            "voice_pulses_per_frame",
            all(
                len(frame.get("voice_pulses", []))
                == frame_sequence.get("summary", {}).get("lane_count", 0)
                for frame in frames
            ),
            {
                "expected_lane_count": frame_sequence.get("summary", {}).get("lane_count"),
            },
        )
    )
    checks.append(
        build_check(
            "frame_index_contiguous",
            [frame.get("frame_index") for frame in frames]
            == list(range(1, len(frames) + 1)),
            {
                "first_frame_index": frames[0].get("frame_index") if frames else None,
                "last_frame_index": frames[-1].get("frame_index") if frames else None,
            },
        )
    )
    checks.append(
        build_check(
            "poster_ppm",
            poster_header is not None
            and poster_header[0] == "P6"
            and poster_header[1] == canvas.get("width")
            and poster_header[2] == canvas.get("height")
            and poster_header[3] == 255,
            {
                "poster_header": poster_header,
                "canvas": canvas,
            },
        )
    )
    checks.append(
        build_check(
            "mp4_generation",
            (not mp4_generated and not mp4_path.exists())
            or (
                mp4_generated
                and mp4_path.exists()
                and mp4_probe is not None
                and mp4_width == canvas.get("width")
                and mp4_height == canvas.get("height")
                and float_close(mp4_avg_fps, float(expected_fps), float(fps_tolerance))
                and (
                    mp4_nb_frames is None
                    or abs(mp4_nb_frames - int(expected_frame_count)) <= int(frame_count_tolerance)
                )
                and float_close(mp4_duration, float(expected_duration), duration_tolerance)
            ),
            {
                "mp4_generated": mp4_generated,
                "mp4_exists": mp4_path.exists(),
                "mp4_probe": mp4_probe,
                "probe_source": probe_source,
                "expected_frame_count": expected_frame_count,
                "frame_count_tolerance": frame_count_tolerance,
                "expected_fps": expected_fps,
                "fps_tolerance": fps_tolerance,
                "expected_duration_seconds": expected_duration,
                "duration_tolerance_seconds": duration_tolerance,
                "probed_width": mp4_width,
                "probed_height": mp4_height,
                "probed_avg_fps": mp4_avg_fps,
                "probed_nb_frames": mp4_nb_frames,
                "probed_duration_seconds": mp4_duration,
            },
        )
    )
    checks.append(
        build_check(
            "mp4_stream_layout",
            (not mp4_generated and not mp4_path.exists())
            or mp4_probe is None
            or (
                mp4_video_stream_count == expected_stream_layout.get("video_stream_count")
                and mp4_audio_stream_count == expected_stream_layout.get("audio_stream_count")
            ),
            {
                "expected_stream_layout": expected_stream_layout,
                "probed_video_stream_count": mp4_video_stream_count,
                "probed_audio_stream_count": mp4_audio_stream_count,
                "probe_source": probe_source,
            },
        )
    )
    checks.append(
        build_check(
            "mp4_keyframe_contract",
            (not mp4_generated and not mp4_path.exists())
            or mp4_probe is None
            or (
                mp4_keyframes.get("status") == "ok"
                and (
                    mp4_keyframes.get("count", 0) >= 1
                    and float_close(
                        mp4_keyframes.get("first_timestamp_seconds"),
                        0.0,
                        duration_tolerance,
                    )
                    and (
                        expected_keyframe_interval is None
                        or mp4_keyframes.get("max_interval_frames") is None
                        or mp4_keyframes.get("max_interval_frames")
                        <= int(expected_keyframe_interval) + int(keyframe_interval_tolerance)
                    )
                )
            ),
            {
                "expected_keyframe_interval_frames": expected_keyframe_interval,
                "keyframe_interval_tolerance_frames": keyframe_interval_tolerance,
                "keyframes": mp4_keyframes,
                "probe_source": probe_source,
            },
        )
    )

    report = write_report(artifact_dir, frame_sequence, checks)
    failed_checks = [check for check in checks if check["status"] == "failed"]
    if failed_checks:
        return fail([f"{check['check_id']} failed" for check in failed_checks])

    print("stage6 video render validation passed")
    print(f"artifact_dir: {artifact_dir}")
    print(f"frame_count: {report['summary']['frame_count']}")
    print(f"cycle_count: {report['summary']['cycle_count']}")
    print(f"lane_count: {report['summary']['lane_count']}")
    print(f"report_file: {artifact_dir / 'stage6_render_validation_report.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
