#!/usr/bin/env python3
"""Neutral-frame gate for Musikalisches fragment concatenation (issue #93).

Contract being enforced: 176 unique fragments (fragment 1..176), each opening on
15 fully transparent frames and closing on 15 fully transparent frames, with all
pixel alpha below --threshold in every gate frame. Transparent gates are what
make any concatenation order seamless, whatever the 11**16 slot orderings are.

Usage:
  neutral_frame_check.py --generate DIR              # deterministic fixture, 176 fragments
  neutral_frame_check.py --fragments-dir DIR [--threshold 0.05]

Fragment layout expected under --fragments-dir:
  fragment_001/frame_0000.png ... frame_0040.png   (>= 31 frames, sorted by frame number)

Only the Python standard library is used (zlib + struct for PNG), so the check
runs on any real render output as well as on the generated fixture.
"""
from __future__ import annotations

import argparse
import re
import struct
import sys
import zlib
from pathlib import Path

HEAD_FRAMES = 15
TAIL_FRAMES = 15
EXPECTED_FRAGMENTS = 176
MIN_FRAMES = HEAD_FRAMES + 1 + TAIL_FRAMES  # at least one opaque frame in the middle

# Fixture geometry: small on purpose, the gate contract is about alpha, not size.
WIDTH, HEIGHT, MIDDLE_FRAMES = 96, 64, 11
TOTAL_FRAMES = HEAD_FRAMES + MIDDLE_FRAMES + TAIL_FRAMES  # 41

FRAGMENT_RE = re.compile(r"^fragment_(\d+)$")
FRAME_NUM_RE = re.compile(r"(\d+)")


# ---------------------------------------------------------------- PNG I/O -----

def read_png(path: Path) -> tuple[int, int, bytes]:
    """Read an 8-bit non-interlaced RGB/RGBA PNG into (width, height, RGBA bytes)."""
    data = path.read_bytes()
    if data[:8] != b"\x89PNG\r\n\x1a\n":
        raise ValueError(f"{path}: not a PNG")
    ihdr = None
    idat = bytearray()
    pos = 8
    while pos + 8 <= len(data):
        (length,) = struct.unpack(">I", data[pos:pos + 4])
        tag = data[pos + 4:pos + 8]
        body = data[pos + 8:pos + 8 + length]
        if tag == b"IHDR":
            ihdr = struct.unpack(">IIBBBBB", body)
        elif tag == b"IDAT":
            idat += body
        elif tag == b"IEND":
            break
        pos += 12 + length
    if ihdr is None:
        raise ValueError(f"{path}: missing IHDR")
    width, height, depth, ctype, comp, filt, inter = ihdr
    if depth != 8 or comp != 0 or filt != 0 or inter != 0:
        raise ValueError(f"{path}: only 8-bit non-interlaced PNG supported (depth={depth}, interlace={inter})")
    if ctype not in (2, 6):
        raise ValueError(f"{path}: expected RGB or RGBA PNG, got color type {ctype}")
    channels = 3 if ctype == 2 else 4
    stride = width * channels
    raw = zlib.decompress(bytes(idat))
    if len(raw) < height * (stride + 1):
        raise ValueError(f"{path}: truncated IDAT")
    out = bytearray(width * height * 4)
    prev = bytearray(stride)
    bpp = channels
    p = 0
    for y in range(height):
        f = raw[p]
        p += 1
        line = bytearray(raw[p:p + stride])
        p += stride
        if f == 1:  # Sub
            for i in range(bpp, stride):
                line[i] = (line[i] + line[i - bpp]) & 0xFF
        elif f == 2:  # Up
            for i in range(stride):
                line[i] = (line[i] + prev[i]) & 0xFF
        elif f == 3:  # Average
            for i in range(stride):
                a = line[i - bpp] if i >= bpp else 0
                line[i] = (line[i] + ((a + prev[i]) >> 1)) & 0xFF
        elif f == 4:  # Paeth
            for i in range(stride):
                a = line[i - bpp] if i >= bpp else 0
                b = prev[i]
                c = prev[i - bpp] if i >= bpp else 0
                pp = a + b - c
                pa, pb, pc = abs(pp - a), abs(pp - b), abs(pp - c)
                pred = a if pa <= pb and pa <= pc else (b if pb <= pc else c)
                line[i] = (line[i] + pred) & 0xFF
        elif f != 0:
            raise ValueError(f"{path}: unsupported PNG filter {f}")
        if channels == 4:
            out[y * stride:(y + 1) * stride] = line
        else:
            dst = y * width * 4
            for x in range(width):
                s = x * 3
                out[dst:dst + 3] = line[s:s + 3]
                out[dst + 3] = 255
                dst += 4
        prev = line
    return width, height, bytes(out)


def write_png(path: Path, width: int, height: int, rgba: bytes) -> None:
    """Minimal PNG writer (filter 0 only), same idea as render_spectra_layer.write_png."""
    def chunk(tag: bytes, body: bytes) -> bytes:
        crc = zlib.crc32(tag + body) & 0xFFFFFFFF
        return struct.pack(">I", len(body)) + tag + body + struct.pack(">I", crc)

    row_bytes = width * 4
    rows = bytearray()
    for y in range(height):
        rows.append(0)
        start = y * row_bytes
        rows.extend(rgba[start:start + row_bytes])
    ihdr = struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)
    payload = (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", ihdr)
        + chunk(b"IDAT", zlib.compress(bytes(rows), 6))
        + chunk(b"IEND", b"")
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    # pi-lens-ignore: python-path-traversal
    path.write_bytes(payload)


# ------------------------------------------------------------ fragment map ----

def fragment_dirs(root: Path) -> dict[int, Path]:
    found: dict[int, Path] = {}
    for child in sorted(root.iterdir()):
        match = FRAGMENT_RE.match(child.name)
        if child.is_dir() and match:
            # pi-lens-ignore: ast-grep:unchecked-throwing-call-python
            found[int(match.group(1))] = child
    return found


def frame_paths(fragment_dir: Path) -> list[Path]:
    def sort_key(path: Path) -> tuple[int, int, str]:
        match = FRAME_NUM_RE.search(path.stem)
        # pi-lens-ignore: ast-grep:unchecked-throwing-call-python
        return (0, int(match.group(1)), path.stem) if match else (1, 0, path.stem)

    return sorted((p for p in fragment_dir.iterdir() if p.suffix == ".png"), key=sort_key)


def max_alpha(rgba: bytes) -> float:
    """Highest normalized alpha in an RGBA byte string (0.0 for an empty frame)."""
    if not rgba:
        return 0.0
    return max(rgba[3::4]) / 255.0


# ----------------------------------------------------------------- checking ---

def check_fragments(root: Path, threshold: float) -> dict:
    """Run the head/tail transparency gate over every fragment under root.

    Returns a report dict; 'violations' is non-empty (or 'errors' is non-empty)
    when the contract is broken.
    """
    report: dict = {
        "fragments_dir": str(root),
        "fragments_checked": 0,
        "fragments_expected": EXPECTED_FRAGMENTS,
        "head_frames": HEAD_FRAMES,
        "tail_frames": TAIL_FRAMES,
        "threshold": threshold,
        "max_alpha_head": 0.0,
        "max_alpha_tail": 0.0,
        "violations": [],
        "errors": [],
    }
    if not root.is_dir():
        report["errors"].append(f"fragments dir not found: {root}")
        return report

    fragments = fragment_dirs(root)
    report["fragments_checked"] = len(fragments)
    missing = sorted(set(range(1, EXPECTED_FRAGMENTS + 1)) - set(fragments))
    extra = sorted(set(fragments) - set(range(1, EXPECTED_FRAGMENTS + 1)))
    if missing:
        report["errors"].append(f"missing fragment ids: {missing}")
    if extra:
        report["errors"].append(f"unexpected fragment ids: {extra}")

    for fid in sorted(fragments):
        frames = frame_paths(fragments[fid])
        if len(frames) < MIN_FRAMES:
            report["errors"].append(
                f"fragment_{fid:03d}: {len(frames)} frame(s), need >= {MIN_FRAMES}"
            )
            continue
        for position, subset in (("head", frames[:HEAD_FRAMES]), ("tail", frames[-TAIL_FRAMES:])):
            for path in subset:
                try:
                    _, _, rgba = read_png(path)
                except (OSError, ValueError, zlib.error) as exc:
                    report["errors"].append(f"fragment_{fid:03d}: {exc}")
                    continue
                observed = max_alpha(rgba)
                key = "max_alpha_head" if position == "head" else "max_alpha_tail"
                report[key] = max(report[key], observed)
                if observed >= threshold:
                    report["violations"].append(
                        {
                            "fragment": fid,
                            "fragment_dir": fragments[fid].name,
                            "position": position,
                            "frame": path.name,
                            "max_alpha": observed,
                        }
                    )
    report["pass"] = not report["violations"] and not report["errors"]
    return report


def print_report(report: dict) -> None:
    for error in report["errors"]:
        print(f"ERROR {error}")
    for violation in report["violations"]:
        print(
            "VIOLATION fragment_{fid:03d} {position} {frame} "
            "max_alpha={alpha:.6f} (threshold {threshold})".format(
                fid=violation["fragment"],
                position=violation["position"],
                frame=violation["frame"],
                alpha=violation["max_alpha"],
                threshold=report["threshold"],
            )
        )
    if report["pass"]:
        print(
            "neutral frame check: {n}/{e} fragments passed "
            "(head {h} + tail {t} frames, alpha < {thr})".format(
                n=report["fragments_checked"],
                e=report["fragments_expected"],
                h=report["head_frames"],
                t=report["tail_frames"],
                thr=report["threshold"],
            )
        )
    else:
        print(
            "neutral frame check FAILED: {v} violation(s), {e} error(s) "
            "over {n} fragment(s)".format(
                v=len(report["violations"]),
                e=len(report["errors"]),
                n=report["fragments_checked"],
            )
        )


# ------------------------------------------------------------- fixture gen ----

def frame_rgba(fragment_id: int, index: int) -> bytes:
    """Deterministic RGBA for one fixture frame: opaque middle, transparent gates."""
    rgba = bytearray(WIDTH * HEIGHT * 4)
    if HEAD_FRAMES <= index < HEAD_FRAMES + MIDDLE_FRAMES:
        step = index - HEAD_FRAMES
        base = ((fragment_id * 37) % 256, (fragment_id * 91 + 40) % 256, (fragment_id * 151 + 80) % 256)
        accent = tuple(255 - channel for channel in base)
        row = bytes(base) + b"\xff"
        rgba[:] = row * WIDTH * HEIGHT
        x0 = (fragment_id * 7 + step * 3) % (WIDTH - 16)
        y0 = (fragment_id * 11 + step * 5) % (HEIGHT - 8)
        block = (bytes(accent) + b"\xff") * 16
        for y in range(y0, y0 + 8):
            start = (y * WIDTH + x0) * 4
            rgba[start:start + 16 * 4] = block
    return bytes(rgba)


def generate(root: Path, count: int = EXPECTED_FRAGMENTS) -> None:
    for fragment_id in range(1, count + 1):
        fragment_dir = root / f"fragment_{fragment_id:03d}"
        fragment_dir.mkdir(parents=True, exist_ok=True)
        for index in range(TOTAL_FRAMES):
            path = fragment_dir / f"frame_{index:04d}.png"
            write_png(path, WIDTH, HEIGHT, frame_rgba(fragment_id, index))
    print(
        f"generated {count} deterministic fragment(s) x {TOTAL_FRAMES} frame(s) "
        f"({WIDTH}x{HEIGHT} RGBA) into {root}"
    )


# --------------------------------------------------------------------- main ----

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--fragments-dir", type=Path, help="directory holding fragment_NNN/ frame sequences")
    parser.add_argument("--threshold", type=float, default=0.05, help="max allowed normalized alpha in a gate frame")
    parser.add_argument("--generate", type=Path, metavar="DIR", help="write the deterministic fixture into DIR and exit")
    args = parser.parse_args(argv)

    if args.generate:
        generate(args.generate)
        return 0
    if not args.fragments_dir:
        parser.error("--fragments-dir is required unless --generate is used")

    report = check_fragments(args.fragments_dir, args.threshold)
    print_report(report)
    return 0 if report["pass"] else 1


if __name__ == "__main__":
    sys.exit(main())
