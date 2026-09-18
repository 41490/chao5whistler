#!/usr/bin/env python3
"""Pure-stdlib BS.1770-4 loudness measurement for stage5 stream artifacts.

No numpy/scipy/ffmpeg: the K-weighting filter, the gating logic, and the
clipping detector are all implemented on top of the Python standard library,
following the same style as the other ``src/musikalisches/tools`` helpers.

Measured quantities
-------------------
- ``integrated_lufs``: gated integrated loudness (400 ms blocks, 75 % overlap,
  absolute -70 LUFS gate plus the relative -10 LU gate).
- ``lufs_short_term_min`` / ``lufs_short_term_max``: 3 s sliding windows
  (100 ms hop) that clear the absolute gate. ``None`` when every window is
  silent.
- ``true_peak_dbtp``: sample-peak estimate in dBFS. This is a conservative
  estimate (no 4x oversampling), which is exactly what a WAV-domain gate
  needs: it can never report a peak lower than the rendered samples.
- ``clipping_detected``: at least one run of >= 3 consecutive full-scale
  samples. The mix bus clamps to full scale, so a run that long is a hard
  clip, not a legitimate transient.
- ``dynamic_spread_db``: p95 - p5 of 400 ms window RMS values (dBFS), over
  non-silent windows only.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
import tempfile
import wave
from array import array
from math import fsum, log10, sqrt
from pathlib import Path


LUFS_OFFSET = -0.691
ABSOLUTE_GATE_LUFS = -70.0
RELATIVE_GATE_LU = -10.0
BLOCK_SECONDS = 0.4
BLOCK_OVERLAP = 0.75
SHORT_TERM_SECONDS = 3.0
SHORT_TERM_HOP_SECONDS = 0.1
DYNAMIC_WINDOW_SECONDS = 0.4
CLIP_RUN_THRESHOLD = 3
CLIP_SAMPLE_THRESHOLD = 32766
CHANNEL_WEIGHTS = (1.0, 1.0)
FULL_SCALE = 32767.0
FULL_SCALE_SQUARED = FULL_SCALE * FULL_SCALE
MEASUREMENT_ID = "bs1770_4_kweighting_stdlib_v1"

# Analog prototype constants from ITU-R BS.1770-4 (via the libebur128
# derivation): the pre-filter is a high-shelf at ~1682 Hz and the RLB stage
# is a high-pass at ~38 Hz. Re-deriving per sample rate keeps 44.1 kHz
# artifacts correct while reproducing the published 48 kHz coefficients.
SHELF_F0 = 1681.974450955533
SHELF_GAIN_DB = 3.999843853973347
SHELF_Q = 0.7071752369554196
SHELF_VB_EXPONENT = 0.4996667741545416
HIGHPASS_F0 = 38.13547087602444
HIGHPASS_Q = 0.5003270373238773


def k_weighting_coefficients(sample_rate: int) -> tuple[tuple[tuple[float, float, float], tuple[float, float, float]], ...]:
    """Return the two cascaded biquad coefficient sets for ``sample_rate``."""
    if sample_rate <= 0:
        raise ValueError("sample_rate must be > 0")

    k = math.tan(math.pi * SHELF_F0 / sample_rate)
    vh = 10.0 ** (SHELF_GAIN_DB / 20.0)
    vb = vh**SHELF_VB_EXPONENT
    a0 = 1.0 + k / SHELF_Q + k * k
    shelf = (
        (
            (vh + vb * k / SHELF_Q + k * k) / a0,
            2.0 * (k * k - vh) / a0,
            (vh - vb * k / SHELF_Q + k * k) / a0,
        ),
        (
            1.0,
            2.0 * (k * k - 1.0) / a0,
            (1.0 - k / SHELF_Q + k * k) / a0,
        ),
    )

    k = math.tan(math.pi * HIGHPASS_F0 / sample_rate)
    a0 = 1.0 + k / HIGHPASS_Q + k * k
    high_pass = (
        (1.0, -2.0, 1.0),
        (
            1.0,
            2.0 * (k * k - 1.0) / a0,
            (1.0 - k / HIGHPASS_Q + k * k) / a0,
        ),
    )
    return (shelf, high_pass)


def k_weighted_cumulative_squares(samples: array, sample_rate: int) -> array:
    """K-weight ``samples`` and return the cumulative sum of squares.

    Both biquad stages run in transposed direct form II inside a single pass,
    so no intermediate filtered buffer is allocated: the returned cumulative
    sum is all the block and short-term windows need. Values stay in squared
    int16 units; ``_window_mean_square`` normalizes them to full scale.
    """
    (shelf_b, shelf_a), (hp_b, hp_a) = k_weighting_coefficients(sample_rate)
    b0, b1, b2 = shelf_b
    a1, a2 = shelf_a[1], shelf_a[2]
    c0, c1, c2 = hp_b
    d1, d2 = hp_a[1], hp_a[2]

    z1 = z2 = 0.0
    w1 = w2 = 0.0
    cumulative = array("d", bytes(8 * (len(samples) + 1)))
    accumulator = 0.0
    index = 1
    for sample in samples:
        stage1 = b0 * sample + z1
        z1 = b1 * sample - a1 * stage1 + z2
        z2 = b2 * sample - a2 * stage1
        stage2 = c0 * stage1 + w1
        w1 = c1 * stage1 - d1 * stage2 + w2
        w2 = c2 * stage1 - d2 * stage2
        accumulator += stage2 * stage2
        cumulative[index] = accumulator
        index += 1
    return cumulative


def _window_mean_square(cumulative: array, start: int, end: int) -> float:
    """Mean square of the K-weighted window, normalized to full scale."""
    return (cumulative[end] - cumulative[start]) / (end - start) / FULL_SCALE_SQUARED


def _window_starts(total_frames: int, window_frames: int, hop_frames: int) -> list[int]:
    if total_frames <= 0:
        return []
    if total_frames < window_frames:
        return [0]
    return list(range(0, total_frames - window_frames + 1, hop_frames))


def _power_to_lufs(power: float) -> float:
    if power <= 0.0:
        return float("-inf")
    return LUFS_OFFSET + 10.0 * log10(power)


def _weighted_power(cumulative_sums: list[array], start: int, end: int) -> float:
    return fsum(
        weight * _window_mean_square(cumulative, start, end)
        for cumulative, weight in zip(cumulative_sums, CHANNEL_WEIGHTS)
    )


def gated_integrated_lufs(block_powers: list[float]) -> tuple[float | None, int]:
    """Apply the BS.1770 absolute + relative gates to per-block powers."""
    loudness = [_power_to_lufs(power) for power in block_powers]
    above_absolute = [
        power
        for power, level in zip(block_powers, loudness)
        if level > ABSOLUTE_GATE_LUFS
    ]
    if not above_absolute:
        return None, 0
    mean_above_absolute = fsum(above_absolute) / len(above_absolute)
    relative_gate = _power_to_lufs(mean_above_absolute) + RELATIVE_GATE_LU
    gated = [
        power
        for power, level in zip(block_powers, loudness)
        if level > ABSOLUTE_GATE_LUFS and level > relative_gate
    ]
    if not gated:
        return None, 0
    return _power_to_lufs(fsum(gated) / len(gated)), len(gated)


def detect_clipping(pcm: array) -> dict:
    longest_run = 0
    current_run = 0
    clipped_samples = 0
    for sample in pcm:
        if sample >= CLIP_SAMPLE_THRESHOLD or sample <= -CLIP_SAMPLE_THRESHOLD:
            current_run += 1
            clipped_samples += 1
            if current_run > longest_run:
                longest_run = current_run
        else:
            current_run = 0
    return {
        "clipping_detected": longest_run >= CLIP_RUN_THRESHOLD,
        "longest_clip_run_samples": longest_run,
        "clipped_sample_count": clipped_samples,
    }


def dynamic_spread_db(pcm: array, *, channels: int, sample_rate: int) -> float | None:
    window_frames = max(1, int(round(DYNAMIC_WINDOW_SECONDS * sample_rate)))
    frame_count = len(pcm) // channels
    levels: list[float] = []
    for start in range(0, frame_count, window_frames):
        end = min(start + window_frames, frame_count)
        chunk = pcm[start * channels : end * channels]
        if not chunk:
            continue
        power = fsum(float(sample) * float(sample) for sample in chunk) / len(chunk)
        if power <= 0.0:
            continue
        levels.append(20.0 * log10(sqrt(power) / FULL_SCALE))
    if len(levels) < 2:
        return None
    levels.sort()
    low = levels[int(round(0.05 * (len(levels) - 1)))]
    high = levels[int(round(0.95 * (len(levels) - 1)))]
    return high - low


def measure_pcm(pcm: array, *, sample_rate: int, channels: int) -> dict:
    if channels <= 0:
        raise ValueError("channels must be > 0")
    if len(pcm) % channels != 0:
        raise ValueError("PCM buffer length must be a multiple of the channel count")
    frame_count = len(pcm) // channels
    result = {
        "measurement": MEASUREMENT_ID,
        "sample_rate": sample_rate,
        "channels": channels,
        "frames": frame_count,
        "duration_seconds": round(frame_count / sample_rate, 6) if sample_rate else 0.0,
        "integrated_lufs": None,
        "lufs_short_term_min": None,
        "lufs_short_term_max": None,
        "true_peak_dbtp": None,
        "peak_dbfs": None,
        "clipping_detected": False,
        "longest_clip_run_samples": 0,
        "clipped_sample_count": 0,
        "dynamic_spread_db": None,
        "block_count": 0,
        "gated_block_count": 0,
        "short_term_window_count": 0,
    }
    if frame_count == 0:
        return result

    peak_value = max(abs(sample) for sample in pcm)
    peak_amplitude = peak_value / FULL_SCALE
    result["peak_dbfs"] = round(20.0 * log10(peak_amplitude), 3) if peak_amplitude > 0 else -180.0
    result["true_peak_dbtp"] = result["peak_dbfs"]
    result.update(detect_clipping(pcm))
    spread = dynamic_spread_db(pcm, channels=channels, sample_rate=sample_rate)
    result["dynamic_spread_db"] = round(spread, 3) if spread is not None else None

    channel_sums = [
        k_weighted_cumulative_squares(pcm[channel::channels], sample_rate)
        for channel in range(channels)
    ]

    block_frames = max(1, int(round(BLOCK_SECONDS * sample_rate)))
    block_hop = max(1, int(round(block_frames * (1.0 - BLOCK_OVERLAP))))
    block_starts = _window_starts(frame_count, block_frames, block_hop)
    block_powers = [
        _weighted_power(channel_sums, start, min(start + block_frames, frame_count))
        for start in block_starts
    ]
    integrated, gated_count = gated_integrated_lufs(block_powers)
    result["block_count"] = len(block_powers)
    result["gated_block_count"] = gated_count
    result["integrated_lufs"] = round(integrated, 3) if integrated is not None else None

    short_term_frames = max(1, int(round(SHORT_TERM_SECONDS * sample_rate)))
    short_term_hop = max(1, int(round(SHORT_TERM_HOP_SECONDS * sample_rate)))
    short_term_starts = _window_starts(frame_count, short_term_frames, short_term_hop)
    short_term_levels = []
    for start in short_term_starts:
        power = _weighted_power(channel_sums, start, min(start + short_term_frames, frame_count))
        level = _power_to_lufs(power)
        if level > ABSOLUTE_GATE_LUFS:
            short_term_levels.append(level)
    result["short_term_window_count"] = len(short_term_levels)
    if short_term_levels:
        result["lufs_short_term_min"] = round(min(short_term_levels), 3)
        result["lufs_short_term_max"] = round(max(short_term_levels), 3)
    return result


def read_wav_pcm(path: Path) -> dict:
    with wave.open(str(path), "rb") as wav_file:
        channels = wav_file.getnchannels()
        sample_width = wav_file.getsampwidth()
        sample_rate = wav_file.getframerate()
        frame_count = wav_file.getnframes()
        pcm_bytes = wav_file.readframes(frame_count)
    if sample_width != 2:
        raise SystemExit(f"loudness_meter expects 16-bit PCM WAV: {path}")
    if channels not in (1, 2):
        raise SystemExit(f"loudness_meter expects mono or stereo WAV: {path}")
    pcm = array("h")
    pcm.frombytes(pcm_bytes)
    if sys.byteorder != "little":
        pcm.byteswap()
    return {
        "sample_rate": sample_rate,
        "channels": channels,
        "frame_count": frame_count,
        "pcm": pcm,
    }


def measure_wav(path: Path) -> dict:
    audio = read_wav_pcm(path)
    measured = measure_pcm(audio["pcm"], sample_rate=audio["sample_rate"], channels=audio["channels"])
    measured["path"] = str(path)
    return measured


def write_wav_pcm(path: Path, *, sample_rate: int, channels: int, pcm: array) -> None:
    with wave.open(str(path), "wb") as wav_file:
        wav_file.setnchannels(channels)
        wav_file.setsampwidth(2)
        wav_file.setframerate(sample_rate)
        wav_file.writeframes(pcm.tobytes())


def _sine_pcm(
    *,
    frequency: float,
    peak_amplitude: float,
    seconds: float,
    sample_rate: int,
    channels: int = 1,
) -> array:
    """Full-scale sine, hard-clamped so peak_amplitude > 1.0 produces clips."""
    pcm = array("h")
    frame_count = int(round(seconds * sample_rate))
    for index in range(frame_count):
        value = int(round(peak_amplitude * math.sin(2.0 * math.pi * frequency * index / sample_rate) * FULL_SCALE))
        value = max(-32767, min(32767, value))
        for _ in range(channels):
            pcm.append(value)
    return pcm


def self_test() -> int:
    """Self-check: 1 kHz calibration, silence gating, and clip detection."""
    failures: list[str] = []
    sample_rate = 48_000
    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir)

        tone_path = tmp_path / "tone.wav"
        write_wav_pcm(
            tone_path,
            sample_rate=sample_rate,
            channels=1,
            pcm=_sine_pcm(
                frequency=1000.0,
                peak_amplitude=0.1 * math.sqrt(2.0),
                seconds=5.0,
                sample_rate=sample_rate,
            ),
        )
        tone = measure_wav(tone_path)
        if tone["integrated_lufs"] is None or abs(tone["integrated_lufs"] + 20.0) > 0.3:
            failures.append(
                f"1 kHz -20 dBFS RMS calibration out of range: integrated_lufs={tone['integrated_lufs']} (want -20.0 +/- 0.3)"
            )
        if tone["clipping_detected"]:
            failures.append("a -20 dBFS sine must not be reported as clipped")

        gated_path = tmp_path / "silence_then_tone.wav"
        write_wav_pcm(
            gated_path,
            sample_rate=sample_rate,
            channels=1,
            pcm=array("h", [0] * (2 * sample_rate))
            + _sine_pcm(
                frequency=1000.0,
                peak_amplitude=0.1 * math.sqrt(2.0),
                seconds=3.0,
                sample_rate=sample_rate,
            ),
        )
        gated = measure_wav(gated_path)
        if gated["integrated_lufs"] is None or gated["integrated_lufs"] <= -21.0:
            failures.append(
                f"silent blocks leaked into gating: integrated_lufs={gated['integrated_lufs']} (want > -21.0)"
            )
        if gated["gated_block_count"] >= gated["block_count"]:
            failures.append(
                "silent blocks must be excluded by the gate: "
                f"gated_block_count={gated['gated_block_count']} block_count={gated['block_count']}"
            )
        if gated["lufs_short_term_min"] is None or gated["lufs_short_term_min"] <= -25.0:
            failures.append(
                f"short-term floor must ignore silent windows: lufs_short_term_min={gated['lufs_short_term_min']}"
            )

        clipped_path = tmp_path / "clipped.wav"
        write_wav_pcm(
            clipped_path,
            sample_rate=sample_rate,
            channels=2,
            pcm=_sine_pcm(
                frequency=100.0,
                peak_amplitude=1.5,
                seconds=1.0,
                sample_rate=sample_rate,
                channels=2,
            ),
        )
        clipped = measure_wav(clipped_path)
        if not clipped["clipping_detected"]:
            failures.append(
                "clamped 1.5x sine must be flagged as clipped: "
                f"longest_clip_run_samples={clipped['longest_clip_run_samples']}"
            )
        if clipped["true_peak_dbtp"] is None or clipped["true_peak_dbtp"] < -0.01:
            failures.append(f"clipped peak estimate must sit at full scale: true_peak_dbtp={clipped['true_peak_dbtp']}")

    if failures:
        print("loudness_meter self-test failed:")
        for failure in failures:
            print(f"- {failure}")
        return 1
    print("loudness_meter self-test passed")
    print(f"calibration: 1 kHz -20 dBFS RMS -> {tone['integrated_lufs']} LUFS")
    print(
        "gating: "
        f"gated_block_count={gated['gated_block_count']}/{gated['block_count']}, "
        f"lufs_short_term_min={gated['lufs_short_term_min']}"
    )
    print(f"clipping: longest_clip_run_samples={clipped['longest_clip_run_samples']}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Measure BS.1770-4 loudness of a 16-bit PCM WAV.")
    parser.add_argument("wav_path", nargs="?", help="16-bit PCM WAV file to measure")
    parser.add_argument("--self-test", action="store_true", help="run the built-in calibration self-test")
    args = parser.parse_args()

    if args.self_test:
        return self_test()
    if not args.wav_path:
        parser.error("provide a WAV path or --self-test")
    wav_path = Path(args.wav_path).resolve()
    if not wav_path.exists():
        print(f"wav does not exist: {wav_path}", file=sys.stderr)
        return 1
    print(json.dumps(measure_wav(wav_path), indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
