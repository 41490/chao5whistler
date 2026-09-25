#!/usr/bin/env bash
# P4 RTMPS preflight (Issue #107, acceptance 3): 60 s of REAL push to YouTube
# through the same persistent `ffmpeg -c copy -f flv` session the soak uses.
#
# Verifies, exit 0 only if ALL hold:
#   * the streamer ran the full 60 s window and exited 0 (ffmpeg never died)
#   * ffmpeg's stderr shows continuous writes and no error/corruption line
#   * the UTC window is recorded, and the stream key appears NOWHERE in any
#     artifact (the log is redacted by the streamer; this re-checks it)
#
# The url/key come from src/rsghsing/rsghsing.local.toml (gitignored, read-only
# overlay). They are never echoed: the key is read into a variable, used only
# for grep, and only the MATCH COUNT is printed.
set -uo pipefail
export PATH="$HOME/.cargo/bin:$PATH"

REPO="$(cd "$(dirname "$0")/../../.." && pwd)"
OUT="/opt/logs/41490/out/rsghsing/p4"
BIN="$REPO/src/rsghsing/target/release/rsghsing"
CFG="$REPO/src/rsghsing/rsghsing.toml"
OVERLAY="$REPO/src/rsghsing/rsghsing.local.toml"
SEGDIR="${SEGDIR:-/opt/logs/41490/out/rsghsing/p3/segments}"
NOW="${NOW:-2026-03-29T11:00:00Z}"
PUSH_SECS="${PUSH_SECS:-60}"
FFLOG="$OUT/preflight-ffmpeg.log"
RUSTLOG="$OUT/preflight-rust.log"
CSV="$OUT/preflight-proc.csv"

mkdir -p "$OUT"
rm -f "$FFLOG" "$RUSTLOG" "$CSV" "$CSV.json" "$OUT/preflight-sampler.log"

echo "== build =="
(cd "$REPO/src/rsghsing" && cargo build --release) || {
  echo "BUILD FAIL"
  exit 1
}

[ -f "$OVERLAY" ] || {
  echo "FAIL: missing overlay $OVERLAY"
  exit 1
}
# Key = last path segment of output.rtmps.url. Read, never printed.
KEY=$(sed -n 's/^url[[:space:]]*=[[:space:]]*".*\/\([^"/]*\)"/\1/p' "$OVERLAY" | head -1)
[ -n "$KEY" ] || {
  echo "FAIL: no rtmps url in the overlay"
  exit 1
}

echo "== rtmps push: now=$NOW duration=${PUSH_SECS}s =="
T0=$(date -u +%Y-%m-%dT%H:%M:%SZ)
E0=$(date -u +%s)
"$BIN" --config "$CFG" --log-level info stream \
  --now "$NOW" --duration "$PUSH_SECS" --segments-dir "$SEGDIR" --ffmpeg-log "$FFLOG" \
  >"$RUSTLOG" 2>&1 &
PID=$!
python3 "$REPO/ops/experiments/rsghsing-p0/sample_proc.py" \
  --pid "$PID" --interval 5 --duration "$((PUSH_SECS + 10))" \
  --out "$CSV" --summary "$CSV.json" --label "p4-rtmps-preflight" \
  >"$OUT/preflight-sampler.log" 2>&1 &
SAMPLER=$!
wait "$PID"
RC=$?
T1=$(date -u +%Y-%m-%dT%H:%M:%SZ)
E1=$(date -u +%s)
wait "$SAMPLER" 2>/dev/null
echo "  rsghsing rc=$RC window=${T0} .. ${T1} ($((E1 - E0))s)"

FAIL=0
[ "$RC" -eq 0 ] || {
  echo "FAIL: streamer exit $RC"
  FAIL=1
}
grep -q "STREAM_SUMMARY" "$RUSTLOG" || {
  echo "FAIL: no STREAM_SUMMARY"
  FAIL=1
}
grep "STREAM_SUMMARY" "$RUSTLOG"
grep -E "session lost|restarts=[1-9]" "$RUSTLOG" && {
  echo "FAIL: ffmpeg session restarted"
  FAIL=1
}

echo "== ffmpeg stderr summary (redacted) =="
# ffmpeg's periodic stats lines are \r-separated on one physical line, so
# normalise first or the counts lie.
# "Failed to update header with correct duration/filesize" is expected here:
# the FLV muxer cannot seek back on a non-seekable socket to patch its header.
BAD=$(tr '\r' '\n' <"$FFLOG" |
  grep -iE "error|corrupt|invalid|failed|refused|timed out" |
  grep -v "Failed to update header" | wc -l)
echo "  anomaly lines: $BAD"
[ "$BAD" -eq 0 ] || {
  tr '\r' '\n' <"$FFLOG" | grep -iE "error|corrupt|invalid|failed|refused|timed out" | grep -v "Failed to update header" | head -5
  FAIL=1
}
# Continuous writes: at least 3 periodic stats lines, the last one at ~60s.
STATS=$(tr '\r' '\n' <"$FFLOG" | grep -c "^frame=")
LAST=$(tr '\r' '\n' <"$FFLOG" | grep "^frame=" | tail -1 | sed 's/.*time=\([0-9:.]*\).*/\1/')
echo "  stats lines: $STATS last_time=$LAST"
[ "$STATS" -ge 3 ] || {
  echo "FAIL: fewer than 3 stats lines"
  FAIL=1
}
python3 - "$LAST" "$PUSH_SECS" <<'PY' || FAIL=1
import sys
last = sys.argv[1]
want = int(sys.argv[2])
parts = [float(x) for x in last.split(":")]
secs = parts[0] * 3600 + parts[1] * 60 + parts[2]
print(f"  last content time {secs:.2f}s vs window {want}s")
if secs < want - 5:
    print(f"FAIL: ffmpeg stopped writing at {secs:.1f}s (< {want - 5}s)")
    sys.exit(1)
print("  continuous write PASS")
PY

echo "== key-leak check (count only, never the value) =="
LEAK=$(grep -rF "$KEY" "$FFLOG" "$RUSTLOG" "$OUT/preflight-sampler.log" 2>/dev/null | wc -l)
echo "  occurrences of the stream key in artifacts: $LEAK"
[ "$LEAK" -eq 0 ] || {
  echo "FAIL: stream key leaked into an artifact"
  FAIL=1
}
grep -c "rtmps-url" "$FFLOG" | sed 's/^/  redacted url placeholders: /'

echo "== resources (/proc sampling) =="
python3 - "$CSV.json" <<'PY'
import json, sys
s = json.load(open(sys.argv[1]))
for p in s.get("procs", []):
    print(f"  {p['comm']:<12} cpu%_1core={p['cpu_avg_pct_one_core']} "
          f"rss_avg={p['rss_avg_kb']/1024:.1f}M rss_peak={p['rss_peak_kb']/1024:.1f}M")
print(f"  tree         cpu%_1core={s.get('tree_cpu_avg_pct_one_core', 0)} "
      f"rss_avg={s.get('tree_rss_avg_kb', 0)/1024:.1f}M rss_peak={s.get('tree_rss_peak_kb', 0)/1024:.1f}M")
PY

if [ "$FAIL" -eq 0 ]; then echo "RTMPS PREFLIGHT PASS"; else echo "RTMPS PREFLIGHT FAIL"; fi
exit "$FAIL"
