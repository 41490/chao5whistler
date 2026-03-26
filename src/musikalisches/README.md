# chao5whistler/src/musikalisches
> 莫扎特印刷骰子游戏实现入口

## current frozen target

- `work_id`: `mozart_dicegame_print_1790s`
- `canonical_witness_id`: `rellstab_1790`
- `verification_witness_id`: `simrock_1793`
- current plan stage: `stage 7: bridge freeze + pre-stage8 hardening`
- first runtime milestone: `offline realization + offline audio/video preview + local bridge smoke`

## boundary

当前入口针对的是 **1790s printed dice-game tradition**，不是 `K.516f autograph`。

因此这里的推进顺序是：

1. source provenance
2. mother-score engineering
3. rules reconciliation
4. ingest contract
5. Rust runtime implementation

当前已完成：

- canonical provenance 冻结
- canonical mother score 冻结
- rules freeze 与 `16x11` 规则表对账完成
- `witness_diff.json` 初版已建立，且保持 `rellstab_1790` 为唯一 canonical runtime 定义
- `ingest/fragments.json` / `ingest/measures.json` / `ingest/validation_report.json` 已冻结
- ingest 已把空 part 显式补成 rest timeline，runtime 不再需要直接解析 `mother_score.musicxml`
- Rust CLI crate 已建立：`cargo run -- render-audio ...`
- runtime 已可输出 realized fragment sequence / note-event sequence / event-transition sequence / synth-event sequence / stream-loop plan / analyzer clock+envelope / offline WAV / M1 validation report
- stage 5 已加入 golden roll cases 与小型 artifact summary，便于回归和 review
- note-event / transition 契约已显式带出 `voice_group` 元数据，可为后续合成器/分析器对接保留分组边界
- `render-audio` 已可在提供 `--soundfont` 时走 `rustysynth` 真实合成；未提供时按 `--soundfont` > `MUSIKALISCHES_SOUNDFONT` > repo/system default 的顺序发现，找不到才回退到内置 deterministic fallback
- stage 5 已补 `loop_count` 连续播放骨架、`synth_profile` 路由配置、以及统一 analyzer 时钟输出，便于进入视频/直播链路前先做人工检验
- stage 6 已补 analyzer -> video stub 预演入口，可把 stage 5 分析输出转成视觉 stub 契约与静态预览
- stage 6 已进入 `render-video` skeleton，可把 stub scene 进一步冻结为离线 frame contract 和本地 mp4 preview
- stage 6 已把默认 visual scene profile 收敛到 repo 配置文件，并补了 2 个可版本化 profile 变体以及单独的 SF2 visual smoke path
- stage 6 scene contract 已升级到 P3：`title_area` / `footer_progress_area` / `selector_label_sprites` / `spectrum_trails` / `short_safe_layout` / `text_overrides` 均进入 schema 与 stub scene
- stage 6 标题文案已改为从 `.toml` 注入；默认走 `src/musikalisches/runtime/config/stage6_default_text_overrides.toml`，支持 `\n` 换行并按中心对齐解析
- `render-video` manifest / validator 现已显式冻结 preview video 的 `expected_frame_count` / `expected_fps` / `expected_duration_seconds`，并补 `sha256` / 文件大小 / fps+duration+keyframe 容差 contract
- 如构建机有 `ffprobe`，`video_render_manifest.json` 会额外带出 mp4 的 stream/container/keyframe 摘要，供后续运维验收对账
- stage 7 已冻结默认 `RTMPS + FLV` bridge profile，并新增 builder / validator / guide
- stage 7 live bridge 已补 `once` / `infinite` 两种 loop mode，默认通过 `MUSIKALISCHES_STAGE7_LOOP_MODE=infinite` 连续对齐 stage5 loop plan 与 stage6 render duration
- stage 7 runtime 已补 `RTMPS preflight` 与可重连执行器：正式推流前先检查协议支持 / DNS / TCP / 轻量 publish probe，运行中真正执行 backoff / retry budget / 连续失败上限
- stage 7 runtime 已补 redacted stderr log / exit report / aggregate runtime report / failure taxonomy，可区分 `handshake_failure` / `auth_failure` / `network_jitter` / `remote_disconnect` / `ingest_configuration_failure`
- stage 7 已基于当前 bridge manifest 生成 `stage7_soak_plan.json`，并提供 `stage7-soak-check` 作为进入 stage 8 前的长时 soak gate
- stage 7 现已补 repo-managed `ffmpeg/ffprobe` 构建入口，可在 `ops/bin/` 内固定出带 `rtmps` output 的本地 toolchain，避免依赖宿主机系统包差异

当前仍未完成：

- stage 6 正式高性能视频编码器
- stage 8 soak / operations

在 stage 5 之前，不应把这里描述成“已经开始实现 K.516f 无限直播工具”。

## implementation gate

只有满足以下条件，才允许正式进入 stage 5 runtime Rust 编码：

1. canonical witness 已冻结
2. `mother_score.musicxml` 不再是 placeholder
3. `rules.json` 与 `16x11` 表完成核对
4. ingest 输出契约已冻结

当前 1-4 已满足，且 stage 5 的最小 M1 pipeline 已可运行。

当前这个目录主要承载执行入口说明和本地校验工具。

统一的人肉检验入口已整理到：

```bash
make -C src/musikalisches help
```

## frozen ops target

根据 `2026-03-22` 的 issue comment，当前运维优先冻结为：

- 分辨率：`1280x720`
- 帧率：`30 fps`
- 视频编码：`H.264`
- 视频 preset：`ultrafast`
- stage 7 目标音频码率：`128 Kbps`

边界说明：

- stage 6 当前产出的 `offline_preview.mp4` 仍是视频-only 本地预览，不含正式直播音轨
- 因此 `128 Kbps` 音频目标属于后续 stage 7 `FFmpeg / RTMP bridge` 的桥接规格，不是当前 stage 6 已完成能力

## ops prerequisites

推荐最小依赖：

- `python3`
- `rustup` stable / `cargo`
- `ffmpeg` + `ffprobe`

可选依赖：

- `MUSIKALISCHES_SOUNDFONT` 或 `SOUND_FONT=/path/to/*.sf2`
- 若已通过系统包安装 `FluidR3_GM.sf2`，`stage5-sf2` 现会自动尝试 `/usr/share/sounds/sf2/FluidR3_GM.sf2`

说明：

- 没有 `ffmpeg` 时，`stage6-video-render` 仍可生成 frame contract / poster，但 mp4 会被标记为 skipped
- 有 `ffmpeg` 但没有 `ffprobe` 时，可以出 mp4；但 preview video contract 无法做完整探测，运维机仍建议成对安装
- 推荐用 `rustup` 安装最新 stable Rust；不要依赖 Debian 仓库内过旧的 `rustc` / `cargo`
- `stage5-stream` 与 `stage5-sf2` 现已默认走持久化 unique-combination ledger，而不再固定 `--demo-rolls`
- 默认 stage5 synth profile 已切到 organ family GM 预设：`program 19 = Church Organ`、`program 20 = Reed Organ`
- 默认 ledger 路径分别为 `ops/out/state/musikalisches/stage5_stream_combination_ledger.json` 与 `ops/out/state/musikalisches/stage5_stream_sf2_combination_ledger.json`
- 每次 `stage5-stream` / `stage5-sf2` 成功运行后，artifact 目录会额外带出 `combination_selection.json`，并把同一份 selection 元数据写入 `render_request.json` / `stream_loop_plan.json` / `artifact_summary.json` / `m1_validation_report.json`
- stage 7 默认只产出本地 `flv` smoke 与 redacted live command，不默认发起真实推流
- 如系统自带 `ffmpeg` 缺少 `rtmps` output，可直接执行 `make -C src/musikalisches stage7-ffmpeg-build` 生成仓库内本地 toolchain，并由 stage6/stage7 目标自动优先使用 `ops/bin/ffmpeg` 与 `ops/bin/ffprobe`

## ops quickstart

最小推荐顺序：

```bash
make -C src/musikalisches stage6-scene-profile-check-all
make -C src/musikalisches stage5-stream
make -C src/musikalisches stage5-stream-check
make -C src/musikalisches stage6-video-stub
make -C src/musikalisches stage6-video-check
make -C src/musikalisches stage6-video-render
make -C src/musikalisches stage6-video-render-check
make -C src/musikalisches stage7-ffmpeg-check
make -C src/musikalisches stage7-bridge
make -C src/musikalisches stage7-bridge-check
make -C src/musikalisches stage7-soak-check
```

如需走 SoundFont smoke：

```bash
make -C src/musikalisches stage5-sf2
make -C src/musikalisches stage5-sf2-check
make -C src/musikalisches stage6-video-stub-sf2
make -C src/musikalisches stage6-video-check-sf2
make -C src/musikalisches stage6-video-render-sf2
make -C src/musikalisches stage6-video-render-check-sf2
```

如需覆盖默认 ledger 路径：

```bash
make -C src/musikalisches stage5-stream \
  STAGE5_LEDGER_PATH=/path/to/stage5_stream_combination_ledger.json
```

## stage 4 refresh

如需重新生成并校验 stage 4 ingest 产物：

```bash
python3 src/musikalisches/tools/freeze_ingest.py
python3 src/musikalisches/tools/validate_ingest_freeze.py
```

## stage 5 M1

构建 release binary：

```bash
bash src/musikalisches/tools/build_release_bins.sh
```

生成一套本地 M1 样例产物：

```bash
cargo run -- render-audio \
  --work mozart_dicegame_print_1790s \
  --demo-rolls \
  --loop-count 4 \
  --output-dir ops/out/m1-demo
```

如有 SoundFont，可走真实合成路径：

```bash
cargo run -- render-audio \
  --work mozart_dicegame_print_1790s \
  --demo-rolls \
  --soundfont /path/to/piano.sf2 \
  --loop-count 4 \
  --output-dir ops/out/m1-sf2
```

如需覆盖默认路由 profile：

```bash
cargo run -- render-audio \
  --work mozart_dicegame_print_1790s \
  --demo-rolls \
  --synth-profile /path/to/profile.json \
  --output-dir ops/out/m1-custom-profile
```

验收这套样例产物：

```bash
python3 src/musikalisches/tools/validate_m1_artifacts.py ops/out/m1-demo
```

人工构建与分流输出检验说明见：

```text
docs/plans/260321-stage5-build-and-manual-test-guide.md
```

## stage 6 preflight

从 stage 5 analyzer 产物生成视觉 stub：

```bash
make -C src/musikalisches stage6-scene-profile-check
make -C src/musikalisches stage6-scene-profile-check-all
make -C src/musikalisches stage6-video-stub
make -C src/musikalisches stage6-video-check
make -C src/musikalisches stage6-video-render
make -C src/musikalisches stage6-video-render-check
```

推荐验收顺序：

1. 先跑 `stage6-scene-profile-check-all`，确保 repo 内全部 profile 都过 contract
2. 再跑 `stage6-video-stub` + `stage6-video-check`，确认 analyzer -> scene 没有断口
3. 最后跑 `stage6-video-render` + `stage6-video-render-check`，确认 frame/mp4 preview contract 自洽

默认 visual scene profile:

```text
src/musikalisches/runtime/config/stage6_default_scene_profile.json
```

对应 schema:

```text
src/musikalisches/runtime/config/stage6_scene_profile.schema.json
```

默认标题 TOML:

```text
src/musikalisches/runtime/config/stage6_default_text_overrides.toml
```

可版本化 profile 变体:

```text
src/musikalisches/runtime/config/stage6_orbital_sunrise_scene_profile.json
src/musikalisches/runtime/config/stage6_blueprint_nocturne_scene_profile.json
```

如已有 SoundFont 路径样例产物，也可单独做一轮 visual smoke：

```bash
make -C src/musikalisches stage6-video-stub-sf2
make -C src/musikalisches stage6-video-check-sf2
make -C src/musikalisches stage6-video-render-sf2
make -C src/musikalisches stage6-video-render-check-sf2
```

如需覆盖默认标题文案来源：

```bash
make -C src/musikalisches stage6-video-stub \
  STAGE6_TEXT_CONFIG=/path/to/stage6_overrides.toml
```

P3 之后，`video_stub_scene.json` 里应额外能看到：

- `title_area`
- `footer_progress_area`
- `selector_label_sprites`
- `spectrum_trails`
- `short_safe_layout`
- `text_overrides`

stub 默认输出：

```text
ops/out/video-stub
```

render-video skeleton 默认输出：

```text
ops/out/video-render
```

render-video 重点验收文件：

```text
ops/out/video-render/video_render_manifest.json
ops/out/video-render/offline_frame_sequence.json
ops/out/video-render/video_render_poster.ppm
ops/out/video-render/stage6_render_validation_report.json
```

其中：

- `offline_frame_sequence.json.summary` 会显式带出 `frame_count` / `fps` / `frame_interval_seconds` / `render_duration_seconds`
- `video_render_manifest.json.artifact_integrity` 会带出 `visual_scene_profile.json` / `offline_frame_sequence.json` / `video_render_poster.ppm` / `offline_preview.mp4` 的 `sha256` 与 `size_bytes`
- `video_render_manifest.json.mp4_generation` 会显式带出 `expected_frame_count` / `expected_fps` / `expected_duration_seconds` / `video_codec` / `video_preset`，以及 `frame_count_tolerance` / `fps_tolerance` / `duration_tolerance_seconds` / `expected_keyframe_interval_frames`
- 如本机可用 `ffprobe`，manifest 还会带出 preview mp4 的 stream/container/keyframe 摘要，便于把编码结果和 contract 对齐
- 默认 ops 目标应优先使用 `stage6_default_scene_profile.json`，即 `1280x720 @ 30fps`
- 其它 scene profile 变体主要用于 contract 演化/回归，不应替代默认运维规格

说明文档见：

```text
docs/plans/260321-stage6-video-stub-guide.md
docs/plans/260321-stage6-render-video-guide.md
docs/plans/260322-stage7-stream-bridge-guide.md
```

## stage 7 bridge freeze

当前 stage 7 默认冻结为：

- ingest：`RTMPS + FLV`
- 视频：`1280x720 @ 30fps`
- 视频编码：`H.264 / libx264`
- preset：`ultrafast`
- 视频码率：`4000 Kbps CBR`
- keyframe：`2 seconds`
- 音频：`AAC stereo @ 44.1 KHz / 128 Kbps`
- 真实推流地址通过 `MUSIKALISCHES_RTMP_URL` 注入，不写入 manifest

当前 stage 7 会生成：

- `stage7_bridge_profile.json`
- `stream_bridge_manifest.json`
- `stream_bridge_ffmpeg_args.json`
- `stage7_failure_taxonomy.json`
- `stage7_soak_plan.json`
- `run_stage7_stream_bridge.sh`
- `stage7_bridge_smoke.flv`
- `stage7_bridge_validation_report.json`
- `stage7_soak_validation_report.json`
- `stage8_ops_readiness_report.json`（通过 `stage8-readiness-check` 生成）
- `stage8-samples/<run-label>/...`（通过 `stage8-sample-retain` 生成）

默认输出目录：

```text
ops/out/stream-bridge
```

当前 runtime / ops 约定：

- 如 `ops/bin/ffmpeg` / `ops/bin/ffprobe` 存在，stage6 / stage7 默认优先使用 repo-managed toolchain
- 可通过 `make -C src/musikalisches stage7-ffmpeg-build` 与 `stage7-ffmpeg-check` 显式重建并验证 `rtmps` output 能力
- 默认 stage7 bridge profile 固定为 `RTMPS` 语义；本地 preflight 自动回归只在临时 profile 中改用 `rtmp://127.0.0.1` 来覆盖失败分支
- `run_stage7_stream_bridge.sh` 默认使用 `MUSIKALISCHES_STAGE7_LOOP_MODE=infinite`
- 如需只跑单次有限输入，可设置 `MUSIKALISCHES_STAGE7_LOOP_MODE=once`
- 如需做受控长时 bridge / soak 预演，可设置 `MUSIKALISCHES_STAGE7_MAX_RUNTIME_SECONDS=<n>`
- `MUSIKALISCHES_STAGE7_MAX_RUNTIME_SECONDS` 的语义是整体 wrapper runtime budget，不是长期无人值守模式参数
- 如需长期无人值守 live mode，应使用 `MUSIKALISCHES_STAGE7_LOOP_MODE=infinite`，并且不要设置 `MUSIKALISCHES_STAGE7_MAX_RUNTIME_SECONDS`
- runtime 会先执行 `protocol_support` / `dns_resolution` / `tcp_connectivity` / `publish_probe` 四步 preflight
- publish probe 会对真实 `RTMPS` 地址做一次轻量 `ffmpeg` 发布试探，用来提前暴露认证或权限错误
- retryable 失败会按 `1s -> 5s -> 15s` backoff 自动重连，达到连续失败上限后才退出
- preflight fail 时，控制台首行会固定打印 `preflight failed: <check_id>; see ...preflight_report.json and ...preflight.stderr.log`
- preflight fail 或 runtime budget 到时退出时，控制台会同步打印最小摘要与 report/log 路径，不再只写到 `logs/*.json`
- 进入人工排障时，先看 `logs/stage7_bridge_preflight_report.json`，再看 `logs/stage7_bridge_preflight.stderr.log`
- runtime 会把 preflight `stderr` 写到 `logs/stage7_bridge_preflight.stderr.log`
- runtime 会把 preflight 报告写到 `logs/stage7_bridge_preflight_report.json`
- runtime 会把 `stderr` 写到 `logs/stage7_bridge_latest.stderr.log`
- runtime 会把退出分类写到 `logs/stage7_bridge_exit_report.json`
- runtime 会把聚合执行结果写到 `logs/stage7_bridge_runtime_report.json`
- `make -C src/musikalisches stage8-sample-retain STAGE8_RUN_LABEL=<label>` 会把当前 preflight/runtime/exit/attempt 日志与 readiness/validation 报告收成 `ops/out/stream-bridge/stage8-samples/<label>/`，并自动生成 `operator_summary_template.md` / `attempt_log_index.json` / `runtime_artifact_digest.json`
- `make -C src/musikalisches stage7-preflight-regression-check` 会自动回归 `target_scheme / protocol_support / dns_resolution / tcp_connectivity / publish_probe` 五条 preflight fail 路径，并把结果写到 `ops/out/stage7-preflight-regressions/stage7_preflight_regression_report.json`

失败分类当前至少覆盖：

- `handshake_failure`
- `auth_failure`
- `ingest_configuration_failure`
- `network_jitter`
- `remote_disconnect`
- `unknown_failure`

进入 stage 8 前，推荐最小验收顺序：

```bash
make -C src/musikalisches stage7-ffmpeg-check
make -C src/musikalisches stage7-bridge
make -C src/musikalisches stage7-bridge-check
make -C src/musikalisches stage7-preflight-regression-check
make -C src/musikalisches stage7-soak-check
make -C src/musikalisches stage8-readiness-check
```

stage 8 真实 soak 的人工运维草稿见：

```text
docs/plans/260324-stage8-real-soak-ops-guide.md
```

真实 preflight / soak 结束后，执行 `make -C src/musikalisches stage8-sample-retain STAGE8_RUN_LABEL=<label>` 可把现场日志与报告固化到独立样本目录，便于 issue 回填与复盘。

运行 stage 5 golden regression：

```bash
cargo test
```

或通过 CLI 写出 golden verification report：

```bash
cargo run -- verify-golden \
  --work mozart_dicegame_print_1790s \
  --output-dir ops/out/golden-check
```
