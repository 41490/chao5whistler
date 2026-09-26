# rsghsing build/install (P5, Issue #108).
#
# The systemd units in ops/systemd/ ExecStart `ops/bin/rsghsing`, so the
# release binary has to be installed there before `systemctl --user start`.
# `make install` is the single command the switch checklist tells the CTO to run.
#
#   make            # cargo build --release
#   make install    # + install -m 755 into ../../ops/bin/rsghsing
#   make test       # cargo test
#   make clean      # cargo clean

BIN := rsghsing
ROOT := $(abspath $(dir $(lastword $(MAKEFILE_LIST)))/../..)
OUT := $(ROOT)/ops/bin

.PHONY: all build install test clean

all: build

build:
	cargo build --release

install: build
	mkdir -p $(OUT)
	install -m 755 target/release/$(BIN) $(OUT)/$(BIN)
	@echo "installed $(OUT)/$(BIN)"

test:
	cargo test

clean:
	cargo clean
