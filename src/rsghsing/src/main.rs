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
mod stream;
mod video;

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

    /// Long-running relay: pump D-1's 15-min TS segments at UTC wall-clock
    /// pace into a persistent `ffmpeg -c copy -f flv` session (P4, Issue #107).
    Stream {
        /// Inject the wall clock: epoch seconds or `2026-03-28T11:00:00Z`.
        /// Deterministic boundary testing; the clock still advances in realtime.
        #[arg(long)]
        now: Option<String>,

        /// Override [output].mode for this run: local | rtmps.
        #[arg(long)]
        output: Option<String>,

        /// Local .flv output path (mode=local).
        #[arg(long)]
        local_path: Option<PathBuf>,

        /// Override [stream].segments_dir (root holding <YYYY-MM-DD>/seg-NN.ts).
        #[arg(long)]
        segments_dir: Option<String>,

        /// Stop after N seconds of wall time (soak/preflight harness).
        #[arg(long)]
        duration: Option<f64>,

        /// ffmpeg stderr log, stream key redacted; default = inherit stderr.
        #[arg(long)]
        ffmpeg_log: Option<PathBuf>,
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

    /// Render one 15-min TS segment (index N) of D-1: h264 30fps 2500k 720p +
    /// aac 128k, absolute PTS, per-event manifest. P3 (Issue #106).
    Segment {
        /// Segment index 0..=95; segment k covers D-1 UTC [k*900s,(k+1)*900s).
        #[arg(long)]
        index: i32,

        /// Output path (.ts). Manifest goes to <out>.manifest.json.
        #[arg(long, short = 'o', default_value = "/tmp/rsghsing-seg.ts")]
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
            RenderKind::Segment { index, out } => {
                let cfg = config::Config::load(&cli.config)?;
                render::render_segment::run(
                    &cfg,
                    &render::render_segment::Args { index, out: &out },
                )
            }
        },
        Command::Stream {
            now,
            output,
            local_path,
            segments_dir,
            duration,
            ffmpeg_log,
        } => {
            let cfg = config::Config::load(&cli.config)?;
            stream::run(
                &cfg,
                &stream::Args {
                    now: now.as_deref(),
                    output: output.as_deref(),
                    local_path: local_path.as_deref(),
                    segments_dir: segments_dir.as_deref(),
                    duration,
                    ffmpeg_log: ffmpeg_log.as_deref(),
                },
            )
        }
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
