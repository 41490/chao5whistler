pub mod schema;
pub mod validate;

use std::fs;
use std::path::{Path, PathBuf};

use anyhow::{bail, Context, Result};
use serde::{Deserialize, Serialize};
use toml::Value;

use self::schema::Config;

pub const RTMP_URL_ENV_VAR: &str = "SONGH_RTMP_URL";

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum OutputFormat {
    Json,
    Toml,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct LoadedConfig {
    pub config: Config,
    pub report: LoadReport,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct LoadReport {
    pub main_config_path: PathBuf,
    pub local_override_path: Option<PathBuf>,
    pub env_rtmp_override_applied: bool,
    pub warnings: Vec<String>,
}

pub fn load_from_path(
    main_config_path: &Path,
    explicit_local_override: Option<&Path>,
) -> Result<LoadedConfig> {
    if !main_config_path.exists() {
        bail!("config file not found: {}", main_config_path.display());
    }

    let main_text = fs::read_to_string(main_config_path)
        .with_context(|| format!("failed to read {}", main_config_path.display()))?;
    let mut merged = parse_toml_document(main_config_path, &main_text)?;

    let local_override_path =
        resolve_local_override_path(main_config_path, explicit_local_override)?;
    if let Some(path) = &local_override_path {
        let local_text = fs::read_to_string(path)
            .with_context(|| format!("failed to read {}", path.display()))?;
        let local_value = parse_toml_document(path, &local_text)?;
        deep_merge(&mut merged, local_value);
    }

    let mut config: Config = merged
        .try_into()
        .with_context(|| format!("failed to decode {}", main_config_path.display()))?;

    let mut env_rtmp_override_applied = false;
    if let Ok(url) = std::env::var(RTMP_URL_ENV_VAR) {
        if !url.trim().is_empty() {
            config.outputs.rtmp.url = url;
            env_rtmp_override_applied = true;
        }
    }

    let warnings = validate::validate(&config)?;
    let report = LoadReport {
        main_config_path: main_config_path.to_path_buf(),
        local_override_path,
        env_rtmp_override_applied,
        warnings,
    };

    Ok(LoadedConfig { config, report })
}

pub fn render_default_toml() -> Result<String> {
    Ok(toml::to_string_pretty(&Config::default())?)
}

fn resolve_local_override_path(
    main_config_path: &Path,
    explicit_local_override: Option<&Path>,
) -> Result<Option<PathBuf>> {
    if let Some(path) = explicit_local_override {
        if !path.exists() {
            bail!("local override file not found: {}", path.display());
        }
        return Ok(Some(path.to_path_buf()));
    }

    let parent = main_config_path.parent().unwrap_or_else(|| Path::new("."));
    let default_override = parent.join("songh.local.toml");
    if default_override.exists() {
        Ok(Some(default_override))
    } else {
        Ok(None)
    }
}

fn parse_toml_document(path: &Path, text: &str) -> Result<Value> {
    text.parse::<Value>()
        .with_context(|| format!("failed to parse TOML in {}", path.display()))
}

fn deep_merge(base: &mut Value, overlay: Value) {
    match (base, overlay) {
        (Value::Table(base_table), Value::Table(overlay_table)) => {
            for (key, value) in overlay_table {
                match base_table.get_mut(&key) {
                    Some(existing) => deep_merge(existing, value),
                    None => {
                        base_table.insert(key, value);
                    }
                }
            }
        }
        (base_slot, overlay_value) => {
            *base_slot = overlay_value;
        }
    }
}

#[cfg(test)]
mod tests {
    use std::fs;
    use std::sync::{Mutex, OnceLock};

    use tempfile::tempdir;

    use super::*;

    fn env_lock() -> &'static Mutex<()> {
        static LOCK: OnceLock<Mutex<()>> = OnceLock::new();
        LOCK.get_or_init(|| Mutex::new(()))
    }

    #[test]
    fn tracked_template_loads_cleanly() {
        let root = PathBuf::from(env!("CARGO_MANIFEST_DIR"))
            .parent()
            .and_then(|path| path.parent())
            .expect("repo root")
            .to_path_buf();
        let config_path = root.join("docs/plans/260321-songh-template.toml");
        let loaded = load_from_path(&config_path, None).expect("template should validate");
        assert_eq!(loaded.config.text.template, "{repo}/{hash:8}");
        assert!(loaded.report.warnings.is_empty());
    }

    #[test]
    fn local_example_merges_cleanly_with_template() {
        let root = PathBuf::from(env!("CARGO_MANIFEST_DIR"))
            .parent()
            .and_then(|path| path.parent())
            .expect("repo root")
            .to_path_buf();
        let template_path = root.join("docs/plans/260321-songh-template.toml");
        let example_path = root.join("src/songh/songh.local.toml.example");
        let temp = tempdir().expect("tempdir");
        let main_path = temp.path().join("songh.toml");
        let local_path = temp.path().join("songh.local.toml");

        fs::copy(&template_path, &main_path).expect("copy template");
        fs::copy(&example_path, &local_path).expect("copy example");

        let loaded = load_from_path(&main_path, None).expect("example should merge");
        assert_eq!(loaded.config.archive.root_dir, "/tmp/songh/archive");
        assert_eq!(
            loaded.config.outputs.record.path,
            "/tmp/songh/records/{date}/{label}.flv"
        );
    }

    #[test]
    fn local_override_wins_over_main_file() {
        let temp = tempdir().expect("tempdir");
        let main_path = temp.path().join("songh.toml");
        let local_path = temp.path().join("songh.local.toml");

        fs::write(
            &main_path,
            r#"[meta]
label = "main"

[outputs]
enable_rtmp = true
"#,
        )
        .expect("write main");
        fs::write(
            &local_path,
            r#"[meta]
label = "local"

[outputs.rtmp]
url = "rtmp://example.invalid/live"
"#,
        )
        .expect("write local");

        let loaded = load_from_path(&main_path, None).expect("load merged config");
        assert_eq!(loaded.config.meta.label, "local");
        assert_eq!(
            loaded.config.outputs.rtmp.url,
            "rtmp://example.invalid/live"
        );
    }

    #[test]
    fn env_override_supplies_rtmp_url() {
        let _guard = env_lock().lock().expect("env lock");
        let temp = tempdir().expect("tempdir");
        let main_path = temp.path().join("songh.toml");
        fs::write(
            &main_path,
            r#"[outputs]
enable_rtmp = true
"#,
        )
        .expect("write main");

        std::env::set_var(RTMP_URL_ENV_VAR, "rtmp://env.invalid/live");
        let loaded =
            load_from_path(&main_path, None).expect("env override should satisfy validation");
        std::env::remove_var(RTMP_URL_ENV_VAR);

        assert!(loaded.report.env_rtmp_override_applied);
        assert_eq!(loaded.config.outputs.rtmp.url, "rtmp://env.invalid/live");
    }

    #[test]
    fn fixed_day_requires_a_value() {
        let temp = tempdir().expect("tempdir");
        let main_path = temp.path().join("songh.toml");
        fs::write(
            &main_path,
            r#"[archive]
selector = "fixed_day"
"#,
        )
        .expect("write main");

        let error = load_from_path(&main_path, None).expect_err("missing fixed_day must fail");
        assert!(error.to_string().contains("archive.fixed_day"));
    }

    #[test]
    fn unknown_template_field_is_fatal() {
        let temp = tempdir().expect("tempdir");
        let main_path = temp.path().join("songh.toml");
        fs::write(
            &main_path,
            r#"[text]
template = "{repo}/{missing}"
"#,
        )
        .expect("write main");

        let error = load_from_path(&main_path, None).expect_err("unknown template field must fail");
        assert!(error.to_string().contains("text.template"));
    }
}
