package config

import (
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"
)

const validTOML = `
[meta]
profile = "test"
engine = "v2"

[archive]
source_dir = "/tmp/assets"
daypack_dir = "/tmp/daypack"
target_date = "2026-03-28"

[archive.download]
enabled = false
base_url = "https://data.gharchive.org"
timeout_secs = 60
max_parallel = 4
user_agent = "ghsingo/0.1"

[events]
types = ["PushEvent", "CreateEvent"]
max_per_second = 4
dedupe_window_secs = 600

[events.weights]
PushEvent = 30
CreateEvent = 40

[audio]
sample_rate = 44100
channels = 2
master_gain_db = 0.0

[video]
width = 1280
height = 720
fps = 30
font_path = "/tmp/font.ttf"
font_size_min = 14
font_size_max = 42

[video.palette]
background = "#002b36"
text = "#fdf6e3"
accent = "#b58900"

[video.motion]
speed_px_per_sec = 180.0
spawn_y_min = 0.50
spawn_y_max = 0.95

[video.text]
bottom_margin_px = 16
despawn_y_min = 0.18
despawn_y_max = 0.45
scale_grow_per_sec = 0.22
rotation_deg = 90.0

[video.background]
mode = "solid"
sequence_dir = ""
sequence_dirs = []
switch_every_secs = 2.0
fade_secs = 0.2

[video.event_colors]
PushEvent = "#268bd2"
CreateEvent = "#2aa198"

[output]
mode = "local"
video_preset = "ultrafast"
audio_bitrate_kbps = 128

[output.local]
path = "/tmp/out.flv"

[output.rtmps]
url = ""

[observe]
log_level = "info"
emit_stats_every_secs = 30
`

func TestLoadValidConfig(t *testing.T) {
	dir := t.TempDir()
	path := filepath.Join(dir, "ghsingo.toml")
	if err := os.WriteFile(path, []byte(validTOML), 0644); err != nil {
		t.Fatalf("write temp config: %v", err)
	}

	cfg, err := Load(path)
	if err != nil {
		t.Fatalf("Load returned error: %v", err)
	}

	if cfg.Meta.Profile != "test" {
		t.Errorf("Meta.Profile = %q, want %q", cfg.Meta.Profile, "test")
	}
	if cfg.Archive.TargetDate != "2026-03-28" {
		t.Errorf("Archive.TargetDate = %q, want %q", cfg.Archive.TargetDate, "2026-03-28")
	}
	if cfg.Audio.SampleRate != 44100 {
		t.Errorf("Audio.SampleRate = %d, want 44100", cfg.Audio.SampleRate)
	}
	if cfg.Video.Width != 1280 {
		t.Errorf("Video.Width = %d, want 1280", cfg.Video.Width)
	}
	if cfg.Video.FPS != 30 {
		t.Errorf("Video.FPS = %d, want 30", cfg.Video.FPS)
	}
	if cfg.Output.Mode != "local" {
		t.Errorf("Output.Mode = %q, want %q", cfg.Output.Mode, "local")
	}
	if cfg.Video.Text.RotationDeg != 90 {
		t.Errorf("Video.Text.RotationDeg = %v, want 90", cfg.Video.Text.RotationDeg)
	}
	if cfg.Video.Background.Mode != "solid" {
		t.Errorf("Video.Background.Mode = %q, want solid", cfg.Video.Background.Mode)
	}
	if len(cfg.Events.Types) != 2 {
		t.Errorf("Events.Types length = %d, want 2", len(cfg.Events.Types))
	}
	if w, ok := cfg.Events.Weights["PushEvent"]; !ok || w != 30 {
		t.Errorf("Events.Weights[PushEvent] = %d, want 30", w)
	}
}

func TestLoadLocalOverlay(t *testing.T) {
	dir := t.TempDir()
	basePath := filepath.Join(dir, "ghsingo.toml")
	if err := os.WriteFile(basePath, []byte(validTOML), 0644); err != nil {
		t.Fatalf("write base config: %v", err)
	}

	// Create .local.toml that overrides output mode to rtmps
	localTOML := `
[output]
mode = "rtmps"

[output.rtmps]
url = "rtmps://a.rtmps.youtube.com/live2/test-key"
`
	localPath := filepath.Join(dir, "ghsingo.local.toml")
	if err := os.WriteFile(localPath, []byte(localTOML), 0644); err != nil {
		t.Fatalf("write local config: %v", err)
	}

	cfg, err := Load(basePath)
	if err != nil {
		t.Fatalf("Load returned error: %v", err)
	}

	// Overlay should override mode
	if cfg.Output.Mode != "rtmps" {
		t.Errorf("Output.Mode = %q, want %q (overlay should override)", cfg.Output.Mode, "rtmps")
	}
	if cfg.Output.RTMPS.URL != "rtmps://a.rtmps.youtube.com/live2/test-key" {
		t.Errorf("Output.RTMPS.URL = %q, want rtmps URL from overlay", cfg.Output.RTMPS.URL)
	}

	// Base values should be preserved
	if cfg.Meta.Profile != "test" {
		t.Errorf("Meta.Profile = %q, want %q (base should be preserved)", cfg.Meta.Profile, "test")
	}
	if cfg.Audio.SampleRate != 44100 {
		t.Errorf("Audio.SampleRate = %d, want 44100 (base should be preserved)", cfg.Audio.SampleRate)
	}
}

func TestLoadNoLocalOverlay(t *testing.T) {
	// When no .local.toml exists, Load should work as before
	dir := t.TempDir()
	basePath := filepath.Join(dir, "ghsingo.toml")
	if err := os.WriteFile(basePath, []byte(validTOML), 0644); err != nil {
		t.Fatalf("write base config: %v", err)
	}

	cfg, err := Load(basePath)
	if err != nil {
		t.Fatalf("Load returned error: %v", err)
	}
	if cfg.Output.Mode != "local" {
		t.Errorf("Output.Mode = %q, want %q", cfg.Output.Mode, "local")
	}
}

func TestResolveTargetDate(t *testing.T) {
	today := time.Now().Format("2006-01-02")
	yesterday := time.Now().AddDate(0, 0, -1).Format("2006-01-02")

	tests := []struct {
		input string
		want  string
	}{
		{"yesterday", yesterday},
		{"today", today},
		{"2026-03-28", "2026-03-28"},
	}
	for _, tt := range tests {
		got := ResolveTargetDate(tt.input)
		if got != tt.want {
			t.Errorf("ResolveTargetDate(%q) = %q, want %q", tt.input, got, tt.want)
		}
	}
}

func TestLoadInvalidMode(t *testing.T) {
	invalid := strings.Replace(validTOML, `mode = "local"`, `mode = "INVALID"`, 1)
	dir := t.TempDir()
	path := filepath.Join(dir, "bad.toml")
	if err := os.WriteFile(path, []byte(invalid), 0644); err != nil {
		t.Fatalf("write temp config: %v", err)
	}

	_, err := Load(path)
	if err == nil {
		t.Fatal("expected error for invalid mode, got nil")
	}
	if !strings.Contains(err.Error(), "INVALID") {
		t.Errorf("error %q should mention INVALID mode", err.Error())
	}
}

func TestLoadInvalidBackgroundMode(t *testing.T) {
	invalid := strings.Replace(validTOML, `mode = "solid"`, `mode = "badmode"`, 1)
	dir := t.TempDir()
	path := filepath.Join(dir, "bad.toml")
	if err := os.WriteFile(path, []byte(invalid), 0644); err != nil {
		t.Fatalf("write temp config: %v", err)
	}

	_, err := Load(path)
	if err == nil {
		t.Fatal("expected error for invalid background mode, got nil")
	}
	if !strings.Contains(err.Error(), "badmode") {
		t.Errorf("error %q should mention badmode", err.Error())
	}
}

func TestVideoBackgroundPatternsPrefersSequenceDirs(t *testing.T) {
	bg := VideoBackground{
		SequenceDir:  "single",
		SequenceDirs: []string{" first ", "", "second"},
	}
	got := bg.Patterns()
	want := []string{"first", "second"}
	if len(got) != len(want) {
		t.Fatalf("len(Patterns()) = %d, want %d", len(got), len(want))
	}
	for i := range want {
		if got[i] != want[i] {
			t.Fatalf("Patterns()[%d] = %q, want %q", i, got[i], want[i])
		}
	}
}

func TestVideoBackgroundPatternsFallsBackToSequenceDir(t *testing.T) {
	bg := VideoBackground{SequenceDir: " single "}
	got := bg.Patterns()
	if len(got) != 1 || got[0] != "single" {
		t.Fatalf("Patterns() = %v, want [single]", got)
	}
}

func TestLoadInvalidBackgroundSwitchEverySecs(t *testing.T) {
	invalid := strings.Replace(validTOML, `switch_every_secs = 2.0`, `switch_every_secs = 0`, 1)
	dir := t.TempDir()
	path := filepath.Join(dir, "bad.toml")
	if err := os.WriteFile(path, []byte(invalid), 0644); err != nil {
		t.Fatalf("write temp config: %v", err)
	}

	_, err := Load(path)
	if err == nil {
		t.Fatal("expected error for invalid switch_every_secs, got nil")
	}
	if !strings.Contains(err.Error(), "switch_every_secs") {
		t.Fatalf("error %q should mention switch_every_secs", err.Error())
	}
}

func TestLoadInvalidBackgroundFadeSecs(t *testing.T) {
	invalid := strings.Replace(validTOML, `fade_secs = 0.2`, `fade_secs = -1`, 1)
	dir := t.TempDir()
	path := filepath.Join(dir, "bad.toml")
	if err := os.WriteFile(path, []byte(invalid), 0644); err != nil {
		t.Fatalf("write temp config: %v", err)
	}

	_, err := Load(path)
	if err == nil {
		t.Fatal("expected error for invalid fade_secs, got nil")
	}
	if !strings.Contains(err.Error(), "fade_secs") {
		t.Fatalf("error %q should mention fade_secs", err.Error())
	}
}

func TestResolvedEngineDefaults(t *testing.T) {
	cases := []struct {
		engine string
		want   string
	}{
		{"", "v2"},
		{"v2", "v2"},
		{"v3", "v3"}, // future engines pass through; validate() rejects them
	}
	for _, tc := range cases {
		c := &Config{Meta: Meta{Engine: tc.engine}}
		if got := c.ResolvedEngine(); got != tc.want {
			t.Errorf("engine=%q: got %q want %q", tc.engine, got, tc.want)
		}
	}
}

func TestLoadV2Schema(t *testing.T) {
	dir := t.TempDir()
	path := filepath.Join(dir, "v2.toml")
	body := `
[meta]
profile = "ambient-v2"
engine  = "v2"
[archive]
source_dir = "x"
daypack_dir = "y"
target_date = "2026-04-01"
[events]
types = ["PushEvent"]
max_per_second = 4
[events.weights]
PushEvent = 30
[audio]
sample_rate = 44100
channels = 2
[composer]
ema_alpha = 0.06
phrase_ticks = 16
accent_base_prob = 0.10
[mixer]
master_gain = 0.55
wet_continuous = 0.06
wet_accent = 0.45
accent_max = 4
[assets.tonal_bed]
wav_path = "/tmp/tb.wav"
gain_db = -4.8
[assets.accents]
bank_dir = "/tmp/bank"
synth_decay = 0.996
[video]
width = 1280
height = 720
fps = 15
[video.background]
mode = "solid"
switch_every_secs = 1.0
fade_secs = 0.0
[output]
mode = "local"
[output.local]
path = "/tmp/x"
`
	if err := os.WriteFile(path, []byte(body), 0644); err != nil {
		t.Fatal(err)
	}
	cfg, err := Load(path)
	if err != nil {
		t.Fatalf("Load v2: %v", err)
	}
	if cfg.ResolvedEngine() != "v2" {
		t.Fatalf("engine = %q, want v2", cfg.ResolvedEngine())
	}
	if cfg.Composer.PhraseTicks != 16 {
		t.Errorf("Composer.PhraseTicks = %d", cfg.Composer.PhraseTicks)
	}
	if cfg.Mixer.MasterGain != 0.55 {
		t.Errorf("Mixer.MasterGain = %v", cfg.Mixer.MasterGain)
	}
	if cfg.Assets.TonalBed.WavPath != "/tmp/tb.wav" {
		t.Errorf("Assets.TonalBed.WavPath = %q", cfg.Assets.TonalBed.WavPath)
	}
	if cfg.Assets.Accents.BankDir != "/tmp/bank" {
		t.Errorf("Assets.Accents.BankDir = %q", cfg.Assets.Accents.BankDir)
	}
}

// TestLoadRejectsUnknownEngine ensures the "v2 only" stance from #38
// holds: validate() refuses anything else.
func TestLoadRejectsUnknownEngine(t *testing.T) {
	dir := t.TempDir()
	path := filepath.Join(dir, "bad.toml")
	body := `
[meta]
profile = "x"
engine = "v3"
[archive]
source_dir = "x"
daypack_dir = "y"
target_date = "2026-04-01"
[events]
types = ["PushEvent"]
max_per_second = 4
[events.weights]
PushEvent = 30
[audio]
sample_rate = 44100
channels = 2
[video]
width = 1280
height = 720
fps = 15
[video.background]
mode = "solid"
switch_every_secs = 1.0
fade_secs = 0.0
[output]
mode = "local"
[output.local]
path = "/tmp/x"
`
	if err := os.WriteFile(path, []byte(body), 0644); err != nil {
		t.Fatal(err)
	}
	if _, err := Load(path); err == nil {
		t.Fatal("expected error for engine=v3")
	} else if !strings.Contains(err.Error(), "v2") {
		t.Fatalf("error should mention v2 as the only supported engine, got %v", err)
	}
}
