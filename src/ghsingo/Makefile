# ghsingo Makefile

.PHONY: build build-prepare build-live build-render-audio build-movpixer \
        build-movpixer-linux-amd64 build-movpixer-darwin-arm64 prepare-assets \
        normalize-voices \
        run-prepare run-live run-live-5m render-audio-5m run-movpixer \
        install-units enable start stop status logs \
        fmt vet test clean

# === Build ===

build: build-prepare build-live build-render-audio build-movpixer

build-prepare:
	go build -o bin/prepare ./cmd/prepare

build-live:
	go build -o bin/live ./cmd/live

build-render-audio:
	go build -o bin/render-audio ./cmd/render-audio

build-movpixer:
	go build -o bin/movpixer ./cmd/movpixer

build-movpixer-linux-amd64:
	GOOS=linux GOARCH=amd64 go build -o bin/movpixer-linux-amd64 ./cmd/movpixer

build-movpixer-darwin-arm64:
	GOOS=darwin GOARCH=arm64 go build -o bin/movpixer-darwin-arm64 ./cmd/movpixer

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
		filter="highpass=f=80,lowpass=f=8000,loudnorm=I=-23:LRA=7:TP=-2"; \
		case "$$etype" in \
			CreateEvent) \
				filter="$$filter,asetrate=44100*0.982,atempo=1.0183,aresample=44100" ;; \
			IssuesEvent) \
				filter="$$filter,asetrate=44100*1.029302,atempo=0.971532,aresample=44100" ;; \
			PullRequestEvent) \
				filter="$$filter,asetrate=44100*1.0,atempo=1.0,aresample=44100" ;; \
		esac; \
		echo "normalizing $$name -> $${etype}.wav"; \
		ffmpeg -i "$$f" \
			-ar 44100 -ac 1 -sample_fmt s16 \
			-af "$$filter" \
			-y "$$out"; \
	done

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
	./bin/render-audio --config ghsingo.toml --duration 5m -o /tmp/ghsingo-audio-5m.m4a
	@echo "Output: /tmp/ghsingo-audio-5m.m4a  →  ffplay /tmp/ghsingo-audio-5m.m4a"

run-movpixer: build-movpixer
	./bin/movpixer --config movpixer.toml

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
	rm -rf bin/ var/ghsingo/records/ /tmp/ghsingo-audio*.m4a
