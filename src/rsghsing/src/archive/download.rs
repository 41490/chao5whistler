//! Hour-pack downloader.
//!
//! Normative reference: `src/ghsingo/internal/archive/download.go`
//! (`base_url` + parallel workers + timeout, `.part` then rename).
//!
//! Blocking std threads only — no async runtime (Issue #104 whitelist).

use std::fs;
use std::io::Read;
use std::path::{Path, PathBuf};
use std::sync::atomic::{AtomicUsize, Ordering};
use std::time::Duration;

use anyhow::{Context, Result, bail};
use ureq::Agent;

use super::daypack::DaypackError;

pub struct DownloadOptions<'a> {
    pub base_url: &'a str,
    pub target_date: &'a str,
    pub source_dir: &'a Path,
    pub hours: &'a [usize],
    pub timeout: Duration,
    pub max_parallel: usize,
    pub user_agent: &'a str,
}

pub fn hour_file_path(source_dir: &Path, target_date: &str, hour: usize) -> PathBuf {
    source_dir.join(format!("{target_date}-{hour}.json.gz"))
}

/// Outcome of one `download_missing_hours` call.
#[derive(Debug, Default)]
pub struct DownloadReport {
    pub missing: usize,
    pub downloaded: usize,
}

/// Fetches only the hour packs that are not already on disk, `max_parallel`
/// at a time. Already-present hours are never re-fetched, which is what makes
/// a second run with the same `--hours` issue zero HTTP requests.
pub fn download_missing_hours(opts: &DownloadOptions<'_>) -> Result<DownloadReport> {
    fs::create_dir_all(opts.source_dir)
        .map_err(DaypackError::Io)
        .with_context(|| format!("mkdir source dir {}", opts.source_dir.display()))?;

    let missing: Vec<usize> = opts
        .hours
        .iter()
        .copied()
        .filter(|h| !hour_file_path(opts.source_dir, opts.target_date, *h).exists())
        .collect();

    let report = DownloadReport {
        missing: missing.len(),
        ..Default::default()
    };
    if missing.is_empty() {
        return Ok(report);
    }

    let agent = build_agent(opts.timeout, opts.user_agent);
    let next = AtomicUsize::new(0);
    let fetched = AtomicUsize::new(0);
    let failures: std::sync::Mutex<Vec<String>> = std::sync::Mutex::new(Vec::new());

    let workers = opts.max_parallel.max(1).min(missing.len());
    std::thread::scope(|scope| {
        for _ in 0..workers {
            scope.spawn(|| loop {
                // Shared cursor: each worker claims the next missing hour.
                let idx = next.fetch_add(1, Ordering::Relaxed);
                let Some(&hour) = missing.get(idx) else {
                    return;
                };
                match download_hour(&agent, opts, hour) {
                    Ok(()) => {
                        fetched.fetch_add(1, Ordering::Relaxed);
                    }
                    Err(e) => failures.lock().unwrap().push(e.to_string()),
                }
            });
        }
    });

    let failures = failures.into_inner().unwrap();
    if !failures.is_empty() {
        bail!("download failed: {}", failures.join("; "));
    }
    Ok(DownloadReport {
        downloaded: fetched.load(Ordering::Relaxed),
        ..report
    })
}

fn build_agent(timeout: Duration, user_agent: &str) -> Agent {
    let mut b = ureq::AgentBuilder::new().timeout(timeout);
    if !user_agent.is_empty() {
        b = b.user_agent(user_agent);
    }
    b.build()
}

fn download_hour(agent: &Agent, opts: &DownloadOptions<'_>, hour: usize) -> Result<()> {
    let url = format!(
        "{}/{}-{}.json.gz",
        opts.base_url.trim_end_matches('/'),
        opts.target_date,
        hour
    );
    let resp = agent
        .get(&url)
        .call()
        .with_context(|| format!("download {url}"))?;
    if resp.status() != 200 {
        bail!("download {url}: unexpected status {}", resp.status());
    }

    let path = hour_file_path(opts.source_dir, opts.target_date, hour);
    let tmp = path.with_extension("json.gz.part");
    let mut reader = resp.into_reader();
    let mut bytes = Vec::new();
    reader
        .read_to_end(&mut bytes)
        .with_context(|| format!("write {}", tmp.display()))?;
    fs::write(&tmp, &bytes)
        .map_err(DaypackError::Io)
        .with_context(|| format!("write {}", tmp.display()))?;
    fs::rename(&tmp, &path)
        .map_err(DaypackError::Io)
        .with_context(|| format!("rename {} -> {}", tmp.display(), path.display()))?;
    Ok(())
}
