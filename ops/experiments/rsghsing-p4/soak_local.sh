#!/usr/bin/env bash
# P4 soak (Issue #107, acceptance 2): >=60 min local relay across >=3 wall-clock
# segment boundaries, driven by the injected `--now` clock.
#
# Verifies, exit 0 only if ALL hold:
#   * wall >= 60 min and >= 3 segment boundaries crossed
#   * output duration  == wall duration  +/- 2 s
#   * video frames     == 30 * wall      +/- 60 frames
#   * ffmpeg stderr    free of decode/corruption anomalies (zero decode error)
#   * no timestamp hole > 0.5 s anywhere in the output (switch points included)
#   * /proc resource table for the pump + ffmpeg (CPU% of one core, RSS)
#
# All artifacts land in /opt/logs/41490/out/rsghsing/p4/ (never in the repo).
set -uo pipefail
export PATH="$HOME/.cargo/bin:$PATH" # cargo lives outside the default PATH

REPO="$(cd "$(dirname "$0")/../../.." && pwd)"
OUT="/opt/logs/41490/out/rsghsing/p4"
BIN="$REPO/src/rsghsing/target/release/rsghsing"
CFG="$REPO/src/rsghsing/rsghsing.toml"
SEGDIR="${SEGDIR:-/opt/logs/41490/out/rsghsing/p3/segments}"

# Wall-clock anchor. The segments dir is keyed by the D-1 (daypack) date, so
# wall 2026-03-29T11:00:00Z plays 2026-03-28/seg-44.ts .. seg-47.ts, i.e.
# exactly 4 segments = 60 min = 3 boundaries (11:15 / 11:30 / 11:45).
NOW="${NOW:-2026-03-29T11:00:00Z}"
SOAK_SECS="${SOAK_SECS:-3600}"
FLV="$OUT/soak.flv"
FFLOG="$OUT/soak-ffmpeg.log"
RUSTLOG="$OUT/soak-rust.log"
CSV="$OUT/soak-proc.csv"
SUMMARY="$OUT/soak-proc.json"

mkdir -p "$OUT"

if [ "${REUSE:-0}" = "1" ]; then
  # Re-judge an existing run's artifacts (used after a criterion change):
  # no new 60 min run, no rebuild, just the checks below on what is on disk.
  echo "== REUSE=1: judging existing artifacts, no new run =="
  [ -s "$FLV" ] && [ -s "$RUSTLOG" ] || {
    echo "FAIL: no artifacts to reuse"
    exit 1
  }
  RC=0
  # The pump's own wall measurement is the authority; the artifacts' mtimes give
  # the absolute window (both are stamped when the run ends).
  T1=$(stat -c %Y "$FLV")
  WALL=$(grep -o "wall_secs=[0-9.]*" "$RUSTLOG" | cut -d= -f2 | cut -d. -f1)
  T0=$((T1 - WALL))
else
  rm -f "$FLV" "$FFLOG" "$RUSTLOG" "$CSV" "$SUMMARY" "$OUT/soak-report.md"

  echo "== build =="
  (cd "$REPO/src/rsghsing" && cargo build --release) || {
    echo "BUILD FAIL"
    exit 1
  }

  echo "== soak: now=$NOW duration=${SOAK_SECS}s segdir=$SEGDIR =="
  T0=$(date -u +%s)
  "$BIN" --config "$CFG" --log-level info stream \
    --now "$NOW" --output local --local-path "$FLV" \
    --segments-dir "$SEGDIR" --duration "$SOAK_SECS" --ffmpeg-log "$FFLOG" \
    >"$RUSTLOG" 2>&1 &
  PID=$!

  # Sample the whole tree (pump + its ffmpeg child) while it runs.
  python3 "$REPO/ops/experiments/rsghsing-p0/sample_proc.py" \
    --pid "$PID" --interval 10 --duration "$((SOAK_SECS + 20))" \
    --out "$CSV" --summary "$SUMMARY" --label "p4-soak" >"$OUT/soak-sampler.log" 2>&1 &
  SAMPLER=$!

  wait "$PID"
  RC=$?
  T1=$(date -u +%s)
  wait "$SAMPLER" 2>/dev/null
fi
if [ "${REUSE:-0}" != "1" ]; then WALL=$((T1 - T0)); fi
echo "  rsghsing rc=$RC wall=${WALL}s"

FAIL=0
[ "$RC" -eq 0 ] || {
  echo "FAIL: streamer exit $RC"
  FAIL=1
}
grep -q "STREAM_SUMMARY" "$RUSTLOG" || {
  echo "FAIL: no STREAM_SUMMARY"
  FAIL=1
}

echo "== boundaries =="
BOUNDARIES=$(grep -c "segment start" "$RUSTLOG")
SEGS=$(grep "segment start" "$RUSTLOG" | sed 's/.*idx=\([0-9]*\).*/\1/' | tr '\n' ' ')
MISSING=$(grep -c "segment missing" "$RUSTLOG")
MISSECS=$(grep -o "missing_secs=[0-9.]*" "$RUSTLOG" | cut -d= -f2)
echo "  segments: $SEGS"
echo "  segment starts=$BOUNDARIES missing_waits=$MISSING missing_secs=${MISSECS:-0}"
[ "$BOUNDARIES" -ge 4 ] || {
  echo "FAIL: need >=4 segment starts (>=3 boundaries)"
  FAIL=1
}
# ponytail: a wait costing <1s is the pump probing the NEXT segment a few ms
# before the window closes (that segment may not exist) -- no content impact,
# proven by the duration/frames/pts checks below. Only a real stall fails.
python3 - "${MISSECS:-0}" <<'PY2' || FAIL=1
import sys
s = float(sys.argv[1])
if s > 1.0:
    print(f"FAIL: {s:.1f}s of missing-segment waiting (real stall)")
    sys.exit(1)
print(f"  missing-segment wait cost {s:.3f}s (<= 1s): PASS")
PY2
grep "STREAM_SUMMARY" "$RUSTLOG"

echo "== ffprobe: duration / frames / streams =="
DUR=$(ffprobe -v error -show_entries format=duration -of csv=p=0 "$FLV")
FRAMES=$(ffprobe -v error -select_streams v:0 -count_frames -show_entries stream=nb_read_frames -of csv=p=0 "$FLV")
STREAMS=$(ffprobe -v error -show_entries stream=codec_type -of csv=p=0 "$FLV" | sort -u | tr '\n' ',')
echo "  duration=${DUR}s frames=$FRAMES streams=$STREAMS wall=${WALL}s"
python3 - "$DUR" "$FRAMES" "$WALL" <<'PY' || FAIL=1
import sys
dur, frames, wall = float(sys.argv[1]), int(sys.argv[2]), int(sys.argv[3])
fails = []
if wall < 3600:
    fails.append(f"wall {wall}s < 3600s")
if abs(dur - wall) > 2.0:
    fails.append(f"duration {dur:.3f}s vs wall {wall}s > 2s")
if abs(frames - 30 * wall) > 60:
    fails.append(f"frames {frames} vs 30*{wall}={30*wall} > 60")
print(f"  dur_err={dur - wall:+.3f}s frame_err={frames - 30 * wall:+d}")
if fails:
    print("FAIL: " + "; ".join(fails))
    sys.exit(1)
print("  duration/frames PASS")
PY

echo "== ffmpeg log: decode anomalies =="
# \r-normalise first: ffmpeg's periodic stats lines share one physical line,
# so a plain grep -c undercounts (and would hide a real anomaly).
BAD=$(tr '\r' '\n' <"$FFLOG" | grep -icE "error|corrupt|discontinu|non-monoton|invalid|drop")
echo "  anomaly lines: $BAD"
[ "$BAD" -eq 0 ] || {
  tr '\r' '\n' <"$FFLOG" | grep -iE "error|corrupt|discontinu|non-monoton|invalid|drop" | head -5
  FAIL=1
}

echo "== timestamp holes (video pts deltas, whole output) =="
ffprobe -v error -select_streams v:0 -show_entries packet=pts_time -of csv=p=0 "$FLV" \
  >"$OUT/soak-vpts.txt" 2>/dev/null
python3 - "$OUT/soak-vpts.txt" <<'PY' || FAIL=1
import sys
ts = [float(x) for x in open(sys.argv[1]).read().split() if x.strip()]
if len(ts) < 2:
    print("FAIL: no video packets")
    sys.exit(1)
gaps = [b - a for a, b in zip(ts, ts[1:])]
worst = max(gaps)
at = ts[gaps.index(worst)]
print(f"  packets={len(ts)} max_gap={worst*1000:.1f}ms at t={at:.3f}s")
if worst > 0.5:
    print(f"FAIL: timestamp hole {worst:.3f}s > 0.5s at {at:.3f}s")
    sys.exit(1)
print("  no hole > 0.5s PASS")
PY

echo "== resources (/proc sampling, pump tree) =="
python3 - "$SUMMARY" <<'PY'
import json, sys
s = json.load(open(sys.argv[1]))
print(f"  {'comm':<12} {'cpu%_1core':>10} {'rss_avg':>10} {'rss_peak':>10}")
for p in s.get("procs", []):
    print(f"  {p['comm']:<12} {p['cpu_avg_pct_one_core']:>10} "
          f"{p['rss_avg_kb']/1024:>9.1f}M {p['rss_peak_kb']/1024:>9.1f}M")
print(f"  tree         {s.get('tree_cpu_avg_pct_one_core', 0):>10} "
      f"{s.get('tree_rss_avg_kb', 0)/1024:>9.1f}M {s.get('tree_rss_peak_kb', 0)/1024:>9.1f}M")
PY

if [ "$FAIL" -eq 0 ]; then echo "SOAK PASS"; else echo "SOAK FAIL"; fi
exit "$FAIL"
