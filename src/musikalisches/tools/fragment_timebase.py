#!/usr/bin/env python3
"""Issue #110 (83-R1) fragment time contract — single source of truth.

Decisions D1/D2 (CTO authorized; D1 revised 2026-09-24 to 90 BPM after an
A/B listening sample: 90 BPM reads more stately, so the whole pipeline is
re-based on 1.0 s fragments):
  * 24 fps timeline.
  * 24 content frames per fragment == 1.0 s of content (3/8 measure @ 90 BPM).
  * 5 fully transparent gate frames at head and tail -> 34 frames per fragment.
  * audio 1.0 s == 44100 samples @ 44100 Hz.
  * onset grid 1/6 s (16th note @ 90 BPM == 4 frames @ 24 fps, exact).
  * ``round(t * FPS)`` must stay within QUANTIZATION_TOLERANCE for every
    onset of the 11 source rolls. Tolerance is 1e-4 frames (~4 µs), not
    exact, because note_event_sequence.json serializes start_seconds to 6
    decimals (worst observed 8e-6 frames at 90 BPM); one frame is 41.7 ms,
    so this is visually zero. The 120 BPM data happened to serialize with
    zero error only because its grid is dyadic (0.125 s).

Every other tool in this lane imports the constants from here instead of
re-deriving them.
"""

import argparse
import sys

FPS = 24
CONTENT_FRAMES = 24
GATE_FRAMES = 5
TOTAL_FRAMES = CONTENT_FRAMES + 2 * GATE_FRAMES  # 34
AUDIO_SR = 44100
AUDIO_SAMPLES = 44100
SEGMENT_SECONDS = 1.0
ONSET_GRID_SECONDS = 1.0 / 6.0  # 16th note @ 90 bpm == 4 frames @ 24 fps
QUANTIZATION_TOLERANCE = 1e-4  # frames; see module docstring


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
    if TOTAL_FRAMES != CONTENT_FRAMES + 2 * GATE_FRAMES:
        failures.append("CONTENT_FRAMES + 2*GATE_FRAMES != TOTAL_FRAMES")
    if SEGMENT_SECONDS * FPS != CONTENT_FRAMES:
        failures.append(f"SEGMENT_SECONDS*FPS={SEGMENT_SECONDS * FPS}, expected {CONTENT_FRAMES}")
    if SEGMENT_SECONDS * AUDIO_SR != AUDIO_SAMPLES:
        failures.append(
            f"SEGMENT_SECONDS*AUDIO_SR={SEGMENT_SECONDS * AUDIO_SR}, expected {AUDIO_SAMPLES}"
        )
    if AUDIO_SAMPLES / AUDIO_SR != SEGMENT_SECONDS:
        failures.append("AUDIO_SAMPLES/AUDIO_SR != SEGMENT_SECONDS")
    grid_frames = ONSET_GRID_SECONDS * FPS
    if grid_frames != int(grid_frames):
        failures.append(f"ONSET_GRID_SECONDS={ONSET_GRID_SECONDS} is not frame aligned")
    for k in range(-96, 97):
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
          f"segment={SEGMENT_SECONDS}s grid={ONSET_GRID_SECONDS:.6f}s "
          f"tol={QUANTIZATION_TOLERANCE}f")
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
