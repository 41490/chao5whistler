#!/usr/bin/env bash
# Issue #103 P0 — baseline + ablation measurements, end to end. Re-runnable.
#
#   task1  ghsingo live-v2 baseline (RSS/CPU, audio-only proof)
#   task2  daypack throughput (24 sample .json.gz -> day.bin)
#   task3  2x feasibility decomposition (a encode / b frame / c audio) + verdict
#   task4  S1-TS byte-pump relay end to end
#
# Outputs: /opt/logs/41490/out/rsghsing/p0/ (never ops/out, never the repo).
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="$(cd "$SCRIPT_DIR/../../.." && pwd)"
OUT="/opt/logs/41490/out/rsghsing/p0"
ASSETS="/opt/src/41490/chao5whistler/ops/assets"
CFG="$SCRIPT_DIR/configs/ghsingo-p0.toml"
BIN="$REPO/ops/bin"
PY=python3

LIVE_SECS="${LIVE_SECS:-300}"     # task1: >= 5 min wall clock
RENDER_SECS="${RENDER_SECS:-300}" # task3c + task4 source clip
ENC_SECS="${ENC_SECS:-600}"       # task3a: 10 min of 720p30 content
SEG_SECS="${SEG_SECS:-150}"       # task4: prototype segment length

mkdir -p "$OUT" "$OUT/segments"

hr() {
  printf '=%.0s' {1..72}
  echo
}

# Machine-readable values for summary(); re-created on every run.
rm -f "$OUT/run.env"
emit() { echo "$1=$2" >>"$OUT/run.env"; }

task1() {
  echo "== task1: ghsingo live-v2 Go baseline =="
  make -C "$REPO/src/ghsingo" build >"$OUT/build.log" 2>&1
  echo "build: ok ($(grep -c '^go build' "$OUT/build.log") binaries)"
  "$BIN/live-v2" --config "$CFG" --duration "${LIVE_SECS}s" \
    --metrics "$OUT/live-v2-metrics.ndjson" --metrics-interval 10s \
    -o "$OUT/live-v2-5m.flv" >"$OUT/live-v2.log" 2>&1 &
  local pid=$!
  $PY "$SCRIPT_DIR/sample_proc.py" --pid "$pid" --interval 10 \
    --duration $((LIVE_SECS + 15)) --out "$OUT/live-v2-proc.csv" \
    --summary "$OUT/live-v2-proc.json" --label live-v2 >/dev/null 2>&1
  wait "$pid"
  ffprobe -v error -show_entries stream=codec_type,codec_name,width,height,r_frame_rate \
    -of csv "$OUT/live-v2-5m.flv" >"$OUT/live-v2-ffprobe.txt"
  echo "live-v2 output streams: $(tr '\n' ' ' <"$OUT/live-v2-ffprobe.txt")"
}

task2() {
  echo "== task2: download/daypack throughput =="
  rm -rf "$OUT/daypack"
  local t0 t1 wall raw daypack
  t0=$($PY -c 'import time; print(time.time())')
  "$BIN/prepare" --config "$CFG" >"$OUT/prepare.log" 2>&1
  t1=$($PY -c 'import time; print(time.time())')
  wall=$($PY -c "print(f'{$t1-$t0:.2f}')")
  raw=$($PY -c "import glob,os;print(sum(os.path.getsize(p) for p in glob.glob('$ASSETS/2026-03-28-*.json.gz')))")
  daypack=$(stat -c%s "$OUT/daypack/2026-03-28/day.bin")
  emit PREPARE_WALL_SECS "$wall"
  emit RAW_GZ_BYTES "$raw"
  emit DAYPACK_BYTES "$daypack"
  $PY - "$wall" "$raw" "$daypack" <<'PYEOF'
import json, sys
wall, raw, pack = (float(a) for a in sys.argv[1:4])
m = json.load(open("/opt/logs/41490/out/rsghsing/p0/daypack/2026-03-28/manifest.json"))
print(f"DOWNLOADS sample_hours=24 raw_gib={raw/2**30:.3f} events={m['total_events']} "
      f"kept={m['kept_events']} daypack_mib={pack/2**20:.2f} "
      f"wall={wall:.1f}s gz_parse_MiB_s={raw/2**20/wall:.1f}")
PYEOF
}

task3() {
  echo "== task3: 2x feasibility decomposition =="
  # (a) encoder ceiling: 720p30 -> 2500k mpegts, both presets.
  for p in ultrafast veryfast; do
    local t0 t1 wall
    t0=$($PY -c 'import time; print(time.time())')
    ffmpeg -v info -f lavfi -i testsrc=size=1280x720:rate=30 \
      -c:v libx264 -preset "$p" -b:v 2500k -t "$ENC_SECS" \
      -f mpegts -y /dev/null 2>"$OUT/enc-$p.log"
    t1=$($PY -c 'import time; print(time.time())')
    wall=$($PY -c "print(f'{$t1-$t0:.2f}')")
    emit "ENCODE_${p^^}_WALL_SECS" "$wall"
    emit "ENCODE_${p^^}_FPS" "$(tr '\r' '\n' <"$OUT/enc-$p.log" | grep -oE 'fps=[[:space:]]*[0-9.]+' | tail -1 | grep -oE '[0-9.]+$')"
  done
  # (b) frame generation cost: live-v2 renders no video, so bench the renderer.
  (cd "$REPO/src/ghsingo" && go test -run '^$' -bench 'BenchmarkRenderFrame$' \
    -benchtime 2000x ./internal/video/) >"$OUT/bench-video.log" 2>&1
  local nsop
  nsop=$(grep -E '^BenchmarkRenderFrame-' "$OUT/bench-video.log" | awk '{print $3}')
  emit BENCH_FRAME_NS_OP "$nsop"
  # (c) audio ceiling: render-audio-v2 offline ratio.
  local t0 t1 wall
  t0=$($PY -c 'import time; print(time.time())')
  "$BIN/render-audio-v2" --config "$CFG" --duration "${RENDER_SECS}s" \
    -o "$OUT/v2-5m.m4a" >"$OUT/render-audio.log" 2>&1 &
  local rpid=$!
  $PY "$SCRIPT_DIR/sample_proc.py" --pid "$rpid" --interval 5 \
    --duration $((RENDER_SECS + 120)) --out "$OUT/render-audio-proc.csv" \
    --summary "$OUT/render-audio-proc.json" --label render-audio-v2 >/dev/null 2>&1
  wait "$rpid"
  t1=$($PY -c 'import time; print(time.time())')
  wall=$($PY -c "print(f'{$t1-$t0:.2f}')")
  emit AUDIO_RENDER_WALL_SECS "$wall"
  emit AUDIO_RATIO "$($PY -c "print(f'{$RENDER_SECS/$wall:.2f}')")"
}

task4() {
  echo "== task4: S1-TS byte-pump relay =="
  rm -f "$OUT"/relay.flv "$OUT"/relay.log "$OUT"/segments/*.ts "$OUT"/segments/list.csv
  # Offline render stand-in: solid-colour background (decision baseline #7)
  # + the real v2 audio from task3c, encoded once at the target bitrates.
  ffmpeg -v error -f lavfi -i "color=c=0x002b36:s=1280x720:r=30" -i "$OUT/v2-5m.m4a" \
    -t "$RENDER_SECS" -c:v libx264 -preset ultrafast -b:v 2500k \
    -g $((SEG_SECS * 30)) -keyint_min $((SEG_SECS * 30)) -sc_threshold 0 \
    -pix_fmt yuv420p -c:a aac -b:a 128k -ar 44100 -ac 2 \
    -y "$OUT/s1-src.mp4" 2>"$OUT/s1-src.log"
  # Pre-rendered TS segments: absolute PTS (reset_timestamps 0) + a
  # discontinuity indicator per segment, so byte-concatenating them into one
  # pipe stays monotonic for the persistent relay ffmpeg.
  ffmpeg -v error -i "$OUT/s1-src.mp4" -c copy -f segment \
    -segment_time "$SEG_SECS" -segment_list "$OUT/segments/list.csv" \
    -segment_list_type csv -reset_timestamps 0 \
    -segment_format_options "mpegts_flags=initial_discontinuity+resend_headers" \
    -y "$OUT/segments/seg%d.ts" 2>"$OUT/s1-segment.log"
  local total=0 d f
  for f in "$OUT"/segments/*.ts; do
    d=$(ffprobe -v error -show_entries format=duration -of csv=p=0 "$f")
    total=$($PY -c "print(round($total + $d, 3))")
  done
  echo "SEGMENT_TOTAL_SECS=$total"
  $PY "$SCRIPT_DIR/pump.py" --segments "$OUT"/segments/*.ts --total-duration "$total" \
    --out "$OUT/relay.flv" --log "$OUT/relay.log" \
    --cpu-csv "$OUT/relay-ffmpeg-cpu.csv" | tee "$OUT/pump.log"
}

summary() {
  $PY - "$OUT" "$LIVE_SECS" "$RENDER_SECS" "$ENC_SECS" "$SEG_SECS" <<'PYEOF'
import glob, json, os, re, subprocess, sys
out, live_s, render_s, enc_s, seg_s = sys.argv[1:6]

def j(p):
    try:
        return json.load(open(p))
    except Exception:
        return {}

def dur(p):
    r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                        "-of", "csv=p=0", p], capture_output=True, text=True)
    return float(r.stdout.strip() or 0)

def val(name):
    m = re.search(rf"^{name}=(.*)$", open(os.path.join(out, "run.env")).read(), re.M)
    return m.group(1) if m else ""

live = j(os.path.join(out, "live-v2-proc.json"))
ra = j(os.path.join(out, "render-audio-proc.json"))
relay = j(os.path.join(out, "relay-ffmpeg-cpu.csv.json"))
segs = sorted(glob.glob(os.path.join(out, "segments", "*.ts")))
seg_durs = [dur(p) for p in segs]
relay_dur = dur(os.path.join(out, "relay.flv"))
log = open(os.path.join(out, "relay.log")).read()
bad = [l for l in log.splitlines()
       if re.search(r"error|corrupt|discontinu|non-monoton|invalid|drop", l, re.I)]

print("===== BASELINE (task 1) =====")
print(f"host: {os.cpu_count()} cores, ffmpeg {subprocess.run(['ffmpeg','-version'],capture_output=True,text=True).stdout.splitlines()[0].split()[2]}")
for p in live.get("procs", []):
    print(f"  {p['comm']:<12} rss_peak={p['rss_peak_kb']/1024:.1f}MiB "
          f"rss_avg={p['rss_avg_kb']/1024:.1f}MiB cpu_avg={p['cpu_avg_pct_one_core']:.1f}%")
print(f"  tree        rss_peak={live.get('tree_rss_peak_kb',0)/1024:.1f}MiB "
      f"rss_avg={live.get('tree_rss_avg_kb',0)/1024:.1f}MiB "
      f"cpu_avg={live.get('tree_cpu_avg_pct_one_core',0):.1f}% of one core")
streams = open(os.path.join(out, "live-v2-ffprobe.txt")).read().split()
print(f"  live-v2 output: {dur(os.path.join(out,'live-v2-5m.flv')):.2f}s, streams={streams} "
      f"-> video path {'ACTIVE' if 'video' in streams else 'NOT in effect (audio-only)'}")

print("===== DOWNLOAD (task 2) =====")
m = j(os.path.join(out, "daypack", "2026-03-28", "manifest.json"))
raw, pack = int(val("RAW_GZ_BYTES")), int(val("DAYPACK_BYTES"))
print(f"  24 sample hours, raw gz {raw/2**30:.3f}GiB, events={m.get('total_events')} "
      f"kept={m.get('kept_events')}, daypack {pack/2**20:.2f}MiB, "
      f"wall={val('PREPARE_WALL_SECS')}s, parse {raw/2**20/float(val('PREPARE_WALL_SECS')):.1f}MiB/s")

print("===== THROUGHPUT_VERDICT =====")
a_uf, a_vf = float(val("ENCODE_ULTRAFAST_FPS")), float(val("ENCODE_VERYFAST_FPS"))
ns = int(val("BENCH_FRAME_NS_OP"))
frame_ms = ns / 1e6
b_core_pct = frame_ms / (1000.0 / 30.0) * 100.0
a_ratio = float(val("AUDIO_RATIO"))
print(f"  a) encode 720p30@2500k: ultrafast {a_uf:.0f}fps ({a_uf/30:.1f}x), "
      f"veryfast {a_vf:.0f}fps ({a_vf/30:.1f}x)  [need >=60fps for 2 jobs]")
print(f"  b) frame gen: {ns} ns/frame = {frame_ms:.3f}ms -> {b_core_pct:.1f}% of one core "
      f"per 30fps task  [need <=50%]")
print(f"  c) audio offline render ratio: {a_ratio:.2f}x realtime "
      f"(render-audio-v2 tree cpu {ra.get('tree_cpu_avg_pct_one_core',0):.1f}% of one core)")
ok = a_vf >= 60 and b_core_pct <= 50
print(f"THROUGHPUT_VERDICT: {'PASS' if ok else 'FAIL'} "
      f"(a_veryfast={a_vf:.0f}fps>=60:{a_vf>=60}, b={b_core_pct:.1f}%<=50:{b_core_pct<=50})")

print("===== S1_RELAY (task 4) =====")
for p, d in zip(segs, seg_durs):
    print(f"  {os.path.basename(p)}: {d:.3f}s ({os.path.getsize(p)/2**20:.2f}MiB)")
print(f"  segments={len(segs)} sum={sum(seg_durs):.3f}s relay.flv={relay_dur:.3f}s "
      f"diff={abs(relay_dur-sum(seg_durs)):.3f}s (limit 0.2s)")
print(f"  relay ffmpeg cpu_avg={relay.get('tree_cpu_avg_pct_one_core',0):.1f}% of one core, "
      f"rss_peak={relay.get('tree_rss_peak_kb',0)/1024:.1f}MiB")
print(f"  pump: {open(os.path.join(out,'pump.log')).read().strip()}")
print(f"  relay.log anomalies: {len(bad)}" + (" -> " + " | ".join(bad) if bad else ""))
PYEOF
}

task1
task2
task3
task4
summary
echo "P0_RUN_COMPLETE"
