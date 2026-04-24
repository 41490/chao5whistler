#!/usr/bin/env bash
# render-bells.sh — pre-render the 15-pitch pentatonic bell bank for ghsingo
# using fluidsynth + FluidR3_GM.sf2 Tubular Bells (Program 14). Each pitch
# is output as 44100 Hz mono 16-bit PCM.
#
# Requirements: fluidsynth, ffmpeg, FluidR3_GM.sf2 at /usr/share/sounds/sf2/
#
# Output: ../../../ops/assets/sounds/bells/sampled/{note}{octave}.wav
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
GHSINGO_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
OUT_DIR="$(cd "$GHSINGO_DIR/../.." && pwd)/ops/assets/sounds/bells/sampled"
SOUNDFONT="/usr/share/sounds/sf2/FluidR3_GM.sf2"

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
	python3 - "$midifile" "$midi" <<'PY'
import struct, sys
path, note = sys.argv[1], int(sys.argv[2])
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
events += b"\x00\xC0\x0E"                   # program change to 14 (Tubular Bells)
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
echo "Bell bank ready at $OUT_DIR"
ls -1 "$OUT_DIR"
