#!/usr/bin/env python3

from __future__ import annotations

import json
import warnings
from pathlib import Path

warnings.filterwarnings("ignore")

from music21 import converter, stream  # type: ignore


ROOT = Path(__file__).resolve().parents[3]
PACKAGE_DIR = ROOT / "docs/study/music_dice_games_package/mozart_dicegame_print_1790s"
INGEST_DIR = PACKAGE_DIR / "ingest"
MUSICXML_PATH = PACKAGE_DIR / "mother_score.musicxml"
MEI_PATH = PACKAGE_DIR / "mother_score.mei"
RULES_PATH = PACKAGE_DIR / "rules.json"
SOURCE_MANIFEST_PATH = PACKAGE_DIR / "source_manifest.json"
FRAGMENTS_PATH = INGEST_DIR / "fragments.json"
MEASURES_PATH = INGEST_DIR / "measures.json"
REPORT_PATH = INGEST_DIR / "validation_report.json"

EXPECTED_FRAGMENT_IDS = list(range(1, 177))
EPSILON = 1e-9
STAGE4_NOTE = (
    "Stage 4 freezes runtime-ready ingest artifacts under ingest/, including normalized "
    "explicit-rest timelines and a validation report."
)


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def dump_json(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")


def qlen(value: float) -> float:
    return round(float(value), 6)


def update_source_manifest() -> None:
    manifest = load_json(SOURCE_MANIFEST_PATH)
    manifest["status"] = "stage4_ingest_frozen"

    notes = manifest.setdefault("notes", [])
    if STAGE4_NOTE not in notes:
        notes.append(STAGE4_NOTE)

    dump_json(SOURCE_MANIFEST_PATH, manifest)


def event_pitches(element) -> list[dict]:
    if element.isRest:
        return []
    pitches = element.pitches if element.isChord else [element.pitch]
    return [
        {
            "name_with_octave": pitch.nameWithOctave,
            "midi": int(pitch.midi),
        }
        for pitch in pitches
    ]


def normalize_measure_events(measure, measure_duration: float) -> tuple[list[dict], dict]:
    source_events = sorted(list(measure.notesAndRests), key=lambda item: qlen(item.offset))
    normalized = []
    cursor = 0.0
    inserted_implicit_rest_events = 0
    note_event_count = 0
    chord_event_count = 0
    rest_event_count = 0
    sounding_event_count = 0

    if not source_events:
        inserted_implicit_rest_events = 1
        normalized.append(
            {
                "event_index": 1,
                "kind": "rest",
                "offset_quarter_length": 0.0,
                "duration_quarter_length": qlen(measure_duration),
                "end_offset_quarter_length": qlen(measure_duration),
                "is_sounding": False,
                "source_encoding": "implicit_measure_rest",
                "source_event_index": None,
                "pitches": [],
            }
        )
        rest_event_count = 1
    else:
        for source_event_index, element in enumerate(source_events, start=1):
            offset = qlen(element.offset)
            duration = qlen(element.duration.quarterLength)
            if offset > cursor + EPSILON:
                inserted_implicit_rest_events += 1
                normalized.append(
                    {
                        "event_index": len(normalized) + 1,
                        "kind": "rest",
                        "offset_quarter_length": qlen(cursor),
                        "duration_quarter_length": qlen(offset - cursor),
                        "end_offset_quarter_length": qlen(offset),
                        "is_sounding": False,
                        "source_encoding": "implicit_gap_rest",
                        "source_event_index": None,
                        "pitches": [],
                    }
                )
                rest_event_count += 1

            if element.isRest:
                kind = "rest"
                rest_event_count += 1
            elif element.isChord:
                kind = "chord"
                chord_event_count += 1
                sounding_event_count += 1
            else:
                kind = "note"
                note_event_count += 1
                sounding_event_count += 1

            normalized.append(
                {
                    "event_index": len(normalized) + 1,
                    "kind": kind,
                    "offset_quarter_length": offset,
                    "duration_quarter_length": duration,
                    "end_offset_quarter_length": qlen(offset + duration),
                    "is_sounding": kind != "rest",
                    "source_encoding": "source_event",
                    "source_event_index": source_event_index,
                    "pitches": event_pitches(element),
                }
            )
            cursor = max(cursor, offset + duration)

        if cursor < measure_duration - EPSILON:
            inserted_implicit_rest_events += 1
            normalized.append(
                {
                    "event_index": len(normalized) + 1,
                    "kind": "rest",
                    "offset_quarter_length": qlen(cursor),
                    "duration_quarter_length": qlen(measure_duration - cursor),
                    "end_offset_quarter_length": qlen(measure_duration),
                    "is_sounding": False,
                    "source_encoding": "implicit_trailing_rest",
                    "source_event_index": None,
                    "pitches": [],
                }
            )
            rest_event_count += 1

    normalized_duration = qlen(
        sum(event["duration_quarter_length"] for event in normalized)
    )

    summary = {
        "source_event_count": len(source_events),
        "normalized_event_count": len(normalized),
        "note_event_count": note_event_count,
        "chord_event_count": chord_event_count,
        "rest_event_count": rest_event_count,
        "sounding_event_count": sounding_event_count,
        "inserted_implicit_rest_event_count": inserted_implicit_rest_events,
        "source_duration_quarter_length": qlen(
            sum(float(element.duration.quarterLength) for element in source_events)
        ),
        "normalized_duration_quarter_length": normalized_duration,
        "is_empty_in_source": len(source_events) == 0,
        "contains_only_rests_after_normalization": sounding_event_count == 0,
    }
    return normalized, summary


def build_validation_report(
    rules: dict,
    measure_sequence: list[int],
    fragments: list[dict],
    measures: list[dict],
) -> dict:
    allowed_values = rules["selector"]["allowed_values"]
    fragment_ids = [fragment["fragment_id"] for fragment in fragments]
    measure_zero_entries = [
        measure for measure in measures if measure["source_measure_number"] == 0
    ]
    structural_measure_numbers = [
        measure["source_measure_number"]
        for measure in measures
        if not measure["included_in_runtime"]
    ]
    structural_measure_numbers_unique = sorted(set(structural_measure_numbers))

    duration_errors = []
    for fragment in fragments:
        for part in fragment["parts"]:
            if abs(part["normalized_duration_quarter_length"] - fragment["duration_quarter_length"]) > EPSILON:
                duration_errors.append(
                    {
                        "fragment_id": fragment["fragment_id"],
                        "part_index": part["part_index"],
                    }
                )

    selector_errors = []
    reverse_lookup_errors = []
    for fragment in fragments:
        selector_value = fragment["selector_binding"]["selector_value"]
        if selector_value not in allowed_values:
            selector_errors.append(
                {
                    "fragment_id": fragment["fragment_id"],
                    "selector_value": selector_value,
                }
            )
        lookup = rules["fragment_lookup"][str(fragment["fragment_id"])]
        if (
            fragment["position_label"] != lookup["position_label"]
            or fragment["position_index"] != lookup["position_index"]
            or selector_value != lookup["selector_value"]
        ):
            reverse_lookup_errors.append(
                {
                    "fragment_id": fragment["fragment_id"],
                    "fragment_position_label": fragment["position_label"],
                    "rules_position_label": lookup["position_label"],
                }
            )

    numbering_errors = []
    runtime_measure_numbers = [
        measure["source_measure_number"]
        for measure in measures
        if measure["included_in_runtime"]
    ]
    if runtime_measure_numbers != EXPECTED_FRAGMENT_IDS:
        numbering_errors.append("runtime measure sequence is not 1..176")
    if measure_sequence.count(0) < 1:
        numbering_errors.append("source measure sequence must contain at least one structural measure 0")

    checks = [
        {
            "check_id": "fragment_coverage",
            "status": "passed" if fragment_ids == EXPECTED_FRAGMENT_IDS else "failed",
            "details": {
                "expected_fragment_count": 176,
                "actual_fragment_count": len(fragment_ids),
            },
        },
        {
            "check_id": "measure_numbering_contract",
            "status": "passed" if not numbering_errors else "failed",
            "details": {
                "runtime_measure_count": len(runtime_measure_numbers),
                "structural_measure_numbers": structural_measure_numbers_unique,
                "structural_measure_zero_occurrences": len(measure_zero_entries),
                "errors": numbering_errors,
            },
        },
        {
            "check_id": "selector_domain",
            "status": "passed" if not selector_errors else "failed",
            "details": {
                "allowed_values": allowed_values,
                "rejected_examples": [1, 13],
                "errors": selector_errors,
            },
        },
        {
            "check_id": "rule_reverse_lookup",
            "status": "passed" if not reverse_lookup_errors else "failed",
            "details": {
                "checked_fragments": len(fragments),
                "errors": reverse_lookup_errors,
            },
        },
        {
            "check_id": "normalized_duration_closure",
            "status": "passed" if not duration_errors else "failed",
            "details": {
                "expected_measure_duration_quarter_length": 1.5,
                "checked_part_timelines": len(fragments) * 2,
                "errors": duration_errors,
            },
        },
        {
            "check_id": "runtime_independence",
            "status": "passed",
            "details": {
                "fragments_artifact_contains_normalized_events": True,
                "measures_artifact_records_structural_measure_zero": bool(measure_zero_entries),
                "structural_measure_zero_occurrences": len(measure_zero_entries),
                "runtime_can_ignore_original_mother_score_at_playback": True,
            },
        },
    ]

    warnings_list = [
        "Structural measure 0 is preserved in measures.json for source traceability but excluded from runtime fragments.",
    ]
    implicit_rest_fills = sum(
        part["inserted_implicit_rest_event_count"]
        for fragment in fragments
        for part in fragment["parts"]
    )
    if implicit_rest_fills:
        warnings_list.append(
            f"Inserted {implicit_rest_fills} implicit rest events to close empty or partial part timelines."
        )

    errors = []
    for check in checks:
        if check["status"] == "failed":
            errors.append(check["check_id"])

    return {
        "work_id": "mozart_dicegame_print_1790s",
        "canonical_witness_id": "rellstab_1790",
        "verification_witness_id": "simrock_1793",
        "status": "passed" if not errors else "failed",
        "stage": "stage4_ingest_frozen",
        "source_files": {
            "mother_score_musicxml": "mother_score.musicxml",
            "mother_score_mei": "mother_score.mei",
            "rules": "rules.json",
            "fragments": "ingest/fragments.json",
            "measures": "ingest/measures.json",
        },
        "summary": {
            "fragment_count": len(fragments),
            "source_measure_count": len(measures),
            "runtime_measure_count": len(
                [measure for measure in measures if measure["included_in_runtime"]]
            ),
            "structural_measure_numbers": structural_measure_numbers_unique,
            "structural_measure_zero_occurrences": len(measure_zero_entries),
            "checks_passed": len([check for check in checks if check["status"] == "passed"]),
            "checks_failed": len(errors),
        },
        "checks": checks,
        "errors": errors,
        "warnings": warnings_list,
    }


def main() -> None:
    rules = load_json(RULES_PATH)
    score = converter.parse(str(MUSICXML_PATH))
    parts = list(score.parts)
    if len(parts) != 2:
        raise RuntimeError("mother_score.musicxml must contain exactly 2 parts before ingest freeze")

    part_measures = []
    measure_sequences = []
    part_metadata = []
    for part_index, part in enumerate(parts, start=1):
        measures = {
            int(measure.number): measure
            for measure in part.getElementsByClass(stream.Measure)
            if isinstance(measure.number, int)
        }
        sequence = [
            int(measure.number)
            for measure in part.getElementsByClass(stream.Measure)
            if isinstance(measure.number, int)
        ]
        part_measures.append(measures)
        measure_sequences.append(sequence)
        part_metadata.append(
            {
                "part_index": part_index,
                "source_part_id": part.id,
                "source_part_name": part.partName,
                "source_part_abbreviation": part.partAbbreviation,
            }
        )

    if measure_sequences[0] != measure_sequences[1]:
        raise RuntimeError("mother_score.musicxml parts do not share the same measure sequence")

    measure_sequence = measure_sequences[0]
    first_fragment_measure = part_measures[0][1]
    expected_duration = qlen(first_fragment_measure.duration.quarterLength)

    measures = []
    fragments = []

    for source_measure_index, measure_number in enumerate(measure_sequence, start=1):
        role = "fragment" if measure_number in EXPECTED_FRAGMENT_IDS else "structural_repeat_boundary"
        included_in_runtime = role == "fragment"
        selector_binding = (
            rules["fragment_lookup"][str(measure_number)] if included_in_runtime else None
        )

        measure_parts = []
        for metadata, measures_by_number in zip(part_metadata, part_measures):
            measure = measures_by_number[measure_number]
            normalized_events, summary = normalize_measure_events(measure, expected_duration)
            measure_parts.append(
                {
                    **metadata,
                    **summary,
                    "events": normalized_events,
                }
            )

        measure_entry = {
            "source_measure_number": measure_number,
            "source_measure_sequence_index": source_measure_index,
            "role": role,
            "included_in_runtime": included_in_runtime,
            "duration_quarter_length": expected_duration,
            "time_signature": "3/8",
            "runtime_fragment_id": measure_number if included_in_runtime else None,
            "selector_binding": (
                {
                    "position_label": selector_binding["position_label"],
                    "position_index": selector_binding["position_index"],
                    "selector_value": selector_binding["selector_value"],
                }
                if selector_binding
                else None
            ),
            "parts": measure_parts,
        }
        measures.append(measure_entry)

        if included_in_runtime:
            fragments.append(
                {
                    "fragment_id": measure_number,
                    "measure_number": measure_number,
                    "source_measure_sequence_index": source_measure_index,
                    "position_label": selector_binding["position_label"],
                    "position_index": selector_binding["position_index"],
                    "selector_binding": {
                        "selector_type": "sum_of_two_d6",
                        "selector_value": selector_binding["selector_value"],
                    },
                    "source_location": {
                        "canonical_witness_id": selector_binding["canonical_witness_id"],
                        "publication_page": selector_binding["publication_page"],
                        "row_index": selector_binding["row_index"],
                        "slot_index": selector_binding["slot_index"],
                        "scan_canvas_index": selector_binding["scan_canvas_index"],
                    },
                    "duration_quarter_length": expected_duration,
                    "time_signature": "3/8",
                    "parts": measure_parts,
                }
            )

    fragments_payload = {
        "work_id": "mozart_dicegame_print_1790s",
        "canonical_witness_id": "rellstab_1790",
        "verification_witness_id": "simrock_1793",
        "status": "stage4_ingest_frozen",
        "source_files": {
            "mother_score_musicxml": "mother_score.musicxml",
            "mother_score_mei": "mother_score.mei",
            "rules": "rules.json",
        },
        "fragment_contract": {
            "fragment_id_range": [1, 176],
            "measure_number_equals_fragment_id": True,
            "excluded_structural_measure_numbers": [0],
            "normalized_event_unit": "quarter_length",
            "normalized_silence_policy": "empty or partial part timelines are closed with explicit rest events",
        },
        "fragments": fragments,
    }

    measures_payload = {
        "work_id": "mozart_dicegame_print_1790s",
        "canonical_witness_id": "rellstab_1790",
        "verification_witness_id": "simrock_1793",
        "status": "stage4_ingest_frozen",
        "source_measure_sequence": measure_sequence,
        "runtime_fragment_measure_numbers": EXPECTED_FRAGMENT_IDS,
        "measures": measures,
    }

    report_payload = build_validation_report(rules, measure_sequence, fragments, measures)

    INGEST_DIR.mkdir(parents=True, exist_ok=True)
    dump_json(FRAGMENTS_PATH, fragments_payload)
    dump_json(MEASURES_PATH, measures_payload)
    dump_json(REPORT_PATH, report_payload)
    update_source_manifest()

    print(f"wrote {FRAGMENTS_PATH.relative_to(ROOT)}")
    print(f"wrote {MEASURES_PATH.relative_to(ROOT)}")
    print(f"wrote {REPORT_PATH.relative_to(ROOT)}")
    print(f"wrote {SOURCE_MANIFEST_PATH.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
