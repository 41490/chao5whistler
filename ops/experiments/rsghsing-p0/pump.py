#!/usr/bin/env python3
"""S1-TS relay prototype: paced byte pump -> persistent ffmpeg -c copy flv.

Feeds pre-rendered .ts segments into ONE long-lived ffmpeg process
(`-f mpegts -i pipe:0 -c copy -f flv`) at realtime pace, i.e. the wall-clock
byte pump of the rsghsing S1 design (zero transcode). While the pump runs it
also samples the ffmpeg process tree with sample_proc.py so the CPU cost of
the relay itself is on record.

Usage:
    pump.py --segments a.ts b.ts --total-duration 300 --out relay.flv \
            --log relay.log --cpu-csv relay-ffmpeg-cpu.csv
"""

import argparse
import os
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
CHUNK = 32 * 1024


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--segments", nargs="+", required=True)
    ap.add_argument("--total-duration", type=float, required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--log", required=True)
    ap.add_argument("--cpu-csv")
    args = ap.parse_args()

    total_bytes = sum(os.path.getsize(p) for p in args.segments)
    if total_bytes <= 0:
        print("pump: empty input", file=sys.stderr)
        return 1

    with open(args.log, "w") as logf:
        proc = subprocess.Popen(
            [
                "ffmpeg", "-hide_banner", "-v", "warning",
                "-f", "mpegts", "-i", "pipe:0",
                "-c", "copy", "-f", "flv", "-y", args.out,
            ],
            stdin=subprocess.PIPE,
            stdout=logf,
            stderr=logf,
        )

    sampler = None
    stdin = proc.stdin
    if stdin is None:  # pragma: no cover - Popen always gives us a pipe
        print("pump: no stdin pipe", file=sys.stderr)
        return 1
    if args.cpu_csv:
        sampler = subprocess.Popen(
            [
                sys.executable, os.path.join(HERE, "sample_proc.py"),
                "--pid", str(proc.pid),
                "--interval", "1",
                "--duration", str(int(args.total_duration) + 5),
                "--out", args.cpu_csv,
                "--summary", args.cpu_csv + ".json",
                "--label", "relay-ffmpeg",
            ],
            stdout=subprocess.DEVNULL,
        )

    start = time.monotonic()
    written = 0
    for path in args.segments:
        with open(path, "rb") as f:
            while True:
                chunk = f.read(CHUNK)
                if not chunk:
                    break
                try:
                    stdin.write(chunk)
                except BrokenPipeError:
                    print("pump: ffmpeg closed the pipe early", file=sys.stderr)
                    return 1
                written += len(chunk)
                # Pace: bytes_written/total_bytes of the content must map to
                # the same fraction of the realtime duration.
                target = written / total_bytes * args.total_duration
                lag = time.monotonic() - start
                if target > lag:
                    time.sleep(target - lag)
    stdin.close()
    rc = proc.wait()
    if sampler:
        sampler.wait()

    wall = time.monotonic() - start
    print(
        f"PUMP bytes={written} wall_secs={wall:.2f} "
        f"pace_x={args.total_duration / wall:.3f} ffmpeg_rc={rc}"
    )
    return rc


if __name__ == "__main__":
    sys.exit(main())
