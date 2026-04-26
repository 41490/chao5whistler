// Package observe is the soak/long-run telemetry sink for #37.
//
// Recorder writes one JSON object per Sample() call. Each object is
// newline-delimited so the output is jq-friendly and trivially appendable
// across restarts. The intended consumer is cmd/soak-analyze, but
// nothing in this package depends on that tool — it's the same shape any
// log-aggregator would happily ingest.
package observe

import (
	"context"
	"encoding/json"
	"io"
	"os"
	"path/filepath"
	"runtime"
	"sync"
	"time"
)

// Sample is one observation snapshot.
type Sample struct {
	Time            time.Time `json:"time"`
	UptimeSecs      float64   `json:"uptime_secs"`
	BackendName     string    `json:"backend"`
	BackendRestarts int64     `json:"backend_restarts"`
	BackendLastErr  string    `json:"backend_last_err,omitempty"`

	Ticks               int     `json:"ticks"`
	Accents             int     `json:"accents"`
	SectionTransitions  int     `json:"section_transitions"`
	ModeTransitions     int     `json:"mode_transitions"`
	Density             float64 `json:"density"`
	Brightness          float64 `json:"brightness"`
	Mode                string  `json:"mode"`
	Section             string  `json:"section"`

	HeapAllocBytes uint64 `json:"heap_alloc_bytes"`
	GoroutineCount int    `json:"goroutine_count"`
}

// Source is the callback Recorder uses to fill in non-runtime fields of
// a Sample at write time. Implemented by cmd/live-v2 over the
// BackendBox + gov2.Backend pair.
type Source func() Sample

// Recorder owns one output writer and one ticker; goroutine-safe.
type Recorder struct {
	w        io.Writer
	closer   io.Closer
	source   Source
	interval time.Duration
	start    time.Time
	mu       sync.Mutex
	stopped  bool
}

// New creates a Recorder writing newline-delimited JSON to outPath.
// Pass an empty path to write to stderr (useful in unit tests).
func New(outPath string, interval time.Duration, source Source) (*Recorder, error) {
	r := &Recorder{
		source:   source,
		interval: interval,
		start:    time.Now(),
	}
	if outPath == "" {
		r.w = os.Stderr
		return r, nil
	}
	if err := os.MkdirAll(filepath.Dir(outPath), 0755); err != nil {
		return nil, err
	}
	f, err := os.OpenFile(outPath, os.O_CREATE|os.O_WRONLY|os.O_APPEND, 0644)
	if err != nil {
		return nil, err
	}
	r.w = f
	r.closer = f
	return r, nil
}

// Run blocks until ctx is cancelled, emitting one Sample per interval.
func (r *Recorder) Run(ctx context.Context) {
	t := time.NewTicker(r.interval)
	defer t.Stop()
	for {
		select {
		case <-ctx.Done():
			return
		case <-t.C:
			_ = r.Tick()
		}
	}
}

// Tick emits one Sample synchronously.
func (r *Recorder) Tick() error {
	r.mu.Lock()
	defer r.mu.Unlock()
	if r.stopped {
		return nil
	}
	s := r.source()
	s.Time = time.Now()
	s.UptimeSecs = time.Since(r.start).Seconds()
	var ms runtime.MemStats
	runtime.ReadMemStats(&ms)
	s.HeapAllocBytes = ms.HeapAlloc
	s.GoroutineCount = runtime.NumGoroutine()
	enc := json.NewEncoder(r.w)
	return enc.Encode(s)
}

// Close flushes and closes the underlying writer (if owned by the
// Recorder) and stops further Tick output.
func (r *Recorder) Close() error {
	r.mu.Lock()
	defer r.mu.Unlock()
	r.stopped = true
	if r.closer != nil {
		return r.closer.Close()
	}
	return nil
}
