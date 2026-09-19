# Issue #65: Lofi-Longhouse Style Profile Plan

## Goal
Add an independent, optional ambient style profile for lofi-longhouse style without modifying the existing academic defaults.

## Non-targets
- Do NOT modify `stage5_default_synth_profile.json`, `stage5_default_soundscape_profile.json`, `stage6_default_scene_profile.json`, or any default academic profile.
- Do NOT rewrite `freeze_rules.py` or canonical witness/rules.
- Do NOT add drums to the default academic output.
- Do NOT do long soak or live orchestration work.
- Do NOT claim pure score restoration.

## Implementation
- `stage5_lofi_longhouse_synth_profile.json`: explicit rhythm, drums, harmony pad, effects chain, loudness ceiling/peak limits.
- `stage5_lofi_longhouse_soundscape_profile.json`: all derived layers marked `derived_style_layer: true` and individually muteable.
- `stage6_lofi_longhouse_scene_profile.json`: slow static background scene mode reusing structural events.
- `lofi_longhouse_manifest.py`: procedural asset generator producing assets + manifests.
- `validate_lofi_longhouse_profile.py`: profile isolation and manifest field validator.
- `lofi_longhouse_render_ab.py`: offline A/B render producing audio report + visual preview with `profile_id` and `style=lofi-longhouse`.
- Makefile targets: `stage5-lofi-longhouse`, `stage5-lofi-longhouse-check`, `stage5-lofi-longhouse-render`.

## Acceptance
- Default academic profile behavior unchanged.
- All derived style layers individually muteable and marked `derived_style_layer: true`.
- Manifest fields present: `asset_id`, `source_url`, `license`, `attribution_required`, `loop_duration_seconds`, `loudness_target_dbfs`, `sha256`.
- At least one 16-cycle offline render with audio report + visual preview; preview metadata includes `profile_id` and `style=lofi-longhouse`.
- README and this plan describe non-target exclusions and A/B comparison.

## Verification
- `python3 src/musikalisches/tools/validate_lofi_longhouse_profile.py` — PASS.
- `python3 src/musikalisches/tools/lofi_longhouse_render_ab.py --output-dir ops/out/lofi-longhouse-render --loop-count 16` — PASS.
