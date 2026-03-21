# 260321 songh toml spec

> status: config-freeze draft
>
> model: Codex (GPT-5)
>
> basis: `docs/plans/260320-songh-issue-2-architecture-plan.md`
>
> issue: <https://github.com/41490/chao5whistler/issues/2>

## purpose

这份文档专门冻结 `songh.toml` 的配置面。

目标不是“举例”，而是明确：

1. 最终有哪些 section。
2. 每个字段的类型、默认值、是否必填。
3. 哪些字段允许留空，哪些不允许。
4. 哪些字段互斥，哪些字段必须联动。
5. secret、local override、tracked template 的边界是什么。

## config artifacts

在真正实现时，配置文件边界冻结为 3 层：

### 1. tracked template

- 位置：仓库内模板文件
- 用途：文档化、示例化、基线化
- 允许进入版本库
- 不允许放 secret

### 2. runtime main config

- 默认文件名：`songh.toml`
- 用途：实际运行配置
- 默认不应包含 secret
- 可由 `--config <path>` 指定其他路径

### 3. local override

- 默认文件名：`songh.local.toml`
- 用途：本机覆盖配置
- 必须进入 `.gitignore`
- 允许写本机路径覆盖
- 不建议写 stream key；stream key 优先走环境变量

## precedence

配置优先级冻结为：

1. CLI 显式传入 `--config`
2. main config file
3. local override file
4. env secrets override specific fields

注意：

- 这里的“优先级”是“后者覆盖前者”。
- 如果没有 local override，则跳过这一层。

## secret boundary

### no longer secret

- GitHub source token

原因：

- source 已迁移到 `gharchive.org`

### still secret

- `RTMP/RTMPS` stream url / key

冻结规则：

- tracked template 中只能给空值或占位值
- main config 中也默认留空
- 运行时从环境变量注入

推荐环境变量：

- `SONGH_RTMP_URL`

## section map

`songh.toml` 冻结为以下 section：

```text
[meta]
[runtime]
[archive]
[archive.download]
[archive.normalize]
[replay]
[fallback]
[events]
[events.weights]
[text]
[audio]
[audio.background]
[audio.mix]
[audio.voices.CreateEvent]
[audio.voices.DeleteEvent]
[audio.voices.PushEvent]
[audio.voices.IssuesEvent]
[audio.voices.IssueCommentEvent]
[audio.voices.CommitCommentEvent]
[audio.voices.PullRequestEvent]
[audio.voices.PublicEvent]
[audio.voices.ForkEvent]
[audio.voices.ReleaseEvent]
[video.canvas]
[video.palette]
[video.text]
[video.motion]
[outputs]
[outputs.rtmp]
[outputs.record]
[observe]
```

## field spec

### `[meta]`

#### `profile`

- type: `string`
- required: no
- default: `"default"`
- meaning: 当前配置剖面名称，仅用于日志和录制文件名标签

#### `label`

- type: `string`
- required: no
- default: `"songh"`
- meaning: 人类可读标签

### `[runtime]`

#### `mode`

- type: `string`
- required: yes
- allowed:
  - `"archive_replay"`
  - `"random_fallback"`
  - `"dry_run"`
- default: `"archive_replay"`

#### `clock`

- type: `string`
- required: yes
- allowed:
  - `"realtime_day"`
- default: `"realtime_day"`

冻结说明：

- V1 只支持 `realtime_day`
- 不支持加速回放、不支持慢放

#### `start_policy`

- type: `string`
- required: yes
- allowed:
  - `"immediate"`
  - `"align_to_next_second"`
- default: `"align_to_next_second"`

### `[archive]`

#### `root_dir`

- type: `string`
- required: yes
- default: `"var/songh/archive"`
- meaning: day-pack 根目录

#### `selector`

- type: `string`
- required: yes
- allowed:
  - `"latest_complete_day"`
  - `"fixed_day"`
- default: `"latest_complete_day"`

#### `preferred_offset_days`

- type: `integer`
- required: yes
- default: `2`
- min: `0`

#### `fixed_day`

- type: `string`
- required: no
- default: `""`
- format: `YYYY-MM-DD`
- validation:
  - 只有当 `selector = "fixed_day"` 时才允许非空

### `[archive.download]`

#### `enabled`

- type: `bool`
- required: yes
- default: `true`

#### `base_url`

- type: `string`
- required: yes
- default: `"https://data.gharchive.org"`

#### `timeout_secs`

- type: `integer`
- required: yes
- default: `60`
- min: `5`

#### `max_parallel`

- type: `integer`
- required: yes
- default: `4`
- min: `1`
- max: `24`

#### `user_agent`

- type: `string`
- required: yes
- default: `"songh/0.1"`

### `[archive.normalize]`

#### `codec`

- type: `string`
- required: yes
- allowed:
  - `"jsonl.zst"`
  - `"jsonl.gz"`
- default: `"jsonl.zst"`

#### `write_minute_index`

- type: `bool`
- required: yes
- default: `true`

#### `write_stats`

- type: `bool`
- required: yes
- default: `true`

#### `drop_secondary_events`

- type: `bool`
- required: yes
- default: `true`

冻结说明：

- V1 明确丢弃 10 类之外的次级事件

### `[replay]`

#### `max_events_per_second`

- type: `integer`
- required: yes
- default: `4`
- fixed: `4`

#### `dedupe_window_secs`

- type: `integer`
- required: yes
- default: `600`
- fixed: `600`

#### `selection_order`

- type: `array<string>`
- required: yes
- default:
  - `"weight_desc"`
  - `"created_at_asc"`
  - `"event_id_asc"`

#### `overflow_policy`

- type: `string`
- required: yes
- allowed:
  - `"drop_and_count"`
- default: `"drop_and_count"`

### `[fallback]`

#### `enabled`

- type: `bool`
- required: yes
- default: `true`

#### `density_scale`

- type: `float`
- required: yes
- default: `0.5`
- min: `0.0`
- max: `1.0`

冻结说明：

- “进一步稀疏一倍”冻结为 `0.5`

#### `seed`

- type: `integer`
- required: no
- default: `0`
- meaning:
  - `0` 表示启动时自动生成
  - 非 `0` 表示固定种子

#### `density_source`

- type: `string`
- required: yes
- allowed:
  - `"history_if_available"`
  - `"builtin_only"`
- default: `"history_if_available"`

#### `synthetic_repo_prefix`

- type: `string`
- required: yes
- default: `"synthetic/repo"`

#### `synthetic_actor_prefix`

- type: `string`
- required: yes
- default: `"synthetic_actor"`

### `[events]`

#### `primary_types`

- type: `array<string>`
- required: yes
- fixed content:
  - `"CreateEvent"`
  - `"DeleteEvent"`
  - `"PushEvent"`
  - `"IssuesEvent"`
  - `"IssueCommentEvent"`
  - `"CommitCommentEvent"`
  - `"PullRequestEvent"`
  - `"PublicEvent"`
  - `"ForkEvent"`
  - `"ReleaseEvent"`

#### `hash_len_default`

- type: `integer`
- required: yes
- default: `8`
- min: `4`
- max: `16`

### `[events.weights]`

所有字段：

- type: `integer`
- required: yes
- min: `1`
- max: `100`

冻结默认值：

- `CreateEvent = 10`
- `DeleteEvent = 20`
- `PushEvent = 30`
- `IssuesEvent = 40`
- `IssueCommentEvent = 50`
- `CommitCommentEvent = 60`
- `PullRequestEvent = 70`
- `PublicEvent = 80`
- `ForkEvent = 90`
- `ReleaseEvent = 100`

### `[text]`

#### `template`

- type: `string`
- required: yes
- default: `"{repo}/{hash:8}"`

#### `unknown_field_policy`

- type: `string`
- required: yes
- allowed:
  - `"error"`
- default: `"error"`

#### `empty_field_policy`

- type: `string`
- required: yes
- allowed:
  - `"render_empty"`
- default: `"render_empty"`

#### `max_rendered_chars`

- type: `integer`
- required: yes
- default: `64`
- min: `8`

#### `allow_multiline`

- type: `bool`
- required: yes
- default: `false`

冻结说明：

- V1 文本只允许单行

### `[audio]`

#### `sample_rate`

- type: `integer`
- required: yes
- fixed: `48000`

#### `channels`

- type: `integer`
- required: yes
- default: `2`
- fixed: `2`

#### `master_gain_db`

- type: `float`
- required: yes
- default: `0.0`

#### `voice_mode_default`

- type: `string`
- required: yes
- allowed:
  - `"synth"`
  - `"wav_sample"`
  - `"hybrid"`
- default: `"hybrid"`

### `[audio.background]`

#### `enabled`

- type: `bool`
- required: yes
- default: `false`

#### `wav_path`

- type: `string`
- required: no
- default: `""`
- validation:
  - 当 `enabled = true` 时必须非空
  - 只允许 `.wav`

#### `gain_db`

- type: `float`
- required: yes
- default: `-9.0`

#### `loop`

- type: `bool`
- required: yes
- default: `true`

### `[audio.mix]`

#### `crossfade_ms`

- type: `integer`
- required: yes
- default: `80`
- min: `0`

#### `limiter_enabled`

- type: `bool`
- required: yes
- default: `true`

#### `limiter_ceiling_dbfs`

- type: `float`
- required: yes
- default: `-1.0`

### `[audio.voices.<EventType>]`

10 个主事件都必须有一个 voice section。

每个 voice section 共享字段：

#### `enabled`

- type: `bool`
- required: yes
- default: `true`

#### `mode`

- type: `string`
- required: yes
- allowed:
  - `"synth"`
  - `"wav_sample"`
  - `"hybrid"`

#### `preset`

- type: `string`
- required: yes
- meaning: 逻辑预设名，不要求现在就定义所有 DSP 细节

#### `sample_path`

- type: `string`
- required: no
- default: `""`
- validation:
  - 当 `mode = "wav_sample"` 时必须非空
  - 当 `mode = "hybrid"` 时可选

#### `gain_db`

- type: `float`
- required: yes
- default: `0.0`

#### `duration_ms`

- type: `integer`
- required: yes
- default: `900`
- min: `50`

#### `pan`

- type: `float`
- required: yes
- default: `0.0`
- min: `-1.0`
- max: `1.0`

### `[video.canvas]`

#### `width`

- type: `integer`
- required: yes
- default: `1920`
- min: `320`

#### `height`

- type: `integer`
- required: yes
- default: `1080`
- min: `240`

#### `fps`

- type: `integer`
- required: yes
- default: `30`
- min: `1`
- max: `60`

### `[video.palette]`

#### `theme`

- type: `string`
- required: yes
- allowed:
  - `"solarized_dark"`
- default: `"solarized_dark"`

#### `background_hex`

- type: `string`
- required: yes
- default: `"#002b36"`

#### `text_hex`

- type: `string`
- required: yes
- default: `"#fdf6e3"`

#### `accent_hex`

- type: `string`
- required: yes
- default: `"#b58900"`

### `[video.text]`

#### `font_path`

- type: `string`
- required: yes
- default: `"assets/1942.ttf"`

#### `font_size_min`

- type: `integer`
- required: yes
- default: `14`
- min: `4`

#### `font_size_max`

- type: `integer`
- required: yes
- default: `42`
- min: `4`
- validation:
  - 必须 `>= font_size_min`

#### `stroke_width`

- type: `integer`
- required: yes
- default: `2`
- min: `0`

#### `initial_alpha`

- type: `integer`
- required: yes
- default: `220`
- range: `0..255`

#### `bottom_spawn_min_ratio`

- type: `float`
- required: yes
- default: `0.50`
- min: `0.0`
- max: `1.0`

#### `bottom_spawn_max_ratio`

- type: `float`
- required: yes
- default: `0.95`
- min: `0.0`
- max: `1.0`
- validation:
  - 必须 `>= bottom_spawn_min_ratio`

### `[video.motion]`

#### `mode`

- type: `string`
- required: yes
- allowed:
  - `"vertical"`
  - `"fixed_angle"`
  - `"random_angle"`
- default: `"vertical"`

#### `angle_deg`

- type: `float`
- required: no
- default: `0.0`
- validation:
  - 当 `mode = "fixed_angle"` 时使用

#### `random_min_deg`

- type: `float`
- required: no
- default: `-25.0`
- validation:
  - 当 `mode = "random_angle"` 时使用

#### `random_max_deg`

- type: `float`
- required: no
- default: `25.0`
- validation:
  - 当 `mode = "random_angle"` 时使用
  - 必须 `> random_min_deg`

#### `speed_px_per_sec`

- type: `float`
- required: yes
- default: `180.0`
- min: `1.0`

### `[outputs]`

#### `enable_rtmp`

- type: `bool`
- required: yes
- default: `false`

#### `enable_local_record`

- type: `bool`
- required: yes
- default: `true`

#### `tee_muxer`

- type: `bool`
- required: yes
- default: `true`

冻结说明：

- V1 默认单次编码，多路输出

### `[outputs.rtmp]`

#### `url`

- type: `string`
- required: no
- default: `""`
- validation:
  - 当 `enable_rtmp = true` 时，必须由 env 或 local override 提供

#### `container`

- type: `string`
- required: yes
- allowed:
  - `"flv"`
- default: `"flv"`

### `[outputs.record]`

#### `enabled`

- type: `bool`
- required: yes
- default: `true`

#### `path`

- type: `string`
- required: yes
- default: `"var/songh/records/{date}/{label}.flv"`

#### `container`

- type: `string`
- required: yes
- allowed:
  - `"flv"`
- default: `"flv"`

冻结说明：

- 默认本地录制容器已拍板为 `.flv`

### `[observe]`

#### `log_level`

- type: `string`
- required: yes
- allowed:
  - `"trace"`
  - `"debug"`
  - `"info"`
  - `"warn"`
  - `"error"`
- default: `"info"`

#### `emit_stats_every_secs`

- type: `integer`
- required: yes
- default: `30`
- min: `1`

#### `write_runtime_report`

- type: `bool`
- required: yes
- default: `true`

## template syntax freeze

### supported syntax

- `{field}`
- `{field:N}`

其中：

- `field` 必须来自允许字段表
- `N` 表示前缀截断长度

### allowed fields

- `repo`
- `repo_owner`
- `repo_name`
- `type`
- `actor`
- `hash`
- `id`
- `weight`
- `hour`
- `minute`
- `second`

### unsupported syntax

V1 明确不支持：

- 条件表达式
- 默认值表达式
- 嵌套模板
- 多行模板
- 函数调用

## validation freeze

启动前校验必须一次完成，不允许边跑边猜。

### fatal errors

- 运行模式非法
- `selector = "fixed_day"` 但 `fixed_day` 为空
- `enable_rtmp = true` 但没有 RTMP url
- 背景启用但 `wav_path` 为空
- `wav_path` 不是 `.wav`
- `font_size_max < font_size_min`
- `random_max_deg <= random_min_deg`
- 模板含未知字段
- 本地录制容器不是 `flv`

### warnings only

- `enable_rtmp = false` 且 `enable_local_record = false`
- `fallback.enabled = false` 但 archive 目录为空
- `master_gain_db` 明显过高

## frozen defaults that matter

实现前最重要的默认值冻结为：

- `mode = "archive_replay"`
- `selector = "latest_complete_day"`
- `preferred_offset_days = 2`
- `max_events_per_second = 4`
- `dedupe_window_secs = 600`
- `fallback.density_scale = 0.5`
- `sample_rate = 48000`
- `video.canvas = 1920x1080@30`
- `video.motion.mode = "vertical"`
- `text.template = "{repo}/{hash:8}"`
- `outputs.record.container = "flv"`

## paired artifact

本规格对应模板文件：

- `docs/plans/260321-songh-template.toml`

两者必须保持同步：

- 规格文档负责解释
- 模板文件负责示范

# refer.

## model

- Codex (GPT-5)

## basis

- `docs/plans/260320-songh-issue-2-architecture-plan.md`
- Issue 决策评论: <https://github.com/41490/chao5whistler/issues/2#issuecomment-4101418171>
- Issue 继续推进回复: <https://github.com/41490/chao5whistler/issues/2#issuecomment-4101811137>
