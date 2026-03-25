#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
import random
import subprocess
from datetime import datetime, timezone
from pathlib import Path


RULES_PATH = (
    Path(__file__).resolve().parents[3]
    / "docs"
    / "study"
    / "music_dice_games_package"
    / "mozart_dicegame_print_1790s"
    / "rules.json"
)
SELECTION_FILE = "combination_selection.json"
SELECTION_MODE = "unique_random_persistent_ledger"
LEDGER_STAGE = "stage5_unique_combination_ledger"


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


def augment_artifact(artifact_dir: Path, selection: dict) -> None:
    selection_path = artifact_dir / SELECTION_FILE
    write_json(selection_path, selection)

    for file_name in (
        "render_request.json",
        "stream_loop_plan.json",
        "artifact_summary.json",
        "m1_validation_report.json",
    ):
        path = artifact_dir / file_name
        payload = load_json(path)
        payload["selection"] = selection
        output_files = payload.get("output_files")
        if isinstance(output_files, dict):
            output_files["combination_selection"] = SELECTION_FILE
        write_json(path, payload)


def build_runtime_command(args: argparse.Namespace, rolls: list[int]) -> list[str]:
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
    if args.synth_profile:
        command.extend(["--synth-profile", args.synth_profile])
    return command


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
    runtime_command = build_runtime_command(args, rolls)

    print(f"stage5 unique selection: {combination_id_for_rolls(rolls)}")
    print(f"stage5 ledger: {ledger_path}")
    print(f"stage5 output_dir: {output_dir}")
    subprocess.run(runtime_command, check=True)

    selection = build_selection_payload(
        work_id=args.work_id,
        position_labels=position_labels,
        allowed_values=allowed_values,
        rolls=rolls,
        ledger_path=ledger_path,
        played_unique_count=len(existing_ids) + 1,
        collision_retries=collision_retries,
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

    augment_artifact(output_dir, selection)
    write_json(ledger_path, ledger)

    print(f"selection_file: {output_dir / SELECTION_FILE}")
    print(f"played_unique_count: {selection['played_unique_count']}")
    print(f"total_combinations: {selection['total_combinations']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
