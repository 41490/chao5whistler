package archive

import (
	"bytes"
	"compress/gzip"
	"encoding/json"
	"testing"
)

// makeGzipJSON compresses a slice of JSON objects into gzip newline-delimited bytes.
func makeGzipJSON(t *testing.T, records []map[string]any) *bytes.Buffer {
	t.Helper()
	var buf bytes.Buffer
	gz := gzip.NewWriter(&buf)
	for _, rec := range records {
		b, err := json.Marshal(rec)
		if err != nil {
			t.Fatalf("marshal: %v", err)
		}
		gz.Write(b)
		gz.Write([]byte("\n"))
	}
	if err := gz.Close(); err != nil {
		t.Fatalf("gzip close: %v", err)
	}
	return &buf
}

func TestParseGzipEvents(t *testing.T) {
	records := []map[string]any{
		{"id": "1", "type": "PushEvent", "actor": map[string]any{"login": "alice"}, "repo": map[string]any{"name": "alice/foo"}, "created_at": "2026-03-29T01:00:00Z"},
		{"id": "2", "type": "PushEvent", "actor": map[string]any{"login": "bob"}, "repo": map[string]any{"name": "bob/bar"}, "created_at": "2026-03-29T02:30:00Z"},
		{"id": "3", "type": "WatchEvent", "actor": map[string]any{"login": "carol"}, "repo": map[string]any{"name": "carol/baz"}, "created_at": "2026-03-29T03:00:00Z"},
		{"id": "4", "type": "ReleaseEvent", "actor": map[string]any{"login": "dave"}, "repo": map[string]any{"name": "dave/qux"}, "created_at": "2026-03-29T12:00:00Z"},
	}

	buf := makeGzipJSON(t, records)

	allowed := map[string]bool{
		"PushEvent":    true,
		"ReleaseEvent": true,
	}
	weights := map[string]int{
		"PushEvent":    10,
		"ReleaseEvent": 50,
	}

	events, err := ParseGzipEvents(buf, allowed, weights)
	if err != nil {
		t.Fatalf("ParseGzipEvents: %v", err)
	}

	// WatchEvent should be filtered out -> 3 allowed, but only 2 PushEvent + 1 ReleaseEvent = 3.
	if len(events) != 3 {
		t.Fatalf("got %d events, want 3", len(events))
	}

	// Check that no WatchEvent made it through.
	for _, ev := range events {
		if ev.EventType == "WatchEvent" {
			t.Error("WatchEvent should have been filtered out")
		}
	}

	// Find the ReleaseEvent and verify its weight.
	var found bool
	for _, ev := range events {
		if ev.EventType == "ReleaseEvent" {
			found = true
			if ev.BaseWeight != 50 {
				t.Errorf("ReleaseEvent weight: got %d, want 50", ev.BaseWeight)
			}
			// 12:00:00 UTC = 43200 seconds.
			if ev.Second != 43200 {
				t.Errorf("ReleaseEvent second: got %d, want 43200", ev.Second)
			}
		}
	}
	if !found {
		t.Error("ReleaseEvent not found in results")
	}
}

func TestBucketAndSelectTopN(t *testing.T) {
	// 5 events all in the same second (second 100).
	events := []ParsedEvent{
		{Second: 100, EventType: "PushEvent", BaseWeight: 10, Repo: "a/1", Actor: "u1", Text: "a/1", ID: "1"},
		{Second: 100, EventType: "PushEvent", BaseWeight: 50, Repo: "b/2", Actor: "u2", Text: "b/2", ID: "2"},
		{Second: 100, EventType: "CreateEvent", BaseWeight: 30, Repo: "c/3", Actor: "u3", Text: "c/3", ID: "3"},
		{Second: 100, EventType: "IssuesEvent", BaseWeight: 20, Repo: "d/4", Actor: "u4", Text: "d/4", ID: "4"},
		{Second: 100, EventType: "ForkEvent", BaseWeight: 40, Repo: "e/5", Actor: "u5", Text: "e/5", ID: "5"},
	}

	ticks := BucketAndSelect(events, 4, 0)

	if len(ticks) != TotalTicks {
		t.Fatalf("ticks length: got %d, want %d", len(ticks), TotalTicks)
	}

	selected := ticks[100].Events
	if len(selected) != 4 {
		t.Fatalf("tick[100] events: got %d, want 4", len(selected))
	}

	// Should be sorted by weight descending: 50, 40, 30, 20 -> the event with weight 10 is dropped.
	// After normalisation to 0-255: 50*255/50=255, 40*255/50=204, 30*255/50=153, 20*255/50=102
	expectedWeights := []uint8{255, 204, 153, 102}
	for i, want := range expectedWeights {
		if selected[i].Weight != want {
			t.Errorf("event[%d] weight: got %d, want %d", i, selected[i].Weight, want)
		}
	}
}
