# 260326 issue9 multilayer soundscape implementation plan

日期: `2026-03-26`

状态: `detailed staged plan`

来源:

- issue: `https://github.com/41490/chao5whistler/issues/9`
- latest decision comment: `https://github.com/41490/chao5whistler/issues/9#issuecomment-4132603918`
- study reference: `docs/study/260326-opus-free_audio_resources_guide.md`
- repo baseline:
  - `src/musikalisches/tools/build_stage5_unique_stream.py`
  - `src/musikalisches/tools/build_stage7_stream_bridge.py`
  - `src/musikalisches/tools/run_stage7_stream_bridge_runtime.py`

## 1. purpose

这份计划用于把 issue #9 最后一条回复里已经确认的方向，收束成一套可以持续落地的增强开发顺序。

本轮核心目标不是继续做 `8h` soak，而是先把“音乐性”和“长期自动换曲能力”补到足以重新进入真实 live 验证的程度。

本轮要同时完成 4 件事：

1. 把正式 live 音频基线切到 `stage5-sf2`
2. 把单组合保留时长冻结为 `16` 个 source cycle
3. 把单层 organ 输出扩成可控的多层声景
4. 给 live 路径补真正的 `next-combination scheduler/supervisor`

## 2. frozen decisions

issue #9 当前已经冻结以下 4 条决策：

1. 当前 `8h` soak 已停止，稳定性验证后置，先解决音乐性问题
2. 组合切换节奏固定为 `16` 个 cycle / 组合
3. 正式 live 音频后端切到 `stage5-sf2`
4. 参考 `docs/study/260326-opus-free_audio_resources_guide.md`，把背景扩展为“多层声景”，并整理成分阶段开发计划

## 3. current repo baseline

### 3.1 reusable pieces already present

- `stage5` 已有持久化 unique-combination ledger，能生成 `combination_id`、`played_unique_count`、`progress_label`
- `stage5-sf2` 已可走 `rustysynth` 真实 `SoundFont` 合成，不再受 `fallback_additive` 音色上限约束
- `stage6` 已能消费 stage5 产物并输出 `offline_preview.mp4`
- `stage7` 已有 bridge contract、preflight、runtime report、failure taxonomy、sample retention
- `systemd --user` live 入口已经存在，可作为后续 scheduler 接入点

### 3.2 current blockers

- 当前 live 路径只会重复推同一套 frozen `offline_audio.wav + offline_preview.mp4`
- `stage7` 没有“边界点申请下一组合并切换输入”的 supervisor
- 当前音频链路没有 background mix bus、ambient asset contract、drone contract、layer validation
- 当前 stage6 画面没有表达“当前声景层”或“当前 registration/profile”的能力
- 当前 stage8 readiness/ops 文档默认假设 source pair 在 soak 内不变

## 4. target architecture for this round

本轮建议先落到 `v1` 架构：

1. `Layer A`: 主旋律，来自 `stage5-sf2` 的 Mozart dice game organ render
2. `Layer B`: 低频持续音 `drone/pedal`，由 stage5 根据当前组合派生
3. `Layer C`: 环境声 `ambient bed`，来自受许可证约束的 loop asset pool
4. `Layer D`: 全局空间感处理，第一阶段优先做轻量 wet bus；卷积混响作为可后置增强

输出原则：

- stage5 负责生成统一混音后的 `offline_audio.wav`
- stage6/stage7/stage8 统一消费同一份混音产物，避免 live 端单独偷偷加层
- layer 元数据必须进入 artifact contract，保证 analyzer / validator / ops 可以看到真实声景组成

## 5. non-goals for this round

- 不在本轮恢复正式 `8h` soak 作为主目标
- 不在本轮做多机协同或分布式全局 ledger
- 不在本轮切换到纯实时 Rust 推流链替代现有 FFmpeg bridge
- 不在本轮追求“无缝热切换到零黑帧”级别的高复杂度切流
- 不在本轮一次性引入大量外部版权不清晰的音频素材

## 6. execution order

## phase P0: plan freeze and contract inventory

目标:

- 把 issue #9 决策固化为仓库内正式计划
- 列清当前 stage5/stage6/stage7/stage8 哪些 contract 可以复用，哪些必须扩展

范围:

- `docs/plans`
- `src/musikalisches/README.md`
- `src/musikalisches/USAGE.md`

产物:

- 本计划文档
- issue #9 技术决策提醒评论

验收门槛:

- 后续实现不再讨论 `16` cycle / 组合、`stage5-sf2`、以及“live 内必须持续前进 ledger”这些原则

## phase P1: live baseline shift to sf2 + 16-cycle artifacts

目标:

- 先把 live 基线从 `fallback_additive` 迁到 `stage5-sf2`
- 把单组合产物长度从当前默认短 loop 收束到 `16` 个 cycle

范围:

- `src/musikalisches/Makefile`
- `src/musikalisches/tools/build_stage5_unique_stream.py`
- `src/musikalisches/runtime`
- stage5/stage6/stage7 对 `loop_count` 的校验与默认值

必需变化:

- 新增或冻结 live profile 默认 `loop_count = 16`
- 明确区分:
  - offline smoke 的短 loop 默认值
  - live scheduler 的正式组合时长默认值
- `stage5-sf2` 作为 live 路径默认入口
- artifact 中显式记录:
  - `render_backend = soundfont_rustysynth`
  - `loop_count`
  - `combination_hold_cycles`
  - `source_cycle_duration_seconds`
  - `combination_duration_seconds`

验收门槛:

- 单次 stage5 live-profile 构建产物能稳定输出约 `16 * 12s = 192s` 级别的 source pair
- stage6/stage7 validator 不再把该长度视为异常
- live 路径默认不再退回 `fallback_additive`

## phase P2: soundscape asset pack and license manifest

目标:

- 为多层声景建立最小可用素材池和可审计 license manifest

范围:

- `ops/assets`
- `docs/study`
- 新的 asset manifest / validation tool

建议目录:

- `ops/assets/soundscapes/ambient/`
- `ops/assets/soundscapes/drone/`
- `ops/assets/soundscapes/impulse/`
- `ops/assets/soundscapes/manifests/`

必需变化:

- 每个可直播素材都必须有 manifest，至少记录:
  - `asset_id`
  - `layer_kind`
  - `source_url`
  - `license`
  - `attribution_required`
  - `loop_duration_seconds`
  - `loudness_target_dbfs`
  - `sha256`
- 先建立 `v1` 白名单:
  - `CC0`
  - `public_domain`
  - `Pixabay-like no-attribution commercial use`
- 若允许 `CC BY`，必须同步规划 description/about 页署名出口

验收门槛:

- 仓库内至少有一组可跑通的 ambient/drone 资产清单
- validator 能拒绝缺许可证字段或缺哈希的素材
- 后续 stage5 不读取“裸文件夹随机 wav”，只读取 manifest 化资产池

## phase P3: stage5 multilayer audio mix bus

目标:

- 把多层声景真正下沉到 stage5，输出统一混音结果

范围:

- `src/musikalisches/runtime`
- `src/musikalisches/tools/build_stage5_unique_stream.py`
- stage5 synth profile / new soundscape profile
- `validate_m1_artifacts.py`

建议的 v1 profile 结构:

- `main_registration_profile`
- `drone_profile`
- `ambient_profile`
- `global_fx_profile`
- `mix_bus_profile`

必需变化:

- stage5 根据 `combination_id` 或独立 seed 选择:
  - organ registration
  - ambient asset
  - drone strategy
- 新增 `soundscape_selection.json`，记录本次实际选中的 layer 资产与参数
- `offline_audio.wav` 改为 stage5 统一混音后的结果
- `artifact_summary.json` / `render_request.json` / `stream_loop_plan.json` / `m1_validation_report.json` 同步带出声景元数据
- validator 至少校验:
  - layer 清单存在
  - 主旋律层存在
  - mixed duration 与 `16` cycle 时长一致
  - 峰值 / RMS / loudness 不越界

建议的 v1 混音顺序:

1. 渲染主旋律 `sf2 organ`
2. 叠加 `drone/pedal`
3. 叠加 `ambient bed`
4. 做总线 gain / limiter
5. 可选做轻量 room/reverb

验收门槛:

- 单个 stage5 live-profile 产物在听感上已明显不是单层 organ
- analyzer/validator/summary 能看到实际 layer 组成
- 去掉 stage7 `amix` 也不影响最终 live 听感一致性

## phase P4: stage6 scene and metadata upgrade

目标:

- 让画面最少知道“这一首现在是什么声景配置”，而不是只有组合编号

范围:

- `src/musikalisches/tools/build_stage6_video_stub.py`
- `src/musikalisches/tools/build_stage6_video_render.py`
- stage6 scene profile / schema / validator

建议新增 contract:

- `soundscape_badges`
- `registration_label`
- `ambient_label`
- `combination_hold_progress`
- `layer_palette_hint`

必需变化:

- stage6 可消费 `soundscape_selection.json` 或等价 metadata
- footer 除组合进度外，至少能显示当前:
  - registration
  - ambient scene 名称
  - 当前组合在 `16` cycle 内的进度
- 画面层不必逐帧可视化真实音频分轨，但文案和调色需跟实际声景一致

验收门槛:

- 预览视频里能辨认当前组合对应的声景配置
- 画面文案与 stage5 真实音频层选择一致
- 新字段缺失时 validator 能给出明确失败摘要

## phase P5: stage8 live scheduler/supervisor

目标:

- 让 live 运行期间能在组合边界持续前进，而不是无限重复同一套 source pair

范围:

- 新 scheduler/supervisor tool
- `ops/systemd`
- stage7/stage8 ops guide
- 可能新增独立 live artifact 目录约定

推荐第一版策略:

- 不做复杂热切换
- 采用“边界点预构建下一套 artifact + 受控切换/重启 bridge”的 supervisor
- 任何时候最多保留:
  - `current`
  - `next`
  - `previous`
  三套 live artifact

必需变化:

- 新增 live supervisor 状态机:
  - `prepare_current`
  - `publish_current`
  - `prepare_next`
  - `switch_at_boundary`
  - `promote_next`
  - `retain_previous_report`
- scheduler 在切换前必须:
  - 从 ledger 申请下一个唯一组合
  - 生成 stage5/stage6/stage7 工件
  - 校验工件完整
  - 到边界点后执行受控切换
- 失败时必须有保底策略:
  - `next` 构建失败则继续维持 `current` 一轮
  - 超过阈值则进入 degraded/live-hold 状态并告警

建议输出新报告:

- `live_scheduler_state.json`
- `live_scheduler_history.json`
- `live_scheduler_failure_report.json`

验收门槛:

- live 期间能连续前进多个唯一组合
- ledger 在 supervisor 重启后仍持续前进，不因重启回退
- 切换失败不会直接把 live 打断成无输出

## phase P6: readiness, soak, and operator workflow refresh

目标:

- 把新的 live scheduler 和多层声景纳入现有 stage8 readiness/样本留存体系

范围:

- `docs/plans/260324-stage8-real-soak-ops-guide.md`
- `src/musikalisches/USAGE.md`
- `validate_stage7_stream_bridge.py`
- `validate_stage8_ops_readiness.py`
- `retain_stage8_ops_samples.py`

必需变化:

- readiness 检查新增:
  - live scheduler contract 完整
  - soundscape asset manifest 完整
  - `stage5-sf2` 默认路径可用
  - `16` cycle / 组合配置与 live profile 一致
- 样本留存新增:
  - 当前/下一首组合信息
  - soundscape selection
  - 资产 license 摘要
  - 切换历史
- soak 重新分层:
  - `music-smoke`: 多层声景听感/切换正确
  - `short-live`: 真实平台短时多次切换
  - `8h-soak`: 稳定性验证最后再跑

验收门槛:

- 运维文档可完整指导一次“多层声景 + 自动换曲”的真实短时 live
- `8h` soak 重新开始前，先有短时真实多次切换样本

## 7. implementation slices

建议按以下切片推进，避免一次性大改：

1. `slice-1`: 固化 live profile，切到 `stage5-sf2`，冻结 `16` cycle 默认值
2. `slice-2`: 建 soundscape asset manifest 与 validator
3. `slice-3`: 在 stage5 落地 ambient + drone + mix bus
4. `slice-4`: 在 stage6 补最小声景 metadata 展示
5. `slice-5`: 实现 live scheduler/supervisor 和受控切换
6. `slice-6`: 更新 readiness / sample retention / ops guide，最后回到真实 soak

## 8. risks and mitigations

风险 1: 外部素材许可证不清晰，后续 live 不可用

- 缓解: `v1` 先限制到白名单许可；所有素材必须 manifest 化

风险 2: 多层混音把主旋律淹没，听感变脏

- 缓解: 先冻结每层 loudness/gain guardrail，并在 validator 中校验

风险 3: scheduler 切换机制过于复杂，导致 live 反而更脆弱

- 缓解: 第一版只做受控切换/重启，不追求复杂热切换

风险 4: stage7/stage8 仍假设单一 source pair，不兼容新 supervisor

- 缓解: readiness/sample retention 提前纳入 scheduler 状态文件

风险 5: `sf2` 资产或 profile 选择太随机，缺乏稳定风格

- 缓解: 先用少量 curated registration profile，而不是完全自由随机 program

## 9. decisions still needed from the user

以下问题仍需用户继续拍板，建议在开始 P2/P3 前冻结：

1. `v1` 多层声景是否先只做 `main organ + drone + ambient`，把卷积混响放到后续增强？
   - 建议: `是`
2. 素材许可白名单是否严格限制为 `CC0 / public domain / Pixabay-like`，暂不接收 `CC BY`？
   - 建议: `是`
3. live 切换机制第一版是否接受“边界点受控重启 bridge”，而不是追求无缝热切换？
   - 建议: `是`
4. `ambient` 切换粒度是否以“每个组合固定一层”为默认，而不是组合内再动态换 ambient？
   - 建议: `是`
5. organ registration 是否先走“少量 curated profile 池随机”，而不是直接暴露任意 GM program 随机？
   - 建议: `是`
6. stage6 画面是否需要在第一版直接显示具体层名和 registration 名称？
   - 建议: `是`

## 10. ready-to-start order

如果上述未决项基本接受建议，实际开发顺序应为：

1. 先做 P1，确保 live 基线已经是 `sf2 + 16 cycles`
2. 再做 P2/P3，把多层声景下沉到 stage5
3. 再做 P4，让画面元数据跟上
4. 最后做 P5/P6，恢复真实平台短时 live 和后续 soak
