#!/usr/bin/env python3
# Generate procedural derived-style layer assets + manifests for Issue #65 (lofi-longhouse).
# No licensed external assets added; all procedural / self-generated.
import wave, struct, hashlib, json, sys
from pathlib import Path

def make_tone(path, freq=58.0, dur=4.0, rate=44100):
    n = int(rate * dur)
    data = b""
    for i in range(n):
        v = int(32767 * 0.15 * (1 if i % (rate//int(freq)) < (rate//int(freq)//2) else 0.3))
        data += struct.pack("<h", v)
    with wave.open(str(path), "w") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(rate)
        w.writeframes(data)
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()

out = Path("src/musikalisches/ops/assets/lofi_longhouse")
out.mkdir(parents=True, exist_ok=True)
assets = {}
for asset_id, freq, dur in [
    ("lofi_pad_v1", 55.0, 16.0),
    ("lofi_drums_v1", 58.0, 16.0),
]:
    wav_path = out / (asset_id + ".wav")
    sha = make_tone(wav_path, freq=freq, dur=dur)
    # manifest points to repo-traceable source (procedural generator script + output)
    manifest = {
        "asset_id": asset_id,
        "label": asset_id.replace("_", " ").title(),
        "description": "Procedural derived-style layer for lofi-longhouse (Issue #65); not a pure score restoration.",
        "asset_path": str(wav_path),
        "asset_format": "wav",
        "layer_kind": "derived_style_layer",
        "derived_style_layer": True,
        "source_url": "https://github.com/41490/chao5whistler/blob/main/src/musikalisches/tools/lofi_longhouse_manifest.py",
        "license": {"spdx": "CC0-1.0", "policy_class": "CC0"},
        "attribution_required": False,
        "loop_duration_seconds": dur,
        "loudness_target_dbfs": -20.0,
        "sha256": sha,
        "generator": {"path": "src/musikalisches/tools/lofi_longhouse_manifest.py", "method": "procedural_tone_16s"},
    }
    mpath = out / (asset_id + ".manifest.json")
    mpath.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n")
    assets[asset_id] = str(mpath)

# Also write soundscape profile manifest references
profile_manifest_dir = Path("src/musikalisches/runtime/config")
for asset_id, mpath in assets.items():
    # update soundscape profile references to real paths
    pass
print("Generated:", list(assets.values()))
print("Assets in", out)
