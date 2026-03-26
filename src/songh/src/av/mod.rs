use std::env;
use std::fs;
use std::io::ErrorKind;
use std::path::{Path, PathBuf};
use std::process::Command;

use anyhow::{anyhow, bail, Context, Result};
use serde::{Deserialize, Serialize};

use crate::audio;
use crate::config::schema::{Config, MotionMode};
use crate::video;

const FFMPEG_BIN_ENV_VAR: &str = "SONGH_FFMPEG_BIN";
const FFPROBE_BIN_ENV_VAR: &str = "SONGH_FFPROBE_BIN";
const PROBE_DURATION_TOLERANCE_SECS: f64 = 0.25;

#[derive(Debug, Clone, Serialize)]
pub struct AvRenderReport {
    pub schema_version: String,
    pub output_dir: PathBuf,
    pub video_output_dir: PathBuf,
    pub audio_output_dir: PathBuf,
    pub preview_mp4_path: PathBuf,
    pub manifest_path: PathBuf,
    pub ffprobe_path: Option<PathBuf>,
    pub ffmpeg_bin: PathBuf,
    pub ffprobe_bin: Option<PathBuf>,
    pub ffmpeg_args: Vec<String>,
    pub expected_frame_count: u64,
    pub expected_fps: u32,
    pub expected_duration_seconds: f64,
    pub video_codec: String,
    pub video_preset: String,
    pub audio_bitrate_kbps: u32,
    pub probe: Option<AvProbeSummary>,
    pub video: video::VideoRenderReport,
    pub audio: audio::AudioRenderReport,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub struct AvProbeSummary {
    pub format_name: Option<String>,
    pub duration_seconds: Option<f64>,
    pub size_bytes: Option<u64>,
    pub streams: Vec<AvProbeStreamSummary>,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub struct AvProbeStreamSummary {
    pub index: u32,
    pub codec_type: String,
    pub codec_name: Option<String>,
    pub width: Option<u32>,
    pub height: Option<u32>,
    pub sample_rate: Option<u32>,
    pub channels: Option<u32>,
    pub avg_frame_rate: Option<String>,
    pub nb_frames: Option<u64>,
    pub duration_seconds: Option<f64>,
}

#[derive(Debug, Clone, Deserialize)]
struct RawProbeOutput {
    #[serde(default)]
    format: Option<RawProbeFormat>,
    #[serde(default)]
    streams: Vec<RawProbeStream>,
}

#[derive(Debug, Clone, Deserialize)]
struct RawProbeFormat {
    #[serde(default)]
    format_name: Option<String>,
    #[serde(default)]
    duration: Option<String>,
    #[serde(default)]
    size: Option<String>,
}

#[derive(Debug, Clone, Deserialize)]
struct RawProbeStream {
    #[serde(default)]
    index: Option<u32>,
    #[serde(default)]
    codec_type: String,
    #[serde(default)]
    codec_name: Option<String>,
    #[serde(default)]
    width: Option<u32>,
    #[serde(default)]
    height: Option<u32>,
    #[serde(default)]
    sample_rate: Option<String>,
    #[serde(default)]
    channels: Option<u32>,
    #[serde(default)]
    avg_frame_rate: Option<String>,
    #[serde(default)]
    nb_frames: Option<String>,
    #[serde(default)]
    duration: Option<String>,
}

pub fn render_day_pack(
    config: &Config,
    day: &str,
    archive_root_override: Option<&Path>,
    output_dir: &Path,
    start_second: u32,
    duration_secs: u32,
    motion_mode_override: Option<MotionMode>,
    angle_deg_override: Option<f64>,
) -> Result<AvRenderReport> {
    fs::create_dir_all(output_dir)
        .with_context(|| format!("create stage6 render dir {}", output_dir.display()))?;

    let video_output_dir = output_dir.join("video");
    let audio_output_dir = output_dir.join("audio");
    let video = video::render_day_pack(
        config,
        day,
        archive_root_override,
        &video_output_dir,
        start_second,
        duration_secs,
        motion_mode_override,
        angle_deg_override,
    )?;
    let audio = audio::render_day_pack(
        config,
        day,
        archive_root_override,
        &audio_output_dir,
        start_second,
        duration_secs,
    )?;

    let preview_mp4_path = output_dir.join("offline_preview.mp4");
    let ffmpeg_bin = resolve_binary(FFMPEG_BIN_ENV_VAR, "ffmpeg");
    let ffmpeg_args = build_ffmpeg_args(config, &video, &audio, &preview_mp4_path)?;
    run_ffmpeg(&ffmpeg_bin, &ffmpeg_args)?;

    let ffprobe_path = output_dir.join("ffprobe.json");
    let (ffprobe_bin, probe_path, probe) = run_ffprobe(&preview_mp4_path, &ffprobe_path)?;
    if let Some(probe) = &probe {
        validate_probe(config, probe, &video, &audio)?;
    }

    let manifest_path = output_dir.join("render-manifest.json");
    let report = AvRenderReport {
        schema_version: "stage6.av_render.v1".to_string(),
        output_dir: output_dir.to_path_buf(),
        video_output_dir,
        audio_output_dir,
        preview_mp4_path: preview_mp4_path.clone(),
        manifest_path: manifest_path.clone(),
        ffprobe_path: probe_path,
        ffmpeg_bin,
        ffprobe_bin,
        ffmpeg_args,
        expected_frame_count: video.rendered_frame_count as u64,
        expected_fps: video.frame_plan.fps,
        expected_duration_seconds: round4(
            video.rendered_frame_count as f64 / video.frame_plan.fps as f64,
        ),
        video_codec: config.outputs.encode.video_codec.clone(),
        video_preset: config.outputs.encode.video_preset.clone(),
        audio_bitrate_kbps: config.outputs.encode.audio_bitrate_kbps,
        probe,
        video,
        audio,
    };
    fs::write(&manifest_path, serde_json::to_vec_pretty(&report)?)
        .with_context(|| format!("write stage6 render manifest {}", manifest_path.display()))?;

    Ok(report)
}

fn build_ffmpeg_args(
    config: &Config,
    video: &video::VideoRenderReport,
    audio: &audio::AudioRenderReport,
    output_path: &Path,
) -> Result<Vec<String>> {
    let video_codec = match config.outputs.encode.video_codec.as_str() {
        "h264" => "libx264",
        other => bail!(
            "stage6 render currently only supports outputs.encode.video_codec = h264, got {other}"
        ),
    };

    Ok(vec![
        "-y".to_string(),
        "-loglevel".to_string(),
        "error".to_string(),
        "-framerate".to_string(),
        video.frame_plan.fps.to_string(),
        "-i".to_string(),
        video
            .frames_dir
            .join("frame-%06d.png")
            .display()
            .to_string(),
        "-i".to_string(),
        audio.wav_path.display().to_string(),
        "-c:v".to_string(),
        video_codec.to_string(),
        "-preset".to_string(),
        config.outputs.encode.video_preset.clone(),
        "-pix_fmt".to_string(),
        "yuv420p".to_string(),
        "-c:a".to_string(),
        "aac".to_string(),
        "-b:a".to_string(),
        format!("{}k", config.outputs.encode.audio_bitrate_kbps),
        "-movflags".to_string(),
        "+faststart".to_string(),
        "-shortest".to_string(),
        output_path.display().to_string(),
    ])
}

fn run_ffmpeg(ffmpeg_bin: &Path, ffmpeg_args: &[String]) -> Result<()> {
    let output = Command::new(ffmpeg_bin)
        .args(ffmpeg_args)
        .output()
        .map_err(|error| {
            if error.kind() == ErrorKind::NotFound {
                anyhow!(
                    "ffmpeg binary not found at {} (set {} or install ffmpeg)",
                    ffmpeg_bin.display(),
                    FFMPEG_BIN_ENV_VAR
                )
            } else {
                anyhow!(error)
            }
        })?;

    if output.status.success() {
        return Ok(());
    }

    let stderr = String::from_utf8_lossy(&output.stderr);
    bail!("ffmpeg exited with {}: {}", output.status, stderr.trim());
}

fn run_ffprobe(
    preview_mp4_path: &Path,
    ffprobe_path: &Path,
) -> Result<(Option<PathBuf>, Option<PathBuf>, Option<AvProbeSummary>)> {
    let ffprobe_bin = resolve_binary(FFPROBE_BIN_ENV_VAR, "ffprobe");
    let args = vec![
        "-v".to_string(),
        "error".to_string(),
        "-show_entries".to_string(),
        "format=format_name,duration,size:stream=index,codec_type,codec_name,width,height,sample_rate,channels,avg_frame_rate,nb_frames,duration".to_string(),
        "-of".to_string(),
        "json".to_string(),
        preview_mp4_path.display().to_string(),
    ];

    let output = match Command::new(&ffprobe_bin).args(&args).output() {
        Ok(output) => output,
        Err(error) if error.kind() == ErrorKind::NotFound => return Ok((None, None, None)),
        Err(error) => {
            return Err(error).with_context(|| format!("spawn ffprobe {}", ffprobe_bin.display()))
        }
    };

    if !output.status.success() {
        let stderr = String::from_utf8_lossy(&output.stderr);
        bail!("ffprobe exited with {}: {}", output.status, stderr.trim());
    }

    fs::write(ffprobe_path, &output.stdout)
        .with_context(|| format!("write stage6 ffprobe {}", ffprobe_path.display()))?;
    let raw: RawProbeOutput = serde_json::from_slice(&output.stdout)
        .with_context(|| format!("parse ffprobe json {}", ffprobe_path.display()))?;

    Ok((
        Some(ffprobe_bin),
        Some(ffprobe_path.to_path_buf()),
        Some(convert_probe(raw)?),
    ))
}

fn convert_probe(raw: RawProbeOutput) -> Result<AvProbeSummary> {
    let format = raw.format;
    let streams = raw
        .streams
        .into_iter()
        .map(|stream| {
            Ok(AvProbeStreamSummary {
                index: stream.index.unwrap_or(0),
                codec_type: stream.codec_type,
                codec_name: stream.codec_name,
                width: stream.width,
                height: stream.height,
                sample_rate: parse_optional_u32(stream.sample_rate.as_deref(), "sample_rate")?,
                channels: stream.channels,
                avg_frame_rate: stream.avg_frame_rate,
                nb_frames: parse_optional_u64(stream.nb_frames.as_deref(), "nb_frames")?,
                duration_seconds: parse_optional_f64(stream.duration.as_deref(), "duration")?,
            })
        })
        .collect::<Result<Vec<_>>>()?;

    Ok(AvProbeSummary {
        format_name: format.as_ref().and_then(|entry| entry.format_name.clone()),
        duration_seconds: parse_optional_f64(
            format.as_ref().and_then(|entry| entry.duration.as_deref()),
            "format.duration",
        )?,
        size_bytes: parse_optional_u64(
            format.as_ref().and_then(|entry| entry.size.as_deref()),
            "format.size",
        )?,
        streams,
    })
}

fn validate_probe(
    config: &Config,
    probe: &AvProbeSummary,
    video: &video::VideoRenderReport,
    audio: &audio::AudioRenderReport,
) -> Result<()> {
    let expected_duration = video.rendered_frame_count as f64 / video.frame_plan.fps as f64;
    if let Some(duration) = probe.duration_seconds {
        if (duration - expected_duration).abs() > PROBE_DURATION_TOLERANCE_SECS {
            bail!(
                "ffprobe format.duration {:.3}s does not match expected {:.3}s",
                duration,
                expected_duration
            );
        }
    }

    let video_stream = probe
        .streams
        .iter()
        .find(|stream| stream.codec_type == "video")
        .ok_or_else(|| anyhow!("ffprobe missing video stream"))?;
    if let Some(width) = video_stream.width {
        if width != video.frame_plan.canvas_width {
            bail!(
                "ffprobe video width {} does not match expected {}",
                width,
                video.frame_plan.canvas_width
            );
        }
    }
    if let Some(height) = video_stream.height {
        if height != video.frame_plan.canvas_height {
            bail!(
                "ffprobe video height {} does not match expected {}",
                height,
                video.frame_plan.canvas_height
            );
        }
    }
    if let Some(codec_name) = video_stream.codec_name.as_deref() {
        if config.outputs.encode.video_codec == "h264" && codec_name != "h264" {
            bail!(
                "ffprobe video codec {} does not match expected h264",
                codec_name
            );
        }
    }
    if let Some(nb_frames) = video_stream.nb_frames {
        if nb_frames != video.rendered_frame_count as u64 {
            bail!(
                "ffprobe video nb_frames {} does not match expected {}",
                nb_frames,
                video.rendered_frame_count
            );
        }
    }

    let audio_stream = probe
        .streams
        .iter()
        .find(|stream| stream.codec_type == "audio")
        .ok_or_else(|| anyhow!("ffprobe missing audio stream"))?;
    if let Some(codec_name) = audio_stream.codec_name.as_deref() {
        if codec_name != "aac" {
            bail!(
                "ffprobe audio codec {} does not match expected aac",
                codec_name
            );
        }
    }
    if let Some(sample_rate) = audio_stream.sample_rate {
        if sample_rate != audio.frame_plan.sample_rate {
            bail!(
                "ffprobe audio sample_rate {} does not match expected {}",
                sample_rate,
                audio.frame_plan.sample_rate
            );
        }
    }
    if let Some(channels) = audio_stream.channels {
        if channels != audio.frame_plan.channels {
            bail!(
                "ffprobe audio channels {} does not match expected {}",
                channels,
                audio.frame_plan.channels
            );
        }
    }

    Ok(())
}

fn resolve_binary(env_var: &str, default_bin: &str) -> PathBuf {
    match env::var(env_var) {
        Ok(value) if !value.trim().is_empty() => PathBuf::from(value),
        _ => PathBuf::from(default_bin),
    }
}

fn parse_optional_f64(raw: Option<&str>, field_name: &str) -> Result<Option<f64>> {
    raw.map(|value| {
        value
            .parse::<f64>()
            .with_context(|| format!("parse ffprobe {}={value}", field_name))
    })
    .transpose()
}

fn parse_optional_u32(raw: Option<&str>, field_name: &str) -> Result<Option<u32>> {
    raw.map(|value| {
        value
            .parse::<u32>()
            .with_context(|| format!("parse ffprobe {}={value}", field_name))
    })
    .transpose()
}

fn parse_optional_u64(raw: Option<&str>, field_name: &str) -> Result<Option<u64>> {
    raw.map(|value| {
        value
            .parse::<u64>()
            .with_context(|| format!("parse ffprobe {}={value}", field_name))
    })
    .transpose()
}

fn round4(value: f64) -> f64 {
    (value * 10_000.0).round() / 10_000.0
}

#[cfg(test)]
mod tests {
    use tempfile::tempdir;

    use super::*;
    use crate::archive;
    use crate::config::schema::Config;
    use crate::test_support;

    #[cfg(unix)]
    use std::os::unix::fs::PermissionsExt;

    #[derive(Debug)]
    struct EnvVarGuard {
        key: &'static str,
        previous: Option<String>,
    }

    impl EnvVarGuard {
        fn set(key: &'static str, value: impl AsRef<std::ffi::OsStr>) -> Self {
            let previous = env::var(key).ok();
            env::set_var(key, value);
            Self { key, previous }
        }
    }

    impl Drop for EnvVarGuard {
        fn drop(&mut self) {
            match &self.previous {
                Some(value) => env::set_var(self.key, value),
                None => env::remove_var(self.key),
            }
        }
    }

    fn write_executable_script(path: &Path, body: &str) {
        fs::write(path, body).expect("write script");
        #[cfg(unix)]
        {
            let mut permissions = fs::metadata(path).expect("metadata").permissions();
            permissions.set_mode(0o755);
            fs::set_permissions(path, permissions).expect("chmod");
        }
    }

    #[test]
    fn render_day_pack_writes_preview_mp4_and_probe_manifest() {
        let _guard = test_support::env_lock().lock().expect("lock env");
        let temp = tempdir().expect("tempdir");
        let archive_root = temp.path().join("archive");
        let output_dir = temp.path().join("render-av");
        let ffmpeg_bin = temp.path().join("fake-ffmpeg.sh");
        let ffprobe_bin = temp.path().join("fake-ffprobe.sh");
        let ffmpeg_log = temp.path().join("ffmpeg.log");
        let ffprobe_fixture = temp.path().join("ffprobe.json.fixture");
        let day = "2026-03-19";

        write_executable_script(
            &ffmpeg_bin,
            r#"#!/bin/sh
set -eu
printf '%s\n' "$@" > "$SONGH_TEST_FFMPEG_LOG"
out=""
prev=""
input_count=0
for arg in "$@"; do
  if [ "$prev" = "-i" ]; then
    input_count=$((input_count + 1))
    if [ "$input_count" -eq 1 ]; then
      case "$arg" in
        *frame-%06d.png) : ;;
        *) echo "unexpected video input: $arg" >&2; exit 11 ;;
      esac
      first_frame="$(dirname "$arg")/frame-000000.png"
      [ -f "$first_frame" ]
    elif [ "$input_count" -eq 2 ]; then
      [ -f "$arg" ]
    fi
    prev=""
  else
    prev="$arg"
  fi
  out="$arg"
done
printf 'fake-mp4' > "$out"
"#,
        );
        write_executable_script(
            &ffprobe_bin,
            r#"#!/bin/sh
set -eu
cat "$SONGH_TEST_FFPROBE_FIXTURE"
"#,
        );
        fs::write(
            &ffprobe_fixture,
            r#"{
  "format": {
    "format_name": "mov,mp4,m4a,3gp,3g2,mj2",
    "duration": "8.000000",
    "size": "12345"
  },
  "streams": [
    {
      "index": 0,
      "codec_type": "video",
      "codec_name": "h264",
      "width": 160,
      "height": 90,
      "avg_frame_rate": "4/1",
      "nb_frames": "32",
      "duration": "8.000000"
    },
    {
      "index": 1,
      "codec_type": "audio",
      "codec_name": "aac",
      "sample_rate": "48000",
      "channels": 2,
      "duration": "8.000000"
    }
  ]
}"#,
        )
        .expect("write ffprobe fixture");
        let _ffmpeg_bin = EnvVarGuard::set(FFMPEG_BIN_ENV_VAR, ffmpeg_bin.as_os_str());
        let _ffprobe_bin = EnvVarGuard::set(FFPROBE_BIN_ENV_VAR, ffprobe_bin.as_os_str());
        let _ffmpeg_log = EnvVarGuard::set("SONGH_TEST_FFMPEG_LOG", ffmpeg_log.as_os_str());
        let _ffprobe_fixture =
            EnvVarGuard::set("SONGH_TEST_FFPROBE_FIXTURE", ffprobe_fixture.as_os_str());

        archive::seed_fixture_raw(&archive_root, day, true).expect("seed fixture");
        let mut config = Config::default();
        config.archive.root_dir = archive_root.display().to_string();
        config.video.canvas.width = 160;
        config.video.canvas.height = 90;
        config.video.canvas.fps = 4;
        config.video.text.stroke_width = 1;
        archive::prepare_day_pack(&config, day, Some(&archive_root), true, true).expect("prepare");

        let report = render_day_pack(
            &config,
            day,
            Some(&archive_root),
            &output_dir,
            750,
            8,
            Some(MotionMode::Vertical),
            None,
        )
        .expect("render av");

        assert!(report.preview_mp4_path.exists());
        assert!(report.manifest_path.exists());
        assert_eq!(report.expected_frame_count, 32);
        assert_eq!(report.expected_fps, 4);
        assert_eq!(report.expected_duration_seconds, 8.0);
        assert_eq!(report.video.rendered_frame_count, 32);
        assert_eq!(report.audio.rendered_frame_count, 384_000);
        assert!(report.ffprobe_path.as_ref().expect("probe path").exists());

        let ffmpeg_args = fs::read_to_string(&ffmpeg_log).expect("read ffmpeg log");
        assert!(ffmpeg_args.contains("frame-%06d.png"));
        assert!(ffmpeg_args.contains("offline_audio.wav"));
        assert!(ffmpeg_args.contains("libx264"));
        assert!(ffmpeg_args.contains("aac"));
        assert!(ffmpeg_args.contains("128k"));

        let probe = report.probe.as_ref().expect("probe summary");
        assert_eq!(
            probe.format_name.as_deref(),
            Some("mov,mp4,m4a,3gp,3g2,mj2")
        );
        assert_eq!(probe.size_bytes, Some(12_345));
        let video_stream = probe
            .streams
            .iter()
            .find(|stream| stream.codec_type == "video")
            .expect("video stream");
        assert_eq!(video_stream.width, Some(160));
        assert_eq!(video_stream.height, Some(90));
        assert_eq!(video_stream.nb_frames, Some(32));
        let audio_stream = probe
            .streams
            .iter()
            .find(|stream| stream.codec_type == "audio")
            .expect("audio stream");
        assert_eq!(audio_stream.sample_rate, Some(48_000));
        assert_eq!(audio_stream.channels, Some(2));
    }
}
