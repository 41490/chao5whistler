#!/usr/bin/env bash
# P5 resource gate (Issue #108, acceptance 4) — exit 0 only if every gate holds.
#
# Local stream for 10 min WITH 2 concurrent render jobs running, sampled from
# /proc (pidstat is not installed on this host, so we reuse the P0 sampler).
#
# Gates:
#   * live-period full stack (sched + stream + ffmpeg remux) <= 30% of ONE core
#   * full-stack RSS <= 400 MB
#   * every render process runs at nice >= 10 (decision baseline #12)
#
# Everything runs on P5's own copy under /opt/logs/41490/out/rsghsing/p5/;
# the P3 originals are read-only input. No systemctl, no real enable/start.
set -uo pipefail

REPO="$(cd "$(dirname "$0")/../../.." && pwd)"
OUT="/opt/logs/41490/out/rsghsing/p5"
BIN="$REPO/src/rsghsing/target/release/rsghsing"
CFG="$REPO/src/rsghsing/rsghsing.toml"
P3SEG="/opt/logs/41490/out/rsghsing/p3/segments"
SEG="$OUT/segments"
RAW="$OUT/raw"
SAMPLER="$REPO/ops/experiments/rsghsing-p0/sample_proc.py"
NOW="2026-03-29T11:00:00Z"   # plays D-1 = 2026-03-28, ready window seg-44..48
GATE_SECS="${GATE_SECS:-600}"
INTERVAL="${INTERVAL:-10}"
CPU_GATE="${CPU_GATE:-30}"
RSS_GATE_MB="${RSS_GATE_MB:-400}"
NICE_GATE="${NICE_GATE:-10}"

FAIL=0
say() { printf '%s\n' "$*"; }
ok() { say "  PASS $*"; }
bad() { say "  FAIL $*"; FAIL=1; }

[ -x "$BIN" ] || { say "FAIL: no binary at $BIN"; exit 1; }
[ -d "$P3SEG/2026-03-28" ] || { say "FAIL: no P3 segments at $P3SEG"; exit 1; }
[ "$SEG" != "$P3SEG" ] || { say "FAIL: refusing to touch the P3 tree"; exit 1; }
mkdir -p "$OUT"

# ---------------------------------------------------------------- set-up
say "== set-up: P5 copy with TWO holes in the ready window =="
rm -rf "$SEG" "$RAW" "$OUT"/gate-*.csv "$OUT"/gate-*.json "$OUT"/gate-*.log "$OUT"/gate-*.flv
mkdir -p "$RAW" "$SEG"
cp -r "$P3SEG/2026-03-28" "$SEG/2026-03-28"
[ -s "$SEG/2026-03-28/seg-44.ts" ] || { say "FAIL: P5 copy failed"; exit 1; }
# 45 and 46 missing -> exactly render_jobs=2 concurrent renders for the window.
rm -f "$SEG/2026-03-28/seg-45.ts" "$SEG/2026-03-28/seg-46.ts"
say "  holes: seg-45, seg-46 (water level wants 44..48)"

# ---------------------------------------------------------------- run
say "== run: sched daemon + local stream for ${GATE_SECS}s =="
FLV="$OUT/gate-stream.flv"
FFLOG="$OUT/gate-ffmpeg.log"
SCHEDLOG="$OUT/gate-sched.log"
STREAMLOG="$OUT/gate-stream.log"

"$BIN" --config "$CFG" sched --duration "$((GATE_SECS + 240))" \
  --segments-dir "$SEG" --archive-dir "$RAW" \
  --metrics-file "$OUT/gate-metrics.jsonl" >"$SCHEDLOG" 2>&1 &
SCHED=$!

"$BIN" --config "$CFG" stream --now "$NOW" --output local --local-path "$FLV" \
  --segments-dir "$SEG" --duration "$GATE_SECS" --ffmpeg-log "$FFLOG" \
  >"$STREAMLOG" 2>&1 &
STREAM=$!
say "  sched pid=$SCHED stream pid=$STREAM"

# nice sampler: every 2 s, record the nice value of every live render process
# (the reniced rsghsing/ffmpeg children of the sched tree).
python3 - "$SCHED" "$OUT/gate-nice.csv" "$GATE_SECS" <<'PY' &
import os, sys, time
root, out, secs = int(sys.argv[1]), sys.argv[2], float(sys.argv[3])

def stat(pid):
    try:
        d = open(f"/proc/{pid}/stat", "rb").read().decode("utf-8", "replace")
    except OSError:
        return None
    rp = d.rfind(")")
    f = d[rp + 2:].split()
    return f[16], f[17]  # nice, priority (state is f[0])

def all_stats():
    stats = {}
    for e in os.listdir("/proc"):
        if not e.isdigit():
            continue
        s = stat(int(e))
        if s:
            stats[int(e)] = s
    return stats

def descendants(root, stats):
    kids = {}
    for pid, s in stats.items():
        ppid = int(s[1])
        kids.setdefault(ppid, []).append(pid)
    out, stack = [], [root]
    while stack:
        p = stack.pop()
        if p not in stats:
            continue
        out.append(p)
        stack.extend(kids.get(p, []))
    return out

end = time.time() + secs
rows = []
while time.time() < end:
    stats = all_stats()
    for pid in descendants(root, stats):
        try:
            cmd = open(f"/proc/{pid}/cmdline", "rb").read().decode("utf-8", "replace")
        except OSError:
            continue
        if "render" in cmd or "ffmpeg" in cmd:
            rows.append((round(time.time()), pid, int(stats[pid][0]), cmd.split("\x00")[0]))
    time.sleep(2)
with open(out, "w") as f:
    f.write("t,pid,nice,comm\n")
    for r in rows:
        f.write("%d,%d,%d,%s\n" % r)
PY
NICE=$!

python3 "$SAMPLER" --pid "$SCHED" --interval "$INTERVAL" \
  --duration "$((GATE_SECS + 30))" --out "$OUT/gate-sched-proc.csv" \
  --summary "$OUT/gate-sched-proc.json" --label "p5-gate-sched" \
  >"$OUT/gate-sampler-sched.log" 2>&1 &
SAMP1=$!
python3 "$SAMPLER" --pid "$STREAM" --interval "$INTERVAL" \
  --duration "$((GATE_SECS + 30))" --out "$OUT/gate-stream-proc.csv" \
  --summary "$OUT/gate-stream-proc.json" --label "p5-gate-stream" \
  >"$OUT/gate-sampler-stream.log" 2>&1 &
SAMP2=$!

wait "$STREAM"; RC_STREAM=$?
wait "$SCHED"; RC_SCHED=$?
wait "$NICE" 2>/dev/null
wait "$SAMP1" "$SAMP2" 2>/dev/null
say "  stream rc=$RC_STREAM sched rc=$RC_SCHED"
[ "$RC_STREAM" -eq 0 ] || bad "streamer exited $RC_STREAM"
[ "$RC_SCHED" -eq 0 ] || bad "sched exited $RC_SCHED"

# ---------------------------------------------------------------- judge
say "== gate: live-period full stack (sched tree + stream tree) =="
python3 - "$OUT/gate-sched-proc.json" "$OUT/gate-stream-proc.json" \
  "$CPU_GATE" "$RSS_GATE_MB" "$OUT/gate-nice.csv" "$NICE_GATE" <<'PY' || FAIL=1
import csv, json, sys
sched, stream, cpu_gate, rss_gate_mb = sys.argv[1], sys.argv[2], float(sys.argv[3]), int(sys.argv[4])
nice_csv, nice_gate = sys.argv[5], int(sys.argv[6])
a, b = json.load(open(sched)), json.load(open(stream))

def rows(p):
    out = {}
    for pr in p.get("procs", []):
        k = pr["comm"]
        d = out.setdefault(k, {"cpu": 0.0, "rss_peak": 0, "n": 0})
        d["cpu"] += pr["cpu_avg_pct_one_core"]
        d["rss_peak"] = max(d["rss_peak"], pr["rss_peak_kb"])
        d["n"] += 1
    return out

merged = {}
for src in (a, b):
    for comm, d in rows(src).items():
        m = merged.setdefault(comm, {"cpu": 0.0, "rss_peak": 0})
        m["cpu"] += d["cpu"]
        m["rss_peak"] = max(m["rss_peak"], d["rss_peak"])

print(f"  {'comm':<14}{'cpu%_1core':>11}{'rss_peak':>11}")
for comm, d in sorted(merged.items(), key=lambda kv: -kv[1]["cpu"]):
    print(f"  {comm:<14}{d['cpu']:>11.1f}{d['rss_peak']/1024:>9.1f}M")
cpu = round(sum(d["cpu"] for d in merged.values()), 1)
rss = sum(d["rss_peak"] for d in merged.values()) / 1024
print(f"  {'FULL STACK':<14}{cpu:>11.1f}{rss:>9.1f}M")

fails = []
if cpu > cpu_gate:
    fails.append(f"full-stack CPU {cpu}% > {cpu_gate}% of one core")
if rss > rss_gate_mb:
    fails.append(f"full-stack RSS {rss:.1f}M > {rss_gate_mb}M")

# Render processes must be reniced (decision baseline #12).
nices = []
with open(nice_csv) as f:
    for r in csv.DictReader(f):
        nices.append(int(r["nice"]))
if nices:
    lo = min(nices)
    print(f"  render/ffmpeg nice: min={lo} samples={len(nices)} comms="
          f"{sorted({r['comm'] for r in csv.DictReader(open(nice_csv))})}")
    if lo < nice_gate:
        fails.append(f"render nice {lo} < {nice_gate}")
else:
    fails.append("no render process was sampled (no concurrent render job?)")

if fails:
    print("FAIL: " + "; ".join(fails))
    sys.exit(1)
print(f"  CPU {cpu}% <= {cpu_gate}% ; RSS {rss:.1f}M <= {rss_gate_mb}M ; nice >= {nice_gate}")
PY
[ "${FAIL:-0}" -eq 0 ] && ok "CPU/RSS/nice gates"

say "== gate: relay integrity under load =="
grep -q STREAM_SUMMARY "$STREAMLOG" || bad "no STREAM_SUMMARY"
grep STREAM_SUMMARY "$STREAMLOG"
python3 - "$OUT/gate-metrics.jsonl" <<'PY' || FAIL=1
import json, sys
ticks = [json.loads(l) for l in open(sys.argv[1]) if l.strip()]
if not ticks:
    print("FAIL: no metrics ticks"); sys.exit(1)
last = ticks[-1]
print(f"  ticks={len(ticks)} rendered_total={last['rendered_total']} "
      f"removed_total={last['removed_total']} on_disk={last['on_disk']}")
assert last["rendered_total"] >= 2, last["rendered_total"]
assert last["on_disk"] == 5, last["on_disk"]
PY
[ "${FAIL:-0}" -eq 0 ] && ok "water level held while streaming"

say "== resource gate summary =="
if [ "$FAIL" -eq 0 ]; then say "RESOURCE_GATE PASS"; else say "RESOURCE_GATE FAIL"; fi
exit "$FAIL"
