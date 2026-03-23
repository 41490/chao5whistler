use std::path::PathBuf;

use anyhow::{anyhow, bail, Result};

use crate::config::OutputFormat;

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum CliCommand {
    Help,
    CheckConfig(CheckConfigArgs),
    PrintDefaultConfig(PrintDefaultConfigArgs),
    SeedFixtureRaw(SeedFixtureRawArgs),
    PrepareDayPack(PrepareDayPackArgs),
    ValidateDayPack(ValidateDayPackArgs),
    SampleReplay(SampleReplayArgs),
    ReplayDryRun(ReplayDryRunArgs),
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct CheckConfigArgs {
    pub config_path: Option<PathBuf>,
    pub local_override_path: Option<PathBuf>,
    pub dump_json: bool,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct PrintDefaultConfigArgs {
    pub format: OutputFormat,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct SeedFixtureRawArgs {
    pub archive_root: PathBuf,
    pub day: String,
    pub force: bool,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct PrepareDayPackArgs {
    pub config_path: Option<PathBuf>,
    pub archive_root: Option<PathBuf>,
    pub day: String,
    pub force: bool,
    pub skip_download: bool,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct ValidateDayPackArgs {
    pub config_path: Option<PathBuf>,
    pub archive_root: Option<PathBuf>,
    pub day: String,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct SampleReplayArgs {
    pub config_path: Option<PathBuf>,
    pub archive_root: Option<PathBuf>,
    pub day: String,
    pub start_second: u32,
    pub duration_secs: u32,
    pub dump_json: bool,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct ReplayDryRunArgs {
    pub config_path: Option<PathBuf>,
    pub archive_root: Option<PathBuf>,
    pub day: String,
    pub start_second: u32,
    pub duration_secs: u32,
    pub dump_json: bool,
}

pub fn parse<I>(args: I) -> Result<CliCommand>
where
    I: IntoIterator,
    I::Item: Into<String>,
{
    let args = args.into_iter().map(Into::into).collect::<Vec<_>>();
    if args.is_empty() {
        return Ok(CliCommand::Help);
    }

    let command = &args[0];
    match command.as_str() {
        "help" | "--help" | "-h" => Ok(CliCommand::Help),
        "check-config" => parse_check_config(&args[1..]),
        "print-default-config" => parse_print_default_config(&args[1..]),
        "seed-fixture-raw" => parse_seed_fixture_raw(&args[1..]),
        "prepare-day-pack" => parse_prepare_day_pack(&args[1..]),
        "validate-day-pack" => parse_validate_day_pack(&args[1..]),
        "sample-replay" => parse_sample_replay(&args[1..]),
        "replay-dry-run" => parse_replay_dry_run(&args[1..]),
        other => Err(anyhow!("unknown command: {other}\n\n{}", help_text())),
    }
}

pub fn help_text() -> &'static str {
    r#"songh CLI

USAGE:
  songh check-config [--config PATH] [--local-override PATH] [--dump-json]
  songh print-default-config [--format toml|json]
  songh seed-fixture-raw --archive-root PATH --day YYYY-MM-DD [--force]
  songh prepare-day-pack [--config PATH] [--archive-root PATH] --day YYYY-MM-DD [--force] [--skip-download]
  songh validate-day-pack [--config PATH] [--archive-root PATH] --day YYYY-MM-DD
  songh sample-replay [--config PATH] [--archive-root PATH] --day YYYY-MM-DD [--start-second N] [--duration-secs N] [--dump-json]
  songh replay-dry-run [--config PATH] [--archive-root PATH] --day YYYY-MM-DD [--start-second N] [--duration-secs N] [--dump-json]
  songh help

COMMANDS:
  check-config         Load, merge, validate, and optionally dump effective config
  print-default-config Render the built-in default config
  seed-fixture-raw     Write a deterministic local GH Archive-style raw fixture
  prepare-day-pack     Download or reuse raw files, then build normalized/index/manifest outputs
  validate-day-pack    Verify a prepared day-pack against checksums and event counts
  sample-replay        Run replay selection on a prepared day-pack window
  replay-dry-run       Emit continuous ReplayTick output for a prepared day-pack window
  help                 Show this help
"#
}

fn parse_check_config(args: &[String]) -> Result<CliCommand> {
    let mut config_path = None;
    let mut local_override_path = None;
    let mut dump_json = false;
    let mut index = 0;

    while index < args.len() {
        match args[index].as_str() {
            "--config" => {
                let value = args
                    .get(index + 1)
                    .ok_or_else(|| anyhow!("--config requires a path"))?;
                config_path = Some(PathBuf::from(value));
                index += 2;
            }
            "--local-override" => {
                let value = args
                    .get(index + 1)
                    .ok_or_else(|| anyhow!("--local-override requires a path"))?;
                local_override_path = Some(PathBuf::from(value));
                index += 2;
            }
            "--dump-json" => {
                dump_json = true;
                index += 1;
            }
            other => bail!("unknown check-config flag: {other}"),
        }
    }

    Ok(CliCommand::CheckConfig(CheckConfigArgs {
        config_path,
        local_override_path,
        dump_json,
    }))
}

fn parse_print_default_config(args: &[String]) -> Result<CliCommand> {
    let mut format = OutputFormat::Toml;
    let mut index = 0;

    while index < args.len() {
        match args[index].as_str() {
            "--format" => {
                let value = args
                    .get(index + 1)
                    .ok_or_else(|| anyhow!("--format requires toml or json"))?;
                format = match value.as_str() {
                    "toml" => OutputFormat::Toml,
                    "json" => OutputFormat::Json,
                    other => bail!("unsupported format: {other}"),
                };
                index += 2;
            }
            other => bail!("unknown print-default-config flag: {other}"),
        }
    }

    Ok(CliCommand::PrintDefaultConfig(PrintDefaultConfigArgs {
        format,
    }))
}

fn parse_seed_fixture_raw(args: &[String]) -> Result<CliCommand> {
    let mut archive_root = None;
    let mut day = None;
    let mut force = false;
    let mut index = 0;

    while index < args.len() {
        match args[index].as_str() {
            "--archive-root" => {
                let value = args
                    .get(index + 1)
                    .ok_or_else(|| anyhow!("--archive-root requires a path"))?;
                archive_root = Some(PathBuf::from(value));
                index += 2;
            }
            "--day" => {
                let value = args
                    .get(index + 1)
                    .ok_or_else(|| anyhow!("--day requires YYYY-MM-DD"))?;
                day = Some(value.clone());
                index += 2;
            }
            "--force" => {
                force = true;
                index += 1;
            }
            other => bail!("unknown seed-fixture-raw flag: {other}"),
        }
    }

    Ok(CliCommand::SeedFixtureRaw(SeedFixtureRawArgs {
        archive_root: archive_root.ok_or_else(|| anyhow!("--archive-root is required"))?,
        day: day.ok_or_else(|| anyhow!("--day is required"))?,
        force,
    }))
}

fn parse_prepare_day_pack(args: &[String]) -> Result<CliCommand> {
    let mut config_path = None;
    let mut archive_root = None;
    let mut day = None;
    let mut force = false;
    let mut skip_download = false;
    let mut index = 0;

    while index < args.len() {
        match args[index].as_str() {
            "--config" => {
                let value = args
                    .get(index + 1)
                    .ok_or_else(|| anyhow!("--config requires a path"))?;
                config_path = Some(PathBuf::from(value));
                index += 2;
            }
            "--archive-root" => {
                let value = args
                    .get(index + 1)
                    .ok_or_else(|| anyhow!("--archive-root requires a path"))?;
                archive_root = Some(PathBuf::from(value));
                index += 2;
            }
            "--day" => {
                let value = args
                    .get(index + 1)
                    .ok_or_else(|| anyhow!("--day requires YYYY-MM-DD"))?;
                day = Some(value.clone());
                index += 2;
            }
            "--force" => {
                force = true;
                index += 1;
            }
            "--skip-download" => {
                skip_download = true;
                index += 1;
            }
            other => bail!("unknown prepare-day-pack flag: {other}"),
        }
    }

    Ok(CliCommand::PrepareDayPack(PrepareDayPackArgs {
        config_path,
        archive_root,
        day: day.ok_or_else(|| anyhow!("--day is required"))?,
        force,
        skip_download,
    }))
}

fn parse_validate_day_pack(args: &[String]) -> Result<CliCommand> {
    let mut config_path = None;
    let mut archive_root = None;
    let mut day = None;
    let mut index = 0;

    while index < args.len() {
        match args[index].as_str() {
            "--config" => {
                let value = args
                    .get(index + 1)
                    .ok_or_else(|| anyhow!("--config requires a path"))?;
                config_path = Some(PathBuf::from(value));
                index += 2;
            }
            "--archive-root" => {
                let value = args
                    .get(index + 1)
                    .ok_or_else(|| anyhow!("--archive-root requires a path"))?;
                archive_root = Some(PathBuf::from(value));
                index += 2;
            }
            "--day" => {
                let value = args
                    .get(index + 1)
                    .ok_or_else(|| anyhow!("--day requires YYYY-MM-DD"))?;
                day = Some(value.clone());
                index += 2;
            }
            other => bail!("unknown validate-day-pack flag: {other}"),
        }
    }

    Ok(CliCommand::ValidateDayPack(ValidateDayPackArgs {
        config_path,
        archive_root,
        day: day.ok_or_else(|| anyhow!("--day is required"))?,
    }))
}

fn parse_sample_replay(args: &[String]) -> Result<CliCommand> {
    let mut config_path = None;
    let mut archive_root = None;
    let mut day = None;
    let mut start_second = 0_u32;
    let mut duration_secs = 60_u32;
    let mut dump_json = false;
    let mut index = 0;

    while index < args.len() {
        match args[index].as_str() {
            "--config" => {
                let value = args
                    .get(index + 1)
                    .ok_or_else(|| anyhow!("--config requires a path"))?;
                config_path = Some(PathBuf::from(value));
                index += 2;
            }
            "--archive-root" => {
                let value = args
                    .get(index + 1)
                    .ok_or_else(|| anyhow!("--archive-root requires a path"))?;
                archive_root = Some(PathBuf::from(value));
                index += 2;
            }
            "--day" => {
                let value = args
                    .get(index + 1)
                    .ok_or_else(|| anyhow!("--day requires YYYY-MM-DD"))?;
                day = Some(value.clone());
                index += 2;
            }
            "--start-second" => {
                let value = args
                    .get(index + 1)
                    .ok_or_else(|| anyhow!("--start-second requires an integer"))?;
                start_second = value
                    .parse::<u32>()
                    .map_err(|_| anyhow!("--start-second must be an integer"))?;
                index += 2;
            }
            "--duration-secs" => {
                let value = args
                    .get(index + 1)
                    .ok_or_else(|| anyhow!("--duration-secs requires an integer"))?;
                duration_secs = value
                    .parse::<u32>()
                    .map_err(|_| anyhow!("--duration-secs must be an integer"))?;
                index += 2;
            }
            "--dump-json" => {
                dump_json = true;
                index += 1;
            }
            other => bail!("unknown sample-replay flag: {other}"),
        }
    }

    Ok(CliCommand::SampleReplay(SampleReplayArgs {
        config_path,
        archive_root,
        day: day.ok_or_else(|| anyhow!("--day is required"))?,
        start_second,
        duration_secs,
        dump_json,
    }))
}

fn parse_replay_dry_run(args: &[String]) -> Result<CliCommand> {
    let mut config_path = None;
    let mut archive_root = None;
    let mut day = None;
    let mut start_second = 0_u32;
    let mut duration_secs = 60_u32;
    let mut dump_json = false;
    let mut index = 0;

    while index < args.len() {
        match args[index].as_str() {
            "--config" => {
                let value = args
                    .get(index + 1)
                    .ok_or_else(|| anyhow!("--config requires a path"))?;
                config_path = Some(PathBuf::from(value));
                index += 2;
            }
            "--archive-root" => {
                let value = args
                    .get(index + 1)
                    .ok_or_else(|| anyhow!("--archive-root requires a path"))?;
                archive_root = Some(PathBuf::from(value));
                index += 2;
            }
            "--day" => {
                let value = args
                    .get(index + 1)
                    .ok_or_else(|| anyhow!("--day requires YYYY-MM-DD"))?;
                day = Some(value.clone());
                index += 2;
            }
            "--start-second" => {
                let value = args
                    .get(index + 1)
                    .ok_or_else(|| anyhow!("--start-second requires a number"))?;
                start_second = value
                    .parse::<u32>()
                    .map_err(|_| anyhow!("--start-second must be an unsigned integer"))?;
                index += 2;
            }
            "--duration-secs" => {
                let value = args
                    .get(index + 1)
                    .ok_or_else(|| anyhow!("--duration-secs requires a number"))?;
                duration_secs = value
                    .parse::<u32>()
                    .map_err(|_| anyhow!("--duration-secs must be an unsigned integer"))?;
                index += 2;
            }
            "--dump-json" => {
                dump_json = true;
                index += 1;
            }
            other => bail!("unknown replay-dry-run flag: {other}"),
        }
    }

    Ok(CliCommand::ReplayDryRun(ReplayDryRunArgs {
        config_path,
        archive_root,
        day: day.ok_or_else(|| anyhow!("--day is required"))?,
        start_second,
        duration_secs,
        dump_json,
    }))
}
