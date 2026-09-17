//! Configurable adapter for the stage5 / stage6 / bridge commands.
//!
//! The weaver never hardcodes a Makefile target or a tool path. Every external
//! command is a named step in a JSON adapter config: `program` plus `args`,
//! where args may contain `{placeholder}` tokens the weaver substitutes from
//! the run config and the current asset. That keeps the default adapter pointed
//! at the existing Python tools while letting tests swap in fakes.

use std::collections::BTreeMap;
use std::fs::File;
use std::path::{Path, PathBuf};
use std::process::{Command, Stdio};
use std::thread;
use std::time::{Duration, Instant};

use anyhow::{anyhow, bail, Context, Result};
use serde::{Deserialize, Serialize};

use super::jsonio;

/// Render audio for a new combination (existing stage5 tool by default).
pub const STEP_STAGE5_AUDIO: &str = "stage5_audio";
/// Derive the stage6 video stub from the stage5 artifacts (optional).
pub const STEP_STAGE6_STUB: &str = "stage6_stub";
/// Render the offline video preview (existing stage6 tool by default).
pub const STEP_STAGE6_VIDEO: &str = "stage6_video";
/// Freeze the bridge contract for the published asset (optional).
pub const STEP_BRIDGE_BUILD: &str = "bridge_build";
/// Hand the published asset to the bridge for playback (fake bridge in tests).
pub const STEP_BRIDGE_RUN: &str = "bridge_run";

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct AdapterStep {
    pub program: String,
    #[serde(default)]
    pub args: Vec<String>,
    /// Per-step wall-clock budget; falls back to the weaver-wide value.
    #[serde(default)]
    pub timeout_seconds: Option<f64>,
    #[serde(default)]
    pub description: Option<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct AdapterConfig {
    pub adapter_id: String,
    #[serde(default)]
    pub description: Option<String>,
    pub steps: BTreeMap<String, AdapterStep>,
}

impl AdapterConfig {
    pub fn from_path(path: &Path) -> Result<Self> {
        jsonio::read_json(path).with_context(|| format!("load adapter config {}", path.display()))
    }
}

#[derive(Debug, Clone, Serialize)]
pub struct StepOutcome {
    pub step: String,
    pub argv: Vec<String>,
    pub exit_code: i32,
    pub timed_out: bool,
    pub duration_seconds: f64,
    pub log_path: String,
}

impl StepOutcome {
    pub fn succeeded(&self) -> bool {
        self.exit_code == 0 && !self.timed_out
    }
}

#[derive(Debug, Clone)]
pub struct Adapter {
    config: AdapterConfig,
    vars: BTreeMap<String, String>,
    repo_root: PathBuf,
    default_timeout_seconds: Option<f64>,
}

impl Adapter {
    pub fn load(path: &Path) -> Result<Self> {
        let config = AdapterConfig::from_path(path)?;
        Ok(Self {
            config,
            vars: BTreeMap::new(),
            repo_root: PathBuf::from("."),
            default_timeout_seconds: None,
        })
    }

    pub fn adapter_id(&self) -> &str {
        &self.config.adapter_id
    }

    pub fn set_repo_root(&mut self, repo_root: &Path) {
        self.repo_root = repo_root.to_path_buf();
    }

    pub fn set_default_timeout(&mut self, timeout_seconds: Option<f64>) {
        self.default_timeout_seconds = timeout_seconds;
    }

    pub fn set_var(&mut self, key: &str, value: impl Into<String>) {
        self.vars.insert(key.to_string(), value.into());
    }

    pub fn has_step(&self, step: &str) -> bool {
        self.config.steps.contains_key(step)
    }

    pub fn step_names(&self) -> Vec<String> {
        self.config.steps.keys().cloned().collect()
    }

    /// Resolve `program` plus `args` with placeholders substituted.
    pub fn render_step(&self, step: &str) -> Result<Vec<String>> {
        let definition = self
            .config
            .steps
            .get(step)
            .ok_or_else(|| anyhow!("adapter config has no step named {step}"))?;
        let mut argv = Vec::with_capacity(definition.args.len() + 1);
        argv.push(substitute(&definition.program, &self.vars)?);
        for arg in &definition.args {
            argv.push(substitute(arg, &self.vars)?);
        }
        Ok(argv)
    }

    pub fn step_timeout_seconds(&self, step: &str) -> Result<Option<f64>> {
        let definition = self
            .config
            .steps
            .get(step)
            .ok_or_else(|| anyhow!("adapter config has no step named {step}"))?;
        Ok(definition.timeout_seconds.or(self.default_timeout_seconds))
    }

    /// Run a required step; a missing step definition is a config error.
    pub fn run_step(&self, step: &str, log_dir: &Path) -> Result<StepOutcome> {
        let argv = self.render_step(step)?;
        let timeout = self.step_timeout_seconds(step)?;
        self.execute(step, &argv, timeout, log_dir)
    }

    /// Run an optional step; `Ok(None)` when the adapter does not define it.
    pub fn run_optional_step(&self, step: &str, log_dir: &Path) -> Result<Option<StepOutcome>> {
        if !self.has_step(step) {
            return Ok(None);
        }
        self.run_step(step, log_dir).map(Some)
    }

    fn execute(
        &self,
        step: &str,
        argv: &[String],
        timeout: Option<f64>,
        log_dir: &Path,
    ) -> Result<StepOutcome> {
        let program = argv
            .first()
            .ok_or_else(|| anyhow!("adapter step {step} rendered an empty argv"))?;
        std::fs::create_dir_all(log_dir)
            .with_context(|| format!("create log dir {}", log_dir.display()))?;
        let log_path = log_dir.join(format!("{step}.log"));
        let log_handle = File::create(&log_path)
            .with_context(|| format!("create step log {}", log_path.display()))?;
        let log_clone = log_handle
            .try_clone()
            .with_context(|| format!("clone step log handle {}", log_path.display()))?;

        let mut command = Command::new(program);
        command.args(&argv[1..]);
        command.current_dir(&self.repo_root);
        command.stdin(Stdio::null());
        command.stdout(Stdio::from(log_handle));
        command.stderr(Stdio::from(log_clone));

        let started = Instant::now();
        let mut child = command
            .spawn()
            .with_context(|| format!("spawn adapter step {step}: {program}"))?;
        let mut timed_out = false;
        let exit_code = loop {
            if let Some(status) = child
                .try_wait()
                .with_context(|| format!("wait for adapter step {step}"))?
            {
                break status.code().unwrap_or(1);
            }
            if let Some(limit) = timeout {
                if started.elapsed().as_secs_f64() >= limit {
                    timed_out = true;
                    let _ = child.kill();
                    let status = child.wait()?;
                    break status.code().unwrap_or(124);
                }
            }
            thread::sleep(Duration::from_millis(50));
        };

        Ok(StepOutcome {
            step: step.to_string(),
            argv: argv.to_vec(),
            exit_code,
            timed_out,
            duration_seconds: jsonio::round6(started.elapsed().as_secs_f64()),
            log_path: log_path.display().to_string(),
        })
    }
}

/// Replace `{placeholder}` tokens; a `{...}` that is not a known identifier is
/// passed through untouched so adapter args may contain literal braces.
fn substitute(text: &str, vars: &BTreeMap<String, String>) -> Result<String> {
    let mut out = String::with_capacity(text.len());
    let mut rest = text;
    while let Some(open) = rest.find('{') {
        out.push_str(&rest[..open]);
        let after = &rest[open + 1..];
        let Some(close) = after.find('}') else {
            bail!("unterminated placeholder in adapter value {text:?}");
        };
        let name = &after[..close];
        let is_identifier = !name.is_empty()
            && name
                .bytes()
                .all(|byte| byte.is_ascii_alphanumeric() || byte == b'_');
        if is_identifier {
            let value = vars
                .get(name)
                .ok_or_else(|| anyhow!("unknown adapter placeholder {{{name}}} in {text:?}"))?;
            out.push_str(value);
        } else {
            out.push('{');
            out.push_str(name);
            out.push('}');
        }
        rest = &after[close + 1..];
    }
    out.push_str(rest);
    Ok(out)
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::collections::BTreeMap;

    fn vars() -> BTreeMap<String, String> {
        BTreeMap::from([
            ("asset_dir".to_string(), "/buffer/comb-1".to_string()),
            ("combination_id".to_string(), "1,2".to_string()),
        ])
    }

    #[test]
    fn substitutes_known_placeholders() {
        assert_eq!(
            substitute("{asset_dir}/{combination_id}.json", &vars()).unwrap(),
            "/buffer/comb-1/1,2.json"
        );
    }

    #[test]
    fn unknown_placeholder_is_a_config_error() {
        let error = substitute("{nope}", &vars()).unwrap_err();
        assert!(error.to_string().contains("unknown adapter placeholder"));
    }

    #[test]
    fn non_identifier_braces_pass_through() {
        assert_eq!(
            substitute("drawtext=text='{a b}'", &vars()).unwrap(),
            "drawtext=text='{a b}'"
        );
    }

    #[test]
    fn unterminated_placeholder_is_rejected() {
        assert!(substitute("oops {asset_dir", &vars()).is_err());
    }

    #[test]
    fn step_lookup_reports_missing_steps() {
        let dir = std::env::temp_dir().join(format!("weaver-adapter-{}", std::process::id()));
        std::fs::create_dir_all(&dir).unwrap();
        let path = dir.join("adapter.json");
        std::fs::write(
            &path,
            r#"{"adapter_id":"test","steps":{"bridge_run":{"program":"python3","args":["{asset_dir}"]}}}"#,
        )
        .unwrap();
        let mut adapter = Adapter::load(&path).unwrap();
        adapter.set_var("asset_dir", "/buffer/comb-1");
        assert_eq!(adapter.adapter_id(), "test");
        assert!(adapter.has_step(STEP_BRIDGE_RUN));
        assert!(!adapter.has_step(STEP_STAGE5_AUDIO));
        assert_eq!(
            adapter.render_step(STEP_BRIDGE_RUN).unwrap(),
            vec!["python3".to_string(), "/buffer/comb-1".to_string()]
        );
        assert!(adapter.render_step(STEP_STAGE5_AUDIO).is_err());
        assert!(adapter.run_optional_step(STEP_STAGE6_STUB, &dir).unwrap().is_none());
        std::fs::remove_dir_all(&dir).unwrap();
    }

    #[test]
    fn runs_a_step_and_captures_exit_code_and_log() {
        let dir = std::env::temp_dir().join(format!("weaver-adapter-run-{}", std::process::id()));
        let _ = std::fs::remove_dir_all(&dir);
        let log_dir = dir.join("logs");
        std::fs::create_dir_all(&dir).unwrap();
        let path = dir.join("adapter.json");
        std::fs::write(
            &path,
            r#"{"adapter_id":"test","steps":{"bridge_run":{"program":"sh","args":["-c","echo hello; exit 7"]}}}"#,
        )
        .unwrap();
        let adapter = Adapter::load(&path).unwrap();
        let outcome = adapter.run_step(STEP_BRIDGE_RUN, &log_dir).unwrap();
        assert_eq!(outcome.exit_code, 7);
        assert!(!outcome.succeeded());
        let log = std::fs::read_to_string(&outcome.log_path).unwrap();
        assert!(log.contains("hello"));
        std::fs::remove_dir_all(&dir).unwrap();
    }
}
