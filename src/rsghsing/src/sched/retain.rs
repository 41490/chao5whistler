//! Retention sweep: the ring buffer that keeps only `retain_days` of history
//! (P5, Issue #108, decision baseline #5 "段与 raw 只保留 1 天").
//!
//! Two roots are swept with the SAME rule, because both are per-day data:
//!   * `<segments_root>/<YYYY-MM-DD>/seg-NN.ts`  (P3 segments, the relay input)
//!   * `<archive_root>/<YYYY-MM-DD>-HH.json.gz`  (raw GH Archive hour packs)
//!
//! Rule: a date is expired when it is strictly older than
//! `today - retain_days`. With `retain_days = 1` that means today and
//! yesterday survive (yesterday is what the streamer plays), everything
//! 2+ days old is deleted.
//!
//! Data-loss guard: the date currently PLAYING is never removed, whatever the
//! config says. That is what makes the 00:00 UTC rollover safe — see `sweep`.

use std::path::{Path, PathBuf};

use crate::config::{days_from_civil, ymd};

/// `today - retain_days`, in days since the epoch. Dates strictly below this
/// are expired.
pub fn retain_cutoff_days(today_days: i64, retain_days: i64) -> i64 {
    today_days - retain_days.max(0)
}

/// True when `date` is older than the retention window.
pub fn is_expired(date: &str, today_days: i64, retain_days: i64) -> bool {
    match parse_date(date) {
        Some(days) => days < retain_cutoff_days(today_days, retain_days),
        // Unparseable names are left alone: a typo must not delete data.
        None => false,
    }
}

/// `YYYY-MM-DD` -> days since the epoch; `None` for anything else.
pub fn parse_date(name: &str) -> Option<i64> {
    let parts: Vec<&str> = name.split('-').collect();
    if parts.len() != 3 {
        return None;
    }
    let y: i64 = parts[0].parse().ok()?;
    let m: u32 = parts[1].parse().ok()?;
    let d: u32 = parts[2].parse().ok()?;
    if !(1..=12).contains(&m) || !(1..=31).contains(&d) {
        return None;
    }
    Some(days_from_civil(y, m, d))
}

/// What a sweep did, for the metrics line.
#[derive(Debug, Default)]
pub struct Sweep {
    /// Paths actually removed.
    pub removed: Vec<PathBuf>,
    /// Bytes freed.
    pub freed_bytes: u64,
    /// Date dirs/files that survived (name -> why it survived).
    pub kept: Vec<String>,
}

fn dir_size(path: &Path) -> u64 {
    let mut total = 0u64;
    if let Ok(entries) = std::fs::read_dir(path) {
        for e in entries.flatten() {
            let p = e.path();
            total += match e.file_type() {
                Ok(t) if t.is_dir() => dir_size(&p),
                _ => e.metadata().map(|m| m.len()).unwrap_or(0),
            };
        }
    }
    total
}

/// Removes expired segment day-dirs and expired raw hour files.
///
/// `protected` (the date playing at `now`) is skipped even when the config
/// would expire it: the streamer is pumping that directory right now.
pub fn sweep(
    now: i64,
    retain_days: i64,
    segments_root: &Path,
    archive_root: &Path,
) -> Sweep {
    let today_days = now.div_euclid(86_400);
    let protected = ymd(today_days - 1); // play_date(now) == D-1
    let mut out = Sweep::default();

    // Segments: one directory per day.
    if let Ok(entries) = std::fs::read_dir(segments_root) {
        let mut dirs: Vec<PathBuf> = entries.flatten().map(|e| e.path()).collect();
        dirs.sort();
        for dir in dirs {
            let Some(name) = dir.file_name().map(|n| n.to_string_lossy().into_owned()) else {
                continue;
            };
            if !dir.is_dir() || !is_expired(&name, today_days, retain_days) {
                continue;
            }
            if name == protected {
                out.kept.push(format!("{name}(playing)"));
                continue;
            }
            let size = dir_size(&dir);
            match std::fs::remove_dir_all(&dir) {
                Ok(()) => {
                    out.freed_bytes += size;
                    out.removed.push(dir);
                }
                Err(e) => tracing::warn!("retain: cannot remove {}: {e}", dir.display()),
            }
        }
    }

    // Raw hour packs: flat `<date>-HH.json.gz` files.
    if let Ok(entries) = std::fs::read_dir(archive_root) {
        let mut files: Vec<PathBuf> = entries.flatten().map(|e| e.path()).collect();
        files.sort();
        for f in files {
            let Some(name) = f.file_name().map(|n| n.to_string_lossy().into_owned()) else {
                continue;
            };
            let stem = name.trim_end_matches(".json.gz");
            let Some((date_part, _hour)) = stem.rsplit_once('-') else {
                continue;
            };
            if !is_expired(date_part, today_days, retain_days) {
                continue;
            }
            if date_part == protected {
                out.kept.push(format!("{date_part}(playing)"));
                continue;
            }
            let size = f.metadata().map(|m| m.len()).unwrap_or(0);
            match std::fs::remove_file(&f) {
                Ok(()) => {
                    out.freed_bytes += size;
                    out.removed.push(f);
                }
                Err(e) => tracing::warn!("retain: cannot remove {}: {e}", f.display()),
            }
        }
    }

    out
}

#[cfg(test)]
mod tests {
    use super::*;

    /// 2026-03-29T12:00:00Z -> today = 2026-03-29, playing date = 2026-03-28.
    const NOW: i64 = 1_774_742_400;

    fn days(name: &str) -> i64 {
        parse_date(name).unwrap()
    }

    #[test]
    fn retain_one_day_keeps_today_and_yesterday() {
        let today = NOW.div_euclid(86_400);
        assert_eq!(ymd(today), "2026-03-29");
        assert_eq!(ymd(today - 1), "2026-03-28");
        // Playing date and today survive; 2 days old is deleted.
        assert!(!is_expired("2026-03-29", today, 1));
        assert!(!is_expired("2026-03-28", today, 1));
        assert!(is_expired("2026-03-27", today, 1));
        assert!(is_expired("2026-03-01", today, 1));
        // retain_days = 3 keeps a week of history.
        assert!(!is_expired("2026-03-27", today, 3));
        assert!(is_expired("2026-03-25", today, 3));
    }

    #[test]
    fn unparseable_names_are_never_expired() {
        let today = NOW.div_euclid(86_400);
        assert!(!is_expired("not-a-date", today, 1));
        assert!(!is_expired("2026-13-99", today, 1));
        assert!(!is_expired("", today, 1));
        assert!(parse_date("2026-03-28").is_some());
        assert_eq!(days("1970-01-02"), 1);
    }

    #[test]
    fn sweep_deletes_only_expired_day_dirs() {
        let root = std::env::temp_dir().join("rsghsing-sched-retain");
        let _ = std::fs::remove_dir_all(&root);
        let segs = root.join("segments");
        let raw = root.join("raw");
        for d in ["2026-03-27", "2026-03-28", "2026-03-29", "keepme"] {
            let dir = segs.join(d);
            std::fs::create_dir_all(&dir).unwrap();
            std::fs::write(dir.join("seg-00.ts"), vec![0u8; 4096]).unwrap();
        }
        std::fs::create_dir_all(&raw).unwrap();
        for f in ["2026-03-27-11.json.gz", "2026-03-28-11.json.gz", "2026-03-29-0.json.gz"] {
            std::fs::write(raw.join(f), vec![0u8; 2048]).unwrap();
        }

        let s = sweep(NOW, 1, &segs, &raw);
        // 2026-03-27 is 2 days old -> gone, from BOTH roots.
        assert!(s.removed.iter().any(|p| p.ends_with("2026-03-27")));
        assert!(!segs.join("2026-03-27").exists());
        assert!(!raw.join("2026-03-27-11.json.gz").exists());
        // The playing date (D-1) and today are untouched, as is the typo dir.
        assert!(segs.join("2026-03-28").exists());
        assert!(segs.join("2026-03-29").exists());
        assert!(segs.join("keepme").exists());
        assert!(raw.join("2026-03-28-11.json.gz").exists());
        assert!(raw.join("2026-03-29-0.json.gz").exists());
        assert_eq!(s.freed_bytes, 4096 + 2048);
    }

    #[test]
    fn sweep_never_removes_the_playing_date_even_at_retain_zero() {
        let root = std::env::temp_dir().join("rsghsing-sched-retain0");
        let _ = std::fs::remove_dir_all(&root);
        let segs = root.join("segments");
        let raw = root.join("raw");
        for d in ["2026-03-27", "2026-03-28", "2026-03-29"] {
            std::fs::create_dir_all(segs.join(d)).unwrap();
        }
        std::fs::create_dir_all(&raw).unwrap();

        // retain_days = 0 would expire yesterday too — the guard still wins.
        let s = sweep(NOW, 0, &segs, &raw);
        assert!(segs.join("2026-03-28").exists(), "playing date survived");
        assert!(!segs.join("2026-03-27").exists());
        // today is not history yet, so retain_days = 0 keeps it.
        assert!(segs.join("2026-03-29").exists());
        assert_eq!(s.kept, vec!["2026-03-28(playing)".to_string()]);
    }
}
