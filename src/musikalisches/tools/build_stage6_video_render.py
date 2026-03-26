#!/usr/bin/env python3

from __future__ import annotations

import argparse
import hashlib
import json
import math
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


FONT_5X7 = {
    " ": ("00000", "00000", "00000", "00000", "00000", "00000", "00000"),
    ",": ("00000", "00000", "00000", "00000", "00110", "00110", "00100"),
    ".": ("00000", "00000", "00000", "00000", "00000", "00110", "00110"),
    "/": ("00001", "00010", "00100", "01000", "10000", "00000", "00000"),
    ":": ("00000", "00110", "00110", "00000", "00110", "00110", "00000"),
    "=": ("00000", "11111", "00000", "11111", "00000", "00000", "00000"),
    "-": ("00000", "00000", "00000", "11111", "00000", "00000", "00000"),
    "0": ("01110", "10001", "10011", "10101", "11001", "10001", "01110"),
    "1": ("00100", "01100", "00100", "00100", "00100", "00100", "01110"),
    "2": ("01110", "10001", "00001", "00010", "00100", "01000", "11111"),
    "3": ("11110", "00001", "00001", "01110", "00001", "00001", "11110"),
    "4": ("00010", "00110", "01010", "10010", "11111", "00010", "00010"),
    "5": ("11111", "10000", "10000", "11110", "00001", "00001", "11110"),
    "6": ("01110", "10000", "10000", "11110", "10001", "10001", "01110"),
    "7": ("11111", "00001", "00010", "00100", "01000", "01000", "01000"),
    "8": ("01110", "10001", "10001", "01110", "10001", "10001", "01110"),
    "9": ("01110", "10001", "10001", "01111", "00001", "00001", "01110"),
    "A": ("01110", "10001", "10001", "11111", "10001", "10001", "10001"),
    "B": ("11110", "10001", "10001", "11110", "10001", "10001", "11110"),
    "C": ("01110", "10001", "10000", "10000", "10000", "10001", "01110"),
    "D": ("11100", "10010", "10001", "10001", "10001", "10010", "11100"),
    "E": ("11111", "10000", "10000", "11110", "10000", "10000", "11111"),
    "F": ("11111", "10000", "10000", "11110", "10000", "10000", "10000"),
    "G": ("01110", "10001", "10000", "10111", "10001", "10001", "01110"),
    "H": ("10001", "10001", "10001", "11111", "10001", "10001", "10001"),
    "I": ("01110", "00100", "00100", "00100", "00100", "00100", "01110"),
    "J": ("00111", "00010", "00010", "00010", "10010", "10010", "01100"),
    "K": ("10001", "10010", "10100", "11000", "10100", "10010", "10001"),
    "L": ("10000", "10000", "10000", "10000", "10000", "10000", "11111"),
    "M": ("10001", "11011", "10101", "10101", "10001", "10001", "10001"),
    "N": ("10001", "11001", "10101", "10011", "10001", "10001", "10001"),
    "O": ("01110", "10001", "10001", "10001", "10001", "10001", "01110"),
    "P": ("11110", "10001", "10001", "11110", "10000", "10000", "10000"),
    "Q": ("01110", "10001", "10001", "10001", "10101", "10010", "01101"),
    "R": ("11110", "10001", "10001", "11110", "10100", "10010", "10001"),
    "S": ("01111", "10000", "10000", "01110", "00001", "00001", "11110"),
    "T": ("11111", "00100", "00100", "00100", "00100", "00100", "00100"),
    "U": ("10001", "10001", "10001", "10001", "10001", "10001", "01110"),
    "V": ("10001", "10001", "10001", "10001", "10001", "01010", "00100"),
    "W": ("10001", "10001", "10001", "10101", "10101", "10101", "01010"),
    "X": ("10001", "10001", "01010", "00100", "01010", "10001", "10001"),
    "Y": ("10001", "10001", "01010", "00100", "00100", "00100", "00100"),
    "Z": ("11111", "00001", "00010", "00100", "01000", "10000", "11111"),
}


def text_columns(text: str) -> int:
    return max(0, len(text) * 6 - 1)


def choose_text_scale(text: str, *, max_width: int, preferred_font_size: int) -> int:
    preferred_scale = max(1, int(round(preferred_font_size / 8)))
    max_scale_by_width = max(1, max_width // max(1, text_columns(text)))
    return max(1, min(preferred_scale, max_scale_by_width))


def measure_text(text: str, scale: int) -> tuple[int, int]:
    return text_columns(text) * scale, 7 * scale


def glyph_for_char(character: str) -> tuple[str, ...]:
    glyph = FONT_5X7.get(character)
    if glyph is not None:
        return glyph
    uppercase = character.upper()
    return FONT_5X7.get(uppercase, FONT_5X7[" "])


def draw_text(
    buffer: bytearray,
    width: int,
    height: int,
    text: str,
    x: int,
    y: int,
    scale: int,
    color: tuple[int, int, int],
    alpha: float,
) -> None:
    cursor_x = x
    for character in text:
        glyph = glyph_for_char(character)
        for row_index, row in enumerate(glyph):
            for column_index, bit in enumerate(row):
                if bit != "1":
                    continue
                for dy in range(scale):
                    for dx in range(scale):
                        blend_pixel(
                            buffer,
                            width,
                            height,
                            cursor_x + column_index * scale + dx,
                            y + row_index * scale + dy,
                            color,
                            alpha,
                        )
        cursor_x += 6 * scale


def draw_rect_stroke(
    buffer: bytearray,
    width: int,
    height: int,
    x: int,
    y: int,
    rect_width: int,
    rect_height: int,
    stroke_width: int,
    color: tuple[int, int, int],
    alpha: float,
) -> None:
    for offset in range(max(1, stroke_width)):
        draw_hline(buffer, width, height, x, y + offset, x + rect_width, color, alpha)
        draw_hline(
            buffer,
            width,
            height,
            x,
            y + rect_height - 1 - offset,
            x + rect_width,
            color,
            alpha,
        )
        draw_vline(buffer, width, height, x + offset, y, y + rect_height, color, alpha)
        draw_vline(
            buffer,
            width,
            height,
            x + rect_width - 1 - offset,
            y,
            y + rect_height,
            color,
            alpha,
        )


def draw_line(
    buffer: bytearray,
    width: int,
    height: int,
    x0: float,
    y0: float,
    x1: float,
    y1: float,
    color: tuple[int, int, int],
    alpha: float,
    stroke_width: int,
) -> None:
    steps = max(abs(int(round(x1 - x0))), abs(int(round(y1 - y0))), 1)
    for step in range(steps + 1):
        ratio = step / steps
        x = int(round(lerp(x0, x1, ratio)))
        y = int(round(lerp(y0, y1, ratio)))
        radius = max(0, stroke_width // 2)
        for dy in range(-radius, radius + 1):
            for dx in range(-radius, radius + 1):
                blend_pixel(buffer, width, height, x + dx, y + dy, color, alpha)


def draw_polyline(
    buffer: bytearray,
    width: int,
    height: int,
    points: list[tuple[float, float]],
    color: tuple[int, int, int],
    alpha: float,
    stroke_width: int,
) -> None:
    for index in range(len(points) - 1):
        draw_line(
            buffer,
            width,
            height,
            points[index][0],
            points[index][1],
            points[index + 1][0],
            points[index + 1][1],
            color,
            alpha,
            stroke_width,
        )


def rect_contains_rect(outer: dict, inner: dict) -> bool:
    return (
        inner.get("x", 0) >= outer.get("x", 0)
        and inner.get("y", 0) >= outer.get("y", 0)
        and inner.get("x", 0) + inner.get("width", 0)
        <= outer.get("x", 0) + outer.get("width", 0)
        and inner.get("y", 0) + inner.get("height", 0)
        <= outer.get("y", 0) + outer.get("height", 0)
    )


def is_window_active(window: dict, clock_seconds: float) -> bool:
    return window.get("start_seconds", 0.0) <= clock_seconds < window.get("end_seconds", 0.0)


def find_active_selector_sprite(selector_block: dict, clock_seconds: float) -> dict | None:
    for sprite in selector_block.get("sprites", []):
        if any(is_window_active(window, clock_seconds) for window in sprite.get("active_windows", [])):
            return sprite
    return None


def find_spectrum_active_point_index(spectrum_block: dict, clock_seconds: float) -> int | None:
    sampled_points = spectrum_block.get("sampled_points", [])
    if not sampled_points:
        return None
    active_index = 0
    for index, point in enumerate(sampled_points):
        if point.get("clock_seconds", 0.0) <= clock_seconds:
            active_index = index
        else:
            break
    return active_index


def spectrum_point_x(spectrum_block: dict, index: int) -> float:
    count = max(1, spectrum_block.get("sampled_point_count", 0) - 1)
    return spectrum_block["x"] + index * (spectrum_block["width"] / count)


def build_title_line_layout(title_area: dict) -> list[dict]:
    text_lines = title_area.get("text_lines", [])
    if not text_lines:
        return []
    line_gap = title_area["line_gap_px"]
    preferred = title_area["base_font_size_px"]
    scales = [
        choose_text_scale(
            line,
            max_width=title_area["width"],
            preferred_font_size=preferred,
        )
        for line in text_lines
    ]
    line_heights = [7 * scale for scale in scales]
    total_height = sum(line_heights) + line_gap * max(0, len(text_lines) - 1)
    cursor_y = title_area["y"] + max(0, (title_area["height"] - total_height) // 2)
    layout: list[dict] = []
    for index, line in enumerate(text_lines):
        line_width, line_height = measure_text(line, scales[index])
        layout.append(
            {
                "text": line,
                "scale": scales[index],
                "x": int(round(title_area["x"] + (title_area["width"] - line_width) / 2)),
                "y": int(round(cursor_y)),
                "width": line_width,
                "height": line_height,
            }
        )
        cursor_y += line_height + line_gap
    return layout


def draw_title_overlay(
    buffer: bytearray,
    width: int,
    height: int,
    title_area: dict,
    frame: dict,
    scene: dict,
) -> None:
    accent_rgb = hex_to_rgb(frame["cycle_accent_color"])
    text_rgb = hex_to_rgb(scene["palette"]["text_color"])
    for line_index, line in enumerate(build_title_line_layout(title_area)):
        phase = frame["clock_seconds"] * 2.4 + line_index * 0.9
        jitter_x = int(round(lerp(-2.0, 2.0, (1.0 + math.sin(phase)) / 2.0)))
        jitter_y = int(round(lerp(-1.0, 1.0, (1.0 + math.cos(phase * 0.7)) / 2.0)))
        for glow_offset in ((-1, 0), (1, 0), (0, -1), (0, 1)):
            draw_text(
                buffer,
                width,
                height,
                line["text"],
                line["x"] + jitter_x + glow_offset[0],
                line["y"] + jitter_y + glow_offset[1],
                line["scale"],
                accent_rgb,
                0.12,
            )
        draw_text(
            buffer,
            width,
            height,
            line["text"],
            line["x"],
            line["y"],
            line["scale"],
            text_rgb,
            0.95,
        )


def draw_footer_overlay(
    buffer: bytearray,
    width: int,
    height: int,
    footer_area: dict,
    frame: dict,
    scene: dict,
) -> None:
    text = footer_area.get("text", "")
    scale = choose_text_scale(
        text,
        max_width=footer_area["width"],
        preferred_font_size=footer_area["font_size_px"],
    )
    text_width, text_height = measure_text(text, scale)
    x = int(round(footer_area["x"] + (footer_area["width"] - text_width) / 2))
    y = int(round(footer_area["y"] + (footer_area["height"] - text_height) / 2))
    accent_rgb = hex_to_rgb(frame["cycle_accent_color"])
    text_rgb = hex_to_rgb(scene["palette"]["text_color"])
    draw_text(buffer, width, height, text, x, y + 1, scale, accent_rgb, 0.18)
    draw_text(buffer, width, height, text, x, y, scale, text_rgb, 0.92)


def layout_soundscape_badges(soundscape_badges: dict) -> list[dict]:
    badges = soundscape_badges.get("badges", [])
    badge_count = len(badges)
    if badge_count == 0:
        return []
    gap = soundscape_badges.get("badge_gap_px", 0)
    badge_height = max(
        1,
        int(
            (soundscape_badges["height"] - gap * max(0, badge_count - 1))
            / max(1, badge_count)
        ),
    )
    rows: list[dict] = []
    for index, badge in enumerate(badges):
        rows.append(
            {
                "badge": badge,
                "x": soundscape_badges["x"],
                "y": soundscape_badges["y"] + index * (badge_height + gap),
                "width": soundscape_badges["width"],
                "height": badge_height,
            }
        )
    return rows


def resolve_soundscape_badge_text(badge: dict, frame: dict) -> str:
    progress = badge.get("progress")
    if isinstance(progress, dict):
        total_cycles = max(1, int(progress.get("total_cycles", 1)))
        current_cycle = max(
            1,
            min(total_cycles, int(frame.get("cycle_index", progress.get("current_cycle_index", 1)))),
        )
        return progress.get("value_template", "{current_cycle} / {total_cycles}").format(
            current_cycle=current_cycle,
            total_cycles=total_cycles,
        )
    return badge.get("value", "")


def draw_soundscape_overlay(
    buffer: bytearray,
    width: int,
    height: int,
    soundscape_badges: dict,
    frame: dict,
    scene: dict,
) -> None:
    panel_rgb = hex_to_rgb(scene["palette"]["panel_color"])
    text_rgb = hex_to_rgb(scene["palette"]["text_color"])
    for row in layout_soundscape_badges(soundscape_badges):
        badge = row["badge"]
        accent_rgb = hex_to_rgb(badge["accent_color"])
        fill_rect(
            buffer,
            width,
            height,
            row["x"],
            row["y"],
            row["width"],
            row["height"],
            panel_rgb,
            0.82,
        )
        draw_rect_stroke(
            buffer,
            width,
            height,
            row["x"],
            row["y"],
            row["width"],
            row["height"],
            2,
            accent_rgb,
            0.92,
        )
        text = f"{badge['title']}: {resolve_soundscape_badge_text(badge, frame)}"
        scale = choose_text_scale(
            text,
            max_width=max(1, row["width"] - 24),
            preferred_font_size=soundscape_badges["font_size_px"],
        )
        text_height = measure_text(text, scale)[1]
        x = row["x"] + 12
        y = int(round(row["y"] + (row["height"] - text_height) / 2))
        draw_text(buffer, width, height, text, x, y + 1, scale, accent_rgb, 0.18)
        draw_text(buffer, width, height, text, x, y, scale, text_rgb, 0.94)


def draw_selector_overlay(
    buffer: bytearray,
    width: int,
    height: int,
    selector_block: dict,
    frame: dict,
    scene: dict,
) -> None:
    text_rgb = hex_to_rgb(scene["palette"]["text_color"])
    panel_rgb = hex_to_rgb(scene["palette"]["panel_color"])
    safe_layout = scene["short_safe_layout"]
    for sprite in selector_block.get("sprites", []):
        active_windows = sprite.get("active_windows", [])
        active_window = next(
            (window for window in active_windows if is_window_active(window, frame["clock_seconds"])),
            None,
        )
        idle_phase = frame["clock_seconds"] * 1.6 + sprite["position_index"] * 0.7
        drift_ratio = (1.0 + math.sin(idle_phase)) / 2.0
        x_offset = lerp(
            -sprite["idle_motion"]["drift_px"],
            sprite["idle_motion"]["drift_px"],
            drift_ratio,
        )
        y_offset = 0.0
        scale_multiplier = 1.0
        fill_alpha = 0.74
        stroke_alpha = 0.8
        if active_window is not None:
            progress = clamp(
                (frame["clock_seconds"] - active_window["start_seconds"])
                / max(1e-9, active_window["end_seconds"] - active_window["start_seconds"]),
                0.0,
                1.0,
            )
            bounce = math.sin(progress * math.pi)
            y_offset = -sprite["active_motion"]["bounce_y_px"] * bounce
            scale_multiplier = 1.0 + (
                sprite["active_motion"]["scale_multiplier"] - 1.0
            ) * bounce
            fill_alpha = 0.88
            stroke_alpha = 0.95
        rect_width = max(1, int(round(sprite["width"] * scale_multiplier)))
        rect_height = max(1, int(round(sprite["height"] * scale_multiplier)))
        rect_x = int(round(sprite["x"] + x_offset - (rect_width - sprite["width"]) / 2))
        rect_y = int(round(sprite["y"] + y_offset - (rect_height - sprite["height"]) / 2))
        rect_x = min(
            max(rect_x, safe_layout["x"]),
            safe_layout["x"] + safe_layout["width"] - rect_width,
        )
        rect_y = min(
            max(rect_y, safe_layout["y"]),
            safe_layout["y"] + safe_layout["height"] - rect_height,
        )
        accent_rgb = hex_to_rgb(sprite["accent_color"])
        fill_rect(buffer, width, height, rect_x, rect_y, rect_width, rect_height, panel_rgb, fill_alpha)
        draw_rect_stroke(
            buffer,
            width,
            height,
            rect_x,
            rect_y,
            rect_width,
            rect_height,
            2 if active_window is not None else 1,
            accent_rgb,
            stroke_alpha,
        )
        scale = choose_text_scale(
            sprite["text"],
            max_width=max(1, rect_width - 12),
            preferred_font_size=int(round(sprite["font_size_px"] * scale_multiplier)),
        )
        text_width, text_height = measure_text(sprite["text"], scale)
        text_x = rect_x + max(0, (rect_width - text_width) // 2)
        text_y = rect_y + max(0, (rect_height - text_height) // 2)
        draw_text(buffer, width, height, sprite["text"], text_x, text_y, scale, accent_rgb, 0.18)
        draw_text(buffer, width, height, sprite["text"], text_x, text_y, scale, text_rgb, 0.95)


def draw_spectrum_overlay(
    buffer: bytearray,
    width: int,
    height: int,
    spectrum_block: dict,
    frame: dict,
) -> None:
    sampled_points = spectrum_block.get("sampled_points", [])
    if len(sampled_points) < 2:
        return
    active_index = find_spectrum_active_point_index(spectrum_block, frame["clock_seconds"])
    if active_index is None:
        return
    accent_rgb = hex_to_rgb(frame["cycle_accent_color"])
    draw_rect_stroke(
        buffer,
        width,
        height,
        spectrum_block["x"],
        spectrum_block["y"],
        spectrum_block["width"],
        spectrum_block["height"],
        1,
        accent_rgb,
        0.12,
    )
    for layer_index in range(spectrum_block.get("trail_count", 0)):
        layer_end = max(1, active_index - layer_index * 3)
        layer_start = max(0, layer_end - 18)
        layer_points = [
            (
                spectrum_point_x(spectrum_block, point_index),
                sampled_points[point_index]["trail_y_px"],
            )
            for point_index in range(layer_start, layer_end + 1)
        ]
        if len(layer_points) < 2:
            continue
        layer_alpha = clamp(
            spectrum_block["alpha_base"]
            + ((spectrum_block["trail_count"] - layer_index) / max(1, spectrum_block["trail_count"]))
            * spectrum_block["alpha_range"],
            0.04,
            0.45,
        )
        stroke_width = int(
            round(
                lerp(
                    spectrum_block["stroke_min_width_px"],
                    spectrum_block["stroke_max_width_px"],
                    1.0 - layer_index / max(1, spectrum_block["trail_count"]),
                )
            )
        )
        draw_polyline(
            buffer,
            width,
            height,
            layer_points,
            accent_rgb,
            layer_alpha * 0.9,
            max(1, stroke_width),
        )
    active_point = sampled_points[active_index]
    draw_circle_fill(
        buffer,
        width,
        height,
        int(round(spectrum_point_x(spectrum_block, active_index))),
        int(round(active_point["trail_y_px"])),
        5,
        accent_rgb,
        0.38,
    )


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

        active_selector = find_active_selector_sprite(
            scene.get("selector_label_sprites", {}),
            clock_seconds,
        )
        active_spectrum_index = find_spectrum_active_point_index(
            scene.get("spectrum_trails", {}),
            clock_seconds,
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
                "active_selector_sprite_id": (
                    active_selector.get("sprite_id") if active_selector else None
                ),
                "active_selector_position_index": (
                    active_selector.get("position_index") if active_selector else None
                ),
                "active_selector_value": (
                    active_selector.get("selector_value") if active_selector else None
                ),
                "spectrum_active_point_index": active_spectrum_index,
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
        "title_area": scene["title_area"],
        "soundscape_badges": scene["soundscape_badges"],
        "footer_progress_area": scene["footer_progress_area"],
        "selector_label_sprites": scene["selector_label_sprites"],
        "spectrum_trails": scene["spectrum_trails"],
        "short_safe_layout": scene["short_safe_layout"],
        "text_overrides": scene["text_overrides"],
        "frames": frames,
        "summary": {
            "frame_count": len(frames),
            "lane_count": scene["summary"]["lane_count"],
            "cycle_count": scene["summary"]["cycle_count"],
            "window_count": scene["summary"]["window_count"],
            "selector_label_count": scene["summary"]["selector_label_count"],
            "soundscape_badge_count": scene["summary"]["soundscape_badge_count"],
            "title_line_count": scene["summary"]["title_line_count"],
            "spectrum_sampled_point_count": scene["spectrum_trails"]["sampled_point_count"],
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
    safe_layout = scene.get("short_safe_layout", {})
    if safe_layout:
        draw_rect_stroke(
            buffer,
            width,
            height,
            safe_layout["x"],
            safe_layout["y"],
            safe_layout["width"],
            safe_layout["height"],
            1,
            hex_to_rgb(palette["grid_color"]),
            0.16,
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
    draw_spectrum_overlay(
        buffer,
        width,
        height,
        scene.get("spectrum_trails", {}),
        frame,
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

    draw_selector_overlay(
        buffer,
        width,
        height,
        scene.get("selector_label_sprites", {}),
        frame,
        scene,
    )
    draw_title_overlay(
        buffer,
        width,
        height,
        scene.get("title_area", {}),
        frame,
        scene,
    )
    draw_soundscape_overlay(
        buffer,
        width,
        height,
        scene.get("soundscape_badges", {}),
        frame,
        scene,
    )
    draw_footer_overlay(
        buffer,
        width,
        height,
        scene.get("footer_progress_area", {}),
        frame,
        scene,
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
            "selector_label_count": frame_sequence["summary"]["selector_label_count"],
            "soundscape_badge_count": frame_sequence["summary"]["soundscape_badge_count"],
            "title_line_count": frame_sequence["summary"]["title_line_count"],
            "spectrum_sampled_point_count": frame_sequence["summary"][
                "spectrum_sampled_point_count"
            ],
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
