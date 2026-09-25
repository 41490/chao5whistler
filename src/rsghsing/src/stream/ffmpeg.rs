//! Persistent ffmpeg session for the S1 zero-transcode relay (P4, #107).
//!
//! One long-lived `ffmpeg -f mpegts -i pipe:0 -c copy -f flv <target>` process
//! per stream (decision baseline #3): the pump writes pre-rendered TS bytes,
//! ffmpeg only remuxes — no rawvideo/f32le inputs, no encode. Ported in
//! spirit from `src/ghsingo/internal/stream/ffmpeg.go`, minus its two-input
//! shape. The session never breaks on its own: the only intended restart is a
//! dead output (network drop), after which the caller re-pumps the current
//! segment from the wall-clock position.
//!
//! SECURITY: the RTMPS URL carries the stream key, so every ffmpeg line is
//! redacted before it reaches a log file or tracing. The key must never be
//! echoed, logged, or reported.

use std::fs::OpenOptions;
use std::io::{BufRead, BufReader, Write};
use std::path::{Path, PathBuf};
use std::process::{Child, Command, Stdio};
use std::thread::JoinHandle;

use anyhow::{bail, Context, Result};

/// Where the relay writes to.
pub enum Target {
    Local(PathBuf),
    Rtmps(String),
}

/// One managed ffmpeg process plus its stderr collector.
pub struct Session {
    child: Child,
    stdin: Option<std::process::ChildStdin>,
    stderr: Option<JoinHandle<()>>,
}

/// Replaces the RTMPS URL and its stream key with placeholders.
/// Trust boundary: ffmpeg echoes the output URL on start and in some errors.
pub fn redact(line: &str, url: &str) -> String {
    if url.is_empty() {
        return line.to_string(); // local mode: no secret in play
    }
    let mut out = line.replace(url, "<rtmps-url>");
    if let Some(key) = url.rsplit('/').next() {
        if key.len() >= 8 && !key.contains('<') {
            out = out.replace(key, "<stream-key>");
        }
    }
    out
}

impl Session {
    /// Starts ffmpeg with `-c copy` into `target`; stderr is appended to
    /// `log_path` (redacted) when given, else inherited.
    pub fn spawn(
        ffmpeg: &str,
        target: &Target,
        log_path: Option<&Path>,
        secret: &str,
    ) -> Result<Session> {
        let mut cmd = Command::new(ffmpeg);
        cmd.args([
            "-hide_banner",
            "-nostdin",
            "-v",
            "info",
            "-stats_period",
            "15",
            "-f",
            "mpegts",
            "-i",
            "pipe:0",
            "-c",
            "copy",
        ]);
        match target {
            Target::Local(p) => {
                if p.extension().is_none() {
                    bail!("local output {} needs an .flv extension", p.display());
                }
                cmd.arg("-y").arg(p);
            }
            Target::Rtmps(url) => {
                cmd.args(["-f", "flv"]).arg(url);
            }
        }
        let mut child = cmd
            .stdin(Stdio::piped())
            .stderr(Stdio::piped())
            .stdout(Stdio::null())
            .spawn()
            .context("spawn ffmpeg")?;
        let stdin = child.stdin.take().context("ffmpeg stdin pipe")?;
        let stderr = child.stderr.take().context("ffmpeg stderr pipe")?;

        let stderr = match log_path {
            Some(p) => {
                if let Some(dir) = p.parent() {
                    if !dir.as_os_str().is_empty() {
                        std::fs::create_dir_all(dir).ok();
                    }
                }
                let file = OpenOptions::new().create(true).append(true).open(p)?;
                let secret = secret.to_string();
                Some(std::thread::spawn(move || {
                    let mut file = file;
                    for line in BufReader::new(stderr).lines().map_while(Result::ok) {
                        let line = redact(&line, &secret);
                        let _ = writeln!(file, "{line}");
                    }
                }))
            }
            None => {
                let secret = secret.to_string();
                Some(std::thread::spawn(move || {
                    for line in BufReader::new(stderr).lines().map_while(Result::ok) {
                        let line = redact(&line, &secret);
                        if line.contains("rror") || line.contains("arning") {
                            tracing::warn!("ffmpeg: {line}");
                        }
                    }
                }))
            }
        };
        Ok(Session {
            child,
            stdin: Some(stdin),
            stderr,
        })
    }

    /// stdin handle, for the pump.
    pub fn stdin(&mut self) -> &mut std::process::ChildStdin {
        self.stdin.as_mut().expect("stdin taken")
    }

    /// Closes the pipe (EOF) and waits for ffmpeg to finish writing the
    /// trailer — without this the local .flv is left truncated.
    pub fn finish(mut self) -> Result<()> {
        drop(self.stdin.take());
        let status = self.child.wait().context("ffmpeg wait")?;
        if let Some(h) = self.stderr.take() {
            let _ = h.join();
        }
        if !status.success() {
            bail!("ffmpeg exited with {status}");
        }
        Ok(())
    }

    /// Kills a session we are abandoning (broken output). Never on the happy
    /// path: `finish` is what finalises the local file.
    pub fn abort(mut self) {
        drop(self.stdin.take());
        let _ = self.child.kill();
        let _ = self.child.wait();
        if let Some(h) = self.stderr.take() {
            let _ = h.join();
        }
    }
}
