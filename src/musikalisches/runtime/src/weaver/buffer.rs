//! Buffer depth accounting and backpressure thresholds.
//!
//! The buffer itself is not a separate data structure: the published records in
//! the weaver ledger *are* the buffer. This module owns the policy (target
//! depth, low-water mark) and the depth observations the throughput report
//! needs.

use anyhow::{bail, Result};

/// Issue #62 approved decision 4: initial pool depth `N = 3`.
pub const DEFAULT_DEPTH_TARGET: usize = 3;
/// Issue #62 approved decision 4: refill is triggered below depth 2.
pub const DEFAULT_LOW_WATER: usize = 2;

#[derive(Debug, Clone, PartialEq)]
pub struct BufferStats {
    pub depth_target: usize,
    pub low_water: usize,
    pub min_depth: usize,
    pub max_depth: usize,
    pub samples: Vec<usize>,
}

impl BufferStats {
    pub fn new(depth_target: usize, low_water: usize) -> Self {
        Self {
            depth_target,
            low_water,
            min_depth: usize::MAX,
            max_depth: 0,
            samples: Vec::new(),
        }
    }

    pub fn observe(&mut self, depth: usize) {
        self.min_depth = self.min_depth.min(depth);
        self.max_depth = self.max_depth.max(depth);
        self.samples.push(depth);
    }

    /// `None` until the first observation; keeps an empty run from reporting a
    /// `usize::MAX` sentinel as a real minimum.
    pub fn min_depth_or_zero(&self) -> usize {
        if self.min_depth == usize::MAX {
            0
        } else {
            self.min_depth
        }
    }
}

#[derive(Debug, Clone)]
pub struct Buffer {
    depth_target: usize,
    low_water: usize,
    stats: BufferStats,
}

impl Buffer {
    pub fn new(depth_target: usize, low_water: usize) -> Result<Self> {
        if low_water > depth_target {
            bail!("--low-water ({low_water}) must be <= --buffer-depth ({depth_target})");
        }
        Ok(Self {
            depth_target,
            low_water,
            stats: BufferStats::new(depth_target, low_water),
        })
    }

    pub fn depth_target(&self) -> usize {
        self.depth_target
    }

    pub fn low_water(&self) -> usize {
        self.low_water
    }

    pub fn observe(&mut self, depth: usize) {
        self.stats.observe(depth);
    }

    pub fn stats(&self) -> &BufferStats {
        &self.stats
    }

    /// Producer is behind: keep rendering until the pool is back to target depth.
    pub fn needs_refill(&self, depth: usize) -> bool {
        depth < self.depth_target
    }

    /// Backpressure signal: the pool is below the low-water mark.
    pub fn is_low(&self, depth: usize) -> bool {
        depth < self.low_water
    }

    pub fn missing_slots(&self, depth: usize) -> usize {
        self.depth_target.saturating_sub(depth)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn rejects_low_water_above_target() {
        assert!(Buffer::new(2, 3).is_err());
    }

    #[test]
    fn thresholds_match_issue_62_decisions() {
        let buffer = Buffer::new(DEFAULT_DEPTH_TARGET, DEFAULT_LOW_WATER).unwrap();
        assert_eq!(buffer.depth_target(), 3);
        assert_eq!(buffer.low_water(), 2);
        assert!(buffer.needs_refill(2));
        assert!(!buffer.needs_refill(3));
        assert!(buffer.is_low(1));
        assert!(!buffer.is_low(2));
        assert_eq!(buffer.missing_slots(1), 2);
        assert_eq!(buffer.missing_slots(5), 0);
    }

    #[test]
    fn stats_track_min_and_max_depth() {
        let mut buffer = Buffer::new(3, 2).unwrap();
        for depth in [0, 3, 1, 2] {
            buffer.observe(depth);
        }
        let stats = buffer.stats();
        assert_eq!(stats.min_depth_or_zero(), 0);
        assert_eq!(stats.max_depth, 3);
        assert_eq!(stats.samples, vec![0, 3, 1, 2]);
    }

    #[test]
    fn stats_without_samples_report_zero_minimum() {
        let stats = BufferStats::new(3, 2);
        assert_eq!(stats.min_depth_or_zero(), 0);
        assert_eq!(stats.max_depth, 0);
    }
}
