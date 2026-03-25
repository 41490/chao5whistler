# 260325 issue4 staged implementation plan

日期: `2026-03-25`

状态: `staged plan`

来源:

- issue: `https://github.com/41490/chao5whistler/issues/4`
- decision comment: `https://github.com/41490/chao5whistler/issues/4#issuecomment-4124242931`
- prior scope split: `https://github.com/41490/chao5whistler/issues/4#issuecomment-4124203798`

## 1. purpose

这份计划用于把 issue #4 中已经确认的长期直播优化需求，收束为一套分阶段、可验收、可回滚的实施顺序。

目标不是把 stage5 / stage6 / stage7 混成一次性大改，而是先冻结决策，再按依赖关系推进：

1. 先消除 stage7 运维语义误解与静默失败感知
2. 再补“长期无人值守不重复”的调度基础
3. 再升级 scene contract 与 renderer
4. 最后收口到真实 stage8 soak

## 2. frozen decisions

issue #4 当前已冻结以下 8 条决策，后续实现默认以此为边界：

1. 去重范围：`重启后也不重复`
2. 输出主规格：`1280x720` 横屏为主，`Shorts` 由 YouTube 云端切
3. 总组合数口径：以 canonical 规则为准，即当前 `11^16 = 45,949,729,863,572,161`
4. 中央展示口径：显示每个位置对应的 `selector/roll` 结果，不显示“实际音高集合代表音”
5. 频谱层：先做基于现有 `envelope` 的伪频谱动线，不做真实 FFT
6. 管风琴音色：第一步只改 `MIDI program`；同时补一次网络调研，若有现成资源可后续接入
7. 标题文案：`Musikalisches Wuerfelspiel:Mozart Rellstab 1790`
8. 标题配置面：标题文案必须来自 `.toml` 配置文件，支持 `\n` 换行，且多行按中心对齐

## 3. design constraints

### 3.1 hard constraints

- stage7 当前问题不能靠文档口头解释解决，必须把 console 可观测性补到运行入口
- “重启后不重复”不能只靠内存集合，必须引入持久化 ledger
- 新的视觉需求不能只改 stage6 renderer，必须先扩 stage5 产物契约与 stage6 scene schema
- 标题文案不能继续只写死在 scene profile JSON 中，后续必须给出 `.toml` 配置入口与换行语义
- stage8 soak 只消费已经冻结好的 stage5/stage6/stage7 工件，不承担需求探索职能

### 3.2 non-goals for this round

- 不在本轮切主输出到竖屏 `720x1280`
- 不在本轮实现真实 FFT 频谱
- 不在本轮直接改成多机协同的全局去重系统
- 不在本轮引入纯 Rust 编码/推流替代 FFmpeg bridge

## 4. execution order

## phase P0: spec freeze and plan sync

目标:

- 把 issue #4 的 7 条确认项变成仓库内正式 plan
- 明确 stage5 / stage6 / stage7 各自负责的变化边界

产物:

- 本计划文档
- issue #4 决策提醒评论

验收门槛:

- 后续实现不再反复讨论去重范围、布局主规格、总组合数口径、标题文案

## phase P1: stage7 semantics and observability

目标:

- 解决 `MUSIKALISCHES_STAGE7_MAX_RUNTIME_SECONDS` 被误解为“长期直播参数”的问题
- 解决 preflight fail 或 runtime budget 到时退出时的“静默退出”感知

范围:

- `run_stage7_stream_bridge.sh`
- `run_stage7_stream_bridge_runtime.py`
- stage7 / stage8 运维文档

必需变化:

- 明确 `MAX_RUNTIME_SECONDS` 语义是 `overall wrapper runtime budget`
- 明确长期运行模式是 `LOOP_MODE=infinite` 且不设置 runtime limit
- 所有 preflight fail 分支同步向 `stderr` 打印最小摘要
- wrapper 退出前打印 report/log 路径

验收门槛:

- 使用错误 URL 或 runtime budget 到时退出时，控制台能直接看到失败摘要
- 操作者无需先翻 Python 源码才能理解“为什么 120 秒后退出”

## phase P2: stage5 unique combination scheduler

目标:

- 为“长期无人值守且重启后不重复”补齐真正的调度层

范围:

- stage5 roll 生成入口
- combination ledger 持久化
- stage5 artifact schema

必需变化:

- 新增 canonical `combination_id` 表示
- 新增随机 `16` 位 roll 生成入口，替代当前只靠 `--demo-rolls`
- 新增持久化 ledger，记录已播组合
- 撞库时自动重投，不输出 replayed artifact
- artifact 显式写出:
  - `combination_id`
  - `rolls`
  - `selector_results`
  - `total_combinations`
  - `played_unique_count`
  - `is_replayed`

默认边界:

- 先按单机本地持久化 ledger 实现
- ledger 损坏或缺失时，运行必须显式报错或进入受控重建流程，不能默默重复

验收门槛:

- 单次进程内无重复
- 重启进程后仍不重复
- 进度数字与 canonical 组合总数口径一致

## phase P3: stage6 scene contract upgrade

目标:

- 把新视觉需求先冻结成可校验 schema，再交给 renderer 消费

范围:

- stage6 scene profile / schema
- stage5 analyzer -> stage6 scene builder contract

新增 contract 区块:

- `title_area`
- `footer_progress_area`
- `selector_label_sprites`
- `spectrum_trails`
- `short_safe_layout`
- `text_overrides`

必需字段:

- 标题文本与两行排版策略
- `.toml` 注入标题文本、`\n` 换行解析、以及多行居中规则
- progress 文案格式
- label 的布局边界、随机种子、大小范围、idle/active motion 参数
- 伪频谱层的 envelope 映射参数
- 1280x720 主规格下的 short-safe 中央区域约束

验收门槛:

- scene manifest 能完整表达新画面元素
- validator 能拒绝缺字段或越界布局

## phase P4: stage6 renderer upgrade

目标:

- 把冻结后的 scene contract 变成稳定的本地预览视频输出

范围:

- stage6 video renderer
- stage6 preview validation

必需变化:

- 顶部标题区：两行排版 + 轻微 glow jitter
- 底部 footer：`played_unique_count / total_combinations`
- 中央区域：16 个 selector/roll label 的随机布局
- 当前正在演奏的 label 做轻微上下跳动
- 非当前 label 做轻微左右晃动
- 所有文字下层增加伪频谱动线背景

验收门槛:

- `1280x720` 预览中标题、中央标签、footer 全部可读
- 按 short-safe 中央区观察时，核心信息不被裁掉
- motion 不影响可读性，不遮挡主要文案

## phase P5: organ timbre track

目标:

- 先给直播链路一个可工作的管风琴方向音色，再评估更高质量资源

分两步:

1. 第一阶段只改 `MIDI program` 到 organ family
2. 第二阶段做网络调研，若存在可复用的 organ `sf2` 或同类资源，再作为可选 profile 引入

边界:

- 不让外部音色资源成为 P2/P3/P4 的阻塞项
- 资源调研失败时，主链路仍可用 program 级切换继续推进

验收门槛:

- 默认 profile 可输出 organ family 音色
- 若引入外部资源，必须以可选方式接入，不破坏 deterministic fallback

## phase P6: stage7 integration and stage8 soak

目标:

- 让新的调度产物与新 renderer 输出进入现有 stage7 bridge，并完成真实平台 soak

范围:

- stage7 bridge 输入工件适配
- stage8 ops guide 更新
- 真机 preflight / soak 样本留存

必需变化:

- stage7 默认消费新的 stage5/stage6 产物字段
- 文档明确真实长期直播启动方式
- 报告里能对账组合进度、退出分类、重试次数与 soak 时长

验收门槛:

- 真实 `rtmps://...` 地址上，preflight 能稳定推进到 publish probe 或 pass
- `LOOP_MODE=infinite` 且不设 runtime limit 时，直播不会因为“预算参数误用”提前停止
- stage8 汇报中可同时给出直播稳定性与组合进度信息

## 5. dependency graph

严格依赖如下：

- `P1` 必须先完成，否则后续运维仍会被“静默退出”误导
- `P2` 是 `P3/P4/P6` 的前置，没有持久化去重就没有真实长期直播进度
- `P3` 是 `P4` 的前置，没有 schema 冻结就不应直接改 renderer
- `P5` 可与 `P3/P4` 部分并行，但不能阻塞主链路
- `P6` 最后执行，因为它依赖新的 stage5/stage6 产物已稳定

## 6. recommended implementation order

建议实际落地顺序：

1. 先做 `P1`，尽快修掉 stage7 语义误解和 console 观测缺口
2. 再做 `P2`，建立可持久化的不重复调度基础
3. 再做 `P3`，冻结 scene contract
4. 然后做 `P4`，把视觉层补齐
5. `P5` 作为并行支线推进
6. 最后执行 `P6`，进入真实平台 soak

## 7. stage ownership summary

- stage5 负责：组合生成、去重 ledger、进度元数据
- stage6 负责：scene schema、title/footer/label/spectrum 的视觉表达
- stage7 负责：live wrapper、preflight、runtime observability、bridge 集成
- stage8 负责：真实平台人工运维与 soak 验收

## 8. exit condition

只有当以下条件同时满足，issue #4 这一轮需求才算完成：

1. 控制台不再出现“静默退出”感知
2. 长期直播可以在重启后继续保证组合不重复
3. 画面中能稳定显示标题、组合进度、selector/roll 标签、伪频谱动线
4. 默认音色已切到 organ family，外部资源调研结果已归档
5. 新工件已通过 stage7 bridge 并完成至少一轮真实 stage8 soak
