//! Minimal 16-bit PCM WAV reader + helpers. Ported from `internal/audio/wav.go`.
//!
//! Hand-rolled rather than a crate: the P2 whitelist allows a small wav lib,
//! but the decoder is 40 lines and the format is fixed (16-bit PCM, whatever
//! channel count the asset carries), so the dependency buys nothing.

use anyhow::{bail, Result};

/// Reads WAV bytes and returns interleaved float32 samples in [-1, 1).
/// Supports 16-bit PCM WAV only, like the Go reference.
pub fn decode_pcm(data: &[u8]) -> Result<Vec<f32>> {
    if data.len() < 44 {
        bail!("audio: data too short for WAV header");
    }
    if &data[0..4] != b"RIFF" {
        bail!("audio: missing RIFF tag");
    }
    if &data[8..12] != b"WAVE" {
        bail!("audio: missing WAVE tag");
    }

    let mut audio_format: u16 = 0;
    let mut bits_per_sample: u16 = 0;
    let mut data_bytes: &[u8] = &[];
    let mut pos = 12usize;
    while pos + 8 <= data.len() {
        let chunk_id = &data[pos..pos + 4];
        let chunk_size = u32::from_le_bytes(data[pos + 4..pos + 8].try_into().unwrap()) as usize;
        pos += 8;
        match chunk_id {
            b"fmt " => {
                if chunk_size < 16 || pos + 16 > data.len() {
                    bail!("audio: fmt chunk too small");
                }
                audio_format = u16::from_le_bytes(data[pos..pos + 2].try_into().unwrap());
                bits_per_sample = u16::from_le_bytes(data[pos + 14..pos + 16].try_into().unwrap());
            }
            b"data" => {
                let end = (pos + chunk_size).min(data.len());
                data_bytes = &data[pos..end];
            }
            _ => {}
        }
        pos += chunk_size;
        if !chunk_size.is_multiple_of(2) {
            pos += 1;
        }
    }

    if audio_format != 1 {
        bail!("audio: unsupported format {audio_format} (only PCM=1)");
    }
    if bits_per_sample != 16 {
        bail!("audio: unsupported bits per sample {bits_per_sample} (only 16)");
    }
    if data_bytes.is_empty() {
        bail!("audio: no data chunk found");
    }

    let num_samples = data_bytes.len() / 2;
    let mut out = Vec::with_capacity(num_samples);
    for i in 0..num_samples {
        let s = i16::from_le_bytes([data_bytes[i * 2], data_bytes[i * 2 + 1]]);
        out.push(f32::from(s) / f32::from(i16::MAX));
    }
    Ok(out)
}

pub fn load_wav_file(path: &std::path::Path) -> Result<Vec<f32>> {
    let data = std::fs::read(path)?;
    decode_pcm(&data)
}

/// dB -> linear: 10^(db/20).
pub fn gain_to_linear(db: f64) -> f32 {
    10f64.powf(db / 20.0) as f32
}

#[cfg(test)]
mod tests {
    use super::*;

    fn wav(samples: &[i16]) -> Vec<u8> {
        let data_len = samples.len() * 2;
        let mut v = Vec::new();
        v.extend_from_slice(b"RIFF");
        v.extend_from_slice(&((36 + data_len) as u32).to_le_bytes());
        v.extend_from_slice(b"WAVE");
        v.extend_from_slice(b"fmt ");
        v.extend_from_slice(&16u32.to_le_bytes());
        v.extend_from_slice(&1u16.to_le_bytes()); // PCM
        v.extend_from_slice(&1u16.to_le_bytes()); // mono
        v.extend_from_slice(&44_100u32.to_le_bytes());
        v.extend_from_slice(&88_200u32.to_le_bytes());
        v.extend_from_slice(&2u16.to_le_bytes());
        v.extend_from_slice(&16u16.to_le_bytes());
        v.extend_from_slice(b"data");
        v.extend_from_slice(&(data_len as u32).to_le_bytes());
        for s in samples {
            v.extend_from_slice(&s.to_le_bytes());
        }
        v
    }

    #[test]
    fn decodes_sixteen_bit_pcm_to_unit_float() {
        let pcm = decode_pcm(&wav(&[0, i16::MAX, i16::MIN, 16384])).unwrap();
        assert_eq!(pcm[0], 0.0);
        assert!((pcm[1] - 1.0).abs() < 1e-6);
        // Go divides by MaxInt16 too, so i16::MIN lands slightly past -1.
        assert!((pcm[2] + 1.0000305).abs() < 1e-6);
        assert!((pcm[3] - 16384.0 / 32767.0).abs() < 1e-6);
    }

    #[test]
    fn rejects_non_pcm_and_short_buffers() {
        assert!(decode_pcm(b"short").is_err());
        let mut bad = wav(&[0]);
        bad[20] = 3; // audio_format = IEEE float
        assert!(decode_pcm(&bad).is_err());
    }

    #[test]
    fn gain_to_linear_matches_go() {
        assert!((gain_to_linear(-4.8) - 0.575_439_9).abs() < 1e-4);
        assert_eq!(gain_to_linear(0.0), 1.0);
    }
}
