#!/usr/bin/env bash
# Issue #104 P1 — Go prepare vs rsghsing prepare, same input, same output.
#
#   parity.sh <date> <hour>
#
# Both binaries read the SAME hour pack (var/rsghsing/archive/raw), write their
# own GSIN day-pack, and both are reduced by daypack_stats.py. Exit 0 only when
# the two stats blobs are byte-identical, i.e. the event sets match tick for
# tick and type for type.
#
# Outputs: /opt/logs/41490/out/rsghsing/p1/ (never ops/out, never the repo).
set -euo pipefail

DATE="${1:?usage: parity.sh <date> <hour>}"
HOUR="${2:?usage: parity.sh <date> <hour>}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="$(cd "$SCRIPT_DIR/../../.." && pwd)"
OUT="/opt/logs/41490/out/rsghsing/p1"
RAW="$REPO/var/rsghsing/archive/raw"
SAMPLES="/opt/src/41490/chao5whistler/ops/assets"
RS="$REPO/src/rsghsing"
GO_CFG_TEMPLATE="$SCRIPT_DIR/configs/ghsingo-p1.toml"
PY=python3

mkdir -p "$OUT"

# --- 1. same input for both sides -------------------------------------------
if [[ ! -f "$RAW/$DATE-$HOUR.json.gz" ]]; then
  echo "== seed raw: $DATE-$HOUR.json.gz (from samples) =="
  mkdir -p "$RAW"
  cp "$SAMPLES/$DATE-$HOUR.json.gz" "$RAW/$DATE-$HOUR.json.gz"
fi
echo "== input: $RAW/$DATE-$HOUR.json.gz ($(stat -c%s "$RAW/$DATE-$HOUR.json.gz") bytes) =="

rm -rf "$OUT/go" "$OUT/rust" "$REPO/var/rsghsing/daypack/$DATE"
mkdir -p "$OUT/go/daypack" "$OUT/rust/daypack"

# --- 2. Go prepare (read-only reference) -------------------------------------
sed "s|@@DATE@@|$DATE|; s|@@RAWDIR@@|$RAW|" "$GO_CFG_TEMPLATE" >"$OUT/ghsingo-p1.toml"
echo "== go prepare =="
"$REPO/ops/bin/prepare" --config "$OUT/ghsingo-p1.toml" --hours "$HOUR" \
  >"$OUT/go-prepare.log" 2>&1
GO_DAYPACK="$OUT/go/daypack/$DATE/day.bin"

# --- 3. rsghsing prepare (real rsghsing.toml + rsghsing.local.toml overlay) --
if [[ ! -x "$RS/target/release/rsghsing" ]]; then
  echo "== cargo build --release =="
  (cd "$RS" && cargo build --release >"$OUT/cargo-build.log" 2>&1)
fi
echo "== rsghsing prepare =="
(cd "$RS" && "$RS/target/release/rsghsing" prepare \
  --config rsghsing.toml --date "$DATE" --hours "$HOUR") \
  >"$OUT/rust-prepare.log" 2>&1
RS_DAYPACK="$REPO/var/rsghsing/daypack/$DATE/day.bin"
cp "$RS_DAYPACK" "$OUT/rust/daypack/$DATE-day.bin"
cp "$REPO/var/rsghsing/daypack/$DATE/manifest.json" "$OUT/rust/manifest.json"

# --- 4. reduce both and diff --------------------------------------------------
$PY "$SCRIPT_DIR/daypack_stats.py" "$GO_DAYPACK" "$OUT/go-stats.json"
$PY "$SCRIPT_DIR/daypack_stats.py" "$RS_DAYPACK" "$OUT/rust-stats.json"

echo "== go daypack:   $GO_DAYPACK =="
echo "== rust daypack: $RS_DAYPACK =="
echo "== stats (identical for both sides) =="
$PY -c 'import json,sys;d=json.load(open(sys.argv[1]));d.pop("ticks");print(json.dumps(d,sort_keys=True))' "$OUT/go-stats.json"
echo "== day.bin sha256 =="
sha256sum "$GO_DAYPACK" "$RS_DAYPACK" | sed "s|$OUT/go/daypack/$DATE|go |;s|$REPO/var/rsghsing/daypack/$DATE|rust|"

if diff -u "$OUT/go-stats.json" "$OUT/rust-stats.json" >"$OUT/stats.diff"; then
  echo "PARITY_OK date=$DATE hour=$HOUR ticks_identical=true"
else
  echo "PARITY_FAIL date=$DATE hour=$HOUR (see $OUT/stats.diff)"
  head -40 "$OUT/stats.diff"
  exit 1
fi
