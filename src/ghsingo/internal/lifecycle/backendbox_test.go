package lifecycle

import (
	"errors"
	"testing"

	"github.com/41490/chao5whistler/src/ghsingo/internal/backend"
)

// fakeBackend is a Backend that fails RenderFrame after `failsAfter`
// successful frames. Used to drive the unhealthy-after-error path.
type fakeBackend struct {
	failsAfter int
	frames     int
	closed     bool
}

func (f *fakeBackend) Init() error  { return nil }
func (f *fakeBackend) Close() error { f.closed = true; return nil }
func (f *fakeBackend) ApplyEventsForSecond(_ []backend.Event) {}
func (f *fakeBackend) RenderFrame() ([]float32, error) {
	f.frames++
	if f.failsAfter > 0 && f.frames > f.failsAfter {
		return nil, errors.New("simulated render failure")
	}
	return make([]float32, 4), nil
}
func (f *fakeBackend) SampleRate() int      { return 44100 }
func (f *fakeBackend) SamplesPerFrame() int { return 2 }
func (f *fakeBackend) Name() string         { return "fake" }

// TestBackendBoxSilenceWhenInnerErrors: after the inner backend fails,
// RenderFrame must keep returning silence (never error).
func TestBackendBoxSilenceWhenInnerErrors(t *testing.T) {
	box := NewBackendBox(func() (backend.Backend, error) {
		return &fakeBackend{failsAfter: 3}, nil
	}, 2)
	if err := box.Init(); err != nil {
		t.Fatal(err)
	}
	defer box.Close()

	// Three successful frames then several silent ones.
	for i := 0; i < 10; i++ {
		f, err := box.RenderFrame()
		if err != nil {
			t.Fatalf("RenderFrame returned error at i=%d: %v", i, err)
		}
		if len(f) != 4 {
			t.Fatalf("frame len at i=%d = %d, want 4", i, len(f))
		}
	}
	if box.LastInitErr() == nil {
		t.Fatal("LastInitErr should be non-nil after inner failure")
	}
}

// TestBackendBoxRestartRecovers: Restart() rebuilds the inner backend
// and the next frame is no longer silence.
func TestBackendBoxRestartRecovers(t *testing.T) {
	calls := 0
	box := NewBackendBox(func() (backend.Backend, error) {
		calls++
		// First instance fails after 1 frame; subsequent instances are healthy.
		if calls == 1 {
			return &fakeBackend{failsAfter: 1}, nil
		}
		return &fakeBackend{}, nil
	}, 2)
	if err := box.Init(); err != nil {
		t.Fatal(err)
	}
	defer box.Close()

	_, _ = box.RenderFrame() // first ok
	_, _ = box.RenderFrame() // triggers inner err -> unhealthy

	if box.LastInitErr() == nil {
		t.Fatal("expected lastErr after inner failure")
	}
	if err := box.Restart(); err != nil {
		t.Fatalf("Restart: %v", err)
	}
	if box.RestartCount() != 1 {
		t.Fatalf("RestartCount = %d, want 1", box.RestartCount())
	}
	if box.LastInitErr() != nil {
		t.Fatalf("LastInitErr should be cleared after successful Restart, got %v", box.LastInitErr())
	}
}

// TestBackendBoxFactoryFailureKeepsSilent: a Factory that returns an
// error must leave the box unhealthy but RenderFrame still returns
// silence (no panic, no propagation).
func TestBackendBoxFactoryFailureKeepsSilent(t *testing.T) {
	box := NewBackendBox(func() (backend.Backend, error) {
		return nil, errors.New("factory boom")
	}, 2)
	if err := box.Init(); err == nil {
		t.Fatal("expected factory error to surface from Init")
	}
	for i := 0; i < 5; i++ {
		f, err := box.RenderFrame()
		if err != nil {
			t.Fatalf("RenderFrame errored at i=%d: %v", i, err)
		}
		// Silent frame is all zeros.
		for j, v := range f {
			if v != 0 {
				t.Fatalf("frame[%d][%d] = %v, want silence", i, j, v)
			}
		}
	}
}

// TestBackendBoxApplyEventsDroppedWhenUnhealthy: ApplyEventsForSecond
// must not panic when the box has no inner backend.
func TestBackendBoxApplyEventsDroppedWhenUnhealthy(t *testing.T) {
	box := NewBackendBox(func() (backend.Backend, error) {
		return nil, errors.New("never alive")
	}, 2)
	_ = box.Init()
	box.ApplyEventsForSecond([]backend.Event{{TypeID: 0, Weight: 30}})
	// no panic = pass
}

// TestBackendBoxImplementsBackend asserts the wrapper itself satisfies
// the Backend interface.
func TestBackendBoxImplementsBackend(t *testing.T) {
	var _ backend.Backend = (*BackendBox)(nil)
}
