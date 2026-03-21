#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
from pathlib import Path

from stage6_scene_profile import (
    SCENE_PROFILE_SCHEMA_PATH,
    validate_scene_profile_payload,
)


REQUIRED_FILES = {
    "visual_scene_profile.json",
    "video_stub_manifest.json",
    "video_stub_scene.json",
    "video_stub_preview.svg",
}


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def build_check(check_id: str, passed: bool, details: dict) -> dict:
    return {
        "check_id": check_id,
        "status": "passed" if passed else "failed",
        "details": details,
    }


def write_report(
    output_dir: Path,
    scene: dict,
    checks: list[dict],
) -> dict:
    failed = [check for check in checks if check["status"] == "failed"]
    report = {
        "stage": "stage6_video_stub",
        "status": "passed" if not failed else "failed",
        "summary": {
            "checks_total": len(checks),
            "checks_failed": len(failed),
            "window_count": scene.get("summary", {}).get("window_count", 0),
            "cycle_count": scene.get("summary", {}).get("cycle_count", 0),
            "lane_count": scene.get("summary", {}).get("lane_count", 0),
            "total_duration_seconds": scene.get("summary", {}).get(
                "total_duration_seconds"
            ),
        },
        "checks": checks,
    }
    (output_dir / "stage6_validation_report.json").write_text(
        json.dumps(report, ensure_ascii=True, indent=2) + "\n",
        encoding="utf-8",
    )
    return report


def fail(errors: list[str]) -> int:
    print("stage6 video stub validation failed:")
    for error in errors:
        print(f"- {error}")
    return 1


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Validate stage6 analyzer-to-video stub artifacts."
    )
    parser.add_argument(
        "artifact_dir",
        nargs="?",
        default="ops/out/video-stub",
        help="stage6 artifact directory containing video_stub_manifest.json",
    )
    args = parser.parse_args()

    artifact_dir = Path(args.artifact_dir).resolve()
    if not artifact_dir.exists():
        return fail([f"artifact directory does not exist: {artifact_dir}"])

    file_names = {path.name for path in artifact_dir.iterdir() if path.is_file()}
    missing = sorted(REQUIRED_FILES - file_names)
    if missing:
        return fail([f"missing files: {', '.join(missing)}"])

    scene_profile = load_json(artifact_dir / "visual_scene_profile.json")
    manifest = load_json(artifact_dir / "video_stub_manifest.json")
    scene = load_json(artifact_dir / "video_stub_scene.json")
    preview_text = (artifact_dir / "video_stub_preview.svg").read_text(encoding="utf-8")

    keyframes = scene.get("keyframes", [])
    lanes = scene.get("lane_layout", [])
    cycles = scene.get("cycles", [])
    checks: list[dict] = []
    scene_profile_errors = validate_scene_profile_payload(
        scene_profile,
        allow_output_metadata=True,
    )

    checks.append(
        build_check(
            "stage",
            manifest.get("stage") == "stage6_video_stub"
            and scene.get("stage") == "stage6_video_stub",
            {
                "manifest_stage": manifest.get("stage"),
                "scene_stage": scene.get("stage"),
            },
        )
    )
    checks.append(
        build_check(
            "palette",
            scene.get("palette", {}).get("palette_id")
            == scene_profile.get("palette", {}).get("palette_id"),
            {
                "scene_palette_id": scene.get("palette", {}).get("palette_id"),
                "profile_palette_id": scene_profile.get("palette", {}).get("palette_id"),
            },
        )
    )
    checks.append(
        build_check(
            "scene_profile_contract",
            not scene_profile_errors,
            {
                "schema_file": str(SCENE_PROFILE_SCHEMA_PATH),
                "error_count": len(scene_profile_errors),
                "errors": scene_profile_errors,
            },
        )
    )
    checks.append(
        build_check(
            "scene_profile_id",
            scene.get("visual_scene_profile_id") == scene_profile.get("profile_id")
            and manifest.get("visual_scene_profile_id") == scene_profile.get("profile_id"),
            {
                "scene_profile_id": scene.get("visual_scene_profile_id"),
                "manifest_profile_id": manifest.get("visual_scene_profile_id"),
                "profile_id": scene_profile.get("profile_id"),
            },
        )
    )
    checks.append(
        build_check(
            "scene_profile_source",
            scene.get("visual_scene_profile_source") == scene_profile.get("source")
            and manifest.get("visual_scene_profile_source") == scene_profile.get("source")
            and scene.get("visual_scene_profile_path") == scene_profile.get("source_path")
            and manifest.get("visual_scene_profile_path") == scene_profile.get("source_path"),
            {
                "scene_source": scene.get("visual_scene_profile_source"),
                "manifest_source": manifest.get("visual_scene_profile_source"),
                "profile_source": scene_profile.get("source"),
                "scene_path": scene.get("visual_scene_profile_path"),
                "manifest_path": manifest.get("visual_scene_profile_path"),
                "profile_path": scene_profile.get("source_path"),
            },
        )
    )
    checks.append(
        build_check(
            "canvas",
            scene.get("canvas", {}).get("width", 0)
            == scene_profile.get("canvas", {}).get("width")
            and scene.get("canvas", {}).get("height", 0)
            == scene_profile.get("canvas", {}).get("height")
            and scene.get("canvas", {}).get("fps", 0)
            == scene_profile.get("canvas", {}).get("fps"),
            {
                "scene_canvas": scene.get("canvas", {}),
                "profile_canvas": scene_profile.get("canvas", {}),
            },
        )
    )
    checks.append(
        build_check(
            "motion",
            scene.get("motion", {}).get("mode")
            == scene_profile.get("motion", {}).get("mode"),
            {
                "scene_motion": scene.get("motion", {}).get("mode"),
                "profile_motion": scene_profile.get("motion", {}).get("mode"),
            },
        )
    )
    checks.append(
        build_check(
            "summary_window_count",
            scene.get("summary", {}).get("window_count") == len(keyframes) and len(keyframes) > 0,
            {
                "summary_window_count": scene.get("summary", {}).get("window_count"),
                "actual_window_count": len(keyframes),
            },
        )
    )
    checks.append(
        build_check(
            "summary_cycle_count",
            scene.get("summary", {}).get("cycle_count") == len(cycles) and len(cycles) > 0,
            {
                "summary_cycle_count": scene.get("summary", {}).get("cycle_count"),
                "actual_cycle_count": len(cycles),
            },
        )
    )
    checks.append(
        build_check(
            "summary_lane_count",
            scene.get("summary", {}).get("lane_count") == len(lanes) and len(lanes) > 0,
            {
                "summary_lane_count": scene.get("summary", {}).get("lane_count"),
                "actual_lane_count": len(lanes),
            },
        )
    )
    checks.append(
        build_check(
            "manifest_scene_file",
            manifest.get("artifacts", {}).get("scene_file") == "video_stub_scene.json",
            {"artifacts": manifest.get("artifacts", {})},
        )
    )
    checks.append(
        build_check(
            "manifest_profile_file",
            manifest.get("artifacts", {}).get("visual_scene_profile_file")
            == "visual_scene_profile.json",
            {"artifacts": manifest.get("artifacts", {})},
        )
    )
    checks.append(
        build_check(
            "manifest_preview_file",
            manifest.get("artifacts", {}).get("preview_file") == "video_stub_preview.svg",
            {"artifacts": manifest.get("artifacts", {})},
        )
    )
    checks.append(
        build_check(
            "clock_monotonic",
            all(
                keyframes[index].get("clock_seconds", 0.0)
                <= keyframes[index + 1].get("clock_seconds", 0.0)
                for index in range(len(keyframes) - 1)
            ),
            {
                "first_clock_seconds": keyframes[0].get("clock_seconds") if keyframes else None,
                "last_clock_seconds": keyframes[-1].get("clock_seconds") if keyframes else None,
            },
        )
    )
    checks.append(
        build_check(
            "voice_pulses_per_keyframe",
            all(len(frame.get("voice_pulses", [])) == len(lanes) for frame in keyframes),
            {"lane_count": len(lanes)},
        )
    )
    checks.append(
        build_check(
            "cycle_window_counts",
            sum(cycle.get("window_count", 0) for cycle in cycles) == len(keyframes),
            {
                "cycle_window_total": sum(cycle.get("window_count", 0) for cycle in cycles),
                "window_count": len(keyframes),
            },
        )
    )
    checks.append(
        build_check(
            "preview_svg",
            "<svg" in preview_text and "<rect" in preview_text,
            {"preview_bytes": len(preview_text)},
        )
    )

    report = write_report(artifact_dir, scene, checks)
    failed_checks = [check for check in checks if check["status"] == "failed"]
    if failed_checks:
        return fail([f"{check['check_id']} failed" for check in failed_checks])

    print("stage6 video stub validation passed")
    print(f"artifact_dir: {artifact_dir}")
    print(f"window_count: {report['summary']['window_count']}")
    print(f"cycle_count: {report['summary']['cycle_count']}")
    print(f"lane_count: {report['summary']['lane_count']}")
    print(f"report_file: {artifact_dir / 'stage6_validation_report.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
