# ghsingo 音乐性重构设计 (noise-era → bell-era)

- **Issue**: #27
- **Parent**: #17 (Go 重写), #19 (P0~P6 音源/空间/节拍修缮)
- **Date**: 2026-04-24
- **作者**: ZoomQuiet + Claude
- **前置分支**: `ghsingo-noisea` (2f9cdf5e) 保留噪音版全套代码作可回退锚
- **目标**: 把 ghsingo 的"海洋采样叠加"白噪范式,替换为"调音装置"范式——让随机 GitHub 事件驱动出内在和谐的无限音乐。

## 1. 目标与非目标

### 目标
- **音高即和谐**: 所有事件触发的音都量化到严格五声音阶(宫商角徵羽),任意密度/组合都天然相容。
- **单音色家族**: 主层使用编钟音色,构建一致的声学空间。
- **事件 → 音**: 保持 GH 事件作为真·随机源;每秒内按事件类型计数排序,决定主辅音与配重。
- **稀疏点发**: 保留 ms 级原始触发时间,允许钟声自然衰减跨秒。
- **可并行 ghsingo-noisea**: 设计不破坏 BGM/beat/ducking/reverb 等 #19 成果的复用。

### 非目标 (YAGNI)
- **不做**完整 MIDI 引擎,也不做 DAW 级合成器。
- **不做**旋律作曲/和弦进行的生成式 AI(方案 C),本期恒定宫调。
- **不做**多调性漂移(decision 2 = 严格五声,调性固定 C)。
- **不做**深度重构 video/replay/archive 模块;此期只动 `internal/audio/` + 配置 + 资产。

## 2. 决策记录(来自 issue #27)

| # | 决策项 | 选择 |
|---|-------|------|
| 1 | 音色 | **编钟 (bianzhong)** |
| 2 | 音阶 | **严格宫商角徵羽** (C D E G A) |
| 3 | 海洋采样 | **仅 ReleaseEvent 保留**,作为"大事件"瞬间叠加素材 |
| 4 | BGM | **保留** `cosmos-leveloop-339.wav` 循环 |
| 5 | 事件→音高映射 | **完全按当秒计数排序**(无 hash 记忆) |
| 6 | 音高网格规模 | **15 音 = 5 音名 × 3 八度** |
| 7 | 合成路径 | **混合:长音采样 + 合成短音** |
| 8 | 验证节奏 | **直接做方案 B**(完全替换非 Release 事件) |

## 3. 系统架构

### 3.1 音高网格 (pitch grid)

严格五声 × 3 八度,共 15 音。参考频率(等律近似):

```
    八度3      八度4       八度5
  ┌──────┬──────┬──────┐
宫 │ C3   │ C4   │ C5   │   131 Hz   262 Hz   523 Hz
商 │ D3   │ D4   │ D5   │   147       294       587
角 │ E3   │ E4   │ E5   │   165       330       659
徵 │ G3   │ G4   │ G5   │   196       392       784
羽 │ A3   │ A4   │ A5   │   220       440       880
  └──────┴──────┴──────┘
  (低·沉)  (中·稳)   (高·亮)
```

C3 ~ A5 覆盖约 130 Hz~880 Hz,是钟类乐器听感最甜的频带。

### 3.2 秒簇算法 (per-second cluster)

输入: 当前 1 秒内所有 GH 事件 `[(type, ms_offset, weight, actor)...]`

```
[1] 过滤:
    - 丢弃不在 {Push, Create, Issues, PR, Fork} 中的类型
    - Release 单独保底,始终保留

[2] 计数并排序(按当秒该类型出现次数降序):
    例: {Push: 8, Issues: 3, Create: 2, PR: 1, Fork: 0}
       排序后: [Push, Issues, Create, PR]  (取前 4)

[3] 赋音(音名按排名)
    rank 1 (主音)  → 宫 C    vel = 1.00
    rank 2 (辅音1) → 商 D    vel = 0.75
    rank 3 (辅音2) → 角 E    vel = 0.60
    rank 4 (辅音3) → 徵 G    vel = 0.45
    Release       → 羽 A    vel = 1.00  (同时触发海洋采样)

[4] 赋八度(按 rank,营造"主音居中、辅音分散"的声部布局)
    rank 1 → 中八度 (C4)    ← 主音落在人耳最稳的听区
    rank 2 → D4/D5 交替     ← 该 rank 在本秒出现第 N 次: N 偶=D4, N 奇=D5
    rank 3 → 高八度 (E5)
    rank 4 → 低八度 (G3)    ← 辅音低音补底
    Release → 高八度 (A5) + 海洋浪涌

[5] 触发:按每个事件在该秒内的原始 ms_offset 精确散布
    每个事件 → (音名, 八度, velocity, ms_offset)

[6] 自然衰减:钟声 ring-out 1.5~3 s,不强制截断,允许跨秒共振
```

### 3.3 数据流

```
GH Archive  →  DayPack  →  ReplayEngine (1 sec / tick)
                              │
                              ▼
                     ┌────────────────────┐
                     │   ClusterEngine    │  ← [新增]
                     │  - 按类型计数排序   │
                     │  - rank → 音名     │
                     │  - rank → 八度     │
                     │  - ms_offset 保留   │
                     └────────────────────┘
                              │
                              ▼
                     [(pitch_id, vel, ms_off), ...]
                              │
                              ▼
              ┌─────────────────────────────────┐
              │          Mixer                  │
              │   ┌────────────────────────┐    │
              │   │ BellBank (15 采样)      │    │ ← 长音采样
              │   │   fluidsynth 预渲染     │    │
              │   └────────────────────────┘    │
              │   ┌────────────────────────┐    │
              │   │ KarplusStrong (实时)    │    │ ← 合成短音
              │   │   频率 → 钟声模拟       │    │
              │   └────────────────────────┘    │
              │   ┌────────────────────────┐    │
              │   │ OceanSample (保留1个)   │    │ ← 仅 Release
              │   └────────────────────────┘    │
              │   ┌────────────────────────┐    │
              │   │ BGM cosmos-leveloop     │    │
              │   │ (crossfade, ducking)    │    │
              │   └────────────────────────┘    │
              │   ┌────────────────────────┐    │
              │   │ Reverb (Schroeder 4t)   │    │
              │   └────────────────────────┘    │
              └─────────────────────────────────┘
                              │
                              ▼
                    Stereo f32 PCM / frame
                              │
                              ▼
                         FFmpeg (audio pipe)
```

### 3.4 声部混合策略 (决策 7 = 混合)

为平衡真实感与多声部密度,两套声源按 rank 分工:

| 用途 | 声源 | 触发场景 | 理由 |
|------|------|---------|------|
| 长音采样 (2~3 s) | `bells/sampled/{note}_{octave}.wav` | rank 1 (主音) & Release | 主音+高潮需要厚实钟鸣,采样保留泛音结构 |
| 合成短音 (0.8~1.2 s) | Karplus-Strong (Go 运行时) | rank 2~4 (辅音) | 辅音密度大,合成零样本依赖,可多声部不卡 |

采样来源:

- **首版**: 用 FluidR3_GM.sf2 的 **Tubular Bells (Program 14)** 通过 `fluidsynth` 预渲染 15 个 pitch 的 WAV。接受听感偏"西洋管钟"而非纯正编钟的折中,**作为 ready-to-ship 基线**。
- **后续优化(不阻塞本期交付)**: 寻找/录制真·编钟采样,替换 `bells/sampled/*.wav` 即可,无代码改动。

`fluidsynth` 预渲染通过 `Makefile` 的 `prepare-bells` 目标封装,与现有 `prepare-assets` 同级。不强制系统安装 `fluidsynth`——若缺席,Makefile 给出 `apt install fluidsynth` 提示并退出。

### 3.5 Karplus-Strong 简述

算法本身 ~60 行 Go,结构:

```
Init:
  delayLen = sampleRate / freq
  buffer[delayLen] = white_noise()  ← 初始激励

Each sample:
  out = buffer[pos]
  // 单极低通 + 衰减 = 钟声自然衰减 + 泛音递减
  next = (buffer[pos] + buffer[(pos+1) % delayLen]) * 0.5 * decay
  buffer[pos] = next
  pos = (pos + 1) % delayLen
```

- `decay` ≈ 0.996(控制 ring-out 长度)
- 钟声特性额外用 `2×` 延迟串联实现"二次振荡"("铛—铃")
- 完全确定性(种子可固定),便于测试

### 3.6 配置变更 (ghsingo.toml)

移除:
```toml
[audio.voices.PushEvent]       # 删
[audio.voices.CreateEvent]     # 删
[audio.voices.IssuesEvent]     # 删
[audio.voices.PullRequestEvent]# 删
[audio.voices.ForkEvent]       # 删
```

保留(仅 Release):
```toml
[audio.voices.ReleaseEvent]
wav_path = "../../ops/assets/sounds/normalized/ReleaseEvent.wav"
gain_db = 3.1
duration_ms = 2490
```

新增:
```toml
[audio.bells]
# 15 个预渲染采样
bank_dir = "../../ops/assets/sounds/bells/sampled"
# 文件命名: {note}{octave}.wav  例: C4.wav, D5.wav, G3.wav
# 运行时合成 (Karplus-Strong) 使用相同频率
sample_gain_db = -2.0
synth_gain_db  = -4.0        # 合成短音略低,避免辅音喧宾夺主
synth_decay    = 0.996

[audio.cluster]
# 秒簇算法参数
keep_top_n = 4                # 主类型 + 3 辅
event_types = ["PushEvent", "CreateEvent", "IssuesEvent",
               "PullRequestEvent", "ForkEvent"]
always_fire = ["ReleaseEvent"]
velocity_curve = [1.00, 0.75, 0.60, 0.45]  # rank 1..4
release_velocity = 1.00
# 八度分配 (rank → octave),-1 表示按事件序号交替
octave_rank1    = 4          # 固定
octave_rank2    = [4, 5]     # 列表:按该 rank 在本秒内第 N 次出现循环取用
octave_rank3    = 5          # 固定
octave_rank4    = 3          # 固定
octave_release  = 5          # 固定
```

保留不变:
```toml
[audio.bgm]    # cosmos-leveloop-339 继续用
[audio.beat]   # beat generator 暂保留,但 gain 下调至 -26 dB
               # 理由: 钟层已含丰富节奏,低音鼓心跳作亚听觉锚即可
```

### 3.7 Mixer 改造

`internal/audio/mixer.go` 改动:

```
已删:
  - map voices: eventType → wav  (6 项)
  - TriggerEvent(typeID, weight)
  - voicePan(typeID) 的类型→声像映射

新增:
  - BellBank                    (15 pitch 采样库)
  - KarplusStrong               (合成器,按需生成实例)
  - ClusterEngine.Schedule(events)  → []NoteEvent
  - TriggerNote(pitchID, octave, vel, source {sample|synth})
  - notePan(pitchID, octave)    → 声像,按音名分布,不按事件类型

保留:
  - ScheduleSecond 签名(参数语义变化)
  - Reverb.Process
  - BGM 循环 + crossfade
  - BGM ducking
  - BeatGenerator (gain 下调)
  - softClip
```

声像策略改为"按音名分布":
- 宫 C → 0.50 (中)
- 商 D → 0.35 (偏左)
- 角 E → 0.65 (偏右)
- 徵 G → 0.25 (左)
- 羽 A → 0.75 (右)

这样 5 个音名分布在立体声场,听感更开阔,而不是按事件类型随机散布。

### 3.8 资产生成流程 (Makefile 新 target)

```makefile
prepare-bells: ops/assets/sounds/bells/sampled/A5.wav

ops/assets/sounds/bells/sampled/A5.wav:
	@command -v fluidsynth >/dev/null || \
	  { echo "需先 apt install fluidsynth"; exit 1; }
	@mkdir -p ops/assets/sounds/bells/sampled
	@bash src/ghsingo/scripts/render-bells.sh
```

`render-bells.sh` 生成临时 MIDI → fluidsynth 渲染 → ffmpeg 归一化到 44100/mono/16-bit,命名 `{note}{octave}.wav`。

## 4. 错误处理与边界

| 场景 | 行为 |
|------|------|
| `bells/sampled/*.wav` 缺失 | 启动即失败,提示运行 `make prepare-bells` |
| 某 pitch 采样缺失 | 退化为该 pitch 的 Karplus-Strong 合成,不静默 |
| 某秒事件数 = 0 | 不触发任何钟声,BGM 继续 |
| 事件类型超过 4 + Release | 截取 top-4 + Release,其余忽略(决策已定) |
| Release 海洋采样 `ReleaseEvent.wav` 缺失 | 退化为仅 A5 钟声,warning 日志 |
| ms_offset 超出 1 秒 | 截至 999 ms |
| 同秒同 ms 多事件 | 允许同时触发(已有混音+softClip) |

## 5. 测试策略

### 5.1 单元测试 (新增/修改)
- `cluster_test.go`: 给定事件输入列表,验证 rank 赋音、八度、velocity 是否符合规则
- `bellbank_test.go`: 验证 15 pitch 加载、缺失时回退到合成器
- `karplus_test.go`: 验证指定频率/衰减生成的样本能量合理
- `mixer_test.go` 扩展: 验证混合声源(采样+合成)同时触发时不削波

### 5.2 集成/听感验证
- `cmd/render-audio` 生成 5 分钟 MP3:
  ```
  go run ./cmd/render-audio --config ghsingo.toml --duration 5m -o /tmp/bell-era-5m.mp3
  ```
- 验收听感:
  - 能明确听到钟声为主,BGM 为底
  - 同时触发的钟声和谐不刺耳
  - 密集秒(>10 事件)不削波、不浑浊
  - Release 时海洋浪涌 + 高钟能被识别为"重要瞬间"

### 5.3 回归保护
- `beat`/reverb/ducking/crossfade 已有测试需继续通过
- 视频输出(`cmd/live`)生成一个 30 秒样本,确认音视频同步未退化

## 6. 回退路径

- `ghsingo-noisea` 书签已在 GitHub:https://github.com/41490/chao5whistler/tree/ghsingo-noisea
- 若 bell-era 效果不如预期,`jj new ghsingo-noisea` 或 GitHub checkout 即可回到噪音版。
- 本期所有改动集中在 `internal/audio/` + `ghsingo.toml` + `Makefile` + `ops/assets/sounds/bells/`;其它模块(video/archive/replay/stream)不动,降低合并风险。

## 7. 分阶段交付

| 阶段 | 产出 | 验收 |
|------|------|------|
| S1 资产 | `prepare-bells` + 15 WAV | 播放任意一个 wav 听起来是钟声 |
| S2 BellBank + ClusterEngine | Go 代码 + 单元测试 | 测试全绿 |
| S3 Karplus-Strong | synth 模块 + 测试 | 指定频率波形 FFT 主峰对齐 |
| S4 Mixer 改造 | 删除旧 voices 路径,接入新链路 | 单元测试全绿 |
| S5 配置更新 | `ghsingo.toml` + Makefile | `make prepare-bells && go build ./...` 通过 |
| S6 5 分钟 MP3 | render-audio 输出 | CTO 听感确认"有音乐性",无白噪 |
| S7 5 分钟视频 | `cmd/live` 本地 record | 音视频同步、无音频削波 |

## 8. 未决项 / 待后续迭代

- **真编钟采样**: 首版用 Tubular Bells 折中。合适的真编钟素材(CC0/CC-BY)落地后直接替换 `bells/sampled/*.wav`,不改代码。
- **BGM 调性适配**: `cosmos-leveloop-339` 的基频未验证是否合 C 调;若跑完 5 分钟样本后听感相冲,考虑 ffmpeg 预处理移调,或换 BGM。暂不阻塞本期。
- **Beat generator 去留**: 本期保留但 gain 降至 -26 dB,样本落地后再定是否彻底移除。
- **多调性漂移**: 本期不做,决策 2 已定恒定宫调。未来迭代可引入。

## 9. 与 ghsingo-noisea 的关系

```
main (2f9cdf5e)
  ├─ [ghsingo-noisea bookmark]  ← 永久快照,噪音版全部代码
  │
  └─ [新 change woyxwzqm]        ← 本设计的起点
       ↓
     本次实现: 删除 5 个事件的海洋 voices
               新增 BellBank / Karplus / ClusterEngine
               重构 Mixer
               更新配置 + Makefile
       ↓
     新 bookmark: codex/issue-27-bell-era  (待创建)
```

两个分支并存,可随时对比听感 / 回退。

