#!/usr/bin/env bash
# check-jack-routing.sh — pre-flight for the scsynth + JACK live path
# (#35 + #36). Reports clear pass/fail for each runtime dependency the
# ambient v2 mainline needs in production.
#
# Exits 0 only if every required check passes.
set -uo pipefail

fail=0
pass() { echo "  ok    $1"; }
warn() { echo "  warn  $1"; }
err()  { echo "  fail  $1"; fail=1; }

echo "scsynth runtime check (#35/#36)"

# 1. scsynth binary
if command -v scsynth >/dev/null; then
	pass "scsynth on PATH ($(command -v scsynth))"
else
	err "scsynth not found (apt install supercollider-server)"
fi

# 2. sclang for SynthDef compilation
if command -v sclang >/dev/null; then
	pass "sclang on PATH ($(command -v sclang))"
else
	warn "sclang not found — needed for 'make compile-synthdefs' only"
fi

# 3. JACK or pipewire-jack
if command -v jackd >/dev/null; then
	pass "jackd on PATH ($(command -v jackd))"
elif command -v pw-jack >/dev/null; then
	pass "pipewire-jack present ($(command -v pw-jack))"
else
	err "jackd / pw-jack not found (apt install jackd2 OR pipewire-jack)"
fi

# 4. compiled SynthDefs
if [[ -d "$(dirname "$0")/../scsynth/synthdefs" ]]; then
	count=$(find "$(dirname "$0")/../scsynth/synthdefs" -name '*.scsyndef' | wc -l)
	if [[ "$count" -ge 4 ]]; then
		pass "synthdefs/*.scsyndef present (${count} files)"
	else
		warn "synthdefs not compiled yet — run 'make compile-synthdefs'"
	fi
fi

# 5. JACK port reachable (only if a server is running)
if command -v jack_lsp >/dev/null; then
	if jack_lsp >/dev/null 2>&1; then
		pass "JACK server reachable via jack_lsp"
	else
		warn "JACK server not running — start with 'jackd -d alsa' or rely on pipewire"
	fi
fi

if [[ "$fail" -eq 0 ]]; then
	echo "all required dependencies present."
	exit 0
fi
echo "missing required dependencies — see 'fail' lines above."
exit 1
