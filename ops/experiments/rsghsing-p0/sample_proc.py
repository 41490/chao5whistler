#!/usr/bin/env python3
"""Sample RSS + CPU% of a process tree from /proc — the pidstat -rud stand-in.

pidstat is not installed on this host (no sysstat package), so this reads the
same numbers straight out of /proc: VmRSS for resident memory and
utime+stime deltas over CLK_TCK for CPU. CPU% is normalised to ONE core
(100% = one saturated core), which is what pidstat reports.

Usage:
    sample_proc.py --pid 1234 --interval 10 --duration 300 --out cpu.csv
                   [--summary summary.json] [--label live-v2]

Outputs one CSV row per sample per live process in the tree (root pid plus
every descendant), then a per-pid + tree summary.
"""

import argparse
import csv
import json
import os
import sys
import time

CLK = os.sysconf("SC_CLK_TCK")
NCPU = os.cpu_count() or 1


def read_stat(pid):
    try:
        with open(f"/proc/{pid}/stat", "rb") as f:
            data = f.read().decode("utf-8", "replace")
    except OSError:
        return None
    rp = data.rfind(")")
    if rp < 0:
        return None
    comm = data[data.find("(") + 1 : rp]
    rest = data[rp + 2 :].split()
    # rest[0]=state rest[1]=ppid ... rest[11]=utime rest[12]=stime
    try:
        return comm, int(rest[1]), int(rest[11]) + int(rest[12])
    except (IndexError, ValueError):
        return None


def read_rss(pid):
    try:
        with open(f"/proc/{pid}/status") as f:
            for line in f:
                if line.startswith("VmRSS:"):
                    return int(line.split()[1])  # kB
    except OSError:
        pass
    return 0


def descendants(root):
    """root pid plus every live descendant, discovered by a ppid walk."""
    stats = {}
    for entry in os.listdir("/proc"):
        if not entry.isdigit():
            continue
        pid = int(entry)
        st = read_stat(pid)
        if st:
            stats[pid] = st
    kids = {}
    for pid, (_comm, ppid, _cpu) in stats.items():
        kids.setdefault(ppid, []).append(pid)
    out, stack = [], [root]
    while stack:
        pid = stack.pop()
        if pid not in stats:
            continue
        out.append(pid)
        stack.extend(kids.get(pid, []))
    return out, stats


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pid", type=int, required=True)
    ap.add_argument("--interval", type=float, default=10.0)
    ap.add_argument("--duration", type=float, default=300.0)
    ap.add_argument("--out", required=True)
    ap.add_argument("--summary")
    ap.add_argument("--label", default="")
    args = ap.parse_args()

    rows = []
    prev = {}
    tree_rss, tree_cpu = [], []
    start = time.monotonic()
    n = max(1, int(round(args.duration / args.interval)))

    for i in range(n + 1):
        pids, stats = descendants(args.pid)
        if not pids:
            break
        rss_sum = 0
        cpu_sum = 0.0
        now = time.monotonic() - start
        for pid in pids:
            comm, _ppid, cputicks = stats[pid]
            rss = read_rss(pid)
            rss_sum += rss
            if pid in prev:
                dticks = cputicks - prev[pid]
                dt = args.interval
                cpu = (dticks / CLK) / dt * 100.0  # % of one core
            else:
                cpu = 0.0
            prev[pid] = cputicks
            cpu_sum += cpu
            rows.append(
                {
                    "t": round(now, 1),
                    "pid": pid,
                    "comm": comm,
                    "rss_kb": rss,
                    "cpu_pct_one_core": round(cpu, 1),
                }
            )
        tree_rss.append(rss_sum)
        tree_cpu.append(cpu_sum)
        if i == n:
            break
        time.sleep(args.interval)

    with open(args.out, "w", newline="") as f:
        w = csv.DictWriter(
            f, fieldnames=["t", "pid", "comm", "rss_kb", "cpu_pct_one_core"]
        )
        w.writeheader()
        w.writerows(rows)

    per_pid = {}
    for r in rows:
        d = per_pid.setdefault(
            (r["pid"], r["comm"]),
            {"rss_peak_kb": 0, "rss_sum": 0, "rss_n": 0, "cpu_sum": 0.0, "cpu_n": 0},
        )
        d["rss_peak_kb"] = max(d["rss_peak_kb"], r["rss_kb"])
        d["rss_sum"] += r["rss_kb"]
        d["rss_n"] += 1
        d["cpu_sum"] += r["cpu_pct_one_core"]
        d["cpu_n"] += 1

    procs = []
    for (pid, comm), d in sorted(per_pid.items()):
        procs.append(
            {
                "pid": pid,
                "comm": comm,
                "rss_peak_kb": d["rss_peak_kb"],
                "rss_avg_kb": round(d["rss_sum"] / max(1, d["rss_n"]), 1),
                # CPU% is only meaningful from the 2nd sample on.
                "cpu_avg_pct_one_core": round(
                    d["cpu_sum"] / max(1, d["cpu_n"] - 1) if d["cpu_n"] > 1 else 0.0, 1
                ),
            }
        )

    summary = {
        "label": args.label,
        "root_pid": args.pid,
        "ncpu": NCPU,
        "samples": len(rows),
        "interval_secs": args.interval,
        "procs": procs,
        "tree_rss_peak_kb": max(tree_rss) if tree_rss else 0,
        "tree_rss_avg_kb": round(sum(tree_rss) / len(tree_rss), 1) if tree_rss else 0,
        "tree_cpu_avg_pct_one_core": round(
            sum(tree_cpu[1:]) / max(1, len(tree_cpu) - 1), 1
        )
        if len(tree_cpu) > 1
        else 0.0,
    }
    if args.summary:
        with open(args.summary, "w") as f:
            json.dump(summary, f, indent=2)
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
