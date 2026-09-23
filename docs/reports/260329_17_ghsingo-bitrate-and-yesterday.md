# 260329 #17 ghsingo bitrate fix + target_date yesterday

## 1. Bitrate Fix

### Problem

YouTube 报警: 当前码率 791.84 Kbps，建议 ≥ 2500 Kbps。

原因: FFmpeg 未设 `-b:v`，libx264 默认 CRF 23 模式，在 720p ultrafast 下仅产生 ~700-800 Kbps。

### Fix

- `stream.Options` 增加 `VideoBitrateKbps` 字段
- `BuildArgs()` 当 `VideoBitrateKbps > 0` 时追加 `-b:v {N}k`
- `config.Output` 增加 `video_bitrate_kbps` TOML 字段
- `ghsingo.toml` 默认设为 2500 (YouTube 720p 最低建议值)

总码率: 2500 (video) + 128 (audio) = 2628 Kbps ≥ 2500 Kbps。

## 2. target_date = "yesterday"

### Problem

`prepare` 命令中 `target_date = "yesterday"` 只有 placeholder，直接 exit(1)。

### Fix

- `config.ResolveTargetDate()` 解析 "yesterday"/"today" 为 YYYY-MM-DD
- `prepare/main.go` 调用 `config.ResolveTargetDate()` 替代硬编码检查

### Usage

```toml
# ghsingo.toml
[archive]
target_date = "yesterday"   # 自动解析为昨日日期

[archive.download]
enabled = true               # 启用自动下载
```

```bash
./bin/prepare --config ghsingo.toml   # 下载昨日数据 + 生成 daypack
./bin/live --config ghsingo.toml      # 推流
```

## Files Changed

| File | Change |
|---|---|
| `internal/config/config.go` | +`VideoBitrateKbps` field, +`ResolveTargetDate()` |
| `internal/config/config_test.go` | +`TestResolveTargetDate` |
| `internal/stream/ffmpeg.go` | +`VideoBitrateKbps` in Options, `-b:v` in BuildArgs |
| `internal/stream/ffmpeg_test.go` | +`TestBuildArgsVideoBitrate`, +`TestBuildArgsNoVideoBitrateWhenZero` |
| `cmd/live/main.go` | pass `VideoBitrateKbps` to stream.Options |
| `cmd/prepare/main.go` | use `config.ResolveTargetDate()` |
| `ghsingo.toml` | add `video_bitrate_kbps = 2500` |

## Test Results

All packages pass, no regression.
