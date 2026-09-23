#!/usr/bin/env python3
"""Offline audio driver for live-stream animation sync.

Buffers audio into memory and maps playback position -> animation frame index.
Designed for the streaming animation pipeline (canvas 1280x720 @ 30fps).

Acceptance:
    python3 audio_driver.py --audio ops/out/stream-smoke/offline_audio.wav \
        --duration 60 --output test_audio.json
"""
from __future__ import annotations

import argparse
import json
import struct
import sys
import time
import wave
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

CANVAS_FPS = 30
DEFAULT_BUFFER_SECONDS = 60


@dataclass
class FrameMapping:
    """One entry: an audio time maps to an animation frame index."""
    audio_seconds: float
    frame_index: int
    sample_offset: int


@dataclass
class AudioDriverResult:
    """Result of loading and buffering the offline audio."""
    audio_path: str
    actual_duration_seconds: float
    requested_buffer_seconds: float
    buffered_seconds: float
    total_samples: int
    sample_rate: int
    channels: int
    sample_width_bytes: int
    frame_fps: int
    frame_count: int
    mappings: list[dict[str, Any]] = field(default_factory=list)
    warmup_elapsed_seconds: float = 0.0
    note: str = ""


def read_wav(path: Path) -> tuple[bytes, wave.Wave_read]:
    """Open WAV and return raw frames + metadata."""
    wf = wave.open(str(path), "rb")
    frames = wf.readframes(wf.getnframes())
    return frames, wf


def buffer_seconds(wf: wave.Wave_read, requested_seconds: float) -> tuple[bytes, int]:
    """Read up to requested_seconds worth of frames from WAV."""
    total_frames = wf.getnframes()
    desired_frames = int(requested_seconds * wf.getframerate())
    frames_to_read = min(total_frames, desired_frames)
    frames = wf.readframes(frames_to_read)
    return frames, frames_to_read


def build_frame_mapping(
    sample_rate: int,
    frames_read: int,
    fps: int = CANVAS_FPS,
    max_entries: int = 1200,
) -> list[dict[str, Any]]:
    """Map audio playback positions to animation frame indices.

    Entry spacing: one mapping per animation frame (every 1/fps seconds).
    """
    duration = frames_read / sample_rate if sample_rate > 0 else 0.0
    total_animation_frames = max(1, int(duration * fps))

    mappings: list[dict[str, Any]] = []
    step = max(1, total_animation_frames // max_entries) if total_animation_frames > max_entries else 1
    for frame_index in range(0, total_animation_frames, step):
        audio_seconds = frame_index / fps
        sample_offset = int(audio_seconds * sample_rate)
        if sample_offset > frames_read:
            break
        mappings.append(
            {
                "audio_seconds": round(audio_seconds, 6),
                "frame_index": frame_index,
                "sample_offset": sample_offset,
            }
        )
    return mappings


def load_and_buffer(audio_path: Path, buffer_seconds_requested: float) -> AudioDriverResult:
    """Open WAV, buffer audio, return structured result."""
    start = time.monotonic()
    if not audio_path.exists():
        raise FileNotFoundError(f"audio file not found: {audio_path}")

    frames, wf = read_wav(audio_path)
    sample_rate = wf.getframerate()
    channels = wf.getnchannels()
    sample_width = wf.getsampwidth()
    total_samples = wf.getnframes()
    actual_duration = total_samples / sample_rate if sample_rate > 0 else 0.0

    buffered_frames, actual_read = buffer_seconds(wf, buffer_seconds_requested)
    buffered_duration = actual_read / sample_rate if sample_rate > 0 else 0.0

    mappings = build_frame_mapping(sample_rate, actual_read, CANVAS_FPS)

    elapsed = time.monotonic() - start
    note = ""
    if actual_read < total_samples:
        note = (
            f"Requested buffer {buffer_seconds_requested}s but audio is only "
            f"{actual_duration:.3f}s; buffered {buffered_duration:.3f}s."
        )

    wf.close()

    return AudioDriverResult(
        audio_path=str(audio_path),
        actual_duration_seconds=round(actual_duration, 6),
        requested_buffer_seconds=buffer_seconds_requested,
        buffered_seconds=round(buffered_duration, 6),
        total_samples=total_samples,
        sample_rate=sample_rate,
        channels=channels,
        sample_width_bytes=sample_width,
        frame_fps=CANVAS_FPS,
        frame_count=len(mappings),
        mappings=mappings,
        warmup_elapsed_seconds=round(elapsed, 6),
        note=note,
    )


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--audio", required=True, help="Path to offline .wav file for buffering."
    )
    parser.add_argument(
        "--duration",
        type=float,
        default=DEFAULT_BUFFER_SECONDS,
        help="Requested buffer duration in seconds (default: 60).",
    )
    parser.add_argument(
        "--output", required=True, help="Path to output JSON file."
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)
    audio_path = Path(args.audio)
    output_path = Path(args.output)

    result = load_and_buffer(audio_path, args.duration)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(asdict(result), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    print(
        f"Loaded {result.audio_path}: "
        f"{result.buffered_seconds}s buffered / "
        f"{result.frame_count} frame mappings "
        f"(warmup {result.warmup_elapsed_seconds:.4f}s). "
        f"Output: {output_path}"
    )
    if result.note:
        print(f"Note: {result.note}")


if __name__ == "__main__":
    main()
