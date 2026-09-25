#!/usr/bin/env python3
"""Issue #111 (83-R2): grand-staff five-line notation layer from R1 SVG sprites.

Single-fragment input -> a 34-frame RGBA PNG sequence (1280x720, transparent
background), plus an E2 ablation collage and a run manifest. Musical glyphs are
blitted from the R1 Wikimedia sprite PNGs (never drawn with python geometry);
staff rules / ledger lines are the only straight lines drawn directly (there is
no staff-line sprite). The time contract is imported from fragment_timebase.py.

D4 reading form (CTO authorized, standard reading order):
  * the playhead is pinned to screen centre; the score scrolls right-to-left.
  * the note currently sounding sits centred + highlighted (solarized cyan);
  * played notes drift left and fade; future notes queue to the right in
    standard reading order.
  * the last content frame (playback complete, 0-based content frame 23) drops
    the whole staff to alpha 0; head/tail gates stay fully transparent.

Layout, palette and scaling are self-decided (see r2_manifest.json "decisions").
"""
from __future__ import annotations

import argparse
import ctypes
import json
import math
import struct
import sys
import zlib
from array import array
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fragment_timebase import (  # noqa: E402
    CONTENT_FRAMES,
    FPS,
    GATE_FRAMES,
    ONSET_GRID_SECONDS,
    QUANTIZATION_TOLERANCE,
    SEGMENT_SECONDS,
    TOTAL_FRAMES,
    onset_quantization_error,
    onset_to_frame,
)

# ---- self-decided layout / palette (mirrored into r2_manifest "decisions") ----
CANVAS_W, CANVAS_H = 1280, 720
GAP = 16                                   # staff line spacing; one diatonic step = GAP/2 px
TREBLE_TOP = CANVAS_H // 2 - 5 * GAP       # 280 : top line F5 of Kb. U. (treble)
BASS_TOP = TREBLE_TOP + 6 * GAP            # 376 : top line A3 of Kb. L. (bass)
                                            # shared middle-C ledger line sits at TREBLE_TOP+5*GAP=360
CLEF_X = 48                                # clefs anchored near the left margin
CENTER_X = CANVAS_W // 2                   # 640 : pinned playhead / current-note x
MIDC_LEDGER_Y = TREBLE_TOP + 5 * GAP       # 360 : shared middle-C ledger line between the two staves
NOTE_X_LO, NOTE_X_HI = 130, 1200         # note-body region: clefs x<=105, barline x>=1256
PPS = 540.0                                # px per second of onset delta (1/6 s onset -> 90 px)
FADE_TAU = 0.25                            # s ; past-note alpha decay constant
PAST_PEAK = 0.8                            # past-note alpha at the instant it releases

LINE_T, LINE_A = 2, 0.70                   # staff rule thickness / alpha
NOTEHEAD_W, NOTEHEAD_H = 20, 16            # blitted notehead footprint
STEM_W, STEM_LEN = 3, round(GAP * 3.2)     # stem rectangle footprint
ACC_H = round(GAP * 2.2)                   # accidental footprint height (width follows aspect)

SOL = {
    "line":    (0x93, 0xA1, 0xA1),         # base1 : mid grey rules, reads on light & dark
    "future":  (0x83, 0x94, 0x96),         # base0 : queued notes
    "past":    (0x58, 0x6E, 0x75),         # base01: recedes as it fades
    "current": (0x2A, 0xA1, 0x98),         # cyan  : highlight, mid-bright on both grounds
    "bg":      (0x07, 0x36, 0x42),         # base02: collage panel ground only
}
LINE, FUTURE, PAST, CURRENT = SOL["line"], SOL["future"], SOL["past"], SOL["current"]

LETTER_STEPS = {"C": 0, "D": 1, "E": 2, "F": 3, "G": 4, "A": 5, "B": 6}
ACC_SPRITE = {"#": "sharp", "b": "flat", "n": "natural"}

DEFAULT_DATA_ROOT = "/opt/logs/41490/out/issue83-data-90bpm"
DEFAULT_SPRITES = "/opt/logs/41490/out/260924-issue83-r1/sprites"
DEFAULT_OUT_ROOT = "/opt/logs/41490/out/260924-issue83-r2"
SAMPLE_FRAGMENTS = (7, 68, 90)             # 7<-roll8, 68<-roll10, 90<-roll11 (resolved dynamically)
COLLAGE_TILE_CF = CONTENT_FRAMES // 2      # keyframe content frame (t = 12/24 = 0.5 s)


# --------------------------------------------------------------------------- -
# PNG read (cairo, no PIL in this lane) — mirrors build_glyph_sprites.py read-back
# --------------------------------------------------------------------------- -
_CAIRO = None


def _cairo():
    global _CAIRO
    if _CAIRO is None:
        c = ctypes.CDLL("libcairo.so.2")
        c.cairo_image_surface_create_from_png.restype = ctypes.c_void_p
        c.cairo_image_surface_create_from_png.argtypes = [ctypes.c_char_p]
        c.cairo_surface_flush.argtypes = [ctypes.c_void_p]
        c.cairo_image_surface_get_width.restype = ctypes.c_int
        c.cairo_image_surface_get_width.argtypes = [ctypes.c_void_p]
        c.cairo_image_surface_get_height.restype = ctypes.c_int
        c.cairo_image_surface_get_height.argtypes = [ctypes.c_void_p]
        c.cairo_image_surface_get_stride.restype = ctypes.c_int
        c.cairo_image_surface_get_stride.argtypes = [ctypes.c_void_p]
        c.cairo_image_surface_get_data.restype = ctypes.POINTER(ctypes.c_ubyte)
        c.cairo_image_surface_get_data.argtypes = [ctypes.c_void_p]
        c.cairo_surface_destroy.argtypes = [ctypes.c_void_p]
        _CAIRO = c
    return _CAIRO


def read_png_alpha(path):
    """(width, height, alpha_bytes) for a PNG via cairo (ARGB32 premult; A at +3)."""
    c = _cairo()
    surf = c.cairo_image_surface_create_from_png(str(path).encode())
    if not surf:
        raise RuntimeError(f"cairo could not read {path}")
    try:
        c.cairo_surface_flush(surf)
        w = c.cairo_image_surface_get_width(surf)
        h = c.cairo_image_surface_get_height(surf)
        stride = c.cairo_image_surface_get_stride(surf)
        data = c.cairo_image_surface_get_data(surf)
        alpha = bytearray(w * h)
        for y in range(h):
            row, base = y * stride, y * w
            for x in range(w):
                alpha[base + x] = data[row + x * 4 + 3]
        return w, h, bytes(alpha)
    finally:
        c.cairo_surface_destroy(surf)


def png_size(path):
    head = Path(path).read_bytes()[:33]
    if head[:8] != b"\x89PNG\r\n\x1a\n":
        raise ValueError(f"{path} is not a PNG")
    return struct.unpack(">II", head[16:24])


def max_alpha(path):
    _, _, alpha = read_png_alpha(path)
    return max(alpha) if alpha else 0


# --------------------------------------------------------------------------- -
# sprite loading + scaled blit
# --------------------------------------------------------------------------- -
class Sprites:
    """Loads R1 sprite alpha masks and nearest-neighbour resamples them."""

    def __init__(self, root):
        self.root = Path(root)
        self._masks = {}
        self._scaled = {}

    def mask(self, name):
        if name not in self._masks:
            path = self.root / f"{name}.png"
            if not path.exists():
                raise SystemExit(f"missing sprite: {path}")
            self._masks[name] = read_png_alpha(path)
        return self._masks[name]

    def scaled(self, name, tw, th):
        tw, th = max(1, tw), max(1, th)
        key = (name, tw, th)
        cached = self._scaled.get(key)
        if cached is not None:
            return cached
        w, h, alpha = self.mask(name)
        out = bytearray(tw * th)
        for j in range(th):
            srow = (j * h // th) * w
            orow = j * tw
            for i in range(tw):
                out[orow + i] = alpha[srow + i * w // tw]
        res = (tw, th, bytes(out))
        self._scaled[key] = res
        return res


# --------------------------------------------------------------------------- -
# canvas raster ops (straight-alpha source-over)
# --------------------------------------------------------------------------- -
def blank_canvas():
    return array("B", bytes(CANVAS_W * CANVAS_H * 4))


def _to_byte(value):
    """Clamp a finite 0..255 float to a byte. Callers pass validated floats only."""
    if value < 0.0:
        return 0
    if value > 255.0:
        return 255
    return round(value)


def _over(canvas, di, tint, sa):
    if sa <= 0.0:
        return
    da = canvas[di + 3] / 255.0
    oa = sa + da * (1.0 - sa)
    if oa <= 0.0:
        return
    inv = 1.0 / oa
    keep = da * (1.0 - sa)
    canvas[di] = _to_byte((tint[0] * sa + canvas[di] * keep) * inv)
    canvas[di + 1] = _to_byte((tint[1] * sa + canvas[di + 1] * keep) * inv)
    canvas[di + 2] = _to_byte((tint[2] * sa + canvas[di + 2] * keep) * inv)
    canvas[di + 3] = _to_byte(oa * 255.0)


def fill_rect(canvas, x0, y0, w, h, tint, alpha):
    for y in range(y0, y0 + h):
        if y < 0 or y >= CANVAS_H:
            continue
        row = y * CANVAS_W
        for x in range(x0, x0 + w):
            if 0 <= x < CANVAS_W:
                _over(canvas, (row + x) * 4, tint, alpha)


def blit(canvas, sprites, name, dx, dy, dw, dh, tint, alpha):
    w, h, a = sprites.scaled(name, dw, dh)
    for j in range(h):
        y = dy + j
        if y < 0 or y >= CANVAS_H:
            continue
        row, arow = y * CANVAS_W, j * w
        for i in range(w):
            m = a[arow + i]
            if not m:
                continue
            x = dx + i
            if 0 <= x < CANVAS_W:
                _over(canvas, (row + x) * 4, tint, (m / 255.0) * alpha)


def draw_staff(canvas, sprites):
    for top in (TREBLE_TOP, BASS_TOP):
        for k in range(5):
            fill_rect(canvas, 0, top + k * GAP, CANVAS_W, LINE_T, LINE, LINE_A)
        fill_rect(canvas, CANVAS_W - 24, top, 2, 4 * GAP, LINE, LINE_A)  # terminal barline
    tsw, tsh, _ = sprites.mask("treble_clef")
    tch = 7 * GAP
    tcw = round(tch * tsw / tsh)
    blit(canvas, sprites, "treble_clef", CLEF_X, round(TREBLE_TOP + 3 * GAP - tch / 2), tcw, tch, LINE, 0.9)
    bsw, bsh, _ = sprites.mask("bass_clef")
    bch = round(2.5 * GAP)
    bcw = round(bch * bsw / bsh)
    blit(canvas, sprites, "bass_clef", CLEF_X, round(BASS_TOP + GAP - bch / 2), bcw, bch, LINE, 0.9)


def draw_note(canvas, sprites, note, x, tint, alpha):
    y = round(note["y"])
    top = TREBLE_TOP if note["upper"] else BASS_TOP
    bottom = top + 4 * GAP
    half = GAP / 2  # one diatonic step; ledger lines land on even steps from a staff line
    ledger_w = round(NOTEHEAD_W * 1.7)
    if y < top:
        n = round((top - y) / half) // 2
        for k in range(1, n + 1):
            ly = top - k * GAP
            fill_rect(canvas, round(x - ledger_w / 2), ly - LINE_T // 2, ledger_w, LINE_T, tint, alpha)
    elif y > bottom:
        n = round((y - bottom) / half) // 2
        for k in range(1, n + 1):
            ly = bottom + k * GAP
            fill_rect(canvas, round(x - ledger_w / 2), ly - LINE_T // 2, ledger_w, LINE_T, tint, alpha)
    if note["acc"]:
        name = ACC_SPRITE[note["acc"]]
        sw, sh, _ = sprites.mask(name)
        aw = round(ACC_H * sw / sh)
        blit(canvas, sprites, name, round(x - NOTEHEAD_W / 2 - aw + 1), round(y - ACC_H / 2), aw, ACC_H, tint, alpha)
    mid = top + 2 * GAP
    hw = NOTEHEAD_W / 2
    if y >= mid:  # stem up on the right of the notehead
        blit(canvas, sprites, "stem", round(x + hw - STEM_W / 2), y - STEM_LEN, STEM_W, STEM_LEN, tint, alpha)
    else:         # stem down on the left
        blit(canvas, sprites, "stem", round(x - hw - STEM_W / 2), y, STEM_W, STEM_LEN, tint, alpha)
    blit(canvas, sprites, "notehead_black", round(x - hw), y - NOTEHEAD_H // 2, NOTEHEAD_W, NOTEHEAD_H, tint, alpha)


def render_frame(notes, t, sprites):
    canvas = blank_canvas()
    draw_staff(canvas, sprites)
    onsets = [n["onset"] for n in notes]
    anchor = max((o for o in onsets if o <= t), default=(min(onsets) if onsets else 0.0))
    for n in sorted(notes, key=lambda n: n["onset"]):
        x = CENTER_X + (n["onset"] - anchor) * PPS
        if x < -80 or x > CANVAS_W + 80:
            continue
        if t >= n["end"]:
            alpha = PAST_PEAK * math.exp(-(t - n["end"]) / FADE_TAU)
            if alpha < 0.03:
                continue
            tint = PAST
        elif n["onset"] <= t:
            tint, alpha = CURRENT, 1.0
        else:
            tint, alpha = FUTURE, 0.9
        draw_note(canvas, sprites, n, x, tint, alpha)
    return canvas


def render_reference(notes, sprites):
    """Static, non-scrolling standard-notation view for the E2 comparison tile."""
    canvas = blank_canvas()
    draw_staff(canvas, sprites)
    dur = max((n["end"] for n in notes), default=SEGMENT_SECONDS)
    for n in sorted(notes, key=lambda n: n["onset"]):
        x = 220 + (n["onset"] / max(dur, 1e-6)) * 820
        draw_note(canvas, sprites, n, x, FUTURE, 0.92)
    return canvas


# --------------------------------------------------------------------------- -
# PNG write (pure python, straight RGBA) — mirrors render_spectra_layer.py
# --------------------------------------------------------------------------- -
def write_png(path, width, height, rgba):
    def chunk(tag, data):
        crc = zlib.crc32(tag + data) & 0xFFFFFFFF
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", crc)

    rows = bytearray()
    row_bytes = width * 4
    for y in range(height):
        rows.append(0)
        start = y * row_bytes
        rows.extend(rgba[start:start + row_bytes].tobytes())
    compressed = zlib.compress(bytes(rows), 9)
    ihdr = struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)
    payload = (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr)
               + chunk(b"IDAT", compressed) + chunk(b"IEND", b""))
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)


# --------------------------------------------------------------------------- -
# data
# --------------------------------------------------------------------------- -
def find_roll(data_root, fid):
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
                return roll_dir, frag
    raise SystemExit(f"fragment {fid} not found under {data_root}")


def load_fragment(data_root, fid):
    roll_dir, frag = find_roll(data_root, fid)
    try:
        seq = json.loads((roll_dir / "note_event_sequence.json").read_text(encoding="utf-8"))
        start = float(frag["start_seconds"])
        notes = []
        for e in seq["note_events"]:
            if e["fragment_id"] != fid:
                continue
            name = e["pitch_name_with_octave"]
            letter, rest, acc = name[0].upper(), name[1:], ""
            if rest[:1] in ("#", "b"):
                acc, rest = rest[0], rest[1:]
            diatonic = 7 * int(rest) + LETTER_STEPS[letter]
            # The frozen mother score reverses staff labels vs pitch content:
            # "Keyboard Lower Staff" carries the high/treble line (midi 60-86) and
            # "Keyboard Upper Staff" the low/bass line (midi 36-62). Assign the
            # staff by pitch content, i.e. flip the label comparison (this is a
            # render-layer correction; the frozen score is never edited).
            upper = e["source_part_id"] == "Keyboard Lower Staff"
            if upper:
                y = (TREBLE_TOP + 4 * GAP) - (diatonic - 30) * (GAP / 2)   # E4 (30) on treble bottom line
            else:
                y = (BASS_TOP + 4 * GAP) - (diatonic - 18) * (GAP / 2)      # G2 (18) on bass bottom line
            notes.append(dict(onset=float(e["start_seconds"]) - start, end=float(e["end_seconds"]) - start,
                              midi=int(e["midi"]), acc=acc, upper=upper, y=y,
                              name=name, part=e["source_part_abbreviation"]))
    except (OSError, ValueError, KeyError) as error:
        raise SystemExit(f"invalid fragment {fid} data in {roll_dir.name}: {error}") from error
    notes.sort(key=lambda n: (n["onset"], n["midi"]))
    return notes, frag, roll_dir.name


def render_fragment(notes, out_dir, sprites):
    """Write the 34-frame sequence; returns (per-frame max alpha, per-frame middle-C-band max alpha)."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    for old in out_dir.glob("frame_*.png"):
        old.unlink()
    alphas, midc = [], []
    band = range(MIDC_LEDGER_Y - 5, MIDC_LEDGER_Y + 6)  # rows around the shared middle-C ledger (y=360)
    for g in range(TOTAL_FRAMES):
        c = g - GATE_FRAMES
        if c < 0 or c >= CONTENT_FRAMES or c == CONTENT_FRAMES - 1:
            canvas = blank_canvas()                       # head/tail gate + completion frame
        else:
            canvas = render_frame(notes, c / FPS, sprites)
        write_png(out_dir / f"frame_{g:04d}.png", CANVAS_W, CANVAS_H, canvas)
        alphas.append(max(canvas[3::4]) if len(canvas) else 0)
        band_max = 0
        for yy in band:                                   # note-body band only (clefs/barline excluded)
            row = yy * CANVAS_W * 4
            m = max(canvas[row + NOTE_X_LO * 4 + 3: row + NOTE_X_HI * 4 + 3: 4], default=0)
            band_max = max(band_max, m)
        midc.append(band_max)
    return alphas, midc


def build_collage(tiles, out_path):
    tw, th, gap, margin = 290, 163, 18, 14
    total_w = 2 * margin + len(tiles) * tw + (len(tiles) - 1) * gap
    height = 2 * margin + th
    bg = SOL["bg"]
    canvas = array("B", bytes(total_w * height * 4))
    for i in range(total_w * height):
        canvas[i * 4:i * 4 + 3] = array("B", bg)
        canvas[i * 4 + 3] = 255
    for idx, src in enumerate(tiles):
        tx, ty = margin + idx * (tw + gap), margin
        for j in range(th):
            sy = j * CANVAS_H // th
            for i in range(tw):
                sx = i * CANVAS_W // tw
                sdi = (sy * CANVAS_W + sx) * 4
                a = src[sdi + 3] / 255.0
                if a <= 0:
                    continue
                di = ((ty + j) * total_w + tx + i) * 4
                ia = 1 - a
                canvas[di] = _to_byte(src[sdi] * a + canvas[di] * ia)
                canvas[di + 1] = _to_byte(src[sdi + 1] * a + canvas[di + 1] * ia)
                canvas[di + 2] = _to_byte(src[sdi + 2] * a + canvas[di + 2] * ia)
    write_png(out_path, total_w, height, canvas)
    return total_w, height


# --------------------------------------------------------------------------- -
# self-test / production
# --------------------------------------------------------------------------- -
def _check(failures, cond, msg):
    if not cond:
        failures.append(msg)


def selftest(data_root, out_root, sprites_root):
    sprites = Sprites(sprites_root)
    out_root = Path(out_root)
    out_root.mkdir(parents=True, exist_ok=True)
    failures, worst, samples = [], 0.0, {}

    for fid in SAMPLE_FRAGMENTS:
        notes, frag, roll = load_fragment(data_root, fid)
        out_dir = out_root / f"fragment_{fid}"
        alphas, midc = render_fragment(notes, out_dir, sprites)
        files = sorted(out_dir.glob("frame_*.png"))
        _check(failures, len(files) == TOTAL_FRAMES, f"frag {fid}: {len(files)} frames != {TOTAL_FRAMES}")
        for i in range(GATE_FRAMES):                                   # (b) head/tail gates transparent
            _check(failures, alphas[i] == 0, f"frag {fid}: head gate frame_{i:04d} alpha={alphas[i]}")
            _check(failures, alphas[TOTAL_FRAMES - 1 - i] == 0,
                   f"frag {fid}: tail gate frame_{TOTAL_FRAMES-1-i:04d} alpha={alphas[TOTAL_FRAMES-1-i]}")
        last_c = GATE_FRAMES + CONTENT_FRAMES - 1                      # (c) completion frame empty, prev not
        _check(failures, alphas[last_c] == 0, f"frag {fid}: completion frame_{last_c:04d} alpha={alphas[last_c]}")
        _check(failures, alphas[last_c - 1] > 0, f"frag {fid}: frame_{last_c-1:04d} unexpectedly empty")
        for g in range(GATE_FRAMES, last_c):                            # (f) no spurious middle-C ledger band
            _check(failures, midc[g] == 0,
                   f"frag {fid}: middle-C ledger band y=355..365 nonempty in frame_{g:04d} alpha={midc[g]}")
        for f in files:                                                # (e) size 1280x720
            w, h = png_size(f)
            _check(failures, (w, h) == (CANVAS_W, CANVAS_H), f"frag {fid}: {f.name} size {w}x{h}")
        for g in (0, last_c - 1, last_c):                              # disk round-trip proof
            _check(failures, max_alpha(out_dir / f"frame_{g:04d}.png") == alphas[g],
                   f"frag {fid}: PNG round-trip mismatch on frame_{g:04d}")
        onset_map = []                                                 # (d) quantization
        for n in notes:
            err = onset_quantization_error(n["onset"])
            worst = max(worst, err)
            _check(failures, err < QUANTIZATION_TOLERANCE,
                   f"frag {fid}: onset {n['onset']} quant err {err}")
            onset_map.append(dict(onset=round(n["onset"], 6), frame=onset_to_frame(n["onset"]),
                                  err=err, midi=n["midi"], part=n["part"]))
        samples[str(fid)] = dict(roll=roll, start_seconds=frag["start_seconds"],
                                 end_seconds=frag["end_seconds"], frames=len(files),
                                 note_count=len(notes), onset_to_frame=onset_map)

    tiles = [render_reference(load_fragment(data_root, SAMPLE_FRAGMENTS[0])[0], sprites)]
    for fid in SAMPLE_FRAGMENTS:
        tiles.append(render_frame(load_fragment(data_root, fid)[0], COLLAGE_TILE_CF / FPS, sprites))
    cw, ch = build_collage(tiles, out_root / "e2_collage.png")

    manifest = {
        "issue": 111, "lane": "83-R2",
        "timebase": dict(fps=FPS, content_frames=CONTENT_FRAMES, gate_frames=GATE_FRAMES,
                         total_frames=TOTAL_FRAMES, segment_seconds=SEGMENT_SECONDS,
                         onset_grid_seconds=ONSET_GRID_SECONDS,
                         quantization_tolerance=QUANTIZATION_TOLERANCE),
        "canvas": dict(width=CANVAS_W, height=CANVAS_H, format="RGBA PNG", background="transparent"),
        "decisions": {
            "layout": (f"grand staff: Kb.U. treble (F5 line y={TREBLE_TOP}) + Kb.L. bass (A3 line y={BASS_TOP}), "
                       f"GAP={GAP}px/step, shared middle-C ledger y={TREBLE_TOP+5*GAP}. Playhead pinned at "
                       f"x={CENTER_X} (screen centre); PPS={PPS}px/s so a 1/6s onset = 90px. Score scrolls "
                       "right-to-left: past notes drift left & fade, future notes queue right in reading order."),
            "highlight": ("current note = solarized cyan #2aa198 @ full alpha; future = base0 #839496 @0.9; "
                          "past = base01 #586e75 @ 0.8*exp(-age/0.25s); staff/clefs/ledgers = base1 #93a1a1 "
                          "@0.7. Mid-luminance greys + a mid-bright cyan read on both light #fdf6e3 and dark "
                          "#002b36 grounds."),
            "scaling": ("glyphs blitted from R1 Wikimedia sprites; the alpha channel is used as a coverage mask "
                        "and recoloured per note (sources are pure black). Staff height normalised to "
                        f"GAP={GAP}; notehead {NOTEHEAD_W}x{NOTEHEAD_H}, stem {STEM_W}x{STEM_LEN}, accidental "
                        f"h={ACC_H} (aspect preserved), treble clef h=7*GAP centred on G4, bass clef h=2.5*GAP "
                        "centred on F. Nearest-neighbour resample (no PIL)."),
            "clef_anchoring": ("approximate (ponytail): Wikimedia sprites share no metric; vertical centring on "
                               "the canonical curl/line is eyeball-tuned, not font-metric exact. Re-tune CLEF_X "
                               "and the clef heights if the E2 review objects."),
            "staff_lines": ("drawn as thin filled rectangles (no staff-line sprite exists); structural rules, "
                            "not musical glyphs, so this sits outside the 'blit-only, no python-drawn "
                            "disks/clefs' rule."),
            "staff_assignment": ("staff chosen by pitch content, not label: the frozen mother score reverses "
                                 "staff names vs pitch ('Keyboard Lower Staff' = high/treble midi 60-86, "
                                 "'Keyboard Upper Staff' = low/bass midi 36-62), so upper = "
                                 "source_part_id=='Keyboard Lower Staff'. Ledger counts use diatonic "
                                 "half-steps (floor(steps/2)); the notehead y is unchanged."),
        },
        "samples": samples,
        "worst_quantization_error_frames": worst,
        "collage": dict(path="e2_collage.png", width=cw, height=ch,
                        tiles=["standard_reference"] + [f"fragment_{f}" for f in SAMPLE_FRAGMENTS],
                        keyframe_content_frame=COLLAGE_TILE_CF),
    }
    (out_root / "r2_manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")

    for fid in SAMPLE_FRAGMENTS:
        print(f"[{'PASS' if not failures else '....'}] fragment {fid}: {samples[str(fid)]['frames']} frames, "
              f"{samples[str(fid)]['note_count']} notes (roll {samples[str(fid)]['roll']})")
    print(f"[{'PASS' if worst < QUANTIZATION_TOLERANCE else 'FAIL'}] worst onset quantization error "
          f"{worst:.3e} < {QUANTIZATION_TOLERANCE} frames")
    print(f"collage: e2_collage.png ({cw}x{ch}), manifest: r2_manifest.json")
    if failures:
        for msg in failures:
            print(f"       FAIL {msg}")
        print(f"[FAIL] staff-layer self-check: {len(failures)} failure(s)")
        return 1
    print("[PASS] staff-layer self-check (a-e)")
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--data-root", default=DEFAULT_DATA_ROOT)
    ap.add_argument("--fragment", type=int)
    ap.add_argument("--out-dir")
    ap.add_argument("--out-root", default=DEFAULT_OUT_ROOT)
    ap.add_argument("--sprites", default=DEFAULT_SPRITES)
    ap.add_argument("--selftest", action="store_true")
    args = ap.parse_args(argv)

    if args.selftest:
        return selftest(args.data_root, args.out_root, args.sprites)
    if args.fragment is None or not args.out_dir:
        ap.error("--fragment and --out-dir are required (or pass --selftest)")

    notes, frag, roll = load_fragment(args.data_root, args.fragment)
    render_fragment(notes, args.out_dir, Sprites(args.sprites))
    print(f"rendered fragment {args.fragment} (roll {roll}) "
          f"{frag['start_seconds']}s-{frag['end_seconds']}s -> {TOTAL_FRAMES} frames in {args.out_dir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
