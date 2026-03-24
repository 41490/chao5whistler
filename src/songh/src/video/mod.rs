use std::fs;
use std::path::{Path, PathBuf};

use anyhow::{anyhow, bail, Context, Result};
use font8x8::{UnicodeFonts, BASIC_FONTS};
use image::{ImageBuffer, Rgba, RgbaImage};
use serde::Serialize;
use sha2::{Digest, Sha256};

use crate::config::schema::{Config, MotionMode};
use crate::replay;
use crate::text;

const BITMAP_GLYPH_WIDTH: u32 = 8;
const BITMAP_GLYPH_HEIGHT: u32 = 8;

#[derive(Debug, Clone, Serialize)]
pub struct VideoSampleReport {
    pub schema_version: String,
    pub archive_root: PathBuf,
    pub source_day: String,
    pub start_second: u32,
    pub duration_secs: u32,
    pub motion_mode: String,
    pub canvas_width: u32,
    pub canvas_height: u32,
    pub fps: u32,
    pub emitted_sprite_count: usize,
    pub sprites: Vec<VideoSpritePlan>,
    pub frames: Vec<VideoFrameSample>,
}

#[derive(Debug, Clone, Serialize)]
pub struct VideoRenderReport {
    pub schema_version: String,
    pub output_dir: PathBuf,
    pub frames_dir: PathBuf,
    pub frame_plan_path: PathBuf,
    pub manifest_path: PathBuf,
    pub rendered_frame_count: usize,
    pub frame_plan: VideoSampleReport,
}

#[derive(Debug, Clone, Serialize)]
pub struct VideoSpritePlan {
    pub event_id: String,
    pub label: String,
    pub source_day: String,
    pub second_of_day: u32,
    pub spawn_replay_second: u64,
    pub font_size: u32,
    pub angle_deg: f64,
    pub spawn_x: f64,
    pub spawn_y: f64,
    pub velocity_x: f64,
    pub velocity_y: f64,
    pub lifetime_secs: f64,
}

#[derive(Debug, Clone, Serialize)]
pub struct VideoFrameSample {
    pub frame_index: u64,
    pub frame_time_secs: f64,
    pub replay_second: u64,
    pub source_day: String,
    pub second_of_day: u32,
    pub active_items: Vec<VideoFrameItem>,
}

#[derive(Debug, Clone, Serialize)]
pub struct VideoFrameItem {
    pub event_id: String,
    pub label: String,
    pub x: f64,
    pub y: f64,
    pub alpha: u32,
    pub font_size: u32,
    pub angle_deg: f64,
}

pub fn sample_day_pack(
    config: &Config,
    day: &str,
    archive_root_override: Option<&Path>,
    start_second: u32,
    duration_secs: u32,
    motion_mode_override: Option<MotionMode>,
    angle_deg_override: Option<f64>,
) -> Result<VideoSampleReport> {
    if duration_secs == 0 || duration_secs > 30 {
        bail!("stage4 sample-video --duration-secs must be within 1..=30");
    }

    let mut effective_config = config.clone();
    if let Some(mode) = motion_mode_override {
        effective_config.video.motion.mode = mode;
    }
    if let Some(angle_deg) = angle_deg_override {
        effective_config.video.motion.angle_deg = angle_deg;
    }

    let replay_report = replay::dry_run_day_pack(
        &effective_config,
        day,
        archive_root_override,
        start_second,
        duration_secs,
    )?;
    let motion_mode = effective_config.video.motion.mode;
    let fps = effective_config.video.canvas.fps;

    let sprites = replay_report
        .ticks
        .iter()
        .flat_map(|tick| {
            tick.events.iter().map(|event| {
                VideoSpritePlan::from_runtime_event(
                    &effective_config,
                    motion_mode,
                    tick.replay_second,
                    tick.source_day.as_str(),
                    tick.second_of_day,
                    event,
                )
            })
        })
        .collect::<Result<Vec<_>>>()?;

    let total_frames = replay_report.duration_secs as u64 * fps as u64;
    let frames = (0..total_frames)
        .map(|frame_index| {
            let frame_time_secs = frame_index as f64 / fps as f64;
            let tick_index = frame_time_secs.floor() as usize;
            let tick = replay_report
                .ticks
                .get(tick_index)
                .ok_or_else(|| anyhow!("frame index {} exceeds replay ticks", frame_index))?;

            let active_items = sprites
                .iter()
                .filter_map(|sprite| sprite.sample_at(&effective_config, frame_time_secs))
                .collect::<Vec<_>>();

            Ok(VideoFrameSample {
                frame_index,
                frame_time_secs,
                replay_second: tick.replay_second,
                source_day: tick.source_day.clone(),
                second_of_day: tick.second_of_day,
                active_items,
            })
        })
        .collect::<Result<Vec<_>>>()?;

    Ok(VideoSampleReport {
        schema_version: "stage4.video_sample.v1".to_string(),
        archive_root: replay_report.archive_root,
        source_day: day.to_string(),
        start_second,
        duration_secs: replay_report.duration_secs,
        motion_mode: motion_mode.as_str().to_string(),
        canvas_width: effective_config.video.canvas.width,
        canvas_height: effective_config.video.canvas.height,
        fps,
        emitted_sprite_count: sprites.len(),
        sprites,
        frames,
    })
}

pub fn render_day_pack(
    config: &Config,
    day: &str,
    archive_root_override: Option<&Path>,
    output_dir: &Path,
    start_second: u32,
    duration_secs: u32,
    motion_mode_override: Option<MotionMode>,
    angle_deg_override: Option<f64>,
) -> Result<VideoRenderReport> {
    let frame_plan = sample_day_pack(
        config,
        day,
        archive_root_override,
        start_second,
        duration_secs,
        motion_mode_override,
        angle_deg_override,
    )?;
    fs::create_dir_all(output_dir)
        .with_context(|| format!("create stage4 render dir {}", output_dir.display()))?;
    let frames_dir = output_dir.join("frames");
    if frames_dir.exists() {
        fs::remove_dir_all(&frames_dir)
            .with_context(|| format!("clear stage4 render frames dir {}", frames_dir.display()))?;
    }
    fs::create_dir_all(&frames_dir)
        .with_context(|| format!("create stage4 render frames dir {}", frames_dir.display()))?;

    let frame_plan_path = output_dir.join("frame-plan.json");
    fs::write(&frame_plan_path, serde_json::to_vec_pretty(&frame_plan)?)
        .with_context(|| format!("write stage4 frame-plan {}", frame_plan_path.display()))?;

    for frame in &frame_plan.frames {
        let image = render_frame(config, &frame_plan, frame)?;
        let frame_path = frames_dir.join(format!("frame-{:06}.png", frame.frame_index));
        image
            .save(&frame_path)
            .with_context(|| format!("write rendered frame {}", frame_path.display()))?;
    }

    let manifest_path = output_dir.join("render-manifest.json");
    let report = VideoRenderReport {
        schema_version: "stage4.video_render.v1".to_string(),
        output_dir: output_dir.to_path_buf(),
        frames_dir,
        frame_plan_path,
        manifest_path: manifest_path.clone(),
        rendered_frame_count: frame_plan.frames.len(),
        frame_plan,
    };
    fs::write(&manifest_path, serde_json::to_vec_pretty(&report)?)
        .with_context(|| format!("write stage4 render manifest {}", manifest_path.display()))?;

    Ok(report)
}

impl VideoSpritePlan {
    fn from_runtime_event(
        config: &Config,
        motion_mode: MotionMode,
        spawn_replay_second: u64,
        source_day: &str,
        second_of_day: u32,
        event: &crate::model::runtime_event::RuntimeEvent,
    ) -> Result<Self> {
        let label = text::render_template(&config.text, &event.text_fields)?;
        let font_size = font_size_for_weight(
            config.video.text.font_size_min,
            config.video.text.font_size_max,
            event.weight,
        );
        let label_width = estimate_label_width(&label, font_size);
        let spawn_x = spawn_x(config, event, label_width);
        let spawn_y = spawn_y(config, event);
        let angle_deg = motion_angle_deg(config, motion_mode, event, spawn_replay_second);
        let angle_rad = angle_deg.to_radians();
        let speed = config.video.motion.speed_px_per_sec;
        let velocity_x = speed * angle_rad.sin();
        let velocity_y = -speed * angle_rad.cos();
        let lifetime_secs = lifetime_secs(
            config,
            spawn_x,
            spawn_y,
            label_width,
            estimate_label_height(font_size),
            velocity_x,
            velocity_y,
        );

        Ok(Self {
            event_id: event.event_id.clone(),
            label,
            source_day: source_day.to_string(),
            second_of_day,
            spawn_replay_second,
            font_size,
            angle_deg,
            spawn_x,
            spawn_y,
            velocity_x,
            velocity_y,
            lifetime_secs,
        })
    }

    fn sample_at(&self, config: &Config, frame_time_secs: f64) -> Option<VideoFrameItem> {
        let age_secs = frame_time_secs - self.spawn_replay_second as f64;
        if age_secs < 0.0 || age_secs > self.lifetime_secs {
            return None;
        }

        let x = self.spawn_x + self.velocity_x * age_secs;
        let y = self.spawn_y + self.velocity_y * age_secs;
        let fade = 1.0 - (age_secs / self.lifetime_secs);
        let alpha = ((config.video.text.initial_alpha as f64) * fade)
            .round()
            .clamp(0.0, 255.0) as u32;

        Some(VideoFrameItem {
            event_id: self.event_id.clone(),
            label: self.label.clone(),
            x: round2(x),
            y: round2(y),
            alpha,
            font_size: self.font_size,
            angle_deg: round2(self.angle_deg),
        })
    }
}

fn render_frame(
    config: &Config,
    frame_plan: &VideoSampleReport,
    frame: &VideoFrameSample,
) -> Result<RgbaImage> {
    let background = parse_hex_color(&config.video.palette.background_hex)?;
    let text_color = parse_hex_color(&config.video.palette.text_hex)?;
    let accent_color = parse_hex_color(&config.video.palette.accent_hex)?;
    let mut image = ImageBuffer::from_pixel(
        frame_plan.canvas_width,
        frame_plan.canvas_height,
        Rgba([background[0], background[1], background[2], 255]),
    );

    for item in &frame.active_items {
        draw_label(
            &mut image,
            item,
            text_color,
            accent_color,
            config.video.text.stroke_width,
        );
    }

    Ok(image)
}

fn draw_label(
    image: &mut RgbaImage,
    item: &VideoFrameItem,
    text_color: [u8; 3],
    accent_color: [u8; 3],
    stroke_width: u32,
) {
    let scale = bitmap_scale(item.font_size);
    let base_x = item.x.round() as i32;
    let base_y = item.y.round() as i32;
    let outline_alpha = item.alpha.min(180);

    if stroke_width > 0 {
        let outline_offsets = outline_offsets(scale, stroke_width);
        for (dx, dy) in outline_offsets {
            draw_bitmap_text(
                image,
                &item.label,
                base_x + dx,
                base_y + dy,
                scale,
                accent_color,
                outline_alpha,
            );
        }
    }

    draw_bitmap_text(
        image,
        &item.label,
        base_x,
        base_y,
        scale,
        text_color,
        item.alpha,
    );
}

fn draw_bitmap_text(
    image: &mut RgbaImage,
    label: &str,
    base_x: i32,
    base_y: i32,
    scale: u32,
    color: [u8; 3],
    alpha: u32,
) {
    let advance = (BITMAP_GLYPH_WIDTH * scale) as i32;
    for (index, ch) in label.chars().enumerate() {
        let glyph_x = base_x + index as i32 * advance;
        draw_bitmap_char(image, ch, glyph_x, base_y, scale, color, alpha);
    }
}

fn draw_bitmap_char(
    image: &mut RgbaImage,
    ch: char,
    base_x: i32,
    base_y: i32,
    scale: u32,
    color: [u8; 3],
    alpha: u32,
) {
    let fallback = BASIC_FONTS
        .get('?')
        .expect("font8x8 basic font must contain ?");
    let glyph = BASIC_FONTS.get(ch).unwrap_or(fallback);

    for (row, bits) in glyph.iter().enumerate() {
        for col in 0..BITMAP_GLYPH_WIDTH {
            if bits & (1u8 << col) == 0 {
                continue;
            }
            let pixel_x = base_x + col as i32 * scale as i32;
            let pixel_y = base_y + row as i32 * scale as i32;
            fill_rect(image, pixel_x, pixel_y, scale, scale, color, alpha);
        }
    }
}

fn fill_rect(
    image: &mut RgbaImage,
    x: i32,
    y: i32,
    width: u32,
    height: u32,
    color: [u8; 3],
    alpha: u32,
) {
    for dy in 0..height {
        for dx in 0..width {
            blend_pixel(
                image,
                x + dx as i32,
                y + dy as i32,
                [color[0], color[1], color[2], alpha.min(255) as u8],
            );
        }
    }
}

fn blend_pixel(image: &mut RgbaImage, x: i32, y: i32, top: [u8; 4]) {
    if x < 0 || y < 0 {
        return;
    }
    let Ok(x) = u32::try_from(x) else {
        return;
    };
    let Ok(y) = u32::try_from(y) else {
        return;
    };
    if x >= image.width() || y >= image.height() {
        return;
    }

    let bottom = image.get_pixel(x, y).0;
    let alpha = top[3] as f32 / 255.0;
    let inv_alpha = 1.0 - alpha;
    let blended = [
        (top[0] as f32 * alpha + bottom[0] as f32 * inv_alpha).round() as u8,
        (top[1] as f32 * alpha + bottom[1] as f32 * inv_alpha).round() as u8,
        (top[2] as f32 * alpha + bottom[2] as f32 * inv_alpha).round() as u8,
        255,
    ];
    image.put_pixel(x, y, Rgba(blended));
}

fn outline_offsets(scale: u32, stroke_width: u32) -> Vec<(i32, i32)> {
    let radius = (stroke_width.max(1) * scale.max(1)) as i32;
    let mut offsets = Vec::new();
    for dy in -radius..=radius {
        for dx in -radius..=radius {
            if dx == 0 && dy == 0 {
                continue;
            }
            if dx.abs().max(dy.abs()) <= radius {
                offsets.push((dx, dy));
            }
        }
    }
    offsets
}

fn font_size_for_weight(min: u32, max: u32, weight: u8) -> u32 {
    if max <= min {
        return min;
    }
    let span = (max - min) as f64;
    let ratio = (weight as f64 / 100.0).clamp(0.0, 1.0);
    min + (span * ratio).round() as u32
}

fn estimate_label_width(label: &str, font_size: u32) -> f64 {
    (label.chars().count().max(1) as f64) * bitmap_advance(font_size) as f64
}

fn estimate_label_height(font_size: u32) -> f64 {
    (BITMAP_GLYPH_HEIGHT * bitmap_scale(font_size)) as f64
}

fn bitmap_scale(font_size: u32) -> u32 {
    ((font_size + (BITMAP_GLYPH_HEIGHT - 1)) / BITMAP_GLYPH_HEIGHT).max(1)
}

fn bitmap_advance(font_size: u32) -> u32 {
    BITMAP_GLYPH_WIDTH * bitmap_scale(font_size)
}

fn spawn_x(
    config: &Config,
    event: &crate::model::runtime_event::RuntimeEvent,
    label_width: f64,
) -> f64 {
    let max_x = (config.video.canvas.width as f64 - label_width).max(0.0);
    hashed_unit_interval(&event.event_id, "spawn_x") * max_x
}

fn spawn_y(config: &Config, event: &crate::model::runtime_event::RuntimeEvent) -> f64 {
    let min = config.video.text.bottom_spawn_min_ratio;
    let max = config.video.text.bottom_spawn_max_ratio;
    let ratio = min + (max - min) * hashed_unit_interval(&event.event_id, "spawn_y");
    ratio.clamp(0.0, 1.0) * config.video.canvas.height as f64
}

fn motion_angle_deg(
    config: &Config,
    motion_mode: MotionMode,
    event: &crate::model::runtime_event::RuntimeEvent,
    spawn_replay_second: u64,
) -> f64 {
    match motion_mode {
        MotionMode::Vertical => 0.0,
        MotionMode::FixedAngle => config.video.motion.angle_deg,
        MotionMode::RandomAngle => {
            let min = config.video.motion.random_min_deg;
            let max = config.video.motion.random_max_deg;
            min + (max - min)
                * hashed_unit_interval(&event.event_id, &spawn_replay_second.to_string())
        }
    }
}

fn lifetime_secs(
    config: &Config,
    spawn_x: f64,
    spawn_y: f64,
    label_width: f64,
    label_height: f64,
    velocity_x: f64,
    velocity_y: f64,
) -> f64 {
    let x_exit = time_to_exit(
        spawn_x,
        velocity_x,
        -label_width,
        config.video.canvas.width as f64,
    );
    let y_exit = time_to_exit(
        spawn_y,
        velocity_y,
        -label_height,
        config.video.canvas.height as f64 + label_height,
    );

    x_exit.min(y_exit).clamp(1.0, 30.0)
}

fn time_to_exit(position: f64, velocity: f64, min_bound: f64, max_bound: f64) -> f64 {
    if velocity > 0.0 {
        ((max_bound - position) / velocity).max(0.0)
    } else if velocity < 0.0 {
        ((min_bound - position) / velocity).max(0.0)
    } else {
        f64::INFINITY
    }
}

fn hashed_unit_interval(value: &str, salt: &str) -> f64 {
    let digest = Sha256::digest(format!("{value}:{salt}").as_bytes());
    let raw = u64::from_be_bytes(digest[..8].try_into().expect("8 bytes"));
    raw as f64 / u64::MAX as f64
}

fn parse_hex_color(value: &str) -> Result<[u8; 3]> {
    let trimmed = value.trim();
    let hex = trimmed.strip_prefix('#').unwrap_or(trimmed);
    if hex.len() != 6 {
        bail!("video palette color must be 6 hex digits: {value}");
    }

    let parse_channel = |range: std::ops::Range<usize>| -> Result<u8> {
        u8::from_str_radix(&hex[range], 16)
            .with_context(|| format!("invalid hex channel in color {value}"))
    };

    Ok([
        parse_channel(0..2)?,
        parse_channel(2..4)?,
        parse_channel(4..6)?,
    ])
}

fn round2(value: f64) -> f64 {
    (value * 100.0).round() / 100.0
}

#[cfg(test)]
mod tests {
    use tempfile::tempdir;

    use super::*;
    use crate::archive;

    #[test]
    fn video_sample_vertical_mode_emits_sprite_and_frames() {
        let temp = tempdir().expect("tempdir");
        let archive_root = temp.path().join("archive");
        let day = "2026-03-19";

        archive::seed_fixture_raw(&archive_root, day, true).expect("seed fixture");
        let mut config = Config::default();
        config.archive.root_dir = archive_root.display().to_string();
        archive::prepare_day_pack(&config, day, Some(&archive_root), true, true).expect("prepare");

        let report = sample_day_pack(
            &config,
            day,
            Some(&archive_root),
            750,
            8,
            Some(MotionMode::Vertical),
            None,
        )
        .expect("sample video");

        assert_eq!(report.motion_mode, "vertical");
        assert_eq!(report.emitted_sprite_count, 1);
        assert_eq!(report.frames.len(), 240);
        assert_eq!(report.sprites[0].label, "fixture/00-createevent/76168126");

        let first_active_frame = report
            .frames
            .iter()
            .find(|frame| !frame.active_items.is_empty())
            .expect("active frame");
        assert_eq!(first_active_frame.replay_second, 4);
        assert_eq!(first_active_frame.active_items[0].angle_deg, 0.0);
    }

    #[test]
    fn video_sample_random_angle_is_deterministic() {
        let temp = tempdir().expect("tempdir");
        let archive_root = temp.path().join("archive");
        let day = "2026-03-19";

        archive::seed_fixture_raw(&archive_root, day, true).expect("seed fixture");
        let mut config = Config::default();
        config.archive.root_dir = archive_root.display().to_string();
        archive::prepare_day_pack(&config, day, Some(&archive_root), true, true).expect("prepare");

        let first = sample_day_pack(
            &config,
            day,
            Some(&archive_root),
            750,
            8,
            Some(MotionMode::RandomAngle),
            None,
        )
        .expect("first sample");
        let second = sample_day_pack(
            &config,
            day,
            Some(&archive_root),
            750,
            8,
            Some(MotionMode::RandomAngle),
            None,
        )
        .expect("second sample");

        let angle = first.sprites[0].angle_deg;
        assert_eq!(angle, second.sprites[0].angle_deg);
        assert!(angle >= config.video.motion.random_min_deg);
        assert!(angle <= config.video.motion.random_max_deg);
    }

    #[test]
    fn render_day_pack_writes_png_sequence_and_manifest() {
        let temp = tempdir().expect("tempdir");
        let archive_root = temp.path().join("archive");
        let output_dir = temp.path().join("render");
        let day = "2026-03-19";

        archive::seed_fixture_raw(&archive_root, day, true).expect("seed fixture");
        let mut config = Config::default();
        config.archive.root_dir = archive_root.display().to_string();
        config.video.canvas.width = 160;
        config.video.canvas.height = 90;
        config.video.canvas.fps = 4;
        config.video.text.stroke_width = 1;
        archive::prepare_day_pack(&config, day, Some(&archive_root), true, true).expect("prepare");

        let report = render_day_pack(
            &config,
            day,
            Some(&archive_root),
            &output_dir,
            750,
            8,
            Some(MotionMode::Vertical),
            None,
        )
        .expect("render sample");

        assert_eq!(report.rendered_frame_count, 32);
        assert!(report.frame_plan_path.exists());
        assert!(report.manifest_path.exists());
        assert!(report.frames_dir.join("frame-000000.png").exists());
        assert!(report.frames_dir.join("frame-000016.png").exists());

        let active_frame = report
            .frame_plan
            .frames
            .iter()
            .find(|frame| !frame.active_items.is_empty())
            .expect("active frame");
        let rendered = image::open(
            report
                .frames_dir
                .join(format!("frame-{0:06}.png", active_frame.frame_index)),
        )
        .expect("open rendered frame")
        .to_rgba8();

        let background = parse_hex_color(&config.video.palette.background_hex).expect("bg");
        let background_pixel = [background[0], background[1], background[2], 255];
        let non_background_count = rendered
            .pixels()
            .filter(|pixel| pixel.0 != background_pixel)
            .count();
        assert!(non_background_count > 0);
    }
}
