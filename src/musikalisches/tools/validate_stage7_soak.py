#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
from math import ceil
from pathlib import Path


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: dict) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=True, indent=2) + "\n",
        encoding="utf-8",
    )


def build_check(check_id: str, passed: bool, details: dict) -> dict:
    return {
        "check_id": check_id,
        "status": "passed" if passed else "failed",
        "details": details,
    }


def fail(errors: list[str]) -> int:
    print("stage7 soak validation failed:")
    for error in errors:
        print(f"- {error}")
    return 1


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Validate the pre-stage8 soak readiness contract derived from a stage7 bridge artifact directory."
    )
    parser.add_argument(
        "artifact_dir",
        nargs="?",
        default="ops/out/stream-bridge",
        help="stage7 bridge artifact directory containing stage7_soak_plan.json",
    )
    args = parser.parse_args()

    artifact_dir = Path(args.artifact_dir).resolve()
    if not artifact_dir.exists():
        return fail([f"artifact directory does not exist: {artifact_dir}"])

    manifest_path = artifact_dir / "stream_bridge_manifest.json"
    soak_plan_path = artifact_dir / "stage7_soak_plan.json"
    failure_taxonomy_path = artifact_dir / "stage7_failure_taxonomy.json"
    if not manifest_path.exists() or not soak_plan_path.exists() or not failure_taxonomy_path.exists():
        return fail(
            [
                "missing required soak files: stream_bridge_manifest.json, "
                "stage7_soak_plan.json, stage7_failure_taxonomy.json"
            ]
        )

    manifest = load_json(manifest_path)
    soak_plan = load_json(soak_plan_path)
    failure_taxonomy = load_json(failure_taxonomy_path)
    runtime_observability = manifest.get("runtime_observability", {})
    log_dir = artifact_dir / runtime_observability.get("log_dir", "")
    runtime_report_path = (
        log_dir / runtime_observability.get("exit_report_file", "")
        if runtime_observability.get("exit_report_file")
        else None
    )
    stderr_log_path = (
        log_dir / runtime_observability.get("stderr_log_file", "")
        if runtime_observability.get("stderr_log_file")
        else None
    )

    class_ids = {
        entry.get("class_id")
        for entry in failure_taxonomy.get("classes", [])
        if isinstance(entry, dict)
    }
    retryable_class_ids = {
        entry.get("class_id")
        for entry in failure_taxonomy.get("classes", [])
        if isinstance(entry, dict) and entry.get("retryable") is True
    }
    checks: list[dict] = []

    expected_loops = None
    minimum_runtime_seconds = soak_plan.get("minimum_runtime_seconds")
    source_duration_seconds = soak_plan.get("source_duration_seconds")
    if minimum_runtime_seconds and source_duration_seconds:
        expected_loops = ceil(minimum_runtime_seconds / source_duration_seconds)

    checks.append(
        build_check(
            "stage_identity",
            manifest.get("stage") == "stage7_stream_bridge"
            and soak_plan.get("stage") == "stage7_pre_stage8_soak",
            {
                "manifest_stage": manifest.get("stage"),
                "soak_stage": soak_plan.get("stage"),
            },
        )
    )
    checks.append(
        build_check(
            "loop_readiness",
            manifest.get("loop_bridge", {}).get("default_loop_mode") == "infinite"
            and manifest.get("loop_bridge", {}).get("loop_control_env")
            and manifest.get("loop_bridge", {}).get("max_runtime_env"),
            {
                "loop_bridge": manifest.get("loop_bridge"),
            },
        )
    )
    checks.append(
        build_check(
            "runtime_budget",
            soak_plan.get("minimum_runtime_hours", 0) >= 8
            and soak_plan.get("expected_source_loop_iterations") == expected_loops,
            {
                "minimum_runtime_hours": soak_plan.get("minimum_runtime_hours"),
                "expected_source_loop_iterations": soak_plan.get("expected_source_loop_iterations"),
                "recomputed_expected_source_loop_iterations": expected_loops,
            },
        )
    )
    checks.append(
        build_check(
            "drift_budget",
            isinstance(soak_plan.get("drift_budget", {}).get("max_abs_drift_seconds_per_hour"), (int, float))
            and soak_plan.get("drift_budget", {}).get("max_abs_drift_seconds_per_hour", 0) > 0,
            {
                "drift_budget": soak_plan.get("drift_budget"),
            },
        )
    )
    checks.append(
        build_check(
            "reconnect_policy",
            set(soak_plan.get("reconnect_policy", {}).get("retryable_classes", [])) == retryable_class_ids
            and set(soak_plan.get("exit_classification_coverage", [])) == class_ids,
            {
                "retryable_classes": soak_plan.get("reconnect_policy", {}).get("retryable_classes"),
                "expected_retryable_classes": sorted(retryable_class_ids),
                "exit_classification_coverage": soak_plan.get("exit_classification_coverage"),
                "expected_classification_coverage": sorted(class_ids),
            },
        )
    )
    checks.append(
        build_check(
            "runtime_observability",
            log_dir.exists()
            and set(soak_plan.get("required_runtime_files", []))
            == {
                f"{runtime_observability.get('log_dir')}/{runtime_observability.get('stderr_log_file')}",
                f"{runtime_observability.get('log_dir')}/{runtime_observability.get('exit_report_file')}",
            },
            {
                "log_dir": str(log_dir),
                "log_dir_exists": log_dir.exists(),
                "required_runtime_files": soak_plan.get("required_runtime_files"),
            },
        )
    )

    if runtime_report_path and runtime_report_path.exists():
        runtime_report = load_json(runtime_report_path)
        checks.append(
            build_check(
                "runtime_report_classification",
                runtime_report.get("exit_class_id") in class_ids
                and stderr_log_path is not None
                and stderr_log_path.exists(),
                {
                    "runtime_report_file": str(runtime_report_path),
                    "exit_class_id": runtime_report.get("exit_class_id"),
                    "stderr_log_file": str(stderr_log_path) if stderr_log_path else None,
                    "stderr_log_exists": stderr_log_path.exists() if stderr_log_path else False,
                },
            )
        )

    failed = [check for check in checks if check["status"] == "failed"]
    report = {
        "stage": "stage7_pre_stage8_soak",
        "status": "passed" if not failed else "failed",
        "summary": {
            "checks_total": len(checks),
            "checks_failed": len(failed),
            "minimum_runtime_hours": soak_plan.get("minimum_runtime_hours"),
            "expected_source_loop_iterations": soak_plan.get("expected_source_loop_iterations"),
        },
        "checks": checks,
    }
    write_json(artifact_dir / "stage7_soak_validation_report.json", report)

    if failed:
        return fail([f"{check['check_id']}: {check['details']}" for check in failed])

    print("stage7 soak validation passed")
    print(f"artifact_dir: {artifact_dir}")
    print(f"minimum_runtime_hours: {soak_plan.get('minimum_runtime_hours')}")
    print(f"expected_source_loop_iterations: {soak_plan.get('expected_source_loop_iterations')}")
    print(f"report_file: {artifact_dir / 'stage7_soak_validation_report.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
