//! Shared render helpers: daypack lookup, duration/clock parsing, window
//! mapping, engine construction.
//!
//! Ported from `cmd/render-audio-v2` (audio render + sidecar) and
//! `cmd/composer-demo` (timeline JSON). The Go `backend.Backend` seam and its
//! two implementations (`backend/gov2`, `backend/sc`) plus `internal/lifecycle`
//! are not ported: the render path calls `audio::Engine` directly. Evidence for
//! that ablation lives in the P2 report.

pub mod composer_timeline;
pub mod render_audio;

use std::path::{Path, PathBuf};

use anyhow::{bail, Context, Result};

use crate::archive::daypack::{Daypack, Event as PackEvent};
use crate::audio::bellbank::BellBank;
use crate::audio::mixer::{Engine, MixerConfig};
use crate::audio::wav;
use crate::composer::{Config as ComposerConfig, Event};

/// `findLatestDaypack`: newest `<daypack_dir>/<date>/day.bin` by name sort.
pub fn find_latest_daypack(dir: &Path) -> Result<(PathBuf, String)> {
    let mut dates = Vec::new();
    for e in std::fs::read_dir(dir).with_context(|| format!("read daypack dir {}", dir.display()))? {
        let e = e?;
        if !e.file_type()?.is_dir() {
            continue;
        }
        let name = e.file_name().to_string_lossy().into_owned();
        if e.path().join("day.bin").exists() {
            dates.push(name);
        }
    }
    if dates.is_empty() {
        bail!("no daypack found in {}", dir.display());
    }
    dates.sort();
    let latest = dates.last().unwrap().clone();
    Ok((dir.join(&latest).join("day.bin"), latest))
}

/// Parses "HH:MM" / "HH:MM:SS" into seconds-of-day. Empty -> 0.
pub fn parse_start_clock(spec: &str) -> Result<i32> {
    let spec = spec.trim();
    if spec.is_empty() {
        return Ok(0);
    }
    let parts: Vec<&str> = spec.split(':').collect();
    if parts.len() < 2 || parts.len() > 3 {
        bail!("expected HH:MM or HH:MM:SS, got {spec:?}");
    }
    let h: i32 = parts[0].parse().context("bad hour")?;
    let m: i32 = parts[1].parse().context("bad minute")?;
    let s: i32 = if parts.len() == 3 {
        parts[2].parse().context("bad second")?
    } else {
        0
    };
    if !(0..24).contains(&h) || !(0..60).contains(&m) || !(0..60).contains(&s) {
        bail!("clock out of range: {spec:?}");
    }
    Ok(h * 3600 + m * 60 + s)
}

/// Parses a Go duration string: "30s", "5m", "1h30m", "90".
pub fn parse_duration(spec: &str) -> Result<f64> {
    let spec = spec.trim();
    if spec.is_empty() {
        bail!("empty duration");
    }
    let mut total = 0.0f64;
    let mut num = String::new();
    let mut chars = spec.chars().peekable();
    while let Some(c) = chars.next() {
        if c.is_ascii_digit() || c == '.' {
            num.push(c);
            continue;
        }
        let unit = match c {
            'h' => 3600.0,
            'm' => {
                if chars.peek() == Some(&'s') {
                    chars.next();
                    0.001
                } else {
                    60.0
                }
            }
            's' => 1.0,
            other => bail!("unknown duration unit {other:?} in {spec:?}"),
        };
        let v: f64 = num.parse().with_context(|| format!("bad number in {spec:?}"))?;
        total += v * unit;
        num.clear();
    }
    if !num.is_empty() {
        total += num.parse::<f64>().with_context(|| format!("bad number in {spec:?}"))?;
    }
    if total <= 0.0 {
        bail!("duration must be positive, got {spec:?}");
    }
    Ok(total)
}

/// `sourceWindowForRenderSecond`: maps a render second onto a source window.
pub fn source_window_for_render_second(
    start_second: i32,
    source_rate: f64,
    render_second: i32,
) -> (i32, i32) {
    let window_start = start_second + (render_second as f64 * source_rate).floor() as i32;
    let mut window_end = start_second + ((render_second + 1) as f64 * source_rate).floor() as i32;
    if window_end <= window_start {
        window_end = window_start + 1;
    }
    (window_start, window_end)
}

/// `collectWindowEvents`: wraps around the day's ticks (86400 slots).
pub fn collect_window_events(pack: &Daypack, window_start: i32, window_end: i32) -> Vec<PackEvent> {
    if pack.ticks.is_empty() {
        return Vec::new();
    }
    let mut out = Vec::new();
    for second in window_start..window_end {
        let idx = second.rem_euclid(pack.ticks.len() as i32) as usize;
        out.extend(pack.ticks[idx].events.iter().cloned());
    }
    out
}

fn to_composer_events(evs: &[PackEvent]) -> Vec<Event> {
    evs.iter()
        .map(|e| Event {
            type_id: e.type_id,
            weight: e.weight,
        })
        .collect()
}

/// Builds the engine from config. Mirrors `buildGoV2Backend`.
pub fn build_engine(cfg: &crate::config::Config, seed: i64) -> Result<Engine> {
    let composer_cfg = ComposerConfig {
        ema_alpha: cfg.composer.ema_alpha,
        density_saturation: cfg.composer.density_saturation,
        brightness_saturation: cfg.composer.brightness_saturation,
        phrase_ticks: i64::from(cfg.composer.phrase_ticks),
        accent_cooldown_ticks: i64::from(cfg.composer.accent_cooldown_ticks),
        accent_base_prob: cfg.composer.accent_base_prob,
        seed: if seed != 0 { seed } else { cfg.composer.seed },
    };
    let mixer_cfg = MixerConfig {
        master_gain: cfg.mixer.master_gain,
        drone_gain: cfg.mixer.drone_gain,
        bed_gain: cfg.mixer.bed_gain,
        tonal_bed_gain: cfg.mixer.tonal_bed_gain,
        accent_gain: cfg.mixer.accent_gain,
        wet_continuous: cfg.mixer.wet_continuous,
        wet_accent: cfg.mixer.wet_accent,
        accent_max: cfg.mixer.accent_max,
    };
    let mut engine = Engine::new(cfg.audio.sample_rate, cfg.video.fps, composer_cfg, mixer_cfg);

    if !cfg.assets.accents.bank_dir.is_empty() {
        let mut bank = BellBank::new(cfg.audio.sample_rate);
        if cfg.assets.accents.synth_decay > 0.0 {
            bank.set_synth_decay(cfg.assets.accents.synth_decay);
        }
        match bank.load_from_dir(Path::new(&cfg.assets.accents.bank_dir)) {
            Ok(n) => tracing::info!(
                samples = n,
                path = cfg.assets.accents.bank_dir.as_str(),
                "accent bank loaded"
            ),
            Err(e) => tracing::warn!(
                err = %e,
                path = cfg.assets.accents.bank_dir.as_str(),
                "load accent bank"
            ),
        }
        engine.mixer.set_accent_bank(bank);
    }

    if !cfg.assets.tonal_bed.wav_path.is_empty() {
        match wav::load_wav_file(Path::new(&cfg.assets.tonal_bed.wav_path)) {
            Ok(pcm) => {
                tracing::info!(
                    samples = pcm.len(),
                    path = cfg.assets.tonal_bed.wav_path.as_str(),
                    "tonal bed loaded"
                );
                if cfg.assets.tonal_bed.gain_db != 0.0 {
                    engine
                        .mixer
                        .set_tonal_bed_gain(wav::gain_to_linear(cfg.assets.tonal_bed.gain_db));
                }
                engine.mixer.set_tonal_bed_pcm(pcm);
            }
            Err(e) => tracing::warn!(
                err = %e,
                path = cfg.assets.tonal_bed.wav_path.as_str(),
                "load tonal bed"
            ),
        }
    }
    Ok(engine)
}
