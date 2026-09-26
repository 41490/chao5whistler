//! Buffer water level: which segments must exist right now (P5, Issue #108).
//!
//! Pure functions of an epoch second so `--now` makes the whole plan
//! deterministic under test. The segment index / play-date mapping is NOT
//! reimplemented here: it is borrowed from `stream::schedule`, so the
//! scheduler and the streamer can never disagree about which file plays at T.

use crate::stream::schedule::{segment_index, segment_start, SEGMENTS_PER_DAY, SEGMENT_SECS};

/// Segments that must exist at `now`: the closed interval
/// `[idx(now), idx(now) + buffer]`, clamped to the last segment of the day.
///
/// `buffer = 4` therefore keeps 5 files (the playing one plus 4 ahead), i.e.
/// the segment that starts exactly 4 x 15 min = 1 h from now is already on
/// disk — the "1 h lead" of the decision baseline.
pub fn ready_indices(now: i64, buffer: i64) -> Vec<i64> {
    let idx = segment_index(now);
    let end = (idx + buffer.max(0)).min(SEGMENTS_PER_DAY - 1);
    (idx..=end).collect()
}

/// Epoch second at which ready index `k` starts (may be in the future).
pub fn segment_start_epoch(now: i64, k: i64) -> i64 {
    segment_start(now) + (k - segment_index(now)) * SEGMENT_SECS
}

/// Lead time of the farthest ready segment, in seconds (1 h at buffer=4).
pub fn lead_secs(now: i64, buffer: i64) -> i64 {
    let ready = ready_indices(now, buffer);
    match (ready.first(), ready.last()) {
        (Some(&f), Some(&l)) => segment_start_epoch(now, l) - segment_start_epoch(now, f),
        _ => 0,
    }
}

/// Indices of the ready window whose segment file is absent. `exists` is the
/// only impure part, injected so the plan is testable without a filesystem.
pub fn missing_indices(now: i64, buffer: i64, exists: impl Fn(i64) -> bool) -> Vec<i64> {
    ready_indices(now, buffer)
        .into_iter()
        .filter(|k| !exists(*k))
        .collect()
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::path::Path;

    /// 2026-03-28T00:00:00Z — the daypack/segment date the P3 set was built from.
    const D: i64 = 1_774_656_000;
    /// Wall clock one day later: at this instant the pump plays D-1 = 2026-03-28.
    const NEXT: i64 = D + 86_400;

    fn at(h: i64, m: i64, s: i64) -> i64 {
        NEXT + h * 3600 + m * 60 + s
    }

    #[test]
    fn buffer_four_keeps_one_hour_of_lead() {
        let now = at(11, 0, 0); // idx 44
        assert_eq!(ready_indices(now, 4), vec![44, 45, 46, 47, 48]);
        // The farthest ready segment starts exactly 4 x 900 s = 1 h from now.
        assert_eq!(segment_start_epoch(now, 48), now + 3600);
        assert_eq!(lead_secs(now, 4), 3600);
        // buffer 0 degenerates to the playing segment only.
        assert_eq!(ready_indices(now, 0), vec![44]);
    }

    #[test]
    fn midnight_boundary_flips_to_the_new_d_minus_one_idx_zero() {
        // 00:00:00 UTC -> play date flips to the new D-1, idx 0.
        assert_eq!(ready_indices(NEXT, 4), vec![0, 1, 2, 3, 4]);
        assert_eq!(segment_start_epoch(NEXT, 0), NEXT);
        assert_eq!(
            crate::stream::schedule::segment_path(Path::new("/seg"), NEXT),
            Path::new("/seg/2026-03-28/seg-00.ts")
        );
        // One second earlier: still the old day's last segment, window clamped.
        let late = NEXT - 1;
        assert_eq!(ready_indices(late, 4), vec![95]);
        assert_eq!(crate::stream::schedule::play_date(late), "2026-03-27");
    }

    #[test]
    fn twenty_three_forty_five_clamps_the_window_to_the_last_segment() {
        // 23:45 -> idx 95; 95+4 would run off the day, so the window is [95].
        let now = at(23, 45, 0);
        assert_eq!(segment_index(now), 95);
        assert_eq!(ready_indices(now, 4), vec![95]);
        assert_eq!(ready_indices(now, 1), vec![95]);
        assert_eq!(lead_secs(now, 4), 0);
    }

    #[test]
    fn missing_plan_reports_only_absent_ready_indices() {
        let now = at(11, 0, 0);
        // seg-46 absent (the chaos scenario: a hole in the middle).
        let missing = missing_indices(now, 4, |k| k != 46);
        assert_eq!(missing, vec![46]);
        // Everything present -> nothing to render.
        assert!(missing_indices(now, 4, |_| true).is_empty());
        // Nothing present -> the whole window, in ascending order.
        assert_eq!(missing_indices(now, 4, |_| false), vec![44, 45, 46, 47, 48]);
        // A hole OUTSIDE the window is not our problem.
        assert!(missing_indices(now, 4, |k| k != 12).is_empty());
    }
}
