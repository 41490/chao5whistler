// Package lifecycle decouples the ffmpeg/RTMP stream lifetime from the
// audio backend lifetime (#36).
//
// BackendBox wraps an internal/backend.Backend and a Factory. If the
// inner backend errors on RenderFrame or ApplyEventsForSecond, or if a
// caller signals Restart(), the box tears the inner backend down and
// rebuilds via Factory while continuing to emit silence frames so the
// outer ffmpeg pipe never sees an EOF. The 24/7 live invariant is:
// ffmpeg/RTMP outlives every individual scsynth crash.
package lifecycle

import (
	"sync"
	"sync/atomic"

	"github.com/41490/chao5whistler/src/ghsingo/internal/backend"
)

// Factory builds a fresh backend instance. It is called once on
// startup and again after every restart.
type Factory func() (backend.Backend, error)

// BackendBox itself implements backend.Backend, so callers can wrap an
// existing pipeline by changing exactly one line.
type BackendBox struct {
	factory      Factory
	samplesFrame int

	mu       sync.Mutex
	inner    backend.Backend
	healthy  bool
	silence  []float32
	restarts atomic.Int64

	// lastErr holds the most recent factory-or-Init error so soak
	// tooling (#37) can surface what's wrong without injecting a logger.
	// Guarded by mu (storing typed-nil into atomic.Value panics, so a
	// plain mutex stays simpler and correct).
	lastErr error
}

// NewBackendBox builds the box but does not call Init yet. samplesPerFrame
// must match what the underlying backend will return; it determines the
// length of silence frames produced during outages.
func NewBackendBox(factory Factory, samplesPerFrame int) *BackendBox {
	if samplesPerFrame <= 0 {
		samplesPerFrame = 2940 // 44100/15 sane default
	}
	return &BackendBox{
		factory:      factory,
		samplesFrame: samplesPerFrame,
		silence:      make([]float32, samplesPerFrame*2),
	}
}

// Init builds the inner backend for the first time. If Factory or the
// inner Init fails, the box stays in unhealthy state and starts emitting
// silence — Init returns the underlying error so the caller can decide
// whether to abort or proceed (live RTMP usually wants to proceed and
// rely on Restart()).
func (b *BackendBox) Init() error {
	return b.replaceInner()
}

// Close tears down the current inner backend. It is idempotent.
func (b *BackendBox) Close() error {
	b.mu.Lock()
	defer b.mu.Unlock()
	if b.inner == nil {
		return nil
	}
	err := b.inner.Close()
	b.inner = nil
	b.healthy = false
	return err
}

// ApplyEventsForSecond forwards to the inner backend if healthy, drops
// the events on the floor otherwise. Drops are silent: missing events
// during a restart are usually preferable to crashing.
func (b *BackendBox) ApplyEventsForSecond(events []backend.Event) {
	b.mu.Lock()
	inner := b.inner
	healthy := b.healthy
	b.mu.Unlock()
	if !healthy || inner == nil {
		return
	}
	inner.ApplyEventsForSecond(events)
}

// RenderFrame returns a frame from the inner backend, or silence if the
// backend is unhealthy. RenderFrame never returns an error so callers
// can assume the stream pipe always has bytes to consume.
func (b *BackendBox) RenderFrame() ([]float32, error) {
	b.mu.Lock()
	inner := b.inner
	healthy := b.healthy
	b.mu.Unlock()
	if !healthy || inner == nil {
		return b.silenceFrame(), nil
	}
	frame, err := inner.RenderFrame()
	if err != nil {
		// Inner backend signaled an error mid-frame; mark unhealthy and
		// return silence. The next caller will see silence too until a
		// Restart succeeds.
		b.mu.Lock()
		b.healthy = false
		b.lastErr = err
		b.mu.Unlock()
		return b.silenceFrame(), nil
	}
	if len(frame) == 0 {
		return b.silenceFrame(), nil
	}
	return frame, nil
}

// Restart drives a graceful tear-down + rebuild without dropping the
// outer stream. While the rebuild runs, RenderFrame returns silence.
// Returns the rebuild error (caller may choose to retry on a timer).
func (b *BackendBox) Restart() error {
	b.restarts.Add(1)
	return b.replaceInner()
}

// RestartCount reports how many times Restart() has been called
// (including the initial Init's failure-recovery path).
func (b *BackendBox) RestartCount() int64 { return b.restarts.Load() }

// LastInitErr returns the most recent factory/Init error, or nil if
// the box has been healthy since startup.
func (b *BackendBox) LastInitErr() error {
	b.mu.Lock()
	defer b.mu.Unlock()
	return b.lastErr
}

// SampleRate forwards to inner; returns 0 when no inner is alive.
func (b *BackendBox) SampleRate() int {
	b.mu.Lock()
	defer b.mu.Unlock()
	if b.inner == nil {
		return 0
	}
	return b.inner.SampleRate()
}

// SamplesPerFrame returns the configured frame size (used for silence).
func (b *BackendBox) SamplesPerFrame() int { return b.samplesFrame }

// Name reports the wrapping shape so logs make sense ("box(scsynth)").
func (b *BackendBox) Name() string {
	b.mu.Lock()
	inner := b.inner
	b.mu.Unlock()
	if inner == nil {
		return "box(unhealthy)"
	}
	return "box(" + inner.Name() + ")"
}

func (b *BackendBox) replaceInner() error {
	b.mu.Lock()
	old := b.inner
	b.inner = nil
	b.healthy = false
	b.mu.Unlock()
	if old != nil {
		_ = old.Close()
	}

	next, err := b.factory()
	if err != nil {
		b.mu.Lock()
		b.lastErr = err
		b.mu.Unlock()
		return err
	}
	if err := next.Init(); err != nil {
		_ = next.Close()
		b.mu.Lock()
		b.lastErr = err
		b.mu.Unlock()
		return err
	}

	b.mu.Lock()
	b.inner = next
	b.healthy = true
	b.lastErr = nil
	b.mu.Unlock()
	return nil
}

func (b *BackendBox) silenceFrame() []float32 {
	// Cleared once during construction; nothing writes to it, but
	// callers might mutate, so reset before handing out. Cheap loop —
	// 2*samplesPerFrame floats.
	for i := range b.silence {
		b.silence[i] = 0
	}
	return b.silence
}

var _ backend.Backend = (*BackendBox)(nil)
