use std::path::PathBuf;

use anyhow::{bail, Result};

use crate::cli::{CheckConfigArgs, CliCommand, PrintDefaultConfigArgs};
use crate::config::{self, OutputFormat};

pub fn run<I>(args: I) -> Result<()>
where
    I: IntoIterator,
    I::Item: Into<String>,
{
    match crate::cli::parse(args)? {
        CliCommand::Help => {
            println!("{}", crate::cli::help_text());
        }
        CliCommand::CheckConfig(args) => run_check_config(args)?,
        CliCommand::PrintDefaultConfig(args) => run_print_default_config(args)?,
    }

    Ok(())
}

fn run_check_config(args: CheckConfigArgs) -> Result<()> {
    let config_path = args.config_path.unwrap_or_else(default_runtime_config_path);
    let loaded = config::load_from_path(&config_path, args.local_override_path.as_deref())?;

    println!("songh stage1 config validation passed");
    println!("main config: {}", config_path.display());
    match loaded.report.local_override_path {
        Some(path) => println!("local override: {}", path.display()),
        None => println!("local override: <none>"),
    }
    println!(
        "env override: SONGH_RTMP_URL {}",
        if loaded.report.env_rtmp_override_applied {
            "applied"
        } else {
            "not-set"
        }
    );
    println!("effective mode: {}", loaded.config.runtime.mode.as_str());
    println!(
        "effective archive selector: {}",
        loaded.config.archive.selector.as_str()
    );
    println!(
        "effective outputs: rtmp={} local_record={}",
        loaded.config.outputs.enable_rtmp, loaded.config.outputs.enable_local_record
    );

    if loaded.report.warnings.is_empty() {
        println!("warnings: 0");
    } else {
        println!("warnings: {}", loaded.report.warnings.len());
        for warning in &loaded.report.warnings {
            println!("- {warning}");
        }
    }

    if args.dump_json {
        println!("{}", serde_json::to_string_pretty(&loaded.config)?);
    }

    Ok(())
}

fn run_print_default_config(args: PrintDefaultConfigArgs) -> Result<()> {
    match args.format {
        OutputFormat::Json => {
            println!(
                "{}",
                serde_json::to_string_pretty(&config::schema::Config::default())?
            );
        }
        OutputFormat::Toml => {
            println!("{}", config::render_default_toml()?);
        }
    }

    Ok(())
}

fn default_runtime_config_path() -> PathBuf {
    std::env::current_dir()
        .map(|cwd| cwd.join("songh.toml"))
        .unwrap_or_else(|_| PathBuf::from("songh.toml"))
}

#[allow(dead_code)]
fn ensure_file_exists(path: &PathBuf) -> Result<()> {
    if !path.exists() {
        bail!("config file not found: {}", path.display());
    }

    Ok(())
}
