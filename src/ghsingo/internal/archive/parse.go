package archive

import (
	"bufio"
	"compress/gzip"
	"encoding/json"
	"fmt"
	"io"
	"sort"
	"time"
)

// EventTypeID maps GH Archive event type strings to compact numeric IDs.
// Duplicated from config package to avoid circular dependency.
var EventTypeID = map[string]uint8{
	"PushEvent":        0,
	"CreateEvent":      1,
	"IssuesEvent":      2,
	"PullRequestEvent": 3,
	"ForkEvent":        4,
	"ReleaseEvent":     5,
}

// ParsedEvent is the intermediate representation of a single GH Archive event.
type ParsedEvent struct {
	Second     int
	EventType  string
	BaseWeight int
	Repo       string
	Actor      string
	Text       string
	ID         string
}

// ghArchiveEvent is the minimal JSON shape we care about from GH Archive.
type ghArchiveEvent struct {
	ID        string `json:"id"`
	Type      string `json:"type"`
	Actor     struct {
		Login string `json:"login"`
	} `json:"actor"`
	Repo struct {
		Name string `json:"name"`
	} `json:"repo"`
	CreatedAt string `json:"created_at"`
}

// ParseGzipEvents reads gzip-compressed JSON lines from r, filtering by
// allowedTypes. weights maps event type to base weight value.
func ParseGzipEvents(r io.Reader, allowedTypes map[string]bool, weights map[string]int) ([]ParsedEvent, error) {
	gz, err := gzip.NewReader(r)
	if err != nil {
		return nil, fmt.Errorf("gzip open: %w", err)
	}
	defer gz.Close()

	var events []ParsedEvent
	scanner := bufio.NewScanner(gz)
	// GH Archive lines can be large; raise buffer limit.
	scanner.Buffer(make([]byte, 0, 512*1024), 2*1024*1024)

	for scanner.Scan() {
		var raw ghArchiveEvent
		if err := json.Unmarshal(scanner.Bytes(), &raw); err != nil {
			// Skip malformed lines rather than aborting the whole file.
			continue
		}
		if !allowedTypes[raw.Type] {
			continue
		}

		sec, err := secondOfDay(raw.CreatedAt)
		if err != nil {
			continue
		}

		w := weights[raw.Type]

		// Build a short text label: "actor/repo"
		text := raw.Actor.Login
		if raw.Repo.Name != "" {
			text = raw.Repo.Name
		}
		text = truncateUTF8(text, MaxTextLen)

		events = append(events, ParsedEvent{
			Second:     sec,
			EventType:  raw.Type,
			BaseWeight: w,
			Repo:       raw.Repo.Name,
			Actor:      raw.Actor.Login,
			Text:       text,
			ID:         raw.ID,
		})
	}
	if err := scanner.Err(); err != nil {
		return nil, fmt.Errorf("scan: %w", err)
	}
	return events, nil
}

// BucketAndSelect distributes parsed events into 86400 second-slots,
// deduplicates the same repo within dedupeWindowSecs, keeps up to maxPerSec
// per slot (highest weight first), and normalises weights to 0-255.
func BucketAndSelect(events []ParsedEvent, maxPerSec int, dedupeWindowSecs int) []Tick {
	// Sort by second ascending, then by weight descending.
	sort.Slice(events, func(i, j int) bool {
		if events[i].Second != events[j].Second {
			return events[i].Second < events[j].Second
		}
		return events[i].BaseWeight > events[j].BaseWeight
	})

	// Bucket into slots.
	type bucket struct {
		events []ParsedEvent
	}
	buckets := make([][]ParsedEvent, TotalTicks)
	for i := range events {
		s := events[i].Second
		if s < 0 || s >= TotalTicks {
			continue
		}
		buckets[s] = append(buckets[s], events[i])
	}

	// Track last-seen second for each repo to enforce dedup window.
	repoLastSeen := make(map[string]int)

	// Find global max weight for normalisation.
	globalMax := 1
	for _, ev := range events {
		if ev.BaseWeight > globalMax {
			globalMax = ev.BaseWeight
		}
	}

	ticks := make([]Tick, TotalTicks)
	for sec := 0; sec < TotalTicks; sec++ {
		selected := make([]Event, 0, maxPerSec)
		for _, ev := range buckets[sec] {
			if len(selected) >= maxPerSec {
				break
			}
			// Dedup: skip if same repo appeared within window.
			if last, ok := repoLastSeen[ev.Repo]; ok {
				if sec-last < dedupeWindowSecs {
					continue
				}
			}
			repoLastSeen[ev.Repo] = sec

			tid, ok := EventTypeID[ev.EventType]
			if !ok {
				continue
			}

			// Normalise weight to 0-255.
			norm := uint8(ev.BaseWeight * 255 / globalMax)

			selected = append(selected, Event{
				TypeID: tid,
				Weight: norm,
				Text:   truncateUTF8(ev.Text, MaxTextLen),
			})
		}
		ticks[sec].Events = selected
	}
	return ticks
}

// secondOfDay parses an ISO-8601 timestamp and returns the second-of-day in UTC.
func secondOfDay(ts string) (int, error) {
	t, err := time.Parse(time.RFC3339, ts)
	if err != nil {
		// Try alternate format used by some GH Archive dumps.
		t, err = time.Parse("2006-01-02T15:04:05", ts)
		if err != nil {
			return 0, fmt.Errorf("parse time %q: %w", ts, err)
		}
	}
	t = t.UTC()
	return t.Hour()*3600 + t.Minute()*60 + t.Second(), nil
}
