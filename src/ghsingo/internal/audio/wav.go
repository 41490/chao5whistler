package audio

import (
	"encoding/binary"
	"errors"
	"fmt"
	"math"
	"os"
)

// DecodePCM reads WAV bytes and returns interleaved float32 samples.
// Supports 16-bit PCM WAV only.
func DecodePCM(data []byte) ([]float32, error) {
	if len(data) < 44 {
		return nil, errors.New("audio: data too short for WAV header")
	}
	if string(data[0:4]) != "RIFF" {
		return nil, errors.New("audio: missing RIFF tag")
	}
	if string(data[8:12]) != "WAVE" {
		return nil, errors.New("audio: missing WAVE tag")
	}

	var (
		audioFormat   uint16
		numChannels   uint16
		bitsPerSample uint16
		dataBytes     []byte
	)
	pos := 12
	for pos+8 <= len(data) {
		chunkID := string(data[pos : pos+4])
		chunkSize := int(binary.LittleEndian.Uint32(data[pos+4 : pos+8]))
		pos += 8

		switch chunkID {
		case "fmt ":
			if chunkSize < 16 || pos+16 > len(data) {
				return nil, errors.New("audio: fmt chunk too small")
			}
			audioFormat = binary.LittleEndian.Uint16(data[pos : pos+2])
			numChannels = binary.LittleEndian.Uint16(data[pos+2 : pos+4])
			bitsPerSample = binary.LittleEndian.Uint16(data[pos+14 : pos+16])
		case "data":
			end := pos + chunkSize
			if end > len(data) {
				end = len(data)
			}
			dataBytes = data[pos:end]
		}

		pos += chunkSize
		if chunkSize%2 != 0 {
			pos++
		}
	}

	if audioFormat != 1 {
		return nil, fmt.Errorf("audio: unsupported format %d (only PCM=1)", audioFormat)
	}
	if bitsPerSample != 16 {
		return nil, fmt.Errorf("audio: unsupported bits per sample %d (only 16)", bitsPerSample)
	}
	if dataBytes == nil {
		return nil, errors.New("audio: no data chunk found")
	}
	_ = numChannels

	numSamples := len(dataBytes) / 2
	out := make([]float32, numSamples)
	for i := 0; i < numSamples; i++ {
		s := int16(binary.LittleEndian.Uint16(dataBytes[i*2 : i*2+2]))
		out[i] = float32(s) / float32(math.MaxInt16)
	}
	return out, nil
}

// LoadWavFile loads WAV from disk.
func LoadWavFile(path string) ([]float32, error) {
	data, err := os.ReadFile(path)
	if err != nil {
		return nil, fmt.Errorf("audio: %w", err)
	}
	return DecodePCM(data)
}

// GainToLinear converts dB to linear: 10^(db/20).
func GainToLinear(db float64) float32 {
	return float32(math.Pow(10, db/20.0))
}

// ApplyFadeOut returns a copy of pcm with a linear fade-out applied to the
// last tailRatio fraction of the samples.
func ApplyFadeOut(pcm []float32, tailRatio float32) []float32 {
	n := len(pcm)
	if n == 0 || tailRatio <= 0 {
		return pcm
	}
	fadeStart := int(float32(n) * (1.0 - tailRatio))
	fadeLen := n - fadeStart
	if fadeLen <= 0 {
		return pcm
	}
	out := make([]float32, n)
	copy(out, pcm)
	for i := fadeStart; i < n; i++ {
		t := float32(i-fadeStart) / float32(fadeLen)
		out[i] *= (1.0 - t)
	}
	return out
}

// notePan maps a 五声 note to stereo pan position (0=L, 0.5=C, 1=R).
// 宫 centre, 商 偏左, 角 偏右, 徵 远左, 羽 远右.
func notePan(n Note) float32 {
	pans := [NoteCount]float32{0.50, 0.35, 0.65, 0.25, 0.75}
	return pans[n]
}
