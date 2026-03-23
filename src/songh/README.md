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
