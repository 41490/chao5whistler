//! JSON-lines metrics for `rsghsing sched` (P5, Issue #108).
//!
//! One line per tick, appended to `--metrics-file` AND echoed to stdout (the
//! systemd unit sends stdout to the journal, so both sinks stay in sync).
//! serde_json is already a dependency; hand-rolling the escaping would be
//! strictly more code and strictly less correct.

use std::fs::OpenOptions;
use std::io::Write;
use std::path::Path;

use serde_json::{json, Value};

/// One tick's observation. Everything the operator needs to judge the water
/// level without reading the segment directory by hand.
#[derive(Default)]
pub struct Tick {
    pub epoch: i64,
    /// Playing date (D-1).
    pub date: String,
    /// Ready window indices.
    pub ready: Vec<i64>,
    /// Ready indices with no file on disk.
    pub missing: Vec<i64>,
    /// Indices dispatched this tick.
    pub dispatched: Vec<i64>,
    /// Render seconds per finished index.
    pub rendered: Vec<(i64, f64)>,
    /// Paths removed by the retention sweep.
    pub removed: Vec<String>,
    pub freed_bytes: u64,
    /// Cumulative counters since daemon start.
    pub rendered_total: u64,
    pub removed_total: u64,
    /// Segment files currently on disk for the playing date.
    pub on_disk: usize,
    /// Seconds of lead time the ready window currently covers.
    pub lead_secs: i64,
}

pub struct Sink {
    file: Option<std::fs::File>,
}

impl Sink {
    pub fn new(path: Option<&Path>) -> Sink {
        let file = path.and_then(|p| {
            if let Some(parent) = p.parent() {
                let _ = std::fs::create_dir_all(parent);
            }
            OpenOptions::new().create(true).append(true).open(p).ok()
        });
        Sink { file }
    }

    /// Writes one JSON line to both sinks; a broken metrics file never takes
    /// the daemon down (it is observability, not control flow).
    pub fn emit(&mut self, t: &Tick) {
        let line = to_json(t).to_string();
        println!("{line}");
        if let Some(f) = self.file.as_mut() {
            let _ = writeln!(f, "{line}");
            let _ = f.flush();
        }
    }
}

/// The tick as a JSON object (the one-line-per-tick record).
pub fn to_json(t: &Tick) -> Value {
    json!({
        "ts": t.epoch,
        "utc": utc_stamp(t.epoch),
        "date": t.date,
        "ready": t.ready,
        "missing": t.missing,
        "dispatched": t.dispatched,
        "rendered": t.rendered.iter()
            .map(|(k, s)| json!({"index": k, "secs": (s * 10.0).round() / 10.0}))
            .collect::<Vec<_>>(),
        "removed": t.removed,
        "freed_bytes": t.freed_bytes,
        "rendered_total": t.rendered_total,
        "removed_total": t.removed_total,
        "on_disk": t.on_disk,
        "lead_secs": t.lead_secs,
    })
}

/// `YYYY-MM-DDTHH:MM:SSZ` from an epoch second (UTC, decision baseline #1).
pub fn utc_stamp(epoch: i64) -> String {
    let days = epoch.div_euclid(86_400);
    let sod = epoch.rem_euclid(86_400);
    let (y, m, d) = crate::config::civil_from_days(days);
    format!(
        "{y:04}-{m:02}-{d:02}T{:02}:{:02}:{:02}Z",
        sod / 3600,
        (sod % 3600) / 60,
        sod % 60
    )
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn utc_stamp_is_iso_utc() {
        assert_eq!(utc_stamp(1_774_782_429), "2026-03-29T11:07:09Z");
        assert_eq!(utc_stamp(0), "1970-01-01T00:00:00Z");
        assert_eq!(utc_stamp(86_399), "1970-01-01T23:59:59Z");
    }

    #[test]
    fn tick_serialises_as_one_flat_json_line() {
        let t = Tick {
            epoch: 1_774_782_429,
            date: "2026-03-28".into(),
            ready: vec![44, 45, 46, 47, 48],
            missing: vec![46],
            dispatched: vec![46],
            rendered: vec![(46, 421.37)],
            removed: vec!["/s/2026-03-27".into()],
            freed_bytes: 1_234,
            rendered_total: 3,
            removed_total: 1,
            on_disk: 4,
            lead_secs: 3600,
        };
        let line = to_json(&t).to_string();
        assert!(!line.contains('\n'), "one line per tick");
        let v: Value = serde_json::from_str(&line).unwrap();
        assert_eq!(v["utc"], "2026-03-29T11:07:09Z");
        assert_eq!(v["date"], "2026-03-28");
        assert_eq!(v["ready"][4], 48);
        assert_eq!(v["missing"][0], 46);
        assert_eq!(v["rendered"][0]["secs"], 421.4);
        assert_eq!(v["on_disk"], 4);
        assert_eq!(v["rendered_total"], 3);
    }
}
