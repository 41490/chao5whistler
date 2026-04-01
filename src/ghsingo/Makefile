# ghsingo Makefile

.PHONY: build build-prepare build-live prepare-assets \
        run-prepare run-live run-live-5m \
        install-units enable start stop status logs \
        fmt vet test clean

# === Build ===

build: build-prepare build-live

build-prepare:
	go build -o bin/prepare ./cmd/prepare

build-live:
	go build -o bin/live ./cmd/live

# === Asset preparation ===

# normalize-voices: Convert ocean_v3events/ samples to 44100 Hz mono 16-bit PCM
# with EBU R128 loudness normalization and bandpass (80–8000 Hz).
# Output files named by event type (e.g. PushEvent.wav) in sounds/.
normalize-voices:
	@mkdir -p ../../ops/assets/sounds/normalized
	@for f in ../../ops/assets/sounds/ocean_v3events/*.wav; do \
		name=$$(basename "$$f"); \
		etype=$$(echo "$$name" | cut -d'-' -f1); \
		out="../../ops/assets/sounds/normalized/$${etype}.wav"; \
		echo "normalizing $$name -> $${etype}.wav"; \
		ffmpeg -i "$$f" \
			-ar 44100 -ac 1 -sample_fmt s16 \
			-af "highpass=f=80,lowpass=f=8000,loudnorm=I=-23:LRA=7:TP=-2" \
			-y "$$out"; \
	done

# generate-heartbeat: Generate 72 BPM bass drum loop using FluidR3_GM.sf2.
# Requires: python3, fluidsynth (apt install fluidsynth)
generate-heartbeat:
	python3 ops/scripts/gen_heartbeat_midi.py /tmp/heartbeat_drum.mid
	fluidsynth -ni -g 0.5 -o synth.sample-rate=44100 \
		/usr/share/sounds/sf2/FluidR3_GM.sf2 \
		/tmp/heartbeat_drum.mid \
		-F /tmp/heartbeat_drum_raw.wav -r 44100
	ffmpeg -i /tmp/heartbeat_drum_raw.wav \
		-ar 44100 -ac 1 -sample_fmt s16 \
		-af "lowpass=f=200,loudnorm=I=-30:TP=-6" \
		-y ../../ops/assets/sounds/heartbeat_drum.wav
	rm -f /tmp/heartbeat_drum.mid /tmp/heartbeat_drum_raw.wav

prepare-assets: normalize-voices
	ffmpeg -i ../../ops/assets/cosmos-leveloop-339.mp3 \
		-ar 44100 -ac 2 -y ../../ops/assets/cosmos-leveloop-339.wav

# === Run ===

run-prepare: build-prepare
	./bin/prepare --config ghsingo.toml

run-live: build-live
	./bin/live --config ghsingo.toml

run-live-5m: build-live
	timeout 300 ./bin/live --config ghsingo.toml

# === Systemd ===

install-units:
	mkdir -p ~/.config/systemd/user
	cp ops/systemd/ghsingo-prepare.service ~/.config/systemd/user/
	cp ops/systemd/ghsingo-prepare.timer ~/.config/systemd/user/
	cp ops/systemd/ghsingo-live.service ~/.config/systemd/user/
	systemctl --user daemon-reload

enable:
	systemctl --user enable ghsingo-live ghsingo-prepare.timer

start:
	systemctl --user start ghsingo-live

stop:
	systemctl --user stop ghsingo-live

status:
	systemctl --user status ghsingo-live ghsingo-prepare.timer

logs:
	journalctl --user -u ghsingo-live -f

# === Development ===

fmt:
	go fmt ./...

vet:
	go vet ./...

test:
	go test ./... -v

clean:
	rm -rf bin/ var/ghsingo/records/
