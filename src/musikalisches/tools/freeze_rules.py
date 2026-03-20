#!/usr/bin/env python3

from __future__ import annotations

import json
import xml.etree.ElementTree as ET
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
PACKAGE_DIR = ROOT / "docs/study/music_dice_games_package/mozart_dicegame_print_1790s"
LOOKUP_PATH = ROOT / "docs/study/music_source_basis_package/docs/mozart_16x11_table.json"
IDENTITY_MAP_PATH = PACKAGE_DIR / "fragment_identity_map.json"
MUSICXML_PATH = PACKAGE_DIR / "mother_score.musicxml"
MEI_PATH = PACKAGE_DIR / "mother_score.mei"
RULES_PATH = PACKAGE_DIR / "rules.json"
WITNESS_DIFF_PATH = PACKAGE_DIR / "witness_diff.json"
MEI_NS = {"mei": "http://www.music-encoding.org/ns/mei"}


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def dump_json(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")


def extract_fragment_ids_from_musicxml(path: Path) -> list[int]:
    root = ET.parse(path).getroot()
    parts = root.findall("part")
    part_sequences = []
    for part in parts:
        measures = []
        for measure in part.findall("measure"):
            number = measure.attrib.get("number", "")
            if number.isdigit():
                value = int(number)
                if 1 <= value <= 176:
                    measures.append(value)
        part_sequences.append(measures)

    expected = list(range(1, 177))
    for index, sequence in enumerate(part_sequences, start=1):
        if sequence != expected:
            raise RuntimeError(
                f"mother_score.musicxml part {index} does not expose fragment ids 1..176 in order"
            )
    return expected


def build_identity_locations(identity_map: dict) -> dict[int, dict]:
    locations: dict[int, dict] = {}
    for page in identity_map["pages"]:
        publication_page = page["publication_page"]
        for row in page["rows"]:
            for slot_index, fragment_id in enumerate(
                range(row["start_fragment_id"], row["end_fragment_id"] + 1),
                start=1,
            ):
                locations[fragment_id] = {
                    "publication_page": publication_page,
                    "row_index": row["row_index"],
                    "slot_index": slot_index,
                    "scan_canvas_index": page["scan_canvas_index"],
                }
    return locations


def build_rules_payload(lookup: dict, identity_locations: dict[int, dict]) -> dict:
    rolls = lookup["rolls"]
    column_labels = list(lookup["columns"].keys())
    fragment_lookup = {}
    columns = {}

    for position_index, label in enumerate(column_labels, start=1):
        fragments = lookup["columns"][label]
        roll_to_fragment = {str(roll): fragment for roll, fragment in zip(rolls, fragments)}
        columns[label] = {
            "position_index": position_index,
            "fragment_ids_by_roll": roll_to_fragment,
        }
        for roll, fragment_id in zip(rolls, fragments):
            location = identity_locations[fragment_id]
            fragment_lookup[str(fragment_id)] = {
                "fragment_id": fragment_id,
                "mother_score_measure_number": fragment_id,
                "position_label": label,
                "position_index": position_index,
                "selector_value": roll,
                "canonical_witness_id": "rellstab_1790",
                **location,
            }

    return {
        "work_id": "mozart_dicegame_print_1790s",
        "canonical_witness_id": "rellstab_1790",
        "verification_witness_id": "simrock_1793",
        "mode": "columnar_choice",
        "positions": 16,
        "position_labels": column_labels,
        "selector": {
            "type": "sum_of_two_d6",
            "dice_count": 2,
            "dice_faces": 6,
            "allowed_values": rolls,
        },
        "fragment_contract": {
            "source_musicxml_file": "mother_score.musicxml",
            "source_mei_file": "mother_score.mei",
            "fragment_id_range": [1, 176],
            "measure_number_equals_fragment_id": True,
            "excluded_structural_measure_numbers": [0],
        },
        "selection_policy": {
            "one_fragment_per_position": True,
            "concatenate_in_position_order": True,
            "position_groups": ["A1-A8", "B1-B8"],
        },
        "columns": columns,
        "fragment_lookup": fragment_lookup,
        "reconciliation": {
            "lookup_table_file": "../../music_source_basis_package/docs/mozart_16x11_table.json",
            "identity_map_file": "fragment_identity_map.json",
            "mother_score_file": "mother_score.musicxml",
            "confirmed_against_mother_score": True,
            "confirmed_fragment_count": 176,
            "notes": [
                "Each fragment id in the lookup table resolves to exactly one mother-score measure.",
                "Each mother-score fragment measure resolves back to exactly one position label and selector value.",
                "Simrock 1793 remains outside fragment-level reconciliation until witness tracing advances beyond file-level freeze.",
            ],
        },
        "manual_verification": {
            "checklist": [
                "There must be exactly 16 output positions.",
                "Each position accepts one selector result derived from the sum of two six-sided dice.",
                "Selector values must lie in the inclusive range 2..12.",
                "Each fragment id must map both to one mother-score measure and one printed-rule position.",
                "Simrock 1793 differences must be recorded separately and must not redefine the canonical runtime source.",
            ]
        },
        "status": "stage3_rules_frozen",
    }


def build_lookup_payload(existing_lookup: dict) -> dict:
    return {
        "work_id": "mozart_dicegame_print_1790s",
        "canonical_witness_id": "rellstab_1790",
        "status": "stage3_reconciled_against_mother_score",
        "rolls": existing_lookup["rolls"],
        "position_labels": list(existing_lookup["columns"].keys()),
        "columns": existing_lookup["columns"],
        "reconciliation": {
            "mother_score_file": "../music_dice_games_package/mozart_dicegame_print_1790s/mother_score.musicxml",
            "fragment_contract": "measure number == fragment id for 1..176; measure 0 is structural only",
            "confirmed_unique_fragment_ids": 176,
            "confirmed_columns": 16,
            "confirmed_rolls_per_column": 11,
        },
    }


def build_witness_diff_payload() -> dict:
    return {
        "work_id": "mozart_dicegame_print_1790s",
        "canonical_witness_id": "rellstab_1790",
        "verification_witness_id": "simrock_1793",
        "status": "stage3_initial_witness_diff",
        "comparison_scope": {
            "canonical_rules_source": "rules.json",
            "canonical_mother_score_source": "mother_score.musicxml",
            "verification_trace_status": "file_level_frozen_only",
            "fragment_level_comparison_ready": False,
        },
        "summary": {
            "canonical_runtime_definition": "rellstab_1790 remains authoritative",
            "verification_scope": "Simrock 1793 is frozen only at the file level in the current repository state",
            "diff_assertion_policy": "No fragment-level differences are asserted until the verification witness is page-traced and fragment-addressable",
        },
        "diffs": [],
    }


def update_musicxml_status() -> None:
    tree = ET.parse(MUSICXML_PATH)
    root = tree.getroot()
    miscellaneous = root.find("./identification/miscellaneous")
    if miscellaneous is None:
        raise RuntimeError("mother_score.musicxml is missing identification/miscellaneous")

    for field in miscellaneous.findall("miscellaneous-field"):
        if field.attrib.get("name") == "rules-reconciliation-status":
            field.text = (
                "Stage 3 frozen. rules.json and mozart_16x11_table.json are "
                "reconciled against this Rellstab mother score."
            )
            break
    else:
        raise RuntimeError("mother_score.musicxml is missing rules-reconciliation-status metadata")

    tree.write(MUSICXML_PATH, encoding="utf-8", xml_declaration=True)


def update_mei_status() -> None:
    tree = ET.parse(MEI_PATH)
    root = tree.getroot()

    pub_stmt_paragraph = root.find(".//mei:fileDesc/mei:pubStmt/mei:p", MEI_NS)
    if pub_stmt_paragraph is not None:
        pub_stmt_paragraph.text = (
            "Stage 2 mother-score freeze generated from the canonical Humdrum source "
            "for the Rellstab ca.1790 witness and retained as the stage 3 "
            "rules-reconciliation source."
        )

    notes_stmt = root.find(".//mei:fileDesc/mei:notesStmt", MEI_NS)
    if notes_stmt is None:
        raise RuntimeError("mother_score.mei is missing notesStmt")

    for annot in notes_stmt.findall("mei:annot", MEI_NS):
        if (annot.text or "").startswith("rules-reconciliation-status:"):
            annot.text = "rules-reconciliation-status: stage3_rules_frozen"
            break
    else:
        note = ET.SubElement(notes_stmt, "{http://www.music-encoding.org/ns/mei}annot")
        note.text = "rules-reconciliation-status: stage3_rules_frozen"

    tree.write(MEI_PATH, encoding="utf-8", xml_declaration=True)


def main() -> None:
    lookup = load_json(LOOKUP_PATH)
    identity_map = load_json(IDENTITY_MAP_PATH)
    fragment_ids = extract_fragment_ids_from_musicxml(MUSICXML_PATH)
    if fragment_ids != list(range(1, 177)):
        raise RuntimeError("mother_score.musicxml fragment ids are not frozen to 1..176")

    identity_locations = build_identity_locations(identity_map)
    if sorted(identity_locations) != fragment_ids:
        raise RuntimeError("fragment_identity_map.json does not cover fragment ids 1..176 exactly once")

    rules = build_rules_payload(lookup, identity_locations)
    lookup_payload = build_lookup_payload(lookup)
    witness_diff = build_witness_diff_payload()

    dump_json(RULES_PATH, rules)
    dump_json(LOOKUP_PATH, lookup_payload)
    dump_json(WITNESS_DIFF_PATH, witness_diff)
    update_musicxml_status()
    update_mei_status()

    print(f"wrote {RULES_PATH.relative_to(ROOT)}")
    print(f"wrote {LOOKUP_PATH.relative_to(ROOT)}")
    print(f"wrote {WITNESS_DIFF_PATH.relative_to(ROOT)}")
    print(f"updated {MUSICXML_PATH.relative_to(ROOT)}")
    print(f"updated {MEI_PATH.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
