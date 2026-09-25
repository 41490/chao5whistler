#!/usr/bin/env python3
"""Issue #112 (83-R3): single-fragment spectrum ripple layer (RGBA, transparent bg).

One fragment in -> a 34-frame RGBA PNG sequence (1280x720). The time contract
(fps / content frames / gate frames / segment seconds) is imported from
fragment_timebase.py; nothing about the timeline is re-derived here.

Visual contract (CTO authorized, D5 + D1-revised):
  * one colour only: solarized cyan #2aa198 (reads on both #002b36 and #fdf6e3;
    the earlier near-background cyan was invisible on the dark ground, so no
    near-background tint is allowed any more).
  * constant alpha 0.70, never modulated by amplitude. Every inked pixel carries
    the *same* straight-alpha quad, so overlapping ripples are idempotent writes
    (source-over of an identical quad is a no-op) and the "inked pixel ==
    #2aa198 @ 0.70" assertion holds everywhere with no blending bookkeeping.
    Amplitude therefore shows up as geometry only.
  * background fully transparent; alpha comes only from ripple pixels.
  * phase is a pure function of ABSOLUTE time (fragment start + frame/fps),
    never of the frame index, so adjacent fragments of the same roll splice
    without a phase jump (asserted in --selftest).

Layout, mapping and shape are self-decided (mirrored into r3_manifest.json
"decisions"); the acceptance constraints (single colour, alpha band, absolute
phase) are honoured.
"""
from __future__ import annotations

import argparse
import bisect
import json
import math
import struct
import sys
import zlib
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fragment_timebase import (  # noqa: E402
    CONTENT_FRAMES,
    FPS,
    GATE_FRAMES,
    SEGMENT_SECONDS,
    TOTAL_FRAMES,
)

# ---- self-decided layout / palette (mirrored into r3_manifest "decisions") ----
CANVAS_W, CANVAS_H = 1280, 720
CX, CY = CANVAS_W // 2, CANVAS_H // 2        # ripples radiate from screen centre

INK = (0x2A, 0xA1, 0x98)                     # #2aa198 solarized cyan
INK_ALPHA = 0.70                             # constant, never amplitude-modulated
INK_A_BYTE = int(INK_ALPHA * 255)            # 178 -> 178/255 = 0.698, inside [0.68,0.72]
INK_QUAD = bytes((*INK, INK_A_BYTE))
_ROW_FILL = INK_QUAD * CANVAS_W              # spans are sliced out of it (memmove)

NUM_BANDS = 20                               # analysis bands -> concentric rings
RING_R_MIN = 44.0                            # px, band 0 (lowest) = innermost ring
RING_R_STEP = 34.0                           # px between successive ring radii
RING_SWELL_PX = 18.0                         # radial breathing amplitude
RING_TRAVEL_S = 2.0                          # s per ripple cycle (0.5 cycle / fragment)
RING_PHASE_STEP = 0.09                       # cycles of phase lead per band (outward travel)
RING_THICK_MAX = 7                           # px thickness at band energy 1.0
SPECTRAL_RATE = 1.7                          # 1/s, band-shape shimmer
CORE_R_MIN, CORE_R_MAX = 10.0, 44.0          # px, pulsing centre disc (focal point)
CORE_PERIOD_S = 1.0                          # s, one pulse per fragment
LEVEL_REF_PCTL = 0.95                        # per-roll loudness reference (95th pct env)
LEVEL_CURVE = 0.8                            # gamma on the normalised level

DEFAULT_DATA_ROOT = "/opt/logs/41490/out/issue83-data-90bpm"
DEFAULT_OUT_ROOT = "/opt/logs/41490/out/260924-issue83-r3"
SAMPLE_FRAGMENTS = (7, 68, 90)               # 7<-roll8, 68<-roll10, 90<-roll11

PHASE_FORMULA = (
    "ripple phase(t_abs, band) = 2*pi*(t_abs/{travel}s) - band*{step} cycles, with "
    "t_abs = fragment.start_seconds + content_frame/{fps} (ABSOLUTE roll time, never the "
    "0..23 frame index); level(t_abs) = linear interpolation of envelope_amplitude over "
    "window clock_seconds, divided by the roll {pct}th percentile of envelope_amplitude "
    "and raised to the power {curve}"
).format(travel=RING_TRAVEL_S, step=RING_PHASE_STEP, fps=FPS,
         pct=int(LEVEL_REF_PCTL * 100), curve=LEVEL_CURVE)


# --------------------------------------------------------------------------- -
# PNG write (pure python, straight RGBA) / read-back (filter 0 only)
# --------------------------------------------------------------------------- -
def write_png(path, width, height, rgba) -> None:
    def chunk(tag: bytes, data: bytes) -> bytes:
        crc = zlib.crc32(tag + data) & 0xFFFFFFFF
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", crc)

    rows = bytearray()
    row_bytes = width * 4
    for y in range(height):
        rows.append(0)
        start = y * row_bytes
        rows.extend(rgba[start:start + row_bytes])
    ihdr = struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)
    payload = (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr)
               + chunk(b"IDAT", zlib.compress(bytes(rows), 6)) + chunk(b"IEND", b""))
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)


def read_png(path) -> tuple[int, int, bytes]:
    """(width, height, raster RGBA bytes) — inverse of write_png (filter 0 rows)."""
    data = Path(path).read_bytes()
    if data[:8] != b"\x89PNG\r\n\x1a\n":
        raise ValueError(f"{path} is not a PNG")
    pos, idat, ihdr = 8, bytearray(), None
    while pos < len(data):
        (length,) = struct.unpack(">I", data[pos:pos + 4])
        tag = data[pos + 4:pos + 8]
        body = data[pos + 8:pos + 8 + length]
        if tag == b"IHDR":
            ihdr = struct.unpack(">IIBBBBB", body)
        elif tag == b"IDAT":
            idat += body
        pos += 12 + length
    width, height, depth, colour = ihdr[0], ihdr[1], ihdr[2], ihdr[3] if ihdr else (0, 0, 0, 0)
    if ihdr is None or (depth, colour) != (8, 6):
        raise ValueError(f"{path}: expected 8-bit RGBA IHDR, got {ihdr}")
    raw = zlib.decompress(bytes(idat))
    row_bytes = width * 4
    if len(raw) != height * (row_bytes + 1):
        raise ValueError(f"{path}: unexpected raster size {len(raw)}")
    raster = bytearray()
    for y in range(height):
        if raw[y * (row_bytes + 1)] != 0:
            raise ValueError(f"{path}: row {y} uses a non-zero PNG filter")
        raster += raw[y * (row_bytes + 1) + 1:(y + 1) * (row_bytes + 1)]
    return width, height, bytes(raster)


def png_size(path) -> tuple[int, int]:
    head = Path(path).read_bytes()[:33]
    if head[:8] != b"\x89PNG\r\n\x1a\n":
        raise ValueError(f"{path} is not a PNG")
    return struct.unpack(">II", head[16:24])


# --------------------------------------------------------------------------- -
# data: fragment -> roll -> analysis windows
# --------------------------------------------------------------------------- -
def find_roll(data_root, fid: int):
    for roll_dir in sorted(Path(data_root).glob("roll*")):
        rp = roll_dir / "realized_fragment_sequence.json"
        if not rp.exists():
            continue
        try:
            fragments = json.loads(rp.read_text(encoding="utf-8"))["fragments"]
        except (OSError, ValueError, KeyError) as error:
            raise SystemExit(f"unreadable {rp}: {error}") from error
        for frag in fragments:
            if frag["fragment_id"] == fid:
                return roll_dir, frag, fragments
    raise SystemExit(f"fragment {fid} not found under {data_root}")


def load_windows(roll_dir: Path) -> tuple[list[float], list[float], float]:
    """(clock_seconds, envelope_amplitude, reference level), sorted by clock."""
    data = json.loads((roll_dir / "analysis_window_sequence.json").read_text(encoding="utf-8"))
    windows = data.get("windows")
    if not isinstance(windows, list) or not windows:
        raise SystemExit(f"{roll_dir.name}: analysis_window_sequence.json missing windows[]")
    pairs = sorted((float(w["clock_seconds"]), float(w["envelope_amplitude"])) for w in windows)
    times = [p[0] for p in pairs]
    envs = [p[1] for p in pairs]
    ordered = sorted(envs)
    ref = ordered[min(len(ordered) - 1, int(LEVEL_REF_PCTL * len(ordered)))] or max(ordered) or 1.0
    return times, envs, ref


def level_at(times: list[float], envs: list[float], ref: float, t: float) -> float:
    """Loudness in 0..1 as a continuous function of ABSOLUTE time (linear interp)."""
    i = bisect.bisect_left(times, t)
    if i <= 0:
        value = envs[0]
    elif i >= len(times):
        value = envs[-1]
    else:
        span = times[i] - times[i - 1]
        frac = 0.0 if span <= 0 else (t - times[i - 1]) / span
        value = envs[i - 1] + (envs[i] - envs[i - 1]) * frac
    return min(1.0, (max(0.0, value) / ref) ** LEVEL_CURVE)


def band_energies(level: float, t: float) -> list[float]:
    """Per-band energies: a pure function of (level, absolute time) — no frame index."""
    energies = []
    for band in range(NUM_BANDS):
        phase = (band + 1) * 0.73 + t * SPECTRAL_RATE
        shape = 0.35 + 0.65 * abs(math.sin(phase))
        tilt = 1.0 - 0.35 * band / (NUM_BANDS - 1)       # low bands carry more energy
        energies.append(level * shape * tilt)
    return energies


# --------------------------------------------------------------------------- -
# raster: concentric ripples, hard-edged, one ink quad
# --------------------------------------------------------------------------- -
def _span(canvas: bytearray, y: int, xa: float, xb: float) -> None:
    x0 = max(0, int(math.ceil(xa)))
    x1 = min(CANVAS_W - 1, int(math.floor(xb)))
    if x1 < x0:
        return
    offset = (y * CANVAS_W + x0) * 4
    n = (x1 - x0 + 1) * 4
    canvas[offset:offset + n] = _ROW_FILL[:n]


def _disc(canvas: bytearray, radius: float) -> None:
    if radius <= 0:
        return
    for y in range(max(0, int(math.ceil(CY - radius))), min(CANVAS_H - 1, int(math.floor(CY + radius))) + 1):
        dy = y - CY
        reach = math.sqrt(max(0.0, radius * radius - dy * dy))
        _span(canvas, y, CX - reach, CX + reach)


def _ring(canvas: bytearray, radius: float, thickness: float) -> None:
    r_in = max(0.0, radius - thickness / 2.0)
    r_out = radius + thickness / 2.0
    for y in range(max(0, int(math.ceil(CY - r_out))), min(CANVAS_H - 1, int(math.floor(CY + r_out))) + 1):
        dy = y - CY
        outer = math.sqrt(max(0.0, r_out * r_out - dy * dy))
        inner = math.sqrt(max(0.0, r_in * r_in - dy * dy)) if r_in > 0 else 0.0
        _span(canvas, y, CX - outer, CX - inner)
        _span(canvas, y, CX + inner, CX + outer)


def render_frame(t_abs: float, level: float) -> bytearray:
    """One content frame: ripples as a pure function of absolute time."""
    canvas = bytearray(CANVAS_W * CANVAS_H * 4)           # fully transparent ground
    core = CORE_R_MIN + (CORE_R_MAX - CORE_R_MIN) * level * (
        0.5 + 0.5 * math.sin(2 * math.pi * t_abs / CORE_PERIOD_S))
    _disc(canvas, core)
    for band, energy in enumerate(band_energies(level, t_abs)):
        radius = RING_R_MIN + RING_R_STEP * band + RING_SWELL_PX * energy * math.sin(
            2 * math.pi * (t_abs / RING_TRAVEL_S) - band * RING_PHASE_STEP)
        _ring(canvas, radius, 1 + round(RING_THICK_MAX * energy))
    return canvas


def blank_frame() -> bytearray:
    return bytearray(CANVAS_W * CANVAS_H * 4)


# --------------------------------------------------------------------------- -
# rendering / measurement
# --------------------------------------------------------------------------- -
def ink_count(canvas) -> int:
    return len(canvas) // 4 - canvas[3::4].count(0)


def frame_diff(a, b) -> int:
    """Pixels whose ink state changed between two frames (ink is binary: 0 or 178)."""
    return sum(x != y for x, y in zip(a[3::4], b[3::4]))


def frame_at(t_abs: float, times, envs, ref: float) -> bytearray:
    return render_frame(t_abs, level_at(times, envs, ref, t_abs))


def measure(data_root, fid: int) -> dict:
    """Render a fragment's 34 frames in memory and measure them (no disk writes)."""
    roll_dir, frag, _ = find_roll(data_root, fid)
    times, envs, ref = load_windows(roll_dir)
    start = float(frag["start_seconds"])
    ink, diffs, previous = [], [], None
    for g in range(TOTAL_FRAMES):
        c = g - GATE_FRAMES
        canvas = blank_frame() if c < 0 or c >= CONTENT_FRAMES else frame_at(start + c / FPS, times, envs, ref)
        ink.append(ink_count(canvas))
        if 0 < c < CONTENT_FRAMES:
            diffs.append(frame_diff(previous, canvas))
        if 0 <= c < CONTENT_FRAMES:
            previous = canvas
    content_ink = ink[GATE_FRAMES:GATE_FRAMES + CONTENT_FRAMES]
    return dict(fid=fid, roll=roll_dir.name, position_index=frag.get("position_index"),
                start_seconds=start, end_seconds=float(frag["end_seconds"]), frames=TOTAL_FRAMES,
                ink=ink, content_ink_min=min(content_ink), content_ink_max=max(content_ink),
                content_ink_mean=round(sum(content_ink) / len(content_ink), 1),
                intra_max=max(diffs) if diffs else 0,
                intra_mean=round(sum(diffs) / len(diffs), 1) if diffs else 0.0,
                gate_ink=max(ink[:GATE_FRAMES] + ink[GATE_FRAMES + CONTENT_FRAMES:]),
                ref_level=round(ref, 6))


def render_fragment(data_root, fid: int, out_dir) -> dict:
    """Write the 34-frame PNG sequence to out_dir and return the measurements."""
    roll_dir, frag, _ = find_roll(data_root, fid)
    times, envs, ref = load_windows(roll_dir)
    start = float(frag["start_seconds"])
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    for old in out_dir.glob("frame_*.png"):
        old.unlink()
    ink = []
    for g in range(TOTAL_FRAMES):
        c = g - GATE_FRAMES
        canvas = blank_frame() if c < 0 or c >= CONTENT_FRAMES else frame_at(start + c / FPS, times, envs, ref)
        write_png(out_dir / f"frame_{g:04d}.png", CANVAS_W, CANVAS_H, canvas)
        ink.append(ink_count(canvas))
    stats = measure(data_root, fid)                        # same geometry, re-derived for the report
    stats["ink"] = ink
    return stats


def verify_on_disk(fid: int, out_dir, stats: dict, failures: list) -> dict:
    """Re-read every written PNG; prove frames/size/gate/colour/alpha on the bytes."""
    out_dir = Path(out_dir)
    files = sorted(out_dir.glob("frame_*.png"))
    if len(files) != TOTAL_FRAMES:
        failures.append(f"frag {fid}: {len(files)} frames != {TOTAL_FRAMES}")
    alpha_lo, alpha_hi = round(0.68 * 255), round(0.72 * 255)
    checked, ink_min, ink_max = 0, None, 0
    for index, path in enumerate(files):
        width, height, raster = read_png(path)
        if (width, height) != (CANVAS_W, CANVAS_H):
            failures.append(f"frag {fid}: {path.name} size {width}x{height}")
        alpha = raster[3::4]
        ink = len(alpha) - alpha.count(0)
        if index < GATE_FRAMES or index >= GATE_FRAMES + CONTENT_FRAMES:        # (b) gates
            if ink:
                failures.append(f"frag {fid}: gate {path.name} has {ink} inked pixels")
            continue
        if ink != stats["ink"][index]:                                          # disk round-trip
            failures.append(f"frag {fid}: {path.name} disk ink {ink} != rendered {stats['ink'][index]}")
        if raster.count(INK_QUAD) != ink:                                       # (c) colour
            failures.append(f"frag {fid}: {path.name} has pixels that are not #2aa198")
        if alpha.count(INK_A_BYTE) + alpha.count(0) != len(alpha):              # (c) alpha
            failures.append(f"frag {fid}: {path.name} has alpha bytes outside {{0,{INK_A_BYTE}}}")
        ink_min = ink if ink_min is None else min(ink_min, ink)
        ink_max = max(ink_max, ink)
        checked += 1
    if not checked or not ink_min:                                              # (e) non-empty
        failures.append(f"frag {fid}: no content frame carries ink")
    return dict(frames=len(files), content_frames_checked=checked,
                ink_colour="#%02x%02x%02x" % INK, alpha_byte=INK_A_BYTE,
                alpha_ratio=round(INK_A_BYTE / 255, 4),
                alpha_band=[round(alpha_lo / 255, 4), round(alpha_hi / 255, 4)],
                content_ink_min=ink_min or 0, content_ink_max=ink_max)


def continuity(data_root, fid: int, failures: list, cache: dict) -> list:
    """(d) splice check: same-roll neighbour boundary frames vs in-fragment motion."""
    roll_dir, frag, fragments = find_roll(data_root, fid)
    times, envs, ref = load_windows(roll_dir)
    start = float(frag["start_seconds"])
    last = frame_at(start + (CONTENT_FRAMES - 1) / FPS, times, envs, ref)
    first = frame_at(start, times, envs, ref)
    stats = cache.setdefault(fid, measure(data_root, fid))
    position = frag.get("position_index") or 0
    pairs = []
    for step in (-1, 1):                                        # previous / next neighbour
        neighbour = next((f for f in fragments if f.get("position_index") == position + step), None)
        if neighbour is None:
            continue
        nid = neighbour["fragment_id"]
        other_stats = cache.setdefault(nid, measure(data_root, nid))
        if step == 1:
            other = frame_at(float(neighbour["start_seconds"]), times, envs, ref)
            boundary = frame_diff(last, other)
            label = f"{fid}:content_{CONTENT_FRAMES - 1} -> {nid}:content_0"
        else:
            other = frame_at(float(neighbour["start_seconds"]) + (CONTENT_FRAMES - 1) / FPS, times, envs, ref)
            boundary = frame_diff(other, first)
            label = f"{nid}:content_{CONTENT_FRAMES - 1} -> {fid}:content_0"
        ceiling = max(stats["intra_max"], other_stats["intra_max"])
        pairs.append(dict(pair=label, neighbour_fid=nid, step=step,
                          boundary_time_gap_s=round(1 / FPS, 6),
                          boundary_diff_px=boundary, ceiling_intra_max_px=ceiling,
                          fragment_intra_max_px=stats["intra_max"],
                          neighbour_intra_max_px=other_stats["intra_max"],
                          fragment_intra_mean_px=stats["intra_mean"],
                          neighbour_intra_mean_px=other_stats["intra_mean"],
                          passed=boundary <= ceiling))
        if boundary > ceiling:
            failures.append(f"frag {fid}: boundary diff {boundary} > intra max {ceiling} ({label})")
    return pairs


# --------------------------------------------------------------------------- -
# self-test
# --------------------------------------------------------------------------- -
def selftest(data_root, out_root) -> int:
    out_root = Path(out_root)
    out_root.mkdir(parents=True, exist_ok=True)
    failures: list[str] = []
    samples, continuity_report, cache = {}, [], {}

    for fid in SAMPLE_FRAGMENTS:
        stats = render_fragment(data_root, fid, out_root / f"fragment_{fid}")
        disk = verify_on_disk(fid, out_root / f"fragment_{fid}", stats, failures)
        samples[str(fid)] = {k: v for k, v in stats.items() if k != "ink"}
        samples[str(fid)].update(disk)
        continuity_report.extend(continuity(data_root, fid, failures, cache))
        print(f"[{'PASS' if not failures else '....'}] fragment {fid}: {stats['frames']} frames, roll {stats['roll']}, "
              f"content ink {disk['content_ink_min']}..{disk['content_ink_max']} px, gate ink {stats['gate_ink']}")

    for fid in SAMPLE_FRAGMENTS:                                            # (a)(c)(e)
        sample = samples[str(fid)]
        print(f"[{'PASS' if sample['frames'] == TOTAL_FRAMES else 'FAIL'}] fragment {fid}: "
              f"{sample['frames']} frames at {CANVAS_W}x{CANVAS_H} RGBA, ink {sample['ink_colour']} @ "
              f"alpha {sample['alpha_ratio']} (band {sample['alpha_band']}), every content frame inked "
              f"(min {sample['content_ink_min']} px)")
    for pair in continuity_report:                                          # (d)
        print(f"[{'PASS' if pair['passed'] else 'FAIL'}] phase continuity {pair['pair']}: boundary diff "
              f"{pair['boundary_diff_px']} px <= intra max {pair['ceiling_intra_max_px']} px "
              f"(frag mean {pair['fragment_intra_mean_px']} px, neighbour mean {pair['neighbour_intra_mean_px']} px)")

    manifest = {
        "issue": 112, "lane": "83-R3",
        "timebase": dict(fps=FPS, content_frames=CONTENT_FRAMES, gate_frames=GATE_FRAMES,
                         total_frames=TOTAL_FRAMES, segment_seconds=SEGMENT_SECONDS,
                         source="fragment_timebase.py (imported, never re-derived)"),
        "canvas": dict(width=CANVAS_W, height=CANVAS_H, format="RGBA PNG (straight, non-premultiplied)",
                       background="transparent"),
        "ink": dict(colour="#%02x%02x%02x" % INK, alpha=INK_ALPHA, alpha_byte=INK_A_BYTE,
                    alpha_ratio=INK_A_BYTE / 255, constant=True),
        "phase_formula": PHASE_FORMULA,
        "decisions": {
            "shape": (f"concentric ripples (同心波): {NUM_BANDS} analysis bands -> {NUM_BANDS} hard-edged rings "
                      f"radiating from the canvas centre ({CX},{CY}), base radii {RING_R_MIN:.0f}.."
                      f"{RING_R_MIN + RING_R_STEP * (NUM_BANDS - 1):.0f} px in {RING_R_STEP:.0f} px steps, plus a "
                      f"pulsing centre disc ({CORE_R_MIN:.0f}->{CORE_R_MAX:.0f} px). Rings are filled per scanline "
                      "as radial spans (memmove, no per-pixel python loop) and are hard-edged: no anti-aliasing, "
                      "so every inked pixel is exactly one quad and the colour/alpha assertion stays exact."),
            "frequency_to_geometry": (f"band index (low->high) maps to ring radius, inner->outer: "
                                      f"r_band = {RING_R_MIN:.0f} + {RING_R_STEP:.0f}*band, with a spectral tilt "
                                      "1-0.35*band/(N-1) so the low (inner) rings stay energetic, as in the "
                                      "source mix."),
            "amplitude_to_geometry": (f"loudness drives geometry only, never colour or alpha: ring thickness = "
                                      f"1+round({RING_THICK_MAX}*energy) px, radial swell = "
                                      f"{RING_SWELL_PX:.0f}*energy*sin(phase) px, centre disc radius scales with "
                                      f"level. level = (envelope / roll {int(LEVEL_REF_PCTL * 100)}th percentile)"
                                      f"^{LEVEL_CURVE}, linearly interpolated over window clock_seconds."),
            "phase": (f"ripple phase is a pure function of ABSOLUTE roll time: phase_band(t) = "
                      f"2*pi*(t/{RING_TRAVEL_S}s) - band*{RING_PHASE_STEP}, t = fragment.start_seconds + "
                      f"content_frame/{FPS}. One ripple cycle per {RING_TRAVEL_S}s and {RING_PHASE_STEP} cycles "
                      "of lead per band, so the wave travels outward and adjacent fragments of a roll continue "
                      "the same wave (asserted in --selftest)."),
            "colour": ("single solarized cyan #2aa198 at a constant alpha 0.70 for every inked pixel. All ink is "
                       "the same straight-alpha quad, so overlapping ripples are idempotent writes and no pixel "
                       "can leave the [0.68,0.72] alpha band. Reads on both the dark #002b36 and the light "
                       "#fdf6e3 ground; no near-background tint (the earlier dark-ground cyan was invisible)."),
            "gates": (f"head and tail {GATE_FRAMES} frames are blank canvases (max alpha 0); all "
                      f"{CONTENT_FRAMES} content frames carry ink."),
        },
        "samples": samples,
        "phase_continuity": continuity_report,
        "assertions": {
            "a_frames": f"{TOTAL_FRAMES} frames per fragment at {CANVAS_W}x{CANVAS_H} RGBA",
            "b_gates": f"head/tail {GATE_FRAMES} frames max_alpha == 0",
            "c_colour": f"inked pixels == #2aa198, alpha byte {INK_A_BYTE} ({INK_A_BYTE / 255:.3f}) in [0.68,0.72]",
            "d_phase": "boundary frame diff <= max in-fragment frame diff (per same-roll neighbour pair)",
            "e_nonempty": "every content frame has ink > 0",
        },
    }
    (out_root / "r3_manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")

    if failures:
        for message in failures:
            print(f"       FAIL {message}")
        print(f"[FAIL] spectra-layer self-check: {len(failures)} failure(s)")
        return 1
    print(f"[PASS] spectra-layer self-check (a-e) — manifest: {out_root / 'r3_manifest.json'}")
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-root", default=DEFAULT_DATA_ROOT)
    parser.add_argument("--fragment", type=int)
    parser.add_argument("--out-dir")
    parser.add_argument("--out-root", default=DEFAULT_OUT_ROOT)
    parser.add_argument("--selftest", action="store_true")
    args = parser.parse_args(argv)

    if args.selftest:
        return selftest(args.data_root, args.out_root)
    if args.fragment is None or not args.out_dir:
        parser.error("--fragment and --out-dir are required (or pass --selftest)")

    stats = render_fragment(args.data_root, args.fragment, args.out_dir)
    print(f"rendered fragment {args.fragment} (roll {stats['roll']}, position {stats['position_index']}) "
          f"{stats['start_seconds']}s-{stats['end_seconds']}s -> {stats['frames']} frames in {args.out_dir} "
          f"(ink #2aa198 @ {INK_ALPHA}, content ink {stats['content_ink_min']}..{stats['content_ink_max']} px, "
          f"phase 2*pi*(t_abs/{RING_TRAVEL_S}s) - band*{RING_PHASE_STEP})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
