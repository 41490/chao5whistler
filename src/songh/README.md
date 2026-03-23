# chao5whistler/src/songh

当前目录按 issue #2 的实现顺序推进 `songh`。

当前已进入：

- stage 3: `second-of-day replay engine`

当前阶段统一人工检验入口：

```bash
make -C src/songh stage3-manual
```

当前阶段自动回归入口：

```bash
make -C src/songh stage3-all
```

当前阶段连续 tick 观察入口：

```bash
make -C src/songh stage3-dry-run
```

当前阶段跨 midnight rollover smoke 入口：

```bash
make -C src/songh stage3-rollover-smoke
```

当前已落地：

- stage 2: `gharchive day-pack downloader + normalize pipeline`
- stage 3: `second-of-day replay engine`

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

stage 4 条件判断：

- 如果这里的 stage 4 指按当前实现顺序继续进入 video engine，那么开工条件已满足：
  - replay 输入契约已冻结为 `RuntimeEvent` / `ReplayTick`
  - `video.canvas` / `video.motion` / `outputs.encode` 默认值已冻结并受配置校验保护
  - 跨 midnight / next day rollover 已有单测 + smoke target 固定
- 但 stage 4 还没有完成，当前仍缺：
  - 文本排版与轨迹求解
  - `vertical | fixed_angle | random_angle` 三类样片
  - 真实 video frame 输出链路
- 如果严格沿用 `docs/plans/260320-songh-issue-2-architecture-plan.md` 的编号，则其中 stage 4 仍是 `video engine`，只是该计划里 stage 3 叫 `audio engine`；因此当前结论应理解为：
  - 已满足启动 stage 4 实现的基础条件
  - 尚未满足 stage 4 产物完成条件
