package audio

import (
	"math"
	"testing"
)

func TestKarplusProducesSignal(t *testing.T) {
	v := NewKarplusVoice(44100, 440.0, 0.996, 1.0)
	var sumSq float64
	for i := 0; i < 4410; i++ {
		s := v.NextSample()
		sumSq += float64(s) * float64(s)
	}
	rms := math.Sqrt(sumSq / 4410)
	if rms < 0.001 {
		t.Errorf("Karplus voice RMS = %v, expected > 0.001 (too quiet)", rms)
	}
	if rms > 1.0 {
		t.Errorf("Karplus voice RMS = %v, exceeds 1.0 (clipping)", rms)
	}
}

func TestKarplusDecays(t *testing.T) {
	v := NewKarplusVoice(44100, 440.0, 0.990, 1.0)
	rms := func(n int) float64 {
		var sq float64
		for i := 0; i < n; i++ {
			s := v.NextSample()
			sq += float64(s) * float64(s)
		}
		return math.Sqrt(sq / float64(n))
	}
	early := rms(4410)
	late := rms(4410)
	if late >= early {
		t.Errorf("decay broken: early RMS %v vs late RMS %v (late should be smaller)", early, late)
	}
}

func TestKarplusDoneAfterLifetime(t *testing.T) {
	v := NewKarplusVoice(44100, 440.0, 0.990, 1.0)
	for i := 0; i < 44100*3; i++ {
		v.NextSample()
	}
	if !v.Done() {
		t.Error("voice should be Done after 3 seconds")
	}
	if v.NextSample() != 0 {
		t.Error("Done voice should return silence")
	}
}

func TestKarplusVelocityScales(t *testing.T) {
	vHi := NewKarplusVoice(44100, 440.0, 0.996, 1.0)
	vLo := NewKarplusVoice(44100, 440.0, 0.996, 0.25)
	peakHi, peakLo := float32(0), float32(0)
	for i := 0; i < 1000; i++ {
		h, l := vHi.NextSample(), vLo.NextSample()
		if abs32(h) > peakHi {
			peakHi = abs32(h)
		}
		if abs32(l) > peakLo {
			peakLo = abs32(l)
		}
	}
	if peakLo >= peakHi {
		t.Errorf("velocity not scaling: hi peak %v vs lo peak %v", peakHi, peakLo)
	}
}

func abs32(x float32) float32 {
	if x < 0 {
		return -x
	}
	return x
}
