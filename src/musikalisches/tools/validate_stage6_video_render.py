#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
from pathlib import Path

from stage6_scene_profile import SCENE_PROFILE_SCHEMA_PATH, validate_scene_profile_payload


REQUIRED_FILES = {
    "visual_scene_profile.json",
    "video_render_manifest.json",
    "offline_frame_sequence.json",
    "video_render_poster.ppm",
}


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def build_check(check_id: str, passed: bool, details: dict) -> dict:
    return {
        "check_id": check_id,
        "status": "passed" if passed else "failed",
        "details": details,
    }


def fail(errors: list[str]) -> int:
    print("stage6 video render validation failed:")
    for error in errors:
        print(f"- {error}")
    return 1


def write_report(output_dir: Path, frame_sequence: dict, checks: list[dict]) -> dict:
    failed = [check for check in checks if check["status"] == "failed"]
    report = {
        "stage": "stage6_video_render",
        "status": "passed" if not failed else "failed",
        "summary": {
            "checks_total": len(checks),
            "checks_failed": len(failed),
            "frame_count": frame_sequence.get("summary", {}).get("frame_count", 0),
            "cycle_count": frame_sequence.get("summary", {}).get("cycle_count", 0),
            "lane_count": frame_sequence.get("summary", {}).get("lane_count", 0),
            "total_duration_seconds": frame_sequence.get("summary", {}).get(
                "total_duration_seconds"
            ),
        },
        "checks": checks,
    }
    (output_dir / "stage6_render_validation_report.json").write_text(
        json.dumps(report, ensure_ascii=True, indent=2) + "\n",
        encoding="utf-8",
    )
    return report


def probe_mp4(path: Path) -> dict | None:
    ffprobe = shutil.which("ffprobe")
    if not ffprobe or not path.exists():
        return None
    result = subprocess.run(
        [
            ffprobe,
            "-v",
            "error",
            "-show_entries",
            "stream=width,height,avg_frame_rate",
            "-show_entries",
            "format=duration",
            "-of",
            "json",
            str(path),
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return None
    return json.loads(result.stdout)


def ppm_header(path: Path) -> tuple[str, int, int, int] | None:
    with path.open("rb") as handle:
        magic = handle.readline().decode("ascii", errors="replace").strip()
        dimensions = handle.readline().decode("ascii", errors="replace").strip().split()
        max_value = handle.readline().decode("ascii", errors="replace").strip()
    if len(dimensions) != 2:
        return None
    return magic, int(dimensions[0]), int(dimensions[1]), int(max_value)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Validate stage6 render-video skeleton artifacts."
    )
    parser.add_argument(
        "artifact_dir",
        nargs="?",
        default="ops/out/video-render",
        help="stage6 render artifact directory containing video_render_manifest.json",
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
    manifest = load_json(artifact_dir / "video_render_manifest.json")
    frame_sequence = load_json(artifact_dir / "offline_frame_sequence.json")
    poster_header = ppm_header(artifact_dir / "video_render_poster.ppm")
    source_dir = Path(manifest.get("source_artifact_dir", ""))
    source_scene_path = source_dir / manifest.get("source_scene_file", "")
    checks: list[dict] = []

    scene_profile_errors = validate_scene_profile_payload(
        scene_profile,
        allow_output_metadata=True,
    )
    frames = frame_sequence.get("frames", [])
    canvas = frame_sequence.get("canvas", {})
    mp4_generated = manifest.get("mp4_generation", {}).get("generated", False)
    mp4_path = artifact_dir / "offline_preview.mp4"
    mp4_probe = probe_mp4(mp4_path) if mp4_generated else None

    checks.append(
        build_check(
            "stage",
            manifest.get("stage") == "stage6_video_render"
            and frame_sequence.get("stage") == "stage6_video_render",
            {
                "manifest_stage": manifest.get("stage"),
                "frame_sequence_stage": frame_sequence.get("stage"),
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
            "scene_profile_identity",
            manifest.get("visual_scene_profile_id") == scene_profile.get("profile_id")
            and frame_sequence.get("visual_scene_profile_id") == scene_profile.get("profile_id")
            and manifest.get("visual_scene_profile_source") == scene_profile.get("source")
            and frame_sequence.get("visual_scene_profile_source") == scene_profile.get("source")
            and manifest.get("visual_scene_profile_path") == scene_profile.get("source_path")
            and frame_sequence.get("visual_scene_profile_path") == scene_profile.get("source_path"),
            {
                "manifest_profile_id": manifest.get("visual_scene_profile_id"),
                "frame_sequence_profile_id": frame_sequence.get("visual_scene_profile_id"),
                "profile_id": scene_profile.get("profile_id"),
                "manifest_profile_source": manifest.get("visual_scene_profile_source"),
                "frame_sequence_profile_source": frame_sequence.get("visual_scene_profile_source"),
                "profile_source": scene_profile.get("source"),
                "manifest_profile_path": manifest.get("visual_scene_profile_path"),
                "frame_sequence_profile_path": frame_sequence.get("visual_scene_profile_path"),
                "profile_path": scene_profile.get("source_path"),
            },
        )
    )
    checks.append(
        build_check(
            "source_scene",
            source_dir.exists() and source_scene_path.exists(),
            {
                "source_artifact_dir": str(source_dir),
                "source_scene_file": str(source_scene_path),
            },
        )
    )
    checks.append(
        build_check(
            "canvas",
            canvas.get("width") == scene_profile.get("canvas", {}).get("width")
            and canvas.get("height") == scene_profile.get("canvas", {}).get("height")
            and canvas.get("fps") == scene_profile.get("canvas", {}).get("fps"),
            {
                "frame_canvas": canvas,
                "profile_canvas": scene_profile.get("canvas", {}),
            },
        )
    )
    checks.append(
        build_check(
            "frame_count",
            frame_sequence.get("summary", {}).get("frame_count") == len(frames) and len(frames) > 0,
            {
                "summary_frame_count": frame_sequence.get("summary", {}).get("frame_count"),
                "actual_frame_count": len(frames),
            },
        )
    )
    checks.append(
        build_check(
            "frame_clock_monotonic",
            all(
                frames[index].get("clock_seconds", 0.0)
                <= frames[index + 1].get("clock_seconds", 0.0)
                for index in range(len(frames) - 1)
            ),
            {
                "first_clock_seconds": frames[0].get("clock_seconds") if frames else None,
                "last_clock_seconds": frames[-1].get("clock_seconds") if frames else None,
            },
        )
    )
    checks.append(
        build_check(
            "voice_pulses_per_frame",
            all(
                len(frame.get("voice_pulses", []))
                == frame_sequence.get("summary", {}).get("lane_count", 0)
                for frame in frames
            ),
            {
                "expected_lane_count": frame_sequence.get("summary", {}).get("lane_count"),
            },
        )
    )
    checks.append(
        build_check(
            "frame_index_contiguous",
            [frame.get("frame_index") for frame in frames]
            == list(range(1, len(frames) + 1)),
            {
                "first_frame_index": frames[0].get("frame_index") if frames else None,
                "last_frame_index": frames[-1].get("frame_index") if frames else None,
            },
        )
    )
    checks.append(
        build_check(
            "poster_ppm",
            poster_header is not None
            and poster_header[0] == "P6"
            and poster_header[1] == canvas.get("width")
            and poster_header[2] == canvas.get("height")
            and poster_header[3] == 255,
            {
                "poster_header": poster_header,
                "canvas": canvas,
            },
        )
    )
    checks.append(
        build_check(
            "mp4_generation",
            (not mp4_generated and not mp4_path.exists())
            or (
                mp4_generated
                and mp4_path.exists()
                and mp4_probe is not None
                and mp4_probe.get("streams", [{}])[0].get("width") == canvas.get("width")
                and mp4_probe.get("streams", [{}])[0].get("height") == canvas.get("height")
            ),
            {
                "mp4_generated": mp4_generated,
                "mp4_exists": mp4_path.exists(),
                "mp4_probe": mp4_probe,
            },
        )
    )

    report = write_report(artifact_dir, frame_sequence, checks)
    failed_checks = [check for check in checks if check["status"] == "failed"]
    if failed_checks:
        return fail([f"{check['check_id']} failed" for check in failed_checks])

    print("stage6 video render validation passed")
    print(f"artifact_dir: {artifact_dir}")
    print(f"frame_count: {report['summary']['frame_count']}")
    print(f"cycle_count: {report['summary']['cycle_count']}")
    print(f"lane_count: {report['summary']['lane_count']}")
    print(f"report_file: {artifact_dir / 'stage6_render_validation_report.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
