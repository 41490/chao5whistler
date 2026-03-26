#!/usr/bin/env python3

from __future__ import annotations

import argparse
import hashlib
import json
import math
import random
import subprocess
import sys
import wave
from array import array
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
RULES_PATH = (
    ROOT
    / "docs"
    / "study"
    / "music_dice_games_package"
    / "mozart_dicegame_print_1790s"
    / "rules.json"
)
DEFAULT_SOUNDSCAPE_PROFILE = (
    ROOT / "src" / "musikalisches" / "runtime" / "config" / "stage5_default_soundscape_profile.json"
)
SELECTION_FILE = "combination_selection.json"
SOUNDSCAPE_SELECTION_FILE = "soundscape_selection.json"
SELECTION_MODE = "unique_random_persistent_ledger"
LEDGER_STAGE = "stage5_unique_combination_ledger"
SOUNDSCAPE_STAGE = "stage5_soundscape_selection"
MIX_BUS_STAGE = "stage5_soundscape_mix_bus_v1"


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=True, indent=2) + "\n",
        encoding="utf-8",
    )


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def round6(value: float) -> float:
    return round(value, 6)


def db_to_amplitude(db_value: float) -> float:
    return 10.0 ** (db_value / 20.0)


def amplitude_to_dbfs(value: float) -> float:
    return -180.0 if value <= 0.0 else round6(20.0 * math.log10(value))


def stable_index(seed_text: str, size: int) -> int:
    if size <= 0:
        raise SystemExit("stable_index size must be > 0")
    digest = hashlib.sha256(seed_text.encode("utf-8")).digest()
    return int.from_bytes(digest[:8], "big") % size


def combination_id_for_rolls(rolls: list[int]) -> str:
    return ",".join(str(value) for value in rolls)


def combination_ordinal_one_based(rolls: list[int], allowed_values: list[int]) -> int:
    base = len(allowed_values)
    value_to_digit = {value: index for index, value in enumerate(allowed_values)}
    ordinal = 0
    for roll in rolls:
        ordinal = ordinal * base + value_to_digit[roll]
    return ordinal + 1


def load_rules() -> dict:
    if not RULES_PATH.exists():
        raise SystemExit(f"rules file does not exist: {RULES_PATH}")
    return load_json(RULES_PATH)


def load_or_init_ledger(
    *,
    ledger_path: Path,
    work_id: str,
    position_labels: list[str],
    allowed_values: list[int],
    total_combinations: int,
) -> dict:
    if not ledger_path.exists():
        return {
            "stage": LEDGER_STAGE,
            "work_id": work_id,
            "selection_mode": SELECTION_MODE,
            "position_labels": position_labels,
            "allowed_values": allowed_values,
            "total_combinations": total_combinations,
            "played_unique_count": 0,
            "entries": [],
        }

    ledger = load_json(ledger_path)
    if ledger.get("stage") != LEDGER_STAGE:
        raise SystemExit(f"unsupported ledger stage in {ledger_path}")
    if ledger.get("work_id") != work_id:
        raise SystemExit(f"ledger work_id mismatch in {ledger_path}")
    if ledger.get("position_labels") != position_labels:
        raise SystemExit(f"ledger position_labels mismatch in {ledger_path}")
    if ledger.get("allowed_values") != allowed_values:
        raise SystemExit(f"ledger allowed_values mismatch in {ledger_path}")
    if ledger.get("total_combinations") != total_combinations:
        raise SystemExit(f"ledger total_combinations mismatch in {ledger_path}")
    entries = ledger.get("entries")
    if not isinstance(entries, list):
        raise SystemExit(f"ledger entries must be an array in {ledger_path}")
    if ledger.get("played_unique_count") != len(entries):
        raise SystemExit(f"ledger played_unique_count mismatch in {ledger_path}")
    return ledger


def choose_unique_rolls(
    *,
    position_labels: list[str],
    allowed_values: list[int],
    existing_ids: set[str],
) -> tuple[list[int], int]:
    chooser = random.SystemRandom()
    max_attempts = 10_000
    for attempt in range(max_attempts):
        rolls = [chooser.choice(allowed_values) for _ in position_labels]
        if combination_id_for_rolls(rolls) not in existing_ids:
            return rolls, attempt
    raise SystemExit(
        f"failed to allocate a unique combination after {max_attempts} attempts; "
        "ledger may be unexpectedly dense or corrupted"
    )


def build_selection_payload(
    *,
    work_id: str,
    position_labels: list[str],
    allowed_values: list[int],
    rolls: list[int],
    ledger_path: Path,
    played_unique_count: int,
    collision_retries: int,
) -> dict:
    combination_id = combination_id_for_rolls(rolls)
    selector_results = [
        {
            "position_label": position_label,
            "position_index": index,
            "selector_value": selector_value,
        }
        for index, (position_label, selector_value) in enumerate(zip(position_labels, rolls), start=1)
    ]
    total_combinations = len(allowed_values) ** len(position_labels)
    return {
        "work_id": work_id,
        "selection_mode": SELECTION_MODE,
        "combination_id": combination_id,
        "combination_ordinal_one_based": combination_ordinal_one_based(rolls, allowed_values),
        "rolls": rolls,
        "position_labels": position_labels,
        "allowed_values": allowed_values,
        "selector_results": selector_results,
        "total_combinations": total_combinations,
        "played_unique_count": played_unique_count,
        "is_replayed": False,
        "collision_retries": collision_retries,
        "ledger_path": str(ledger_path),
        "recorded_at": utc_now(),
    }


def ensure_output_files(payload: dict) -> dict:
    output_files = payload.get("output_files")
    if not isinstance(output_files, dict):
        output_files = {}
        payload["output_files"] = output_files
    return output_files


def augment_selection_artifact(artifact_dir: Path, selection: dict) -> None:
    stream_plan_payload = load_json(artifact_dir / "stream_loop_plan.json")
    summary_payload = load_json(artifact_dir / "artifact_summary.json")
    enriched_selection = dict(selection)

    loop_count = stream_plan_payload.get("loop_count")
    cycle_duration_seconds = stream_plan_payload.get("cycle_duration_seconds")
    if isinstance(loop_count, int) and loop_count > 0:
        enriched_selection["combination_hold_cycles"] = loop_count
    if isinstance(cycle_duration_seconds, (int, float)):
        enriched_selection["source_cycle_duration_seconds"] = round6(float(cycle_duration_seconds))
    if (
        isinstance(loop_count, int)
        and loop_count > 0
        and isinstance(cycle_duration_seconds, (int, float))
    ):
        enriched_selection["combination_duration_seconds"] = round6(
            float(loop_count) * float(cycle_duration_seconds)
        )
    audio_render_backend = summary_payload.get("audio", {}).get("render_backend")
    if isinstance(audio_render_backend, str) and audio_render_backend:
        enriched_selection["audio_render_backend"] = audio_render_backend

    selection_path = artifact_dir / SELECTION_FILE
    write_json(selection_path, enriched_selection)

    for file_name in (
        "render_request.json",
        "stream_loop_plan.json",
        "artifact_summary.json",
        "m1_validation_report.json",
    ):
        path = artifact_dir / file_name
        payload = load_json(path)
        payload["selection"] = enriched_selection
        output_files = ensure_output_files(payload)
        output_files["combination_selection"] = SELECTION_FILE
        write_json(path, payload)


def resolve_repo_path(raw_path: str, *, base_dir: Path | None = None) -> Path:
    candidate = Path(raw_path)
    if candidate.is_absolute():
        return candidate.resolve()
    if base_dir is not None:
        base_candidate = (base_dir / candidate).resolve()
        if base_candidate.exists():
            return base_candidate
    return (ROOT / candidate).resolve()


def load_soundscape_profile(profile_path: Path) -> dict:
    if not profile_path.exists():
        raise SystemExit(f"soundscape profile does not exist: {profile_path}")
    payload = load_json(profile_path)
    if not payload.get("profile_id"):
        raise SystemExit(f"soundscape profile missing profile_id: {profile_path}")
    if not isinstance(payload.get("main_registration_profiles"), list) or not payload["main_registration_profiles"]:
        raise SystemExit(f"soundscape profile must define main_registration_profiles: {profile_path}")
    if not isinstance(payload.get("required_layer_kinds"), list) or not payload["required_layer_kinds"]:
        raise SystemExit(f"soundscape profile must define required_layer_kinds: {profile_path}")
    mix_bus = payload.get("mix_bus_profile")
    if not isinstance(mix_bus, dict) or not mix_bus.get("profile_id"):
        raise SystemExit(f"soundscape profile must define mix_bus_profile.profile_id: {profile_path}")
    payload["source_path"] = str(profile_path)
    payload["source_dir"] = str(profile_path.parent)
    return payload


def resolve_registration_choice(
    *,
    args: argparse.Namespace,
    selection: dict,
    soundscape_profile: dict | None,
) -> dict | None:
    if args.synth_profile:
        synth_profile_path = resolve_repo_path(args.synth_profile)
        synth_profile = load_json(synth_profile_path)
        return {
            "registration_id": synth_profile.get("profile_id") or synth_profile_path.stem,
            "label": synth_profile.get("profile_id") or synth_profile_path.stem,
            "selection_index": 0,
            "selection_source": "cli_override",
            "synth_profile_path": str(synth_profile_path),
            "synth_profile_id": synth_profile.get("profile_id") or synth_profile_path.stem,
        }

    if soundscape_profile is None:
        return None

    registrations = soundscape_profile["main_registration_profiles"]
    index = stable_index(selection["combination_id"] + ":registration", len(registrations))
    registration = registrations[index]
    synth_profile_path = resolve_repo_path(
        registration["synth_profile_path"],
        base_dir=Path(soundscape_profile["source_dir"]),
    )
    synth_profile = load_json(synth_profile_path)
    return {
        "registration_id": registration.get("registration_id") or synth_profile.get("profile_id") or synth_profile_path.stem,
        "label": registration.get("label") or synth_profile.get("profile_id") or synth_profile_path.stem,
        "selection_index": index,
        "selection_source": soundscape_profile.get("selection_mode", "deterministic"),
        "synth_profile_path": str(synth_profile_path),
        "synth_profile_id": synth_profile.get("profile_id") or synth_profile_path.stem,
    }


def build_runtime_command(
    args: argparse.Namespace,
    rolls: list[int],
    registration_choice: dict | None,
) -> list[str]:
    command = [
        args.cargo_bin,
        "run",
        "--",
        "render-audio",
        "--work",
        args.work_id,
        "--rolls",
        combination_id_for_rolls(rolls),
        "--loop-count",
        str(args.loop_count),
        "--analysis-window-ms",
        str(args.analysis_window_ms),
        "--tempo-bpm",
        str(args.tempo_bpm),
        "--sample-rate",
        str(args.sample_rate),
        "--output-dir",
        str(args.output_dir),
    ]
    if args.soundfont:
        command.extend(["--soundfont", args.soundfont])
    if registration_choice and registration_choice.get("synth_profile_path"):
        command.extend(["--synth-profile", registration_choice["synth_profile_path"]])
    elif args.synth_profile:
        command.extend(["--synth-profile", args.synth_profile])
    return command


def read_wav_pcm(path: Path) -> dict:
    with wave.open(str(path), "rb") as wav_file:
        channels = wav_file.getnchannels()
        sample_width = wav_file.getsampwidth()
        sample_rate = wav_file.getframerate()
        frame_count = wav_file.getnframes()
        pcm_bytes = wav_file.readframes(frame_count)
    if channels != 2:
        raise SystemExit(f"expected stereo WAV for soundscape mixing: {path}")
    if sample_width != 2:
        raise SystemExit(f"expected 16-bit PCM WAV for soundscape mixing: {path}")
    pcm = array("h")
    pcm.frombytes(pcm_bytes)
    if sys.byteorder != "little":
        pcm.byteswap()
    return {
        "path": str(path),
        "sample_rate": sample_rate,
        "channels": channels,
        "sample_width": sample_width,
        "frame_count": frame_count,
        "pcm": pcm,
    }


def write_wav_pcm(path: Path, *, sample_rate: int, pcm: array) -> None:
    with wave.open(str(path), "wb") as wav_file:
        wav_file.setnchannels(2)
        wav_file.setsampwidth(2)
        wav_file.setframerate(sample_rate)
        wav_file.writeframes(pcm.tobytes())


def compute_audio_stats_from_pcm(pcm: array, *, sample_rate: int) -> dict:
    if len(pcm) % 2 != 0:
        raise SystemExit("stereo PCM buffer must contain an even number of samples")
    sample_count = len(pcm)
    frame_count = sample_count // 2
    peak_value = max(abs(sample) for sample in pcm) if pcm else 0
    rms_numerator = sum(int(sample) * int(sample) for sample in pcm)
    peak_amplitude = peak_value / 32767.0 if peak_value else 0.0
    rms_amplitude = math.sqrt(rms_numerator / sample_count) / 32767.0 if sample_count else 0.0
    return {
        "frames": frame_count,
        "duration_seconds": round6(frame_count / sample_rate) if sample_rate else 0.0,
        "peak_amplitude": round6(peak_amplitude),
        "peak_dbfs": amplitude_to_dbfs(peak_amplitude),
        "rms_amplitude": round6(rms_amplitude),
        "rms_dbfs": amplitude_to_dbfs(rms_amplitude),
    }


def mix_asset_into(
    mixed: array,
    *,
    asset_pcm: array,
    asset_frame_count: int,
    asset_sample_rate: int,
    target_frame_count: int,
    target_sample_rate: int,
    gain: float,
) -> None:
    if asset_frame_count <= 0:
        raise SystemExit("soundscape asset frame_count must be > 0")
    if asset_sample_rate <= 0 or target_sample_rate <= 0:
        raise SystemExit("sample_rate must be > 0 for soundscape mixing")

    if asset_sample_rate == target_sample_rate:
        for frame_index in range(target_frame_count):
            source_frame = frame_index % asset_frame_count
            target_base = frame_index * 2
            source_base = source_frame * 2
            mixed[target_base] += (asset_pcm[source_base] / 32767.0) * gain
            mixed[target_base + 1] += (asset_pcm[source_base + 1] / 32767.0) * gain
        return

    ratio = asset_sample_rate / float(target_sample_rate)
    for frame_index in range(target_frame_count):
        source_position = (frame_index * ratio) % asset_frame_count
        source_floor = int(source_position)
        source_frac = source_position - source_floor
        source_next = (source_floor + 1) % asset_frame_count
        target_base = frame_index * 2
        floor_base = source_floor * 2
        next_base = source_next * 2
        left = (
            (asset_pcm[floor_base] / 32767.0) * (1.0 - source_frac)
            + (asset_pcm[next_base] / 32767.0) * source_frac
        )
        right = (
            (asset_pcm[floor_base + 1] / 32767.0) * (1.0 - source_frac)
            + (asset_pcm[next_base + 1] / 32767.0) * source_frac
        )
        mixed[target_base] += left * gain
        mixed[target_base + 1] += right * gain


def write_mix_to_pcm(mixed: array) -> array:
    output = array("h")
    for sample in mixed:
        clamped = max(-0.999969, min(0.999969, sample))
        output.append(int(round(clamped * 32767.0)))
    return output


def load_asset_pack(soundscape_profile: dict) -> tuple[dict, dict[str, list[dict]]]:
    pack_manifest_path = resolve_repo_path(
        soundscape_profile["asset_pack_manifest_path"],
        base_dir=Path(soundscape_profile["source_dir"]),
    )
    if not pack_manifest_path.exists():
        raise SystemExit(f"soundscape asset pack manifest does not exist: {pack_manifest_path}")
    pack_manifest = load_json(pack_manifest_path)
    assets_by_layer: dict[str, list[dict]] = {}
    for entry in pack_manifest.get("assets", []):
        manifest_path_value = entry.get("manifest_path")
        if not manifest_path_value:
            raise SystemExit(f"soundscape pack manifest entry missing manifest_path: {pack_manifest_path}")
        manifest_path = resolve_repo_path(manifest_path_value)
        asset_manifest = load_json(manifest_path)
        asset_manifest["manifest_path"] = str(manifest_path)
        asset_manifest["resolved_asset_path"] = str(resolve_repo_path(asset_manifest["asset_path"]))
        assets_by_layer.setdefault(asset_manifest["layer_kind"], []).append(asset_manifest)

    for layer_kind in soundscape_profile.get("required_layer_kinds", []):
        if not assets_by_layer.get(layer_kind):
            raise SystemExit(
                f"soundscape asset pack {pack_manifest_path} does not provide required layer_kind={layer_kind}"
            )
    pack_manifest["resolved_manifest_path"] = str(pack_manifest_path)
    return pack_manifest, assets_by_layer


def select_layer_asset(*, assets: list[dict], combination_id: str, layer_kind: str) -> tuple[dict, int]:
    index = stable_index(f"{combination_id}:{layer_kind}", len(assets))
    return assets[index], index


def summarize_soundscape(
    *,
    soundscape_selection: dict,
    final_audio_stats: dict,
) -> dict:
    asset_layers = {layer["layer_kind"]: layer for layer in soundscape_selection["layers"] if layer["layer_kind"] != "main"}
    return {
        "selection_file": SOUNDSCAPE_SELECTION_FILE,
        "profile_id": soundscape_selection["soundscape_profile_id"],
        "mix_bus_profile_id": soundscape_selection["mix_bus"]["profile_id"],
        "registration_id": soundscape_selection["registration"]["registration_id"],
        "registration_label": soundscape_selection["registration"]["label"],
        "ambient_asset_id": asset_layers["ambient"]["asset_id"],
        "ambient_label": asset_layers["ambient"]["label"],
        "drone_asset_id": asset_layers["drone"]["asset_id"],
        "drone_label": asset_layers["drone"]["label"],
        "layer_count": len(soundscape_selection["layers"]),
        "duration_seconds": final_audio_stats["duration_seconds"],
        "peak_amplitude": final_audio_stats["peak_amplitude"],
        "rms_dbfs": final_audio_stats["rms_dbfs"],
    }


def update_stage5_contracts(
    *,
    artifact_dir: Path,
    selection: dict,
    soundscape_selection: dict,
    final_audio_stats: dict,
    registration_choice: dict,
) -> None:
    render_request = load_json(artifact_dir / "render_request.json")
    stream_loop_plan = load_json(artifact_dir / "stream_loop_plan.json")
    artifact_summary = load_json(artifact_dir / "artifact_summary.json")
    validation_report = load_json(artifact_dir / "m1_validation_report.json")

    soundscape_summary = summarize_soundscape(
        soundscape_selection=soundscape_selection,
        final_audio_stats=final_audio_stats,
    )

    for payload in (render_request, stream_loop_plan, artifact_summary, validation_report):
        payload["soundscape"] = soundscape_summary
        output_files = ensure_output_files(payload)
        output_files["combination_selection"] = SELECTION_FILE
        output_files["soundscape_selection"] = SOUNDSCAPE_SELECTION_FILE

    audio_summary = artifact_summary.setdefault("audio", {})
    audio_summary["mixed_layers"] = True
    audio_summary["mix_bus_profile_id"] = soundscape_selection["mix_bus"]["profile_id"]
    audio_summary["source_audio_render_backend"] = audio_summary.get("render_backend")
    audio_summary["frames"] = final_audio_stats["frames"]
    audio_summary["duration_seconds"] = final_audio_stats["duration_seconds"]
    audio_summary["peak_amplitude"] = final_audio_stats["peak_amplitude"]
    audio_summary["peak_dbfs"] = final_audio_stats["peak_dbfs"]
    audio_summary["rms_amplitude"] = final_audio_stats["rms_amplitude"]
    audio_summary["rms_dbfs"] = final_audio_stats["rms_dbfs"]
    audio_summary["post_mix_gain"] = soundscape_selection["mix_bus"]["post_mix_gain"]
    artifact_summary["soundscape"] = soundscape_summary

    summary = validation_report.setdefault("summary", {})
    summary["soundscape_profile_id"] = soundscape_selection["soundscape_profile_id"]
    summary["soundscape_mix_bus_profile_id"] = soundscape_selection["mix_bus"]["profile_id"]
    summary["soundscape_layer_count"] = len(soundscape_selection["layers"])
    summary["registration_profile_id"] = registration_choice["synth_profile_id"]
    summary["registration_label"] = registration_choice["label"]
    summary["soundscape_peak_amplitude"] = final_audio_stats["peak_amplitude"]
    summary["soundscape_peak_dbfs"] = final_audio_stats["peak_dbfs"]
    summary["soundscape_rms_dbfs"] = final_audio_stats["rms_dbfs"]
    summary["audio_frames"] = final_audio_stats["frames"]
    summary["peak_amplitude"] = final_audio_stats["peak_amplitude"]
    validation_report["soundscape"] = soundscape_summary

    checks = validation_report.setdefault("checks", [])
    mix_bus = soundscape_selection["mix_bus"]
    expected_duration = selection["combination_duration_seconds"]
    layer_kinds = [layer["layer_kind"] for layer in soundscape_selection["layers"]]
    checks.extend(
        [
            {
                "check_id": "soundscape_selection_present",
                "status": "passed",
                "details": {
                    "soundscape_profile_id": soundscape_selection["soundscape_profile_id"],
                    "mix_bus_profile_id": mix_bus["profile_id"],
                    "registration_id": soundscape_selection["registration"]["registration_id"],
                },
            },
            {
                "check_id": "soundscape_layer_contract",
                "status": "passed" if layer_kinds == ["main", "drone", "ambient"] else "failed",
                "details": {"actual_layer_kinds": layer_kinds},
            },
            {
                "check_id": "soundscape_mix_duration_consistency",
                "status": "passed"
                if abs(final_audio_stats["duration_seconds"] - expected_duration) <= 0.01
                else "failed",
                "details": {
                    "actual_duration_seconds": final_audio_stats["duration_seconds"],
                    "expected_duration_seconds": expected_duration,
                },
            },
            {
                "check_id": "soundscape_peak_guardrail",
                "status": "passed"
                if mix_bus["target_peak_min_amplitude"]
                <= final_audio_stats["peak_amplitude"]
                <= mix_bus["target_peak_max_amplitude"]
                else "failed",
                "details": {
                    "actual_peak_amplitude": final_audio_stats["peak_amplitude"],
                    "target_peak_min_amplitude": mix_bus["target_peak_min_amplitude"],
                    "target_peak_max_amplitude": mix_bus["target_peak_max_amplitude"],
                },
            },
            {
                "check_id": "soundscape_rms_guardrail",
                "status": "passed"
                if mix_bus["target_rms_min_dbfs"]
                <= final_audio_stats["rms_dbfs"]
                <= mix_bus["target_rms_max_dbfs"]
                else "failed",
                "details": {
                    "actual_rms_dbfs": final_audio_stats["rms_dbfs"],
                    "target_rms_min_dbfs": mix_bus["target_rms_min_dbfs"],
                    "target_rms_max_dbfs": mix_bus["target_rms_max_dbfs"],
                },
            },
        ]
    )
    checks_passed = sum(1 for check in checks if check.get("status") == "passed")
    checks_failed = sum(1 for check in checks if check.get("status") == "failed")
    summary["checks_passed"] = checks_passed
    summary["checks_failed"] = checks_failed
    if checks_failed:
        validation_report["status"] = "failed"
        validation_report.setdefault("errors", []).append("soundscape mix bus checks failed")
        raise SystemExit("soundscape mix bus checks failed; see m1_validation_report.json for details")
    validation_report["status"] = "passed"

    write_json(artifact_dir / "render_request.json", render_request)
    write_json(artifact_dir / "stream_loop_plan.json", stream_loop_plan)
    write_json(artifact_dir / "artifact_summary.json", artifact_summary)
    write_json(artifact_dir / "m1_validation_report.json", validation_report)


def apply_soundscape_mix(
    *,
    artifact_dir: Path,
    selection: dict,
    soundscape_profile: dict,
    registration_choice: dict,
) -> None:
    pack_manifest, assets_by_layer = load_asset_pack(soundscape_profile)
    main_audio_path = artifact_dir / "offline_audio.wav"
    main_audio = read_wav_pcm(main_audio_path)
    target_frame_count = main_audio["frame_count"]
    target_sample_rate = main_audio["sample_rate"]
    final_duration_seconds = round6(target_frame_count / target_sample_rate)

    mix_bus_profile = soundscape_profile["mix_bus_profile"]
    main_gain = db_to_amplitude(float(mix_bus_profile["main_gain_db"]))
    drone_gain = db_to_amplitude(float(mix_bus_profile["drone_gain_db"]))
    ambient_gain = db_to_amplitude(float(mix_bus_profile["ambient_gain_db"]))
    master_gain = db_to_amplitude(float(mix_bus_profile.get("master_gain_db", 0.0)))
    ceiling = float(mix_bus_profile["peak_ceiling_amplitude"])
    target_peak_min = float(mix_bus_profile["target_peak_min_amplitude"])
    target_peak_max = float(mix_bus_profile["target_peak_max_amplitude"])
    target_rms_min = float(mix_bus_profile["target_rms_min_dbfs"])
    target_rms_max = float(mix_bus_profile["target_rms_max_dbfs"])

    mixed = array("f", ((sample / 32767.0) * main_gain for sample in main_audio["pcm"]))
    main_audio_stats = compute_audio_stats_from_pcm(main_audio["pcm"], sample_rate=target_sample_rate)

    layer_entries: list[dict] = [
        {
            "layer_id": "main_organ",
            "layer_kind": "main",
            "label": registration_choice["label"],
            "gain_db": float(mix_bus_profile["main_gain_db"]),
            "source": "stage5_render_audio",
            "render_backend": selection["audio_render_backend"],
            "synth_profile_id": registration_choice["synth_profile_id"],
            "synth_profile_path": registration_choice["synth_profile_path"],
            "duration_seconds": final_duration_seconds,
        }
    ]

    selected_asset_ids: dict[str, str] = {}
    for layer_kind, gain_db, gain in (
        ("drone", float(mix_bus_profile["drone_gain_db"]), drone_gain),
        ("ambient", float(mix_bus_profile["ambient_gain_db"]), ambient_gain),
    ):
        asset_manifest, selection_index = select_layer_asset(
            assets=assets_by_layer[layer_kind],
            combination_id=selection["combination_id"],
            layer_kind=layer_kind,
        )
        asset_audio = read_wav_pcm(Path(asset_manifest["resolved_asset_path"]))
        mix_asset_into(
            mixed,
            asset_pcm=asset_audio["pcm"],
            asset_frame_count=asset_audio["frame_count"],
            asset_sample_rate=asset_audio["sample_rate"],
            target_frame_count=target_frame_count,
            target_sample_rate=target_sample_rate,
            gain=gain,
        )
        selected_asset_ids[layer_kind] = asset_manifest["asset_id"]
        layer_entries.append(
            {
                "layer_id": f"{layer_kind}_bed",
                "layer_kind": layer_kind,
                "asset_id": asset_manifest["asset_id"],
                "label": asset_manifest.get("label") or asset_manifest["asset_id"],
                "description": asset_manifest.get("description"),
                "selection_index": selection_index,
                "manifest_path": asset_manifest["manifest_path"],
                "asset_path": asset_manifest["resolved_asset_path"],
                "sha256": asset_manifest["sha256"],
                "loop_duration_seconds": asset_manifest["loop_duration_seconds"],
                "loudness_target_dbfs": asset_manifest["loudness_target_dbfs"],
                "gain_db": gain_db,
                "duration_seconds": final_duration_seconds,
            }
        )

    if master_gain != 1.0:
        for index in range(len(mixed)):
            mixed[index] *= master_gain

    peak_before_limiter = max(abs(sample) for sample in mixed) if mixed else 0.0
    post_mix_gain = 1.0
    if 0.0 < peak_before_limiter < target_peak_min:
        boost = target_peak_min / peak_before_limiter
        if peak_before_limiter * boost <= ceiling:
            post_mix_gain *= boost
    if peak_before_limiter * post_mix_gain > ceiling:
        post_mix_gain *= ceiling / (peak_before_limiter * post_mix_gain)
    if post_mix_gain != 1.0:
        for index in range(len(mixed)):
            mixed[index] *= post_mix_gain

    mixed_pcm = write_mix_to_pcm(mixed)
    write_wav_pcm(main_audio_path, sample_rate=target_sample_rate, pcm=mixed_pcm)
    final_audio_stats = compute_audio_stats_from_pcm(mixed_pcm, sample_rate=target_sample_rate)

    if not (target_peak_min <= final_audio_stats["peak_amplitude"] <= target_peak_max):
        raise SystemExit(
            "soundscape peak guardrail failed: "
            f"peak={final_audio_stats['peak_amplitude']} not in [{target_peak_min}, {target_peak_max}]"
        )
    if not (target_rms_min <= final_audio_stats["rms_dbfs"] <= target_rms_max):
        raise SystemExit(
            "soundscape RMS guardrail failed: "
            f"rms_dbfs={final_audio_stats['rms_dbfs']} not in [{target_rms_min}, {target_rms_max}]"
        )

    soundscape_selection = {
        "stage": SOUNDSCAPE_STAGE,
        "soundscape_profile_id": soundscape_profile["profile_id"],
        "soundscape_profile_path": soundscape_profile["source_path"],
        "selection_mode": soundscape_profile.get("selection_mode", "deterministic"),
        "asset_pack_id": pack_manifest.get("asset_pack_id"),
        "asset_pack_manifest_path": pack_manifest["resolved_manifest_path"],
        "combination_id": selection["combination_id"],
        "combination_hold_cycles": selection["combination_hold_cycles"],
        "source_cycle_duration_seconds": selection["source_cycle_duration_seconds"],
        "combination_duration_seconds": selection["combination_duration_seconds"],
        "recorded_at": utc_now(),
        "registration": {
            "registration_id": registration_choice["registration_id"],
            "label": registration_choice["label"],
            "selection_index": registration_choice["selection_index"],
            "selection_source": registration_choice["selection_source"],
            "synth_profile_id": registration_choice["synth_profile_id"],
            "synth_profile_path": registration_choice["synth_profile_path"],
        },
        "layers": layer_entries,
        "mix_bus": {
            "stage": MIX_BUS_STAGE,
            "profile_id": mix_bus_profile["profile_id"],
            "main_gain_db": float(mix_bus_profile["main_gain_db"]),
            "drone_gain_db": float(mix_bus_profile["drone_gain_db"]),
            "ambient_gain_db": float(mix_bus_profile["ambient_gain_db"]),
            "master_gain_db": float(mix_bus_profile.get("master_gain_db", 0.0)),
            "post_mix_gain": round6(post_mix_gain),
            "peak_ceiling_amplitude": ceiling,
            "target_peak_min_amplitude": target_peak_min,
            "target_peak_max_amplitude": target_peak_max,
            "target_rms_min_dbfs": target_rms_min,
            "target_rms_max_dbfs": target_rms_max,
            "output_frames": final_audio_stats["frames"],
            "output_duration_seconds": final_audio_stats["duration_seconds"],
            "peak_amplitude": final_audio_stats["peak_amplitude"],
            "peak_dbfs": final_audio_stats["peak_dbfs"],
            "rms_amplitude": final_audio_stats["rms_amplitude"],
            "rms_dbfs": final_audio_stats["rms_dbfs"],
            "main_audio_peak_amplitude": main_audio_stats["peak_amplitude"],
        },
        "selected_asset_ids": selected_asset_ids,
    }
    write_json(artifact_dir / SOUNDSCAPE_SELECTION_FILE, soundscape_selection)
    update_stage5_contracts(
        artifact_dir=artifact_dir,
        selection=selection,
        soundscape_selection=soundscape_selection,
        final_audio_stats=final_audio_stats,
        registration_choice=registration_choice,
    )


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Allocate a unique stage5 combination from a persistent ledger, then render stream artifacts."
    )
    parser.add_argument("--work-id", default="mozart_dicegame_print_1790s")
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--ledger-path", required=True)
    parser.add_argument("--cargo-bin", default="cargo")
    parser.add_argument("--loop-count", type=int, default=4)
    parser.add_argument("--analysis-window-ms", type=int, default=40)
    parser.add_argument("--tempo-bpm", type=float, default=120.0)
    parser.add_argument("--sample-rate", type=int, default=44_100)
    parser.add_argument("--soundfont")
    parser.add_argument("--synth-profile")
    parser.add_argument("--soundscape-profile", default=str(DEFAULT_SOUNDSCAPE_PROFILE))
    parser.add_argument(
        "--no-soundscape",
        action="store_true",
        help="disable the P3 soundscape mix bus and render only the primary stage5 organ layer",
    )
    args = parser.parse_args()

    output_dir = Path(args.output_dir).resolve()
    ledger_path = Path(args.ledger_path).resolve()

    rules = load_rules()
    if rules.get("work_id") != args.work_id:
        raise SystemExit(
            f"rules work_id mismatch: requested {args.work_id}, rules file carries {rules.get('work_id')}"
        )

    position_labels = rules.get("position_labels")
    allowed_values = rules.get("selector", {}).get("allowed_values")
    if not isinstance(position_labels, list) or not position_labels:
        raise SystemExit("rules position_labels must be a non-empty array")
    if not isinstance(allowed_values, list) or not allowed_values:
        raise SystemExit("rules selector.allowed_values must be a non-empty array")

    total_combinations = len(allowed_values) ** len(position_labels)
    ledger = load_or_init_ledger(
        ledger_path=ledger_path,
        work_id=args.work_id,
        position_labels=position_labels,
        allowed_values=allowed_values,
        total_combinations=total_combinations,
    )

    existing_ids = {entry.get("combination_id") for entry in ledger["entries"]}
    if None in existing_ids:
        raise SystemExit(f"ledger contains an entry without combination_id: {ledger_path}")
    if len(existing_ids) != len(ledger["entries"]):
        raise SystemExit(f"ledger contains duplicate combination_id entries: {ledger_path}")
    if len(existing_ids) >= total_combinations:
        raise SystemExit(f"ledger is exhausted: all {total_combinations} canonical combinations were already used")

    rolls, collision_retries = choose_unique_rolls(
        position_labels=position_labels,
        allowed_values=allowed_values,
        existing_ids=existing_ids,
    )
    selection = build_selection_payload(
        work_id=args.work_id,
        position_labels=position_labels,
        allowed_values=allowed_values,
        rolls=rolls,
        ledger_path=ledger_path,
        played_unique_count=len(existing_ids) + 1,
        collision_retries=collision_retries,
    )

    soundscape_profile = None
    if not args.no_soundscape:
        soundscape_profile = load_soundscape_profile(Path(args.soundscape_profile).resolve())
    registration_choice = resolve_registration_choice(
        args=args,
        selection=selection,
        soundscape_profile=soundscape_profile,
    )
    runtime_command = build_runtime_command(args, rolls, registration_choice)

    print(f"stage5 unique selection: {combination_id_for_rolls(rolls)}")
    print(f"stage5 ledger: {ledger_path}")
    print(f"stage5 output_dir: {output_dir}")
    if registration_choice:
        print(
            "stage5 registration: "
            f"{registration_choice['label']} ({registration_choice['synth_profile_id']})"
        )
    subprocess.run(runtime_command, check=True)

    augment_selection_artifact(output_dir, selection)
    selection = load_json(output_dir / SELECTION_FILE)

    if soundscape_profile is not None:
        if registration_choice is None:
            raise SystemExit("soundscape mix requested but no registration choice resolved")
        apply_soundscape_mix(
            artifact_dir=output_dir,
            selection=selection,
            soundscape_profile=soundscape_profile,
            registration_choice=registration_choice,
        )

    ledger["entries"].append(
        {
            "combination_id": selection["combination_id"],
            "combination_ordinal_one_based": selection["combination_ordinal_one_based"],
            "rolls": rolls,
            "recorded_at": selection["recorded_at"],
        }
    )
    ledger["played_unique_count"] = len(ledger["entries"])
    write_json(ledger_path, ledger)

    print(f"selection_file: {output_dir / SELECTION_FILE}")
    if soundscape_profile is not None:
        print(f"soundscape_selection_file: {output_dir / SOUNDSCAPE_SELECTION_FILE}")
    print(f"played_unique_count: {selection['played_unique_count']}")
    print(f"total_combinations: {selection['total_combinations']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
