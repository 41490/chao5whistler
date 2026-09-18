#!/usr/bin/env python3
"""Fake stage5/stage6 renderer for weaver end-to-end tests.

This is a test fixture, not a production tool. It emits the same artifact
*filenames* the real stage5/stage6 tools emit, with deterministic filler bytes,
so the weaver's adapter, publish and ledger paths can be exercised in seconds
instead of minutes. It deliberately mirrors one real contract: the stage5 stage
is the combination allocator, so it appends to the combination ledger it is
handed and the weaver reads the allocated id back from
`combination_selection.json`.
"""

from __future__ import annotations

import argparse
import json
import math
import struct
import sys
import time
import wave
from pathlib import Path

WORK_ID = "mozart_dicegame_print_1790s"
POSITION_COUNT = 16
DIGIT_BASE = 11
DIGIT_OFFSET = 2


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=True, indent=2) + "\n", encoding="utf-8")


def combination_digits_for_index(index: int) -> list[int]:
    digits = []
    value = index
    for _ in range(POSITION_COUNT):
        digits.append(DIGIT_OFFSET + (value % DIGIT_BASE))
        value //= DIGIT_BASE
    return digits


def combination_id_for_index(index: int) -> str:
    return ",".join(str(digit) for digit in combination_digits_for_index(index))


def load_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise SystemExit(f"fake render: cannot read {path}: {error}") from error


def next_index(ledger_path: Path) -> int:
    if not ledger_path.exists():
        return 0
    payload = load_json(ledger_path)
    return len(payload.get("entries", []))


def write_silence(path: Path, duration_seconds: float, sample_rate: int = 44_100) -> int:
    frames = max(1, math.ceil(duration_seconds * sample_rate))
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(2)
        handle.setsampwidth(2)
        handle.setframerate(sample_rate)
        handle.writeframes(b"\x00\x00\x00\x00" * frames)
    return frames


def render_stage5(args: argparse.Namespace) -> int:
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    ledger_path = Path(args.combination_ledger)
    index = next_index(ledger_path)
    rolls = combination_digits_for_index(index)
    combination_id = ",".join(str(digit) for digit in rolls)
    frames = write_silence(output_dir / "offline_audio.wav", args.duration_seconds)

    write_json(
        output_dir / "combination_selection.json",
        {
            "work_id": args.work_id,
            "selection_mode": "unique_random_persistent_ledger",
            "combination_id": combination_id,
            "rolls": rolls,
            "played_unique_count": index + 1,
            "is_replayed": False,
            "ledger_path": str(ledger_path),
            "render_backend": "fake_weaver_render",
        },
    )
    write_json(
        output_dir / "stream_loop_plan.json",
        {
            "work_id": args.work_id,
            "loop_count": 1,
            "cycle_duration_seconds": round(args.duration_seconds, 6),
            "total_duration_seconds": round(args.duration_seconds, 6),
            "total_duration_frames": frames,
        },
    )
    write_json(
        output_dir / "artifact_summary.json",
        {
            "work_id": args.work_id,
            "audio": {
                "path": "offline_audio.wav",
                "render_backend": "fake_weaver_render",
                "duration_seconds": round(args.duration_seconds, 6),
                "frames": frames,
            },
        },
    )
    write_json(
        output_dir / "soundscape_selection.json",
        {"stage": "stage5_soundscape_selection", "combination_id": combination_id},
    )

    ledger = (
        load_json(ledger_path)
        if ledger_path.exists()
        else {"stage": "stage5_unique_combination_ledger", "entries": []}
    )
    ledger.setdefault("entries", []).append(
        {"combination_id": combination_id, "rolls": rolls, "recorded_at": "fake"}
    )
    ledger["played_unique_count"] = len(ledger["entries"])
    write_json(ledger_path, ledger)
    print(f"fake stage5 combination_id: {combination_id}")
    return 0


def render_stage6(args: argparse.Namespace) -> int:
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    frame_count = max(1, math.ceil(args.duration_seconds * 30))
    write_json(
        output_dir / "video_render_manifest.json",
        {
            "stage": "stage6_video_render",
            "fps": 30,
            "frame_count": frame_count,
            "duration_seconds": round(args.duration_seconds, 6),
            "render_backend": "fake_weaver_render",
        },
    )
    # Not a real mp4: the fake bridge only verifies digests, and the dry-run
    # adapter keeps the real stage6 renderer.
    (output_dir / "offline_preview.mp4").write_bytes(
        b"FAKEMP4" + struct.pack("<I", frame_count)
    )
    print(f"fake stage6 frames: {frame_count}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Fake stage5/stage6 renderer for weaver tests.")
    parser.add_argument("--stage", choices=("stage5", "stage6"), required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--work-id", default=WORK_ID)
    parser.add_argument("--duration-seconds", type=float, default=0.5)
    parser.add_argument(
        "--combination-ledger",
        default="",
        help="stage5 combination ledger to append to (stage5 only)",
    )
    parser.add_argument(
        "--sleep-seconds",
        type=float,
        default=0.0,
        help="artificial render latency, used to force a cannot-sustain-live verdict",
    )
    parser.add_argument(
        "--fail-first",
        type=int,
        default=0,
        help="fail the first N invocations, counted in --fail-state (retry-log test hook)",
    )
    parser.add_argument(
        "--fail-state",
        default="",
        help="counter file used by --fail-first",
    )
    args = parser.parse_args()

    if args.fail_first > 0:
        if not args.fail_state:
            print("--fail-state is required with --fail-first", file=sys.stderr)
            return 2
        state_path = Path(args.fail_state)
        state_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            seen = int(state_path.read_text().strip())
        except (OSError, ValueError):
            seen = 0
        seen += 1
        state_path.write_text(f"{seen}\n")
        if seen <= args.fail_first:
            print(f"fake {args.stage} failure {seen}/{args.fail_first}", file=sys.stderr)
            return 1

    if args.sleep_seconds > 0:
        time.sleep(args.sleep_seconds)
    if args.stage == "stage5":
        if not args.combination_ledger:
            print("--combination-ledger is required for --stage stage5", file=sys.stderr)
            return 2
        return render_stage5(args)
    return render_stage6(args)


if __name__ == "__main__":
    raise SystemExit(main())
