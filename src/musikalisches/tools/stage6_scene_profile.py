from __future__ import annotations

import json
import re
from pathlib import Path


DEFAULT_SCENE_PROFILE_PATH = (
    Path(__file__).resolve().parent.parent
    / "runtime"
    / "config"
    / "stage6_default_scene_profile.json"
)
SCENE_PROFILE_SCHEMA_PATH = (
    Path(__file__).resolve().parent.parent
    / "runtime"
    / "config"
    / "stage6_scene_profile.schema.json"
)

TOP_LEVEL_REQUIRED_KEYS = {
    "profile_id",
    "description",
    "canvas",
    "palette",
    "motion",
    "preview",
}
TOP_LEVEL_OPTIONAL_KEYS = {"source", "source_path"}
CANVAS_KEYS = {"width", "height", "fps"}
PALETTE_KEYS = {
    "palette_id",
    "background_color",
    "panel_color",
    "grid_color",
    "text_color",
    "accent_sequence",
    "colors",
}
MOTION_KEYS = {
    "mode",
    "clock_source",
    "keyframe_source",
    "rotation_degrees_per_second",
    "base_scale",
    "envelope_scale_range",
    "grid_alpha_base",
    "grid_alpha_range",
    "lane_center_y_ratio",
    "lane_bias_y_range_ratio",
    "lane_energy_base",
    "lane_energy_scale",
    "lane_wave_height_px",
    "lane_orbit_px",
    "lane_orbit_wave_px",
    "base_radius_px",
    "radius_range_px",
    "base_opacity",
    "opacity_range",
    "base_stroke_width_px",
    "stroke_width_range_px",
}
PREVIEW_KEYS = {
    "sampled_window_limit",
    "title",
    "geometry_label",
    "envelope_label",
}
HEX_COLOR_RE = re.compile(r"^#[0-9A-Fa-f]{6}$")


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _is_nonempty_string(value: object) -> bool:
    return isinstance(value, str) and value.strip() != ""


def _is_number(value: object) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _is_integer(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _check_exact_keys(
    payload: dict,
    *,
    label: str,
    required: set[str],
    optional: set[str] | None = None,
) -> list[str]:
    optional = optional or set()
    errors: list[str] = []
    keys = set(payload)
    missing = sorted(required - keys)
    unexpected = sorted(keys - required - optional)
    if missing:
        errors.append(f"{label} missing keys: {', '.join(missing)}")
    if unexpected:
        errors.append(f"{label} contains unexpected keys: {', '.join(unexpected)}")
    return errors


def validate_scene_profile_payload(
    profile: object,
    *,
    allow_output_metadata: bool = True,
) -> list[str]:
    if not isinstance(profile, dict):
        return ["scene profile root must be a JSON object"]

    errors: list[str] = []
    errors.extend(
        _check_exact_keys(
            profile,
            label="scene profile",
            required=TOP_LEVEL_REQUIRED_KEYS,
            optional=TOP_LEVEL_OPTIONAL_KEYS if allow_output_metadata else set(),
        )
    )

    profile_id = profile.get("profile_id")
    if not _is_nonempty_string(profile_id):
        errors.append("scene profile profile_id must be a non-empty string")

    description = profile.get("description")
    if not _is_nonempty_string(description):
        errors.append("scene profile description must be a non-empty string")

    if "source" in profile or "source_path" in profile:
        if not allow_output_metadata:
            errors.append("scene profile source/source_path are not allowed in input profiles")
        else:
            source = profile.get("source")
            source_path = profile.get("source_path")
            if source not in {"repo_default", "cli"}:
                errors.append("scene profile source must be one of: repo_default, cli")
            if not _is_nonempty_string(source_path):
                errors.append("scene profile source_path must be a non-empty string")

    canvas = profile.get("canvas")
    if not isinstance(canvas, dict):
        errors.append("scene profile canvas must be an object")
    else:
        errors.extend(_check_exact_keys(canvas, label="scene profile canvas", required=CANVAS_KEYS))
        width = canvas.get("width")
        if not _is_integer(width) or width < 320:
            errors.append("scene profile canvas.width must be an integer >= 320")
        height = canvas.get("height")
        if not _is_integer(height) or height < 240:
            errors.append("scene profile canvas.height must be an integer >= 240")
        fps = canvas.get("fps")
        if not _is_integer(fps) or not 1 <= fps <= 60:
            errors.append("scene profile canvas.fps must be an integer within 1..=60")

    palette = profile.get("palette")
    if not isinstance(palette, dict):
        errors.append("scene profile palette must be an object")
    else:
        errors.extend(_check_exact_keys(palette, label="scene profile palette", required=PALETTE_KEYS))
        if not _is_nonempty_string(palette.get("palette_id")):
            errors.append("scene profile palette.palette_id must be a non-empty string")
        for color_field in ("background_color", "panel_color", "grid_color", "text_color"):
            color_value = palette.get(color_field)
            if not isinstance(color_value, str) or not HEX_COLOR_RE.match(color_value):
                errors.append(f"scene profile palette.{color_field} must be a #RRGGBB color")

        colors = palette.get("colors")
        if not isinstance(colors, dict) or not colors:
            errors.append("scene profile palette.colors must be a non-empty object")
            colors = {}
        else:
            for color_name, color_value in colors.items():
                if not _is_nonempty_string(color_name):
                    errors.append("scene profile palette.colors keys must be non-empty strings")
                if not isinstance(color_value, str) or not HEX_COLOR_RE.match(color_value):
                    errors.append(
                        f"scene profile palette.colors.{color_name} must be a #RRGGBB color"
                    )

        accent_sequence = palette.get("accent_sequence")
        if not isinstance(accent_sequence, list) or not accent_sequence:
            errors.append("scene profile palette.accent_sequence must be a non-empty array")
        else:
            seen_accents: set[str] = set()
            for accent_name in accent_sequence:
                if not _is_nonempty_string(accent_name):
                    errors.append(
                        "scene profile palette.accent_sequence entries must be non-empty strings"
                    )
                    continue
                if accent_name in seen_accents:
                    errors.append(
                        f"scene profile palette.accent_sequence must not repeat '{accent_name}'"
                    )
                seen_accents.add(accent_name)
                if accent_name not in colors:
                    errors.append(
                        f"scene profile palette.accent_sequence references missing color '{accent_name}'"
                    )

    motion = profile.get("motion")
    if not isinstance(motion, dict):
        errors.append("scene profile motion must be an object")
    else:
        errors.extend(_check_exact_keys(motion, label="scene profile motion", required=MOTION_KEYS))
        for text_field in ("mode", "clock_source", "keyframe_source"):
            if not _is_nonempty_string(motion.get(text_field)):
                errors.append(f"scene profile motion.{text_field} must be a non-empty string")

        positive_number_fields = {
            "rotation_degrees_per_second",
            "base_scale",
            "base_radius_px",
            "base_stroke_width_px",
        }
        nonnegative_number_fields = {
            "envelope_scale_range",
            "lane_energy_base",
            "lane_energy_scale",
            "lane_wave_height_px",
            "lane_orbit_px",
            "lane_orbit_wave_px",
            "radius_range_px",
            "stroke_width_range_px",
        }
        ratio_fields = {
            "grid_alpha_base",
            "grid_alpha_range",
            "lane_center_y_ratio",
            "lane_bias_y_range_ratio",
            "base_opacity",
            "opacity_range",
        }

        for field_name in positive_number_fields:
            value = motion.get(field_name)
            if not _is_number(value) or value <= 0:
                errors.append(f"scene profile motion.{field_name} must be > 0")
        for field_name in nonnegative_number_fields:
            value = motion.get(field_name)
            if not _is_number(value) or value < 0:
                errors.append(f"scene profile motion.{field_name} must be >= 0")
        for field_name in ratio_fields:
            value = motion.get(field_name)
            if not _is_number(value) or not 0.0 <= value <= 1.0:
                errors.append(f"scene profile motion.{field_name} must be within 0.0..=1.0")

        if (
            _is_number(motion.get("grid_alpha_base"))
            and _is_number(motion.get("grid_alpha_range"))
            and motion["grid_alpha_base"] + motion["grid_alpha_range"] > 1.0
        ):
            errors.append(
                "scene profile motion.grid_alpha_base + grid_alpha_range must be <= 1.0"
            )
        if (
            _is_number(motion.get("base_opacity"))
            and _is_number(motion.get("opacity_range"))
            and motion["base_opacity"] + motion["opacity_range"] > 1.0
        ):
            errors.append("scene profile motion.base_opacity + opacity_range must be <= 1.0")

    preview = profile.get("preview")
    if not isinstance(preview, dict):
        errors.append("scene profile preview must be an object")
    else:
        errors.extend(_check_exact_keys(preview, label="scene profile preview", required=PREVIEW_KEYS))
        sampled_window_limit = preview.get("sampled_window_limit")
        if not _is_integer(sampled_window_limit) or sampled_window_limit <= 0:
            errors.append("scene profile preview.sampled_window_limit must be an integer > 0")
        for text_field in ("title", "geometry_label", "envelope_label"):
            if not _is_nonempty_string(preview.get(text_field)):
                errors.append(f"scene profile preview.{text_field} must be a non-empty string")

    return errors
