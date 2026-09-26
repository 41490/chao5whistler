//! `rsghsing sched` — the P5 daemon (Issue #108).
//!
//! Owns the buffer water level and NOTHING else. Per the decision baseline:
//!   * systemd owns process lifetime (the streamer is `Restart=always` in its
//!     own unit, the prepare timer fires the daypack build) — this daemon
//!     never restarts the streamer;
//!   * this daemon owns the water level, the render queue, retention and the
//!     JSON-lines metrics.
//!
//! One tick:
//!   1. plan  = [idx(now), idx(now)+buffer_segments] of D-1, minus what is on
//!      disk;
//!   2. dispatch the missing indices through the render queue (<= render_jobs
//!      concurrent, each `nice -n 10 ionice -c3`);
//!   3. sweep retention (segment dirs + raw hour packs older than
//!      retain_days) — strictly AFTER step 2, so the 00:00 UTC rollover always
//!      has the new D-1's idx0 on disk before yesterday's files go away;
//!   4. emit one metrics line.
//!
//! `--once` runs a single tick (what the chaos harness drives); the default is
//! the daemon loop the systemd unit runs.

pub mod metrics;
pub mod queue;
pub mod retain;
pub mod water;

use std::path::{Path, PathBuf};
use std::time::Duration;

use anyhow::{bail, Result};

use crate::config::Config;
use crate::stream::parse_now;

pub struct Args<'a> {
    /// Injected wall clock: epoch seconds or `2026-03-28T11:00:00Z`.
    pub now: Option<&'a str>,
    /// Override `[stream].segments_dir` (root holding `<D-1>/seg-NN.ts`).
    pub segments_dir: Option<&'a str>,
    /// Override `[archive].source_dir` (root holding `<D-1>-HH.json.gz`).
    pub archive_dir: Option<&'a str>,
    /// Tick interval in seconds (default `[sched].interval_secs`).
    pub interval: Option<f64>,
    /// Stop after N seconds of wall time.
    pub duration: Option<f64>,
    /// Run exactly one tick and exit.
    pub once: bool,
    /// Append the JSON-lines metrics here (stdout always gets them too).
    pub metrics_file: Option<&'a Path>,
}

/// Resolved wall clock: the injected `--now` stays fixed (deterministic under
/// the chaos harness), otherwise the real UTC clock is read every tick.
fn resolve_now(spec: Option<&str>) -> Result<Box<dyn Fn() -> i64>> {
    match spec {
        Some(s) => {
            let fixed = parse_now(s)?;
            Ok(Box::new(move || fixed))
        }
        None => Ok(Box::new(|| {
            std::time::SystemTime::now()
                .duration_since(std::time::UNIX_EPOCH)
                .map(|d| d.as_secs() as i64)
                .unwrap_or(0)
        })),
    }
}

pub fn run(cfg: &Config, args: &Args, bin: &Path, config_path: &Path) -> Result<()> {
    let segments_root = PathBuf::from(
        args.segments_dir
            .map_or_else(|| cfg.stream.segments_dir.clone(), String::from),
    );
    if segments_root.as_os_str().is_empty() {
        bail!("no segments dir: pass --segments-dir or set [stream].segments_dir");
    }
    let archive_root = PathBuf::from(
        args.archive_dir
            .map_or_else(|| cfg.archive.source_dir.clone(), String::from),
    );

    let interval =
        Duration::from_secs_f64(args.interval.unwrap_or(cfg.sched.interval_secs).max(0.05));
    let deadline = args
        .duration
        .map(|d| std::time::Instant::now() + Duration::from_secs_f64(d.max(0.0)));
    let clock = resolve_now(args.now)?;
    let mut sink = metrics::Sink::new(args.metrics_file);
    let mut rendered_total = 0u64;
    let mut removed_total = 0u64;
    let started = std::time::Instant::now();

    loop {
        let tick = tick(
            cfg,
            clock(),
            &segments_root,
            &archive_root,
            bin,
            config_path,
            &mut rendered_total,
            &mut removed_total,
        )?;
        sink.emit(&tick);

        if args.once {
            break;
        }
        if deadline.is_some_and(|d| std::time::Instant::now() >= d) {
            break;
        }
        std::thread::sleep(interval);
    }

    println!(
        "SCHED_SUMMARY ticks_done wall_secs={:.1} rendered_total={rendered_total} \
         removed_total={removed_total}",
        started.elapsed().as_secs_f64()
    );
    Ok(())
}

/// One water-level tick. Returns the metrics record.
fn tick(
    cfg: &Config,
    now: i64,
    segments_root: &Path,
    archive_root: &Path,
    bin: &Path,
    config_path: &Path,
    rendered_total: &mut u64,
    removed_total: &mut u64,
) -> Result<metrics::Tick> {
    let date = crate::stream::schedule::play_date(now);
    let ready = water::ready_indices(now, cfg.sched.buffer_segments);
    let day_dir = segments_root.join(&date);
    let missing = water::missing_indices(now, cfg.sched.buffer_segments, |k| {
        queue::segment_path(segments_root, &date, k).is_file()
    });
    let on_disk = std::fs::read_dir(&day_dir)
        .map(|e| {
            e.flatten()
                .filter(|e| {
                    e.path()
                        .extension()
                        .is_some_and(|x| x.eq_ignore_ascii_case("ts"))
                })
                .count()
        })
        .unwrap_or(0);

    let rendered = if missing.is_empty() {
        Vec::new()
    } else {
        queue::dispatch(&missing, cfg.sched.render_jobs, |k| {
            queue::spawn_render(bin, config_path, segments_root, &date, k)
        })?
    };
    *rendered_total += rendered.len() as u64;

    let swept = retain::sweep(now, cfg.sched.retain_days, segments_root, archive_root);
    *removed_total += swept.removed.len() as u64;

    Ok(metrics::Tick {
        epoch: now,
        date,
        ready,
        missing,
        dispatched: rendered.iter().map(|(k, _)| *k).collect(),
        rendered,
        removed: swept
            .removed
            .iter()
            .map(|p| p.display().to_string())
            .collect(),
        freed_bytes: swept.freed_bytes,
        rendered_total: *rendered_total,
        removed_total: *removed_total,
        on_disk,
        lead_secs: water::lead_secs(now, cfg.sched.buffer_segments),
    })
}
