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

[audio.bgm]
wav_path = "/tmp/bgm.wav"
gain_db = -9.0
loop = true

[audio.voices.PushEvent]
wav_path = "/tmp/push.wav"
gain_db = 0.0
duration_ms = 500

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
	if v, ok := cfg.Audio.Voices["PushEvent"]; !ok || v.DurationMs != 500 {
		t.Errorf("Audio.Voices[PushEvent].DurationMs = %d, want 500", v.DurationMs)
	}
	if cfg.Audio.BGM.Loop != true {
		t.Error("Audio.BGM.Loop = false, want true")
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

func TestLoadBellSection(t *testing.T) {
	dir := t.TempDir()
	cfgPath := filepath.Join(dir, "c.toml")
	if err := os.WriteFile(cfgPath, []byte(`
[meta]
profile = "test"
[archive]
source_dir = "x"
daypack_dir = "y"
target_date = "2026-04-01"
[events]
types = ["PushEvent"]
max_per_second = 4
[events.weights]
PushEvent = 10
[audio]
sample_rate = 44100
channels = 2
[audio.bgm]
wav_path = ""
gain_db = 0
[audio.beat]
gain_db = 0
[audio.bells]
bank_dir = "bells"
sample_gain_db = -2.0
synth_gain_db = -4.0
synth_decay = 0.995
[audio.cluster]
keep_top_n = 4
event_types = ["PushEvent", "CreateEvent"]
always_fire = ["ReleaseEvent"]
velocities = [1.0, 0.75, 0.6, 0.45]
release_velocity = 1.0
octave_rank1 = 4
octave_rank2 = [4, 5]
octave_rank3 = 5
octave_rank4 = 3
octave_release = 5
spread_ms = 500
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
`), 0644); err != nil {
		t.Fatal(err)
	}
	cfg, err := Load(cfgPath)
	if err != nil {
		t.Fatal(err)
	}
	if cfg.Audio.Bells.BankDir != "bells" {
		t.Errorf("BankDir = %q, want %q", cfg.Audio.Bells.BankDir, "bells")
	}
	if cfg.Audio.Bells.SynthDecay != 0.995 {
		t.Errorf("SynthDecay = %v", cfg.Audio.Bells.SynthDecay)
	}
	if cfg.Audio.Cluster.KeepTopN != 4 {
		t.Errorf("KeepTopN = %d", cfg.Audio.Cluster.KeepTopN)
	}
	if len(cfg.Audio.Cluster.OctaveRank2) != 2 {
		t.Errorf("OctaveRank2 = %v", cfg.Audio.Cluster.OctaveRank2)
	}
	if cfg.Audio.Cluster.Velocities[0] != 1.0 {
		t.Errorf("Velocities[0] = %v", cfg.Audio.Cluster.Velocities[0])
	}
}
