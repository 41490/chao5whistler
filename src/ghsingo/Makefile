# ghsingo Makefile — bell-era removed in #38; v2 ambient is the only path.

ROOT := $(abspath $(CURDIR)/../..)
BIN_DIR := $(ROOT)/ops/bin
VAR_DIR := $(ROOT)/var/ghsingo

.PHONY: build build-prepare build-live-v2 \
        build-audio-metrics build-composer-demo build-render-audio-v2 \
        build-soak-analyze build-movpixer \
        build-movpixer-linux-amd64 build-movpixer-darwin-arm64 prepare-assets \
        prepare-bells prepare-tonal-bed compile-synthdefs check-jack-routing \
        normalize-voices \
        run-prepare run-live-v2-5m run-movpixer \
        composer-timeline composer-timeline-5m \
        render-audio-v2-30s render-audio-v2-5m render-audio-v2-scsynth-30s \
        soak-90s soak-24h soak-7d \
        install-units enable start stop status logs \
        fmt vet test clean

# === Build ===

build: build-prepare build-live-v2 build-audio-metrics build-composer-demo \
       build-render-audio-v2 build-soak-analyze build-movpixer

build-prepare:
	go build -o $(BIN_DIR)/prepare ./cmd/prepare

build-live-v2:
	go build -o $(BIN_DIR)/live-v2 ./cmd/live-v2

build-audio-metrics:
	go build -o $(BIN_DIR)/audio-metrics ./cmd/audio-metrics

build-composer-demo:
	go build -o $(BIN_DIR)/composer-demo ./cmd/composer-demo

build-render-audio-v2:
	go build -o $(BIN_DIR)/render-audio-v2 ./cmd/render-audio-v2

build-soak-analyze:
	go build -o $(BIN_DIR)/soak-analyze ./cmd/soak-analyze

build-movpixer:
	go build -o $(BIN_DIR)/movpixer ./cmd/movpixer

build-movpixer-linux-amd64:
	GOOS=linux GOARCH=amd64 go build -o $(BIN_DIR)/movpixer-linux-amd64 ./cmd/movpixer

build-movpixer-darwin-arm64:
	GOOS=darwin GOARCH=arm64 go build -o $(BIN_DIR)/movpixer-darwin-arm64 ./cmd/movpixer

# === Asset preparation ===

# normalize-voices: Convert ocean_v3events/ samples to 44100 Hz mono 16-bit PCM
# with EBU R128 loudness normalization and bandpass (80–8000 Hz).
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

# prepare-bells: render the GM 14 Tubular Bells bank used as the v2
# accent voice library (`[assets.accents].bank_dir`). The mallet/organ
# variants from bell-era are gone (#38).
prepare-bells:
	bash scripts/render-bells.sh --bank-name sampled --program 14

# prepare-tonal-bed: derive ops/assets/sounds/ambient/tonal-bed.wav from
# the cosmos-leveloop source for use as v2's L0.5 sample-based bed (#32).
prepare-tonal-bed:
	bash scripts/prepare-tonal-bed.sh

# compile-synthdefs: compile scsynth/synthdefs/*.scd -> .scsyndef (#35).
# Requires `sclang` on PATH (apt install supercollider-language).
compile-synthdefs:
	bash scripts/compile-synthdefs.sh

# check-jack-routing: report which scsynth/JACK runtime dependencies
# are present (#36). Exits non-zero if any required dep is missing.
check-jack-routing:
	bash scripts/check-jack-routing.sh

# === Run ===

run-prepare: build-prepare
	$(BIN_DIR)/prepare --config ghsingo.toml

# run-live-v2-5m: realtime ambient backend (#34) for 5 minutes,
# audio-only, output to /tmp/live-v2-5m.flv. Verifies the backend
# abstraction works end-to-end at wall-clock pace.
run-live-v2-5m: build-live-v2
	$(BIN_DIR)/live-v2 --config ghsingo.toml --duration 5m -o /tmp/live-v2-5m.flv

# composer-timeline: drive the state-vector composer (#30) against the
# latest daypack and dump the per-second state timeline as JSON.
composer-timeline: build-composer-demo
	mkdir -p ../../ops/out/composer
	$(BIN_DIR)/composer-demo --config ghsingo.toml --duration 30s -o ../../ops/out/composer/timeline-30s.json
	@echo "Output: ops/out/composer/timeline-30s.json"

composer-timeline-5m: build-composer-demo
	mkdir -p ../../ops/out/composer
	$(BIN_DIR)/composer-demo --config ghsingo.toml --duration 5m -o ../../ops/out/composer/timeline-5m.json
	@echo "Output: ops/out/composer/timeline-5m.json"

# render-audio-v2: ambient render to m4a + audio-metrics report.
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

# render-audio-v2-scsynth-30s: drive the scsynth backend (#35). Requires
# scsynth on PATH and pre-compiled SynthDefs (run `make compile-synthdefs`
# once). Without scsynth, the render fails with a clear "not on PATH"
# error, intended.
render-audio-v2-scsynth-30s: build-render-audio-v2 build-audio-metrics
	mkdir -p ../../ops/out/v2
	$(BIN_DIR)/render-audio-v2 --config ghsingo.toml --backend scsynth \
		--synthdef-dir scsynth/synthdefs \
		--duration 30s -o ../../ops/out/v2/v2-scsynth-30s.m4a
	$(BIN_DIR)/audio-metrics --audio ../../ops/out/v2/v2-scsynth-30s.m4a --out ../../ops/out/v2/v2-scsynth-30s.report.json
	@echo "Output: ops/out/v2/v2-scsynth-30s.m4a + ops/out/v2/v2-scsynth-30s.report.json"

# soak-* targets run live-v2 with metrics + snapshot enabled and then
# evaluate via soak-analyze (#37). soak-90s is the CI smoke variant —
# 90 seconds is enough to cross at least one Section transition with
# the default 16-tick phrase length.
soak-90s: build-live-v2 build-soak-analyze
	mkdir -p ../../var/ghsingo/soak
	$(BIN_DIR)/live-v2 --config ghsingo.toml --duration 90s \
		--metrics ../../var/ghsingo/soak/metrics-90s.ndjson \
		--metrics-interval 5s \
		--snapshot ../../var/ghsingo/soak/snapshot-90s.json \
		-o ../../var/ghsingo/soak/90s.flv 2>&1 | tail -3
	$(BIN_DIR)/soak-analyze --in ../../var/ghsingo/soak/metrics-90s.ndjson \
		--min-uptime 80s --max-zero-density-secs 30

soak-24h: build-live-v2 build-soak-analyze
	mkdir -p ../../var/ghsingo/soak
	$(BIN_DIR)/live-v2 --config ghsingo.toml --duration 24h \
		--metrics ../../var/ghsingo/soak/metrics-24h.ndjson \
		--metrics-interval 30s \
		--snapshot ../../var/ghsingo/soak/snapshot-24h.json \
		-o ../../var/ghsingo/soak/24h.flv

soak-7d: build-live-v2 build-soak-analyze
	mkdir -p ../../var/ghsingo/soak
	$(BIN_DIR)/live-v2 --config ghsingo.toml --duration 168h \
		--metrics ../../var/ghsingo/soak/metrics-7d.ndjson \
		--metrics-interval 30s \
		--snapshot ../../var/ghsingo/soak/snapshot-7d.json \
		-o ../../var/ghsingo/soak/7d.flv

run-movpixer: build-movpixer
	$(BIN_DIR)/movpixer --config movpixer.toml

# === Systemd ===

install-units:
	mkdir -p ~/.config/systemd/user
	cp ops/systemd/ghsingo-prepare.service ~/.config/systemd/user/
	cp ops/systemd/ghsingo-prepare.timer ~/.config/systemd/user/
	cp ops/systemd/ghsingo-live-v2.service ~/.config/systemd/user/
	systemctl --user daemon-reload
	@echo "Installed v2 units. Send SIGUSR1 to recover the backend without dropping the stream:"
	@echo "  systemctl --user kill -s USR1 ghsingo-live-v2.service"

enable:
	systemctl --user enable ghsingo-live-v2 ghsingo-prepare.timer

start:
	systemctl --user start ghsingo-live-v2

stop:
	systemctl --user stop ghsingo-live-v2

status:
	systemctl --user status ghsingo-live-v2 ghsingo-prepare.timer

logs:
	journalctl --user -u ghsingo-live-v2 -f

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
		$(BIN_DIR)/live-v2 \
		$(BIN_DIR)/movpixer \
		$(BIN_DIR)/movpixer-darwin-arm64 \
		$(BIN_DIR)/movpixer-linux-amd64 \
		$(BIN_DIR)/prepare \
		$(BIN_DIR)/render-audio-v2 \
		$(BIN_DIR)/soak-analyze \
		/tmp/ghsingo-audio*.m4a
