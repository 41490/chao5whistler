use std::path::PathBuf;

use anyhow::{anyhow, bail, Result};

use crate::config::OutputFormat;

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum CliCommand {
    Help,
    CheckConfig(CheckConfigArgs),
    PrintDefaultConfig(PrintDefaultConfigArgs),
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
        other => Err(anyhow!("unknown command: {other}\n\n{}", help_text())),
    }
}

pub fn help_text() -> &'static str {
    r#"songh stage-1 CLI

USAGE:
  songh check-config [--config PATH] [--local-override PATH] [--dump-json]
  songh print-default-config [--format toml|json]
  songh help

COMMANDS:
  check-config         Load, merge, validate, and optionally dump effective config
  print-default-config Render the built-in default config
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
