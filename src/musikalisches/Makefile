SHELL := /bin/bash

ROOT := $(abspath $(CURDIR)/../..)
WORK_ID := mozart_dicegame_print_1790s
DEMO_OUT := $(ROOT)/ops/out/m1-demo
STREAM_DEMO_OUT := $(ROOT)/ops/out/stream-demo
STREAM_SF2_OUT := $(ROOT)/ops/out/stream-sf2
GOLDEN_OUT := $(ROOT)/ops/out/golden-check
VIDEO_STUB_OUT := $(ROOT)/ops/out/video-stub
VIDEO_STUB_SF2_OUT := $(ROOT)/ops/out/video-stub-sf2
DEFAULT_SYNTH_PROFILE := $(ROOT)/src/musikalisches/runtime/config/stage5_default_synth_profile.json
DEFAULT_STAGE6_SCENE_PROFILE := $(ROOT)/src/musikalisches/runtime/config/stage6_default_scene_profile.json
DEFAULT_SOUNDFONT := $(ROOT)/ops/assets/soundfonts/default.sf2
PYTHON ?= python
CARGO ?= cargo
MAKEFLAGS += --no-print-directory

.PHONY: help
help:
	@printf '%s\n' \
	'Musikalisches stage dispatch' \
	'' \
	'Core:' \
	'  make stage2-validate        Validate frozen mother score' \
	'  make stage3-validate        Validate frozen rules contract' \
	'  make stage4-freeze          Regenerate stage-4 ingest artifacts' \
	'  make stage4-validate        Validate stage-4 ingest artifacts' \
	'  make stage5-build           Build release bins via helper script' \
	'  make stage5-test            Run cargo test regression set' \
	'  make stage5-golden          Run CLI golden verification' \
	'' \
	'Manual verification:' \
	'  make stage5-demo           Render fallback demo artifacts' \
	'  make stage5-validate       Validate fallback demo artifacts' \
	'  make stage5-stream         Render looped stream demo artifacts' \
	'  make stage5-stream-check   Validate looped stream demo artifacts' \
	'  make stage5-stream-play    Play looped demo WAV with ffplay' \
	'  make stage5-sf2            Render looped SoundFont demo artifacts' \
	'  make stage5-sf2-check      Validate looped SoundFont demo artifacts' \
	'  make stage5-profile-show   Show default synth profile path' \
	'' \
	'Stage 6 preflight:' \
	'  make stage6-video-stub    Derive visual stub artifacts from analyzer output' \
	'  make stage6-video-check   Validate stage6 visual stub artifacts' \
	'  make stage6-video-stub-sf2 Build visual stub from SoundFont artifacts' \
	'  make stage6-video-check-sf2 Validate SoundFont visual stub artifacts' \
	'  make stage6-scene-profile-check Validate stage6 scene profile contract' \
	'  make stage6-scene-profile-show Show default stage6 scene profile path' \
	'  make stage6-plan-show     Show stage6 video stub guide path' \
	'' \
	'Utilities:' \
	'  make stage5-all            fmt + test + golden + stream render + validate' \
	'  make stage6-all            stage5-stream + stage6 stub build + validate' \
	'  make stage6-sf2-all        stage5-sf2 + stage6 sf2 stub build + validate' \
	'  make plans-open            Print manual test guide path' \
	'  make clean-out             Remove generated artifact dirs used by Makefile' \
	'' \
	'Variables:' \
	'  SOUND_FONT=/path/to/file.sf2       Override SoundFont for stage5-sf2' \
	'  SYNTH_PROFILE=/path/to/profile.json Override synth routing profile' \
	'  LOOP_COUNT=4                       Override loop count for stream targets' \
	'  ANALYSIS_WINDOW_MS=40              Override analyzer window size' \
	'  STAGE6_SOURCE_DIR=/path/to/artifacts Override stage6 fallback source dir' \
	'  STAGE6_SF2_SOURCE_DIR=/path/to/artifacts Override stage6 sf2 source dir' \
	'  STAGE6_SCENE_PROFILE=/path/to/profile.json Override stage6 scene profile'

.PHONY: stage2-validate
stage2-validate:
	cd $(ROOT) && $(PYTHON) src/musikalisches/tools/validate_mother_score.py

.PHONY: stage3-validate
stage3-validate:
	cd $(ROOT) && $(PYTHON) src/musikalisches/tools/validate_rules_freeze.py

.PHONY: stage4-freeze
stage4-freeze:
	cd $(ROOT) && $(PYTHON) src/musikalisches/tools/freeze_ingest.py

.PHONY: stage4-validate
stage4-validate:
	cd $(ROOT) && $(PYTHON) src/musikalisches/tools/validate_ingest_freeze.py

.PHONY: stage5-build
stage5-build:
	cd $(ROOT) && bash src/musikalisches/tools/build_release_bins.sh

.PHONY: stage5-test
stage5-test:
	cd $(ROOT) && $(CARGO) test

.PHONY: stage5-golden
stage5-golden:
	cd $(ROOT) && $(CARGO) run -- verify-golden --work $(WORK_ID) --output-dir $(GOLDEN_OUT)

.PHONY: stage5-demo
stage5-demo:
	cd $(ROOT) && $(CARGO) run -- render-audio \
		--work $(WORK_ID) \
		--demo-rolls \
		--output-dir $(DEMO_OUT)

.PHONY: stage5-validate
stage5-validate:
	cd $(ROOT) && $(PYTHON) src/musikalisches/tools/validate_m1_artifacts.py $(DEMO_OUT)

.PHONY: stage5-stream
stage5-stream:
	cd $(ROOT) && $(CARGO) run -- render-audio \
		--work $(WORK_ID) \
		--demo-rolls \
		--loop-count $${LOOP_COUNT:-4} \
		--analysis-window-ms $${ANALYSIS_WINDOW_MS:-40} \
		$(if $(SYNTH_PROFILE),--synth-profile $(SYNTH_PROFILE),) \
		--output-dir $(STREAM_DEMO_OUT)

.PHONY: stage5-stream-check
stage5-stream-check:
	cd $(ROOT) && $(PYTHON) src/musikalisches/tools/validate_m1_artifacts.py $(STREAM_DEMO_OUT)

.PHONY: stage5-stream-play
stage5-stream-play:
	cd $(ROOT) && ffplay -autoexit -nodisp $(STREAM_DEMO_OUT)/offline_audio.wav

.PHONY: stage5-sf2
stage5-sf2:
	@if [[ -n "$(SOUND_FONT)" ]]; then \
		SF2="$(SOUND_FONT)"; \
	elif [[ -n "$$MUSIKALISCHES_SOUNDFONT" ]]; then \
		SF2="$$MUSIKALISCHES_SOUNDFONT"; \
	elif [[ -f "$(DEFAULT_SOUNDFONT)" ]]; then \
		SF2="$(DEFAULT_SOUNDFONT)"; \
	else \
		printf '%s\n' "missing SoundFont: set SOUND_FONT=... or MUSIKALISCHES_SOUNDFONT or place $(DEFAULT_SOUNDFONT)"; \
		exit 1; \
	fi; \
	cd $(ROOT) && $(CARGO) run -- render-audio \
		--work $(WORK_ID) \
		--demo-rolls \
		--loop-count $${LOOP_COUNT:-4} \
		--analysis-window-ms $${ANALYSIS_WINDOW_MS:-40} \
		--soundfont "$$SF2" \
		$(if $(SYNTH_PROFILE),--synth-profile $(SYNTH_PROFILE),) \
		--output-dir $(STREAM_SF2_OUT)

.PHONY: stage5-sf2-check
stage5-sf2-check:
	cd $(ROOT) && $(PYTHON) src/musikalisches/tools/validate_m1_artifacts.py $(STREAM_SF2_OUT)

.PHONY: stage5-profile-show
stage5-profile-show:
	@printf '%s\n' $(DEFAULT_SYNTH_PROFILE)

.PHONY: stage6-video-stub
stage6-video-stub:
	@SOURCE_DIR="$${STAGE6_SOURCE_DIR:-$(STREAM_DEMO_OUT)}"; \
	if [[ ! -f "$$SOURCE_DIR/analysis_window_sequence.json" ]]; then \
		$(MAKE) stage5-stream; \
	fi; \
	cd $(ROOT) && $(PYTHON) src/musikalisches/tools/build_stage6_video_stub.py \
		$(if $(STAGE6_SCENE_PROFILE),--scene-profile $(STAGE6_SCENE_PROFILE),) \
		"$$SOURCE_DIR" \
		$(VIDEO_STUB_OUT)

.PHONY: stage6-video-check
stage6-video-check:
	@if [[ ! -f "$(VIDEO_STUB_OUT)/video_stub_scene.json" ]]; then \
		$(MAKE) stage6-video-stub; \
	fi
	cd $(ROOT) && $(PYTHON) src/musikalisches/tools/validate_stage6_video_stub.py $(VIDEO_STUB_OUT)

.PHONY: stage6-video-stub-sf2
stage6-video-stub-sf2:
	@SOURCE_DIR="$${STAGE6_SF2_SOURCE_DIR:-$(STREAM_SF2_OUT)}"; \
	if [[ ! -f "$$SOURCE_DIR/analysis_window_sequence.json" ]]; then \
		$(MAKE) stage5-sf2; \
	fi; \
	cd $(ROOT) && $(PYTHON) src/musikalisches/tools/build_stage6_video_stub.py \
		$(if $(STAGE6_SCENE_PROFILE),--scene-profile $(STAGE6_SCENE_PROFILE),) \
		"$$SOURCE_DIR" \
		$(VIDEO_STUB_SF2_OUT)

.PHONY: stage6-video-check-sf2
stage6-video-check-sf2:
	@if [[ ! -f "$(VIDEO_STUB_SF2_OUT)/video_stub_scene.json" ]]; then \
		$(MAKE) stage6-video-stub-sf2; \
	fi
	cd $(ROOT) && $(PYTHON) src/musikalisches/tools/validate_stage6_video_stub.py $(VIDEO_STUB_SF2_OUT)

.PHONY: stage6-scene-profile-check
stage6-scene-profile-check:
	cd $(ROOT) && $(PYTHON) src/musikalisches/tools/validate_stage6_scene_profile.py \
		"$${STAGE6_SCENE_PROFILE:-$(DEFAULT_STAGE6_SCENE_PROFILE)}"

.PHONY: stage6-scene-profile-show
stage6-scene-profile-show:
	@printf '%s\n' $(DEFAULT_STAGE6_SCENE_PROFILE)

.PHONY: stage6-plan-show
stage6-plan-show:
	@printf '%s\n' $(ROOT)/docs/plans/260321-stage6-video-stub-guide.md

.PHONY: stage5-all
stage5-all:
	cd $(ROOT) && $(CARGO) fmt --all
	@$(MAKE) stage5-test
	@$(MAKE) stage5-golden
	@$(MAKE) stage5-stream
	@$(MAKE) stage5-stream-check

.PHONY: stage6-all
stage6-all:
	@$(MAKE) stage5-stream
	@$(MAKE) stage6-video-stub
	@$(MAKE) stage6-video-check

.PHONY: stage6-sf2-all
stage6-sf2-all:
	@$(MAKE) stage5-sf2
	@$(MAKE) stage6-video-stub-sf2
	@$(MAKE) stage6-video-check-sf2

.PHONY: plans-open
plans-open:
	@printf '%s\n' $(ROOT)/docs/plans/260321-stage5-build-and-manual-test-guide.md

.PHONY: clean-out
clean-out:
	rm -rf $(DEMO_OUT) $(STREAM_DEMO_OUT) $(STREAM_SF2_OUT) $(GOLDEN_OUT) $(VIDEO_STUB_OUT) $(VIDEO_STUB_SF2_OUT)
