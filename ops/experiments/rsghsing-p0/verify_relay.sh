#!/usr/bin/env bash
# Issue #103 acceptance: S1-TS relay integrity.
#   * relay.flv duration == sum of segment durations (<= 0.2s)
#   * >= 2 segments, both video and audio present
#   * relay.log free of decode/discontinuity anomalies
# Exit 0 only when all three hold.
set -euo pipefail

OUT="/opt/logs/41490/out/rsghsing/p0"
PY=python3

[ -f "$OUT/relay.flv" ] || { echo "FAIL: missing $OUT/relay.flv"; exit 1; }
[ -f "$OUT/relay.log" ] || { echo "FAIL: missing $OUT/relay.log"; exit 1; }
shopt -s nullglob
segs=("$OUT"/segments/*.ts)
[ "${#segs[@]}" -ge 2 ] || { echo "FAIL: need >=2 segments, found ${#segs[@]}"; exit 1; }

$PY - "$OUT" "${segs[@]}" <<'PYEOF'
import re, subprocess, sys, os
out, segs = sys.argv[1], sys.argv[2:]

def dur(p):
    r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                        "-of", "csv=p=0", p], capture_output=True, text=True)
    return float(r.stdout.strip() or 0)

def streams(p):
    r = subprocess.run(["ffprobe", "-v", "error", "-show_entries",
                        "stream=codec_type", "-of", "csv=p=0", p],
                       capture_output=True, text=True)
    return sorted(set(r.stdout.split()))

seg_durs = [dur(p) for p in segs]
relay = dur(os.path.join(out, "relay.flv"))
total = sum(seg_durs)
diff = abs(relay - total)

print(f"segments={len(segs)} sum={total:.3f}s relay={relay:.3f}s diff={diff:.3f}s")
for p, d in zip(segs, seg_durs):
    print(f"  {os.path.basename(p)} {d:.3f}s")

bad = [l for l in open(os.path.join(out, "relay.log")).read().splitlines()
       if re.search(r"error|corrupt|discontinu|non-monoton|invalid|drop", l, re.I)]
print(f"relay.log anomaly lines: {len(bad)}")
for l in bad:
    print("  " + l)

st = streams(os.path.join(out, "relay.flv"))
print(f"relay.flv streams: {st}")

fails = []
if diff > 0.2:
    fails.append(f"duration diff {diff:.3f}s > 0.2s")
if bad:
    fails.append(f"{len(bad)} anomaly line(s) in relay.log")
if sorted(set(st)) != ["audio", "video"]:
    fails.append(f"relay.flv streams {st}")
if fails:
    print("FAIL: " + "; ".join(fails))
    sys.exit(1)
print("PASS: relay duration matches segment sum, log clean, A+V present")
PYEOF
