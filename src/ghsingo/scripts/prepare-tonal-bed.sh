#!/usr/bin/env bash
# prepare-tonal-bed.sh — derive an ambient tonal-bed sample from the
# existing cosmos-leveloop source (#32). The legacy BGM path treated this
# sample as a "looped background music"; v2 reclassifies it as one of
# three always-on ambient layers (drone-synth / tonal-bed-sample /
# bed-synth) and pre-processes it accordingly:
#
#   - down 1 octave (asetrate=*0.5 + atempo=2.0 to keep duration)
#   - lowpass 1.2 kHz (sit under the accent layer)
#   - EBU R128 normalize to I=-23 LUFS so the bed never dominates
#
# Output: ops/assets/sounds/ambient/tonal-bed.wav (mono, 44.1 kHz, s16).
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
GHSINGO_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
ROOT_DIR="$(cd "$GHSINGO_DIR/../.." && pwd)"

SRC="${SRC:-$ROOT_DIR/ops/assets/cosmos-leveloop-339.wav}"
OUT_DIR="$ROOT_DIR/ops/assets/sounds/ambient"
OUT="$OUT_DIR/tonal-bed.wav"

if [[ ! -f "$SRC" ]]; then
	echo "error: source $SRC not found." >&2
	echo "       Run 'make prepare-assets' first to materialize cosmos-leveloop-339.wav." >&2
	exit 1
fi

mkdir -p "$OUT_DIR"

ffmpeg -y -hide_banner -i "$SRC" \
	-ar 44100 -ac 1 -sample_fmt s16 \
	-af "asetrate=22050,atempo=2.0,aresample=44100,lowpass=f=1200,loudnorm=I=-23:LRA=7:TP=-2" \
	"$OUT"

echo "tonal bed ready at $OUT"
