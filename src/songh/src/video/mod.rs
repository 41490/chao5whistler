use std::collections::{BTreeMap, HashMap};
use std::fs;
use std::path::{Path, PathBuf};

use anyhow::{anyhow, bail, Context, Result};
use image::imageops::{blur, rotate90};
use image::{ImageBuffer, Rgba, RgbaImage};
use rusttype::{point, Font, PositionedGlyph, Scale};
use serde::Serialize;
use sha2::{Digest, Sha256};

use crate::config::schema::{Config, MotionMode, PaletteTheme};
use crate::model::normalized_event::NormalizedEvent;
use crate::replay::{self, ReplayTick};
use crate::text;

const MAX_STAGE4_KEY_TEXT_SEGMENTS_PER_SECOND: usize = 9;
const MAX_STAGE4_LIFETIME_SECS: f64 = 14.0;
const TEXT_ROTATION_DEG: f64 = 90.0;
const MAX_BLUR_SIGMA: f32 = 4.0;

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
    pub key_text_segment_limit_per_second: usize,
    pub emitted_sprite_count: usize,
    pub type_color_assignments: Vec<VideoTypeColorAssignment>,
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
    pub first_active_frame_golden: Option<VideoGoldenFrame>,
    pub peak_density_frame_golden: Option<VideoGoldenFrame>,
    pub frame_plan: VideoSampleReport,
}

#[derive(Debug, Clone, Serialize)]
pub struct VideoGoldenFrame {
    pub tag: String,
    pub frame_index: u64,
    pub frame_time_secs: f64,
    pub frame_path: PathBuf,
    pub rgba_sha256: String,
    pub non_background_pixel_count: u64,
    pub active_item_count: usize,
    pub distinct_event_type_count: usize,
    pub distinct_font_size_count: usize,
}

#[derive(Debug, Clone, Serialize)]
pub struct VideoTypeColorAssignment {
    pub event_type: String,
    pub window_event_count: u64,
    pub color_hex: String,
    pub contrast_ratio: f64,
}

#[derive(Debug, Clone, Serialize)]
pub struct VideoSpritePlan {
    pub event_id: String,
    pub event_type: String,
    pub label: String,
    pub color_hex: String,
    pub source_day: String,
    pub second_of_day: u32,
    pub spawn_replay_second: u64,
    pub font_size: u32,
    pub rendered_width: f64,
    pub rendered_height: f64,
    pub second_type_count: u32,
    pub second_type_rank: u32,
    pub initial_gain_db: f64,
    pub text_rotation_deg: f64,
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
    pub event_type: String,
    pub label: String,
    pub color_hex: String,
    pub x: f64,
    pub y: f64,
    pub alpha: u32,
    pub blur_sigma: f64,
    pub font_size: u32,
    pub second_type_count: u32,
    pub initial_gain_db: f64,
    pub text_rotation_deg: f64,
    pub angle_deg: f64,
}

#[derive(Debug, Clone)]
struct SelectedSourceEvent {
    event: NormalizedEvent,
    second_type_count: u32,
    second_type_rank: u32,
    font_size: u32,
    initial_gain_db: f64,
}

#[derive(Debug, Clone)]
struct SpriteDraft {
    selected: SelectedSourceEvent,
    label: String,
    color_hex: String,
    rendered_width: f64,
    rendered_height: f64,
    spawn_x: f64,
    spawn_y: f64,
}

struct LoadedFont {
    font: Font<'static>,
}

#[derive(Debug, Clone, Copy)]
struct LabelMetrics {
    width: f64,
    height: f64,
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

    let font = load_font(&effective_config.video.text.font_path)?;
    let replay_report = replay::dry_run_day_pack(
        &effective_config,
        day,
        archive_root_override,
        start_second,
        duration_secs,
    )?;
    let motion_mode = effective_config.video.motion.mode;
    let fps = effective_config.video.canvas.fps;
    let source_events_by_tick =
        load_source_events_for_ticks(&replay_report.archive_root, &replay_report.ticks)?;
    let type_color_assignments =
        build_type_color_assignments(&effective_config, &source_events_by_tick)?;
    let color_by_type = type_color_assignments
        .iter()
        .map(|entry| (entry.event_type.clone(), entry.color_hex.clone()))
        .collect::<HashMap<_, _>>();

    let sprites = replay_report
        .ticks
        .iter()
        .map(|tick| {
            let source_events = source_events_by_tick
                .get(&(tick.source_day.clone(), tick.second_of_day))
                .cloned()
                .unwrap_or_default();
            build_sprites_for_tick(
                &effective_config,
                &font,
                motion_mode,
                tick,
                &source_events,
                &color_by_type,
            )
        })
        .collect::<Result<Vec<_>>>()?
        .into_iter()
        .flatten()
        .collect::<Vec<_>>();

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
        schema_version: "stage4.video_sample.v2".to_string(),
        archive_root: replay_report.archive_root,
        source_day: day.to_string(),
        start_second,
        duration_secs: replay_report.duration_secs,
        motion_mode: motion_mode.as_str().to_string(),
        canvas_width: effective_config.video.canvas.width,
        canvas_height: effective_config.video.canvas.height,
        fps,
        key_text_segment_limit_per_second: MAX_STAGE4_KEY_TEXT_SEGMENTS_PER_SECOND,
        emitted_sprite_count: sprites.len(),
        type_color_assignments,
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

    let font = load_font(&config.video.text.font_path)?;
    let sprite_assets = build_sprite_assets(config, &font, &frame_plan)?;
    let background = parse_hex_color(&config.video.palette.background_hex)?;
    let background_pixel = [background[0], background[1], background[2], 255];
    let mut first_active_frame_golden = None;
    let mut peak_density_frame_golden = None;
    let mut peak_density_signature = None;
    for frame in &frame_plan.frames {
        let image = render_frame(config, &frame_plan, frame, &sprite_assets)?;
        let frame_path = frames_dir.join(format!("frame-{:06}.png", frame.frame_index));
        image
            .save(&frame_path)
            .with_context(|| format!("write rendered frame {}", frame_path.display()))?;
        if first_active_frame_golden.is_none() && !frame.active_items.is_empty() {
            first_active_frame_golden = Some(build_golden_frame(
                "first_active",
                frame,
                &frame_path,
                &image,
                background_pixel,
            ));
        }
        let signature = frame_density_signature(frame);
        if signature.0 >= 2 {
            let replace_peak = peak_density_signature
                .map(|best: (usize, usize, usize, u64)| {
                    signature.0 > best.0
                        || (signature.0 == best.0
                            && (signature.1 > best.1
                                || (signature.1 == best.1
                                    && (signature.2 > best.2
                                        || (signature.2 == best.2 && frame.frame_index < best.3)))))
                })
                .unwrap_or(true);
            if replace_peak {
                peak_density_signature =
                    Some((signature.0, signature.1, signature.2, frame.frame_index));
                peak_density_frame_golden = Some(build_golden_frame(
                    "peak_density",
                    frame,
                    &frame_path,
                    &image,
                    background_pixel,
                ));
            }
        }
    }

    let manifest_path = output_dir.join("render-manifest.json");
    let report = VideoRenderReport {
        schema_version: "stage4.video_render.v4".to_string(),
        output_dir: output_dir.to_path_buf(),
        frames_dir,
        frame_plan_path,
        manifest_path: manifest_path.clone(),
        rendered_frame_count: frame_plan.frames.len(),
        first_active_frame_golden,
        peak_density_frame_golden,
        frame_plan,
    };
    fs::write(&manifest_path, serde_json::to_vec_pretty(&report)?)
        .with_context(|| format!("write stage4 render manifest {}", manifest_path.display()))?;

    Ok(report)
}

impl VideoSpritePlan {
    fn from_draft(
        config: &Config,
        motion_mode: MotionMode,
        spawn_replay_second: u64,
        source_day: &str,
        second_of_day: u32,
        draft: SpriteDraft,
    ) -> Result<Self> {
        let angle_deg = motion_angle_deg(
            config,
            motion_mode,
            &draft.selected.event,
            spawn_replay_second,
        );
        let angle_rad = angle_deg.to_radians();
        let speed = config.video.motion.speed_px_per_sec;
        let velocity_x = speed * angle_rad.sin();
        let velocity_y = -speed * angle_rad.cos();
        let lifetime_secs = lifetime_secs(
            config,
            draft.spawn_x,
            draft.spawn_y,
            draft.rendered_width,
            draft.rendered_height,
            velocity_x,
            velocity_y,
        );

        Ok(Self {
            event_id: draft.selected.event.event_id.clone(),
            event_type: draft.selected.event.event_type.clone(),
            label: draft.label,
            color_hex: draft.color_hex,
            source_day: source_day.to_string(),
            second_of_day,
            spawn_replay_second,
            font_size: draft.selected.font_size,
            rendered_width: round2(draft.rendered_width),
            rendered_height: round2(draft.rendered_height),
            second_type_count: draft.selected.second_type_count,
            second_type_rank: draft.selected.second_type_rank,
            initial_gain_db: round2(draft.selected.initial_gain_db),
            text_rotation_deg: TEXT_ROTATION_DEG,
            angle_deg,
            spawn_x: draft.spawn_x,
            spawn_y: draft.spawn_y,
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
        let blur_sigma = (MAX_BLUR_SIGMA as f64) * (age_secs / self.lifetime_secs).clamp(0.0, 1.0);

        Some(VideoFrameItem {
            event_id: self.event_id.clone(),
            event_type: self.event_type.clone(),
            label: self.label.clone(),
            color_hex: self.color_hex.clone(),
            x: round2(x),
            y: round2(y),
            alpha,
            blur_sigma: round2(blur_sigma),
            font_size: self.font_size,
            second_type_count: self.second_type_count,
            initial_gain_db: self.initial_gain_db,
            text_rotation_deg: self.text_rotation_deg,
            angle_deg: round2(self.angle_deg),
        })
    }
}

fn build_sprites_for_tick(
    config: &Config,
    font: &LoadedFont,
    motion_mode: MotionMode,
    tick: &ReplayTick,
    source_events: &[NormalizedEvent],
    color_by_type: &HashMap<String, String>,
) -> Result<Vec<VideoSpritePlan>> {
    let mut drafts = select_key_events_for_second(config, source_events)
        .into_iter()
        .map(|selected| {
            let label = text::render_template(&config.text, &selected.event.text_fields)?;
            let horizontal_metrics = measure_label(font, &label, selected.font_size);
            Ok(SpriteDraft {
                color_hex: color_by_type
                    .get(&selected.event.event_type)
                    .cloned()
                    .unwrap_or_else(|| config.video.palette.text_hex.clone()),
                label,
                rendered_width: horizontal_metrics.height.max(1.0),
                rendered_height: horizontal_metrics.width.max(1.0),
                selected,
                spawn_x: 0.0,
                spawn_y: 0.0,
            })
        })
        .collect::<Result<Vec<_>>>()?;

    assign_spawn_positions(
        config,
        tick.source_day.as_str(),
        tick.second_of_day,
        &mut drafts,
    );

    drafts
        .into_iter()
        .map(|draft| {
            VideoSpritePlan::from_draft(
                config,
                motion_mode,
                tick.replay_second,
                tick.source_day.as_str(),
                tick.second_of_day,
                draft,
            )
        })
        .collect()
}

fn assign_spawn_positions(
    config: &Config,
    source_day: &str,
    second_of_day: u32,
    drafts: &mut [SpriteDraft],
) {
    if drafts.is_empty() {
        return;
    }

    if drafts.len() == 1 {
        let draft = &mut drafts[0];
        draft.spawn_x = spawn_x(config, &draft.selected.event.event_id, draft.rendered_width);
        draft.spawn_y = spawn_y(
            config,
            &draft.selected.event.event_id,
            draft.rendered_height,
        );
        return;
    }

    let mut lane_order = (0..drafts.len()).collect::<Vec<_>>();
    lane_order.sort_by_key(|index| {
        hashed_u64(
            &format!(
                "{source_day}:{second_of_day}:{}",
                drafts[*index].selected.event.event_id
            ),
            "spawn_lane",
        )
    });

    let available_width = config.video.canvas.width as f64;
    let total_width = lane_order
        .iter()
        .map(|index| drafts[*index].rendered_width)
        .sum::<f64>();
    let preferred_gap = (available_width * 0.018).max(8.0);

    if total_width + preferred_gap * (drafts.len().saturating_sub(1) as f64) <= available_width {
        let used_width = total_width + preferred_gap * (drafts.len().saturating_sub(1) as f64);
        let mut cursor_x = ((available_width - used_width).max(0.0)) / 2.0;
        for index in lane_order {
            let draft = &mut drafts[index];
            let max_x = (available_width - draft.rendered_width).max(0.0);
            draft.spawn_x = cursor_x.min(max_x);
            draft.spawn_y = spawn_y(
                config,
                &draft.selected.event.event_id,
                draft.rendered_height,
            );
            cursor_x = draft.spawn_x + draft.rendered_width + preferred_gap;
        }
        return;
    }

    let mut cumulative_width = 0.0;
    for index in lane_order {
        let draft = &mut drafts[index];
        let center_ratio = (cumulative_width + draft.rendered_width / 2.0) / total_width.max(1.0);
        let max_x = (available_width - draft.rendered_width).max(0.0);
        draft.spawn_x =
            (center_ratio * available_width - draft.rendered_width / 2.0).clamp(0.0, max_x);
        draft.spawn_y = spawn_y(
            config,
            &draft.selected.event.event_id,
            draft.rendered_height,
        );
        cumulative_width += draft.rendered_width;
    }
}

fn render_frame(
    config: &Config,
    frame_plan: &VideoSampleReport,
    frame: &VideoFrameSample,
    sprite_assets: &HashMap<String, RgbaImage>,
) -> Result<RgbaImage> {
    let background = parse_hex_color(&config.video.palette.background_hex)?;
    let mut image = ImageBuffer::from_pixel(
        frame_plan.canvas_width,
        frame_plan.canvas_height,
        Rgba([background[0], background[1], background[2], 255]),
    );

    for item in &frame.active_items {
        let base = sprite_assets
            .get(&item.event_id)
            .ok_or_else(|| anyhow!("missing sprite asset for {}", item.event_id))?;
        draw_sprite(
            &mut image,
            base,
            item.x,
            item.y,
            item.alpha,
            item.blur_sigma as f32,
        );
    }

    Ok(image)
}

fn build_sprite_assets(
    config: &Config,
    font: &LoadedFont,
    frame_plan: &VideoSampleReport,
) -> Result<HashMap<String, RgbaImage>> {
    let mut assets = HashMap::new();
    for sprite in &frame_plan.sprites {
        let fill_color = parse_hex_color(&sprite.color_hex)?;
        let outline_color = outline_color_for_fill(config, &sprite.color_hex)?;
        let text_image = render_text_sprite(
            font,
            &sprite.label,
            sprite.font_size,
            fill_color,
            outline_color,
            config.video.text.stroke_width,
        )?;
        assets.insert(sprite.event_id.clone(), rotate90(&text_image));
    }
    Ok(assets)
}

fn draw_sprite(
    image: &mut RgbaImage,
    base: &RgbaImage,
    x: f64,
    y: f64,
    alpha: u32,
    blur_sigma: f32,
) {
    let mut layer = if blur_sigma > 0.0 {
        blur(base, blur_sigma)
    } else {
        base.clone()
    };
    apply_alpha(&mut layer, alpha);

    let base_x = x.round() as i32;
    let base_y = y.round() as i32;
    for (dx, dy, pixel) in rgba_pixels(&layer) {
        if pixel[3] == 0 {
            continue;
        }
        blend_pixel(image, base_x + dx, base_y + dy, pixel);
    }
}

fn rgba_pixels(image: &RgbaImage) -> impl Iterator<Item = (i32, i32, [u8; 4])> + '_ {
    image
        .enumerate_pixels()
        .map(|(x, y, pixel)| (x as i32, y as i32, [pixel[0], pixel[1], pixel[2], pixel[3]]))
}

fn apply_alpha(image: &mut RgbaImage, alpha: u32) {
    let alpha_ratio = (alpha.min(255) as f32) / 255.0;
    for pixel in image.pixels_mut() {
        pixel.0[3] = ((pixel.0[3] as f32) * alpha_ratio)
            .round()
            .clamp(0.0, 255.0) as u8;
    }
}

fn render_text_sprite(
    font: &LoadedFont,
    label: &str,
    font_size: u32,
    fill_color: [u8; 3],
    outline_color: [u8; 3],
    stroke_width: u32,
) -> Result<RgbaImage> {
    let scale = Scale::uniform(font_size as f32);
    let v_metrics = font.font.v_metrics(scale);
    let glyphs = font
        .font
        .layout(label, scale, point(0.0, v_metrics.ascent))
        .collect::<Vec<_>>();
    let bounds = glyph_bounds(&glyphs).unwrap_or((0, 0, 1, v_metrics.ascent.ceil() as i32));
    let padding = stroke_width.max(1) as i32 + 2;
    let width = (bounds.2 - bounds.0 + padding * 2).max(1) as u32;
    let height = (bounds.3 - bounds.1 + padding * 2).max(1) as u32;
    let mut image = ImageBuffer::from_pixel(width, height, Rgba([0, 0, 0, 0]));

    if stroke_width > 0 {
        for (dx, dy) in outline_offsets(stroke_width) {
            draw_glyphs(
                &mut image,
                &glyphs,
                bounds.0,
                bounds.1,
                padding,
                dx,
                dy,
                outline_color,
            );
        }
    }

    draw_glyphs(
        &mut image, &glyphs, bounds.0, bounds.1, padding, 0, 0, fill_color,
    );

    Ok(image)
}

fn draw_glyphs(
    image: &mut RgbaImage,
    glyphs: &[PositionedGlyph<'_>],
    min_x: i32,
    min_y: i32,
    padding: i32,
    dx: i32,
    dy: i32,
    color: [u8; 3],
) {
    for glyph in glyphs {
        let Some(bbox) = glyph.pixel_bounding_box() else {
            continue;
        };
        glyph.draw(|x, y, coverage| {
            if coverage <= 0.0 {
                return;
            }
            let px = x as i32 + bbox.min.x - min_x + padding + dx;
            let py = y as i32 + bbox.min.y - min_y + padding + dy;
            blend_pixel(
                image,
                px,
                py,
                [
                    color[0],
                    color[1],
                    color[2],
                    (coverage * 255.0).round().clamp(0.0, 255.0) as u8,
                ],
            );
        });
    }
}

fn measure_label(font: &LoadedFont, label: &str, font_size: u32) -> LabelMetrics {
    let scale = Scale::uniform(font_size as f32);
    let v_metrics = font.font.v_metrics(scale);
    let glyphs = font
        .font
        .layout(label, scale, point(0.0, v_metrics.ascent))
        .collect::<Vec<_>>();
    if let Some((min_x, min_y, max_x, max_y)) = glyph_bounds(&glyphs) {
        LabelMetrics {
            width: (max_x - min_x).max(1) as f64,
            height: (max_y - min_y).max(1) as f64,
        }
    } else {
        LabelMetrics {
            width: 1.0,
            height: (v_metrics.ascent - v_metrics.descent).ceil().max(1.0) as f64,
        }
    }
}

fn glyph_bounds(glyphs: &[PositionedGlyph<'_>]) -> Option<(i32, i32, i32, i32)> {
    let mut min_x = i32::MAX;
    let mut min_y = i32::MAX;
    let mut max_x = i32::MIN;
    let mut max_y = i32::MIN;

    for glyph in glyphs {
        let Some(bbox) = glyph.pixel_bounding_box() else {
            continue;
        };
        min_x = min_x.min(bbox.min.x);
        min_y = min_y.min(bbox.min.y);
        max_x = max_x.max(bbox.max.x);
        max_y = max_y.max(bbox.max.y);
    }

    if min_x == i32::MAX {
        None
    } else {
        Some((min_x, min_y, max_x, max_y))
    }
}

fn outline_offsets(stroke_width: u32) -> Vec<(i32, i32)> {
    let radius = stroke_width.max(1) as i32;
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

fn load_source_events_for_ticks(
    archive_root: &Path,
    ticks: &[ReplayTick],
) -> Result<BTreeMap<(String, u32), Vec<NormalizedEvent>>> {
    let mut ranges = BTreeMap::<String, (u32, u32)>::new();
    for tick in ticks {
        let entry = ranges
            .entry(tick.source_day.clone())
            .or_insert((tick.second_of_day, tick.second_of_day + 1));
        entry.0 = entry.0.min(tick.second_of_day);
        entry.1 = entry.1.max((tick.second_of_day + 1).min(86_400));
    }

    let mut events_by_tick = BTreeMap::new();
    for (day, (start_second, end_second)) in ranges {
        let per_second =
            replay::load_source_events_for_range(archive_root, &day, start_second, end_second)?;
        for (second_of_day, events) in per_second {
            events_by_tick.insert((day.clone(), second_of_day), events);
        }
    }

    Ok(events_by_tick)
}

fn select_key_events_for_second(
    config: &Config,
    source_events: &[NormalizedEvent],
) -> Vec<SelectedSourceEvent> {
    if source_events.is_empty() {
        return Vec::new();
    }

    let mut counts = BTreeMap::<String, u32>::new();
    for event in source_events {
        *counts.entry(event.event_type.clone()).or_insert(0) += 1;
    }
    let max_count = counts.values().copied().max().unwrap_or(1);

    let mut type_order = counts
        .iter()
        .map(|(event_type, count)| (event_type.clone(), *count))
        .collect::<Vec<_>>();
    type_order.sort_by(|left, right| {
        right
            .1
            .cmp(&left.1)
            .then_with(|| event_weight(config, &right.0).cmp(&event_weight(config, &left.0)))
            .then_with(|| left.0.cmp(&right.0))
    });

    let type_rank = type_order
        .iter()
        .enumerate()
        .map(|(index, (event_type, _))| (event_type.clone(), (index + 1) as u32))
        .collect::<HashMap<_, _>>();

    let mut selected = Vec::new();
    for (event_type, count) in type_order {
        let mut events = source_events
            .iter()
            .filter(|event| event.event_type == event_type)
            .cloned()
            .collect::<Vec<_>>();
        events.sort_by(|left, right| {
            right
                .weight
                .cmp(&left.weight)
                .then_with(|| left.created_at_utc.cmp(&right.created_at_utc))
                .then_with(|| left.event_id.cmp(&right.event_id))
        });

        for event in events {
            selected.push(SelectedSourceEvent {
                event,
                second_type_count: count,
                second_type_rank: *type_rank.get(&event_type).unwrap_or(&1),
                font_size: font_size_for_type_density(
                    config.video.text.font_size_min,
                    config.video.text.font_size_max,
                    count,
                    max_count,
                ),
                initial_gain_db: gain_db_for_type_density(count, max_count),
            });
            if selected.len() >= MAX_STAGE4_KEY_TEXT_SEGMENTS_PER_SECOND {
                return selected;
            }
        }
    }

    selected
}

fn build_type_color_assignments(
    config: &Config,
    source_events_by_tick: &BTreeMap<(String, u32), Vec<NormalizedEvent>>,
) -> Result<Vec<VideoTypeColorAssignment>> {
    let background = parse_hex_color(&config.video.palette.background_hex)?;
    let mut counts = BTreeMap::<String, u64>::new();
    for events in source_events_by_tick.values() {
        for event in events {
            *counts.entry(event.event_type.clone()).or_insert(0) += 1;
        }
    }

    let mut ranked_types = counts.into_iter().collect::<Vec<_>>();
    ranked_types.sort_by(|left, right| {
        right
            .1
            .cmp(&left.1)
            .then_with(|| event_weight(config, &right.0).cmp(&event_weight(config, &left.0)))
            .then_with(|| left.0.cmp(&right.0))
    });

    let mut color_candidates = theme_event_color_candidates(config)?;
    color_candidates.sort_by(|left, right| {
        let left_contrast = contrast_ratio(parse_hex_color(left).unwrap_or(background), background);
        let right_contrast =
            contrast_ratio(parse_hex_color(right).unwrap_or(background), background);
        right_contrast
            .partial_cmp(&left_contrast)
            .unwrap_or(std::cmp::Ordering::Equal)
    });

    Ok(ranked_types
        .into_iter()
        .enumerate()
        .map(|(index, (event_type, window_event_count))| {
            let color_hex = color_candidates
                .get(index)
                .cloned()
                .unwrap_or_else(|| config.video.palette.text_hex.clone());
            let contrast = contrast_ratio(
                parse_hex_color(&color_hex).unwrap_or(background),
                background,
            );
            VideoTypeColorAssignment {
                event_type,
                window_event_count,
                color_hex,
                contrast_ratio: round2(contrast),
            }
        })
        .collect())
}

fn theme_event_color_candidates(config: &Config) -> Result<Vec<String>> {
    match config.video.palette.theme {
        PaletteTheme::SolarizedDark => Ok(dedup_preserve_order(vec![
            config.video.palette.text_hex.clone(),
            "#eee8d5".to_string(),
            config.video.palette.accent_hex.clone(),
            "#cb4b16".to_string(),
            "#dc322f".to_string(),
            "#d33682".to_string(),
            "#6c71c4".to_string(),
            "#268bd2".to_string(),
            "#2aa198".to_string(),
            "#859900".to_string(),
        ])),
    }
}

fn dedup_preserve_order(values: Vec<String>) -> Vec<String> {
    let mut deduped = Vec::new();
    for value in values {
        if !deduped.contains(&value) {
            deduped.push(value);
        }
    }
    deduped
}

fn event_weight(config: &Config, event_type: &str) -> u8 {
    config
        .events
        .weights
        .iter()
        .find(|(kind, _)| kind.as_str() == event_type)
        .map(|(_, weight)| *weight)
        .unwrap_or(0)
}

fn font_size_for_type_density(min: u32, max: u32, type_count: u32, max_count: u32) -> u32 {
    if max <= min {
        return min;
    }
    if max_count <= 1 {
        return min + ((max - min) / 2);
    }
    let ratio = (type_count.saturating_sub(1)) as f64 / (max_count.saturating_sub(1)) as f64;
    min + (((max - min) as f64) * ratio).round() as u32
}

fn gain_db_for_type_density(type_count: u32, max_count: u32) -> f64 {
    if max_count <= 1 {
        return 0.0;
    }
    let ratio = (type_count.saturating_sub(1)) as f64 / (max_count.saturating_sub(1)) as f64;
    -4.0 + ratio * 10.0
}

fn spawn_x(config: &Config, event_id: &str, label_width: f64) -> f64 {
    let max_x = (config.video.canvas.width as f64 - label_width).max(0.0);
    hashed_unit_interval(event_id, "spawn_x") * max_x
}

fn spawn_y(config: &Config, event_id: &str, label_height: f64) -> f64 {
    let min = config.video.text.bottom_spawn_min_ratio;
    let max = config.video.text.bottom_spawn_max_ratio;
    let ratio = min + (max - min) * hashed_unit_interval(event_id, "spawn_y");
    let max_y = (config.video.canvas.height as f64 - label_height).max(0.0);
    ratio.clamp(0.0, 1.0) * max_y
}

fn motion_angle_deg(
    config: &Config,
    motion_mode: MotionMode,
    event: &NormalizedEvent,
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

    x_exit.min(y_exit).clamp(1.0, MAX_STAGE4_LIFETIME_SECS)
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

fn hashed_u64(value: &str, salt: &str) -> u64 {
    let digest = Sha256::digest(format!("{value}:{salt}").as_bytes());
    u64::from_be_bytes(digest[..8].try_into().expect("8 bytes"))
}

fn hashed_unit_interval(value: &str, salt: &str) -> f64 {
    hashed_u64(value, salt) as f64 / u64::MAX as f64
}

fn load_font(path: &str) -> Result<LoadedFont> {
    let resolved_path = resolve_font_path(path)?;
    let font_bytes = fs::read(&resolved_path)
        .with_context(|| format!("failed to read font {}", resolved_path.display()))?;
    let font = Font::try_from_vec(font_bytes)
        .ok_or_else(|| anyhow!("failed to parse font {}", resolved_path.display()))?;
    Ok(LoadedFont { font })
}

fn resolve_font_path(path: &str) -> Result<PathBuf> {
    let candidate = PathBuf::from(path);
    if candidate.is_absolute() && candidate.exists() {
        return Ok(candidate);
    }
    if candidate.exists() {
        return Ok(candidate);
    }

    let repo_root = PathBuf::from(env!("CARGO_MANIFEST_DIR"))
        .parent()
        .and_then(|path| path.parent())
        .ok_or_else(|| anyhow!("failed to resolve repo root from CARGO_MANIFEST_DIR"))?
        .to_path_buf();
    let repo_relative = repo_root.join(path);
    if repo_relative.exists() {
        return Ok(repo_relative);
    }

    bail!("video.text.font_path does not exist: {path}")
}

fn outline_color_for_fill(config: &Config, fill_hex: &str) -> Result<[u8; 3]> {
    if fill_hex.eq_ignore_ascii_case(&config.video.palette.text_hex) {
        parse_hex_color(&config.video.palette.accent_hex)
    } else {
        parse_hex_color(&config.video.palette.text_hex)
    }
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

fn contrast_ratio(foreground: [u8; 3], background: [u8; 3]) -> f64 {
    let fg = relative_luminance(foreground);
    let bg = relative_luminance(background);
    let (lighter, darker) = if fg >= bg { (fg, bg) } else { (bg, fg) };
    (lighter + 0.05) / (darker + 0.05)
}

fn relative_luminance(color: [u8; 3]) -> f64 {
    let convert = |channel: u8| {
        let normalized = channel as f64 / 255.0;
        if normalized <= 0.03928 {
            normalized / 12.92
        } else {
            ((normalized + 0.055) / 1.055).powf(2.4)
        }
    };

    0.2126 * convert(color[0]) + 0.7152 * convert(color[1]) + 0.0722 * convert(color[2])
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

fn rgba_sha256(image: &RgbaImage) -> String {
    hex::encode(Sha256::digest(image.as_raw()))
}

fn build_golden_frame(
    tag: &str,
    frame: &VideoFrameSample,
    frame_path: &Path,
    image: &RgbaImage,
    background_pixel: [u8; 4],
) -> VideoGoldenFrame {
    let (active_item_count, distinct_event_type_count, distinct_font_size_count) =
        frame_density_signature(frame);
    VideoGoldenFrame {
        tag: tag.to_string(),
        frame_index: frame.frame_index,
        frame_time_secs: round2(frame.frame_time_secs),
        frame_path: frame_path.to_path_buf(),
        rgba_sha256: rgba_sha256(image),
        non_background_pixel_count: non_background_pixel_count(image, background_pixel),
        active_item_count,
        distinct_event_type_count,
        distinct_font_size_count,
    }
}

fn frame_density_signature(frame: &VideoFrameSample) -> (usize, usize, usize) {
    let mut distinct_types = BTreeMap::<String, ()>::new();
    let mut distinct_font_sizes = BTreeMap::<u32, ()>::new();
    for item in &frame.active_items {
        distinct_types.insert(item.event_type.clone(), ());
        distinct_font_sizes.insert(item.font_size, ());
    }
    (
        frame.active_items.len(),
        distinct_types.len(),
        distinct_font_sizes.len(),
    )
}

fn non_background_pixel_count(image: &RgbaImage, background_pixel: [u8; 4]) -> u64 {
    image
        .pixels()
        .filter(|pixel| pixel.0 != background_pixel)
        .count() as u64
}

fn round2(value: f64) -> f64 {
    (value * 100.0).round() / 100.0
}

#[cfg(test)]
mod tests {
    use std::path::Path;

    use serde_json::json;
    use tempfile::tempdir;

    use super::*;
    use crate::archive;

    fn write_dense_second_raw_fixture(archive_root: &Path, day: &str) {
        let raw_path = archive_root.join(day).join("raw").join("00.json.gz");
        let mut raw_events = Vec::new();

        for index in 0..5 {
            raw_events.push(json!({
                "id": format!("push-{index}"),
                "type": "PushEvent",
                "created_at": format!("{day}T00:12:34Z"),
                "repo": {"name": "fixture/dense-push"},
                "actor": {"login": format!("push_actor_{index}")},
                "payload": {"head": format!("aa11bb22cc33dd44ee55ff66778899aa00bb{index:02x}")},
            }));
        }
        for index in 0..3 {
            raw_events.push(json!({
                "id": format!("issues-{index}"),
                "type": "IssuesEvent",
                "created_at": format!("{day}T00:12:34Z"),
                "repo": {"name": "fixture/dense-issues"},
                "actor": {"login": format!("issues_actor_{index}")},
                "payload": {"issue": {"id": 10_000 + index}},
            }));
        }
        for index in 0..2 {
            raw_events.push(json!({
                "id": format!("release-{index}"),
                "type": "ReleaseEvent",
                "created_at": format!("{day}T00:12:34Z"),
                "repo": {"name": "fixture/dense-release"},
                "actor": {"login": format!("release_actor_{index}")},
                "payload": {"release": {"id": 20_000 + index}},
            }));
        }

        archive::materialize::write_gzip_json_lines(&raw_path, &raw_events)
            .expect("write dense raw");
    }

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
        assert_eq!(report.sprites[0].text_rotation_deg, 90.0);
        assert_eq!(report.sprites[0].initial_gain_db, 0.0);

        let first_active_frame = report
            .frames
            .iter()
            .find(|frame| !frame.active_items.is_empty())
            .expect("active frame");
        assert_eq!(first_active_frame.replay_second, 4);
        assert_eq!(first_active_frame.active_items[0].angle_deg, 0.0);
        assert_eq!(first_active_frame.active_items[0].text_rotation_deg, 90.0);
        assert!(first_active_frame.active_items[0].blur_sigma >= 0.0);
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
    fn stage4_limits_dense_seconds_and_ranks_type_density() {
        let temp = tempdir().expect("tempdir");
        let archive_root = temp.path().join("archive");
        let day = "2026-03-19";

        archive::seed_fixture_raw(&archive_root, day, true).expect("seed fixture");
        write_dense_second_raw_fixture(&archive_root, day);

        let mut config = Config::default();
        config.archive.root_dir = archive_root.display().to_string();
        archive::prepare_day_pack(&config, day, Some(&archive_root), true, true).expect("prepare");

        let report = sample_day_pack(
            &config,
            day,
            Some(&archive_root),
            754,
            1,
            Some(MotionMode::Vertical),
            None,
        )
        .expect("sample dense second");

        assert_eq!(report.key_text_segment_limit_per_second, 9);
        assert_eq!(report.emitted_sprite_count, 9);

        let mut per_type = BTreeMap::<String, usize>::new();
        for sprite in &report.sprites {
            *per_type.entry(sprite.event_type.clone()).or_insert(0) += 1;
        }
        assert_eq!(per_type.get("PushEvent"), Some(&5));
        assert_eq!(per_type.get("IssuesEvent"), Some(&3));
        assert_eq!(per_type.get("ReleaseEvent"), Some(&1));
        assert_eq!(report.type_color_assignments[0].event_type, "PushEvent");
        assert!(
            report.type_color_assignments[0].contrast_ratio
                >= report.type_color_assignments[1].contrast_ratio
        );

        let push_sprite = report
            .sprites
            .iter()
            .find(|sprite| sprite.event_type == "PushEvent")
            .expect("push sprite");
        let release_sprite = report
            .sprites
            .iter()
            .find(|sprite| sprite.event_type == "ReleaseEvent")
            .expect("release sprite");
        assert!(push_sprite.font_size > release_sprite.font_size);
        assert!(push_sprite.initial_gain_db > release_sprite.initial_gain_db);

        let mut sprites_by_x = report.sprites.clone();
        sprites_by_x.sort_by(|left, right| {
            left.spawn_x
                .partial_cmp(&right.spawn_x)
                .expect("spawn x ordering")
        });
        for pair in sprites_by_x.windows(2) {
            let left = &pair[0];
            let right = &pair[1];
            assert!(
                left.spawn_x + left.rendered_width <= right.spawn_x,
                "expected non-overlapping lanes: {:?} vs {:?}",
                left,
                right
            );
        }
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
        assert!(report.first_active_frame_golden.is_some());

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
        let non_background_count = non_background_pixel_count(&rendered, background_pixel);
        assert!(non_background_count > 0);

        let golden = report
            .first_active_frame_golden
            .as_ref()
            .expect("first active frame golden");
        assert_eq!(golden.tag, "first_active");
        assert_eq!(golden.frame_index, active_frame.frame_index);
        assert_eq!(golden.non_background_pixel_count, non_background_count);
        assert_eq!(golden.active_item_count, 1);
        assert_eq!(golden.distinct_event_type_count, 1);
        assert_eq!(golden.distinct_font_size_count, 1);
        assert_eq!(
            golden.rgba_sha256,
            "c4a3d37e4ae5274dc769aac8630efc31652334071cbcb7ea6462029b756b48ac"
        );
        assert!(report.peak_density_frame_golden.is_none());
    }

    #[test]
    fn render_day_pack_dense_fixture_exports_peak_density_golden() {
        let temp = tempdir().expect("tempdir");
        let archive_root = temp.path().join("archive");
        let output_dir = temp.path().join("render-dense");
        let day = "2026-03-19";

        archive::seed_fixture_raw(&archive_root, day, true).expect("seed fixture");
        write_dense_second_raw_fixture(&archive_root, day);

        let mut config = Config::default();
        config.archive.root_dir = archive_root.display().to_string();
        config.video.canvas.width = 320;
        config.video.canvas.height = 180;
        config.video.canvas.fps = 4;
        config.video.text.stroke_width = 1;
        archive::prepare_day_pack(&config, day, Some(&archive_root), true, true).expect("prepare");

        let report = render_day_pack(
            &config,
            day,
            Some(&archive_root),
            &output_dir,
            754,
            1,
            Some(MotionMode::Vertical),
            None,
        )
        .expect("render dense sample");

        let peak = report
            .peak_density_frame_golden
            .as_ref()
            .expect("peak density frame golden");
        assert_eq!(peak.tag, "peak_density");
        assert_eq!(peak.frame_index, 0);
        assert_eq!(peak.active_item_count, 9);
        assert_eq!(peak.distinct_event_type_count, 3);
        assert_eq!(peak.distinct_font_size_count, 3);
        assert_eq!(
            peak.rgba_sha256,
            "d0efd77ff998edf3f6297e67b0b95822ddc427c659bfda918ce3bb3bc0ec3933"
        );
    }

    #[test]
    fn default_font_path_resolves_repo_asset() {
        let path =
            resolve_font_path("ops/assets/3270NerdFontMono-Condensed.ttf").expect("resolve font");
        assert!(path.ends_with("ops/assets/3270NerdFontMono-Condensed.ttf"));
    }
}
