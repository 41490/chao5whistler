#!/usr/bin/env python3
"""Render full-canvas semi-transparent Solarized mono spectrum ripples from analysis windows."""
from __future__ import annotations

import argparse
import json
import math
import struct
import zlib
from array import array
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
NUM_BANDS = 20
ALPHA_MIN = 0.15
ALPHA_MAX = 0.25

SOLARIZED = {
    "solarized_dark": ("#002b36", "#073642"),
    "solarized_light": ("#839496", "#93a1a1"),
}


def resolve_path(value: str) -> Path:
    path = Path(value)
    candidates = (
        path,
        ROOT / path,
        ROOT / "src/musikalisches/runtime" / path,
        ROOT / "src/musikalisches/runtime/config" / path.name,
    )
    for candidate in candidates:
        if candidate.exists():
            return candidate
    raise FileNotFoundError(f"input path not found: {value}")


def hex_rgb(value: str) -> tuple[int, int, int]:
    value = value.removeprefix("#")
    return int(value[0:2], 16), int(value[2:4], 16), int(value[4:6], 16)


def mix(a: tuple[int, int, int], b: tuple[int, int, int], t: float) -> tuple[int, int, int]:
    t = max(0.0, min(1.0, t))
    return tuple(int(a[i] + (b[i] - a[i]) * t) for i in range(3))


def band_energies(window: dict, window_index: int) -> list[float]:
    env = float(window.get("envelope_amplitude", 0.0))
    rms = float(window.get("rms_amplitude", 0.0))
    peak = float(window.get("peak_amplitude", 0.0))
    base = max(env, rms * 0.85, peak * 0.35, 0.02)
    energies: list[float] = []
    for band in range(NUM_BANDS):
        phase = (band + 1) * 0.73 + window_index * 0.17
        shape = 0.35 + 0.65 * abs(math.sin(phase))
        tilt = 1.0 - abs(band - NUM_BANDS / 2) / (NUM_BANDS / 2) * 0.35
        energies.append(base * shape * tilt)
    peak_energy = max(energies) or 1.0
    return [min(1.0, value / peak_energy) for value in energies]


def window_at_clock(windows: list[dict], clock: float) -> tuple[dict, int]:
    best_index = 0
    best_delta = math.inf
    for index, window in enumerate(windows):
        delta = abs(float(window["clock_seconds"]) - clock)
        if delta < best_delta:
            best_delta = delta
            best_index = index
    return windows[best_index], best_index


def palette_pair(scene: dict) -> tuple[tuple[int, int, int], tuple[int, int, int]]:
    palette_id = scene.get("palette", {}).get("palette_id", "solarized_dark")
    if palette_id == "solarized_light":
        low, high = SOLARIZED["solarized_light"]
    else:
        low = scene.get("palette", {}).get("background_color", SOLARIZED["solarized_dark"][0])
        high = scene.get("palette", {}).get("panel_color", SOLARIZED["solarized_dark"][1])
    return hex_rgb(low), hex_rgb(high)


def frame_rgba(scene: dict, windows: list[dict], frame: int) -> tuple[int, int, array]:
    width = int(scene["canvas"]["width"])
    height = int(scene["canvas"]["height"])
    fps = float(scene["canvas"].get("fps", 30))
    clock = frame / fps
    window, window_index = window_at_clock(windows, clock)
    energies = band_energies(window, window_index)
    low_rgb, high_rgb = palette_pair(scene)
    band_height = height / NUM_BANDS
    pixels = array("B", [0] * (width * height * 4))

    def plot(x: int, y: int, rgb: tuple[int, int, int], alpha: float) -> None:
        if not (0 <= x < width and 0 <= y < height):
            return
        index = (y * width + x) * 4
        alpha_byte = int(max(0.0, min(1.0, alpha)) * 255)
        if alpha_byte == 0:
            return
        existing = pixels[index + 3]
        if alpha_byte <= existing:
            return
        pixels[index : index + 3] = array("B", rgb)
        pixels[index + 3] = alpha_byte

    for band, energy in enumerate(energies):
        rgb = mix(low_rgb, high_rgb, band / max(NUM_BANDS - 1, 1))
        alpha = ALPHA_MIN + (ALPHA_MAX - ALPHA_MIN) * energy
        center_y = (band + 0.5) * band_height
        wave_px = 6.0 + energy * 18.0
        for x in range(width):
            t = x / max(width - 1, 1)
            local = energies[(band + int(t * 3)) % NUM_BANDS]
            y = center_y + math.sin(t * math.pi * 4 + band * 0.4 + clock * 3.5) * wave_px * local
            y_int = int(round(y))
            plot(x, y_int, rgb, alpha)
            if wave_px > 8:
                plot(x, y_int + 1, rgb, max(ALPHA_MIN, alpha * 0.85))

    return width, height, pixels


def write_png(path: Path, width: int, height: int, rgba: array) -> None:
    def chunk(tag: bytes, data: bytes) -> bytes:
        crc = zlib.crc32(tag + data) & 0xFFFFFFFF
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", crc)

    rows = bytearray()
    row_bytes = width * 4
    for y in range(height):
        rows.append(0)
        start = y * row_bytes
        rows.extend(rgba[start : start + row_bytes].tobytes())
    compressed = zlib.compress(bytes(rows), 9)
    ihdr = struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)
    payload = b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr) + chunk(b"IDAT", compressed) + chunk(b"IEND", b"")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)


def render_sequence(scene_path: Path, analysis_path: Path, output_dir: Path, frames: int, start_frame: int) -> None:
    scene = json.loads(scene_path.read_text(encoding="utf-8"))
    analysis = json.loads(analysis_path.read_text(encoding="utf-8"))
    windows = analysis.get("windows")
    if not isinstance(windows, list) or not windows:
        raise ValueError("analysis_window_sequence.json missing non-empty windows[]")
    output_dir.mkdir(parents=True, exist_ok=True)
    for offset in range(frames):
        frame = start_frame + offset
        width, height, rgba = frame_rgba(scene, windows, frame)
        out = output_dir / f"spectra_{frame:03d}.png"
        write_png(out, width, height, rgba)
    print(f"rendered {frames} transparent spectrum frame(s) to {output_dir}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scene", required=True, type=Path)
    parser.add_argument("--analysis", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--frames", type=int, default=90)
    parser.add_argument("--start-frame", type=int, default=0)
    args = parser.parse_args()
    try:
        scene = resolve_path(str(args.scene))
        analysis = resolve_path(str(args.analysis))
    except FileNotFoundError as error:
        parser.error(str(error))
    render_sequence(scene, analysis, args.output_dir, args.frames, args.start_frame)


if __name__ == "__main__":
    main()
