//! Throughput measurement and the "can we actually stay live?" verdict.
//!
//! Issue #62 decision 7 is a hard gate: the weaver must *measure* stage5+stage6
//! generation throughput against asset playback throughput, and if generation
//! cannot keep up it has to say "cannot sustain live" instead of hiding the
//! shortfall behind repeated combinations.

use serde::{Deserialize, Serialize};

use super::buffer::BufferStats;
use super::jsonio;
use super::ledger::FailureSummary;

pub const THROUGHPUT_REPORT_STAGE: &str = "weaver_throughput_report_v1";
pub const EXIT_REPORT_STAGE: &str = "weaver_exit_report_v1";

pub const VERDICT_SUSTAINABLE: &str = "can_sustain_live";
pub const VERDICT_UNSUSTAINABLE: &str = "cannot_sustain_live";
pub const VERDICT_INSUFFICIENT: &str = "insufficient_samples";

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct ThroughputReport {
    pub stage: String,
    pub work_id: String,
    pub adapter_id: String,
    pub generated_assets: u64,
    pub consumed_assets: u64,
    pub generation_seconds: f64,
    pub generation_assets_per_minute: f64,
    pub playback_seconds: f64,
    pub playback_assets_per_minute: f64,
    /// Real-time demand implied by the asset durations themselves (60s / mean
    /// asset duration), for context next to the measured playback rate.
    pub required_playback_assets_per_minute: f64,
    pub mean_asset_duration_seconds: f64,
    pub buffer_depth_target: usize,
    pub low_water: usize,
    pub buffer_depth_min: usize,
    pub buffer_depth_max: usize,
    pub buffer_depth_samples: Vec<usize>,
    pub distinct_consumed_combination_ids: Vec<String>,
    pub checkpointed_records: usize,
    pub failed_records: usize,
    pub recovered_records: usize,
    pub sustainable_live: bool,
    pub verdict: String,
    pub notes: Vec<String>,
    pub recorded_at: String,
}

#[derive(Debug, Clone)]
pub struct ThroughputInput {
    pub work_id: String,
    pub adapter_id: String,
    pub generated_assets: u64,
    pub generation_seconds: f64,
    pub consumed_assets: u64,
    pub playback_seconds: f64,
    pub consumed_asset_duration_seconds: f64,
    pub stats: BufferStats,
    pub distinct_consumed_combination_ids: Vec<String>,
    pub checkpointed_records: usize,
    pub failed_records: usize,
    pub recovered_records: usize,
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct ExitReport {
    pub stage: String,
    pub work_id: String,
    pub adapter_id: String,
    pub adapter_steps: Vec<String>,
    pub exit_class: String,
    pub exit_code: i32,
    pub message: String,
    pub recorded_at: String,
    pub throughput_report_path: String,
    pub buffer_depth: usize,
    pub generated_assets: u64,
    pub consumed_assets: u64,
    pub recovered_records: usize,
    pub failed_records: Vec<FailureSummary>,
}

fn rate_per_minute(count: u64, seconds: f64) -> f64 {
    if count == 0 || seconds <= 0.0 {
        return 0.0;
    }
    jsonio::round6(count as f64 / seconds * 60.0)
}

pub fn build_throughput_report(input: ThroughputInput) -> ThroughputReport {
    let generation_rate = rate_per_minute(input.generated_assets, input.generation_seconds);
    let playback_rate = rate_per_minute(input.consumed_assets, input.playback_seconds);
    let mean_duration = if input.consumed_assets == 0 {
        0.0
    } else {
        jsonio::round6(input.consumed_asset_duration_seconds / input.consumed_assets as f64)
    };
    let required_rate = if mean_duration > 0.0 {
        jsonio::round6(60.0 / mean_duration)
    } else {
        0.0
    };

    let mut notes = Vec::new();
    let (sustainable_live, verdict) = if generation_rate <= 0.0 || playback_rate <= 0.0 {
        notes.push(
            "insufficient samples: both a generation rate and a measured playback rate are needed \
             for the live-sustain verdict"
                .to_string(),
        );
        (true, VERDICT_INSUFFICIENT.to_string())
    } else if generation_rate < playback_rate {
        notes.push(format!(
            "cannot sustain live: generation throughput {generation_rate} combinations/min is below \
             playback throughput {playback_rate} assets/min; the weaver refuses to mask the shortfall \
             with repeated combinations"
        ));
        (false, VERDICT_UNSUSTAINABLE.to_string())
    } else {
        notes.push(format!(
            "generation throughput {generation_rate} combinations/min covers playback throughput \
             {playback_rate} assets/min"
        ));
        (true, VERDICT_SUSTAINABLE.to_string())
    };
    if required_rate > 0.0 {
        notes.push(format!(
            "real-time playback demand for a {mean_duration}s asset is {required_rate} assets/min"
        ));
    }

    ThroughputReport {
        stage: THROUGHPUT_REPORT_STAGE.to_string(),
        work_id: input.work_id,
        adapter_id: input.adapter_id,
        generated_assets: input.generated_assets,
        consumed_assets: input.consumed_assets,
        generation_seconds: jsonio::round6(input.generation_seconds),
        generation_assets_per_minute: generation_rate,
        playback_seconds: jsonio::round6(input.playback_seconds),
        playback_assets_per_minute: playback_rate,
        required_playback_assets_per_minute: required_rate,
        mean_asset_duration_seconds: mean_duration,
        buffer_depth_target: input.stats.depth_target,
        low_water: input.stats.low_water,
        buffer_depth_min: input.stats.min_depth_or_zero(),
        buffer_depth_max: input.stats.max_depth,
        buffer_depth_samples: input.stats.samples,
        distinct_consumed_combination_ids: input.distinct_consumed_combination_ids,
        checkpointed_records: input.checkpointed_records,
        failed_records: input.failed_records,
        recovered_records: input.recovered_records,
        sustainable_live,
        verdict,
        notes,
        recorded_at: jsonio::utc_now(),
    }
}

pub fn write_throughput_report(path: &std::path::Path, report: &ThroughputReport) -> anyhow::Result<()> {
    jsonio::write_json_atomic(path, report)
}

pub fn write_exit_report(path: &std::path::Path, report: &ExitReport) -> anyhow::Result<()> {
    jsonio::write_json_atomic(path, report)
}

#[cfg(test)]
mod tests {
    use super::*;
    use super::super::buffer::BufferStats;

    fn input(generated: u64, generation_seconds: f64, consumed: u64, playback_seconds: f64) -> ThroughputInput {
        let mut stats = BufferStats::new(3, 2);
        stats.observe(1);
        stats.observe(3);
        stats.observe(2);
        ThroughputInput {
            work_id: "mozart_dicegame_print_1790s".to_string(),
            adapter_id: "test".to_string(),
            generated_assets: generated,
            generation_seconds,
            consumed_assets: consumed,
            playback_seconds,
            consumed_asset_duration_seconds: consumed as f64 * 0.5,
            stats,
            distinct_consumed_combination_ids: vec!["1,2,3".to_string()],
            checkpointed_records: consumed as usize,
            failed_records: 0,
            recovered_records: 0,
        }
    }

    #[test]
    fn reports_throughputs_and_buffer_depth_bounds() {
        let report = build_throughput_report(input(3, 30.0, 3, 60.0));
        assert_eq!(report.generation_assets_per_minute, 6.0);
        assert_eq!(report.playback_assets_per_minute, 3.0);
        assert_eq!(report.buffer_depth_min, 1);
        assert_eq!(report.buffer_depth_max, 3);
        assert_eq!(report.buffer_depth_target, 3);
        assert_eq!(report.low_water, 2);
        assert_eq!(report.mean_asset_duration_seconds, 0.5);
        assert_eq!(report.required_playback_assets_per_minute, 120.0);
        assert!(report.sustainable_live);
        assert_eq!(report.verdict, VERDICT_SUSTAINABLE);
    }

    #[test]
    fn flags_cannot_sustain_live_when_generation_lags() {
        let report = build_throughput_report(input(1, 60.0, 3, 60.0));
        assert!(!report.sustainable_live);
        assert_eq!(report.verdict, VERDICT_UNSUSTAINABLE);
        assert!(report
            .notes
            .iter()
            .any(|note| note.contains("cannot sustain live") && note.contains("repeated combinations")));
    }

    #[test]
    fn reports_insufficient_samples_without_a_playback_rate() {
        let report = build_throughput_report(input(3, 30.0, 0, 0.0));
        assert_eq!(report.verdict, VERDICT_INSUFFICIENT);
        assert!(report.sustainable_live);
        assert_eq!(report.playback_assets_per_minute, 0.0);
    }
}
