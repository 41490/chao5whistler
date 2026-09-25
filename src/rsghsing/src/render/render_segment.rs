//! `rsghsing render segment --index N` — P3 offline segment producer (#106).
//!
//! Segment `k` covers D-1 UTC `[k*900s, (k+1)*900s)` (decision baseline #1).
//! Renders 900s of video (30fps 720p h264 2500k, solid-bg event floaters) and
//! audio (P2 engine -> aac 128k), muxes them into an MPEG-TS segment with
//! ABSOLUTE PTS and a per-segment discontinuity flag (P0-D3), and writes a
//! per-event manifest for daypack cross-check.

use std::io::Write;
use std::path::Path;
use std::process::{Command, Stdio};

use anyhow::{bail, Context, Result};

use super::{
    build_engine, collect_window_events, find_latest_daypack, source_window_for_render_second,
    to_composer_events,
};
use crate::archive::daypack::{Daypack, Event as PackEvent};
use crate::archive::parse::event_type_name;
use crate::config::Config;
use crate::video::{self, Renderer, SEGMENT_FPS};

/// Seconds per segment (15 min, decision baseline #4).
pub const SEGMENT_SECS: i32 = 900;

pub struct Args<'a> {
    pub index: i32,
    pub out: &'a Path,
}

/// Segment `k` covers D-1 UTC seconds `[k*900, (k+1)*900)` (decision baseline #1).
pub fn segment_window(index: i32) -> (i32, i32) {
    (index * SEGMENT_SECS, (index + 1) * SEGMENT_SECS)
}

/// One event as recorded in the manifest (the daypack cross-check contract).
struct ManifestEvent {
    type_name: String,
    daypack_tick: i32,
    offset_ms: i64,
    end_x: i32,
    end_y: i32,
    color: String,
}

/// Renders `[ws, we)` of daypack audio (realtime) to a raw f32le stereo file
/// via the P2 engine. Returns the temp path; caller removes it.
fn render_audio_f32le(
    cfg: &Config,
    pack: &Daypack,
    ws: i32,
    seed: i64,
    audio_path: &Path,
) -> Result<()> {
    let dur = f64::from(SEGMENT_SECS);
    let mut engine = build_engine(cfg, seed)?;
    let sample_rate = cfg.audio.sample_rate;
    let fps = cfg.video.fps;
    let total_frames = (dur * f64::from(fps)) as i64;
    let mut buf: Vec<u8> = Vec::with_capacity((sample_rate as usize) * 4 * 2);
    let mut last_window = i32::MIN;
    for f in 0..total_frames {
        let rs = (f / i64::from(fps)) as i32;
        let (w0, w1) = source_window_for_render_second(ws, 1.0, rs);
        if w0 != last_window {
            last_window = w0;
            let evs = collect_window_events(pack, w0, w1);
            engine.apply_events_for_second(&to_composer_events(&evs));
        }
        let samples = engine.render_frame();
        for s in &samples {
            buf.extend_from_slice(&s.to_le_bytes());
        }
    }
    std::fs::write(audio_path, &buf)?;
    Ok(())
}

/// Spawns the segment ffmpeg: rawvideo RGBA on stdin + f32le audio file ->
/// libx264/aac MPEG-TS with absolute PTS (`-output_ts_offset ws`) and a
/// per-segment discontinuity flag (P0-D3). No B-frames keep DTS monotonic so
/// byte-concatenated segments decode cleanly.
fn spawn_ffmpeg(cfg: &Config, trim_samples: i64, audio_path: &Path, out: &Path) -> Result<std::process::Child> {
    let p = video::resolve_params(&cfg.video);
    Command::new("ffmpeg")
        .args([
            "-f", "rawvideo", "-pix_fmt", "rgba", "-s",
            &format!("{}x{}", p.width, p.height),
            "-r", &SEGMENT_FPS.to_string(), "-i", "pipe:0",
        ])
        .args([
            "-f", "f32le", "-ar", &cfg.audio.sample_rate.to_string(), "-ac", "2",
            "-i", &audio_path.to_string_lossy(),
        ])
        .args(["-map", "0:v", "-map", "1:a"])
        .args(["-af", &format!("aresample=async=1:first_pts=0,atrim=end_sample={trim_samples}")])
        .args([
            "-c:v", "libx264", "-preset", "veryfast",
            "-b:v", "2500k", "-maxrate", "2500k", "-bufsize", "2500k",
            "-g", "60", "-pix_fmt", "yuv420p", "-bf", "0",
            "-x264-params", "nal-hrd=cbr:force-cfr=1",
        ])
        .args(["-c:a", "aac", "-b:a", "128k"])
        .args(["-avoid_negative_ts", "make_zero", "-muxdelay", "0", "-muxpreload", "0"])
        .args([
            "-f", "mpegts", "-mpegts_flags", "+initial_discontinuity+resend_headers",
        ])
        .arg(out)
        .stdin(Stdio::piped())
        .stderr(Stdio::inherit())
        .stdout(Stdio::null())
        .spawn()
        .context("spawn ffmpeg")
}

fn color_hex(c: video::Rgba) -> String {
    format!("#{:02x}{:02x}{:02x}", c.r, c.g, c.b)
}

/// Re-mux the clean (PTS-from-0) segment onto its absolute timeline and stamp a
/// per-segment discontinuity. A plain `-c copy` preserves the monotonic DTS from
/// the clean stage and only shifts it by `offset` (no avoid_negative_ts to cancel
/// it), so byte-concat stays monotonic (P0-D3).
fn remux_absolute(clean: &Path, offset: i32, out: &Path) -> Result<()> {
    let status = Command::new("ffmpeg")
        .args(["-y", "-v", "error"])
        .arg("-i")
        .arg(clean)
        .args(["-c", "copy"])
        .args([
            "-mpegts_flags",
            "+initial_discontinuity+resend_headers",
            "-output_ts_offset",
            &format!("{offset}"),
        ])
        .arg(out)
        .status()
        .context("spawn ffmpeg remux")?;
    if !status.success() {
        bail!("ffmpeg remux exited with {status}");
    }
    Ok(())
}

pub fn run(cfg: &Config, args: &Args<'_>) -> Result<()> {
    let index = args.index;
    if index < 0 || index > 95 {
        bail!("segment index {index} out of range 0..=95");
    }
    let (ws, we) = segment_window(index);

    let (daypack_path, date_str) = find_latest_daypack(Path::new(&cfg.archive.daypack_dir))?;
    let pack = Daypack::read(&daypack_path)?;
    if pack.ticks.is_empty() {
        bail!("daypack {} has no ticks", daypack_path.display());
    }

    // Events in [ws, we) in tick order, each carrying its absolute daypack tick.
    let mut events: Vec<(i32, PackEvent)> = Vec::new();
    for tick in ws..we {
        let idx = tick.rem_euclid(pack.ticks.len() as i32) as usize;
        for ev in &pack.ticks[idx].events {
            events.push((tick, ev.clone()));
        }
    }

    if let Some(parent) = args.out.parent() {
        if !parent.as_os_str().is_empty() {
            std::fs::create_dir_all(parent)?;
        }
    }
    let audio_path = args.out.with_extension("f32");
    let manifest_path = args.out.with_extension("manifest.json");

    // Audio: P2 engine renders [ws, we) realtime to a raw f32le temp file.
    render_audio_f32le(cfg, &pack, ws, cfg.composer.seed, &audio_path)?;

    // Trim audio to a whole number of AAC frames strictly below the segment end so
    // the padded last frame cannot overrun into the next segment on concat.
    let trim_samples = (i64::from(SEGMENT_SECS) * i64::from(cfg.audio.sample_rate) / 1024) * 1024;

    // Video: solid-bg event floaters, streamed as RGBA into ffmpeg stdin (clean,
    // PTS from 0), then re-muxed onto the absolute [ws, we) timeline.
    let params = video::resolve_params(&cfg.video);
    let mut renderer = Renderer::new(params, SEGMENT_FPS, 0x51ed_1060 ^ index as u64);
    let clean = args.out.with_extension("clean.tmp");
    let mut child = spawn_ffmpeg(cfg, trim_samples, &audio_path, &clean)?;
    let mut stdin = child.stdin.take().context("ffmpeg stdin pipe")?;

    let total_frames = u64::from(SEGMENT_FPS) * u64::from(SEGMENT_SECS as u32);
    let fps_u = u64::from(SEGMENT_FPS);
    let mut next_ev = 0usize;
    let mut manifest_events: Vec<ManifestEvent> = Vec::with_capacity(events.len());
    for f in 0..total_frames {
        if f % fps_u == 0 {
            let s = (f / fps_u) as i32; // local second within the segment
            while next_ev < events.len() && events[next_ev].0 - ws <= s {
                let (tick, ev) = &events[next_ev];
                let color = renderer.color_for(ev.type_id);
                let (ex, ey) = renderer
                    .spawn(&ev.text, ev.type_id, ev.weight)
                    .map(|i| (i.end_x, i.end_y))
                    .unwrap_or((0, 0));
                manifest_events.push(ManifestEvent {
                    type_name: event_type_name(ev.type_id).unwrap_or("Unknown").to_string(),
                    daypack_tick: *tick,
                    offset_ms: i64::from(*tick - ws) * 1000,
                    end_x: ex,
                    end_y: ey,
                    color: color_hex(color),
                });
                next_ev += 1;
            }
        }
        let frame = renderer.render_frame();
        if stdin.write_all(frame).is_err() {
            break;
        }
    }
    drop(stdin);
    let status = child.wait().context("ffmpeg wait")?;
    if !status.success() {
        bail!("ffmpeg exited with {status}");
    }
    remux_absolute(&clean, ws, args.out)?;
    let _ = std::fs::remove_file(&clean);
    let _ = std::fs::remove_file(&audio_path);

    write_manifest(&manifest_path, index, &date_str, ws, we, &manifest_events)?;
    tracing::info!(
        out = %args.out.display(),
        manifest = %manifest_path.display(),
        events = manifest_events.len(),
        daypack = %date_str,
        window = format!("[{ws},{we})"),
        "segment done"
    );
    Ok(())
}

/// Writes the per-event manifest JSON (daypack cross-check contract).
fn write_manifest(
    path: &Path,
    index: i32,
    date_str: &str,
    ws: i32,
    we: i32,
    events: &[ManifestEvent],
) -> Result<()> {
    let mut j = String::with_capacity(events.len() * 96 + 512);
    j.push_str("{\n");
    j.push_str(&format!("  \"segment_index\": {index},\n"));
    j.push_str(&format!("  \"daypack_date\": \"{date_str}\",\n"));
    j.push_str(&format!("  \"window_start_sec\": {ws},\n"));
    j.push_str(&format!("  \"window_end_sec\": {we},\n"));
    j.push_str(&format!("  \"duration_secs\": {SEGMENT_SECS},\n"));
    j.push_str(&format!("  \"pts_offset_secs\": {ws},\n"));
    j.push_str(&format!("  \"event_count\": {},\n", events.len()));
    j.push_str("  \"events\": [\n");
    for (i, e) in events.iter().enumerate() {
        let comma = if i + 1 < events.len() { "," } else { "" };
        j.push_str(&format!(
            "    {{\"type\": \"{}\", \"daypack_tick\": {}, \"offset_ms\": {}, \"end_x\": {}, \"end_y\": {}, \"color\": \"{}\"}}{comma}\n",
            e.type_name, e.daypack_tick, e.offset_ms, e.end_x, e.end_y, e.color
        ));
    }
    j.push_str("  ]\n}\n");
    std::fs::write(path, j)?;
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn segment_window_maps_index_to_utc_seconds() {
        // Segment k covers D-1 UTC [k*900, (k+1)*900).
        assert_eq!(segment_window(0), (0, 900));
        assert_eq!(segment_window(44), (39_600, 40_500)); // 11:00:00
        assert_eq!(segment_window(47), (42_300, 43_200)); // 11:45:00
        assert_eq!(segment_window(95), (85_500, 86_400)); // 23:45:00
        // Contiguous, non-overlapping.
        let (_, e44) = segment_window(44);
        let (s45, _) = segment_window(45);
        assert_eq!(e44, s45);
    }
}
