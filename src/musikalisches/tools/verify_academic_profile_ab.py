#!/usr/bin/env python3
"""Machine check for the issue #63 academic organ A/B profiles.

Compares two already-rendered artifact directories (dry baseline vs. enhanced
chapel profile) and asserts the expectations declared by the enhanced profile's
``mix.ab_expectations``. The script never renders: both directories must come
from

    cargo run -- render-audio --work mozart_dicegame_print_1790s --demo-rolls \
      --synth-profile <dry.json>      --output-dir <dry-dir>
    cargo run -- render-audio --work mozart_dicegame_print_1790s --demo-rolls \
      --synth-profile <chapel.json>   --output-dir <enhanced-dir>

Stdlib only (``loudness_meter.py`` next to this file is also stdlib only).

Assertions
----------
a) ``note_event_sequence.json`` / ``event_transition_sequence.json`` /
   ``realized_fragment_sequence.json`` are byte-identical on both sides: the
   mix profile must not move the note/transition/realization layers.
b) premix dynamic spread: ``dynamic_spread_db(enhanced) >=
   dynamic_spread_db(dry) + ab_expectations.dynamic_spread_gain_db_min``.
   Measured on ``offline_audio.wav`` (the render-audio premix, i.e. before the
   stage5 soundscape mix bus adds the beds). The post-mix-bus WAV compresses the
   spread, so it is never used for this assertion.
c) reverb tail present on the enhanced side only.
d) melody not masked: the enhanced main-layer envelope peak retains
   ``MELODY_PEAK_RETENTION_MIN`` of the dry peak, and the enhanced short-term
   loudness range is wider than the dry one (dynamics really exist).
e) enhanced premix ``integrated_lufs`` sits inside ``ab_expectations.lufs_band``;
   the dry side is recorded but not asserted.

Exit status: 0 when every assertion passes, 1 otherwise. Failures are printed
and (with ``--report``) written into the report JSON under
``failed_assertions``.

Measurement notes (Issue #71)
------------------------------
* The renderer appends a configurable zero-input tail after the last note-off
  before applying equal-length reverb. Assertion (c) measures window RMS dBFS
  in that post-last-note-off region; dry participates only as the explicit
  no-tail counter-example.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
from pathlib import Path

from loudness_meter import measure_pcm, read_wav_pcm

IDENTITY_ARTIFACTS = (
    "note_event_sequence.json",
    "event_transition_sequence.json",
    "realized_fragment_sequence.json",
)
ANALYSIS_FILE = "analysis_window_sequence.json"
NOTE_EVENT_FILE = "note_event_sequence.json"
ARTIFACT_SUMMARY_FILE = "artifact_summary.json"
AUDIO_FILE = "offline_audio.wav"
REQUIRED_FILES = IDENTITY_ARTIFACTS + (
    ANALYSIS_FILE,
    ARTIFACT_SUMMARY_FILE,
    AUDIO_FILE,
)

# Main-layer envelope peak retained by the enhanced render, relative to the dry
# render. Source: issue #63 lane1/lane2 acceptance baseline -- the chapel
# profile's EQ/pan/velocity changes are allowed to attenuate the main layer, but
# by no more than ~2 dB (dry peak envelope 0.0553 -> enhanced 0.0647, i.e. 1.17x).
MELODY_PEAK_RETENTION_MIN = 0.8
MEASUREMENT_ID = "issue71_academic_ab_absolute_tail_v2"
EXPECTATION_KEYS = (
    "dynamic_spread_gain_db_min",
    "reverb_tail_dbfs_min",
    "lufs_band",
)


class InputError(Exception):
    """An input artifact or profile could not be read, parsed, or validated."""


def load_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise InputError(f"cannot read {path}: {error}") from error


def require_float(mapping: dict, key: str, context: str) -> float:
    value = mapping.get(key)
    if isinstance(value, (int, float, str)):
        try:
            return float(value)
        except ValueError as error:
            raise InputError(f"{context}.{key} must be a number, got {value!r}") from error
    raise InputError(f"{context}.{key} must be a number, got {value!r}")


def require_expectations(profile: dict) -> dict:
    expectations = profile.get("mix", {}).get("ab_expectations")
    if not isinstance(expectations, dict):
        raise InputError(
            f"profile {profile.get('profile_id')} has no mix.ab_expectations block"
        )
    missing = [key for key in EXPECTATION_KEYS if key not in expectations]
    if missing:
        raise InputError(f"mix.ab_expectations is missing {missing}")
    return expectations


def require_lufs_band(expectations: dict) -> tuple[float, float]:
    band = expectations.get("lufs_band")
    if not isinstance(band, (list, tuple)) or len(band) != 2:
        raise InputError(f"mix.ab_expectations.lufs_band must be a 2-element list, got {band!r}")
    try:
        return float(band[0]), float(band[1])
    except (TypeError, ValueError) as error:
        raise InputError(f"mix.ab_expectations.lufs_band must be numeric, got {band!r}") from error


def dbfs(amplitude: float | None) -> float | None:
    if amplitude is None or amplitude <= 0.0:
        return None
    return round(20.0 * math.log10(amplitude), 3)


def missing_artifacts(directory: Path) -> list[str]:
    return [name for name in REQUIRED_FILES if not (directory / name).is_file()]


def check_sequence_identity(dry_dir: Path, enhanced_dir: Path) -> dict:
    artifacts: dict[str, dict] = {}
    failures: list[str] = []
    for name in IDENTITY_ARTIFACTS:
        dry_bytes = (dry_dir / name).read_bytes()
        enhanced_bytes = (enhanced_dir / name).read_bytes()
        identical = dry_bytes == enhanced_bytes
        artifacts[name] = {
            "byte_identical": identical,
            "sha256_dry": hashlib.sha256(dry_bytes).hexdigest(),
            "sha256_enhanced": hashlib.sha256(enhanced_bytes).hexdigest(),
        }
        if not identical:
            failures.append(f"a: {name} differs between the dry and enhanced renders")
    return {"passed": not failures, "failures": failures, "artifacts": artifacts}


def check_dynamic_spread(
    dry_measure: dict, enhanced_measure: dict, expectations: dict
) -> dict:
    dry_spread = dry_measure["dynamic_spread_db"]
    enhanced_spread = enhanced_measure["dynamic_spread_db"]
    required = require_float(expectations, "dynamic_spread_gain_db_min", "mix.ab_expectations")
    gain = (
        None
        if dry_spread is None or enhanced_spread is None
        else round(enhanced_spread - dry_spread, 3)
    )
    failures: list[str] = []
    if gain is None:
        failures.append("b: dynamic_spread_db is missing on one side of the premix render")
    elif gain < required:
        failures.append(
            f"b: premix dynamic spread gain {gain} dB < required {required} dB "
            f"(dry {dry_spread} dB, enhanced {enhanced_spread} dB)"
        )
    return {
        "passed": not failures,
        "failures": failures,
        "premix_dynamic_spread_db_dry": dry_spread,
        "premix_dynamic_spread_db_enhanced": enhanced_spread,
        "premix_dynamic_spread_gain_db": gain,
        "required_dynamic_spread_gain_db_min": required,
    }


def check_reverb_tail(
    enhanced_windows: list[dict],
    note_events: list[dict],
    expectations: dict,
) -> dict:
    last_note_off = max(event["end_seconds"] for event in note_events)
    indices = [
        index for index, window in enumerate(enhanced_windows)
        if window["start_seconds"] >= last_note_off
    ]
    floor = require_float(expectations, "reverb_tail_dbfs_min", "mix.ab_expectations")
    failures: list[str] = []
    result = {
        "passed": False,
        "failures": failures,
        "tail_window_basis": "post_last_note_off_rms",
        "tail_window_count": len(indices),
        "last_note_off_seconds": last_note_off,
        "required_reverb_tail_dbfs_min": floor,
        "reverb_tail_dbfs_enhanced": None,
    }
    if not indices:
        failures.append("c: no observable tail region.")
        return result
    enhanced_tail = dbfs(max(enhanced_windows[i]["rms_amplitude"] for i in indices))
    result.update(
        {
            "reverb_tail_dbfs_enhanced": enhanced_tail,
            "reverb_tail_measure": "maximum post-last-note-off window RMS dBFS",
        }
    )
    if enhanced_tail is None or enhanced_tail < floor:
        failures.append(
            f"c: enhanced tail {enhanced_tail} dBFS < required floor {floor} dBFS "
            f"(post-last-note-off, {len(indices)} windows)"
        )
    result["passed"] = not failures
    return result


def short_term_range(measure: dict) -> float | None:
    low = measure["lufs_short_term_min"]
    high = measure["lufs_short_term_max"]
    if low is None or high is None:
        return None
    return round(high - low, 3)


def check_melody_unmasked(
    dry_windows: list[dict], enhanced_windows: list[dict], dry_measure: dict, enhanced_measure: dict
) -> dict:
    dry_peak = max(window["envelope_amplitude"] for window in dry_windows)
    enhanced_peak = max(window["envelope_amplitude"] for window in enhanced_windows)
    retention = round(enhanced_peak / dry_peak, 3) if dry_peak > 0.0 else None
    dry_range = short_term_range(dry_measure)
    enhanced_range = short_term_range(enhanced_measure)
    failures: list[str] = []
    if retention is None or retention < MELODY_PEAK_RETENTION_MIN:
        failures.append(
            f"d: main-layer envelope peak retention {retention} < required "
            f"{MELODY_PEAK_RETENTION_MIN} (dry {dry_peak}, enhanced {enhanced_peak})"
        )
    if dry_range is None or enhanced_range is None or enhanced_range <= dry_range:
        failures.append(
            f"d: enhanced short-term loudness range {enhanced_range} dB is not wider "
            f"than the dry range {dry_range} dB"
        )
    return {
        "passed": not failures,
        "failures": failures,
        "main_layer_envelope_peak_dry": dry_peak,
        "main_layer_envelope_peak_enhanced": enhanced_peak,
        "main_layer_envelope_peak_retention": retention,
        "required_main_layer_envelope_peak_retention_min": MELODY_PEAK_RETENTION_MIN,
        "lufs_short_term_range_db_dry": dry_range,
        "lufs_short_term_range_db_enhanced": enhanced_range,
    }


def check_lufs_band(dry_measure: dict, enhanced_measure: dict, expectations: dict) -> dict:
    low, high = require_lufs_band(expectations)
    integrated = enhanced_measure["integrated_lufs"]
    failures: list[str] = []
    if integrated is None or not low <= integrated <= high:
        failures.append(
            f"e: enhanced premix integrated_lufs {integrated} outside declared band "
            f"[{low}, {high}] (basis {expectations.get('lufs_band_basis')})"
        )
    return {
        "passed": not failures,
        "failures": failures,
        "integrated_lufs_dry": dry_measure["integrated_lufs"],
        "integrated_lufs_enhanced": integrated,
        "lufs_band": [low, high],
        "lufs_band_basis": expectations.get("lufs_band_basis"),
        "dry_side_asserted": False,
    }


def measure_note_active(path: Path, last_note_off: float) -> dict:
    try:
        audio = read_wav_pcm(path)
        frame_count = int(last_note_off * audio["sample_rate"])
        pcm = audio["pcm"][: frame_count * audio["channels"]]
        return measure_pcm(pcm, sample_rate=audio["sample_rate"], channels=audio["channels"])
    except (OSError, ValueError, KeyError, TypeError) as error:
        raise InputError(f"cannot measure note-active PCM {path}: {error}") from error


def run_checks(dry_dir: Path, enhanced_dir: Path, profile: dict) -> dict:
    expectations = require_expectations(profile)
    dry_windows = load_json(dry_dir / ANALYSIS_FILE)["windows"]
    enhanced_windows = load_json(enhanced_dir / ANALYSIS_FILE)["windows"]
    note_events = load_json(enhanced_dir / NOTE_EVENT_FILE)["note_events"]
    last_note_off = max(event["end_seconds"] for event in note_events)
    dry_measure = measure_note_active(dry_dir / AUDIO_FILE, last_note_off)
    enhanced_measure = measure_note_active(enhanced_dir / AUDIO_FILE, last_note_off)

    checks = {
        "a_sequence_identity": check_sequence_identity(dry_dir, enhanced_dir),
        "b_premix_dynamic_spread": check_dynamic_spread(
            dry_measure, enhanced_measure, expectations
        ),
        "c_reverb_tail": check_reverb_tail(
            enhanced_windows, note_events, expectations
        ),
        "d_melody_unmasked": check_melody_unmasked(
            dry_windows, enhanced_windows, dry_measure, enhanced_measure
        ),
        "e_lufs_band": check_lufs_band(dry_measure, enhanced_measure, expectations),
    }
    failed = [name for name, check in checks.items() if not check["passed"]]
    failures = [reason for check in checks.values() for reason in check["failures"]]
    return {
        "check": "academic_profile_ab",
        "measurement": MEASUREMENT_ID,
        "dry_dir": str(dry_dir),
        "enhanced_dir": str(enhanced_dir),
        "profile_id": profile.get("profile_id"),
        "premix_measure_basis": "note_active_region",
        "premix_measure_duration_semantics": "duration_seconds is note-active region duration",
        "premix_loudness_dry": dry_measure,
        "premix_loudness_enhanced": enhanced_measure,
        "assertions": checks,
        "failed_assertions": failed,
        "failures": failures,
        "passed": not failed,
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Machine-check the issue #63 academic dry/enhanced A/B renders."
    )
    parser.add_argument("--dry", required=True, help="artifact dir rendered with the dry profile")
    parser.add_argument(
        "--enhanced", required=True, help="artifact dir rendered with the enhanced profile"
    )
    parser.add_argument(
        "--profile", required=True, help="enhanced profile JSON carrying mix.ab_expectations"
    )
    parser.add_argument("--report", help="optional path for the JSON report")
    args = parser.parse_args()

    dry_dir = Path(args.dry).resolve()
    enhanced_dir = Path(args.enhanced).resolve()
    profile_path = Path(args.profile).resolve()

    report: dict = {
        "check": "academic_profile_ab",
        "measurement": MEASUREMENT_ID,
        "dry_dir": str(dry_dir),
        "enhanced_dir": str(enhanced_dir),
        "profile": str(profile_path),
        "passed": False,
        "failed_assertions": ["input"],
        "failures": [],
    }
    for label, directory in (("dry", dry_dir), ("enhanced", enhanced_dir)):
        missing = missing_artifacts(directory)
        if missing:
            report["failures"].append(f"input: {label} dir {directory} is missing {missing}")
    if not profile_path.is_file():
        report["failures"].append(f"input: profile {profile_path} does not exist")
    if report["failures"]:
        write_report(args.report, report)
        for failure in report["failures"]:
            print(f"[FAIL] {failure}")
        return 1

    try:
        report = run_checks(dry_dir, enhanced_dir, load_json(profile_path))
    except InputError as error:
        report["failed_assertions"] = ["input"]
        report["failures"].append(f"input: {error}")
        write_report(args.report, report)
        print(f"[FAIL] input: {error}")
        return 1
    write_report(args.report, report)

    for name, check in report["assertions"].items():
        print(f"[{'PASS' if check['passed'] else 'FAIL'}] {name}")
        for failure in check["failures"]:
            print(f"       {failure}")
    if report["passed"]:
        print(f"A/B check passed: {dry_dir} vs {enhanced_dir}")
        return 0
    print(f"A/B check failed: {', '.join(report['failed_assertions'])}")
    return 1


def write_report(path: str | None, report: dict) -> None:
    if not path:
        return
    report_path = Path(path)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    sys.exit(main())
