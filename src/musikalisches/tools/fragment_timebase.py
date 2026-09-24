#!/usr/bin/env python3
"""Issue #110 (83-R1) fragment time contract — single source of truth.

Decisions D1/D2 (CTO authorized):
  * 24 fps timeline.
  * 18 content frames per fragment == 0.75 s of content.
  * 5 fully transparent gate frames at head and tail -> 28 frames per fragment.
  * audio 0.75 s == 33075 samples @ 44100 Hz.
  * onset grid 0.125 s (half a frame); ``round(t * FPS)`` must be exact
    (zero quantization error) for every onset of the 11 source rolls.

Every other tool in this lane imports the constants from here instead of
re-deriving them.
"""

import argparse
import sys

FPS = 24
CONTENT_FRAMES = 18
GATE_FRAMES = 5
TOTAL_FRAMES = CONTENT_FRAMES + 2 * GATE_FRAMES  # 28
AUDIO_SR = 44100
AUDIO_SAMPLES = 33075
SEGMENT_SECONDS = 0.75
ONSET_GRID_SECONDS = 0.125  # 16th note @ 120 bpm == 3 frames @ 24 fps
QUANTIZATION_TOLERANCE = 1e-9


def onset_to_frame(t):
    """Map an onset time (seconds) to a frame index on the 24 fps grid."""
    return round(t * FPS)


def frame_to_seconds(frame):
    return frame / FPS


def onset_quantization_error(t):
    """|round(t*FPS) - t*FPS| — must stay below QUANTIZATION_TOLERANCE."""
    return abs(onset_to_frame(t) - t * FPS)


def contract_failures():
    """Return a list of human-readable contract violations (empty == healthy)."""
    failures = []
    if TOTAL_FRAMES != 28:
        failures.append(f"TOTAL_FRAMES={TOTAL_FRAMES}, expected 28")
    if CONTENT_FRAMES + 2 * GATE_FRAMES != TOTAL_FRAMES:
        failures.append("CONTENT_FRAMES + 2*GATE_FRAMES != TOTAL_FRAMES")
    if SEGMENT_SECONDS * FPS != CONTENT_FRAMES:
        failures.append(f"SEGMENT_SECONDS*FPS={SEGMENT_SECONDS * FPS}, expected {CONTENT_FRAMES}")
    if SEGMENT_SECONDS * AUDIO_SR != AUDIO_SAMPLES:
        failures.append(
            f"SEGMENT_SECONDS*AUDIO_SR={SEGMENT_SECONDS * AUDIO_SR}, expected {AUDIO_SAMPLES}"
        )
    if AUDIO_SAMPLES / AUDIO_SR != SEGMENT_SECONDS:
        failures.append("AUDIO_SAMPLES/AUDIO_SR != SEGMENT_SECONDS")
    if ONSET_GRID_SECONDS * FPS != int(ONSET_GRID_SECONDS * FPS):
        failures.append(f"ONSET_GRID_SECONDS={ONSET_GRID_SECONDS} is not frame aligned")
    for k in range(-48, 49):
        t = k * ONSET_GRID_SECONDS
        err = onset_quantization_error(t)
        if err >= QUANTIZATION_TOLERANCE:
            failures.append(f"onset t={t!r} quantization error {err!r}")
            break
    return failures


def selftest():
    failures = contract_failures()
    print(f"timebase: fps={FPS} content={CONTENT_FRAMES} gate={GATE_FRAMES} "
          f"total={TOTAL_FRAMES} audio={AUDIO_SAMPLES}@{AUDIO_SR} "
          f"segment={SEGMENT_SECONDS}s grid={ONSET_GRID_SECONDS}s")
    print(f"[{'PASS' if not failures else 'FAIL'}] time contract self-check")
    for f in failures:
        print(f"       {f}")
    return 1 if failures else 0


def main(argv=None):
    ap = argparse.ArgumentParser(description="issue #110 fragment time contract")
    ap.add_argument("--selftest", action="store_true", help="run contract self-check")
    args = ap.parse_args(argv)
    if args.selftest:
        return selftest()
    ap.error("choose --selftest")
    return 2


if __name__ == "__main__":
    sys.exit(main())
