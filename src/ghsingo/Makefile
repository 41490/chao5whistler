# ghsingo Makefile

.PHONY: build build-prepare build-live build-render-audio prepare-assets \
        normalize-voices generate-heartbeat \
        run-prepare run-live run-live-5m render-audio-5m \
        install-units enable start stop status logs \
        fmt vet test clean

# === Build ===

build: build-prepare build-live build-render-audio

build-prepare:
	go build -o bin/prepare ./cmd/prepare

build-live:
	go build -o bin/live ./cmd/live

build-render-audio:
	go build -o bin/render-audio ./cmd/render-audio

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

# generate-heartbeat: Synthesize a bass drum sample using ffmpeg aevalsrc.
# No external dependencies required (uses ffmpeg only).
# For a GM soundfont version (higher quality), see:
#   apt install fluidsynth  +  use GM note 36 on channel 10
generate-heartbeat:
	@mkdir -p ../../ops/assets/sounds/normalized
	ffmpeg -f lavfi \
		-i "aevalsrc=sin(2*PI*80*t)*exp(-t*25)*0.8+sin(2*PI*40*t)*exp(-t*40)*0.3:s=44100:d=0.35" \
		-ar 44100 -ac 1 -sample_fmt s16 \
		-af "loudnorm=I=-18:TP=-3" \
		-y ../../ops/assets/sounds/normalized/heartbeat_drum.wav

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

# render-audio-5m: Render 5 minutes of audio to MP3 for quick verification.
render-audio-5m: build-render-audio
	./bin/render-audio --config ghsingo.toml --duration 5m -o /tmp/ghsingo-audio-5m.mp3
	@echo "Output: /tmp/ghsingo-audio-5m.mp3  →  ffplay /tmp/ghsingo-audio-5m.mp3"

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
	rm -rf bin/ var/ghsingo/records/ /tmp/ghsingo-audio*.mp3
