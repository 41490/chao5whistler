//! rsghsing — Rust rewrite of ghsingo (Issue #104).
//!
//! Single binary, subcommand dispatch. P1 ships `prepare` only; later phases
//! append variants to `Command` and a match arm here.

mod archive;
mod audio;
mod composer;
mod config;
mod gorand;
mod gosort;
mod log;
mod render;

use std::path::PathBuf;

use anyhow::Result;
use clap::{Parser, Subcommand};

#[derive(Parser)]
#[command(name = "rsghsing", version, about = "rsghsing — ghsingo in Rust")]
struct Cli {
    #[command(subcommand)]
    command: Command,

    /// Path to the base TOML config; `<stem>.local.toml` overlays it.
    #[arg(long, global = true, default_value = "rsghsing.toml")]
    config: PathBuf,

    /// Log level: error | warn | info | debug | trace.
    #[arg(long, global = true, default_value = "info")]
    log_level: String,
}

#[derive(Subcommand)]
enum Command {
    /// Download (if enabled), parse and bucket GH Archive hour packs into a
    /// GSIN day-pack.
    Prepare {
        /// Override [archive].target_date (also accepts yesterday/today).
        #[arg(long)]
        date: Option<String>,

        /// Comma-separated UTC hours or ranges, e.g. 11 or 12-17. Empty = 0-23.
        #[arg(long, default_value = "")]
        hours: String,
    },

    /// Drive the composer against the latest daypack and dump the JSON state
    /// timeline (same shape as Go `cmd/composer-demo`).
    ComposerTimeline {
        #[arg(long)]
        duration: String,

        /// Composer rng seed; 0 = use [composer].seed.
        #[arg(long, default_value = "0")]
        seed: i64,

        #[arg(
            long,
            short = 'o',
            default_value = "/tmp/rsghsing-composer-timeline.json"
        )]
        out: PathBuf,
    },

    /// Render an audio file from a daypack time window via the v2 engine.
    Render {
        #[command(subcommand)]
        kind: RenderKind,
    },
}

#[derive(Subcommand)]
enum RenderKind {
    /// Render `--duration` of audio starting at `--start-clock` in the daypack.
    Audio {
        /// UTC clock within the daypack, e.g. 14:00 or 14:00:00.
        #[arg(long, default_value = "")]
        start_clock: String,

        /// Source data span mapped into the render duration, e.g. 1h.
        /// Empty = same as --duration (real-time mapping).
        #[arg(long, default_value = "")]
        source_span: String,

        #[arg(long)]
        duration: String,

        #[arg(long, default_value = "0")]
        seed: i64,

        /// Output path (.m4a; ffmpeg aac 128k). Sidecar goes to <out>.metrics.json.
        #[arg(long, short = 'o', default_value = "/tmp/rsghsing-audio.m4a")]
        out: PathBuf,
    },
}

fn main() -> Result<()> {
    let cli = Cli::parse();
    log::init(parse_level(&cli.log_level));

    match cli.command {
        Command::Prepare { date, hours } => {
            let cfg = config::Config::load(&cli.config)?;
            archive::prepare::run(
                &cfg,
                &archive::prepare::PrepareArgs {
                    date: date.as_deref(),
                    hours: &hours,
                },
            )
        }
        Command::ComposerTimeline {
            duration,
            seed,
            out,
        } => {
            let cfg = config::Config::load(&cli.config)?;
            render::composer_timeline::run(&cfg, &duration, seed, &out)
        }
        Command::Render { kind } => match kind {
            RenderKind::Audio {
                start_clock,
                source_span,
                duration,
                seed,
                out,
            } => {
                let cfg = config::Config::load(&cli.config)?;
                render::render_audio::run(
                    &cfg,
                    &render::render_audio::Args {
                        config: &cli.config.display().to_string(),
                        start_clock: &start_clock,
                        source_span: &source_span,
                        duration: &duration,
                        seed,
                        out: &out,
                    },
                )
            }
        },
    }
}

fn parse_level(s: &str) -> tracing::Level {
    match s.to_ascii_lowercase().as_str() {
        "error" => tracing::Level::ERROR,
        "warn" => tracing::Level::WARN,
        "debug" => tracing::Level::DEBUG,
        "trace" => tracing::Level::TRACE,
        _ => tracing::Level::INFO,
    }
}
