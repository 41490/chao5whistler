//! State-vector composer (#30), ported from `src/ghsingo/internal/composer`.
//!
//! Pure logic: no audio, no toml, no I/O. The RNG is a byte-for-byte port of
//! Go's `math/rand` (see `crate::gorand`) so the emitted timeline can diff to
//! zero against `cmd/composer-demo` (Issue #105, acceptance 2).

/// 五声 mode selection. The slow state drifts across four modes.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Mode {
    Yo,
    Hira,
    In,
    Ryo,
}

impl Mode {
    pub fn as_str(self) -> &'static str {
        match self {
            Mode::Yo => "yo",
            Mode::Hira => "hira",
            Mode::In => "in",
            Mode::Ryo => "ryo",
        }
    }
    pub fn from_i64(v: i64) -> Mode {
        match v {
            1 => Mode::Hira,
            2 => Mode::In,
            3 => Mode::Ryo,
            _ => Mode::Yo,
        }
    }
}

/// Long-period phrase state: Rest -> Build -> Flow -> Ebb -> Rest.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Section {
    Rest,
    Build,
    Flow,
    Ebb,
}

impl Section {
    pub fn as_str(self) -> &'static str {
        match self {
            Section::Rest => "rest",
            Section::Build => "build",
            Section::Flow => "flow",
            Section::Ebb => "ebb",
        }
    }
    pub fn from_i64(v: i64) -> Section {
        match v {
            1 => Section::Build,
            2 => Section::Flow,
            3 => Section::Ebb,
            _ => Section::Rest,
        }
    }
}

/// The slow-moving musical state at the end of a tick.
#[derive(Debug, Clone, Copy, PartialEq)]
pub struct State {
    pub density: f64,
    pub brightness: f64,
    pub mode: Mode,
    pub section: Section,
    pub accent_prob: f64,
    pub ticks_in_phrase: i32,
}

/// One GH event arrival in the current tick.
#[derive(Debug, Clone, Copy)]
pub struct Event {
    pub type_id: u8,
    pub weight: u8,
}

/// A sparse "L2" trigger emitted by the phrase scheduler.
#[derive(Debug, Clone, Copy, PartialEq)]
pub struct Accent {
    pub velocity: f64,
    pub degree: i32,
    pub octave: i32,
    pub from_mode: Mode,
}

/// What one `tick` returns: the new slow state plus 0+ sparse accents.
#[derive(Debug, Clone)]
pub struct Output {
    pub state: State,
    pub accents: Vec<Accent>,
}

/// Composer tuning. Zero values fall back to vetted defaults.
#[derive(Debug, Clone)]
pub struct Config {
    pub ema_alpha: f64,
    pub density_saturation: f64,
    pub brightness_saturation: f64,
    pub phrase_ticks: i64,
    pub accent_cooldown_ticks: i64,
    pub accent_base_prob: f64,
    pub seed: i64,
}

impl Default for Config {
    fn default() -> Self {
        Self {
            ema_alpha: 0.06,
            density_saturation: 12.0,
            brightness_saturation: 80.0,
            phrase_ticks: 16,
            accent_cooldown_ticks: 3,
            accent_base_prob: 0.10,
            seed: 0,
        }
    }
}

impl Config {
    fn apply_defaults(&mut self) {
        if self.ema_alpha <= 0.0 {
            self.ema_alpha = 0.06;
        }
        if self.density_saturation <= 0.0 {
            self.density_saturation = 12.0;
        }
        if self.brightness_saturation <= 0.0 {
            self.brightness_saturation = 80.0;
        }
        if self.phrase_ticks <= 0 {
            self.phrase_ticks = 16;
        }
        if self.accent_cooldown_ticks <= 0 {
            self.accent_cooldown_ticks = 3;
        }
        if self.accent_base_prob <= 0.0 {
            self.accent_base_prob = 0.10;
        }
    }
}

/// The stateful state-vector composer. One instance per render.
pub struct Composer {
    cfg: Config,
    state: State,
    rng: crate::gorand::GoRand,
    cooldown: i64,
    ticks_in_phrase: i64,
    total_ticks: i64,
}

impl Composer {
    pub fn new(cfg: Config) -> Self {
        let mut cfg = cfg;
        cfg.apply_defaults();
        let seed = cfg.seed_resolved();
        let mut c = Composer {
            cfg,
            state: State {
                density: 0.0,
                brightness: 0.0,
                mode: Mode::Yo,
                section: Section::Rest,
                accent_prob: 0.0,
                ticks_in_phrase: 0,
            },
            rng: crate::gorand::GoRand::new(seed),
            cooldown: 0,
            ticks_in_phrase: 0,
            total_ticks: 0,
        };
        c.state.accent_prob = c.cfg.accent_base_prob * section_multiplier(c.state.section);
        c
    }

    pub fn state(&self) -> State {
        self.state
    }

    pub fn total_ticks(&self) -> i64 {
        self.total_ticks
    }

    /// Advances the composer by one tick (= one data-second).
    pub fn tick(&mut self, events: &[Event]) -> Output {
        let mut raw_density = events.len() as f64 / self.cfg.density_saturation;
        if raw_density > 1.0 {
            raw_density = 1.0;
        }

        let mut raw_bright = 0.0;
        if !events.is_empty() {
            let sum: u64 = events.iter().map(|e| u64::from(e.weight)).sum();
            raw_bright = (sum as f64 / events.len() as f64) / self.cfg.brightness_saturation;
            if raw_bright > 1.0 {
                raw_bright = 1.0;
            }
        }

        let a = self.cfg.ema_alpha;
        self.state.density = self.state.density * (1.0 - a) + raw_density * a;
        self.state.brightness = self.state.brightness * (1.0 - a) + raw_bright * a;

        self.ticks_in_phrase += 1;
        if self.ticks_in_phrase >= self.cfg.phrase_ticks {
            self.advance_section();
            self.ticks_in_phrase = 0;
        }

        let prob = self.cfg.accent_base_prob * section_multiplier(self.state.section);
        self.state.accent_prob = prob;

        let mut accents: Vec<Accent> = Vec::new();
        if self.cooldown > 0 {
            self.cooldown -= 1;
        } else if self.rng.float64() < prob {
            accents.push(self.make_accent());
            self.cooldown = self.cfg.accent_cooldown_ticks;
        }

        self.state.ticks_in_phrase = self.ticks_in_phrase as i32;
        self.total_ticks += 1;

        Output {
            state: self.state,
            accents,
        }
    }

    fn advance_section(&mut self) {
        self.state.section = next_section(self.state.section);
        if self.state.section == Section::Flow {
            self.state.mode = pick_mode(self.state.brightness, &mut self.rng);
        }
    }

    fn make_accent(&mut self) -> Accent {
        let vel = 0.55 + 0.45 * self.state.brightness;
        let octave = if self.state.brightness > 0.66 {
            5
        } else if self.state.brightness < 0.33 {
            3
        } else {
            4
        };
        Accent {
            velocity: vel,
            degree: self.rng.intn(5),
            octave,
            from_mode: self.state.mode,
        }
    }
}

impl Config {
    /// Go: `seed == 0` -> `time.Now().UnixNano()`. The render/composer-timeline
    /// paths always pass an explicit seed, so 0 keeps its Go meaning only for
    /// `New`; callers that need determinism set it.
    fn seed_resolved(&self) -> i64 {
        if self.seed == 0 {
            // Go: time.Now().UnixNano().
            std::time::SystemTime::now()
                .duration_since(std::time::UNIX_EPOCH)
                .map(|d| d.as_nanos() as i64)
                .unwrap_or(89482311)
        } else {
            self.seed
        }
    }
}

pub fn next_section(s: Section) -> Section {
    match s {
        Section::Rest => Section::Build,
        Section::Build => Section::Flow,
        Section::Flow => Section::Ebb,
        Section::Ebb => Section::Rest,
    }
}

pub fn section_multiplier(s: Section) -> f64 {
    match s {
        Section::Rest => 0.0,
        Section::Build => 1.5,
        Section::Flow => 3.0,
        Section::Ebb => 1.0,
    }
}

fn pick_mode(brightness: f64, rng: &mut crate::gorand::GoRand) -> Mode {
    let r = rng.float64();
    if brightness > 0.66 {
        if r < 0.7 {
            Mode::Yo
        } else if r < 0.9 {
            Mode::Ryo
        } else {
            Mode::Hira
        }
    } else if brightness > 0.33 {
        if r < 0.5 {
            Mode::Hira
        } else if r < 0.8 {
            Mode::Yo
        } else {
            Mode::In
        }
    } else if r < 0.6 {
        Mode::In
    } else if r < 0.85 {
        Mode::Hira
    } else {
        Mode::Ryo
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn cfg(seed: i64) -> Config {
        Config {
            seed,
            ..Config::default()
        }
    }

    /// Same seed + same tick sequence -> byte-identical output, every run.
    /// This is the property acceptance 2 ("golden diff=0") rests on.
    #[test]
    fn same_seed_and_ticks_produce_identical_output() {
        let seq: Vec<Vec<Event>> = (0..600)
            .map(|i| {
                let n = (i * 7) % 5;
                (0..n)
                    .map(|k| Event {
                        type_id: (k % 6) as u8,
                        weight: (30 + (i * 13 + k * 17) % 71) as u8,
                    })
                    .collect()
            })
            .collect();

        let run = || {
            let mut c = Composer::new(cfg(20260328));
            seq.iter()
                .map(|evs| c.tick(evs))
                .map(|o| format!("{:?}|{:?}", o.state, o.accents))
                .collect::<Vec<_>>()
                .join("\n")
        };
        assert_eq!(run(), run());
    }

    /// Different seeds must diverge (proves the rng is actually wired in).
    #[test]
    fn different_seed_diverges() {
        let seq: Vec<Vec<Event>> = (0..200).map(|_| Vec::new()).collect();
        let accents = |seed: i64| {
            let mut c = Composer::new(cfg(seed));
            seq.iter().map(|e| c.tick(e).accents.len()).sum::<usize>()
        };
        assert_ne!(accents(1), accents(2));
    }

    /// Zero-valued config fields fall back to the #30 defaults.
    #[test]
    fn zero_config_uses_vetted_defaults() {
        let c = Composer::new(Config::default());
        assert_eq!(c.cfg.ema_alpha, 0.06);
        assert_eq!(c.cfg.density_saturation, 12.0);
        assert_eq!(c.cfg.brightness_saturation, 80.0);
        assert_eq!(c.cfg.phrase_ticks, 16);
        assert_eq!(c.cfg.accent_cooldown_ticks, 3);
        assert_eq!(c.cfg.accent_base_prob, 0.10);
    }

    /// Rest gates accents to zero: a long silence must stay silent, and
    /// the phrase scheduler must still advance sections.
    #[test]
    fn rest_section_suppresses_accents_and_phrase_cycles() {
        let mut c = Composer::new(cfg(7));
        let mut accents = 0usize;
        let mut sections = Vec::new();
        for _ in 0..16 {
            let o = c.tick(&[]);
            accents += o.accents.len();
            if sections.last() != Some(&o.state.section) {
                sections.push(o.state.section);
            }
        }
        assert_eq!(accents, 0);
        assert_eq!(sections, vec![Section::Rest, Section::Build]);
    }

    /// Density saturates at 1.0 no matter how large the burst is (#30 core).
    #[test]
    fn density_saturates_at_one() {
        let mut c = Composer::new(cfg(11));
        let burst: Vec<Event> = (0..200)
            .map(|_k| Event {
                type_id: 0,
                weight: 255,
            })
            .collect();
        for _ in 0..500 {
            c.tick(&burst);
        }
        assert!((c.state().density - 1.0).abs() < 1e-12);
    }
}
