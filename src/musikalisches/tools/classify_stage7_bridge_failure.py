#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: dict) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=True, indent=2) + "\n",
        encoding="utf-8",
    )


def redact_text(raw_text: str, env_var_names: list[str]) -> tuple[str, list[str]]:
    redacted = raw_text
    applied: list[str] = []
    for env_var in env_var_names:
        value = os.environ.get(env_var, "")
        if value:
            marker = f"<redacted:{env_var}>"
            if value in redacted:
                redacted = redacted.replace(value, marker)
                applied.append(env_var)
    return redacted, applied


def classify_exit(raw_text: str, exit_code: int, taxonomy: dict) -> tuple[dict, list[str]]:
    lowered = raw_text.lower()
    classes = taxonomy.get("classes", [])

    for entry in classes:
        for matched_code in entry.get("match_exit_codes", []):
            if exit_code == matched_code:
                return entry, []

    for entry in classes:
        matches = [
            token for token in entry.get("match_any", []) if token and token.lower() in lowered
        ]
        if matches:
            return entry, matches

    default_class_id = taxonomy.get("default_class_id")
    for entry in classes:
        if entry.get("class_id") == default_class_id:
            return entry, []
    raise SystemExit("failure taxonomy default_class_id is missing from classes")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Classify a stage7 RTMPS bridge stderr log and persist a redacted runtime report."
    )
    parser.add_argument("--input-log", required=True, help="raw ffmpeg stderr log path")
    parser.add_argument("--output-log", required=True, help="redacted log output path")
    parser.add_argument("--output-report", required=True, help="runtime report JSON path")
    parser.add_argument("--failure-taxonomy", required=True, help="failure taxonomy JSON path")
    parser.add_argument("--exit-code", required=True, type=int, help="ffmpeg process exit code")
    parser.add_argument("--loop-mode", default="infinite", help="selected stage7 loop mode")
    parser.add_argument(
        "--max-runtime-seconds",
        default="0",
        help="requested max runtime seconds, or 0 when unset",
    )
    parser.add_argument(
        "--command-shell",
        default="",
        help="redacted shell command used to launch the bridge wrapper",
    )
    parser.add_argument(
        "--redact-env-var",
        action="append",
        default=[],
        help="environment variable name whose runtime value must be redacted from logs",
    )
    args = parser.parse_args()

    input_log = Path(args.input_log).resolve()
    output_log = Path(args.output_log).resolve()
    output_report = Path(args.output_report).resolve()
    taxonomy = load_json(Path(args.failure_taxonomy).resolve())
    raw_text = input_log.read_text(encoding="utf-8", errors="replace") if input_log.exists() else ""
    redacted_text, applied_redactions = redact_text(raw_text, args.redact_env_var)
    redacted_command_shell, applied_command_redactions = redact_text(
        args.command_shell,
        args.redact_env_var,
    )
    applied_redactions = sorted(set(applied_redactions) | set(applied_command_redactions))
    matched_class, matched_tokens = classify_exit(raw_text, args.exit_code, taxonomy)
    class_id = matched_class["class_id"]
    if class_id == "clean_exit":
        classification_status = "clean_exit"
    elif class_id == "runtime_limit_reached":
        classification_status = "runtime_limit_reached"
    elif class_id == "interrupted":
        classification_status = "interrupted"
    elif matched_class.get("retryable") is True:
        classification_status = "retryable_failure"
    else:
        classification_status = "terminal_failure"

    output_log.parent.mkdir(parents=True, exist_ok=True)
    output_report.parent.mkdir(parents=True, exist_ok=True)
    output_log.write_text(redacted_text, encoding="utf-8")
    write_json(
        output_report,
        {
            "stage": "stage7_stream_bridge_runtime",
            "status": classification_status,
            "exit_code": args.exit_code,
            "exit_class_id": class_id,
            "retryable": matched_class.get("retryable", False),
            "matched_tokens": matched_tokens,
            "loop_mode": args.loop_mode,
            "max_runtime_seconds": float(args.max_runtime_seconds or 0),
            "command_shell": redacted_command_shell,
            "taxonomy_id": taxonomy.get("taxonomy_id"),
            "log_file": str(output_log),
            "log_line_count": len(redacted_text.splitlines()),
            "redacted_env_vars_requested": args.redact_env_var,
            "redacted_env_vars_applied": applied_redactions,
        },
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
