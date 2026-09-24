//! `rsghsing prepare` — download (if enabled) -> parse -> bucket -> GSIN.
//!
//! Mirrors `src/ghsingo/cmd/prepare/main.go` step for step so the two
//! binaries produce the same day-pack from the same hour packs.

use std::collections::BTreeMap;
use std::fs;
use std::path::Path;
use std::time::Duration;

use anyhow::{bail, Context, Result};
use tracing::info;

use super::daypack::Daypack;
use super::download::{download_missing_hours, hour_file_path, DownloadOptions};
use super::hours::parse_hours;
use super::parse::{bucket_and_select, parse_gzip_events};
use crate::config::{Archive, Config, Events};

pub struct PrepareArgs<'a> {
    pub date: Option<&'a str>,
    pub hours: &'a str,
}

pub fn run(cfg: &Config, args: &PrepareArgs<'_>) -> Result<()> {
    let archive: &Archive = &cfg.archive;
    let target_date = args
        .date
        .map(str::to_string)
        .unwrap_or_else(|| crate::config::resolve_target_date(&archive.target_date));
    let hours = parse_hours(args.hours)?;

    info!(
        "prepare starting profile={} target_date={} hours={:?}",
        cfg.meta.profile, target_date, hours
    );

    if archive.download.enabled {
        let report = download_missing_hours(&DownloadOptions {
            base_url: &archive.download.base_url,
            target_date: &target_date,
            source_dir: Path::new(&archive.source_dir),
            hours: &hours,
            timeout: Duration::from_secs(archive.download.timeout_secs.max(1)),
            max_parallel: archive.download.max_parallel,
            user_agent: &archive.download.user_agent,
        })?;
        info!(
            "download complete missing={} downloaded={}",
            report.missing, report.downloaded
        );
    }

    // Go: requireAll = download.enabled || hoursSpec != "" — with --hours
    // given, every requested hour must exist; without it, use what is there.
    let require_all = archive.download.enabled || !args.hours.trim().is_empty();
    let mut gz_files = Vec::new();
    let mut missing_hours = Vec::new();
    for &h in &hours {
        let path = hour_file_path(Path::new(&archive.source_dir), &target_date, h);
        if path.exists() {
            gz_files.push(path);
        } else {
            missing_hours.push(h);
        }
    }
    if require_all && !missing_hours.is_empty() {
        bail!(
            "missing required source files source_dir={} date={} hours={:?}",
            archive.source_dir,
            target_date,
            missing_hours
        );
    }
    if gz_files.is_empty() {
        bail!(
            "no .json.gz files found source_dir={} date={}",
            archive.source_dir,
            target_date
        );
    }
    info!("found source files count={}", gz_files.len());

    let mut all_events = Vec::new();
    for path in &gz_files {
        info!("parsing file={}", path.display());
        let f = fs::File::open(path).with_context(|| format!("open {}", path.display()))?;
        let events = parse_gzip_events(f, &allowed_types(&cfg.events), &cfg.events.weights)
            .with_context(|| format!("parse {}", path.display()))?;
        all_events.extend(events);
    }
    let total_events = all_events.len();
    info!("total parsed events count={}", total_events);

    let ticks = bucket_and_select(
        all_events,
        cfg.events.max_per_second,
        cfg.events.dedupe_window_secs,
    );
    let pack = Daypack::new(ymd_to_u32(&target_date), ticks);

    let out_dir = Path::new(&archive.daypack_dir).join(&target_date);
    fs::create_dir_all(&out_dir)
        .map_err(super::daypack::DaypackError::Io)
        .with_context(|| format!("mkdir {}", out_dir.display()))?;
    let bin_path = out_dir.join("day.bin");
    pack.write(&bin_path)
        .with_context(|| format!("write daypack {}", bin_path.display()))?;

    let manifest = manifest(&target_date, &hours, &gz_files, total_events, &pack);
    let manifest_path = out_dir.join("manifest.json");
    fs::write(&manifest_path, serde_json::to_vec_pretty(&manifest)?)
        .with_context(|| format!("write {}", manifest_path.display()))?;

    let kept: usize = pack.ticks.iter().map(|t| t.events.len()).sum();

    // Read the day-pack back before declaring success: a truncated or
    // half-written file must fail here, not silently at render time.
    let reread = Daypack::read(&bin_path)
        .with_context(|| format!("read back daypack {}", bin_path.display()))?;
    let reread_kept: usize = reread.ticks.iter().map(|t| t.events.len()).sum();
    if reread.date != pack.date || reread_kept != kept {
        bail!(
            "daypack verification failed for {}: wrote date={} kept={}, read back date={} kept={}",
            bin_path.display(),
            pack.date,
            kept,
            reread.date,
            reread_kept
        );
    }

    info!(
        "prepare complete daypack={} kept_events={} ticks_with_events={} verified=true",
        bin_path.display(),
        kept,
        pack.ticks.iter().filter(|t| !t.events.is_empty()).count()
    );
    Ok(())
}

fn allowed_types(events: &Events) -> BTreeMap<String, bool> {
    events.types.iter().map(|t| (t.clone(), true)).collect()
}

/// "2026-03-28" -> 20260328
fn ymd_to_u32(date: &str) -> u32 {
    date.chars()
        .filter(|c| c.is_ascii_digit())
        .collect::<String>()
        .parse()
        .unwrap_or(0)
}

fn manifest(
    target_date: &str,
    hours: &[usize],
    gz_files: &[std::path::PathBuf],
    total_events: usize,
    pack: &Daypack,
) -> serde_json::Value {
    let mut by_type: BTreeMap<String, usize> = BTreeMap::new();
    let mut kept = 0usize;
    let mut with_events = 0usize;
    for tick in &pack.ticks {
        if !tick.events.is_empty() {
            with_events += 1;
        }
        for ev in &tick.events {
            kept += 1;
            *by_type
                .entry(
                    super::parse::event_type_name(ev.type_id)
                        .unwrap_or("?")
                        .to_string(),
                )
                .or_default() += 1;
        }
    }
    serde_json::json!({
        "date": target_date,
        "total_events": total_events,
        "requested_hours": hours,
        "source_files": gz_files,
        "total_ticks": pack.ticks.len(),
        "kept_events": kept,
        "ticks_with_events": with_events,
        "empty_ticks": pack.ticks.len() - with_events,
        "by_type": by_type,
    })
}
