//! L1 pink-noise bed. Ported from `internal/audio/bed.go`.
//!
//! Go seeds the Voss-McCartney rows from `rand.NewSource(0xb1d)` — a fixed
//! seed — so this layer is bit-deterministic on both sides.

use crate::gorand::GoRand;

const BED_SEED: i64 = 0xb1d;

pub struct BedVoice {
    sample_rate: i32,
    rng: GoRand,
    rows: [f32; 5],
    counter: i64,
    lp1: f32,
    lp2: f32,
    a: f32,
    target_gain: f32,
    gain: f32,
    gain_slew: f32,
}

impl BedVoice {
    pub fn new(sample_rate: i32) -> Self {
        BedVoice {
            sample_rate,
            rng: GoRand::new(BED_SEED),
            rows: [0.0; 5],
            counter: 0,
            lp1: 0.0,
            lp2: 0.0,
            a: 0.04, // ~600 Hz at 44.1 kHz
            target_gain: 0.0,
            gain: 0.0,
            gain_slew: 1.0 / sample_rate as f32 * 3.0,
        }
    }

    pub fn set_target_gain(&mut self, g: f32) {
        self.target_gain = g.clamp(0.0, 1.0);
    }

    pub fn next_sample(&mut self) -> f32 {
        self.counter += 1;
        for i in 0..5i32 {
            if self.counter % (1i64 << i) == 0 {
                self.rows[i as usize] = (self.rng.float64() * 2.0 - 1.0) as f32;
            }
        }
        let mut pink = 0.0f32;
        for r in self.rows {
            pink += r;
        }
        pink *= 0.2;

        self.lp1 += self.a * (pink - self.lp1);
        self.lp2 += self.a * (self.lp1 - self.lp2);

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

        self.lp2 * self.gain
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn bed_is_deterministic_for_a_given_seed() {
        let run = || {
            let mut b = BedVoice::new(44_100);
            b.set_target_gain(0.2);
            (0..5_000).map(|_| b.next_sample()).collect::<Vec<_>>()
        };
        assert_eq!(run(), run());
    }

    #[test]
    fn lowpass_keeps_output_bounded() {
        let mut b = BedVoice::new(44_100);
        b.set_target_gain(1.0);
        for _ in 0..44_100 {
            b.next_sample();
        }
        let peak = (0..44_100).map(|_| b.next_sample()).fold(0.0f32, f32::max);
        assert!(peak <= 1.0, "peak {peak}");
    }
}
