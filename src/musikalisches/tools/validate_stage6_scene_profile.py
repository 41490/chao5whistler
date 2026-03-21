#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
from pathlib import Path

from stage6_scene_profile import (
    DEFAULT_SCENE_PROFILE_PATH,
    SCENE_PROFILE_SCHEMA_PATH,
    load_json,
    validate_scene_profile_payload,
)


def fail(errors: list[str]) -> int:
    print("stage6 scene profile validation failed:")
    for error in errors:
        print(f"- {error}")
    return 1


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Validate a stage6 scene profile contract."
    )
    parser.add_argument(
        "profile_path",
        nargs="?",
        default=str(DEFAULT_SCENE_PROFILE_PATH),
        help="scene profile JSON path",
    )
    args = parser.parse_args()

    profile_path = Path(args.profile_path).resolve()
    if not profile_path.exists():
        return fail([f"scene profile does not exist: {profile_path}"])

    try:
        profile = load_json(profile_path)
    except json.JSONDecodeError as exc:
        return fail([f"invalid JSON in {profile_path}: {exc}"])

    errors = validate_scene_profile_payload(profile, allow_output_metadata=True)
    if errors:
        return fail(errors)

    print("stage6 scene profile validation passed")
    print(f"profile_file: {profile_path}")
    print(f"schema_file: {SCENE_PROFILE_SCHEMA_PATH}")
    print(f"profile_id: {profile['profile_id']}")
    print(
        "canvas: "
        f"{profile['canvas']['width']}x{profile['canvas']['height']}@{profile['canvas']['fps']}"
    )
    print(f"motion_mode: {profile['motion']['mode']}")
    print(f"palette_id: {profile['palette']['palette_id']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
