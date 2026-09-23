package observe

import (
	"bytes"
	"context"
	"encoding/json"
	"strings"
	"sync/atomic"
	"testing"
	"time"
)

func TestRecorderTickWritesNDJSON(t *testing.T) {
	var buf bytes.Buffer
	r := &Recorder{
		w:        &buf,
		interval: 50 * time.Millisecond,
		start:    time.Now(),
		source: func() Sample {
			return Sample{BackendName: "fake", Density: 0.5}
		},
	}
	if err := r.Tick(); err != nil {
		t.Fatal(err)
	}
	if err := r.Tick(); err != nil {
		t.Fatal(err)
	}

	lines := strings.Split(strings.TrimSpace(buf.String()), "\n")
	if len(lines) != 2 {
		t.Fatalf("got %d lines, want 2: %q", len(lines), buf.String())
	}
	for _, ln := range lines {
		var s Sample
		if err := json.Unmarshal([]byte(ln), &s); err != nil {
			t.Fatalf("invalid JSON line %q: %v", ln, err)
		}
		if s.BackendName != "fake" {
			t.Errorf("BackendName = %q, want fake", s.BackendName)
		}
		if s.HeapAllocBytes == 0 {
			t.Error("HeapAllocBytes should be populated by ReadMemStats")
		}
	}
}

func TestRecorderRunStopsOnContext(t *testing.T) {
	var buf bytes.Buffer
	var calls atomic.Int64
	r := &Recorder{
		w:        &buf,
		interval: 5 * time.Millisecond,
		start:    time.Now(),
		source: func() Sample {
			calls.Add(1)
			return Sample{BackendName: "fake"}
		},
	}
	ctx, cancel := context.WithTimeout(context.Background(), 30*time.Millisecond)
	defer cancel()
	r.Run(ctx)
	// At 5ms ticks and 30ms timeout we expect roughly 4-6 ticks; tolerate jitter.
	if got := calls.Load(); got < 2 {
		t.Fatalf("only %d ticks emitted in 30ms; ticker not running", got)
	}
}
