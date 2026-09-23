package main

import (
	"encoding/json"
	"flag"
	"fmt"
	"log/slog"
	"os"
	"path/filepath"
	"strings"
	"time"

	"github.com/41490/chao5whistler/src/ghsingo/internal/archive"
	"github.com/41490/chao5whistler/src/ghsingo/internal/config"
)

func main() {
	configPath := flag.String("config", "ghsingo.toml", "path to config file")
	hoursSpec := flag.String("hours", "", "comma-separated UTC hours or ranges to prepare, e.g. 16 or 12-17")
	flag.Parse()

	cfg, err := config.Load(*configPath)
	if err != nil {
		slog.Error("load config", "err", err)
		os.Exit(1)
	}

	slog.Info("prepare starting", "profile", cfg.Meta.Profile, "target_date", cfg.Archive.TargetDate, "hours", *hoursSpec)

	targetDate := config.ResolveTargetDate(cfg.Archive.TargetDate)
	hours, err := parseHours(*hoursSpec)
	if err != nil {
		slog.Error("parse hours", "spec", *hoursSpec, "err", err)
		os.Exit(2)
	}

	allowedTypes := make(map[string]bool)
	for _, t := range cfg.Events.Types {
		allowedTypes[t] = true
	}

	if cfg.Archive.Download.Enabled {
		err := archive.DownloadMissingHours(archive.DownloadOptions{
			BaseURL:     cfg.Archive.Download.BaseURL,
			TargetDate:  targetDate,
			SourceDir:   cfg.Archive.SourceDir,
			Hours:       hours,
			Timeout:     time.Duration(cfg.Archive.Download.TimeoutSecs) * time.Second,
			MaxParallel: cfg.Archive.Download.MaxParallel,
			UserAgent:   cfg.Archive.Download.UserAgent,
		})
		if err != nil {
			slog.Error("download inputs", "err", err, "date", targetDate)
			os.Exit(1)
		}
	}

	requireAll := cfg.Archive.Download.Enabled || strings.TrimSpace(*hoursSpec) != ""

	// Find source .json.gz files: {source_dir}/{date}-{H}.json.gz
	var gzFiles []string
	missingHours := make([]int, 0)
	availableHours := make([]int, 0, len(hours))
	for _, h := range hours {
		path := archive.HourFilePath(cfg.Archive.SourceDir, targetDate, h)
		if _, err := os.Stat(path); err == nil {
			gzFiles = append(gzFiles, path)
			availableHours = append(availableHours, h)
		} else if os.IsNotExist(err) {
			missingHours = append(missingHours, h)
		} else {
			slog.Error("stat source file", "path", path, "err", err)
			os.Exit(1)
		}
	}
	if requireAll && len(missingHours) > 0 {
		slog.Error("missing required source files", "source_dir", cfg.Archive.SourceDir, "date", targetDate, "hours", missingHours)
		os.Exit(1)
	}
	if len(gzFiles) == 0 {
		slog.Error("no .json.gz files found", "source_dir", cfg.Archive.SourceDir, "date", targetDate, "hours", hours)
		os.Exit(1)
	}
	slog.Info("found source files", "count", len(gzFiles), "hours", availableHours)

	var allEvents []archive.ParsedEvent
	for _, path := range gzFiles {
		slog.Info("parsing", "file", filepath.Base(path))
		f, err := os.Open(path)
		if err != nil {
			slog.Error("open file", "path", path, "err", err)
			os.Exit(1)
		}
		events, err := archive.ParseGzipEvents(f, allowedTypes, cfg.Events.Weights)
		f.Close()
		if err != nil {
			slog.Error("parse file", "path", path, "err", err)
			os.Exit(1)
		}
		allEvents = append(allEvents, events...)
	}
	slog.Info("total parsed events", "count", len(allEvents))

	ticks := archive.BucketAndSelect(allEvents, cfg.Events.MaxPerSecond, cfg.Events.DedupeWindowSecs)

	// Parse date to YYYYMMDD uint32
	dateStr := strings.ReplaceAll(targetDate, "-", "")
	var dateNum uint32
	fmt.Sscanf(dateStr, "%d", &dateNum)

	pack := &archive.Daypack{
		Header: archive.Header{
			Magic:      [4]byte{'G', 'S', 'I', 'N'},
			Version:    1,
			Date:       dateNum,
			TotalTicks: archive.TotalTicks,
		},
		Ticks: ticks,
	}

	outDir := filepath.Join(cfg.Archive.DaypackDir, targetDate)
	os.MkdirAll(outDir, 0755)

	binPath := filepath.Join(outDir, "day.bin")
	if err := archive.WriteDaypack(binPath, pack); err != nil {
		slog.Error("write daypack", "err", err)
		os.Exit(1)
	}

	// Write manifest.json
	keptEvents := 0
	ticksWithEvents := 0
	byType := make(map[string]int)
	for _, tick := range ticks {
		if len(tick.Events) > 0 {
			ticksWithEvents++
		}
		keptEvents += len(tick.Events)
		for _, e := range tick.Events {
			for name, id := range archive.EventTypeID {
				if id == e.TypeID {
					byType[name]++
				}
			}
		}
	}
	manifest := map[string]any{
		"date":              targetDate,
		"requested_hours":   hours,
		"available_hours":   availableHours,
		"source_files":      gzFiles,
		"total_events":      len(allEvents),
		"kept_events":       keptEvents,
		"ticks_with_events": ticksWithEvents,
		"empty_ticks":       archive.TotalTicks - ticksWithEvents,
		"by_type":           byType,
	}
	manifestJSON, _ := json.MarshalIndent(manifest, "", "  ")
	manifestPath := filepath.Join(outDir, "manifest.json")
	os.WriteFile(manifestPath, manifestJSON, 0644)

	info, _ := os.Stat(binPath)
	slog.Info("prepare complete",
		"daypack", binPath,
		"size_mb", fmt.Sprintf("%.1f", float64(info.Size())/(1024*1024)),
		"kept_events", keptEvents,
		"ticks_with_events", ticksWithEvents,
	)
}
