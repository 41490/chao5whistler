// Package gov2 is the Go reference implementation of backend.Backend.
// It wraps composer (#30) + MixerV2 (#31) + the v2 asset pipeline
// (#32). Everything above this package can stay backend-agnostic — see
// internal/backend/backend.go for the contract.
package gov2

import (
	"github.com/41490/chao5whistler/src/ghsingo/internal/audio"
	"github.com/41490/chao5whistler/src/ghsingo/internal/backend"
	"github.com/41490/chao5whistler/src/ghsingo/internal/composer"
)

// Options carries everything the gov2 backend needs from a v2 toml
// (and from the daypack metadata). Filling Mixer/Composer is optional
// — zero-valued fields fall back to in-code defaults.
type Options struct {
	SampleRate int
	FPS        int

	Composer composer.Config
	Mixer    MixerConfig
	Assets   AssetsConfig
}

// MixerConfig mirrors the v2 [mixer] toml block.
type MixerConfig struct {
	MasterGain    float32
	DroneGain     float32
	BedGain       float32
	TonalBedGain  float32
	AccentGain    float32
	WetContinuous float32
	WetAccent     float32
	AccentMax     int
}

// AssetsConfig mirrors the v2 [assets.*] toml blocks. PCM is loaded by
// the caller and passed in pre-decoded so this package does no I/O.
type AssetsConfig struct {
	TonalBedPCM     []float32
	TonalBedGainDB  float64
	AccentBank      *audio.BellBank
	AccentSynthDecay float64 // surfaced for completeness; the bank caller already applied it
}

// Stats accumulates over a backend's lifetime so sidecar reporters
// don't have to peek inside composer/mixer themselves.
type Stats struct {
	Ticks              int
	Accents            int
	SectionTransitions int
	ModeTransitions    int
}

// Backend is the gov2 implementation. Construct via New.
type Backend struct {
	opts Options
	mx   *audio.MixerV2
	c    *composer.Composer

	stats       Stats
	prevSection composer.Section
	prevMode    composer.Mode
}

// New builds the backend but does not allocate external resources;
// call Init (a no-op for gov2 today) before driving it.
func New(opts Options) *Backend {
	if opts.SampleRate <= 0 {
		opts.SampleRate = 44100
	}
	if opts.FPS <= 0 {
		opts.FPS = 15
	}
	accentMax := opts.Mixer.AccentMax
	if accentMax <= 0 {
		accentMax = 4
	}
	mx := audio.NewMixerV2(opts.SampleRate, opts.FPS, accentMax)
	if opts.Mixer.MasterGain > 0 {
		mx.SetMasterGain(opts.Mixer.MasterGain)
	}
	if opts.Mixer.DroneGain > 0 {
		mx.SetDroneGain(opts.Mixer.DroneGain)
	}
	if opts.Mixer.BedGain > 0 {
		mx.SetBedGain(opts.Mixer.BedGain)
	}
	if opts.Mixer.TonalBedGain > 0 {
		mx.SetTonalBedGain(opts.Mixer.TonalBedGain)
	}
	if opts.Mixer.AccentGain > 0 {
		mx.SetAccentGain(opts.Mixer.AccentGain)
	}
	if opts.Mixer.WetContinuous > 0 || opts.Mixer.WetAccent > 0 {
		mx.SetWet(opts.Mixer.WetContinuous, opts.Mixer.WetAccent)
	}
	if opts.Assets.AccentBank != nil {
		mx.SetAccentBank(opts.Assets.AccentBank)
	}
	if len(opts.Assets.TonalBedPCM) > 0 {
		mx.SetTonalBedPCM(opts.Assets.TonalBedPCM)
		if opts.Assets.TonalBedGainDB != 0 {
			mx.SetTonalBedGain(audio.GainToLinear(opts.Assets.TonalBedGainDB))
		}
	}

	return &Backend{
		opts:        opts,
		mx:          mx,
		c:           composer.New(opts.Composer),
		prevSection: composer.SectionRest,
		prevMode:    composer.ModeYo,
	}
}

// Init satisfies backend.Backend; gov2 has no external resources.
func (b *Backend) Init() error { return nil }

// Close satisfies backend.Backend; gov2 has nothing to release.
func (b *Backend) Close() error { return nil }

// ApplyEventsForSecond ticks the composer and feeds the resulting
// state + accents into the mixer.
func (b *Backend) ApplyEventsForSecond(events []backend.Event) {
	cevs := make([]composer.Event, len(events))
	for i, e := range events {
		cevs[i] = composer.Event{TypeID: e.TypeID, Weight: e.Weight}
	}
	out := b.c.Tick(cevs)
	b.mx.ApplyOutput(out)

	b.stats.Ticks++
	b.stats.Accents += len(out.Accents)
	if out.State.Section != b.prevSection {
		b.stats.SectionTransitions++
		b.prevSection = out.State.Section
	}
	if out.State.Mode != b.prevMode {
		b.stats.ModeTransitions++
		b.prevMode = out.State.Mode
	}
}

// RenderFrame returns one stereo float32 frame.
func (b *Backend) RenderFrame() ([]float32, error) {
	return b.mx.RenderFrame(), nil
}

// SampleRate returns the configured sample rate.
func (b *Backend) SampleRate() int { return b.opts.SampleRate }

// SamplesPerFrame returns sample-rate / fps.
func (b *Backend) SamplesPerFrame() int { return b.opts.SampleRate / b.opts.FPS }

// Name identifies the backend.
func (b *Backend) Name() string { return "go-v2" }

// LastState exposes the composer state for sidecar/metric use without
// breaking the Backend interface.
func (b *Backend) LastState() composer.State { return b.mx.LastState() }

// Stats returns lifetime counters since the backend was constructed.
func (b *Backend) Stats() Stats { return b.stats }
