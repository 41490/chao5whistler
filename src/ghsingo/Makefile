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

prepare-assets:
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
