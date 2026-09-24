#!/usr/bin/env python3
"""Slice the 11 source rolls into 176 audio fragments for issue #110 (83-R1).

Each fragment is exactly ``AUDIO_SAMPLES`` (33075) frames @ 44100 Hz == 0.75 s of
content; the 5+5 transparent gate frames live in the video time base only (see
``fragment_timebase.py``), so no gate samples are written here.

Outputs:
  <out>/audio/fragment_XXX.wav   176 slices, numbered 001..176 across rolls
  <out>/r1_manifest.json          "audio" section merged into the run manifest

Usage:
  python3 slice_fragment_audio.py [--data-root DIR] [--out-root DIR] [--selftest]
"""

import argparse
import json
import re
import sys
import wave
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from build_glyph_sprites import alpha_nonzero
from fragment_timebase import (AUDIO_SAMPLES, AUDIO_SR, QUANTIZATION_TOLERANCE,
                               contract_failures, onset_quantization_error)

DEFAULT_DATA_ROOT = "/opt/logs/41490/out/issue83-data"
DEFAULT_OUT_ROOT = "/opt/logs/41490/out/260924-issue83-r1"
MANIFEST_NAME = "r1_manifest.json"
EXPECTED_ROLLS = 11
EXPECTED_FRAGMENTS = 176
ROLL_RE = re.compile(r"^roll(\d+)$")


def discover_rolls(data_root):
    """roll2..roll12 in numeric order (lexicographic sort would misorder roll10)."""
    rolls = []
    for entry in Path(data_root).iterdir():
        match = ROLL_RE.match(entry.name) if entry.is_dir() else None
        if match:
            rolls.append((int(match.group(1)), entry))
    return [entry for _, entry in sorted(rolls)]


def read_json(path):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise SystemExit(f"unreadable json {path}: {exc}")


def onset_errors(data_root):
    """Every onset (note starts + fragment starts) of every roll, with its error."""
    errors = []
    for roll in discover_rolls(data_root):
        notes = read_json(roll / "note_event_sequence.json")
        frags = read_json(roll / "realized_fragment_sequence.json")
        times = [ev["start_seconds"] for ev in notes["note_events"]]
        times += [f["start_seconds"] for f in frags["fragments"]]
        for t in times:
            errors.append((roll.name, t, onset_quantization_error(t)))
    return errors


def slice_all(data_root, out_root):
    """Cut every fragment of every roll; returns the manifest "audio" section."""
    out_audio = Path(out_root) / "audio"
    out_audio.mkdir(parents=True, exist_ok=True)
    rolls = discover_rolls(data_root)
    if len(rolls) != EXPECTED_ROLLS:
        raise SystemExit(f"expected {EXPECTED_ROLLS} rolls, found {len(rolls)}")

    entries = []
    index = 0
    src_params = None
    for roll in rolls:
        seq = read_json(roll / "realized_fragment_sequence.json")
        with wave.open(str(roll / "offline_audio.wav"), "rb") as src:
            params = src.getparams()
            frames = src.readframes(src.getnframes())
        if params.framerate != AUDIO_SR:
            raise SystemExit(f"{roll}: framerate {params.framerate} != {AUDIO_SR}")
        if src_params is None:
            src_params = params
        elif src_params != params:
            raise SystemExit(f"{roll}: wav params differ from the first roll")
        frame_bytes = params.nchannels * params.sampwidth
        for frag in seq["fragments"]:
            index += 1
            start = round(frag["start_seconds"] * AUDIO_SR)
            stop = start + AUDIO_SAMPLES
            if round(frag["end_seconds"] * AUDIO_SR) != stop:
                raise SystemExit(
                    f"{roll} fragment {frag['fragment_id']}: "
                    f"{frag['start_seconds']}..{frag['end_seconds']}s is not "
                    f"{AUDIO_SAMPLES} samples")
            if stop > len(frames) // frame_bytes:
                raise SystemExit(
                    f"{roll} fragment {frag['fragment_id']}: slice exceeds source audio")
            name = f"fragment_{index:03d}.wav"
            with wave.open(str(out_audio / name), "wb") as dst:
                dst.setparams(params)
                dst.writeframes(frames[start * frame_bytes:stop * frame_bytes])
            entries.append(dict(
                index=index, file=name, roll=roll.name,
                fragment_id=frag["fragment_id"], step_index=frag["step_index"],
                position_label=frag["position_label"],
                start_seconds=frag["start_seconds"], end_seconds=frag["end_seconds"],
                start_sample=start, end_sample=stop, nframes=AUDIO_SAMPLES))
    if len(entries) != EXPECTED_FRAGMENTS:
        raise SystemExit(f"expected {EXPECTED_FRAGMENTS} fragments, wrote {len(entries)}")
    if src_params is None:
        raise SystemExit("no rolls read")
    return dict(count=len(entries), samples_per_fragment=AUDIO_SAMPLES,
                sample_rate=AUDIO_SR, channels=src_params.nchannels,
                sampwidth=src_params.sampwidth, fragments=entries)


def write_manifest(out_root, audio):
    path = Path(out_root) / MANIFEST_NAME
    manifest = {}
    if path.exists():
        try:
            manifest = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise SystemExit(f"unreadable manifest {path}: {exc}")
    manifest.setdefault("generated_by", "issue83-r1")
    manifest["audio"] = audio
    path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n",
                    encoding="utf-8")
    return path


def selftest(data_root, out_root):
    failures = []

    def check(desc, ok, detail=""):
        print(f"[{'PASS' if ok else 'FAIL'}] {desc}{(' — ' + detail) if detail else ''}")
        if not ok:
            failures.append(desc)

    # (a) 176 slices, each exactly 33075 frames
    audio_dir = Path(out_root) / "audio"
    wavs = sorted(audio_dir.glob("fragment_*.wav")) if audio_dir.is_dir() else []
    check(f"{EXPECTED_FRAGMENTS} fragment files present", len(wavs) == EXPECTED_FRAGMENTS,
          f"found {len(wavs)}")
    bad = []
    for wav in wavs:
        with wave.open(str(wav), "rb") as fh:
            if fh.getnframes() != AUDIO_SAMPLES or fh.getframerate() != AUDIO_SR:
                bad.append(f"{wav.name}:{fh.getnframes()}@{fh.getframerate()}")
    check("every slice == 33075 samples @44100Hz", not bad, ",".join(bad[:5]))

    # (b) time contract + zero quantization over all 11 rolls
    contract = contract_failures()
    check("timebase contract (18+5+5=28, 0.75*24=18, 0.75s==33075 samples)",
          not contract, "; ".join(contract))
    errs = onset_errors(data_root)
    worst = max((e for _, _, e in errs), default=0.0)
    check(f"zero quantization over {len(errs)} onsets in {EXPECTED_ROLLS} rolls",
          worst < QUANTIZATION_TOLERANCE, f"max error {worst!r}")

    # (c) every sprite is RGBA with non-empty alpha
    sprite_dir = Path(out_root) / "sprites"
    pngs = sorted(sprite_dir.glob("*.png")) if sprite_dir.is_dir() else []
    if not pngs:
        check("sprite PNGs present", False, f"none under {sprite_dir}")
    else:
        bad_sprite = []
        for png in pngs:
            try:
                if alpha_nonzero(png) <= 0:
                    bad_sprite.append(f"{png.name}:empty-alpha")
            except RuntimeError as exc:
                bad_sprite.append(f"{png.name}:{exc}")
        check(f"{len(pngs)} sprites RGBA with alpha>0", not bad_sprite,
              ",".join(bad_sprite[:5]))

    # manifest agrees with what is on disk
    path = Path(out_root) / MANIFEST_NAME
    if path.exists():
        manifest = read_json(path)
        audio = manifest.get("audio") or {}
        listed = audio.get("fragments", [])
        check("manifest lists 176 slices with 33075 samples each",
              len(listed) == EXPECTED_FRAGMENTS
              and all(f["nframes"] == AUDIO_SAMPLES for f in listed),
              f"{len(listed)} entries")
        check("manifest lists every sprite", len(manifest.get("sprites", [])) == len(pngs),
              f"{len(manifest.get('sprites', []))} vs {len(pngs)} on disk")
    else:
        check("manifest present", False, str(path))

    print(f"selftest: {len(failures)} failure(s)")
    return 1 if failures else 0


def main(argv=None):
    ap = argparse.ArgumentParser(description="slice roll audio into 176 fragments")
    ap.add_argument("--data-root", default=DEFAULT_DATA_ROOT)
    ap.add_argument("--out-root", default=DEFAULT_OUT_ROOT)
    ap.add_argument("--selftest", action="store_true")
    args = ap.parse_args(argv)

    if args.selftest:
        return selftest(args.data_root, args.out_root)

    audio = slice_all(args.data_root, args.out_root)
    path = write_manifest(args.out_root, audio)
    print(f"wrote {path} (audio: {audio['count']} slices x {audio['samples_per_fragment']} samples)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
