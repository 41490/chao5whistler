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
	Meta     Meta           `toml:"meta"`
	Archive  Archive        `toml:"archive"`
	Events   Events         `toml:"events"`
	Audio    Audio          `toml:"audio"`
	Video    Video          `toml:"video"`
	Output   Output         `toml:"output"`
	Observe  Observe        `toml:"observe"`
	Composer ConfigComposer `toml:"composer"`
	Mixer    ConfigMixer    `toml:"mixer"`
	Assets   ConfigAssets   `toml:"assets"`
}

type Meta struct {
	Profile string `toml:"profile"`
	// Legacy marks a profile as a frozen bell-era baseline. Frozen profiles
	// are kept only as A/B reference for the ambient-engine refactor (#28)
	// and will be removed by #38 once the new mainline is stable. Setting
	// this true does not change runtime behavior; tooling (e.g. baseline
	// reports) reads it to label outputs.
	Legacy bool `toml:"legacy"`
	// Engine selects the audio engine: "v1" (bell-era, frozen) or "v2"
	// (ambient, #28+). Empty defaults to "v1" so existing profiles keep
	// loading; the new ghsingo-v2.toml sets engine = "v2" explicitly.
	Engine string `toml:"engine"`
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
	KeepTopN            int        `toml:"keep_top_n"`
	EventTypes          []string   `toml:"event_types"`
	AlwaysFire          []string   `toml:"always_fire"`
	Velocities          [4]float32 `toml:"velocities"`
	ReleaseVelocity     float32    `toml:"release_velocity"`
	OctaveRank1         int        `toml:"octave_rank1"`
	OctaveRank2         []int      `toml:"octave_rank2"`
	OctaveRank3         int        `toml:"octave_rank3"`
	OctaveRank4         int        `toml:"octave_rank4"`
	OctaveRelease       int        `toml:"octave_release"`
	SpreadMs            int        `toml:"spread_ms"`
	ConductorMode       bool       `toml:"conductor_mode"`
	LeadVelocity        float32    `toml:"lead_velocity"`
	BackgroundVelocity  float32    `toml:"background_velocity"`
	WindowMs            int        `toml:"window_ms"`
	WindowJitterMs      int        `toml:"window_jitter_ms"`
	MinStrikeIntervalMs int        `toml:"min_strike_interval_ms"`
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

// ConfigComposer maps to the [composer] block (v2 only). Fields mirror
// composer.Config exactly. Zero values fall back to composer defaults.
type ConfigComposer struct {
	EMAAlpha             float64 `toml:"ema_alpha"`
	DensitySaturation    float64 `toml:"density_saturation"`
	BrightnessSaturation float64 `toml:"brightness_saturation"`
	PhraseTicks          int     `toml:"phrase_ticks"`
	AccentCooldownTicks  int     `toml:"accent_cooldown_ticks"`
	AccentBaseProb       float64 `toml:"accent_base_prob"`
	Seed                 int64   `toml:"seed"`
}

// ConfigMixer maps to the [mixer] block (v2 only). Each field is a linear
// gain or wet ratio in [0,1]; when zero the MixerV2 default applies.
type ConfigMixer struct {
	MasterGain    float32 `toml:"master_gain"`
	DroneGain     float32 `toml:"drone_gain"`
	BedGain       float32 `toml:"bed_gain"`
	TonalBedGain  float32 `toml:"tonal_bed_gain"`
	AccentGain    float32 `toml:"accent_gain"`
	WetContinuous float32 `toml:"wet_continuous"`
	WetAccent     float32 `toml:"wet_accent"`
	AccentMax     int     `toml:"accent_max"`
}

// ConfigAssets maps to the [assets.*] blocks (v2 only). Replaces the
// bell-era [audio.bgm] / [audio.bells] role assignments.
type ConfigAssets struct {
	TonalBed AssetTonalBed `toml:"tonal_bed"`
	Accents  AssetAccents  `toml:"accents"`
}

type AssetTonalBed struct {
	WavPath string  `toml:"wav_path"`
	GainDB  float64 `toml:"gain_db"`
}

type AssetAccents struct {
	BankDir    string  `toml:"bank_dir"`
	SynthDecay float64 `toml:"synth_decay"`
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

// ResolvedEngine returns the engine name to use, applying the rule
// "blank engine + Legacy=true means v1, blank engine otherwise means v1
// for compatibility — only an explicit engine = \"v2\" opts into the
// ambient mainline." This keeps every bell-era profile in the v1 lane
// without a code change.
func (c *Config) ResolvedEngine() string {
	switch c.Meta.Engine {
	case "v1", "v2":
		return c.Meta.Engine
	}
	return "v1"
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
	if c.ResolvedEngine() == "v2" {
		if c.Meta.Legacy {
			return fmt.Errorf("meta.engine=\"v2\" cannot be combined with meta.legacy=true")
		}
		if c.Audio.Cluster.KeepTopN > 0 || len(c.Audio.Cluster.EventTypes) > 0 {
			return fmt.Errorf("meta.engine=\"v2\" must not define [audio.cluster] (bell-era only); use [composer] instead")
		}
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
