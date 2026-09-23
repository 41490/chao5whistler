#!/usr/bin/env python3
"""Validator for Issue #65 lofi-longhouse profile isolation and manifest fields."""
import json, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent.parent
ACADEMIC_DEFAULTS = {
    "src/musikalisches/runtime/config/stage5_default_synth_profile.json",
    "src/musikalisches/runtime/config/stage5_default_soundscape_profile.json",
    "src/musikalisches/runtime/config/stage6_default_scene_profile.json",
}
LOFI_PROFILES = [
    "src/musikalisches/runtime/config/stage5_lofi_longhouse_synth_profile.json",
    "src/musikalisches/runtime/config/stage5_lofi_longhouse_soundscape_profile.json",
    "src/musikalisches/runtime/config/stage6_lofi_longhouse_scene_profile.json",
]
REQUIRED_MANIFEST_FIELDS = {
    "asset_id", "source_url", "license", "attribution_required",
    "loop_duration_seconds", "loudness_target_dbfs", "sha256",
}

errors = []

# 1. Academic defaults unchanged (no diff from origin/main)
for rel in ACADEMIC_DEFAULTS:
    p = ROOT / rel
    if not p.exists():
        errors.append(f"missing academic default: {rel}")
    else:
        # verify it still contains expected profile_id markers
        data = json.loads(p.read_text())
        if rel.endswith("stage5_default_synth_profile.json"):
            if data.get("profile_id") != "stage5_default_dual_voice_organ_family":
                errors.append(f"academic default {rel} profile_id changed")
        elif rel.endswith("stage5_default_soundscape_profile.json"):
            if data.get("profile_id") != "stage5_default_multilayer_soundscape_v1":
                errors.append(f"academic default {rel} profile_id changed")
        elif rel.endswith("stage6_default_scene_profile.json"):
            if data.get("profile_id") != "stage6_default_dual_orbit_solarized_dark":
                errors.append(f"academic default {rel} profile_id changed")

# 2. lofi profiles exist and have style field
for rel in LOFI_PROFILES:
    p = ROOT / rel
    if not p.exists():
        errors.append(f"missing lofi profile: {rel}")
        continue
    data = json.loads(p.read_text())
    if data.get("style") != "lofi-longhouse":
        errors.append(f"{rel} missing style=lofi-longhouse")

# 3. derived_style_layer flags in soundscape
sc = json.loads((ROOT / LOFI_PROFILES[1]).read_text())
for layer in sc.get("derived_layers", []):
    if not layer.get("derived_style_layer"):
        errors.append(f"derived layer {layer.get('layer_id')} missing derived_style_layer=true")
    if not layer.get("muteable"):
        errors.append(f"derived layer {layer.get('layer_id')} not muteable")
# mix bus must have loudness/peak limits
mb = sc.get("mix_bus_profile", {})
if mb.get("peak_ceiling_amplitude", 1.0) > 0.95:
    errors.append("lofi mix bus peak ceiling too high")
if mb.get("require_no_clipping") is not True:
    errors.append("lofi mix bus must require no clipping")

# 4. manifest fields
for mpath in sorted((ROOT / "src/musikalisches/ops/assets/lofi_longhouse").glob("*.manifest.json")):
    data = json.loads(mpath.read_text())
    missing = REQUIRED_MANIFEST_FIELDS - set(data)
    if missing:
        errors.append(f"{mpath.name}: missing {missing}")
    if not str(data.get("source_url", "")).startswith("https://github.com/41490/chao5whistler"):
        errors.append(f"{mpath.name}: source_url not repo-traceable")
    if data.get("attribution_required") is not True and data.get("attribution_required") is not False:
        errors.append(f"{mpath.name}: attribution_required not bool")
    if float(data.get("loudness_target_dbfs", 1.0)) >= 0.0:
        errors.append(f"{mpath.name}: loudness_target_dbfs must be negative")
    if float(data.get("loop_duration_seconds", 0.0)) <= 0.0:
        errors.append(f"{mpath.name}: loop_duration_seconds must be > 0")
    wav = mpath.parent / (data["asset_id"] + ".wav")
    if not wav.exists():
        errors.append(f"{mpath.name}: wav missing")
    else:
        import hashlib
        actual = hashlib.sha256(wav.read_bytes()).hexdigest()
        if actual != data.get("sha256"):
            errors.append(f"{mpath.name}: sha256 mismatch")

if errors:
    print("VALIDATION FAILED:")
    for e in errors:
        print(" -", e)
    sys.exit(1)
print("lofi-longhouse profile validation OK")
sys.exit(0)
