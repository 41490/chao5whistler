//! Accent voice bank. Ported from `internal/audio/bellbank.go`.
//!
//! Call-chain note for the P2 report: `render-audio-v2` loads the sampled
//! bank via `LoadFromDir`, but `MixerV2.spawnAccent` only ever calls
//! `SynthVoice` — `SampleVoice` is never constructed on the render path. The
//! loaded PCM is therefore inert; it is kept so the port's behaviour (and the
//! "load N samples" log line) matches Go exactly.

use std::path::Path;

use anyhow::Result;

use crate::audio::karplus::KarplusVoice;
use crate::audio::pitch::{self, Pitch};
use crate::audio::wav;

pub struct BellBank {
    sample_rate: i32,
    samples: Vec<(Pitch, Vec<f32>)>,
    synth_decay: f64,
}

impl BellBank {
    pub fn new(sample_rate: i32) -> Self {
        BellBank {
            sample_rate,
            samples: Vec::new(),
            synth_decay: 0.996,
        }
    }

    pub fn set_synth_decay(&mut self, decay: f64) {
        self.synth_decay = decay;
    }

    /// Scans `dir` for `{note}{octave}.wav` matching the 15 pitches.
    /// Missing files are skipped. Returns the number loaded.
    pub fn load_from_dir(&mut self, dir: &Path) -> Result<usize> {
        let mut loaded = 0;
        for p in pitch::all_pitches() {
            let path = dir.join(p.filename());
            if !path.exists() {
                continue;
            }
            let pcm = wav::load_wav_file(&path)
                .map_err(|e| anyhow::anyhow!("load {}: {e}", path.display()))?;
            self.samples.push((p, pcm));
            loaded += 1;
        }
        Ok(loaded)
    }

    pub fn has_sample(&self, p: Pitch) -> bool {
        self.samples.iter().any(|(k, _)| *k == p)
    }

    pub fn synth_voice(&self, p: Pitch, velocity: f32, seed: i64) -> KarplusVoice {
        KarplusVoice::new(self.sample_rate, p.frequency(), self.synth_decay, velocity, seed)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn synth_voice_is_silenced_after_two_seconds() {
        let b = BellBank::new(44_100);
        let mut v = b.synth_voice(
            Pitch { note: pitch::Note::Gong, octave: pitch::Octave::Mid },
            1.0,
            1,
        );
        for _ in 0..44_100 * 3 {
            v.next_sample();
        }
        assert!(v.done());
        assert_eq!(v.next_sample(), 0.0);
    }

    #[test]
    fn load_from_dir_missing_dir_loads_nothing() {
        let mut b = BellBank::new(44_100);
        assert_eq!(b.load_from_dir(Path::new("/nonexistent-rsghsing")).unwrap(), 0);
    }
}
