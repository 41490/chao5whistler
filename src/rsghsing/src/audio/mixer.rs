//! MixerV2 — the ambient bus mixer (#28/#31/#32).
//! Ported from `src/ghsingo/internal/audio/mixer_v2.go`.
//!
//! Layer map:
//!   L0   drone      — sine root + sub, gain ∝ (1 - 0.4*Density)
//!   L0.5 tonal-bed  — looped sample bed
//!   L1   bed        — lowpassed pink noise, gain ∝ Brightness
//!   L2   accent     — Karplus voice, fired on composer.Accent
//!   all             — one shared reverb send at per-bus wet ratios

use crate::audio::bed::BedVoice;
use crate::audio::bellbank::BellBank;
use crate::audio::drone::DroneVoice;
use crate::audio::pitch::{self, Note, Pitch};
use crate::audio::reverb::Reverb;
use crate::audio::tonal_bed::TonalBedVoice;
use crate::composer::{self, Accent, Composer, Mode, Output, State, Section};

const ACCENT_SEED_BASE: i64 = 0x5eed_1050;

pub struct PendingAccent {
    accent: Accent,
    trigger_at_sample: i32,
}

pub struct ActiveAccent {
    voice: crate::audio::karplus::KarplusVoice,
    pan: f32,
    gain: f32,
    offset: i32,
}

pub struct MixerV2 {
    sample_rate: i32,
    fps: i32,
    samples_per_frame: usize,

    drone: DroneVoice,
    bed: BedVoice,
    tonal_bed: TonalBedVoice,

    bells: Option<BellBank>,
    accent_max: usize,

    reverb: Reverb,

    pending_accents: Vec<PendingAccent>,
    active_accents: Vec<ActiveAccent>,

    drone_gain: f32,
    bed_gain: f32,
    tonal_bed_gain: f32,
    accent_gain: f32,
    master_gain: f32,

    wet_continuous: f32,
    wet_accent: f32,

    last_state: State,
    accent_serial: i64,
}

/// Mirrors the v2 MixerConfig / the `[mixer]` toml block. Linear gains.
#[derive(Debug, Clone, Copy)]
pub struct MixerConfig {
    pub master_gain: f32,
    pub drone_gain: f32,
    pub bed_gain: f32,
    pub tonal_bed_gain: f32,
    pub accent_gain: f32,
    pub wet_continuous: f32,
    pub wet_accent: f32,
    pub accent_max: usize,
}

impl Default for MixerConfig {
    fn default() -> Self {
        MixerConfig {
            master_gain: 0.55,
            drone_gain: 1.0,
            bed_gain: 1.0,
            tonal_bed_gain: 1.0,
            accent_gain: 1.0,
            wet_continuous: 0.06,
            wet_accent: 0.45,
            accent_max: 4,
        }
    }
}

impl MixerV2 {
    pub fn new(sample_rate: i32, fps: i32, accent_max: usize) -> Self {
        let accent_max = if accent_max == 0 { 4 } else { accent_max };
        MixerV2 {
            sample_rate,
            fps,
            samples_per_frame: (sample_rate / fps) as usize,
            drone: DroneVoice::new(sample_rate),
            bed: BedVoice::new(sample_rate),
            tonal_bed: TonalBedVoice::new(sample_rate, Vec::new()),
            bells: None,
            accent_max,
            reverb: Reverb::new(sample_rate),
            pending_accents: Vec::new(),
            active_accents: Vec::new(),
            drone_gain: 1.0,
            bed_gain: 1.0,
            tonal_bed_gain: 1.0,
            accent_gain: 1.0,
            // 0.55 master leaves ~5 dB of headroom for inter-sample peaks
            // after AAC encoding plus the shared-reverb send stacking.
            master_gain: 0.55,
            wet_continuous: 0.06,
            wet_accent: 0.45,
            last_state: State {
                density: 0.0,
                brightness: 0.0,
                mode: Mode::Yo,
                section: Section::Rest,
                accent_prob: 0.0,
                ticks_in_phrase: 0,
            },
            accent_serial: 0,
        }
    }

    pub fn apply_config(&mut self, cfg: MixerConfig) {
        if cfg.master_gain > 0.0 {
            self.master_gain = cfg.master_gain;
        }
        if cfg.drone_gain > 0.0 {
            self.drone_gain = cfg.drone_gain;
        }
        if cfg.bed_gain > 0.0 {
            self.bed_gain = cfg.bed_gain;
        }
        if cfg.tonal_bed_gain > 0.0 {
            self.tonal_bed_gain = cfg.tonal_bed_gain;
        }
        if cfg.accent_gain > 0.0 {
            self.accent_gain = cfg.accent_gain;
        }
        if cfg.wet_continuous > 0.0 || cfg.wet_accent > 0.0 {
            self.wet_continuous = clamp_unit(cfg.wet_continuous);
            self.wet_accent = clamp_unit(cfg.wet_accent);
        }
        self.accent_max = if cfg.accent_max == 0 { 4 } else { cfg.accent_max };
    }

    pub fn set_accent_bank(&mut self, b: BellBank) {
        self.bells = Some(b);
    }

    pub fn set_tonal_bed_pcm(&mut self, pcm: Vec<f32>) {
        self.tonal_bed = TonalBedVoice::new(self.sample_rate, pcm);
    }

    pub fn set_tonal_bed_gain(&mut self, g: f32) {
        self.tonal_bed_gain = g;
    }

    pub fn last_state(&self) -> State {
        self.last_state
    }

    /// Consumes one composer tick: retarget the long-lived voices and queue
    /// any accents for the next frame.
    pub fn apply_output(&mut self, o: &Output) {
        self.last_state = o.state;
        self.drone.set_mode(o.state.mode);
        // Density ducks the drone so accents have room; never below ~0.16.
        self.drone
            .set_target_gain(0.16 * (1.0 - 0.4 * o.state.density as f32));
        // Bed swells with brightness; never below 0.04.
        self.bed
            .set_target_gain(0.04 + 0.16 * o.state.brightness as f32);
        // Tonal bed sits between drone and bed; Rest dips it so the engine
        // breathes.
        let tonal_target = if o.state.section == Section::Rest {
            0.10
        } else {
            0.18
        };
        self.tonal_bed.set_target_gain(tonal_target);

        for a in &o.accents {
            let off = ((self.pending_accents.len() as i32) % 4) * (self.sample_rate / 40);
            self.pending_accents.push(PendingAccent {
                accent: *a,
                trigger_at_sample: off,
            });
        }
    }

    /// Emits one stereo float32 frame (interleaved L/R), `samples_per_frame*2`.
    pub fn render_frame(&mut self) -> Vec<f32> {
        let n = self.samples_per_frame;
        let mut out = vec![0.0f32; n * 2];

        // Spawn accents whose offset falls inside this frame.
        let mut remaining: Vec<PendingAccent> = Vec::with_capacity(self.pending_accents.len());
        for p in std::mem::take(&mut self.pending_accents) {
            if p.trigger_at_sample < n as i32 {
                self.spawn_accent(p.accent, -p.trigger_at_sample);
            } else {
                remaining.push(PendingAccent {
                    trigger_at_sample: p.trigger_at_sample - n as i32,
                    ..p
                });
            }
        }
        self.pending_accents = remaining;

        for i in 0..n {
            let drone = self.drone.next_sample() * self.drone_gain;
            let tonal = self.tonal_bed.next_sample() * self.tonal_bed_gain;
            let bed = self.bed.next_sample() * self.bed_gain;
            let mono = drone + tonal + bed;

            let mut accent_mix = 0.0f32;
            for v in &mut self.active_accents {
                if v.offset < 0 {
                    v.offset += 1;
                    continue;
                }
                if v.voice.done() {
                    continue;
                }
                accent_mix += v.voice.next_sample() * v.gain;
            }
            let accent_dry = accent_mix * self.accent_gain;

            let space_in = mono * self.wet_continuous + accent_dry * self.wet_accent;
            let space_out = self.reverb.process(space_in);

            // Balanced linear pan on accent dry: total energy <= 1 across
            // L+R, so centred continuous layers cannot push either channel
            // past unity.
            let (pan_l, pan_r) = if let Some(a) = self.active_accents.first() {
                (1.0 - a.pan, a.pan)
            } else {
                (0.5, 0.5)
            };
            let l = (mono + accent_dry * pan_l + space_out) * self.master_gain;
            let r = (mono + accent_dry * pan_r + space_out) * self.master_gain;

            out[i * 2] = soft_clip(l);
            out[i * 2 + 1] = soft_clip(r);
        }

        // Reap finished accents.
        self.active_accents.retain(|v| !v.voice.done());

        out
    }

    fn spawn_accent(&mut self, a: Accent, offset: i32) {
        if self.bells.is_none() {
            return;
        }
        if self.active_accents.len() >= self.accent_max {
            // Steal the oldest voice — keeps polyphony bounded.
            self.active_accents.remove(0);
        }
        let pitch = pitch_for_accent(a);
        let pan = pitch::note_pan(pitch.note);
        self.accent_serial += 1;
        let seed = ACCENT_SEED_BASE.wrapping_add(self.accent_serial);
        let voice = self
            .bells
            .as_ref()
            .unwrap()
            .synth_voice(pitch, a.velocity as f32, seed);
        self.active_accents.push(ActiveAccent {
            voice,
            pan,
            gain: 1.0,
            offset,
        });
    }
}

fn clamp_unit(x: f32) -> f32 {
    x.clamp(0.0, 1.0)
}

fn soft_clip(x: f32) -> f32 {
    if x > 1.5 {
        1.0
    } else if x < -1.5 {
        -1.0
    } else {
        (x as f64).tanh() as f32
    }
}

/// Mode picks the rotation of the pentatonic scale; Degree is the 0..4 step.
pub fn pitch_for_accent(a: Accent) -> Pitch {
    let notes = pentatonic_for_mode(a.from_mode);
    let deg = a.degree.clamp(0, notes.len() as i32 - 1) as usize;
    Pitch {
        note: notes[deg],
        octave: match a.octave {
            3 => pitch::Octave::Low,
            5 => pitch::Octave::High,
            _ => pitch::Octave::Mid,
        },
    }
}

fn pentatonic_for_mode(m: Mode) -> [Note; 5] {
    let base = [
        Note::Gong,
        Note::Shang,
        Note::Jue,
        Note::Zhi,
        Note::Yu,
    ];
    let rot = match m {
        Mode::Yo => 0,     // 宫
        Mode::Hira => 1,   // 商
        Mode::In => 2,     // 角
        Mode::Ryo => 4,    // 羽
    };
    let mut out = [Note::Gong; 5];
    for i in 0..5 {
        out[i] = base[(i + rot) % 5];
    }
    out
}

/// The engine: composer (#30) + mixer (#31). It is the whole of what the Go
/// backend seam provided on the render path; the interface and its alternate
/// implementation are gone — see the P2 report's ablation list.
pub struct Engine {
    pub mixer: MixerV2,
    pub composer: Composer,
    pub ticks: i64,
    pub accents: i64,
    pub section_transitions: i64,
    pub mode_transitions: i64,
    prev_section: Section,
    prev_mode: Mode,
}

impl Engine {
    pub fn new(
        sample_rate: i32,
        fps: i32,
        composer_cfg: composer::Config,
        mixer_cfg: MixerConfig,
    ) -> Self {
        let mut mixer = MixerV2::new(sample_rate, fps, mixer_cfg.accent_max);
        mixer.apply_config(mixer_cfg);
        Engine {
            mixer,
            composer: Composer::new(composer_cfg),
            ticks: 0,
            accents: 0,
            section_transitions: 0,
            mode_transitions: 0,
            prev_section: Section::Rest,
            prev_mode: Mode::Yo,
        }
    }

    /// Folds one data-second of events into the slow state and queues accents.
    pub fn apply_events_for_second(&mut self, events: &[composer::Event]) {
        let out = self.composer.tick(events);
        self.mixer.apply_output(&out);

        self.ticks += 1;
        self.accents += out.accents.len() as i64;
        if out.state.section != self.prev_section {
            self.section_transitions += 1;
            self.prev_section = out.state.section;
        }
        if out.state.mode != self.prev_mode {
            self.mode_transitions += 1;
            self.prev_mode = out.state.mode;
        }
    }

    pub fn render_frame(&mut self) -> Vec<f32> {
        self.mixer.render_frame()
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    /// RMS of one rendered frame, both channels pooled.
    fn frame_rms(m: &mut MixerV2) -> f64 {
        let f = m.render_frame();
        let n = f.len() as f64;
        (f.iter().map(|&s| f64::from(s) * f64::from(s)).sum::<f64>() / n).sqrt()
    }

    /// Renders `frames` frames and returns the pooled RMS.
    fn rms_over(m: &mut MixerV2, frames: usize) -> f64 {
        let mut acc = 0.0f64;
        let mut n = 0usize;
        for _ in 0..frames {
            for s in m.render_frame() {
                acc += f64::from(s) * f64::from(s);
                n += 1;
            }
        }
        assert!(n > 0);
        (acc / n as f64).sqrt()
    }

    /// A steady-state composer tick: no accents, mid density/brightness.
    fn steady_output(density: f64, brightness: f64) -> Output {
        Output {
            state: State {
                density,
                brightness,
                mode: Mode::Yo,
                section: Section::Build,
                accent_prob: 0.0,
                ticks_in_phrase: 4,
            },
            accents: Vec::new(),
        }
    }

    #[test]
    fn continuous_buses_are_audible_and_do_not_clip() {
        let mut m = MixerV2::new(44_100, 15, 4);
        m.apply_config(MixerConfig::default());
        // Let the gain slew settle before measuring.
        for _ in 0..40 {
            m.apply_output(&steady_output(0.3, 0.5));
        }
        let rms = rms_over(&mut m, 30);
        assert!(rms > 0.01, "mixer output is silent: rms={rms}");
        assert!(rms < 0.5, "mixer output too hot: rms={rms}");
    }

    #[test]
    fn each_continuous_bus_contributes_measurable_energy() {
        // apply_config mirrors the Go builder and ignores a zero gain, so the
        // buses are muted on the struct itself here. Each bus is measured in
        // isolation: everything else muted, so the RMS is that bus alone.
        let solo = |mute: fn(&mut MixerV2)| -> f64 {
            let mut m = MixerV2::new(44_100, 15, 4);
            m.apply_config(MixerConfig::default());
            m.drone_gain = 0.0;
            m.bed_gain = 0.0;
            m.tonal_bed_gain = 0.0;
            mute(&mut m);
            for _ in 0..40 {
                m.apply_output(&steady_output(0.3, 0.5));
            }
            rms_over(&mut m, 30)
        };

        let drone = solo(|m| m.drone_gain = 1.0);
        let bed = solo(|m| m.bed_gain = 1.0);
        let master = solo(|m| m.master_gain = 1.0); // nothing else on
        assert!(master < 1e-6, "master-only render is not silent: {master}");
        assert!(drone > 0.02, "drone bus is inaudible: rms={drone}");
        assert!(bed > 0.002, "bed bus is inaudible: rms={bed}");
        // The layer map puts the bed well under the drone; if that inverts the
        // bed has become the lead layer.
        assert!(bed < drone, "bed ({bed}) overtook drone ({drone})");

        // Muting each bus on top of the others must remove energy.
        fn paired(mute: fn(&mut MixerV2)) -> (f64, f64) {
            let mut full = MixerV2::new(44_100, 15, 4);
            full.apply_config(MixerConfig::default());
            let mut cut = MixerV2::new(44_100, 15, 4);
            cut.apply_config(MixerConfig::default());
            mute(&mut cut);
            for _ in 0..40 {
                full.apply_output(&steady_output(0.3, 0.5));
                cut.apply_output(&steady_output(0.3, 0.5));
            }
            (rms_over(&mut full, 30), rms_over(&mut cut, 30))
        }
        fn kill_drone(m: &mut MixerV2) {
            m.drone_gain = 0.0;
        }
        fn kill_bed(m: &mut MixerV2) {
            m.bed_gain = 0.0;
        }
        for (name, mute) in [("drone", kill_drone as fn(&mut MixerV2)),
                             ("bed", kill_bed as fn(&mut MixerV2))] {
            let (a, b) = paired(mute);
            assert!(b < a, "{name} mute did not reduce energy: {a} -> {b}");
        }
    }

    #[test]
    fn tonal_bed_and_accent_buses_add_energy_on_top() {
        // No tonal PCM and no bank: continuous buses only.
        let mut bare = MixerV2::new(44_100, 15, 4);
        bare.apply_config(MixerConfig::default());
        // With tonal PCM loaded the bed must add energy.
        let mut bedded = MixerV2::new(44_100, 15, 4);
        bedded.apply_config(MixerConfig::default());
        bedded.set_tonal_bed_pcm(
            (0..2_205)
                .map(|i| (f64::from(i) * 0.01).sin() as f32 * 0.5)
                .collect(),
        );
        for _ in 0..40 {
            bare.apply_output(&steady_output(0.3, 0.5));
            bedded.apply_output(&steady_output(0.3, 0.5));
        }
        let a = rms_over(&mut bare, 30);
        let b = rms_over(&mut bedded, 30);
        assert!(b > a * 1.05, "tonal bed added no energy: {a} -> {b}");

        // Accents: a bank must make the accent bus audible.
        let mut silent = MixerV2::new(44_100, 15, 4);
        silent.apply_config(MixerConfig::default());
        let mut banked = MixerV2::new(44_100, 15, 4);
        banked.apply_config(MixerConfig::default());
        banked.set_accent_bank(BellBank::new(44_100));
        let with_accent = Output {
            accents: vec![Accent {
                from_mode: Mode::Yo,
                degree: 0,
                octave: 3,
                velocity: 100.0,
            }],
            ..steady_output(0.3, 0.5)
        };
        for _ in 0..20 {
            silent.apply_output(&with_accent);
            banked.apply_output(&with_accent);
        }
        let c = rms_over(&mut silent, 5);
        let d = rms_over(&mut banked, 5);
        assert!(d > c * 1.05, "accent bus added no energy: {c} -> {d}");
    }
}
