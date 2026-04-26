# ghsingo Makefile

ROOT := $(abspath $(CURDIR)/../..)
BIN_DIR := $(ROOT)/ops/bin
VAR_DIR := $(ROOT)/var/ghsingo

.PHONY: build build-prepare build-live build-render-audio build-audio-metrics \
        build-composer-demo build-render-audio-v2 build-movpixer \
        build-movpixer-linux-amd64 build-movpixer-darwin-arm64 prepare-assets \
        prepare-bells prepare-bells-mallet prepare-bells-organ prepare-bells-all \
        normalize-voices \
        run-prepare run-live run-live-5m render-audio-5m run-movpixer \
        composer-timeline composer-timeline-5m \
        render-audio-v2-30s render-audio-v2-5m \
        baseline baseline-30s baseline-5m \
        install-units enable start stop status logs \
        fmt vet test clean

# === Build ===

build: build-prepare build-live build-render-audio build-audio-metrics build-composer-demo build-render-audio-v2 build-movpixer

build-prepare:
	go build -o $(BIN_DIR)/prepare ./cmd/prepare

build-live:
	go build -o $(BIN_DIR)/live ./cmd/live

build-render-audio:
	go build -o $(BIN_DIR)/render-audio ./cmd/render-audio

build-audio-metrics:
	go build -o $(BIN_DIR)/audio-metrics ./cmd/audio-metrics

build-composer-demo:
	go build -o $(BIN_DIR)/composer-demo ./cmd/composer-demo

build-render-audio-v2:
	go build -o $(BIN_DIR)/render-audio-v2 ./cmd/render-audio-v2

build-movpixer:
	go build -o $(BIN_DIR)/movpixer ./cmd/movpixer

build-movpixer-linux-amd64:
	GOOS=linux GOARCH=amd64 go build -o $(BIN_DIR)/movpixer-linux-amd64 ./cmd/movpixer

build-movpixer-darwin-arm64:
	GOOS=darwin GOARCH=arm64 go build -o $(BIN_DIR)/movpixer-darwin-arm64 ./cmd/movpixer

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

# prepare-bells: render the default Tubular Bells bank (GM 14) used by
# ghsingo.toml. Additional comparison banks are GM 12 Marimba and GM 19
# Church Organ.
prepare-bells:
	bash scripts/render-bells.sh --bank-name sampled --program 14

prepare-bells-mallet:
	bash scripts/render-bells.sh --bank-name mallet --program 12

prepare-bells-organ:
	bash scripts/render-bells.sh --bank-name organ --program 19

prepare-bells-all: prepare-bells prepare-bells-mallet prepare-bells-organ

# === Run ===

run-prepare: build-prepare
	$(BIN_DIR)/prepare --config ghsingo.toml

run-live: build-live
	$(BIN_DIR)/live --config ghsingo.toml

run-live-5m: build-live
	timeout 300 $(BIN_DIR)/live --config ghsingo.toml

# render-audio-5m: Render 5 minutes of audio to MP3 for quick verification.
render-audio-5m: build-render-audio
	$(BIN_DIR)/render-audio --config ghsingo.toml --duration 5m -o /tmp/ghsingo-audio-5m.m4a
	@echo "Output: /tmp/ghsingo-audio-5m.m4a  →  ffplay /tmp/ghsingo-audio-5m.m4a"

# baseline: render default/mallet/organ as the frozen bell-era baseline (#29).
# Output: ops/out/baseline/{REPORT.md, <profile>.m4a, <profile>.report.json}.
# Override duration with DURATION=5m (default 30s).
baseline: baseline-30s

baseline-30s: build-render-audio build-audio-metrics
	DURATION=30s bash scripts/render-baseline.sh

baseline-5m: build-render-audio build-audio-metrics
	DURATION=5m bash scripts/render-baseline.sh

# composer-timeline: drive the v1 state-vector composer (#30) against the
# latest daypack and dump the per-second state timeline as JSON.
composer-timeline: build-composer-demo
	mkdir -p ../../ops/out/composer
	$(BIN_DIR)/composer-demo --config ghsingo.toml --duration 30s -o ../../ops/out/composer/timeline-30s.json
	@echo "Output: ops/out/composer/timeline-30s.json"

composer-timeline-5m: build-composer-demo
	mkdir -p ../../ops/out/composer
	$(BIN_DIR)/composer-demo --config ghsingo.toml --duration 5m -o ../../ops/out/composer/timeline-5m.json
	@echo "Output: ops/out/composer/timeline-5m.json"

# render-audio-v2: ambient v2 mixer (#31). Drives the composer (#30) into
# MixerV2 (drone + bed + accent bank), same sidecar contract as render-audio
# so audio-metrics can A/B vs the bell-era baseline (#29).
render-audio-v2-30s: build-render-audio-v2 build-audio-metrics
	mkdir -p ../../ops/out/v2
	$(BIN_DIR)/render-audio-v2 --config ghsingo.toml --duration 30s -o ../../ops/out/v2/v2-30s.m4a
	$(BIN_DIR)/audio-metrics --audio ../../ops/out/v2/v2-30s.m4a --out ../../ops/out/v2/v2-30s.report.json
	@echo "Output: ops/out/v2/v2-30s.m4a + ops/out/v2/v2-30s.report.json"

render-audio-v2-5m: build-render-audio-v2 build-audio-metrics
	mkdir -p ../../ops/out/v2
	$(BIN_DIR)/render-audio-v2 --config ghsingo.toml --duration 5m -o ../../ops/out/v2/v2-5m.m4a
	$(BIN_DIR)/audio-metrics --audio ../../ops/out/v2/v2-5m.m4a --out ../../ops/out/v2/v2-5m.report.json
	@echo "Output: ops/out/v2/v2-5m.m4a + ops/out/v2/v2-5m.report.json"

run-movpixer: build-movpixer
	$(BIN_DIR)/movpixer --config movpixer.toml

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
	rm -rf $(VAR_DIR)/records/ \
		$(BIN_DIR)/audio-metrics \
		$(BIN_DIR)/composer-demo \
		$(BIN_DIR)/live \
		$(BIN_DIR)/movpixer \
		$(BIN_DIR)/movpixer-darwin-arm64 \
		$(BIN_DIR)/movpixer-linux-amd64 \
		$(BIN_DIR)/prepare \
		$(BIN_DIR)/render-audio \
		$(BIN_DIR)/render-audio-v2 \
		/tmp/ghsingo-audio*.m4a
