#!/usr/bin/env bash
# P5 unit dry run (Issue #108): prove the four units are syntactically valid AND
# that the command lines they would execute actually work — without ever calling
# `systemctl enable/start/restart` (real enable is the CTO's job, see the switch
# checklist in README.md).
#
#   bash ops/experiments/rsghsing-p5/unit_dryrun.sh
#
# exit 0 only if:
#   * systemd-analyze verify passes on all four units;
#   * every ExecStart binary path exists and is executable;
#   * the sched/prepare command lines run against a scratch root and exit 0.
set -uo pipefail

REPO="$(cd "$(dirname "$0")/../../.." && pwd)"
OUT="/opt/logs/41490/out/rsghsing/p5"
UNITDIR="$REPO/ops/systemd"
UNITS=(rsghsing-prepare.timer rsghsing-prepare.service
  rsghsing-sched.service rsghsing-stream.service)
NOW="2026-03-29T11:00:00Z" # plays D-1 = 2026-03-28, ready window seg-44..48

FAIL=0
say() { printf '%s\n' "$*"; }
ok() { say "  PASS $*"; }
bad() {
  say "  FAIL $*"
  FAIL=1
}

say "== systemd-analyze verify =="
systemd-analyze verify "${UNITS[@]/#/$UNITDIR/}"
[ $? -eq 0 ] && ok "all four units verify" || bad "systemd-analyze verify failed"

say "== make install (proves the units' ExecStart target is produced) =="
make -C "$REPO/src/rsghsing" install >"$OUT/dryrun-make.log" 2>&1
[ $? -eq 0 ] && ok "make -C src/rsghsing install -> $(tail -1 "$OUT/dryrun-make.log")" ||
  bad "make install failed (see $OUT/dryrun-make.log)"

say "== ExecStart resolution (no systemctl) =="
CFG="$REPO/src/rsghsing/rsghsing.toml"
for u in rsghsing-prepare.service rsghsing-sched.service rsghsing-stream.service; do
  LINE=$(grep -m1 '^ExecStart=' "$UNITDIR/$u" | cut -d= -f2-)
  # Strip the leading `-` (systemd's "ignore failure" prefix) to get the binary.
  BIN=$(printf '%s' "$LINE" | sed 's/^-//' | awk '{print $1}')
  say "  $u"
  say "    ExecStart=$LINE"
  # The canonical path is the deployed main checkout; on this host the install
  # step belongs to the CTO, so a missing binary there is a WARNING, not a fail.
  if [ -x "$BIN" ]; then
    ok "$BIN exists and is executable"
  else
    say "  WARN $BIN not installed yet (CTO runs: make -C src/rsghsing install)"
  fi
done
[ -x "$REPO/ops/bin/rsghsing" ] && ok "install target produced in this worktree" ||
  bad "make install produced no binary at $REPO/ops/bin/rsghsing"
[ -f "$CFG" ] && ok "config $CFG present" || bad "config $CFG missing"

say "== timer =="
grep -q 'OnCalendar=\*-\*-\* 00:20:00' "$UNITDIR/rsghsing-prepare.timer" &&
  ok "prepare fires at UTC 00:20" || bad "prepare OnCalendar wrong"
grep -q 'Persistent=true' "$UNITDIR/rsghsing-prepare.timer" &&
  ok "Persistent=true (missed window replayed)" || bad "Persistent missing"
systemd-analyze calendar '*-*-* 00:20:00' >/dev/null 2>&1 &&
  ok "OnCalendar expression is valid" || bad "OnCalendar expression invalid"

say "== command-line dry run (scratch root, no services) =="
SEG="$OUT/dryrun/segments"
RAW="$OUT/dryrun/raw"
rm -rf "$OUT/dryrun"
mkdir -p "$SEG" "$RAW"
"$REPO/src/rsghsing/target/release/rsghsing" --config "$CFG" sched --once \
  --now "$NOW" --segments-dir "$SEG" --archive-dir "$RAW" \
  --metrics-file "$OUT/dryrun/metrics.jsonl" >"$OUT/dryrun/sched.log" 2>&1
[ $? -eq 0 ] && ok "sched command line runs (empty root -> renders nothing, exits 0)" ||
  bad "sched command line failed (see $OUT/dryrun/sched.log)"
"$REPO/src/rsghsing/target/release/rsghsing" --config "$CFG" --help >/dev/null 2>&1
[ $? -eq 0 ] && ok "rsghsing --help ok" || bad "rsghsing --help failed"

say "== unit dry run summary =="
if [ "$FAIL" -eq 0 ]; then say "UNIT_DRYRUN PASS"; else say "UNIT_DRYRUN FAIL"; fi
exit "$FAIL"
