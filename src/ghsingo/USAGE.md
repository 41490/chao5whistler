# ghsingo Usage

## 主要流程

`ghsingo` 当前分成三段：

1. 准备事件与声音素材
2. 准备背景图序列
3. 本地渲染或推流直播

常用目录与配置：

- 主配置: `src/ghsingo/ghsingo.toml`
- 背景抽帧配置: `src/ghsingo/movpixer.toml`
- GHArchive 原始小时缓存: `var/ghsingo/archive/raw/`
- 本地输出目录: `var/ghsingo/records/`
- 背景序列目录: `ops/assets/backgrounds/movpixer/`

## 编译

在 `src/ghsingo` 目录执行：

```bash
make build
```

只编译某个工具：

```bash
make build-live
make build-movpixer
```

交叉编译 `movpixer`：

```bash
make build-movpixer-linux-amd64
make build-movpixer-darwin-arm64
```

输出文件分别位于：

- `ops/bin/movpixer-linux-amd64`
- `ops/bin/movpixer-darwin-arm64`

## 素材准备

准备音频素材：

```bash
make prepare-assets
```

准备 gharchive 日包与事件缓存：

```bash
make run-prepare
```

如需让 `prepare` 自动下载缺失的 GHArchive 小时文件，开启：

```toml
[archive.download]
enabled = true
```

如只想处理特定 UTC 小时段，可直接运行：

```bash
../../ops/bin/prepare --config ghsingo.toml --hours 16
../../ops/bin/prepare --config ghsingo.toml --hours 12-17
```

`--hours` 使用 GHArchive 的 UTC 小时编号，不是本地时区小时。

关键配置项在 `ghsingo.toml`：

- `[archive] target_date`: 指定要使用哪一天的 GitHub 历史事件
- `[archive.download]`: 控制是否自动下载缺失的小时文件
- `[events]`: 控制纳入哪些事件类型
- `[audio.*]`: 控制 BGM、事件音色、增益与时长

## movpixer 用法

`movpixer` 用于从视频中抽取代表帧，生成像素化背景序列。

默认运行：

```bash
make run-movpixer
```

等价命令：

```bash
../../ops/bin/movpixer --config movpixer.toml
```

### 指定不同视频和输出目录

修改 `movpixer.toml` 中这几项：

```toml
[input]
video_path = "../../ops/assets/vid/your-video.mp4"

[output]
dir = "../../ops/assets/backgrounds/movpixer/your-video-name"
png_prefix = "frame"
resolution = "1280x720"
```

生成后，目标目录里会包含：

- 一组 `frame-0001.png` 之类的 PNG
- `manifest.json`

`manifest.json` 会记录当前序列帧清单，直播渲染时按它顺序轮换。

`resolution` 可选；不写时保持源视频分辨率，写了则按 `宽x高` 输出，例如 `1280x720`。
缩放语义与直播阶段一致：先覆盖目标画布，再居中裁切到最终尺寸。

### 多集视频的推荐目录组织

建议每一集一个独立目录，例如：

```text
ops/assets/backgrounds/movpixer/
  Headspace.S01E01/
  Headspace.S01E02/
  Headspace.S01E07/
```

这样后续切换背景时，只需要改 `ghsingo.toml` 里的 `sequence_dir`。
现在推荐改 `sequence_dirs`；`sequence_dir` 仅保留兼容。

### 背景效果参数

`movpixer.toml` 中可调：

- `grid_width_px` / `grid_height_px`: 像素块大小
- `glow_strength`: 单格边缘向内的柔和光强
- `glow_width_px`: 单格边缘向内发光长度
- `blur_radius_px`: 像素化后整体模糊半径
- `brightness_scale`: 整体亮度缩放，`0.68` 表示降低 32%
- `window_secs`: 每隔多少秒抽一个代表帧
- `max_frames`: 限制最多生成多少帧，`0` 表示不限制
- `resolution`: 输出 PNG 的目标分辨率，格式为 `宽x高`；为空时沿用源视频尺寸

## 使用背景序列进行本地渲染

在 `ghsingo.toml` 中启用：

```toml
[video.background]
mode = "mosaic_sequence"
sequence_dirs = ["../../ops/assets/backgrounds/movpixer/Headspace.S01E07"]
switch_every_secs = 2.0
fade_secs = 0.2
```

也支持 glob：

```toml
[video.background]
mode = "mosaic_sequence"
sequence_dirs = ["../../ops/assets/backgrounds/movpixer/ScavengersReign0*"]
switch_every_secs = 2.0
fade_secs = 0.2
```

规则固定如下：

- 若 `sequence_dirs` 非空，只使用 `sequence_dirs`
- 否则回退使用 `sequence_dir`
- 每个 pattern 按声明顺序展开
- glob 结果按目录名字典序排序
- 同一目录若被多个 pattern 命中，只使用一次
- 每个目录优先按 `manifest.json` 顺序取帧，否则按 `*.png` 名字典序
- 所有目录帧会被串成一个总序列，播完后从头循环
- 若某个 pattern 没匹配到目录，或目录里没有可用 PNG，会直接报错退出

然后执行：

```bash
make run-live
```

生成本地视频：

- 输出路径由 `[output.local].path` 控制
- 默认写到 `var/ghsingo/records/`

快速生成 5 分钟本地预览：

```bash
make run-live-5m
```

如果要把某个 UTC 时间窗压缩成更短的离线音频，可直接用：

```bash
../../ops/bin/render-audio-v2 \
  --config ../../var/ghsingo/sonify/ghsingo-hourly.toml \
  --start-clock 16:00 \
  --source-span 1h \
  --duration 5m \
  -o ../../ops/out/sonify/example-16utc-5m.m4a
```

## 直播方式

### 本地文件渲染

配置：

```toml
[output]
mode = "local"

[output.local]
path = "../../var/ghsingo/records/{date}.flv"
```

执行：

```bash
make run-live
```

### RTMPS 推流

配置：

```toml
[output]
mode = "rtmps"

[output.rtmps]
url = "rtmps://..."
```

执行：

```bash
make run-live
```

## 下次更换背景时需要改哪里

如果要在下次生成视频或直播时换成新的背景系列，通常只改两处：

1. `src/ghsingo/movpixer.toml`
   - 改 `input.video_path`
   - 改 `output.dir`

2. `src/ghsingo/ghsingo.toml`
   - 优先改 `video.background.sequence_dirs`
   - 兼容场景下也可改 `video.background.sequence_dir`
   - 如有需要改 `switch_every_secs` 和 `fade_secs`

完成后执行：

```bash
make run-movpixer
make run-live
```
