#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import shlex
import shutil
import subprocess
from pathlib import Path

TOTAL_COMBINATIONS = 45949729863572161
CONFIG_PATH = Path(__file__).with_name("position_config.json")


def ffmpeg_binary() -> str:
    for candidate in (shutil.which("ffmpeg"), "/usr/bin/ffmpeg"):
        if candidate and Path(candidate).exists():
            filters = subprocess.run(
                [candidate, "-filters"], capture_output=True, text=True, check=False
            ).stdout
            if "drawtext" in filters:
                return candidate
    return "ffmpeg"

def build_command(fragment: int, output: Path) -> list[str]:
    config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    position = config["fragments"][str(fragment)]
    text = position["text_template"].format(fragment=fragment)
    drawtext = f"drawtext=text={text}:x={position['x']}:y={position['y']}"
    return [
        ffmpeg_binary(), "-y", "-f", "lavfi", "-i", "color=c=black:s=320x240:r=1",
        "-frames:v", "1", "-vf", drawtext, "-pix_fmt", "yuvj444p", str(output),
    ]

def main() -> int:
    parser = argparse.ArgumentParser(description="Inject fragment progress with ffmpeg drawtext.")
    parser.add_argument("--fragment", required=True, type=int)
    parser.add_argument("--output", type=Path, default=Path("progress.ppm"))
    parser.add_argument("--print-command", action="store_true")
    args = parser.parse_args()
    if not 1 <= args.fragment <= 176:
        parser.error("--fragment must be between 1 and 176")
    command = build_command(args.fragment, args.output)
    print(shlex.join(command))
    if args.print_command:
        return 0
    subprocess.run(command, check=True)
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
