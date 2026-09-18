//! SoundFont resolution for stage5, mirroring the `make stage5-sf2` precedence.
//!
//! The repo does not bundle a SoundFont (`ops/assets/**` is gitignored), so the
//! weaver must never assume one fixed path: it resolves the same chain the
//! Makefile resolves and fails fast with the candidate list when nothing works.

use std::path::{Path, PathBuf};

use anyhow::{bail, Result};

pub const SOUNDFONT_ENV_VAR: &str = "MUSIKALISCHES_SOUNDFONT";
pub const DEFAULT_REPO_SOUNDFONT: &str = "ops/assets/soundfonts/default.sf2";
pub const DEFAULT_SYSTEM_SOUNDFONTS: [&str; 4] = [
    "/usr/share/sounds/sf2/FluidR3_GM.sf2",
    "/usr/share/sounds/sf2/TimGM6mb.sf2",
    "/usr/share/sounds/sf2/FluidR3Mono_GM.sf2",
    "/usr/local/share/sounds/sf2/default.sf2",
];

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct SoundfontChoice {
    pub path: PathBuf,
    /// Which candidate won: `explicit`, `env`, `repo_default` or `system`.
    pub source: String,
}

/// Pure precedence table: explicit > env > repo default > system candidates.
pub fn select_soundfont(
    explicit: Option<&Path>,
    env_value: Option<&Path>,
    repo_default: &Path,
    system_candidates: &[&str],
) -> Result<SoundfontChoice> {
    if let Some(path) = explicit {
        if !path.is_file() {
            bail!("soundfont path does not exist: {}", path.display());
        }
        return Ok(SoundfontChoice {
            path: path.to_path_buf(),
            source: "explicit".to_string(),
        });
    }
    if let Some(path) = env_value {
        if !path.is_file() {
            bail!(
                "soundfont path from {SOUNDFONT_ENV_VAR} does not exist: {}",
                path.display()
            );
        }
        return Ok(SoundfontChoice {
            path: path.to_path_buf(),
            source: "env".to_string(),
        });
    }
    if repo_default.is_file() {
        return Ok(SoundfontChoice {
            path: repo_default.to_path_buf(),
            source: "repo_default".to_string(),
        });
    }
    for candidate in system_candidates {
        let path = Path::new(candidate);
        if path.is_file() {
            return Ok(SoundfontChoice {
                path: path.to_path_buf(),
                source: "system".to_string(),
            });
        }
    }
    bail!(
        "missing SoundFont: pass --soundfont <path>, set {SOUNDFONT_ENV_VAR}=<path>, \
         place {}, or install one of: {}",
        repo_default.display(),
        system_candidates.join(", ")
    )
}

/// Resolve for a repo root, reading the environment for the second candidate.
pub fn resolve_soundfont(repo_root: &Path, explicit: Option<&str>) -> Result<SoundfontChoice> {
    let explicit_path = explicit.map(|raw| repo_root.join(raw));
    let env_path = std::env::var_os(SOUNDFONT_ENV_VAR).map(|value| repo_root.join(value));
    let repo_default = repo_root.join(DEFAULT_REPO_SOUNDFONT);
    select_soundfont(
        explicit_path.as_deref(),
        env_path.as_deref(),
        &repo_default,
        &DEFAULT_SYSTEM_SOUNDFONTS,
    )
}

#[cfg(test)]
mod tests {
    use super::*;

    fn scratch(name: &str) -> PathBuf {
        let root = std::env::temp_dir().join(format!("weaver-sf2-{name}-{}", std::process::id()));
        let _ = std::fs::remove_dir_all(&root);
        std::fs::create_dir_all(&root).expect("create scratch dir");
        root
    }

    fn touch(path: &Path) -> PathBuf {
        std::fs::write(path, b"sf2").expect("write sf2 stub");
        path.to_path_buf()
    }

    #[test]
    fn explicit_wins_over_env_repo_default_and_system() {
        let root = scratch("explicit");
        let explicit = touch(&root.join("explicit.sf2"));
        let env = touch(&root.join("env.sf2"));
        let repo_default = touch(&root.join("repo.sf2"));
        let system = touch(&root.join("system.sf2"));
        let choice = select_soundfont(
            Some(&explicit),
            Some(&env),
            &repo_default,
            &[system.to_str().unwrap()],
        )
        .unwrap();
        assert_eq!(choice.path, explicit);
        assert_eq!(choice.source, "explicit");
    }

    #[test]
    fn env_beats_repo_default_and_repo_default_beats_system() {
        let root = scratch("order");
        let env = touch(&root.join("env.sf2"));
        let repo_default = touch(&root.join("repo.sf2"));
        let system = touch(&root.join("system.sf2"));

        let from_env = select_soundfont(
            None,
            Some(&env),
            &repo_default,
            &[system.to_str().unwrap()],
        )
        .unwrap();
        assert_eq!(from_env.path, env);
        assert_eq!(from_env.source, "env");

        let from_repo = select_soundfont(
            None,
            None,
            &repo_default,
            &[system.to_str().unwrap()],
        )
        .unwrap();
        assert_eq!(from_repo.path, repo_default);
        assert_eq!(from_repo.source, "repo_default");
    }

    #[test]
    fn system_candidates_are_tried_in_order_and_skipped_when_missing() {
        let root = scratch("system");
        let missing = root.join("missing.sf2");
        let system = touch(&root.join("system.sf2"));
        let choice = select_soundfont(
            None,
            None,
            &missing,
            &[missing.to_str().unwrap(), system.to_str().unwrap()],
        )
        .unwrap();
        assert_eq!(choice.path, system);
        assert_eq!(choice.source, "system");
    }

    #[test]
    fn missing_explicit_soundfont_is_an_error() {
        let root = scratch("bad-explicit");
        let repo_default = touch(&root.join("repo.sf2"));
        let error = select_soundfont(
            Some(&root.join("nope.sf2")),
            None,
            &repo_default,
            &[repo_default.to_str().unwrap()],
        )
        .unwrap_err()
        .to_string();
        assert!(error.contains("does not exist"), "{error}");
        assert!(error.contains("nope.sf2"), "{error}");
    }

    #[test]
    fn no_candidate_names_the_env_var_and_the_candidates() {
        let root = scratch("none");
        let repo_default = root.join("ops/assets/soundfonts/default.sf2");
        let absent = ["/nonexistent/weaver-a.sf2", "/nonexistent/weaver-b.sf2"];
        let error = select_soundfont(None, None, &repo_default, &absent)
            .unwrap_err()
            .to_string();
        assert!(error.contains(SOUNDFONT_ENV_VAR), "{error}");
        assert!(error.contains("--soundfont"), "{error}");
        assert!(error.contains("weaver-a.sf2"), "{error}");
        assert!(error.contains(repo_default.to_str().unwrap()), "{error}");
    }
}
