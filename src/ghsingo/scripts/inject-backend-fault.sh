#!/usr/bin/env bash
# inject-backend-fault.sh — fault-injection harness for #37. Sends a
# SIGTERM to the running scsynth subprocess (when one exists), forcing
# the supervisor to restart it. Then sends SIGUSR1 to the parent
# live-v2 so BackendBox.Restart() rebuilds the inner backend cleanly.
#
# Usage:
#   ./inject-backend-fault.sh                 # find the process by name
#   ./inject-backend-fault.sh <live_v2_pid>   # explicit pid
#
# Verification: after the script returns, soak-analyze should show:
#   - backend_restarts increases by exactly 1
#   - density never strictly hits 0 (silence is fed via BackendBox during
#     the brief restart window, ffmpeg never sees an EOF)
set -euo pipefail

if [[ $# -gt 0 ]]; then
	pid="$1"
else
	pid="$(pgrep -f 'live-v2 --config' | head -1 || true)"
	if [[ -z "$pid" ]]; then
		echo "error: no live-v2 process found; pass pid explicitly" >&2
		exit 1
	fi
fi

echo "live-v2 pid: $pid"

# Try to kill the scsynth subprocess if any.
sc_pid="$(pgrep -P "$pid" -f scsynth | head -1 || true)"
if [[ -n "$sc_pid" ]]; then
	echo "killing scsynth child: $sc_pid"
	kill -TERM "$sc_pid"
fi

# Trigger a Backend Restart on the parent.
echo "sending SIGUSR1 to live-v2 ($pid) -> BackendBox.Restart()"
kill -USR1 "$pid"

echo "fault injected. Watch metrics file for backend_restarts to bump."
