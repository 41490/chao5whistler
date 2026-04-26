// audio-metrics: Run ffmpeg's loudnorm filter against a rendered audio file
// to extract LUFS / LRA / true-peak, merge with the trigger-level sidecar
// written by render-audio, and emit one combined metrics JSON.
//
// Usage:
//
//	audio-metrics --audio out.m4a [--sidecar out.m4a.metrics.json] [--out report.json]
//
// Designed for #29 (freeze bell-era baseline + audio metrics report). The
// output is intentionally small and stable so future #28 child issues can
// diff their renders against the bell-era baseline without re-deriving the
// schema.
package main

import (
	"bytes"
	"encoding/json"
	"flag"
	"fmt"
	"os"
	"os/exec"
	"strconv"
)

type loudnormRaw struct {
	InputI      string `json:"input_i"`
	InputTP     string `json:"input_tp"`
	InputLRA    string `json:"input_lra"`
	InputThresh string `json:"input_thresh"`
}

type loudness struct {
	IntegratedLUFS float64 `json:"integrated_lufs"`
	LRA            float64 `json:"lra"`
	TruePeakDBTP   float64 `json:"true_peak_dbtp"`
	ThresholdLUFS  float64 `json:"threshold_lufs"`
}

type sidecar struct {
	Profile             string  `json:"profile"`
	Legacy              bool    `json:"legacy"`
	Config              string  `json:"config"`
	DaypackDate         string  `json:"daypack_date"`
	DurationSecs        float64 `json:"duration_secs"`
	SampleRate          int     `json:"sample_rate"`
	Ticks               int     `json:"ticks"`
	LeadStrikes         int     `json:"lead_strikes"`
	BackgroundStrikes   int     `json:"background_strikes"`
	ReleaseAccents      int     `json:"release_accents"`
	EffStrikeRatePerSec float64 `json:"effective_strike_rate_per_sec"`
	ReleaseAccentRate   float64 `json:"release_accent_rate_per_sec"`
}

type combined struct {
	Audio    string   `json:"audio"`
	Loudness loudness `json:"loudness"`
	Sidecar  sidecar  `json:"sidecar,omitempty"`
}

func main() {
	audio := flag.String("audio", "", "rendered audio file (wav/m4a/mp3)")
	sidePath := flag.String("sidecar", "", "optional render-audio sidecar JSON; default <audio>.metrics.json")
	outPath := flag.String("out", "", "output combined JSON; default <audio>.report.json")
	flag.Parse()

	if *audio == "" {
		fmt.Fprintln(os.Stderr, "audio-metrics: --audio is required")
		os.Exit(2)
	}
	if *sidePath == "" {
		*sidePath = *audio + ".metrics.json"
	}
	if *outPath == "" {
		*outPath = *audio + ".report.json"
	}

	loud, err := analyzeLoudness(*audio)
	if err != nil {
		fmt.Fprintf(os.Stderr, "audio-metrics: loudness analysis failed: %v\n", err)
		os.Exit(1)
	}

	report := combined{Audio: *audio, Loudness: loud}
	if data, err := os.ReadFile(*sidePath); err == nil {
		if err := json.Unmarshal(data, &report.Sidecar); err != nil {
			fmt.Fprintf(os.Stderr, "audio-metrics: sidecar %s parse failed: %v\n", *sidePath, err)
			os.Exit(1)
		}
	}

	out, err := json.MarshalIndent(report, "", "  ")
	if err != nil {
		fmt.Fprintf(os.Stderr, "audio-metrics: marshal: %v\n", err)
		os.Exit(1)
	}
	if err := os.WriteFile(*outPath, append(out, '\n'), 0644); err != nil {
		fmt.Fprintf(os.Stderr, "audio-metrics: write %s: %v\n", *outPath, err)
		os.Exit(1)
	}
	fmt.Println(*outPath)
}

func analyzeLoudness(audio string) (loudness, error) {
	cmd := exec.Command(
		"ffmpeg",
		"-hide_banner",
		"-nostats",
		"-i", audio,
		"-af", "loudnorm=I=-16:TP=-1.5:LRA=11:print_format=json",
		"-f", "null", "-",
	)
	var stderr bytes.Buffer
	cmd.Stderr = &stderr
	if err := cmd.Run(); err != nil {
		return loudness{}, fmt.Errorf("ffmpeg: %w: %s", err, tail(stderr.String(), 400))
	}
	return parseLoudnorm(stderr.Bytes())
}

func parseLoudnorm(stderr []byte) (loudness, error) {
	start := bytes.LastIndex(stderr, []byte("{"))
	end := bytes.LastIndex(stderr, []byte("}"))
	if start == -1 || end == -1 || end < start {
		return loudness{}, fmt.Errorf("no loudnorm JSON block in ffmpeg stderr")
	}
	var raw loudnormRaw
	if err := json.Unmarshal(stderr[start:end+1], &raw); err != nil {
		return loudness{}, fmt.Errorf("parse loudnorm JSON: %w", err)
	}
	out := loudness{}
	for _, p := range []struct {
		dst *float64
		s   string
	}{
		{&out.IntegratedLUFS, raw.InputI},
		{&out.LRA, raw.InputLRA},
		{&out.TruePeakDBTP, raw.InputTP},
		{&out.ThresholdLUFS, raw.InputThresh},
	} {
		if p.s == "" {
			continue
		}
		v, err := strconv.ParseFloat(p.s, 64)
		if err != nil {
			return loudness{}, fmt.Errorf("parse %q: %w", p.s, err)
		}
		*p.dst = v
	}
	return out, nil
}

func tail(s string, n int) string {
	if len(s) <= n {
		return s
	}
	return "..." + s[len(s)-n:]
}
