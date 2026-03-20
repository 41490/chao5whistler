# 260320-musikalisches guiding plan

> status: guiding plan
>
> model: Codex (GPT-5)
>
> basis: `docs/assay/260320-musikalisches-research-plan.md`

## purpose

这份文件不是研究结论稿，而是整个工程的指导性详细计划。

它负责回答 4 个问题：

1. 这个工程现在到底在做什么。
2. 先做什么，后做什么，什么不能并行做。
3. 每一阶段的产物、验收门槛、退出条件是什么。
4. 什么条件满足后，才允许从“资料工程”进入“Rust 实现工程”。

## project definition

当前冻结后的工程定义如下：

- 工程入口：`src/musikalisches`
- 首个 work family：Mozart dice-game printed tradition
- 首个 canonical work：`mozart_dicegame_print_1790s`
- canonical witness：`Rellstab, Berlin, ca.1790`
- verification witness：`N. Simrock, Bonn, 1793`
- 首个运行目标：`offline realization + offline audio render`

由此得到的总目标不是“立刻推流”，而是：

- 先把一个可追溯、可校验、可重放、可离线出音频的 Mozart 1790 印刷骰子游戏数据产品做完整；
- 再在这个稳定数据基础上，逐步扩展到视频与直播。

## governing principles

### 1. data before runtime

任何运行时功能都不能先于数据冻结。

严格顺序是：

1. witness 定义
2. 母谱录入
3. 规则核对
4. ingest 规范化
5. 离线 realization
6. 离线音频
7. 视频
8. 推流

### 2. one canonical witness first

首阶段只允许一个 canonical witness。

当前固定为：

- `rellstab_1790`

`simrock_1793` 只作为复核来源，不作为并行输入事实源。

### 3. runtime must consume normalized data

运行时不应直接依赖：

- 原始 MEI
- 原始 MusicXML
- 原始扫描页

运行时应只依赖 ingest 之后的规范化产物。

### 4. deterministic first

在进入视频和直播前，系统必须先满足：

- 同输入可重放
- 同规则可校验
- 同片段可追溯

如果这一点不成立，后续直播只会放大错误。

### 5. research and implementation stay separated

后续文档与产物要持续区分：

- `docs/study/*`
  - 研究原料
- `docs/assay/*`
  - 研究结论与依据
- `docs/plans/*`
  - 实施与推进计划
- `src/musikalisches`
  - 最终实现

## scope

## in scope

- Mozart 1790 印刷骰子游戏传统的数据产品化
- `Rellstab 1790` 底本优先的母谱工程
- `Simrock 1793` 复核差异工程
- `MusicXML + MEI + JSON` 的三层契约
- offline ingest
- deterministic realization
- offline audio render
- 后续视频和推流的进入门槛设计

## out of scope for the current engineering start

- 直接开发实时直播
- 直接开发最终视频风格
- 同时支持多个 Mozart 传统
- 直接实现纯 Rust 媒体编码/RTMP
- 一开始就做多 work family 通用框架

## project tracks

整个工程拆成 5 条 track，但不是全部并行。

### track A: source governance

负责：

- witness 定义
- source manifest
- canonical / verification policy
- 页码与扫描指认

### track B: mother-score engineering

负责：

- `mother_score.musicxml`
- `mother_score.mei`
- fragment id 体系
- 结构完整性

### track C: rules and validation

负责：

- `rules.json`
- `16x11` 表一致性
- realization 校验
- witness diff

### track D: ingest pipeline

负责：

- MusicXML ingest
- MEI 对齐
- normalized fragments / measures / report

### track E: runtime implementation

负责：

- offline realization
- offline audio render
- analyzer
- video
- stream

其中 A/B/C 是前置轨道，D 在其后，E 最后。

## master execution order

### stage 0: object freeze

目标：

- 冻结工作对象，不再混用 K.516f 与 1790s printed tradition

完成条件：

- 全部后续文档统一使用：
  - `mozart_dicegame_print_1790s`
  - `rellstab_1790`
  - `simrock_1793`

退出条件：

- 若对象再次漂移，后续阶段一律暂停

### stage 1: source freeze

目标：

- 冻结底本、复核底本与来源链

必需产物：

- `source_manifest.json` witness 级字段补全
- 页码与扫描来源追踪表
- fragment identity map 草案

验收门槛：

- 对每个片段编号，都知道它属于哪个 witness、页码和定位方式

不得跳过：

- 不能先录 MusicXML 再回头补 provenance

### stage 2: mother-score freeze

目标：

- 形成可核验的 `mother_score.musicxml`
- 形成配套 `mother_score.mei`

必需产物：

- `mother_score.musicxml`
- `mother_score.mei`
- 片段编号到小节/声部的稳定映射

验收门槛：

- 每个 fragment 都能稳定定位
- 音高、时值、声部边界闭合
- 不依赖人工口述解释

退出条件：

- 若仍有大段 placeholder，不能进入下一阶段

### stage 3: rules freeze

目标：

- 规则层与母谱层完全对齐

必需产物：

- `rules.json`
- `mozart_16x11_table.json` 对账记录
- `witness_diff.json` 初版

验收门槛：

- 从规则表到谱面可正向定位
- 从谱面 fragment 可反向回到规则位点
- Simrock 差异不影响 canonical 运行时定义，或已显式记录

### stage 4: ingest freeze

目标：

- 把 scholarly source 转成 runtime-ready normalized data

必需产物：

- `ingest/fragments.json`
- `ingest/measures.json`
- `ingest/validation_report.json`

验收门槛：

- runtime 不再需要直接解析 mother score
- validation report 可稳定发现：
  - 缺 fragment
  - 非法 selector
  - 时值不闭合
  - 编号不一致

### stage 5: milestone M1

目标：

- 完成 deterministic offline realization
- 完成 offline audio render

必需产物：

- realized fragment sequence
- note-event sequence
- offline audio output
- M1 验证报告

验收门槛：

- 同一组输入多次运行一致
- realization 与 `16x11` 规则一致
- 音频没有结构性错误

### stage 6: visual expansion

前提：

- stage 5 完成

目标：

- 在稳定音频事件与分析数据上接入视频渲染

必需产物：

- analyzer 输出契约
- visual scene rules
- offline video sample

验收门槛：

- 视觉严格依附已冻结的分析输出
- 不反向改变音频或 realization 契约

### stage 7: stream bridge

前提：

- 音频和视频离线输出稳定

目标：

- 建立 FFmpeg 桥接与 env-based key 输入

必需产物：

- stream adapter 设计
- FFmpeg 参数模板
- 启动/失败日志策略

验收门槛：

- 不泄漏 stream key
- 失败路径可诊断

### stage 8: soak and operations

前提：

- 离线与桥接都稳定

目标：

- 8h~24h 连续运行验证

必需产物：

- soak test 记录
- drift 检查
- restart / recovery 策略

验收门槛：

- 不出现不可解释的同步漂移
- 崩溃与退出可被记录与归类

## detailed milestone table

### milestone M0

名称：

- canonical data contract freeze

输入：

- 当前 `docs/study/*`
- `docs/assay/260320-musikalisches-research-plan.md`

输出：

- witness policy
- data contract
- source manifest schema

完成定义：

- 工程内不再对“到底实现哪一个 Mozart 对象”有歧义

### milestone M1

名称：

- deterministic offline realization

输入：

- canonical mother score
- rules
- explicit roll sequence

输出：

- fragment sequence
- normalized note events
- offline audio

完成定义：

- realization 与音频输出可重放

### milestone M2

名称：

- offline visual coupling

输入：

- M1 输出
- analyzer contract

输出：

- offline video sample

完成定义：

- 视频只依赖已冻结的分析层

### milestone M3

名称：

- controlled stream bridge

输入：

- M1/M2 输出
- FFmpeg adapter design

输出：

- RTMP bridge draft

完成定义：

- 具备安全的 key 输入方式和可诊断失败路径

## deliverables by artifact

### required document deliverables

- `docs/assay/260320-musikalisches-research-plan.md`
- `docs/plans/260320-musikalisches-guiding-plan.md`

### required study deliverables before coding

- `source_manifest.json` witness 级补全
- `rules.json` 固化
- `mother_score.musicxml` 完整版
- `mother_score.mei` 对齐版
- `fragment identity map`
- `witness_diff.json`

### required implementation deliverables before video

- `fragments.json`
- `measures.json`
- `validation_report.json`
- deterministic realization sample
- offline audio sample

## dependencies and precedence

以下依赖不可颠倒：

- `source_manifest` 先于 `mother_score`
- `mother_score` 先于 `ingest`
- `rules reconciliation` 先于 `realize`
- `realize` 先于 `render-audio`
- `render-audio` 先于 `render-video`
- `render-video` 先于 `stream`

唯一允许的并行，是：

- 在不改 canonical 定义的前提下，Simrock 1793 的 witness diff 可与 Rellstab 1790 的 mother-score 录入局部并行

## review checkpoints

### checkpoint A

时机：

- stage 1 结束

你应重点审核：

- 是否真的冻结了 `rellstab_1790`
- `source_manifest` 是否足够追溯

### checkpoint B

时机：

- stage 2 结束

你应重点审核：

- `mother_score.musicxml` 是否能独立表达片段事实
- 是否仍残留 placeholder

### checkpoint C

时机：

- stage 3 结束

你应重点审核：

- `16x11` 表、`rules.json` 与 mother score 是否三者一致

### checkpoint D

时机：

- stage 5 结束

你应重点审核：

- realization 是否 deterministic
- offline audio 是否能作为后续所有阶段的黄金样本

## implementation entry criteria

只有满足以下条件，才允许正式进入 Rust 编码：

1. canonical witness 已冻结
2. `mother_score.musicxml` 不再是 placeholder
3. `rules.json` 与 `16x11` 表完成核对
4. 至少有一份可用的 normalized ingest 产物设计
5. M1 的输入输出契约已被你认可

否则，编码只会把数据问题转移成代码问题。

## change control

如果未来需要修改以下任何一项，必须先改文档，再改实现：

- `work_id`
- `canonical_witness_id`
- selector 模型
- fragment 编号体系
- ingest 输出契约
- milestone 完成定义

换言之：

- 文档是实现的前置约束
- 不是实现后的补充说明

## next planning target

在这份 guiding plan 获得你确认后，下一份计划文档才适合进一步细化为：

- 首批实施 TODO 清单
- 每阶段产物模板
- 每个产物的最小字段清单
- 实施时的审查顺序

那一版才会真正成为“开始动手前的执行手册”。

# refer.

## A. direct basis

- `docs/assay/260320-musikalisches-research-plan.md`

## B. repository internal sources

- `docs/study/music_dice_games_package/README.md`
- `docs/study/music_dice_games_package/mozart_dicegame_print_1790s/README.md`
- `docs/study/music_dice_games_package/mozart_dicegame_print_1790s/index.json`
- `docs/study/music_dice_games_package/mozart_dicegame_print_1790s/rules.json`
- `docs/study/music_dice_games_package/mozart_dicegame_print_1790s/source_manifest.json`
- `docs/study/music_source_basis_package/docs/mozart_16x11_table.json`
- `docs/study/music_source_basis_package/rust/examples/mozart_rules.rs`
- `docs/study/music_source_basis_package/rust/examples/musicxml_to_mei_via_verovio.rs`

## C. externally verified sources already incorporated via assay

- IMSLP: `Musikalisches Würfelspiel, K.516f`
  - https://imslp.org/wiki/Musikalisches_W%C3%BCrfelspiel%2C_K.516f_(Mozart%2C_Wolfgang_Amadeus)
- IMSLP: `Musikalische Würfelspiele, K.Anh.C.30.01`
  - https://imslp.org/wiki/Musikalische_W%C3%BCrfelspiele%2C_K.Anh.C.30.01_%28Mozart%2C_Wolfgang_Amadeus%29
- Wikipedia: `Musikalisches Würfelspiel`
  - https://en.wikipedia.org/wiki/Musikalisches_W%C3%BCrfelspiel
- W3C: `MusicXML 4.0`
  - https://www.w3.org/2021/06/musicxml40/
- MEI Guidelines 5.1
  - https://music-encoding.org/guidelines/v5/content/index.html
- Verovio reference: `Encoding formats`
  - https://book.verovio.org/interactive-notation/encoding-formats.html
- Verovio reference: `Input formats`
  - https://book.verovio.org/toolkit-reference/input-formats.html
