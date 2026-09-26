#!/usr/bin/env python3
"""Issue #113 (83-R4): single-fragment dice layer (RGBA, transparent bg).

One fragment in -> a 34-frame RGBA PNG sequence (1280x720). The time contract
(fps / content frames / gate frames / segment seconds) is imported from
fragment_timebase.py; nothing about the timeline is re-derived here.

Visual contract (CTO authorized, D6):
  * ASCII digit style (the historic look); no SVG dice pips.
  * the 24 content frames are TWO segments inside the single content window:
    a rolling segment (digits flip fast, one new digit per frame) followed by a
    lock segment that holds the settled number so the viewer can read it. The
    last content frame (0-based content frame 23) is already the locked number.
  * anchored bottom-LEFT, clear of the stage-6 footer progress band.
  * background fully transparent; the frame carries nothing but the digits.
  * the number shown comes from ``realized_fragment_sequence.json``'s
    ``selector_value`` (the dice roll that selected this fragment) — never
    hardcoded, never derived from the fragment id.

The old design (number dissipating into | - _ / \ characters that drifted
toward the staff, cross-coupled with the notation layer) is gone: this renderer
owns nothing but the digit body, and no other layer is referenced.

Layout, palette and the roll/lock split are self-decided (mirrored into
r4_manifest.json "decisions"); the acceptance constraints (single fragment in,
34 frames, gates, two-segment content, selector-driven number, anchor) are
honoured.
"""
from __future__ import annotations

import argparse
import hashlib
import json
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

# ---- self-decided layout / palette (mirrored into r4_manifest "decisions") ----
CANVAS_W, CANVAS_H = 1280, 720

INK = (0xB5, 0x89, 0x00)                     # #b58900 solarized yellow: dice/game accent
INK_ALPHA = 0.85                             # constant, never modulated
INK_A_BYTE = 216                             # int(0.85 * 255) = 216.75 -> 216; 216/255 = 0.847
INK_QUAD = bytes((*INK, INK_A_BYTE))
_ROW_FILL = INK_QUAD * CANVAS_W              # spans are sliced out of it (memmove)

# 5x7 bitmap font, classic terminal look. Key == the character it draws.
GLYPHS = {
    "0": ("01110", "10001", "10011", "10101", "11001", "10001", "01110"),
    "1": ("00100", "01100", "00100", "00100", "00100", "00100", "01110"),
    "2": ("01110", "10001", "00001", "00010", "00100", "01000", "11111"),
    "3": ("11111", "00010", "00100", "00010", "00001", "10001", "01110"),
    "4": ("00010", "00110", "01010", "10010", "11111", "00010", "00010"),
    "5": ("11111", "10000", "11110", "00001", "00001", "10001", "01110"),
    "6": ("00110", "01000", "10000", "11110", "10001", "10001", "01110"),
    "7": ("11111", "00001", "00010", "00100", "01000", "01000", "01000"),
    "8": ("01110", "10001", "10001", "01110", "10001", "10001", "01110"),
    "9": ("01110", "10001", "10001", "01111", "00001", "00010", "01100"),
}
GLYPH_W, GLYPH_H = 5, 7
GLYPH_PITCH = GLYPH_W + 1                    # one blank column between digits
GLYPH_SCALE = 10                             # px per font pixel

# bottom-left anchor: top-left corner of the first glyph cell.
ANCHOR_X, ANCHOR_Y = 40, 560
# stage6_default_scene_profile.json footer_progress_area: x/y/w/h = 438/648/405/40
FOOTER_X, FOOTER_Y, FOOTER_W, FOOTER_H = 438, 648, 405, 40
FOOTER_Y_LO, FOOTER_Y_HI = FOOTER_Y, FOOTER_Y + FOOTER_H

# two-segment split of the 24 content frames (self-decided, mirrored to manifest)
ROLL_FRAMES = 16                             # digits flip, one new digit per frame
LOCK_FRAMES = CONTENT_FRAMES - ROLL_FRAMES   # 8 frames holding the settled number
assert ROLL_FRAMES + LOCK_FRAMES == CONTENT_FRAMES

DICE_MIN, DICE_MAX = 2, 12                   # two-dice sums, the roll domain
ROLL_STEP = 7                                # coprime with the domain size -> every frame flips

DEFAULT_DATA_ROOT = "/opt/logs/41490/out/issue83-data-90bpm"
DEFAULT_OUT_ROOT = "/opt/logs/41490/out/260924-issue83-r4"
SAMPLE_FRAGMENTS = (7, 68, 90)               # 7<-roll8, 68<-roll10, 90<-roll11 (resolved dynamically)


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
    if ihdr is None or (ihdr[2], ihdr[3]) != (8, 6):
        raise ValueError(f"{path}: expected 8-bit RGBA IHDR, got {ihdr}")
    width, height = ihdr[0], ihdr[1]
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


# --------------------------------------------------------------------------- -
# raster: ASCII digits, hard-edged, one ink quad
# --------------------------------------------------------------------------- -
def _span(canvas: bytearray, y: int, xa: int, xb: int) -> None:
    x0 = max(0, xa)
    x1 = min(CANVAS_W - 1, xb)
    if x1 < x0:
        return
    offset = (y * CANVAS_W + x0) * 4
    n = (x1 - x0 + 1) * 4
    canvas[offset:offset + n] = _ROW_FILL[:n]


def rasterize_text(text: str) -> bytearray:
    """A fresh transparent canvas carrying only ``text`` at the anchor.

    Independent entry point: the self-test re-derives the expected number
    through this function (glyph table + anchor) instead of trusting whatever
    the frame loop happened to draw.
    """
    canvas = bytearray(CANVAS_W * CANVAS_H * 4)
    for index, ch in enumerate(text):
        rows = GLYPHS.get(ch)
        if rows is None:
            raise ValueError(f"no glyph for {ch!r}")
        cell_x = ANCHOR_X + index * GLYPH_PITCH * GLYPH_SCALE
        for gy, bits in enumerate(rows):
            y = ANCHOR_Y + gy * GLYPH_SCALE
            if not (0 <= y < CANVAS_H):
                continue
            for gx, bit in enumerate(bits):
                if bit == "1":
                    _span(canvas, y, cell_x + gx * GLYPH_SCALE,
                          cell_x + (gx + 1) * GLYPH_SCALE - 1)
    return canvas


def blank_frame() -> bytearray:
    return bytearray(CANVAS_W * CANVAS_H * 4)


def rolling_digits(fid: int, selector: int) -> list[int]:
    """The ROLL_FRAMES digits flipped through before the number locks.

    Deterministic in (fragment id, selector). The roll walks a fixed cycle over
    the two-dice sum domain with the settled value removed, so the number never
    shows up mid-roll — the lock is a genuine reveal — and no two adjacent
    frames can repeat.
    """
    span = DICE_MAX - DICE_MIN + 1
    cycle = [DICE_MIN + (c * ROLL_STEP + fid) % span for c in range(span)]
    digits = [d for d in cycle if d != selector]
    if not digits:
        raise SystemExit(f"fragment {fid}: roll domain {DICE_MIN}..{DICE_MAX} has no value but {selector}")
    return [digits[c % len(digits)] for c in range(ROLL_FRAMES)]


def digit_at(fid: int, selector: int, content_frame: int) -> int:
    """Which number content frame ``content_frame`` shows (roll then lock)."""
    if content_frame < ROLL_FRAMES:
        return rolling_digits(fid, selector)[content_frame]
    return selector


# --------------------------------------------------------------------------- -
# measurement (works on an in-memory canvas or a re-read disk raster)
# --------------------------------------------------------------------------- -
def max_alpha(raster) -> int:
    return max(raster[3::4])


def ink_count(raster) -> int:
    return len(raster) // 4 - raster[3::4].count(0)


def ink_bbox(raster):
    """(x0, y0, x1, y1) of the inked pixels, or None when the frame is blank."""
    stride = CANVAS_W * 4
    x0, y0, x1, y1 = CANVAS_W, CANVAS_H, -1, -1
    for y in range(CANVAS_H):
        row = raster[y * stride:(y + 1) * stride]
        first = row.find(INK_QUAD)
        if first < 0:
            continue
        if y0 == CANVAS_H:
            y0 = y
        y1 = y
        x0 = min(x0, first // 4)
        x1 = max(x1, row.rfind(INK_QUAD) // 4)
    return None if y1 < y0 else (x0, y0, x1, y1)


def ink_region(raster, bbox) -> bytes:
    """The raster cropped to the ink bbox — the "inked area" the hashes run over."""
    x0, y0, x1, y1 = bbox
    stride = CANVAS_W * 4
    lo, hi = x0 * 4, (x1 + 1) * 4
    return b"".join(raster[y * stride + lo:y * stride + hi] for y in range(y0, y1 + 1))


def ink_digest(raster, bbox) -> str:
    return hashlib.sha256(ink_region(raster, bbox)).hexdigest()


# --------------------------------------------------------------------------- -
# data: fragment -> roll -> selector_value
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


def _selector(frag: dict, fid: int) -> int:
    """selector_value of a fragment record, or a hard failure (no silent default)."""
    try:
        return int(frag["selector_value"])
    except (KeyError, TypeError, ValueError) as error:
        raise SystemExit(f"fragment {fid}: unusable selector_value: {error}") from error


def _seconds(frag: dict, key: str, fid: int) -> float:
    try:
        return float(frag[key])
    except (KeyError, TypeError, ValueError) as error:
        raise SystemExit(f"fragment {fid}: unusable {key}: {error}") from error


def selector_of(data_root, fid: int) -> int:
    """The dice roll that selected this fragment, read from the data — never derived."""
    _, frag, _ = find_roll(data_root, fid)
    return _selector(frag, fid)


def frame_for(content_frame: int, fid: int, selector: int) -> bytearray:
    if content_frame < 0 or content_frame >= CONTENT_FRAMES:
        return blank_frame()
    return rasterize_text(str(digit_at(fid, selector, content_frame)))


# --------------------------------------------------------------------------- -
# rendering
# --------------------------------------------------------------------------- -
def render_fragment(data_root, fid: int, out_dir) -> dict:
    """Write the 34-frame PNG sequence + final.png to out_dir; return measurements."""
    roll_dir, frag, _ = find_roll(data_root, fid)
    selector = _selector(frag, fid)
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    for old in out_dir.glob("frame_*.png"):
        old.unlink()
    for g in range(TOTAL_FRAMES):
        canvas = frame_for(g - GATE_FRAMES, fid, selector)
        write_png(out_dir / f"frame_{g:04d}.png", CANVAS_W, CANVAS_H, canvas)
    final = frame_for(CONTENT_FRAMES - 1, fid, selector)
    write_png(out_dir / "final.png", CANVAS_W, CANVAS_H, final)
    return measure(data_root, fid)


def measure(data_root, fid: int) -> dict:
    """Render a fragment's 34 frames in memory and measure them (no disk writes)."""
    roll_dir, frag, _ = find_roll(data_root, fid)
    selector = _selector(frag, fid)
    start = _seconds(frag, "start_seconds", fid)
    digits, digests, bboxes, ink = [], [], [], []
    for g in range(TOTAL_FRAMES):
        c = g - GATE_FRAMES
        canvas = frame_for(c, fid, selector)
        ink.append(ink_count(canvas))
        bbox = ink_bbox(canvas)
        bboxes.append(list(bbox) if bbox else None)
        digests.append(ink_digest(canvas, bbox) if bbox else None)
        if 0 <= c < CONTENT_FRAMES:
            digits.append(digit_at(fid, selector, c))
    return dict(fid=fid, roll=roll_dir.name, position_index=frag.get("position_index"),
                selector_value=selector, start_seconds=start,
                end_seconds=_seconds(frag, "end_seconds", fid), frames=TOTAL_FRAMES,
                digits=digits, digests=digests, bboxes=bboxes, ink=ink,
                gate_ink=max(ink[:GATE_FRAMES] + ink[GATE_FRAMES + CONTENT_FRAMES:]),
                content_ink_min=min(ink[GATE_FRAMES:GATE_FRAMES + CONTENT_FRAMES]),
                content_ink_max=max(ink[GATE_FRAMES:GATE_FRAMES + CONTENT_FRAMES]))


# --------------------------------------------------------------------------- -
# self-test
# --------------------------------------------------------------------------- -
def verify_on_disk(fid: int, out_dir, stats: dict, failures: list) -> dict:
    """Re-read every written PNG; prove frames/size/gate/ink on the bytes."""
    out_dir = Path(out_dir)
    files = sorted(out_dir.glob("frame_*.png"))
    if len(files) != TOTAL_FRAMES:
        failures.append(f"frag {fid}: {len(files)} frames != {TOTAL_FRAMES}")
    checked, gate_blank, bbox = 0, 0, None
    for index, path in enumerate(files):
        width, height, raster = read_png(path)
        if (width, height) != (CANVAS_W, CANVAS_H):
            failures.append(f"frag {fid}: {path.name} size {width}x{height}")
        peak = max_alpha(raster)
        if index < GATE_FRAMES or index >= GATE_FRAMES + CONTENT_FRAMES:        # (b) gates
            if peak:
                failures.append(f"frag {fid}: gate {path.name} max_alpha {peak} != 0")
            else:
                gate_blank += 1
            continue
        if ink_count(raster) != stats["ink"][index]:                            # disk round-trip
            failures.append(f"frag {fid}: {path.name} disk ink {ink_count(raster)} != rendered {stats['ink'][index]}")
        if raster.count(INK_QUAD) != ink_count(raster):                         # single ink quad
            failures.append(f"frag {fid}: {path.name} has pixels that are not #b58900 @ {INK_A_BYTE}")
        if peak != INK_A_BYTE:                                                  # constant alpha
            failures.append(f"frag {fid}: {path.name} max_alpha {peak} != {INK_A_BYTE}")
        if index == GATE_FRAMES + CONTENT_FRAMES - 1:                           # (e) anchor
            bbox = ink_bbox(raster)
        checked += 1
    if not checked:
        failures.append(f"frag {fid}: no content frame found")
    return dict(frames=len(files), content_frames_checked=checked, gates_blank=gate_blank,
                final_bbox=bbox, ink_colour="#%02x%02x%02x" % INK, alpha_byte=INK_A_BYTE,
                alpha_ratio=round(INK_A_BYTE / 255, 4))


def independent_digit_check(out_dir, fid: int, selector: int, failures: list) -> dict:
    """(c) Prove the settled number from the pixels, not from the render state.

    ``rasterize_text`` is called fresh from the glyph table for every candidate
    1..12, and each candidate bitmap is compared pixel-by-pixel with the last
    content frame read back from disk. Exactly one candidate may match, and it
    must be the fragment's ``selector_value``.
    """
    path = Path(out_dir) / f"frame_{GATE_FRAMES + CONTENT_FRAMES - 1:04d}.png"
    width, height, raster = read_png(path)
    if (width, height) != (CANVAS_W, CANVAS_H):
        failures.append(f"frag {fid}: final frame size {width}x{height}")
    bbox = ink_bbox(raster)
    if bbox is None:
        failures.append(f"frag {fid}: final content frame carries no ink")
        return dict(method="glyph-table re-render + pixel diff", candidates=[],
                    selector_value=selector, unique_match=None, passed=False)
    target = ink_region(raster, bbox)
    candidates = []
    for value in range(DICE_MIN, DICE_MAX + 1):
        expected = rasterize_text(str(value))
        exp_bbox = ink_bbox(expected)
        diff = None
        if exp_bbox == bbox:                       # same footprint -> comparable masks
            diff = sum(a != b for a, b in zip(ink_region(expected, exp_bbox), target))
        candidates.append(dict(value=value, bbox=list(exp_bbox) if exp_bbox else None,
                               pixel_diff=diff, matches=diff == 0))
    matches = [c["value"] for c in candidates if c["matches"]]
    passed = matches == [selector]
    if not passed:
        failures.append(f"frag {fid}: independent digit check matched {matches}, expected [{selector}]")
    return dict(method=("last content frame re-read from disk; for every candidate "
                        f"{DICE_MIN}..{DICE_MAX} the glyph table is re-rasterised through "
                        "rasterize_text() and compared pixel-by-pixel with the frame's ink "
                        "region; exactly one zero-diff candidate must equal selector_value"),
                selector_value=selector, candidates=candidates, unique_match=matches,
                matched_value=matches[0] if matches else None, passed=passed)


def segment_hash_checks(stats: dict, failures: list) -> dict:
    """(d) rolling segment flips every frame; lock segment is byte-identical."""
    digests = stats["digests"][GATE_FRAMES:GATE_FRAMES + CONTENT_FRAMES]
    roll_pairs = [(i, digests[i] != digests[i + 1]) for i in range(ROLL_FRAMES - 1)]
    lock_pairs = [(i + ROLL_FRAMES, digests[i + ROLL_FRAMES] == digests[i + ROLL_FRAMES + 1])
                  for i in range(LOCK_FRAMES - 1)]
    boundary_flips = digests[ROLL_FRAMES - 1] != digests[ROLL_FRAMES]
    early = [i for i, d in enumerate(stats["digits"][:ROLL_FRAMES]) if d == stats["selector_value"]]
    for i in early:
        failures.append(f"frag {stats['fid']}: rolling frame {i} already shows the settled number")
    for index, flipped in roll_pairs:
        if not flipped:
            failures.append(f"frag {stats['fid']}: rolling frames {index}->{index + 1} did not change")
    for index, same in lock_pairs:
        if not same:
            failures.append(f"frag {stats['fid']}: lock frames {index}->{index + 1} changed")
    if not boundary_flips:
        failures.append(f"frag {stats['fid']}: roll->lock boundary did not change")
    pairs_ok = all(ok for _, ok in roll_pairs + lock_pairs)
    return dict(rolling_frames=ROLL_FRAMES, lock_frames=LOCK_FRAMES,
                rolling_pairs_checked=len(roll_pairs),
                rolling_pairs_flipped=sum(1 for _, ok in roll_pairs if ok),
                lock_pairs_checked=len(lock_pairs),
                lock_pairs_identical=sum(1 for _, ok in lock_pairs if ok),
                boundary_flipped=boundary_flips,
                settled_number_hidden_while_rolling=not early,
                passed=pairs_ok and boundary_flips and not early)


def anchor_check(bbox, failures: list, fid: int) -> dict:
    """(e) every inked pixel sits in the declared bottom-left box, clear of the footer."""
    if bbox is None:
        failures.append(f"frag {fid}: no ink bbox to anchor-check")
        return dict(passed=False)
    x0, y0, x1, y1 = bbox
    declared = dict(x=[ANCHOR_X, ANCHOR_X + (GLYPH_PITCH * 2 - 1) * GLYPH_SCALE - 1],
                    y=[ANCHOR_Y, ANCHOR_Y + GLYPH_H * GLYPH_SCALE - 1])
    inside = (declared["x"][0] <= x0 and x1 <= declared["x"][1]
              and declared["y"][0] <= y0 and y1 <= declared["y"][1])
    lower_left = x1 < CANVAS_W // 2 and y0 > CANVAS_H // 2
    clear = y1 < FOOTER_Y_LO and not (x1 >= FOOTER_X and x0 < FOOTER_X + FOOTER_W)
    passed = inside and lower_left and clear
    if not inside:
        failures.append(f"frag {fid}: ink bbox {bbox} outside declared {declared}")
    if not lower_left:
        failures.append(f"frag {fid}: ink bbox {bbox} is not in the lower-left quadrant")
    if not clear:
        failures.append(f"frag {fid}: ink bbox {bbox} overlaps the footer band y[{FOOTER_Y_LO},{FOOTER_Y_HI})")
    return dict(measured_bbox=list(bbox), declared_box=declared,
                lower_left_quadrant=lower_left, footer_clearance_px=FOOTER_Y_LO - y1,
                footer_band=dict(x=FOOTER_X, y=FOOTER_Y, width=FOOTER_W, height=FOOTER_H,
                                 y_range=[FOOTER_Y_LO, FOOTER_Y_HI],
                                 source="config/stage6_default_scene_profile.json"),
                passed=passed)


def selftest(data_root, out_root) -> int:
    out_root = Path(out_root)
    out_root.mkdir(parents=True, exist_ok=True)
    failures: list[str] = []
    samples, digit_checks, hash_checks, anchors = {}, {}, {}, {}

    for fid in SAMPLE_FRAGMENTS:
        stats = render_fragment(data_root, fid, out_root / f"fragment_{fid}")
        disk = verify_on_disk(fid, out_root / f"fragment_{fid}", stats, failures)
        digit = independent_digit_check(out_root / f"fragment_{fid}", fid, stats["selector_value"], failures)
        hashes = segment_hash_checks(stats, failures)
        anchor = anchor_check(disk["final_bbox"], failures, fid)
        samples[str(fid)] = {k: v for k, v in stats.items() if k not in ("digests", "bboxes", "ink")}
        samples[str(fid)].update(disk)
        digit_checks[str(fid)], hash_checks[str(fid)], anchors[str(fid)] = digit, hashes, anchor
        print(f"[{'PASS' if not failures else '....'}] fragment {fid}: {stats['frames']} frames, roll {stats['roll']}, "
              f"selector {stats['selector_value']}, content ink {stats['content_ink_min']}..{stats['content_ink_max']} px, "
              f"gate ink {stats['gate_ink']}")

    for fid in SAMPLE_FRAGMENTS:                                            # (a)(b)
        s = samples[str(fid)]
        print(f"[{'PASS' if s['frames'] == TOTAL_FRAMES and s['gates_blank'] == 2 * GATE_FRAMES else 'FAIL'}] "
              f"fragment {fid}: {s['frames']} frames at {CANVAS_W}x{CANVAS_H} RGBA, "
              f"{s['gates_blank']}/{2 * GATE_FRAMES} gate frames max_alpha == 0, "
              f"ink #b58900 @ alpha {s['alpha_ratio']} ({s['content_frames_checked']} content frames checked)")
    for fid in SAMPLE_FRAGMENTS:                                            # (c)
        d = digit_checks[str(fid)]
        print(f"[{'PASS' if d['passed'] else 'FAIL'}] fragment {fid}: last content frame reads "
              f"{d['matched_value']} (independent glyph re-render, unique zero-diff match) == "
              f"selector_value {d['selector_value']}")
    for fid in SAMPLE_FRAGMENTS:                                            # (d)
        h = hash_checks[str(fid)]
        print(f"[{'PASS' if h['passed'] else 'FAIL'}] fragment {fid}: rolling {h['rolling_pairs_flipped']}/"
              f"{h['rolling_pairs_checked']} adjacent pairs changed, lock {h['lock_pairs_identical']}/"
              f"{h['lock_pairs_checked']} identical, roll->lock boundary flipped {h['boundary_flipped']}, "
              f"settled number hidden while rolling {h['settled_number_hidden_while_rolling']}")
    for fid in SAMPLE_FRAGMENTS:                                            # (e)
        a = anchors[str(fid)]
        print(f"[{'PASS' if a['passed'] else 'FAIL'}] fragment {fid}: ink bbox {a['measured_bbox']} inside "
              f"declared box, lower-left {a['lower_left_quadrant']}, footer clearance "
              f"{a['footer_clearance_px']} px above y={FOOTER_Y_LO}")

    manifest = {
        "issue": 113, "lane": "83-R4",
        "timebase": dict(fps=FPS, content_frames=CONTENT_FRAMES, gate_frames=GATE_FRAMES,
                         total_frames=TOTAL_FRAMES, segment_seconds=SEGMENT_SECONDS,
                         source="fragment_timebase.py (imported, never re-derived)"),
        "canvas": dict(width=CANVAS_W, height=CANVAS_H, format="RGBA PNG (straight, non-premultiplied)",
                       background="transparent"),
        "ink": dict(colour="#%02x%02x%02x" % INK, alpha=INK_ALPHA, alpha_byte=INK_A_BYTE,
                    alpha_ratio=INK_A_BYTE / 255, constant=True),
        "decisions": {
            "style": ("ASCII digit style kept from the historic renderer (D6): the number is drawn with a "
                      f"5x7 bitmap terminal font scaled x{GLYPH_SCALE}, one ink quad, hard-edged, no "
                      "anti-aliasing. No SVG dice pips, no dice-face artwork."),
            "two_segment_split": (f"the {CONTENT_FRAMES} content frames split into a rolling segment of "
                                  f"{ROLL_FRAMES} frames (content 0..{ROLL_FRAMES - 1}) and a lock segment of "
                                  f"{LOCK_FRAMES} frames (content {ROLL_FRAMES}..{CONTENT_FRAMES - 1}). "
                                  "Rolling flips to a new digit every single frame (24 fps = 41.7 ms per "
                                  "digit, reads as a tumbling die); the lock then holds the settled number "
                                  f"for {LOCK_FRAMES} frames = {LOCK_FRAMES / FPS:.3f} s so it is comfortably "
                                  "readable, and content frame 23 (the last one) is already the settled "
                                  "number. The split leans toward rolling because the eye needs far less "
                                  "time to read two glyphs than to accept them as moving."),
            "rolling_sequence": (f"digit(c) = the c-th entry of the fixed cycle "
                                 f"[{DICE_MIN} + (k*{ROLL_STEP} + fragment_id) mod "
                                 f"{DICE_MAX - DICE_MIN + 1} for k] with selector_value removed, so the "
                                 "settled number never appears mid-roll and no two adjacent frames repeat "
                                 f"(the cycle has {DICE_MAX - DICE_MIN} distinct values, longer than the "
                                 f"{ROLL_FRAMES}-frame roll, so it never even wraps)."),
            "number_source": ("realized_fragment_sequence.json's selector_value — the dice roll that "
                              "selected the fragment. Read from the data at render time; never derived "
                              "from the fragment id and never hardcoded."),
            "anchor": (f"bottom-left anchor at (x={ANCHOR_X}, y={ANCHOR_Y}) = the top-left corner of the "
                       f"first glyph cell. A two-digit number occupies "
                       f"{(GLYPH_PITCH * 2 - 1) * GLYPH_SCALE}x{GLYPH_H * GLYPH_SCALE} px, so the whole body "
                       f"stays inside x[{ANCHOR_X},{(GLYPH_PITCH * 2 - 1) * GLYPH_SCALE + ANCHOR_X}] "
                       f"y[{ANCHOR_Y},{ANCHOR_Y + GLYPH_H * GLYPH_SCALE}] — lower-left quadrant, clear of "
                       "the centre staves and of the playhead."),
            "footer_avoidance": (f"stage6 footer progress band from config/stage6_default_scene_profile.json "
                                 f"footer_progress_area: x={FOOTER_X} y={FOOTER_Y} "
                                 f"w={FOOTER_W} h={FOOTER_H} -> occupied y range "
                                 f"[{FOOTER_Y_LO},{FOOTER_Y_HI}). The anchor was moved up from the "
                                 f"suggested y=H-120={CANVAS_H - 120} to y={ANCHOR_Y} so the glyph body "
                                 f"(bottom {ANCHOR_Y + GLYPH_H * GLYPH_SCALE}) keeps "
                                 f"{FOOTER_Y_LO - (ANCHOR_Y + GLYPH_H * GLYPH_SCALE)} px of clearance above "
                                 "the band; the avoidance interval is asserted per fragment."),
            "removed_design": ("the old 'number dissipates into | - _ / \\ characters drifting toward the "
                               "staff' cross-layer coupling is deleted. This renderer draws nothing but the "
                               "digit body and references no other layer."),
            "gates": (f"head and tail {GATE_FRAMES} frames are blank canvases (max alpha 0); all "
                      f"{CONTENT_FRAMES} content frames carry ink."),
        },
        "samples": samples,
        "digit_checks": digit_checks,
        "segment_hashes": hash_checks,
        "anchors": anchors,
        "assertions": {
            "a_frames": f"{TOTAL_FRAMES} frames per fragment at {CANVAS_W}x{CANVAS_H} RGBA",
            "b_gates": f"head/tail {GATE_FRAMES} frames max_alpha == 0 ({2 * GATE_FRAMES} per fragment)",
            "c_number": ("last content frame re-read from disk and compared pixel-by-pixel against a fresh "
                         f"rasterize_text() of every candidate {DICE_MIN}..{DICE_MAX} from the glyph table; "
                         "exactly one zero-diff candidate, equal to selector_value"),
            "d_segments": (f"rolling segment: {ROLL_FRAMES - 1} adjacent pairs all differ (sha256 of the ink "
                           f"region); lock segment: {LOCK_FRAMES - 1} adjacent pairs all identical; the "
                           "roll->lock boundary pair differs"),
            "e_anchor": (f"all ink inside the declared box and above the footer band y>={FOOTER_Y_LO}; "
                         "bbox in the lower-left quadrant (x < 640, y > 360)"),
        },
    }
    (out_root / "r4_manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")

    if failures:
        for message in failures:
            print(f"       FAIL {message}")
        print(f"[FAIL] dice-layer self-check: {len(failures)} failure(s)")
        return 1
    print(f"[PASS] dice-layer self-check (a-e) — manifest: {out_root / 'r4_manifest.json'}")
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
    print(f"rendered fragment {args.fragment} (roll {stats['roll']}, position {stats['position_index']}, "
          f"selector {stats['selector_value']}) {stats['start_seconds']}s-{stats['end_seconds']}s -> "
          f"{stats['frames']} frames + final.png in {args.out_dir} "
          f"(roll {ROLL_FRAMES} / lock {LOCK_FRAMES}, ink #b58900 @ {INK_ALPHA}, anchor ({ANCHOR_X},{ANCHOR_Y}))")
    return 0


if __name__ == "__main__":
    sys.exit(main())
