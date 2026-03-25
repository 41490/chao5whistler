#!/usr/bin/env python3

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import tempfile
from pathlib import Path

from stage6_scene_profile import validate_scene_profile_payload


REQUIRED_INPUT_FILES = {
    "visual_scene_profile.json",
    "video_stub_manifest.json",
    "video_stub_scene.json",
    "stage6_validation_report.json",
}
MP4_VIDEO_CODEC = "h264"
MP4_VIDEO_ENCODER = "libx264"
MP4_VIDEO_PRESET = "ultrafast"
MP4_PIXEL_FORMAT = "yuv420p"
MP4_KEYFRAME_INTERVAL_SECONDS = 2
MP4_FRAME_COUNT_TOLERANCE = 1
MP4_FPS_TOLERANCE = 0.01
MP4_KEYFRAME_INTERVAL_TOLERANCE_FRAMES = 1


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: dict) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=True, indent=2) + "\n",
        encoding="utf-8",
    )


def write_ppm(path: Path, width: int, height: int, payload: bytes) -> None:
    with path.open("wb") as handle:
        handle.write(f"P6\n{width} {height}\n255\n".encode("ascii"))
        handle.write(payload)


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


def clamp(value: float, lower: float, upper: float) -> float:
    return min(upper, max(lower, value))


def lerp(left: float, right: float, ratio: float) -> float:
    return left + (right - left) * ratio


def hex_to_rgb(value: str) -> tuple[int, int, int]:
    return tuple(int(value[index : index + 2], 16) for index in (1, 3, 5))


def build_frame_sequence(scene: dict) -> dict:
    keyframes = scene.get("keyframes", [])
    if not keyframes:
        raise SystemExit("video stub scene must contain at least one keyframe")

    fps = scene["canvas"]["fps"]
    duration = scene["summary"]["total_duration_seconds"]
    total_frames = max(1, round(duration * fps))
    cycles = scene.get("cycles", [])
    right_cursor = 1
    frames: list[dict] = []

    for frame_index in range(total_frames):
        clock_seconds = frame_index / fps
        while (
            right_cursor < len(keyframes)
            and keyframes[right_cursor]["clock_seconds"] < clock_seconds
        ):
            right_cursor += 1
        left_keyframe = keyframes[max(0, right_cursor - 1)]
        right_keyframe = keyframes[min(right_cursor, len(keyframes) - 1)]
        if right_keyframe["clock_seconds"] <= left_keyframe["clock_seconds"]:
            ratio = 0.0
        else:
            ratio = clamp(
                (clock_seconds - left_keyframe["clock_seconds"])
                / (right_keyframe["clock_seconds"] - left_keyframe["clock_seconds"]),
                0.0,
                1.0,
            )

        cycle = (
            cycles[-1]
            if cycles
            else {
                "cycle_index": 1,
                "accent_color": scene["palette"]["colors"]["cyan"],
            }
        )
        for candidate in cycles:
            if candidate["start_seconds"] <= clock_seconds < candidate["end_seconds"]:
                cycle = candidate
                break

        right_pulses = {
            pulse["lane_id"]: pulse for pulse in right_keyframe.get("voice_pulses", [])
        }
        voice_pulses: list[dict] = []
        for left_pulse in left_keyframe.get("voice_pulses", []):
            right_pulse = right_pulses.get(left_pulse["lane_id"], left_pulse)
            voice_pulses.append(
                {
                    "lane_id": left_pulse["lane_id"],
                    "part_index": left_pulse["part_index"],
                    "channel": left_pulse["channel"],
                    "color": left_pulse["color"],
                    "center_x": round(
                        lerp(left_pulse["center_x"], right_pulse["center_x"], ratio),
                        2,
                    ),
                    "center_y": round(
                        lerp(left_pulse["center_y"], right_pulse["center_y"], ratio),
                        2,
                    ),
                    "radius_px": round(
                        lerp(left_pulse["radius_px"], right_pulse["radius_px"], ratio),
                        2,
                    ),
                    "stroke_width_px": round(
                        lerp(
                            left_pulse["stroke_width_px"],
                            right_pulse["stroke_width_px"],
                            ratio,
                        ),
                        2,
                    ),
                    "opacity": round(
                        lerp(left_pulse["opacity"], right_pulse["opacity"], ratio),
                        3,
                    ),
                    "orbit_offset_px": round(
                        lerp(
                            left_pulse["orbit_offset_px"],
                            right_pulse["orbit_offset_px"],
                            ratio,
                        ),
                        2,
                    ),
                }
            )

        frames.append(
            {
                "frame_index": frame_index + 1,
                "clock_seconds": round6(clock_seconds),
                "cycle_index": cycle["cycle_index"],
                "cycle_accent_color": cycle["accent_color"],
                "source_window_index": left_keyframe["window_index"],
                "source_window_clock_seconds": left_keyframe["clock_seconds"],
                "grid_alpha": round(
                    lerp(left_keyframe["grid_alpha"], right_keyframe["grid_alpha"], ratio),
                    3,
                ),
                "global_scale": round(
                    lerp(
                        left_keyframe["global_scale"],
                        right_keyframe["global_scale"],
                        ratio,
                    ),
                    3,
                ),
                "rotation_degrees": round(
                    lerp(
                        left_keyframe["rotation_degrees"],
                        right_keyframe["rotation_degrees"],
                        ratio,
                    ),
                    2,
                ),
                "background_color": scene["canvas"]["background_color"],
                "voice_pulses": voice_pulses,
            }
        )

    return {
        "stage": "stage6_video_render",
        "work_id": scene["work_id"],
        "source_stage": scene["stage"],
        "visual_scene_profile_id": scene["visual_scene_profile_id"],
        "visual_scene_profile_source": scene["visual_scene_profile_source"],
        "visual_scene_profile_path": scene["visual_scene_profile_path"],
        "canvas": scene["canvas"],
        "palette": {
            "palette_id": scene["palette"]["palette_id"],
            "background_color": scene["palette"]["background_color"],
            "panel_color": scene["palette"]["panel_color"],
            "grid_color": scene["palette"]["grid_color"],
            "text_color": scene["palette"]["text_color"],
        },
        "motion": {
            "mode": scene["motion"]["mode"],
            "clock_source": scene["motion"]["clock_source"],
            "keyframe_source": scene["motion"]["keyframe_source"],
        },
        "frames": frames,
        "summary": {
            "frame_count": len(frames),
            "lane_count": scene["summary"]["lane_count"],
            "cycle_count": scene["summary"]["cycle_count"],
            "window_count": scene["summary"]["window_count"],
            "fps": scene["canvas"]["fps"],
            "frame_interval_seconds": round6(1.0 / scene["canvas"]["fps"]),
            "render_duration_seconds": round6(len(frames) / scene["canvas"]["fps"]),
            "total_duration_seconds": scene["summary"]["total_duration_seconds"],
            "sample_rate": scene["summary"]["sample_rate"],
        },
    }


def build_base_canvas(scene: dict) -> bytearray:
    width = scene["canvas"]["width"]
    height = scene["canvas"]["height"]
    palette = scene["palette"]
    background = bytes(hex_to_rgb(palette["background_color"]))
    buffer = bytearray(background * (width * height))
    panel_margin = 48
    fill_rect(
        buffer,
        width,
        height,
        panel_margin,
        panel_margin,
        width - panel_margin * 2,
        height - panel_margin * 2,
        hex_to_rgb(palette["panel_color"]),
        1.0,
    )
    guide_alpha = clamp(scene["motion"]["grid_alpha_base"] + 0.08, 0.0, 0.4)
    for lane in scene.get("lane_layout", []):
        draw_hline(
            buffer,
            width,
            height,
            panel_margin,
            int(round(lane["center_y"])),
            width - panel_margin,
            hex_to_rgb(palette["grid_color"]),
            guide_alpha,
        )
        draw_vline(
            buffer,
            width,
            height,
            int(round(lane["center_x"])),
            panel_margin + 32,
            height - panel_margin - 64,
            hex_to_rgb(palette["grid_color"]),
            guide_alpha * 0.7,
        )
    return buffer


def render_frame_bytes(scene: dict, frame: dict, base_canvas: bytearray) -> bytes:
    width = scene["canvas"]["width"]
    height = scene["canvas"]["height"]
    buffer = bytearray(base_canvas)
    accent_rgb = hex_to_rgb(frame["cycle_accent_color"])
    fill_rect(buffer, width, height, 0, height - 30, width, 30, accent_rgb, 0.8)
    draw_hline(
        buffer,
        width,
        height,
        48,
        height - 90,
        width - 48,
        hex_to_rgb(scene["palette"]["grid_color"]),
        clamp(frame["grid_alpha"], 0.05, 0.45),
    )

    for pulse in frame.get("voice_pulses", []):
        center_x = int(round(pulse["center_x"] + pulse["orbit_offset_px"]))
        center_y = int(round(pulse["center_y"]))
        radius = int(round(pulse["radius_px"] * frame["global_scale"]))
        radius = max(18, min(radius, min(width, height) // 3))
        stroke_width = max(1, int(round(pulse["stroke_width_px"])))
        color = hex_to_rgb(pulse["color"])
        opacity = clamp(pulse["opacity"], 0.12, 0.95)
        draw_circle_fill(
            buffer,
            width,
            height,
            center_x,
            center_y,
            max(6, radius // 8),
            color,
            opacity * 0.55,
        )
        draw_circle_stroke(
            buffer,
            width,
            height,
            center_x,
            center_y,
            radius,
            stroke_width,
            color,
            opacity,
        )

    return bytes(buffer)


def blend_pixel(
    buffer: bytearray,
    width: int,
    height: int,
    x: int,
    y: int,
    color: tuple[int, int, int],
    alpha: float,
) -> None:
    if x < 0 or y < 0 or x >= width or y >= height or alpha <= 0.0:
        return
    alpha = clamp(alpha, 0.0, 1.0)
    offset = (y * width + x) * 3
    inverse = 1.0 - alpha
    buffer[offset] = int(round(buffer[offset] * inverse + color[0] * alpha))
    buffer[offset + 1] = int(round(buffer[offset + 1] * inverse + color[1] * alpha))
    buffer[offset + 2] = int(round(buffer[offset + 2] * inverse + color[2] * alpha))


def fill_rect(
    buffer: bytearray,
    width: int,
    height: int,
    x: int,
    y: int,
    rect_width: int,
    rect_height: int,
    color: tuple[int, int, int],
    alpha: float,
) -> None:
    x0 = max(0, x)
    y0 = max(0, y)
    x1 = min(width, x + rect_width)
    y1 = min(height, y + rect_height)
    for row in range(y0, y1):
        for column in range(x0, x1):
            blend_pixel(buffer, width, height, column, row, color, alpha)


def draw_hline(
    buffer: bytearray,
    width: int,
    height: int,
    x0: int,
    y: int,
    x1: int,
    color: tuple[int, int, int],
    alpha: float,
) -> None:
    if y < 0 or y >= height:
        return
    for x in range(max(0, x0), min(width, x1)):
        blend_pixel(buffer, width, height, x, y, color, alpha)


def draw_vline(
    buffer: bytearray,
    width: int,
    height: int,
    x: int,
    y0: int,
    y1: int,
    color: tuple[int, int, int],
    alpha: float,
) -> None:
    if x < 0 or x >= width:
        return
    for y in range(max(0, y0), min(height, y1)):
        blend_pixel(buffer, width, height, x, y, color, alpha)


def draw_circle_fill(
    buffer: bytearray,
    width: int,
    height: int,
    center_x: int,
    center_y: int,
    radius: int,
    color: tuple[int, int, int],
    alpha: float,
) -> None:
    radius_squared = radius * radius
    for y in range(center_y - radius, center_y + radius + 1):
        for x in range(center_x - radius, center_x + radius + 1):
            dx = x - center_x
            dy = y - center_y
            if dx * dx + dy * dy <= radius_squared:
                blend_pixel(buffer, width, height, x, y, color, alpha)


def draw_circle_stroke(
    buffer: bytearray,
    width: int,
    height: int,
    center_x: int,
    center_y: int,
    radius: int,
    stroke_width: int,
    color: tuple[int, int, int],
    alpha: float,
) -> None:
    outer = radius + max(1, stroke_width // 2)
    inner = max(0, radius - max(1, stroke_width // 2))
    outer_squared = outer * outer
    inner_squared = inner * inner
    for y in range(center_y - outer, center_y + outer + 1):
        for x in range(center_x - outer, center_x + outer + 1):
            dx = x - center_x
            dy = y - center_y
            distance_squared = dx * dx + dy * dy
            if inner_squared <= distance_squared <= outer_squared:
                blend_pixel(buffer, width, height, x, y, color, alpha)


def encode_mp4(
    ffmpeg_bin: str,
    output_path: Path,
    width: int,
    height: int,
    fps: int,
    frame_sequence: dict,
    scene: dict,
    base_canvas: bytearray,
) -> None:
    keyframe_interval = max(1, fps * MP4_KEYFRAME_INTERVAL_SECONDS)
    command = [
        ffmpeg_bin,
        "-y",
        "-f",
        "rawvideo",
        "-pix_fmt",
        "rgb24",
        "-video_size",
        f"{width}x{height}",
        "-framerate",
        str(fps),
        "-i",
        "-",
        "-an",
        "-c:v",
        MP4_VIDEO_ENCODER,
        "-preset",
        MP4_VIDEO_PRESET,
        "-g",
        str(keyframe_interval),
        "-keyint_min",
        str(keyframe_interval),
        "-sc_threshold",
        "0",
        "-pix_fmt",
        MP4_PIXEL_FORMAT,
        "-movflags",
        "+faststart",
        str(output_path),
    ]
    with tempfile.TemporaryFile() as stderr_handle:
        process = subprocess.Popen(
            command,
            stdin=subprocess.PIPE,
            stderr=stderr_handle,
        )
        assert process.stdin is not None
        for frame in frame_sequence["frames"]:
            process.stdin.write(render_frame_bytes(scene, frame, base_canvas))
        process.stdin.close()
        exit_code = process.wait()
        if exit_code != 0:
            stderr_handle.seek(0)
            stderr = stderr_handle.read().decode("utf-8", errors="replace")
            raise SystemExit(f"ffmpeg failed with exit code {exit_code}:\n{stderr}")


def probe_mp4(ffprobe_bin: str | None, output_path: Path) -> dict | None:
    if not ffprobe_bin or not output_path.exists():
        return None
    result = subprocess.run(
        [
            ffprobe_bin,
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
            str(output_path),
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return {
            "status": "ffprobe_failed",
            "exit_code": result.returncode,
            "stderr": result.stderr.strip(),
        }

    raw_probe = json.loads(result.stdout)
    format_payload = raw_probe.get("format", {})
    streams = raw_probe.get("streams", [])
    video_streams = [stream for stream in streams if stream.get("codec_type") == "video"]
    audio_streams = [stream for stream in streams if stream.get("codec_type") == "audio"]
    primary_video_stream = video_streams[0] if video_streams else {}
    keyframe_result = subprocess.run(
        [
            ffprobe_bin,
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
            str(output_path),
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
                timestamps.append(round6(timestamp))
        max_interval_seconds = None
        if len(timestamps) >= 2:
            max_interval_seconds = max(
                round6(timestamps[index + 1] - timestamps[index])
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
                int(round(max_interval_seconds * parse_rate(primary_video_stream.get("avg_frame_rate"))))
                if max_interval_seconds is not None
                and parse_rate(primary_video_stream.get("avg_frame_rate")) is not None
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


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Build stage6 render-video skeleton artifacts from stage6 stub outputs."
    )
    parser.add_argument(
        "source_artifact_dir",
        nargs="?",
        default="ops/out/video-stub",
        help="stage6 stub artifact directory containing video_stub_scene.json",
    )
    parser.add_argument(
        "output_dir",
        nargs="?",
        default="ops/out/video-render",
        help="directory where stage6 render artifacts will be written",
    )
    parser.add_argument(
        "--ffmpeg-bin",
        default="ffmpeg",
        help="ffmpeg binary used to encode the mp4 preview",
    )
    parser.add_argument(
        "--skip-mp4",
        action="store_true",
        help="build only the offline frame contract without encoding an mp4 preview",
    )
    args = parser.parse_args()

    source_dir = Path(args.source_artifact_dir).resolve()
    output_dir = Path(args.output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    if not source_dir.exists():
        raise SystemExit(f"source artifact directory does not exist: {source_dir}")

    source_files = {path.name for path in source_dir.iterdir() if path.is_file()}
    missing = sorted(REQUIRED_INPUT_FILES - source_files)
    if missing:
        raise SystemExit(
            "source artifact directory is missing required stage6 files: "
            + ", ".join(missing)
        )

    scene_profile = load_json(source_dir / "visual_scene_profile.json")
    scene_profile_errors = validate_scene_profile_payload(
        scene_profile,
        allow_output_metadata=True,
    )
    if scene_profile_errors:
        raise SystemExit(
            "scene profile validation failed:\n- " + "\n- ".join(scene_profile_errors)
        )

    stub_manifest = load_json(source_dir / "video_stub_manifest.json")
    stub_scene = load_json(source_dir / "video_stub_scene.json")
    stub_validation = load_json(source_dir / "stage6_validation_report.json")
    if stub_validation.get("status") != "passed":
        raise SystemExit("source stage6 stub validation report must have status=passed")

    frame_sequence = build_frame_sequence(stub_scene)
    width = frame_sequence["canvas"]["width"]
    height = frame_sequence["canvas"]["height"]
    fps = frame_sequence["canvas"]["fps"]
    base_canvas = build_base_canvas(stub_scene)

    poster_frame = frame_sequence["frames"][len(frame_sequence["frames"]) // 2]
    poster_path = output_dir / "video_render_poster.ppm"
    write_ppm(
        poster_path,
        width,
        height,
        render_frame_bytes(stub_scene, poster_frame, base_canvas),
    )

    mp4_path = output_dir / "offline_preview.mp4"
    mp4_requested = not args.skip_mp4
    ffmpeg_path = shutil.which(args.ffmpeg_bin) if mp4_requested else None
    ffprobe_path = shutil.which("ffprobe") if mp4_requested else None
    mp4_generated = False
    mp4_reason = None
    mp4_probe = None
    if mp4_requested and not ffmpeg_path:
        mp4_reason = f"ffmpeg binary not found: {args.ffmpeg_bin}"
    elif mp4_requested:
        encode_mp4(
            ffmpeg_path,
            mp4_path,
            width,
            height,
            fps,
            frame_sequence,
            stub_scene,
            base_canvas,
        )
        mp4_generated = True
        mp4_reason = "encoded_with_ffmpeg"
        mp4_probe = probe_mp4(ffprobe_path, mp4_path)
    else:
        mp4_reason = "skipped_by_flag"

    write_json(output_dir / "visual_scene_profile.json", scene_profile)
    write_json(output_dir / "offline_frame_sequence.json", frame_sequence)
    artifact_integrity = {
        "visual_scene_profile.json": build_file_fingerprint(output_dir / "visual_scene_profile.json"),
        "offline_frame_sequence.json": build_file_fingerprint(
            output_dir / "offline_frame_sequence.json"
        ),
        "video_render_poster.ppm": build_file_fingerprint(poster_path),
    }
    if mp4_generated:
        artifact_integrity["offline_preview.mp4"] = build_file_fingerprint(mp4_path)
    duration_tolerance = round6(max(0.05, 1.5 / fps))
    keyframe_interval = max(1, fps * MP4_KEYFRAME_INTERVAL_SECONDS)

    manifest = {
        "stage": "stage6_video_render",
        "description": "Offline frame contract and mp4 preview derived from the stage6 video stub scene.",
        "work_id": stub_scene["work_id"],
        "source_artifact_dir": str(source_dir),
        "source_stage": stub_scene["stage"],
        "source_stub_manifest_stage": stub_manifest.get("stage"),
        "source_scene_file": "video_stub_scene.json",
        "visual_scene_profile_id": frame_sequence["visual_scene_profile_id"],
        "visual_scene_profile_source": frame_sequence["visual_scene_profile_source"],
        "visual_scene_profile_path": frame_sequence["visual_scene_profile_path"],
        "input_files": sorted(REQUIRED_INPUT_FILES),
        "artifacts": {
            "visual_scene_profile_file": "visual_scene_profile.json",
            "frame_sequence_file": "offline_frame_sequence.json",
            "poster_file": "video_render_poster.ppm",
            "preview_video_file": "offline_preview.mp4" if mp4_generated else None,
            "validation_report_file": "stage6_render_validation_report.json",
        },
        "artifact_integrity": artifact_integrity,
        "generation_summary": {
            "frame_count": frame_sequence["summary"]["frame_count"],
            "window_count": frame_sequence["summary"]["window_count"],
            "cycle_count": frame_sequence["summary"]["cycle_count"],
            "lane_count": frame_sequence["summary"]["lane_count"],
            "frame_interval_seconds": frame_sequence["summary"]["frame_interval_seconds"],
            "render_duration_seconds": frame_sequence["summary"]["render_duration_seconds"],
            "total_duration_seconds": frame_sequence["summary"]["total_duration_seconds"],
            "canvas": f"{width}x{height}",
            "fps": fps,
            "motion_mode": frame_sequence["motion"]["mode"],
            "palette_id": frame_sequence["palette"]["palette_id"],
            "render_backend": "python_rgb24_ffmpeg" if mp4_generated else "python_contract_only",
            "mp4_generated": mp4_generated,
            "video_codec": MP4_VIDEO_CODEC,
            "video_encoder": MP4_VIDEO_ENCODER,
            "video_preset": MP4_VIDEO_PRESET,
            "poster_frame_index": poster_frame["frame_index"],
        },
        "mp4_generation": {
            "requested": mp4_requested,
            "generated": mp4_generated,
            "ffmpeg_bin": ffmpeg_path,
            "ffprobe_bin": ffprobe_path,
            "reason": mp4_reason,
            "expected_frame_count": frame_sequence["summary"]["frame_count"],
            "expected_fps": fps,
            "expected_duration_seconds": frame_sequence["summary"]["render_duration_seconds"],
            "frame_count_tolerance": MP4_FRAME_COUNT_TOLERANCE,
            "fps_tolerance": MP4_FPS_TOLERANCE,
            "duration_tolerance_seconds": duration_tolerance,
            "expected_keyframe_interval_frames": keyframe_interval,
            "keyframe_interval_tolerance_frames": MP4_KEYFRAME_INTERVAL_TOLERANCE_FRAMES,
            "expected_stream_layout": {
                "video_stream_count": 1,
                "audio_stream_count": 0,
            },
            "video_codec": MP4_VIDEO_CODEC,
            "video_encoder": MP4_VIDEO_ENCODER,
            "video_preset": MP4_VIDEO_PRESET,
            "pixel_format": MP4_PIXEL_FORMAT,
            "movflags": ["+faststart"],
            "scene_cut_disabled": True,
            "probe": mp4_probe,
        },
    }
    write_json(output_dir / "video_render_manifest.json", manifest)

    print("stage6 video render built")
    print(f"artifact_dir: {output_dir}")
    print(f"profile_id: {frame_sequence['visual_scene_profile_id']}")
    print(f"frame_count: {frame_sequence['summary']['frame_count']}")
    print(f"canvas: {width}x{height}@{fps}")
    print(f"frame_sequence_file: {output_dir / 'offline_frame_sequence.json'}")
    print(f"poster_file: {poster_path}")
    if mp4_generated:
        print(f"preview_video_file: {mp4_path}")
    else:
        print(f"preview_video_skipped: {mp4_reason}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
