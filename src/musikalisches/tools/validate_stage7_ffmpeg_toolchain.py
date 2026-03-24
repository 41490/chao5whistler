#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
from pathlib import Path


def write_json(path: Path, payload: dict) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=True, indent=2) + "\n",
        encoding="utf-8",
    )


def run(args: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        args,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )


def parse_protocols(output: str) -> dict[str, set[str]]:
    sections = {"Input": set(), "Output": set()}
    current: str | None = None
    for raw_line in output.splitlines():
        line = raw_line.strip()
        if line == "Input:":
            current = "Input"
            continue
        if line == "Output:":
            current = "Output"
            continue
        if not line or current is None or line.endswith(":"):
            continue
        sections[current].add(line)
    return sections


def build_check(check_id: str, passed: bool, details: dict) -> dict:
    return {
        "check_id": check_id,
        "status": "passed" if passed else "failed",
        "details": details,
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Validate repo-managed ffmpeg/ffprobe toolchain for stage7 RTMPS use."
    )
    parser.add_argument("--ffmpeg-bin", default="ops/bin/ffmpeg")
    parser.add_argument("--ffprobe-bin", default="ops/bin/ffprobe")
    parser.add_argument(
        "--output-dir",
        default="ops/out/ffmpeg-rtmps-check",
        help="directory for the validation report",
    )
    args = parser.parse_args()

    ffmpeg_bin = shutil.which(args.ffmpeg_bin) or args.ffmpeg_bin
    ffprobe_bin = shutil.which(args.ffprobe_bin) or args.ffprobe_bin
    output_dir = Path(args.output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    checks: list[dict] = []
    ffmpeg_version = run([ffmpeg_bin, "-version"])
    ffprobe_version = run([ffprobe_bin, "-version"])

    checks.append(
        build_check(
            "ffmpeg_exists",
            ffmpeg_version.returncode == 0,
            {"ffmpeg_bin": ffmpeg_bin, "exit_code": ffmpeg_version.returncode},
        )
    )
    checks.append(
        build_check(
            "ffprobe_exists",
            ffprobe_version.returncode == 0,
            {"ffprobe_bin": ffprobe_bin, "exit_code": ffprobe_version.returncode},
        )
    )

    protocols_run = run([ffmpeg_bin, "-protocols"])
    protocol_sections = parse_protocols(protocols_run.stdout + "\n" + protocols_run.stderr)
    checks.append(
        build_check(
            "rtmps_output_protocol",
            protocols_run.returncode == 0 and "rtmps" in protocol_sections["Output"],
            {
                "ffmpeg_bin": ffmpeg_bin,
                "output_protocols": sorted(protocol_sections["Output"]),
            },
        )
    )

    encoders_run = run([ffmpeg_bin, "-encoders"])
    checks.append(
        build_check(
            "libx264_encoder",
            encoders_run.returncode == 0 and "libx264" in encoders_run.stdout,
            {"ffmpeg_bin": ffmpeg_bin},
        )
    )

    filters_run = run([ffmpeg_bin, "-filters"])
    checks.append(
        build_check(
            "lavfi_support",
            filters_run.returncode == 0
            and "testsrc" in filters_run.stdout
            and "anullsrc" in filters_run.stdout,
            {"ffmpeg_bin": ffmpeg_bin},
        )
    )

    smoke_output_path = output_dir / "ffmpeg_rtmps_validation_smoke.flv"
    encode_run = run(
        [
            ffmpeg_bin,
            "-y",
            "-f",
            "lavfi",
            "-i",
            "testsrc=size=320x180:rate=10",
            "-f",
            "lavfi",
            "-i",
            "anullsrc=r=44100:cl=stereo",
            "-t",
            "2",
            "-map",
            "0:v:0",
            "-map",
            "1:a:0",
            "-c:v",
            "libx264",
            "-preset",
            "ultrafast",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            "-b:a",
            "96k",
            "-ar",
            "44100",
            "-ac",
            "2",
            "-f",
            "flv",
            str(smoke_output_path),
        ]
    )
    checks.append(
        build_check(
            "local_encode_smoke",
            encode_run.returncode == 0 and smoke_output_path.exists(),
            {
                "ffmpeg_bin": ffmpeg_bin,
                "smoke_output_file": str(smoke_output_path),
                "exit_code": encode_run.returncode,
            },
        )
    )

    probe_run = run(
        [
            ffprobe_bin,
            "-v",
            "error",
            "-show_entries",
            "format=format_name",
            "-of",
            "json",
            str(smoke_output_path),
        ]
    )
    checks.append(
        build_check(
            "ffprobe_smoke",
            probe_run.returncode == 0 and "flv" in probe_run.stdout,
            {
                "ffprobe_bin": ffprobe_bin,
                "smoke_output_file": str(smoke_output_path),
                "exit_code": probe_run.returncode,
            },
        )
    )

    failed = [check for check in checks if check["status"] == "failed"]
    report = {
        "stage": "stage7_ffmpeg_toolchain",
        "status": "passed" if not failed else "failed",
        "summary": {
            "checks_total": len(checks),
            "checks_failed": len(failed),
            "ffmpeg_bin": ffmpeg_bin,
            "ffprobe_bin": ffprobe_bin,
        },
        "checks": checks,
        "ffmpeg_version": ffmpeg_version.stdout.splitlines()[:3],
        "ffprobe_version": ffprobe_version.stdout.splitlines()[:3],
    }
    write_json(output_dir / "stage7_ffmpeg_toolchain_validation_report.json", report)

    if failed:
        print("stage7 ffmpeg toolchain validation failed:")
        for check in failed:
            print(f"- {check['check_id']}: {check['details']}")
        return 1

    print("stage7 ffmpeg toolchain validation passed")
    print(f"ffmpeg_bin: {ffmpeg_bin}")
    print(f"ffprobe_bin: {ffprobe_bin}")
    print(f"report_file: {output_dir / 'stage7_ffmpeg_toolchain_validation_report.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
