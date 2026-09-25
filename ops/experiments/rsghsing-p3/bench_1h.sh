#!/usr/bin/env bash
# P3 bench (Issue #106, acceptance 3): render 4 consecutive segments (1h of
# content), time the wall clock, verify ffprobe params + manifest + a 2-segment
# byte-concat smoke (P0-D3), and emit 3 screenshots + a contact sheet to $OUT.
# Exit 0 only if every check passes. Never silently lowers 30fps/2500k.
set -uo pipefail
REPO="$(cd "$(dirname "$0")/../../.." && pwd)"
OUT="/opt/logs/41490/out/rsghsing/p3"
DATE="$(ls "$REPO/var/rsghsing/daypack" 2>/dev/null | head -1)"
SEGDIR="$OUT/segments/$DATE"
BIN="$REPO/src/rsghsing/target/release/rsghsing"
CFG="$REPO/src/rsghsing/rsghsing.toml"
SEGS=(44 45 46 47)
BUDGET=1800
mkdir -p "$SEGDIR"

echo "== build =="
( cd "$REPO/src/rsghsing" && cargo build --release ) || { echo "BUILD FAIL"; exit 1; }

echo "== render 4 segments (k=${SEGS[*]}, date=$DATE; parallel jobs) =="
T0=$(date +%s)
WALLS_FILE="$(mktemp)"
for k in "${SEGS[@]}"; do
  (
    seg="$SEGDIR/seg-$(printf '%02d' "$k").ts"
    s=$(date +%s)
    "$BIN" render segment --index "$k" --config "$CFG" -o "$seg" >/dev/null 2>&1
    rc=$?
    e=$(date +%s)
    echo "$k $((e-s)) $rc" >> "$WALLS_FILE"
  ) &
done
wait
T1=$(date +%s); TOTAL=$((T1-T0))
declare -a WALLS
while read -r k w rc; do
  WALLS+=("$w")
  echo "  seg-$k wall=${w}s rc=$rc"
  [ "$rc" -eq 0 ] || { echo "RENDER FAIL k=$k"; rm -f "$WALLS_FILE"; exit 1; }
done < <(sort -n "$WALLS_FILE")
rm -f "$WALLS_FILE"

FAIL=0
echo "== ffprobe params (dur 900±0.5, 30/1, 1280x720, v≥2400k, a≥120k, mpegts) =="
printf "%-8s %-10s %-8s %-11s %-8s %-8s %-8s %s\n" \
  seg dur_s r_frame WxH v_kbps a_kbps fmt result
for k in "${SEGS[@]}"; do
  seg="$SEGDIR/seg-$(printf '%02d' "$k").ts"
  dur=$(ffprobe -v error -show_entries format=duration -of csv=p=0 "$seg")
  rfr=$(ffprobe -v error -select_streams v:0 -show_entries stream=r_frame_rate -of csv=p=0 "$seg" | head -1)
  wh=$(ffprobe -v error -select_streams v:0 -show_entries stream=width,height -of csv=p=0 "$seg" | head -1 | tr ',' 'x')
  fmt=$(ffprobe -v error -show_entries format=format_name -of default=nw=1:nk=1 "$seg")
  duri=${dur%.*}
  vbytes=$(ffprobe -v error -select_streams v:0 -show_entries packet=size -of csv=p=0 "$seg" | awk '{s+=$1}END{print s+0}')
  abytes=$(ffprobe -v error -select_streams a:0 -show_entries packet=size -of csv=p=0 "$seg" | awk '{s+=$1}END{print s+0}')
  vk=$(( vbytes*8/duri/1000 )); ak=$(( abytes*8/duri/1000 ))
  res=OK
  awk "BEGIN{exit !($dur>=899.5 && $dur<=900.5)}" || { res=BAD_dur; FAIL=1; }
  [ "$rfr" = "30/1" ] || { res=BAD_rfr; FAIL=1; }
  [ "$wh" = "1280x720" ] || { res=BAD_res; FAIL=1; }
  [ "$vk" -ge 2400 ] || { res=BAD_vbr; FAIL=1; }
  [ "$ak" -ge 120 ] || { res=BAD_abr; FAIL=1; }
  echo "$fmt" | grep -q mpegts || { res=BAD_fmt; FAIL=1; }
  printf "seg-%02d  %-10s %-8s %-11s %-8s %-8s %-8s %s\n" "$k" "$dur" "$rfr" "$wh" "$vk" "$ak" "$fmt" "$res"
done

echo "== manifest cross-check =="
for k in "${SEGS[@]}"; do
  seg="$SEGDIR/seg-$(printf '%02d' "$k").ts"
  python3 "$REPO/ops/experiments/rsghsing-p3/manifest_check.py" "$seg" || FAIL=1
done

echo "== P0-D3 concat smoke (byte concat, -c copy; expect NO corrupt/non-monotonic) =="
a="$SEGDIR/seg-44.ts"; b="$SEGDIR/seg-45.ts"
smoke=$(ffmpeg -f mpegts -i "concat:$a|$b" -c copy -f null - 2>&1 | grep -iE "corrupt|monotonic|invalid")
if [ -n "$smoke" ]; then echo "  SMOKE FAIL (44|45):"; echo "$smoke"; FAIL=1; else echo "  concat:44|45 CLEAN"; fi
all="$SEGDIR/seg-44.ts|$SEGDIR/seg-45.ts|$SEGDIR/seg-46.ts|$SEGDIR/seg-47.ts"
smoke4=$(ffmpeg -f mpegts -i "concat:$all" -c copy -f null - 2>&1 | grep -iE "corrupt|monotonic|invalid")
if [ -n "$smoke4" ]; then echo "  SMOKE FAIL (44..47):"; echo "$smoke4"; FAIL=1; else echo "  concat:44..47 CLEAN"; fi

echo "== screenshots (head/mid/tail of seg-44; relative seek, PTS-agnostic) =="
a="$SEGDIR/seg-44.ts"
ffmpeg -y -v error -ss 1   -i "$a" -frames:v 1 "$OUT/shot_head.png" 2>/dev/null
ffmpeg -y -v error -ss 450 -i "$a" -frames:v 1 "$OUT/shot_mid.png"  2>/dev/null
ffmpeg -y -v error -ss 898 -i "$a" -frames:v 1 "$OUT/shot_tail.png" 2>/dev/null
ffmpeg -y -v error -i "$OUT/shot_head.png" -i "$OUT/shot_mid.png" -i "$OUT/shot_tail.png" \
  -filter_complex hstack=inputs=3 "$OUT/contact_sheet.png" 2>/dev/null
for f in shot_head shot_mid shot_tail contact_sheet; do
  if [ -s "$OUT/$f.png" ]; then :; else echo "  MISSING $f.png"; FAIL=1; fi
done
[ "$FAIL" -eq 0 ] && echo "  $OUT/shot_head.png | shot_mid.png | shot_tail.png | contact_sheet.png"

echo "== bench summary =="
echo "per-seg walls (s): ${WALLS[*]}"
echo "TOTAL wall = ${TOTAL}s (budget ${BUDGET}s)"
if [ "$TOTAL" -le "$BUDGET" ]; then echo "WALL PASS"; else echo "WALL FAIL (>${BUDGET}s)"; FAIL=1; fi
if [ "$FAIL" -eq 0 ]; then echo "BENCH PASS"; exit 0; else echo "BENCH FAIL"; exit 1; fi
