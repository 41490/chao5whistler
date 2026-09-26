#!/usr/bin/env bash
# P5 chaos (Issue #108, acceptance 3) — three scenarios, exit 0 only if all pass.
#
#   ① delete a MIDDLE segment from the P5 copy -> `sched` re-renders it back to
#      the water level [idx(now), idx(now)+4];
#   ② kill the streamer (systemd Restart=always path) -> relaunch resumes at the
#      correct wall-clock segment; kill its ffmpeg child -> internal backoff
#      respawn, still no hole in the output;
#   ③ retention deletes ONLY segments/raw older than retain_days (today and the
#      playing date survive).
#
# SAFETY: every experiment runs on P5's OWN copy under
# /opt/logs/41490/out/rsghsing/p5/. The P3 originals
# /opt/logs/41490/out/rsghsing/p3/segments are READ-ONLY input (P4 + audit still
# use them) and are never written to. Artifacts land in $OUT, never in the repo.
set -uo pipefail

REPO="$(cd "$(dirname "$0")/../../.." && pwd)"
OUT="/opt/logs/41490/out/rsghsing/p5"
BIN="$REPO/src/rsghsing/target/release/rsghsing"
CFG="$REPO/src/rsghsing/rsghsing.toml"
P3SEG="/opt/logs/41490/out/rsghsing/p3/segments"
SEG="$OUT/segments"
RAW="$OUT/raw"
# Wall 2026-03-29T11:00:00Z plays D-1 = 2026-03-28, ready window seg-44..48.
NOW="2026-03-29T11:00:00Z"
METRICS="$OUT/chaos-metrics.jsonl"
RENDERLOG="$OUT/chaos-render.log"

FAIL=0
say() { printf '%s\n' "$*"; }
ok() { say "  PASS $*"; }
bad() { say "  FAIL $*"; FAIL=1; }

[ -x "$BIN" ] || { say "FAIL: no binary at $BIN (run cargo build --release)"; exit 1; }
[ -d "$P3SEG/2026-03-28" ] || { say "FAIL: no P3 segments at $P3SEG"; exit 1; }
# The P3 tree must never be written to; assert it is not our target.
[ "$SEG" != "$P3SEG" ] || { say "FAIL: refusing to touch the P3 tree"; exit 1; }

mkdir -p "$OUT"

# ---------------------------------------------------------------- scenario ①
say "== ① delete a middle segment -> sched re-renders to the water level =="
rm -rf "$SEG" "$RAW" "$METRICS" "$RENDERLOG"
mkdir -p "$RAW" "$SEG"
cp -r "$P3SEG/2026-03-28" "$SEG/2026-03-28"
[ -s "$SEG/2026-03-28/seg-44.ts" ] || { say "FAIL: P5 copy failed"; exit 1; }
# P3 produced seg-44..47; the water level at $NOW wants 44..48.
rm -f "$SEG/2026-03-28/seg-46.ts" "$SEG/2026-03-28/seg-46.manifest.json"
NTS=$(find "$SEG/2026-03-28" -maxdepth 1 -name 'seg-*.ts' | wc -l)
say "  before: $NTS ts files, seg-46 deleted"

START=$(date -u +%s)
"$BIN" --config "$CFG" sched --once --now "$NOW" \
  --segments-dir "$SEG" --archive-dir "$RAW" \
  --metrics-file "$METRICS" >"$RENDERLOG" 2>&1
RC=$?
ELAPSED=$(( $(date -u +%s) - START ))
say "  sched rc=$RC elapsed=${ELAPSED}s"
[ "$RC" -eq 0 ] || bad "sched --once exited $RC (see $RENDERLOG)"

for k in 44 45 46 47 48; do
  f="$SEG/2026-03-28/seg-$k.ts"
  [ -s "$f" ] || { bad "seg-$k.ts missing/empty after re-render"; continue; }
  ok "seg-$k.ts present ($(stat -c %s "$f") bytes)"
done
# The re-rendered segment must be a real TS, not a truncated leftover.
SZ=$(stat -c %s "$SEG/2026-03-28/seg-46.ts" 2>/dev/null || echo 0)
[ "$SZ" -gt 10000000 ] || bad "seg-46.ts too small ($SZ bytes) — not a real render"
python3 - "$METRICS" <<'PY' || FAIL=1
import json, sys
lines = [json.loads(l) for l in open(sys.argv[1]) if l.strip()]
t = lines[-1]
assert t["date"] == "2026-03-28", t["date"]
assert t["ready"] == [44, 45, 46, 47, 48], t["ready"]
assert 46 in t["dispatched"], t["dispatched"]
assert set(t["dispatched"]) == set(t["missing"]), (t["dispatched"], t["missing"])
assert t["rendered_total"] == len(t["rendered"]), t["rendered_total"]
assert t["lead_secs"] == 3600, t["lead_secs"]
assert t["on_disk"] + len(t["dispatched"]) == 5, (t["on_disk"], t["dispatched"])
print(f"  metrics: ready={t['ready']} missing={t['missing']} "
      f"dispatched={t['dispatched']} lead={t['lead_secs']}s on_disk_before={t['on_disk']}")
PY
[ "${FAIL:-0}" -eq 0 ] && ok "water level restored to [44..48]"

# ---------------------------------------------------------------- scenario ②
say "== ② kill streamer -> systemd Restart=always path -> resume at wall-clock segment =="
FLV1="$OUT/chaos-stream-1.flv"
FLV2="$OUT/chaos-stream-2.flv"
LOG="$OUT/chaos-stream.log"
rm -f "$FLV1" "$FLV2" "$LOG"

# Run 1: 20 s of relay, then SIGKILL the streamer (what a crash looks like to
# systemd; Restart=always is what brings it back).
"$BIN" --config "$CFG" stream --now "$NOW" --output local --local-path "$FLV1" \
  --segments-dir "$SEG" --duration 20 >>"$LOG" 2>&1 &
PID1=$!
sleep 22
kill -9 "$PID1" 2>/dev/null
wait "$PID1" 2>/dev/null
say "  run1 killed (pid $PID1), flv1=$(stat -c %s "$FLV1" 2>/dev/null || echo 0) bytes"

# Run 2 = the systemd respawn. It must pick the segment the wall clock is in
# (11:00:22 -> still seg-44), not restart the day from idx 0.
"$BIN" --config "$CFG" stream --now "$NOW" --output local --local-path "$FLV2" \
  --segments-dir "$SEG" --duration 45 >>"$LOG" 2>&1 &
PID2=$!
sleep 12
# Kill the ffmpeg child instead: the pump must back off, respawn and resume.
FFPID=$(pgrep -P "$PID2" | head -1)
say "  killing ffmpeg child pid=$FFPID of streamer $PID2"
[ -n "$FFPID" ] && kill -9 "$FFPID" 2>/dev/null
wait "$PID2"
RC2=$?
say "  run2 rc=$RC2 flv2=$(stat -c %s "$FLV2" 2>/dev/null || echo 0) bytes"
[ "$RC2" -eq 0 ] || bad "respawned streamer exited $RC2 (see $LOG)"

# It must have started (and resumed) on the segment the wall clock points at.
grep -q "segment start idx=44" "$LOG" || bad "no resume on seg-44 after respawn"
grep -q "STREAM_SUMMARY" "$LOG" || bad "no STREAM_SUMMARY after respawn"
RESTARTS=$(grep -o "restarts=[0-9]*" "$LOG" | tail -1 | cut -d= -f2)
say "  ffmpeg respawns=${RESTARTS:-0} segments=$(grep -o 'idx=[0-9]*' "$LOG" | sort -u | tr '\n' ' ')"
[ "${RESTARTS:-0}" -ge 1 ] || bad "ffmpeg kill did not trigger the restart path"
DUR2=$(ffprobe -v error -show_entries format=duration -of csv=p=0 "$FLV2" 2>/dev/null || echo 0)
python3 - "$DUR2" <<'PY' || FAIL=1
import sys
d = float(sys.argv[1])
print(f"  respawned run output duration={d:.2f}s (wall ~45s, minus backoff)")
if d < 20:
    print(f"FAIL: only {d:.2f}s relayed after the crash")
    sys.exit(1)
PY
[ "${FAIL:-0}" -eq 0 ] && ok "streamer resumed from the wall-clock segment"

# ---------------------------------------------------------------- scenario ③
say "== ③ retention deletes only segments/raw older than retain_days =="
# 2026-03-26 (3d) and 2026-03-27 (2d) are expired; 2026-03-28 is the playing
# date, 2026-03-29 is today.
for d in 2026-03-26 2026-03-27; do
  mkdir -p "$SEG/$d"
  head -c 65536 /dev/zero >"$SEG/$d/seg-00.ts"
  head -c 4096 /dev/zero >"$RAW/$d-11.json.gz"
done
"$BIN" --config "$CFG" sched --once --now "$NOW" \
  --segments-dir "$SEG" --archive-dir "$RAW" \
  --metrics-file "$METRICS" >"$OUT/chaos-retain.log" 2>&1
RC3=$?
say "  sched rc=$RC3"
[ "$RC3" -eq 0 ] || bad "retention tick exited $RC3"
for d in 2026-03-26 2026-03-27; do
  [ -e "$SEG/$d" ] && bad "expired segment dir $d survived"
  [ -e "$RAW/$d-11.json.gz" ] && bad "expired raw file $d-11.json.gz survived"
done
[ -d "$SEG/2026-03-28" ] || bad "playing date dir was deleted"
for k in 44 45 46 47 48; do
  [ -s "$SEG/2026-03-28/seg-$k.ts" ] || bad "playing-date seg-$k.ts lost by retention"
done
python3 - "$METRICS" <<'PY' || FAIL=1
import json, sys
t = [json.loads(l) for l in open(sys.argv[1]) if l.strip()][-1]
removed = " ".join(t["removed"])
for want in ("2026-03-26", "2026-03-27"):
    assert want in removed, (want, t["removed"])
assert "2026-03-28" not in removed, t["removed"]
assert t["removed_total"] == len(t["removed"]) == 4, t["removed"]
assert t["rendered_total"] == 0, t["rendered_total"]
print(f"  removed={t['removed']} freed={t['freed_bytes']}B")
PY
[ "${FAIL:-0}" -eq 0 ] && ok "only >retain_days data removed"

say "== chaos summary =="
if [ "$FAIL" -eq 0 ]; then say "CHAOS PASS"; else say "CHAOS FAIL"; fi
exit "$FAIL"
