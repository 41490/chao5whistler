//! Karplus-Strong one-shot bell voice. Ported from `internal/audio/karplus.go`.
//!
//! NOTE on determinism: Go seeds this voice from the *global* `math/rand`,
//! which Go 1.20+ auto-seeds per process — so two Go renders of the same
//! window are already not sample-identical. rsghsing seeds a local generator
//! from a fixed constant instead; the audio-parity tolerance (|Δ| ≤ 1.0 LU)
//! absorbs the difference and every render is reproducible.

use crate::gorand::GoRand;

pub struct KarplusVoice {
    buf: Vec<f32>,
    pos: usize,
    decay: f64,
    remaining: i32,
    velocity: f32,
}

impl KarplusVoice {
    /// `freq` in Hz, `decay` in 0.99..0.999, `velocity` scales excitation.
    /// Auto-silences after ~2 seconds (safety cap).
    pub fn new(sample_rate: i32, freq: f64, decay: f64, velocity: f32, seed: i64) -> Self {
        let mut n = (f64::from(sample_rate) / freq) as usize;
        if n < 2 {
            n = 2;
        }
        let mut rng = GoRand::new(seed);
        let buf: Vec<f32> = (0..n)
            .map(|_| (rng.float64() * 2.0 - 1.0) as f32 * velocity)
            .collect();
        KarplusVoice {
            buf,
            pos: 0,
            decay,
            remaining: sample_rate * 2,
            velocity,
        }
    }

    pub fn next_sample(&mut self) -> f32 {
        if self.remaining <= 0 {
            return 0.0;
        }
        let out = self.buf[self.pos];
        let next = (self.pos + 1) % self.buf.len();
        let averaged = (self.buf[self.pos] + self.buf[next]) * 0.5;
        self.buf[self.pos] = (f64::from(averaged) * self.decay) as f32;
        self.pos = next;
        self.remaining -= 1;
        out
    }

    pub fn done(&self) -> bool {
        self.remaining <= 0
    }
}
