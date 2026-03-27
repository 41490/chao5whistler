#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
import os
import shutil
import socket
import subprocess
import sys
import threading
from pathlib import Path

from stage7_bridge_profile import DEFAULT_BRIDGE_PROFILE_PATH


ROOT_PATH = Path(__file__).resolve().parents[3]
BUILD_STAGE7_STREAM_BRIDGE_TOOL = Path(__file__).resolve().parent / "build_stage7_stream_bridge.py"
RUN_STAGE7_STREAM_BRIDGE_RUNTIME_TOOL = (
    Path(__file__).resolve().parent / "run_stage7_stream_bridge_runtime.py"
)
RUST_RUNTIME_BIN_NAME = "musikalisches-stage7-runtime"
RUNTIME_BIN_ENV = "MUSIKALISCHES_STAGE7_RUNTIME_BIN"
STREAM_URL_ENV = "MUSIKALISCHES_RTMP_URL"
REPORT_FILE = "stage7_preflight_regression_report.json"
SCENARIO_ORDER = [
    "target_scheme",
    "protocol_support",
    "dns_resolution",
    "tcp_connectivity",
    "publish_probe",
]
EXPECTED_CHECK_SEQUENCES = {
    "target_scheme": [],
    "protocol_support": ["protocol_support"],
    "dns_resolution": ["protocol_support", "dns_resolution"],
    "tcp_connectivity": ["protocol_support", "dns_resolution", "tcp_connectivity"],
    "publish_probe": [
        "protocol_support",
        "dns_resolution",
        "tcp_connectivity",
        "publish_probe",
    ],
}


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: dict) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=True, indent=2) + "\n",
        encoding="utf-8",
    )


def fail(errors: list[str]) -> int:
    print("stage7 preflight regression validation failed:")
    for error in errors:
        print(f"- {error}")
    return 1


def build_profile(*, protocol: str, stream_url_example: str, output_path: Path) -> Path:
    profile = load_json(DEFAULT_BRIDGE_PROFILE_PATH)
    profile["profile_id"] = f"stage7_preflight_regression_{protocol}_h264_aac_720p30"
    profile["description"] = (
        "Temporary stage7 bridge profile for automated preflight failure regression checks."
    )
    profile["ingest"]["protocol"] = protocol
    profile["ingest"]["stream_url_example"] = stream_url_example
    write_json(output_path, profile)
    return output_path


def build_bridge_artifacts(
    *,
    audio_dir: Path,
    video_dir: Path,
    output_dir: Path,
    profile_path: Path,
    ffmpeg_bin: str,
    ffprobe_bin: str,
) -> None:
    if output_dir.exists():
        shutil.rmtree(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [
            sys.executable,
            str(BUILD_STAGE7_STREAM_BRIDGE_TOOL),
            "--bridge-profile",
            str(profile_path),
            "--ffmpeg-bin",
            ffmpeg_bin,
            "--ffprobe-bin",
            ffprobe_bin,
            "--skip-smoke",
            str(audio_dir),
            str(video_dir),
            str(output_dir),
        ],
        check=True,
        cwd=ROOT_PATH,
    )


def run_runtime(*, artifact_dir: Path, target_url: str) -> subprocess.CompletedProcess[str]:
    env = dict(os.environ)
    env[STREAM_URL_ENV] = target_url
    runtime_bin = resolve_runtime_bin(env)
    command = (
        [
            runtime_bin,
            "--artifact-dir",
            str(artifact_dir),
            "--stream-url-env",
            STREAM_URL_ENV,
            "--loop-mode",
            "once",
            "--max-runtime-seconds",
            "0",
        ]
        if runtime_bin
        else [
            sys.executable,
            str(RUN_STAGE7_STREAM_BRIDGE_RUNTIME_TOOL),
            "--artifact-dir",
            str(artifact_dir),
            "--stream-url-env",
            STREAM_URL_ENV,
            "--loop-mode",
            "once",
            "--max-runtime-seconds",
            "0",
        ]
    )
    return subprocess.run(
        command,
        check=False,
        capture_output=True,
        text=True,
        cwd=ROOT_PATH,
        env=env,
    )


def resolve_runtime_bin(env: dict[str, str]) -> str | None:
    explicit = env.get(RUNTIME_BIN_ENV, "").strip()
    if explicit:
        explicit_path = Path(explicit)
        if not explicit_path.is_file():
            raise SystemExit(f"{RUNTIME_BIN_ENV} does not point to a file: {explicit_path}")
        if not os.access(explicit_path, os.X_OK):
            raise SystemExit(f"{RUNTIME_BIN_ENV} is not executable: {explicit_path}")
        return str(explicit_path)

    for candidate in (
        ROOT_PATH / "target" / "release" / RUST_RUNTIME_BIN_NAME,
        ROOT_PATH / "target" / "debug" / RUST_RUNTIME_BIN_NAME,
    ):
        if candidate.is_file() and os.access(candidate, os.X_OK):
            return str(candidate)
    return None


def reserve_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as handle:
        handle.bind(("127.0.0.1", 0))
        return int(handle.getsockname()[1])


class RejectingTcpServer:
    def __init__(self) -> None:
        self._server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._server.bind(("127.0.0.1", 0))
        self._server.listen()
        self.port = int(self._server.getsockname()[1])
        self._stop_event = threading.Event()
        self._thread = threading.Thread(target=self._serve, daemon=True)

    def _serve(self) -> None:
        self._server.settimeout(0.2)
        while not self._stop_event.is_set():
            try:
                connection, _ = self._server.accept()
            except TimeoutError:
                continue
            except OSError:
                break
            with connection:
                connection.settimeout(0.2)
                try:
                    connection.recv(256)
                except OSError:
                    pass
                try:
                    connection.sendall(b"not an rtmp server\r\n")
                except OSError:
                    pass

    def __enter__(self) -> "RejectingTcpServer":
        self._thread.start()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self._stop_event.set()
        self._server.close()
        self._thread.join(timeout=1.0)


def write_fake_ffmpeg(path: Path) -> Path:
    path.write_text(
        "#!/usr/bin/env bash\n"
        "set -eu\n"
        "if [[ \"${1:-}\" == \"-protocols\" ]]; then\n"
        "  cat <<'EOF'\n"
        "Supported file protocols:\n"
        "Input:\n"
        "  file\n"
        "Output:\n"
        "  file\n"
        "EOF\n"
        "  exit 0\n"
        "fi\n"
        "printf '%s\\n' 'fake ffmpeg only supports -protocols in this regression harness' >&2\n"
        "exit 2\n",
        encoding="utf-8",
    )
    path.chmod(0o755)
    return path


def evaluate_scenario(*, scenario_id: str, artifact_dir: Path, result: subprocess.CompletedProcess[str]) -> dict:
    log_dir = artifact_dir / "logs"
    preflight_report_path = log_dir / "stage7_bridge_preflight_report.json"
    preflight_log_path = log_dir / "stage7_bridge_preflight.stderr.log"
    runtime_report_path = log_dir / "stage7_bridge_runtime_report.json"
    exit_report_path = log_dir / "stage7_bridge_exit_report.json"
    stderr_lines = [line for line in result.stderr.splitlines() if line.strip()]
    expected_first_line = (
        f"preflight failed: {scenario_id}; see {preflight_report_path} and {preflight_log_path}"
    )

    checks: list[dict] = []

    def record(check_id: str, passed: bool, details: dict) -> None:
        checks.append(
            {
                "check_id": check_id,
                "status": "passed" if passed else "failed",
                "details": details,
            }
        )

    record(
        "runtime_exit_code",
        result.returncode != 0,
        {
            "exit_code": result.returncode,
            "stdout": result.stdout.strip(),
            "stderr_first_line": stderr_lines[0] if stderr_lines else None,
        },
    )
    record(
        "console_first_line",
        bool(stderr_lines) and stderr_lines[0] == expected_first_line,
        {
            "expected": expected_first_line,
            "actual": stderr_lines[0] if stderr_lines else None,
        },
    )
    record(
        "report_files",
        all(
            path.exists()
            for path in (
                preflight_report_path,
                preflight_log_path,
                runtime_report_path,
                exit_report_path,
            )
        ),
        {
            "preflight_report_path": str(preflight_report_path),
            "preflight_log_path": str(preflight_log_path),
            "runtime_report_path": str(runtime_report_path),
            "exit_report_path": str(exit_report_path),
        },
    )

    preflight_report = load_json(preflight_report_path) if preflight_report_path.exists() else {}
    runtime_report = load_json(runtime_report_path) if runtime_report_path.exists() else {}
    exit_report = load_json(exit_report_path) if exit_report_path.exists() else {}
    observed_checks = [check.get("check_id") for check in preflight_report.get("checks", [])]

    record(
        "preflight_report",
        preflight_report.get("status") == "preflight_failed"
        and preflight_report.get("failed_check_id") == scenario_id,
        {
            "status": preflight_report.get("status"),
            "failed_check_id": preflight_report.get("failed_check_id"),
            "exit_class_id": preflight_report.get("exit_class_id"),
            "exit_code": preflight_report.get("exit_code"),
        },
    )
    record(
        "runtime_report",
        runtime_report.get("status") == "preflight_failed"
        and runtime_report.get("attempts_total") == 0
        and runtime_report.get("preflight_report_file") == str(preflight_report_path),
        {
            "status": runtime_report.get("status"),
            "attempts_total": runtime_report.get("attempts_total"),
            "preflight_report_file": runtime_report.get("preflight_report_file"),
        },
    )
    record(
        "check_sequence",
        observed_checks == EXPECTED_CHECK_SEQUENCES[scenario_id],
        {
            "expected": EXPECTED_CHECK_SEQUENCES[scenario_id],
            "observed": observed_checks,
        },
    )
    record(
        "latest_exit_report",
        exit_report.get("status") == "preflight_failed"
        and exit_report.get("failed_check_id") == scenario_id,
        {
            "status": exit_report.get("status"),
            "failed_check_id": exit_report.get("failed_check_id"),
        },
    )

    return {
        "scenario_id": scenario_id,
        "status": "passed" if all(check["status"] == "passed" for check in checks) else "failed",
        "artifact_dir": str(artifact_dir),
        "checks": checks,
        "stderr_preview": stderr_lines[:6],
        "reports": {
            "preflight_report": preflight_report,
            "runtime_report": runtime_report,
            "exit_report": exit_report,
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Validate automated stage7 preflight failure observability regressions."
    )
    parser.add_argument(
        "audio_artifact_dir",
        nargs="?",
        default="ops/out/stream-demo",
        help="stage5 artifact directory containing offline_audio.wav",
    )
    parser.add_argument(
        "video_artifact_dir",
        nargs="?",
        default="ops/out/video-render",
        help="stage6 render artifact directory containing offline_preview.mp4",
    )
    parser.add_argument(
        "output_dir",
        nargs="?",
        default="ops/out/stage7-preflight-regressions",
        help="directory where per-scenario stage7 preflight regression artifacts will be written",
    )
    parser.add_argument(
        "--ffmpeg-bin",
        default="ffmpeg",
        help="ffmpeg binary used for local regression scenarios",
    )
    parser.add_argument(
        "--ffprobe-bin",
        default="ffprobe",
        help="ffprobe binary passed through to the stage7 builder",
    )
    args = parser.parse_args()

    audio_dir = Path(args.audio_artifact_dir).resolve()
    video_dir = Path(args.video_artifact_dir).resolve()
    output_dir = Path(args.output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    fake_ffmpeg_dir = output_dir / "_bin"
    fake_ffmpeg_dir.mkdir(parents=True, exist_ok=True)
    fake_ffmpeg_path = write_fake_ffmpeg(fake_ffmpeg_dir / "ffmpeg-no-rtmp.sh")

    base_profile_path = build_profile(
        protocol="rtmp",
        stream_url_example="rtmp://127.0.0.1/live2/<stream-key>",
        output_path=output_dir / "stage7_preflight_regression_profile.rtmp.json",
    )

    scenario_results: list[dict] = []

    target_scheme_dir = output_dir / "scenario-target-scheme"
    build_bridge_artifacts(
        audio_dir=audio_dir,
        video_dir=video_dir,
        output_dir=target_scheme_dir,
        profile_path=base_profile_path,
        ffmpeg_bin=args.ffmpeg_bin,
        ffprobe_bin=args.ffprobe_bin,
    )
    scenario_results.append(
        evaluate_scenario(
            scenario_id="target_scheme",
            artifact_dir=target_scheme_dir,
            result=run_runtime(
                artifact_dir=target_scheme_dir,
                target_url="rtmps://127.0.0.1/live/target-scheme",
            ),
        )
    )

    protocol_support_dir = output_dir / "scenario-protocol-support"
    build_bridge_artifacts(
        audio_dir=audio_dir,
        video_dir=video_dir,
        output_dir=protocol_support_dir,
        profile_path=base_profile_path,
        ffmpeg_bin=str(fake_ffmpeg_path),
        ffprobe_bin=args.ffprobe_bin,
    )
    scenario_results.append(
        evaluate_scenario(
            scenario_id="protocol_support",
            artifact_dir=protocol_support_dir,
            result=run_runtime(
                artifact_dir=protocol_support_dir,
                target_url="rtmp://127.0.0.1/live/protocol-support",
            ),
        )
    )

    dns_resolution_dir = output_dir / "scenario-dns-resolution"
    build_bridge_artifacts(
        audio_dir=audio_dir,
        video_dir=video_dir,
        output_dir=dns_resolution_dir,
        profile_path=base_profile_path,
        ffmpeg_bin=args.ffmpeg_bin,
        ffprobe_bin=args.ffprobe_bin,
    )
    scenario_results.append(
        evaluate_scenario(
            scenario_id="dns_resolution",
            artifact_dir=dns_resolution_dir,
            result=run_runtime(
                artifact_dir=dns_resolution_dir,
                target_url="rtmp://preflight-regression.invalid/live/dns-resolution",
            ),
        )
    )

    tcp_connectivity_dir = output_dir / "scenario-tcp-connectivity"
    build_bridge_artifacts(
        audio_dir=audio_dir,
        video_dir=video_dir,
        output_dir=tcp_connectivity_dir,
        profile_path=base_profile_path,
        ffmpeg_bin=args.ffmpeg_bin,
        ffprobe_bin=args.ffprobe_bin,
    )
    scenario_results.append(
        evaluate_scenario(
            scenario_id="tcp_connectivity",
            artifact_dir=tcp_connectivity_dir,
            result=run_runtime(
                artifact_dir=tcp_connectivity_dir,
                target_url=f"rtmp://127.0.0.1:{reserve_port()}/live/tcp-connectivity",
            ),
        )
    )

    publish_probe_dir = output_dir / "scenario-publish-probe"
    build_bridge_artifacts(
        audio_dir=audio_dir,
        video_dir=video_dir,
        output_dir=publish_probe_dir,
        profile_path=base_profile_path,
        ffmpeg_bin=args.ffmpeg_bin,
        ffprobe_bin=args.ffprobe_bin,
    )
    with RejectingTcpServer() as rejecting_server:
        scenario_results.append(
            evaluate_scenario(
                scenario_id="publish_probe",
                artifact_dir=publish_probe_dir,
                result=run_runtime(
                    artifact_dir=publish_probe_dir,
                    target_url=f"rtmp://127.0.0.1:{rejecting_server.port}/live/publish-probe",
                ),
            )
        )

    failed_scenarios = [
        scenario["scenario_id"]
        for scenario in scenario_results
        if scenario["status"] == "failed"
    ]
    report = {
        "stage": "stage7_preflight_regression",
        "status": "passed" if not failed_scenarios else "failed",
        "summary": {
            "scenarios_total": len(scenario_results),
            "scenarios_failed": len(failed_scenarios),
            "failed_scenarios": failed_scenarios,
            "audio_artifact_dir": str(audio_dir),
            "video_artifact_dir": str(video_dir),
            "ffmpeg_bin": args.ffmpeg_bin,
            "ffprobe_bin": args.ffprobe_bin,
            "preferred_runtime": "rust",
            "runtime_bin_env": RUNTIME_BIN_ENV,
            "runtime_bin_name": RUST_RUNTIME_BIN_NAME,
            "resolved_runtime_bin": resolve_runtime_bin(dict(os.environ)),
            "fallback_runtime_tool": str(RUN_STAGE7_STREAM_BRIDGE_RUNTIME_TOOL),
        },
        "scenarios": scenario_results,
    }
    write_json(output_dir / REPORT_FILE, report)

    if failed_scenarios:
        return fail(
            [
                f"{scenario_id} regression failed; see {output_dir / REPORT_FILE}"
                for scenario_id in failed_scenarios
            ]
        )

    print("stage7 preflight regression validation passed")
    print(f"output_dir: {output_dir}")
    print(f"report_file: {output_dir / REPORT_FILE}")
    print(f"scenarios: {', '.join(SCENARIO_ORDER)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
