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
    "title_area",
    "footer_progress_area",
    "selector_label_sprites",
    "spectrum_trails",
    "short_safe_layout",
    "text_overrides",
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
TITLE_AREA_KEYS = {
    "x",
    "y",
    "width",
    "height",
    "max_lines",
    "layout_strategy",
    "text_align",
    "base_font_size_px",
    "line_gap_px",
}
FOOTER_PROGRESS_AREA_KEYS = {
    "x",
    "y",
    "width",
    "height",
    "format_template",
    "text_align",
    "font_size_px",
}
SELECTOR_LABEL_SPRITES_KEYS = {
    "x",
    "y",
    "width",
    "height",
    "random_seed_source",
    "label_min_font_size_px",
    "label_max_font_size_px",
    "label_padding_px",
    "idle_drift_px",
    "idle_rotation_degrees",
    "active_bounce_y_px",
    "active_scale_multiplier",
}
SPECTRUM_TRAILS_KEYS = {
    "x",
    "y",
    "width",
    "height",
    "trail_count",
    "envelope_floor",
    "envelope_ceiling",
    "stroke_min_width_px",
    "stroke_max_width_px",
    "alpha_base",
    "alpha_range",
}
SHORT_SAFE_LAYOUT_KEYS = {
    "x",
    "y",
    "width",
    "height",
    "target_aspect_ratio",
}
TEXT_OVERRIDES_KEYS = {
    "default_toml_path",
    "toml_section",
    "title_key",
    "newline_mode",
    "horizontal_alignment",
    "max_title_lines",
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


def _check_rect_bounds(
    payload: dict,
    *,
    label: str,
    canvas_width: int,
    canvas_height: int,
) -> list[str]:
    errors: list[str] = []
    for field_name in ("x", "y", "width", "height"):
        value = payload.get(field_name)
        if not _is_integer(value):
            errors.append(f"{label}.{field_name} must be an integer")
    if errors:
        return errors

    if payload["x"] < 0 or payload["y"] < 0:
        errors.append(f"{label}.x and {label}.y must be >= 0")
    if payload["width"] <= 0 or payload["height"] <= 0:
        errors.append(f"{label}.width and {label}.height must be > 0")
    if payload["x"] + payload["width"] > canvas_width:
        errors.append(f"{label} must fit within canvas width {canvas_width}")
    if payload["y"] + payload["height"] > canvas_height:
        errors.append(f"{label} must fit within canvas height {canvas_height}")
    return errors


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
    canvas_width: int | None = None
    canvas_height: int | None = None
    if not isinstance(canvas, dict):
        errors.append("scene profile canvas must be an object")
    else:
        errors.extend(_check_exact_keys(canvas, label="scene profile canvas", required=CANVAS_KEYS))
        width = canvas.get("width")
        if not _is_integer(width) or width < 320:
            errors.append("scene profile canvas.width must be an integer >= 320")
        else:
            canvas_width = width
        height = canvas.get("height")
        if not _is_integer(height) or height < 240:
            errors.append("scene profile canvas.height must be an integer >= 240")
        else:
            canvas_height = height
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

    title_area = profile.get("title_area")
    if not isinstance(title_area, dict):
        errors.append("scene profile title_area must be an object")
    else:
        errors.extend(
            _check_exact_keys(title_area, label="scene profile title_area", required=TITLE_AREA_KEYS)
        )
        if canvas_width is not None and canvas_height is not None:
            errors.extend(
                _check_rect_bounds(
                    title_area,
                    label="scene profile title_area",
                    canvas_width=canvas_width,
                    canvas_height=canvas_height,
                )
            )
        max_lines = title_area.get("max_lines")
        if not _is_integer(max_lines) or not 1 <= max_lines <= 2:
            errors.append("scene profile title_area.max_lines must be 1 or 2")
        if title_area.get("layout_strategy") != "explicit_newlines_centered":
            errors.append(
                "scene profile title_area.layout_strategy must be explicit_newlines_centered"
            )
        if title_area.get("text_align") != "center":
            errors.append("scene profile title_area.text_align must be center")
        for field_name in ("base_font_size_px", "line_gap_px"):
            value = title_area.get(field_name)
            if not _is_integer(value) or value < 0:
                errors.append(f"scene profile title_area.{field_name} must be an integer >= 0")
        if _is_integer(title_area.get("base_font_size_px")) and title_area["base_font_size_px"] <= 0:
            errors.append("scene profile title_area.base_font_size_px must be > 0")

    footer_progress_area = profile.get("footer_progress_area")
    if not isinstance(footer_progress_area, dict):
        errors.append("scene profile footer_progress_area must be an object")
    else:
        errors.extend(
            _check_exact_keys(
                footer_progress_area,
                label="scene profile footer_progress_area",
                required=FOOTER_PROGRESS_AREA_KEYS,
            )
        )
        if canvas_width is not None and canvas_height is not None:
            errors.extend(
                _check_rect_bounds(
                    footer_progress_area,
                    label="scene profile footer_progress_area",
                    canvas_width=canvas_width,
                    canvas_height=canvas_height,
                )
            )
        if footer_progress_area.get("text_align") != "center":
            errors.append("scene profile footer_progress_area.text_align must be center")
        format_template = footer_progress_area.get("format_template")
        if not _is_nonempty_string(format_template):
            errors.append(
                "scene profile footer_progress_area.format_template must be a non-empty string"
            )
        else:
            for placeholder in ("{played_unique_count}", "{total_combinations}"):
                if placeholder not in format_template:
                    errors.append(
                        "scene profile footer_progress_area.format_template must include "
                        "{played_unique_count} and {total_combinations}"
                    )
                    break
        font_size_px = footer_progress_area.get("font_size_px")
        if not _is_integer(font_size_px) or font_size_px <= 0:
            errors.append("scene profile footer_progress_area.font_size_px must be an integer > 0")

    selector_label_sprites = profile.get("selector_label_sprites")
    if not isinstance(selector_label_sprites, dict):
        errors.append("scene profile selector_label_sprites must be an object")
    else:
        errors.extend(
            _check_exact_keys(
                selector_label_sprites,
                label="scene profile selector_label_sprites",
                required=SELECTOR_LABEL_SPRITES_KEYS,
            )
        )
        if canvas_width is not None and canvas_height is not None:
            errors.extend(
                _check_rect_bounds(
                    selector_label_sprites,
                    label="scene profile selector_label_sprites",
                    canvas_width=canvas_width,
                    canvas_height=canvas_height,
                )
            )
        if selector_label_sprites.get("random_seed_source") != "selection.combination_id":
            errors.append(
                "scene profile selector_label_sprites.random_seed_source must be selection.combination_id"
            )
        for field_name in (
            "label_min_font_size_px",
            "label_max_font_size_px",
            "label_padding_px",
            "idle_drift_px",
            "idle_rotation_degrees",
            "active_bounce_y_px",
        ):
            value = selector_label_sprites.get(field_name)
            if not _is_integer(value) or value < 0:
                errors.append(
                    f"scene profile selector_label_sprites.{field_name} must be an integer >= 0"
                )
        if (
            _is_integer(selector_label_sprites.get("label_min_font_size_px"))
            and _is_integer(selector_label_sprites.get("label_max_font_size_px"))
            and selector_label_sprites["label_min_font_size_px"]
            > selector_label_sprites["label_max_font_size_px"]
        ):
            errors.append(
                "scene profile selector_label_sprites.label_min_font_size_px must be <= label_max_font_size_px"
            )
        active_scale_multiplier = selector_label_sprites.get("active_scale_multiplier")
        if not _is_number(active_scale_multiplier) or active_scale_multiplier < 1.0:
            errors.append(
                "scene profile selector_label_sprites.active_scale_multiplier must be >= 1.0"
            )

    spectrum_trails = profile.get("spectrum_trails")
    if not isinstance(spectrum_trails, dict):
        errors.append("scene profile spectrum_trails must be an object")
    else:
        errors.extend(
            _check_exact_keys(
                spectrum_trails,
                label="scene profile spectrum_trails",
                required=SPECTRUM_TRAILS_KEYS,
            )
        )
        if canvas_width is not None and canvas_height is not None:
            errors.extend(
                _check_rect_bounds(
                    spectrum_trails,
                    label="scene profile spectrum_trails",
                    canvas_width=canvas_width,
                    canvas_height=canvas_height,
                )
            )
        trail_count = spectrum_trails.get("trail_count")
        if not _is_integer(trail_count) or trail_count <= 0:
            errors.append("scene profile spectrum_trails.trail_count must be an integer > 0")
        envelope_floor = spectrum_trails.get("envelope_floor")
        envelope_ceiling = spectrum_trails.get("envelope_ceiling")
        if not _is_number(envelope_floor) or not 0.0 <= envelope_floor <= 1.0:
            errors.append("scene profile spectrum_trails.envelope_floor must be within 0.0..=1.0")
        if not _is_number(envelope_ceiling) or not 0.0 <= envelope_ceiling <= 1.0:
            errors.append("scene profile spectrum_trails.envelope_ceiling must be within 0.0..=1.0")
        if (
            _is_number(envelope_floor)
            and _is_number(envelope_ceiling)
            and envelope_floor >= envelope_ceiling
        ):
            errors.append(
                "scene profile spectrum_trails.envelope_floor must be < envelope_ceiling"
            )
        for field_name in ("stroke_min_width_px", "stroke_max_width_px"):
            value = spectrum_trails.get(field_name)
            if not _is_number(value) or value <= 0:
                errors.append(f"scene profile spectrum_trails.{field_name} must be > 0")
        if (
            _is_number(spectrum_trails.get("stroke_min_width_px"))
            and _is_number(spectrum_trails.get("stroke_max_width_px"))
            and spectrum_trails["stroke_min_width_px"] > spectrum_trails["stroke_max_width_px"]
        ):
            errors.append(
                "scene profile spectrum_trails.stroke_min_width_px must be <= stroke_max_width_px"
            )
        for field_name in ("alpha_base", "alpha_range"):
            value = spectrum_trails.get(field_name)
            if not _is_number(value) or not 0.0 <= value <= 1.0:
                errors.append(f"scene profile spectrum_trails.{field_name} must be within 0.0..=1.0")
        if (
            _is_number(spectrum_trails.get("alpha_base"))
            and _is_number(spectrum_trails.get("alpha_range"))
            and spectrum_trails["alpha_base"] + spectrum_trails["alpha_range"] > 1.0
        ):
            errors.append(
                "scene profile spectrum_trails.alpha_base + alpha_range must be <= 1.0"
            )

    short_safe_layout = profile.get("short_safe_layout")
    if not isinstance(short_safe_layout, dict):
        errors.append("scene profile short_safe_layout must be an object")
    else:
        errors.extend(
            _check_exact_keys(
                short_safe_layout,
                label="scene profile short_safe_layout",
                required=SHORT_SAFE_LAYOUT_KEYS,
            )
        )
        if canvas_width is not None and canvas_height is not None:
            errors.extend(
                _check_rect_bounds(
                    short_safe_layout,
                    label="scene profile short_safe_layout",
                    canvas_width=canvas_width,
                    canvas_height=canvas_height,
                )
            )
        if short_safe_layout.get("target_aspect_ratio") != "9:16":
            errors.append("scene profile short_safe_layout.target_aspect_ratio must be 9:16")

    text_overrides = profile.get("text_overrides")
    if not isinstance(text_overrides, dict):
        errors.append("scene profile text_overrides must be an object")
    else:
        errors.extend(
            _check_exact_keys(
                text_overrides,
                label="scene profile text_overrides",
                required=TEXT_OVERRIDES_KEYS,
            )
        )
        for field_name in ("default_toml_path", "toml_section", "title_key"):
            if not _is_nonempty_string(text_overrides.get(field_name)):
                errors.append(f"scene profile text_overrides.{field_name} must be a non-empty string")
        if text_overrides.get("newline_mode") != "escaped_or_literal_newline":
            errors.append(
                "scene profile text_overrides.newline_mode must be escaped_or_literal_newline"
            )
        if text_overrides.get("horizontal_alignment") != "center":
            errors.append("scene profile text_overrides.horizontal_alignment must be center")
        max_title_lines = text_overrides.get("max_title_lines")
        if not _is_integer(max_title_lines) or not 1 <= max_title_lines <= 2:
            errors.append("scene profile text_overrides.max_title_lines must be 1 or 2")

    return errors
