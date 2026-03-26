# chao5whistler/src/songh

当前目录按 issue #2 的实现顺序推进 `songh`。

当前已进入：

- stage 7: `live bridge + real-stream preflight`

当前阶段统一人工检验入口：

```bash
make -C src/songh stage7-manual
```

当前阶段自动回归入口：

```bash
make -C src/songh stage7-all
```

当前阶段 systemd --user 安装入口：

```bash
make -C src/songh systemd-user-install
```

当前阶段人工运行文档：

```text
src/songh/USAGE.md
```

当前阶段连续 tick 观察入口：

```bash
make -C src/songh stage3-dry-run
```

当前阶段跨 midnight rollover smoke 入口：

```bash
make -C src/songh stage3-rollover-smoke
```

当前阶段 stage 4 样片入口：

```bash
make -C src/songh stage4-manual
```

当前阶段 stage 4 PNG 样片落盘入口：

```bash
make -C src/songh stage4-render-fixture
```

当前阶段 stage 5 音频样片入口：

```bash
make -C src/songh stage5-manual
```

当前阶段 stage 5 WAV 样片落盘入口：

```bash
make -C src/songh stage5-render-fixture
```

当前阶段 stage 6 A/V 样片入口：

```bash
make -C src/songh stage6-manual
```

当前阶段 stage 6 MP4 样片落盘入口：

```bash
make -C src/songh stage6-render-fixture
```

当前已落地：

- stage 2: `gharchive day-pack downloader + normalize pipeline`
- stage 3: `second-of-day replay engine`
- stage 4: `video frame-plan sample baseline`
- stage 5: `audio cue-plan + offline wav sample baseline`
- stage 6: `offline mp4 preview baseline`
- stage 7: `live bridge artifact + real-stream preflight baseline`

补充说明：

- `sample-replay` 现在复用 `ReplayEngine` / `ReplayTick` runtime API：
  - 每秒推进一个 tick
  - `top-4` 稳定选择
  - `10-minute dedupe`
  - `overflow count`
  - 跨 midnight 自动轮换到下一个 complete day-pack
- runtime buffer 已从 `hour-buffer` 细化为 `minute-buffer`：
  - 继续复用现有 `minute_offsets.json`
  - 降低长时 replay/live runtime 的驻留事件集
- `replay-dry-run` 已补跨 midnight smoke target：
  - 固定验证 `2026-03-19 23:59:50 -> 2026-03-20 00:00:09`
  - `stage3-all` / `stage3-manual` 现在都会覆盖 rollover smoke
- stage 4 已补最小 video sample 链路：
  - CLI: `sample-video`
  - 输入直接复用 `ReplayTick` / `RuntimeEvent`
  - 输出为可回归的 frame-plan JSON sample
- stage 4 已补最小 raster/frame sink：
  - CLI: `render-video-sample`
  - 输出 `frame-plan.json` + `render-manifest.json` + `frames/*.png`
  - 当前文本已接真实 TTF raster，不再停留在 bitmap glyph baseline
  - `render-manifest` 现已导出首个 active frame 的 golden hash，供像素级回归
- stage 4 文本可视规则已补：
  - 默认正式字体使用 `ops/assets/3270NerdFontMono-Condensed.ttf`
  - 文本整体顺时针旋转 `90°`，形成竖直文本段
  - 文本段统一向上漂浮，并随生命周期逐步模糊、淡出
  - 单秒关键文本段总数固定 `< 10`，当前上限为 `9`
  - 单秒内按事件类型数量排序，数量更高者获得更大字号和更高 `initial_gain_db` 元数据
  - 同秒文本段现在会做横向车道化，优先减少高密度秒的局部重叠
  - 连续 dense seconds 之间会短时保持 `lane_hold_key -> lane_index`，降低 lane 抖动
  - `VideoSpritePlan` 已补 `lane_hold_key` / `lane_index` 元数据，便于回归与调参
  - 事件类型颜色按 Solarized Dark 主题色与背景反差排序分配，数量最多的类型拿最高反差色
- 当前已支持三类 motion mode 样片：
  - `vertical`
  - `fixed_angle`
  - `random_angle`
- 文本主载荷已开始按 `text.template` 渲染：
  - 当前使用 runtime event 的 `text_fields`
  - 遵守 `{repo}/{hash:8}` 这类宽度截断语义
- stage4 make target 已补：
  - `stage4-sample-vertical`
  - `stage4-sample-fixed`
  - `stage4-sample-random`
  - `stage4-render-fixture`
  - `stage4-all`
- stage 5 已补最小 offline audio 链路：
  - CLI: `sample-audio`
  - CLI: `render-audio-sample`
  - 输出 `audio-plan.json` + `offline_audio.wav` + `render-manifest.json`
  - 每个 cue 现在会把 second-type density 映射成真实 `initial_gain_db`
  - 当前先用 deterministic synth baseline 验证 `voice_gain_db + initial_gain_db` 混音效果
  - `audio.background.wav` 已接入 stage5 mix bus，支持 `gain_db` 和 `loop = true|false`
- stage5 make target 已补：
  - `stage5-sample-fixture`
  - `stage5-render-fixture`
  - `stage5-manual`
  - `stage5-all`
- stage 6 已补最小 A/V 合流链路：
  - CLI: `render-av-sample`
  - 输出 `video/` + `audio/` + `offline_preview.mp4` + `render-manifest.json`
  - 如环境有 `ffprobe`，会额外输出 `ffprobe.json` 并校验 width/height/sample_rate/channels/nb_frames
  - 预览编码已冻结到 `H.264 + AAC`，复用当前 `outputs.encode` 的 `ultrafast / 128 kbps` 决策
- stage6 make target 已补：
  - `stage6-render-fixture`
  - `stage6-manual`
  - `stage6-all`
- stage 7 已补最小 live bridge 链路：
  - CLI: `build-stream-bridge`
  - CLI: `run-stream-bridge`
  - 输出 `stage7_bridge_smoke.flv` + `stream_bridge_manifest.json` + `stream_bridge_ffmpeg_args.json`
  - 真实开播前会做 `target_scheme / protocol_support / dns_resolution / tcp_connectivity / publish_probe`
  - runtime 会写 `logs/stage7_bridge_preflight_report.json` / `stage7_bridge_runtime_report.json` / `stage7_bridge_latest.stderr.log`
  - build 阶段仍会冻结一份 stage6 `offline_preview.mp4` 并产出本地 smoke `.flv`
  - 但真正 `run-stream-bridge` 已切到按秒 live generator：Rust 持续生成 raw RGBA frame + PCM chunk，ffmpeg 常驻读取 FIFO 后推 `RTMP/RTMPS + 本地 .flv`
  - live runtime 会遵守 `runtime.start_policy` 和 `runtime.clock`
- stage7 make target 已补：
  - `stage7-build-fixture`
  - `stage7-manual`
  - `stage7-all`
- runtime tick 事件已冻结为共享契约：
  - `src/songh/src/model/runtime_event.rs`
  - 后续 archive replay / fallback synthetic / audio / video 共用这一层
- fallback synthetic runtime 现已接通到 replay/audio/video：
  - `runtime.mode = random_fallback` 时可直接产出 synthetic tick / cue / sprite
  - 当请求的 day-pack 缺失且 `fallback.enabled = true` 时，会自动回退到 synthetic 输出
  - `fallback.density_source = history_if_available` 时会优先复用本地 complete day-pack 的 minute density
- stage 3 冻结决策已同步到配置层：
  - `runtime.clock` 允许 `realtime_day | fast`
  - `replay.selection_order` 固定为 `weight_desc -> event_id_asc`
  - `video.canvas` 默认值更新为 `1280x720@30`
  - `outputs.encode` 冻结为 `h264 / ultrafast / 128 kbps`
- `manifest.toml` 已补：
  - `generator_version`
  - `config_fingerprint`
- 仓库已补 `src/songh/songh.local.toml.example` 作为本机覆盖参考

stage 7 当前判断：

- stage4 PNG 序列和 stage5 WAV 现已能合流为 `offline_preview.mp4`
- stage7 现已把该 mp4 冻结为 smoke/build 基线，并产出本地 `stage7_bridge_smoke.flv`
- stage7 runtime 已能脱离 loop mp4，改为真正按秒推进的常驻 live A/V 生成链路
- 真实推流前会前置暴露 URL scheme、ffmpeg protocol support、DNS、TCP 和 publish probe 问题
- 但进入长期真实直播前，当前还缺：
  - 更真实的 voice backend / sample backend
