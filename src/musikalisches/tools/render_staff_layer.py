#!/usr/bin/env python3
"""Render a centered, horizontally moving five-line staff layer as binary PPM."""
from __future__ import annotations

import argparse
import array
import json
import math
import struct
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]


def resolve_path(value: str) -> Path:
    path = Path(value)
    candidates = (
        path,
        ROOT / path,
        ROOT / "src/musikalisches/runtime" / path,
        ROOT / "src/musikalisches/runtime/config" / path.name,
        ROOT.parents[2] / path,
    )
    for candidate in candidates:
        if candidate.exists():
            return candidate
    raise FileNotFoundError(f"input path not found: {value}")


def color(value: str) -> tuple[int, int, int]:
    value = value.removeprefix("#")
    return (int(value[0:2], 16), int(value[2:4], 16), int(value[4:6], 16))


def blend(pixels: array.array, width: int, x: int, y: int,
           rgb: tuple[int, int, int], alpha: float) -> None:
    if not (0 <= x < width and 0 <= y):
        return
    index = (y * width + x) * 3
    if index + 2 >= len(pixels):
        return
    alpha = max(0.0, min(1.0, alpha))
    try:
        for channel, value in enumerate(rgb):
            pixels[index + channel] = int(pixels[index + channel] * (1 - alpha) + value * alpha)
    except (IndexError, OverflowError, ValueError) as error:
        raise ValueError("invalid raster pixel operation") from error


def disk(pixels: array.array, width: int, height: int, cx: float, cy: float,
         radius: float, rgb: tuple[int, int, int], alpha: float) -> None:
    try:
        left, right = max(0, int(cx - radius)), min(width - 1, int(cx + radius))
        top, bottom = max(0, int(cy - radius)), min(height - 1, int(cy + radius))
    except (OverflowError, ValueError) as error:
        raise ValueError("invalid raster disk geometry") from error
    for y in range(top, bottom + 1):
        for x in range(left, right + 1):
            distance = math.hypot(x - cx, y - cy)
            if distance <= radius:
                blend(pixels, width, x, y, rgb, alpha * (1 - distance / radius) ** 2)


def draw_line(pixels: array.array, width: int, height: int, x1: int, y1: int,
              x2: int, y2: int, rgb: tuple[int, int, int], alpha: float,
              thickness: int = 1) -> None:
    steps = max(abs(x2 - x1), abs(y2 - y1), 1)
    for step in range(steps + 1):
        fraction = step / steps
        x = round(x1 + (x2 - x1) * fraction)
        y = round(y1 + (y2 - y1) * fraction)
        for offset in range(-thickness // 2, thickness // 2 + 1):
            if abs(y2 - y1) >= abs(x2 - x1):
                blend(pixels, width, x + offset, y, rgb, alpha)
            else:
                blend(pixels, width, x, y + offset, rgb, alpha)


def frame_pixels(scene: dict, notes: list[dict], frame: int) -> tuple[int, int, array.array]:
    width, height = scene["canvas"]["width"], scene["canvas"]["height"]
    background = color(scene["palette"]["background_color"])
    pixels = array.array("B", background * (width * height))
    staff_height = round(height * 0.2)
    staff_top = (height - staff_height) // 2
    center_y = height // 2
    fps = scene["canvas"].get("fps", 30)
    clock = frame / fps
    fragment_times: dict[int, list[float]] = {}
    for note in notes:
        fragment_times.setdefault(note["fragment_id"], []).append(note["start_seconds"])
    fragments = sorted(fragment_times)
    starts = {fragment: min(values) for fragment, values in fragment_times.items()}
    duration = max((note["end_seconds"] for note in notes), default=1.0)
    fragment_length = duration / max(len(fragments), 1)
    current = min(fragments, key=lambda fragment: abs(starts[fragment] - clock)) if fragments else None
    line_rgb = color(scene["palette"]["grid_color"])
    note_rgb = color(scene["palette"]["colors"]["cyan"])
    active_rgb = color(scene["palette"]["colors"]["yellow"])
    for line in range(5):
        y = staff_top + 30 + line * 21
        draw_line(pixels, width, height, 0, y, width - 1, y, line_rgb, 0.8, 2)
    pixels_per_second = width / max(fragment_length * 4.0, 1.0)
    for note in notes:
        fragment = note["fragment_id"]
        origin = starts[current] if current is not None else clock
        delta = starts[fragment] - origin
        is_current = fragment == current
        x = width / 2 if is_current else width / 2 + (-delta if delta > 0 else -delta) * pixels_per_second * (-1 if delta > 0 else 1)
        note_age = clock - note["start_seconds"]
        active_pulse = math.exp(-abs(note_age) / max(fragment_length * 0.35, 0.01))
        fade = (0.78 + 0.22 * active_pulse) if is_current else math.exp(-abs(delta) / max(fragment_length * 3, 0.01))
        y = center_y + (64 - note["midi"]) * 7
        if not staff_top - 20 <= y <= staff_top + staff_height + 20 or not -30 <= x <= width + 30:
            continue
        rgb = active_rgb if is_current else note_rgb
        disk(pixels, width, height, x, y, 14, rgb, 0.10 * fade)
        disk(pixels, width, height, x, y, 5, rgb, 0.35 * fade)
        disk(pixels, width, height, x, y, 2.5, rgb, 0.95 * fade)
        draw_line(pixels, width, height, round(x + 3), round(y), round(x + 3), round(y - 34), rgb, 0.75 * fade, 2)
    return width, height, pixels


def render(scene_path: Path, events_path: Path, frame: int, output: Path) -> None:
    try:
        scene = json.loads(scene_path.read_text(encoding="utf-8"))
        payload = json.loads(events_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise ValueError(f"invalid render input: {error}") from error
    width, height, pixels = frame_pixels(scene, payload["note_events"], frame)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(struct.pack(f">{len(pixels)}s", pixels.tobytes()))
    raw = output.read_bytes()
    output.write_bytes(f"P6\n{width} {height}\n255\n".encode() + raw)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scene", required=True, type=Path)
    parser.add_argument("--note-events", required=True, type=Path)
    parser.add_argument("--frame", type=int, default=0)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--frames", type=int, default=1)
    args = parser.parse_args()
    try:
        scene, events = resolve_path(str(args.scene)), resolve_path(str(args.note_events))
    except FileNotFoundError as error:
        parser.error(str(error))
    for offset in range(args.frames):
        output = args.output if offset == 0 else args.output.with_name(
            f"{args.output.stem}_{offset:02d}{args.output.suffix}")
        render(scene, events, args.frame + offset, output)
    print(f"rendered {args.frames} frame(s) from frame {args.frame}")


if __name__ == "__main__":
    main()
