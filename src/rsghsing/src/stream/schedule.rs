//! Wall clock -> segment mapping for `rsghsing stream` (P4, Issue #107).
//!
//! Decision baseline #1 (UTC): wall now T plays D-1's segment
//! `idx = floor(seconds_of_day(T) / 900)`, i.e. yesterday HH:MM:SS maps onto
//! today HH:MM:SS. Everything here is a pure function of an epoch second so
//! `--now` makes the whole schedule deterministic under test.

use std::path::{Path, PathBuf};

/// Seconds per segment (15 min, decision baseline #4).
pub const SEGMENT_SECS: i64 = 900;
/// Segments per UTC day.
pub const SEGMENTS_PER_DAY: i64 = 86_400 / SEGMENT_SECS;
/// MPEG-TS packet size; byte seeks are snapped down to this boundary.
pub const TS_PACKET: u64 = 188;

/// `idx = floor(seconds_of_day(T) / 900)`, clamped to 0..=95.
pub fn segment_index(epoch: i64) -> i64 {
    let idx = epoch.rem_euclid(86_400) / SEGMENT_SECS;
    debug_assert!(idx < SEGMENTS_PER_DAY, "idx {idx} out of 0..={SEGMENTS_PER_DAY}");
    idx
}

/// Offset of T inside its own segment (0..900).
pub fn offset_in_segment(epoch: i64) -> i64 {
    epoch.rem_euclid(SEGMENT_SECS)
}

/// Epoch of the segment boundary at or before T.
pub fn segment_start(epoch: i64) -> i64 {
    epoch.div_euclid(SEGMENT_SECS) * SEGMENT_SECS
}

/// Daypack date played at T: D-1 in UTC. At 00:00:00 UTC this flips to the
/// new D-1, so idx 0 of a fresh daypack starts playing (cross-day rule).
pub fn play_date(epoch: i64) -> String {
    crate::config::ymd(epoch.div_euclid(86_400) - 1)
}

/// `seg-<idx>.ts` (two digits, matching the P3 producer).
pub fn segment_name(idx: i64) -> String {
    format!("seg-{idx:02}.ts")
}

/// Full path of the segment playing at T.
pub fn segment_path(dir: &Path, epoch: i64) -> PathBuf {
    dir.join(play_date(epoch)).join(segment_name(segment_index(epoch)))
}

/// Byte offset inside a segment for wall time T: the TS packet boundary at or
/// before T's fractional position, 0 when T sits on the segment boundary.
/// Used to start (or resume) mid-segment without falling behind the wall
/// clock; `-c copy` means no decode happens, so a mid-GOP cut is harmless.
pub fn byte_offset(epoch: i64, size: u64) -> u64 {
    if size == 0 {
        return 0;
    }
    let raw = u128::from(offset_in_segment(epoch) as u64) * u128::from(size)
        / u128::from(SEGMENT_SECS as u64);
    ((raw / u128::from(TS_PACKET)) * u128::from(TS_PACKET)) as u64
}

#[cfg(test)]
mod tests {
    use super::*;

    /// 2026-03-28T00:00:00Z = the daypack/segment date the P3 set was built from.
    const D: i64 = 1_774_656_000;
    /// Wall clock one day later: at this instant the pump plays D-1 = 2026-03-28.
    const NEXT: i64 = D + 86_400;

    #[test]
    fn boundary_table_maps_seconds_of_day_to_index() {
        // 23:59:55 -> idx 95 (last segment of the day).
        assert_eq!(segment_index(D + 86_395), 95);
        assert_eq!(segment_index(D + 86_399), 95);
        // 00:00:00 -> idx 0.
        assert_eq!(segment_index(D), 0);
        assert_eq!(segment_index(D + 900), 1);
        // Same clock on the NEXT day wraps back to idx 0.
        assert_eq!(segment_index(D + 86_400), 0);
        assert_eq!(segment_index(NEXT + 86_395), 95);
        assert_eq!(segment_index(NEXT + 89_999), 3); // 00:59:59 of the day after
        for idx in 0..SEGMENTS_PER_DAY {
            let t = D + idx * SEGMENT_SECS;
            assert_eq!(segment_index(t), idx, "idx {idx}");
            assert_eq!(segment_index(t + SEGMENT_SECS - 1), idx, "idx {idx} tail");
        }
    }

    #[test]
    fn offset_within_segment_and_segment_start() {
        assert_eq!(offset_in_segment(D), 0);
        assert_eq!(offset_in_segment(D + 86_395), 895); // 23:59:55
        assert_eq!(offset_in_segment(D + 86_400), 0);
        assert_eq!(offset_in_segment(D + 600), 600);
        assert_eq!(segment_start(D + 86_395), D + 85_500);
        assert_eq!(segment_start(D + 600), D);
    }

    #[test]
    fn cross_day_midnight_plays_the_new_d_minus_one_idx0() {
        // T = 2026-03-29T00:00:00Z -> D-1 flips to 2026-03-28, idx 0.
        assert_eq!(play_date(NEXT), "2026-03-28");
        assert_eq!(segment_index(NEXT), 0);
        // One second earlier: still 2026-03-27's own last segment.
        assert_eq!(play_date(D + 86_399), "2026-03-27");
        assert_eq!(segment_index(D + 86_399), 95);
    }

    #[test]
    fn segment_paths_and_byte_offset_are_packet_aligned() {
        // Wall 2026-03-29T11:00:00Z -> D-1 2026-03-28, seg-44 (the P3 set).
        let t = NEXT + 11 * 3600;
        assert_eq!(segment_index(t), 44);
        assert_eq!(segment_path(Path::new("/seg"), t), Path::new("/seg/2026-03-28/seg-44.ts"));
        // On the boundary the pump starts at the segment head.
        assert_eq!(byte_offset(t, 309_704_056), 0);
        // Mid-segment: 10 min into a 15 min segment -> ~2/3 of the file,
        // snapped DOWN to a 188-byte TS packet boundary.
        let mid = t + 600;
        let off = byte_offset(mid, 309_704_056);
        let expect = 309_704_056u64 * 600 / 900;
        assert!(off <= expect && expect - off < TS_PACKET, "off={off} expect={expect}");
        assert_eq!(off % TS_PACKET, 0);
        assert_eq!(byte_offset(mid, 0), 0); // empty file guard
    }
}
