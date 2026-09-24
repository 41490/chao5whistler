//! Schroeder reverb: 4 parallel combs -> 2 series all-passes.
//! Ported from `internal/audio/reverb.go`.

pub struct Reverb {
    combs: [CombFilter; 4],
    allpasses: [AllpassFilter; 2],
    wet: f32,
}

struct CombFilter {
    buf: Vec<f32>,
    pos: usize,
    gain: f32,
}

struct AllpassFilter {
    buf: Vec<f32>,
    pos: usize,
    gain: f32,
}

impl CombFilter {
    fn process(&mut self, x: f32) -> f32 {
        let out = self.buf[self.pos];
        self.buf[self.pos] = x + out * self.gain;
        self.pos = (self.pos + 1) % self.buf.len();
        out
    }
}

impl AllpassFilter {
    fn process(&mut self, x: f32) -> f32 {
        let delayed = self.buf[self.pos];
        let out = -x + delayed;
        self.buf[self.pos] = x + delayed * self.gain;
        self.pos = (self.pos + 1) % self.buf.len();
        out
    }
}

impl Reverb {
    pub fn new(sample_rate: i32) -> Self {
        // Mutually-prime comb delays (ms) to avoid metallic resonance.
        let comb_delays_ms = [37.0f64, 41.0, 43.0, 47.0];
        let comb_gains = [0.80f32, 0.78, 0.76, 0.74];
        let ap_delays_ms = [5.0f64, 1.7];
        let ap_gains = [0.5f32, 0.5];

        let mut combs: [CombFilter; 4] = [
            CombFilter {
                buf: Vec::new(),
                pos: 0,
                gain: 0.0,
            },
            CombFilter {
                buf: Vec::new(),
                pos: 0,
                gain: 0.0,
            },
            CombFilter {
                buf: Vec::new(),
                pos: 0,
                gain: 0.0,
            },
            CombFilter {
                buf: Vec::new(),
                pos: 0,
                gain: 0.0,
            },
        ];
        for i in 0..4 {
            let n = (comb_delays_ms[i] * f64::from(sample_rate) / 1000.0) as usize;
            combs[i] = CombFilter {
                buf: vec![0.0; n.max(1)],
                pos: 0,
                gain: comb_gains[i],
            };
        }

        let mut allpasses: [AllpassFilter; 2] = [
            AllpassFilter {
                buf: Vec::new(),
                pos: 0,
                gain: 0.0,
            },
            AllpassFilter {
                buf: Vec::new(),
                pos: 0,
                gain: 0.0,
            },
        ];
        for i in 0..2 {
            let n = ((ap_delays_ms[i] * f64::from(sample_rate) / 1000.0) as usize).max(1);
            allpasses[i] = AllpassFilter {
                buf: vec![0.0; n],
                pos: 0,
                gain: ap_gains[i],
            };
        }

        Reverb {
            combs,
            allpasses,
            wet: 0.25,
        }
    }

    pub fn set_wet(&mut self, wet: f32) {
        self.wet = wet;
    }

    pub fn process(&mut self, x: f32) -> f32 {
        let mut comb_sum = 0.0f32;
        for c in &mut self.combs {
            comb_sum += c.process(x);
        }
        comb_sum *= 0.25;
        let mut ap = self.allpasses[0].process(comb_sum);
        ap = self.allpasses[1].process(ap);
        x * (1.0 - self.wet) + ap * self.wet
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    /// Acceptance 3: the reverb must be stable for a 10-minute render —
    /// no NaN, no unbounded growth (all comb gains are < 1, so the loop is
    /// contractive; this pins that property).
    #[test]
    fn ten_minutes_of_signal_stays_finite_and_bounded() {
        let sample_rate = 44_100;
        let mut r = Reverb::new(sample_rate);
        r.set_wet(0.45);
        let mut peak = 0.0f32;
        for i in 0..(sample_rate * 600) {
            // Worst-case-ish drive: full-scale square-ish input.
            let x = if i % 2 == 0 { 1.0 } else { -1.0 };
            let y = r.process(x);
            assert!(y.is_finite(), "non-finite at sample {i}");
            peak = peak.max(y.abs());
        }
        assert!(peak < 4.0, "reverb diverged: peak {peak}");
    }

    #[test]
    fn wet_zero_returns_dry() {
        let mut r = Reverb::new(44_100);
        r.set_wet(0.0);
        assert_eq!(r.process(0.5), 0.5);
    }
}
