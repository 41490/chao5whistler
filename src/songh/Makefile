SHELL := /bin/bash

ROOT := $(abspath $(CURDIR)/../..)
MANIFEST := $(ROOT)/src/songh/Cargo.toml
TRACKED_TEMPLATE := $(ROOT)/docs/plans/260321-songh-template.toml
CARGO ?= cargo
MAKEFLAGS += --no-print-directory

.PHONY: help
help:
	@printf '%s\n' \
	'songh stage dispatch' \
	'' \
	'Stage 1: config loader / schema / validate' \
	'  make stage1-fmt             Format the stage-1 crate' \
	'  make stage1-test            Run stage-1 unit tests' \
	'  make stage1-check-template  Validate the tracked template config' \
	'  make stage1-dump-defaults   Print built-in default config as TOML' \
	'  make stage1-manual          Unified manual verification command' \
	'  make stage1-all             fmt + test + tracked-template check' \
	'' \
	'Next stage after review:' \
	'  stage2 archive day-pack downloader + normalize pipeline'

.PHONY: stage1-fmt
stage1-fmt:
	cd $(ROOT) && $(CARGO) fmt --manifest-path $(MANIFEST)

.PHONY: stage1-test
stage1-test:
	cd $(ROOT) && $(CARGO) test --manifest-path $(MANIFEST)

.PHONY: stage1-check-template
stage1-check-template:
	cd $(ROOT) && $(CARGO) run --manifest-path $(MANIFEST) -- \
		check-config --config $(TRACKED_TEMPLATE)

.PHONY: stage1-dump-defaults
stage1-dump-defaults:
	cd $(ROOT) && $(CARGO) run --manifest-path $(MANIFEST) -- \
		print-default-config --format toml

.PHONY: stage1-manual
stage1-manual:
	cd $(ROOT) && $(CARGO) run --manifest-path $(MANIFEST) -- \
		check-config --config $(TRACKED_TEMPLATE) --dump-json

.PHONY: stage1-all
stage1-all:
	@$(MAKE) stage1-fmt
	@$(MAKE) stage1-test
	@$(MAKE) stage1-check-template
