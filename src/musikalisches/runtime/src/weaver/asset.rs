//! Atomic asset publication.
//!
//! A generated asset is assembled in a hidden temp directory *inside* the
//! buffer directory and only then `rename`d into its final name. A bridge can
//! therefore never observe a half-written asset: the ledger only ever points at
//! a directory that appeared atomically and carries a complete manifest.

use std::fs;
use std::path::{Path, PathBuf};

use anyhow::{anyhow, bail, Context, Result};
use serde::{Deserialize, Serialize};

use super::hash::sha256_file;
use super::jsonio;

/// Files every published asset must carry. These are the existing artifact
/// contracts from stage5/stage6 (issue #62 brief) — the weaver adds no new
/// required inputs of its own.
pub const DEFAULT_REQUIRED_ASSET_FILES: [&str; 6] = [
    "combination_selection.json",
    "stream_loop_plan.json",
    "artifact_summary.json",
    "offline_audio.wav",
    "video_render_manifest.json",
    "offline_preview.mp4",
];

/// Copied along when present so downstream bridge tooling keeps working.
pub const OPTIONAL_ASSET_FILES: [&str; 7] = [
    "soundscape_selection.json",
    "analysis_window_sequence.json",
    "render_request.json",
    "m1_validation_report.json",
    "stage6_render_validation_report.json",
    "visual_scene_profile.json",
    "video_render_poster.ppm",
];

pub const ASSET_MANIFEST_FILE: &str = "weaver_asset_manifest.json";
pub const ASSET_MANIFEST_STAGE: &str = "weaver_published_asset_v1";
pub const TEMP_PUBLISH_PREFIX: &str = ".tmp-publish-";

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct AssetFileEntry {
    pub name: String,
    pub sha256: String,
    pub bytes: u64,
    pub source: String,
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct AssetManifest {
    pub stage: String,
    pub asset_id: String,
    pub combination_id: String,
    pub work_id: String,
    pub record_id: String,
    pub duration_seconds: f64,
    pub generation_status: String,
    pub generated_at: String,
    pub audio_source_dir: String,
    pub video_source_dir: String,
    pub files: Vec<AssetFileEntry>,
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct PublishOutcome {
    pub asset_id: String,
    pub asset_dir: PathBuf,
    pub combination_id: String,
    pub duration_seconds: f64,
    pub files: Vec<AssetFileEntry>,
}

/// Combination ids are `1,2,3,...`; map them onto a filesystem-safe asset id.
pub fn sanitize_asset_id(combination_id: &str) -> String {
    let mut sanitized = String::with_capacity(combination_id.len() + 5);
    sanitized.push_str("comb-");
    for character in combination_id.chars() {
        if character.is_ascii_alphanumeric() || character == '.' || character == '_' || character == '-' {
            sanitized.push(character);
        } else {
            sanitized.push('-');
        }
    }
    if sanitized.len() > 160 {
        sanitized.truncate(160);
    }
    sanitized
}

/// The stage5 tool is the allocator; the weaver reads the combination it chose.
pub fn read_combination_id(audio_dir: &Path) -> Result<String> {
    let path = audio_dir.join("combination_selection.json");
    let payload = jsonio::read_json_value(&path)
        .with_context(|| format!("read stage5 selection {}", path.display()))?;
    let combination_id = payload
        .get("combination_id")
        .and_then(|value| value.as_str())
        .ok_or_else(|| anyhow!("{} has no combination_id", path.display()))?;
    if combination_id.trim().is_empty() {
        bail!("{} carries an empty combination_id", path.display());
    }
    Ok(combination_id.to_string())
}

/// Asset duration, resolved from the existing stage5 contract with fallbacks.
pub fn read_duration_seconds(audio_dir: &Path) -> Result<f64> {
    let loop_plan_path = audio_dir.join("stream_loop_plan.json");
    if loop_plan_path.is_file() {
        let payload = jsonio::read_json_value(&loop_plan_path)?;
        if let Some(total) = payload.get("total_duration_seconds").and_then(|v| v.as_f64()) {
            if total > 0.0 {
                return Ok(jsonio::round6(total));
            }
        }
        let cycle = payload
            .get("cycle_duration_seconds")
            .and_then(|v| v.as_f64());
        let loops = payload.get("loop_count").and_then(|v| v.as_u64());
        if let (Some(cycle), Some(loops)) = (cycle, loops) {
            if cycle > 0.0 && loops > 0 {
                return Ok(jsonio::round6(cycle * loops as f64));
            }
        }
    }

    let summary_path = audio_dir.join("artifact_summary.json");
    if summary_path.is_file() {
        let payload = jsonio::read_json_value(&summary_path)?;
        if let Some(duration) = payload
            .get("audio")
            .and_then(|audio| audio.get("duration_seconds"))
            .and_then(|value| value.as_f64())
        {
            if duration > 0.0 {
                return Ok(jsonio::round6(duration));
            }
        }
    }

    bail!(
        "cannot resolve asset duration from {} (stream_loop_plan.json / artifact_summary.json)",
        audio_dir.display()
    )
}

/// Remove temp publish directories left behind by a crash mid-publish.
pub fn cleanup_temp_publish_dirs(buffer_dir: &Path) -> Result<usize> {
    if !buffer_dir.is_dir() {
        return Ok(0);
    }
    let mut removed = 0;
    for entry in fs::read_dir(buffer_dir)
        .with_context(|| format!("read buffer dir {}", buffer_dir.display()))?
    {
        let entry = entry?;
        let name = entry.file_name().to_string_lossy().to_string();
        if name.starts_with(TEMP_PUBLISH_PREFIX) && entry.file_type()?.is_dir() {
            fs::remove_dir_all(entry.path())
                .with_context(|| format!("remove stale temp publish dir {}", entry.path().display()))?;
            removed += 1;
        }
    }
    Ok(removed)
}

/// Assemble the publish unit in a temp dir, verify it, then rename it into place.
#[allow(clippy::too_many_arguments)]
pub fn publish_asset(
    sha256sum_bin: &str,
    buffer_dir: &Path,
    audio_dir: &Path,
    video_dir: &Path,
    work_id: &str,
    record_id: &str,
    required_files: &[&str],
) -> Result<PublishOutcome> {
    let combination_id = read_combination_id(audio_dir)?;
    let duration_seconds = read_duration_seconds(audio_dir)?;
    let asset_id = sanitize_asset_id(&combination_id);
    let asset_dir = buffer_dir.join(&asset_id);
    if asset_dir.exists() {
        bail!(
            "refusing to publish {}: {} already exists (assets are immutable)",
            combination_id,
            asset_dir.display()
        );
    }

    fs::create_dir_all(buffer_dir)
        .with_context(|| format!("create buffer dir {}", buffer_dir.display()))?;
    let temp_dir = buffer_dir.join(format!(
        "{TEMP_PUBLISH_PREFIX}{asset_id}-{}-{}",
        std::process::id(),
        jsonio::utc_now().replace(':', "")
    ));
    let _ = fs::remove_dir_all(&temp_dir);
    fs::create_dir_all(&temp_dir)
        .with_context(|| format!("create temp publish dir {}", temp_dir.display()))?;

    let assembled = (|| -> Result<Vec<AssetFileEntry>> {
        let mut missing = Vec::new();
        let mut entries = Vec::new();
        for name in required_files {
            match locate_asset_file(audio_dir, video_dir, name) {
                Some((source_dir, source_label)) => {
                    entries.push(copy_and_hash(
                        sha256sum_bin,
                        &source_dir.join(name),
                        &temp_dir.join(name),
                        name,
                        source_label,
                    )?);
                }
                None => missing.push((*name).to_string()),
            }
        }
        if !missing.is_empty() {
            bail!(
                "asset {combination_id} is incomplete; missing required file(s): {}",
                missing.join(", ")
            );
        }
        for name in OPTIONAL_ASSET_FILES {
            if let Some((source_dir, source_label)) = locate_asset_file(audio_dir, video_dir, name) {
                entries.push(copy_and_hash(
                    sha256sum_bin,
                    &source_dir.join(name),
                    &temp_dir.join(name),
                    name,
                    source_label,
                )?);
            }
        }
        entries.sort_by(|left, right| left.name.cmp(&right.name));
        Ok(entries)
    })();

    let files = match assembled {
        Ok(files) => files,
        Err(error) => {
            let _ = fs::remove_dir_all(&temp_dir);
            return Err(error);
        }
    };

    let manifest = AssetManifest {
        stage: ASSET_MANIFEST_STAGE.to_string(),
        asset_id: asset_id.clone(),
        combination_id: combination_id.clone(),
        work_id: work_id.to_string(),
        record_id: record_id.to_string(),
        duration_seconds,
        generation_status: "published".to_string(),
        generated_at: jsonio::utc_now(),
        audio_source_dir: audio_dir.display().to_string(),
        video_source_dir: video_dir.display().to_string(),
        files: files.clone(),
    };
    jsonio::write_json_atomic(&temp_dir.join(ASSET_MANIFEST_FILE), &manifest)?;

    fs::rename(&temp_dir, &asset_dir).with_context(|| {
        format!(
            "atomically publish {} -> {}",
            temp_dir.display(),
            asset_dir.display()
        )
    })?;

    Ok(PublishOutcome {
        asset_id,
        asset_dir,
        combination_id,
        duration_seconds,
        files,
    })
}

fn locate_asset_file(audio_dir: &Path, video_dir: &Path, name: &str) -> Option<(PathBuf, &'static str)> {
    let audio_candidate = audio_dir.join(name);
    if audio_candidate.is_file() {
        return Some((audio_dir.to_path_buf(), "audio"));
    }
    let video_candidate = video_dir.join(name);
    if video_candidate.is_file() {
        return Some((video_dir.to_path_buf(), "video"));
    }
    None
}

fn copy_and_hash(
    sha256sum_bin: &str,
    source: &Path,
    destination: &Path,
    name: &str,
    source_label: &'static str,
) -> Result<AssetFileEntry> {
    fs::copy(source, destination)
        .with_context(|| format!("copy {} -> {}", source.display(), destination.display()))?;
    let bytes = fs::metadata(destination)
        .with_context(|| format!("stat {}", destination.display()))?
        .len();
    if bytes == 0 {
        bail!("refusing to publish empty file {}", source.display());
    }
    let sha256 = sha256_file(sha256sum_bin, destination)?;
    Ok(AssetFileEntry {
        name: name.to_string(),
        sha256,
        bytes,
        source: source_label.to_string(),
    })
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::weaver::hash::DEFAULT_SHA256SUM_BIN;

    fn scratch(tag: &str) -> PathBuf {
        let dir = std::env::temp_dir().join(format!(
            "weaver-asset-{tag}-{}-{}",
            std::process::id(),
            jsonio::utc_now().replace(':', "")
        ));
        let _ = fs::remove_dir_all(&dir);
        fs::create_dir_all(&dir).unwrap();
        dir
    }

    fn write_stage5_fixture(audio_dir: &Path, combination_id: &str, duration: f64) {
        fs::create_dir_all(audio_dir).unwrap();
        fs::write(
            audio_dir.join("combination_selection.json"),
            format!("{{\"combination_id\":\"{combination_id}\"}}\n"),
        )
        .unwrap();
        fs::write(
            audio_dir.join("stream_loop_plan.json"),
            format!("{{\"total_duration_seconds\":{duration},\"loop_count\":2}}\n"),
        )
        .unwrap();
        fs::write(audio_dir.join("artifact_summary.json"), "{\"work_id\":\"x\"}\n").unwrap();
        fs::write(audio_dir.join("offline_audio.wav"), b"RIFF-fake-wav").unwrap();
        fs::write(audio_dir.join("soundscape_selection.json"), "{\"stage\":\"x\"}\n").unwrap();
    }

    fn write_stage6_fixture(video_dir: &Path) {
        fs::create_dir_all(video_dir).unwrap();
        fs::write(
            video_dir.join("video_render_manifest.json"),
            "{\"stage\":\"x\"}\n",
        )
        .unwrap();
        fs::write(video_dir.join("offline_preview.mp4"), b"fake-mp4").unwrap();
    }

    #[test]
    fn publishes_a_complete_unit_with_digests() {
        let dir = scratch("publish");
        let audio_dir = dir.join("audio");
        let video_dir = dir.join("video");
        let buffer_dir = dir.join("buffer");
        write_stage5_fixture(&audio_dir, "1,2,3", 12.5);
        write_stage6_fixture(&video_dir);

        let outcome = publish_asset(
            DEFAULT_SHA256SUM_BIN,
            &buffer_dir,
            &audio_dir,
            &video_dir,
            "mozart_dicegame_print_1790s",
            "rec-1",
            &DEFAULT_REQUIRED_ASSET_FILES,
        )
        .unwrap();

        assert_eq!(outcome.combination_id, "1,2,3");
        assert_eq!(outcome.asset_id, "comb-1-2-3");
        assert_eq!(outcome.duration_seconds, 12.5);
        assert!(outcome.asset_dir.join(ASSET_MANIFEST_FILE).is_file());
        let manifest: AssetManifest =
            jsonio::read_json(&outcome.asset_dir.join(ASSET_MANIFEST_FILE)).unwrap();
        assert_eq!(manifest.generation_status, "published");
        assert_eq!(manifest.combination_id, "1,2,3");
        assert_eq!(manifest.files.len(), DEFAULT_REQUIRED_ASSET_FILES.len() + 1);
        for entry in &manifest.files {
            assert_eq!(entry.sha256.len(), 64);
            assert!(entry.bytes > 0);
        }
        assert!(manifest
            .files
            .iter()
            .any(|entry| entry.name == "offline_audio.wav" && entry.source == "audio"));
        assert!(manifest
            .files
            .iter()
            .any(|entry| entry.name == "offline_preview.mp4" && entry.source == "video"));
        // no temp leftovers
        assert_eq!(cleanup_temp_publish_dirs(&buffer_dir).unwrap(), 0);
        fs::remove_dir_all(&dir).unwrap();
    }

    #[test]
    fn incomplete_asset_is_rejected_and_leaves_no_visible_dir() {
        let dir = scratch("incomplete");
        let audio_dir = dir.join("audio");
        let video_dir = dir.join("video");
        let buffer_dir = dir.join("buffer");
        write_stage5_fixture(&audio_dir, "4,5,6", 3.0);
        fs::create_dir_all(&video_dir).unwrap(); // no video files at all

        let error = publish_asset(
            DEFAULT_SHA256SUM_BIN,
            &buffer_dir,
            &audio_dir,
            &video_dir,
            "mozart_dicegame_print_1790s",
            "rec-1",
            &DEFAULT_REQUIRED_ASSET_FILES,
        )
        .unwrap_err();
        assert!(error.to_string().contains("incomplete"));
        assert!(!buffer_dir.join("comb-4-5-6").exists());
        assert_eq!(cleanup_temp_publish_dirs(&buffer_dir).unwrap(), 0);
        fs::remove_dir_all(&dir).unwrap();
    }

    #[test]
    fn republishing_the_same_combination_is_refused() {
        let dir = scratch("republish");
        let audio_dir = dir.join("audio");
        let video_dir = dir.join("video");
        let buffer_dir = dir.join("buffer");
        write_stage5_fixture(&audio_dir, "7,8,9", 1.0);
        write_stage6_fixture(&video_dir);
        let publish = || {
            publish_asset(
                DEFAULT_SHA256SUM_BIN,
                &buffer_dir,
                &audio_dir,
                &video_dir,
                "mozart_dicegame_print_1790s",
                "rec-1",
                &DEFAULT_REQUIRED_ASSET_FILES,
            )
        };
        publish().unwrap();
        let error = publish().unwrap_err();
        assert!(error.to_string().contains("already exists"));
        fs::remove_dir_all(&dir).unwrap();
    }

    #[test]
    fn stale_temp_publish_dirs_are_cleaned() {
        let dir = scratch("tempclean");
        let buffer_dir = dir.join("buffer");
        let stale = buffer_dir.join(format!("{TEMP_PUBLISH_PREFIX}comb-1-2-3"));
        fs::create_dir_all(&stale).unwrap();
        fs::write(stale.join("half.wav"), b"partial").unwrap();
        assert_eq!(cleanup_temp_publish_dirs(&buffer_dir).unwrap(), 1);
        assert!(!stale.exists());
        fs::remove_dir_all(&dir).unwrap();
    }

    #[test]
    fn duration_falls_back_to_cycle_times_loops_then_audio_summary() {
        let dir = scratch("duration");
        let audio_dir = dir.join("audio");
        fs::create_dir_all(&audio_dir).unwrap();
        fs::write(
            audio_dir.join("stream_loop_plan.json"),
            "{\"cycle_duration_seconds\":2.5,\"loop_count\":4}\n",
        )
        .unwrap();
        assert_eq!(read_duration_seconds(&audio_dir).unwrap(), 10.0);
        fs::remove_file(audio_dir.join("stream_loop_plan.json")).unwrap();
        fs::write(
            audio_dir.join("artifact_summary.json"),
            "{\"audio\":{\"duration_seconds\":192.0}}\n",
        )
        .unwrap();
        assert_eq!(read_duration_seconds(&audio_dir).unwrap(), 192.0);
        fs::remove_dir_all(&dir).unwrap();
    }

    #[test]
    fn sanitized_asset_ids_are_filesystem_safe_and_distinct() {
        assert_eq!(sanitize_asset_id("1,2,3"), "comb-1-2-3");
        assert_ne!(sanitize_asset_id("1,23"), sanitize_asset_id("12,3"));
        assert!(!sanitize_asset_id("1,2/3").contains('/'));
    }

    #[test]
    fn missing_combination_selection_is_an_error() {
        let dir = scratch("noselection");
        let audio_dir = dir.join("audio");
        fs::create_dir_all(&audio_dir).unwrap();
        assert!(read_combination_id(&audio_dir).is_err());
        fs::remove_dir_all(&dir).unwrap();
    }
}
