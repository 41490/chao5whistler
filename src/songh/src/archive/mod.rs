pub mod download;
pub mod index;
pub mod manifest;
pub mod materialize;
pub mod normalize;

use std::collections::BTreeMap;
use std::fs;
use std::path::{Path, PathBuf};

use anyhow::{bail, Context, Result};
use chrono::Utc;

use crate::config::schema::{Config, EventType, NormalizeCodec};
use crate::model::normalized_event::NormalizedEvent;

use self::download::download_missing_raw_hours;
use self::index::{HourMinuteIndex, MinuteOffsetRecord};
use self::manifest::{
    config_fingerprint, DayPackManifest, DayPackStats, FileChecksumRecord, HourManifestRecord,
    HourStats, IndexRecord,
};
use self::materialize::open_gzip_lines;
use self::normalize::{
    build_fixture_primary_event, build_fixture_secondary_event, normalize_event,
};

#[derive(Debug, Clone)]
pub struct FixtureSeedReport {
    pub raw_file_count: usize,
    pub raw_event_count: u64,
}

#[derive(Debug, Clone)]
pub struct PrepareDayPackReport {
    pub archive_root: PathBuf,
    pub source_day: String,
    pub raw_event_count: u64,
    pub normalized_event_count: u64,
    pub dropped_secondary_event_count: u64,
    pub manifest_path: PathBuf,
}

#[derive(Debug, Clone)]
pub struct ValidateDayPackReport {
    pub archive_root: PathBuf,
    pub source_day: String,
    pub raw_file_count: usize,
    pub normalized_file_count: usize,
    pub normalized_event_count: u64,
    pub minute_index_hours: usize,
}

pub fn seed_fixture_raw(archive_root: &Path, day: &str, force: bool) -> Result<FixtureSeedReport> {
    validate_day(day)?;
    let layout = DayPackLayout::new(archive_root.to_path_buf(), day.to_string());
    if force && layout.raw_dir.exists() {
        fs::remove_dir_all(&layout.raw_dir)
            .with_context(|| format!("failed to remove {}", layout.raw_dir.display()))?;
    }
    fs::create_dir_all(&layout.raw_dir)
        .with_context(|| format!("failed to create {}", layout.raw_dir.display()))?;

    let mut raw_event_count = 0_u64;
    for hour in 0..24_u8 {
        let primary_type = EventType::ALL[(hour as usize) % EventType::ALL.len()];
        let primary = build_fixture_primary_event(day, hour, primary_type);
        let secondary = build_fixture_secondary_event(day, hour);
        let raw_path = layout.raw_hour_path(hour);
        materialize::write_gzip_json_lines(&raw_path, &[primary, secondary])?;
        raw_event_count += 2;
    }

    Ok(FixtureSeedReport {
        raw_file_count: 24,
        raw_event_count,
    })
}

pub fn prepare_day_pack(
    config: &Config,
    day: &str,
    archive_root_override: Option<&Path>,
    force: bool,
    skip_download: bool,
) -> Result<PrepareDayPackReport> {
    validate_day(day)?;
    let archive_root = resolve_archive_root(config, archive_root_override);
    let layout = DayPackLayout::new(archive_root.clone(), day.to_string());
    fs::create_dir_all(&layout.day_dir)
        .with_context(|| format!("failed to create {}", layout.day_dir.display()))?;

    if force {
        if !skip_download && layout.raw_dir.exists() {
            fs::remove_dir_all(&layout.raw_dir)
                .with_context(|| format!("failed to reset {}", layout.raw_dir.display()))?;
        }
        if layout.normalized_dir.exists() {
            fs::remove_dir_all(&layout.normalized_dir)
                .with_context(|| format!("failed to reset {}", layout.normalized_dir.display()))?;
        }
        if layout.index_dir.exists() {
            fs::remove_dir_all(&layout.index_dir)
                .with_context(|| format!("failed to reset {}", layout.index_dir.display()))?;
        }
        if layout.manifest_path.exists() {
            fs::remove_file(&layout.manifest_path)
                .with_context(|| format!("failed to remove {}", layout.manifest_path.display()))?;
        }
    }

    fs::create_dir_all(&layout.raw_dir)
        .with_context(|| format!("failed to create {}", layout.raw_dir.display()))?;
    fs::create_dir_all(&layout.normalized_dir)
        .with_context(|| format!("failed to create {}", layout.normalized_dir.display()))?;
    fs::create_dir_all(&layout.index_dir)
        .with_context(|| format!("failed to create {}", layout.index_dir.display()))?;

    if skip_download {
        ensure_all_raw_hours_exist(&layout)?;
    } else {
        download_missing_raw_hours(config, &layout)?;
    }

    let allowed_types = config
        .events
        .primary_types
        .iter()
        .map(|event| event.as_str().to_string())
        .collect::<Vec<_>>();
    let weight_map = config
        .events
        .weights
        .iter()
        .map(|(event, weight)| (event.as_str().to_string(), *weight))
        .collect::<BTreeMap<_, _>>();

    let mut raw_files = Vec::new();
    let mut normalized_files = Vec::new();
    let mut hour_stats = Vec::new();
    let mut hour_indexes = Vec::new();
    let mut totals = BuildTotals::default();

    for hour in 0..24_u8 {
        let raw_path = layout.raw_hour_path(hour);
        let normalized_path = layout.normalized_hour_path(config.archive.normalize.codec, hour);
        let mut writer = materialize::open_encoded_line_writer(
            &normalized_path,
            config.archive.normalize.codec,
        )?;

        let mut lines = open_gzip_lines(&raw_path)?;
        let mut line_number = 0_u64;
        let mut normalized_count = 0_u64;
        let mut dropped_secondary_count = 0_u64;
        let mut raw_event_count = 0_u64;
        let mut per_type = BTreeMap::<String, u64>::new();
        let mut minute_counts = [0_u64; 60];
        let mut minute_offsets = vec![None::<MinuteOffsetRecord>; 60];
        let mut uncompressed_byte_offset = 0_u64;
        let mut first_created_at = None::<String>;
        let mut last_created_at = None::<String>;

        while let Some(line) = lines.next() {
            let line = line?;
            line_number += 1;
            raw_event_count += 1;
            let value: serde_json::Value = serde_json::from_str(&line)
                .with_context(|| format!("failed to parse JSON in {}", raw_path.display()))?;
            match normalize_event(
                &value,
                day,
                hour,
                line_number,
                &weight_map,
                config.events.hash_len_default as usize,
            )? {
                Some(event) => {
                    let minute = (event.second_of_day / 60) % 60;
                    minute_offsets[minute as usize].get_or_insert(MinuteOffsetRecord {
                        minute: minute as u8,
                        second_of_day_start: (hour as u32) * 3600 + minute * 60,
                        event_index_offset: normalized_count,
                        uncompressed_byte_offset,
                        event_count: 0,
                    });
                    minute_counts[minute as usize] += 1;
                    if let Some(entry) = minute_offsets[minute as usize].as_mut() {
                        entry.event_count += 1;
                    }

                    first_created_at.get_or_insert_with(|| event.created_at_utc.clone());
                    last_created_at = Some(event.created_at_utc.clone());
                    *per_type.entry(event.event_type.clone()).or_insert(0) += 1;

                    let line = serde_json::to_string(&event)?;
                    writer.write_line(&line)?;
                    uncompressed_byte_offset += (line.len() + 1) as u64;
                    normalized_count += 1;
                }
                None => {
                    dropped_secondary_count += 1;
                }
            }
        }

        writer.finish()?;

        let minute_index = build_hour_minute_index(
            day,
            hour,
            &layout.relative_normalized_hour_path(config.archive.normalize.codec, hour),
            &minute_counts,
            &minute_offsets,
            normalized_count,
            uncompressed_byte_offset,
        );

        let raw_file = checksum_record(&raw_path, &layout.archive_root)?;
        let normalized_file = checksum_record(&normalized_path, &layout.archive_root)?;

        totals.raw_event_count += raw_event_count;
        totals.normalized_event_count += normalized_count;
        totals.dropped_secondary_event_count += dropped_secondary_count;
        for (event_type, count) in &per_type {
            *totals.per_type.entry(event_type.clone()).or_insert(0) += count;
        }
        if totals.first_created_at.is_none() {
            totals.first_created_at = first_created_at.clone();
        }
        if last_created_at.is_some() {
            totals.last_created_at = last_created_at.clone();
        }

        raw_files.push(HourManifestRecord {
            hour,
            relative_path: raw_file.relative_path.clone(),
            size_bytes: raw_file.size_bytes,
            sha256: raw_file.sha256.clone(),
            event_count: raw_event_count,
        });
        normalized_files.push(HourManifestRecord {
            hour,
            relative_path: normalized_file.relative_path.clone(),
            size_bytes: normalized_file.size_bytes,
            sha256: normalized_file.sha256.clone(),
            event_count: normalized_count,
        });
        hour_stats.push(HourStats {
            hour,
            raw_event_count,
            normalized_event_count: normalized_count,
            dropped_secondary_event_count: dropped_secondary_count,
            per_event_type: per_type,
            first_created_at_utc: first_created_at,
            last_created_at_utc: last_created_at,
        });
        hour_indexes.push(minute_index);
    }

    let generated_at_utc = Utc::now().to_rfc3339();
    let minute_offsets_payload = index::MinuteOffsetsIndex {
        schema_version: "stage2.minute_offsets.v1".to_string(),
        source_day: day.to_string(),
        generated_at_utc: generated_at_utc.clone(),
        hours: hour_indexes,
    };
    let stats_payload = DayPackStats {
        schema_version: "stage2.stats.v1".to_string(),
        source_day: day.to_string(),
        generated_at_utc: generated_at_utc.clone(),
        raw_event_count: totals.raw_event_count,
        normalized_event_count: totals.normalized_event_count,
        dropped_secondary_event_count: totals.dropped_secondary_event_count,
        supported_event_classes: allowed_types.clone(),
        per_event_type: totals.per_type.clone(),
        first_created_at_utc: totals.first_created_at.clone(),
        last_created_at_utc: totals.last_created_at.clone(),
        per_hour: hour_stats,
    };

    let minute_offsets_text = serde_json::to_string_pretty(&minute_offsets_payload)?;
    fs::write(&layout.minute_offsets_path, minute_offsets_text)
        .with_context(|| format!("failed to write {}", layout.minute_offsets_path.display()))?;
    let stats_text = serde_json::to_string_pretty(&stats_payload)?;
    fs::write(&layout.stats_path, stats_text)
        .with_context(|| format!("failed to write {}", layout.stats_path.display()))?;

    let stats_record = checksum_record(&layout.stats_path, &layout.archive_root)?;
    let minute_offsets_record = checksum_record(&layout.minute_offsets_path, &layout.archive_root)?;
    let config_fingerprint = config_fingerprint(config)?;

    let manifest = DayPackManifest {
        schema_version: "stage2.manifest.v2".to_string(),
        source_day: day.to_string(),
        generated_at_utc,
        generator_version: env!("CARGO_PKG_VERSION").to_string(),
        config_fingerprint,
        complete: true,
        codec: codec_name(config.archive.normalize.codec).to_string(),
        supported_event_classes: allowed_types,
        raw_hours: raw_files,
        normalized_hours: normalized_files,
        index_files: vec![
            IndexRecord {
                kind: "stats".to_string(),
                relative_path: stats_record.relative_path,
                size_bytes: stats_record.size_bytes,
                sha256: stats_record.sha256,
            },
            IndexRecord {
                kind: "minute_offsets".to_string(),
                relative_path: minute_offsets_record.relative_path,
                size_bytes: minute_offsets_record.size_bytes,
                sha256: minute_offsets_record.sha256,
            },
        ],
        totals: manifest::ManifestTotals {
            raw_event_count: totals.raw_event_count,
            normalized_event_count: totals.normalized_event_count,
            dropped_secondary_event_count: totals.dropped_secondary_event_count,
        },
        created_at_range: manifest::CreatedAtRange {
            first_created_at_utc: totals.first_created_at,
            last_created_at_utc: totals.last_created_at,
        },
    };
    fs::write(&layout.manifest_path, toml::to_string_pretty(&manifest)?)
        .with_context(|| format!("failed to write {}", layout.manifest_path.display()))?;

    Ok(PrepareDayPackReport {
        archive_root,
        source_day: day.to_string(),
        raw_event_count: totals.raw_event_count,
        normalized_event_count: totals.normalized_event_count,
        dropped_secondary_event_count: totals.dropped_secondary_event_count,
        manifest_path: layout.manifest_path,
    })
}

pub fn validate_day_pack(
    config: &Config,
    day: &str,
    archive_root_override: Option<&Path>,
) -> Result<ValidateDayPackReport> {
    validate_day(day)?;
    let archive_root = resolve_archive_root(config, archive_root_override);
    let layout = DayPackLayout::new(archive_root.clone(), day.to_string());

    let manifest: DayPackManifest = toml::from_str(
        &fs::read_to_string(&layout.manifest_path)
            .with_context(|| format!("failed to read {}", layout.manifest_path.display()))?,
    )
    .with_context(|| format!("failed to parse {}", layout.manifest_path.display()))?;
    let stats: DayPackStats = serde_json::from_str(
        &fs::read_to_string(&layout.stats_path)
            .with_context(|| format!("failed to read {}", layout.stats_path.display()))?,
    )
    .with_context(|| format!("failed to parse {}", layout.stats_path.display()))?;
    let minute_offsets: index::MinuteOffsetsIndex = serde_json::from_str(
        &fs::read_to_string(&layout.minute_offsets_path)
            .with_context(|| format!("failed to read {}", layout.minute_offsets_path.display()))?,
    )
    .with_context(|| format!("failed to parse {}", layout.minute_offsets_path.display()))?;

    if !manifest.complete {
        bail!("manifest marks day-pack as incomplete");
    }
    if manifest.generator_version.trim().is_empty() {
        bail!("manifest generator_version must not be empty");
    }
    if manifest.config_fingerprint.trim().is_empty() {
        bail!("manifest config_fingerprint must not be empty");
    }
    if manifest.raw_hours.len() != 24 {
        bail!("manifest must declare 24 raw hours");
    }
    if manifest.normalized_hours.len() != 24 {
        bail!("manifest must declare 24 normalized hours");
    }
    if minute_offsets.hours.len() != 24 {
        bail!("minute_offsets.json must declare 24 hours");
    }

    let mut normalized_event_count = 0_u64;
    for raw in &manifest.raw_hours {
        let record = checksum_record(&archive_root.join(&raw.relative_path), &archive_root)?;
        if record.sha256 != raw.sha256 || record.size_bytes != raw.size_bytes {
            bail!("raw checksum mismatch for {}", raw.relative_path);
        }
    }

    for normalized in &manifest.normalized_hours {
        let path = archive_root.join(&normalized.relative_path);
        let record = checksum_record(&path, &archive_root)?;
        if record.sha256 != normalized.sha256 || record.size_bytes != normalized.size_bytes {
            bail!(
                "normalized checksum mismatch for {}",
                normalized.relative_path
            );
        }

        let events = materialize::read_encoded_json_lines::<NormalizedEvent>(&path)?;
        normalized_event_count += events.len() as u64;
        if events.len() as u64 != normalized.event_count {
            bail!(
                "normalized event count mismatch for {}",
                normalized.relative_path
            );
        }
    }

    for index_record in &manifest.index_files {
        let record = checksum_record(
            &archive_root.join(&index_record.relative_path),
            &archive_root,
        )?;
        if record.sha256 != index_record.sha256 || record.size_bytes != index_record.size_bytes {
            bail!("index checksum mismatch for {}", index_record.relative_path);
        }
    }

    if normalized_event_count != manifest.totals.normalized_event_count {
        bail!("manifest normalized_event_count does not match normalized files");
    }
    if stats.normalized_event_count != manifest.totals.normalized_event_count {
        bail!("stats normalized_event_count does not match manifest");
    }
    if stats.raw_event_count != manifest.totals.raw_event_count {
        bail!("stats raw_event_count does not match manifest");
    }

    for hour_index in &minute_offsets.hours {
        if hour_index.minute_offsets.len() != 60 {
            bail!(
                "minute_offsets hour {} must declare 60 minute entries",
                hour_index.hour
            );
        }
        let sum = hour_index
            .minute_offsets
            .iter()
            .map(|entry| entry.event_count)
            .sum::<u64>();
        let expected = manifest
            .normalized_hours
            .iter()
            .find(|entry| entry.hour == hour_index.hour)
            .map(|entry| entry.event_count)
            .unwrap_or_default();
        if sum != expected {
            bail!(
                "minute_offsets hour {} event count mismatch",
                hour_index.hour
            );
        }
    }

    Ok(ValidateDayPackReport {
        archive_root,
        source_day: day.to_string(),
        raw_file_count: manifest.raw_hours.len(),
        normalized_file_count: manifest.normalized_hours.len(),
        normalized_event_count,
        minute_index_hours: minute_offsets.hours.len(),
    })
}

#[derive(Debug, Clone)]
pub struct DayPackLayout {
    pub archive_root: PathBuf,
    pub day_dir: PathBuf,
    pub raw_dir: PathBuf,
    pub normalized_dir: PathBuf,
    pub index_dir: PathBuf,
    pub minute_offsets_path: PathBuf,
    pub stats_path: PathBuf,
    pub manifest_path: PathBuf,
    pub source_day: String,
}

impl DayPackLayout {
    pub(crate) fn new(archive_root: PathBuf, source_day: String) -> Self {
        let day_dir = archive_root.join(&source_day);
        let raw_dir = day_dir.join("raw");
        let normalized_dir = day_dir.join("normalized");
        let index_dir = day_dir.join("index");
        Self {
            archive_root,
            day_dir: day_dir.clone(),
            raw_dir,
            normalized_dir,
            index_dir: index_dir.clone(),
            minute_offsets_path: index_dir.join("minute_offsets.json"),
            stats_path: index_dir.join("stats.json"),
            manifest_path: day_dir.join("manifest.toml"),
            source_day,
        }
    }

    pub fn raw_hour_path(&self, hour: u8) -> PathBuf {
        self.raw_dir.join(format!("{hour:02}.json.gz"))
    }

    pub fn normalized_hour_path(&self, codec: NormalizeCodec, hour: u8) -> PathBuf {
        self.normalized_dir
            .join(format!("{hour:02}.{}", codec_name(codec)))
    }

    pub fn relative_normalized_hour_path(&self, codec: NormalizeCodec, hour: u8) -> String {
        format!(
            "{}/{}/{}",
            self.source_day,
            "normalized",
            format!("{hour:02}.{}", codec_name(codec))
        )
    }
}

#[derive(Debug, Default)]
struct BuildTotals {
    raw_event_count: u64,
    normalized_event_count: u64,
    dropped_secondary_event_count: u64,
    per_type: BTreeMap<String, u64>,
    first_created_at: Option<String>,
    last_created_at: Option<String>,
}

fn build_hour_minute_index(
    day: &str,
    hour: u8,
    relative_path: &str,
    minute_counts: &[u64; 60],
    minute_offsets: &[Option<MinuteOffsetRecord>],
    normalized_count: u64,
    uncompressed_byte_offset: u64,
) -> HourMinuteIndex {
    let mut resolved = Vec::with_capacity(60);
    let mut current_byte_offset = 0_u64;
    for minute in 0..60_u8 {
        if let Some(entry) = &minute_offsets[minute as usize] {
            current_byte_offset = if entry.event_count > 0 {
                entry.uncompressed_byte_offset + 0
            } else {
                entry.uncompressed_byte_offset
            };
            resolved.push(entry.clone());
        } else {
            let event_index_offset = minute_counts[..minute as usize]
                .iter()
                .copied()
                .sum::<u64>();
            let fallback_offset = if event_index_offset == normalized_count {
                uncompressed_byte_offset
            } else {
                current_byte_offset
            };
            resolved.push(MinuteOffsetRecord {
                minute,
                second_of_day_start: (hour as u32) * 3600 + (minute as u32) * 60,
                event_index_offset,
                uncompressed_byte_offset: fallback_offset,
                event_count: 0,
            });
        }
    }

    for minute in 1..60 {
        if resolved[minute].event_count == 0 {
            resolved[minute].uncompressed_byte_offset =
                resolved[minute - 1].uncompressed_byte_offset;
        }
        if resolved[minute].event_index_offset < resolved[minute - 1].event_index_offset {
            resolved[minute].event_index_offset = resolved[minute - 1].event_index_offset;
        }
    }

    HourMinuteIndex {
        source_day: day.to_string(),
        hour,
        normalized_relative_path: relative_path.to_string(),
        minute_offsets: resolved,
    }
}

pub(crate) fn resolve_archive_root(config: &Config, override_root: Option<&Path>) -> PathBuf {
    override_root
        .map(Path::to_path_buf)
        .unwrap_or_else(|| PathBuf::from(&config.archive.root_dir))
}

fn ensure_all_raw_hours_exist(layout: &DayPackLayout) -> Result<()> {
    for hour in 0..24_u8 {
        let path = layout.raw_hour_path(hour);
        if !path.exists() {
            bail!("missing raw hour file: {}", path.display());
        }
    }
    Ok(())
}

pub(crate) fn validate_day(day: &str) -> Result<()> {
    let parts = day.split('-').collect::<Vec<_>>();
    if parts.len() != 3 {
        bail!("day must use YYYY-MM-DD");
    }
    let year = parts[0].parse::<u32>().ok();
    let month = parts[1].parse::<u32>().ok();
    let day_value = parts[2].parse::<u32>().ok();
    if year.is_none() || month.is_none() || day_value.is_none() {
        bail!("day must use YYYY-MM-DD");
    }
    Ok(())
}

fn checksum_record(path: &Path, archive_root: &Path) -> Result<FileChecksumRecord> {
    manifest::checksum_record(path, archive_root)
}

fn codec_name(codec: NormalizeCodec) -> &'static str {
    match codec {
        NormalizeCodec::JsonlZst => "jsonl.zst",
        NormalizeCodec::JsonlGz => "jsonl.gz",
    }
}

#[cfg(test)]
mod tests {
    use std::fs;

    use tempfile::tempdir;

    use super::*;
    use crate::config::schema::Config;

    #[test]
    fn fixture_seed_prepare_and_validate_round_trip() {
        let temp = tempdir().expect("tempdir");
        let archive_root = temp.path().join("archive");
        let day = "2026-03-19";

        seed_fixture_raw(&archive_root, day, true).expect("seed fixture");

        let mut config = Config::default();
        config.archive.root_dir = archive_root.display().to_string();

        let prepared =
            prepare_day_pack(&config, day, Some(&archive_root), true, true).expect("prepare");
        assert_eq!(prepared.raw_event_count, 48);
        assert_eq!(prepared.normalized_event_count, 24);
        assert_eq!(prepared.dropped_secondary_event_count, 24);
        let manifest: DayPackManifest =
            toml::from_str(&fs::read_to_string(&prepared.manifest_path).expect("read manifest"))
                .expect("parse manifest");
        assert_eq!(manifest.generator_version, env!("CARGO_PKG_VERSION"));
        assert!(!manifest.config_fingerprint.is_empty());

        let validated =
            validate_day_pack(&config, day, Some(&archive_root)).expect("validate day-pack");
        assert_eq!(validated.raw_file_count, 24);
        assert_eq!(validated.normalized_file_count, 24);
        assert_eq!(validated.normalized_event_count, 24);
        assert_eq!(validated.minute_index_hours, 24);
    }
}
