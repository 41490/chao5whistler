#!/usr/bin/env python3

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path


CONTRACT_FILES = [
    "stream_bridge_manifest.json",
    "stage7_bridge_profile.json",
    "stream_bridge_ffmpeg_args.json",
    "stage7_failure_taxonomy.json",
    "stage7_soak_plan.json",
    "run_stage7_stream_bridge.sh",
    "stage7_bridge_validation_report.json",
    "stage7_soak_validation_report.json",
    "stage8_ops_readiness_report.json",
]


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: dict) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=True, indent=2) + "\n",
        encoding="utf-8",
    )


def write_text(path: Path, payload: str) -> None:
    path.write_text(payload, encoding="utf-8")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def build_file_digest(path: Path) -> dict:
    return {
        "file": path.name,
        "size_bytes": path.stat().st_size,
        "sha256": sha256_file(path),
    }


def fail(errors: list[str]) -> int:
    print("stage8 ops sample retention failed:")
    for error in errors:
        print(f"- {error}")
    return 1


def utc_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def sanitize_label(label: str) -> str:
    sanitized = re.sub(r"[^A-Za-z0-9._-]+", "-", label.strip()).strip(".-")
    if not sanitized:
        raise SystemExit("run label resolved to empty after sanitization")
    return sanitized


def resolve_path(base_dir: Path, raw_path: str) -> Path:
    path = Path(raw_path)
    return path if path.is_absolute() else (base_dir / path)


def copy_entry(source: Path, sample_dir: Path, relative_path: str, bucket: str) -> dict:
    destination = sample_dir / relative_path
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)
    return {
        "bucket": bucket,
        "relative_path": relative_path,
        "source_path": str(source),
        "retained_path": str(destination),
        "digest": build_file_digest(destination),
    }


def build_attempt_index(
    *,
    attempts: list[dict],
    artifact_dir: Path,
    sample_dir: Path,
) -> tuple[list[dict], list[dict], list[str]]:
    index_entries: list[dict] = []
    copied_entries: list[dict] = []
    errors: list[str] = []

    for attempt in attempts:
        attempt_index = attempt.get("attempt_index")
        log_path_raw = attempt.get("stderr_log_file")
        report_path_raw = attempt.get("exit_report_file")
        if not log_path_raw or not report_path_raw:
            errors.append(f"attempt {attempt_index}: missing stderr_log_file or exit_report_file")
            continue

        log_path = resolve_path(artifact_dir, log_path_raw)
        report_path = resolve_path(artifact_dir, report_path_raw)
        if not log_path.exists():
            errors.append(f"attempt {attempt_index}: missing log file {log_path}")
            continue
        if not report_path.exists():
            errors.append(f"attempt {attempt_index}: missing exit report file {report_path}")
            continue

        retained_log = f"logs/{log_path.name}"
        retained_report = f"logs/{report_path.name}"
        copied_entries.append(copy_entry(log_path, sample_dir, retained_log, "attempt"))
        copied_entries.append(copy_entry(report_path, sample_dir, retained_report, "attempt"))

        index_entries.append(
            {
                "attempt_index": attempt_index,
                "status": attempt.get("status"),
                "started_at": attempt.get("started_at"),
                "finished_at": attempt.get("finished_at"),
                "elapsed_seconds": attempt.get("elapsed_seconds"),
                "exit_code": attempt.get("exit_code"),
                "exit_class_id": attempt.get("exit_class_id"),
                "retryable": attempt.get("retryable"),
                "backoff_seconds_before_next": attempt.get("backoff_seconds_before_next"),
                "retained_log_file": retained_log,
                "retained_exit_report_file": retained_report,
            }
        )

    return index_entries, copied_entries, errors


def build_operator_summary(
    *,
    run_label: str,
    sample_dir: Path,
    preflight_report: dict,
    runtime_report: dict,
    exit_report: dict,
    attempt_index_file: str,
    runtime_digest_file: str,
) -> str:
    target = runtime_report.get("target") or preflight_report.get("target") or {}
    target_host = target.get("host", "<platform/host>")
    target_scheme = target.get("scheme", "rtmps")
    return "\n".join(
        [
            "# Stage8 Sample Summary",
            "",
            f"- run_label: {run_label}",
            f"- retained_sample_dir: {sample_dir}",
            f"- stage8 soak host: {target_scheme}://{target_host}",
            f"- preflight: {preflight_report.get('status')}",
            f"- preflight_failed_check_id: {preflight_report.get('failed_check_id') or '<none>'}",
            f"- runtime_status: {runtime_report.get('status')}",
            f"- runtime_duration_seconds: {runtime_report.get('elapsed_seconds')}",
            f"- attempts_total: {runtime_report.get('attempts_total')}",
            f"- final_exit_class_id: {runtime_report.get('final_exit_class_id') or exit_report.get('exit_class_id')}",
            "- drift observation: <none / details>",
            "- operator notes: <details>",
            "",
            "Artifacts:",
            f"- attempt log index: {attempt_index_file}",
            f"- runtime artifact digest: {runtime_digest_file}",
            "- preflight report: logs/stage7_bridge_preflight_report.json",
            "- runtime report: logs/stage7_bridge_runtime_report.json",
            "- exit report: logs/stage7_bridge_exit_report.json",
            "- latest stderr: logs/stage7_bridge_latest.stderr.log",
            "",
        ]
    )


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Retain stage8 preflight/soak sample artifacts into a self-contained bundle."
    )
    parser.add_argument(
        "artifact_dir",
        nargs="?",
        default="ops/out/stream-bridge",
        help="stage7 bridge artifact directory",
    )
    parser.add_argument(
        "--run-label",
        default="",
        help="stable label for the retained sample directory",
    )
    args = parser.parse_args()

    artifact_dir = Path(args.artifact_dir).resolve()
    if not artifact_dir.exists():
        return fail([f"artifact directory does not exist: {artifact_dir}"])

    manifest_path = artifact_dir / "stream_bridge_manifest.json"
    if not manifest_path.exists():
        return fail([f"missing manifest: {manifest_path}"])

    manifest = load_json(manifest_path)
    stage8_ops = manifest.get("stage8_ops", {})
    sample_retention = stage8_ops.get("sample_retention", {})
    if not isinstance(sample_retention, dict):
        return fail(["stream_bridge_manifest.json missing stage8_ops.sample_retention contract"])

    runtime_observability = manifest.get("runtime_observability", {})
    log_dir = artifact_dir / runtime_observability.get("log_dir", "logs")

    required_runtime_files = {
        "preflight_log": log_dir / runtime_observability.get("preflight_log_file", ""),
        "preflight_report": log_dir / runtime_observability.get("preflight_report_file", ""),
        "latest_stderr": log_dir / runtime_observability.get("stderr_log_file", ""),
        "exit_report": log_dir / runtime_observability.get("exit_report_file", ""),
        "runtime_report": log_dir / runtime_observability.get("runtime_report_file", ""),
    }
    missing_runtime = [
        f"{name}: {path}"
        for name, path in required_runtime_files.items()
        if not path.name or not path.exists()
    ]
    if missing_runtime:
        return fail(["missing runtime artifacts required for retention:"] + missing_runtime)

    missing_contract = [
        str(artifact_dir / file_name)
        for file_name in CONTRACT_FILES
        if not (artifact_dir / file_name).exists()
    ]
    if missing_contract:
        return fail(["missing contract artifacts:"] + missing_contract)

    runtime_report = load_json(required_runtime_files["runtime_report"])
    preflight_report = load_json(required_runtime_files["preflight_report"])
    exit_report = load_json(required_runtime_files["exit_report"])

    run_label = sanitize_label(args.run_label or utc_stamp())
    samples_dir = artifact_dir / sample_retention.get("samples_dir", "stage8-samples")
    sample_dir = samples_dir / run_label
    if sample_dir.exists():
        return fail([f"sample directory already exists: {sample_dir}"])
    sample_dir.mkdir(parents=True, exist_ok=False)

    copied_entries: list[dict] = []
    for file_name in CONTRACT_FILES:
        copied_entries.append(copy_entry(artifact_dir / file_name, sample_dir, file_name, "contract"))

    copied_entries.extend(
        [
            copy_entry(
                required_runtime_files["preflight_log"],
                sample_dir,
                f"logs/{required_runtime_files['preflight_log'].name}",
                "runtime",
            ),
            copy_entry(
                required_runtime_files["preflight_report"],
                sample_dir,
                f"logs/{required_runtime_files['preflight_report'].name}",
                "runtime",
            ),
            copy_entry(
                required_runtime_files["latest_stderr"],
                sample_dir,
                f"logs/{required_runtime_files['latest_stderr'].name}",
                "runtime",
            ),
            copy_entry(
                required_runtime_files["exit_report"],
                sample_dir,
                f"logs/{required_runtime_files['exit_report'].name}",
                "runtime",
            ),
            copy_entry(
                required_runtime_files["runtime_report"],
                sample_dir,
                f"logs/{required_runtime_files['runtime_report'].name}",
                "runtime",
            ),
        ]
    )

    optional_runtime_entries: list[dict] = []
    background_files = stage8_ops.get("background_files", {})
    for optional_name in ["console_log_file", "pid_file"]:
        optional_relative_path = background_files.get(optional_name)
        if not optional_relative_path:
            continue
        optional_source = artifact_dir / optional_relative_path
        if optional_source.exists():
            optional_runtime_entries.append(
                copy_entry(optional_source, sample_dir, optional_relative_path, "optional_runtime")
            )
    copied_entries.extend(optional_runtime_entries)

    attempt_index, attempt_entries, attempt_errors = build_attempt_index(
        attempts=runtime_report.get("attempts", []),
        artifact_dir=artifact_dir,
        sample_dir=sample_dir,
    )
    if attempt_errors:
        shutil.rmtree(sample_dir)
        return fail(attempt_errors)
    copied_entries.extend(attempt_entries)

    attempt_index_file = sample_retention.get("attempt_log_index_file", "attempt_log_index.json")
    runtime_digest_file = sample_retention.get(
        "runtime_artifact_digest_file",
        "runtime_artifact_digest.json",
    )
    retention_report_file = sample_retention.get(
        "retention_report_file",
        "stage8_sample_retention_report.json",
    )
    operator_summary_file = sample_retention.get(
        "operator_summary_template_file",
        "operator_summary_template.md",
    )

    attempt_index_payload = {
        "stage": "stage8_attempt_log_index",
        "run_label": run_label,
        "runtime_status": runtime_report.get("status"),
        "attempts_total": runtime_report.get("attempts_total"),
        "attempts_indexed": len(attempt_index),
        "attempts": attempt_index,
    }
    write_json(sample_dir / attempt_index_file, attempt_index_payload)

    runtime_digest_payload = {
        "stage": "stage8_runtime_artifact_digest",
        "run_label": run_label,
        "retained_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "preflight_status": preflight_report.get("status"),
        "runtime_status": runtime_report.get("status"),
        "final_exit_class_id": runtime_report.get("final_exit_class_id")
        or exit_report.get("exit_class_id"),
        "files": copied_entries,
    }
    write_json(sample_dir / runtime_digest_file, runtime_digest_payload)

    operator_summary = build_operator_summary(
        run_label=run_label,
        sample_dir=sample_dir,
        preflight_report=preflight_report,
        runtime_report=runtime_report,
        exit_report=exit_report,
        attempt_index_file=attempt_index_file,
        runtime_digest_file=runtime_digest_file,
    )
    write_text(sample_dir / operator_summary_file, operator_summary)

    retention_report = {
        "stage": "stage8_ops_sample_retention",
        "status": "captured",
        "run_label": run_label,
        "artifact_dir": str(artifact_dir),
        "sample_dir": str(sample_dir),
        "summary": {
            "work_id": manifest.get("work_id"),
            "preflight_status": preflight_report.get("status"),
            "runtime_status": runtime_report.get("status"),
            "runtime_elapsed_seconds": runtime_report.get("elapsed_seconds"),
            "attempts_total": runtime_report.get("attempts_total"),
            "final_exit_class_id": runtime_report.get("final_exit_class_id")
            or exit_report.get("exit_class_id"),
            "files_retained_total": len(copied_entries) + 4,
        },
        "outputs": {
            "operator_summary_template_file": operator_summary_file,
            "attempt_log_index_file": attempt_index_file,
            "runtime_artifact_digest_file": runtime_digest_file,
            "retention_report_file": retention_report_file,
        },
    }
    write_json(sample_dir / retention_report_file, retention_report)

    print("stage8 ops sample retention captured")
    print(f"artifact_dir: {artifact_dir}")
    print(f"run_label: {run_label}")
    print(f"sample_dir: {sample_dir}")
    print(f"operator_summary_template: {sample_dir / operator_summary_file}")
    print(f"retention_report: {sample_dir / retention_report_file}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
