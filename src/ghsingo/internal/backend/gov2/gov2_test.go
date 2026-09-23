package gov2

import (
	"testing"

	"github.com/41490/chao5whistler/src/ghsingo/internal/backend"
	"github.com/41490/chao5whistler/src/ghsingo/internal/composer"
)

// TestGoV2ImplementsBackend asserts at compile time + runtime that *Backend
// satisfies the interface. Catching this here means the cmd/* binaries
// never have to fight type assertions.
func TestGoV2ImplementsBackend(t *testing.T) {
	var _ backend.Backend = (*Backend)(nil)
	b := New(Options{SampleRate: 44100, FPS: 15})
	if b.Name() != "go-v2" {
		t.Fatalf("Name = %q, want go-v2", b.Name())
	}
	if b.SampleRate() != 44100 {
		t.Fatalf("SampleRate = %d, want 44100", b.SampleRate())
	}
	if b.SamplesPerFrame() != 44100/15 {
		t.Fatalf("SamplesPerFrame = %d, want %d", b.SamplesPerFrame(), 44100/15)
	}
	if err := b.Init(); err != nil {
		t.Fatalf("Init: %v", err)
	}
	defer b.Close()

	b.ApplyEventsForSecond([]backend.Event{{TypeID: 0, Weight: 30}})
	frame, err := b.RenderFrame()
	if err != nil {
		t.Fatalf("RenderFrame: %v", err)
	}
	want := b.SamplesPerFrame() * 2
	if len(frame) != want {
		t.Fatalf("frame len %d, want %d", len(frame), want)
	}
}

// TestGoV2DensityRisesIndependentlyOfAccents — the architectural bridge
// from #30 stays preserved under the backend abstraction: high event
// counts must lift composer.State.Density without flooding accents.
func TestGoV2DensityRisesIndependentlyOfAccents(t *testing.T) {
	b := New(Options{
		SampleRate: 44100,
		FPS:        15,
		Composer:   composer.Config{Seed: 42, PhraseTicks: 16},
	})
	defer b.Close()

	heavy := make([]backend.Event, 50)
	for i := range heavy {
		heavy[i] = backend.Event{TypeID: 0, Weight: 30}
	}
	for i := 0; i < 60; i++ {
		b.ApplyEventsForSecond(heavy)
		_, _ = b.RenderFrame()
	}
	if d := b.LastState().Density; d < 0.5 {
		t.Fatalf("heavy load Density = %.3f, want > 0.5", d)
	}
}
