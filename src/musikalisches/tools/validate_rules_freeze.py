#!/usr/bin/env python3

from __future__ import annotations

import json
import sys
import xml.etree.ElementTree as ET
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
PACKAGE_DIR = ROOT / "docs/study/music_dice_games_package/mozart_dicegame_print_1790s"
LOOKUP_PATH = ROOT / "docs/study/music_source_basis_package/docs/mozart_16x11_table.json"
RULES_PATH = PACKAGE_DIR / "rules.json"
WITNESS_DIFF_PATH = PACKAGE_DIR / "witness_diff.json"
MUSICXML_PATH = PACKAGE_DIR / "mother_score.musicxml"


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def fail(errors: list[str]) -> int:
    print("stage3 rules freeze validation failed:")
    for error in errors:
        print(f"- {error}")
    return 1


def extract_fragment_ids(path: Path) -> list[int]:
    root = ET.parse(path).getroot()
    expected = list(range(1, 177))
    sequences = []
    for part in root.findall("part"):
        sequence = []
        for measure in part.findall("measure"):
            number = measure.attrib.get("number", "")
            if number.isdigit():
                value = int(number)
                if 1 <= value <= 176:
                    sequence.append(value)
        sequences.append(sequence)
    for index, sequence in enumerate(sequences, start=1):
        if sequence != expected:
            raise RuntimeError(f"mother_score.musicxml part {index} does not expose fragment ids 1..176")
    return expected


def build_identity_locations(identity_map: dict) -> dict[int, dict]:
    locations: dict[int, dict] = {}
    for page in identity_map["pages"]:
        for row in page["rows"]:
            for slot_index, fragment_id in enumerate(
                range(row["start_fragment_id"], row["end_fragment_id"] + 1),
                start=1,
            ):
                locations[fragment_id] = {
                    "publication_page": page["publication_page"],
                    "row_index": row["row_index"],
                    "slot_index": slot_index,
                    "scan_canvas_index": page["scan_canvas_index"],
                }
    return locations


def main() -> int:
    rules = load_json(RULES_PATH)
    lookup = load_json(LOOKUP_PATH)
    identity_map = load_json(PACKAGE_DIR / "fragment_identity_map.json")
    witness_diff = load_json(WITNESS_DIFF_PATH)
    fragment_ids = extract_fragment_ids(MUSICXML_PATH)
    identity_locations = build_identity_locations(identity_map)

    errors = []
    expected_rolls = list(range(2, 13))
    expected_positions = [
        "A1",
        "A2",
        "A3",
        "A4",
        "A5",
        "A6",
        "A7",
        "A8",
        "B1",
        "B2",
        "B3",
        "B4",
        "B5",
        "B6",
        "B7",
        "B8",
    ]

    if rules.get("status") != "stage3_rules_frozen":
        errors.append("rules.json status must be stage3_rules_frozen")
    if rules.get("canonical_witness_id") != "rellstab_1790":
        errors.append("rules.json canonical_witness_id must be rellstab_1790")
    if rules.get("verification_witness_id") != "simrock_1793":
        errors.append("rules.json verification_witness_id must be simrock_1793")
    if rules.get("positions") != 16:
        errors.append("rules.json positions must equal 16")
    if rules.get("position_labels") != expected_positions:
        errors.append("rules.json position_labels must equal A1..B8")
    if rules.get("selector", {}).get("allowed_values") != expected_rolls:
        errors.append("rules.json selector allowed_values must equal 2..12")

    if lookup.get("status") != "stage3_reconciled_against_mother_score":
        errors.append("mozart_16x11_table.json status must record stage3 reconciliation")
    if lookup.get("canonical_witness_id") != "rellstab_1790":
        errors.append("mozart_16x11_table.json canonical_witness_id must be rellstab_1790")
    if lookup.get("position_labels") != expected_positions:
        errors.append("mozart_16x11_table.json position_labels must equal A1..B8")

    fragment_lookup = rules.get("fragment_lookup", {})
    if sorted(int(fragment_id) for fragment_id in fragment_lookup) != fragment_ids:
        errors.append("rules.json fragment_lookup must cover fragment ids 1..176 exactly once")

    seen_pairs = set()
    for position_index, label in enumerate(expected_positions, start=1):
        column = rules.get("columns", {}).get(label)
        lookup_column = lookup.get("columns", {}).get(label)
        if column is None:
            errors.append(f"rules.json missing column {label}")
            continue
        if lookup_column is None:
            errors.append(f"mozart_16x11_table.json missing column {label}")
            continue
        if column.get("position_index") != position_index:
            errors.append(f"rules.json column {label} has wrong position_index")
        roll_map = column.get("fragment_ids_by_roll", {})
        translated = [roll_map.get(str(roll)) for roll in expected_rolls]
        if translated != lookup_column:
            errors.append(f"rules.json column {label} does not match mozart_16x11_table.json")
        for roll, fragment_id in zip(expected_rolls, lookup_column):
            pair = (label, roll)
            if pair in seen_pairs:
                errors.append(f"duplicate position/roll pair detected: {label} / {roll}")
            seen_pairs.add(pair)
            entry = fragment_lookup.get(str(fragment_id))
            if entry is None:
                errors.append(f"rules.json missing fragment_lookup entry for fragment {fragment_id}")
                continue
            if entry.get("position_label") != label:
                errors.append(f"fragment {fragment_id} reverse lookup label mismatch")
            if entry.get("position_index") != position_index:
                errors.append(f"fragment {fragment_id} reverse lookup position_index mismatch")
            if entry.get("selector_value") != roll:
                errors.append(f"fragment {fragment_id} reverse lookup selector mismatch")
            if entry.get("mother_score_measure_number") != fragment_id:
                errors.append(f"fragment {fragment_id} must map to the same mother-score measure number")
            if entry.get("canonical_witness_id") != "rellstab_1790":
                errors.append(f"fragment {fragment_id} canonical witness mismatch")
            location = identity_locations[fragment_id]
            for key, value in location.items():
                if entry.get(key) != value:
                    errors.append(f"fragment {fragment_id} {key} mismatch against fragment_identity_map.json")

    if witness_diff.get("status") != "stage3_initial_witness_diff":
        errors.append("witness_diff.json status must be stage3_initial_witness_diff")
    if witness_diff.get("canonical_witness_id") != "rellstab_1790":
        errors.append("witness_diff.json canonical_witness_id must be rellstab_1790")
    if witness_diff.get("verification_witness_id") != "simrock_1793":
        errors.append("witness_diff.json verification_witness_id must be simrock_1793")
    scope = witness_diff.get("comparison_scope", {})
    if scope.get("fragment_level_comparison_ready") is not False:
        errors.append("witness_diff.json must not claim fragment-level comparison readiness yet")
    if scope.get("verification_trace_status") != "file_level_frozen_only":
        errors.append("witness_diff.json verification_trace_status must be file_level_frozen_only")
    if witness_diff.get("diffs") != []:
        errors.append("witness_diff.json diffs must remain empty until fragment-level verification is available")

    if errors:
        return fail(errors)

    print("stage3 rules freeze validation passed")
    print("canonical witness: rellstab_1790")
    print("verification witness: simrock_1793")
    print("rules coverage: 16 positions x 11 selector values -> 176 unique fragments")
    print("witness diff: file-level Simrock freeze only; fragment-level comparison still deferred")
    return 0


if __name__ == "__main__":
    sys.exit(main())
