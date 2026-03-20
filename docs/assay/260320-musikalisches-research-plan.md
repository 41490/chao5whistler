# 260320-musikalisches research plan

> status: assay only, no code changes
>
> model: Codex (GPT-5)

## case summary

本轮调研后的正确理解，不应再直接写成“开始实现 K.516f 无限直播工具”，而应先拆成两个层次：

1. `src/musikalisches` 是未来实现入口。
2. 当前仓库里已经给出的 Mozart 研究包，主目录是 `docs/study/music_dice_games_package/mozart_dicegame_print_1790s`，它对应的是 **1790s 印刷骰子游戏传统**，不是已经完成外交式编码的 `K.516f` 手稿母谱。

因此，当前真正可执行的工作不是立刻写 Rust 引擎，而是先把“对象到底是哪一个 witness / tradition”定清楚，再把母谱层和规则层的资料链条冻结。

## decision record

根据你本轮最新确认，以下决策已经冻结：

1. 首个 Mozart 目标：接受以 `mozart_dicegame_print_1790s` 作为首个可执行对象。
2. canonical printed witness：`Rellstab, ca.1790` 优先；`N. Simrock, 1793` 作为复核 witness。
3. 首个可运行里程碑：同意先做到 `offline realization + offline audio render`。

由此带来的直接含义是：

- 当前项目第一阶段的主题不再是“直播工具”，而是“Rellstab 1790 印刷骰子游戏数据产品化”。
- `src/musikalisches` 的首个目标不是实时系统，而是先消费一套可核验、可重放、可转音频的稳定数据。
- Simrock 1793 不作为并行底本，而作为差异复核来源。

## verified findings

### 1. 当前仓库的 Mozart 资料包，已经采用了正确的分层方向

仓库内现有研究包已经明确采用：

- `mother_score.mei`
- `mother_score.musicxml`
- `index.json`
- `rules.json`
- `source_manifest.json`

这说明后续 Rust 工程不应把“谱面事实”和“随机规则”混在一份数据里，而应保持：

- 母谱层：`MEI / MusicXML`
- 规则层：`JSON`
- 运行时索引层：由 Rust 在 ingest 阶段生成的内部规范化结构

但需要注意，`docs/study/music_dice_games_package/README.md` 已经明确说明当前 `mother_score.mei` 与 `mother_score.musicxml` 还是 **template placeholders**，不能把它们误当作已经可直接驱动实现的权威谱面。

### 2. 当前仓库里存在“研究对象混线”的风险

仓库内 `src/musikalisches/README.md` 仍在把以下两条传统揉在一起：

- `K.516f` 手稿传统
- 1790s 印刷骰子游戏传统

而外部核验显示，这两者至少在资料入口上是应当区分的：

- IMSLP 的 `Musikalisches Würfelspiel, K.516f` 页面单列为 `1787`。
- IMSLP 的 `Musikalische Würfelspiele, K.Anh.C.30.01` 页面则单列为 1790s 印刷传统，并明确出现 `Rellstab` 与 `N. Simrock` 两条印刷来源。
- Wikipedia 也把“1792/Simrock 出版的骰子游戏传统”与“1787 手稿含 176 个单小节片段但无掷骰说明”放在同一词条下分开描述。

结论：

- “Musikalisches Würfelspiel” 可以是总题。
- 但“首个要做的 Mozart 数据集”必须在 `K.516f autograph` 与 `1790s printed dice-game tradition` 之间二选一。
- 在你当前给定的本仓库资料里，**更接近可实施起点的是 `mozart_dicegame_print_1790s`，不是已经完备的 K.516f 外交式母谱。**

### 3. 母谱层应以 MusicXML 为首要 ingest 格式，MEI 为存档与校验增强层

外部核验显示：

- MusicXML 4.0 在 W3C 页面上被定义为用于数字乐谱交换与归档的开放格式，且文档结构、reference、schema 与示例齐全。
- MEI 5.1 官方指南明确覆盖了 `Metadata`、`Facsimiles and Recordings`、`Integrating MEI with other Standards and Formats`。

因此，结合当前仓库资料，最稳的工程策略不是“MEI 或 MusicXML 二选一”，而是：

- `MusicXML` 作为首要 ingest 格式：
  - 更适合先把音符、时值、声部、分小节结构拉进 Rust 侧。
- `MEI` 作为学术存档与增强描述层：
  - 更适合保留来源、修订、facsimile、外交式标注等。

这也与仓库内已有示例 `musicxml_to_mei_via_verovio.rs` 的方向一致：先稳定 MusicXML 流，再补 MEI 对齐，而不是一开始把运行时建立在 MEI 直接解析上。

### 4. JSON 规则层当前已经足够承担“先研究后实现”的约束角色

仓库内 `docs/study/music_source_basis_package/docs/mozart_16x11_table.json` 已经给出了：

- `11` 个掷骰和结果：`2..12`
- `16` 个列位：`A1..A8`, `B1..B8`
- 每列对应 `11` 个候选片段编号

这说明对于 Mozart 印刷型传统，`rules.json` 与 `16x11 table` 可以先承担：

- 规则校验
- 选段索引
- 样例重放

但它们仍不能替代母谱层本身，因为：

- 规则层只告诉你“该选哪一格”
- 母谱层才告诉你“这一格真正的音符是什么”

### 5. C. P. E. Bach 数据包的成熟度高于 Mozart 印刷包

外部核验显示，Bach Digital 对 `Wq 257 / H 869` 这一作品页直接暴露了：

- `PDF`
- `XML`
- `MEI`
- `JSON-LD`

并明确给出：

- `Wq 257`
- `H 869`
- `ca. 1757`
- Marpurg 1757 的刊载信息

这意味着：

- `cpebach_wq257_h869_einfall` 更接近“可直接做机器 ingest”的资料条件。
- Mozart 1790s 包目前则更像“研究 scaffold + 规则层已备好 + 母谱层待外交式转写”。

这点不改变项目主线，但会影响节奏：

- Mozart 方向先要补母谱。
- C. P. E. Bach 方向可更早验证 ingest 流水线。

## corrected plan

### phase r0: freeze the canonical target

在任何 Rust 代码启动前，先冻结首个 canonical work：

- 选项 A：`mozart_dicegame_print_1790s`
- 选项 B：`K.516f autograph`

我的当前建议：

- **先以 `mozart_dicegame_print_1790s` 为首个可执行数据集**

原因：

- 它已经有 `rules.json`、`index.json`、`source_manifest.json`
- 本仓库已有 `16x11` 表与 Rust 示例
- 资料结构与“骰子选择 -> 片段拼接”的运行时模型更直接对应

如果你仍坚持 “必须先做精确 K.516f”，那就应把下一阶段改名为：

- `K.516f diplomatic transcription project`

而不是直接称为直播工具实现，因为那会把“谱面整理工程”伪装成“软件工程”。

### phase r1: normalize the source contract

对 `src/musikalisches` 未来要消费的数据，先冻结统一 contract：

```text
work/
  index.json
  rules.json
  source_manifest.json
  mother_score.musicxml
  mother_score.mei
  ingest/
    fragments.json
    measures.json
    validation_report.json
```

建议职责：

- `index.json`：作品元信息、generation model、instrumentation
- `rules.json`：规则与约束
- `source_manifest.json`：来源与 witness 追踪
- `mother_score.musicxml`：首要 ingest 输入
- `mother_score.mei`：校验与存档增强
- `ingest/*.json`：Rust 运行时真正消费的规范化结果

关键点：

- 运行时不要直接依赖原始 MEI/MusicXML 做实时解析
- 应先离线 ingest，再产出稳定内部结构

### phase r2: complete the Mozart mother-score gap

如果首个 canonical work 选 `mozart_dicegame_print_1790s`，真正的待补项是：

1. 选定 canonical printed witness
2. 逐片段转写成可核验的 `mother_score.musicxml`
3. 再生成或对齐 `mother_score.mei`
4. 用 `16x11 table` 反查每个片段编号是否落对

这一步完成前，不建议写合成器。

因为如果母谱未冻结，后续这些层都会返工：

- fragment id
- measure boundary
- voice split
- repeat / pickup / ornament interpretation
- seed replay consistency

### phase r3: use C. P. E. Bach as the ingest rehearsal work

建议把 `cpebach_wq257_h869_einfall` 作为 ingest rehearsal：

- 不是为了替代 Mozart 主线
- 而是为了先跑通：
  - `XML/MEI -> normalized JSON`
  - `source_manifest -> validation_report`
  - `Rust schema -> offline render sample`

这样可以把“资料处理链”和“作品特殊规则”拆开验证。

### phase r4: define implementation order after data is frozen

当 `mother_score` 和 `rules` 真正确认后，再进入实现顺序：

1. offline ingest
2. deterministic fragment realization
3. offline audio render
4. background layer mix
5. analyzer
6. geometric video
7. ffmpeg bridge
8. long-run streaming

这一步之前，不建议再讨论编码参数、RTMP 细节或画面效果优先级。

## implementation-grade specification

### A. canonical source policy

从这一轮起，建议在文档和后续实现中统一使用以下叫法：

- `work family`
  - Mozart dice-game printed tradition
- `canonical witness`
  - Rellstab, Berlin, ca.1790
- `verification witness`
  - N. Simrock, Bonn, 1793

这样做的目的，是避免以后再把：

- 作品家族
- witness
- 运行时 work id

混成一个层次。

建议的稳定标识：

```text
work_id: mozart_dicegame_print_1790s
canonical_witness_id: rellstab_1790
verification_witness_ids:
  - simrock_1793
```

### B. repository-facing target layout

当前不修改实现代码，但后续实施应围绕如下目录关系组织：

```text
src/musikalisches/
  README.md
  future Rust workspace

docs/study/music_dice_games_package/
  mozart_dicegame_print_1790s/
    mother_score.musicxml
    mother_score.mei
    index.json
    rules.json
    source_manifest.json

docs/study/music_source_basis_package/
  docs/
    mozart_16x11_table.json
    source_pages.md
  rust/examples/
    mozart_rules.rs
    musicxml_to_mei_via_verovio.rs

docs/assay/
  260320-musikalisches-research-plan.md
```

其中职责要固定为：

- `docs/study/*`
  - 研究资料与来源基础
- `docs/assay/*`
  - 决策、实施方案、风险与验收稿
- `src/musikalisches`
  - 最终实现入口

### C. data contract draft

下面这一版已经可以作为后续实现的前置契约草案。

#### 1. `index.json`

职责：

- work id
- 标题与归属说明
- witness 级别信息
- generation model
- instrumentation
- 运行时最小元数据

建议字段：

```json
{
  "id": "mozart_dicegame_print_1790s",
  "canonical_witness_id": "rellstab_1790",
  "verification_witness_ids": ["simrock_1793"],
  "title": "Musikalische Wuerfelspiele",
  "catalogue": ["K.Anh.C.30.01", "K.3 Anh. 294d"],
  "date": "ca. 1790 (printed tradition)",
  "instrumentation": "keyboard",
  "generation_model": "columnar_dice_selection",
  "output_positions": 16,
  "selector": {
    "kind": "two_d6_sum",
    "min": 2,
    "max": 12
  }
}
```

#### 2. `rules.json`

职责：

- 明确如何从 selector 映射到 fragment id
- 明确 edition-specific constraints
- 明确可重放校验方式

建议字段扩展：

```json
{
  "work_id": "mozart_dicegame_print_1790s",
  "canonical_witness_id": "rellstab_1790",
  "selector_table_ref": "docs/mozart_16x11_table.json",
  "positions": ["A1","A2","A3","A4","A5","A6","A7","A8","B1","B2","B3","B4","B5","B6","B7","B8"],
  "rolls": [2,3,4,5,6,7,8,9,10,11,12],
  "selection_policy": {
    "one_fragment_per_position": true,
    "concatenate_in_position_order": true
  }
}
```

#### 3. `source_manifest.json`

职责：

- 固定来源链
- 明确 canonical 与 verification witness
- 记录扫描、页码、后续转写责任

建议字段扩展：

```json
{
  "work_id": "mozart_dicegame_print_1790s",
  "canonical_witness": {
    "id": "rellstab_1790",
    "label": "Walzer oder Schleifer",
    "publisher": "Rellstab",
    "date": "ca.1790",
    "role": "canonical"
  },
  "verification_witnesses": [
    {
      "id": "simrock_1793",
      "label": "Walzer oder Schleifer / Englische Contretänze",
      "publisher": "N. Simrock",
      "date": "1793",
      "role": "verification"
    }
  ]
}
```

#### 4. `mother_score.musicxml`

职责：

- 首要 ingest 入口
- 明确小节边界、声部、时值、调号、拍号
- 允许后续做离线规范化

要求：

- 每个可选片段在结构上都能被稳定定位
- 每个小节或片段必须有稳定 id 映射到 fragment number
- 不能依赖人工记忆或“第几页第几行”这种不稳定引用

#### 5. `mother_score.mei`

职责：

- 存档增强层
- 承接 facsimile / revision / scholarly metadata
- 用于长期保存 witness 信息

当前建议：

- 不作为首个运行时解析入口
- 先由 MusicXML ingest 稳定后再与 MEI 对齐

#### 6. future normalized ingest artifacts

虽然现在不写实现，但应提前约定未来会生成：

```text
ingest/
  fragments.json
  measures.json
  witness_diff.json
  validation_report.json
```

建议职责：

- `fragments.json`
  - fragment id -> note events
- `measures.json`
  - measure id -> structural metadata
- `witness_diff.json`
  - canonical 与 verification witness 差异
- `validation_report.json`
  - 数据闭合性与规则一致性报告

### D. transcription and verification workflow

这是后续实施前最重要的“人工 + 机器”协同流程。

#### step 1: lock scan provenance

对 Rellstab 1790 底本，先固定：

- 扫描来源
- 文件标识
- 页码范围
- 页内片段覆盖关系

不完成这一步，不应开始录入 `mother_score.musicxml`。

#### step 2: build fragment identity map

先做一张独立映射表：

```text
fragment_number -> witness page -> staff/system location -> position label
```

目的：

- 避免转写时把 fragment id 直接写死在乐谱编辑器里
- 保留后续复核与替换空间

#### step 3: encode mother score

录入顺序建议：

1. 拍号 / 调号 /小节边界
2. 右手与左手声部
3. 装饰音 / 连线 / 反复与版式相关对象
4. fragment id 标记

要求：

- 先保音高与时值正确
- 再补版式与增强信息

#### step 4: rule reconciliation

将 `mother_score.musicxml` 中的 fragment id 与：

- `mozart_16x11_table.json`
- `rules.json`

做双向核对：

- 从规则表抽样 -> 应能定位到谱面 fragment
- 从谱面 fragment -> 应能回到列位与编号体系

#### step 5: verification witness comparison

再用 Simrock 1793 做复核：

- 如果完全一致：标记 `confirmed`
- 如果存在差异：记入 `witness_diff.json`
- 如果差异影响运行时：
  - 先保持 Rellstab 为 canonical
  - 不要一边实现一边摇摆底本

### E. first runnable milestone definition

既然你已经确认首个里程碑是 `offline realization + offline audio render`，那它的完成标准必须写死。

#### milestone name

`M1: deterministic offline realization`

#### required inputs

- canonical `mother_score.musicxml`
- `rules.json`
- 16 个 selector 值
- 固定 seed 或显式 roll sequence

#### required outputs

- 一份 realized fragment id 序列
- 一份结构化 note event 序列
- 一份离线音频文件
- 一份 validation report

#### success criteria

- 同一组 selector 输入，多次输出完全一致
- realized fragment id 序列与 `16x11` 规则一致
- 导出的离线音频无丢拍、无明显越界时值
- 验证报告能指出缺片段、时值不闭合、无效 selector 等错误

### F. proposed later CLI surface

当前不实现，但后续建议尽量围绕这组命令展开，避免一开始把 CLI 做散：

```text
musikalisches ingest verify --work mozart_dicegame_print_1790s
musikalisches realize --work mozart_dicegame_print_1790s --rolls 2,5,10,...
musikalisches render-audio --work mozart_dicegame_print_1790s --rolls ...
musikalisches render-video --work mozart_dicegame_print_1790s --rolls ...
musikalisches stream --work mozart_dicegame_print_1790s --rtmp ... --stream-key-env YT_KEY
```

设计原则：

- `ingest verify` 必须先于 `realize`
- `render-audio` 必须先于 `render-video`
- `stream` 永远是最后一层 adapter

### G. gate-based execution order

后续进入实施时，建议严格按 gate 推进：

#### gate 0

研究对象冻结：

- Mozart printed tradition
- Rellstab 1790 canonical
- Simrock 1793 verification

#### gate 1

母谱层冻结：

- `mother_score.musicxml` 可核对
- `source_manifest.json` 可追溯
- `rules.json` 与 `16x11` 一致

#### gate 2

规范化 ingest 冻结：

- `fragments.json`
- `validation_report.json`

#### gate 3

离线重放冻结：

- deterministic realization
- offline audio render

#### gate 4

视听联动：

- analyzer
- geometric video

#### gate 5

桥接推流：

- ffmpeg sidecar / subprocess
- env-based stream key

#### gate 6

长稳：

- soak test
- drift check
- restart policy

### H. concrete risks to watch

#### risk 1: work identity drift

最危险的不是技术问题，而是对象又从 `1790s printed tradition` 漂回 `K.516f autograph`。

规避方法：

- 每份后续文档都写 `canonical_witness_id`
- 不再只写 “Mozart dice game”

#### risk 2: placeholder mother score mistaken as final source

当前仓库里的 `mother_score.*` 仍是 placeholder。

规避方法：

- 在真正完成转写前，不把它们作为可运行事实输入

#### risk 3: witness comparison too late

如果 Simrock 1793 的复核拖到实现后期，差异会冲击：

- fragment id
- realization
- golden sample

规避方法：

- 在 `M1` 前完成至少一轮 witness diff

#### risk 4: direct runtime parsing of scholarly formats

直接在运行时解析 MEI/MusicXML，会把：

- 学术表示
- 运行时表示

耦合在一起。

规避方法：

- 先 ingest，后运行

### I. detail level now considered sufficient for implementation prep

到这一版为止，已经足够支撑下一轮进入两种工作之一：

1. 继续修订研究资产
2. 开始制定实施规格

但还不适合直接编码的前提是：

- `mother_score.musicxml` 仍未完成外交式录入
- `source_manifest.json` 仍需提升到 witness 级别
- `validation_report` 仍只是计划中的产物

换句话说，**现在已经足够详细，可以开始“实施准备”；但还不等于可以直接跳过数据工程开始写 Rust。**

## recommended decisions before implementation

### decision 1

请你审核并明确：

- 首个 Mozart 目标到底是
  - `K.516f autograph`
  - 还是 `mozart_dicegame_print_1790s`

这是当前最重要的决策。

### decision 2

如果选 `mozart_dicegame_print_1790s`，请再确认：

- canonical witness 先以哪一个为底本
  - `Rellstab, ca.1790`
  - `N. Simrock, 1793`

我的建议：

- 先选一个底本做主记录
- 另一个只做复核层

不要双底本并行起步。

### decision 3

请你确认首个“可运行里程碑”是不是：

- `offline realization + offline audio render`

而不是：

- 直接进入视频或直播

如果这一步不先锁住，后续“看起来动起来了”的系统很容易建立在未冻结的谱面之上。

## non-goals for this round

本轮不应做：

- 代码实现
- crate 版本钉死
- 推流参数最终值敲定
- SoundFont 最终资产选型
- 长稳压测

本轮只应产出：

- 正确对象定义
- 正确资料链
- 正确实施顺序

## audit reminder

请你重点审核以下两句是否接受：

1. 当前仓库给出的 Mozart 研究资产，实际上更支持“先做 1790s 印刷骰子游戏传统”，而不是“已经可直接做精确 K.516f 实现”。
2. `src/musikalisches/README.md` 现有叙述存在作品传统混线，后续若实施，必须先纠正这层对象定义。

如果你认可这两句，我下一步才适合继续把它收敛成“可实施规格”；如果你不认可，就应先改研究对象，不应进入编码。

# refer.

## A. DuckDuckGo search entry points

以下检索入口用于先定位外部资料；部分查询在自动化环境中可正常返回结果，部分查询会触发 DuckDuckGo anti-bot，后者未作为核心事实依据使用。

- DuckDuckGo Lite: `Musikalisches Würfelspiel K.516f IMSLP`
  - https://lite.duckduckgo.com/lite/?q=Musikalisches+W%C3%BCrfelspiel+K.516f+IMSLP
- DuckDuckGo Lite: `MusicXML site:www.w3.org musicxml`
  - https://lite.duckduckgo.com/lite/?q=MusicXML+site%3Awww.w3.org+musicxml
- DuckDuckGo Lite: `MEI site:music-encoding.org guidelines`
  - https://lite.duckduckgo.com/lite/?q=MEI+site%3Amusic-encoding.org+guidelines

## B. Primary external sources verified

### Mozart / dice-game traditions

- IMSLP: `Musikalisches Würfelspiel, K.516f`
  - https://imslp.org/wiki/Musikalisches_W%C3%BCrfelspiel%2C_K.516f_(Mozart%2C_Wolfgang_Amadeus)
- IMSLP: `Musikalische Würfelspiele, K.Anh.C.30.01`
  - https://imslp.org/wiki/Musikalische_W%C3%BCrfelspiele%2C_K.Anh.C.30.01_%28Mozart%2C_Wolfgang_Amadeus%29
- Wikipedia: `Musikalisches Würfelspiel`
  - https://en.wikipedia.org/wiki/Musikalisches_W%C3%BCrfelspiel

### Music notation formats

- W3C: `MusicXML 4.0`
  - https://www.w3.org/2021/06/musicxml40/
- MEI Guidelines 5.1
  - https://music-encoding.org/guidelines/v5/content/index.html
- Verovio reference: `Encoding formats`
  - https://book.verovio.org/interactive-notation/encoding-formats.html
- Verovio reference: `Input formats`
  - https://book.verovio.org/toolkit-reference/input-formats.html

### C. P. E. Bach source basis

- Bach Digital: `Wq 257 / H 869`
  - https://www.bach-digital.de/receive/BachDigitalWork_work_00010280

## C. Repository internal research assets

- `docs/study/music_dice_games_package/README.md`
- `docs/study/music_dice_games_package/mozart_dicegame_print_1790s/README.md`
- `docs/study/music_dice_games_package/mozart_dicegame_print_1790s/index.json`
- `docs/study/music_dice_games_package/mozart_dicegame_print_1790s/rules.json`
- `docs/study/music_dice_games_package/mozart_dicegame_print_1790s/source_manifest.json`
- `docs/study/music_source_basis_package/README.md`
- `docs/study/music_source_basis_package/docs/source_pages.md`
- `docs/study/music_source_basis_package/docs/mozart_16x11_table.json`
- `docs/study/music_source_basis_package/rust/examples/mozart_rules.rs`
- `docs/study/music_source_basis_package/rust/examples/musicxml_to_mei_via_verovio.rs`
- `src/musikalisches/README.md`

## D. Verification notes

- DuckDuckGo Lite 在本次自动化调研中对部分查询返回了正常结果，对部分查询触发了 anti-bot challenge。
- 本文中的核心事实结论，仅采用：
  - 成功通过 DuckDuckGo 检索定位到的外部来源
  - 或仓库内已存在、可直接检查的研究资料
- 对于未能稳定通过 DuckDuckGo 自动化检索的主题，本报告没有把它们作为决定性事实前提写进实施建议。
- 对 Verovio 的使用建议，本报告仅采用了通过 DuckDuckGo Lite 成功定位到的 Verovio 官方 reference book 页面所支持的结论：
  - Verovio 的 primary notation encoding format 是 MEI
  - Verovio 支持 MusicXML 输入
  - Verovio 可将载入的 MusicXML 转为内部 MEI 并导出
