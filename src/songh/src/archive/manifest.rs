use std::collections::BTreeMap;
use std::fs;
use std::io::Read;
use std::path::Path;

use anyhow::{Context, Result};
use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha256};

use crate::config::schema::Config;

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct DayPackManifest {
    pub schema_version: String,
    pub source_day: String,
    pub generated_at_utc: String,
    pub generator_version: String,
    pub config_fingerprint: String,
    pub complete: bool,
    pub codec: String,
    pub supported_event_classes: Vec<String>,
    pub raw_hours: Vec<HourManifestRecord>,
    pub normalized_hours: Vec<HourManifestRecord>,
    pub index_files: Vec<IndexRecord>,
    pub totals: ManifestTotals,
    pub created_at_range: CreatedAtRange,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct HourManifestRecord {
    pub hour: u8,
    pub relative_path: String,
    pub size_bytes: u64,
    pub sha256: String,
    pub event_count: u64,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct IndexRecord {
    pub kind: String,
    pub relative_path: String,
    pub size_bytes: u64,
    pub sha256: String,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ManifestTotals {
    pub raw_event_count: u64,
    pub normalized_event_count: u64,
    pub dropped_secondary_event_count: u64,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct CreatedAtRange {
    pub first_created_at_utc: Option<String>,
    pub last_created_at_utc: Option<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct DayPackStats {
    pub schema_version: String,
    pub source_day: String,
    pub generated_at_utc: String,
    pub raw_event_count: u64,
    pub normalized_event_count: u64,
    pub dropped_secondary_event_count: u64,
    pub supported_event_classes: Vec<String>,
    pub per_event_type: BTreeMap<String, u64>,
    pub first_created_at_utc: Option<String>,
    pub last_created_at_utc: Option<String>,
    pub per_hour: Vec<HourStats>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct HourStats {
    pub hour: u8,
    pub raw_event_count: u64,
    pub normalized_event_count: u64,
    pub dropped_secondary_event_count: u64,
    pub per_event_type: BTreeMap<String, u64>,
    pub first_created_at_utc: Option<String>,
    pub last_created_at_utc: Option<String>,
}

#[derive(Debug, Clone)]
pub struct FileChecksumRecord {
    pub relative_path: String,
    pub size_bytes: u64,
    pub sha256: String,
}

pub fn checksum_record(path: &Path, archive_root: &Path) -> Result<FileChecksumRecord> {
    let metadata =
        fs::metadata(path).with_context(|| format!("failed to stat {}", path.display()))?;
    let mut hasher = Sha256::new();
    let mut file =
        fs::File::open(path).with_context(|| format!("failed to open {}", path.display()))?;
    let mut buffer = [0_u8; 64 * 1024];
    loop {
        let read = file
            .read(&mut buffer)
            .with_context(|| format!("failed to read {}", path.display()))?;
        if read == 0 {
            break;
        }
        hasher.update(&buffer[..read]);
    }

    let relative = path
        .strip_prefix(archive_root)
        .unwrap_or(path)
        .to_string_lossy()
        .replace('\\', "/");

    Ok(FileChecksumRecord {
        relative_path: relative,
        size_bytes: metadata.len(),
        sha256: hex::encode(hasher.finalize()),
    })
}

pub fn config_fingerprint(config: &Config) -> Result<String> {
    let payload = serde_json::to_vec(config)?;
    let mut hasher = Sha256::new();
    hasher.update(payload);
    Ok(hex::encode(hasher.finalize()))
}
