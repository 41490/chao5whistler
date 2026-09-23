//! Asset hashing.
//!
//! The publish unit records a `sha256` for every file it ships so a consumer
//! can prove the bytes it reads are the bytes that were published. The digest
//! is produced by the system `sha256sum` (coreutils) through the same
//! process-spawning path the rest of the repo uses for `python3` / `ffmpeg`.
//!
//! Deliberately not a Rust `sha2` dependency: issue #62's mana grant does not
//! cover `Cargo.lock`, and a direct dependency rewrites it.

use std::path::Path;
use std::process::Command;

use anyhow::{anyhow, bail, Context, Result};

/// Default digest tool. Overridable from the CLI for non-coreutils hosts.
pub const DEFAULT_SHA256SUM_BIN: &str = "sha256sum";

/// Digest of a file as lowercase hex.
pub fn sha256_file(sha256sum_bin: &str, path: &Path) -> Result<String> {
    let output = Command::new(sha256sum_bin)
        .arg(path)
        .output()
        .with_context(|| format!("run {sha256sum_bin} {}", path.display()))?;
    if !output.status.success() {
        let stderr = String::from_utf8_lossy(&output.stderr);
        bail!(
            "{sha256sum_bin} failed for {} (exit {:?}): {}",
            path.display(),
            output.status.code(),
            stderr.trim()
        );
    }
    let stdout = String::from_utf8_lossy(&output.stdout);
    let digest = stdout
        .split_whitespace()
        .next()
        .ok_or_else(|| anyhow!("{sha256sum_bin} produced no digest for {}", path.display()))?;
    if digest.len() != 64 || !digest.bytes().all(|byte| byte.is_ascii_hexdigit()) {
        bail!(
            "{sha256sum_bin} produced an unexpected digest for {}: {digest}",
            path.display()
        );
    }
    Ok(digest.to_ascii_lowercase())
}

#[cfg(test)]
mod tests {
    use super::*;

    fn scratch_dir(tag: &str) -> std::path::PathBuf {
        let dir = std::env::temp_dir().join(format!(
            "weaver-hash-{tag}-{}-{:?}",
            std::process::id(),
            std::thread::current().id()
        ));
        let _ = std::fs::remove_dir_all(&dir);
        std::fs::create_dir_all(&dir).unwrap();
        dir
    }

    #[test]
    fn empty_file_matches_known_vector() {
        let dir = scratch_dir("empty");
        let path = dir.join("empty.bin");
        std::fs::write(&path, b"").unwrap();
        assert_eq!(
            sha256_file(DEFAULT_SHA256SUM_BIN, &path).unwrap(),
            "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
        );
        std::fs::remove_dir_all(&dir).unwrap();
    }

    #[test]
    fn abc_matches_known_vector() {
        let dir = scratch_dir("abc");
        let path = dir.join("abc.bin");
        std::fs::write(&path, b"abc").unwrap();
        assert_eq!(
            sha256_file(DEFAULT_SHA256SUM_BIN, &path).unwrap(),
            "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"
        );
        std::fs::remove_dir_all(&dir).unwrap();
    }

    #[test]
    fn missing_file_is_an_error_not_a_panic() {
        let error = sha256_file(
            DEFAULT_SHA256SUM_BIN,
            Path::new("/definitely/not/here/weaver.bin"),
        )
        .unwrap_err();
        assert!(error.to_string().contains("sha256sum"));
    }
}
