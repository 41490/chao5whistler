SHELL := /bin/bash

ROOT := $(abspath $(CURDIR)/../..)
MANIFEST := $(ROOT)/src/songh/Cargo.toml
TRACKED_TEMPLATE := $(ROOT)/docs/plans/260321-songh-template.toml
STAGE2_FIXTURE_ROOT := $(ROOT)/ops/out/songh-stage2-archive
STAGE2_FIXTURE_DAY := 2026-03-19
STAGE3_SAMPLE_START := 0
STAGE3_SAMPLE_DURATION := 7200
STAGE3_ROLLOVER_NEXT_DAY := 2026-03-20
STAGE3_ROLLOVER_START := 86390
STAGE3_ROLLOVER_DURATION := 20
STAGE4_SAMPLE_START := 750
STAGE4_SAMPLE_DURATION := 8
STAGE4_RENDER_ROOT := $(ROOT)/ops/out/songh-stage4-video-sample
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
		'Stage 2: archive day-pack downloader + normalize pipeline' \
		'  make stage2-seed-fixture    Write a deterministic local raw fixture day' \
		'  make stage2-prepare-fixture Build normalized/index/manifest from fixture raw' \
		'  make stage2-validate-fixture Validate the generated fixture day-pack' \
		'  make stage2-manual          Unified manual verification command' \
		'  make stage2-all             fmt + test + fixture prepare + validate' \
		'' \
	'Stage 3: second-of-day replay engine' \
	'  make stage3-dry-run         Emit continuous ReplayTick JSON from the prepared fixture day-pack' \
	'  make stage3-rollover-smoke  Verify cross-midnight rollover into the next prepared fixture day-pack' \
	'  make stage3-sample-fixture  Run replay sample on the prepared fixture day-pack' \
	'  make stage3-manual          Unified stage-3 manual verification command' \
	'  make stage3-all             fmt + test + stage2-manual + replay sample + rollover smoke' \
	'' \
	'Stage 4: video frame-plan samples' \
	'  make stage4-sample-vertical Emit vertical motion stage4 frame-plan sample' \
	'  make stage4-sample-fixed    Emit fixed-angle motion stage4 frame-plan sample' \
	'  make stage4-sample-random   Emit random-angle motion stage4 frame-plan sample' \
	'  make stage4-render-fixture  Render a vertical stage4 PNG frame sample artifact' \
	'  make stage4-manual          Unified stage-4 sample verification command' \
	'  make stage4-all             fmt + test + stage2-manual + stage4 samples + PNG render'

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

.PHONY: stage2-seed-fixture
stage2-seed-fixture:
	cd $(ROOT) && $(CARGO) run --manifest-path $(MANIFEST) -- \
		seed-fixture-raw --archive-root $(STAGE2_FIXTURE_ROOT) --day $(STAGE2_FIXTURE_DAY) --force

.PHONY: stage2-prepare-fixture
stage2-prepare-fixture:
	cd $(ROOT) && $(CARGO) run --manifest-path $(MANIFEST) -- \
		prepare-day-pack --config $(TRACKED_TEMPLATE) --archive-root $(STAGE2_FIXTURE_ROOT) \
		--day $(STAGE2_FIXTURE_DAY) --skip-download --force

.PHONY: stage2-validate-fixture
stage2-validate-fixture:
	cd $(ROOT) && $(CARGO) run --manifest-path $(MANIFEST) -- \
		validate-day-pack --config $(TRACKED_TEMPLATE) --archive-root $(STAGE2_FIXTURE_ROOT) \
		--day $(STAGE2_FIXTURE_DAY)

.PHONY: stage2-manual
stage2-manual:
	@$(MAKE) stage2-seed-fixture
	@$(MAKE) stage2-prepare-fixture
	@$(MAKE) stage2-validate-fixture

.PHONY: stage2-all
stage2-all:
	@$(MAKE) stage1-fmt
	@$(MAKE) stage1-test
	@$(MAKE) stage2-seed-fixture
	@$(MAKE) stage2-prepare-fixture
	@$(MAKE) stage2-validate-fixture

.PHONY: stage3-sample-fixture
stage3-sample-fixture:
	cd $(ROOT) && $(CARGO) run --manifest-path $(MANIFEST) -- \
		sample-replay --config $(TRACKED_TEMPLATE) --archive-root $(STAGE2_FIXTURE_ROOT) \
		--day $(STAGE2_FIXTURE_DAY) --start-second $(STAGE3_SAMPLE_START) \
		--duration-secs $(STAGE3_SAMPLE_DURATION) --dump-json

.PHONY: stage3-dry-run
stage3-dry-run:
	cd $(ROOT) && $(CARGO) run --manifest-path $(MANIFEST) -- \
		replay-dry-run --config $(TRACKED_TEMPLATE) --archive-root $(STAGE2_FIXTURE_ROOT) \
		--day $(STAGE2_FIXTURE_DAY) --start-second $(STAGE3_SAMPLE_START) \
		--duration-secs 30 --dump-json

.PHONY: stage3-seed-rollover-fixture
stage3-seed-rollover-fixture:
	cd $(ROOT) && $(CARGO) run --manifest-path $(MANIFEST) -- \
		seed-fixture-raw --archive-root $(STAGE2_FIXTURE_ROOT) --day $(STAGE2_FIXTURE_DAY) --force
	cd $(ROOT) && $(CARGO) run --manifest-path $(MANIFEST) -- \
		seed-fixture-raw --archive-root $(STAGE2_FIXTURE_ROOT) --day $(STAGE3_ROLLOVER_NEXT_DAY) --force

.PHONY: stage3-prepare-rollover-fixture
stage3-prepare-rollover-fixture:
	cd $(ROOT) && $(CARGO) run --manifest-path $(MANIFEST) -- \
		prepare-day-pack --config $(TRACKED_TEMPLATE) --archive-root $(STAGE2_FIXTURE_ROOT) \
		--day $(STAGE2_FIXTURE_DAY) --skip-download --force
	cd $(ROOT) && $(CARGO) run --manifest-path $(MANIFEST) -- \
		prepare-day-pack --config $(TRACKED_TEMPLATE) --archive-root $(STAGE2_FIXTURE_ROOT) \
		--day $(STAGE3_ROLLOVER_NEXT_DAY) --skip-download --force

.PHONY: stage3-rollover-smoke
stage3-rollover-smoke:
	@$(MAKE) stage3-seed-rollover-fixture
	@$(MAKE) stage3-prepare-rollover-fixture
	@tmp="$$(mktemp)"; trap 'rm -f "$$tmp"' EXIT; \
	cd $(ROOT) && $(CARGO) run --manifest-path $(MANIFEST) -- \
		replay-dry-run --config $(TRACKED_TEMPLATE) --archive-root $(STAGE2_FIXTURE_ROOT) \
		--day $(STAGE2_FIXTURE_DAY) --start-second $(STAGE3_ROLLOVER_START) \
		--duration-secs $(STAGE3_ROLLOVER_DURATION) --dump-json > "$$tmp"; \
	rg -q '"source_day": "$(STAGE2_FIXTURE_DAY)"' "$$tmp"; \
	rg -q '"source_day": "$(STAGE3_ROLLOVER_NEXT_DAY)"' "$$tmp"; \
	printf 'songh stage3 rollover smoke passed\n'; \
	printf 'source day rollover: %s -> %s\n' "$(STAGE2_FIXTURE_DAY)" "$(STAGE3_ROLLOVER_NEXT_DAY)"; \
	printf 'start second: %s, duration secs: %s\n' "$(STAGE3_ROLLOVER_START)" "$(STAGE3_ROLLOVER_DURATION)"

.PHONY: stage3-manual
stage3-manual:
	@$(MAKE) stage2-manual
	@$(MAKE) stage3-sample-fixture
	@$(MAKE) stage3-rollover-smoke

.PHONY: stage3-all
stage3-all:
	@$(MAKE) stage1-fmt
	@$(MAKE) stage1-test
	@$(MAKE) stage2-manual
	@$(MAKE) stage3-sample-fixture
	@$(MAKE) stage3-rollover-smoke

.PHONY: stage4-sample-vertical
stage4-sample-vertical:
	cd $(ROOT) && $(CARGO) run --manifest-path $(MANIFEST) -- \
		sample-video --config $(TRACKED_TEMPLATE) --archive-root $(STAGE2_FIXTURE_ROOT) \
		--day $(STAGE2_FIXTURE_DAY) --start-second $(STAGE4_SAMPLE_START) \
		--duration-secs $(STAGE4_SAMPLE_DURATION) --motion-mode vertical --dump-json

.PHONY: stage4-sample-fixed
stage4-sample-fixed:
	cd $(ROOT) && $(CARGO) run --manifest-path $(MANIFEST) -- \
		sample-video --config $(TRACKED_TEMPLATE) --archive-root $(STAGE2_FIXTURE_ROOT) \
		--day $(STAGE2_FIXTURE_DAY) --start-second $(STAGE4_SAMPLE_START) \
		--duration-secs $(STAGE4_SAMPLE_DURATION) --motion-mode fixed_angle --angle-deg 18 --dump-json

.PHONY: stage4-sample-random
stage4-sample-random:
	cd $(ROOT) && $(CARGO) run --manifest-path $(MANIFEST) -- \
		sample-video --config $(TRACKED_TEMPLATE) --archive-root $(STAGE2_FIXTURE_ROOT) \
		--day $(STAGE2_FIXTURE_DAY) --start-second $(STAGE4_SAMPLE_START) \
		--duration-secs $(STAGE4_SAMPLE_DURATION) --motion-mode random_angle --dump-json

.PHONY: stage4-manual
stage4-manual:
	@$(MAKE) stage2-manual
	@$(MAKE) stage4-sample-vertical
	@$(MAKE) stage4-sample-fixed
	@$(MAKE) stage4-sample-random
	@$(MAKE) stage4-render-fixture

.PHONY: stage4-render-fixture
stage4-render-fixture:
	cd $(ROOT) && $(CARGO) run --manifest-path $(MANIFEST) -- \
		render-video-sample --config $(TRACKED_TEMPLATE) --archive-root $(STAGE2_FIXTURE_ROOT) \
		--output-dir $(STAGE4_RENDER_ROOT) --day $(STAGE2_FIXTURE_DAY) \
		--start-second $(STAGE4_SAMPLE_START) --duration-secs $(STAGE4_SAMPLE_DURATION) \
		--motion-mode vertical

.PHONY: stage4-all
stage4-all:
	@$(MAKE) stage1-fmt
	@$(MAKE) stage1-test
	@$(MAKE) stage2-manual
	@$(MAKE) stage4-sample-vertical
	@$(MAKE) stage4-sample-fixed
	@$(MAKE) stage4-sample-random
	@$(MAKE) stage4-render-fixture
