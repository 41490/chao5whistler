package audio

import (
	"fmt"
	"os"
	"path/filepath"
)

// BellBank maps each pentatonic Pitch to either a pre-rendered long-form sample
// (preferred for rank-1 and Release events) or an on-demand Karplus-Strong
// synth voice (used for rank 2-4 and as a fallback when a sample is missing).
type BellBank struct {
	sampleRate int
	samples    map[Pitch][]float32
	synthDecay float64
}

// NewBellBank creates an empty bank using the given sample rate for synth.
func NewBellBank(sampleRate int) *BellBank {
	return &BellBank{
		sampleRate: sampleRate,
		samples:    make(map[Pitch][]float32),
		synthDecay: 0.996,
	}
}

// SetSynthDecay configures the Karplus-Strong decay coefficient (0.990~0.999).
func (b *BellBank) SetSynthDecay(decay float64) {
	b.synthDecay = decay
}

// LoadFromDir scans dir for {note}{octave}.wav files matching the 15 pitches
// and loads every one it finds. Missing files are silently skipped (the
// runtime falls back to synth). Returns the number of samples loaded.
func (b *BellBank) LoadFromDir(dir string) (int, error) {
	loaded := 0
	for _, p := range AllPitches() {
		path := filepath.Join(dir, p.Filename())
		if _, err := os.Stat(path); err != nil {
			continue
		}
		pcm, err := LoadWavFile(path)
		if err != nil {
			return loaded, fmt.Errorf("load %s: %w", path, err)
		}
		b.samples[p] = pcm
		loaded++
	}
	return loaded, nil
}

// HasSample reports whether a pre-rendered sample exists for pitch p.
func (b *BellBank) HasSample(p Pitch) bool {
	_, ok := b.samples[p]
	return ok
}

// SampleVoice returns a new playback voice for p, or nil if no sample is
// loaded for that pitch.
func (b *BellBank) SampleVoice(p Pitch, velocity float32) *SampleVoice {
	pcm, ok := b.samples[p]
	if !ok {
		return nil
	}
	return &SampleVoice{pcm: pcm, velocity: velocity}
}

// SynthVoice returns a new Karplus-Strong synth voice for p.
func (b *BellBank) SynthVoice(p Pitch, velocity float32) *KarplusVoice {
	return NewKarplusVoice(b.sampleRate, p.Frequency(), b.synthDecay, velocity)
}

// SampleVoice is a one-shot sampled-bell playback instance.
type SampleVoice struct {
	pcm      []float32
	pos      int
	velocity float32
}

// NextSample returns one sample and advances the playhead.
func (s *SampleVoice) NextSample() float32 {
	if s.pos >= len(s.pcm) {
		return 0
	}
	v := s.pcm[s.pos] * s.velocity
	s.pos++
	return v
}

// Done reports whether the sample has finished.
func (s *SampleVoice) Done() bool {
	return s.pos >= len(s.pcm)
}
