# 260503 issue40 bird-era forest mainline plan

日期: `2026-05-03`

状态: `detailed staged plan`

来源:

- issue: `https://github.com/41490/chao5whistler/issues/40`
- latest decision comment: `https://github.com/41490/chao5whistler/issues/40#issuecomment-4375703875`
- parent decision: `https://github.com/41490/chao5whistler/issues/28`
- deferred visual track: `https://github.com/41490/chao5whistler/issues/39`
- study reference: `docs/study/260501-opus-ghsingo-audio-architecture.md`
- current repo baseline:
  - `src/ghsingo/internal/composer/composer.go`
  - `src/ghsingo/internal/audio/mixer_v2.go`
  - `src/ghsingo/internal/backend/backend.go`
  - `src/ghsingo/internal/backend/gov2/gov2.go`
  - `src/ghsingo/internal/backend/sc/sc.go`
  - `src/ghsingo/scsynth/synthdefs/ghsingo_synthdefs.scd`

## 1. purpose

这份计划不是重复研究文档里的美学论证，而是把它压成一套**可以接到当前
`ghsingo` v2 代码骨架上的工程路线**。

本轮目标是把已经落地的 `state-vector + multi-layer + backend abstraction`
继续推进到 bird-era 主线:

1. 鸟鸣层从“可选 texture”升级为**核心安全信号层**
2. GitHub 事件主要用于调制“森林活性状态”，而不是继续增加可听 strike
3. bell accent 保留，但只作为稀有高价值事件的点缀
4. `go-v2` 先验证音乐语义，`scsynth` 作为生产级执行后端完成收敛

## 2. frozen direction for issue #40

基于 `2026-05-04` 的 issue 决策评论，本 issue 当前冻结以下方向：

1. **birdsong-first**
   - v3 主线以鸟鸣层为核心，而不是以 bell accent 为核心
2. **95/5 event split**
   - `95%` 事件只改慢状态
   - `5%` 稀有事件才触发可辨识的 accent
3. **visual stays deferred**
   - `0-5s` 视觉 hook 继续留在 `#39`
4. **Go-first, scsynth-final**
   - 第一阶段先在 `go-v2` 里做鸟鸣原型
   - 不在第一步就把正确性押注到 `scsynth`
5. **asset contract before sound-design sprawl**
   - 先把鸟素材、许可、响度、频段、署名出口做成合同
   - 不允许先堆 wav 再回头补治理
6. **CC-BY accepted, public-domain also researched**
   - 接受 `CC-BY`
   - 同时调研公开版权 / public-domain 的真实鸟录音来源
7. **4+1 starter pack**
   - 第一批素材固定为 `4` 个日间稳定物种 + `1` 个夜间候选物种
8. **night species entry from phase 1**
   - 第一阶段就保留独立夜间物种入口
9. **rare-event accent may be natural, not bell-only**
   - 稀有事件 accent 可以是 bell
   - 也可以是风声、雨声等对等自然采样
10. **keep tonal-bed in phase 1**
   - 第一阶段继续继承当前 `tonal-bed`
   - 先验证 bird 层与状态映射，再决定是否替换 floor

## 3. current repo baseline

### 3.1 what already exists

当前主线已经不再是 bell-era 的“每秒 cluster 直接敲钟”模型。仓库里已经具备：

- `composer` 慢状态:
  - `Density`
  - `Brightness`
  - `Mode`
  - `Section`
  - `AccentProb`
- `MixerV2` 长生命周期总线:
  - `L0` drone
  - `L0.5` tonal bed
  - `L1` pink-noise bed
  - `L2` sparse bell accent
  - shared reverb
- `backend.Backend` 抽象:
  - `go-v2`
  - `scsynth`
- `BackendBox` 生命周期包装:
  - 允许 backend 崩溃重启时 FFmpeg/RTMP 继续存活
- `observe/recorder` 与 `audio-metrics`:
  - 已有长期跑与统计的落脚点

### 3.2 what is still missing

bird-era 在当前仓库里还没有形成真正实现：

1. `composer.State` 没有“鸟鸣层状态”
2. `config` 没有 `[assets.birds]`、`[mixer.birds]`、`[composer.birds]`
3. `MixerV2` 没有鸟鸣 bus / grain scheduler / species diversity contract
4. `scsynth` SynthDef 只有 drone / tonal / bed / accent 四层
5. 资产合同里没有鸟素材 manifest、许可审计、署名出口
6. 观测项里没有 bird peak / bird density / species diversity 相关指标

结论:
**issue #40 不是调参数，而是 v2 -> v3 的层级重排与合同扩展。**

## 4. target architecture

建议把主线层级调整为：

| layer | 角色 | 生命周期 | 当前实现 | v3 目标 |
|---|---|---|---|---|
| `L0` | drone floor | always on | 已有 | 保留，继续做低频地基 |
| `L0.5` | tonal floor / pad | always on | 已有 | 保留，但允许更中性化 |
| `L1` | birds core bus | always on | 无 | **新增，主角层** |
| `L2` | forest air / bed | always on | pink-noise bed | 从“噪声床”进化为更服务鸟层的空气层 |
| `L3` | sparse bell/natural accent | sparse | 已有 | 降级为稀有事件点缀 |
| `all` | shared space + limiter | always on | 部分已有 | 统一空间感与 bird ceiling |

对应的数据流调整为：

```text
GH events
  -> composer v3 state
     -> habitat activity / bird density / bird diversity / mode / section
  -> backend
     -> continuous floors (drone / tonal / air)
     -> continuous bird bus
     -> sparse accents
  -> shared reverb + hard ceiling
  -> ffmpeg -> RTMP
```

## 5. musical control model

### 5.1 composer v3 state extension

建议在 `composer.State` 基础上新增：

- `BirdActivity`
  - 当前森林活跃度，控制鸟 grain 的平均触发密度
- `BirdDiversity`
  - 当前允许活跃的物种数量或分布权重
- `BirdBrightness`
  - 鸟层高频存在感，给 daypart / event entropy 调制
- `Daypart`
  - `dawn / day / dusk / night`
- `EventExcitement`
  - 稀有事件短时提升量，用于 `PR merged / Release`

建议在 `composer.Output` 基础上新增：

- `BirdCue`
  - 给 backend 的连续鸟层目标参数
- `AccentKind`
  - 区分普通 bell accent 与 `release spotlight`

### 5.2 event mapping

推荐先冻结一版**不追求炫技、只追求稳定隐喻**的事件映射：

| GitHub 事件 | 主要作用 | 默认处理 |
|---|---|---|
| `PushEvent` | 维持森林活性 | `BirdActivity` EMA 小幅上升 |
| `IssueCommentEvent` 或等价讨论量 | 增加栖息地繁忙度 | `BirdDiversity` baseline 小幅上升 |
| `PullRequestEvent opened` | 新鸟加入 | 30s 内平滑提高一种物种权重 |
| `PullRequestEvent merged` | 短时喜讯 | `EventExcitement` 上升，8-12s 内回落 |
| `ReleaseEvent` | 罕见强事件 | 允许 bell spotlight + birds short bloom |
| `ForkEvent` | 空间迁移 | 触发 pan / distance 微调，不增加 strike rate |
| `WatchEvent` / star 类 | 尽量少刺激鸟层 | 保留给视觉或更轻微的 accent/metadata |

核心约束：

1. 事件高峰**不能**直接转成更多 bird hits
2. 所有状态变化必须走 `Lag/EMA`
3. 鸟层变化要像“森林活了/静了”，不是“采样开始刷屏”

## 6. asset and license contract

### 6.1 directory and manifest proposal

建议新增：

```text
ops/assets/sounds/birds/
├── raw/
├── prepared/
├── manifests/
└── attribution/
```

最小 manifest 字段：

- `asset_id`
- `species`
- `source_url`
- `recordist`
- `license`
- `attribution_required`
- `duration_seconds`
- `sample_rate`
- `integrated_lufs`
- `peak_dbfs`
- `bandpass_hz`
- `sha256`
- `daypart_tags`
- `behavior_tags`

### 6.2 default asset policy

当前冻结决策：

1. 接受 `CC-BY`
2. 同步调研公开版权 / public-domain 的真实鸟录音来源
3. 同步产出 `attribution.md/json`
4. 在直播描述模板和仓库文档中保留署名出口
5. 素材先收敛到 `4+1`

原因:
现在工程瓶颈不是“鸟种太少”，而是**没有合同、没有过滤、没有响度边界**。

## 7. implementation phases

## phase P0: plan freeze and baseline inventory

目标:

- 冻结 `issue #40` 的范围和默认决策
- 记录当前 v2 代码与 bird-era 的差距

范围:

- `docs/plans`
- `docs/ambient/assets.md`
- `docs/ambient/config.md`
- issue `#40`

产物:

- 本计划文档
- issue 中的讨论清单

验收门槛:

- 后续实现不再反复争论“鸟层是否主角”“视觉是否并入本线”

## phase P1: bird asset pack and QA contract

目标:

- 建立最小可用鸟素材池
- 把许可证、频段、响度、物种标签做成可审计合同

范围:

- `ops/assets/sounds/birds/`
- `scripts/prepare-*`
- `docs/ambient/assets.md`
- child issue: `#41`

必需变化:

- 准备 `4` 种白天主物种 + `1` 种夜间候选物种
- 同步调研公开版权 / public-domain 的真实采样来源
- 产出 manifest 与 attribution 文件
- 增加预处理步骤:
  - 高通/低通
  - loudness trim
  - 噪声与过激片段剔除

验收门槛:

- 仓库里能明确指出“哪些 wav 可用于 live”
- validator 能拒绝缺许可证或缺哈希的素材

## phase P2: go-v2 bird bus prototype

目标:

- 在现有 `go-v2` 主线上验证 bird-era 的核心听感

范围:

- `src/ghsingo/internal/audio/`
- `src/ghsingo/internal/backend/gov2/`
- `src/ghsingo/cmd/render-audio-v2`
- child issue: `#42`

建议变化:

- 新增 `birdlayer.go` 或等价模块
- 先做**简化 sample-slice/granular**:
  - grain size `80-120ms`
  - density `0.3-1.5/sec`
  - 最大同时活跃鸟数 `<= 3`
  - pitch 默认不动
- 在 `MixerV2` 新增 bird bus gain、wet、ceiling

验收门槛:

- `render-audio-v2` 能输出包含连续鸟层的本地样本
- 30 分钟主观连听时，鸟层听起来是“环境安全信号”，不是重复采样机

## phase P3: composer v3 and config/schema contract

目标:

- 把鸟层从“音频 patch”升级为正式状态模型

范围:

- `src/ghsingo/internal/composer/composer.go`
- `src/ghsingo/internal/config/config.go`
- `docs/ambient/config.md`
- `ghsingo.toml`
- child issue: `#44`

必需变化:

- composer 新增 bird 相关状态
- 配置新增建议块:
  - `[composer.birds]`
  - `[mixer.birds]`
  - `[assets.birds]`
- 明确 daypart / density / diversity / excitement 参数

验收门槛:

- 不看代码也能从 toml 理解“当前 profile 的鸟层策略”
- 高事件密度不会推高 bell accent 的发射率

## phase P3.5: rare-event natural accent policy

目标:

- 把稀有事件 accent 从 `bell-only` 推进到 `bell or natural accent`

范围:

- accent taxonomy
- `Release / merged PR` 映射
- 自然采样候选: 风声、雨声、稀疏自然瞬态
- child issue: `#45`

验收门槛:

- rare-event accent 不再争夺主前景
- 自然 accent 替代不会破坏 birdsong-first 主线

## phase P4: scsynth parity and shared-space hardening

目标:

- 把已经在 `go-v2` 验证过的语义迁到 `scsynth`

范围:

- `src/ghsingo/internal/backend/sc/`
- `src/ghsingo/scsynth/synthdefs/ghsingo_synthdefs.scd`
- `scripts/compile-synthdefs.sh`
- child issue: `#43`

必需变化:

- 新增 bird granular / bird bloom / night-bird 相关 SynthDef
- 所有层统一进入共享空间与 master ceiling
- supervisor 指标中加入 synth/node 健康检查

验收门槛:

- `go-v2` 与 `scsynth` 在同一 profile 上语义一致
- scsynth 重启不会导致 RTMP 流中断

## phase P5: observe, soak, and production profile

目标:

- 把 bird-era 收敛成可长期运行的默认 live profile

范围:

- `src/ghsingo/internal/observe/`
- `src/ghsingo/cmd/audio-metrics`
- `ops/systemd/`
- `docs/ambient/soak-runbook.md`
- child issue: `#46`

建议新增观测项:

- `bird_peak_dbfs`
- `bird_density_per_min`
- `species_switch_count`
- `release_bloom_count`
- `backend_restart_count`

验收门槛:

- 24h soak 期间无 RTMP 断流
- 7d soak 没有 bird layer 节点泄漏或峰值越界
- 默认 profile 的 bird peak 始终受硬上限约束

## 8. explicit non-goals

本 issue 默认不做：

1. `#39` 的视觉启动钩子
2. 一次性引入大量未经治理的外部素材
3. 重新发明一套与当前 backend 抽象不兼容的实时音频框架
4. 把 bell accent 完全删除
5. 在没有资产合同前就讨论“20 种鸟还是 50 种鸟”

## 9. task decomposition

当前已拆出的实现 issue：

1. `#41` `ghsingo: bird asset contract + 4+1 intake pack`
2. `#42` `ghsingo: go-v2 bird bus prototype`
3. `#44` `ghsingo: composer v3 bird state + config schema`
4. `#45` `ghsingo: rare-event natural accent bank`
5. `#43` `ghsingo: scsynth bird-layer parity`
6. `#46` `ghsingo: bird-era observe metrics + soak profile`

推荐依赖顺序：

1. `#41`
2. `#42` 与 `#44`
3. `#45`
4. `#43`
5. `#46`

## 10. remaining questions

经过 `2026-05-04` 的决策后，以下问题仍允许在实现中继续细化，但不阻塞拆分：

1. **物种落位**
   - `4+1` 具体选哪几种鸟，优先级如何排
2. **公开版权来源优先级**
   - `CC-BY` 与 public-domain 候选库各自优先从哪些站点/录音人开始
3. **夜间行为模型**
   - 夜间是单独夜行鸟主导，还是“夜间鸟 + 更低密度 + 更远空间感”的混合策略
4. **rare-event accent 候选池**
   - 风声、雨声、稀疏自然瞬态里，哪些最适合作为 `Release / merged PR` 默认 accent
5. **bird ceiling 与 loudness 目标**
   - `go-v2` 与 `scsynth` 两条路径上，bird layer 的硬上限和默认 gain 取值怎么对齐

## 11. done definition

只有同时满足以下条件，issue #40 才算完成：

1. bird-era 已被固化成仓库内可执行计划，而不是停留在研究文档
2. 当前代码基线与未来改动边界已经明确，不再模糊描述“加一层鸟鸣试试”
3. 资产、配置、composer、backend、observe 的合同变化已经列清楚
4. issue 线程里已有冻结决策与子 issue 分解，而不是只有一个标题
5. 后续实现工作可以据此继续拆分，不需要重新做一遍架构定义
