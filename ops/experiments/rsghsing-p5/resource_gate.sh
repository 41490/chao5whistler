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
# NB: gate-*.json* (not gate-*.json) — the metrics file is .jsonl.
rm -rf "$SEG" "$RAW" "$OUT"/gate-*.csv "$OUT"/gate-*.json* "$OUT"/gate-*.log "$OUT"/gate-*.flv
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

"$BIN" --config "$CFG" sched --duration "$((GATE_SECS + 240))" --now "$NOW" \
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
    return f[1], f[16]  # ppid, nice (state is f[0], utime f[11], stime f[12])

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
        ppid = int(s[0])  # stat() -> (ppid, nice)
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
            rows.append((round(time.time()), pid, int(stats[pid][1]), cmd.split("\x00")[0]))
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

# LIVE = the stream pump tree (remux ffmpeg is `-c copy`) + the sched daemon
# itself. RENDER = everything sched spawns (decision baseline #12: those are
# expected to be expensive, they are niced down, not gated).
groups = {"live": [], "render": []}
for src in (a, b):
    for pr in src.get("procs", []):
        live = src is b or pr["pid"] == src["root_pid"]
        groups["live" if live else "render"].append(pr)

print(f"  {'comm':<20}{'group':>8}{'cpu%_1core':>11}{'rss_peak':>11}")
totals = {}
for g, procs in groups.items():
    for pr in procs:
        k = (pr["comm"], g)
        d = totals.setdefault(k, [0.0, 0])
        d[0] += pr["cpu_avg_pct_one_core"]
        d[1] = max(d[1], pr["rss_peak_kb"])
for (comm, g), (c, r) in sorted(totals.items(), key=lambda kv: -kv[1][0]):
    print(f"  {comm:<20}{g:>8}{c:>11.1f}{r/1024:>9.1f}M")

def total(g):
    cpu = sum(p["cpu_avg_pct_one_core"] for p in groups[g])
    rss = sum(p["rss_peak_kb"] for p in groups[g]) / 1024
    return round(cpu, 1), rss
lcpu, lrss = total("live")
print(f"  {'LIVE STACK':<20}{'live':>8}{lcpu:>11.1f}{lrss:>9.1f}M")
if groups["render"]:
    rcpu, rrss = total("render")
    print(f"  {'render jobs':<20}{'render':>8}{rcpu:>11.1f}{rrss:>9.1f}M   (niced, not gated)")

fails = []
if lcpu > cpu_gate:
    fails.append(f"live-stack CPU {lcpu}% > {cpu_gate}% of one core")
if lrss > rss_gate_mb:
    fails.append(f"live-stack RSS {lrss:.1f}M > {rss_gate_mb}M")

# Render processes must be reniced (decision baseline #12).
nices, comms = [], set()
with open(nice_csv) as f:
    for r in csv.DictReader(f):
        nices.append(int(r["nice"]))
        comms.add(r["comm"])
if nices:
    lo = min(nices)
    print(f"  render/ffmpeg nice: min={lo} samples={len(nices)} comms={sorted(comms)}")
    if lo < nice_gate:
        fails.append(f"render nice {lo} < {nice_gate}")
else:
    fails.append("no render process was sampled (no concurrent render job?)")

if fails:
    print("FAIL: " + "; ".join(fails))
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
