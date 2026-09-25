//! ab_glyph font rasterization for the P3 video path (Issue #106).
//!
//! Rasterizes a text string into an RGBA sprite: one alpha-masked colour,
//! laid out horizontally then rotated 90° to match the Go renderer's vertical
//! floaters (`internal/video/renderer.go` buildTextSprite). The floater's
//! fade alpha is applied at composite time, so the sprite stores only glyph
//! coverage in its alpha channel.

use ab_glyph::{Font, FontArc, PxScale, ScaleFont};

/// Parses a TTF/OTF byte slice into an owned ab_glyph font.
pub fn load(data: &[u8]) -> Result<FontArc, ab_glyph::InvalidFont> {
    FontArc::try_from_vec(data.to_vec())
}

/// A rasterized RGBA sprite: `width*height` pixels, 4 bytes each. Alpha holds
/// glyph coverage (0..255); RGB holds the requested colour.
pub struct Sprite {
    pub width: usize,
    pub height: usize,
    pub pixels: Vec<u8>,
}

/// Rasterizes `text` at `size` px in `color` ([r,g,b,_]; alpha = coverage).
/// Returns `None` when the font has no outline for any glyph (e.g. empty text).
pub fn rasterize_text(font: &FontArc, text: &str, size: f32, color: [u8; 4]) -> Option<Sprite> {
    if text.is_empty() {
        return None;
    }
    let scaled = font.as_scaled(PxScale::from(size));
    let mut glyphs: Vec<(f32, f32, ab_glyph::OutlinedGlyph)> = Vec::new();
    let mut pen = 0.0f32;
    let (mut min_y, mut max_y) = (f32::INFINITY, f32::NEG_INFINITY);
    for c in text.chars() {
        let gid = font.glyph_id(c);
        let glyph = scaled.scaled_glyph(c);
        let adv = scaled.h_advance(gid);
        if let Some(og) = font.outline_glyph(glyph) {
            let b = og.px_bounds();
            min_y = min_y.min(b.min.y);
            max_y = max_y.max(b.max.y);
            glyphs.push((pen + b.min.x, b.min.y, og));
        }
        pen += adv;
    }
    if glyphs.is_empty() {
        return None;
    }
    let pad = (size * 0.3).max(4.0);
    let baseline = -min_y + pad; // sprite row of the text baseline
    let h = (max_y - min_y).ceil() as usize + 2 * pad as usize;
    let w = pen.ceil() as usize + 2 * pad as usize;
    let mut px = vec![0u8; w * h * 4];
    for (gx, gy, og) in &glyphs {
        let ox = (*gx + pad).round() as i32;
        let oy = (baseline + *gy).round() as i32;
        og.draw(|x, y, v| {
            if v <= 0.0 {
                return;
            }
            let sx = ox + x as i32;
            let sy = oy + y as i32;
            if sx < 0 || sy < 0 || sx as usize >= w || sy as usize >= h {
                return;
            }
            let i = (sy as usize * w + sx as usize) * 4;
            px[i] = color[0];
            px[i + 1] = color[1];
            px[i + 2] = color[2];
            px[i + 3] = (v * 255.0) as u8;
        });
    }
    let (pixels, width, height) = rotate90_cw(px, w, h);
    Some(Sprite {
        width,
        height,
        pixels,
    })
}

/// Rotates an RGBA buffer 90° clockwise; a WxH image becomes HxW.
fn rotate90_cw(px: Vec<u8>, w: usize, h: usize) -> (Vec<u8>, usize, usize) {
    let mut out = vec![0u8; w * h * 4];
    for y in 0..h {
        for x in 0..w {
            // dst (col = h-1-y, row = x) <- src (x, y); dst is HxW.
            let dx = h - 1 - y;
            let dy = x;
            let s = (y * w + x) * 4;
            let d = (dy * h + dx) * 4;
            out[d..d + 4].copy_from_slice(&px[s..s + 4]);
        }
    }
    (out, h, w)
}

/// Nearest-neighbor rescale of an RGBA sprite by `scale` (matches Go
/// `xdraw.NearestNeighbor.Scale`). Returns a new sprite; rounding matches Go's
/// `int(math.Round(dim*scale))` with a 1px floor.
pub fn scale_nearest(s: &Sprite, scale: f64) -> Sprite {
    let nw = ((s.width as f64) * scale).round().max(1.0) as usize;
    let nh = ((s.height as f64) * scale).round().max(1.0) as usize;
    let mut out = vec![0u8; nw * nh * 4];
    for dy in 0..nh {
        let sy = (dy * s.height / nh).min(s.height - 1);
        for dx in 0..nw {
            let sx = (dx * s.width / nw).min(s.width - 1);
            let si = (sy * s.width + sx) * 4;
            let di = (dy * nw + dx) * 4;
            out[di..di + 4].copy_from_slice(&s.pixels[si..si + 4]);
        }
    }
    Sprite {
        width: nw,
        height: nh,
        pixels: out,
    }
}
