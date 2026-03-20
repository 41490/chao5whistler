#!/usr/bin/env python3

from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path

import warnings

warnings.filterwarnings("ignore")

from music21 import converter  # type: ignore


ROOT = Path(__file__).resolve().parents[3]
PACKAGE_DIR = ROOT / "docs/study/music_dice_games_package/mozart_dicegame_print_1790s"
SOURCE_PATH = PACKAGE_DIR / "mother_score.source.k516f.krn"
MUSICXML_PATH = PACKAGE_DIR / "mother_score.musicxml"
MEI_PATH = PACKAGE_DIR / "mother_score.mei"
MEI_NS = {"mei": "http://www.music-encoding.org/ns/mei"}


def fail(message: str) -> int:
    print(f"stage2 mother-score validation failed: {message}")
    return 1


def validate_musicxml() -> tuple[bool, str]:
    text = MUSICXML_PATH.read_text(encoding="utf-8")
    if "template-placeholder" in text or "Template only" in text:
        return False, "mother_score.musicxml still contains placeholder text"

    score = converter.parse(str(MUSICXML_PATH))
    if len(score.parts) != 2:
        return False, "mother_score.musicxml must contain exactly 2 parts"

    for index, part in enumerate(score.parts, start=1):
        numbered = [
            measure.number
            for measure in part.getElementsByClass("Measure")
            if isinstance(measure.number, int) and 1 <= measure.number <= 176
        ]
        if numbered != list(range(1, 177)):
            return False, f"part {index} does not contain fragment measures 1..176 in order"

    time_signatures = {
        ts.ratioString for ts in score.recurse().getElementsByClass("TimeSignature")
    }
    if time_signatures != {"3/8"}:
        return False, f"mother_score.musicxml time signatures are not frozen to 3/8: {time_signatures}"

    required_strings = [
        "canonical-witness-id",
        "rellstab_1790",
        "fragment-id-contract",
        "rules-reconciliation-status",
    ]
    for item in required_strings:
        if item not in text:
            return False, f"mother_score.musicxml is missing metadata marker: {item}"

    return True, "musicxml ok"


def read_rules_reconciliation_status() -> str:
    tree = ET.parse(MUSICXML_PATH)
    root = tree.getroot()
    for field in root.findall("./identification/miscellaneous/miscellaneous-field"):
        if field.attrib.get("name") == "rules-reconciliation-status":
            return field.text or "unknown"
    return "missing"


def validate_mei() -> tuple[bool, str]:
    text = MEI_PATH.read_text(encoding="utf-8")
    if "template placeholder" in text:
        return False, "mother_score.mei still contains placeholder text"

    tree = ET.parse(MEI_PATH)
    measures = tree.findall(".//mei:measure", MEI_NS)
    fragment_measures = [
        measure
        for measure in measures
        if measure.attrib.get("n", "").isdigit()
        and 1 <= int(measure.attrib["n"]) <= 176
    ]
    numbers = [int(measure.attrib["n"]) for measure in fragment_measures]
    if numbers != list(range(1, 177)):
        return False, "mother_score.mei does not contain fragment measures 1..176 in order"

    ids = [measure.attrib.get("{http://www.w3.org/XML/1998/namespace}id") for measure in fragment_measures]
    expected_ids = [f"frag{i:03d}" for i in range(1, 177)]
    if ids != expected_ids:
        return False, "mother_score.mei xml:id contract does not match frag001..frag176"

    staff_defs = tree.findall(".//mei:staffDef", MEI_NS)
    if len(staff_defs) != 2:
        return False, "mother_score.mei must contain exactly 2 staff definitions"

    if "Musikalisches Wuerfelspiel" not in text or "rellstab_1790" not in text:
        return False, "mother_score.mei is missing frozen title or witness metadata"

    return True, "mei ok"


def main() -> int:
    for path in (SOURCE_PATH, MUSICXML_PATH, MEI_PATH):
        if not path.exists():
            return fail(f"missing required file: {path.relative_to(ROOT)}")

    source_text = SOURCE_PATH.read_text(encoding="utf-8")
    if "!!!SMS: Rellstabschen Musikhandlung, Op. 142, Berlin: c.1790" not in source_text:
        return fail("mother_score.source.k516f.krn does not match the expected Rellstab source marker")

    ok, reason = validate_musicxml()
    if not ok:
        return fail(reason)

    ok, reason = validate_mei()
    if not ok:
        return fail(reason)

    print("stage2 mother-score validation passed")
    print("canonical source: mother_score.source.k516f.krn")
    print("fragment contract: measure number == fragment id for 1..176")
    print(f"rules reconciliation: {read_rules_reconciliation_status()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
