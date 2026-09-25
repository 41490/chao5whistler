//! Paced byte pump for `rsghsing stream` (P4, Issue #107).
//!
//! Feeds the bytes of the D-1 segment that the wall clock selects into the
//! persistent ffmpeg session at realtime pace (decision baseline #3: zero
//! transcode, the bytes ARE the stream). Segment switch = the next segment's
//! first byte continues the same pipe: P3 segments carry absolute PTS plus a
//! discontinuity flag, so byte concatenation is seamless (P0-D3, P3 verified).
//!
//! A missing segment is waited for (warn + metric), never skipped — the water
//! level is P5's business, not the streamer's.

use std::fs::File;
use std::io::{Read, Seek, SeekFrom, Write};
use std::path::Path;
use std::sync::atomic::{AtomicBool, Ordering};
use std::time::{Duration, Instant};

use anyhow::{bail, Context, Result};

use super::schedule;

/// Injectable wall clock: anchored at `base_epoch`, advancing with real time.
/// `--now` only moves the anchor, which makes every boundary decision
/// deterministic under test without any clock abstraction in production.
pub struct Clock {
    base_epoch: i64,
    base: Instant,
}

impl Clock {
    pub fn new(base_epoch: i64) -> Self {
        Clock {
            base_epoch,
            base: Instant::now(),
        }
    }

    /// Virtual wall clock, whole seconds.
    pub fn now(&self) -> i64 {
        self.base_epoch + self.base.elapsed().as_secs() as i64
    }

    /// Monotonic instant at which the virtual wall clock will read `epoch`.
    pub fn instant_at(&self, epoch: i64) -> Instant {
        self.base + Duration::from_secs((epoch - self.base_epoch).max(0) as u64)
    }

    /// "HH:MM:SS" of the virtual wall clock, for logs.
    pub fn clock_str(&self) -> String {
        let s = self.now().rem_euclid(86_400);
        format!("{:02}:{:02}:{:02}", s / 3600, s / 60 % 60, s % 60)
    }
}

/// Why the pump stopped.
pub enum Outcome {
    /// `--duration` elapsed (harness stop).
    Deadline,
    /// SIGINT/SIGTERM (daemon stop).
    Signal,
}

#[derive(Default)]
pub struct Stats {
    pub segments: u64,
    /// Segment switches actually crossed while pumping.
    pub boundaries: u64,
    pub bytes: u64,
    pub missing_waits: u64,
    pub missing_secs: f64,
}

pub struct Cfg<'a> {
    pub dir: &'a Path,
    pub chunk: usize,
    pub missing_poll: Duration,
    pub stop_after: Option<Duration>,
}

/// Sleeps until `deadline` in short slices so a stop request lands quickly.
fn sleep_until(deadline: Instant, stop: &AtomicBool) {
    while !stop.load(Ordering::SeqCst) {
        let now = Instant::now();
        if now >= deadline {
            return;
        }
        std::thread::sleep((deadline - now).min(Duration::from_millis(20)));
    }
}

/// Runs until the deadline, a signal, or a write error (broken session).
pub fn run<W: Write>(
    cfg: &Cfg,
    clock: &Clock,
    sink: &mut W,
    stop: &AtomicBool,
    stats: &mut Stats,
) -> Result<Outcome> {
    let start = Instant::now();
    let mut buf = vec![0u8; cfg.chunk.max(4096)];
    let mut last_idx: Option<i64> = None;

    loop {
        if stop.load(Ordering::SeqCst) {
            return Ok(Outcome::Signal);
        }
        if let Some(d) = cfg.stop_after {
            if start.elapsed() >= d {
                return Ok(Outcome::Deadline);
            }
        }
        let t = clock.now();
        let idx = schedule::segment_index(t);
        let path = schedule::segment_path(cfg.dir, t);
        if !path.exists() {
            // Requested window over: stop instead of warning about a segment
            // we were never going to play.
            if let Some(d) = cfg.stop_after {
                if start.elapsed() >= d {
                    return Ok(Outcome::Deadline);
                }
            }
            // Wait for the segment to become ready: warn + metric, no skip.
            stats.missing_waits += 1;
            tracing::warn!(
                "segment missing; waiting for it to become ready (no skip) {}",
                path.display()
            );
            let wait = match cfg.stop_after {
                Some(d) => cfg
                    .missing_poll
                    .min(d.saturating_sub(start.elapsed()).max(Duration::from_millis(20))),
                None => cfg.missing_poll,
            };
            let t0 = Instant::now();
            sleep_until(t0 + wait, stop);
            stats.missing_secs += t0.elapsed().as_secs_f64();
            continue;
        }

        let size = std::fs::metadata(&path)
            .with_context(|| format!("stat {}", path.display()))?
            .len();
        if size == 0 {
            bail!("segment {} is empty", path.display());
        }
        let mut f = File::open(&path).with_context(|| format!("open {}", path.display()))?;
        // Mid-segment start/resume: jump to the wall-clock position, snapped
        // down to a TS packet boundary (0 on a boundary).
        let skip = schedule::byte_offset(t, size);
        f.seek(SeekFrom::Start(skip))
            .with_context(|| format!("seek {}", path.display()))?;
        if let Some(prev) = last_idx {
            if prev != idx {
                stats.boundaries += 1;
            }
        }
        last_idx = Some(idx);
        stats.segments += 1;
        tracing::info!(
            "segment start idx={} date={} wall_utc={} skip_bytes={}",
            idx,
            schedule::play_date(t),
            clock.clock_str(),
            skip
        );

        let seg_epoch = schedule::segment_start(t);
        let mut done = skip;
        loop {
            if stop.load(Ordering::SeqCst) {
                return Ok(Outcome::Signal);
            }
            if let Some(d) = cfg.stop_after {
                if start.elapsed() >= d {
                    return Ok(Outcome::Deadline);
                }
            }
            let n = f.read(&mut buf).context("read segment")?;
            if n == 0 {
                break; // segment fully pumped; the outer loop picks the next one
            }
            if let Err(e) = sink.write_all(&buf[..n]) {
                return Err(anyhow::anyhow!("ffmpeg write failed: {e}"));
            }
            stats.bytes += n as u64;
            done += n as u64;
            // Wall-clock pace: bytes_written/size of the segment maps onto the
            // same fraction of its 900s window. Behind schedule -> no sleep.
            // ponytail: byte-fraction pacing assumes ~CBR segments (P3 is
            // 2501k/130k CBR); a VBR segment would drift. Swap for PTS-driven
            // pacing if that ever changes.
            let frac = (u128::from(done) * u128::from(schedule::SEGMENT_SECS as u64)
                / u128::from(size)) as i64;
            sleep_until(clock.instant_at(seg_epoch + frac), stop);
        }
    }
}
