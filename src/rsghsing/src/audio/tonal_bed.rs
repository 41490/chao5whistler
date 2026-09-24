//! L0.5 sample-based tonal bed. Ported from `internal/audio/tonal_bed.go`.

pub struct TonalBedVoice {
    pcm: Vec<f32>,
    pos: usize,
    crossfade: usize,
    lp: f32,
    a: f32,
    gain: f32,
    target_gain: f32,
    gain_slew: f32,
}

impl TonalBedVoice {
    pub fn new(sample_rate: i32, pcm: Vec<f32>) -> Self {
        let mut crossfade = sample_rate as usize / 20; // 50 ms
        if crossfade > pcm.len() / 2 {
            crossfade = pcm.len() / 2;
        }
        TonalBedVoice {
            pcm,
            pos: 0,
            crossfade,
            lp: 0.0,
            a: 0.10, // ~1.5 kHz lowpass
            gain: 0.0,
            target_gain: 0.0,
            gain_slew: 1.0 / sample_rate as f32 * 4.0,
        }
    }

    pub fn set_target_gain(&mut self, g: f32) {
        self.target_gain = g.clamp(0.0, 1.0);
    }

    pub fn next_sample(&mut self) -> f32 {
        if self.pcm.is_empty() {
            return 0.0;
        }
        let loop_len = self.pcm.len();
        let pos = self.pos % loop_len;
        let mut s = self.pcm[pos];

        if self.crossfade > 0 && self.crossfade < loop_len / 2 {
            let tail = loop_len - self.crossfade;
            if pos >= tail {
                let fade_out = (loop_len - pos) as f32 / self.crossfade as f32;
                let fade_in = 1.0 - fade_out;
                let head_pos = pos - tail;
                s = s * fade_out + self.pcm[head_pos] * fade_in;
            }
        }
        self.pos += 1;

        self.lp += self.a * (s - self.lp);

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

        self.lp * self.gain
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn empty_pcm_is_silent() {
        let mut t = TonalBedVoice::new(44_100, Vec::new());
        assert_eq!(t.next_sample(), 0.0);
    }

    #[test]
    fn crossfade_region_stays_continuous() {
        let pcm: Vec<f32> = (0..1_000).map(|i| (i as f32 / 1_000.0) - 0.5).collect();
        let mut t = TonalBedVoice::new(44_100, pcm);
        t.set_target_gain(1.0);
        let out: Vec<f32> = (0..3_000).map(|_| t.next_sample()).collect();
        for w in out.windows(2) {
            assert!((w[1] - w[0]).abs() < 0.05, "jump {} -> {}", w[0], w[1]);
        }
    }
}
