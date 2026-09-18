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
- formal live baseline 现冻结为：`stage5-sf2 + stage6-video-render-sf2 + 16-cycle source pair`

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
- stage7/stage8 默认 live 输入已切到 `ops/out/stream-sf2` 与 `ops/out/video-render-sf2`
- formal live source pair 默认固定为 `16` cycles / 组合；`stage8-readiness-check` 也会显式验证该约束
- issue #9 `P2` 现已引入 `ops/assets/soundscapes/` 资产包约定；seed pack 先冻结 `ambient + drone` manifest、许可证白名单和 `sha256` 校验
- issue #9 `P3` 现已把 `main organ + drone + ambient` 下沉到 stage5：默认会根据 `combination_id` 选 registration/profile 和 soundscape assets，并把统一混音结果直接写回 `offline_audio.wav`
- stage 7 默认只产出本地 `flv` smoke 与 redacted live command，不默认发起真实推流
- 如系统自带 `ffmpeg` 缺少 `rtmps` output，可直接执行 `make -C src/musikalisches stage7-ffmpeg-build` 生成仓库内本地 toolchain，并由 stage6/stage7 目标自动优先使用 `ops/bin/ffmpeg` 与 `ops/bin/ffprobe`

## soundscape asset pack

issue #9 的 `P2` 先把多层声景的素材 contract 单独冻结出来：

- 资产根目录：`ops/assets/soundscapes/`
- 必需层：至少一组 `ambient` 和一组 `drone`
- 当前许可证白名单：`CC0` / `public_domain` / `pixabay_no_attribution`
- 每个 asset manifest 至少显式记录 `asset_id` / `layer_kind` / `source_url` / `license` / `attribution_required` / `loop_duration_seconds` / `loudness_target_dbfs` / `sha256`

生成 seed pack：

```bash
make -C src/musikalisches soundscape-assets-generate
```

验证 seed pack：

```bash
make -C src/musikalisches soundscape-assets-check
```

P2 只负责冻结素材池和 license manifest，不在这一阶段把这些层真正混进 stage5；那部分属于后续 `P3`。

## stage5 soundscape mix bus

当前默认 stage5 unique-stream 构建已进入 issue #9 `P3`：

- 默认 soundscape profile：`src/musikalisches/runtime/config/stage5_default_soundscape_profile.json`
- 默认 registration 池：
  - `stage5_default_synth_profile.json`
  - `stage5_bright_chapel_synth_profile.json`
  - `stage5_processional_reeds_synth_profile.json`
- 学术向 A/B 池（issue #63，需显式指定）：
  - `stage5_academic_organ_dry_synth_profile.json`（显式 dry 基线，reverb 关、velocity 平）
  - `stage5_academic_chapel_synth_profile.json`（短 chapel reverb + velocity 曲线 + 声部 EQ/pan + 微量 gain automation）
- 默认会生成 `soundscape_selection.json`
- 默认会把 `ambient + drone` 真正混入 stage5 的 `offline_audio.wav`

新的 stage5 关键 contract：

- `combination_selection.json`: 组合与 hold 元数据
- `soundscape_selection.json`: registration + ambient/drone 选择结果与 mix-bus 摘要
- `artifact_summary.json` / `render_request.json` / `stream_loop_plan.json` / `m1_validation_report.json`
  现会同步带出 `soundscape` 摘要和 `output_files.soundscape_selection`

常用命令：

```bash
make -C src/musikalisches stage5-soundscape-profile-show
make -C src/musikalisches stage5-sf2 LOOP_COUNT=16
make -C src/musikalisches stage5-sf2-check
```

如需覆盖默认 soundscape profile：

```bash
make -C src/musikalisches stage5-sf2 \
  LOOP_COUNT=16 \
  SOUNDSCAPE_PROFILE=/path/to/stage5_soundscape_profile.json
```

## stage5 academic synth profile mix（issue #63）

synth profile 顶层新增可选 `mix` 块，voice_group 新增可选 `velocity_curve` / `eq` /
`pan` / `gain_automation`。**所有新字段缺省即旧行为**：不带 `mix` 的 profile（含
默认 profile 与既有两个 registration 变体）反序列化、序列化与渲染结果都保持不变。

- `mix.reverb{enabled,wet,dry,decay_seconds,room_size,damping}`：`finalize_audio_render`
  内的纯算法 Schroeder reverb（comb + allpass，无 IR 资产、无新增 crate）。
- `mix.master_trim_db`：归一化后的总线微调。
- `mix.dynamic{velocity_depth,phrase_period_quarters,beat_accent_pattern}` 与
  voice_group `velocity_curve`：逐 note_on 计算 velocity 写入 `data2`（`build_synth_event_sequence`）。
- voice_group `eq{gain_db,tilt}` / `pan` / `gain_automation{depth_db,period_quarters}`：
  fallback 渲染路径的幅度 / 声像；SoundFont 路径以 CC7 / CC10 / CC91 下发
  （`apply_synth_event`）。
- `mix.ab_expectations{dynamic_spread_gain_db_min,reverb_tail_dbfs_min,lufs_band,lufs_band_basis}`：
  供 A/B 校验 lane 读取的阈值，不在 Rust 侧执行门禁。`lufs_band` 以 premix
  实测为准（`lufs_band_basis=premix_render_offline_audio`）：issue #70 把 dry/chapel
  的 `mix.master_trim_db` 抬到 premix integrated ≈ −19 LUFS 后，`lufs_band` 已同步
  收紧为 `[-20.0, -18.0]`。

A/B 与回退：

```bash
cargo run -- render-audio \
  --work mozart_dicegame_print_1790s \
  --demo-rolls \
  --synth-profile src/musikalisches/runtime/config/stage5_academic_chapel_synth_profile.json \
  --output-dir /tmp/ab-enhanced

# 回退到 dry 基线（或直接不带 --synth-profile 走默认 profile）
cargo run -- render-audio \
  --work mozart_dicegame_print_1790s \
  --demo-rolls \
  --synth-profile src/musikalisches/runtime/config/stage5_academic_organ_dry_synth_profile.json \
  --output-dir /tmp/ab-dry
```

A/B 机检（不渲染，只读两个已渲染目录）：

```bash
python3 src/musikalisches/tools/verify_academic_profile_ab.py \
  --dry /tmp/ab-dry \
  --enhanced /tmp/ab-enhanced \
  --profile src/musikalisches/runtime/config/stage5_academic_chapel_synth_profile.json \
  --report /tmp/ab-report.json
```

退出码 0 表示五条断言全过，非 0 时 report JSON 的 `failed_assertions` / `failures`
列出具体失败项。断言：note/transition/realization 三层逐字节一致；premix
`dynamic_spread_db` 增益 ≥ `ab_expectations.dynamic_spread_gain_db_min`；reverb
尾部存在（补偿两侧渲染总增益后仍高出 dry ≥ 1 dB）；主层 envelope 峰值保留
≥ 0.8× 且 short-term 波动范围更宽；premix `integrated_lufs` 落在 `lufs_band` 内。
反例自检：把 dry 目录同时传给 `--enhanced`，退出码必须非 0。
动态/混响断言只看 premix（render-audio 的 `offline_audio.wav`）；恒定 bed 会压缩
混音后的 spread，final mix 只适用下面的 mix_bus 门禁字段。阈值来源、reverb 截断
取舍与已知偏差见 `docs/plans/260917-issue63-academic-organ-mix-profile-plan.md`。

stage5-sf2 / stage5-stream 同样支持 `SYNTH_PROFILE=` 覆盖；未指定时继续使用既有
registration 池，schema 扩展不影响默认链路。

### mix_bus 门禁字段

`runtime/config/stage5_default_soundscape_profile.json` 的 `mix_bus_profile` 是
soundscape 混音总线的门禁契约，由 `tools/validate_m1_artifacts.py` 读回后对
`offline_audio.wav` 断言（阈值不在校验器里重复硬编码）：

- `main_registration_profiles[].gain_db`：per-registration 静态响度 trim
  （issue #70），issue #75 起**降级为回退常量**：仅当主层响度测量不可用
  （如静默渲染）时才替代逐组合 trim。缺省 `0.0`。
- `mix_bus_profile.bed_offset_db`：逐组合前馈标定常量（issue #75）。构建时用
  `tools/loudness_meter.py` 量一次**未叠 bed、未过限幅器的主层渲染**，算出
  `combination_trim_db = -19.0 - measured_main_lufs + bed_offset_db` 并**替换**
  registration trim（仍是单增益级，无迭代收敛）；`bed_offset_db` 吸收混音链路
  固定偏移（`main_gain_db` 串联与 bed 叠加净贡献），由实测标定。测量值、trim
  与来源（`trim_source: measured|fallback`）记录进 `soundscape_selection.json`。
  `--synth-profile` CLI 覆盖与默认池走同一集中 trim 解析，不再静默关闭标定。
- `target_rms_min_dbfs` / `target_rms_max_dbfs`：总线 RMS 区间。issue #63 曾把下限
  由 −28 放宽到 −30 dBFS；issue #70 随 trim 标定把下限收回 **−28 dBFS**。
- `target_lufs_min` / `target_lufs_max`：BS.1770-4 gated integrated 区间，issue #70
  收紧为 **−20.0 / −18.0 LUFS**（最终混音 WAV 交付面），由
  `tools/loudness_meter.py` 计量。issue #75 起逐组合前馈 trim 把每个组合
  标定到带心 −19.0 LUFS。
- `true_peak_ceiling_dbtp`：采样峰值上限（默认 −0.5 dBTP）。
- `require_no_clipping`：为真时，≥3 个连续满量程样本即判失败。
- `envelope_coupling{enabled,depth_db}`：开启后 `build_stage5_unique_stream.py`
  用 `analysis_window_sequence.json` 的 `envelope_amplitude` 逐帧调制 bed 增益
  （最响窗保持基础增益，最轻窗最多衰减 `depth_db`）；默认关闭。

回退：不带 `SOUNDSCAPE_PROFILE=` 即回到 `stage5_default_soundscape_profile.json`；
不带 `SYNTH_PROFILE=` 即回到默认 registration 池（非 academic profile）。

## ops quickstart

最小推荐顺序：

```bash
make -C src/musikalisches stage6-scene-profile-check-all
make -C src/musikalisches stage5-sf2 LOOP_COUNT=16
make -C src/musikalisches stage5-sf2-check
make -C src/musikalisches stage6-video-stub-sf2
make -C src/musikalisches stage6-video-check-sf2
make -C src/musikalisches stage6-video-render-sf2
make -C src/musikalisches stage6-video-render-check-sf2
make -C src/musikalisches stage7-ffmpeg-check
make -C src/musikalisches stage7-bridge
make -C src/musikalisches stage7-bridge-check
make -C src/musikalisches stage7-soak-check
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
- `run_stage7_stream_bridge.sh` 会优先调用 `target/release/musikalisches-stage7-runtime` 或 `target/debug/musikalisches-stage7-runtime`；只有在 Rust runtime 不存在时才回退到 Python wrapper
- 可用 `MUSIKALISCHES_STAGE7_RUNTIME_BIN=/abs/path/to/musikalisches-stage7-runtime` 显式指定 live-host 上的 Rust runtime 二进制
- 无论走 Rust runtime 还是 Python fallback，stage7 的 redaction / failure classification 都已内建在 runtime 内，不再要求 live-host 额外依赖 `classify_stage7_bridge_failure.py`
- `make -C src/musikalisches stage7-preflight-regression-check` 现在也会优先复用同一套 Rust runtime 解析逻辑；若仓库里还没有已编译二进制，会先构建 `musikalisches-stage7-runtime`
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
