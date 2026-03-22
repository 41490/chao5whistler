use std::fs;
use std::thread;

use anyhow::{Context, Result};
use reqwest::blocking::Client;

use crate::archive::DayPackLayout;
use crate::config::schema::Config;

pub fn download_missing_raw_hours(config: &Config, layout: &DayPackLayout) -> Result<()> {
    let missing_hours = (0..24_u8)
        .filter(|hour| !layout.raw_hour_path(*hour).exists())
        .collect::<Vec<_>>();
    if missing_hours.is_empty() {
        return Ok(());
    }
    if !config.archive.download.enabled {
        anyhow::bail!(
            "archive.download.enabled = false and missing {} raw hour files",
            missing_hours.len()
        );
    }

    let client = Client::builder()
        .timeout(std::time::Duration::from_secs(
            config.archive.download.timeout_secs as u64,
        ))
        .user_agent(config.archive.download.user_agent.clone())
        .build()
        .context("failed to build HTTP client")?;

    let max_parallel = config.archive.download.max_parallel.max(1) as usize;
    for chunk in missing_hours.chunks(max_parallel) {
        let mut handles = Vec::with_capacity(chunk.len());
        for hour in chunk {
            let client = client.clone();
            let output_path = layout.raw_hour_path(*hour);
            let source_day = layout.source_day.clone();
            let base_url = config.archive.download.base_url.clone();
            let hour = *hour;
            handles.push(thread::spawn(move || -> Result<()> {
                let url = format!(
                    "{}/{}-{}.json.gz",
                    base_url.trim_end_matches('/'),
                    source_day,
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
                Ok(())
            }));
        }

        for handle in handles {
            handle
                .join()
                .map_err(|_| anyhow::anyhow!("download worker thread panicked"))??;
        }
    }

    Ok(())
}
