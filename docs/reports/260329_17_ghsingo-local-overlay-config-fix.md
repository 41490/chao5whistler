# 260329 #17 ghsingo local overlay config fix

## Issue

YouTube 后台未收到直播内容。

## Root Cause

`config.Load()` 只读 `--config` 指定的单一文件。用户创建的 `ghsingo.local.toml`
(含 `mode = "rtmps"` + 推流密钥) 从未被加载，FFmpeg 以 `mode=local` 启动，
输出到本地文件 `var/ghsingo/records/2026-03-28.flv`。

CLI 日志证据:

```
INFO ffmpeg started pid=1635743 mode=local
Output #0, flv, to 'var/ghsingo/records/2026-03-28.flv'
```

## Fix

`internal/config/config.go` — `Load()` 增加 local overlay 逻辑:

1. 加载 base config (e.g. `ghsingo.toml`)
2. 推导 overlay 路径 (`ghsingo.local.toml`)
3. 若 overlay 存在，TOML decode 到同一 struct (merge 语义，只覆盖有值字段)
4. 执行 validate

新增 `localOverlayPath()` helper 函数。

## Files Changed

| File | Change |
|---|---|
| `internal/config/config.go` | `Load()` + `localOverlayPath()` |
| `internal/config/config_test.go` | +2 tests: `TestLoadLocalOverlay`, `TestLoadNoLocalOverlay` |

## Test Results

```
ok  internal/config    4/4 pass
ok  all packages       18/18 pass (no regression)
```

## Verification

用户重新执行 `./bin/live --config ghsingo.toml` 后，程序将自动合并
`ghsingo.local.toml`，以 `mode=rtmps` 启动推流到 YouTube。

## Next Steps

1. 用户重新推流验证 YouTube 后台收到内容
2. P1: `target_date = "yesterday"` 自动日期计算
3. P1: systemd unit 部署
