# Stage 6 Video Stub Guide

日期: `2026-03-21`  
定位: `stage 6 preflight`

## 1. 当前结论

- 现阶段还没有正式 `render-video`
- 但 stage 5 已经具备:
  - `analysis_window_sequence.json`
  - `stream_loop_plan.json`
  - `synth_routing_profile.json`
- 因此先补一条 analyzer -> video stub 预演链路，用来冻结“视觉只消费分析层”的入口

结论:

- stage 6 现在可以先验证视觉契约
- 还不引入 FFmpeg 或真实视频编码
- 先把 palette / motion / cycle 边界 / lane 布局导出成可检查产物

## 2. 推荐命令

先确保已有 stage 5 stream artifact:

```bash
make -C src/musikalisches stage5-stream
```

先校验 scene profile contract:

```bash
make -C src/musikalisches stage6-scene-profile-check
```

生成 stage 6 stub:

```bash
make -C src/musikalisches stage6-video-stub
```

校验 stub:

```bash
make -C src/musikalisches stage6-video-check
```

如需对 SoundFont 路径做独立 smoke:

```bash
make -C src/musikalisches stage6-video-stub-sf2
make -C src/musikalisches stage6-video-check-sf2
```

如需改输入目录:

```bash
make -C src/musikalisches stage6-video-stub \
  STAGE6_SOURCE_DIR=ops/out/stream-sf2
```

如需替换 scene profile:

```bash
make -C src/musikalisches stage6-video-stub \
  STAGE6_SCENE_PROFILE=/path/to/scene_profile.json
```

## 3. 输入与输出

默认输入目录:

- `ops/out/stream-demo`

默认 scene profile:

- `src/musikalisches/runtime/config/stage6_default_scene_profile.json`
- `src/musikalisches/runtime/config/stage6_scene_profile.schema.json`

要求已有 4 个 stage 5 文件:

- `analysis_window_sequence.json`
- `stream_loop_plan.json`
- `synth_routing_profile.json`
- `artifact_summary.json`

默认输出目录:

- `ops/out/video-stub`

生成文件:

- `visual_scene_profile.json`
- `video_stub_manifest.json`
- `video_stub_scene.json`
- `video_stub_preview.svg`
- `stage6_validation_report.json`

## 4. 人工检查点

- `video_stub_scene.json`
  - `visual_scene_profile_id` 必须存在
  - `palette.palette_id = "solarized_dark"`
  - `motion.mode = "dual_orbit_pulse"`
  - `summary.window_count` 必须等于 `analysis_window_sequence.json.windows` 数量
  - `summary.cycle_count` 必须等于 `stream_loop_plan.json.loop_count`
- `visual_scene_profile.json`
  - `profile_id` 应与 `video_stub_scene.json.visual_scene_profile_id` 一致
  - `canvas` / `palette` / `motion` 应为本次实际生效参数
  - `source` / `source_path` 应与 scene / manifest 一致
- `lane_layout`
  - 数量必须等于 `synth_routing_profile.json.voice_groups`
  - `channel` 不应丢失
  - 左右增益差应被投影为不同 `stereo_bias`
- `keyframes`
  - `clock_seconds` 单调递增
  - 每个 keyframe 都有同数量 `voice_pulses`
  - `cycle_index` 与 stage 5 cycle 边界一致
- `video_stub_preview.svg`
  - 应能看见 Solarized Dark 背景
  - 应能看见按 cycle 切换的 accent 色
  - 包络线不应完全平直

## 5. 进入正式 render-video 前的最小门槛

- stage 5 stream artifact 已稳定可重建
- stage 6 stub validation 通过
- 视觉侧只依赖 analyzer / loop-plan / synth-profile，不反向读取音频合成内部状态
- palette / motion / lane-layout 三类规则已能在 stub 中稳定导出
