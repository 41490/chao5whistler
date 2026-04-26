package audio

import (
	"math"
	"testing"
)

// TestTonalBedNilSamplesSafe: a TonalBedVoice with no PCM must not panic
// and must emit silence; this is the "disabled layer" path.
func TestTonalBedNilSamplesSafe(t *testing.T) {
	v := NewTonalBedVoice(44100, nil)
	v.SetTargetGain(1.0)
	for i := 0; i < 1000; i++ {
		if got := v.NextSample(); got != 0 {
			t.Fatalf("nil PCM should be silent, got %v at i=%d", got, i)
		}
	}
}

// TestTonalBedLoopsWithCrossfade: a short ramp PCM should keep playing
// past its length (the loop) and produce no zero samples at the
// crossfade boundary (proves the crossfade smooths the seam).
func TestTonalBedLoopsWithCrossfade(t *testing.T) {
	const sr = 44100
	pcm := make([]float32, sr) // 1 second of ramp
	for i := range pcm {
		pcm[i] = float32(i+1) / float32(len(pcm))
	}
	v := NewTonalBedVoice(sr, pcm)
	v.SetTargetGain(1.0)

	// Walk past one loop boundary.
	var minAbs float32 = math.MaxFloat32
	for i := 0; i < int(float64(len(pcm))*1.5); i++ {
		s := v.NextSample()
		if i > sr/4 && i < int(float64(len(pcm))*1.4) {
			abs := s
			if abs < 0 {
				abs = -abs
			}
			if abs < minAbs {
				minAbs = abs
			}
		}
	}
	// After the slew + steady state, the lowpassed ramp should never
	// drop to absolute zero — that would mean the crossfade is dead-zoning.
	if minAbs == 0 {
		t.Fatal("tonal bed produced a hard zero across the loop boundary")
	}
}

// TestTonalBedGainSlew: target gain is reached smoothly, never overshoots.
func TestTonalBedGainSlew(t *testing.T) {
	const sr = 44100
	pcm := make([]float32, sr/10)
	for i := range pcm {
		pcm[i] = 0.5
	}
	v := NewTonalBedVoice(sr, pcm)
	v.SetTargetGain(0.8)

	var maxOut float32
	for i := 0; i < sr; i++ {
		s := v.NextSample()
		if s > maxOut {
			maxOut = s
		}
	}
	// 0.5 input × 0.8 target * lowpass headroom ≈ 0.4 ceiling. Anything
	// above 0.5 means the slew overshot the target.
	if maxOut > 0.5 {
		t.Fatalf("gain overshoot: max=%.3f", maxOut)
	}
	if maxOut < 0.2 {
		t.Fatalf("gain never approached target: max=%.3f", maxOut)
	}
}
