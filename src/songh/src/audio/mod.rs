use std::collections::{BTreeMap, HashMap};
use std::fs;
use std::path::{Path, PathBuf};

use anyhow::{anyhow, bail, Context, Result};
use serde::Serialize;
use sha2::{Digest, Sha256};

use crate::config::schema::{Config, EventType, VoiceConfig};
use crate::model::normalized_event::NormalizedEvent;
use crate::replay::{self, ReplayTick};

const MAX_STAGE5_DURATION_SECS: u32 = 30;
const BASE_CUE_AMPLITUDE: f32 = 0.18;

#[derive(Debug, Clone, Serialize)]
pub struct AudioSampleReport {
    pub schema_version: String,
    pub archive_root: PathBuf,
    pub source_day: String,
    pub start_second: u32,
    pub duration_secs: u32,
    pub sample_rate: u32,
    pub channels: u32,
    pub total_frames: u64,
    pub emitted_cue_count: usize,
    pub seconds: Vec<AudioSecondSummary>,
    pub cues: Vec<AudioCuePlan>,
}

#[derive(Debug, Clone, Serialize)]
pub struct AudioSecondSummary {
    pub replay_second: u64,
    pub source_day: String,
    pub second_of_day: u32,
    pub source_event_count: u64,
    pub emitted_event_count: u64,
    pub distinct_event_type_count: usize,
    pub max_initial_gain_db: f64,
    pub min_initial_gain_db: f64,
}

#[derive(Debug, Clone, Serialize)]
pub struct AudioCuePlan {
    pub event_id: String,
    pub event_type: String,
    pub voice_preset: String,
    pub waveform: String,
    pub source_day: String,
    pub second_of_day: u32,
    pub spawn_replay_second: u64,
    pub start_frame: u64,
    pub duration_frames: u64,
    pub base_frequency_hz: f64,
    pub pan: f64,
    pub voice_gain_db: f64,
    pub initial_gain_db: f64,
    pub applied_gain_db: f64,
}

#[derive(Debug, Clone, Serialize)]
pub struct AudioRenderReport {
    pub schema_version: String,
    pub output_dir: PathBuf,
    pub wav_path: PathBuf,
    pub audio_plan_path: PathBuf,
    pub manifest_path: PathBuf,
    pub rendered_frame_count: u64,
    pub rendered_cue_count: usize,
    pub peak_amplitude: f64,
    pub limited_sample_count: u64,
    pub wav_sha256: String,
    pub frame_plan: AudioSampleReport,
}

#[derive(Debug, Clone)]
struct SecondDensity {
    max_type_count: u32,
    count_by_type: HashMap<String, u32>,
}

pub fn sample_day_pack(
    config: &Config,
    day: &str,
    archive_root_override: Option<&Path>,
    start_second: u32,
    duration_secs: u32,
) -> Result<AudioSampleReport> {
    if duration_secs == 0 || duration_secs > MAX_STAGE5_DURATION_SECS {
        bail!("stage5 sample-audio --duration-secs must be within 1..={MAX_STAGE5_DURATION_SECS}");
    }

    if config.audio.channels != 2 {
        bail!("stage5 audio render currently requires stereo output");
    }

    let replay_report = replay::dry_run_day_pack(
        config,
        day,
        archive_root_override,
        start_second,
        duration_secs,
    )?;
    let density_by_tick =
        load_density_for_ticks(&replay_report.archive_root, &replay_report.ticks)?;
    let sample_rate = config.audio.sample_rate;
    let total_frames = replay_report.duration_secs as u64 * sample_rate as u64;

    let mut seconds = Vec::new();
    let mut cues = Vec::new();

    for tick in &replay_report.ticks {
        let density = density_by_tick
            .get(&(tick.source_day.clone(), tick.second_of_day))
            .cloned()
            .unwrap_or_else(|| empty_density(&tick.events));

        let mut cue_initial_gains = Vec::new();
        let mut distinct_event_types = BTreeMap::<String, ()>::new();
        for event in &tick.events {
            let voice = resolve_voice_config(config, &event.event_type)?;
            let initial_gain_db = density_gain_for_event(&density, &event.event_type);
            cue_initial_gains.push(initial_gain_db);
            distinct_event_types.insert(event.event_type.clone(), ());
            cues.push(AudioCuePlan {
                event_id: event.event_id.clone(),
                event_type: event.event_type.clone(),
                voice_preset: voice.preset.clone(),
                waveform: waveform_name(&voice.preset).to_string(),
                source_day: tick.source_day.clone(),
                second_of_day: tick.second_of_day,
                spawn_replay_second: tick.replay_second,
                start_frame: tick.replay_second * sample_rate as u64,
                duration_frames: ms_to_frames(voice.duration_ms, sample_rate),
                base_frequency_hz: round2(base_frequency_hz(&voice.preset, &event.event_type)),
                pan: round2(voice.pan),
                voice_gain_db: round2(voice.gain_db),
                initial_gain_db: round2(initial_gain_db),
                applied_gain_db: round2(voice.gain_db + initial_gain_db),
            });
        }

        let (min_initial_gain_db, max_initial_gain_db) = if cue_initial_gains.is_empty() {
            (0.0, 0.0)
        } else {
            let min = cue_initial_gains
                .iter()
                .copied()
                .fold(f64::INFINITY, f64::min);
            let max = cue_initial_gains
                .iter()
                .copied()
                .fold(f64::NEG_INFINITY, f64::max);
            (round2(min), round2(max))
        };

        seconds.push(AudioSecondSummary {
            replay_second: tick.replay_second,
            source_day: tick.source_day.clone(),
            second_of_day: tick.second_of_day,
            source_event_count: tick.source_event_count,
            emitted_event_count: tick.emitted_event_count,
            distinct_event_type_count: distinct_event_types.len(),
            max_initial_gain_db,
            min_initial_gain_db,
        });
    }

    Ok(AudioSampleReport {
        schema_version: "stage5.audio_sample.v1".to_string(),
        archive_root: replay_report.archive_root,
        source_day: day.to_string(),
        start_second,
        duration_secs: replay_report.duration_secs,
        sample_rate,
        channels: config.audio.channels,
        total_frames,
        emitted_cue_count: cues.len(),
        seconds,
        cues,
    })
}

pub fn render_day_pack(
    config: &Config,
    day: &str,
    archive_root_override: Option<&Path>,
    output_dir: &Path,
    start_second: u32,
    duration_secs: u32,
) -> Result<AudioRenderReport> {
    if config.audio.background.enabled {
        bail!("stage5 audio.background mixing is not implemented yet");
    }

    let frame_plan = sample_day_pack(
        config,
        day,
        archive_root_override,
        start_second,
        duration_secs,
    )?;
    fs::create_dir_all(output_dir)
        .with_context(|| format!("create stage5 render dir {}", output_dir.display()))?;

    let audio_plan_path = output_dir.join("audio-plan.json");
    fs::write(&audio_plan_path, serde_json::to_vec_pretty(&frame_plan)?)
        .with_context(|| format!("write stage5 audio plan {}", audio_plan_path.display()))?;

    let (left, right, limited_sample_count, peak_amplitude) = render_mix(config, &frame_plan)?;
    let wav_path = output_dir.join("offline_audio.wav");
    write_wav_pcm16(&wav_path, frame_plan.sample_rate, &left, &right)?;
    let wav_sha256 =
        hex::encode(Sha256::digest(fs::read(&wav_path).with_context(|| {
            format!("read rendered wav {}", wav_path.display())
        })?));

    let manifest_path = output_dir.join("render-manifest.json");
    let report = AudioRenderReport {
        schema_version: "stage5.audio_render.v1".to_string(),
        output_dir: output_dir.to_path_buf(),
        wav_path: wav_path.clone(),
        audio_plan_path,
        manifest_path: manifest_path.clone(),
        rendered_frame_count: frame_plan.total_frames,
        rendered_cue_count: frame_plan.cues.len(),
        peak_amplitude: round4(peak_amplitude as f64),
        limited_sample_count,
        wav_sha256,
        frame_plan,
    };
    fs::write(&manifest_path, serde_json::to_vec_pretty(&report)?)
        .with_context(|| format!("write stage5 audio manifest {}", manifest_path.display()))?;

    Ok(report)
}

fn render_mix(
    config: &Config,
    frame_plan: &AudioSampleReport,
) -> Result<(Vec<f32>, Vec<f32>, u64, f32)> {
    let total_frames = usize::try_from(frame_plan.total_frames)
        .map_err(|_| anyhow!("audio frame count exceeds addressable memory"))?;
    let mut left = vec![0.0_f32; total_frames];
    let mut right = vec![0.0_f32; total_frames];
    let sample_rate = frame_plan.sample_rate as f32;

    for cue in &frame_plan.cues {
        let start_frame = usize::try_from(cue.start_frame)
            .map_err(|_| anyhow!("cue start frame exceeds addressable memory"))?;
        if start_frame >= total_frames {
            continue;
        }
        let duration_frames = usize::try_from(cue.duration_frames)
            .map_err(|_| anyhow!("cue duration exceeds addressable memory"))?;
        let cue_frames = duration_frames.min(total_frames - start_frame);
        if cue_frames == 0 {
            continue;
        }

        let fade_frames = ((config.audio.mix.crossfade_ms as u64 * frame_plan.sample_rate as u64)
            / 1_000)
            .min((cue_frames / 2) as u64) as usize;
        let gain = db_to_linear(cue.applied_gain_db) * BASE_CUE_AMPLITUDE;
        let (left_gain, right_gain) = pan_gains(cue.pan as f32);
        let waveform = cue.waveform.as_str();
        let frequency_hz = cue.base_frequency_hz as f32;

        for cue_index in 0..cue_frames {
            let global_index = start_frame + cue_index;
            let seconds = cue_index as f32 / sample_rate;
            let sample = oscillator_sample(waveform, frequency_hz, seconds);
            let envelope = envelope_gain(cue_index, cue_frames, fade_frames);
            let value = sample * envelope * gain;
            left[global_index] += value * left_gain;
            right[global_index] += value * right_gain;
        }
    }

    let master_gain = db_to_linear(config.audio.master_gain_db);
    for sample in &mut left {
        *sample *= master_gain;
    }
    for sample in &mut right {
        *sample *= master_gain;
    }

    let limiter_ceiling = db_to_linear(config.audio.mix.limiter_ceiling_dbfs).min(1.0);
    let peak_before_limiter = peak_amplitude(&left, &right);
    let limited_sample_count =
        if config.audio.mix.limiter_enabled && peak_before_limiter > limiter_ceiling {
            let scale = limiter_ceiling / peak_before_limiter;
            let mut count = 0_u64;
            for sample in &mut left {
                if sample.abs() > limiter_ceiling {
                    count += 1;
                }
                *sample *= scale;
            }
            for sample in &mut right {
                if sample.abs() > limiter_ceiling {
                    count += 1;
                }
                *sample *= scale;
            }
            count
        } else {
            0
        };

    let peak_after_limiter = peak_amplitude(&left, &right);
    Ok((left, right, limited_sample_count, peak_after_limiter))
}

fn load_density_for_ticks(
    archive_root: &Path,
    ticks: &[ReplayTick],
) -> Result<BTreeMap<(String, u32), SecondDensity>> {
    let mut ranges = BTreeMap::<String, (u32, u32)>::new();
    for tick in ticks {
        let entry = ranges
            .entry(tick.source_day.clone())
            .or_insert((tick.second_of_day, tick.second_of_day + 1));
        entry.0 = entry.0.min(tick.second_of_day);
        entry.1 = entry.1.max((tick.second_of_day + 1).min(86_400));
    }

    let mut density_by_tick = BTreeMap::new();
    for (day, (start_second, end_second)) in ranges {
        let events_by_second =
            replay::load_source_events_for_range(archive_root, &day, start_second, end_second)?;
        for (second_of_day, events) in events_by_second {
            density_by_tick.insert((day.clone(), second_of_day), density_for_second(&events));
        }
    }

    Ok(density_by_tick)
}

fn density_for_second(events: &[NormalizedEvent]) -> SecondDensity {
    let mut count_by_type = HashMap::<String, u32>::new();
    for event in events {
        *count_by_type.entry(event.event_type.clone()).or_insert(0) += 1;
    }
    let max_type_count = count_by_type.values().copied().max().unwrap_or(1);
    SecondDensity {
        max_type_count,
        count_by_type,
    }
}

fn empty_density(events: &[crate::model::runtime_event::RuntimeEvent]) -> SecondDensity {
    let mut count_by_type = HashMap::<String, u32>::new();
    for event in events {
        *count_by_type.entry(event.event_type.clone()).or_insert(0) += 1;
    }
    let max_type_count = count_by_type.values().copied().max().unwrap_or(1);
    SecondDensity {
        max_type_count,
        count_by_type,
    }
}

fn density_gain_for_event(density: &SecondDensity, event_type: &str) -> f64 {
    let type_count = density.count_by_type.get(event_type).copied().unwrap_or(1);
    gain_db_for_type_density(type_count, density.max_type_count)
}

fn gain_db_for_type_density(type_count: u32, max_count: u32) -> f64 {
    if max_count <= 1 {
        return 0.0;
    }
    let ratio = (type_count.saturating_sub(1)) as f64 / (max_count.saturating_sub(1)) as f64;
    -4.0 + ratio * 10.0
}

fn resolve_voice_config<'a>(config: &'a Config, event_type: &str) -> Result<&'a VoiceConfig> {
    let event_type = EventType::from_str_name(event_type)
        .ok_or_else(|| anyhow!("unsupported audio event type: {event_type}"))?;
    config
        .audio
        .voices
        .get(&event_type)
        .ok_or_else(|| anyhow!("missing audio voice config for {}", event_type.as_str()))
}

fn waveform_name(preset: &str) -> &'static str {
    match hashed_u64(preset, "waveform") % 4 {
        0 => "sine",
        1 => "triangle",
        2 => "square",
        _ => "saw",
    }
}

fn base_frequency_hz(preset: &str, event_type: &str) -> f64 {
    let event_offset = match event_type {
        "CreateEvent" => 0.0,
        "DeleteEvent" => 24.0,
        "PushEvent" => 48.0,
        "IssuesEvent" => 72.0,
        "IssueCommentEvent" => 96.0,
        "CommitCommentEvent" => 120.0,
        "PullRequestEvent" => 144.0,
        "PublicEvent" => 168.0,
        "ForkEvent" => 192.0,
        "ReleaseEvent" => 216.0,
        _ => 0.0,
    };
    180.0 + event_offset + hashed_unit_interval(preset, "frequency") * 80.0
}

fn ms_to_frames(duration_ms: u32, sample_rate: u32) -> u64 {
    ((duration_ms as u64 * sample_rate as u64) / 1_000).max(1)
}

fn db_to_linear(gain_db: f64) -> f32 {
    (10.0_f64.powf(gain_db / 20.0)) as f32
}

fn pan_gains(pan: f32) -> (f32, f32) {
    let angle = (pan.clamp(-1.0, 1.0) + 1.0) * std::f32::consts::FRAC_PI_4;
    (angle.cos(), angle.sin())
}

fn oscillator_sample(waveform: &str, frequency_hz: f32, seconds: f32) -> f32 {
    let phase = (frequency_hz * seconds).fract();
    match waveform {
        "triangle" => 1.0 - 4.0 * (phase - 0.5).abs(),
        "square" => {
            if phase < 0.5 {
                1.0
            } else {
                -1.0
            }
        }
        "saw" => phase * 2.0 - 1.0,
        _ => (seconds * frequency_hz * std::f32::consts::TAU).sin(),
    }
}

fn envelope_gain(index: usize, total: usize, fade: usize) -> f32 {
    if fade == 0 || total <= 1 {
        return 1.0;
    }
    let fade_in = ((index + 1) as f32 / fade as f32).clamp(0.0, 1.0);
    let fade_out = ((total - index) as f32 / fade as f32).clamp(0.0, 1.0);
    fade_in.min(fade_out)
}

fn peak_amplitude(left: &[f32], right: &[f32]) -> f32 {
    left.iter()
        .chain(right.iter())
        .fold(0.0_f32, |peak, sample| peak.max(sample.abs()))
}

fn write_wav_pcm16(path: &Path, sample_rate: u32, left: &[f32], right: &[f32]) -> Result<()> {
    if left.len() != right.len() {
        bail!("left/right channel lengths must match");
    }

    let frame_count = left.len() as u32;
    let channels = 2_u16;
    let bits_per_sample = 16_u16;
    let block_align = channels * (bits_per_sample / 8);
    let byte_rate = sample_rate * block_align as u32;
    let data_len = frame_count * block_align as u32;
    let riff_len = 36_u32 + data_len;

    let mut bytes = Vec::with_capacity((44 + data_len) as usize);
    bytes.extend_from_slice(b"RIFF");
    bytes.extend_from_slice(&riff_len.to_le_bytes());
    bytes.extend_from_slice(b"WAVE");
    bytes.extend_from_slice(b"fmt ");
    bytes.extend_from_slice(&16_u32.to_le_bytes());
    bytes.extend_from_slice(&1_u16.to_le_bytes());
    bytes.extend_from_slice(&channels.to_le_bytes());
    bytes.extend_from_slice(&sample_rate.to_le_bytes());
    bytes.extend_from_slice(&byte_rate.to_le_bytes());
    bytes.extend_from_slice(&block_align.to_le_bytes());
    bytes.extend_from_slice(&bits_per_sample.to_le_bytes());
    bytes.extend_from_slice(b"data");
    bytes.extend_from_slice(&data_len.to_le_bytes());

    for index in 0..left.len() {
        bytes.extend_from_slice(&quantize_pcm16(left[index]).to_le_bytes());
        bytes.extend_from_slice(&quantize_pcm16(right[index]).to_le_bytes());
    }

    fs::write(path, bytes).with_context(|| format!("write wav {}", path.display()))
}

fn quantize_pcm16(sample: f32) -> i16 {
    let scaled = (sample.clamp(-1.0, 1.0) * i16::MAX as f32).round();
    scaled.clamp(i16::MIN as f32, i16::MAX as f32) as i16
}

fn hashed_u64(value: &str, salt: &str) -> u64 {
    let digest = Sha256::digest(format!("{value}:{salt}").as_bytes());
    u64::from_be_bytes(digest[..8].try_into().expect("8 bytes"))
}

fn hashed_unit_interval(value: &str, salt: &str) -> f64 {
    hashed_u64(value, salt) as f64 / u64::MAX as f64
}

fn round2(value: f64) -> f64 {
    (value * 100.0).round() / 100.0
}

fn round4(value: f64) -> f64 {
    (value * 10_000.0).round() / 10_000.0
}

#[cfg(test)]
mod tests {
    use std::path::Path;

    use serde_json::{json, Value};
    use tempfile::tempdir;

    use super::*;
    use crate::archive;

    fn time_for_second(second_of_day: u32) -> String {
        let hour = second_of_day / 3_600;
        let minute = (second_of_day % 3_600) / 60;
        let second = second_of_day % 60;
        format!("{hour:02}:{minute:02}:{second:02}")
    }

    fn dense_second_raw_events(day: &str, second_of_day: u32, id_prefix: &str) -> Vec<Value> {
        let mut raw_events = Vec::new();
        let created_at = format!("{day}T{}Z", time_for_second(second_of_day));

        for index in 0..5 {
            raw_events.push(json!({
                "id": format!("{id_prefix}-push-{index}"),
                "type": "PushEvent",
                "created_at": created_at.clone(),
                "repo": {"name": "fixture/dense-push"},
                "actor": {"login": format!("push_actor_{index}")},
                "payload": {"head": format!("aa11bb22cc33dd44ee55ff66778899aa00bb{index:02x}")},
            }));
        }
        for index in 0..3 {
            raw_events.push(json!({
                "id": format!("{id_prefix}-issues-{index}"),
                "type": "IssuesEvent",
                "created_at": created_at.clone(),
                "repo": {"name": "fixture/dense-issues"},
                "actor": {"login": format!("issues_actor_{index}")},
                "payload": {"issue": {"id": 10_000 + index}},
            }));
        }
        for index in 0..2 {
            raw_events.push(json!({
                "id": format!("{id_prefix}-release-{index}"),
                "type": "ReleaseEvent",
                "created_at": created_at.clone(),
                "repo": {"name": "fixture/dense-release"},
                "actor": {"login": format!("release_actor_{index}")},
                "payload": {"release": {"id": 20_000 + index}},
            }));
        }

        raw_events
    }

    fn write_dense_second_raw_fixture(
        archive_root: &Path,
        day: &str,
        second_of_day: u32,
        id_prefix: &str,
    ) {
        let raw_path = archive_root.join(day).join("raw").join("00.json.gz");
        let raw_events = dense_second_raw_events(day, second_of_day, id_prefix);
        archive::materialize::write_gzip_json_lines(&raw_path, &raw_events)
            .expect("write dense raw");
    }

    #[test]
    fn audio_sample_emits_cue_and_density_gain() {
        let temp = tempdir().expect("tempdir");
        let archive_root = temp.path().join("archive");
        let day = "2026-03-19";

        archive::seed_fixture_raw(&archive_root, day, true).expect("seed fixture");
        let mut config = Config::default();
        config.archive.root_dir = archive_root.display().to_string();
        archive::prepare_day_pack(&config, day, Some(&archive_root), true, true).expect("prepare");

        let report =
            sample_day_pack(&config, day, Some(&archive_root), 750, 8).expect("sample audio");

        assert_eq!(report.sample_rate, 48_000);
        assert_eq!(report.channels, 2);
        assert_eq!(report.total_frames, 384_000);
        assert_eq!(report.emitted_cue_count, 1);
        assert_eq!(report.cues[0].event_type, "CreateEvent");
        assert_eq!(report.cues[0].voice_gain_db, -2.0);
        assert_eq!(report.cues[0].initial_gain_db, 0.0);
        assert_eq!(report.cues[0].applied_gain_db, -2.0);
        assert_eq!(report.seconds[4].emitted_event_count, 1);
    }

    #[test]
    fn stage5_dense_second_applies_density_gain_to_rendered_cues() {
        let temp = tempdir().expect("tempdir");
        let archive_root = temp.path().join("archive");
        let day = "2026-03-19";

        archive::seed_fixture_raw(&archive_root, day, true).expect("seed fixture");
        write_dense_second_raw_fixture(&archive_root, day, 754, "dense-a");

        let mut config = Config::default();
        config.archive.root_dir = archive_root.display().to_string();
        archive::prepare_day_pack(&config, day, Some(&archive_root), true, true).expect("prepare");

        let report =
            sample_day_pack(&config, day, Some(&archive_root), 754, 1).expect("sample audio");

        assert_eq!(report.emitted_cue_count, 4);
        let release_gain = report
            .cues
            .iter()
            .find(|cue| cue.event_type == "ReleaseEvent")
            .expect("release cue")
            .initial_gain_db;
        let issues_gain = report
            .cues
            .iter()
            .find(|cue| cue.event_type == "IssuesEvent")
            .expect("issues cue")
            .initial_gain_db;
        assert!(issues_gain > release_gain);
        assert_eq!(release_gain, -1.5);
        assert_eq!(issues_gain, 1.0);
    }

    #[test]
    fn render_day_pack_writes_wav_and_manifest() {
        let temp = tempdir().expect("tempdir");
        let archive_root = temp.path().join("archive");
        let output_dir = temp.path().join("render-audio");
        let day = "2026-03-19";

        archive::seed_fixture_raw(&archive_root, day, true).expect("seed fixture");
        let mut config = Config::default();
        config.archive.root_dir = archive_root.display().to_string();
        archive::prepare_day_pack(&config, day, Some(&archive_root), true, true).expect("prepare");

        let report = render_day_pack(&config, day, Some(&archive_root), &output_dir, 750, 8)
            .expect("render audio");

        assert_eq!(report.rendered_frame_count, 384_000);
        assert_eq!(report.rendered_cue_count, 1);
        assert!(report.wav_path.exists());
        assert!(report.audio_plan_path.exists());
        assert!(report.manifest_path.exists());
        assert!(report.peak_amplitude > 0.0);
        assert_eq!(report.limited_sample_count, 0);
        assert_eq!(
            report.wav_sha256,
            "d05d4d67ef70b3e37c9f09110ee464991b9610fdaeb880f74fb01c09a41bee82"
        );
    }
}
