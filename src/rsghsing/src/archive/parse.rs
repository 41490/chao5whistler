//! GH Archive hour-pack parsing: filter -> bucket -> select.
//!
//! Normative references:
//!   * `src/ghsingo/internal/archive/parse.go` (filter/bucket semantics)
//!   * `src/ghsingo/internal/config/config.go` (event type IDs)

use std::collections::BTreeMap;
use std::io::{self, BufRead, BufReader};

use flate2::bufread::MultiGzDecoder;
use serde::Deserialize;

use super::daypack::{Event, Tick, TOTAL_TICKS, truncate_utf8};

/// Same table as Go `archive.EventTypeID` / `config.EventTypeID`.
pub const EVENT_TYPE_IDS: [(&str, u8); 6] = [
    ("PushEvent", 0),
    ("CreateEvent", 1),
    ("IssuesEvent", 2),
    ("PullRequestEvent", 3),
    ("ForkEvent", 4),
    ("ReleaseEvent", 5),
];

pub fn event_type_id(name: &str) -> Option<u8> {
    EVENT_TYPE_IDS
        .iter()
        .find(|(n, _)| *n == name)
        .map(|(_, id)| *id)
}

pub fn event_type_name(id: u8) -> Option<&'static str> {
    EVENT_TYPE_IDS
        .iter()
        .find(|(_, i)| *i == id)
        .map(|(n, _)| *n)
}

#[derive(Debug, Clone)]
pub struct ParsedEvent {
    pub second: i64,
    pub event_type: String,
    pub base_weight: i64,
    pub repo: String,
    pub text: String,
}

/// Minimal GH Archive JSON shape; everything else on the line is ignored.
#[derive(Debug, Deserialize)]
struct GhArchiveEvent {
    #[serde(rename = "type", default)]
    kind: String,
    #[serde(default)]
    actor: Actor,
    #[serde(default)]
    repo: Repo,
    #[serde(default)]
    created_at: String,
}

#[derive(Debug, Default, Deserialize)]
struct Actor {
    #[serde(default)]
    login: String,
}

#[derive(Debug, Default, Deserialize)]
struct Repo {
    #[serde(default)]
    name: String,
}

/// Reads gzip JSON lines, keeping only `allowed_types` with a weight.
pub fn parse_gzip_events<R: io::Read>(
    reader: R,
    allowed_types: &BTreeMap<String, bool>,
    weights: &BTreeMap<String, i64>,
) -> io::Result<Vec<ParsedEvent>> {
    let mut events = Vec::new();
    for line in BufReader::new(MultiGzDecoder::new(BufReader::new(reader))).lines() {
        let line = line?;
        let raw: GhArchiveEvent = match serde_json::from_str(&line) {
            Ok(ev) => ev,
            // Skip malformed lines rather than aborting the whole file.
            Err(_) => continue,
        };
        if !allowed_types.get(&raw.kind).copied().unwrap_or(false) {
            continue;
        }
        let Some(second) = second_of_day(&raw.created_at) else {
            continue;
        };
        let text = if raw.repo.name.is_empty() {
            raw.actor.login.clone()
        } else {
            raw.repo.name.clone()
        };
        events.push(ParsedEvent {
            second,
            event_type: raw.kind.clone(),
            base_weight: weights.get(&raw.kind).copied().unwrap_or(0),
            repo: raw.repo.name,
            text: truncate_utf8(&text, super::daypack::MAX_TEXT_LEN).to_string(),
        });
    }
    Ok(events)
}

/// Distributes events into 86 400 second-slots, dedupes the same repo within
/// `dedupe_window_secs`, keeps up to `max_per_sec` per slot (highest weight
/// first) and normalises weights to 0-255.
///
/// The sort MUST be `gosort::sort_like_go`: Go's `sort.Slice` is unstable, and
/// events that tie on (second, base_weight) — the common case — are ordered by
/// pdqsort's permutation, which decides which repos win a slot when the
/// per-second cap or the dedup window bites. A stable sort gives a different
/// (still self-consistent) day-pack; see gosort.rs for the measurement.
pub fn bucket_and_select(
    mut events: Vec<ParsedEvent>,
    max_per_sec: usize,
    dedupe_window_secs: i64,
) -> Vec<Tick> {
    crate::gosort::sort_like_go(&mut events, &|a, b| {
        a.second != b.second && a.second < b.second || a.second == b.second && a.base_weight > b.base_weight
    });

    let mut buckets: Vec<Vec<ParsedEvent>> = vec![Vec::new(); TOTAL_TICKS];
    for ev in events {
        if ev.second < 0 || ev.second >= TOTAL_TICKS as i64 {
            continue;
        }
        buckets[ev.second as usize].push(ev);
    }

    let mut repo_last_seen: BTreeMap<String, i64> = BTreeMap::new();
    let mut global_max = 1;
    for bucket in &buckets {
        for ev in bucket {
            if ev.base_weight > global_max {
                global_max = ev.base_weight;
            }
        }
    }

    let mut ticks = vec![Tick::default(); TOTAL_TICKS];
    for (sec, bucket) in buckets.iter().enumerate() {
        let sec = sec as i64;
        let mut selected: Vec<Event> = Vec::with_capacity(max_per_sec);
        for ev in bucket {
            if selected.len() >= max_per_sec {
                break;
            }
            if let Some(last) = repo_last_seen.get(&ev.repo) {
                if sec - last < dedupe_window_secs {
                    continue;
                }
            }
            repo_last_seen.insert(ev.repo.clone(), sec);
            let Some(type_id) = event_type_id(&ev.event_type) else {
                continue;
            };
            selected.push(Event {
                type_id,
                // 0-255 normalisation, integer division like Go.
                weight: (ev.base_weight * 255 / global_max) as u8,
                text: ev.text.clone(),
            });
        }
        ticks[sec as usize].events = selected;
    }
    ticks
}

/// Second-of-day in UTC. Accepts RFC3339 (with `Z`/offset) and the bare
/// `2006-01-02T15:04:05` form Go falls back to.
pub fn second_of_day(ts: &str) -> Option<i64> {
    let b = ts.as_bytes();
    if b.len() < 19 {
        return None;
    }
    // Fixed ASCII separators; a non-ASCII byte simply fails the comparison,
    // so this never panics on multi-byte input.
    if b[4] != b'-' || b[7] != b'-' || b[10] != b'T' || b[13] != b':' || b[16] != b':' {
        return None;
    }
    let digits = |s: &str| -> Option<i64> { s.parse().ok() };
    let (y, m, d) = (digits(&ts[0..4])?, digits(&ts[5..7])?, digits(&ts[8..10])?);
    let (hh, mm, ss) = (digits(&ts[11..13])?, digits(&ts[14..16])?, digits(&ts[17..19])?);
    let mut epoch = days_from_civil(y, m as u32, d as u32) * 86_400 + hh * 3600 + mm * 60 + ss;
    let rest = &ts[19..];
    if let Some(off) = parse_offset(rest) {
        epoch -= off;
    }
    Some(epoch.rem_euclid(86_400))
}

/// Returns the UTC offset in seconds for the substring after the seconds field.
fn parse_offset(rest: &str) -> Option<i64> {
    let rest = rest.trim_start();
    if rest.is_empty() {
        return None; // bare "2006-01-02T15:04:05" is UTC, like Go's fallback.
    }
    if let Some(f) = rest.strip_prefix('.') {
        let end = f.find(|c: char| !c.is_ascii_digit()).unwrap_or(f.len());
        return parse_offset(&f[end..]);
    }
    let rest = rest.trim_start();
    if rest.starts_with('Z') || rest.starts_with('z') {
        return Some(0);
    }
    let sign = match rest.as_bytes().first()? {
        b'+' => 1,
        b'-' => -1,
        _ => return None,
    };
    // Accept "+02:00", "+0200" and "+02"; the separator is optional.
    let digits: String = rest[1..].chars().filter(|c| c.is_ascii_digit()).collect();
    if digits.len() == 4 {
        let h: i64 = digits[0..2].parse().ok()?;
        let m: i64 = digits[2..4].parse().ok()?;
        return Some(sign * (h * 3600 + m * 60));
    }
    None
}

/// Inverse of `civil_from_days`; shared shape with `config::days_from_civil`.
pub fn days_from_civil(y: i64, m: u32, d: u32) -> i64 {
    let y = if m <= 2 { y - 1 } else { y };
    let era = if y >= 0 { y } else { y - 399 } / 400;
    let yoe = y - era * 400;
    let mp = i64::from(if m > 2 { m - 3 } else { m + 9 });
    let doy = (153 * mp + 2) / 5 + i64::from(d) - 1;
    let doe = yoe * 365 + yoe / 4 - yoe / 100 + doy;
    era * 146_097 + doe - 719_468
}

#[cfg(test)]
mod tests {
    use super::*;
    use flate2::write::GzEncoder;
    use flate2::Compression;

    fn allowed(names: &[&str]) -> BTreeMap<String, bool> {
        names.iter().map(|n| (n.to_string(), true)).collect()
    }

    fn weights() -> BTreeMap<String, i64> {
        [
            ("PushEvent", 30),
            ("CreateEvent", 40),
            ("IssuesEvent", 50),
            ("PullRequestEvent", 70),
            ("ForkEvent", 80),
            ("ReleaseEvent", 100),
        ]
        .iter()
        .map(|(k, v)| (k.to_string(), *v))
        .collect()
    }

    fn gz(lines: &[String]) -> Vec<u8> {
        let mut enc = GzEncoder::new(Vec::new(), Compression::default());
        use std::io::Write;
        for l in lines {
            enc.write_all(l.as_bytes()).unwrap();
            enc.write_all(b"\n").unwrap();
        }
        enc.finish().unwrap()
    }

    fn line(id: &str, kind: &str, repo: &str, at: &str) -> String {
        format!(
            r#"{{"id":"{id}","type":"{kind}","actor":{{"login":"actor-{id}"}},"repo":{{"name":"{repo}"}},"created_at":"{at}","payload":{{"size":1}}}}"#
        )
    }

    #[test]
    fn parses_filters_and_weights() {
        let lines = vec![
            line("1", "PushEvent", "o/r", "2026-03-28T11:00:01Z"),
            line("2", "WatchEvent", "o/r", "2026-03-28T11:00:02Z"), // not allowed
            line("3", "ReleaseEvent", "o/rel", "2026-03-28T11:00:03Z"),
            "{ this is not json".to_string(), // malformed, skipped
        ];
        let evs = parse_gzip_events(gz(&lines).as_slice(), &allowed(&["PushEvent", "ReleaseEvent"]), &weights()).unwrap();
        assert_eq!(evs.len(), 2);
        assert_eq!(evs[0].event_type, "PushEvent");
        assert_eq!(evs[0].base_weight, 30);
        assert_eq!(evs[0].second, 11 * 3600 + 1);
        assert_eq!(evs[0].text, "o/r");
        assert_eq!(evs[1].base_weight, 100);
    }

    #[test]
    fn text_falls_back_to_actor_when_repo_missing() {
        let l = r#"{"id":"9","type":"PushEvent","actor":{"login":"octocat"},"created_at":"2026-03-28T11:00:09Z"}"#;
        let evs = parse_gzip_events(gz(&[l.to_string()]).as_slice(), &allowed(&["PushEvent"]), &weights()).unwrap();
        assert_eq!(evs[0].text, "octocat");
        assert_eq!(evs[0].repo, "");
    }

    #[test]
    fn second_of_day_handles_offsets_and_bare_form() {
        assert_eq!(second_of_day("2026-03-28T11:00:01Z"), Some(11 * 3600 + 1));
        assert_eq!(second_of_day("2026-03-28T11:00:01"), Some(11 * 3600 + 1));
        // +02:00 means the UTC second-of-day is two hours earlier.
        assert_eq!(second_of_day("2026-03-28T11:00:01+02:00"), Some(9 * 3600 + 1));
        assert_eq!(second_of_day("2026-03-28T00:30:00-01:00"), Some(3600 + 1800));
        assert_eq!(second_of_day("2026-03-28T11:00:01.250Z"), Some(11 * 3600 + 1));
        assert_eq!(second_of_day("nonsense"), None);
        assert_eq!(second_of_day(""), None);
    }

    fn ev(sec: i64, kind: &str, repo: &str) -> ParsedEvent {
        ParsedEvent {
            second: sec,
            event_type: kind.to_string(),
            base_weight: weights()[kind],
            repo: repo.to_string(),
            text: repo.to_string(),
        }
    }

    #[test]
    fn buckets_cap_per_second_and_normalise_weights() {
        // 5 pushes in one second, 4 distinct repos -> 4 kept, weight 255.
        let events: Vec<ParsedEvent> = (0..5)
            .map(|i| ev(60, "PushEvent", &format!("o/r{i}")))
            .collect();
        let ticks = bucket_and_select(events, 4, 600);
        assert_eq!(ticks.len(), TOTAL_TICKS);
        assert_eq!(ticks[60].events.len(), 4);
        assert!(ticks[60].events.iter().all(|e| e.weight == 255));
        assert_eq!(ticks[60].events[0].type_id, 0);
        // A heavier type in the same second wins the slots first.
        let ticks = bucket_and_select(
            vec![ev(60, "PushEvent", "o/a"), ev(60, "ReleaseEvent", "o/b"), ev(60, "ForkEvent", "o/c")],
            1,
            600,
        );
        assert_eq!(ticks[60].events.len(), 1);
        assert_eq!(ticks[60].events[0].type_id, 5); // ReleaseEvent, weight 100
        assert_eq!(ticks[60].events[0].weight, 255);
    }

    #[test]
    fn dedupes_same_repo_within_window() {
        let ticks = bucket_and_select(
            vec![ev(10, "PushEvent", "o/r"), ev(20, "PushEvent", "o/r"), ev(700, "PushEvent", "o/r")],
            4,
            600,
        );
        assert_eq!(ticks[10].events.len(), 1);
        assert_eq!(ticks[20].events.len(), 0); // 10s later, inside the 600s window
        assert_eq!(ticks[700].events.len(), 1); // 690s after the last hit, outside
    }

    #[test]
    fn out_of_range_seconds_are_dropped() {
        let ticks = bucket_and_select(
            vec![ev(-5, "PushEvent", "o/a"), ev(TOTAL_TICKS as i64, "PushEvent", "o/b"), ev(1, "PushEvent", "o/c")],
            4,
            600,
        );
        assert_eq!(ticks[1].events.len(), 1);
    }
}
