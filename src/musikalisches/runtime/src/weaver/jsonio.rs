//! Small JSON / timestamp helpers shared by the weaver modules.

use std::fs::{self, File};
use std::io::Write;
use std::path::Path;

use anyhow::{anyhow, Context, Result};
use chrono::{DateTime, SecondsFormat, Utc};
use serde::de::DeserializeOwned;
use serde::Serialize;
use serde_json::Value;

/// RFC3339 UTC timestamp with second precision, matching the repo's other artifacts.
pub fn utc_now() -> String {
    Utc::now().to_rfc3339_opts(SecondsFormat::Secs, true)
}

pub fn parse_timestamp(value: &str) -> Result<DateTime<Utc>> {
    Ok(DateTime::parse_from_rfc3339(value)
        .with_context(|| format!("parse timestamp {value}"))?
        .with_timezone(&Utc))
}

/// Whole seconds between `value` and `now`; negative when `value` is in the future.
pub fn age_seconds(value: &str, now: DateTime<Utc>) -> Result<i64> {
    Ok((now - parse_timestamp(value)?).num_seconds())
}

pub fn round6(value: f64) -> f64 {
    (value * 1_000_000.0).round() / 1_000_000.0
}

/// Write JSON through a sibling temp file plus `rename`, so a crash never leaves
/// a half-written state file behind.
pub fn write_json_atomic<T: Serialize>(path: &Path, value: &T) -> Result<()> {
    let parent = path
        .parent()
        .ok_or_else(|| anyhow!("path has no parent directory: {}", path.display()))?;
    fs::create_dir_all(parent).with_context(|| format!("create dir {}", parent.display()))?;
    let file_name = path
        .file_name()
        .ok_or_else(|| anyhow!("path has no file name: {}", path.display()))?
        .to_string_lossy()
        .to_string();
    let tmp_path = parent.join(format!(".{file_name}.tmp-{}", std::process::id()));

    let serialized = serde_json::to_string_pretty(value)?;
    {
        let mut handle = File::create(&tmp_path)
            .with_context(|| format!("create temp file {}", tmp_path.display()))?;
        handle
            .write_all(serialized.as_bytes())
            .with_context(|| format!("write temp file {}", tmp_path.display()))?;
        handle.write_all(b"\n")?;
        handle.sync_all()?;
    }
    fs::rename(&tmp_path, path)
        .with_context(|| format!("publish {} -> {}", tmp_path.display(), path.display()))?;
    Ok(())
}

pub fn read_json<T: DeserializeOwned>(path: &Path) -> Result<T> {
    let raw =
        fs::read_to_string(path).with_context(|| format!("read json file {}", path.display()))?;
    serde_json::from_str(&raw).with_context(|| format!("parse json file {}", path.display()))
}

pub fn read_json_value(path: &Path) -> Result<Value> {
    read_json(path)
}
