#!/usr/bin/env python3
"""Layer composition pipeline: overlay staff + spectra + dice, inject L3 progress, 15-frame transparent segments."""

import argparse
import subprocess
from pathlib import Path

# Fixed progress value: 11^16 = 45,949,729,863,572,161
PROGRESS = "123/45949729863572161"

def compose(staff, spectra, dice, output):
    """Compose three transparent layers into a single video."""
    cmd = [
        "ffmpeg", "-y", "-i", staff, "-i", spectra, "-i", dice,
        "-filter_complex",
        # Overlay staff and spectra side-by-side
        "[0:v][1:v]overlay=0:0[s1];[s1][2:v]overlay=0:0[s2]",
        # Inject L3 progress layer at bottom center
        "-vf", f"drawtext=text='{PROGRESS}':x=20:y=30:fontfile=/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf:fontcolor=white:fontsize=16",
        "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p",
        output
    ]
    subprocess.run(cmd, check=True)

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Composite staff, spectra, and dice layers into a single video with L3 progress overlay."
    )
    parser.add_argument("--staff", required=True, help="Path to staff layer video (PPM/PNG sequence)")
    parser.add_argument("--spectra", required=True, help="Path to spectra layer video (PPM/PNG sequence)")
    parser.add_argument("--dice", required=True, help="Path to dice animation video (PPM/PNG sequence)")
    parser.add_argument("--output", required=True, help="Output video path")
    args = parser.parse_args()
    compose(args.staff, args.spectra, args.dice, args.output)
