//! P3 video path (Issue #106): solid-background RGBA frame renderer with
//! rising/fading event-text floaters. Ported from `src/ghsingo/internal/video/
//! renderer.go` (mode=solid); the background sequence (movpixer) is dropped per
//! decision 7. Text is rasterized once per floater into an RGBA sprite
//! (ab_glyph) and only re-composited each frame — the background is a flat
//! colour fill into a reused canvas, never re-rasterized.

pub mod font;

use std::collections::BTreeMap;

use ab_glyph::FontArc;

use crate::archive::parse::event_type_name;
use crate::config::Video as VideoCfg;

/// Fixed segment video frame rate (decision baseline #5). The audio/composer
/// tick rate stays `[video].fps`; this is the encoded TS frame rate only.
pub const SEGMENT_FPS: u32 = 30;
/// Bounded live floaters, matching Go `Renderer.maxFloaters`.
pub const MAX_FLOATERS: usize = 24;

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct Rgba {
    pub r: u8,
    pub g: u8,
    pub b: u8,
    pub a: u8,
}

/// Parses "#rrggbb" (or "rrggbb") to RGBA; anything else -> opaque black.
pub fn parse_hex(s: &str) -> Rgba {
    let h = s.strip_prefix('#').unwrap_or(s);
    if h.len() != 6 {
        return Rgba {
            r: 0,
            g: 0,
            b: 0,
            a: 255,
        };
    }
    let p = |i: usize| u8::from_str_radix(&h[i..i + 2], 16).unwrap_or(0);
    Rgba {
        r: p(0),
        g: p(2),
        b: p(4),
        a: 255,
    }
}

/// Concrete, defaulted visual parameters resolved from `[video]`.
pub struct VideoParams {
    pub width: usize,
    pub height: usize,
    pub bg: Rgba,
    pub text_color: Rgba,
    pub font_path: String,
    pub font_size_min: f32,
    pub font_size_max: f32,
    pub speed: f64,
    pub bottom_margin: f64,
    pub scale_grow: f64,
    pub event_colors: BTreeMap<u8, Rgba>,
}

/// Resolves `[video]` into concrete params, applying Solarized-Dark defaults
/// for any field the config leaves empty/zero (mirrors Go `video.New`).
pub fn resolve_params(cfg: &VideoCfg) -> VideoParams {
    let width = if cfg.width > 0 {
        cfg.width as usize
    } else {
        1280
    };
    let height = if cfg.height > 0 {
        cfg.height as usize
    } else {
        720
    };
    let bg = if cfg.palette.background.is_empty() {
        parse_hex("#002b36")
    } else {
        parse_hex(&cfg.palette.background)
    };
    let text_color = if cfg.palette.text.is_empty() {
        parse_hex("#839496")
    } else {
        parse_hex(&cfg.palette.text)
    };
    let (fmin, fmax) = (
        if cfg.font_size_min > 0 {
            cfg.font_size_min as f32
        } else {
            14.0
        },
        if cfg.font_size_max > 0 {
            cfg.font_size_max as f32
        } else {
            48.0
        },
    );
    let speed = if cfg.motion.speed_px_per_sec > 0.0 {
        cfg.motion.speed_px_per_sec
    } else {
        180.0
    };
    let bottom_margin = if cfg.text.bottom_margin_px > 0 {
        f64::from(cfg.text.bottom_margin_px)
    } else {
        16.0
    };
    let scale_grow = if cfg.text.scale_grow_per_sec > 0.0 {
        cfg.text.scale_grow_per_sec
    } else {
        0.22
    };
    let mut event_colors = BTreeMap::new();
    for id in 0u8..6 {
        if let Some(name) = event_type_name(id) {
            if let Some(hex) = cfg.event_colors.get(name) {
                event_colors.insert(id, parse_hex(hex));
            }
        }
    }
    VideoParams {
        width,
        height,
        bg,
        text_color,
        font_path: cfg.font_path.clone(),
        font_size_min: fmin,
        font_size_max: fmax,
        speed,
        bottom_margin,
        scale_grow,
        event_colors,
    }
}

/// Deterministic xorshift64* PRNG -> f64 in [0,1). Self-contained so the video
/// path never disturbs the composer's Go-exact `gorand` stream.
struct Rng(u64);

impl Rng {
    fn new(seed: u64) -> Self {
        Rng(seed ^ 0x9E37_79B9_7F4A_7C15)
    }
    fn next_f64(&mut self) -> f64 {
        let mut x = self.0;
        x ^= x >> 12;
        x ^= x << 25;
        x ^= x >> 27;
        self.0 = x;
        let v = x.wrapping_mul(0x2545_F491_4F6C_DD1D);
        (v >> 11) as f64 / (1u64 << 53) as f64
    }
}

/// Entry anchor reported to the manifest for a spawned floater.
#[derive(Debug, Clone, Copy)]
pub struct SpawnInfo {
    pub end_x: i32,
    pub end_y: i32,
}

struct Floater {
    x: f64,
    y: f64,
    scale: f64,
    alpha: f64,
    speed: f64,
    scale_grow: f64,
    font_size: f64,
    half_extent: f64,
    age: f64,
    wobble_amp: f64,
    wobble_freq: f64,
    wobble_phase: f64,
    sprite: font::Sprite,
    scaled: BTreeMap<i32, font::Sprite>,
}

/// Solid-background RGBA renderer with rising text floaters.
pub struct Renderer {
    w: usize,
    h: usize,
    fps: f64,
    p: VideoParams,
    font: Option<FontArc>,
    canvas: Vec<u8>,
    clean: Vec<u8>,
    floaters: Vec<Floater>,
    rng: Rng,
}

impl Renderer {
    /// Loads the font (if any) and allocates the reusable canvas.
    pub fn new(p: VideoParams, fps: u32, seed: u64) -> Self {
        let font = if p.font_path.is_empty() {
            None
        } else {
            match std::fs::read(&p.font_path) {
                Ok(bytes) => match font::load(&bytes) {
                    Ok(f) => Some(f),
                    Err(e) => {
                        tracing::warn!(err = %e, path = p.font_path.as_str(), "load video font");
                        None
                    }
                },
                Err(e) => {
                    tracing::warn!(err = %e, path = p.font_path.as_str(), "read video font");
                    None
                }
            }
        };
        let canvas = vec![0u8; p.width * p.height * 4];
        // Static layer: the flat background, cached once and memcpy'd per frame.
        let mut clean = vec![0u8; p.width * p.height * 4];
        for px in clean.chunks_exact_mut(4) {
            px[0] = p.bg.r;
            px[1] = p.bg.g;
            px[2] = p.bg.b;
            px[3] = 255;
        }
        Renderer {
            w: p.width,
            h: p.height,
            fps: f64::from(fps),
            p,
            font,
            canvas,
            clean,
            floaters: Vec::new(),
            rng: Rng::new(seed),
        }
    }

    /// Spawns a text floater for one event. `weight` (0-255) drives font size;
    /// `type_id` selects the event colour (falls back to the text colour).
    /// Returns the entry anchor recorded in the manifest.
    pub fn spawn(&mut self, text: &str, type_id: u8, weight: u8) -> Option<SpawnInfo> {
        let font = self.font.as_ref()?;
        let font_size = self.p.font_size_min
            + (self.p.font_size_max - self.p.font_size_min) * (f32::from(weight) / 255.0);
        let color = self
            .p
            .event_colors
            .get(&type_id)
            .copied()
            .unwrap_or(self.p.text_color);
        let sprite = font::rasterize_text(font, text, font_size, [color.r, color.g, color.b, 255])?;
        // Rotated 90°: text width became sprite height, so the rise half-extent
        // is the (rotated) sprite height scaled; Go uses textExtent = width.
        let text_extent = sprite.height as f64;
        let x_pad = f64::from(font_size) * 0.75;
        let max_x = (self.w as f64 - x_pad).max(x_pad);
        let x = x_pad + self.rng.next_f64() * (max_x - x_pad);
        let y = self.h as f64 - self.p.bottom_margin;
        self.floaters.push(Floater {
            x,
            y,
            scale: 0.9,
            alpha: 220.0,
            speed: self.p.speed,
            scale_grow: self.p.scale_grow,
            font_size: f64::from(font_size),
            half_extent: (text_extent * 0.9) / 2.0,
            age: 0.0,
            wobble_amp: 1.0 + self.rng.next_f64() * 3.0,
            wobble_freq: 1.2 + self.rng.next_f64() * 1.8,
            wobble_phase: self.rng.next_f64() * std::f64::consts::PI * 2.0,
            sprite,
            scaled: BTreeMap::new(),
        });
        if self.floaters.len() > MAX_FLOATERS {
            let drop = self.floaters.len() - MAX_FLOATERS;
            self.floaters.drain(0..drop);
        }
        Some(SpawnInfo {
            end_x: x.round() as i32,
            end_y: y.round() as i32,
        })
    }

    /// Advances the simulation one tick and returns the RGBA frame (reused
    /// buffer; caller must copy or consume before the next call).
    pub fn render_frame(&mut self) -> &[u8] {
        // Static layer: memcpy the cached flat background into the reused canvas.
        self.canvas.copy_from_slice(&self.clean);
        let dt = 1.0 / self.fps;
        for f in &mut self.floaters {
            f.y -= f.speed * dt;
            f.age += dt;
            f.scale += f.scale_grow * dt;
            let mut half = self_half_extent(f);
            if half < f.font_size * 0.5 {
                half = f.font_size * 0.5;
            }
            f.half_extent = half;
            f.alpha = alpha_for(f.y, half);
        }
        // Composite (two loops so scale cache borrows don't alias the canvas).
        let w = self.w;
        let h = self.h;
        let n = self.floaters.len();
        for i in 0..n {
            let (draw_x, cy, alpha_f, key) = {
                let f = &self.floaters[i];
                let draw_x = f.x
                    + (f.age * f.wobble_freq * std::f64::consts::PI * 2.0 + f.wobble_phase).sin()
                        * f.wobble_amp;
                (
                    draw_x,
                    f.y.round() as i64,
                    (f.alpha / 255.0).clamp(0.0, 1.0),
                    (f.scale * 20.0).round().max(1.0) as i32,
                )
            };
            if !self.floaters[i].scaled.contains_key(&key) {
                let scale = f64::from(key) / 20.0;
                let scaled = font::scale_nearest(&self.floaters[i].sprite, scale);
                self.floaters[i].scaled.insert(key, scaled);
            }
            let sprite = self.floaters[i].scaled.get(&key).unwrap();
            let cx = draw_x.round() as i64;
            let sw = sprite.width as i64;
            let sh = sprite.height as i64;
            let ox = cx - sw / 2;
            let oy = cy - sh / 2;
            for sy in 0..sh {
                let dy = oy + sy;
                if dy < 0 || dy >= h as i64 {
                    continue;
                }
                for sx in 0..sw {
                    let dx = ox + sx;
                    if dx < 0 || dx >= w as i64 {
                        continue;
                    }
                    let si = (sy * sw + sx) * 4;
                    let sa = sprite.pixels[si as usize + 3];
                    if sa == 0 {
                        continue;
                    }
                    let a = (f64::from(sa) / 255.0) * alpha_f;
                    if a <= 0.0 {
                        continue;
                    }
                    let di = (dy as usize * w + dx as usize) * 4;
                    let dst = &mut self.canvas[di..di + 4];
                    dst[0] = blend(dst[0], sprite.pixels[si as usize], a);
                    dst[1] = blend(dst[1], sprite.pixels[si as usize + 1], a);
                    dst[2] = blend(dst[2], sprite.pixels[si as usize + 2], a);
                }
            }
        }
        // Cull floaters that have risen off the top or fully faded.
        self.floaters
            .retain(|f| is_alive(f.y, f.half_extent, f.alpha));
        &self.canvas
    }

    /// Event colour for `type_id` (event palette, else the text colour).
    pub fn color_for(&self, type_id: u8) -> Rgba {
        self.p
            .event_colors
            .get(&type_id)
            .copied()
            .unwrap_or(self.p.text_color)
    }
}

/// Alpha for a floater at height `y` with half-extent `half` (Go fade rule):
/// full 220 while clear of the top, linearly to 0 as it crosses `half`.
fn alpha_for(y: f64, half: f64) -> f64 {
    if y < half {
        let progress = ((half - y) / (half * 2.0)).clamp(0.0, 1.0);
        220.0 * (1.0 - progress)
    } else {
        220.0
    }
}

/// A floater lives while any part is still on-screen and not fully faded.
fn is_alive(y: f64, half: f64, alpha: f64) -> bool {
    y + half > 0.0 && alpha > 0.0
}

/// Half-extent of a floater's scaled sprite (textExtent*scale / 2), where
/// textExtent is the rotated sprite height (Go uses pre-rotation text width).
fn self_half_extent(f: &Floater) -> f64 {
    (f.sprite.height as f64 * f.scale) / 2.0
}

/// Straight source-over alpha blend of one channel.
fn blend(dst: u8, src: u8, a: f64) -> u8 {
    (f64::from(src) * a + f64::from(dst) * (1.0 - a))
        .round()
        .clamp(0.0, 255.0) as u8
}

#[cfg(test)]
mod tests {
    use super::*;

    fn base_cfg() -> VideoCfg {
        VideoCfg {
            fps: 15,
            width: 1280,
            height: 720,
            font_path: String::new(),
            font_size_min: 14,
            font_size_max: 42,
            palette: crate::config::VideoPalette {
                background: "#002b36".into(),
                text: "#fdf6e3".into(),
            },
            motion: crate::config::VideoMotion {
                speed_px_per_sec: 180.0,
                spawn_y_min: 0.50,
                spawn_y_max: 0.95,
            },
            text: crate::config::VideoText {
                bottom_margin_px: 16,
                despawn_y_min: 0.18,
                despawn_y_max: 0.45,
                scale_grow_per_sec: 0.22,
                rotation_deg: 90.0,
            },
            event_colors: [
                ("PushEvent", "#268bd2"),
                ("CreateEvent", "#2aa198"),
                ("IssuesEvent", "#cb4b16"),
                ("PullRequestEvent", "#d33682"),
                ("ForkEvent", "#93a1a1"),
                ("ReleaseEvent", "#dc322f"),
            ]
            .iter()
            .map(|(k, v)| ((*k).to_string(), (*v).to_string()))
            .collect(),
        }
    }

    #[test]
    fn parse_hex_reads_solarized() {
        assert_eq!(
            parse_hex("#002b36"),
            Rgba {
                r: 0,
                g: 43,
                b: 54,
                a: 255
            }
        );
        assert_eq!(
            parse_hex("fdf6e3"),
            Rgba {
                r: 253,
                g: 246,
                b: 227,
                a: 255
            }
        );
        assert_eq!(
            parse_hex("#bogus"),
            Rgba {
                r: 0,
                g: 0,
                b: 0,
                a: 255
            }
        );
    }

    #[test]
    fn resolve_params_applies_defaults_and_maps_event_colors() {
        let p = resolve_params(&base_cfg());
        assert_eq!(p.width, 1280);
        assert_eq!(p.height, 720);
        assert_eq!(
            p.bg,
            Rgba {
                r: 0,
                g: 43,
                b: 54,
                a: 255
            }
        );
        assert_eq!(p.speed, 180.0);
        assert_eq!(p.bottom_margin, 16.0);
        assert_eq!(p.scale_grow, 0.22);
        // type_id 0 (PushEvent) -> #268bd2, 5 (ReleaseEvent) -> #dc322f.
        assert_eq!(
            p.event_colors[&0],
            Rgba {
                r: 0x26,
                g: 0x8b,
                b: 0xd2,
                a: 255
            }
        );
        assert_eq!(
            p.event_colors[&5],
            Rgba {
                r: 0xdc,
                g: 0x32,
                b: 0x2f,
                a: 255
            }
        );
        assert_eq!(p.event_colors.len(), 6);

        // Empty config -> Solarized/Go defaults, no event colors.
        let d = resolve_params(&VideoCfg::default());
        assert_eq!(d.width, 1280);
        assert_eq!(d.height, 720);
        assert_eq!(d.speed, 180.0);
        assert_eq!(d.font_size_min, 14.0);
        assert!(d.event_colors.is_empty());
    }

    #[test]
    fn spawn_despawn_boundary_alpha_and_liveness() {
        let half = 10.0;
        // Clear of the top -> full alpha, alive.
        assert!((alpha_for(100.0, half) - 220.0).abs() < 1e-9);
        assert!(is_alive(100.0, half, alpha_for(100.0, half)));
        // Exactly at the fade threshold (y == half) -> still full.
        assert!((alpha_for(half, half) - 220.0).abs() < 1e-9);
        // Midway through the fade band -> half alpha.
        assert!((alpha_for(0.0, half) - 110.0).abs() < 1e-9);
        assert!(is_alive(0.0, half, alpha_for(0.0, half)));
        // Fully faded once y == -half (progress clamped to 1).
        assert!(alpha_for(-half, half).abs() < 1e-9);
        assert!(!is_alive(-half, half, alpha_for(-half, half)));
        // Culled once the whole sprite is off the top (y + half <= 0).
        assert!(!is_alive(-half - 0.001, half, 220.0));
    }

    #[test]
    fn scale_nearest_doubles_dimensions() {
        let s = font::Sprite {
            width: 2,
            height: 3,
            pixels: vec![
                1, 2, 3, 255, 4, 5, 6, 255, 7, 8, 9, 255, 10, 11, 12, 255, 13, 14, 15, 255, 16, 17,
                18, 255,
            ],
        };
        let d = font::scale_nearest(&s, 2.0);
        assert_eq!(d.width, 4);
        assert_eq!(d.height, 6);
        assert_eq!(d.pixels.len(), 4 * 6 * 4);
        // Top-left pixel preserved by nearest-neighbor.
        assert_eq!(&d.pixels[0..4], &[1, 2, 3, 255]);
    }
}
