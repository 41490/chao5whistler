#!/usr/bin/env bash
# render-baseline.sh — Freeze the bell-era baseline (#29).
#
# Renders default / mallet / organ profiles with `render-audio`, then runs
# `audio-metrics` against each output and writes one combined Markdown
# report. Re-runnable; outputs go under ops/out/baseline/.
#
# Requirements: go (build), ffmpeg (loudnorm).
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
GHSINGO_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
ROOT_DIR="$(cd "$GHSINGO_DIR/../.." && pwd)"
BIN_DIR="$ROOT_DIR/ops/bin"
OUT_DIR="$ROOT_DIR/ops/out/baseline"
DURATION="${DURATION:-30s}"

mkdir -p "$OUT_DIR"

(cd "$GHSINGO_DIR" && go build -o "$BIN_DIR/render-audio" ./cmd/render-audio)
(cd "$GHSINGO_DIR" && go build -o "$BIN_DIR/audio-metrics" ./cmd/audio-metrics)

declare -a PROFILES=(
	"default:ghsingo.toml"
	"mallet:ghsingo-mallet.toml"
	"organ:ghsingo-organ.toml"
)

REPORT="$OUT_DIR/REPORT.md"
TS="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
COMMIT="$(git -C "$ROOT_DIR" rev-parse --short HEAD 2>/dev/null || echo unknown)"

{
	echo "# bell-era baseline report"
	echo
	echo "- generated: ${TS}"
	echo "- duration: ${DURATION}"
	echo "- commit: ${COMMIT}"
	echo "- legacy: yes (frozen — do not extend, see #28/#38)"
	echo
	echo "| profile | LUFS | LRA | true peak (dBTP) | strikes/s | release/s | ticks |"
	echo "|---|---:|---:|---:|---:|---:|---:|"
} > "$REPORT"

for entry in "${PROFILES[@]}"; do
	name="${entry%%:*}"
	cfg="${entry##*:}"
	audio="$OUT_DIR/${name}.m4a"
	report_json="$OUT_DIR/${name}.report.json"

	echo ">>> rendering $name ($cfg, $DURATION)"
	(cd "$GHSINGO_DIR" && "$BIN_DIR/render-audio" \
		--config "$cfg" --duration "$DURATION" -o "$audio")

	echo ">>> measuring $name"
	"$BIN_DIR/audio-metrics" --audio "$audio" --out "$report_json"

	python3 - "$report_json" "$name" >> "$REPORT" <<'PY'
import json, sys
path, name = sys.argv[1], sys.argv[2]
with open(path) as f:
    r = json.load(f)
loud = r.get("loudness", {})
side = r.get("sidecar", {})
fmt = lambda v: f"{v:.2f}" if isinstance(v, (int, float)) else "-"
print("| {n} | {lufs} | {lra} | {tp} | {sr} | {rr} | {ticks} |".format(
    n=name,
    lufs=fmt(loud.get("integrated_lufs", 0.0)),
    lra=fmt(loud.get("lra", 0.0)),
    tp=fmt(loud.get("true_peak_dbtp", 0.0)),
    sr=fmt(side.get("effective_strike_rate_per_sec", 0.0)),
    rr=fmt(side.get("release_accent_rate_per_sec", 0.0)),
    ticks=side.get("ticks", "-"),
))
PY
done

{
	echo
	echo "Per-profile JSON reports:"
	for entry in "${PROFILES[@]}"; do
		name="${entry%%:*}"
		echo "- \`ops/out/baseline/${name}.report.json\`"
	done
} >> "$REPORT"

echo
echo "Report: $REPORT"
