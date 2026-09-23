# ghsingo 架构设计

> GH Archive 事件声音化 + Go 实时直播推流
>
> 日期: 2026-03-29
> 状态: CTO 已批准, 待实现
> Issue: #17

## 1. 背景

| 世代 | 技术栈 | 时间 | 状态 |
|---|---|---|---|
| ghwhistler | Python + ffmpeg | 2023-11 | 已归档 |
| songh | Rust (7阶段管线) | 2026-03 | 可用, 迭代慢 |
| **ghsingo** | **Go** | **2026-03-29** | **本文档** |

选择 Go 而非 Rust 的理由: 更快的编译速度 (增量编译 1-3s), 更简洁的并发模型
(goroutine + channel), 标准库覆盖面广 (`os/exec`, `io.Pipe`, `image`),
GC 影响可忽略 (<1ms 暂停 vs 33ms/帧).

## 2. 架构决策

以下所有决策均于 2026-03-29 经 CTO 逐条确认。

### D1: 音频模型 — GH Archive 事件映射为海洋生物叫声

GH Archive 事件映射到 6 个预录制的海洋生物 WAV 采样。
背景音乐 (`cosmos-leveloop-339.wav`) 在底层持续循环播放。
golang 架构文档中的 Mozart Dice Game / SoundFont 管风琴方案**不采用**。

### D2: 视频可视化 — Solarized Dark + 浮升文字 (MVP)

MVP 使用 Solarized Dark 纯色背景 + 事件hash文字向上浮升动画。
电影帧马赛克背景推迟到后续迭代。

### D3: 系统架构 — 2阶段分离

- **prepare** (离线): 下载 GH Archive + 预处理为 day-pack 二进制文件
- **live** (在线): 读取 day-pack, 实时音视频合成, 输出到目标

prepare 通过 systemd timer 每日触发。live 作为 7x24 常驻服务运行。
下载失败不会中断正在进行的直播。

### D4: 音频素材 — 预录制 WAV 采样

从 Freesound.org/BBC Sound Effects 获取 CC0 授权的海洋生物音频文件。
存放于 `ops/assets/sounds/`, 通过 .toml 配置事件类型到音频路径的映射。
MVP 不做程序合成。

### D5: BGM 格式 — 构建时 MP3 转 WAV

Makefile 的 `prepare-assets` target 通过 ffmpeg 将 MP3 转换为 WAV。
运行时只处理 WAV PCM, 使用 `go-audio/wav` 读取。

### D6: FFmpeg IPC — 双管道 + 互斥输出

- 视频 RGBA 通过 `pipe:0` (stdin), 音频 PCM 通过 `pipe:3` (额外 fd)
- .toml 中 `output.mode`: `"local"` 或 `"rtmps"`, 二者互斥
- 不使用 tee muxer

### D7: Go 模块结构 — 双 binary + 共享 internal

```
src/ghsingo/
├── go.mod
├── Makefile
├── ghsingo.toml              # 配置模板 (tracked)
├── ghsingo.local.toml        # 本地覆盖 (gitignored)
├── cmd/
│   ├── prepare/main.go       # 离线 CLI
│   └── live/main.go          # 常驻服务
├── internal/
│   ├── config/               # .toml 解析 + 校验
│   ├── archive/              # GH Archive 下载 + 解析
│   ├── replay/               # day-pack 逐秒回放引擎
│   ├── audio/                # WAV 采样加载 + PCM 混音 + BGM 循环
│   ├── video/                # RGBA 帧渲染 (fogleman/gg)
│   └── stream/               # FFmpeg 子进程 + 双管道管理
└── ops/
    └── systemd/              # .service + .timer unit 模板
```

### D8: day-pack — 专用二进制格式

prepare 输出 `day.bin`, live 以零解析开销直接消费。

```
day.bin layout:
┌─────────────────────────────────────────────┐
│ Header (16 bytes)                           │
│   magic: "GSIN" (4B)                        │
│   version: u16                              │
│   date: YYYYMMDD as u32                     │
│   total_ticks: u32 (= 86400)               │
│   reserved: 2B                              │
├─────────────────────────────────────────────┤
│ Tick[0]  second=0                           │
│   count: u8 (0~4)                           │
│   Event[0]: type_id(u8) + weight(u8)        │
│             + text_len(u8) + text([]byte)   │
│   Event[1]: ...                             │
├─────────────────────────────────────────────┤
│ Tick[1]  second=1                           │
│   ...                                       │
├─────────────────────────────────────────────┤
│ ... 共 86400 个 tick                        │
└─────────────────────────────────────────────┘
```

- type_id: u8, 0~5 映射到 6 种事件类型
- weight: u8, 0~255, prepare 阶段已归一化; live 直接用于控制字号和音量
- text: 预截断的显示文本 (如 `user/repo/abc123`), 最大 64 字节 UTF-8
- prepare 阶段完成 top-4 选择、去重、权重归一化、文本截断
- 内存估算: ~18MB (对比原始 JSONL 方案 ~200MB)

### D9: 事件类型 — MVP 6 种高频事件

| type_id | 事件类型 | 基础权重 |
|---|---|---|
| 0 | PushEvent | 30 |
| 1 | CreateEvent | 40 |
| 2 | IssuesEvent | 50 |
| 3 | PullRequestEvent | 70 |
| 4 | ForkEvent | 80 |
| 5 | ReleaseEvent | 100 |

其余事件类型在 prepare 阶段丢弃。

## 3. 系统全景

```
┌─────────────────────────────────────────────────────────────┐
│                    systemd --user                           │
│                                                             │
│  ghsingo-prepare.timer ──→ ghsingo-prepare.service          │
│  (每日触发)                  │                              │
│                              ▼                              │
│                    ┌──────────────┐                         │
│                    │   prepare    │                         │
│                    │   (离线)     │                         │
│                    └──────┬───────┘                         │
│                           │                                 │
│              ┌────────────▼─────────────┐                  │
│              │  var/ghsingo/daypack/    │                   │
│              │  └─ 2026-03-28/         │                   │
│              │     ├─ day.bin          │                   │
│              │     └─ manifest.json    │                   │
│              └────────────┬─────────────┘                  │
│                           │                                 │
│  ghsingo-live.service ────▼                                 │
│  (7x24 常驻)       ┌──────────────┐                        │
│                    │    live      │                         │
│                    └──┬───┬──────┘                          │
│              pipe:0   │   │  pipe:3                         │
│              (RGBA)   │   │  (PCM)                          │
│                    ┌──▼───▼──┐                              │
│                    │  FFmpeg  │                              │
│                    └────┬────┘                              │
│                    ┌────▼────┐                              │
│                    │ output  │                              │
│                    │ .mode   │                              │
│                    ├─────────┤                              │
│                    │ local → var/ghsingo/records/{date}.flv │
│                    │ rtmps → YouTube RTMPS                  │
│                    └─────────┘                              │
└─────────────────────────────────────────────────────────────┘
```

## 4. live 进程内部结构

```
┌─ live process ──────────────────────────────────────────┐
│                                                         │
│  ┌─────────┐    tick chan     ┌──────────────────┐      │
│  │ replay  │ ──────────────→ │    renderer      │      │
│  │ engine  │  Tick{sec,evts} │                  │      │
│  └─────────┘                 │  ┌─────────────┐ │      │
│  (读取 day.bin,              │  │video worker │→pipe:0 │
│   按墙钟时间                 │  │(fogleman/gg)│  RGBA  │
│   逐秒发射 tick)             │  ├─────────────┤ │      │
│                              │  │audio worker │→pipe:3 │
│  ┌─────────┐                 │  │(WAV+BGM mix)│  PCM   │
│  │  BGM    │ PCM循环缓冲 →   │  └─────────────┘ │      │
│  │ loader  │                 └──────────┬───────┘      │
│  └─────────┘                            │              │
│                              ┌──────────▼───────┐      │
│                              │  stream manager  │      │
│                              │  (FFmpeg 子进程)  │      │
│                              └──────────────────┘      │
└─────────────────────────────────────────────────────────┘
```

### 每帧时序 (33.3ms @ 30fps)

1. replay 引擎在对应墙钟秒发射 Tick (含 0~4 条事件)
2. video worker: 更新浮升文字状态 → 渲染 RGBA 帧 → 写入 pipe:0
3. audio worker: 触发新事件对应的 WAV 采样 + 混入 BGM → 写入 1470 个采样 → pipe:3
4. 音视频同步靠恒定帧率保证: 每帧 = 1470 PCM 采样 (44100 / 30)

### 浮升文字生命周期

- 生成: 事件到达 → 随机 X 在 [0, width], Y 在 [spawn_y_min, spawn_y_max]
- 字号: `font_size_min + (font_size_max - font_size_min) * weight / 255`
- 上浮: 以 `speed_px_per_sec` 像素/秒的速度向上移动
- 淡出: alpha 从 220 线性递减到 0
- 消亡: Y < 0 或 alpha = 0 时移除

### 每帧音频混音

```
output[i] = clamp(
    bgm_pcm[bgm_pos % bgm_len] * bgm_gain
  + sum(active_samples[j].pcm[offset] * voice_gain)
  , -1.0, 1.0
)
```

- BGM: 环形缓冲区, 到达末尾后回绕到起点
- 事件采样: 事件到达时触发, 播放完毕后移除
- 主增益在混音后、clamp 前施加

## 5. prepare 数据管线

```
GH Archive CDN (.json.gz, ~40MB/个)
  │
  ▼ HTTP GET (或使用本地 ops/assets/ 副本)
  │
  ▼ 解压 + JSON 逐行解析
  │
  ▼ 过滤: 只保留 6 种事件类型
  │
  ▼ 提取: {type, repo, actor, created_at, id}
  │
  ▼ 按 created_at 排序, 按秒分桶 (0~86399)
  │
  ▼ 每秒桶内: 去重 (同 repo 600s 窗口内),
  │  按权重降序排列, 取 top-4
  │
  ▼ 归一化: weight → u8(0~255), text → 截断 ≤64B UTF-8
  │
  ▼ 序列化为 day.bin + manifest.json
  │
  var/ghsingo/daypack/{date}/
  ├── day.bin          (~18MB)
  └── manifest.json
```

### manifest.json

```json
{
  "date": "2026-03-28",
  "total_events": 1847293,
  "kept_events": 312847,
  "ticks_with_events": 78421,
  "empty_ticks": 7979,
  "by_type": {
    "PushEvent": 198432,
    "CreateEvent": 54321,
    "IssuesEvent": 23456,
    "PullRequestEvent": 19876,
    "ForkEvent": 11234,
    "ReleaseEvent": 5528
  }
}
```

## 6. 配置文件 (.toml)

```toml
[meta]
profile = "default"

[archive]
source_dir = "ops/assets"
daypack_dir = "var/ghsingo/daypack"
target_date = "yesterday"    # "yesterday" 或 "2026-03-28"

[archive.download]
enabled = true
base_url = "https://data.gharchive.org"
timeout_secs = 60
max_parallel = 4
user_agent = "ghsingo/0.1"

[events]
types = [
  "PushEvent", "CreateEvent", "IssuesEvent",
  "PullRequestEvent", "ForkEvent", "ReleaseEvent",
]
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
mode = "local"               # "local" 或 "rtmps", 互斥
video_preset = "ultrafast"
audio_bitrate_kbps = 128

[output.local]
path = "var/ghsingo/records/{date}.flv"

[output.rtmps]
url = ""                     # 通过 ghsingo.local.toml 覆盖

[observe]
log_level = "info"
emit_stats_every_secs = 30
```

密钥注入优先级:
1. `GHSINGO_RTMPS_URL` 环境变量
2. `ghsingo.local.toml` (gitignored)
3. `ghsingo.toml` (tracked 模板)

## 7. Go 依赖

```
github.com/fogleman/gg        v1.3.0    # 2D 渲染 (RGBA 帧)
github.com/go-audio/wav       v1.1.0    # WAV 文件解码
github.com/BurntSushi/toml    v1.3.0    # TOML 配置解析
```

标准库覆盖: `os/exec`, `os.Pipe`, `io`, `encoding/binary`,
`encoding/json`, `compress/gzip`, `image`, `image/color`, `math/rand/v2`,
`log/slog`, `time`, `flag`, `path/filepath`, `net/http`.

最小依赖足迹 — 仅 3 个外部模块。

## 8. Makefile Targets

```makefile
# 构建
build-prepare:      go build -o bin/prepare ./cmd/prepare
build-live:         go build -o bin/live ./cmd/live
build:              build-prepare build-live

# 资源预处理
prepare-assets:     ffmpeg -i ops/assets/cosmos-leveloop-339.mp3 \
                      -ar 44100 -ac 2 ops/assets/cosmos-leveloop-339.wav

# 运行
run-prepare:        ./bin/prepare --config ghsingo.toml
run-live:           ./bin/live --config ghsingo.toml
run-live-5m:        timeout 300 ./bin/live --config ghsingo.toml

# Systemd
install-units:      cp ops/systemd/*.service ops/systemd/*.timer \
                      ~/.config/systemd/user/
enable:             systemctl --user enable ghsingo-live ghsingo-prepare.timer
start:              systemctl --user start ghsingo-live
stop:               systemctl --user stop ghsingo-live
status:             systemctl --user status ghsingo-live ghsingo-prepare.timer
logs:               journalctl --user -u ghsingo-live -f

# 开发
fmt:                go fmt ./...
vet:                go vet ./...
test:               go test ./...
clean:              rm -rf bin/ var/ghsingo/records/
```

## 9. 错误处理

| 场景 | 行为 |
|---|---|
| 目标日期无 day-pack | live 记录错误日志, 回退到最近可用的 day-pack |
| FFmpeg 进程崩溃 | live 检测到 broken pipe, 重启 FFmpeg 子进程, 从当前 tick 恢复 |
| GH Archive 下载失败 | prepare 退避重试 3 次, 全部失败则以非零状态退出 |
| day.bin 损坏 (magic/version 不匹配) | live 拒绝该文件, 回退到前一天的 day-pack |
| RTMPS 连接断开 | 由 FFmpeg `-reconnect` 参数处理重连 |
| 所有事件 WAV 文件缺失 | live 拒绝启动, 日志列出缺失文件 |
| BGM WAV 缺失 | live 正常启动但无背景音乐, 日志记录警告 |

## 10. 固定参数

| 参数 | 值 |
|---|---|
| 分辨率 | 1280x720 |
| 帧率 | 30 fps |
| 视频编码 | H.264 ultrafast |
| 音频码率 | 128 Kbps |
| 音频采样率 | 44100 Hz |
| 音频声道 | 2 (立体声) |
| 配色主题 | Solarized Dark |
| 配置格式 | 单一 .toml |
| 部署方式 | systemd --user |
| 构建系统 | Makefile |
| 数据源 | gharchive.org (前一天数据) |
| 开发样本 | ops/assets/2026-03-28-11.json.gz |
| 背景音乐 | cosmos-leveloop-339.mp3 (构建时转为 .wav) |
| 事件类型 | 6 种 (PushEvent, CreateEvent, IssuesEvent, PullRequestEvent, ForkEvent, ReleaseEvent) |
| 每秒最大事件数 | 4 |
| 去重窗口 | 600s |
| day-pack 格式 | 专用二进制 (day.bin, ~18MB) |
| 输出模式 | local / rtmps (互斥) |
