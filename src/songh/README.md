# chao5whistler/src/songh

当前目录按 issue #2 的实现顺序推进 `songh`。

当前已进入：

- stage 4: `video frame-plan samples`

当前阶段统一人工检验入口：

```bash
make -C src/songh stage4-manual
```

当前阶段自动回归入口：

```bash
make -C src/songh stage4-all
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

当前已落地：

- stage 2: `gharchive day-pack downloader + normalize pipeline`
- stage 3: `second-of-day replay engine`
- stage 4: `video frame-plan sample baseline`

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
- runtime tick 事件已冻结为共享契约：
  - `src/songh/src/model/runtime_event.rs`
  - 后续 archive replay / fallback synthetic / audio / video 共用这一层
- stage 3 冻结决策已同步到配置层：
  - `runtime.clock` 允许 `realtime_day | fast`
  - `replay.selection_order` 固定为 `weight_desc -> event_id_asc`
  - `video.canvas` 默认值更新为 `1280x720@30`
  - `outputs.encode` 冻结为 `h264 / ultrafast / 128 kbps`
- `manifest.toml` 已补：
  - `generator_version`
  - `config_fingerprint`
- 仓库已补 `src/songh/songh.local.toml.example` 作为本机覆盖参考

stage 4 当前判断：

- stage 4 已正式启动，并已有最小可回归产物：
  - 三类 motion mode 的 frame-plan sample
  - 文本模板渲染
  - 基于 canvas / speed / angle 的轨迹规划
  - 基于真实归档秒级密度的 `<10/s` 关键文本段筛选
  - vertical motion 的 PNG 帧序列样片
  - 真实 TTF raster + 90° 文本旋转 + blur/fade 生命周期
  - 首个 active frame 的 golden hash 回归
  - 高密度 frame 的第二档 golden hash 回归
- 但 stage 4 仍未完成，当前还缺：
  - 样片进一步落到视频容器
