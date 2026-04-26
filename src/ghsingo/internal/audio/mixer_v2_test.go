package audio

import (
	"math"
	"testing"

	"github.com/41490/chao5whistler/src/ghsingo/internal/composer"
)

// rmsOf computes root-mean-square of an interleaved stereo float32 buffer.
func rmsOf(buf []float32) float64 {
	if len(buf) == 0 {
		return 0
	}
	var s float64
	for _, v := range buf {
		s += float64(v) * float64(v)
	}
	return math.Sqrt(s / float64(len(buf)))
}

// TestMixerV2ContinuousFloor is the #31 DoD: the v2 mixer must produce a
// continuous audible floor (drone + bed) even when no events arrive and
// no accents fire. Compare to bell-era which would output near-silence
// in the same scenario after the bell decay.
func TestMixerV2ContinuousFloor(t *testing.T) {
	const sr = 44100
	const fps = 15
	mx := NewMixerV2(sr, fps, 4)

	// Drive a state representative of "low activity": Density=0.1, Brightness=0.5.
	mx.ApplyOutput(composer.Output{
		State: composer.State{
			Density:    0.1,
			Brightness: 0.5,
			Mode:       composer.ModeYo,
			Section:    composer.SectionRest,
		},
	})

	// Render ~1 second to let drone+bed slew up.
	for i := 0; i < fps; i++ {
		mx.RenderFrame()
	}

	// Now measure the next 1 second — must be non-silent.
	var rmsTotal float64
	const windows = 5
	for i := 0; i < windows; i++ {
		var buf []float32
		for j := 0; j < fps/windows; j++ {
			buf = append(buf, mx.RenderFrame()...)
		}
		rmsTotal += rmsOf(buf)
	}
	avgRMS := rmsTotal / windows
	if avgRMS < 0.005 {
		t.Fatalf("mixer v2 floor too quiet: avg RMS %.5f (need >= 0.005 — drone+bed must always be audible)", avgRMS)
	}
}

// TestMixerV2BrightnessLiftsBed: pushing Brightness from 0 -> 1 should
// raise the steady-state RMS (the bed gain ramps with brightness).
func TestMixerV2BrightnessLiftsBed(t *testing.T) {
	const sr = 44100
	const fps = 15

	measure := func(brightness float64) float64 {
		mx := NewMixerV2(sr, fps, 4)
		mx.ApplyOutput(composer.Output{State: composer.State{
			Density:    0.0,
			Brightness: brightness,
			Mode:       composer.ModeYo,
			Section:    composer.SectionRest,
		}})
		// Slew time: ~2s for the bed/drone to settle.
		for i := 0; i < fps*3; i++ {
			mx.RenderFrame()
		}
		var buf []float32
		for i := 0; i < fps; i++ {
			buf = append(buf, mx.RenderFrame()...)
		}
		return rmsOf(buf)
	}

	low := measure(0.0)
	high := measure(1.0)
	if high <= low {
		t.Fatalf("brightness=1 RMS (%.4f) must exceed brightness=0 (%.4f)", high, low)
	}
}

// TestMixerV2AccentBoundedPolyphony: even if 100 accents arrive in one
// tick, simultaneously active voices must not exceed accentMax.
func TestMixerV2AccentBoundedPolyphony(t *testing.T) {
	const sr = 44100
	const fps = 15
	mx := NewMixerV2(sr, fps, 3)
	mx.SetAccentBank(NewBellBank(sr))

	accents := make([]composer.Accent, 100)
	for i := range accents {
		accents[i] = composer.Accent{Velocity: 0.8, Degree: i % 5, Octave: 4, FromMode: composer.ModeYo}
	}
	mx.ApplyOutput(composer.Output{
		State:   composer.State{Mode: composer.ModeYo},
		Accents: accents,
	})

	// Render two frames so spawn happens.
	mx.RenderFrame()
	mx.RenderFrame()
	if got := len(mx.activeAccents); got > 3 {
		t.Fatalf("active accents %d > cap 3", got)
	}
}

// TestMixerV2NoAccentsWithoutBank: with no bell bank installed, accent
// events should be silently dropped (no panic, no nil deref).
func TestMixerV2NoAccentsWithoutBank(t *testing.T) {
	const sr = 44100
	const fps = 15
	mx := NewMixerV2(sr, fps, 4)

	mx.ApplyOutput(composer.Output{
		State: composer.State{Mode: composer.ModeYo},
		Accents: []composer.Accent{
			{Velocity: 0.7, Degree: 0, Octave: 4, FromMode: composer.ModeYo},
		},
	})
	for i := 0; i < fps; i++ {
		_ = mx.RenderFrame()
	}
	if len(mx.activeAccents) != 0 {
		t.Fatalf("unexpected accent voices spawned without bank: %d", len(mx.activeAccents))
	}
}

// TestPentatonicForModeRotates ensures mode -> note rotation gives
// distinct degree-0 tonics for at least three of the four modes.
func TestPentatonicForModeRotates(t *testing.T) {
	yo := pentatonicForMode(composer.ModeYo)[0]
	hira := pentatonicForMode(composer.ModeHira)[0]
	in := pentatonicForMode(composer.ModeIn)[0]
	if yo == hira || hira == in || yo == in {
		t.Fatalf("expected distinct tonics across Yo/Hira/In, got %v %v %v", yo, hira, in)
	}
}
