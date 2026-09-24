#!/usr/bin/env python3
"""Render an ASCII dice animation layer as binary PPM frames.

Each dice throw (roll) maps to a fragment via the 2-dice → sum mapping.
The number encoding dissipates as | - _ / \ characters drifting left
toward the staff, with a bottom progress counter incrementing each cycle.
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]

# Two dice sums 2-12 map to fragment indices 0-15 (14 rolls + 2 wraps = 16 measures)
ROLL_TO_FRAGMENT = {2: 0, 3: 1, 4: 2, 5: 3, 6: 4, 7: 5, 8: 6, 9: 7, 10: 8, 11: 9, 12: 10}

# ASCII encoding for numbers 2-12 (5-frame dissipation sequence)
DICE_ASCII = {
    2:  ["2 . . . .", ". 2 . . .", ". . 2 . .", ". . . 2 .", ". . . . 2"],
    3:  ["3 3 . . .", ". 3 3 . .", ". . 3 3 .", ". . . 3 3", "3 . . . 3"],
    4:  ["4 4 4 . .", ". 4 4 4 .", ". . 4 4 4", "4 . . . 4", "4 4 4 4 4"],
    5:  ["5 5 5 5 .", ". 5 5 5 5", "5 . . . 5", "5 5 5 5 .", ". 5 5 5 5"],
    6:  ["6 6 6 6 .", ". 6 6 6 6", "6 . . . 6", "6 6 6 6 .", ". 6 6 6 6"],
    7:  ["7 7 . . .", ". 7 7 . .", ". . 7 7 .", ". . . 7 7", "7 . . . 7"],
    8:  ["8 8 8 . .", ". 8 8 8 .", ". . 8 8 8", ". 8 8 8 .", "8 8 8 . ."],
    9:  ["9 9 9 9 .", ". 9 9 9 9", "9 . . . 9", "9 9 9 9 .", ". 9 9 9 9"],
    10: ["1 0 . . .", ". 1 0 . .", ". . 1 0 .", ". . . 1 0", "1 0 . . ."],
    11: ["1 1 . . .", ". 1 1 . .", ". . 1 1 .", ". . . 1 1", "1 . . . 1"],
    12: ["1 2 . . .", ". 1 2 . .", ". . 1 2 .", ". . . 1 2", "1 2 . . ."],
}

DRIFT_CHARS = ["|", "-", "_", "/", "\\"]


def resolve_path(value: str) -> Path:
    path = Path(value)
    if path.is_absolute():
        return path
    for base in (Path.cwd(), ROOT):
        candidate = base / path
        if candidate.exists():
            return candidate
    raise FileNotFoundError(f"input path not found: {value}")


def load_scene(path: Path) -> dict:
    with path.open() as f:
        return json.load(f)


def load_note_events(path: Path) -> dict:
    with path.open() as f:
        return json.load(f)


def color(value: str) -> tuple[int, int, int]:
    value = value.removeprefix("#")
    return (int(value[0:2], 16), int(value[2:4], 16), int(value[4:6], 16))


def blend(pixels: bytearray, width: int, x: int, y: int,
          rgb: tuple[int, int, int], alpha: float) -> None:
    if not (0 <= x < width and 0 <= y):
        return
    try:
        i = (y * width + x) * 3
        r = int(pixels[i] * (1 - alpha) + rgb[0] * alpha)
        g = int(pixels[i + 1] * (1 - alpha) + rgb[1] * alpha)
        b = int(pixels[i + 2] * (1 - alpha) + rgb[2] * alpha)
        pixels[i] = min(255, max(0, r))
        pixels[i + 1] = min(255, max(0, g))
        pixels[i + 2] = min(255, max(0, b))
    except IndexError as error:
        raise ValueError("invalid raster pixel operation") from error


def draw_char(pixels: bytearray, width: int, height: int,
              cx: float, cy: float, ch: str, size: int,
              rgb: tuple[int, int, int], alpha: float) -> None:
    """Draw a single ASCII character as a block pixel."""
    offsets = {
        "|":  (0, 0), "-":  (0, 0), "_":  (0, 1),
        "/":  (0, 0), "\\": (0, 0), " ": (-1, -1),
    }
    ox, oy = offsets.get(ch, (0, 0))
    if ch == " ":
        return
    half = size // 2
    for dy in range(-half, half + 1):
        for dx in range(-half, half + 1):
            x = int(cx + dx)
            y = int(cy + dy + oy * half)
            if 0 <= x < width and 0 <= y < height:
                blend(pixels, width, x, y, rgb, alpha)


def draw_text_line(pixels: bytearray, width: int, height: int,
                   text: str, x: int, y: int, size: int,
                   rgb: tuple[int, int, int], alpha: float) -> None:
    """Draw a text line character by character."""
    for i, ch in enumerate(text):
        draw_char(pixels, width, height, x + i * size, y, ch, size, rgb, alpha)


def make_frame(scene: dict, roll: int, fragment_id: int,
               cycle: int, total_cycles: int, dissipate_frame: int,
               total_dissipate: int = 5) -> tuple[int, int, bytearray]:
    """Render one PPM frame for a dice throw."""
    width = scene["canvas"]["width"]
    height = scene["canvas"]["height"]
    pixels = bytearray(width * height * 3)

    bg = color(scene["palette"]["background_color"])
    for i in range(0, len(pixels), 3):
        pixels[i] = bg[0]
        pixels[i + 1] = bg[1]
        pixels[i + 2] = bg[2]

    accent = scene["palette"]["accent_sequence"]
    rgb = color(scene["palette"]["colors"].get(accent[cycle % len(accent)], "#93a1a1"))

    # Staff lines (reference — centered vertically)
    staff_y = int(height * 0.45)
    for offset in (-2, -1, 0, 1, 2):
        y = staff_y + offset * 8
        for x in range(width):
            blend(pixels, width, x, y, rgb, 0.15)

    # Dice number dissipating: draw | - _ / \ characters drifting left
    char_alpha = 1.0 - (dissipate_frame / total_dissipate) * 0.6
    start_x = int(width * 0.75)
    for fi in range(total_dissipate):
        cx = start_x - fi * 20
        cy = staff_y + 40 + fi * 12
        ch = DRIFT_CHARS[fi % len(DRIFT_CHARS)]
        draw_char(pixels, width, height, cx, cy, ch, 14, rgb, char_alpha * (1 - fi / total_dissipate))

    # Dice number in center
    num_text = str(roll)
    num_x = width // 2 - 20
    num_y = staff_y - 60
    draw_text_line(pixels, width, height, num_text, num_x, num_y, 36, rgb, 0.9)

    # Fragment label
    frag_text = f"frag:{fragment_id}"
    draw_text_line(pixels, width, height, frag_text, width // 2 - 40, num_y + 40, 14, rgb, 0.6)

    # Bottom progress: cycle + 1
    progress = cycle + 1
    prog_text = f"progress: {progress}/{total_cycles}"
    prog_rgb = color(scene["palette"]["colors"].get("yellow", "#b58900"))
    draw_text_line(pixels, width, height, prog_text, 40, height - 40, 18, prog_rgb, 0.9)

    # Cycle indicator
    cycle_text = f"cycle: {cycle}"
    draw_text_line(pixels, width, height, cycle_text, width - 200, height - 40, 14, rgb, 0.6)

    return width, height, pixels


def compute_durations(note_events_data: dict) -> list[float]:
    """Compute per-roll durations from note events."""
    total_seconds = note_events_data.get("total_duration_seconds", 12.0)
    rolls = note_events_data.get("rolls", [])
    if not rolls:
        return [total_seconds / 14.0] * 14
    # Distribute total duration proportionally by roll count
    per_roll = total_seconds / len(rolls)
    return [per_roll] * len(rolls)


def render(scene: dict, note_events: dict, output_dir: Path,
           cycles: int = 14, dissipate_frames: int = 5) -> list[Path]:
    """Render dice animation frames."""
    output_dir.mkdir(parents=True, exist_ok=True)
    durations = compute_durations(note_events)
    rolls = note_events.get("rolls", [])
    fragment_count = note_events.get("summary", {}).get("fragment_count", 16)

    paths: list[Path] = []
    frame_idx = 0
    for cycle in range(min(cycles, len(rolls))):
        roll = rolls[cycle] if cycle < len(rolls) else 7
        fragment_id = ROLL_TO_FRAGMENT.get(roll, cycle % fragment_count)
        duration = durations[cycle] if cycle < len(durations) else 0.5
        frames_in_roll = max(1, int(duration * scene["canvas"]["fps"]))

        for df in range(dissipate_frames):
            w, h, raw = make_frame(scene, roll, fragment_id, cycle, cycles, df, dissipate_frames)
            header = f"P6\n{w} {h}\n255\n".encode()
            out_path = output_dir / f"dice_{frame_idx:06d}.ppm"
            out_path.write_bytes(header + raw)
            paths.append(out_path)
            frame_idx += 1

    return paths


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scene", required=True, help="Path to scene profile JSON")
    parser.add_argument("--note-events", required=True, help="Path to note_event_sequence.json")
    parser.add_argument("--output-dir", required=True, help="Output directory for PPM frames")
    parser.add_argument("--cycles", type=int, default=14, help="Number of dice cycles")
    parser.add_argument("--dissipate-frames", type=int, default=5, help="Dissipation frames per roll")
    args = parser.parse_args()

    scene_path = resolve_path(args.scene)
    events_path = resolve_path(args.note_events)
    output_dir = Path(args.output_dir)

    scene = load_scene(scene_path)
    note_events = load_note_events(events_path)

    paths = render(scene, note_events, output_dir, args.cycles, args.dissipate_frames)
    print(f"rendered {len(paths)} dice frame(s) to {output_dir}")


if __name__ == "__main__":
    main()