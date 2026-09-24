//! `rsghsing render audio` — ported from `cmd/render-audio-v2`.
//!
//! Renders `--duration` of audio starting at `--start-clock` inside the latest
//! daypack, pipes f32le stereo into ffmpeg and encodes AAC 128k to `-o`.
//! Writes the same sidecar JSON the Go tool writes, so `audio-metrics` can
//! compare the two renders (Issue #105, acceptance 3).

use std::io::Write;
use std::path::Path;
use std::process::Command;

use anyhow::{bail, Context, Result};

use super::{
    build_engine, collect_window_events, find_latest_daypack, parse_duration, parse_start_clock,
    source_window_for_render_second, to_composer_events,
};

pub struct Args<'a> {
    pub config: &'a str,
    pub start_clock: &'a str,
    pub source_span: &'a str,
    pub duration: &'a str,
    pub seed: i64,
    pub out: &'a Path,
}

pub fn run(cfg: &crate::config::Config, args: &Args<'_>) -> Result<()> {
    let dur = parse_duration(args.duration)?;
    let start_second = parse_start_clock(args.start_clock)?;
    let source_span = if args.source_span.trim().is_empty() {
        dur
    } else {
        parse_duration(args.source_span)?
    };

    let (daypack_path, date_str) = find_latest_daypack(Path::new(&cfg.archive.daypack_dir))?;
    let pack = crate::archive::daypack::Daypack::read(&daypack_path)?;
    if pack.ticks.is_empty() {
        bail!("daypack {} has no ticks", daypack_path.display());
    }

    let mut engine = build_engine(cfg, args.seed)?;
    let sample_rate = cfg.audio.sample_rate;
    let fps = cfg.video.fps;
    let total_frames = (dur * f64::from(fps)) as i64;

    if let Some(parent) = args.out.parent() {
        if !parent.as_os_str().is_empty() {
            std::fs::create_dir_all(parent)?;
        }
    }

    // ffmpeg: f32le stereo on stdin -> aac 128k on disk.
    let mut child = spawn_ffmpeg(sample_rate, args.out)?;
    let mut stdin = child.stdin.take().context("ffmpeg stdin pipe")?;

    let source_rate = source_span / dur;
    let mut last_window_start = i32::MIN;
    for f in 0..total_frames {
        let render_second = (f / i64::from(fps)) as i32;
        let (window_start, window_end) =
            source_window_for_render_second(start_second, source_rate, render_second);
        if window_start != last_window_start {
            last_window_start = window_start;
            let evs = collect_window_events(&pack, window_start, window_end);
            engine.apply_events_for_second(&to_composer_events(&evs));
        }

        let samples = engine.render_frame();
        let bytes: Vec<u8> = samples.iter().flat_map(|s| s.to_le_bytes()).collect();
        if let Err(e) = stdin.write_all(&bytes) {
            tracing::error!(err = %e, "write to ffmpeg");
            break;
        }

        let rendered = f + 1;
        if rendered % i64::from(fps) == 0 && rendered % i64::from(fps) * 5 == 0 {
            tracing::info!(rendered, target = total_frames, "v2 progress");
        }
    }

    drop(stdin);
    let status = child.wait().context("ffmpeg wait")?;
    if !status.success() {
        bail!("ffmpeg exited with {status}");
    }

    let duration_secs = total_frames as f64 / f64::from(fps);
    let accents = engine.accents;
    let eff_strike_rate = if duration_secs > 0.0 {
        accents as f64 / duration_secs
    } else {
        0.0
    };
    let last = engine.mixer.last_state();

    let sidecar = format!(
        r#"{{
  "profile": "{}",
  "engine": "rsghsing-v2",
  "config": "{}",
  "daypack_date": "{}",
  "start_second": {},
  "source_span_secs": {source_span},
  "duration_secs": {duration_secs},
  "sample_rate": {sample_rate},
  "ticks": {},
  "lead_strikes": {},
  "background_strikes": 0,
  "release_accents": 0,
  "effective_strike_rate_per_sec": {eff_strike_rate},
  "release_accent_rate_per_sec": 0,
  "final_density": {},
  "final_brightness": {},
  "section_transitions": {},
  "mode_transitions": {}
}}
"#,
        cfg.meta.profile,
        args.config,
        date_str,
        start_second,
        engine.ticks,
        accents,
        last.density,
        last.brightness,
        engine.section_transitions,
        engine.mode_transitions,
    );
    let side_path = format!("{}.metrics.json", args.out.display());
    std::fs::write(&side_path, sidecar)?;
    tracing::info!(path = %side_path, "metrics sidecar");

    tracing::info!(
        output = %args.out.display(),
        ticks = engine.ticks,
        accents,
        final_density = format!("{:.3}", last.density),
        final_brightness = format!("{:.3}", last.brightness),
        "done v2"
    );
    Ok(())
}

fn spawn_ffmpeg(sample_rate: i32, out: &Path) -> Result<std::process::Child> {
    Command::new("ffmpeg")
        .args(["-f", "f32le", "-ar"])
        .arg(sample_rate.to_string())
        .args(["-ac", "2", "-i", "pipe:0"])
        .args(["-c:a", "aac", "-b:a", "128k", "-y"])
        .arg(out)
        .stdin(std::process::Stdio::piped())
        .stderr(std::process::Stdio::inherit())
        .stdout(std::process::Stdio::null())
        .spawn()
        .context("spawn ffmpeg")
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn parses_go_style_durations() {
        assert_eq!(parse_duration("30s").unwrap(), 30.0);
        assert_eq!(parse_duration("5m").unwrap(), 300.0);
        assert_eq!(parse_duration("1h30m").unwrap(), 5400.0);
        assert_eq!(parse_duration("1500ms").unwrap(), 1.5);
        assert_eq!(parse_duration("90").unwrap(), 90.0);
        assert!(parse_duration("0s").is_err());
        assert!(parse_duration("5x").is_err());
    }

    #[test]
    fn parses_start_clock_like_go_time_parse() {
        assert_eq!(parse_start_clock("").unwrap(), 0);
        assert_eq!(parse_start_clock("14:00").unwrap(), 50_400);
        assert_eq!(parse_start_clock("16:00:00").unwrap(), 57_600);
        assert_eq!(parse_start_clock(" 00:00:01 ").unwrap(), 1);
        assert!(parse_start_clock("25:00").is_err());
        assert!(parse_start_clock("nope").is_err());
    }

    #[test]
    fn window_mapping_matches_go_source_window_for_render_second() {
        // Go: windowStart = start + floor(rs*rate); end = floor((rs+1)*rate).
        assert_eq!(source_window_for_render_second(50_400, 1.0, 0), (50_400, 50_401));
        assert_eq!(source_window_for_render_second(50_400, 12.0, 0), (50_400, 50_412));
        assert_eq!(
            source_window_for_render_second(50_400, 12.0, 1),
            (50_412, 50_424)
        );
        // Degenerate rate still advances by at least one second.
        assert_eq!(source_window_for_render_second(0, 0.0, 3), (0, 1));
    }
}
