#!/usr/bin/env python3

from __future__ import annotations

import json
import sys
import warnings
from pathlib import Path

warnings.filterwarnings("ignore")

from music21 import converter, stream  # type: ignore


ROOT = Path(__file__).resolve().parents[3]
PACKAGE_DIR = ROOT / "docs/study/music_dice_games_package/mozart_dicegame_print_1790s"
INGEST_DIR = PACKAGE_DIR / "ingest"
MUSICXML_PATH = PACKAGE_DIR / "mother_score.musicxml"
RULES_PATH = PACKAGE_DIR / "rules.json"
SOURCE_MANIFEST_PATH = PACKAGE_DIR / "source_manifest.json"
FRAGMENTS_PATH = INGEST_DIR / "fragments.json"
MEASURES_PATH = INGEST_DIR / "measures.json"
REPORT_PATH = INGEST_DIR / "validation_report.json"

EXPECTED_FRAGMENT_IDS = list(range(1, 177))
EXPECTED_POSITIONS = [
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
EPSILON = 1e-9
STAGE4_NOTE = (
    "Stage 4 freezes runtime-ready ingest artifacts under ingest/, including normalized "
    "explicit-rest timelines and a validation report."
)


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def fail(errors: list[str]) -> int:
    print("stage4 ingest validation failed:")
    for error in errors:
        print(f"- {error}")
    return 1


def main() -> int:
    for path in (FRAGMENTS_PATH, MEASURES_PATH, REPORT_PATH):
        if not path.exists():
            return fail([f"missing required ingest artifact: {path.relative_to(ROOT)}"])

    rules = load_json(RULES_PATH)
    source_manifest = load_json(SOURCE_MANIFEST_PATH)
    fragments_payload = load_json(FRAGMENTS_PATH)
    measures_payload = load_json(MEASURES_PATH)
    report_payload = load_json(REPORT_PATH)
    score = converter.parse(str(MUSICXML_PATH))

    errors = []

    for payload_name, payload in (
        ("fragments.json", fragments_payload),
        ("measures.json", measures_payload),
    ):
        if payload.get("status") != "stage4_ingest_frozen":
            errors.append(f"{payload_name} status must be stage4_ingest_frozen")

    if report_payload.get("status") != "passed":
        errors.append("validation_report.json status must be passed")
    if report_payload.get("stage") != "stage4_ingest_frozen":
        errors.append("validation_report.json stage must be stage4_ingest_frozen")
    if source_manifest.get("status") != "stage4_ingest_frozen":
        errors.append("source_manifest.json status must be stage4_ingest_frozen")
    if STAGE4_NOTE not in source_manifest.get("notes", []):
        errors.append("source_manifest.json must record the stage-4 ingest freeze note")

    fragment_entries = fragments_payload.get("fragments", [])
    measure_entries = measures_payload.get("measures", [])
    fragment_ids = [entry["fragment_id"] for entry in fragment_entries]
    if fragment_ids != EXPECTED_FRAGMENT_IDS:
        errors.append("fragments.json must contain fragment ids 1..176 in order")

    score_sequences = []
    for part in score.parts:
        sequence = [
            int(measure.number)
            for measure in part.getElementsByClass(stream.Measure)
            if isinstance(measure.number, int)
        ]
        score_sequences.append(sequence)
    if len(score_sequences) != 2 or score_sequences[0] != score_sequences[1]:
        errors.append("mother_score.musicxml parts must share the same source measure sequence")
    else:
        if measures_payload.get("source_measure_sequence") != score_sequences[0]:
            errors.append("measures.json source_measure_sequence does not match mother_score.musicxml")

    runtime_measure_numbers = measures_payload.get("runtime_fragment_measure_numbers")
    if runtime_measure_numbers != EXPECTED_FRAGMENT_IDS:
        errors.append("measures.json runtime_fragment_measure_numbers must equal 1..176")

    measure_zero_entries = [entry for entry in measure_entries if entry["source_measure_number"] == 0]
    if not measure_zero_entries:
        errors.append("measures.json must contain structural measure 0 entries")
    for index, measure_zero in enumerate(measure_zero_entries, start=1):
        if measure_zero.get("included_in_runtime") is not False:
            errors.append(f"structural measure 0 occurrence {index} must be excluded from runtime")

    if len(measure_entries) != len(measures_payload.get("source_measure_sequence", [])):
        errors.append("measures.json measure count must match source_measure_sequence length")

    for entry in fragment_entries:
        fragment_id = entry["fragment_id"]
        if entry.get("measure_number") != fragment_id:
            errors.append(f"fragment {fragment_id} measure_number must equal fragment_id")
        if entry.get("position_label") not in EXPECTED_POSITIONS:
            errors.append(f"fragment {fragment_id} has invalid position_label")
        binding = entry.get("selector_binding", {})
        if binding.get("selector_type") != "sum_of_two_d6":
            errors.append(f"fragment {fragment_id} selector_type must be sum_of_two_d6")
        if binding.get("selector_value") not in rules["selector"]["allowed_values"]:
            errors.append(f"fragment {fragment_id} selector_value is outside rules domain")

        rules_lookup = rules["fragment_lookup"][str(fragment_id)]
        if entry.get("position_label") != rules_lookup["position_label"]:
            errors.append(f"fragment {fragment_id} position_label does not match rules.json")
        if entry.get("position_index") != rules_lookup["position_index"]:
            errors.append(f"fragment {fragment_id} position_index does not match rules.json")
        if binding.get("selector_value") != rules_lookup["selector_value"]:
            errors.append(f"fragment {fragment_id} selector_value does not match rules.json")

        parts = entry.get("parts", [])
        if len(parts) != 2:
            errors.append(f"fragment {fragment_id} must contain exactly 2 parts")
            continue
        for part in parts:
            timeline = part.get("events", [])
            if not timeline:
                errors.append(f"fragment {fragment_id} part {part['part_index']} has no normalized events")
                continue
            duration_sum = sum(event["duration_quarter_length"] for event in timeline)
            if abs(duration_sum - entry["duration_quarter_length"]) > EPSILON:
                errors.append(
                    f"fragment {fragment_id} part {part['part_index']} duration does not close"
                )
            if abs(part["normalized_duration_quarter_length"] - entry["duration_quarter_length"]) > EPSILON:
                errors.append(
                    f"fragment {fragment_id} part {part['part_index']} normalized_duration_quarter_length mismatch"
                )
            previous_end = 0.0
            for event in timeline:
                if abs(event["offset_quarter_length"] - previous_end) > EPSILON:
                    errors.append(
                        f"fragment {fragment_id} part {part['part_index']} has a timeline gap or overlap"
                    )
                    break
                previous_end = event["end_offset_quarter_length"]
            if abs(previous_end - entry["duration_quarter_length"]) > EPSILON:
                errors.append(
                    f"fragment {fragment_id} part {part['part_index']} does not end at measure duration"
                )

    passed_checks = [check for check in report_payload.get("checks", []) if check["status"] == "passed"]
    failed_checks = [check for check in report_payload.get("checks", []) if check["status"] == "failed"]
    if len(passed_checks) != report_payload.get("summary", {}).get("checks_passed"):
        errors.append("validation_report.json checks_passed summary mismatch")
    if len(failed_checks) != report_payload.get("summary", {}).get("checks_failed"):
        errors.append("validation_report.json checks_failed summary mismatch")
    if report_payload.get("summary", {}).get("fragment_count") != 176:
        errors.append("validation_report.json fragment_count summary must equal 176")
    if report_payload.get("summary", {}).get("runtime_measure_count") != 176:
        errors.append("validation_report.json runtime_measure_count must equal 176")
    if report_payload.get("summary", {}).get("structural_measure_numbers") != [0]:
        errors.append("validation_report.json structural_measure_numbers must equal [0]")
    if report_payload.get("summary", {}).get("structural_measure_zero_occurrences") != len(measure_zero_entries):
        errors.append("validation_report.json structural_measure_zero_occurrences mismatch")
    if report_payload.get("errors") != []:
        errors.append("validation_report.json errors must be empty for a passed stage4 freeze")

    if errors:
        return fail(errors)

    structural_measure_zero_occurrences = report_payload["summary"]["structural_measure_zero_occurrences"]
    print("stage4 ingest validation passed")
    print("runtime-ready fragments: 176")
    print(
        "source measures retained: "
        f"{len(measure_entries)} (including structural measure 0 repeated "
        f"{structural_measure_zero_occurrences} times)"
    )
    print("selector domain: 2..12 with 16 positions")
    print("runtime can consume ingest/*.json without parsing mother_score.musicxml")
    return 0


if __name__ == "__main__":
    sys.exit(main())
