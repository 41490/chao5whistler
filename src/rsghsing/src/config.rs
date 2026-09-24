//! rsghsing configuration.
//!
//! Normative reference: `src/ghsingo/internal/config/config.go`.
//! Semantics kept identical on purpose:
//!   * one base TOML file;
//!   * an optional sibling `<basename>.local.toml` overlay that overrides
//!     ONLY the keys it actually mentions (deep merge on tables);
//!   * `target_date = "yesterday" | "today"` resolves to a YYYY-MM-DD string.
//!
//! P1 models only the sections `prepare` needs (meta / archive / events /
//! output). Unknown sections (audio, video, composer, mixer, assets, observe)
//! are ignored by serde, so the shared rsghsing.toml profile keeps parsing;
//! add them here when a later subcommand needs them.

use std::collections::BTreeMap;
use std::path::{Path, PathBuf};
use std::time::{SystemTime, UNIX_EPOCH};

use anyhow::{bail, Context, Result};
use serde::Deserialize;

#[derive(Debug, Clone, Default, Deserialize)]
pub struct Config {
    #[serde(default)]
    pub meta: Meta,
    #[serde(default)]
    pub archive: Archive,
    #[serde(default)]
    pub events: Events,
    #[serde(default)]
    pub output: Output,
}

#[derive(Debug, Clone, Default, Deserialize)]
pub struct Meta {
    pub profile: String,
    pub engine: String,
}

#[derive(Debug, Clone, Default, Deserialize)]
pub struct Archive {
    pub source_dir: String,
    pub daypack_dir: String,
    pub target_date: String,
    #[serde(default)]
    pub download: ArchiveDownload,
}

#[derive(Debug, Clone, Default, Deserialize)]
pub struct ArchiveDownload {
    pub enabled: bool,
    pub base_url: String,
    pub timeout_secs: u64,
    pub max_parallel: usize,
    pub user_agent: String,
}

#[derive(Debug, Clone, Default, Deserialize)]
pub struct Events {
    pub types: Vec<String>,
    pub max_per_second: usize,
    pub dedupe_window_secs: i64,
    #[serde(default)]
    pub weights: BTreeMap<String, i64>,
}

#[derive(Debug, Clone, Default, Deserialize)]
pub struct Output {
    pub mode: String,
    #[serde(default)]
    pub rtmps: OutputRTMPS,
}

#[derive(Debug, Clone, Default, Deserialize)]
pub struct OutputRTMPS {
    pub url: String,
}

impl Config {
    /// Loads `path`, then overlays `<stem>.local.<ext>` when it exists.
    pub fn load(path: &Path) -> Result<Config> {
        let text = std::fs::read_to_string(path)
            .with_context(|| format!("read config {}", path.display()))?;
        let mut merged: toml::Value =
            toml::from_str(&text).with_context(|| format!("parse config {}", path.display()))?;

        let local = local_overlay_path(path);
        if let Ok(local_text) = std::fs::read_to_string(&local) {
            let overlay: toml::Value = toml::from_str(&local_text)
                .with_context(|| format!("parse local overlay {}", local.display()))?;
            merge_value(&mut merged, overlay);
        }

        let mut cfg: Config = merged.try_into().context("deserialize merged config")?;
        cfg.resolve_paths(path);
        cfg.validate()?;
        Ok(cfg)
    }

    /// Relative `[archive]` paths resolve against the config file's directory
    /// so `--config` behaves identically from any CWD. ghsingo resolves them
    /// against the CWD; when the config sits next to the CWD (its documented
    /// invocation) the two agree exactly.
    fn resolve_paths(&mut self, base: &Path) {
        let dir = base.parent().unwrap_or(Path::new("."));
        for field in [&mut self.archive.source_dir, &mut self.archive.daypack_dir] {
            if field.is_empty() || Path::new(field.as_str()).is_absolute() {
                continue;
            }
            *field = dir.join(&*field).to_string_lossy().into_owned();
        }
    }

    /// "" and "v2" both resolve to v2; anything else is rejected by validate().
    /// Mirrors Go `Config.ResolvedEngine()` (post-#38 "v2 only").
    pub fn resolved_engine(&self) -> &str {
        match self.meta.engine.as_str() {
            "" | "v2" => "v2",
            other => other,
        }
    }

    fn validate(&self) -> Result<()> {
        match self.output.mode.as_str() {
            "local" | "rtmps" => {}
            other => bail!(
                "output.mode must be \"local\" or \"rtmps\", got {:?}",
                other
            ),
        }
        if self.output.mode == "rtmps" && self.output.rtmps.url.is_empty() {
            bail!("output.rtmps.url required when mode is \"rtmps\"");
        }
        if self.events.max_per_second == 0 {
            bail!("events.max_per_second must be positive");
        }
        if self.resolved_engine() != "v2" {
            bail!(
                "meta.engine = {:?} is not supported (only \"v2\" remains after #38)",
                self.meta.engine
            );
        }
        Ok(())
    }
}

/// "rsghsing.toml" -> "rsghsing.local.toml"
pub fn local_overlay_path(base: &Path) -> PathBuf {
    let ext = base
        .extension()
        .map(|e| format!(".{}", e.to_string_lossy()))
        .unwrap_or_default();
    let stem = base
        .to_string_lossy()
        .strip_suffix(&ext)
        .unwrap_or(&base.to_string_lossy())
        .to_string();
    PathBuf::from(format!("{stem}.local{ext}"))
}

/// Deep merge: overlay keys win, keys the overlay does not mention survive.
fn merge_value(base: &mut toml::Value, overlay: toml::Value) {
    match (base, overlay) {
        (toml::Value::Table(b), toml::Value::Table(o)) => {
            for (k, v) in o {
                match b.get_mut(&k) {
                    Some(slot) => merge_value(slot, v),
                    None => {
                        b.insert(k, v);
                    }
                }
            }
        }
        (slot, v) => *slot = v,
    }
}

/// Resolves symbolic date names, mirroring Go `config.ResolveTargetDate`.
/// UTC is used explicitly (decision baseline #1: UTC execution); Go uses
/// local time, which is UTC on every host rsghsing runs on.
pub fn resolve_target_date(spec: &str) -> String {
    match spec {
        "today" => ymd(utc_days()),
        "yesterday" => ymd(utc_days() - 1),
        other => other.to_string(),
    }
}

fn utc_days() -> i64 {
    let secs = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|d| d.as_secs() as i64)
        .unwrap_or(0);
    secs.div_euclid(86_400)
}

fn ymd(days: i64) -> String {
    let (y, m, d) = civil_from_days(days);
    format!("{y:04}-{m:02}-{d:02}")
}

/// Howard Hinnant's `civil_from_days`: days since 1970-01-01 -> (y, m, d).
fn civil_from_days(z: i64) -> (i64, u32, u32) {
    let z = z + 719_468;
    let era = if z >= 0 { z } else { z - 146_096 } / 146_097;
    let doe = z - era * 146_097;
    let yoe = (doe - doe / 1460 + doe / 36_524 - doe / 146_096) / 365;
    let y = yoe + era * 400;
    let doy = doe - (365 * yoe + yoe / 4 - yoe / 100);
    let mp = (5 * doy + 2) / 153;
    let d = (doy - (153 * mp + 2) / 5 + 1) as u32;
    let m = if mp < 10 { mp + 3 } else { mp - 9 } as u32;
    (y + i64::from(m <= 2), m, d)
}

/// Inverse of `civil_from_days`.
#[cfg(test)]
fn days_from_civil(y: i64, m: u32, d: u32) -> i64 {
    let y = if m <= 2 { y - 1 } else { y };
    let era = if y >= 0 { y } else { y - 399 } / 400;
    let yoe = y - era * 400;
    let mp = i64::from(if m > 2 { m - 3 } else { m + 9 });
    let doy = (153 * mp + 2) / 5 + i64::from(d) - 1;
    let doe = yoe * 365 + yoe / 4 - yoe / 100 + doy;
    era * 146_097 + doe - 719_468
}

#[cfg(test)]
mod tests {
    use super::*;

    const BASE: &str = r#"
[meta]
profile = "ambient"
engine  = "v2"

[archive]
source_dir   = "var/rsghsing/archive/raw"
daypack_dir  = "var/rsghsing/daypack"
target_date  = "2026-03-28"

[archive.download]
enabled      = false
base_url     = "https://data.gharchive.org"
timeout_secs = 60
max_parallel = 4
user_agent   = "rsghsing/0.1"

[events]
types = ["PushEvent", "CreateEvent"]
max_per_second = 4
dedupe_window_secs = 600

[events.weights]
PushEvent = 30
CreateEvent = 40

[output]
mode = "local"

[output.local]
path = "var/rsghsing/records/{date}.flv"

[output.rtmps]
url = ""
"#;

    /// Scratch dir under the OS temp dir; no `tempfile` dep needed.
    fn scratch(name: &str) -> PathBuf {
        let dir = std::env::temp_dir().join(format!("rsghsing-test-{name}"));
        let _ = std::fs::remove_dir_all(&dir);
        std::fs::create_dir_all(&dir).unwrap();
        dir
    }

    fn write(dir: &Path, name: &str, body: &str) -> PathBuf {
        let p = dir.join(name);
        std::fs::write(&p, body).unwrap();
        p
    }

    #[test]
    fn load_valid_config() {
        let dir = scratch("valid");
        let cfg = Config::load(&write(&dir, "rsghsing.toml", BASE)).unwrap();
        assert_eq!(cfg.meta.profile, "ambient");
        assert_eq!(cfg.archive.target_date, "2026-03-28");
        assert_eq!(cfg.events.max_per_second, 4);
        assert_eq!(cfg.events.dedupe_window_secs, 600);
        assert_eq!(cfg.events.weights["PushEvent"], 30);
        assert_eq!(cfg.output.mode, "local");
        assert_eq!(cfg.resolved_engine(), "v2");
    }

    /// Rust counterpart of Go `TestLoadLocalOverlay`: the overlay overrides
    /// only the keys it mentions; every base value survives.
    #[test]
    fn local_overlay_overrides_only_present_keys() {
        let dir = scratch("overlay");
        write(&dir, "rsghsing.toml", BASE);
        write(
            &dir,
            "rsghsing.local.toml",
            r#"
[output]
mode = "rtmps"

[output.rtmps]
url = "rtmps://a.rtmps.youtube.com/live2/test-key"
"#,
        );
        let cfg = Config::load(&dir.join("rsghsing.toml")).unwrap();
        assert_eq!(cfg.output.mode, "rtmps");
        assert_eq!(
            cfg.output.rtmps.url,
            "rtmps://a.rtmps.youtube.com/live2/test-key"
        );
        assert_eq!(cfg.meta.profile, "ambient");
        assert_eq!(cfg.events.max_per_second, 4);
        assert_eq!(cfg.events.weights["CreateEvent"], 40);
        assert_eq!(cfg.archive.target_date, "2026-03-28");
    }

    #[test]
    fn overlay_merges_nested_tables_without_dropping_siblings() {
        let dir = scratch("nested");
        write(&dir, "rsghsing.toml", BASE);
        write(
            &dir,
            "rsghsing.local.toml",
            "[events]\nmax_per_second = 8\n",
        );
        let cfg = Config::load(&dir.join("rsghsing.toml")).unwrap();
        assert_eq!(cfg.events.max_per_second, 8);
        assert_eq!(cfg.events.dedupe_window_secs, 600);
        assert_eq!(cfg.events.weights.len(), 2);
    }

    #[test]
    fn relative_archive_paths_resolve_against_the_config_dir() {
        let dir = scratch("paths");
        let cfg = Config::load(&write(&dir, "rsghsing.toml", BASE)).unwrap();
        assert!(
            cfg.archive
                .source_dir
                .starts_with(&dir.to_string_lossy().to_string()),
            "{}",
            cfg.archive.source_dir
        );
        assert!(
            cfg.archive
                .daypack_dir
                .starts_with(&dir.to_string_lossy().to_string()),
            "{}",
            cfg.archive.daypack_dir
        );
        assert!(cfg.archive.source_dir.ends_with("var/rsghsing/archive/raw"));
    }

    #[test]
    fn missing_overlay_is_fine() {
        let dir = scratch("nolocal");
        let cfg = Config::load(&write(&dir, "rsghsing.toml", BASE)).unwrap();
        assert_eq!(cfg.output.mode, "local");
        assert!(cfg.output.rtmps.url.is_empty());
    }

    #[test]
    fn rejects_invalid_output_mode() {
        let dir = scratch("badmode");
        let bad = BASE.replace("mode = \"local\"", "mode = \"INVALID\"");
        let err = Config::load(&write(&dir, "rsghsing.toml", &bad)).unwrap_err();
        assert!(err.to_string().contains("INVALID"), "{err}");
    }

    #[test]
    fn rejects_rtmps_without_url() {
        let dir = scratch("nourl");
        let bad = BASE.replace("mode = \"local\"", "mode = \"rtmps\"");
        let err = Config::load(&write(&dir, "rsghsing.toml", &bad)).unwrap_err();
        assert!(err.to_string().contains("rtmps.url"), "{err}");
    }

    #[test]
    fn rejects_engine_other_than_v2() {
        let dir = scratch("engine");
        let bad = BASE.replace("engine  = \"v2\"", "engine  = \"v3\"");
        let err = Config::load(&write(&dir, "rsghsing.toml", &bad)).unwrap_err();
        assert!(err.to_string().contains("v2"), "{err}");
    }

    #[test]
    fn resolve_target_date_symbols_and_literal() {
        let today = resolve_target_date("today");
        let yesterday = resolve_target_date("yesterday");
        assert_eq!(resolve_target_date("2026-03-28"), "2026-03-28");
        let (y, m, d) = parse_ymd(&today);
        assert_eq!(ymd(days_from_civil(y, m, d) - 1), yesterday);
    }

    fn parse_ymd(s: &str) -> (i64, u32, u32) {
        let n: Vec<u32> = s.split('-').map(|p| p.parse().unwrap()).collect();
        (i64::from(n[0]), n[1], n[2])
    }
}
