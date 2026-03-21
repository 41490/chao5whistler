#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path


REQUIRED_INPUT_FILES = {
    "analysis_window_sequence.json",
    "stream_loop_plan.json",
    "synth_routing_profile.json",
    "artifact_summary.json",
}

SOLARIZED_DARK = {
    "base03": "#002b36",
    "base02": "#073642",
    "base01": "#586e75",
    "base00": "#657b83",
    "base0": "#839496",
    "base1": "#93a1a1",
    "yellow": "#b58900",
    "orange": "#cb4b16",
    "red": "#dc322f",
    "magenta": "#d33682",
    "violet": "#6c71c4",
    "blue": "#268bd2",
    "cyan": "#2aa198",
    "green": "#859900",
}

CYCLE_ACCENTS = [
    "blue",
    "cyan",
    "green",
    "yellow",
    "orange",
    "magenta",
    "violet",
    "red",
]


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


def build_lane_layout(
    synth_profile: dict,
    width: int,
    height: int,
) -> list[dict]:
    voice_groups = synth_profile.get("voice_groups", [])
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
        accent_name = CYCLE_ACCENTS[(index - 1) % len(CYCLE_ACCENTS)]
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
                "center_y": round(height * 0.46 + stereo_bias * height * 0.08, 2),
                "left_gain": group.get("left_gain"),
                "right_gain": group.get("right_gain"),
                "accent_name": accent_name,
                "accent_color": SOLARIZED_DARK[accent_name],
            }
        )
    return lanes


def build_cycles(stream_plan: dict, analysis_windows: list[dict]) -> list[dict]:
    cycles: list[dict] = []
    for cycle in stream_plan.get("cycles", []):
        cycle_windows = [
            window
            for window in analysis_windows
            if window.get("cycle_index") == cycle.get("cycle_index")
        ]
        accent_name = CYCLE_ACCENTS[(cycle["cycle_index"] - 1) % len(CYCLE_ACCENTS)]
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
                "accent_color": SOLARIZED_DARK[accent_name],
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
) -> list[dict]:
    windows = analysis.get("windows", [])
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
                normalized_envelope * (0.75 + lane["amplitude_weight"] * 0.5),
            )
            center_y = lane["center_y"] + math.sin(
                window.get("clock_seconds", 0.0) * 1.7 + lane["part_index"]
            ) * 12.0
            voice_pulses.append(
                {
                    "lane_id": lane["lane_id"],
                    "part_index": lane["part_index"],
                    "channel": lane["channel"],
                    "color": lane["accent_color"],
                    "center_x": lane["center_x"],
                    "center_y": round(center_y, 2),
                    "radius_px": round(72.0 + lane_energy * 210.0, 2),
                    "stroke_width_px": round(2.0 + normalized_peak * 6.0, 2),
                    "opacity": round(0.28 + lane_energy * 0.55, 3),
                    "orbit_offset_px": round(
                        lane["stereo_bias"] * 42.0
                        + math.cos(window.get("clock_seconds", 0.0) + lane["part_index"]) * 8.0,
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
                "background_color": SOLARIZED_DARK["base03"],
                "cycle_accent_color": cycle_color_by_index.get(
                    cycle_index,
                    SOLARIZED_DARK["blue"],
                ),
                "grid_alpha": round(0.08 + normalized_envelope * 0.18, 3),
                "global_scale": round(0.65 + normalized_envelope * 0.7, 3),
                "rotation_degrees": round(
                    (window.get("clock_seconds", 0.0) * 24.0) % 360.0,
                    2,
                ),
                "voice_pulses": voice_pulses,
            }
        )
    return keyframes


def build_preview_svg(scene: dict) -> str:
    width = scene["canvas"]["width"]
    height = scene["canvas"]["height"]
    palette = scene["palette"]["colors"]
    keyframes = scene["keyframes"]
    preview_keyframes = sample_items(keyframes, limit=180)
    representative = keyframes[len(keyframes) // 2]
    chart_x = 80
    chart_y = 400
    chart_width = width - 160
    chart_height = 220

    bar_width = max(2.0, chart_width / max(1, len(preview_keyframes)))
    envelope_points: list[str] = []
    bars: list[str] = []
    for index, keyframe in enumerate(preview_keyframes):
        x = chart_x + index * bar_width
        envelope_height = keyframe["normalized_envelope"] * (chart_height - 24)
        y = chart_y + chart_height - envelope_height
        envelope_points.append(f"{round(x + bar_width / 2, 2)},{round(y, 2)}")
        bars.append(
            "<rect "
            f"x=\"{round(x, 2)}\" "
            f"y=\"{round(y, 2)}\" "
            f"width=\"{round(max(1.0, bar_width - 1.0), 2)}\" "
            f"height=\"{round(envelope_height, 2)}\" "
            f"fill=\"{keyframe['cycle_accent_color']}\" "
            "opacity=\"0.82\" />"
        )

    cycle_markers: list[str] = []
    for cycle in scene["cycles"]:
        position = chart_x + (
            cycle["start_seconds"] / max(scene["summary"]["total_duration_seconds"], 1e-9)
        ) * chart_width
        cycle_markers.append(
            f"<line x1=\"{round(position, 2)}\" y1=\"{chart_y}\" "
            f"x2=\"{round(position, 2)}\" y2=\"{chart_y + chart_height}\" "
            f"stroke=\"{palette['base01']}\" stroke-width=\"1\" stroke-dasharray=\"4 8\" />"
        )
        cycle_markers.append(
            f"<text x=\"{round(position + 8, 2)}\" y=\"{chart_y - 12}\" "
            f"font-size=\"18\" fill=\"{cycle['accent_color']}\">cycle {cycle['cycle_index']}</text>"
        )

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

    lines = [
        f"<svg xmlns=\"http://www.w3.org/2000/svg\" width=\"{width}\" height=\"{height}\" viewBox=\"0 0 {width} {height}\">",
        f"<rect width=\"{width}\" height=\"{height}\" fill=\"{palette['base03']}\" />",
        f"<rect x=\"48\" y=\"48\" width=\"{width - 96}\" height=\"{height - 96}\" rx=\"24\" fill=\"{palette['base02']}\" stroke=\"{palette['base01']}\" stroke-width=\"2\" />",
        f"<text x=\"80\" y=\"104\" font-size=\"34\" fill=\"{palette['base1']}\">musikalisches stage6 video stub preview</text>",
        f"<text x=\"80\" y=\"140\" font-size=\"18\" fill=\"{palette['base0']}\">palette: solarized_dark | motion: {scene['motion']['mode']} | keyframes: {scene['summary']['window_count']}</text>",
        f"<text x=\"80\" y=\"176\" font-size=\"18\" fill=\"{palette['base0']}\">source: {scene['input_summary']['source_artifact_dir']}</text>",
        f"<text x=\"80\" y=\"240\" font-size=\"20\" fill=\"{palette['cyan']}\">representative pulse geometry</text>",
        *lane_circles,
        f"<rect x=\"{chart_x}\" y=\"{chart_y}\" width=\"{chart_width}\" height=\"{chart_height}\" rx=\"14\" fill=\"{palette['base03']}\" stroke=\"{palette['base01']}\" stroke-width=\"1.5\" />",
        *cycle_markers,
        *bars,
        f"<polyline fill=\"none\" stroke=\"{palette['base1']}\" stroke-width=\"2.5\" points=\"{' '.join(envelope_points)}\" />",
        f"<text x=\"{chart_x}\" y=\"{chart_y + chart_height + 34}\" font-size=\"18\" fill=\"{palette['base0']}\">sampled analyzer envelope over time</text>",
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
    parser.add_argument("--width", type=int, default=1280, help="preview canvas width")
    parser.add_argument("--height", type=int, default=720, help="preview canvas height")
    parser.add_argument("--fps", type=int, default=30, help="target preview frame rate")
    args = parser.parse_args()

    source_dir = Path(args.source_artifact_dir).resolve()
    output_dir = Path(args.output_dir).resolve()
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

    if analysis.get("work_id") != stream_plan.get("work_id"):
        raise SystemExit("work_id mismatch between analysis_window_sequence.json and stream_loop_plan.json")
    if stream_plan.get("synth_routing_profile_id") != synth_profile.get("profile_id"):
        raise SystemExit("synth routing profile mismatch between stream loop plan and synth profile")
    if not analysis.get("windows"):
        raise SystemExit("analysis_window_sequence.json must contain at least one analyzer window")
    if not synth_profile.get("voice_groups"):
        raise SystemExit("synth_routing_profile.json must contain at least one voice group")

    lanes = build_lane_layout(synth_profile, width=args.width, height=args.height)
    cycles = build_cycles(stream_plan, analysis.get("windows", []))
    if not cycles:
        raise SystemExit("stream_loop_plan.json must contain at least one cycle")
    keyframes = build_keyframes(analysis, cycles, lanes)

    scene = {
        "stage": "stage6_video_stub",
        "work_id": analysis.get("work_id"),
        "source_stage": "stage5_m1_runtime",
        "canvas": {
            "width": args.width,
            "height": args.height,
            "fps": args.fps,
            "background_color": SOLARIZED_DARK["base03"],
        },
        "palette": {
            "palette_id": "solarized_dark",
            "colors": SOLARIZED_DARK,
        },
        "motion": {
            "mode": "dual_orbit_pulse",
            "clock_source": "analysis_window_sequence.clock_seconds",
            "keyframe_source": "one_keyframe_per_analysis_window",
        },
        "input_summary": {
            "source_artifact_dir": str(source_dir),
            "render_backend": analysis.get("render_backend"),
            "soundfont_source": analysis.get("soundfont_source"),
            "loop_count": analysis.get("loop_count"),
            "analysis_window_count": len(analysis.get("windows", [])),
            "synth_routing_profile_id": synth_profile.get("profile_id"),
            "audio_duration_seconds": artifact_summary.get("audio_duration_seconds"),
        },
        "lane_layout": lanes,
        "cycles": cycles,
        "keyframes": keyframes,
        "summary": {
            "window_count": len(keyframes),
            "cycle_count": len(cycles),
            "lane_count": len(lanes),
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
        "input_files": sorted(REQUIRED_INPUT_FILES),
        "artifacts": {
            "scene_file": "video_stub_scene.json",
            "preview_file": "video_stub_preview.svg",
            "validation_report_file": "stage6_validation_report.json",
        },
        "generation_summary": {
            "window_count": scene["summary"]["window_count"],
            "cycle_count": scene["summary"]["cycle_count"],
            "lane_count": scene["summary"]["lane_count"],
            "total_duration_seconds": scene["summary"]["total_duration_seconds"],
            "canvas": f"{args.width}x{args.height}",
            "fps": args.fps,
            "motion_mode": scene["motion"]["mode"],
        },
    }

    write_json(output_dir / "video_stub_scene.json", scene)
    write_json(output_dir / "video_stub_manifest.json", manifest)
    (output_dir / "video_stub_preview.svg").write_text(
        build_preview_svg(scene),
        encoding="utf-8",
    )

    print("stage6 video stub built")
    print(f"source_artifact_dir: {source_dir}")
    print(f"output_dir: {output_dir}")
    print(f"scene_file: {output_dir / 'video_stub_scene.json'}")
    print(f"preview_file: {output_dir / 'video_stub_preview.svg'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
