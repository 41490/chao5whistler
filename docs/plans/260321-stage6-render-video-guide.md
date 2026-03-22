# Stage 6 Render-Video Guide

日期: `2026-03-21`  
定位: `stage 6 render-video skeleton`

## 1. 当前结论

- stage 6 不再只停在 stub
- 现在已补 `scene JSON -> offline frame sequence -> mp4 preview` 骨架
- 这条链路只消费 stage 6 stub scene，不反向依赖 stage 5 合成细节，也不进入 stage 7 RTMP bridge

结论:

- `render-video` 的最小 contract 已具备
- 当前实现重点是离线 frame contract 与本地 mp4 预览
- 仍未进入直播桥接、推流恢复、长稳运维

## 2. 推荐命令

先确保 stage 6 stub 已通过：

```bash
make -C src/musikalisches stage6-video-check
```

批量校验 repo 内全部 scene profile：

```bash
make -C src/musikalisches stage6-scene-profile-check-all
```

构建默认 render-video 骨架：

```bash
make -C src/musikalisches stage6-video-render
```

校验 render-video 产物：

```bash
make -C src/musikalisches stage6-video-render-check
```

如需对 SoundFont 路径独立 smoke：

```bash
make -C src/musikalisches stage6-video-render-sf2
make -C src/musikalisches stage6-video-render-check-sf2
```

如需切到变体 profile，可先重建 stub：

```bash
make -C src/musikalisches stage6-video-stub \
  STAGE6_SCENE_PROFILE=src/musikalisches/runtime/config/stage6_orbital_sunrise_scene_profile.json
make -C src/musikalisches stage6-video-render
```

## 3. 输入与输出

默认输入目录:

- `ops/out/video-stub`

默认输出目录:

- `ops/out/video-render`

默认输出文件:

- `visual_scene_profile.json`
- `video_render_manifest.json`
- `offline_frame_sequence.json`
- `video_render_poster.ppm`
- `offline_preview.mp4`
- `stage6_render_validation_report.json`

如果显式 `--skip-mp4` 或缺少 `ffmpeg`，则仍会生成：

- `offline_frame_sequence.json`
- `video_render_poster.ppm`

但 manifest 会把 mp4 标记为 skipped。

## 4. 人工检查点

- `offline_frame_sequence.json`
  - `summary.frame_count` 必须等于 `frames` 数量
  - `clock_seconds` 必须单调递增
  - 每帧 `voice_pulses` 数量必须等于 `lane_count`
- `video_render_manifest.json`
  - `source_stage = stage6_video_stub`
  - `visual_scene_profile_*` 必须与 scene profile 一致
  - `mp4_generation.generated` 与实际文件存在性一致
- `video_render_poster.ppm`
  - 分辨率必须与 profile `canvas` 一致
  - 能看见当前 cycle accent 条和 lane pulse 圆环
- `offline_preview.mp4`
  - 这是本地离线预览，不是 stage 7 bridge
  - 分辨率 / fps 必须与 profile `canvas` 一致

## 5. 已补的 profile 变体

- `src/musikalisches/runtime/config/stage6_default_scene_profile.json`
  - 默认 Solarized Dark 720p@30
- `src/musikalisches/runtime/config/stage6_orbital_sunrise_scene_profile.json`
  - 暖色 720p@24
- `src/musikalisches/runtime/config/stage6_blueprint_nocturne_scene_profile.json`
  - 宽屏 1080p@30

这三份 profile 共享同一 schema，用来验证：

- palette 可演化
- motion 参数可演化
- 分辨率与 fps 可演化
- scene/profile/source/path contract 仍保持稳定

## 6. 当前边界

- 当前 mp4 是 stage 6 本地离线预览，不包含 RTMP / FFmpeg live bridge
- 当前渲染器是 Python skeleton，不是最终高性能编码器
- 当前目标是冻结 frame contract，而不是先追求复杂视觉风格
