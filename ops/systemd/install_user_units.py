#!/usr/bin/env python3

from __future__ import annotations

import argparse
import re
import shutil
import subprocess
import sys
import tomllib
from pathlib import Path


UNIT_NAME_RE = re.compile(r"^[A-Za-z0-9_.@-]+$")


def load_toml(path: Path) -> dict:
    with path.open("rb") as handle:
        return tomllib.load(handle)


def resolve_path(base_dir: Path, raw_path: str) -> Path:
    path = Path(raw_path).expanduser()
    return path if path.is_absolute() else (base_dir / path).resolve()


def validate_config(config: dict) -> tuple[dict, dict, dict]:
    service = config.get("service")
    modes = config.get("modes")
    install = config.get("install", {})
    if not isinstance(service, dict):
        raise SystemExit("systemd config missing [service] table")
    if not isinstance(modes, dict) or not modes:
        raise SystemExit("systemd config missing [modes] table")
    if not isinstance(install, dict):
        raise SystemExit("systemd config [install] must be a TOML table")
    return service, modes, install


def systemd_quote(value: str) -> str:
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def build_unit_name(prefix: str, mode: str) -> str:
    unit_name = f"{prefix}-{mode}.service"
    if not UNIT_NAME_RE.fullmatch(unit_name):
        raise SystemExit(f"invalid systemd unit name derived from config: {unit_name}")
    return unit_name


def render_unit(
    *,
    description: str,
    mode: str,
    service_type: str,
    working_directory: Path,
    runner_path: Path,
    config_path: Path,
    python_bin: str,
    syslog_identifier: str,
    wanted_by: list[str],
) -> str:
    wanted_by_lines = wanted_by or ["default.target"]
    unit_lines = [
        "[Unit]",
        f"Description={description} ({mode})",
        "Wants=network-online.target",
        "After=network-online.target",
        "",
        "[Service]",
        f"Type={service_type}",
        f"WorkingDirectory={working_directory}",
        'Environment="PYTHONUNBUFFERED=1"',
        (
            "ExecStart="
            + " ".join(
                [
                    systemd_quote(python_bin),
                    systemd_quote(str(runner_path)),
                    "--config",
                    systemd_quote(str(config_path)),
                    "--mode",
                    systemd_quote(mode),
                ]
            )
        ),
        "KillSignal=SIGINT",
        "KillMode=control-group",
        "TimeoutStopSec=45",
        "Restart=no",
        "StandardOutput=journal",
        "StandardError=journal",
        f"SyslogIdentifier={syslog_identifier}",
        "",
        "[Install]",
    ]
    unit_lines.extend(f"WantedBy={target}" for target in wanted_by_lines)
    unit_lines.append("")
    return "\n".join(unit_lines)


def maybe_daemon_reload() -> None:
    result = subprocess.run(
        ["systemctl", "--user", "daemon-reload"],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if result.returncode != 0:
        stderr = (result.stderr or "").strip()
        stdout = (result.stdout or "").strip()
        details = stderr or stdout or "systemctl --user daemon-reload failed"
        raise SystemExit(details)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Render and register songh systemd --user units from a TOML config."
    )
    parser.add_argument("--config", required=True, help="path to ops/systemd TOML config")
    parser.add_argument(
        "--unit-dir",
        default="",
        help="override target user unit directory; defaults to config service.user_unit_dir",
    )
    parser.add_argument(
        "--skip-daemon-reload",
        action="store_true",
        help="write unit files only and skip systemctl --user daemon-reload",
    )
    args = parser.parse_args()

    config_path = Path(args.config).expanduser().resolve()
    config = load_toml(config_path)
    service, modes, install = validate_config(config)

    script_dir = Path(__file__).resolve().parent
    repo_root = script_dir.parent.parent
    config_dir = config_path.parent
    working_directory = resolve_path(
        repo_root,
        str(service.get("working_directory", ".")),
    )
    runner_path = resolve_path(
        script_dir,
        str(service.get("runner_script", "run_songh_user_service.py")),
    )
    if not runner_path.exists():
        raise SystemExit(f"missing runner script: {runner_path}")

    configured_python_bin = str(service.get("python_bin", sys.executable)).strip() or sys.executable
    python_bin = shutil.which(configured_python_bin) or configured_python_bin
    unit_name_prefix = str(service.get("unit_name_prefix", "songh-live")).strip()
    default_description = str(service.get("description", "songh stage7 live runtime")).strip()
    journal_identifier_prefix = str(
        service.get("journal_identifier_prefix", unit_name_prefix)
    ).strip()
    default_service_type = str(service.get("service_type", "simple")).strip() or "simple"
    user_unit_dir_raw = args.unit_dir or service.get("user_unit_dir", "~/.config/systemd/user")
    user_unit_dir = resolve_path(config_dir, str(user_unit_dir_raw))
    wanted_by = install.get("wanted_by", ["default.target"])
    if not isinstance(wanted_by, list) or not wanted_by:
        raise SystemExit("install.wanted_by must be a non-empty TOML array")

    user_unit_dir.mkdir(parents=True, exist_ok=True)
    written_units: list[Path] = []
    for mode, mode_config in sorted(modes.items()):
        if not isinstance(mode_config, dict):
            raise SystemExit(f"invalid mode config for {mode}")
        unit_name = build_unit_name(unit_name_prefix, mode)
        mode_description = str(mode_config.get("description", default_description)).strip()
        service_type = str(mode_config.get("service_type", default_service_type)).strip() or "simple"
        syslog_identifier = f"{journal_identifier_prefix}-{mode}"
        unit_payload = render_unit(
            description=mode_description,
            mode=mode,
            service_type=service_type,
            working_directory=working_directory,
            runner_path=runner_path,
            config_path=config_path,
            python_bin=python_bin,
            syslog_identifier=syslog_identifier,
            wanted_by=[str(item) for item in wanted_by],
        )
        unit_path = user_unit_dir / unit_name
        unit_path.write_text(unit_payload, encoding="utf-8")
        written_units.append(unit_path)

    if not args.skip_daemon_reload:
        maybe_daemon_reload()

    print("songh systemd --user units installed")
    print(f"config: {config_path}")
    print(f"unit_dir: {user_unit_dir}")
    print(f"working_directory: {working_directory}")
    for unit_path in written_units:
        unit_name = unit_path.name
        print(f"unit: {unit_path}")
        print(f"start_cmd: systemctl --user start {unit_name}")
        print(f"log_cmd: journalctl --user -u {unit_name} -f")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
