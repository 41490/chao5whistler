// composer-demo: Drive the v1 state-vector composer (#30) against a
// daypack and emit the resulting state timeline as JSON. No audio is
// rendered — this is a read-only inspection tool to let #31 (mixer v2)
// reviewers see exactly what the composer produces over a real day.
//
// Usage:
//
//	go run ./cmd/composer-demo --config ghsingo.toml --duration 5m -o /tmp/composer-timeline.json
//	jq '.summary' /tmp/composer-timeline.json
package main

import (
	"encoding/json"
	"flag"
	"fmt"
	"log/slog"
	"os"
	"path/filepath"
	"sort"
	"time"

	"github.com/41490/chao5whistler/src/ghsingo/internal/archive"
	"github.com/41490/chao5whistler/src/ghsingo/internal/composer"
	"github.com/41490/chao5whistler/src/ghsingo/internal/config"
)

type tick struct {
	Second  int             `json:"second"`
	Events  int             `json:"events"`
	Weights int             `json:"avg_weight"`
	Output  composer.Output `json:"out"`
}

type summary struct {
	Profile           string  `json:"profile"`
	DaypackDate       string  `json:"daypack_date"`
	Ticks             int     `json:"ticks"`
	TotalEvents       int     `json:"total_events"`
	TotalAccents      int     `json:"total_accents"`
	AccentsPerMinute  float64 `json:"accents_per_minute"`
	EventsPerMinute   float64 `json:"events_per_minute"`
	FinalDensity      float64 `json:"final_density"`
	FinalBrightness   float64 `json:"final_brightness"`
	SectionTransitions int    `json:"section_transitions"`
	ModeTransitions   int     `json:"mode_transitions"`
}

type timeline struct {
	Summary summary `json:"summary"`
	Ticks   []tick  `json:"ticks"`
}

func main() {
	configPath := flag.String("config", "ghsingo.toml", "path to config file")
	outPath := flag.String("o", "/tmp/composer-timeline.json", "output JSON path")
	durationStr := flag.String("duration", "5m", "drive duration")
	seedFlag := flag.Int64("seed", 0, "composer rng seed (0 = time.Now)")
	flag.Parse()

	dur, err := time.ParseDuration(*durationStr)
	if err != nil {
		slog.Error("invalid duration", "err", err)
		os.Exit(1)
	}

	cfg, err := config.Load(*configPath)
	if err != nil {
		slog.Error("load config", "err", err)
		os.Exit(1)
	}

	daypackPath, dateStr, err := findLatestDaypack(cfg.Archive.DaypackDir)
	if err != nil {
		slog.Error("find daypack", "err", err)
		os.Exit(1)
	}
	pack, err := archive.ReadDaypack(daypackPath)
	if err != nil {
		slog.Error("read daypack", "err", err)
		os.Exit(1)
	}

	c := composer.New(composer.Config{Seed: *seedFlag})

	totalTicks := int(dur.Seconds())
	tl := timeline{
		Summary: summary{Profile: cfg.Meta.Profile, DaypackDate: dateStr, Ticks: totalTicks},
		Ticks:   make([]tick, 0, totalTicks),
	}

	prevSection := composer.SectionRest
	prevMode := composer.ModeYo
	for i := 0; i < totalTicks; i++ {
		idx := i % len(pack.Ticks)
		evs := pack.Ticks[idx].Events
		composerEvs := make([]composer.Event, len(evs))
		var sumW int
		for j, e := range evs {
			composerEvs[j] = composer.Event{TypeID: e.TypeID, Weight: e.Weight}
			sumW += int(e.Weight)
		}
		out := c.Tick(composerEvs)
		avgW := 0
		if len(evs) > 0 {
			avgW = sumW / len(evs)
		}
		tl.Ticks = append(tl.Ticks, tick{
			Second:  i,
			Events:  len(evs),
			Weights: avgW,
			Output:  out,
		})
		tl.Summary.TotalEvents += len(evs)
		tl.Summary.TotalAccents += len(out.Accents)
		if out.State.Section != prevSection {
			tl.Summary.SectionTransitions++
			prevSection = out.State.Section
		}
		if out.State.Mode != prevMode {
			tl.Summary.ModeTransitions++
			prevMode = out.State.Mode
		}
	}
	if totalTicks > 0 {
		tl.Summary.FinalDensity = tl.Ticks[len(tl.Ticks)-1].Output.State.Density
		tl.Summary.FinalBrightness = tl.Ticks[len(tl.Ticks)-1].Output.State.Brightness
		mins := dur.Minutes()
		tl.Summary.AccentsPerMinute = float64(tl.Summary.TotalAccents) / mins
		tl.Summary.EventsPerMinute = float64(tl.Summary.TotalEvents) / mins
	}

	if err := os.MkdirAll(filepath.Dir(*outPath), 0755); err != nil {
		slog.Error("mkdir", "err", err)
		os.Exit(1)
	}
	buf, err := json.MarshalIndent(tl, "", "  ")
	if err != nil {
		slog.Error("marshal", "err", err)
		os.Exit(1)
	}
	if err := os.WriteFile(*outPath, append(buf, '\n'), 0644); err != nil {
		slog.Error("write", "err", err)
		os.Exit(1)
	}
	slog.Info("composer timeline",
		"out", *outPath,
		"ticks", tl.Summary.Ticks,
		"events", tl.Summary.TotalEvents,
		"accents", tl.Summary.TotalAccents,
		"events_per_min", fmt.Sprintf("%.1f", tl.Summary.EventsPerMinute),
		"accents_per_min", fmt.Sprintf("%.1f", tl.Summary.AccentsPerMinute),
		"final_density", fmt.Sprintf("%.3f", tl.Summary.FinalDensity),
		"final_brightness", fmt.Sprintf("%.3f", tl.Summary.FinalBrightness),
		"section_transitions", tl.Summary.SectionTransitions,
		"mode_transitions", tl.Summary.ModeTransitions,
	)
}

func findLatestDaypack(daypackDir string) (binPath, dateStr string, err error) {
	entries, err := os.ReadDir(daypackDir)
	if err != nil {
		return "", "", fmt.Errorf("read daypack dir %q: %w", daypackDir, err)
	}
	var dirs []string
	for _, e := range entries {
		if !e.IsDir() {
			continue
		}
		p := filepath.Join(daypackDir, e.Name(), "day.bin")
		if _, serr := os.Stat(p); serr == nil {
			dirs = append(dirs, e.Name())
		}
	}
	if len(dirs) == 0 {
		return "", "", fmt.Errorf("no daypack found in %q", daypackDir)
	}
	sort.Strings(dirs)
	latest := dirs[len(dirs)-1]
	return filepath.Join(daypackDir, latest, "day.bin"), latest, nil
}
