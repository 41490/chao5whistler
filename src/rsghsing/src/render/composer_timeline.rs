//! `rsghsing composer-timeline` — ported from `cmd/composer-demo`.
//!
//! JSON shape is byte-compatible with the Go tool so the two timelines can be
//! diffed directly (Issue #105, acceptance 2).

use std::path::Path;

use anyhow::{bail, Result};

use super::{find_latest_daypack, parse_duration};
use crate::composer::{self, Composer, Config, Event};

struct Tick {
    second: i32,
    events: usize,
    avg_weight: i64,
    density: f64,
    brightness: f64,
    mode: &'static str,
    section: &'static str,
    accent_prob: f64,
    ticks_in_phrase: i32,
    accents: Vec<(f64, i32, i32, &'static str)>,
}

pub struct Args<'a> {
    pub duration: &'a str,
    pub seed: i64,
    pub out: &'a Path,
}

pub fn run(cfg: &crate::config::Config, duration: &str, seed: i64, out: &Path) -> Result<()> {
    let secs = parse_duration(duration)?;
    let total_ticks = secs as i64;

    let (daypack_path, date_str) = find_latest_daypack(Path::new(&cfg.archive.daypack_dir))?;
    let pack = crate::archive::daypack::Daypack::read(&daypack_path)?;
    if pack.ticks.is_empty() {
        bail!("daypack {} has no ticks", daypack_path.display());
    }

    let mut c = Composer::new(Config {
        seed: if seed != 0 { seed } else { cfg.composer.seed },
        ..cfg_composer(cfg)
    });

    let mut ticks: Vec<Tick> = Vec::with_capacity(total_ticks as usize);
    let (mut total_events, mut total_accents) = (0i64, 0i64);
    let (mut section_transitions, mut mode_transitions) = (0i64, 0i64);
    let mut prev_section = composer::Section::Rest;
    let mut prev_mode = composer::Mode::Yo;

    for i in 0..total_ticks {
        let idx = (i.rem_euclid(pack.ticks.len() as i64)) as usize;
        let evs = &pack.ticks[idx].events;
        let cevs: Vec<Event> = evs
            .iter()
            .map(|e| Event {
                type_id: e.type_id,
                weight: e.weight,
            })
            .collect();
        let sum_w: i64 = evs.iter().map(|e| i64::from(e.weight)).sum();
        let out_tick = c.tick(&cevs);
        let avg_w = if evs.is_empty() {
            0
        } else {
            sum_w / evs.len() as i64
        };
        ticks.push(Tick {
            second: i as i32,
            events: evs.len(),
            avg_weight: avg_w,
            density: out_tick.state.density,
            brightness: out_tick.state.brightness,
            mode: out_tick.state.mode.as_str(),
            section: out_tick.state.section.as_str(),
            accent_prob: out_tick.state.accent_prob,
            ticks_in_phrase: out_tick.state.ticks_in_phrase,
            accents: out_tick
                .accents
                .iter()
                .map(|a| (a.velocity, a.degree, a.octave, a.from_mode.as_str()))
                .collect(),
        });
        total_events += evs.len() as i64;
        total_accents += out_tick.accents.len() as i64;
        if out_tick.state.section != prev_section {
            section_transitions += 1;
            prev_section = out_tick.state.section;
        }
        if out_tick.state.mode != prev_mode {
            mode_transitions += 1;
            prev_mode = out_tick.state.mode;
        }
    }

    // Go json.MarshalIndent emits `{}` for an empty slice, never `null`.
    let accents_per_min = total_accents as f64 / (total_ticks as f64 / 60.0);
    let events_per_min = total_events as f64 / (total_ticks as f64 / 60.0);
    let (final_density, final_brightness) = ticks
        .last()
        .map(|t| (t.density, t.brightness))
        .unwrap_or((0.0, 0.0));

    if let Some(parent) = out.parent() {
        if !parent.as_os_str().is_empty() {
            std::fs::create_dir_all(parent)?;
        }
    }
    let mut s = String::new();
    s.push_str("{\n");
    s.push_str("  \"summary\": {\n");
    s.push_str(&format!("    \"profile\": \"{}\",\n", cfg.meta.profile));
    s.push_str(&format!("    \"daypack_date\": \"{}\",\n", date_str));
    s.push_str(&format!("    \"ticks\": {total_ticks},\n"));
    s.push_str(&format!("    \"total_events\": {total_events},\n"));
    s.push_str(&format!("    \"total_accents\": {total_accents},\n"));
    s.push_str(&format!("    \"accents_per_minute\": {accents_per_min},\n"));
    s.push_str(&format!("    \"events_per_minute\": {events_per_min},\n"));
    s.push_str(&format!("    \"final_density\": {final_density},\n"));
    s.push_str(&format!("    \"final_brightness\": {final_brightness},\n"));
    s.push_str(&format!(
        "    \"section_transitions\": {section_transitions},\n"
    ));
    s.push_str(&format!("    \"mode_transitions\": {mode_transitions}\n"));
    s.push_str("  },\n");
    s.push_str("  \"ticks\": [");
    for (i, t) in ticks.iter().enumerate() {
        s.push_str(if i == 0 { "\n" } else { ",\n" });
        s.push_str("    {\n");
        s.push_str(&format!("      \"second\": {},\n", t.second));
        s.push_str(&format!("      \"events\": {},\n", t.events));
        s.push_str(&format!("      \"avg_weight\": {},\n", t.avg_weight));
        s.push_str("      \"out\": {\n");
        s.push_str("        \"state\": {\n");
        s.push_str(&format!("          \"density\": {},\n", t.density));
        s.push_str(&format!("          \"brightness\": {},\n", t.brightness));
        s.push_str(&format!("          \"mode\": \"{}\",\n", t.mode));
        s.push_str(&format!("          \"section\": \"{}\",\n", t.section));
        s.push_str(&format!("          \"accent_prob\": {},\n", t.accent_prob));
        s.push_str(&format!(
            "          \"ticks_in_phrase\": {}\n",
            t.ticks_in_phrase
        ));
        s.push_str("        }");
        if t.accents.is_empty() {
            s.push('\n');
        } else {
            s.push_str(",\n        \"accents\": [\n");
            for (j, a) in t.accents.iter().enumerate() {
                s.push_str(if j == 0 {
                    "          "
                } else {
                    ",\n          "
                });
                s.push_str(&format!(
                    "{{\n            \"velocity\": {},\n            \"degree\": {},\n            \"octave\": {},\n            \"mode\": \"{}\"\n          }}",
                    a.0, a.1, a.2, a.3
                ));
            }
            s.push_str("\n        ]\n");
        }
        s.push_str("      }\n");
        s.push_str("    }");
    }
    if !ticks.is_empty() {
        s.push_str("\n  ");
    }
    s.push_str("]\n}\n");
    std::fs::write(out, s)?;

    tracing::info!(
        out = %out.display(),
        ticks = total_ticks,
        events = total_events,
        accents = total_accents,
        events_per_min = format!("{events_per_min:.1}"),
        accents_per_min = format!("{accents_per_min:.1}"),
        final_density = format!("{final_density:.3}"),
        final_brightness = format!("{final_brightness:.3}"),
        section_transitions,
        mode_transitions,
        "composer timeline"
    );
    Ok(())
}

fn cfg_composer(cfg: &crate::config::Config) -> Config {
    Config {
        ema_alpha: cfg.composer.ema_alpha,
        density_saturation: cfg.composer.density_saturation,
        brightness_saturation: cfg.composer.brightness_saturation,
        phrase_ticks: i64::from(cfg.composer.phrase_ticks),
        accent_cooldown_ticks: i64::from(cfg.composer.accent_cooldown_ticks),
        accent_base_prob: cfg.composer.accent_base_prob,
        seed: cfg.composer.seed,
    }
}
