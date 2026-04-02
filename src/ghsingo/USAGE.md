# ghsingo Usage

## 主要流程

`ghsingo` 当前分成三段：

1. 准备事件与声音素材
2. 准备背景图序列
3. 本地渲染或推流直播

常用目录与配置：

- 主配置: `src/ghsingo/ghsingo.toml`
- 背景抽帧配置: `src/ghsingo/movpixer.toml`
- 本地输出目录: `src/ghsingo/var/ghsingo/records/`
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

- `src/ghsingo/bin/movpixer-linux-amd64`
- `src/ghsingo/bin/movpixer-darwin-arm64`

## 素材准备

准备音频素材：

```bash
make prepare-assets
```

准备 gharchive 日包与事件缓存：

```bash
make run-prepare
```

关键配置项在 `ghsingo.toml`：

- `[archive] target_date`: 指定要使用哪一天的 GitHub 历史事件
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
./bin/movpixer --config movpixer.toml
```

### 指定不同视频和输出目录

修改 `movpixer.toml` 中这几项：

```toml
[input]
video_path = "../../ops/assets/vid/your-video.mp4"

[output]
dir = "../../ops/assets/backgrounds/movpixer/your-video-name"
png_prefix = "frame"
```

生成后，目标目录里会包含：

- 一组 `frame-0001.png` 之类的 PNG
- `manifest.json`

`manifest.json` 会记录当前序列帧清单，直播渲染时按它顺序轮换。

### 多集视频的推荐目录组织

建议每一集一个独立目录，例如：

```text
ops/assets/backgrounds/movpixer/
  Headspace.S01E01/
  Headspace.S01E02/
  Headspace.S01E07/
```

这样后续切换背景时，只需要改 `ghsingo.toml` 里的 `sequence_dir`。

### 背景效果参数

`movpixer.toml` 中可调：

- `grid_width_px` / `grid_height_px`: 像素块大小
- `glow_strength`: 单格边缘向内的柔和光强
- `glow_width_px`: 单格边缘向内发光长度
- `blur_radius_px`: 像素化后整体模糊半径
- `brightness_scale`: 整体亮度缩放，`0.68` 表示降低 32%
- `window_secs`: 每隔多少秒抽一个代表帧
- `max_frames`: 限制最多生成多少帧，`0` 表示不限制

## 使用背景序列进行本地渲染

在 `ghsingo.toml` 中启用：

```toml
[video.background]
mode = "mosaic_sequence"
sequence_dir = "../../ops/assets/backgrounds/movpixer/Headspace.S01E07"
switch_every_secs = 2.0
fade_secs = 0.2
```

然后执行：

```bash
make run-live
```

生成本地视频：

- 输出路径由 `[output.local].path` 控制
- 默认写到 `src/ghsingo/var/ghsingo/records/`

快速生成 5 分钟本地预览：

```bash
make run-live-5m
```

## 直播方式

### 本地文件渲染

配置：

```toml
[output]
mode = "local"

[output.local]
path = "var/ghsingo/records/{date}.flv"
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
   - 改 `video.background.sequence_dir`
   - 如有需要改 `switch_every_secs` 和 `fade_secs`

完成后执行：

```bash
make run-movpixer
make run-live
```
