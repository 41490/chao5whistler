// Package sc implements an scsynth-backed audio backend (#35) on top
// of internal/backend.Backend.
//
// Runtime status: this package is the *control* half of the scsynth
// integration — OSC dispatch, supervisor, SynthDef name routing.
// The audio capture half (JACK loopback / pipewire-jack) is still
// owned by #36 (stream/backend lifecycle decoupling); RenderFrame in
// this package returns silence so unit tests can drive the type
// without an audio thread. A machine with scsynth + jackd installed is
// the only way to verify end-to-end live audio, and that integration
// will land alongside #36.
//
// Why a real Backend impl now? #34 promised that "本地渲染和 live 都
// 经由 backend interface 工作" — having a second concrete Backend
// proves the interface is genuinely backend-agnostic, even if the
// audio path is half-built.
package sc

import (
	"context"
	"errors"
	"fmt"
	"math"
	"os/exec"
	"sync/atomic"

	"github.com/41490/chao5whistler/src/ghsingo/internal/backend"
	"github.com/41490/chao5whistler/src/ghsingo/internal/backend/sc/osc"
	"github.com/41490/chao5whistler/src/ghsingo/internal/composer"
)

// Options configures the SC backend.
type Options struct {
	// SampleRate / FPS for the (silent) RenderFrame contract.
	SampleRate int
	FPS        int

	// Composer/Mixer choices that only the SC side cares about.
	Composer composer.Config

	// Address of an externally running scsynth. If empty, a subprocess
	// is spawned through Starter.
	Address string

	// Starter spawns the subprocess. If nil, the default tries
	// scsynth -u <port> on PATH.
	Starter ProcessStarter

	// SynthDefDir is where compiled .scsyndef files live. The Init
	// step sends /d_loadDir to scsynth.
	SynthDefDir string
}

// Backend is the scsynth implementation.
type Backend struct {
	opts        Options
	supervisor  *Supervisor
	c           *composer.Composer
	droneNodeID int32
	bedNodeID   int32
	tonalNodeID int32
	nextNodeID  int32
	prevSection composer.Section
	prevMode    composer.Mode
	stats       atomic.Int64 // Accents fired
	lastState   composer.State
	silence     []float32
}

// New builds the SC backend. Init() actually starts the subprocess.
func New(opts Options) (*Backend, error) {
	if opts.SampleRate <= 0 {
		opts.SampleRate = 44100
	}
	if opts.FPS <= 0 {
		opts.FPS = 15
	}
	if opts.Starter == nil {
		opts.Starter = scsynthStarter("57110")
	}
	if opts.Address == "" {
		opts.Address = "127.0.0.1:57110"
	}
	sup, err := NewSupervisor(SupervisorOptions{
		Starter:      opts.Starter,
		Address:      opts.Address,
	})
	if err != nil {
		return nil, err
	}
	return &Backend{
		opts:        opts,
		supervisor:  sup,
		c:           composer.New(opts.Composer),
		nextNodeID:  2000,
		prevSection: composer.SectionRest,
		prevMode:    composer.ModeYo,
	}, nil
}

// Init starts the subprocess, loads the SynthDef directory, and spawns
// the long-lived drone / bed / tonal nodes.
func (b *Backend) Init() error {
	ctx := context.Background()
	if err := b.supervisor.Start(ctx); err != nil {
		return fmt.Errorf("sc init: %w", err)
	}
	if b.opts.SynthDefDir != "" {
		if err := b.supervisor.Send(osc.Message{
			Address: "/d_loadDir",
			Args:    []any{b.opts.SynthDefDir},
		}); err != nil {
			return fmt.Errorf("sc /d_loadDir: %w", err)
		}
	}
	// Spawn long-lived voices. addAction=0 (head of group), targetGroup=1.
	b.droneNodeID = b.allocNode()
	b.bedNodeID = b.allocNode()
	b.tonalNodeID = b.allocNode()
	for _, spec := range []struct {
		name string
		id   int32
	}{
		{"ghsingo_drone_v1", b.droneNodeID},
		{"ghsingo_bed_v1", b.bedNodeID},
		{"ghsingo_tonal_v1", b.tonalNodeID},
	} {
		if err := b.supervisor.Send(osc.Message{
			Address: "/s_new",
			Args: []any{
				spec.name, spec.id, int32(0), int32(1),
				"freq", float32(220.0), "amp", float32(0.0),
			},
		}); err != nil {
			return fmt.Errorf("sc /s_new %s: %w", spec.name, err)
		}
	}
	return nil
}

// Close kills the subprocess.
func (b *Backend) Close() error {
	return b.supervisor.Close()
}

// ApplyEventsForSecond ticks the composer and dispatches OSC.
//
// Mapping rule:
//   - state.Density / state.Brightness become /n_set on the long-lived
//     drone / bed / tonal nodes (continuous control)
//   - composer.Accent emits a one-shot /s_new of "ghsingo_accent_v1"
func (b *Backend) ApplyEventsForSecond(events []backend.Event) {
	cevs := make([]composer.Event, len(events))
	for i, e := range events {
		cevs[i] = composer.Event{TypeID: e.TypeID, Weight: e.Weight}
	}
	out := b.c.Tick(cevs)
	b.lastState = out.State

	// Continuous: drone amp & freq from Density/Mode
	rootHz := modeRootHz(out.State.Mode)
	droneAmp := float32(0.16 * (1 - 0.4*out.State.Density))
	bedAmp := float32(0.04 + 0.16*out.State.Brightness)
	tonalAmp := float32(0.18)
	if out.State.Section == composer.SectionRest {
		tonalAmp = 0.10
	}
	bundle := osc.Bundle{Messages: []osc.Message{
		{Address: "/n_set", Args: []any{b.droneNodeID, "freq", rootHz, "amp", droneAmp}},
		{Address: "/n_set", Args: []any{b.bedNodeID, "amp", bedAmp}},
		{Address: "/n_set", Args: []any{b.tonalNodeID, "amp", tonalAmp}},
	}}
	if err := b.supervisor.SendBundle(bundle); err != nil {
		// Soft failure: log via stderr would couple to a logger; the
		// test paths set Address="" so this branch is a no-op there.
		_ = err
	}

	for _, a := range out.Accents {
		nid := b.allocNode()
		freq := pitchHz(a)
		if err := b.supervisor.Send(osc.Message{
			Address: "/s_new",
			Args: []any{
				"ghsingo_accent_v1", nid, int32(0), int32(1),
				"freq", freq, "amp", float32(a.Velocity),
			},
		}); err != nil {
			_ = err
		}
		b.stats.Add(1)
	}
	if out.State.Section != b.prevSection {
		b.prevSection = out.State.Section
	}
	if out.State.Mode != b.prevMode {
		b.prevMode = out.State.Mode
	}
}

// RenderFrame returns silence sized to the contract. Live audio capture
// (JACK loopback) is owned by #36.
func (b *Backend) RenderFrame() ([]float32, error) {
	n := b.SamplesPerFrame() * 2
	if cap(b.silence) < n {
		b.silence = make([]float32, n)
	}
	out := b.silence[:n]
	for i := range out {
		out[i] = 0
	}
	return out, nil
}

// SampleRate / SamplesPerFrame / Name satisfy backend.Backend.
func (b *Backend) SampleRate() int      { return b.opts.SampleRate }
func (b *Backend) SamplesPerFrame() int { return b.opts.SampleRate / b.opts.FPS }
func (b *Backend) Name() string         { return "scsynth" }

// LastState exposes the composer state to sidecar reporters.
func (b *Backend) LastState() composer.State { return b.lastState }

// AccentsFired counts how many /s_new accent messages have been sent.
func (b *Backend) AccentsFired() int64 { return b.stats.Load() }

// RestartCount mirrors the supervisor's auto-restart counter so soak
// tooling (#37) can read it.
func (b *Backend) RestartCount() int64 { return b.supervisor.RestartCount() }

func (b *Backend) allocNode() int32 {
	id := b.nextNodeID
	b.nextNodeID++
	return id
}

func modeRootHz(m composer.Mode) float32 {
	switch m {
	case composer.ModeYo:
		return 220.0
	case composer.ModeHira:
		return 196.0
	case composer.ModeIn:
		return 174.61
	case composer.ModeRyo:
		return 233.08
	}
	return 220.0
}

func pitchHz(a composer.Accent) float32 {
	root := modeRootHz(a.FromMode)
	semitones := []float64{0, 2, 4, 7, 9}
	deg := a.Degree % 5
	if deg < 0 {
		deg += 5
	}
	semis := semitones[deg]
	octave := float64(a.Octave - 4)
	return float32(float64(root) * math.Pow(2, (semis/12.0)+octave))
}

// scsynthStarter returns a ProcessStarter that runs `scsynth -u <port>`
// in -u UDP mode. If scsynth is not on PATH, the cmd.Start in the
// supervisor will fail clearly.
func scsynthStarter(port string) ProcessStarter {
	return func(ctx context.Context) (*exec.Cmd, error) {
		path, err := exec.LookPath("scsynth")
		if err != nil {
			return nil, fmt.Errorf("scsynth not on PATH (install supercollider-server): %w", err)
		}
		cmd := exec.CommandContext(ctx, path, "-u", port)
		if err := cmd.Start(); err != nil {
			return nil, fmt.Errorf("scsynth start: %w", err)
		}
		return cmd, nil
	}
}

var _ backend.Backend = (*Backend)(nil)

// errSilent is a no-op kept around so static analyzers don't drop the
// errors import; future revisions will replace _ = err with structured
// logging once #36 wires a logger through Backend.
var errSilent = errors.New("sc: dropped error (#35 silent dispatch)")
var _ = errSilent
