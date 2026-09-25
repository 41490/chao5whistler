//! `rsghsing stream` — long-running wall-clock-aligned relay (P4, Issue #107).
//!
//! Decision baseline #1 (UTC): wall now T plays D-1's segment
//! `idx = floor(seconds_of_day(T) / 900)`. The pump writes that segment's
//! bytes at realtime pace into ONE persistent
//! `ffmpeg -f mpegts -i pipe:0 -c copy -f flv <target>` (decision baseline #3,
//! zero transcode). Session switches happen only on a dead output: backoff,
//! respawn, resume the current segment at the wall-clock position.

pub mod ffmpeg;
pub mod pump;
pub mod schedule;

use std::path::Path;
use std::sync::atomic::{AtomicBool, Ordering};
use std::time::{Duration, Instant};

use anyhow::{bail, Context, Result};

use crate::config::Config;

pub struct Args<'a> {
    /// Injected wall clock: epoch seconds or `2026-03-28T11:00:00Z`.
    pub now: Option<&'a str>,
    /// Overrides `[output].mode` for this run: `local` | `rtmps`.
    pub output: Option<&'a str>,
    /// Local `.flv` output (mode=local).
    pub local_path: Option<&'a Path>,
    /// Overrides `[stream].segments_dir`.
    pub segments_dir: Option<&'a str>,
    /// Stop after N seconds of wall time (soak/preflight harness affordance).
    pub duration: Option<f64>,
    /// ffmpeg stderr log (redacted); default = inherited stderr.
    pub ffmpeg_log: Option<&'a Path>,
}

/// Set by the SIGINT/SIGTERM handler; the pump checks it between chunks so the
/// output file gets its trailer instead of being truncated.
static STOP: AtomicBool = AtomicBool::new(false);

extern "C" fn on_signal(_sig: std::os::raw::c_int) {
    STOP.store(true, Ordering::SeqCst);
}

extern "C" {
    #[link_name = "signal"]
    fn libc_signal(signum: std::os::raw::c_int, handler: usize) -> usize;
}

/// std exposes no signal API and no signal crate is whitelisted, so we take
/// glibc's `signal()` directly. The handler only stores an AtomicBool, which
/// is async-signal-safe.
fn install_signal_handlers() {
    const SIGINT: std::os::raw::c_int = 2;
    const SIGTERM: std::os::raw::c_int = 15;
    unsafe {
        libc_signal(SIGINT, on_signal as *const () as usize);
        libc_signal(SIGTERM, on_signal as *const () as usize);
    }
}

/// Parses `--now`: bare epoch seconds, or `YYYY-MM-DDTHH:MM:SSZ` (a space is
/// accepted instead of `T`). No timezone maths: the spec is UTC by definition.
pub fn parse_now(spec: &str) -> Result<i64> {
    let s = spec.trim();
    if let Ok(n) = s.parse::<i64>() {
        return Ok(n);
    }
    let (d, t) = s
        .split_once(['T', ' '])
        .with_context(|| format!("expected <epoch> or YYYY-MM-DDTHH:MM:SSZ, got {spec:?}"))?;
    let dp: Vec<&str> = d.split('-').collect();
    let tp: Vec<&str> = t.trim_end_matches(['Z', 'z']).split(':').collect();
    if dp.len() != 3 || !(2..=3).contains(&tp.len()) {
        bail!("expected YYYY-MM-DDTHH:MM:SSZ, got {spec:?}");
    }
    let y: i64 = dp[0].parse().context("bad year")?;
    let mo: u32 = dp[1].parse().context("bad month")?;
    let da: u32 = dp[2].parse().context("bad day")?;
    let h: i64 = tp[0].parse().context("bad hour")?;
    let mi: i64 = tp[1].parse().context("bad minute")?;
    let se: i64 = if tp.len() == 3 {
        tp[2].parse().context("bad second")?
    } else {
        0
    };
    if !(1..=12).contains(&mo) || !(1..=31).contains(&da) {
        bail!("date out of range: {spec:?}");
    }
    if !(0..24).contains(&h) || !(0..60).contains(&mi) || !(0..60).contains(&se) {
        bail!("clock out of range: {spec:?}");
    }
    Ok(crate::config::days_from_civil(y, mo, da) * 86_400 + h * 3600 + mi * 60 + se)
}

/// Long-running entry point: resolve the target, then pump until the deadline
/// or a signal, restarting ffmpeg with backoff if the session dies.
pub fn run(cfg: &Config, args: &Args) -> Result<()> {
    let mode = args.output.unwrap_or(cfg.output.mode.as_str());
    let target = match mode {
        "local" => {
            let p = args
                .local_path
                .ok_or_else(|| anyhow::anyhow!("--local-path <path.flv> required in local mode"))?;
            ffmpeg::Target::Local(p.to_path_buf())
        }
        "rtmps" => {
            if cfg.output.rtmps.url.is_empty() {
                bail!("output.rtmps.url required in rtmps mode (see rsghsing.local.toml)");
            }
            ffmpeg::Target::Rtmps(cfg.output.rtmps.url.clone())
        }
        other => bail!("output mode must be \"local\" or \"rtmps\", got {other:?}"),
    };
    // The RTMPS URL is the only secret in play; it is never logged, only used
    // to scrub ffmpeg's own output.
    let secret = match &target {
        ffmpeg::Target::Rtmps(u) => u.clone(),
        ffmpeg::Target::Local(_) => String::new(),
    };
    let dir = args
        .segments_dir
        .or({
            if cfg.stream.segments_dir.is_empty() {
                None
            } else {
                Some(cfg.stream.segments_dir.as_str())
            }
        })
        .ok_or_else(|| {
            anyhow::anyhow!("no segments dir: pass --segments-dir or set [stream].segments_dir")
        })?;

    install_signal_handlers();
    let clock = pump::Clock::new(match &args.now {
        Some(s) => parse_now(s)?,
        None => std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .map(|d| d.as_secs() as i64)
            .unwrap_or(0),
    });
    let pcfg = pump::Cfg {
        dir: std::path::Path::new(&dir),
        chunk: cfg.stream.chunk_bytes,
        missing_poll: Duration::from_secs_f64(cfg.stream.missing_poll_secs.max(0.05)),
        stop_after: args.duration.map(Duration::from_secs_f64),
    };
    let started = Instant::now();
    let mut stats = pump::Stats::default();
    let mut restarts = 0u32;
    let backoff_cap = Duration::from_secs_f64(cfg.stream.restart_backoff_max_secs.max(1.0));

    let outcome = loop {
        let mut session =
            ffmpeg::Session::spawn(&cfg.stream.ffmpeg_path, &target, args.ffmpeg_log, &secret)?;
        match pump::run(&pcfg, &clock, session.stdin(), &STOP, &mut stats) {
            Ok(o) => {
                match session.finish() {
                    Ok(()) => {}
                    // ffmpeg exits non-zero on an empty input; say what actually
                    // happened instead of leaking an exit status.
                    Err(e) if stats.bytes == 0 => {
                        bail!("no segment bytes pumped ({e}); no segment became ready")
                    }
                    Err(e) => return Err(e),
                }
                break o;
            }
            Err(e) => {
                // Only intended cause: the output died (network drop). Backoff,
                // respawn, and resume the current segment at the wall-clock
                // position (the pump recomputes it from the clock).
                restarts += 1;
                let backoff =
                    Duration::from_secs_f64(2f64.powi(i32::try_from(restarts).unwrap_or(5).min(5)))
                        .min(backoff_cap);
                tracing::warn!(
                    "ffmpeg session lost ({e}); restart #{restarts} after {backoff:?}, \
                     resuming the current segment"
                );
                session.abort();
                let until = Instant::now() + backoff;
                while Instant::now() < until && !STOP.load(Ordering::SeqCst) {
                    std::thread::sleep(Duration::from_millis(20));
                }
                if STOP.load(Ordering::SeqCst) {
                    break pump::Outcome::Signal;
                }
            }
        }
    };

    let wall = started.elapsed().as_secs_f64();
    let outcome = match outcome {
        pump::Outcome::Deadline => "deadline",
        pump::Outcome::Signal => "signal",
    };
    println!(
        "STREAM_SUMMARY outcome={outcome} wall_secs={wall:.2} segments={} boundaries={} \
         bytes={} missing_waits={} missing_secs={:.1} restarts={restarts}",
        stats.segments, stats.boundaries, stats.bytes, stats.missing_waits, stats.missing_secs
    );
    tracing::info!(
        "stream done ({outcome}) wall={wall:.1}s segments={} boundaries={} bytes={} \
         missing_waits={} restarts={restarts}",
        stats.segments,
        stats.boundaries,
        stats.bytes,
        stats.missing_waits
    );
    Ok(())
}
