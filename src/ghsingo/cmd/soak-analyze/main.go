// soak-analyze: read an observe.Recorder NDJSON metrics file and decide
// whether the soak run passes the #37 acceptance criteria.
//
// Pass criteria (default; tune via flags as the v2 mainline matures):
//   - run length >= --min-uptime
//   - backend_restarts per hour <= --max-restarts-per-hour
//   - heap_alloc_bytes growth <= --max-heap-growth-mb (between min and max sample)
//   - density never stuck at 0 for >= --max-zero-density-secs (proves
//     events keep flowing and composer keeps moving)
//   - at least one section_transition (composer wasn't deadlocked)
//
// Usage:
//
//	soak-analyze --in /var/log/ghsingo/soak.ndjson [--min-uptime 24h] [...]
package main

import (
	"bufio"
	"encoding/json"
	"flag"
	"fmt"
	"os"
	"time"
)

type sample struct {
	Time               time.Time `json:"time"`
	UptimeSecs         float64   `json:"uptime_secs"`
	BackendRestarts    int64     `json:"backend_restarts"`
	HeapAllocBytes     uint64    `json:"heap_alloc_bytes"`
	GoroutineCount     int       `json:"goroutine_count"`
	Density            float64   `json:"density"`
	SectionTransitions int       `json:"section_transitions"`
}

func main() {
	in := flag.String("in", "", "NDJSON metrics file from observe.Recorder")
	minUptime := flag.Duration("min-uptime", 0, "fail if last sample's uptime < this (0 disables)")
	maxRestartsPerHour := flag.Float64("max-restarts-per-hour", 1.0, "fail if backend_restarts/h exceeds this")
	maxHeapGrowthMB := flag.Float64("max-heap-growth-mb", 256.0, "fail if heap_alloc grows by more than this MiB across the run")
	maxZeroDensityWindowSecs := flag.Float64("max-zero-density-secs", 600.0, "fail if Density stays exactly 0 for more than this many seconds in a row")
	flag.Parse()

	if *in == "" {
		fmt.Fprintln(os.Stderr, "soak-analyze: --in required")
		os.Exit(2)
	}

	f, err := os.Open(*in)
	if err != nil {
		fmt.Fprintf(os.Stderr, "soak-analyze: open %s: %v\n", *in, err)
		os.Exit(1)
	}
	defer f.Close()

	scan := bufio.NewScanner(f)
	scan.Buffer(make([]byte, 1<<20), 1<<20)
	var samples []sample
	for scan.Scan() {
		var s sample
		if err := json.Unmarshal(scan.Bytes(), &s); err != nil {
			fmt.Fprintf(os.Stderr, "soak-analyze: invalid line: %v\n", err)
			os.Exit(1)
		}
		samples = append(samples, s)
	}
	if err := scan.Err(); err != nil {
		fmt.Fprintf(os.Stderr, "soak-analyze: scan: %v\n", err)
		os.Exit(1)
	}
	if len(samples) == 0 {
		fmt.Fprintln(os.Stderr, "soak-analyze: empty file")
		os.Exit(1)
	}

	first := samples[0]
	last := samples[len(samples)-1]

	fmt.Printf("samples: %d\n", len(samples))
	fmt.Printf("uptime:  %.1fs\n", last.UptimeSecs)
	fmt.Printf("restarts: %d (%.2f/h)\n", last.BackendRestarts, restartsPerHour(last))
	fmt.Printf("heap:    %.1f MiB -> %.1f MiB (%+.1f)\n",
		mb(first.HeapAllocBytes), mb(last.HeapAllocBytes),
		mb(last.HeapAllocBytes)-mb(first.HeapAllocBytes))
	fmt.Printf("density: stuck-at-0 max window %.0fs\n", maxZeroDensityWindow(samples))
	fmt.Printf("section_transitions: %d\n", last.SectionTransitions)

	fail := 0
	if *minUptime > 0 && time.Duration(last.UptimeSecs*float64(time.Second)) < *minUptime {
		fmt.Printf("FAIL uptime %.1fs < %s\n", last.UptimeSecs, *minUptime)
		fail++
	}
	if rph := restartsPerHour(last); rph > *maxRestartsPerHour {
		fmt.Printf("FAIL restarts/h %.2f > %.2f\n", rph, *maxRestartsPerHour)
		fail++
	}
	growth := mb(last.HeapAllocBytes) - mb(first.HeapAllocBytes)
	if growth > *maxHeapGrowthMB {
		fmt.Printf("FAIL heap grew %.1f MiB > %.1f MiB cap\n", growth, *maxHeapGrowthMB)
		fail++
	}
	if w := maxZeroDensityWindow(samples); w > *maxZeroDensityWindowSecs {
		fmt.Printf("FAIL density stuck at 0 for %.0fs > %.0fs cap\n", w, *maxZeroDensityWindowSecs)
		fail++
	}
	if last.SectionTransitions == 0 {
		fmt.Println("FAIL section_transitions = 0 (composer phrase scheduler wedged)")
		fail++
	}
	if fail > 0 {
		fmt.Printf("RESULT: FAIL (%d criterion(s))\n", fail)
		os.Exit(1)
	}
	fmt.Println("RESULT: PASS")
}

func mb(b uint64) float64 { return float64(b) / 1024 / 1024 }

func restartsPerHour(s sample) float64 {
	if s.UptimeSecs <= 0 {
		return 0
	}
	return float64(s.BackendRestarts) * 3600 / s.UptimeSecs
}

func maxZeroDensityWindow(samples []sample) float64 {
	var max, runStart float64
	inRun := false
	for _, s := range samples {
		if s.Density == 0 {
			if !inRun {
				runStart = s.UptimeSecs
				inRun = true
			}
			if w := s.UptimeSecs - runStart; w > max {
				max = w
			}
		} else {
			inRun = false
		}
	}
	return max
}
