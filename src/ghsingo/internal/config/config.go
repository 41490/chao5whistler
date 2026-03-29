package config

import (
	"fmt"
	"os"

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
	Voices       map[string]Voice `toml:"voices"`
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

type Video struct {
	Width       int         `toml:"width"`
	Height      int         `toml:"height"`
	FPS         int         `toml:"fps"`
	FontPath    string      `toml:"font_path"`
	FontSizeMin int         `toml:"font_size_min"`
	FontSizeMax int         `toml:"font_size_max"`
	Palette     Palette     `toml:"palette"`
	Motion      VideoMotion `toml:"motion"`
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

type Output struct {
	Mode             string      `toml:"mode"`
	VideoPreset      string      `toml:"video_preset"`
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
	if err := cfg.validate(); err != nil {
		return nil, err
	}
	return &cfg, nil
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
	if c.Events.MaxPerSecond <= 0 {
		return fmt.Errorf("events.max_per_second must be positive")
	}
	return nil
}
