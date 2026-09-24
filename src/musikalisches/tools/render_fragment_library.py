#!/usr/bin/env python3
"""Render the 176-unique-fragment video library for issue #83.

Each fragment (1..176) becomes an RGBA PNG sequence with the layered layout:

  head: 15 fully transparent frames            (neutral gate, issue #93)
  body: bg + spectra layer + staff layer + dice layer (opaque, 255 alpha)
  tail: 15 fully transparent frames            (neutral gate, issue #93)

Layout order follows the #83 plan: L1 spectra background (semi-transparent
Solarized ripples), L0 staff (center), L-1 ASCII dice foreground; L3 progress
is injected at combination level (compose time), not per fragment.

Inputs are the stage5 ``render-audio`` outputs under --data-dir, one ``rollN``
directory per selector value N in 2..12 produced with ``--rolls N*16
--loop-count 1``. Across the 11 runs every (position, roll) pair occurs once,
which covers all 176 unique fragment ids.

Output layout (canonical fragment storage, gate-checkable):

  <out>/fragment_001/frame_0000.png ... frame_NNNN.png
  ...
  <out>/fragment_176/frame_0000.png ... frame_NNNN.png
  <out>/library_manifest.json

Usage:
  render_fragment_library.py                                   # all 176
  render_fragment_library.py --only 42                          # single fragment
  render_fragment_library.py --data-dir DIR --output-dir DIR --workers 10
"""
from __future__ import annotations

import argparse
import json
import math
import os
import time
from array import array
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import render_dice_layer as dice_mod
import render_spectra_layer as spectra_mod
import render_staff_layer as staff_mod

ROOT = Path(__file__).resolve().parents[3]
DEFAULT_DATA_DIR = ROOT / "ops/out/issue83-data"
DEFAULT_SCENE = ROOT / "config/stage6_default_scene_profile.json"
DEFAULT_OUTPUT = ROOT / "ops/out/issue83-fragments"
EXPECTED_FRAGMENTS = 176
GATE_FRAMES = 15  # issue #93: head/tail frames with alpha == 0

# translate() table: 0 stays 0, anything else becomes 1 -> C-speed nonzero scan
_NONZERO = bytes(0 if byte == 0 else 1 for byte in range(256))

_G: dict = {}


def hex_rgb(value: str) -> tuple[int, int, int]:
    value = value.removeprefix("#")
    return int(value[0:2], 16), int(value[2:4], 16), int(value[4:6], 16)


# ------------------------------------------------------------------ inputs ---

def shift_seconds(window: dict, delta: float) -> dict:
    out = dict(window)
    for key in ("start_seconds", "end_seconds", "clock_seconds"):
        if key in out:
            out[key] = float(out[key]) - delta
    return out


def load_payloads(data_dir: Path) -> dict[int, dict]:
    """One payload per fragment id from the 11 roll runs."""
    payloads: dict[int, dict] = {}
    runs = sorted(data_dir.glob("roll*/realized_fragment_sequence.json"))
    if not runs:
        raise SystemExit(f"no roll*/realized_fragment_sequence.json under {data_dir}")
    for realized_path in runs:
        run_dir = realized_path.parent
        realized = json.loads(realized_path.read_text(encoding="utf-8"))
        notes_all = json.loads(
            (run_dir / "note_event_sequence.json").read_text(encoding="utf-8")
        )["note_events"]
        windows_all = json.loads(
            (run_dir / "analysis_window_sequence.json").read_text(encoding="utf-8")
        )["windows"]
        for frag in realized["fragments"]:
            fid = int(frag["fragment_id"])
            if fid in payloads:
                continue
            start = float(frag["start_seconds"])
            end = float(frag["end_seconds"])
            notes = [
                shift_seconds(note, start)
                for note in notes_all
                if int(note["fragment_id"]) == fid
            ]
            if not notes:
                raise SystemExit(f"fragment {fid}: no note events in {run_dir}")
            windows = [shift_seconds(window, start) for window in windows_all]
            payloads[fid] = {
                "notes": notes,
                "windows": windows,
                "duration_seconds": end - start,
                "roll": int(frag["selector_value"]),
                "position_index": int(frag["position_index"]),
                "position_label": frag["position_label"],
                "source_run": run_dir.name,
            }
    missing = sorted(set(range(1, EXPECTED_FRAGMENTS + 1)) - set(payloads))
    if missing:
        raise SystemExit(f"missing fragment ids in data: {missing}")
    if len(payloads) != EXPECTED_FRAGMENTS:
        raise SystemExit(f"expected {EXPECTED_FRAGMENTS} fragments, got {len(payloads)}")
    return payloads


# --------------------------------------------------------------- composite ---

def blend_spectra(dst: bytearray, rgba: array, n_pixels: int) -> None:
    """Src-over blend of the transparent spectra layer onto opaque dst RGB."""
    raw = rgba.tobytes()
    alpha = raw[3::4]
    mask = alpha.translate(_NONZERO)
    pos = -1
    while True:
        pos = mask.find(b"\x01", pos + 1)
        if pos < 0:
            break
        a = alpha[pos]
        src = pos * 4
        dst_i = pos * 3
        inv = 255 - a
        dst[dst_i] = (dst[dst_i] * inv + raw[src] * a) // 255
        dst[dst_i + 1] = (dst[dst_i + 1] * inv + raw[src + 1] * a) // 255
        dst[dst_i + 2] = (dst[dst_i + 2] * inv + raw[src + 2] * a) // 255


def overlay_keyed(dst: bytearray, src: bytes, width: int, height: int, bg: bytes) -> None:
    """Copy src pixels that differ from the flat background color over dst.

    staff/dice renderers paint an opaque background equal to the scene
    background; keying those exact pixels away keeps the layers underneath
    visible while every drawn pixel lands fully opaque.
    """
    bg_row = bg * width
    for y in range(height):
        row_start = y * width * 3
        if src[row_start : row_start + width * 3] == bg_row:
            continue
        for x in range(width):
            k = row_start + x * 3
            if src[k : k + 3] != bg:
                dst[k : k + 3] = src[k : k + 3]


def content_frame(scene: dict, payload: dict, local_frame: int, n_content: int) -> array:
    width = int(scene["canvas"]["width"])
    height = int(scene["canvas"]["height"])
    n_pixels = width * height
    bg = hex_rgb(scene["palette"]["background_color"])

    # L1 base: flat background + semi-transparent spectra ripples
    dst = bytearray(bytes(bg) * n_pixels)
    _, _, spectra_rgba = spectra_mod.frame_rgba(scene, payload["windows"], local_frame)
    blend_spectra(dst, spectra_rgba, n_pixels)

    # L0 staff layer
    _, _, staff_rgb = staff_mod.frame_pixels(scene, payload["notes"], local_frame)
    overlay_keyed(dst, bytes(staff_rgb), width, height, bytes(bg))

    # L-1 dice foreground: this fragment's fixed roll, position as cycle
    total_dissipate = 5
    df = min(int(local_frame * total_dissipate / max(n_content, 1)), total_dissipate - 1)
    _, _, dice_rgb = dice_mod.make_frame(
        scene,
        payload["roll"],
        int(payload.get("fragment_id") or 0),
        payload["position_index"] - 1,
        16,
        df,
        total_dissipate,
    )
    overlay_keyed(dst, bytes(dice_rgb), width, height, bytes(bg))

    rgba = array("B", bytes(n_pixels * 4))
    rgb_arr = array("B", dst)
    rgba[0::4] = rgb_arr[0::3]
    rgba[1::4] = rgb_arr[1::3]
    rgba[2::4] = rgb_arr[2::3]
    rgba[3::4] = array("B", b"\xff" * n_pixels)
    return rgba


# ------------------------------------------------------------------ render ---

def render_fragment(fid: int, payload: dict) -> dict:
    scene = _G["scene"]
    out_root = _G["out_root"]
    width = int(scene["canvas"]["width"])
    height = int(scene["canvas"]["height"])
    fps = float(scene["canvas"].get("fps", 30))
    n_pixels = width * height

    n_content = max(1, math.ceil(payload["duration_seconds"] * fps))
    payload = dict(payload, fragment_id=fid)
    frag_dir = out_root / f"fragment_{fid:03d}"
    frag_dir.mkdir(parents=True, exist_ok=True)

    transparent = array("B", bytes(n_pixels * 4))
    total = GATE_FRAMES + n_content + GATE_FRAMES
    for index in range(total):
        if index < GATE_FRAMES or index >= GATE_FRAMES + n_content:
            rgba = transparent
        else:
            rgba = content_frame(scene, payload, index - GATE_FRAMES, n_content)
        spectra_mod.write_png(frag_dir / f"frame_{index:04d}.png", width, height, rgba)

    return {
        "fragment_id": fid,
        "position_label": payload["position_label"],
        "position_index": payload["position_index"],
        "selector_value": payload["roll"],
        "duration_seconds": payload["duration_seconds"],
        "content_frames": n_content,
        "total_frames": total,
        "gate_frames": GATE_FRAMES,
        "source_run": payload["source_run"],
        "dir": str(frag_dir),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, default=DEFAULT_DATA_DIR)
    parser.add_argument("--scene", type=Path, default=DEFAULT_SCENE)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--workers", type=int, default=os.cpu_count() or 1)
    parser.add_argument("--only", type=int, action="append", default=None,
                        help="render only this fragment id (repeatable)")
    args = parser.parse_args()

    scene = json.loads(args.scene.read_text(encoding="utf-8"))
    payloads = load_payloads(args.data_dir)
    ids = sorted(args.only) if args.only else sorted(payloads)
    for fid in ids:
        if fid not in payloads:
            raise SystemExit(f"unknown fragment id: {fid}")

    args.output_dir.mkdir(parents=True, exist_ok=True)
    _G["scene"] = scene
    _G["out_root"] = args.output_dir

    started = time.time()
    entries = []
    if args.workers <= 1 or len(ids) == 1:
        for fid in ids:
            entries.append(render_fragment(fid, payloads[fid]))
            print(f"fragment_{fid:03d}: {entries[-1]['total_frames']} frames")
    else:
        with ProcessPoolExecutor(max_workers=args.workers) as pool:
            futures = [
                pool.submit(render_fragment, fid, payloads[fid]) for fid in ids
            ]
            for future in futures:
                entry = future.result()
                entries.append(entry)
        entries.sort(key=lambda item: item["fragment_id"])

    elapsed = time.time() - started
    manifest = {
        "issue": 83,
        "contract": (
            "176 unique fragments, each head/tail 15 frames fully transparent "
            "(issue #93 neutral gate); body = background + spectra + staff + dice "
            "layers at full opacity; L3 progress injected at combination level"
        ),
        "scene_profile": str(args.scene),
        "data_dir": str(args.data_dir),
        "canvas": scene["canvas"],
        "fragments_expected": EXPECTED_FRAGMENTS,
        "fragments_rendered": len(entries),
        "gate_frames": GATE_FRAMES,
        "render_seconds": round(elapsed, 1),
        "fragments": entries,
    }
    manifest_path = args.output_dir / "library_manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(
        f"rendered {len(entries)}/{EXPECTED_FRAGMENTS} fragments "
        f"({sum(e['total_frames'] for e in entries)} frames) in {elapsed:.1f}s "
        f"-> {args.output_dir}"
    )


if __name__ == "__main__":
    main()
