#!/usr/bin/env python3

import json
import sys
from pathlib import Path


def load_json(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def main() -> int:
    root = Path(__file__).resolve().parents[3]
    package_dir = root / "docs/study/music_dice_games_package/mozart_dicegame_print_1790s"
    manifest = load_json(package_dir / "source_manifest.json")
    page_trace = load_json(package_dir / "page_trace.json")
    identity_map = load_json(package_dir / "fragment_identity_map.json")
    rules = load_json(package_dir / "rules.json")
    lookup = load_json(root / "docs/study/music_source_basis_package/docs/mozart_16x11_table.json")

    errors = []

    if manifest.get("work_id") != "mozart_dicegame_print_1790s":
        errors.append("source_manifest work_id mismatch")
    if manifest.get("canonical_witness_id") != "rellstab_1790":
        errors.append("canonical witness must be rellstab_1790")
    if manifest.get("verification_witness_ids") != ["simrock_1793"]:
        errors.append("verification witness list must be ['simrock_1793']")

    witness_ids = [w["witness_id"] for w in manifest.get("witnesses", [])]
    if witness_ids != ["rellstab_1790", "simrock_1793"]:
        errors.append("source_manifest witness order or ids mismatch")

    trace_witness_ids = [w["witness_id"] for w in page_trace.get("witnesses", [])]
    if trace_witness_ids != witness_ids:
        errors.append("page_trace witness ids do not match source_manifest")

    if rules.get("positions") != 16:
        errors.append("rules.json positions must equal 16")
    allowed_values = rules.get("selector", {}).get("allowed_values")
    if allowed_values != list(range(2, 13)):
        errors.append("rules.json selector allowed_values must equal 2..12")
    if lookup.get("rolls") != list(range(2, 13)):
        errors.append("mozart_16x11_table.json rolls must equal 2..12")
    if len(lookup.get("columns", {})) != 16:
        errors.append("mozart_16x11_table.json must contain 16 columns")

    canonical_trace = page_trace["witnesses"][0]
    canonical_pages = [
        canvas
        for canvas in canonical_trace.get("scan_canvases", [])
        if canvas.get("kind") == "publication_page"
    ]
    if len(canonical_pages) != 8:
        errors.append("canonical page trace must contain 8 publication pages")
    if [page.get("publication_page") for page in canonical_pages] != list(range(1, 9)):
        errors.append("canonical publication pages must run from 1 to 8")

    if identity_map.get("canonical_witness_id") != "rellstab_1790":
        errors.append("fragment identity map must target rellstab_1790")

    locations = {}
    for page in identity_map.get("pages", []):
        publication_page = page["publication_page"]
        expected_canvas = next(
            (canvas for canvas in canonical_pages if canvas["publication_page"] == publication_page),
            None,
        )
        if expected_canvas is None:
            errors.append(f"identity page {publication_page} missing from page_trace")
            continue
        if page.get("scan_canvas_index") != expected_canvas.get("scan_canvas_index"):
            errors.append(
                f"identity page {publication_page} scan canvas index mismatch: "
                f"{page.get('scan_canvas_index')} != {expected_canvas.get('scan_canvas_index')}"
            )
        for row in page.get("rows", []):
            start = row["start_fragment_id"]
            end = row["end_fragment_id"]
            count = end - start + 1
            if row.get("slot_count") != count:
                errors.append(
                    f"page {publication_page} row {row['row_index']} slot_count mismatch"
                )
            for slot_index, fragment_id in enumerate(range(start, end + 1), start=1):
                if fragment_id in locations:
                    errors.append(f"duplicate fragment id in identity map: {fragment_id}")
                    continue
                locations[fragment_id] = {
                    "publication_page": publication_page,
                    "row_index": row["row_index"],
                    "slot_index": slot_index,
                }

    expected_fragment_ids = list(range(1, 177))
    if sorted(locations.keys()) != expected_fragment_ids:
        errors.append("fragment identity map must cover fragment ids 1..176 exactly once")

    rule_fragment_ids = []
    for column_name, fragments in lookup.get("columns", {}).items():
        if len(fragments) != 11:
            errors.append(f"lookup column {column_name} must contain 11 fragments")
        rule_fragment_ids.extend(fragments)

    if sorted(rule_fragment_ids) != expected_fragment_ids:
        errors.append("16x11 lookup table must contain fragment ids 1..176 exactly once")

    if set(rule_fragment_ids) != set(locations.keys()):
        errors.append("fragment identity map and 16x11 lookup table do not match")

    verification_trace = page_trace["witnesses"][1]
    if verification_trace.get("page_trace_status") != "file_level_frozen_only":
        errors.append("verification witness trace status must be file_level_frozen_only")
    if verification_trace.get("imslp_scan_pages") != 7:
        errors.append("verification witness must record 7 IMSLP scan pages")

    if errors:
        print("stage1 source freeze validation failed:")
        for error in errors:
            print(f"- {error}")
        return 1

    print("stage1 source freeze validation passed")
    print(f"canonical witness: {manifest['canonical_witness_id']}")
    print(f"fragment ids covered: {len(locations)}")
    print(
        "sample fragment locations: "
        f"1 -> {locations[1]}, "
        f"96 -> {locations[96]}, "
        f"176 -> {locations[176]}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
