//! Render dispatch: fill the water level with at most `render_jobs`
//! concurrent `render segment` children (P5, Issue #108).
//!
//! Decision baseline #12 (run in parallel with musikalisches / ng46tv) means
//! every child is reniced: `nice -n 10` + `ionice -c3`. That is done by
//! WRAPPING the child in the coreutils/util-linux binaries instead of calling
//! setpriority/ioprio_setattr ourselves — no libc binding is whitelisted, and
//! the wrapper stays visible in `ps`, so the nice level is auditable from
//! outside the process.

use std::path::{Path, PathBuf};
use std::process::{Child, Command};
use std::time::{Duration, Instant};

use anyhow::{Context, Result};

/// nice value applied to every render child (decision baseline #12).
pub const RENDER_NICE: &str = "10";
/// ionice class applied to every render child: 3 = idle.
pub const RENDER_IONICE_CLASS: &str = "3";

/// `ionice -c 3 nice -n 10` when both binaries exist, degrading gracefully: a
/// host without util-linux must still render, just without the idle I/O class.
pub fn renice_prefix() -> Vec<String> {
    let mut pre = Vec::new();
    if which("ionice") {
        pre.extend(["ionice", "-c", RENDER_IONICE_CLASS].map(String::from));
    }
    pre.extend(["nice", "-n", RENDER_NICE].map(String::from));
    pre
}

fn which(bin: &str) -> bool {
    std::env::var_os("PATH").is_some_and(|paths| {
        std::env::split_paths(&paths).any(|dir| {
            let p = dir.join(bin);
            p.is_file() && {
                use std::os::unix::fs::PermissionsExt;
                p.metadata().is_ok_and(|m| m.permissions().mode() & 0o111 != 0)
            }
        })
    })
}

/// `<root>/<date>/seg-<k>.ts` — the P3 producer's layout, D-1 keyed.
pub fn segment_path(root: &Path, date: &str, index: i64) -> PathBuf {
    root.join(date)
        .join(format!("seg-{index:02}.ts"))
}

/// Spawns one reniced `render segment` child for ready index `k`.
pub fn spawn_render(
    bin: &Path,
    config: &Path,
    segments_root: &Path,
    date: &str,
    index: i64,
) -> Result<Child> {
    let pre = renice_prefix();
    let mut cmd = Command::new(&pre[0]);
    cmd.args(&pre[1..]);
    cmd.arg(bin)
        .arg("--config")
        .arg(config)
        .arg("render")
        .arg("segment")
        .arg("--index")
        .arg(index.to_string())
        .arg("--out")
        .arg(segment_path(segments_root, date, index));
    cmd.spawn()
        .with_context(|| format!("spawn render segment {index}"))
}

/// Drains `pending`, never running more than `limit` children at once.
///
/// The daemon has nothing else to do while the queue drains, so a 250 ms
/// `try_wait` poll is the cheapest correct thing. A failing child is fatal:
/// silently skipping a segment would put a hole in the relay, and the water
/// level would report a level it does not actually have.
pub fn dispatch<S>(
    pending: &[i64],
    limit: usize,
    mut spawn: S,
) -> Result<Vec<(i64, f64)>>
where
    S: FnMut(i64) -> Result<Child>,
{
    let limit = limit.max(1);
    let mut live: Vec<(i64, Child, Instant)> = Vec::new();
    let mut next = 0usize;
    let mut done: Vec<(i64, f64)> = Vec::with_capacity(pending.len());

    while next < pending.len() || !live.is_empty() {
        while next < pending.len() && live.len() < limit {
            let k = pending[next];
            next += 1;
            tracing::info!(
                "render dispatch idx={k} slots={}/{}",
                live.len() + 1,
                limit
            );
            live.push((k, spawn(k)?, Instant::now()));
        }
        std::thread::sleep(Duration::from_millis(250));
        let mut i = 0;
        while i < live.len() {
            match live[i].1.try_wait() {
                Ok(Some(status)) => {
                    let (k, _child, started) = live.remove(i);
                    let secs = started.elapsed().as_secs_f64();
                    if status.success() {
                        tracing::info!("render done idx={k} secs={secs:.1} slots={}", live.len());
                        done.push((k, secs));
                    } else {
                        anyhow::bail!("render segment idx={k} exited with {status} after {secs:.1}s");
                    }
                }
                Ok(None) => i += 1,
                Err(e) => anyhow::bail!("wait render idx={}: {e}", live[i].0),
            }
        }
    }
    Ok(done)
}

#[cfg(test)]
mod tests {
    use super::*;

    /// Fake child: appends "+" on start, "-" on exit, so the caller can
    /// reconstruct the true peak concurrency of the dispatch loop.
    fn marker_child(dir: &Path, index: i64) -> Result<Child> {
        Command::new("sh")
            .arg("-c")
            .arg(format!(
                "echo + >> {d}/marks; sleep 0.25; echo - >> {d}/marks",
                d = dir.display()
            ))
            .env("MARKER_INDEX", index.to_string())
            .spawn()
            .context("spawn marker child")
    }

    fn peak_concurrency(dir: &Path) -> i32 {
        let text = std::fs::read_to_string(dir.join("marks")).unwrap_or_default();
        let (mut live, mut peak) = (0, 0);
        for c in text.chars() {
            if c == '+' {
                live += 1;
                peak = peak.max(live);
            } else if c == '-' {
                live -= 1;
            }
        }
        peak
    }

    #[test]
    fn dispatch_never_exceeds_render_jobs() {
        let dir = std::env::temp_dir().join("rsghsing-sched-queue");
        let _ = std::fs::remove_dir_all(&dir);
        std::fs::create_dir_all(&dir).unwrap();
        let pending: Vec<i64> = (0..6).collect();

        let done = dispatch(&pending, 2, |k| marker_child(&dir, k)).unwrap();

        assert_eq!(done.len(), 6, "every pending index was rendered");
        let peak = peak_concurrency(&dir);
        assert_eq!(peak, 2, "peak concurrency must be exactly render_jobs");
        // Same loop with a single slot stays serial.
        let dir1 = std::env::temp_dir().join("rsghsing-sched-queue1");
        let _ = std::fs::remove_dir_all(&dir1);
        std::fs::create_dir_all(&dir1).unwrap();
        dispatch(&pending, 1, |k| marker_child(&dir1, k)).unwrap();
        assert_eq!(peak_concurrency(&dir1), 1);
    }

    #[test]
    fn renice_prefix_always_nices_and_ionices_when_available() {
        let pre = renice_prefix();
        if which("ionice") {
            assert_eq!(pre, ["ionice", "-c", "3", "nice", "-n", "10"]);
        } else {
            assert_eq!(pre, ["nice", "-n", "10"]);
        }
    }
}
