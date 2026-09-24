//! `--hours` spec parsing.
//!
//! Mirrors `src/ghsingo/cmd/prepare/hours.go`: empty means the whole day,
//! otherwise a comma-separated list of single hours and inclusive ranges,
//! deduplicated and sorted.

use anyhow::{bail, Result};

pub fn parse_hours(spec: &str) -> Result<Vec<usize>> {
    if spec.trim().is_empty() {
        return Ok((0..24).collect());
    }

    let mut seen = [false; 24];
    for part in spec.split(',') {
        let part = part.trim();
        if part.is_empty() {
            bail!("invalid empty hour token in {spec:?}");
        }
        if part.contains('-') {
            let bounds: Vec<&str> = part.split('-').collect();
            if bounds.len() != 2 {
                bail!("invalid hour range {part:?}");
            }
            let start = parse_hour(bounds[0])?;
            let end = parse_hour(bounds[1])?;
            if end < start {
                bail!("invalid descending hour range {part:?}");
            }
            for hour in start..=end {
                seen[hour] = true;
            }
            continue;
        }
        seen[parse_hour(part)?] = true;
    }

    Ok(seen
        .iter()
        .enumerate()
        .filter_map(|(h, on)| on.then_some(h))
        .collect())
}

fn parse_hour(s: &str) -> Result<usize> {
    let hour: usize = s
        .trim()
        .parse()
        .map_err(|_| anyhow::anyhow!("invalid hour {s:?}"))?;
    if hour > 23 {
        bail!("hour {hour} out of range [0,23]");
    }
    Ok(hour)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn empty_means_whole_day() {
        assert_eq!(parse_hours("").unwrap(), (0..24).collect::<Vec<_>>());
        assert_eq!(parse_hours("   ").unwrap(), (0..24).collect::<Vec<_>>());
    }

    #[test]
    fn ranges_dedup_and_sort() {
        assert_eq!(
            parse_hours("16,12-14,13,0").unwrap(),
            vec![0, 12, 13, 14, 16]
        );
    }

    #[test]
    fn rejects_invalid() {
        for spec in ["-1", "24", "7-3", "a", "1,,2", "1-2-3"] {
            assert!(parse_hours(spec).is_err(), "expected error for {spec:?}");
        }
    }
}
