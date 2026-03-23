# 260322 issue #2 songh replay runtime foundation

## context

本次继续依据 issue #2 的最新回复推进：

- 当前基线回复：
  - <https://github.com/41490/chao5whistler/issues/2#issuecomment-4107669911>

回复里明确要求先做基础夯实，再继续进入 audio / video / ffmpeg 主链路。

这次聚焦两件事：

1. 把 stage3 replay 规则抽成后续可复用的 runtime API
2. 提前锁定跨 midnight / day-pack rollover 行为

## landed

- `src/songh/src/replay/` 已从单文件 report 逻辑重构为模块：
  - `mod.rs`
  - `engine.rs`
- 新增 `ReplayEngine`
  - 按秒输出 `ReplayTick`
  - `sample-replay` 已改为复用该 engine
- 新增 `replay-dry-run` CLI
  - 直接输出连续 tick
  - 作为后续 fallback / audio / video 联调的观察入口
- 新增共享事件契约：
  - `src/songh/src/model/runtime_event.rs`
  - 为后续 archive replay / fallback synthetic / text / audio / video 提供统一字段集合
- dedupe TTL 已从 `second_of_day` 修正为 `replay_second`
  - 避免跨 midnight 后窗口无法正确过期
- runtime 已支持自动切到下一个 complete day-pack
  - 当前 pack 到 `23:59:59` 后，下一 tick 会进入后续 pack 的 `00:00:00`

## regression coverage

- 新增 tick 级回归：
  - dedupe 过期以 replay 秒计，而不是 `second_of_day`
- 新增 engine 级回归：
  - 跨午夜后自动切到下一天 pack
- 新增 sample 级回归：
  - `sample_day_pack` 跨午夜窗口会继续采样下一天 pack

## validation

已完成：

```bash
cargo fmt --manifest-path src/songh/Cargo.toml
cargo test --manifest-path src/songh/Cargo.toml
```

结果：

- `12 tests` 全部通过

## next

在这次基础上，后续继续推进时可直接复用：

1. `ReplayTick` 作为 audio/video 输入契约
2. `RuntimeEvent` 作为 archive/fallback 统一事件结构
3. day rollover 语义作为后续 runtime 主循环的既定行为
