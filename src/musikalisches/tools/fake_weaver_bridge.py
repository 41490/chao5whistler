#!/usr/bin/env python3
"""Local fake stage7 bridge for keyless weaver acceptance runs.

It stands in for the RTMPS bridge: instead of publishing to YouTube it verifies
the published asset (manifest present, every recorded sha256 matches the bytes
on disk) and journals the consumption. No stream key, no RTMPS URL, no network.

Journal lines are the evidence the weaver's checkpoint behaviour is built on, so
they are append-only and one line per accepted asset.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

MANIFEST_FILE = "weaver_asset_manifest.json"


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise SystemExit(f"fake bridge: cannot read {path}: {error}") from error


def journal_entries(journal_path: Path) -> list[dict]:
    if not journal_path.exists():
        return []
    entries = []
    for number, line in enumerate(journal_path.read_text(encoding="utf-8").splitlines(), start=1):
        line = line.strip()
        if not line:
            continue
        try:
            entries.append(json.loads(line))
        except json.JSONDecodeError as error:
            raise SystemExit(
                f"fake bridge: corrupt journal line {number} in {journal_path}: {error}"
            ) from error
    return entries


def verify_asset(asset_dir: Path) -> dict:
    manifest_path = asset_dir / MANIFEST_FILE
    if not manifest_path.is_file():
        raise SystemExit(f"fake bridge: missing {MANIFEST_FILE} in {asset_dir}")
    manifest = load_json(manifest_path)
    if manifest.get("generation_status") != "published":
        raise SystemExit(
            f"fake bridge: refusing a non-published asset (status={manifest.get('generation_status')})"
        )
    files = manifest.get("files")
    if not isinstance(files, list) or not files:
        raise SystemExit("fake bridge: asset manifest carries no files")
    for entry in files:
        name = entry.get("name")
        expected = entry.get("sha256")
        path = asset_dir / str(name)
        if not path.is_file():
            raise SystemExit(f"fake bridge: manifest lists missing file {name}")
        actual = sha256_file(path)
        if actual != expected:
            raise SystemExit(
                f"fake bridge: digest mismatch for {name}: manifest={expected} actual={actual}"
            )
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser(description="Local fake stage7 bridge (no ingest key needed).")
    parser.add_argument("--asset-dir", required=True, help="published asset directory")
    parser.add_argument("--journal", default="", help="append-only JSONL consumption journal")
    parser.add_argument(
        "--play-seconds",
        type=float,
        default=0.0,
        help="simulated real-time playback duration for this asset",
    )
    parser.add_argument(
        "--fail-on",
        action="append",
        default=[],
        help="combination_id that should fail (repeatable), for reconnect tests",
    )
    parser.add_argument(
        "--fail-times",
        type=int,
        default=1,
        help="how many times a --fail-on combination fails before succeeding",
    )
    args = parser.parse_args()

    asset_dir = Path(args.asset_dir)
    if not asset_dir.is_dir():
        print(f"fake bridge: asset dir does not exist: {asset_dir}", file=sys.stderr)
        return 3

    manifest = verify_asset(asset_dir)
    combination_id = str(manifest.get("combination_id"))
    journal_path = Path(args.journal) if args.journal else None
    prior = journal_entries(journal_path) if journal_path else []
    prior_failures = sum(
        1 for entry in prior if entry.get("combination_id") == combination_id and entry.get("failed")
    )

    if combination_id in args.fail_on and prior_failures < args.fail_times:
        if journal_path:
            journal_path.parent.mkdir(parents=True, exist_ok=True)
            with journal_path.open("a", encoding="utf-8") as handle:
                handle.write(
                    json.dumps(
                        {
                            "combination_id": combination_id,
                            "asset_id": manifest.get("asset_id"),
                            "failed": True,
                            "reason": "injected bridge failure",
                            "consumed_at": utc_now(),
                        },
                        ensure_ascii=True,
                    )
                    + "\n"
                )
        print(f"fake bridge: injected failure for {combination_id}", file=sys.stderr)
        return 1

    if args.play_seconds > 0:
        time.sleep(args.play_seconds)

    if journal_path:
        journal_path.parent.mkdir(parents=True, exist_ok=True)
        with journal_path.open("a", encoding="utf-8") as handle:
            handle.write(
                json.dumps(
                    {
                        "combination_id": combination_id,
                        "asset_id": manifest.get("asset_id"),
                        "record_id": manifest.get("record_id"),
                        "duration_seconds": manifest.get("duration_seconds"),
                        "play_seconds": args.play_seconds,
                        "verified_files": len(manifest.get("files", [])),
                        "sha256_verified": True,
                        "failed": False,
                        "consumed_at": utc_now(),
                    },
                    ensure_ascii=True,
                )
                + "\n"
            )

    print(
        f"fake bridge: accepted {combination_id} "
        f"({len(manifest.get('files', []))} files verified, {args.play_seconds}s simulated)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
