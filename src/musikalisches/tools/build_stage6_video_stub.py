#!/usr/bin/env python3

from __future__ import annotations

import argparse
import hashlib
import json
import math
import random
from pathlib import Path
from xml.sax.saxutils import escape

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - Python 3.11+ should provide tomllib
    tomllib = None

from stage6_scene_profile import (
    DEFAULT_SCENE_PROFILE_PATH,
    validate_scene_profile_payload,
)


REQUIRED_INPUT_FILES = {
    "analysis_window_sequence.json",
    "stream_loop_plan.json",
    "synth_routing_profile.json",
    "artifact_summary.json",
    "realized_fragment_sequence.json",
}
ROOT_PATH = Path(__file__).resolve().parents[3]


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: dict) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=True, indent=2) + "\n",
        encoding="utf-8",
    )


def sample_items(items: list[dict], limit: int) -> list[dict]:
    if len(items) <= limit:
        return items
    if limit <= 1:
        return [items[0]]

    sampled: list[dict] = []
    last_index = len(items) - 1
    for sample_index in range(limit):
        item_index = round(sample_index * last_index / (limit - 1))
        sampled.append(items[item_index])
    return sampled


def resolve_config_path(path_value: str) -> Path:
    path = Path(path_value)
    if path.is_absolute():
        return path.resolve()
    return (ROOT_PATH / path).resolve()


def load_toml(path: Path) -> dict:
    if tomllib is None:
        raise SystemExit("tomllib is unavailable; Python 3.11+ is required for stage6 text overrides")
    return tomllib.loads(path.read_text(encoding="utf-8"))


def lookup_toml_section(payload: dict, dotted_section: str) -> dict:
    current: object = payload
    for section in dotted_section.split("."):
        if not isinstance(current, dict) or section not in current:
            raise SystemExit(f"missing TOML section [{dotted_section}]")
        current = current[section]
    if not isinstance(current, dict):
        raise SystemExit(f"TOML section [{dotted_section}] must resolve to a table")
    return current


def resolve_title_text(
    scene_profile: dict,
    text_config_override: Path | None,
) -> dict:
    text_contract = scene_profile["text_overrides"]
    text_config_path = (
        text_config_override.resolve()
        if text_config_override is not None
        else resolve_config_path(text_contract["default_toml_path"])
    )
    if not text_config_path.exists():
        raise SystemExit(f"stage6 text config does not exist: {text_config_path}")
    toml_payload = load_toml(text_config_path)
    section = lookup_toml_section(toml_payload, text_contract["toml_section"])
    title_key = text_contract["title_key"]
    raw_title = section.get(title_key)
    if not isinstance(raw_title, str) or raw_title.strip() == "":
        raise SystemExit(
            f"stage6 text config must provide non-empty [{text_contract['toml_section']}].{title_key}"
        )
    normalized_title = raw_title.replace("\\n", "\n")
    title_lines = [line.strip() for line in normalized_title.splitlines() if line.strip()]
    if not title_lines:
        raise SystemExit("stage6 title override must resolve to at least one non-empty line")
    if len(title_lines) > text_contract["max_title_lines"]:
        raise SystemExit(
            f"stage6 title override resolved to {len(title_lines)} lines; "
            f"max supported is {text_contract['max_title_lines']}"
        )
    return {
        "source_path": str(text_config_path),
        "source_section": text_contract["toml_section"],
        "source_key": title_key,
        "raw_title": raw_title,
        "normalized_title": normalized_title,
        "title_lines": title_lines,
        "line_count": len(title_lines),
        "horizontal_alignment": text_contract["horizontal_alignment"],
        "newline_mode": text_contract["newline_mode"],
    }


def format_count(value: int | None) -> str:
    return f"{int(value or 0):,}"


def build_title_area(scene_profile: dict, title_text: dict) -> dict:
    return {
        **scene_profile["title_area"],
        "text_lines": title_text["title_lines"],
        "line_count": title_text["line_count"],
        "source_path": title_text["source_path"],
        "source_section": title_text["source_section"],
        "source_key": title_text["source_key"],
    }


def build_footer_progress_area(scene_profile: dict, selection: dict) -> dict:
    template = scene_profile["footer_progress_area"]["format_template"]
    return {
        **scene_profile["footer_progress_area"],
        "played_unique_count": selection["played_unique_count"],
        "total_combinations": selection["total_combinations"],
        "text": template.format(
            played_unique_count=format_count(selection["played_unique_count"]),
            total_combinations=format_count(selection["total_combinations"]),
        ),
    }


def build_fragment_timeline(realized_fragments: dict, cycles: list[dict]) -> list[dict]:
    fragments = realized_fragments.get("fragments", [])
    if not fragments:
        raise SystemExit("realized_fragment_sequence.json must contain at least one fragment")
    base_duration = realized_fragments.get("summary", {}).get("total_duration_seconds")
    if base_duration is None:
        raise SystemExit("realized_fragment_sequence.json summary.total_duration_seconds is required")

    timeline: list[dict] = []
    for cycle in cycles:
        cycle_duration = cycle.get("end_seconds", 0.0) - cycle.get("start_seconds", 0.0)
        if not math.isclose(cycle_duration, base_duration, rel_tol=0.0, abs_tol=1e-6):
            raise SystemExit(
                "realized_fragment_sequence.json duration must match each stream_loop_plan cycle duration"
            )
        cycle_start = cycle.get("start_seconds", 0.0)
        for fragment in fragments:
            timeline.append(
                {
                    "cycle_index": cycle["cycle_index"],
                    "step_index": fragment["step_index"],
                    "position_label": fragment["position_label"],
                    "position_index": fragment["position_index"],
                    "selector_value": fragment["selector_value"],
                    "fragment_id": fragment["fragment_id"],
                    "start_seconds": round(cycle_start + fragment["start_seconds"], 6),
                    "end_seconds": round(cycle_start + fragment["end_seconds"], 6),
                    "duration_seconds": round(
                        fragment["end_seconds"] - fragment["start_seconds"],
                        6,
                    ),
                }
            )
    return timeline


def build_selector_label_sprites(
    *,
    scene_profile: dict,
    selection: dict,
    fragment_timeline: list[dict],
) -> dict:
    area = scene_profile["selector_label_sprites"]
    rows = 4
    columns = 4
    cell_width = area["width"] / columns
    cell_height = area["height"] / rows
    seed_source = selection["combination_id"]
    seed_value = int(hashlib.sha256(seed_source.encode("utf-8")).hexdigest()[:16], 16)
    chooser = random.Random(seed_value)
    accent_sequence = scene_profile["palette"]["accent_sequence"]
    colors = scene_profile["palette"]["colors"]

    sprites: list[dict] = []
    for index, selector in enumerate(selection["selector_results"]):
        row = index // columns
        column = index % columns
        jitter_x = chooser.uniform(-cell_width * 0.12, cell_width * 0.12)
        jitter_y = chooser.uniform(-cell_height * 0.12, cell_height * 0.12)
        font_size = chooser.randint(
            area["label_min_font_size_px"],
            area["label_max_font_size_px"],
        )
        label_width = int(round(cell_width - area["label_padding_px"] * 2))
        label_height = int(round(max(cell_height * 0.58, font_size * 1.8)))
        x = area["x"] + column * cell_width + area["label_padding_px"] + jitter_x
        y = area["y"] + row * cell_height + area["label_padding_px"] + jitter_y
        x = min(max(x, area["x"]), area["x"] + area["width"] - max(1, label_width))
        y = min(max(y, area["y"]), area["y"] + area["height"] - max(1, label_height))
        active_windows = [
            {
                "cycle_index": fragment["cycle_index"],
                "start_seconds": fragment["start_seconds"],
                "end_seconds": fragment["end_seconds"],
                "fragment_id": fragment["fragment_id"],
            }
            for fragment in fragment_timeline
            if fragment["position_index"] == selector["position_index"]
        ]
        accent_name = accent_sequence[index % len(accent_sequence)]
        sprites.append(
            {
                "sprite_id": f"selector_label_{selector['position_index']:02d}",
                "position_label": selector["position_label"],
                "position_index": selector["position_index"],
                "selector_value": selector["selector_value"],
                "text": f"{selector['position_label']} = {selector['selector_value']}",
                "x": round(x, 2),
                "y": round(y, 2),
                "width": max(1, label_width),
                "height": max(1, label_height),
                "font_size_px": font_size,
                "accent_name": accent_name,
                "accent_color": colors[accent_name],
                "idle_motion": {
                    "drift_px": area["idle_drift_px"],
                    "rotation_degrees": area["idle_rotation_degrees"],
                },
                "active_motion": {
                    "bounce_y_px": area["active_bounce_y_px"],
                    "scale_multiplier": area["active_scale_multiplier"],
                },
                "active_windows": active_windows,
            }
        )

    return {
        **area,
        "random_seed": seed_value,
        "random_seed_value": seed_source,
        "sprite_count": len(sprites),
        "sprites": sprites,
    }


def build_spectrum_trails(scene_profile: dict, keyframes: list[dict], preview_limit: int) -> dict:
    contract = scene_profile["spectrum_trails"]
    sampled = sample_items(keyframes, limit=preview_limit)
    height = contract["height"]
    floor = contract["envelope_floor"]
    ceiling = contract["envelope_ceiling"]
    span = max(ceiling - floor, 1e-9)
    sampled_points: list[dict] = []
    for keyframe in sampled:
        normalized = min(
            1.0,
            max(0.0, (keyframe["normalized_envelope"] - floor) / span),
        )
        sampled_points.append(
            {
                "window_index": keyframe["window_index"],
                "clock_seconds": keyframe["clock_seconds"],
                "normalized_envelope": keyframe["normalized_envelope"],
                "trail_y_px": round(contract["y"] + height * (1.0 - normalized), 2),
                "stroke_width_px": round(
                    contract["stroke_min_width_px"]
                    + normalized
                    * (contract["stroke_max_width_px"] - contract["stroke_min_width_px"]),
                    2,
                ),
                "alpha": round(contract["alpha_base"] + normalized * contract["alpha_range"], 3),
            }
        )
    return {
        **contract,
        "envelope_source": "keyframes.normalized_envelope",
        "sampled_point_count": len(sampled_points),
        "sampled_points": sampled_points,
    }


def build_text_overrides_scene_block(scene_profile: dict, title_text: dict) -> dict:
    return {
        **scene_profile["text_overrides"],
        "resolved_title": title_text["normalized_title"],
        "resolved_title_lines": title_text["title_lines"],
        "source_path": title_text["source_path"],
    }


def resolve_scene_profile(
    profile_path: Path,
    width_override: int | None,
    height_override: int | None,
    fps_override: int | None,
) -> dict:
    if not profile_path.exists():
        raise SystemExit(f"scene profile does not exist: {profile_path}")

    profile = load_json(profile_path)
    input_errors = validate_scene_profile_payload(profile, allow_output_metadata=False)
    if input_errors:
        raise SystemExit(
            "scene profile validation failed:\n- " + "\n- ".join(input_errors)
        )

    resolved = json.loads(json.dumps(profile))
    resolved["canvas"]["width"] = width_override or resolved["canvas"]["width"]
    resolved["canvas"]["height"] = height_override or resolved["canvas"]["height"]
    resolved["canvas"]["fps"] = fps_override or resolved["canvas"]["fps"]
    resolved["source"] = (
        "repo_default"
        if profile_path.resolve() == DEFAULT_SCENE_PROFILE_PATH.resolve()
        else "cli"
    )
    resolved["source_path"] = str(profile_path.resolve())
    resolved_errors = validate_scene_profile_payload(resolved, allow_output_metadata=True)
    if resolved_errors:
        raise SystemExit(
            "resolved scene profile validation failed:\n- " + "\n- ".join(resolved_errors)
        )
    return resolved


def build_lane_layout(
    synth_profile: dict,
    scene_profile: dict,
) -> list[dict]:
    voice_groups = synth_profile.get("voice_groups", [])
    width = scene_profile["canvas"]["width"]
    height = scene_profile["canvas"]["height"]
    motion = scene_profile["motion"]
    palette = scene_profile["palette"]
    max_base_amplitude = max(
        (group.get("base_amplitude", 0.0) for group in voice_groups),
        default=1.0,
    )
    sorted_groups = sorted(
        voice_groups,
        key=lambda group: (
            group.get("right_gain", 0.0) - group.get("left_gain", 0.0),
            group.get("part_index", 0),
        ),
    )

    lanes: list[dict] = []
    spacing = width / (len(sorted_groups) + 1) if sorted_groups else width
    for index, group in enumerate(sorted_groups, start=1):
        stereo_bias = round(
            group.get("right_gain", 0.0) - group.get("left_gain", 0.0),
            3,
        )
        amplitude_weight = max(
            0.2,
            group.get("base_amplitude", 0.0) / max_base_amplitude,
        )
        accent_name = palette["accent_sequence"][
            (index - 1) % len(palette["accent_sequence"])
        ]
        lanes.append(
            {
                "lane_id": f"voice_group_{group.get('part_index', index)}",
                "part_index": group.get("part_index"),
                "channel": group.get("channel"),
                "program": group.get("program"),
                "velocity": group.get("velocity"),
                "stereo_bias": stereo_bias,
                "amplitude_weight": round(amplitude_weight, 6),
                "center_x": round(spacing * index, 2),
                "center_y": round(
                    height * motion["lane_center_y_ratio"]
                    + stereo_bias * height * motion["lane_bias_y_range_ratio"],
                    2,
                ),
                "left_gain": group.get("left_gain"),
                "right_gain": group.get("right_gain"),
                "accent_name": accent_name,
                "accent_color": palette["colors"][accent_name],
            }
        )
    return lanes


def build_cycles(
    stream_plan: dict,
    analysis_windows: list[dict],
    scene_profile: dict,
) -> list[dict]:
    palette = scene_profile["palette"]
    cycles: list[dict] = []
    for cycle in stream_plan.get("cycles", []):
        cycle_windows = [
            window
            for window in analysis_windows
            if window.get("cycle_index") == cycle.get("cycle_index")
        ]
        accent_name = palette["accent_sequence"][
            (cycle["cycle_index"] - 1) % len(palette["accent_sequence"])
        ]
        envelope_values = [window.get("envelope_amplitude", 0.0) for window in cycle_windows]
        cycles.append(
            {
                "cycle_index": cycle.get("cycle_index"),
                "start_seconds": cycle.get("start_seconds"),
                "end_seconds": cycle.get("end_seconds"),
                "start_frame": cycle.get("start_frame"),
                "end_frame": cycle.get("end_frame"),
                "window_count": len(cycle_windows),
                "note_event_count": cycle.get("note_event_count"),
                "synth_event_count": cycle.get("synth_event_count"),
                "accent_name": accent_name,
                "accent_color": palette["colors"][accent_name],
                "mean_envelope_amplitude": round(
                    sum(envelope_values) / len(envelope_values),
                    6,
                )
                if envelope_values
                else 0.0,
                "max_envelope_amplitude": round(max(envelope_values), 6)
                if envelope_values
                else 0.0,
            }
        )
    return cycles


def build_keyframes(
    analysis: dict,
    cycles: list[dict],
    lanes: list[dict],
    scene_profile: dict,
) -> list[dict]:
    windows = analysis.get("windows", [])
    colors = scene_profile["palette"]["colors"]
    motion = scene_profile["motion"]
    accent_sequence = scene_profile["palette"]["accent_sequence"]
    max_envelope = max(
        (window.get("envelope_amplitude", 0.0) for window in windows),
        default=1.0,
    )
    max_peak = max((window.get("peak_amplitude", 0.0) for window in windows), default=1.0)

    cycle_color_by_index = {
        cycle["cycle_index"]: cycle["accent_color"] for cycle in cycles
    }
    keyframes: list[dict] = []
    for window in windows:
        normalized_envelope = min(
            1.0,
            window.get("envelope_amplitude", 0.0) / max_envelope,
        )
        normalized_peak = min(1.0, window.get("peak_amplitude", 0.0) / max_peak)
        cycle_index = window.get("cycle_index", 1)
        voice_pulses = []
        for lane in lanes:
            lane_energy = min(
                1.0,
                normalized_envelope
                * (
                    motion["lane_energy_base"]
                    + lane["amplitude_weight"] * motion["lane_energy_scale"]
                ),
            )
            center_y = lane["center_y"] + math.sin(
                window.get("clock_seconds", 0.0) * 1.7 + lane["part_index"]
            ) * motion["lane_wave_height_px"]
            voice_pulses.append(
                {
                    "lane_id": lane["lane_id"],
                    "part_index": lane["part_index"],
                    "channel": lane["channel"],
                    "color": lane["accent_color"],
                    "center_x": lane["center_x"],
                    "center_y": round(center_y, 2),
                    "radius_px": round(
                        motion["base_radius_px"] + lane_energy * motion["radius_range_px"],
                        2,
                    ),
                    "stroke_width_px": round(
                        motion["base_stroke_width_px"]
                        + normalized_peak * motion["stroke_width_range_px"],
                        2,
                    ),
                    "opacity": round(
                        motion["base_opacity"] + lane_energy * motion["opacity_range"],
                        3,
                    ),
                    "orbit_offset_px": round(
                        lane["stereo_bias"] * motion["lane_orbit_px"]
                        + math.cos(window.get("clock_seconds", 0.0) + lane["part_index"])
                        * motion["lane_orbit_wave_px"],
                        2,
                    ),
                }
            )

        keyframes.append(
            {
                "window_index": window.get("window_index"),
                "cycle_index": cycle_index,
                "clock_seconds": window.get("clock_seconds"),
                "clock_frame": window.get("clock_frame"),
                "start_seconds": window.get("start_seconds"),
                "end_seconds": window.get("end_seconds"),
                "peak_amplitude": window.get("peak_amplitude"),
                "rms_amplitude": window.get("rms_amplitude"),
                "envelope_amplitude": window.get("envelope_amplitude"),
                "normalized_envelope": round(normalized_envelope, 6),
                "normalized_peak": round(normalized_peak, 6),
                "background_color": scene_profile["palette"]["background_color"],
                "cycle_accent_color": cycle_color_by_index.get(
                    cycle_index,
                    colors[accent_sequence[0]],
                ),
                "grid_alpha": round(
                    motion["grid_alpha_base"] + normalized_envelope * motion["grid_alpha_range"],
                    3,
                ),
                "global_scale": round(
                    motion["base_scale"] + normalized_envelope * motion["envelope_scale_range"],
                    3,
                ),
                "rotation_degrees": round(
                    (
                        window.get("clock_seconds", 0.0)
                        * motion["rotation_degrees_per_second"]
                    )
                    % 360.0,
                    2,
                ),
                "voice_pulses": voice_pulses,
            }
        )
    return keyframes


def build_preview_svg(scene: dict) -> str:
    width = scene["canvas"]["width"]
    height = scene["canvas"]["height"]
    palette = scene["palette"]
    keyframes = scene["keyframes"]
    representative = keyframes[len(keyframes) // 2]
    title_area = scene["title_area"]
    footer_area = scene["footer_progress_area"]
    selector_block = scene["selector_label_sprites"]
    short_safe = scene["short_safe_layout"]
    spectrum = scene["spectrum_trails"]

    lane_circles: list[str] = []
    for pulse in representative["voice_pulses"]:
        lane_circles.append(
            "<circle "
            f"cx=\"{pulse['center_x']}\" cy=\"{pulse['center_y']}\" "
            f"r=\"{min(max(pulse['radius_px'], 68.0), 132.0)}\" "
            f"fill=\"none\" stroke=\"{pulse['color']}\" "
            f"stroke-width=\"{pulse['stroke_width_px']}\" "
            f"opacity=\"{pulse['opacity']}\" />"
        )

    spectrum_points = " ".join(
        f"{round(spectrum['x'] + index * (spectrum['width'] / max(1, spectrum['sampled_point_count'] - 1)), 2)},"
        f"{point['trail_y_px']}"
        for index, point in enumerate(spectrum["sampled_points"])
    )
    spectrum_circles = [
        "<circle "
        f"cx=\"{round(spectrum['x'] + index * (spectrum['width'] / max(1, spectrum['sampled_point_count'] - 1)), 2)}\" "
        f"cy=\"{point['trail_y_px']}\" "
        f"r=\"{round(point['stroke_width_px'], 2)}\" "
        f"fill=\"{representative['cycle_accent_color']}\" "
        f"opacity=\"{point['alpha']}\" />"
        for index, point in enumerate(spectrum["sampled_points"])
    ]

    title_lines: list[str] = []
    baseline = title_area["y"] + title_area["base_font_size_px"]
    for index, line in enumerate(title_area["text_lines"]):
        title_lines.append(
            f"<text x=\"{title_area['x'] + title_area['width'] / 2}\" "
            f"y=\"{baseline + index * (title_area['base_font_size_px'] + title_area['line_gap_px'])}\" "
            f"font-size=\"{title_area['base_font_size_px']}\" "
            f"text-anchor=\"middle\" "
            f"fill=\"{palette['text_color']}\">{escape(line)}</text>"
        )

    selector_rects: list[str] = []
    for sprite in selector_block["sprites"]:
        selector_rects.append(
            "<rect "
            f"x=\"{sprite['x']}\" y=\"{sprite['y']}\" "
            f"width=\"{sprite['width']}\" height=\"{sprite['height']}\" "
            f"rx=\"10\" fill=\"{palette['panel_color']}\" "
            f"stroke=\"{sprite['accent_color']}\" stroke-width=\"1.5\" opacity=\"0.92\" />"
        )
        selector_rects.append(
            f"<text x=\"{round(sprite['x'] + sprite['width'] / 2, 2)}\" "
            f"y=\"{round(sprite['y'] + sprite['height'] / 2 + sprite['font_size_px'] / 3, 2)}\" "
            f"font-size=\"{sprite['font_size_px']}\" text-anchor=\"middle\" "
            f"fill=\"{palette['text_color']}\">{escape(sprite['text'])}</text>"
        )

    lines = [
        f"<svg xmlns=\"http://www.w3.org/2000/svg\" width=\"{width}\" height=\"{height}\" viewBox=\"0 0 {width} {height}\">",
        f"<rect width=\"{width}\" height=\"{height}\" fill=\"{palette['background_color']}\" />",
        f"<rect x=\"48\" y=\"48\" width=\"{width - 96}\" height=\"{height - 96}\" rx=\"24\" fill=\"{palette['panel_color']}\" stroke=\"{palette['grid_color']}\" stroke-width=\"2\" />",
        f"<text x=\"80\" y=\"104\" font-size=\"28\" fill=\"{palette['text_color']}\">{escape(scene['preview']['title'])}</text>",
        f"<rect x=\"{short_safe['x']}\" y=\"{short_safe['y']}\" width=\"{short_safe['width']}\" height=\"{short_safe['height']}\" fill=\"none\" stroke=\"{palette['grid_color']}\" stroke-width=\"2\" stroke-dasharray=\"8 8\" opacity=\"0.75\" />",
        *title_lines,
        f"<text x=\"{width / 2}\" y=\"{footer_area['y'] + footer_area['font_size_px']}\" font-size=\"{footer_area['font_size_px']}\" text-anchor=\"middle\" fill=\"{palette['text_color']}\">{escape(footer_area['text'])}</text>",
        f"<text x=\"80\" y=\"146\" font-size=\"18\" fill=\"{palette['text_color']}\">profile: {escape(scene['visual_scene_profile_id'])}</text>",
        f"<text x=\"80\" y=\"176\" font-size=\"18\" fill=\"{palette['text_color']}\">source: {escape(scene['input_summary']['source_artifact_dir'])}</text>",
        f"<text x=\"80\" y=\"206\" font-size=\"18\" fill=\"{palette['text_color']}\">selection: {escape(scene['text_overrides']['source_path'])}</text>",
        *lane_circles,
        f"<rect x=\"{spectrum['x']}\" y=\"{spectrum['y']}\" width=\"{spectrum['width']}\" height=\"{spectrum['height']}\" rx=\"14\" fill=\"none\" stroke=\"{palette['grid_color']}\" stroke-width=\"1.5\" opacity=\"0.65\" />",
        f"<polyline fill=\"none\" stroke=\"{representative['cycle_accent_color']}\" stroke-width=\"3\" points=\"{spectrum_points}\" opacity=\"0.85\" />",
        *spectrum_circles,
        *selector_rects,
        "</svg>",
    ]
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Build stage6 analyzer-to-video stub artifacts from stage5 runtime outputs."
    )
    parser.add_argument(
        "source_artifact_dir",
        nargs="?",
        default="ops/out/stream-demo",
        help="stage5 artifact directory containing analyzer and routing outputs",
    )
    parser.add_argument(
        "output_dir",
        nargs="?",
        default="ops/out/video-stub",
        help="directory where stage6 stub artifacts will be written",
    )
    parser.add_argument(
        "--scene-profile",
        default=str(DEFAULT_SCENE_PROFILE_PATH),
        help="visual scene profile JSON path",
    )
    parser.add_argument(
        "--text-config",
        help="optional TOML file overriding stage6 text_overrides title source",
    )
    parser.add_argument("--width", type=int, help="override profile canvas width")
    parser.add_argument("--height", type=int, help="override profile canvas height")
    parser.add_argument("--fps", type=int, help="override profile frame rate")
    args = parser.parse_args()

    source_dir = Path(args.source_artifact_dir).resolve()
    output_dir = Path(args.output_dir).resolve()
    scene_profile_path = Path(args.scene_profile).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    if not source_dir.exists():
        raise SystemExit(f"source artifact directory does not exist: {source_dir}")

    source_files = {path.name for path in source_dir.iterdir() if path.is_file()}
    missing_files = sorted(REQUIRED_INPUT_FILES - source_files)
    if missing_files:
        raise SystemExit(
            "source artifact directory is missing required stage5 files: "
            + ", ".join(missing_files)
        )

    analysis = load_json(source_dir / "analysis_window_sequence.json")
    stream_plan = load_json(source_dir / "stream_loop_plan.json")
    synth_profile = load_json(source_dir / "synth_routing_profile.json")
    artifact_summary = load_json(source_dir / "artifact_summary.json")
    realized_fragments = load_json(source_dir / "realized_fragment_sequence.json")

    if analysis.get("work_id") != stream_plan.get("work_id"):
        raise SystemExit("work_id mismatch between analysis_window_sequence.json and stream_loop_plan.json")
    if stream_plan.get("synth_routing_profile_id") != synth_profile.get("profile_id"):
        raise SystemExit("synth routing profile mismatch between stream loop plan and synth profile")
    if realized_fragments.get("work_id") != stream_plan.get("work_id"):
        raise SystemExit(
            "work_id mismatch between realized_fragment_sequence.json and stream_loop_plan.json"
        )
    if not analysis.get("windows"):
        raise SystemExit("analysis_window_sequence.json must contain at least one analyzer window")
    if not synth_profile.get("voice_groups"):
        raise SystemExit("synth_routing_profile.json must contain at least one voice group")
    selection = artifact_summary.get("selection")
    if not isinstance(selection, dict):
        raise SystemExit("artifact_summary.json must contain selection metadata from stage5 unique scheduler")
    if len(selection.get("selector_results", [])) != 16:
        raise SystemExit("artifact_summary.json selection.selector_results must contain 16 entries")

    scene_profile = resolve_scene_profile(
        scene_profile_path,
        width_override=args.width,
        height_override=args.height,
        fps_override=args.fps,
    )
    title_text = resolve_title_text(
        scene_profile,
        Path(args.text_config).resolve() if args.text_config else None,
    )
    lanes = build_lane_layout(synth_profile, scene_profile=scene_profile)
    cycles = build_cycles(
        stream_plan,
        analysis.get("windows", []),
        scene_profile=scene_profile,
    )
    if not cycles:
        raise SystemExit("stream_loop_plan.json must contain at least one cycle")
    keyframes = build_keyframes(
        analysis,
        cycles,
        lanes,
        scene_profile=scene_profile,
    )
    fragment_timeline = build_fragment_timeline(realized_fragments, cycles)
    title_area = build_title_area(scene_profile, title_text)
    footer_progress_area = build_footer_progress_area(scene_profile, selection)
    selector_label_sprites = build_selector_label_sprites(
        scene_profile=scene_profile,
        selection=selection,
        fragment_timeline=fragment_timeline,
    )
    spectrum_trails = build_spectrum_trails(
        scene_profile,
        keyframes,
        preview_limit=scene_profile["preview"]["sampled_window_limit"],
    )
    text_overrides = build_text_overrides_scene_block(scene_profile, title_text)

    scene = {
        "stage": "stage6_video_stub",
        "work_id": analysis.get("work_id"),
        "source_stage": "stage5_m1_runtime",
        "visual_scene_profile_id": scene_profile["profile_id"],
        "visual_scene_profile_source": scene_profile["source"],
        "visual_scene_profile_path": scene_profile["source_path"],
        "canvas": {
            "width": scene_profile["canvas"]["width"],
            "height": scene_profile["canvas"]["height"],
            "fps": scene_profile["canvas"]["fps"],
            "background_color": scene_profile["palette"]["background_color"],
        },
        "palette": scene_profile["palette"],
        "motion": scene_profile["motion"],
        "preview": scene_profile["preview"],
        "title_area": title_area,
        "footer_progress_area": footer_progress_area,
        "selector_label_sprites": selector_label_sprites,
        "spectrum_trails": spectrum_trails,
        "short_safe_layout": scene_profile["short_safe_layout"],
        "text_overrides": text_overrides,
        "input_summary": {
            "source_artifact_dir": str(source_dir),
            "render_backend": analysis.get("render_backend"),
            "soundfont_source": analysis.get("soundfont_source"),
            "loop_count": analysis.get("loop_count"),
            "analysis_window_count": len(analysis.get("windows", [])),
            "synth_routing_profile_id": synth_profile.get("profile_id"),
            "visual_scene_profile_id": scene_profile["profile_id"],
            "audio_duration_seconds": artifact_summary.get("audio_duration_seconds"),
        },
        "lane_layout": lanes,
        "cycles": cycles,
        "fragment_timeline": fragment_timeline,
        "keyframes": keyframes,
        "summary": {
            "window_count": len(keyframes),
            "cycle_count": len(cycles),
            "lane_count": len(lanes),
            "selector_label_count": selector_label_sprites["sprite_count"],
            "title_line_count": title_area["line_count"],
            "total_duration_seconds": analysis.get("total_duration_seconds"),
            "sample_rate": analysis.get("sample_rate"),
            "window_size_frames": analysis.get("window_size_frames"),
            "hop_size_frames": analysis.get("hop_size_frames"),
            "max_envelope_amplitude": round(
                max(
                    (frame.get("envelope_amplitude", 0.0) for frame in keyframes),
                    default=0.0,
                ),
                6,
            ),
            "average_envelope_amplitude": round(
                sum(frame.get("envelope_amplitude", 0.0) for frame in keyframes)
                / max(len(keyframes), 1),
                6,
            ),
        },
    }

    manifest = {
        "stage": "stage6_video_stub",
        "description": "Analyzer-to-video stub derived from stage5 runtime artifacts.",
        "work_id": scene["work_id"],
        "source_artifact_dir": str(source_dir),
        "visual_scene_profile_id": scene_profile["profile_id"],
        "visual_scene_profile_source": scene_profile["source"],
        "visual_scene_profile_path": scene_profile["source_path"],
        "input_files": sorted(REQUIRED_INPUT_FILES),
        "artifacts": {
            "visual_scene_profile_file": "visual_scene_profile.json",
            "scene_file": "video_stub_scene.json",
            "preview_file": "video_stub_preview.svg",
            "validation_report_file": "stage6_validation_report.json",
        },
        "generation_summary": {
            "window_count": scene["summary"]["window_count"],
            "cycle_count": scene["summary"]["cycle_count"],
            "lane_count": scene["summary"]["lane_count"],
            "selector_label_count": scene["summary"]["selector_label_count"],
            "title_line_count": scene["summary"]["title_line_count"],
            "total_duration_seconds": scene["summary"]["total_duration_seconds"],
            "canvas": f"{scene['canvas']['width']}x{scene['canvas']['height']}",
            "fps": scene["canvas"]["fps"],
            "motion_mode": scene["motion"]["mode"],
            "palette_id": scene["palette"]["palette_id"],
        },
    }

    write_json(output_dir / "visual_scene_profile.json", scene_profile)
    write_json(output_dir / "video_stub_scene.json", scene)
    write_json(output_dir / "video_stub_manifest.json", manifest)
    (output_dir / "video_stub_preview.svg").write_text(
        build_preview_svg(scene),
        encoding="utf-8",
    )

    print("stage6 video stub built")
    print(f"source_artifact_dir: {source_dir}")
    print(f"output_dir: {output_dir}")
    print(f"scene_profile_file: {output_dir / 'visual_scene_profile.json'}")
    print(f"scene_file: {output_dir / 'video_stub_scene.json'}")
    print(f"preview_file: {output_dir / 'video_stub_preview.svg'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
