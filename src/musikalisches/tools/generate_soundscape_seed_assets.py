#!/usr/bin/env python3

from __future__ import annotations

import hashlib
import json
import math
import wave
from array import array
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
ASSET_ROOT = ROOT / "ops" / "assets" / "soundscapes"
AMBIENT_DIR = ASSET_ROOT / "ambient"
DRONE_DIR = ASSET_ROOT / "drone"
IMPULSE_DIR = ASSET_ROOT / "impulse"
MANIFEST_DIR = ASSET_ROOT / "manifests"
SAMPLE_RATE = 24_000
SAMPLE_WIDTH_BYTES = 2
CHANNELS = 2
REPO_BLOB_ROOT = "https://github.com/41490/chao5whistler/blob/main"
GENERATOR_PATH = "src/musikalisches/tools/generate_soundscape_seed_assets.py"
PACK_ID = "musikalisches_seed_soundscape_v1"
PACK_VERSION = 1


def ensure_directories() -> None:
    for path in (AMBIENT_DIR, DRONE_DIR, IMPULSE_DIR, MANIFEST_DIR):
        path.mkdir(parents=True, exist_ok=True)


def clamp_sample(value: float) -> int:
    return max(-32767, min(32767, int(round(value * 32767.0))))


def write_wav(path: Path, duration_seconds: float, sampler) -> dict:
    total_frames = int(round(duration_seconds * SAMPLE_RATE))
    pcm = array("h")
    peak = 0
    rms_accumulator = 0.0
    for frame_index in range(total_frames):
        left, right = sampler(frame_index / SAMPLE_RATE)
        left_i = clamp_sample(left)
        right_i = clamp_sample(right)
        peak = max(peak, abs(left_i), abs(right_i))
        rms_accumulator += float(left_i * left_i + right_i * right_i)
        pcm.extend((left_i, right_i))

    with wave.open(str(path), "wb") as wav_file:
        wav_file.setnchannels(CHANNELS)
        wav_file.setsampwidth(SAMPLE_WIDTH_BYTES)
        wav_file.setframerate(SAMPLE_RATE)
        wav_file.writeframes(pcm.tobytes())

    rms = math.sqrt(rms_accumulator / max(total_frames * CHANNELS, 1))
    peak_dbfs = 20.0 * math.log10(max(peak / 32767.0, 1e-9))
    rms_dbfs = 20.0 * math.log10(max(rms / 32767.0, 1e-9))
    return {
        "duration_seconds": round(total_frames / SAMPLE_RATE, 6),
        "sample_rate": SAMPLE_RATE,
        "channels": CHANNELS,
        "sample_format": "pcm_s16le",
        "peak_dbfs": round(peak_dbfs, 2),
        "rms_dbfs": round(rms_dbfs, 2),
    }


def sha256_hex(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def ambient_sampler(t: float) -> tuple[float, float]:
    left = 0.0
    right = 0.0
    partials = (
        (120.0, 0.060, 0.17, 0.00),
        (180.0, 0.050, 0.11, 0.13),
        (240.0, 0.045, 0.23, 0.31),
        (360.0, 0.035, 0.07, 0.59),
        (510.0, 0.024, 0.19, 0.83),
        (720.0, 0.016, 0.29, 1.11),
    )
    for frequency, amplitude, lfo_hz, phase in partials:
        motion = 0.72 + 0.28 * math.sin(2.0 * math.pi * lfo_hz * t + phase / 2.0)
        left += amplitude * motion * math.sin(2.0 * math.pi * frequency * t + phase)
        right += amplitude * motion * math.sin(2.0 * math.pi * frequency * t + phase + 0.21)
    wash = 0.018 * math.sin(2.0 * math.pi * (7 / 24) * t)
    left += wash
    right -= wash
    return left, right


def drone_sampler(t: float) -> tuple[float, float]:
    primary = 0.18 * math.sin(2.0 * math.pi * 65.0 * t)
    fifth = 0.09 * math.sin(2.0 * math.pi * 97.5 * t + 0.12)
    octave = 0.06 * math.sin(2.0 * math.pi * 130.0 * t + 0.28)
    breath = 0.82 + 0.18 * math.sin(2.0 * math.pi * (1 / 12) * t)
    shimmer = 0.01 * math.sin(2.0 * math.pi * 260.0 * t + 0.17)
    mono = breath * (primary + fifth + octave) + shimmer
    return mono * 0.98, mono * 0.92


def relative_blob_url(path: Path) -> str:
    rel = path.relative_to(ROOT).as_posix()
    return f"{REPO_BLOB_ROOT}/{rel}"


def asset_manifest(
    *,
    asset_id: str,
    layer_kind: str,
    asset_path: Path,
    synthesis_method: str,
    loudness_target_dbfs: float,
    audio_summary: dict,
) -> dict:
    rel_asset_path = asset_path.relative_to(ROOT).as_posix()
    return {
        "asset_id": asset_id,
        "layer_kind": layer_kind,
        "asset_format": "wav",
        "asset_path": rel_asset_path,
        "source_url": relative_blob_url(asset_path),
        "license": {
            "spdx": "CC0-1.0",
            "policy_class": "CC0",
            "summary": "repo-generated seed loop released under a CC0 baseline for live-safe testing",
        },
        "attribution_required": False,
        "loop_duration_seconds": audio_summary["duration_seconds"],
        "loudness_target_dbfs": loudness_target_dbfs,
        "sha256": sha256_hex(asset_path),
        "audio": audio_summary,
        "generator": {
            "path": GENERATOR_PATH,
            "method": synthesis_method,
            "sample_rate": SAMPLE_RATE,
            "channels": CHANNELS,
        },
        "notes": [
            "Seed asset for issue9 P2 manifest/validator work.",
            "May be replaced by curated field recordings in later phases without changing the manifest contract.",
        ],
    }


def write_json(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")


def main() -> int:
    ensure_directories()

    ambient_path = AMBIENT_DIR / "ambient_chapel_air_v1.wav"
    drone_path = DRONE_DIR / "drone_c_pedal_v1.wav"

    ambient_audio = write_wav(ambient_path, 24.0, ambient_sampler)
    drone_audio = write_wav(drone_path, 12.0, drone_sampler)

    ambient_manifest = asset_manifest(
        asset_id="ambient_chapel_air_v1",
        layer_kind="ambient",
        asset_path=ambient_path,
        synthesis_method="deterministic additive pad swarm",
        loudness_target_dbfs=-24.0,
        audio_summary=ambient_audio,
    )
    drone_manifest = asset_manifest(
        asset_id="drone_c_pedal_v1",
        layer_kind="drone",
        asset_path=drone_path,
        synthesis_method="deterministic pedal-tone stack",
        loudness_target_dbfs=-20.0,
        audio_summary=drone_audio,
    )

    ambient_manifest_path = MANIFEST_DIR / "ambient_chapel_air_v1.json"
    drone_manifest_path = MANIFEST_DIR / "drone_c_pedal_v1.json"
    write_json(ambient_manifest_path, ambient_manifest)
    write_json(drone_manifest_path, drone_manifest)

    pack_manifest = {
        "stage": "soundscape_asset_pack",
        "asset_pack_id": PACK_ID,
        "asset_pack_version": PACK_VERSION,
        "asset_root": ASSET_ROOT.relative_to(ROOT).as_posix(),
        "manifest_root": MANIFEST_DIR.relative_to(ROOT).as_posix(),
        "allowed_policy_classes": [
            "CC0",
            "public_domain",
            "pixabay_no_attribution",
        ],
        "generator": {
            "path": GENERATOR_PATH,
            "description": "Generate deterministic seed soundscape assets and manifests.",
        },
        "assets": [
            {
                "asset_id": ambient_manifest["asset_id"],
                "layer_kind": ambient_manifest["layer_kind"],
                "manifest_path": ambient_manifest_path.relative_to(ROOT).as_posix(),
                "asset_path": ambient_manifest["asset_path"],
            },
            {
                "asset_id": drone_manifest["asset_id"],
                "layer_kind": drone_manifest["layer_kind"],
                "manifest_path": drone_manifest_path.relative_to(ROOT).as_posix(),
                "asset_path": drone_manifest["asset_path"],
            },
        ],
        "summary": {
            "ambient_assets": 1,
            "drone_assets": 1,
            "impulse_assets": 0,
        },
        "notes": [
            "P2 intentionally freezes a minimal pack: one ambient bed and one pedal drone.",
            "Later curated third-party assets must still satisfy the same manifest/license contract.",
        ],
    }
    write_json(MANIFEST_DIR / "soundscape_asset_pack_v1.json", pack_manifest)
    print("soundscape seed assets generated")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
