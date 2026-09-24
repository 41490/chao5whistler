//! rsghsing — Rust rewrite of ghsingo (Issue #104).
//!
//! Single binary, subcommand dispatch. P1 ships `prepare` only; later phases
//! append variants to `Command` and a match arm here.

mod archive;
mod gosort;
mod config;
mod log;

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
}

fn main() -> Result<()> {
    let cli = Cli::parse();
    log::init(parse_level(&cli.log_level));

    match cli.command {
        Command::Prepare { date, hours } => {
            let cfg = config::Config::load(&cli.config)?;
            archive::prepare::run(&cfg, &archive::prepare::PrepareArgs {
                date: date.as_deref(),
                hours: &hours,
            })
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
