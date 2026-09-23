#!/usr/bin/env python3
"""Seam test for Musikalisches fragment concatenation (issue #93).

Draws --random-pairs random (i, j) fragment pairs from --fragments-dir and measures
the pixel discontinuity at the seam: the mean absolute RGBA difference (0..255
scale, alpha included) between the last frame of i and the first frame of j.

Threshold rationale (also emitted into the report):
  A valid fixture has fully transparent gate frames, i.e. canonical transparent
  black (0,0,0,0) on both sides of the seam, so the seam metric is exactly 0.0.
  A broken gate -- an opaque tail meeting a transparent head, or two unrelated
  opaque frames meeting -- scores in the tens to hundreds. The default threshold
  of 2.0 (0.8% of full scale) sits far above any 8-bit encode noise on a real
  render and far below a genuine jump, so it cannot false-positive on a
  deterministic fixture while still catching a real discontinuity.
  To prove the metric is not vacuous, the same measurement is also run on
  adjacent frames *inside* each sampled fragment; that control value must exceed
  the seam threshold or the run fails, so a pass never rests on a dead metric.

Usage:
  concat_test.py --fragments-dir DIR [--random-pairs 20] [--seed 93]
                 [--output test_report.json] [--seam-threshold 2.0] [--threshold 0.05]
"""
from __future__ import annotations

import argparse
import json
import random
import sys
from pathlib import Path

from neutral_frame_check import (
    EXPECTED_FRAGMENTS,
    check_fragments,
    frame_paths,
    fragment_dirs,
    read_png,
)

DEFAULT_SEED = 93
DEFAULT_PAIRS = 20
DEFAULT_SEAM_THRESHOLD = 2.0


def mean_abs_rgba_diff(left: bytes, right: bytes) -> float:
    """Mean absolute difference over all RGBA bytes, on a 0..255 scale."""
    if len(left) != len(right):
        raise ValueError(f"frame size mismatch: {len(left)} vs {len(right)} bytes")
    if not left:
        return 0.0
    return sum(abs(a - b) for a, b in zip(left, right)) / len(left)


def max_internal_adjacent_diff(frames: list[Path]) -> float:
    """Largest adjacent-frame difference inside one fragment (sensitivity control)."""
    worst = 0.0
    previous = None
    for path in frames:
        _, _, rgba = read_png(path)
        if previous is not None:
            worst = max(worst, mean_abs_rgba_diff(previous, rgba))
        previous = rgba
    return worst


def run(root: Path, pairs: int, seed: int, seam_threshold: float, alpha_threshold: float) -> dict:
    neutral = check_fragments(root, alpha_threshold)

    fragments = fragment_dirs(root)
    rng = random.Random(seed)
    sampled: list[tuple[int, int]] = []
    while len(sampled) < pairs:
        left = rng.randrange(1, EXPECTED_FRAGMENTS + 1)
        right = rng.randrange(1, EXPECTED_FRAGMENTS + 1)
        if left != right:
            sampled.append((left, right))

    seam_results = []
    for left, right in sampled:
        left_frames = frame_paths(fragments[left])
        right_frames = frame_paths(fragments[right])
        _, _, tail_rgba = read_png(left_frames[-1])
        _, _, head_rgba = read_png(right_frames[0])
        seam_results.append(
            {
                "from": left,
                "to": right,
                "from_frame": left_frames[-1].name,
                "to_frame": right_frames[0].name,
                "mean_abs_rgba_diff": mean_abs_rgba_diff(tail_rgba, head_rgba),
            }
        )

    # Control: same metric on adjacent frames inside the sampled fragments, so a
    # passing seam cannot be an artifact of a metric that always reads zero.
    control_fragments = sorted({fid for pair in sampled for fid in pair})
    internal_max = 0.0
    for fid in control_fragments:
        internal_max = max(internal_max, max_internal_adjacent_diff(frame_paths(fragments[fid])))

    seam_max = max((item["mean_abs_rgba_diff"] for item in seam_results), default=0.0)
    seam_pass = seam_max <= seam_threshold
    control_pass = internal_max > seam_threshold

    failures = []
    if not neutral["pass"]:
        failures.append("neutral frame gate failed")
    if not seam_pass:
        failures.append(f"seam diff {seam_max:.6f} exceeds threshold {seam_threshold}")
    if not control_pass:
        failures.append(
            f"internal adjacent-frame diff {internal_max:.6f} does not exceed threshold "
            f"{seam_threshold}; metric is not sensitive, result would be vacuous"
        )

    return {
        "issue": 93,
        "pass": not failures,
        "failures": failures,
        "fragments_checked": neutral["fragments_checked"],
        "fragments_expected": EXPECTED_FRAGMENTS,
        "pairs": len(seam_results),
        "seed": seed,
        "fragments_dir": str(root),
        "thresholds": {
            "gate_alpha": alpha_threshold,
            "seam_mean_abs_rgba_diff": seam_threshold,
        },
        "measured": {
            "max_alpha_head": neutral["max_alpha_head"],
            "max_alpha_tail": neutral["max_alpha_tail"],
            "seam_diff_max": seam_max,
            "internal_adjacent_diff_max": internal_max,
        },
        "neutral_frame_check": neutral,
        "seam_pairs": seam_results,
        "rationale": (
            "Seam metric is the mean absolute RGBA difference (0..255, alpha included) "
            "between the last frame of fragment i and the first frame of fragment j. "
            "Valid transparent gates give exactly 0.0; a broken gate scores in the tens "
            "to hundreds. Threshold 2.0 (0.8% of full scale) clears 8-bit encode noise on "
            "real renders and stays far below any genuine jump. internal_adjacent_diff_max "
            "is the same metric applied inside fragments and must exceed the threshold, "
            "so a pass is never an empty assertion."
        ),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--fragments-dir", type=Path, required=True, help="directory holding fragment_NNN/ frame sequences")
    parser.add_argument("--random-pairs", type=int, default=DEFAULT_PAIRS, help="number of random (i, j) pairs to test")
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED, help="RNG seed, fixed by default so reruns are deterministic")
    parser.add_argument("--output", type=Path, default=Path("test_report.json"), help="where to write the JSON report")
    parser.add_argument("--seam-threshold", type=float, default=DEFAULT_SEAM_THRESHOLD, help="max allowed mean abs RGBA diff at a seam")
    parser.add_argument("--threshold", type=float, default=0.05, help="max allowed normalized alpha in a gate frame")
    args = parser.parse_args(argv)

    report = run(args.fragments_dir, args.random_pairs, args.seed, args.seam_threshold, args.threshold)

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    print(f"concat seam test: {report['pairs']} pair(s) over {report['fragments_checked']} fragment(s)")
    print(f"seam diff max: {report['measured']['seam_diff_max']:.6f} (threshold {args.seam_threshold})")
    print(f"internal adjacent-frame diff max: {report['measured']['internal_adjacent_diff_max']:.6f} (control)")
    print(f"report: {args.output}")
    if report["pass"]:
        print("concat seam test PASS")
        return 0
    for failure in report["failures"]:
        print(f"FAIL {failure}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
