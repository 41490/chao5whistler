#!/usr/bin/env bash
# render-bells.sh — pre-render the 15-pitch pentatonic bell bank for ghsingo.
# Defaults to GM program 14 (Tubular Bells) into bells/sampled, and can emit
# alternative banks such as GM 12 (Marimba) or GM 19 (Church Organ).
#
# Requirements: fluidsynth, ffmpeg, FluidR3_GM.sf2 at /usr/share/sounds/sf2/
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
GHSINGO_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
SOUNDFONT="/usr/share/sounds/sf2/FluidR3_GM.sf2"
PROGRAM=14
BANK_NAME="sampled"

usage() {
	echo "usage: $0 [--program <0-127>] [--bank-name <dir>] [--soundfont <path>]" >&2
	exit 1
}

while [[ $# -gt 0 ]]; do
	case "$1" in
		--program)
			PROGRAM="${2:-}"
			shift 2
			;;
		--bank-name)
			BANK_NAME="${2:-}"
			shift 2
			;;
		--soundfont)
			SOUNDFONT="${2:-}"
			shift 2
			;;
		*)
			usage
			;;
	esac
done

if [[ -z "$BANK_NAME" ]]; then
	echo "error: --bank-name must not be empty" >&2
	exit 1
fi
if [[ ! "$PROGRAM" =~ ^[0-9]+$ ]]; then
	echo "error: --program must be an integer in [0,127], got $PROGRAM" >&2
	exit 1
fi
if (( PROGRAM < 0 || PROGRAM > 127 )); then
	echo "error: --program must be in [0,127], got $PROGRAM" >&2
	exit 1
fi

OUT_DIR="$(cd "$GHSINGO_DIR/../.." && pwd)/ops/assets/sounds/bells/$BANK_NAME"

if ! command -v fluidsynth >/dev/null; then
	echo "error: fluidsynth not installed. Try: apt install fluidsynth" >&2
	exit 1
fi
if ! command -v ffmpeg >/dev/null; then
	echo "error: ffmpeg not installed. Try: apt install ffmpeg" >&2
	exit 1
fi
if [[ ! -f "$SOUNDFONT" ]]; then
	echo "error: soundfont not found at $SOUNDFONT" >&2
	exit 1
fi

mkdir -p "$OUT_DIR"

# Pentatonic pitches → MIDI note numbers.
# C3=48 D3=50 E3=52 G3=55 A3=57 C4=60 D4=62 E4=64 G4=67 A4=69 C5=72 D5=74 E5=76 G5=79 A5=81
declare -a PITCHES=(
	"C3:48" "D3:50" "E3:52" "G3:55" "A3:57"
	"C4:60" "D4:62" "E4:64" "G4:67" "A4:69"
	"C5:72" "D5:74" "E5:76" "G5:79" "A5:81"
)

for entry in "${PITCHES[@]}"; do
	name="${entry%:*}"
	midi="${entry#*:}"
	raw="$(mktemp --suffix=.wav)"
	out="$OUT_DIR/${name}.wav"

	midifile="$(mktemp --suffix=.mid)"
	python3 - "$midifile" "$midi" "$PROGRAM" <<'PY'
import struct, sys
path, note, program = sys.argv[1], int(sys.argv[2]), int(sys.argv[3])
def varlen(n):
    out = bytearray()
    out.append(n & 0x7F)
    while n > 0x7F:
        n >>= 7
        out.insert(0, 0x80 | (n & 0x7F))
    return bytes(out)
hdr = b"MThd" + struct.pack(">IHHH", 6, 0, 1, 480)
events = bytearray()
events += b"\x00\xFF\x51\x03\x07\xA1\x20"  # tempo 500000
events += bytes([0x00, 0xC0, program])      # program change
events += bytes([0x00, 0x90, note, 100])    # note on
events += varlen(2880) + bytes([0x80, note, 0])  # note off after 3s
events += varlen(960) + b"\xFF\x2F\x00"     # end of track after 1s ring-out
trk = b"MTrk" + struct.pack(">I", len(events)) + bytes(events)
with open(path, "wb") as f:
    f.write(hdr + trk)
PY

	fluidsynth -ni -g 0.7 -r 44100 -F "$raw" "$SOUNDFONT" "$midifile"
	ffmpeg -y -i "$raw" -ar 44100 -ac 1 -sample_fmt s16 \
		-af "loudnorm=I=-16:LRA=7:TP=-1.5" "$out" 2>/dev/null
	rm -f "$raw" "$midifile"
	echo "rendered $name.wav"
done

echo ""
echo "Bell bank ready at $OUT_DIR (program=$PROGRAM)"
ls -1 "$OUT_DIR"
