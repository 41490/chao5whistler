use std::path::Path;

use anyhow::{bail, Result};

use super::schema::{
    ArchiveSelector, Config, EventType, MotionMode, OutputContainer, ReplaySelectionKey,
    RuntimeClock, UnknownFieldPolicy, VoiceMode,
};

const MAX_WARN_MASTER_GAIN_DB: f64 = 6.0;
const TEMPLATE_FIELDS: [&str; 11] = [
    "repo",
    "repo_owner",
    "repo_name",
    "type",
    "actor",
    "hash",
    "id",
    "weight",
    "hour",
    "minute",
    "second",
];

pub fn validate(config: &Config) -> Result<Vec<String>> {
    let mut errors = Vec::new();
    let mut warnings = Vec::new();

    if !matches!(
        config.runtime.clock,
        RuntimeClock::RealtimeDay | RuntimeClock::Fast
    ) {
        errors.push("runtime.clock must remain one of [realtime_day, fast]".to_string());
    }

    if config.archive.selector == ArchiveSelector::FixedDay {
        if config.archive.fixed_day.trim().is_empty() {
            errors.push(
                "archive.fixed_day must be set when archive.selector = fixed_day".to_string(),
            );
        } else if !is_valid_ymd(&config.archive.fixed_day) {
            errors.push("archive.fixed_day must use YYYY-MM-DD".to_string());
        }
    } else if !config.archive.fixed_day.trim().is_empty()
        && !is_valid_ymd(&config.archive.fixed_day)
    {
        errors.push("archive.fixed_day must use YYYY-MM-DD when provided".to_string());
    }

    if config.archive.download.timeout_secs < 5 {
        errors.push("archive.download.timeout_secs must be >= 5".to_string());
    }
    if !(1..=24).contains(&config.archive.download.max_parallel) {
        errors.push("archive.download.max_parallel must be within 1..=24".to_string());
    }

    if config.replay.max_events_per_second != 4 {
        errors.push("replay.max_events_per_second is frozen to 4".to_string());
    }
    if config.replay.dedupe_window_secs != 600 {
        errors.push("replay.dedupe_window_secs is frozen to 600".to_string());
    }
    if config.replay.selection_order
        != vec![
            ReplaySelectionKey::WeightDesc,
            ReplaySelectionKey::EventIdAsc,
        ]
    {
        errors.push("replay.selection_order must remain [weight_desc, event_id_asc]".to_string());
    }

    if !(0.0..=1.0).contains(&config.fallback.density_scale) {
        errors.push("fallback.density_scale must be within 0.0..=1.0".to_string());
    }

    if config.events.primary_types != EventType::ALL.to_vec() {
        errors.push("events.primary_types must remain the frozen 10-event set".to_string());
    }
    if !(4..=16).contains(&config.events.hash_len_default) {
        errors.push("events.hash_len_default must be within 4..=16".to_string());
    }
    for event in EventType::ALL {
        match config.events.weights.get(&event) {
            Some(weight) if (1..=100).contains(weight) => {}
            Some(_) => errors.push(format!(
                "events.weights.{} must be within 1..=100",
                event.as_str()
            )),
            None => errors.push(format!("events.weights.{} is required", event.as_str())),
        }
    }

    if config.text.unknown_field_policy != UnknownFieldPolicy::Error {
        errors.push("text.unknown_field_policy must remain error".to_string());
    }
    if config.text.max_rendered_chars < 8 {
        errors.push("text.max_rendered_chars must be >= 8".to_string());
    }
    if !config.text.allow_multiline && config.text.template.contains('\n') {
        errors.push(
            "text.template must remain single-line when text.allow_multiline = false".to_string(),
        );
    }
    validate_template(&config.text.template, &mut errors);

    if config.audio.sample_rate != 48_000 {
        errors.push("audio.sample_rate is frozen to 48000".to_string());
    }
    if config.audio.channels != 2 {
        errors.push("audio.channels is frozen to 2".to_string());
    }
    if config.audio.background.enabled {
        if config.audio.background.wav_path.trim().is_empty() {
            errors.push(
                "audio.background.wav_path must be set when background audio is enabled"
                    .to_string(),
            );
        } else if !config.audio.background.wav_path.ends_with(".wav") {
            errors.push("audio.background.wav_path must end with .wav".to_string());
        }
    }

    for event in EventType::ALL {
        match config.audio.voices.get(&event) {
            Some(voice) => {
                if voice.preset.trim().is_empty() {
                    errors.push(format!(
                        "audio.voices.{}.preset must not be empty",
                        event.as_str()
                    ));
                }
                if voice.duration_ms < 50 {
                    errors.push(format!(
                        "audio.voices.{}.duration_ms must be >= 50",
                        event.as_str()
                    ));
                }
                if !(-1.0..=1.0).contains(&voice.pan) {
                    errors.push(format!(
                        "audio.voices.{}.pan must be within -1.0..=1.0",
                        event.as_str()
                    ));
                }
                if voice.mode == VoiceMode::WavSample && voice.sample_path.trim().is_empty() {
                    errors.push(format!(
                        "audio.voices.{}.sample_path must be set when mode = wav_sample",
                        event.as_str()
                    ));
                }
            }
            None => errors.push(format!("audio.voices.{} is required", event.as_str())),
        }
    }

    if config.video.canvas.width < 320 {
        errors.push("video.canvas.width must be >= 320".to_string());
    }
    if config.video.canvas.height < 240 {
        errors.push("video.canvas.height must be >= 240".to_string());
    }
    if !(1..=60).contains(&config.video.canvas.fps) {
        errors.push("video.canvas.fps must be within 1..=60".to_string());
    }
    if config.video.text.font_size_min < 4 {
        errors.push("video.text.font_size_min must be >= 4".to_string());
    }
    if config.video.text.font_size_max < 4 {
        errors.push("video.text.font_size_max must be >= 4".to_string());
    }
    if config.video.text.font_size_max < config.video.text.font_size_min {
        errors.push("video.text.font_size_max must be >= video.text.font_size_min".to_string());
    }
    if config.video.text.initial_alpha > 255 {
        errors.push("video.text.initial_alpha must be within 0..=255".to_string());
    }
    if !ratio_ok(config.video.text.bottom_spawn_min_ratio) {
        errors.push("video.text.bottom_spawn_min_ratio must be within 0.0..=1.0".to_string());
    }
    if !ratio_ok(config.video.text.bottom_spawn_max_ratio) {
        errors.push("video.text.bottom_spawn_max_ratio must be within 0.0..=1.0".to_string());
    }
    if config.video.text.bottom_spawn_max_ratio < config.video.text.bottom_spawn_min_ratio {
        errors.push(
            "video.text.bottom_spawn_max_ratio must be >= video.text.bottom_spawn_min_ratio"
                .to_string(),
        );
    }
    if config.video.motion.mode == MotionMode::RandomAngle
        && config.video.motion.random_max_deg <= config.video.motion.random_min_deg
    {
        errors
            .push("video.motion.random_max_deg must be > video.motion.random_min_deg".to_string());
    }
    if config.video.motion.speed_px_per_sec < 1.0 {
        errors.push("video.motion.speed_px_per_sec must be >= 1.0".to_string());
    }

    if config.outputs.enable_rtmp && config.outputs.rtmp.url.trim().is_empty() {
        errors
            .push("outputs.rtmp.url must be provided when outputs.enable_rtmp = true".to_string());
    }
    if config.outputs.rtmp.container != OutputContainer::Flv {
        errors.push("outputs.rtmp.container must remain flv".to_string());
    }
    if config.outputs.record.container != OutputContainer::Flv {
        errors.push("outputs.record.container must remain flv".to_string());
    }
    if config.outputs.encode.video_codec != "h264" {
        errors.push("outputs.encode.video_codec must remain h264".to_string());
    }
    if config.outputs.encode.video_preset != "ultrafast" {
        errors.push("outputs.encode.video_preset must remain ultrafast".to_string());
    }
    if config.outputs.encode.audio_bitrate_kbps != 128 {
        errors.push("outputs.encode.audio_bitrate_kbps must remain 128".to_string());
    }

    if !config.outputs.enable_rtmp && !config.outputs.enable_local_record {
        warnings.push(
            "outputs.enable_rtmp = false and outputs.enable_local_record = false".to_string(),
        );
    }
    if !config.fallback.enabled && archive_root_looks_empty(&config.archive.root_dir) {
        warnings.push(
            "fallback.enabled = false while archive.root_dir is missing or empty".to_string(),
        );
    }
    if config.audio.master_gain_db > MAX_WARN_MASTER_GAIN_DB {
        warnings.push(format!(
            "audio.master_gain_db = {:.1} dB may clip the final mix",
            config.audio.master_gain_db
        ));
    }

    if errors.is_empty() {
        Ok(warnings)
    } else {
        bail!(errors.join("\n"))
    }
}

fn validate_template(template: &str, errors: &mut Vec<String>) {
    let mut rest = template;
    while let Some(start) = rest.find('{') {
        let after_start = &rest[start + 1..];
        let Some(end) = after_start.find('}') else {
            errors.push("text.template contains an unclosed placeholder".to_string());
            return;
        };

        let placeholder = &after_start[..end];
        if placeholder.is_empty() {
            errors.push("text.template contains an empty placeholder".to_string());
            return;
        }

        let mut parts = placeholder.splitn(2, ':');
        let field = parts.next().unwrap_or_default();
        if !TEMPLATE_FIELDS.contains(&field) {
            errors.push(format!("text.template contains unknown field: {field}"));
        }

        if let Some(width) = parts.next() {
            if width.is_empty()
                || width
                    .parse::<usize>()
                    .ok()
                    .filter(|value| *value > 0)
                    .is_none()
            {
                errors.push(format!(
                    "text.template has invalid width for field {field}: {width}"
                ));
            }
        }

        rest = &after_start[end + 1..];
    }

    if rest.contains('}') {
        errors.push("text.template contains a stray closing brace".to_string());
    }
}

fn ratio_ok(value: f64) -> bool {
    (0.0..=1.0).contains(&value)
}

fn archive_root_looks_empty(root_dir: &str) -> bool {
    let path = Path::new(root_dir);
    if !path.exists() {
        return true;
    }

    match path.read_dir() {
        Ok(mut entries) => entries.next().is_none(),
        Err(_) => true,
    }
}

fn is_valid_ymd(value: &str) -> bool {
    let parts = value.split('-').collect::<Vec<_>>();
    if parts.len() != 3 {
        return false;
    }

    let year = match parts[0].parse::<u32>() {
        Ok(year) if year >= 1970 => year,
        _ => return false,
    };
    let month = match parts[1].parse::<u32>() {
        Ok(month) if (1..=12).contains(&month) => month,
        _ => return false,
    };
    let day = match parts[2].parse::<u32>() {
        Ok(day) if day >= 1 => day,
        _ => return false,
    };

    day <= days_in_month(year, month)
}

fn days_in_month(year: u32, month: u32) -> u32 {
    match month {
        1 | 3 | 5 | 7 | 8 | 10 | 12 => 31,
        4 | 6 | 9 | 11 => 30,
        2 if is_leap_year(year) => 29,
        2 => 28,
        _ => 0,
    }
}

fn is_leap_year(year: u32) -> bool {
    (year % 4 == 0 && year % 100 != 0) || year % 400 == 0
}
