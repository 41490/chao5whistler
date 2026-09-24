#!/usr/bin/env python3
"""Build RGBA sprite PNGs for issue #110 (83-R1) from public score SVGs.

Glyph sources are Wikimedia Commons files (public domain where available); each
SVG is downloaded once into ``<out>/sprites/src/`` and rasterized offline with
librsvg + cairo through ctypes — this lane has no pip/PIL.

Outputs:
  <out>/sprites/<name>.png    RGBA sprite (uniform SCALE on the SVG intrinsic size)
  <out>/sprites/src/*.svg     cached SVG sources
  <out>/r1_manifest.json      "sprites" section merged into the run manifest

Usage:
  python3 build_glyph_sprites.py [--out-root DIR] [--selftest]
"""

import argparse
import ctypes
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fragment_timebase import AUDIO_SAMPLES, AUDIO_SR, CONTENT_FRAMES, FPS, GATE_FRAMES  # noqa: F401

DEFAULT_OUT_ROOT = "/opt/logs/41490/out/260924-issue83-r1"
MANIFEST_NAME = "r1_manifest.json"
SCALE = 3  # uniform multiplier on the SVG intrinsic size; keeps glyph proportions
USER_AGENT = "issue83-sprite-builder/1.0 (offline rasterization; repo 41490/chao5whistler)"
CAIRO_FORMAT_ARGB32 = 0

# name -> Commons source. "file" is the cached filename under sprites/src/.
GLYPHS = [
    dict(name="treble_clef", file="Treble_clef.svg",
         url="https://upload.wikimedia.org/wikipedia/commons/f/fa/Treble_clef.svg",
         commons="File:Treble clef.svg", license="Public domain",
         author="Wikimedia Commons (no machine-readable author)"),
    dict(name="bass_clef", file="Bass_clef.svg",
         url="https://upload.wikimedia.org/wikipedia/commons/6/61/Bass_clef.svg",
         commons="File:Bass clef.svg", license="Public domain",
         author="Wikimedia Commons (no machine-readable author)"),
    dict(name="notehead_black", file="BlackNotehead.svg",
         url="https://upload.wikimedia.org/wikipedia/commons/2/2a/BlackNotehead.svg",
         commons="File:BlackNotehead.svg", license="Public domain", author="Eliyak"),
    dict(name="notehead_white", file="WhiteNotehead.svg",
         url="https://upload.wikimedia.org/wikipedia/commons/6/62/WhiteNotehead.svg",
         commons="File:WhiteNotehead.svg", license="CC BY 2.5", author="っ"),
    dict(name="note_whole", file="Music-wholenote.svg",
         url="https://upload.wikimedia.org/wikipedia/commons/a/a0/Music-wholenote.svg",
         commons="File:Music-wholenote.svg", license="Public domain", author="Popadius"),
    dict(name="note_eighth", file="Music-eighthnote.svg",
         url="https://upload.wikimedia.org/wikipedia/commons/5/5b/Music-eighthnote.svg",
         commons="File:Music-eighthnote.svg", license="Public domain", author="Popadius"),
    dict(name="sharp", file="Music-sharp.svg",
         url="https://upload.wikimedia.org/wikipedia/commons/d/da/Music-sharp.svg",
         commons="File:Music-sharp.svg", license="CC BY-SA 3.0", author="Wikimedia Commons"),
    dict(name="flat", file="Music-flat.svg",
         url="https://upload.wikimedia.org/wikipedia/commons/c/c7/Music-flat.svg",
         commons="File:Music-flat.svg", license="CC BY-SA 3.0", author="Wikimedia Commons"),
    dict(name="natural", file="Music-natural.svg",
         url="https://upload.wikimedia.org/wikipedia/commons/f/f4/Music-natural.svg",
         commons="File:Music-natural.svg", license="CC BY-SA 3.0", author="Wikimedia Commons"),
    dict(name="barline", file="Music-bar.svg",
         url="https://upload.wikimedia.org/wikipedia/commons/4/4d/Music-bar.svg",
         commons="File:Music-bar.svg", license="Public domain",
         author="Wikimedia Commons (derivative work)"),
    # No suitable public-domain Commons file for a bare stem; authored locally as a
    # plain rectangle so the 符干 primitive exists as its own sprite.
    dict(name="stem", file="stem.svg", url=None, commons=None,
         license="generated locally (no third-party source)", author="issue83-r1",
         inline=('<svg xmlns="http://www.w3.org/2000/svg" width="24" height="240" '
                 'viewBox="0 0 24 240"><rect x="8" y="0" width="8" height="240" '
                 'fill="#000000"/></svg>')),
]


class RsvgDimensionData(ctypes.Structure):
    """librsvg's RsvgDimensionData (width/height in SVG user units)."""

    _fields_ = [("width", ctypes.c_int), ("height", ctypes.c_int),
                ("em", ctypes.c_double), ("ex", ctypes.c_double)]


_LIBS = None


def _libs():
    """librsvg + cairo, argtypes configured once."""
    global _LIBS
    if _LIBS is None:
        rsvg = ctypes.CDLL("librsvg-2.so.2")
        cairo = ctypes.CDLL("libcairo.so.2")
        rsvg.rsvg_handle_new_from_file.restype = ctypes.c_void_p
        rsvg.rsvg_handle_new_from_file.argtypes = [ctypes.c_char_p, ctypes.c_void_p]
        rsvg.rsvg_handle_render_cairo.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
        rsvg.rsvg_handle_get_dimensions.restype = None
        rsvg.rsvg_handle_get_dimensions.argtypes = [ctypes.c_void_p,
                                                    ctypes.POINTER(RsvgDimensionData)]
        rsvg.g_object_unref.argtypes = [ctypes.c_void_p]
        cairo.cairo_image_surface_create.restype = ctypes.c_void_p
        cairo.cairo_image_surface_create.argtypes = [ctypes.c_int] * 3
        cairo.cairo_create.restype = ctypes.c_void_p
        cairo.cairo_create.argtypes = [ctypes.c_void_p]
        cairo.cairo_scale.restype = None
        cairo.cairo_scale.argtypes = [ctypes.c_void_p, ctypes.c_double, ctypes.c_double]
        cairo.cairo_set_source_surface.restype = None
        cairo.cairo_set_source_surface.argtypes = [ctypes.c_void_p, ctypes.c_void_p,
                                                   ctypes.c_double, ctypes.c_double]
        cairo.cairo_paint.restype = None
        cairo.cairo_paint.argtypes = [ctypes.c_void_p]
        cairo.cairo_surface_write_to_png.restype = ctypes.c_int
        cairo.cairo_surface_write_to_png.argtypes = [ctypes.c_void_p, ctypes.c_char_p]
        cairo.cairo_surface_flush.restype = None
        cairo.cairo_surface_flush.argtypes = [ctypes.c_void_p]
        cairo.cairo_image_surface_get_data.restype = ctypes.POINTER(ctypes.c_ubyte)
        cairo.cairo_image_surface_get_data.argtypes = [ctypes.c_void_p]
        cairo.cairo_image_surface_get_stride.restype = ctypes.c_int
        cairo.cairo_image_surface_get_stride.argtypes = [ctypes.c_void_p]
        cairo.cairo_image_surface_get_width.restype = ctypes.c_int
        cairo.cairo_image_surface_get_width.argtypes = [ctypes.c_void_p]
        cairo.cairo_image_surface_get_height.restype = ctypes.c_int
        cairo.cairo_image_surface_get_height.argtypes = [ctypes.c_void_p]
        cairo.cairo_image_surface_get_format.restype = ctypes.c_int
        cairo.cairo_image_surface_get_format.argtypes = [ctypes.c_void_p]
        cairo.cairo_image_surface_create_from_png.restype = ctypes.c_void_p
        cairo.cairo_image_surface_create_from_png.argtypes = [ctypes.c_char_p]
        cairo.cairo_surface_destroy.argtypes = [ctypes.c_void_p]
        cairo.cairo_destroy.argtypes = [ctypes.c_void_p]
        _LIBS = (rsvg, cairo)
    return _LIBS


THUMB_BUCKETS = (120, 250, 500, 1280, 1920)  # the only widths upload.wikimedia.org serves
API_URL = "https://commons.wikimedia.org/w/api.php"


class RateLimited(Exception):
    """upload.wikimedia.org refused the original file with HTTP 429."""


def http_get(url):
    """GET bytes; raises RateLimited on 429 so the caller can use a thumbnail."""
    last = None
    for attempt in range(3):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(req, timeout=60) as resp:
                return resp.read()
        except urllib.error.HTTPError as exc:
            if exc.code == 429:
                raise RateLimited(url) from exc
            last = exc
            time.sleep(5 * (attempt + 1))
        except urllib.error.URLError as exc:
            last = exc
            time.sleep(5 * (attempt + 1))
    raise RuntimeError(f"could not fetch {url}: {last}")


def get_with_backoff(url, attempts=4):
    """GET bytes, backing off while Wikimedia keeps answering 429."""
    for attempt in range(attempts):
        try:
            return http_get(url)
        except RateLimited:
            time.sleep(10 * (attempt + 1))
    raise RateLimited(url)


def thumb_url(file_url, width):
    """Original-file URL -> standard thumbnail URL (raster render of the SVG)."""
    base = file_url.split("?")[0]
    name = base.rsplit("/", 1)[-1]
    return base.replace("/commons/", "/commons/thumb/") + f"/{width}px-{name}.png"


def bucket_for(width):
    """Smallest standard thumbnail width >= width (keeps glyph proportions sane)."""
    for bucket in THUMB_BUCKETS:
        if bucket >= width:
            return bucket
    return THUMB_BUCKETS[-1]


def intrinsic_sizes(out_root, glyphs):
    """commons title -> (width, height) from the Commons API, cached on disk."""
    cache = Path(out_root) / "sprites" / "src" / "commons_sizes.json"
    sizes = {}
    if cache.exists():
        try:
            sizes = json.loads(cache.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            sizes = {}
    missing = [g["commons"] for g in glyphs if g.get("commons") and g["commons"] not in sizes]
    if missing:
        url = (f"{API_URL}?action=query&prop=imageinfo&iiprop=size&format=json&titles="
               + urllib.parse.quote("|".join(missing)))
        try:
            data = json.loads(get_with_backoff(url))
            for page in data["query"]["pages"].values():
                info = page["imageinfo"][0]
                sizes[page["title"]] = [info["width"], info["height"]]
        except (OSError, ValueError) as exc:
            raise SystemExit(f"could not read Commons sizes: {exc}")
        cache.parent.mkdir(parents=True, exist_ok=True)
        cache.write_text(json.dumps(sizes, indent=2) + "\n", encoding="utf-8")
    return sizes


def _fetch_thumbnail(glyph, src_dir, sizes):
    """Original file was rate-limited: pull the standard thumbnail bucket instead."""
    width = bucket_for(sizes[glyph["commons"]][0] * SCALE)
    dest = src_dir / f"{glyph['file']}.{width}px.png"
    cached = dest.exists() and dest.stat().st_size > 0
    if cached:
        print(f"  cached {dest.name}")
        return
    try:
        dest.write_bytes(get_with_backoff(thumb_url(glyph["url"], width)))
    except RateLimited as exc:
        raise SystemExit(f"thumbnail for {glyph['file']} kept getting 429: {exc}")
    print(f"  rate-limited (429); {glyph['file']} <- {width}px thumbnail")


def fetch_sources(out_root):
    """Populate <out>/sprites/src/ from the glyph table; returns the src dir."""
    src_dir = Path(out_root) / "sprites" / "src"
    src_dir.mkdir(parents=True, exist_ok=True)
    sizes = intrinsic_sizes(out_root, GLYPHS)
    for glyph in GLYPHS:
        if glyph.get("inline"):
            dest = src_dir / glyph["file"]
            if not (dest.exists() and dest.stat().st_size > 0):
                dest.write_text(glyph["inline"], encoding="utf-8")
            continue
        svg = src_dir / glyph["file"]
        if svg.exists() and svg.stat().st_size > 0:
            continue
        try:
            data = http_get(glyph["url"])
            if not data.lstrip().startswith(b"<"):
                raise ValueError(f"{glyph['url']} did not return SVG markup")
            svg.write_bytes(data)
            print(f"  fetched {glyph['file']} ({len(data)} bytes) <- {glyph['commons']}")
        except RateLimited:
            _fetch_thumbnail(glyph, src_dir, sizes)
        time.sleep(1.5)  # stay polite with upload.wikimedia.org
    return src_dir


def source_for(src_dir, glyph):
    """Cached source for a glyph: the SVG, or its thumbnail PNG when rate-limited."""
    svg = src_dir / glyph["file"]
    if svg.exists():
        return svg
    for candidate in sorted(src_dir.glob(glyph["file"] + ".*px.png")):
        return candidate
    raise SystemExit(f"no cached source for {glyph['name']}")


def rasterize(svg_path, png_path, scale=SCALE):
    """Rasterize one SVG to an RGBA PNG; returns (width, height, alpha_nonzero)."""
    rsvg, cairo = _libs()
    handle = rsvg.rsvg_handle_new_from_file(os.fsencode(svg_path), None)
    if not handle:
        raise RuntimeError(f"librsvg could not load {svg_path}")
    try:
        dims = RsvgDimensionData()
        rsvg.rsvg_handle_get_dimensions(handle, ctypes.byref(dims))
        w = max(1, int(dims.width * scale))
        h = max(1, int(dims.height * scale))
        surface = cairo.cairo_image_surface_create(CAIRO_FORMAT_ARGB32, w, h)
        if not surface:
            raise RuntimeError(f"cairo could not allocate {w}x{h} surface")
        try:
            cr = cairo.cairo_create(surface)
            if not cr:
                raise RuntimeError("cairo could not create a context")
            cairo.cairo_scale(cr, float(scale), float(scale))
            rsvg.rsvg_handle_render_cairo(handle, cr)
            cairo.cairo_destroy(cr)
            cairo.cairo_surface_flush(surface)
            if cairo.cairo_surface_write_to_png(surface, os.fsencode(png_path)) != 0:
                raise RuntimeError(f"cairo could not write {png_path}")
        finally:
            cairo.cairo_surface_destroy(surface)
    finally:
        rsvg.g_object_unref(handle)
    return w, h, alpha_nonzero(png_path)


def alpha_nonzero(png_path):
    """Count pixels with alpha > 0 in a PNG (cairo read-back; no PIL in this lane)."""
    _, cairo = _libs()
    surface = cairo.cairo_image_surface_create_from_png(os.fsencode(png_path))
    if not surface:
        raise RuntimeError(f"cairo could not read back {png_path}")
    try:
        cairo.cairo_surface_flush(surface)
        w = cairo.cairo_image_surface_get_width(surface)
        h = cairo.cairo_image_surface_get_height(surface)
        stride = cairo.cairo_image_surface_get_stride(surface)
        fmt = cairo.cairo_image_surface_get_format(surface)
        if fmt != CAIRO_FORMAT_ARGB32:
            raise RuntimeError(f"{png_path}: surface format {fmt} is not ARGB32/RGBA")
        data = cairo.cairo_image_surface_get_data(surface)
        nz = 0
        for y in range(h):
            row = y * stride
            for x in range(w):
                if data[row + x * 4 + 3]:
                    nz += 1
        return nz
    finally:
        cairo.cairo_surface_destroy(surface)


def rasterize_source(src_path, png_path, scale=SCALE):
    """Rasterize an SVG, or copy a thumbnail PNG through cairo as RGBA."""
    if src_path.suffix != ".svg":
        return copy_rgba(src_path, png_path)
    return rasterize(src_path, png_path, scale)


def copy_rgba(src_png, png_path):
    """Re-encode a raster source as an RGBA (ARGB32) PNG sprite."""
    _, cairo = _libs()
    src = cairo.cairo_image_surface_create_from_png(os.fsencode(src_png))
    if not src:
        raise RuntimeError(f"cairo could not read back {src_png}")
    try:
        cairo.cairo_surface_flush(src)
        w = cairo.cairo_image_surface_get_width(src)
        h = cairo.cairo_image_surface_get_height(src)
        dst = cairo.cairo_image_surface_create(CAIRO_FORMAT_ARGB32, w, h)
        if not dst:
            raise RuntimeError(f"cairo could not allocate {w}x{h} surface")
        try:
            cr = cairo.cairo_create(dst)
            cairo.cairo_set_source_surface(cr, src, 0.0, 0.0)
            cairo.cairo_paint(cr)
            cairo.cairo_destroy(cr)
            cairo.cairo_surface_flush(dst)
            if cairo.cairo_surface_write_to_png(dst, os.fsencode(png_path)) != 0:
                raise RuntimeError(f"cairo could not write {png_path}")
        finally:
            cairo.cairo_surface_destroy(dst)
    finally:
        cairo.cairo_surface_destroy(src)
    return w, h, alpha_nonzero(png_path)


def build(out_root):
    src_dir = fetch_sources(out_root)
    sprite_dir = Path(out_root) / "sprites"
    entries = []
    for glyph in GLYPHS:
        src_path = source_for(src_dir, glyph)
        png_path = sprite_dir / f"{glyph['name']}.png"
        w, h, nz = rasterize_source(src_path, png_path)
        entry = dict(glyph)
        entry.pop("inline", None)
        entry.update(file=f"{glyph['name']}.png", source_svg=f"src/{src_path.name}",
                     source_kind="svg" if src_path.suffix == ".svg" else "thumbnail_png",
                     width=w, height=h, alpha_nonzero_pixels=nz)
        entries.append(entry)
        print(f"  [{'PASS' if nz > 0 else 'FAIL'}] {glyph['name']}: {w}x{h} alpha>0={nz}")
    empty = [e["file"] for e in entries if e["alpha_nonzero_pixels"] <= 0]
    if empty:
        raise SystemExit(f"sprites with empty alpha: {empty}")
    return entries


def manifest_path(out_root):
    return Path(out_root) / MANIFEST_NAME


def load_manifest(out_root):
    path = manifest_path(out_root)
    manifest = {}
    if path.exists():
        try:
            manifest = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise SystemExit(f"unreadable manifest {path}: {exc}")
    manifest.setdefault("generated_by", "issue83-r1")
    manifest.setdefault("sprites", [])
    manifest.setdefault("audio", None)
    return manifest


def selftest(out_root):
    sprite_dir = Path(out_root) / "sprites"
    pngs = sorted(sprite_dir.glob("*.png")) if sprite_dir.is_dir() else []
    if not pngs:
        print(f"[FAIL] no sprites under {sprite_dir}")
        return 1
    failures = 0
    for png in pngs:
        try:
            nz = alpha_nonzero(png)
        except RuntimeError as exc:
            print(f"[FAIL] {png.name}: {exc}")
            failures += 1
            continue
        ok = nz > 0
        print(f"[{'PASS' if ok else 'FAIL'}] {png.name}: alpha>0={nz}")
        failures += 0 if ok else 1
    print(f"sprite self-check: {failures} failure(s)")
    return 1 if failures else 0


def main(argv=None):
    ap = argparse.ArgumentParser(description="build RGBA glyph sprites (issue #110)")
    ap.add_argument("--out-root", default=DEFAULT_OUT_ROOT)
    ap.add_argument("--selftest", action="store_true",
                    help="re-verify every sprite PNG in <out-root>/sprites")
    args = ap.parse_args(argv)

    if args.selftest:
        return selftest(args.out_root)

    entries = build(args.out_root)
    manifest = load_manifest(args.out_root)
    manifest["sprites"] = entries
    manifest["sprite_count"] = len(entries)
    manifest["timebase"] = dict(fps=FPS, content_frames=CONTENT_FRAMES, gate_frames=GATE_FRAMES,
                                total_frames=CONTENT_FRAMES + 2 * GATE_FRAMES,
                                audio_sr=AUDIO_SR, audio_samples=AUDIO_SAMPLES)
    manifest_path(args.out_root).write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"wrote {manifest_path(args.out_root)} ({len(entries)} sprites)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
