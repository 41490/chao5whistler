#!/usr/bin/env bash
# Issue #104 P1 — download idempotency.
#
#   download_idem.sh [date] [hour]
#
# Runs `rsghsing prepare --hours <hour>` twice against the SAME source dir.
# Run 1 must fetch the missing hour pack; run 2 must issue ZERO HTTP requests
# and leave every byte untouched. A third run points base_url at a closed local
# port: it still succeeds, which proves no request is attempted at all.
#
# Outputs: /opt/logs/41490/out/rsghsing/p1/ (never ops/out, never the repo).
set -euo pipefail

DATE="${1:-2026-03-28}"
HOUR="${2:-11}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="$(cd "$SCRIPT_DIR/../../.." && pwd)"
OUT="/opt/logs/41490/out/rsghsing/p1"
RAW="$REPO/var/rsghsing/archive/raw"
BIN="$REPO/src/rsghsing/target/release/rsghsing"
CFG_TEMPLATE="$SCRIPT_DIR/configs/rsghsing-download.toml"
LIVE_URL="https://data.gharchive.org"
DEAD_URL="http://127.0.0.1:9" # discard port, nothing listens there

mkdir -p "$OUT"
if [[ ! -x "$BIN" ]]; then
  (cd "$REPO/src/rsghsing" && cargo build --release >"$OUT/cargo-build.log" 2>&1)
fi

# Probe first: only claim the live-network result when the host is reachable.
if timeout 20 curl -sI --max-time 15 "$LIVE_URL/$DATE-$HOUR.json.gz" >/dev/null 2>&1; then
  MODE="live"
else
  MODE="mock-unavailable"
fi
echo "== network probe: $MODE ($LIVE_URL) =="

# --- run 1: cold cache, must download --------------------------------------
rm -f "$RAW/$DATE-$HOUR.json.gz"
sed "s|@@DATE@@|$DATE|; s|@@BASE_URL@@|$LIVE_URL|; s|@@RAWDIR@@|$RAW|" \
  "$CFG_TEMPLATE" >"$OUT/idem-run1.toml"
rm -rf "$OUT/idem"
"$BIN" prepare --config "$OUT/idem-run1.toml" --date "$DATE" --hours "$HOUR" \
  >"$OUT/idem-run1.log" 2>&1
grep -E "download complete|prepare complete" "$OUT/idem-run1.log"
RAW1=$(sha256sum "$RAW/$DATE-$HOUR.json.gz" | cut -d' ' -f1)
SIZE1=$(stat -c%s "$RAW/$DATE-$HOUR.json.gz")
BIN1=$(sha256sum "$OUT/idem/daypack/$DATE/day.bin" | cut -d' ' -f1)

# --- run 2: warm cache, must be a no-op ------------------------------------
"$BIN" prepare --config "$OUT/idem-run1.toml" --date "$DATE" --hours "$HOUR" \
  >"$OUT/idem-run2.log" 2>&1
grep -E "download complete|prepare complete" "$OUT/idem-run2.log"
RAW2=$(sha256sum "$RAW/$DATE-$HOUR.json.gz" | cut -d' ' -f1)
SIZE2=$(stat -c%s "$RAW/$DATE-$HOUR.json.gz")
BIN2=$(sha256sum "$OUT/idem/daypack/$DATE/day.bin" | cut -d' ' -f1)

# --- run 3: dead base_url, must still succeed (=> zero requests attempted) --
sed "s|@@DATE@@|$DATE|; s|@@BASE_URL@@|$DEAD_URL|; s|@@RAWDIR@@|$RAW|" \
  "$CFG_TEMPLATE" >"$OUT/idem-run3.toml"
if "$BIN" prepare --config "$OUT/idem-run3.toml" --date "$DATE" --hours "$HOUR" \
  >"$OUT/idem-run3.log" 2>&1; then
  echo "== run3 (base_url=$DEAD_URL): succeeded => no HTTP attempted =="
else
  echo "== run3 FAILED (see $OUT/idem-run3.log) =="
  cat "$OUT/idem-run3.log"
  exit 1
fi
BIN3=$(sha256sum "$OUT/idem/daypack/$DATE/day.bin" | cut -d' ' -f1)

echo "== raw: $SIZE1 bytes, sha256 $RAW1 =="
echo "== run2 raw sha256 $RAW2 ($SIZE2 bytes) =="
echo "== day.bin sha256: run1=$BIN1 run2=$BIN2 run3=$BIN3 =="

fail=0
grep -q "downloaded=1" "$OUT/idem-run1.log" || {
  echo "MISS: run1 did not download"
  fail=1
}
grep -q "missing=0 downloaded=0" "$OUT/idem-run2.log" || {
  echo "MISS: run2 was not a no-op"
  fail=1
}
[[ "$RAW1" == "$RAW2" ]] || {
  echo "MISS: raw bytes changed between runs"
  fail=1
}
[[ "$BIN1" == "$BIN2" && "$BIN2" == "$BIN3" ]] || {
  echo "MISS: day.bin not byte-stable"
  fail=1
}
[[ $fail -eq 0 ]] || exit 1

echo "IDEMPOTENT_OK date=$DATE hour=$HOUR mode=$MODE zero_http_on_second_run=true"
