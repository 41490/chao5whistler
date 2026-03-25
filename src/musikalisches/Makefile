SHELL := /bin/bash

ROOT := $(abspath $(CURDIR)/../..)
WORK_ID := mozart_dicegame_print_1790s
DEMO_OUT := $(ROOT)/ops/out/m1-demo
STREAM_DEMO_OUT := $(ROOT)/ops/out/stream-demo
STREAM_SF2_OUT := $(ROOT)/ops/out/stream-sf2
GOLDEN_OUT := $(ROOT)/ops/out/golden-check
VIDEO_STUB_OUT := $(ROOT)/ops/out/video-stub
VIDEO_STUB_SF2_OUT := $(ROOT)/ops/out/video-stub-sf2
VIDEO_RENDER_OUT := $(ROOT)/ops/out/video-render
VIDEO_RENDER_SF2_OUT := $(ROOT)/ops/out/video-render-sf2
STREAM_BRIDGE_OUT := $(ROOT)/ops/out/stream-bridge
FFMPEG_TOOLCHAIN_OUT := $(ROOT)/ops/out/ffmpeg-rtmps-check
STAGE7_PREFLIGHT_REGRESSION_OUT := $(ROOT)/ops/out/stage7-preflight-regressions
DEFAULT_SYNTH_PROFILE := $(ROOT)/src/musikalisches/runtime/config/stage5_default_synth_profile.json
DEFAULT_STAGE6_SCENE_PROFILE := $(ROOT)/src/musikalisches/runtime/config/stage6_default_scene_profile.json
DEFAULT_STAGE6_TEXT_CONFIG := $(ROOT)/src/musikalisches/runtime/config/stage6_default_text_overrides.toml
DEFAULT_STAGE7_BRIDGE_PROFILE := $(ROOT)/src/musikalisches/runtime/config/stage7_default_bridge_profile.json
DEFAULT_SOUNDFONT := $(ROOT)/ops/assets/soundfonts/default.sf2
DEFAULT_SYSTEM_SOUNDFONTS := /usr/share/sounds/sf2/FluidR3_GM.sf2 /usr/share/sounds/sf2/TimGM6mb.sf2 /usr/share/sounds/sf2/FluidR3Mono_GM.sf2 /usr/local/share/sounds/sf2/default.sf2
DEFAULT_STAGE5_LEDGER := $(ROOT)/ops/out/state/musikalisches/stage5_stream_combination_ledger.json
DEFAULT_STAGE5_SF2_LEDGER := $(ROOT)/ops/out/state/musikalisches/stage5_stream_sf2_combination_ledger.json
REPO_FFMPEG_BIN := $(ROOT)/ops/bin/ffmpeg
REPO_FFPROBE_BIN := $(ROOT)/ops/bin/ffprobe
FFMPEG_BIN ?= $(if $(wildcard $(REPO_FFMPEG_BIN)),$(REPO_FFMPEG_BIN),ffmpeg)
FFPROBE_BIN ?= $(if $(wildcard $(REPO_FFPROBE_BIN)),$(REPO_FFPROBE_BIN),ffprobe)
PYTHON ?= python3
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
	'  make stage5-stream         Render looped stream artifacts from a unique persisted combination ledger' \
	'  make stage5-stream-check   Validate looped stream artifacts and unique selection metadata' \
	'  make stage5-stream-play    Play looped demo WAV with ffplay' \
	'  make stage5-sf2            Render looped SoundFont artifacts from a unique persisted combination ledger' \
	'  make stage5-sf2-check      Validate looped SoundFont artifacts and unique selection metadata' \
	'  make stage5-profile-show   Show default synth profile path' \
	'' \
	'Stage 6 preflight:' \
	'  make stage6-video-stub    Derive visual stub artifacts from analyzer output' \
	'  make stage6-video-check   Validate stage6 visual stub artifacts' \
	'  make stage6-video-render  Render offline frame contract and mp4 from stage6 stub' \
	'  make stage6-video-render-check Validate stage6 video render artifacts' \
	'  make stage6-video-stub-sf2 Build visual stub from SoundFont artifacts' \
	'  make stage6-video-check-sf2 Validate SoundFont visual stub artifacts' \
	'  make stage6-video-render-sf2 Render SoundFont-derived offline frame contract and mp4' \
	'  make stage6-video-render-check-sf2 Validate SoundFont video render artifacts' \
	'  make stage6-scene-profile-check Validate stage6 scene profile contract' \
	'  make stage6-scene-profile-check-all Validate all repo stage6 scene profiles' \
	'  make stage6-scene-profile-show Show default stage6 scene profile path' \
	'  make stage6-text-config-show Show default stage6 text override TOML path' \
	'  make stage6-plan-show     Show stage6 video stub guide path' \
	'  make stage6-render-plan-show Show stage6 render-video guide path' \
	'' \
	'Stage 7 bridge freeze:' \
	'  make stage7-bridge        Freeze stage7 FFmpeg bridge contract and local FLV smoke' \
	'  make stage7-bridge-check  Validate stage7 bridge artifacts' \
	'  make stage7-preflight-regression-check Validate automated stage7 preflight fail observability' \
	'  make stage7-soak-check    Validate pre-stage8 soak readiness contract' \
	'  make stage8-readiness-check Validate stage8 real-soak ops readiness gate' \
	'  make stage7-ffmpeg-build  Build repo-managed ffmpeg/ffprobe with RTMPS output support' \
	'  make stage7-ffmpeg-check  Validate repo-managed ffmpeg/ffprobe capability' \
	'  make stage7-bridge-profile-show Show default stage7 bridge profile path' \
	'  make stage7-plan-show     Show stage7 bridge guide path' \
	'  make stage8-plan-show     Show stage8 real-soak ops guide path' \
	'' \
	'Utilities:' \
	'  make stage5-all            fmt + test + golden + stream render + validate' \
	'  make stage6-all            stream + scene profile checks + stub + video render + validate' \
	'  make stage6-sf2-all        sf2 stream + stub + video render + validate' \
	'  make stage7-all            stream + video render + bridge smoke + validate + soak gate' \
	'  make plans-open            Print manual test guide path' \
	'  make clean-out             Remove generated artifact dirs used by Makefile' \
	'' \
	'Variables:' \
	'  SOUND_FONT=/path/to/file.sf2       Override SoundFont for stage5-sf2' \
	'  SYNTH_PROFILE=/path/to/profile.json Override synth routing profile' \
	'  LOOP_COUNT=4                       Override loop count for stream targets' \
	'  ANALYSIS_WINDOW_MS=40              Override analyzer window size' \
	'  STAGE5_LEDGER_PATH=/path/to/ledger.json Override unique-combination ledger for stage5-stream' \
	'  STAGE5_SF2_LEDGER_PATH=/path/to/ledger.json Override unique-combination ledger for stage5-sf2' \
	'  STAGE6_SOURCE_DIR=/path/to/artifacts Override stage6 fallback source dir' \
	'  STAGE6_SF2_SOURCE_DIR=/path/to/artifacts Override stage6 sf2 source dir' \
	'  STAGE6_SCENE_PROFILE=/path/to/profile.json Override stage6 scene profile' \
	'  STAGE6_TEXT_CONFIG=/path/to/overrides.toml Override stage6 title text TOML source' \
	'  STAGE7_AUDIO_SOURCE_DIR=/path/to/artifacts Override stage7 audio source dir' \
	'  STAGE7_VIDEO_SOURCE_DIR=/path/to/artifacts Override stage7 video source dir' \
	'  STAGE7_BRIDGE_PROFILE=/path/to/profile.json Override stage7 bridge profile' \
	'  FFMPEG_BIN=/path/to/ffmpeg             Override ffmpeg binary used by stage6/stage7' \
	'  FFPROBE_BIN=/path/to/ffprobe           Override ffprobe binary used by stage7 checks'

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
	cd $(ROOT) && $(PYTHON) src/musikalisches/tools/build_stage5_unique_stream.py \
		--cargo-bin "$(CARGO)" \
		--work-id $(WORK_ID) \
		--ledger-path "$${STAGE5_LEDGER_PATH:-$(DEFAULT_STAGE5_LEDGER)}" \
		--loop-count $${LOOP_COUNT:-4} \
		--analysis-window-ms $${ANALYSIS_WINDOW_MS:-40} \
		$(if $(SYNTH_PROFILE),--synth-profile $(SYNTH_PROFILE),) \
		--output-dir $(STREAM_DEMO_OUT)

.PHONY: stage5-stream-check
stage5-stream-check:
	cd $(ROOT) && $(PYTHON) src/musikalisches/tools/validate_m1_artifacts.py --require-selection $(STREAM_DEMO_OUT)

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
		for candidate in $(DEFAULT_SYSTEM_SOUNDFONTS); do \
			if [[ -f "$$candidate" ]]; then \
				SF2="$$candidate"; \
				break; \
			fi; \
		done; \
		if [[ -z "$$SF2" ]]; then \
			printf '%s\n' "missing SoundFont: set SOUND_FONT=... or MUSIKALISCHES_SOUNDFONT or place $(DEFAULT_SOUNDFONT) or install one of: $(DEFAULT_SYSTEM_SOUNDFONTS)"; \
			exit 1; \
		fi; \
	fi; \
	cd $(ROOT) && $(PYTHON) src/musikalisches/tools/build_stage5_unique_stream.py \
		--cargo-bin "$(CARGO)" \
		--work-id $(WORK_ID) \
		--ledger-path "$${STAGE5_SF2_LEDGER_PATH:-$(DEFAULT_STAGE5_SF2_LEDGER)}" \
		--loop-count $${LOOP_COUNT:-4} \
		--analysis-window-ms $${ANALYSIS_WINDOW_MS:-40} \
		--soundfont "$$SF2" \
		$(if $(SYNTH_PROFILE),--synth-profile $(SYNTH_PROFILE),) \
		--output-dir $(STREAM_SF2_OUT)

.PHONY: stage5-sf2-check
stage5-sf2-check:
	cd $(ROOT) && $(PYTHON) src/musikalisches/tools/validate_m1_artifacts.py --require-selection $(STREAM_SF2_OUT)

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
		$(if $(STAGE6_TEXT_CONFIG),--text-config $(STAGE6_TEXT_CONFIG),) \
		"$$SOURCE_DIR" \
		$(VIDEO_STUB_OUT)

.PHONY: stage6-video-check
stage6-video-check:
	@if [[ ! -f "$(VIDEO_STUB_OUT)/video_stub_scene.json" ]]; then \
		$(MAKE) stage6-video-stub; \
	fi
	cd $(ROOT) && $(PYTHON) src/musikalisches/tools/validate_stage6_video_stub.py $(VIDEO_STUB_OUT)

.PHONY: stage6-video-render
stage6-video-render:
	@$(MAKE) stage6-video-stub
	@$(MAKE) stage6-video-check
	cd $(ROOT) && PATH="$(ROOT)/ops/bin:$$PATH" $(PYTHON) src/musikalisches/tools/build_stage6_video_render.py \
		--ffmpeg-bin "$(FFMPEG_BIN)" \
		$(VIDEO_STUB_OUT) \
		$(VIDEO_RENDER_OUT)

.PHONY: stage6-video-render-check
stage6-video-render-check:
	@if [[ ! -f "$(VIDEO_RENDER_OUT)/offline_frame_sequence.json" ]]; then \
		$(MAKE) stage6-video-render; \
	fi
	cd $(ROOT) && $(PYTHON) src/musikalisches/tools/validate_stage6_video_render.py $(VIDEO_RENDER_OUT)

.PHONY: stage6-video-stub-sf2
stage6-video-stub-sf2:
	@SOURCE_DIR="$${STAGE6_SF2_SOURCE_DIR:-$(STREAM_SF2_OUT)}"; \
	if [[ ! -f "$$SOURCE_DIR/analysis_window_sequence.json" ]]; then \
		$(MAKE) stage5-sf2; \
	fi; \
	cd $(ROOT) && $(PYTHON) src/musikalisches/tools/build_stage6_video_stub.py \
		$(if $(STAGE6_SCENE_PROFILE),--scene-profile $(STAGE6_SCENE_PROFILE),) \
		$(if $(STAGE6_TEXT_CONFIG),--text-config $(STAGE6_TEXT_CONFIG),) \
		"$$SOURCE_DIR" \
		$(VIDEO_STUB_SF2_OUT)

.PHONY: stage6-video-check-sf2
stage6-video-check-sf2:
	@if [[ ! -f "$(VIDEO_STUB_SF2_OUT)/video_stub_scene.json" ]]; then \
		$(MAKE) stage6-video-stub-sf2; \
	fi
	cd $(ROOT) && $(PYTHON) src/musikalisches/tools/validate_stage6_video_stub.py $(VIDEO_STUB_SF2_OUT)

.PHONY: stage6-video-render-sf2
stage6-video-render-sf2:
	@$(MAKE) stage6-video-stub-sf2
	@$(MAKE) stage6-video-check-sf2
	cd $(ROOT) && PATH="$(ROOT)/ops/bin:$$PATH" $(PYTHON) src/musikalisches/tools/build_stage6_video_render.py \
		--ffmpeg-bin "$(FFMPEG_BIN)" \
		$(VIDEO_STUB_SF2_OUT) \
		$(VIDEO_RENDER_SF2_OUT)

.PHONY: stage6-video-render-check-sf2
stage6-video-render-check-sf2:
	@if [[ ! -f "$(VIDEO_RENDER_SF2_OUT)/offline_frame_sequence.json" ]]; then \
		$(MAKE) stage6-video-render-sf2; \
	fi
	cd $(ROOT) && $(PYTHON) src/musikalisches/tools/validate_stage6_video_render.py $(VIDEO_RENDER_SF2_OUT)

.PHONY: stage6-scene-profile-check
stage6-scene-profile-check:
	cd $(ROOT) && $(PYTHON) src/musikalisches/tools/validate_stage6_scene_profile.py \
		"$${STAGE6_SCENE_PROFILE:-$(DEFAULT_STAGE6_SCENE_PROFILE)}"

.PHONY: stage6-scene-profile-check-all
stage6-scene-profile-check-all:
	@for profile in $(ROOT)/src/musikalisches/runtime/config/stage6*_scene_profile.json; do \
		printf '%s\n' "$$profile"; \
		cd $(ROOT) && $(PYTHON) src/musikalisches/tools/validate_stage6_scene_profile.py "$$profile" || exit $$?; \
	done

.PHONY: stage6-scene-profile-show
stage6-scene-profile-show:
	@printf '%s\n' $(DEFAULT_STAGE6_SCENE_PROFILE)

.PHONY: stage6-text-config-show
stage6-text-config-show:
	@printf '%s\n' $(DEFAULT_STAGE6_TEXT_CONFIG)

.PHONY: stage6-plan-show
stage6-plan-show:
	@printf '%s\n' $(ROOT)/docs/plans/260321-stage6-video-stub-guide.md

.PHONY: stage6-render-plan-show
stage6-render-plan-show:
	@printf '%s\n' $(ROOT)/docs/plans/260321-stage6-render-video-guide.md

.PHONY: stage7-ffmpeg-build
stage7-ffmpeg-build:
	cd $(ROOT) && bash src/musikalisches/tools/build_stage7_rtmps_ffmpeg.sh

.PHONY: stage7-ffmpeg-check
stage7-ffmpeg-check:
	@if [[ ! -x "$(REPO_FFMPEG_BIN)" || ! -x "$(REPO_FFPROBE_BIN)" ]]; then \
		$(MAKE) stage7-ffmpeg-build; \
	fi
	cd $(ROOT) && PATH="$(ROOT)/ops/bin:$$PATH" $(PYTHON) src/musikalisches/tools/validate_stage7_ffmpeg_toolchain.py \
		--ffmpeg-bin "$(FFMPEG_BIN)" \
		--ffprobe-bin "$(FFPROBE_BIN)" \
		--output-dir "$(FFMPEG_TOOLCHAIN_OUT)"

.PHONY: stage7-bridge
stage7-bridge:
	@AUDIO_DIR="$${STAGE7_AUDIO_SOURCE_DIR:-$(STREAM_DEMO_OUT)}"; \
	VIDEO_DIR="$${STAGE7_VIDEO_SOURCE_DIR:-$(VIDEO_RENDER_OUT)}"; \
	for required in artifact_summary.json render_request.json stream_loop_plan.json m1_validation_report.json offline_audio.wav; do \
		if [[ ! -f "$$AUDIO_DIR/$$required" ]]; then \
			$(MAKE) stage5-stream; \
			break; \
		fi; \
	done; \
	for required in video_render_manifest.json stage6_render_validation_report.json offline_preview.mp4 visual_scene_profile.json; do \
		if [[ ! -f "$$VIDEO_DIR/$$required" ]]; then \
			$(MAKE) stage6-video-render; \
			break; \
		fi; \
	done; \
	cd $(ROOT) && PATH="$(ROOT)/ops/bin:$$PATH" $(PYTHON) src/musikalisches/tools/build_stage7_stream_bridge.py \
		$(if $(STAGE7_BRIDGE_PROFILE),--bridge-profile $(STAGE7_BRIDGE_PROFILE),) \
		--ffmpeg-bin "$(FFMPEG_BIN)" \
		--ffprobe-bin "$(FFPROBE_BIN)" \
		"$$AUDIO_DIR" \
		"$$VIDEO_DIR" \
		$(STREAM_BRIDGE_OUT)

.PHONY: stage7-bridge-check
stage7-bridge-check:
	@if [[ ! -f "$(STREAM_BRIDGE_OUT)/stream_bridge_manifest.json" || ! -f "$(STREAM_BRIDGE_OUT)/stream_bridge_ffmpeg_args.json" || ! -f "$(STREAM_BRIDGE_OUT)/run_stage7_stream_bridge.sh" || ! -f "$(STREAM_BRIDGE_OUT)/stage7_failure_taxonomy.json" || ! -f "$(STREAM_BRIDGE_OUT)/stage7_soak_plan.json" ]]; then \
		$(MAKE) stage7-bridge; \
	fi
	cd $(ROOT) && $(PYTHON) src/musikalisches/tools/validate_stage7_stream_bridge.py $(STREAM_BRIDGE_OUT)

.PHONY: stage7-preflight-regression-check
stage7-preflight-regression-check:
	@AUDIO_DIR="$${STAGE7_AUDIO_SOURCE_DIR:-$(STREAM_DEMO_OUT)}"; \
	VIDEO_DIR="$${STAGE7_VIDEO_SOURCE_DIR:-$(VIDEO_RENDER_OUT)}"; \
	for required in artifact_summary.json render_request.json stream_loop_plan.json m1_validation_report.json offline_audio.wav; do \
		if [[ ! -f "$$AUDIO_DIR/$$required" ]]; then \
			$(MAKE) stage5-stream; \
			break; \
		fi; \
	done; \
	for required in video_render_manifest.json stage6_render_validation_report.json offline_preview.mp4 visual_scene_profile.json; do \
		if [[ ! -f "$$VIDEO_DIR/$$required" ]]; then \
			$(MAKE) stage6-video-render; \
			break; \
		fi; \
	done; \
	cd $(ROOT) && PATH="$(ROOT)/ops/bin:$$PATH" $(PYTHON) src/musikalisches/tools/validate_stage7_preflight_failures.py \
		--ffmpeg-bin "$(FFMPEG_BIN)" \
		--ffprobe-bin "$(FFPROBE_BIN)" \
		"$$AUDIO_DIR" \
		"$$VIDEO_DIR" \
		"$(STAGE7_PREFLIGHT_REGRESSION_OUT)"

.PHONY: stage7-soak-check
stage7-soak-check:
	@if [[ ! -f "$(STREAM_BRIDGE_OUT)/stage7_soak_plan.json" ]]; then \
		$(MAKE) stage7-bridge; \
	fi
	cd $(ROOT) && $(PYTHON) src/musikalisches/tools/validate_stage7_soak.py $(STREAM_BRIDGE_OUT)

.PHONY: stage7-bridge-profile-show
stage7-bridge-profile-show:
	@printf '%s\n' $(DEFAULT_STAGE7_BRIDGE_PROFILE)

.PHONY: stage7-plan-show
stage7-plan-show:
	@printf '%s\n' $(ROOT)/docs/plans/260322-stage7-stream-bridge-guide.md

.PHONY: stage8-plan-show
stage8-plan-show:
	@printf '%s\n' $(ROOT)/docs/plans/260324-stage8-real-soak-ops-guide.md

.PHONY: stage8-readiness-check
stage8-readiness-check:
	@$(MAKE) stage7-ffmpeg-check
	@$(MAKE) stage7-bridge-check
	@$(MAKE) stage7-soak-check
	cd $(ROOT) && $(PYTHON) src/musikalisches/tools/validate_stage8_ops_readiness.py \
		--ffmpeg-bin "$(FFMPEG_BIN)" \
		--ffprobe-bin "$(FFPROBE_BIN)" \
		$(STREAM_BRIDGE_OUT)
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
	@$(MAKE) stage6-scene-profile-check-all
	@$(MAKE) stage6-video-stub
	@$(MAKE) stage6-video-check
	@$(MAKE) stage6-video-render
	@$(MAKE) stage6-video-render-check

.PHONY: stage6-sf2-all
stage6-sf2-all:
	@$(MAKE) stage5-sf2
	@$(MAKE) stage6-scene-profile-check-all
	@$(MAKE) stage6-video-stub-sf2
	@$(MAKE) stage6-video-check-sf2
	@$(MAKE) stage6-video-render-sf2
	@$(MAKE) stage6-video-render-check-sf2

.PHONY: stage7-all
stage7-all:
	@$(MAKE) stage5-stream
	@$(MAKE) stage6-video-render
	@$(MAKE) stage7-ffmpeg-check
	@$(MAKE) stage7-bridge
	@$(MAKE) stage7-bridge-check
	@$(MAKE) stage7-preflight-regression-check
	@$(MAKE) stage7-soak-check
.PHONY: plans-open
plans-open:
	@printf '%s\n' $(ROOT)/docs/plans/260321-stage5-build-and-manual-test-guide.md

.PHONY: clean-out
clean-out:
	rm -rf $(DEMO_OUT) $(STREAM_DEMO_OUT) $(STREAM_SF2_OUT) $(GOLDEN_OUT) $(VIDEO_STUB_OUT) $(VIDEO_STUB_SF2_OUT) $(VIDEO_RENDER_OUT) $(VIDEO_RENDER_SF2_OUT) $(STREAM_BRIDGE_OUT) $(FFMPEG_TOOLCHAIN_OUT)
