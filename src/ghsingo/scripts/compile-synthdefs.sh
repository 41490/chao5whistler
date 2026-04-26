#!/usr/bin/env bash
# compile-synthdefs.sh — produce scsynth/synthdefs/*.scsyndef from the
# .scd source files (#35). Requires `sclang` (SuperCollider language)
# on PATH.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
GHSINGO_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
SRC="$GHSINGO_DIR/scsynth/synthdefs/ghsingo_synthdefs.scd"

if ! command -v sclang >/dev/null; then
	echo "error: sclang (SuperCollider) not on PATH." >&2
	echo "       Debian/Ubuntu: apt install supercollider-language" >&2
	exit 1
fi
if [[ ! -f "$SRC" ]]; then
	echo "error: synthdef source not found at $SRC" >&2
	exit 1
fi

cd "$GHSINGO_DIR"
sclang -D "$SRC"
echo "compiled SynthDefs in $GHSINGO_DIR/scsynth/synthdefs/"
