# 260320 songh issue-2 architecture plan

> status: decision-freeze draft
>
> model: Codex (GPT-5)
>
> issue: <https://github.com/41490/chao5whistler/issues/2>
>
> decision comment: <https://github.com/41490/chao5whistler/issues/2#issuecomment-4101418171>
>
> scope: 只做架构澄清、细节冻结、实施规划；本轮不改代码

## purpose

这份文档现在不再是“讨论稿”，而是 `songh` 实施前的冻结版规格说明。

它负责把 6 件事一次讲清楚：

1. `songh` 的输入、输出、长期运行方式是什么。
2. 新决策对旧方案做了哪些根本性修改。
3. `gharchive.org` 数据源到底怎么接，规模有多大，运行时如何消费。
4. 音频、视频、时间轴、模板、随机回退模式分别如何落地。
5. `.toml` 需要冻结到什么粒度，才算“开工前没有脑补式决定”。
6. 哪些点已经冻结，哪些点只是实施时可调参数。

## decision summary

基于最新决策评论，当前冻结结论如下：

- 事件声音体系接受 17 类总体方向，但 V1 主实现先收敛为 10 类主事件。
- 事件权重不再基于代码行数，而改为固定权重表。
- 采样率固定 `48kHz`。
- 背景音乐只支持 `WAV`。
- 文字动画默认“竖直上浮”，同时允许配置成固定角度或随机角度上浮。
- 事件去重窗口固定 `10 分钟`。
- GitHub API 不可用时，不再依赖在线 API，进入“随机数驱动模式”。
- 输出同时支持：
  - `RTMP/RTMPS` 推流
  - 本地录制
- 动画分辨率必须由 `.toml` 配置，不固定死在 `1920x1080`。
- 事件主数据源从 GitHub Events API 迁移为 `gharchive.org` 公开历史档案。
- 文本显示模板必须通过 `.toml` 配置。
- GitHub source credential 不再需要。

## key change from the old plan

和上一版相比，这不是“小修”，而是 4 个基础假设被替换了：

### 1. source layer changed

旧假设：

- 在线轮询 GitHub Events API

新假设：

- 离线下载 `gharchive.org` 小时档案
- 在本地做“按真实时间轴回放”

### 2. weighting logic changed

旧假设：

- 尽量用代码行数作为权重

新假设：

- 用固定事件权重表作为主权重
- 不再把“代码行数”作为核心设计前提

### 3. live semantics changed

旧假设：

- 近实时公共事件声景

新假设：

- 基于历史真实事件时间点重放的“准实时直播生成器”

### 4. config surface expanded

旧假设：

- 配置主要控制流地址、素材、基础渲染参数

新假设：

- `.toml` 还要负责：
  - 文本模板
  - 轨迹模式
  - 分辨率
  - 本地录制
  - day-pack 选择策略
  - fallback 策略

## fact-check

本节只写已核验事实。

### gharchive granularity

已核验事实：

- GH Archive 官方首页明确写明：GitHub 公共事件被聚合成“按小时”的档案。
- 官方访问示例是：
  - `https://data.gharchive.org/YYYY-MM-DD-H.json.gz`
- `data.gharchive.org` 桶中公开可列目录，文件名模式也是小时粒度。

因此：

- 不是官方“单个日包”。
- 如果要用“按天”的概念，必须是我们自己在本地把 24 个小时包组织成一个 day-pack。

### gharchive format

已核验事实：

- 官方说明是 JSON encoded events。
- 抽样 `2026-03-19-12.json.gz` 解压后是逐行 JSON 事件流，可按 JSONL 方式顺序读取。
- 同一小时档案中的单条事件结构与 GitHub event payload 对齐。

因此：

- 本地 ingest 层可以按：
  - `gzip stream`
  - `line reader`
  - `serde_json per line`
- 的方式稳定处理。

### gharchive scale

已核验事实：

- 抽样 `2026-03-19` 全部 24 个小时档案：
  - 压缩后总量约 `812.16 MiB`
  - 单小时平均约 `33.84 MiB`
- 抽样 `2026-03-19-12.json.gz`：
  - 压缩大小约 `26.85 MiB`
  - 解压后约 `141.13 MiB`

由此推断：

- 日级原始 JSONL 体量是“多 GiB 级”，不是“几十 MiB 级”。
- 所以运行架构必须明确区分：
  - raw archive download
  - local normalized pack
  - runtime replay

### GitHub API dependency

已核验事实：

- GH Archive 官方站点说明其内容来自 GitHub public timeline / event data 的历史归档。
- 公开 HTTP 即可下载，无需 GitHub token。

因此：

- `songh` 的 source acquisition 层不再需要 GitHub API token。
- 但这只影响 source credential，不影响 YouTube / RTMP stream key。

### YouTube live bridge

已核验事实：

- YouTube Live 编码建议仍包含：
  - `H.264`
  - `AAC`
  - keyframe `2s`
- `1080p30` 是被支持的常规档位。

因此：

- 直播桥仍以 FFmpeg 子进程输出 `H.264 + AAC` 为主。
- 只是分辨率与码率要配置化，不能再写死。

## frozen scope

### v1 goal

V1 不是“最花哨的直播器”，而是：

- 可靠下载并组织 GH Archive day-pack
- 基于真实历史时间轴稳定回放
- 把 10 类主事件转成连续音频和视频
- 同时输出 RTMP/RTMPS 与本地录制
- 在数据不可用时进入随机数驱动回退模式

### v1 in scope

- `gharchive` 数据获取
- local day-pack 管理
- event normalization
- 10 类主事件权重
- 音频主链路
- 视频主链路
- 文本模板
- 轨迹模式
- 本地录制 + 推流
- 随机数驱动 fallback

### v1 out of scope

- 17 类事件全部精细调音
- GPU 渲染
- 复杂粒子系统
- 多路直播平台并发适配
- 云端分布式数据处理
- 在线 GitHub API enrichment

## primary event classes

V1 主事件冻结为 10 类，使用固定权重表：

| Weight | Event |
|--------|-------|
| 10 | `CreateEvent` |
| 20 | `DeleteEvent` |
| 30 | `PushEvent` |
| 40 | `IssuesEvent` |
| 50 | `IssueCommentEvent` |
| 60 | `CommitCommentEvent` |
| 70 | `PullRequestEvent` |
| 80 | `PublicEvent` |
| 90 | `ForkEvent` |
| 100 | `ReleaseEvent` |

冻结规则：

- 只有这 10 类默认进入渲染管线。
- 其余事件类型在 V1 默认丢弃。
- 后续要扩展到 17 类时，只扩 normalization map 和 voice map，不改主流水线。

## source architecture

### canonical source

`songh` 的 canonical source 改为：

- `gharchive.org` 小时级 `.json.gz`

运行不再依赖：

- GitHub REST API 在线轮询
- GitHub token

### local source model

虽然上游是小时档案，但本地运行时必须看到“day-pack”概念。

推荐目录结构：

```text
var/songh/
├── archive/
│   └── 2026-03-19/
│       ├── raw/
│       │   ├── 00.json.gz
│       │   ├── 01.json.gz
│       │   └── ... 23.json.gz
│       ├── normalized/
│       │   ├── 00.jsonl.zst
│       │   ├── 01.jsonl.zst
│       │   └── ... 23.jsonl.zst
│       ├── index/
│       │   ├── minute_offsets.json
│       │   └── stats.json
│       └── manifest.toml
└── cache/
```

这里的 `day-pack` 是本地约定，不是上游格式。

### completeness rule

一个 day-pack 只有在以下条件同时满足时才算“complete”：

1. `00..23` 共 24 个小时 raw file 全部存在
2. 24 个小时 normalized file 全部成功生成
3. manifest 里记录：
   - source day
   - file sizes
   - event counts
   - supported event classes
   - created_at range

### day selection policy

默认策略冻结为：

- `selector = latest_complete_day`
- `preferred_offset_days = 2`

原因：

- 决策评论明确倾向“前天”
- 这样可以避免抓到当天还未完整的档案集

实现含义：

- 先尝试选择 `today - 2 days`
- 如果本地不存在完整 pack，则回退到“最近一个 complete day-pack”

## ingestion and normalization

### ingest stages

source ingest 冻结为 4 段：

1. `download`
   - 拉 24 个小时 raw gz
2. `materialize`
   - 流式解压
   - 行级 JSON 解析
3. `normalize`
   - 过滤到 10 类主事件
   - 映射到统一内部事件结构
4. `index`
   - 建立按分钟偏移和统计索引

### normalized event contract

运行时不直接消费原始 GH Archive 行。

统一转换为：

```text
NormalizedEvent
- event_id: String
- source_day: YYYY-MM-DD
- source_hour: 0..23
- created_at_utc: RFC3339
- second_of_day: 0..86399
- event_type: String
- weight: u8                 # 10..100
- repo_full_name: String
- actor_login: String
- display_hash: String
- text_fields: Map<String, String>
- audio_class: String
- visual_class: String
- raw_ref: String            # raw source locator
```

### display hash rule

为了避免“有些事件没有 git hash”这个模糊点，`display_hash` 规则冻结如下：

- `PushEvent`
  - 优先 `payload.head`
  - 否则取首个 commit sha
  - 仍无则用 `event_id` 派生短 digest
- `PullRequestEvent`
  - 优先 PR head sha
  - 否则用 PR id / event id 派生短 digest
- `CreateEvent` / `DeleteEvent`
  - 用 `ref_type + ref + event_id` 派生短 digest
- `IssuesEvent` / `IssueCommentEvent` / `CommitCommentEvent`
  - 用对应对象 id + event id 派生短 digest
- `PublicEvent` / `ForkEvent` / `ReleaseEvent`
  - 用 payload 关键 id + event id 派生短 digest

这意味着：

- 所有主事件都保证有 `display_hash`
- 但不是所有 `display_hash` 都是“真实 git commit hash”
- 文档和 UI 文案里必须明确它是“事件 hash 文本”，不是一律“commit hash”

## timeline semantics

### canonical clock

`songh` 的 canonical time axis 现在不是网络时间，而是：

- `source_day` 内每个事件的 `created_at_utc`

运行时回放时，采用：

- wall clock -> archive second-of-day

### playback mapping

V1 冻结为：

- 按“时间点同构”回放

即：

- 当前播放秒 `t`
- 对应 day-pack 中 `second_of_day == t`
- 的事件集合

如果当天持续运行 24h：

- 就相当于把整天真实事件重新经历一遍

### overflow rule

issue 原始描述有“每秒前 4 种行为一个声簇”约束。

V1 冻结为：

1. 按 `second_of_day` 聚合
2. 每秒最多选 4 个事件进入音视频主渲染
3. 排序规则：
   - weight 高优先
   - 同权重按原始时间顺序
   - 再按 event id 稳定排序
4. 溢出事件不渲染，但计入统计

这一步不再模糊：

- 不是“来多少画多少”
- 不是“全量排队延迟播放”
- 就是“每秒 top-4 renderable events”

### dedupe rule

10 分钟 dedupe 窗口继续保留，但它只作用于 runtime emission：

- 作用对象：最近 10 分钟内已发射过的 `event_id`
- 目的：
  - 避免 hour boundary 或重启恢复时重复发射
  - 避免 fallback 切换过程中重复注入

它不作用于 raw archive ingest。

## runtime modes

### mode 1: archive replay

主运行模式。

输入：

- complete day-pack

输出：

- 音频事件
- 视频文本
- 推流 / 本地录制

### mode 2: random fallback

当以下任一条件成立时启用：

- 没有 complete day-pack
- pack 校验失败
- 当前 hour normalized file 不可读
- runtime 明确切换到 fallback

fallback 不再模糊，冻结为：

- 使用 PRNG 生成事件流
- 事件类型只在 10 类主事件中采样
- 采样概率与固定权重正相关
- 文本字段使用 synthetic repo / synthetic hash / synthetic actor
- 时间密度用两级来源：
  - 如果本地已有历史 day-pack，则用其分钟级分布做密度模板
  - 否则使用内建默认密度模板

### mode 3: dry-run

输入：

- day-pack 或 fallback

输出：

- 不推流
- 只写本地录制
- 或只输出统计 / 截帧 / 音频样片

## audio architecture

### audio goals

音频层只负责 4 件事：

1. 把 `weight + event_type` 变成可听见的 cue
2. 处理最多 4 个事件 / 秒的重叠
3. 叠加背景 WAV
4. 输出连续 PCM 给编码器

### internal audio model

V1 建议冻结为：

- sample rate: `48000`
- channels: `2`
- internal format: `f32`

选择双声道的原因：

- 背景 WAV 更自然
- 本地录制和直播兼容更好
- 事件声可以先居中，后续再扩展到轻微左右漂移

### weighting rule

不再使用代码行数。

统一采用：

- `normalized_weight = weight / 100.0`

从它派生：

- 事件增益
- 字号
- 事件时长
- 事件优先级

V1 公式冻结为“单调映射”，具体曲线可调，但语义固定：

- 权重越大：
  - 越响
  - 越长
  - 越大
  - 越优先进入 top-4

### voice strategy

V1 使用“10 类主 voice + 可扩展 17 类表”：

- 10 类主事件必须有 voice preset
- 其余 7 类未来补齐

每个 voice preset 可选：

- `synth`
- `wav_sample`
- `hybrid`

背景音乐固定：

- `WAV only`

### overlap rule

V1 混音规则冻结为：

- 同一秒最多 4 个事件 cue
- cue 之间允许重叠
- 重叠使用固定短 crossfade 窗口
- 总线后置 limiter，避免爆音

## video architecture

### canvas contract

视频画布必须完全配置化：

```toml
[video.canvas]
width = 1920
height = 1080
fps = 30
```

运行时不能假定：

- 一定是 `1920x1080`
- 一定是 `30fps`

### scaling rule

为避免 `720p` 下尺寸语义漂移，V1 冻结：

- 所有视觉尺寸以 `1080p` 为设计基准
- 实际运行时按 `height / 1080.0` 缩放

受这个规则影响的参数：

- font min/max
- stroke width
- rise speed
- alpha fade speed
- bottom padding

### spawn region

issue 已明确“标准画布下半部分随机位置出现”。

V1 冻结：

- 初始出现区域限定在画布下半部分
- `x` 为全宽随机
- `y` 为 `[height * 0.5, height * 0.95]` 区间随机

### trajectory modes

配置面冻结为：

```toml
[video.motion]
mode = "vertical"        # vertical | fixed_angle | random_angle
angle_deg = 0.0          # 相对“正上方”的偏转角
random_min_deg = -25.0
random_max_deg = 25.0
speed_px_per_sec = 180.0
```

语义冻结：

- `vertical`
  - 始终正上方
- `fixed_angle`
  - 使用固定 `angle_deg`
- `random_angle`
  - 每个事件在 `random_min_deg..random_max_deg` 内取角度

这里 `0 deg` 明确表示：

- 正上方

正值表示：

- 向右偏

负值表示：

- 向左偏

### text lifetime

事件寿命不再模糊：

- 文本从 spawn point 出发
- 沿 trajectory 移动
- 当 alpha 为 0 或完全离开画布时结束

V1 默认：

- lifetime 由“到边界的几何距离 / 速度”计算
- 而不是固定秒数硬砍

## text template contract

### template syntax

模板冻结为：

- 花括号字段
- 可带截断长度

示例：

- `{repo}/{hash:8}`
- `{type}/{repo_name}/{hash:7}`
- `{actor}@{repo}/{hash:8}`

### available fields

V1 冻结支持：

- `{repo}`
- `{repo_owner}`
- `{repo_name}`
- `{type}`
- `{actor}`
- `{hash}`
- `{id}`
- `{weight}`
- `{hour}`
- `{minute}`
- `{second}`

截断规则：

- `{hash:8}` 表示只取前 8 个字符

### validation rule

模板解析规则冻结为：

- 未知字段：启动即报 config error
- 已知字段但运行时为空：渲染为空字符串

这样可以避免：

- 运行中才发现模板拼错
- 或因为某类事件缺字段而整条崩溃

## stream bridge

### output policy

同时输出直播和本地录制的规则冻结为：

- 单次编码，多路输出

推荐策略：

- 优先 FFmpeg `tee muxer`

原因：

- 避免双重编码
- 本地文件与直播流保持一致

### stream secret boundary

source credential 已经去掉，但 stream secret 仍然存在。

因此凭据边界冻结为：

- GitHub source: 无 secret
- RTMP/RTMPS: 仍需 stream key

stream key 不允许：

- 写入仓库跟踪的 `.toml`

只允许：

- 环境变量
- 本地未提交覆盖文件

## module proposal

新的主架构不再以 `poller` 为中心，而是以 `day-pack replay` 为中心：

```text
src/songh/
├── Cargo.toml
├── src/
│   ├── main.rs
│   ├── cli.rs
│   ├── app.rs
│   ├── config/
│   │   ├── mod.rs
│   │   ├── schema.rs
│   │   └── validate.rs
│   ├── archive/
│   │   ├── mod.rs
│   │   ├── download.rs
│   │   ├── materialize.rs
│   │   ├── normalize.rs
│   │   ├── index.rs
│   │   └── manifest.rs
│   ├── timeline/
│   │   ├── mod.rs
│   │   ├── day_select.rs
│   │   ├── replay.rs
│   │   ├── bucket.rs
│   │   └── fallback.rs
│   ├── model/
│   │   ├── mod.rs
│   │   ├── normalized_event.rs
│   │   ├── text_template.rs
│   │   └── weights.rs
│   ├── audio/
│   │   ├── mod.rs
│   │   ├── voices.rs
│   │   ├── wav_bank.rs
│   │   ├── synth.rs
│   │   ├── scheduler.rs
│   │   └── mixer.rs
│   ├── video/
│   │   ├── mod.rs
│   │   ├── canvas.rs
│   │   ├── motion.rs
│   │   ├── text.rs
│   │   └── palette.rs
│   ├── stream/
│   │   ├── mod.rs
│   │   ├── ffmpeg.rs
│   │   ├── outputs.rs
│   │   └── clock.rs
│   ├── observe/
│   │   ├── mod.rs
│   │   ├── tracing.rs
│   │   └── stats.rs
│   └── errors.rs
```

## recommended implementation order

### stage 0: config and contract freeze

产物：

- 本文档评审版
- `songh.toml` schema 草案
- 10 类权重表
- 文本模板字段表

退出条件：

- 不再对 source model、weight model、trajectory model 摇摆

### stage 1: archive pack pipeline

目标：

- 下载 24 小时 raw files
- 生成 complete day-pack

产物：

- raw downloader
- normalized emitter
- manifest/index 规范

退出条件：

- 任意 complete day-pack 可重复生成

### stage 2: replay engine

目标：

- 实现 second-of-day bucket replay
- 实现 top-4 selection
- 实现 10 分钟 dedupe

产物：

- replay sample
- minute/hour stats

退出条件：

- 同一 pack 多次 replay 结果一致

### stage 3: audio engine

目标：

- 实现主声音链路和背景 WAV

产物：

- 10 类主事件 cue 样本
- 混音样本
- limiter 验证

### stage 4: video engine

目标：

- 实现可配置分辨率和轨迹

产物：

- `vertical`
- `fixed_angle`
- `random_angle`

三类视频样片

### stage 5: stream bridge

目标：

- 本地录制 + RTMP/RTMPS 双输出

产物：

- ffmpeg 模板
- local record sample
- live dry-run script

### stage 6: fallback mode

目标：

- 缺包、坏包、无包时仍可连续输出

产物：

- synthetic event generator
- fallback stats

### stage 7: soak and reports

目标：

- 长时间运行验证

产物：

- `docs/reports/yymmdd_[Issue No.]_[Case Summary].md`
- 8h / 24h soak 报告

## implementation notes before coding

下面这些点现在全部冻结，不应在编码时临时脑补：

- source input 不是在线 API，而是 GH Archive day-pack
- day-pack 不是上游格式，而是本地组织格式
- 默认只渲染 10 类主事件
- 权重来源是固定权重表，不是行数
- 每秒最多 4 个事件进入主渲染
- 文本主载荷来自模板，不是硬编码字符串拼接
- 所有事件都必须有 `display_hash`
- 分辨率不是固定 1080p
- motion mode 不是只有 vertical
- fallback 必须可独立运行
- GitHub token 从设计中删除
- RTMP key 仍需要安全边界

## config artifacts

为避免实现时再次发散，配置层对应文档冻结为：

- 规格说明：
  - `docs/plans/260321-songh-toml-spec.md`
- 注释模板：
  - `docs/plans/260321-songh-template.toml`

两者分工固定：

- 规格说明负责字段定义、默认值、校验与互斥关系
- 模板文件负责给出可直接实现的注释化基线

## minimal open items

当前仍值得你复核，但已经不阻塞继续编码的点，只剩 3 个：

1. 本地录制默认容器要不要固定为 `.flv`
2. fallback 的默认分钟密度模板要不要做得更稀疏
3. 10 类主事件之外，V1 是否要把少量次级事件映射到最近邻 voice，而不是直接丢弃

如果你不再追加决策，我建议默认采用：

- local record: `.flv`
- fallback density: 稀疏优先
- secondary events: 直接丢弃

# refer.

## model

- Codex (GPT-5)

## primary sources

- Issue #2: <https://github.com/41490/chao5whistler/issues/2>
- 决策评论: <https://github.com/41490/chao5whistler/issues/2#issuecomment-4101418171>
- GitHub issue comment API: <https://api.github.com/repos/41490/chao5whistler/issues/comments/4101418171>

## duckduckgo queries

- GH Archive 小时档案检索: <https://duckduckgo.com/?q=gharchive.org+jsonl+gz+hourly+github+archive&ia=web>
- GH Archive 数据说明检索: <https://duckduckgo.com/?q=gharchive.org+public+timeline+archive+hourly+json.gz&ia=web>
- YouTube Live 编码建议检索: <https://duckduckgo.com/?q=YouTube+Live+encoder+settings+RTMPS+H.264+AAC+1080p+30fps+2+second+keyframe&ia=web>
- FFmpeg tee muxer 检索: <https://duckduckgo.com/?q=ffmpeg+tee+muxer+documentation&ia=web>

## official docs and checked pages

- GH Archive 首页: <https://www.gharchive.org/>
- GH Archive 数据桶: <https://data.gharchive.org/>
- 抽样小时包: <https://data.gharchive.org/2026-03-19-12.json.gz>
- GitHub event types: <https://docs.github.com/en/developers/webhooks-and-events/events/github-event-types>
- YouTube live encoder settings: <https://support.google.com/youtube/answer/2853702?hl=en>
- FFmpeg formats: <https://ffmpeg.org/ffmpeg-formats.html>

## checked local project context

- 历史项目说明: `ghwhistler/README.md`
- 历史事件采集: `ghwhistler/act4gh/_events.py`
- 历史音频拼接: `ghwhistler/act4gh/_audio.py`
- 历史视频上浮: `ghwhistler/act4gh/_video.py`
- 报告目录约定: `docs/reports/`

## fact notes

- GH Archive 官方页面说明档案为小时级聚合；本地 day-pack 是本文新增约定。
- `2026-03-19` 24 小时压缩档抽样总量约 `812.16 MiB`，来自对 `00..23.json.gz` 的 HEAD 汇总。
- `2026-03-19-12.json.gz` 抽样解压后约 `141.13 MiB`，据此可知日级原始 JSONL 是多 GiB 量级。
