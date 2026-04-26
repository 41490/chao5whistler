// migrate-config: translate a bell-era ghsingo*.toml into a v2-shape
// ghsingo*.toml on stdout (or via --out). Migration target schema is
// documented in docs/ambient/config.md (#33).
//
// This is a one-off helper, not a long-term shim. Bell-era profiles are
// frozen by #29 and will be deleted by #38; the v2 mainline owes no
// runtime backward-compat to them.
//
// Usage:
//
//	go run ./cmd/migrate-config --in ghsingo.toml             # to stdout
//	go run ./cmd/migrate-config --in ghsingo.toml --out v2.toml
package main

import (
	"flag"
	"fmt"
	"io"
	"math"
	"os"
	"text/template"

	"github.com/41490/chao5whistler/src/ghsingo/internal/config"
)

const v2Template = `# Migrated from {{.SourcePath}} by cmd/migrate-config (#33).
# Review the [composer] / [mixer] / [assets.*] blocks before shipping
# — bell-era runtime defaults rarely match the v2 ambient targets.

[meta]
profile = "{{.Profile}}-v2"
engine  = "v2"

[archive]
source_dir  = "{{.Archive.SourceDir}}"
daypack_dir = "{{.Archive.DaypackDir}}"
target_date = "{{.Archive.TargetDate}}"

[archive.download]
enabled      = {{.Archive.Download.Enabled}}
base_url     = "{{.Archive.Download.BaseURL}}"
timeout_secs = {{.Archive.Download.TimeoutSecs}}
max_parallel = {{.Archive.Download.MaxParallel}}
user_agent   = "{{.Archive.Download.UserAgent}}"

[events]
types               = {{.Events.TypesTOML}}
max_per_second      = {{.Events.MaxPerSecond}}
dedupe_window_secs  = {{.Events.DedupeWindowSecs}}

[events.weights]
{{range .Events.WeightLines}}{{.}}
{{end}}
[audio]
sample_rate    = {{.Audio.SampleRate}}
channels       = {{.Audio.Channels}}
master_gain_db = {{.Audio.MasterGainDB}}

# Composer (#30). Defaults below match composer.Config defaults; tune
# only if the source profile had unusual behavior worth preserving.
[composer]
ema_alpha             = 0.06
density_saturation    = 12.0
brightness_saturation = 80.0
phrase_ticks          = 16
accent_cooldown_ticks = 3
accent_base_prob      = 0.10
seed                  = 0

# Mixer (#31 + #32). master_gain trimmed to 0.55 keeps true-peak under
# -1.5 dBTP across the layered mix — relax only after measuring.
[mixer]
master_gain    = 0.55
drone_gain     = 1.0
bed_gain       = 1.0
tonal_bed_gain = {{.MigratedTonalBedGain}}
accent_gain    = 1.0
wet_continuous = 0.06
wet_accent     = 0.45
accent_max     = 4

[assets.tonal_bed]
wav_path = "{{.MigratedTonalBedPath}}"
gain_db  = {{.MigratedTonalBedGainDB}}

[assets.accents]
bank_dir    = "{{.MigratedAccentBank}}"
synth_decay = {{.MigratedAccentDecay}}

[video]
width         = {{.Video.Width}}
height        = {{.Video.Height}}
fps           = {{.Video.FPS}}
font_path     = "{{.Video.FontPath}}"
font_size_min = {{.Video.FontSizeMin}}
font_size_max = {{.Video.FontSizeMax}}

[video.palette]
background = "{{.Video.Palette.Background}}"
text       = "{{.Video.Palette.Text}}"
accent     = "{{.Video.Palette.Accent}}"

[video.motion]
speed_px_per_sec = {{.Video.Motion.SpeedPxPerSec}}
spawn_y_min      = {{.Video.Motion.SpawnYMin}}
spawn_y_max      = {{.Video.Motion.SpawnYMax}}

[video.text]
bottom_margin_px   = {{.Video.Text.BottomMarginPx}}
despawn_y_min      = {{.Video.Text.DespawnYMin}}
despawn_y_max      = {{.Video.Text.DespawnYMax}}
scale_grow_per_sec = {{.Video.Text.ScaleGrowPerSec}}
rotation_deg       = {{.Video.Text.RotationDeg}}

[video.background]
mode              = "{{.Video.Background.Mode}}"
sequence_dir      = "{{.Video.Background.SequenceDir}}"
sequence_dirs     = {{.MigratedSequenceDirsTOML}}
switch_every_secs = {{.Video.Background.SwitchEverySecs}}
fade_secs         = {{.Video.Background.FadeSecs}}

[video.event_colors]
{{range .MigratedEventColors}}{{.}}
{{end}}
[output]
mode               = "{{.Output.Mode}}"
video_preset       = "{{.Output.VideoPreset}}"
video_bitrate_kbps = {{.Output.VideoBitrateKbps}}
audio_bitrate_kbps = {{.Output.AudioBitrateKbps}}

[output.local]
path = "{{.Output.Local.Path}}"

[output.rtmps]
url = "{{.Output.RTMPS.URL}}"

[observe]
log_level             = "{{.Observe.LogLevel}}"
emit_stats_every_secs = {{.Observe.EmitStatsEverySecs}}
`

type renderModel struct {
	*config.Config
	SourcePath               string
	Profile                  string
	MigratedTonalBedPath     string
	MigratedTonalBedGainDB   float64
	MigratedTonalBedGain     string
	MigratedAccentBank       string
	MigratedAccentDecay      float64
	MigratedSequenceDirsTOML string
	MigratedEventColors      []string
	Events                   eventsView
}

type eventsView struct {
	TypesTOML        string
	MaxPerSecond     int
	DedupeWindowSecs int
	WeightLines      []string
}

func main() {
	in := flag.String("in", "", "input bell-era toml")
	out := flag.String("out", "", "output v2 toml (default stdout)")
	flag.Parse()
	if *in == "" {
		fmt.Fprintln(os.Stderr, "migrate-config: --in is required")
		os.Exit(2)
	}

	cfg, err := config.Load(*in)
	if err != nil {
		fmt.Fprintf(os.Stderr, "migrate-config: load %s: %v\n", *in, err)
		os.Exit(1)
	}
	if cfg.ResolvedEngine() == "v2" {
		fmt.Fprintf(os.Stderr, "migrate-config: %s already declares engine=\"v2\"; nothing to migrate\n", *in)
		os.Exit(0)
	}

	model := buildModel(cfg, *in)
	tpl := template.Must(template.New("v2").Parse(v2Template))

	var w io.Writer = os.Stdout
	if *out != "" {
		f, err := os.Create(*out)
		if err != nil {
			fmt.Fprintf(os.Stderr, "migrate-config: create %s: %v\n", *out, err)
			os.Exit(1)
		}
		defer f.Close()
		w = f
	}
	if err := tpl.Execute(w, model); err != nil {
		fmt.Fprintf(os.Stderr, "migrate-config: render: %v\n", err)
		os.Exit(1)
	}
}

func buildModel(cfg *config.Config, srcPath string) renderModel {
	tonalPath := "../../ops/assets/sounds/ambient/tonal-bed.wav"
	tonalGainDB := cfg.Audio.BGM.GainDB
	if tonalGainDB == 0 {
		tonalGainDB = -4.8
	}

	accentBank := cfg.Audio.Bells.BankDir
	if accentBank == "" {
		accentBank = "../../ops/assets/sounds/bells/sampled"
	}
	accentDecay := cfg.Audio.Bells.SynthDecay
	if accentDecay == 0 {
		accentDecay = 0.996
	}

	weights := make([]string, 0, len(cfg.Events.Weights))
	for _, t := range cfg.Events.Types {
		if w, ok := cfg.Events.Weights[t]; ok {
			weights = append(weights, fmt.Sprintf("%s = %d", t, w))
		}
	}

	typesTOML := "["
	for i, t := range cfg.Events.Types {
		if i > 0 {
			typesTOML += ", "
		}
		typesTOML += fmt.Sprintf("%q", t)
	}
	typesTOML += "]"

	tbGainLinear := fmt.Sprintf("%.3f", linearFromDB(tonalGainDB))

	seqDirs := "["
	for i, d := range cfg.Video.Background.SequenceDirs {
		if i > 0 {
			seqDirs += ", "
		}
		seqDirs += fmt.Sprintf("%q", d)
	}
	seqDirs += "]"

	colors := make([]string, 0, len(cfg.Video.EventColors))
	for k, v := range cfg.Video.EventColors {
		colors = append(colors, fmt.Sprintf("%s = %q", k, v))
	}

	return renderModel{
		Config:                   cfg,
		SourcePath:               srcPath,
		Profile:                  cfg.Meta.Profile,
		MigratedTonalBedPath:     tonalPath,
		MigratedTonalBedGainDB:   tonalGainDB,
		MigratedTonalBedGain:     tbGainLinear,
		MigratedAccentBank:       accentBank,
		MigratedAccentDecay:      accentDecay,
		MigratedSequenceDirsTOML: seqDirs,
		MigratedEventColors:      colors,
		Events: eventsView{
			TypesTOML:        typesTOML,
			MaxPerSecond:     cfg.Events.MaxPerSecond,
			DedupeWindowSecs: cfg.Events.DedupeWindowSecs,
			WeightLines:      weights,
		},
	}
}

func linearFromDB(db float64) float64 {
	return math.Pow(10, db/20.0)
}
