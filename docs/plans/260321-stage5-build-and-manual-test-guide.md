# Stage 5 Build And Manual Test Guide

日期: `2026-03-21`  
主机: `x86_64-unknown-linux-gnu`

## 1. 当前本机构建结论

- Linux amd64 已实测可编译:
  - `cargo build --release --target x86_64-unknown-linux-gnu`
  - 产物可放到 `ops/bin/musikalisches-linux-amd64`
- macOS arm64 在当前主机尚不能直接链出最终二进制:
  - `cargo build --release --target aarch64-apple-darwin`
  - 当前阻塞: 缺 macOS SDK / Darwin linker
  - 现场报错关键字:
    - `xcrun --sdk macosx --show-sdk-path failed`
    - `cc: error: unrecognized command-line option '-arch'`
    - `cc: error: unrecognized command-line option '-mmacosx-version-min=11.0.0'`

结论:

- 当前仓库已经准备好双目标构建路径
- Linux amd64 可在本机直接出包
- macOS arm64 需要补 `CARGO_TARGET_AARCH64_APPLE_DARWIN_LINKER` 或 `o64-clang`，并提供 macOS SDK 后再出包

## 2. 推荐构建命令

统一脚本:

```bash
bash src/musikalisches/tools/build_release_bins.sh
```

脚本行为:

- 总是构建 `x86_64-unknown-linux-gnu`
- 输出:
  - `ops/bin/musikalisches`
  - `ops/bin/musikalisches-linux-amd64`
- 只有在检测到 Darwin linker 前提满足时，才尝试构建:
  - `ops/bin/musikalisches-macos-arm64`

手工单独构建:

```bash
cargo build --release --target x86_64-unknown-linux-gnu
install -m 755 target/x86_64-unknown-linux-gnu/release/musikalisches ops/bin/musikalisches-linux-amd64
```

```bash
export CARGO_TARGET_AARCH64_APPLE_DARWIN_LINKER=o64-clang
export SDKROOT=/path/to/MacOSX.sdk
cargo build --release --target aarch64-apple-darwin
install -m 755 target/aarch64-apple-darwin/release/musikalisches ops/bin/musikalisches-macos-arm64
```

## 3. SoundFont 约定

默认发现顺序:

1. `--soundfont /path/to/file.sf2`
2. `MUSIKALISCHES_SOUNDFONT`
3. `ops/assets/soundfonts/default.sf2`
4. 系统常见路径，例如 `/usr/share/sounds/sf2/TimGM6mb.sf2`

无 `.sf2` 时:

- 仍可运行
- 后端会自动回退到 deterministic additive fallback
- `m1_validation_report.json.summary.audio_render_backend` 会明确标记

## 4. 分流输出人工检测流程

本阶段“分流”先看两条输出总线:

- 音频总线: `offline_audio.wav`
- 分析总线: `analysis_window_sequence.json`

同时保留 stream skeleton:

- `stream_loop_plan.json`

### 4.1 Fallback 路径检测

执行:

```bash
cargo run -- render-audio \
  --work mozart_dicegame_print_1790s \
  --demo-rolls \
  --loop-count 4 \
  --analysis-window-ms 40 \
  --output-dir ops/out/stream-demo
```

结构校验:

```bash
python src/musikalisches/tools/validate_m1_artifacts.py ops/out/stream-demo
```

人工观察点:

- `render_request.json`
  - `loop_count = 4`
  - `analysis_window_ms = 40`
  - `soundfont_source = "fallback_none"` 或系统默认来源
- `stream_loop_plan.json`
  - `cycles` 长度等于 `4`
  - `buses` 至少有 `main_audio_mix` 与 `analyzer_clock`
- `analysis_window_sequence.json`
  - `windows` 非空
  - `clock_frame` 单调递增
  - `loop_count` 与 `stream_loop_plan.json` 一致
- `m1_validation_report.json`
  - `status = passed`
  - `checks_failed = 0`
  - `audio_render_backend = fallback_additive` 或其它实际后端

主观试听:

```bash
ffplay -autoexit -nodisp ops/out/stream-demo/offline_audio.wav
```

听感重点:

- 每个 cycle 之间不应出现静音断缝
- 双声部应保持左右有轻微分离
- 总音量不应炸裂或明显削波

### 4.2 SoundFont 真实路径检测

若已有标准资产:

```bash
export MUSIKALISCHES_SOUNDFONT=/path/to/default.sf2
```

或直接:

```bash
cargo run -- render-audio \
  --work mozart_dicegame_print_1790s \
  --demo-rolls \
  --loop-count 4 \
  --soundfont /path/to/default.sf2 \
  --output-dir ops/out/stream-sf2
```

检查点:

- `render_request.json.soundfont_source` 应为 `env` 或 `cli`
- `m1_validation_report.json.summary.audio_render_backend` 应为 `soundfont_rustysynth`
- `analysis_window_sequence.json.render_backend` 应与 validation report 一致
- `offline_audio.wav` 可播放且时长与 `stream_loop_plan.json.total_duration_seconds` 对齐

### 4.3 Synth Profile 路径检测

默认 profile:

- `src/musikalisches/runtime/config/stage5_default_synth_profile.json`

运行后应导出:

- `synth_routing_profile.json`

人工检查:

- `profile_id` 已写入
- 两个 `voice_groups` 各有唯一 `channel`
- `part_index 1/2` 都存在
- `base_amplitude / left_gain / right_gain` 为正值

如需自定义 profile:

```bash
cargo run -- render-audio \
  --work mozart_dicegame_print_1790s \
  --demo-rolls \
  --synth-profile /path/to/profile.json \
  --output-dir ops/out/stream-custom-profile
```

### 4.4 阶段验收人工结论模板

建议人工记录以下 6 项:

1. 构建目标: `linux-amd64` / `macos-arm64`
2. 声音后端: `fallback_additive` / `soundfont_rustysynth`
3. loop 连续性: `pass/fail`
4. analysis 时钟单调性: `pass/fail`
5. synth profile 装载结果: `default/custom + profile_id`
6. 是否观察到爆音、静音断缝、错拍或明显左右失衡

## 5. 进入下一阶段前的最小门槛

- Linux amd64 release binary 已生成
- `render-audio --loop-count 4` 可稳定输出
- validator 通过
- `stream_loop_plan.json` / `analysis_window_sequence.json` / `offline_audio.wav` 三者互相对齐
- 至少完成 1 次 SoundFont 真路径检测，或明确记录外部资产阻塞原因
