#!/usr/bin/env python3

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import wave
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
DEFAULT_PACK_MANIFEST = ROOT / "ops" / "assets" / "soundscapes" / "manifests" / "soundscape_asset_pack_v1.json"
EXPECTED_STAGE = "soundscape_asset_pack"
REQUIRED_LAYER_KINDS = {"ambient", "drone"}
ALLOWED_LAYER_KINDS = {"ambient", "drone", "impulse"}
REQUIRED_ASSET_FIELDS = {
    "asset_id",
    "layer_kind",
    "asset_format",
    "asset_path",
    "source_url",
    "license",
    "attribution_required",
    "loop_duration_seconds",
    "loudness_target_dbfs",
    "sha256",
}


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def sha256_hex(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_report(report_path: Path, payload: dict) -> None:
    report_path.write_text(json.dumps(payload, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")


def fail(report_path: Path, errors: list[str], summary: dict) -> int:
    payload = {
        "stage": EXPECTED_STAGE,
        "status": "failed",
        "summary": summary,
        "errors": errors,
    }
    write_report(report_path, payload)
    print("soundscape asset validation failed:")
    for error in errors:
        print(f"- {error}")
    return 1


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Validate the issue9 P2 soundscape asset pack and per-asset manifests."
    )
    parser.add_argument(
        "--pack-manifest",
        default=str(DEFAULT_PACK_MANIFEST),
        help="path to soundscape_asset_pack_v1.json",
    )
    parser.add_argument(
        "--report-path",
        default="",
        help="optional report path; defaults next to the pack manifest",
    )
    args = parser.parse_args()

    pack_manifest_path = Path(args.pack_manifest).resolve()
    report_path = Path(args.report_path).resolve() if args.report_path else pack_manifest_path.parent / "soundscape_asset_validation_report.json"

    if not pack_manifest_path.exists():
        return fail(
            report_path,
            [f"missing pack manifest: {pack_manifest_path}"],
            {"assets_checked": 0, "errors": 1},
        )

    errors: list[str] = []
    pack = load_json(pack_manifest_path)
    summary = {
        "asset_pack_id": pack.get("asset_pack_id"),
        "assets_checked": 0,
        "ambient_assets": 0,
        "drone_assets": 0,
        "impulse_assets": 0,
        "errors": 0,
    }

    if pack.get("stage") != EXPECTED_STAGE:
        errors.append("pack manifest stage must be soundscape_asset_pack")

    allowed_policy_classes = pack.get("allowed_policy_classes")
    if not isinstance(allowed_policy_classes, list) or not allowed_policy_classes:
        errors.append("pack manifest must define non-empty allowed_policy_classes")
        allowed_policy_classes = []

    assets = pack.get("assets")
    if not isinstance(assets, list) or not assets:
        errors.append("pack manifest must define at least one asset entry")
        assets = []

    discovered_layer_kinds: set[str] = set()
    asset_ids: set[str] = set()
    for entry in assets:
        summary["assets_checked"] += 1
        asset_id = entry.get("asset_id")
        layer_kind = entry.get("layer_kind")
        manifest_path_value = entry.get("manifest_path")
        asset_path_value = entry.get("asset_path")

        if not asset_id or asset_id in asset_ids:
            errors.append(f"duplicate or missing asset_id in pack manifest: {asset_id!r}")
            continue
        asset_ids.add(asset_id)

        if layer_kind not in ALLOWED_LAYER_KINDS:
            errors.append(f"{asset_id}: unsupported layer_kind {layer_kind!r}")
            continue
        discovered_layer_kinds.add(layer_kind)
        summary[f"{layer_kind}_assets"] += 1

        if not manifest_path_value:
            errors.append(f"{asset_id}: missing manifest_path in pack manifest")
            continue

        manifest_path = ROOT / manifest_path_value
        if not manifest_path.exists():
            errors.append(f"{asset_id}: manifest file does not exist: {manifest_path}")
            continue

        manifest = load_json(manifest_path)
        missing_fields = sorted(field for field in REQUIRED_ASSET_FIELDS if field not in manifest)
        if missing_fields:
            errors.append(f"{asset_id}: asset manifest missing fields: {', '.join(missing_fields)}")
            continue

        if manifest.get("asset_id") != asset_id:
            errors.append(f"{asset_id}: manifest asset_id mismatch")
        if manifest.get("layer_kind") != layer_kind:
            errors.append(f"{asset_id}: manifest layer_kind mismatch")
        if manifest.get("asset_path") != asset_path_value:
            errors.append(f"{asset_id}: manifest asset_path mismatch with pack manifest")
        if manifest.get("asset_format") != "wav":
            errors.append(f"{asset_id}: asset_format must be wav for P2 seed pack")
        if not isinstance(manifest.get("attribution_required"), bool):
            errors.append(f"{asset_id}: attribution_required must be boolean")
        if not str(manifest.get("source_url", "")).startswith("https://github.com/41490/chao5whistler/blob/main/"):
            errors.append(f"{asset_id}: source_url must point to a repo-traceable blob URL")
        if float(manifest.get("loop_duration_seconds", 0.0)) <= 0.0:
            errors.append(f"{asset_id}: loop_duration_seconds must be > 0")
        if float(manifest.get("loudness_target_dbfs", 1.0)) >= 0.0:
            errors.append(f"{asset_id}: loudness_target_dbfs must be below 0 dBFS")

        license_payload = manifest.get("license", {})
        policy_class = license_payload.get("policy_class")
        if not license_payload.get("spdx"):
            errors.append(f"{asset_id}: license.spdx must be present")
        if not policy_class:
            errors.append(f"{asset_id}: license.policy_class must be present")
        elif policy_class not in allowed_policy_classes:
            errors.append(f"{asset_id}: license.policy_class {policy_class!r} is outside whitelist")

        asset_path = ROOT / manifest.get("asset_path", "")
        if not asset_path.exists():
            errors.append(f"{asset_id}: asset file does not exist: {asset_path}")
            continue

        actual_sha256 = sha256_hex(asset_path)
        if manifest.get("sha256") != actual_sha256:
            errors.append(f"{asset_id}: sha256 mismatch")

        try:
            with wave.open(str(asset_path), "rb") as wav_file:
                duration_seconds = wav_file.getnframes() / float(wav_file.getframerate())
                channels = wav_file.getnchannels()
                sample_rate = wav_file.getframerate()
                sample_width = wav_file.getsampwidth()
        except wave.Error as exc:
            errors.append(f"{asset_id}: unable to read WAV metadata: {exc}")
            continue

        if abs(duration_seconds - float(manifest.get("loop_duration_seconds", 0.0))) > 0.01:
            errors.append(f"{asset_id}: loop_duration_seconds does not match WAV duration")

        audio_payload = manifest.get("audio", {})
        if audio_payload.get("sample_rate") != sample_rate:
            errors.append(f"{asset_id}: audio.sample_rate mismatch")
        if audio_payload.get("channels") != channels:
            errors.append(f"{asset_id}: audio.channels mismatch")
        if audio_payload.get("sample_format") != "pcm_s16le" or sample_width != 2:
            errors.append(f"{asset_id}: audio sample format must be pcm_s16le / 16-bit")

    missing_required_layer_kinds = sorted(REQUIRED_LAYER_KINDS - discovered_layer_kinds)
    if missing_required_layer_kinds:
        errors.append(
            "pack manifest must include at least one asset for each required layer kind: "
            + ", ".join(missing_required_layer_kinds)
        )

    summary["errors"] = len(errors)
    payload = {
        "stage": EXPECTED_STAGE,
        "status": "passed" if not errors else "failed",
        "summary": summary,
        "pack_manifest_path": str(pack_manifest_path),
        "allowed_policy_classes": allowed_policy_classes,
        "errors": errors,
    }
    write_report(report_path, payload)
    if errors:
        print("soundscape asset validation failed:")
        for error in errors:
            print(f"- {error}")
        return 1

    print("soundscape asset validation passed")
    print(f"pack_manifest: {pack_manifest_path}")
    print(f"report: {report_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
