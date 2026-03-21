use std::fs;

use anyhow::{Context, Result};
use reqwest::blocking::Client;

use crate::archive::DayPackLayout;
use crate::config::schema::Config;

pub fn download_missing_raw_hours(config: &Config, layout: &DayPackLayout) -> Result<()> {
    let client = Client::builder()
        .timeout(std::time::Duration::from_secs(
            config.archive.download.timeout_secs as u64,
        ))
        .user_agent(config.archive.download.user_agent.clone())
        .build()
        .context("failed to build HTTP client")?;

    for hour in 0..24_u8 {
        let output_path = layout.raw_hour_path(hour);
        if output_path.exists() {
            continue;
        }

        if !config.archive.download.enabled {
            anyhow::bail!(
                "archive.download.enabled = false and missing raw file: {}",
                output_path.display()
            );
        }

        let url = format!(
            "{}/{}-{}.json.gz",
            config.archive.download.base_url.trim_end_matches('/'),
            layout.source_day,
            hour
        );
        let response = client
            .get(&url)
            .send()
            .with_context(|| format!("failed to GET {url}"))?
            .error_for_status()
            .with_context(|| format!("download failed for {url}"))?;
        let bytes = response.bytes().context("failed to read response body")?;
        fs::write(&output_path, &bytes)
            .with_context(|| format!("failed to write {}", output_path.display()))?;
    }

    Ok(())
}
