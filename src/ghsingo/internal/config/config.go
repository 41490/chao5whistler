package config

import (
	"fmt"
	"os"
	"path/filepath"
	"strings"
	"time"

	"github.com/BurntSushi/toml"
)

type Config struct {
	Meta    Meta    `toml:"meta"`
	Archive Archive `toml:"archive"`
	Events  Events  `toml:"events"`
	Audio   Audio   `toml:"audio"`
	Video   Video   `toml:"video"`
	Output  Output  `toml:"output"`
	Observe Observe `toml:"observe"`
}

type Meta struct {
	Profile string `toml:"profile"`
}

type Archive struct {
	SourceDir  string          `toml:"source_dir"`
	DaypackDir string          `toml:"daypack_dir"`
	TargetDate string          `toml:"target_date"`
	Download   ArchiveDownload `toml:"download"`
}

type ArchiveDownload struct {
	Enabled     bool   `toml:"enabled"`
	BaseURL     string `toml:"base_url"`
	TimeoutSecs int    `toml:"timeout_secs"`
	MaxParallel int    `toml:"max_parallel"`
	UserAgent   string `toml:"user_agent"`
}

type Events struct {
	Types            []string       `toml:"types"`
	MaxPerSecond     int            `toml:"max_per_second"`
	DedupeWindowSecs int            `toml:"dedupe_window_secs"`
	Weights          map[string]int `toml:"weights"`
}

type Audio struct {
	SampleRate   int              `toml:"sample_rate"`
	Channels     int              `toml:"channels"`
	MasterGainDB float64          `toml:"master_gain_db"`
	BGM          AudioBGM         `toml:"bgm"`
	Beat         AudioBeat        `toml:"beat"`
	Voices       map[string]Voice `toml:"voices"`
	Bells        AudioBells       `toml:"bells"`
	Cluster      AudioCluster     `toml:"cluster"`
}

type AudioBeat struct {
	GainDB float64 `toml:"gain_db"`
}

type AudioBGM struct {
	WavPath string  `toml:"wav_path"`
	GainDB  float64 `toml:"gain_db"`
	Loop    bool    `toml:"loop"`
}

type Voice struct {
	WavPath    string  `toml:"wav_path"`
	GainDB     float64 `toml:"gain_db"`
	DurationMs int     `toml:"duration_ms"`
}

// AudioBells configures the 15-pitch pentatonic bell layer.
type AudioBells struct {
	BankDir      string  `toml:"bank_dir"`
	SampleGainDB float64 `toml:"sample_gain_db"`
	SynthGainDB  float64 `toml:"synth_gain_db"`
	SynthDecay   float64 `toml:"synth_decay"`
}

// AudioCluster configures the per-second event-to-note mapping algorithm.
type AudioCluster struct {
	KeepTopN           int        `toml:"keep_top_n"`
	EventTypes         []string   `toml:"event_types"`
	AlwaysFire         []string   `toml:"always_fire"`
	Velocities         [4]float32 `toml:"velocities"`
	ReleaseVelocity    float32    `toml:"release_velocity"`
	OctaveRank1        int        `toml:"octave_rank1"`
	OctaveRank2        []int      `toml:"octave_rank2"`
	OctaveRank3        int        `toml:"octave_rank3"`
	OctaveRank4        int        `toml:"octave_rank4"`
	OctaveRelease      int        `toml:"octave_release"`
	SpreadMs           int        `toml:"spread_ms"`
	ConductorMode      bool       `toml:"conductor_mode"`
	LeadVelocity       float32    `toml:"lead_velocity"`
	BackgroundVelocity float32    `toml:"background_velocity"`
	WindowMs           int        `toml:"window_ms"`
	WindowJitterMs     int        `toml:"window_jitter_ms"`
}

type Video struct {
	Width       int               `toml:"width"`
	Height      int               `toml:"height"`
	FPS         int               `toml:"fps"`
	FontPath    string            `toml:"font_path"`
	FontSizeMin int               `toml:"font_size_min"`
	FontSizeMax int               `toml:"font_size_max"`
	Palette     Palette           `toml:"palette"`
	Motion      VideoMotion       `toml:"motion"`
	Text        VideoText         `toml:"text"`
	Background  VideoBackground   `toml:"background"`
	EventColors map[string]string `toml:"event_colors"`
}

type Palette struct {
	Background string `toml:"background"`
	Text       string `toml:"text"`
	Accent     string `toml:"accent"`
}

type VideoMotion struct {
	SpeedPxPerSec float64 `toml:"speed_px_per_sec"`
	SpawnYMin     float64 `toml:"spawn_y_min"`
	SpawnYMax     float64 `toml:"spawn_y_max"`
}

type VideoText struct {
	BottomMarginPx  int     `toml:"bottom_margin_px"`
	DespawnYMin     float64 `toml:"despawn_y_min"`
	DespawnYMax     float64 `toml:"despawn_y_max"`
	ScaleGrowPerSec float64 `toml:"scale_grow_per_sec"`
	RotationDeg     float64 `toml:"rotation_deg"`
}

type VideoBackground struct {
	Mode            string   `toml:"mode"`
	SequenceDir     string   `toml:"sequence_dir"`
	SequenceDirs    []string `toml:"sequence_dirs"`
	SwitchEverySecs float64  `toml:"switch_every_secs"`
	FadeSecs        float64  `toml:"fade_secs"`
}

type Output struct {
	Mode             string      `toml:"mode"`
	VideoPreset      string      `toml:"video_preset"`
	VideoBitrateKbps int         `toml:"video_bitrate_kbps"`
	AudioBitrateKbps int         `toml:"audio_bitrate_kbps"`
	Local            OutputLocal `toml:"local"`
	RTMPS            OutputRTMPS `toml:"rtmps"`
}

type OutputLocal struct {
	Path string `toml:"path"`
}

type OutputRTMPS struct {
	URL string `toml:"url"`
}

type Observe struct {
	LogLevel           string `toml:"log_level"`
	EmitStatsEverySecs int    `toml:"emit_stats_every_secs"`
}

var EventTypeID = map[string]uint8{
	"PushEvent":        0,
	"CreateEvent":      1,
	"IssuesEvent":      2,
	"PullRequestEvent": 3,
	"ForkEvent":        4,
	"ReleaseEvent":     5,
}

func Load(path string) (*Config, error) {
	data, err := os.ReadFile(path)
	if err != nil {
		return nil, fmt.Errorf("read config: %w", err)
	}
	var cfg Config
	if err := toml.Unmarshal(data, &cfg); err != nil {
		return nil, fmt.Errorf("parse config: %w", err)
	}

	// Apply .local.toml overlay if it exists alongside the base config.
	localPath := localOverlayPath(path)
	if localData, err := os.ReadFile(localPath); err == nil {
		if err := toml.Unmarshal(localData, &cfg); err != nil {
			return nil, fmt.Errorf("parse local overlay %s: %w", localPath, err)
		}
	}

	if err := cfg.validate(); err != nil {
		return nil, err
	}
	return &cfg, nil
}

// localOverlayPath derives the .local.toml path from a base config path.
// e.g. "ghsingo.toml" -> "ghsingo.local.toml"
func localOverlayPath(basePath string) string {
	ext := filepath.Ext(basePath)
	return basePath[:len(basePath)-len(ext)] + ".local" + ext
}

// ResolveTargetDate converts symbolic date names ("yesterday", "today") to
// concrete YYYY-MM-DD strings. Literal dates pass through unchanged.
func ResolveTargetDate(s string) string {
	now := time.Now()
	switch s {
	case "yesterday":
		return now.AddDate(0, 0, -1).Format("2006-01-02")
	case "today":
		return now.Format("2006-01-02")
	default:
		return s
	}
}

func (c *Config) validate() error {
	switch c.Output.Mode {
	case "local", "rtmps":
	default:
		return fmt.Errorf("output.mode must be \"local\" or \"rtmps\", got %q", c.Output.Mode)
	}
	if c.Output.Mode == "rtmps" && c.Output.RTMPS.URL == "" {
		return fmt.Errorf("output.rtmps.url required when mode is \"rtmps\"")
	}
	if c.Audio.SampleRate <= 0 {
		return fmt.Errorf("audio.sample_rate must be positive")
	}
	if c.Video.FPS <= 0 {
		return fmt.Errorf("video.fps must be positive")
	}
	switch c.Video.Background.Mode {
	case "", "solid", "mosaic_sequence":
	default:
		return fmt.Errorf("video.background.mode must be \"solid\" or \"mosaic_sequence\", got %q", c.Video.Background.Mode)
	}
	if c.Video.Background.Mode == "mosaic_sequence" && len(c.Video.Background.Patterns()) == 0 {
		return fmt.Errorf("video.background.sequence_dir or video.background.sequence_dirs required when mode is \"mosaic_sequence\"")
	}
	if c.Video.Background.SwitchEverySecs <= 0 {
		return fmt.Errorf("video.background.switch_every_secs must be positive")
	}
	if c.Video.Background.FadeSecs < 0 {
		return fmt.Errorf("video.background.fade_secs must be >= 0")
	}
	if c.Events.MaxPerSecond <= 0 {
		return fmt.Errorf("events.max_per_second must be positive")
	}
	return nil
}

func (b VideoBackground) Patterns() []string {
	if len(b.SequenceDirs) > 0 {
		return nonEmptyStrings(b.SequenceDirs)
	}
	if strings.TrimSpace(b.SequenceDir) == "" {
		return nil
	}
	return []string{strings.TrimSpace(b.SequenceDir)}
}

func nonEmptyStrings(items []string) []string {
	out := make([]string, 0, len(items))
	for _, item := range items {
		item = strings.TrimSpace(item)
		if item == "" {
			continue
		}
		out = append(out, item)
	}
	return out
}
