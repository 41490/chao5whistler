#!/usr/bin/env bash
# Issue #105 P2 — rendered audio parity.
#
# Go `cmd/render-audio-v2` vs `rsghsing render audio`: same daypack bytes, same
# seed, same --start-clock/--duration, same [audio]/[composer]/[mixer]/[assets]
# values. Each side's render is measured by the Go `cmd/audio-metrics` tool, and
# integrated_lufs / true_peak_dbtp are compared with jq + python3.
# Tolerances: |ΔLUFS| <= 1.0 and |Δtrue peak| <= 1.0 dB.
#
# Two windows:
#   1. 14:00 — the acceptance command verbatim. That hour of this daypack is
#      event-free, so it isolates the continuous buses (drone/bed/tonal-bed) and
#      the reverb.
#   2. 11:00 — the only hour with events, so the same check also covers the
#      accent layer driven by real daypack density/brightness.
#
# Outputs: /opt/logs/41490/out/rsghsing/p2/ (never ops/out, never the repo).
set -euo pipefail

SEED="${SEED:-20260328}"
DUR="${DUR:-5m}"
LUFS_TOL="${LUFS_TOL:-1.0}"
TP_TOL="${TP_TOL:-1.0}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="$(cd "$SCRIPT_DIR/../../.." && pwd)"
OUT="/opt/logs/41490/out/rsghsing/p2"
RS="$REPO/src/rsghsing"
GO_BIN="$REPO/ops/bin"
RS_TOML="$RS/rsghsing.toml"
GO_CFG="$OUT/ghsingo-p2-audio.toml"

mkdir -p "$OUT"

if [[ ! -x "$GO_BIN/composer-demo" || ! -x "$GO_BIN/render-audio-v2" ||
  ! -x "$GO_BIN/audio-metrics" ]]; then
  echo "== make -C src/ghsingo build-composer-demo build-render-audio-v2 \
build-audio-metrics =="
  make -C "$REPO/src/ghsingo" build-composer-demo build-render-audio-v2 \
    build-audio-metrics >"$OUT/go-build.log" 2>&1
fi
if [[ ! -x "$RS/target/release/rsghsing" ]]; then
  echo "== cargo build --release =="
  (cd "$RS" && cargo build --release >"$OUT/cargo-build.log" 2>&1)
fi

fail() {
  echo "AUDIO_PARITY_FAIL $1"
  exit 1
}

DAYPACK_DIR="$(sed -n 's/^daypack_dir *= *"\(.*\)"/\1/p' "$RS_TOML")"
DAYPACK_DIR="${DAYPACK_DIR/#..\/..\//$REPO/}"
DAYPACK_BIN="$(ls -1 "$DAYPACK_DIR"/*/day.bin 2>/dev/null | sort | tail -1)"
[[ -n "$DAYPACK_BIN" ]] || fail "no daypack under $DAYPACK_DIR"

sed "s|@@DAYPACK_DIR@@|$DAYPACK_DIR|" \
  "$SCRIPT_DIR/configs/ghsingo-p2-audio.toml" >"$GO_CFG"

# Both sides must read the identical input bytes.
GO_SHA="$(sha256sum "$DAYPACK_BIN" | cut -d' ' -f1)"
BED="$(sed -n 's/^wav_path *= *"\(.*\)"/\1/p' "$RS_TOML")"
BED_SHA="$(sha256sum "$BED" | cut -d' ' -f1)"
echo "INPUT daypack=$DAYPACK_BIN sha256=$GO_SHA"
echo "INPUT tonal_bed=$BED sha256=$BED_SHA"

check_window() { # <clock> <tag>
  local clock="$1" tag="$2"
  local g="$OUT/go-$tag.m4a" r="$OUT/rust-$tag.m4a"
  echo "== go render-audio-v2 $clock/$DUR seed=$SEED =="
  "$GO_BIN/render-audio-v2" --config "$GO_CFG" --start-clock "$clock" \
    --duration "$DUR" --seed "$SEED" -o "$g" >"$OUT/go-$tag.log" 2>&1
  echo "== rsghsing render audio $clock/$DUR seed=$SEED =="
  (cd "$RS" && "$RS/target/release/rsghsing" render audio --config rsghsing.toml \
    --start-clock "$clock" --duration "$DUR" --seed "$SEED" \
    -o "$r") >"$OUT/rust-$tag.log" 2>&1

  # Both sides are measured by the same Go tool.
  "$GO_BIN/audio-metrics" --audio "$g" --out "$OUT/go-$tag.report.json" >/dev/null
  "$GO_BIN/audio-metrics" --audio "$r" --out "$OUT/rust-$tag.report.json" >/dev/null

  read -r gl gt <<<"$(jq -r '.loudness.integrated_lufs, .loudness.true_peak_dbtp' \
    "$OUT/go-$tag.report.json" | tr '\n' ' ')"
  read -r rl rt <<<"$(jq -r '.loudness.integrated_lufs, .loudness.true_peak_dbtp' \
    "$OUT/rust-$tag.report.json" | tr '\n' ' ')"

  python3 - "$tag" "$gl" "$rl" "$gt" "$rt" "$LUFS_TOL" "$TP_TOL" <<'PY' ||
import sys
tag, gl, rl, gt, rt, lt, tt = sys.argv[1:8]
dl, dt = abs(float(gl) - float(rl)), abs(float(gt) - float(rt))
ok = dl <= float(lt) and dt <= float(tt)
print(f"WINDOW {tag}: go lufs={gl} rust lufs={rl} |d|={dl:.4f} "
      f"(tol {lt}) | go tp={gt} rust tp={rt} |d|={dt:.4f} dB (tol {tt})")
print(f"WINDOW {tag}: {'PASS' if ok else 'FAIL'}")
sys.exit(0 if ok else 1)
PY
    fail "$tag"

  # Render bookkeeping must match too: same ticks, accents, transitions.
  diff <(jq -S 'del(.engine, .config)' "$g.metrics.json") \
    <(jq -S 'del(.engine, .config)' "$r.metrics.json") ||
    fail "$tag sidecar"
  echo "SIDECAR_OK tag=$tag (engine/config fields differ by design)"
}

check_window "14:00" accept
check_window "11:00" events
echo "AUDIO_PARITY_OK seed=$SEED duration=$DUR windows=2"
