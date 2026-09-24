#!/usr/bin/env bash
# Issue #105 P2 — composer timeline golden parity.
#
# Go `cmd/composer-demo` vs `rsghsing composer-timeline`: same daypack bytes,
# same seed, same 5m duration. Exit 0 only when the two JSON timelines are
# byte-identical (diff empty).
#
# Two windows are checked:
#   1. the raw latest daypack — acceptance verbatim ("同 daypack/seed/5m");
#   2. a rotated copy of the same daypack so the 5m window actually carries GH
#      events — that is what exercises the density/brightness EMAs,
#      avg_weight and the mode drift. Both sides read byte-identical input.
#
# Outputs: /opt/logs/41490/out/rsghsing/p2/ (never ops/out, never the repo).
set -euo pipefail

SEED="${SEED:-20260328}"
DUR="${DUR:-5m}"
ROT_OFFSET="${ROT_OFFSET:-39600}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="$(cd "$SCRIPT_DIR/../../.." && pwd)"
OUT="/opt/logs/41490/out/rsghsing/p2"
RS="$REPO/src/rsghsing"
GO_CFG="$OUT/ghsingo-p2-timeline.toml"
RS_CFG="$OUT/rsghsing-p2-timeline.toml"

mkdir -p "$OUT"

GO_BIN="$REPO/ops/bin"
if [[ ! -x "$GO_BIN/composer-demo" || ! -x "$GO_BIN/render-audio-v2" \
   || ! -x "$GO_BIN/audio-metrics" ]]; then
  echo "== make -C src/ghsingo build-composer-demo build-render-audio-v2 \
build-audio-metrics =="
  make -C "$REPO/src/ghsingo" build-composer-demo build-render-audio-v2 \
    build-audio-metrics >"$OUT/go-build.log" 2>&1
fi
if [[ ! -x "$RS/target/release/rsghsing" ]]; then
  echo "== cargo build --release =="
  (cd "$RS" && cargo build --release >"$OUT/cargo-build.log" 2>&1)
fi

# One source of truth for the input path: rsghsing.toml's [archive].daypack_dir,
# with the repo-root-relative prefix expanded so the Go side reads the same file.
DAYPACK_DIR="$(sed -n 's/^daypack_dir *= *"\(.*\)"/\1/p' "$RS/rsghsing.toml")"
DAYPACK_DIR="${DAYPACK_DIR/#..\/..\//$REPO/}"
# Newest <daypack_dir>/<date>/day.bin — the same file both sides consume.
DAYPACK_BIN="$(ls -1 "$DAYPACK_DIR"/*/day.bin 2>/dev/null | sort | tail -1)"
[[ -n "$DAYPACK_BIN" ]] || fail "no daypack under $DAYPACK_DIR"
sed "s|@@DAYPACK_DIR@@|$DAYPACK_DIR|" \
  "$SCRIPT_DIR/configs/ghsingo-p2-timeline.toml" >"$GO_CFG"
cp "$RS/rsghsing.toml" "$RS_CFG"

fail() { echo "TIMELINE_PARITY_FAIL $1"; exit 1; }

check() { # <tag> <go.json> <rust.json>
  local tag="$1" a="$2" b="$3"
  if diff -u "$a" "$b" >"$OUT/timeline-$tag.diff"; then
    echo "PARITY_OK tag=$tag seed=$SEED duration=$DUR \
sha256=$(sha256sum "$a" | cut -c1-16) diff=empty"
  else
    head -40 "$OUT/timeline-$tag.diff" >&2
    fail "$tag (see $OUT/timeline-$tag.diff)"
  fi
}

echo "== go composer-demo (raw daypack) =="
"$GO_BIN/composer-demo" --config "$GO_CFG" --duration "$DUR" \
  --seed "$SEED" -o "$OUT/go-timeline.json" >"$OUT/go-timeline.log" 2>&1
echo "== rsghsing composer-timeline (raw daypack) =="
(cd "$RS" && "$RS/target/release/rsghsing" composer-timeline \
  --config rsghsing.toml --duration "$DUR" --seed "$SEED" \
  -o "$OUT/rust-timeline.json") >"$OUT/rust-timeline.log" 2>&1
check raw "$OUT/go-timeline.json" "$OUT/rust-timeline.json"

# --- rotated daypack so the 5m window carries events -------------------------
ROT="$OUT/rotated"
GO_ROT="$OUT/ghsingo-p2-timeline-rot.toml"
RS_ROT="$OUT/rsghsing-p2-timeline-rot.toml"
python3 - "$DAYPACK_BIN" "$ROT_OFFSET" "$ROT" <<'PY'
import os, sys
src, off, dst_root = sys.argv[1], int(sys.argv[2]), sys.argv[3]
b = open(src, 'rb').read()
nt = int.from_bytes(b[10:14], 'little')
pos, ticks = 16, []
for _ in range(nt):
    n = b[pos]; pos += 1
    start = pos
    for _ in range(n):
        pos += 3 + b[pos + 2]
    ticks.append(bytes([n]) + b[start:pos])
assert pos == len(b), f"trailing bytes: {len(b) - pos}"
date = os.path.basename(os.path.dirname(src))
dst = os.path.join(dst_root, date, 'day.bin')
os.makedirs(os.path.dirname(dst), exist_ok=True)
with open(dst, 'wb') as f:
    f.write(b[:16])
    for i in range(nt):
        f.write(ticks[(i + off) % nt])
print(f"rotated {src} by {off}s -> {dst}")
PY

sed "s|@@DAYPACK_DIR@@|$ROT|" \
  "$SCRIPT_DIR/configs/ghsingo-p2-timeline.toml" >"$GO_ROT"
sed "s|^daypack_dir *=.*|daypack_dir = \"$ROT\"|" "$RS_CFG" >"$RS_ROT"

echo "== go composer-demo (rotated daypack) =="
"$GO_BIN/composer-demo" --config "$GO_ROT" --duration "$DUR" \
  --seed "$SEED" -o "$OUT/go-timeline-rot.json" >"$OUT/go-timeline-rot.log" 2>&1
echo "== rsghsing composer-timeline (rotated daypack) =="
(cd "$RS" && "$RS/target/release/rsghsing" composer-timeline \
  --config "$RS_ROT" --duration "$DUR" --seed "$SEED" \
  -o "$OUT/rust-timeline-rot.json") >"$OUT/rust-timeline-rot.log" 2>&1
check rotated "$OUT/go-timeline-rot.json" "$OUT/rust-timeline-rot.json"

echo "TIMELINE_PARITY_OK seed=$SEED duration=$DUR windows=2"
