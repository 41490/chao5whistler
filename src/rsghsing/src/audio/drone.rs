//! L0 continuous drone. Ported from `internal/audio/drone.go`.

use std::f64::consts::PI;

use crate::composer::Mode;

pub struct DroneVoice {
    sample_rate: i32,
    phase_root: f64,
    phase_sub: f64,
    phase_lfo: f64,
    root_hz: f64,
    sub_hz: f64,
    target_gain: f32,
    gain: f32,
    gain_slew: f32,
}

impl DroneVoice {
    pub fn new(sample_rate: i32) -> Self {
        let mut d = DroneVoice {
            sample_rate,
            phase_root: 0.0,
            phase_sub: 0.0,
            phase_lfo: 0.0,
            root_hz: 220.0,
            sub_hz: 110.0,
            target_gain: 0.0,
            gain: 0.0,
            gain_slew: 1.0 / sample_rate as f32 * 4.0, // ~250 ms slew per unit
        };
        d.set_mode(Mode::Yo);
        d
    }

    pub fn set_mode(&mut self, m: Mode) {
        self.root_hz = match m {
            Mode::Yo => 220.0,
            Mode::Hira => 196.0,
            Mode::In => 174.61,
            Mode::Ryo => 233.08,
        };
        self.sub_hz = self.root_hz * 0.5;
    }

    pub fn set_target_gain(&mut self, g: f32) {
        self.target_gain = g.clamp(0.0, 1.0);
    }

    pub fn next_sample(&mut self) -> f32 {
        if self.gain < self.target_gain {
            self.gain += self.gain_slew;
            if self.gain > self.target_gain {
                self.gain = self.target_gain;
            }
        } else if self.gain > self.target_gain {
            self.gain -= self.gain_slew;
            if self.gain < self.target_gain {
                self.gain = self.target_gain;
            }
        }

        let dt = 1.0 / f64::from(self.sample_rate);
        self.phase_root += 2.0 * PI * self.root_hz * dt;
        self.phase_sub += 2.0 * PI * self.sub_hz * dt;
        self.phase_lfo += 2.0 * PI * 0.1 * dt;
        if self.phase_root > 2.0 * PI {
            self.phase_root -= 2.0 * PI;
        }
        if self.phase_sub > 2.0 * PI {
            self.phase_sub -= 2.0 * PI;
        }
        if self.phase_lfo > 2.0 * PI {
            self.phase_lfo -= 2.0 * PI;
        }

        let lfo = 0.5 + 0.5 * self.phase_lfo.sin();
        let root = self.phase_root.sin() * 0.5;
        let sub = self.phase_sub.sin() * 0.6;
        let mix = (root + sub) * (0.7 + 0.3 * lfo);
        (mix as f32) * self.gain
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn gain_slews_toward_target_and_clamps() {
        let mut d = DroneVoice::new(44_100);
        d.set_target_gain(0.5);
        for _ in 0..44_100 {
            d.next_sample();
        }
        assert!((d.gain - 0.5).abs() < 1e-6);
        d.set_target_gain(9.0);
        assert_eq!(d.target_gain, 1.0);
    }

    #[test]
    fn mode_swaps_root_frequency() {
        let mut d = DroneVoice::new(44_100);
        d.set_mode(Mode::In);
        assert_eq!(d.root_hz, 174.61);
        assert_eq!(d.sub_hz, 174.61 * 0.5);
    }
}
