# ghsingo 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 基于 Go 实现 GH Archive 事件声音化无限直播推流工具, 包含离线 prepare 和在线 live 两个独立 binary.

**Architecture:** 2 阶段系统 — prepare 从 GH Archive JSON 生成专用二进制 day-pack, live 读取 day-pack 逐秒回放, 混合海洋生物 WAV 采样和 BGM 生成音视频, 通过双 pipe 送 FFmpeg 输出. 详见 `docs/assay/260329-ghsingo-architecture.md`.

**Tech Stack:** Go 1.22+, fogleman/gg (2D渲染), go-audio/wav (WAV解码), BurntSushi/toml (配置), FFmpeg (编码/推流)

---

## 文件结构

```
src/ghsingo/
├── go.mod                              # Go 模块定义
├── go.sum
├── Makefile                            # 构建/运行/部署
├── ghsingo.toml                        # 配置模板 (tracked)
├── .gitignore                          # bin/, *.wav (生成的), var/
├── cmd/
│   ├── prepare/main.go                 # prepare 入口, 解析CLI→调用 archive 包
│   └── live/main.go                    # live 入口, 启动回放+渲染+推流循环
├── internal/
│   ├── config/
│   │   ├── config.go                   # TOML 结构体 + Load() + Validate()
│   │   └── config_test.go
│   ├── archive/
│   │   ├── daypack.go                  # day.bin 二进制格式: Header, Tick, Event 结构 + Read/Write
│   │   ├── daypack_test.go
│   │   ├── parse.go                    # GH Archive JSON 解析 + 过滤 + 分桶 + top-4 选择
│   │   └── parse_test.go
│   ├── replay/
│   │   ├── engine.go                   # day-pack → tick channel, 按墙钟逐秒发射
│   │   └── engine_test.go
│   ├── audio/
│   │   ├── mixer.go                    # WAV 采样加载 + PCM 混音 + BGM 循环
│   │   └── mixer_test.go
│   ├── video/
│   │   ├── renderer.go                 # RGBA 帧渲染: Solarized Dark 背景 + 浮升文字
│   │   └── renderer_test.go
│   └── stream/
│       ├── ffmpeg.go                   # FFmpeg 子进程管理: 双 pipe + 启动/停止/重启
│       └── ffmpeg_test.go
└── ops/
    └── systemd/
        ├── ghsingo-prepare.service     # prepare 一次性服务
        ├── ghsingo-prepare.timer       # 每日凌晨触发
        └── ghsingo-live.service        # live 常驻服务
```

---

## Task 1: 项目脚手架 + 配置模块

**Files:**
- Create: `src/ghsingo/go.mod`
- Create: `src/ghsingo/.gitignore`
- Create: `src/ghsingo/ghsingo.toml`
- Create: `src/ghsingo/internal/config/config.go`
- Create: `src/ghsingo/internal/config/config_test.go`

- [ ] **Step 1: 初始化 Go 模块**

```bash
cd src/ghsingo
go mod init github.com/41490/chao5whistler/src/ghsingo
```

- [ ] **Step 2: 创建 .gitignore**

```gitignore
bin/
*.wav
var/
ghsingo.local.toml
```

- [ ] **Step 3: 创建配置模板 ghsingo.toml**

复制架构文档第 6 节的完整 TOML 配置 (见 `docs/assay/260329-ghsingo-architecture.md` 第 6 节).

- [ ] **Step 4: 编写配置结构体失败测试**

```go
// internal/config/config_test.go
package config

import (
	"os"
	"path/filepath"
	"testing"
)

func TestLoadValidConfig(t *testing.T) {
	dir := t.TempDir()
	path := filepath.Join(dir, "test.toml")
	os.WriteFile(path, []byte(`
[meta]
profile = "test"

[archive]
source_dir = "ops/assets"
daypack_dir = "var/ghsingo/daypack"
target_date = "2026-03-28"

[archive.download]
enabled = false
base_url = "https://data.gharchive.org"
timeout_secs = 60
max_parallel = 4
user_agent = "ghsingo/0.1"

[events]
types = ["PushEvent", "CreateEvent", "IssuesEvent", "PullRequestEvent", "ForkEvent", "ReleaseEvent"]
max_per_second = 4
dedupe_window_secs = 600

[events.weights]
PushEvent = 30
CreateEvent = 40
IssuesEvent = 50
PullRequestEvent = 70
ForkEvent = 80
ReleaseEvent = 100

[audio]
sample_rate = 44100
channels = 2
master_gain_db = 0.0

[audio.bgm]
wav_path = "ops/assets/cosmos-leveloop-339.wav"
gain_db = -9.0
loop = true

[audio.voices.PushEvent]
wav_path = "ops/assets/sounds/dolphin_click.wav"
gain_db = 0.0
duration_ms = 500

[audio.voices.CreateEvent]
wav_path = "ops/assets/sounds/seal_bark.wav"
gain_db = -2.0
duration_ms = 700

[audio.voices.IssuesEvent]
wav_path = "ops/assets/sounds/humpback_moan.wav"
gain_db = 1.0
duration_ms = 900

[audio.voices.PullRequestEvent]
wav_path = "ops/assets/sounds/orca_call.wav"
gain_db = 3.0
duration_ms = 1000

[audio.voices.ForkEvent]
wav_path = "ops/assets/sounds/clownfish_pop.wav"
gain_db = 2.0
duration_ms = 800

[audio.voices.ReleaseEvent]
wav_path = "ops/assets/sounds/blue_whale_boom.wav"
gain_db = 4.0
duration_ms = 1400

[video]
width = 1280
height = 720
fps = 30
font_path = "ops/assets/3270NerdFontMono-Condensed.ttf"
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

[output]
mode = "local"
video_preset = "ultrafast"
audio_bitrate_kbps = 128

[output.local]
path = "var/ghsingo/records/{date}.flv"

[output.rtmps]
url = ""

[observe]
log_level = "info"
emit_stats_every_secs = 30
`), 0644)

	cfg, err := Load(path)
	if err != nil {
		t.Fatalf("Load() error: %v", err)
	}
	if cfg.Meta.Profile != "test" {
		t.Errorf("Profile = %q, want %q", cfg.Meta.Profile, "test")
	}
	if cfg.Audio.SampleRate != 44100 {
		t.Errorf("SampleRate = %d, want 44100", cfg.Audio.SampleRate)
	}
	if cfg.Video.Width != 1280 {
		t.Errorf("Width = %d, want 1280", cfg.Video.Width)
	}
	if cfg.Output.Mode != "local" {
		t.Errorf("Mode = %q, want %q", cfg.Output.Mode, "local")
	}
}

func TestLoadInvalidMode(t *testing.T) {
	dir := t.TempDir()
	path := filepath.Join(dir, "bad.toml")
	os.WriteFile(path, []byte(`
[meta]
profile = "bad"
[archive]
source_dir = "x"
daypack_dir = "y"
target_date = "2026-03-28"
[archive.download]
enabled = false
base_url = "https://data.gharchive.org"
timeout_secs = 60
max_parallel = 4
user_agent = "ghsingo/0.1"
[events]
types = ["PushEvent"]
max_per_second = 4
dedupe_window_secs = 600
[events.weights]
PushEvent = 30
[audio]
sample_rate = 44100
channels = 2
master_gain_db = 0.0
[audio.bgm]
wav_path = "x.wav"
gain_db = -9.0
loop = true
[video]
width = 1280
height = 720
fps = 30
font_path = "x.ttf"
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
[output]
mode = "INVALID"
video_preset = "ultrafast"
audio_bitrate_kbps = 128
[output.local]
path = "x.flv"
[output.rtmps]
url = ""
[observe]
log_level = "info"
emit_stats_every_secs = 30
`), 0644)

	_, err := Load(path)
	if err == nil {
		t.Fatal("Load() should fail for invalid output mode")
	}
}
```

- [ ] **Step 5: 运行测试确认失败**

```bash
cd src/ghsingo && go test ./internal/config/ -v
```

预期: FAIL — `Load` 未定义

- [ ] **Step 6: 实现配置模块**

```go
// internal/config/config.go
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
	Mode            string      `toml:"mode"`
	VideoPreset     string      `toml:"video_preset"`
	AudioBitrateKbps int        `toml:"audio_bitrate_kbps"`
	Local           OutputLocal `toml:"local"`
	RTMPS           OutputRTMPS `toml:"rtmps"`
}

type OutputLocal struct {
	Path string `toml:"path"`
}

type OutputRTMPS struct {
	URL string `toml:"url"`
}

type Observe struct {
	LogLevel          string `toml:"log_level"`
	EmitStatsEverySecs int   `toml:"emit_stats_every_secs"`
}

// EventTypeID maps event type name to its type_id (0~5).
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
```

- [ ] **Step 7: 安装依赖并运行测试**

```bash
cd src/ghsingo && go get github.com/BurntSushi/toml@v1.3.0 && go test ./internal/config/ -v
```

预期: 2 passed

- [ ] **Step 8: 提交**

```bash
jj describe -m 'feat(ghsingo): project scaffold + config module (#17)'
```

---

## Task 2: day-pack 二进制格式 (读/写)

**Files:**
- Create: `src/ghsingo/internal/archive/daypack.go`
- Create: `src/ghsingo/internal/archive/daypack_test.go`

- [ ] **Step 1: 编写 day-pack 读写失败测试**

```go
// internal/archive/daypack_test.go
package archive

import (
	"os"
	"path/filepath"
	"testing"
)

func TestDaypackRoundTrip(t *testing.T) {
	pack := &Daypack{
		Header: Header{
			Magic:      [4]byte{'G', 'S', 'I', 'N'},
			Version:    1,
			Date:       20260328,
			TotalTicks: 86400,
		},
		Ticks: make([]Tick, 86400),
	}
	// second 0: 2 events
	pack.Ticks[0] = Tick{
		Events: []Event{
			{TypeID: 0, Weight: 128, Text: "user/repo/abc12345"},
			{TypeID: 3, Weight: 200, Text: "org/project/def678"},
		},
	}
	// second 1: 0 events (empty)
	// second 3600: 1 event
	pack.Ticks[3600] = Tick{
		Events: []Event{
			{TypeID: 5, Weight: 255, Text: "big/release/v1.0.0"},
		},
	}

	dir := t.TempDir()
	path := filepath.Join(dir, "day.bin")

	if err := WriteDaypack(path, pack); err != nil {
		t.Fatalf("WriteDaypack: %v", err)
	}

	got, err := ReadDaypack(path)
	if err != nil {
		t.Fatalf("ReadDaypack: %v", err)
	}

	if got.Header.Date != 20260328 {
		t.Errorf("Date = %d, want 20260328", got.Header.Date)
	}
	if len(got.Ticks[0].Events) != 2 {
		t.Fatalf("Tick[0] events = %d, want 2", len(got.Ticks[0].Events))
	}
	if got.Ticks[0].Events[0].Text != "user/repo/abc12345" {
		t.Errorf("Tick[0].Events[0].Text = %q", got.Ticks[0].Events[0].Text)
	}
	if got.Ticks[0].Events[1].TypeID != 3 {
		t.Errorf("Tick[0].Events[1].TypeID = %d, want 3", got.Ticks[0].Events[1].TypeID)
	}
	if len(got.Ticks[1].Events) != 0 {
		t.Errorf("Tick[1] should be empty, got %d events", len(got.Ticks[1].Events))
	}
	if len(got.Ticks[3600].Events) != 1 {
		t.Fatalf("Tick[3600] events = %d, want 1", len(got.Ticks[3600].Events))
	}
	if got.Ticks[3600].Events[0].Weight != 255 {
		t.Errorf("Tick[3600].Events[0].Weight = %d, want 255", got.Ticks[3600].Events[0].Weight)
	}
}

func TestDaypackBadMagic(t *testing.T) {
	dir := t.TempDir()
	path := filepath.Join(dir, "bad.bin")
	os.WriteFile(path, []byte("NOT_GSIN_HEADER_AT_ALL"), 0644)

	_, err := ReadDaypack(path)
	if err == nil {
		t.Fatal("ReadDaypack should fail for bad magic")
	}
}

func TestDaypackFileSize(t *testing.T) {
	// A daypack with mostly empty ticks should be small
	pack := &Daypack{
		Header: Header{
			Magic:      [4]byte{'G', 'S', 'I', 'N'},
			Version:    1,
			Date:       20260328,
			TotalTicks: 86400,
		},
		Ticks: make([]Tick, 86400),
	}
	// Only 100 ticks have 1 event each
	for i := 0; i < 100; i++ {
		pack.Ticks[i*864] = Tick{
			Events: []Event{
				{TypeID: 0, Weight: 100, Text: "a/b/c"},
			},
		}
	}

	dir := t.TempDir()
	path := filepath.Join(dir, "day.bin")
	WriteDaypack(path, pack)

	info, _ := os.Stat(path)
	// 16 (header) + 86400 * 1 (count byte) + 100 * (3 + 5) = ~87.2KB
	if info.Size() > 200_000 {
		t.Errorf("sparse daypack too large: %d bytes", info.Size())
	}
}
```

- [ ] **Step 2: 运行测试确认失败**

```bash
cd src/ghsingo && go test ./internal/archive/ -v
```

预期: FAIL — 类型未定义

- [ ] **Step 3: 实现 day-pack 格式**

```go
// internal/archive/daypack.go
package archive

import (
	"encoding/binary"
	"fmt"
	"io"
	"os"
)

const (
	HeaderSize   = 16
	MaxEventsPerTick = 4
	MaxTextLen   = 64
	TotalTicks   = 86400
)

type Header struct {
	Magic      [4]byte // "GSIN"
	Version    uint16
	Date       uint32  // YYYYMMDD
	TotalTicks uint32  // always 86400
	Reserved   [2]byte
}

type Event struct {
	TypeID uint8  // 0~5
	Weight uint8  // 0~255
	Text   string // max 64 bytes UTF-8
}

type Tick struct {
	Events []Event // 0~4
}

type Daypack struct {
	Header Header
	Ticks  []Tick
}

func WriteDaypack(path string, pack *Daypack) error {
	f, err := os.Create(path)
	if err != nil {
		return err
	}
	defer f.Close()

	if err := binary.Write(f, binary.LittleEndian, &pack.Header); err != nil {
		return fmt.Errorf("write header: %w", err)
	}

	for i := 0; i < TotalTicks; i++ {
		tick := pack.Ticks[i]
		count := uint8(len(tick.Events))
		if count > MaxEventsPerTick {
			count = MaxEventsPerTick
		}
		if err := f.WriteByte(count); err != nil {
			return err
		}
		for j := 0; j < int(count); j++ {
			evt := tick.Events[j]
			text := []byte(evt.Text)
			if len(text) > MaxTextLen {
				text = text[:MaxTextLen]
			}
			buf := []byte{evt.TypeID, evt.Weight, uint8(len(text))}
			if _, err := f.Write(buf); err != nil {
				return err
			}
			if _, err := f.Write(text); err != nil {
				return err
			}
		}
	}
	return nil
}

func ReadDaypack(path string) (*Daypack, error) {
	f, err := os.Open(path)
	if err != nil {
		return nil, err
	}
	defer f.Close()

	var hdr Header
	if err := binary.Read(f, binary.LittleEndian, &hdr); err != nil {
		return nil, fmt.Errorf("read header: %w", err)
	}
	if hdr.Magic != [4]byte{'G', 'S', 'I', 'N'} {
		return nil, fmt.Errorf("bad magic: %v", hdr.Magic)
	}

	ticks := make([]Tick, TotalTicks)
	for i := 0; i < TotalTicks; i++ {
		countBuf := []byte{0}
		if _, err := io.ReadFull(f, countBuf); err != nil {
			return nil, fmt.Errorf("tick %d count: %w", i, err)
		}
		count := int(countBuf[0])
		events := make([]Event, count)
		for j := 0; j < count; j++ {
			meta := make([]byte, 3)
			if _, err := io.ReadFull(f, meta); err != nil {
				return nil, fmt.Errorf("tick %d event %d meta: %w", i, j, err)
			}
			textLen := int(meta[2])
			text := make([]byte, textLen)
			if _, err := io.ReadFull(f, text); err != nil {
				return nil, fmt.Errorf("tick %d event %d text: %w", i, j, err)
			}
			events[j] = Event{
				TypeID: meta[0],
				Weight: meta[1],
				Text:   string(text),
			}
		}
		ticks[i] = Tick{Events: events}
	}

	return &Daypack{Header: hdr, Ticks: ticks}, nil
}
```

- [ ] **Step 4: 运行测试确认通过**

```bash
cd src/ghsingo && go test ./internal/archive/ -v
```

预期: 3 passed

- [ ] **Step 5: 提交**

```bash
jj describe -m 'feat(ghsingo): day-pack binary format read/write (#17)'
jj new
```

---

## Task 3: GH Archive JSON 解析 + 过滤 + 分桶

**Files:**
- Create: `src/ghsingo/internal/archive/parse.go`
- Create: `src/ghsingo/internal/archive/parse_test.go`

- [ ] **Step 1: 编写解析测试 (用内存中的 gzip JSON)**

```go
// internal/archive/parse_test.go
package archive

import (
	"bytes"
	"compress/gzip"
	"encoding/json"
	"testing"
)

func makeTestGzip(t *testing.T, events []map[string]any) []byte {
	t.Helper()
	var buf bytes.Buffer
	gz := gzip.NewWriter(&buf)
	for _, evt := range events {
		line, _ := json.Marshal(evt)
		gz.Write(line)
		gz.Write([]byte("\n"))
	}
	gz.Close()
	return buf.Bytes()
}

func TestParseGzipEvents(t *testing.T) {
	raw := []map[string]any{
		{"type": "PushEvent", "repo": map[string]any{"name": "user/repo1"}, "actor": map[string]any{"login": "alice"}, "created_at": "2026-03-28T11:00:00Z", "id": "1"},
		{"type": "PushEvent", "repo": map[string]any{"name": "user/repo2"}, "actor": map[string]any{"login": "bob"}, "created_at": "2026-03-28T11:00:00Z", "id": "2"},
		{"type": "WatchEvent", "repo": map[string]any{"name": "user/repo3"}, "actor": map[string]any{"login": "eve"}, "created_at": "2026-03-28T11:00:01Z", "id": "3"},
		{"type": "ReleaseEvent", "repo": map[string]any{"name": "org/proj"}, "actor": map[string]any{"login": "carol"}, "created_at": "2026-03-28T11:00:01Z", "id": "4"},
	}
	data := makeTestGzip(t, raw)

	allowedTypes := map[string]bool{
		"PushEvent": true, "CreateEvent": true, "IssuesEvent": true,
		"PullRequestEvent": true, "ForkEvent": true, "ReleaseEvent": true,
	}
	weights := map[string]int{
		"PushEvent": 30, "CreateEvent": 40, "IssuesEvent": 50,
		"PullRequestEvent": 70, "ForkEvent": 80, "ReleaseEvent": 100,
	}

	events, err := ParseGzipEvents(bytes.NewReader(data), allowedTypes, weights)
	if err != nil {
		t.Fatalf("ParseGzipEvents: %v", err)
	}

	// WatchEvent should be filtered out
	if len(events) != 3 {
		t.Fatalf("got %d events, want 3", len(events))
	}
	// Check that ReleaseEvent has higher weight
	for _, e := range events {
		if e.EventType == "ReleaseEvent" && e.BaseWeight != 100 {
			t.Errorf("ReleaseEvent weight = %d, want 100", e.BaseWeight)
		}
	}
}

func TestBucketAndSelectTopN(t *testing.T) {
	events := []ParsedEvent{
		{Second: 0, EventType: "PushEvent", BaseWeight: 30, Repo: "a/1", Text: "a/1/aaa"},
		{Second: 0, EventType: "PushEvent", BaseWeight: 30, Repo: "a/2", Text: "a/2/bbb"},
		{Second: 0, EventType: "IssuesEvent", BaseWeight: 50, Repo: "a/3", Text: "a/3/ccc"},
		{Second: 0, EventType: "ReleaseEvent", BaseWeight: 100, Repo: "a/4", Text: "a/4/ddd"},
		{Second: 0, EventType: "ForkEvent", BaseWeight: 80, Repo: "a/5", Text: "a/5/eee"},
	}

	ticks := BucketAndSelect(events, 4, 600)

	if len(ticks[0].Events) != 4 {
		t.Fatalf("tick[0] events = %d, want 4", len(ticks[0].Events))
	}
	// Highest weight should be first
	if ticks[0].Events[0].TypeID != 5 { // ReleaseEvent = type_id 5
		t.Errorf("first event TypeID = %d, want 5 (ReleaseEvent)", ticks[0].Events[0].TypeID)
	}
}
```

- [ ] **Step 2: 运行测试确认失败**

```bash
cd src/ghsingo && go test ./internal/archive/ -v -run 'TestParse|TestBucket'
```

预期: FAIL — `ParseGzipEvents`, `ParsedEvent`, `BucketAndSelect` 未定义

- [ ] **Step 3: 实现解析模块**

```go
// internal/archive/parse.go
package archive

import (
	"bufio"
	"compress/gzip"
	"encoding/json"
	"fmt"
	"io"
	"sort"
	"time"
)

type ParsedEvent struct {
	Second     int    // 0~86399
	EventType  string
	BaseWeight int
	Repo       string
	Actor      string
	Text       string
	ID         string
}

type rawEvent struct {
	Type      string `json:"type"`
	Repo      struct {
		Name string `json:"name"`
	} `json:"repo"`
	Actor struct {
		Login string `json:"login"`
	} `json:"actor"`
	CreatedAt string `json:"created_at"`
	ID        string `json:"id"`
}

func ParseGzipEvents(r io.Reader, allowedTypes map[string]bool, weights map[string]int) ([]ParsedEvent, error) {
	gz, err := gzip.NewReader(r)
	if err != nil {
		return nil, fmt.Errorf("gzip open: %w", err)
	}
	defer gz.Close()

	var result []ParsedEvent
	scanner := bufio.NewScanner(gz)
	scanner.Buffer(make([]byte, 1<<20), 1<<20) // 1MB line buffer

	for scanner.Scan() {
		var raw rawEvent
		if err := json.Unmarshal(scanner.Bytes(), &raw); err != nil {
			continue // skip malformed lines
		}
		if !allowedTypes[raw.Type] {
			continue
		}
		t, err := time.Parse(time.RFC3339, raw.CreatedAt)
		if err != nil {
			continue
		}
		sec := t.Hour()*3600 + t.Minute()*60 + t.Second()

		text := raw.Repo.Name + "/" + raw.ID
		if len(text) > MaxTextLen {
			text = text[:MaxTextLen]
		}

		result = append(result, ParsedEvent{
			Second:     sec,
			EventType:  raw.Type,
			BaseWeight: weights[raw.Type],
			Repo:       raw.Repo.Name,
			Actor:      raw.Actor.Login,
			Text:       text,
			ID:         raw.ID,
		})
	}
	return result, scanner.Err()
}

func BucketAndSelect(events []ParsedEvent, maxPerSec int, dedupeWindowSecs int) []Tick {
	// Sort by second, then by weight desc
	sort.Slice(events, func(i, j int) bool {
		if events[i].Second != events[j].Second {
			return events[i].Second < events[j].Second
		}
		return events[i].BaseWeight > events[j].BaseWeight
	})

	ticks := make([]Tick, TotalTicks)
	// Track last-seen second per repo for dedup
	repoLastSeen := make(map[string]int)

	buckets := make(map[int][]ParsedEvent)
	for _, e := range events {
		buckets[e.Second] = append(buckets[e.Second], e)
	}

	// Find max weight for normalization
	maxWeight := 1
	for _, e := range events {
		if e.BaseWeight > maxWeight {
			maxWeight = e.BaseWeight
		}
	}

	for sec := 0; sec < TotalTicks; sec++ {
		bucket := buckets[sec]
		// Already sorted by weight desc from the overall sort
		var selected []Event
		for _, e := range bucket {
			if len(selected) >= maxPerSec {
				break
			}
			// Dedup: skip if same repo seen within window
			if lastSec, ok := repoLastSeen[e.Repo]; ok {
				if sec-lastSec < dedupeWindowSecs {
					continue
				}
			}
			typeID, ok := EventTypeID[e.EventType]
			if !ok {
				continue
			}
			// Normalize weight to 0~255
			w := uint8(e.BaseWeight * 255 / maxWeight)

			selected = append(selected, Event{
				TypeID: typeID,
				Weight: w,
				Text:   e.Text,
			})
			repoLastSeen[e.Repo] = sec
		}
		ticks[sec] = Tick{Events: selected}
	}
	return ticks
}

// EventTypeID is imported from config package but duplicated here
// to avoid circular dependency. Keep in sync.
var EventTypeID = map[string]uint8{
	"PushEvent":        0,
	"CreateEvent":      1,
	"IssuesEvent":      2,
	"PullRequestEvent": 3,
	"ForkEvent":        4,
	"ReleaseEvent":     5,
}
```

- [ ] **Step 4: 运行测试确认通过**

```bash
cd src/ghsingo && go test ./internal/archive/ -v
```

预期: all passed

- [ ] **Step 5: 提交**

```bash
jj describe -m 'feat(ghsingo): GH Archive JSON parse + filter + bucket (#17)'
jj new
```

---

## Task 4: prepare CLI 二进制

**Files:**
- Create: `src/ghsingo/cmd/prepare/main.go`

- [ ] **Step 1: 实现 prepare 入口**

```go
// cmd/prepare/main.go
package main

import (
	"encoding/json"
	"flag"
	"fmt"
	"log/slog"
	"os"
	"path/filepath"
	"strings"

	"github.com/41490/chao5whistler/src/ghsingo/internal/archive"
	"github.com/41490/chao5whistler/src/ghsingo/internal/config"
)

func main() {
	configPath := flag.String("config", "ghsingo.toml", "path to config file")
	flag.Parse()

	cfg, err := config.Load(*configPath)
	if err != nil {
		slog.Error("load config", "err", err)
		os.Exit(1)
	}

	slog.Info("prepare starting", "profile", cfg.Meta.Profile, "target_date", cfg.Archive.TargetDate)

	// Resolve target date
	targetDate := cfg.Archive.TargetDate
	if targetDate == "yesterday" {
		// For MVP: expect caller to pass explicit date or use ops/assets
		slog.Error("target_date=yesterday not yet implemented, use explicit date like 2026-03-28")
		os.Exit(1)
	}

	// Build allowed types and weights maps
	allowedTypes := make(map[string]bool)
	for _, t := range cfg.Events.Types {
		allowedTypes[t] = true
	}

	// Find source .json.gz files
	// Pattern: source_dir/YYYY-MM-DD-{H}.json.gz
	var gzFiles []string
	for h := 0; h < 24; h++ {
		name := fmt.Sprintf("%s-%d.json.gz", targetDate, h)
		path := filepath.Join(cfg.Archive.SourceDir, name)
		if _, err := os.Stat(path); err == nil {
			gzFiles = append(gzFiles, path)
		}
	}
	if len(gzFiles) == 0 {
		slog.Error("no .json.gz files found", "source_dir", cfg.Archive.SourceDir, "date", targetDate)
		os.Exit(1)
	}
	slog.Info("found source files", "count", len(gzFiles))

	// Parse all files
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

	// Bucket and select
	ticks := archive.BucketAndSelect(allEvents, cfg.Events.MaxPerSecond, cfg.Events.DedupeWindowSecs)

	// Build daypack
	// Parse date to uint32 YYYYMMDD
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

	// Create output directory
	outDir := filepath.Join(cfg.Archive.DaypackDir, targetDate)
	os.MkdirAll(outDir, 0755)

	binPath := filepath.Join(outDir, "day.bin")
	if err := archive.WriteDaypack(binPath, pack); err != nil {
		slog.Error("write daypack", "err", err)
		os.Exit(1)
	}

	// Write manifest
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
```

- [ ] **Step 2: 构建并用样本数据验证**

```bash
cd src/ghsingo && go build -o bin/prepare ./cmd/prepare
./bin/prepare --config ghsingo.toml
# 注意: ghsingo.toml 中 target_date 需改为 "2026-03-28", source_dir 指向 ../../ops/assets
```

预期: 输出 `var/ghsingo/daypack/2026-03-28/day.bin` + `manifest.json`, 日志显示统计信息

- [ ] **Step 3: 提交**

```bash
jj describe -m 'feat(ghsingo): prepare CLI binary (#17)'
jj new
```

---

## Task 5: 回放引擎

**Files:**
- Create: `src/ghsingo/internal/replay/engine.go`
- Create: `src/ghsingo/internal/replay/engine_test.go`

- [ ] **Step 1: 编写回放引擎测试**

```go
// internal/replay/engine_test.go
package replay

import (
	"testing"
	"time"

	"github.com/41490/chao5whistler/src/ghsingo/internal/archive"
)

func TestEngineEmitsTicks(t *testing.T) {
	pack := &archive.Daypack{
		Header: archive.Header{
			Magic:      [4]byte{'G', 'S', 'I', 'N'},
			Version:    1,
			Date:       20260328,
			TotalTicks: 86400,
		},
		Ticks: make([]archive.Tick, 86400),
	}
	pack.Ticks[0] = archive.Tick{
		Events: []archive.Event{
			{TypeID: 0, Weight: 128, Text: "test/repo/aaa"},
		},
	}
	pack.Ticks[1] = archive.Tick{
		Events: []archive.Event{
			{TypeID: 3, Weight: 200, Text: "test/repo/bbb"},
		},
	}

	ch := make(chan Tick, 16)
	eng := New(pack, ch)

	// Run from second 0 for 2 ticks using fast clock
	go eng.RunFrom(0, 2, time.Millisecond) // 1ms per tick for testing

	tick0 := <-ch
	if tick0.Second != 0 {
		t.Errorf("tick0.Second = %d, want 0", tick0.Second)
	}
	if len(tick0.Events) != 1 {
		t.Fatalf("tick0 events = %d, want 1", len(tick0.Events))
	}
	if tick0.Events[0].Text != "test/repo/aaa" {
		t.Errorf("tick0 text = %q", tick0.Events[0].Text)
	}

	tick1 := <-ch
	if tick1.Second != 1 {
		t.Errorf("tick1.Second = %d, want 1", tick1.Second)
	}

	// Channel should be closed after maxTicks
	_, open := <-ch
	if open {
		t.Error("channel should be closed after maxTicks")
	}
}

func TestEngineWrapsAtEndOfDay(t *testing.T) {
	pack := &archive.Daypack{
		Header: archive.Header{
			Magic:      [4]byte{'G', 'S', 'I', 'N'},
			Version:    1,
			Date:       20260328,
			TotalTicks: 86400,
		},
		Ticks: make([]archive.Tick, 86400),
	}
	pack.Ticks[86399] = archive.Tick{
		Events: []archive.Event{
			{TypeID: 5, Weight: 255, Text: "last/second"},
		},
	}
	pack.Ticks[0] = archive.Tick{
		Events: []archive.Event{
			{TypeID: 0, Weight: 100, Text: "first/second"},
		},
	}

	ch := make(chan Tick, 16)
	eng := New(pack, ch)

	// Start at 86399, run 3 ticks → should wrap to 0, 1
	go eng.RunFrom(86399, 3, time.Millisecond)

	t0 := <-ch
	if t0.Second != 86399 {
		t.Errorf("t0.Second = %d, want 86399", t0.Second)
	}
	t1 := <-ch
	if t1.Second != 0 {
		t.Errorf("t1.Second = %d, want 0 (wrapped)", t1.Second)
	}
}
```

- [ ] **Step 2: 运行测试确认失败**

```bash
cd src/ghsingo && go test ./internal/replay/ -v
```

预期: FAIL

- [ ] **Step 3: 实现回放引擎**

```go
// internal/replay/engine.go
package replay

import (
	"time"

	"github.com/41490/chao5whistler/src/ghsingo/internal/archive"
)

type Tick struct {
	Second int
	Events []archive.Event
}

type Engine struct {
	pack *archive.Daypack
	ch   chan<- Tick
}

func New(pack *archive.Daypack, ch chan<- Tick) *Engine {
	return &Engine{pack: pack, ch: ch}
}

// RunFrom starts emitting ticks from startSec.
// tickInterval controls pacing (use time.Second for real-time, shorter for tests).
// maxTicks = 0 means infinite (wrap around at end of day).
func (e *Engine) RunFrom(startSec int, maxTicks int, tickInterval time.Duration) {
	defer close(e.ch)

	sec := startSec
	emitted := 0
	ticker := time.NewTicker(tickInterval)
	defer ticker.Stop()

	for {
		if maxTicks > 0 && emitted >= maxTicks {
			return
		}

		<-ticker.C

		idx := sec % archive.TotalTicks
		t := e.pack.Ticks[idx]
		e.ch <- Tick{
			Second: idx,
			Events: t.Events,
		}

		sec++
		emitted++
	}
}

// CurrentSecond returns the second-of-day for the current wall clock.
func CurrentSecond() int {
	now := time.Now()
	return now.Hour()*3600 + now.Minute()*60 + now.Second()
}
```

- [ ] **Step 4: 运行测试确认通过**

```bash
cd src/ghsingo && go test ./internal/replay/ -v
```

预期: all passed

- [ ] **Step 5: 提交**

```bash
jj describe -m 'feat(ghsingo): replay engine with tick emission (#17)'
jj new
```

---

## Task 6: 音频混音器

**Files:**
- Create: `src/ghsingo/internal/audio/mixer.go`
- Create: `src/ghsingo/internal/audio/mixer_test.go`

- [ ] **Step 1: 编写混音器测试**

```go
// internal/audio/mixer_test.go
package audio

import (
	"math"
	"testing"
)

func TestLoadWavSamples(t *testing.T) {
	// Generate a minimal WAV in memory for testing
	wav := generateTestWAV(44100, 2, 4410) // 0.1s stereo
	samples, err := DecodePCM(wav)
	if err != nil {
		t.Fatalf("DecodePCM: %v", err)
	}
	if len(samples) != 4410*2 {
		t.Errorf("samples len = %d, want %d", len(samples), 4410*2)
	}
}

func TestMixerBGMLoop(t *testing.T) {
	// BGM: 100 samples, all 0.5
	bgm := make([]float32, 100)
	for i := range bgm {
		bgm[i] = 0.5
	}

	m := NewMixer(44100, 30)
	m.SetBGM(bgm, 1.0) // gain = 1.0 (0dB)

	// Render 150 samples — should loop the 100-sample BGM
	out := m.RenderFrame(nil)
	// 44100/30 = 1470 samples per frame, stereo = 2940
	if len(out) != 1470*2 {
		t.Fatalf("frame len = %d, want %d", len(out), 1470*2)
	}
	// First sample should be 0.5 * gain
	if math.Abs(float64(out[0])-0.5) > 0.01 {
		t.Errorf("out[0] = %f, want ~0.5", out[0])
	}
}

func TestMixerVoiceTrigger(t *testing.T) {
	// Voice sample: 500 samples of 0.3
	voice := make([]float32, 500)
	for i := range voice {
		voice[i] = 0.3
	}

	m := NewMixer(44100, 30)
	m.RegisterVoice(0, voice, 1.0) // type_id=0, gain=1.0

	// Trigger event
	m.TriggerEvent(0, 128) // type_id=0, weight=128

	out := m.RenderFrame(nil)
	// Should contain the voice mixed in
	if out[0] == 0 {
		t.Error("out[0] should be non-zero after triggering voice")
	}
}

func TestMixerClamp(t *testing.T) {
	m := NewMixer(44100, 30)
	// Set BGM to very loud
	bgm := make([]float32, 10000)
	for i := range bgm {
		bgm[i] = 0.9
	}
	m.SetBGM(bgm, 1.0)

	// Also trigger a loud voice
	voice := make([]float32, 5000)
	for i := range voice {
		voice[i] = 0.9
	}
	m.RegisterVoice(0, voice, 1.0)
	m.TriggerEvent(0, 255)

	out := m.RenderFrame(nil)
	for i, s := range out {
		if s > 1.0 || s < -1.0 {
			t.Fatalf("sample[%d] = %f, exceeds [-1, 1]", i, s)
		}
	}
}

// generateTestWAV creates a minimal valid WAV byte slice.
func generateTestWAV(sampleRate, channels, numSamples int) []byte {
	dataSize := numSamples * channels * 2 // 16-bit
	fileSize := 44 + dataSize
	buf := make([]byte, fileSize)

	// RIFF header
	copy(buf[0:4], "RIFF")
	le32(buf[4:8], uint32(fileSize-8))
	copy(buf[8:12], "WAVE")

	// fmt chunk
	copy(buf[12:16], "fmt ")
	le32(buf[16:20], 16) // chunk size
	le16(buf[20:22], 1)  // PCM
	le16(buf[22:24], uint16(channels))
	le32(buf[24:28], uint32(sampleRate))
	le32(buf[28:32], uint32(sampleRate*channels*2)) // byte rate
	le16(buf[32:34], uint16(channels*2))             // block align
	le16(buf[34:36], 16)                             // bits per sample

	// data chunk
	copy(buf[36:40], "data")
	le32(buf[40:44], uint32(dataSize))

	// Fill with a 440Hz sine wave
	for i := 0; i < numSamples; i++ {
		val := int16(10000 * math.Sin(2*math.Pi*440*float64(i)/float64(sampleRate)))
		for ch := 0; ch < channels; ch++ {
			off := 44 + (i*channels+ch)*2
			le16(buf[off:off+2], uint16(val))
		}
	}
	return buf
}

func le16(b []byte, v uint16) { b[0] = byte(v); b[1] = byte(v >> 8) }
func le32(b []byte, v uint32) { b[0] = byte(v); b[1] = byte(v >> 8); b[2] = byte(v >> 16); b[3] = byte(v >> 24) }
```

- [ ] **Step 2: 运行测试确认失败**

```bash
cd src/ghsingo && go test ./internal/audio/ -v
```

预期: FAIL

- [ ] **Step 3: 实现混音器**

```go
// internal/audio/mixer.go
package audio

import (
	"bytes"
	"encoding/binary"
	"fmt"
	"io"
	"math"
	"os"
)

type Mixer struct {
	sampleRate     int
	fps            int
	samplesPerFrame int

	bgmPCM    []float32
	bgmGain   float32
	bgmPos    int

	voices    map[uint8]voiceBank // type_id → voice data
	active    []activeVoice       // currently playing instances
}

type voiceBank struct {
	pcm  []float32
	gain float32
}

type activeVoice struct {
	typeID uint8
	weight uint8
	offset int
}

func NewMixer(sampleRate, fps int) *Mixer {
	return &Mixer{
		sampleRate:      sampleRate,
		fps:             fps,
		samplesPerFrame: sampleRate / fps,
		voices:          make(map[uint8]voiceBank),
	}
}

func (m *Mixer) SetBGM(pcm []float32, gain float32) {
	m.bgmPCM = pcm
	m.bgmGain = gain
	m.bgmPos = 0
}

func (m *Mixer) RegisterVoice(typeID uint8, pcm []float32, gain float32) {
	m.voices[typeID] = voiceBank{pcm: pcm, gain: gain}
}

func (m *Mixer) TriggerEvent(typeID uint8, weight uint8) {
	if _, ok := m.voices[typeID]; !ok {
		return
	}
	m.active = append(m.active, activeVoice{
		typeID: typeID,
		weight: weight,
		offset: 0,
	})
}

// RenderFrame renders one frame of stereo interleaved PCM (float32).
// events can be nil if no new events this frame.
func (m *Mixer) RenderFrame(events []struct{ TypeID, Weight uint8 }) []float32 {
	for _, e := range events {
		m.TriggerEvent(e.TypeID, e.Weight)
	}

	n := m.samplesPerFrame
	out := make([]float32, n*2) // stereo interleaved

	// Mix BGM
	if len(m.bgmPCM) > 0 {
		for i := 0; i < n; i++ {
			// BGM is mono or stereo — treat as mono for simplicity, duplicate to both channels
			idx := m.bgmPos % len(m.bgmPCM)
			val := m.bgmPCM[idx] * m.bgmGain
			out[i*2] += val   // left
			out[i*2+1] += val // right
			m.bgmPos++
		}
	}

	// Mix active voices
	var remaining []activeVoice
	for _, av := range m.active {
		bank := m.voices[av.typeID]
		weightScale := float32(av.weight) / 255.0
		for i := 0; i < n; i++ {
			if av.offset >= len(bank.pcm) {
				break
			}
			val := bank.pcm[av.offset] * bank.gain * weightScale
			out[i*2] += val
			out[i*2+1] += val
			av.offset++
		}
		if av.offset < len(bank.pcm) {
			remaining = append(remaining, av)
		}
	}
	m.active = remaining

	// Clamp to [-1, 1]
	for i := range out {
		if out[i] > 1.0 {
			out[i] = 1.0
		} else if out[i] < -1.0 {
			out[i] = -1.0
		}
	}

	return out
}

// DecodePCM reads a WAV file and returns interleaved float32 samples.
func DecodePCM(data []byte) ([]float32, error) {
	r := bytes.NewReader(data)

	// Read RIFF header
	var riffID [4]byte
	binary.Read(r, binary.LittleEndian, &riffID)
	if string(riffID[:]) != "RIFF" {
		return nil, fmt.Errorf("not a RIFF file")
	}
	var fileSize uint32
	binary.Read(r, binary.LittleEndian, &fileSize)
	var waveID [4]byte
	binary.Read(r, binary.LittleEndian, &waveID)
	if string(waveID[:]) != "WAVE" {
		return nil, fmt.Errorf("not a WAVE file")
	}

	var channels uint16
	var sampleRate uint32
	var bitsPerSample uint16
	var dataSize uint32

	// Read chunks
	for {
		var chunkID [4]byte
		if err := binary.Read(r, binary.LittleEndian, &chunkID); err != nil {
			if err == io.EOF {
				break
			}
			return nil, err
		}
		var chunkSize uint32
		binary.Read(r, binary.LittleEndian, &chunkSize)

		switch string(chunkID[:]) {
		case "fmt ":
			var audioFormat uint16
			binary.Read(r, binary.LittleEndian, &audioFormat)
			binary.Read(r, binary.LittleEndian, &channels)
			binary.Read(r, binary.LittleEndian, &sampleRate)
			var byteRate uint32
			binary.Read(r, binary.LittleEndian, &byteRate)
			var blockAlign uint16
			binary.Read(r, binary.LittleEndian, &blockAlign)
			binary.Read(r, binary.LittleEndian, &bitsPerSample)
			// Skip any extra fmt bytes
			if chunkSize > 16 {
				r.Seek(int64(chunkSize-16), io.SeekCurrent)
			}
		case "data":
			dataSize = chunkSize
			raw := make([]byte, dataSize)
			io.ReadFull(r, raw)

			numSamples := int(dataSize) / int(channels) / int(bitsPerSample/8)
			result := make([]float32, numSamples*int(channels))

			for i := 0; i < len(result); i++ {
				switch bitsPerSample {
				case 16:
					off := i * 2
					sample := int16(uint16(raw[off]) | uint16(raw[off+1])<<8)
					result[i] = float32(sample) / float32(math.MaxInt16)
				}
			}
			return result, nil
		default:
			r.Seek(int64(chunkSize), io.SeekCurrent)
		}
	}
	return nil, fmt.Errorf("no data chunk found")
}

// LoadWavFile loads a WAV file from disk and returns float32 PCM samples.
func LoadWavFile(path string) ([]float32, error) {
	data, err := os.ReadFile(path)
	if err != nil {
		return nil, err
	}
	return DecodePCM(data)
}

// GainToLinear converts dB to linear scale.
func GainToLinear(db float64) float32 {
	return float32(math.Pow(10, db/20))
}
```

- [ ] **Step 4: 运行测试确认通过**

```bash
cd src/ghsingo && go test ./internal/audio/ -v
```

预期: all passed

- [ ] **Step 5: 提交**

```bash
jj describe -m 'feat(ghsingo): audio mixer with WAV decode + BGM loop (#17)'
jj new
```

---

## Task 7: 视频渲染器

**Files:**
- Create: `src/ghsingo/internal/video/renderer.go`
- Create: `src/ghsingo/internal/video/renderer_test.go`

- [ ] **Step 1: 编写渲染器测试**

```go
// internal/video/renderer_test.go
package video

import (
	"image/color"
	"testing"
)

func TestNewRenderer(t *testing.T) {
	r := New(1280, 720, 30, 180.0, 0.50, 0.95)
	if r.width != 1280 || r.height != 720 {
		t.Errorf("dimensions = %dx%d", r.width, r.height)
	}
}

func TestRenderEmptyFrame(t *testing.T) {
	r := New(1280, 720, 30, 180.0, 0.50, 0.95)
	r.SetPalette("#002b36", "#fdf6e3", "#b58900")
	r.SetFontSizeRange(14, 42)

	rgba := r.RenderFrame()
	if rgba == nil {
		t.Fatal("RenderFrame returned nil")
	}
	if rgba.Bounds().Dx() != 1280 || rgba.Bounds().Dy() != 720 {
		t.Errorf("frame size = %v", rgba.Bounds())
	}
	// Background pixel should be Solarized Dark base03 (#002b36)
	px := rgba.At(0, 0)
	rr, gg, bb, _ := px.RGBA()
	// #002b36 = R:0, G:43, B:54
	if rr>>8 != 0 || gg>>8 != 43 || bb>>8 != 54 {
		t.Errorf("background color = (%d, %d, %d), want (0, 43, 54)", rr>>8, gg>>8, bb>>8)
	}
}

func TestSpawnAndDespawn(t *testing.T) {
	r := New(1280, 720, 30, 180.0, 0.50, 0.95)
	r.SetPalette("#002b36", "#fdf6e3", "#b58900")
	r.SetFontSizeRange(14, 42)

	r.SpawnText("test/text", 128)
	if len(r.floaters) != 1 {
		t.Fatalf("floaters = %d, want 1", len(r.floaters))
	}

	// Render enough frames to move text off screen (720px / 180px/s * 30fps = 120 frames)
	for i := 0; i < 150; i++ {
		r.RenderFrame()
	}
	// Floater should be despawned
	if len(r.floaters) != 0 {
		t.Errorf("floaters = %d after 150 frames, want 0 (despawned)", len(r.floaters))
	}
}

func TestParseHexColor(t *testing.T) {
	c := parseHex("#002b36")
	want := color.RGBA{R: 0, G: 43, B: 54, A: 255}
	if c != want {
		t.Errorf("parseHex(#002b36) = %v, want %v", c, want)
	}
}
```

- [ ] **Step 2: 运行测试确认失败**

```bash
cd src/ghsingo && go test ./internal/video/ -v
```

预期: FAIL

- [ ] **Step 3: 实现视频渲染器**

```go
// internal/video/renderer.go
package video

import (
	"fmt"
	"image"
	"image/color"
	"math/rand/v2"
	"strconv"

	"github.com/fogleman/gg"
)

type floater struct {
	text     string
	x, y     float64
	fontSize float64
	alpha    float64
	speed    float64
}

type Renderer struct {
	width, height int
	fps           int
	speed         float64
	spawnYMin     float64
	spawnYMax     float64
	fontSizeMin   int
	fontSizeMax   int

	bgColor     color.RGBA
	textColor   color.RGBA
	accentColor color.RGBA

	fontPath string
	floaters []*floater
}

func New(width, height, fps int, speed, spawnYMin, spawnYMax float64) *Renderer {
	return &Renderer{
		width:     width,
		height:    height,
		fps:       fps,
		speed:     speed,
		spawnYMin: spawnYMin,
		spawnYMax: spawnYMax,
	}
}

func (r *Renderer) SetPalette(bg, text, accent string) {
	r.bgColor = parseHex(bg)
	r.textColor = parseHex(text)
	r.accentColor = parseHex(accent)
}

func (r *Renderer) SetFontSizeRange(min, max int) {
	r.fontSizeMin = min
	r.fontSizeMax = max
}

func (r *Renderer) SetFontPath(path string) {
	r.fontPath = path
}

func (r *Renderer) SpawnText(text string, weight uint8) {
	ratio := float64(weight) / 255.0
	fontSize := float64(r.fontSizeMin) + ratio*float64(r.fontSizeMax-r.fontSizeMin)
	x := rand.Float64() * float64(r.width)
	yMin := r.spawnYMin * float64(r.height)
	yMax := r.spawnYMax * float64(r.height)
	y := yMin + rand.Float64()*(yMax-yMin)

	r.floaters = append(r.floaters, &floater{
		text:     text,
		x:        x,
		y:        y,
		fontSize: fontSize,
		alpha:    220.0,
		speed:    r.speed,
	})
}

func (r *Renderer) RenderFrame() *image.RGBA {
	dc := gg.NewContext(r.width, r.height)

	// Background
	dc.SetColor(r.bgColor)
	dc.Clear()

	// Update and draw floaters
	dt := 1.0 / float64(r.fps)
	var alive []*floater
	for _, f := range r.floaters {
		// Move upward
		f.y -= f.speed * dt
		// Fade: proportional to remaining travel
		totalTravel := r.spawnYMax * float64(r.height)
		if totalTravel > 0 {
			f.alpha = 220.0 * (f.y / totalTravel)
		}
		if f.alpha < 0 {
			f.alpha = 0
		}

		// Despawn conditions
		if f.y < 0 || f.alpha <= 0 {
			continue
		}

		// Draw text
		a := uint8(f.alpha)
		tc := color.RGBA{R: r.textColor.R, G: r.textColor.G, B: r.textColor.B, A: a}
		dc.SetColor(tc)

		// Use built-in font if no font path (for testing)
		if r.fontPath != "" {
			dc.LoadFontFace(r.fontPath, f.fontSize)
		}
		dc.DrawStringAnchored(f.text, f.x, f.y, 0.5, 0.5)

		alive = append(alive, f)
	}
	r.floaters = alive

	return dc.Image().(*image.RGBA)
}

// RenderFrameRaw returns raw RGBA pixel bytes for piping to FFmpeg.
func (r *Renderer) RenderFrameRaw() []byte {
	img := r.RenderFrame()
	return img.Pix
}

func parseHex(hex string) color.RGBA {
	if len(hex) == 7 && hex[0] == '#' {
		hex = hex[1:]
	}
	if len(hex) != 6 {
		return color.RGBA{A: 255}
	}
	r, _ := strconv.ParseUint(hex[0:2], 16, 8)
	g, _ := strconv.ParseUint(hex[2:4], 16, 8)
	b, _ := strconv.ParseUint(hex[4:6], 16, 8)
	return color.RGBA{R: uint8(r), G: uint8(g), B: uint8(b), A: 255}
}

// Ensure fmt is used (for future error messages)
var _ = fmt.Sprintf
```

- [ ] **Step 4: 安装依赖并运行测试**

```bash
cd src/ghsingo && go get github.com/fogleman/gg@v1.3.0 && go test ./internal/video/ -v
```

预期: all passed

- [ ] **Step 5: 提交**

```bash
jj describe -m 'feat(ghsingo): video renderer with floating text (#17)'
jj new
```

---

## Task 8: FFmpeg 流管理器

**Files:**
- Create: `src/ghsingo/internal/stream/ffmpeg.go`
- Create: `src/ghsingo/internal/stream/ffmpeg_test.go`

- [ ] **Step 1: 编写流管理器测试**

```go
// internal/stream/ffmpeg_test.go
package stream

import (
	"os/exec"
	"testing"
)

func TestBuildLocalArgs(t *testing.T) {
	args := BuildArgs(Options{
		Width:           1280,
		Height:          720,
		FPS:             30,
		VideoPreset:     "ultrafast",
		AudioBitrateKbps: 128,
		SampleRate:      44100,
		Mode:            "local",
		OutputPath:      "/tmp/test.flv",
	})

	// Should contain key args
	assertContains(t, args, "-f", "rawvideo")
	assertContains(t, args, "-pix_fmt", "rgba")
	assertContains(t, args, "-s", "1280x720")
	assertContains(t, args, "-preset", "ultrafast")
	assertContains(t, args, "-b:a", "128k")

	// Last arg should be output path
	last := args[len(args)-1]
	if last != "/tmp/test.flv" {
		t.Errorf("last arg = %q, want /tmp/test.flv", last)
	}
}

func TestBuildRTMPSArgs(t *testing.T) {
	args := BuildArgs(Options{
		Width:           1280,
		Height:          720,
		FPS:             30,
		VideoPreset:     "ultrafast",
		AudioBitrateKbps: 128,
		SampleRate:      44100,
		Mode:            "rtmps",
		RTMPSURL:        "rtmps://a.rtmps.youtube.com/live2/KEY",
	})

	last := args[len(args)-1]
	if last != "rtmps://a.rtmps.youtube.com/live2/KEY" {
		t.Errorf("last arg = %q, want rtmps URL", last)
	}
	// Should contain flv container
	assertContains(t, args, "-f", "flv")
}

func TestFFmpegExists(t *testing.T) {
	_, err := exec.LookPath("ffmpeg")
	if err != nil {
		t.Skip("ffmpeg not installed")
	}
}

func assertContains(t *testing.T, args []string, key, val string) {
	t.Helper()
	for i, a := range args {
		if a == key && i+1 < len(args) && args[i+1] == val {
			return
		}
	}
	t.Errorf("args missing %s %s", key, val)
}
```

- [ ] **Step 2: 运行测试确认失败**

```bash
cd src/ghsingo && go test ./internal/stream/ -v
```

预期: FAIL

- [ ] **Step 3: 实现流管理器**

```go
// internal/stream/ffmpeg.go
package stream

import (
	"fmt"
	"io"
	"log/slog"
	"os"
	"os/exec"
)

type Options struct {
	Width            int
	Height           int
	FPS              int
	VideoPreset      string
	AudioBitrateKbps int
	SampleRate       int
	Mode             string // "local" or "rtmps"
	OutputPath       string // for mode=local
	RTMPSURL         string // for mode=rtmps
}

func BuildArgs(opts Options) []string {
	size := fmt.Sprintf("%dx%d", opts.Width, opts.Height)
	rate := fmt.Sprintf("%d", opts.FPS)
	abitrate := fmt.Sprintf("%dk", opts.AudioBitrateKbps)
	sampleRate := fmt.Sprintf("%d", opts.SampleRate)

	args := []string{
		// Video input: raw RGBA from pipe:0
		"-f", "rawvideo",
		"-pix_fmt", "rgba",
		"-s", size,
		"-r", rate,
		"-i", "pipe:0",
		// Audio input: raw PCM float32 LE stereo from pipe:3
		"-f", "f32le",
		"-ar", sampleRate,
		"-ac", "2",
		"-i", "pipe:3",
		// Video encoding
		"-c:v", "libx264",
		"-preset", opts.VideoPreset,
		"-tune", "zerolatency",
		"-pix_fmt", "yuv420p",
		"-g", fmt.Sprintf("%d", opts.FPS*2), // keyframe every 2s
		// Audio encoding
		"-c:a", "aac",
		"-b:a", abitrate,
		// General
		"-shortest",
		"-y", // overwrite
	}

	switch opts.Mode {
	case "rtmps":
		args = append(args, "-f", "flv")
		args = append(args, opts.RTMPSURL)
	default: // local
		args = append(args, opts.OutputPath)
	}

	return args
}

type Manager struct {
	opts    Options
	cmd     *exec.Cmd
	video   io.WriteCloser // pipe:0
	audio   io.WriteCloser // pipe:3
}

func NewManager(opts Options) *Manager {
	return &Manager{opts: opts}
}

func (m *Manager) Start() error {
	args := BuildArgs(m.opts)
	m.cmd = exec.Command("ffmpeg", args...)

	// pipe:0 = stdin for video
	videoPipe, err := m.cmd.StdinPipe()
	if err != nil {
		return fmt.Errorf("video pipe: %w", err)
	}
	m.video = videoPipe

	// pipe:3 = extra fd for audio
	audioR, audioW, err := os.Pipe()
	if err != nil {
		return fmt.Errorf("audio pipe: %w", err)
	}
	m.audio = audioW
	m.cmd.ExtraFiles = []*os.File{audioR} // fd 3

	m.cmd.Stderr = os.Stderr // let FFmpeg errors show

	if err := m.cmd.Start(); err != nil {
		return fmt.Errorf("ffmpeg start: %w", err)
	}

	// Close read end in parent process
	audioR.Close()

	slog.Info("ffmpeg started", "pid", m.cmd.Process.Pid, "mode", m.opts.Mode)
	return nil
}

func (m *Manager) WriteVideo(data []byte) error {
	_, err := m.video.Write(data)
	return err
}

func (m *Manager) WriteAudio(data []byte) error {
	_, err := m.audio.Write(data)
	return err
}

func (m *Manager) Stop() error {
	if m.video != nil {
		m.video.Close()
	}
	if m.audio != nil {
		m.audio.Close()
	}
	if m.cmd != nil {
		return m.cmd.Wait()
	}
	return nil
}
```

- [ ] **Step 4: 运行测试确认通过**

```bash
cd src/ghsingo && go test ./internal/stream/ -v
```

预期: all passed (FFmpegExists may skip if no ffmpeg)

- [ ] **Step 5: 提交**

```bash
jj describe -m 'feat(ghsingo): FFmpeg stream manager with dual pipe (#17)'
jj new
```

---

## Task 9: live CLI 二进制

**Files:**
- Create: `src/ghsingo/cmd/live/main.go`

- [ ] **Step 1: 实现 live 入口**

```go
// cmd/live/main.go
package main

import (
	"encoding/binary"
	"flag"
	"fmt"
	"log/slog"
	"math"
	"os"
	"path/filepath"
	"sort"
	"strings"
	"time"

	"github.com/41490/chao5whistler/src/ghsingo/internal/archive"
	"github.com/41490/chao5whistler/src/ghsingo/internal/audio"
	"github.com/41490/chao5whistler/src/ghsingo/internal/config"
	"github.com/41490/chao5whistler/src/ghsingo/internal/replay"
	"github.com/41490/chao5whistler/src/ghsingo/internal/stream"
	"github.com/41490/chao5whistler/src/ghsingo/internal/video"
)

func main() {
	configPath := flag.String("config", "ghsingo.toml", "path to config file")
	flag.Parse()

	cfg, err := config.Load(*configPath)
	if err != nil {
		slog.Error("load config", "err", err)
		os.Exit(1)
	}

	slog.Info("live starting", "profile", cfg.Meta.Profile, "output_mode", cfg.Output.Mode)

	// 1. Find latest daypack
	packPath, err := findLatestDaypack(cfg.Archive.DaypackDir)
	if err != nil {
		slog.Error("find daypack", "err", err)
		os.Exit(1)
	}
	slog.Info("using daypack", "path", packPath)

	pack, err := archive.ReadDaypack(packPath)
	if err != nil {
		slog.Error("read daypack", "err", err)
		os.Exit(1)
	}

	// 2. Load audio assets
	mixer := audio.NewMixer(cfg.Audio.SampleRate, cfg.Video.FPS)

	// Load BGM
	if cfg.Audio.BGM.WavPath != "" {
		bgmPCM, err := audio.LoadWavFile(cfg.Audio.BGM.WavPath)
		if err != nil {
			slog.Warn("BGM load failed, continuing without", "err", err)
		} else {
			mixer.SetBGM(bgmPCM, audio.GainToLinear(cfg.Audio.BGM.GainDB))
			slog.Info("BGM loaded", "path", cfg.Audio.BGM.WavPath, "samples", len(bgmPCM))
		}
	}

	// Load voice samples
	for eventType, voice := range cfg.Audio.Voices {
		typeID, ok := config.EventTypeID[eventType]
		if !ok {
			slog.Warn("unknown event type in voices", "type", eventType)
			continue
		}
		pcm, err := audio.LoadWavFile(voice.WavPath)
		if err != nil {
			slog.Error("voice load failed", "type", eventType, "path", voice.WavPath, "err", err)
			os.Exit(1)
		}
		mixer.RegisterVoice(typeID, pcm, audio.GainToLinear(voice.GainDB))
		slog.Info("voice loaded", "type", eventType, "samples", len(pcm))
	}

	// 3. Init video renderer
	renderer := video.New(
		cfg.Video.Width, cfg.Video.Height, cfg.Video.FPS,
		cfg.Video.Motion.SpeedPxPerSec,
		cfg.Video.Motion.SpawnYMin, cfg.Video.Motion.SpawnYMax,
	)
	renderer.SetPalette(
		cfg.Video.Palette.Background,
		cfg.Video.Palette.Text,
		cfg.Video.Palette.Accent,
	)
	renderer.SetFontSizeRange(cfg.Video.FontSizeMin, cfg.Video.FontSizeMax)
	renderer.SetFontPath(cfg.Video.FontPath)

	// 4. Init stream manager
	outputPath := cfg.Output.Local.Path
	if strings.Contains(outputPath, "{date}") {
		outputPath = strings.ReplaceAll(outputPath, "{date}", time.Now().Format("2006-01-02"))
	}
	os.MkdirAll(filepath.Dir(outputPath), 0755)

	mgr := stream.NewManager(stream.Options{
		Width:            cfg.Video.Width,
		Height:           cfg.Video.Height,
		FPS:              cfg.Video.FPS,
		VideoPreset:      cfg.Output.VideoPreset,
		AudioBitrateKbps: cfg.Output.AudioBitrateKbps,
		SampleRate:       cfg.Audio.SampleRate,
		Mode:             cfg.Output.Mode,
		OutputPath:       outputPath,
		RTMPSURL:         cfg.Output.RTMPS.URL,
	})

	if err := mgr.Start(); err != nil {
		slog.Error("ffmpeg start", "err", err)
		os.Exit(1)
	}

	// 5. Start replay engine
	tickCh := make(chan replay.Tick, 4)
	eng := replay.New(pack, tickCh)

	startSec := replay.CurrentSecond()
	go eng.RunFrom(startSec, 0, time.Second) // 0 = infinite

	slog.Info("live streaming", "start_second", startSec)

	// 6. Main render loop
	frameTicker := time.NewTicker(time.Second / time.Duration(cfg.Video.FPS))
	defer frameTicker.Stop()

	statsInterval := time.Duration(cfg.Observe.EmitStatsEverySecs) * time.Second
	statsTicker := time.NewTicker(statsInterval)
	defer statsTicker.Stop()

	var currentTick replay.Tick
	frameCount := 0
	framesPerSec := cfg.Video.FPS

	for {
		select {
		case tick, ok := <-tickCh:
			if !ok {
				slog.Info("replay ended")
				mgr.Stop()
				return
			}
			currentTick = tick
			// Spawn text for new events
			for _, e := range tick.Events {
				renderer.SpawnText(e.Text, e.Weight)
			}

		case <-frameTicker.C:
			// Build event triggers for audio
			var audioEvents []struct{ TypeID, Weight uint8 }
			// Only trigger audio on the first frame of each new second
			if frameCount%framesPerSec == 0 {
				for _, e := range currentTick.Events {
					audioEvents = append(audioEvents, struct{ TypeID, Weight uint8 }{e.TypeID, e.Weight})
				}
				currentTick.Events = nil // clear so we don't re-trigger
			}

			// Render video frame
			rgbaData := renderer.RenderFrameRaw()
			if err := mgr.WriteVideo(rgbaData); err != nil {
				slog.Error("write video", "err", err)
				mgr.Stop()
				return
			}

			// Render audio frame
			pcm := mixer.RenderFrame(audioEvents)
			audioBuf := pcmToBytes(pcm)
			if err := mgr.WriteAudio(audioBuf); err != nil {
				slog.Error("write audio", "err", err)
				mgr.Stop()
				return
			}

			frameCount++

		case <-statsTicker.C:
			slog.Info("stats",
				"frames", frameCount,
				"second", currentTick.Second,
				"uptime", time.Duration(frameCount/cfg.Video.FPS)*time.Second,
			)
		}
	}
}

// pcmToBytes converts float32 PCM to little-endian bytes for FFmpeg f32le input.
func pcmToBytes(pcm []float32) []byte {
	buf := make([]byte, len(pcm)*4)
	for i, s := range pcm {
		bits := math.Float32bits(s)
		binary.LittleEndian.PutUint32(buf[i*4:], bits)
	}
	return buf
}

// findLatestDaypack scans daypack directory for the most recent day.bin.
func findLatestDaypack(dir string) (string, error) {
	entries, err := os.ReadDir(dir)
	if err != nil {
		return "", fmt.Errorf("read daypack dir: %w", err)
	}

	var dates []string
	for _, e := range entries {
		if e.IsDir() {
			binPath := filepath.Join(dir, e.Name(), "day.bin")
			if _, err := os.Stat(binPath); err == nil {
				dates = append(dates, e.Name())
			}
		}
	}
	if len(dates) == 0 {
		return "", fmt.Errorf("no daypack found in %s", dir)
	}

	sort.Strings(dates)
	latest := dates[len(dates)-1]
	return filepath.Join(dir, latest, "day.bin"), nil
}
```

- [ ] **Step 2: 构建**

```bash
cd src/ghsingo && go build -o bin/live ./cmd/live
```

预期: 编译成功

- [ ] **Step 3: 端到端验证 (5秒本地录制)**

```bash
cd src/ghsingo
# 先确保 daypack 存在 (Task 4 已生成)
# 确保 WAV 资源存在 (至少 BGM)
timeout 5 ./bin/live --config ghsingo.toml || true
# 检查是否生成了 .flv 文件
ls -la var/ghsingo/records/
```

预期: 生成一个 .flv 文件 (可能很小, 5秒内容)

- [ ] **Step 4: 提交**

```bash
jj describe -m 'feat(ghsingo): live CLI binary with render loop (#17)'
jj new
```

---

## Task 10: Makefile + systemd units

**Files:**
- Create: `src/ghsingo/Makefile`
- Create: `src/ghsingo/ops/systemd/ghsingo-prepare.service`
- Create: `src/ghsingo/ops/systemd/ghsingo-prepare.timer`
- Create: `src/ghsingo/ops/systemd/ghsingo-live.service`

- [ ] **Step 1: 创建 Makefile**

```makefile
# ghsingo Makefile
# Build, run, and deploy targets for the GH Archive sonification streamer.

.PHONY: build build-prepare build-live prepare-assets \
        run-prepare run-live run-live-5m \
        install-units enable start stop status logs \
        fmt vet test clean

# === Build ===

build: build-prepare build-live

build-prepare:
	go build -o bin/prepare ./cmd/prepare

build-live:
	go build -o bin/live ./cmd/live

# === Asset preparation ===

prepare-assets:
	ffmpeg -i ../../ops/assets/cosmos-leveloop-339.mp3 \
		-ar 44100 -ac 2 -y ../../ops/assets/cosmos-leveloop-339.wav

# === Run ===

run-prepare: build-prepare
	./bin/prepare --config ghsingo.toml

run-live: build-live
	./bin/live --config ghsingo.toml

run-live-5m: build-live
	timeout 300 ./bin/live --config ghsingo.toml

# === Systemd ===

install-units:
	mkdir -p ~/.config/systemd/user
	cp ops/systemd/ghsingo-prepare.service ~/.config/systemd/user/
	cp ops/systemd/ghsingo-prepare.timer ~/.config/systemd/user/
	cp ops/systemd/ghsingo-live.service ~/.config/systemd/user/
	systemctl --user daemon-reload

enable:
	systemctl --user enable ghsingo-live ghsingo-prepare.timer

start:
	systemctl --user start ghsingo-live

stop:
	systemctl --user stop ghsingo-live

status:
	systemctl --user status ghsingo-live ghsingo-prepare.timer

logs:
	journalctl --user -u ghsingo-live -f

# === Development ===

fmt:
	go fmt ./...

vet:
	go vet ./...

test:
	go test ./... -v

clean:
	rm -rf bin/ var/ghsingo/records/
```

- [ ] **Step 2: 创建 systemd units**

`ops/systemd/ghsingo-prepare.service`:
```ini
[Unit]
Description=ghsingo prepare - download and process GH Archive daypack
After=network-online.target
Wants=network-online.target

[Service]
Type=oneshot
WorkingDirectory=%h/src/ghsingo
ExecStart=%h/src/ghsingo/bin/prepare --config %h/src/ghsingo/ghsingo.toml
StandardOutput=journal
StandardError=journal
```

`ops/systemd/ghsingo-prepare.timer`:
```ini
[Unit]
Description=ghsingo prepare daily timer

[Timer]
OnCalendar=*-*-* 02:00:00
Persistent=true
RandomizedDelaySec=300

[Install]
WantedBy=timers.target
```

`ops/systemd/ghsingo-live.service`:
```ini
[Unit]
Description=ghsingo live - GH Archive sonification livestream
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
WorkingDirectory=%h/src/ghsingo
ExecStart=%h/src/ghsingo/bin/live --config %h/src/ghsingo/ghsingo.toml
Restart=on-failure
RestartSec=10
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=default.target
```

- [ ] **Step 3: 验证 Makefile**

```bash
cd src/ghsingo && make build && make test
```

预期: 编译成功, 所有测试通过

- [ ] **Step 4: 提交**

```bash
jj describe -m 'feat(ghsingo): Makefile + systemd units (#17)'
jj new
```

---

## 依赖关系

```
Task 1 (scaffold+config)
  ├─→ Task 2 (daypack format)
  │     └─→ Task 3 (JSON parse)
  │           └─→ Task 4 (prepare CLI)
  ├─→ Task 5 (replay engine) ─────────┐
  ├─→ Task 6 (audio mixer) ───────────┤
  ├─→ Task 7 (video renderer) ────────┼─→ Task 9 (live CLI)
  └─→ Task 8 (stream manager) ────────┘        │
                                                └─→ Task 10 (Makefile+systemd)
```

Task 5/6/7/8 可并行实现 (各自独立, 仅依赖 Task 1 的 config 类型).
Task 9 依赖 Task 2~8 全部完成.
Task 10 依赖 Task 9.
