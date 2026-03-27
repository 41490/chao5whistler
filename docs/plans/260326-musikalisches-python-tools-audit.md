# 260326 musikalisches python tools audit

> status: decision-support plan
>
> date: 2026-03-26
>
> basis:
>
> - issue #13 handoff: `https://github.com/41490/chao5whistler/issues/13`
> - current worktree under `/opt/src/41490/chao5whistler`

## question

需要先回答一个现实问题：

1. `src/musikalisches/tools` 里的 Python 脚本是不是都必须保留。
2. 它们是否参与最终长期 YouTube 直播行为。
3. 若参与，是否应该优先改成 Rust。

这里的判断标准不是“脚本有没有价值”，而是：

- 是否进入最终直播主链路；
- 是否影响长期运行时资源消耗；
- 是否值得为部署简化和维护一致性迁移到 Rust。

## current progress snapshot

先基于 issue #13 和当前工作副本明确现状。

### issue #13 originally asked for

issue #13 的 handoff 说明，上一轮已经把 issue #9 `P4` 的 stage6 soundscape badges 落到 `main`，下一步 `P4.5` 应该做的是：

- 把 `soundscape_selection` 摘要继续冻结到 stage7 contract；
- 再把同一份摘要传播到 stage8 readiness / sample retention；
- 让 stage5 -> stage6 -> stage7 -> stage8 对“当前组合 + 当前声景”的表达一致。

### what the current worktree is actually doing

当前工作副本对 stage7/stage8 的修改，主要在传播：

- `selection_progress`
  - `combination_id`
  - `played_unique_count / total_combinations`

但 stage7/stage8 相关脚本里仍然没有 `soundscape` / `soundscape_selection` 字段传播。

这说明：

- issue #13 指向的 `soundscape summary propagation` 还没有真正完成；
- 当前只是先把 `selection_progress` 贯通到了 stage7/stage8。

换句话说，issue #13 的下一步方向没有错，但当前实现只完成了其中一部分相邻工作。

## current live architecture

按当前 `musikalisches` 的真实执行链路，长期直播不是“实时生成器”，而是“冻结资产 + 长时桥接器”。

### stage5

Rust CLI `musikalisches` 负责：

- realization
- offline audio render
- SoundFont synth
- analyzer window sequence

核心入口是：

- `cargo run -- render-audio ...`
- `src/musikalisches/runtime/src/lib.rs`

### stage6

Python 工具负责把 stage5 产物变成离线视频预览资产：

- `build_stage6_video_stub.py`
- `build_stage6_video_render.py`

产出：

- `video_stub_scene.json`
- `offline_frame_sequence.json`
- `offline_preview.mp4`

### stage7 build

Python builder 负责把 stage5/stage6 产物冻结成直播桥接 contract：

- `build_stage7_stream_bridge.py`

产出：

- `stream_bridge_manifest.json`
- `stream_bridge_ffmpeg_args.json`
- `run_stage7_stream_bridge.sh`
- `stage7_bridge_smoke.flv`

### stage7 runtime

真正进入直播时，当前主链路是：

1. `run_stage7_stream_bridge.sh`
2. `run_stage7_stream_bridge_runtime.py`
3. `ffmpeg`

运行时行为不是再调用 stage5/stage6 重新生成内容，而是：

- 读取已经冻结好的 `offline_preview.mp4`
- 读取已经冻结好的 `offline_audio.wav`
- 用 `ffmpeg` 按 `once|infinite` loop 推到 `RTMPS`

所以当前直播本质上是：

- `pre-rendered mp4 + pre-rendered wav + ffmpeg bridge`

而不是：

- `Rust/Python 常驻实时生成音视频并即时编码推流`

## direct answer

## are these python scripts all required

不是。

更准确的说法是：

- 不是所有脚本都属于“直播必须项”；
- 也不是所有脚本都值得迁移到 Rust；
- 它们可以分成 4 类。

## do they participate in final live behavior

只有极少数直接参与最终直播行为。

直接进入当前 live runtime 的 Python 只有：

- `run_stage7_stream_bridge_runtime.py`
- `classify_stage7_bridge_failure.py`
  - 作为 runtime 的分类逻辑被导入使用

其余脚本大多属于：

- 预先生成离线资产；
- 预先冻结 manifest / wrapper；
- 校验 stage contract；
- 运维留样和 readiness 检查；
- 研究冻结阶段的一次性工具。

## should they be replaced with rust

不应该一刀切。

推荐结论是：

- 不要现在就做 `src/musikalisches/tools` 全量 Rust 重写；
- 如果要迁移，应该优先迁移 stage7 live runtime / ops 这一小簇；
- stage1-stage4 的冻结与验证工具不值得现在重写；
- stage6 Python renderer 是否迁 Rust，不应以“降低直播资源”作为理由，因为它不在 steady-state live path。

## script classification

| group | scripts | whether in steady-state live path | keep? | rust migration priority |
|---|---|---|---|---|
| stage1-stage4 freeze/authorship | `freeze_mother_score.py`, `freeze_rules.py`, `freeze_ingest.py`, `validate_source_freeze.py`, `validate_mother_score.py`, `validate_rules_freeze.py`, `validate_ingest_freeze.py` | no | keep as dev-only tools | low |
| stage5 orchestration | `build_stage5_unique_stream.py`, `validate_m1_artifacts.py` | no | keep for now | low-medium |
| stage6 offline video build | `stage6_scene_profile.py`, `validate_stage6_scene_profile.py`, `build_stage6_video_stub.py`, `validate_stage6_video_stub.py`, `build_stage6_video_render.py`, `validate_stage6_video_render.py` | no | keep if current architecture remains prerender-loop | medium |
| stage7/stage8 live ops | `stage7_bridge_profile.py`, `build_stage7_stream_bridge.py`, `run_stage7_stream_bridge_runtime.py`, `classify_stage7_bridge_failure.py`, `validate_stage7_stream_bridge.py`, `validate_stage7_preflight_failures.py`, `validate_stage7_soak.py`, `validate_stage8_ops_readiness.py`, `retain_stage8_ops_samples.py`, `validate_stage7_ffmpeg_toolchain.py` | partly | yes | high for runtime subset |

## which scripts are effectively non-runtime

下面这些脚本虽然有工程价值，但不该被算进“最终直播行为”：

- `freeze_mother_score.py`
- `freeze_rules.py`
- `freeze_ingest.py`
- `validate_source_freeze.py`
- `validate_mother_score.py`
- `validate_rules_freeze.py`
- `validate_ingest_freeze.py`
- `validate_m1_artifacts.py`
- `validate_stage6_*`
- `validate_stage7_*`
- `validate_stage8_ops_readiness.py`
- `retain_stage8_ops_samples.py`

其中有些是“发布前/运维前重要”，但它们不是 steady-state live loop。

## which scripts do affect the final live behavior

真正会在当前正式直播时执行的 Python 面，主要只有：

### 1. `run_stage7_stream_bridge_runtime.py`

职责：

- 读取 stage7 manifest / ffmpeg args
- 做 preflight
- 做 retry / backoff
- 落日志 / report
- 最终拉起 `ffmpeg`

这是当前 Python live runtime 的核心。

### 2. `classify_stage7_bridge_failure.py`

职责：

- 对 ffmpeg stderr 做 redaction
- 归类 `handshake_failure / auth_failure / network_jitter / ...`

它虽然不是独立 CLI 必经点，但被 runtime import，因此属于 live runtime 一部分。

### 3. `build_stage7_stream_bridge.py`

它不在 steady-state runtime 中常驻，但它决定最终直播怎么跑：

- live command
- loop mode
- failure taxonomy
- soak plan
- wrapper script

因此它属于“直播前构建器”，不是“直播中生成器”。

## resource-consumption implications

如果目标是“最小资源消耗的长期 YouTube 直播流生成器”，最关键的事实是：

- 当前真正长期消耗资源的是 `ffmpeg`；
- 不是 stage6 Python renderer；
- 也不是多数 validator。

### what rewriting stage6 Python to Rust would change

会改善：

- 刷新 stage6 资产时的性能
- 语言一致性
- 部署依赖统一性

不会直接改善：

- 长时间直播时的 CPU / memory steady-state

因为 stage6 当前只在构建离线预览时运行。

### what rewriting stage7 runtime to Rust would change

会改善：

- live host 不再依赖 Python
- runtime / preflight / retry / report 更统一地放入 Rust CLI
- 未来更容易把“静态资产 loop bridge”推进到“常驻生成器”

这才是最接近“最终直播行为”的 Rust 迁移点。

## architectural judgement

当前 `musikalisches` 实际上更像：

- offline asset factory + ffmpeg bridge

而不是：

- low-overhead generative live engine

如果接受这个架构，那么结论非常明确：

- Python 工具大多可以继续存在；
- 只需要收窄 live host 上的 Python 依赖；
- 没必要为了“资源消耗”去重写 stage1-stage6 全部脚本。

如果不接受这个架构，而是希望最终实现：

- 常驻生成音频
- 常驻生成画面
- 按组合切换时无需重跑 stage5/stage6 资产

那么就不该只讨论“替不替 Python”，而应明确切换目标架构为：

- Rust live generator + ffmpeg encoder bridge

这已经不是简单的脚本移植，而是 runtime model 变更。

## songh as a reference path

仓库里已经有一个 Rust 参考方向：

- `src/songh/src/stage7.rs`

它说明两件事：

1. Rust 负责 stage7 build/runtime/preflight 在本仓库里是可行的。
2. 如果要做真正常驻 live generator，Rust 这条路已经有实现范式可参考。

但 `songh` 的内容模型和 `musikalisches` 不同，所以不能机械照抄。

这里更适合作为：

- 迁移思路参考
- CLI 和 runtime 边界参考
- preflight / runtime report 结构参考

## recommended plan

推荐分 3 层做决策。

### decision A: keep current prerender-loop architecture or not

先决定 `musikalisches` 的目标架构是否仍然是：

- `stage5/stage6 预生成`
- `stage7 只做长时 loop bridge`

推荐：先保留这个架构。

理由：

- 它已经最贴近“最低 steady-state 资源”的现实目标；
- 真正常驻的只有 `ffmpeg + 轻量 wrapper`；
- 现在的大多数 Python 都不在长跑路径里。

### decision B: where to remove Python first

如果要降 Python 依赖，优先顺序应当是：

1. `run_stage7_stream_bridge_runtime.py`
2. `classify_stage7_bridge_failure.py`
3. `build_stage7_stream_bridge.py`
4. `validate_stage8_ops_readiness.py` / `retain_stage8_ops_samples.py`

不推荐优先替换：

- `freeze_*`
- `validate_source_freeze.py`
- `validate_mother_score.py`
- `validate_rules_freeze.py`

### decision C: what to do before any migration

在决定 Rust 迁移前，更应先完成 issue #13 原始方向缺口：

- 把 `soundscape_selection` 摘要传播到 stage7/stage8 contract；
- 不要只停在 `selection_progress`；
- 这样 stage5 -> stage8 的 contract 才真正闭合。

否则现在即使开始迁 Rust，也是在迁一个仍未完全定型的 stage7/stage8 contract。

## concrete recommendation

本轮建议采用：

### recommended option

- 保留 stage1-stage6 现有 Python 工具，不做全量 Rust 重写；
- 明确它们属于 build-side / validation-side tooling；
- 先把 issue #13 的 `soundscape summary propagation` 补完整；
- 随后单独开一条实现线，把 stage7 live runtime / preflight / report 迁到 Rust；
- 迁移时优先参考 `src/songh/src/stage7.rs` 的组织方式，但不要强行共用 runtime 模型。

### not recommended now

- 因“最小资源消耗”而重写全部 Python；
- 在 `soundscape` contract 还没稳定前大规模迁 stage7/stage8；
- 直接把 `musikalisches` 改成全实时常驻生成器，而没有先确认这是否真是目标。

## proposed follow-up issue

建议单独建立一个决策型 Issue，标题可类似：

- `Decision: keep musikalisches build-side Python tools, or migrate only stage7 live ops to Rust`

Issue 里需要用户明确拍板的点：

1. `musikalisches` 是否继续保持 `prerendered wav/mp4 + ffmpeg loop bridge` 架构。
2. 是否接受“只迁 stage7 live ops 到 Rust、保留 build-side Python”的分层方案。
3. 是否要把 stage1-stage4 冻结工具明确标注为 `dev-only / archival tooling`。
4. issue #13 的下一步是否先补 `soundscape_selection` 摘要传播，而不是继续扩张别的 live 功能。

## final recommendation

一句话结论：

- `src/musikalisches/tools` 里的 Python 脚本大多数不是最终直播必需项；
- 当前真正参与直播行为的 Python 面主要集中在 stage7 runtime wrapper；
- 因“最小资源消耗”而做全量 Rust 替换没有必要；
- 最合理的迁移目标是：先补完 issue #13 的 soundscape contract，再把 stage7 live ops 这一小簇迁到 Rust。
