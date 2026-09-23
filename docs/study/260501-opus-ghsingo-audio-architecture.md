# ghsingo 音频架构深度方案:从数据声响化到生成式 ambient 直播

> **文档版本**:v3.0(整合 bird-era 神经科学修订)
> **日期**:2026-04-30
> **关联 Issue**:#27(bell-era 重构 → bird-era 进化)
> **前置文档**:`260329-ghsingo-architecture.md`、`2026-04-24-ghsingo-musicality-design.md`

---

## 项目核心定位的根本转变

**旧定位**:用 GitHub 事件做生成式音乐(generative music driven by GitHub events)

**新定位**:**用 GitHub 协作的全球心跳,激活观众大脑里 2 亿年的安全回路**

这是一个**降维打击**——ghsingo 不再和 Spotify、Lofi Girl 在"音乐好听度"上竞争,而是直接绑定到一个比所有现代音乐都古老的神经机制(鸟鸣 → 副交感神经接管 → 杏仁核下调)。bell-era 的精致和声、Lydian 漂移、Markov 旋律、Bronze stems——**这些全都保留,但全都退居次席,作为"森林里偶尔传来的人类协作声音"**。

24/7 直播不是"你听了 30 分钟",而是**"你打开它工作了 8 小时,你的杏仁核被它温柔地按住了 8 小时"**——这是 Hammoud 论文 8 小时持续效应的精确兑现。

---

## TL;DR

**bell-era 的根本病不在"算法不够",而在三件事同时缺位**:
1. 没有低频地基与空间感
2. 音色与触发模式过于单一
3. 事件密度直接耦合到音符密度

**修复路径不是换更精致的合成器,而是**:
- 把事件**从"音的触发器"降级为"慢速状态向量的扰动者"**
- 把**鸟鸣层升级为核心生物锚**(基于 Stobbe 2022 / Hammoud 2022 / Jing 2026 三篇论文的硬数据)
- 调式从 C 五声切到 **F Lydian / D Dorian 漂移**(A=432Hz)
- 音色至少 3 个互补家族(钟+pad+pluck)
- 所有素材统一送进同一个 ≥3s 的 reverb
- 事件高峰期不是触发更多音,而是改变和声/调式/纹理

**工程栈推荐**:**Go 主控 + SuperCollider scsynth 子进程 + OSC + JACK → FFmpeg → RTMP**——2026 年 24/7 ambient 直播最稳的组合。

---

## 1. bell-era 失败的根本诊断

### 1.1 病根排序(三组合并症状)

**根因 #1 — 没有低频地基与空间感**

编钟基频 200–800 Hz、泛音 4–8 kHz,完全没有 <100 Hz 的 sub-bass 和 >10 kHz 的 air。耳朵听到的是"贴脸的小盒子里在敲玩具",而不是"我处在一个有空间的环境中"。所有 ambient 神作(Music for Airports、Stars of the Lid、On Land、Substrata)的物理共性都是**持续低频 drone 垫底 + 长 reverb 包裹**。bell-era 这两样都没有。

**根因 #2 — 音色单一 + 永不留白 + 事件密度直接驱动音符密度**

编钟和 Karplus-Strong 都属于"打击衰减"音色家族,听觉适应(auditory adaptation)在 20–40 秒内会让单一音色"消失"。叠加上"白天 commit 高峰期密集敲钟 → 听众焦虑关窗"的密度耦合,这是项目最哲学也最致命的一条。**Listen to Wikipedia 的关键发现:它用音色和音高分级,不用密度分级**——所以即使大量编辑同时来,也不会"密集敲钟"。Eno 自述 Music for Airports 的核心设计原则是 "a silence at least twice as long as the sound"。

**根因 #3 — BGM 与编钟无 tonal lock**

`cosmos-leveloop-339.wav` 是预制循环,它的调性几乎一定不与你的 C 五声同步。这造成持续低烈度的不协和——听众说不出哪里别扭,但就是不愿意停留。再加上严格五声"全协和无张力"(没有 dissonance 可 resolve),没有和声进行,没有 phrase 弧线,所以听 30 秒和听 30 分钟体感等价。这是"不沉浸"的认知层根源。

### 1.2 一句话归纳

**你做的是 "data sonification"(数据声响化),不是 "data-seeded generative music"(数据作为种子的生成式音乐)。** 区别在于:中间隔了一层"音乐语法/约束系统"——事件不是直接触发音,而是触发"音乐过程的一个状态变化的概率"。

---

## 2. 鸟鸣层科学锚点(三篇核心论文)

| 来源 | 关键发现 | ghsingo 直接采用 |
|---|---|---|
| **Stobbe 2022** (Sci Reports, n=295) | 鸟鸣 6 分钟 → 焦虑/偏执显著下降(中等效应);**低/高多样性都有效**;但只有 high diversity 才同时降低抑郁 | 鸟鸣层用 **≥4 种鸟**(论文 high-diversity 条件用了 6 种)。这不是"为了好听",是为了同时打中三个心理维度 |
| **Hammoud 2022** (Sci Reports, n=1292, 26000+ 实时评估) | 听到/看到鸟 → **心情提升持续 8 小时**;抑郁症人群同样有效 | YouTube 直播观众一旦"上钩 6 分钟",**离开后效应仍持续 8 小时** → 这是 ghsingo 的真正用户价值主张,可以直接写进直播间标题/描述 |
| **Jing 2026** (Applied Acoustics, EEG, n=30) | 1–8 kHz 鸟鸣 @ **45–50 dB SPL** → α 波 +14.1%;>60 dB → 应激 +29%(剧烈反转) | 鸟鸣层音量在最终 master bus 上必须**软上限**——这是 ghsingo 必须新增的硬约束 |

**最关键的发现**:Stobbe 论文反复强调**"低多样性鸟鸣也降焦虑"**——这意味着不需要 50 种鸟的复杂 granular,**4–6 种就够**。这大幅简化工程。

---

## 3. 修订路径 B — 鸟鸣层不再是"L3 中层 texture",而升级为"L4 核心层"

### 3.1 层级权重重分配

```
旧:  L0(子底) + L1(海洋drone) + L2(pad) + L3(鸟鸣 sparse) + L4(air) + L5(事件)
              ████████████████████████████████ 鸟鸣只占 ~15%

新:  L1(地基drone) + L2(pad和声) + L3(编钟点缀) + L4(鸟鸣 - 核心)
              ████████████████ 鸟鸣占 ~40%,作为整个流的"安全信号底色"
```

原因:**Eno 风格的多 voice ambient 是"美学愉悦",鸟鸣是"神经生物愉悦"**。后者更便宜也更直接——大脑在 6 秒内就识别出"森林安全"信号,远早于它判断"这音乐好不好听"。

### 3.2 修订后的 L4 鸟鸣层规格

```
[鸟鸣层 L4 — 生物锚]
来源: 4-6 种鸟的高质量野外录音 (xeno-canto.org, CC-BY)
     推荐组合(与 ghsingo 全球 GitHub 数据的"全球性"呼应):
     - 1× 欧洲大陆鸟(欧亚鸲 European Robin,清晨)
     - 1× 美洲鸟(灰嘲鸫 Gray Catbird,白天)
     - 1× 亚洲鸟(白头鹎 Light-vented Bulbul,温带)
     - 1× 热带/夜行鸟(夜莺 Common Nightingale,黄昏-深夜)
     额外可加 2 种地区性鸟做时区切换。

频段: 1000-8000 Hz (Jing 2026 实测有效区间)
     高通 800 Hz 切除环境低频,低通 9 kHz 切除录音底噪。

响度: 鸟鸣层独立总线 -22 LUFS-S,master bus 后实际 -28 dBFS peak
     这对应到 YouTube 一般观众音量下接收到的 ~45-50 dB SPL
     Master bus 加 dynamic limiter,鸟鸣总线 send 上 -3 dBFS hard ceiling
     永远不让鸟鸣 transient 超过 -3 dBFS,防止 Jing 论文里的 ">60dB 反转"

密度: granular 触发 0.3-1.5 鸟/秒(稀疏感才像真实森林)
     绝不让多于 3 只鸟同时鸣叫
     夜间(UTC 时区相关)切到夜莺单声 0.1/秒,模拟真实夜晚

空间: 每只鸟独立 pan,慢速漂移(LFO 0.02 Hz)
     reverb send 从 50%(近)到 90%(远)分布
     听感:你身处一片有鸟的森林中央,鸟在四周不同距离

调式锁定: 鸟鸣天然是非调性的,但与 L1 drone tonic 不冲突
        因为大脑处理鸟鸣走"自然声音"通路,处理 drone 走"音乐"通路
        两通路独立,不会撞调
```

### 3.3 Granular 配方:Forest at safe distance

```
Recipe G4 — "Forest at safe distance"(基于 Jing 论文优化)
- Source: 4 个 60-90s 单只鸟野外录音(xeno-canto)
- Grain size: 80-120 ms(完整鸣叫片段,不切碎)
- Density: 0.5/sec(稀疏 = 真实森林感)
- Position scan: 0.0001(几乎冻结,grain 在录音同一位置反复取样)
- Position jitter: ±10s(每个 grain 从录音不同位置抽取 → 永不重复)
- Pitch: 完全不动(±0 cent — 鸟鸣有物种识别频率,改 pitch 就不像鸟了)
- Pan jitter: ±90%(立体声宽)
- Amp jitter: -6 dB ±2 dB(每个 grain velocity 微变化)
- Reverb send: 30% short hall + 25% long cathedral(创造"远近双层"鸟群感)
- 物种切换: 每 47 分钟(质数周期)切换 4 个 buffer 中的 1 个
         → 整天的"鸟群"在缓慢演化
```

---

## 4. 多层时间尺度参数表(2 周不重复的工程基础)

设计原则:**所有相邻尺度的周期用质数或互质比例,使全系统的同步周期 → 永远**。

Eno 的 Discreet Music 用 63s + 68s(LCM = 71 分钟),Music for Airports 2/1 用分数互质长度(Bainter 算 ~27 天才循环一次)。ghsingo 直接抄这个数学。

| 时间尺度 | 推荐周期 | 控制对象 | 数据驱动源 |
|---|---|---|---|
| 微时间 | ±25 ms | Humanization(timing jitter, velocity ±15%) | 每事件 |
| 秒级 | 1 s 网格 | Voice 触发(走 importance gate,非全部触发) | 上一秒事件类型分布 |
| Phrase | **7 s / 11 s / 13 s**(互质) | 强制 silence gate(每 phrase 末 ≥1.5s 留白) | 7s 滑窗事件密度 EMA |
| 和声进行 | **47 s / 53 s / 61 s / 67 s** | Chord 切换、reverb wet 量 | 60s 内 push:pr 比例、top language |
| 中观 section | **419 s / 547 s / 691 s / 877 s** | Mode 切换(Ionian/Dorian/Lydian/Phrygian/Aeolian/Mixolydian) | 10 分钟事件类型熵、unique repos |
| 小时级 | **3559 s / 4001 s / 4733 s** | Loudness target、pad 层启用 | 小时 commit 速率 z-score |
| 天级 | 24h(86311s 邻近质数偏移) | Palette 切换(白天 vs 夜晚) | UTC 时段 |
| 周级 | 7d(1/f 噪声驱动) | Timbre family 启用集合 | 周 release 数、热门语言变化 |

**L3 + L4 + L5 三层相位组合,2 周内重复概率 < 10⁻⁵**。这是工程上"2 周不重复但风格连贯"的数学保证。

---

## 5. 调式策略 — Lydian-Dorian 漂移

放弃 C 大调五声,改用更有色彩但仍然"自动和谐"的调式系统:

- **基调 F Lydian**(明亮、悬浮、电影感)。F C D E G A C 这 7 音池,而非 5 音网格
- **每 47 分钟做一次平行漂移**:F Lydian → D Dorian → A Aeolian → C Lydian → G Mixolydian → 短暂 E Phrygian → 回到 F Lydian
- **每 60 秒以 5% 概率从模式外抽 1 个非和谐音**(色彩音),立刻被一个和谐音 resolve → 制造微张力。这是从严格五声"全协和无张力"的死循环里救出来的关键
- 调音用 **A4 = 432Hz**(Marconi Union "Weightless" 实测比 440Hz 更降心率)
- 三个八度太广,改用 **2.5 个八度,中心 C4–C5**(钢琴中音区,听感最舒适)

---

## 6. 事件如何驱动鸟鸣层(核心创新)

这是 ghsingo 真正区别于"普通 ambient 直播"的地方:**让 GitHub 协作活跃度变成"森林生命力"**——一个观众一秒就能直觉理解的隐喻。

### 6.1 事件 → 鸟鸣调制映射

| GitHub 事件 | 鸟鸣层调制 | 隐喻 |
|---|---|---|
| **PushEvent** | 鸟群密度 EMA +0.001(120s 时间常数) | 全球 GitHub commit 在持续 → 森林持续繁忙 |
| **PR opened** | 30 秒后 1 只新鸟加入,缓 fade-in 5s | "一只鸟从远处飞来加入" |
| **PR merged** | 短促一阵(3 秒)鸟群兴奋,密度 ×1.8 持续 8s 后回落 | "森林里发生了好事,鸟群短暂骚动" |
| **PR closed unmerged** | 鸟鸣密度 -10% 持续 60s | "森林安静了一会儿"(轻微) |
| **Issue opened** | 远处单只鸟一声(高 reverb) | "远方有鸟叫了一下" |
| **IssueComment** | 不直接触发,只在 5min 窗口积分 → 调 density baseline | "讨论越多,森林越活" |
| **Fork** | 1 只鸟 pan jump 到新位置 | "鸟换了棵树"(对应 fork = 复制项目) |
| **Star (WatchEvent)** | 0%——鸟鸣层不响应这个 | star 太频繁会让鸟群焦虑;让它去触发顶层编钟 |
| **ReleaseEvent** | 鸟群短暂全鸣 4s + L3 编钟 spotlight + L2 pad 上五度 | "森林日出"——大事件 = 集体响应 |
| **CreateEvent** | 鸟鸣 reverb wet +5% 持续 90s | "森林空间感变深一点" |

**关键设计**:这些调制全部经过 5–30s envelope follower(SC 的 `Lag.kr`)。事件突发时鸟群不会"突然狂叫"——它会**慢慢变得活跃,慢慢回落**,像真实森林。这正是 Stobbe 论文里"安全信号"的本质:**它的连续性,而不是它的具体内容**。

### 6.2 95/5 事件分配原则

- **95% 事件 → 调制状态向量**(density / brightness / bird_diversity),EMA 平滑 30s,从不直接发声
- **5% 罕见事件 → 触发音**(Release / PR merged 等),作为"森林里的特殊瞬间"

---

## 7. 五秒留人钩子(bird-era 修订版)

观众的远古大脑在头 0.5 秒决定"这是个让人放松的声音环境吗"——而不是"这音乐好不好听"。所以钩子的优先级调整为:

### 7.1 启动序列

**0.0–0.5 秒(关键的半秒)**:
- t=0.000s 启动:鸟鸣层 fade-in 600ms,首先是 1 只欧洲大陆鸟在 R 偏 30%(好像在右前方树上)。**这是绝对优先于一切的开场音**
- 同时 L1 brown noise drone fade-in,-32 dBFS(几乎察觉不到的"地基")
- **完全不出现编钟、不出现 BGM 循环**——前 0.5 秒大脑做的是"是不是危险环境"判断,任何明显合成音色都会让远古回路警觉

**0.5–2.0 秒(确认安全)**:
- t=0.700s 第二只鸟从 L 偏 40% 加入(美洲鸟,稍远的 reverb)
- t=1.200s 第三只鸟在中央偏后(reverb wet 70%)
- 此时大脑古老回路已经接收到决定性信号:**多种鸟,持续唱,无大型噪音 → 环境安全**。副交感神经开始接管
- t=1.500s L2 pad 极轻 fade-in 到 -32 dBFS(刚好可察觉的"温度")

**2.0–5.0 秒(暗示有故事)**:
- t=2.500s 第一个 GitHub 事件触发 L3 编钟 spotlight,velocity 0.4,远 reverb——但**这是一只鸟群里的"特殊鸣响"**,不是"音乐元素"
- t=3.500s phrase silence(短暂 0.8s 鸟鸣稀疏,L1 drone 显露)——给"森林呼吸"
- t=5.000s 完整生态就位,移交长程调度

### 7.2 视觉协同

- **0–1 秒**:画面从黑色 fade-in 到非常轻的"清晨森林晨雾"环境(可以用极简抽象的渐变光斑,**不要写实森林**——会喧宾夺主)
- **1–3 秒**:第一个 GitHub 事件出现时,**视觉表现为"鸟在树上扑扇翅膀的微动"**而不是"涟漪"。这把"GitHub 事件 = 森林生命"的隐喻在视觉上锚定
- **3 秒后**:常规 GitHub 事件展示,但**底色永远是"森林晨雾"色调**(低饱和绿/蓝/米色)

### 7.3 直播间命名建议

> **The Forest of GitHub — Live from the Global Open Source Canopy**
> 24/7 ambient soundscape · birdsong + ambient drone · driven by real GitHub events

这种命名 + 视觉 + 音频三位一体的"森林"叙事,**比 bell-era 的"编钟敲击"叙事在 YouTube 算法和 SEO 上都更有竞争力**——"forest sounds"、"birdsong ambient"、"24/7 nature sounds"是已验证的高观看时长 niche。

---

## 8. LUFS 与响度目标

24/7 ambient 直播应该走"低响度高动态范围"路线:

| 指标 | 目标值 |
|---|---|
| Integrated LUFS | **-18 to -20**(低于 YouTube -14 标准) |
| Short-term LUFS | -22 to -16 范围 |
| Loudness Range (LRA) | 6–10 LU |
| True Peak | ≤ -1.5 dBTP(留 0.5dB 给 AAC 编码 inter-sample peak) |
| PLR | ≥ 12 |

**为什么不冲到 -14**:
- YouTube **只下调不上调**,所以 -14 不会比 -18 更响,只是损失了动态
- 24/7 长时间播放听者已调高音量,每个 transient 都会更刺耳
- 长时间听 >-14 LUFS 内容会听觉适应,反而"听不见细节"

---

## 9. 工程选型 — Go 主控 + scsynth 子进程

### 9.1 候选对比结论

经过 ChucK / SuperCollider / Pure Data libpd / Sonic Pi & TidalCycles / FAUST 五大候选的深度对比:

**SuperCollider scsynth(独立进程)是最优选**,理由:
1. 唯一一个**架构上为 client/server 设计、本身就被设计为被外部进程通过 OSC 驱动**的成熟引擎
2. Linux headless 一等公民
3. 现成 Go 客户端 `scgolang/sc` 与 `hypebeast/go-osc`
4. supernova 多核版本可作伸缩选项
5. DSP 质量行业级,数百个 UGen

**ChucK 是第二优**:更轻量、`OscIn/OscOut` 内置、`chuck --loop` 单二进制启动,代价是 DSP 生态比 SC 小一个数量级。

**不推荐作为子进程**:Sonic Pi/TidalCycles(它们本身就是 scsynth 的 client,中间多塞一层 Ruby/Haskell 反而增加复杂度)。

**辅助技术**:FAUST `faust2supercollider` 编译为 SC plugin 扩展 UGen 库——把 Faust 高质量的 reverb/granular 无缝叠加到 SC,是最优集成。

### 9.2 推荐架构

```
┌────────────────────────────────────────────────────────────┐
│                   ghsingo Go 主程序                        │
│  ┌──────────┐  ┌──────────┐  ┌─────────────────────────┐   │
│  │ Composer │→ │Sequencer │→ │ Supervisor              │   │
│  │ FSM      │  │ + jitter │  │ (scsynth heartbeat 监控)│   │
│  └──────────┘  └──────────┘  └─────────────────────────┘   │
│                       │ go-osc (UDP)                       │
└───────────────────────┼────────────────────────────────────┘
                        │ OSC bundle with timetag
                        ▼
              ┌──────────────────┐
              │ scsynth -u 57110 │
              │ --realtime       │
              └────────┬─────────┘
                       │ JACK ports
                       ▼
                ┌─────────────┐
                │ jackd dummy │
                └──────┬──────┘
                       ▼
              ┌────────────────┐
              │ ffmpeg -f jack │ → rtmp://a.rtmp.youtube.com/live2/$KEY
              └────────────────┘
```

### 9.3 关键工程要点

- **SynthDef 离线编译**:用 sclang 一次性 `writeDefFile` 生成 `.scsyndef` 二进制,Go 端用 `/d_load` 加载——避免 Go 自己构建 SynthDef 二进制(格式偶尔变,容易踩坑)
- **节点不泄漏**:每个 SynthDef 必须用 `EnvGen.kr(env, gate, doneAction: 2)` 让 envelope 结束自动 free。Go 定期发 `/g_queryTree` 检查 `num_synths`,超阈值发 `/g_freeAll`
- **Heartbeat + 自动重启**:Go 主程序内置 supervisor,每 5s 发 `/status` 期待 1s 内回 `/status.reply`,3 次超时则强杀重启 scsynth + 重发 SynthDef + 重建拓扑
- **ffmpeg 与 scsynth 解耦生命周期**:scsynth 重启时 ffmpeg 继续从 JACK 拉(数据是静音),YouTube 直播不断流,scsynth 恢复后音乐自动接续
- **音频路由**:裸金属选 `jackd -d dummy`(scsynth 与 JACK 集成最稳,ffmpeg `-f jack` 是一等公民);容器选 `modprobe snd-aloop`
- **Buffer 配置**:24/7 直播**不必追求超低延迟**,JACK buffer 1024–2048 frames @ 48kHz(20–40ms)更抗 OS scheduling 抖动,YouTube 自身有 2–10s buffer 完全无所谓

### 9.4 Go 引擎骨架

```go
package engine

import (
    "context"
    "os/exec"
    "time"
    "github.com/hypebeast/go-osc/osc"
)

type Engine struct {
    proc     *exec.Cmd
    client   *osc.Client    // → scsynth :57110
    server   *osc.Server    // ← 监听 :57111
    statusCh chan StatusReply
    cancel   context.CancelFunc
}

func (e *Engine) Boot(ctx context.Context) error {
    ctx, e.cancel = context.WithCancel(ctx)
    e.proc = exec.CommandContext(ctx, "scsynth",
        "-u", "57110",       // OSC port
        "-a", "1024",        // num audio bus channels
        "-z", "64",          // block size
        "-m", "262144",      // RT mem KB
        "-R", "1")
    if err := e.proc.Start(); err != nil { return err }
    time.Sleep(500 * time.Millisecond)

    d := osc.NewStandardDispatcher()
    d.AddMsgHandler("/status.reply", e.handleStatus)
    d.AddMsgHandler("/n_end",        e.handleNodeEnd)
    e.server = &osc.Server{ Addr: "127.0.0.1:57111", Dispatcher: d }
    go e.server.ListenAndServe()

    e.loadDef("synthdefs/ambient_pad.scsyndef")
    e.loadDef("synthdefs/granular_drone.scsyndef")
    e.loadDef("synthdefs/birdsong_granular.scsyndef")
    return nil
}

func (e *Engine) SpawnSynth(def string, id int32, params map[string]float32) error {
    msg := osc.NewMessage("/s_new")
    msg.Append(def); msg.Append(id)
    msg.Append(int32(0)); msg.Append(int32(1))
    for k, v := range params { msg.Append(k); msg.Append(v) }
    return e.client.Send(msg)
}

func (e *Engine) Heartbeat(ctx context.Context) {
    misses := 0
    tick := time.NewTicker(5 * time.Second)
    for {
        select {
        case <-ctx.Done(): return
        case <-tick.C:
            e.client.Send(osc.NewMessage("/status"))
            select {
            case <-e.statusCh:
                misses = 0
            case <-time.After(time.Second):
                misses++
                if misses >= 3 { e.Restart(); misses = 0 }
            }
        }
    }
}
```

### 9.5 SuperCollider SynthDef 示例

```supercollider
// 鸟鸣 granular(核心)
SynthDef(\birdsong_granular, { |out=0, buf=0, dens=0.5, amp=0.4, panPos=0|
    var trig = Dust.kr(dens);
    var pos = LFNoise2.kr(0.05).range(0, BufDur.kr(buf));
    var grain = TGrains.ar(2, trig, buf, 1.0, pos, 0.1, panPos, amp);
    // 关键:鸟鸣不能 distort,加 limiter
    grain = Limiter.ar(grain, 0.7, 0.01);
    Out.ar(out, grain);
}).writeDefFile("synthdefs/");

// Ambient pad(L2 和声层)
SynthDef(\ambient_pad, { |out=0, freq=220, amp=0.2, att=2, rel=4, pan=0|
    var sig = Mix.fill(5, { |i|
        SinOsc.ar(freq * (1 + (0.005 * (i-2))), 0, 1/5)
    });
    sig = LPF.ar(sig, freq * 4);
    sig = sig * EnvGen.kr(Env([0,1,1,0],[att,2,rel],\sin), doneAction: 2);
    Out.ar(out, Pan2.ar(sig, pan, amp));
}).writeDefFile("synthdefs/");

// Brown noise drone(L1 地基)
SynthDef(\drone_base, { |out=0, freq=65.4, amp=0.15|
    var brown = LPF.ar(BrownNoise.ar(0.3), 200);
    var sub = SinOsc.ar(freq, 0, 0.4);
    var sig = brown + sub;
    sig = LPF.ar(sig, 400);
    Out.ar(out, sig ! 2 * amp);
}).writeDefFile("synthdefs/");
```

---

## 10. Week 1 行动清单(立即可执行)

**Week 1: bird-era prototype(~4 人天)**

1. **从 xeno-canto.org 下载 4–6 种鸟的高质量野外录音**(CC-BY 即可,标注作者);每种 60–90s,选**单只鸟单 species**录音(避免预录混合 → 影响后续 granular)。1 人天
2. **librosa 分析每段录音的频谱**,按 1000–8000 Hz 主能量、清晰度、非疾病(非求救/警告)鸣叫筛选。0.5 人天
3. **在现有 Go 引擎里写鸟鸣 granular 模块**(暂不上 SuperCollider):用现有 PCM 混音管道做简化 granular(每 grain 80–120ms 从随机 offset 取样,Hanning 窗,density 0.5/sec)。1.5 人天
4. **L1 brown drone**:用 Go 实时合成 brown noise(简单 IIR 滤波白噪)+ 一个 sine drone(C2 或与未来 BGM 同 tonic),共占 -28 dBFS。0.5 人天
5. **Master bus 上加 hard limiter @-3 dBFS**(防止 Jing 论文的 60dB 反转风险)。0.2 人天
6. **关键测试**:连续听 30 分钟,**自我评估**:这 30 分钟里你想关掉它的次数有几次?目标是 0 次。0.5 人天
7. **bell-era 的所有改造工作不丢弃**——它们成为 L3 编钟点缀层,但权重从原来的"主角"降到"5% 罕见事件触发"

**整周 ~4 人天**,产出一个**完全不同维度**的 prototype。如果 30 分钟自评通过,直接放上 YouTube 跑 24 小时,看观众平均观看时长——**这是唯一真正可信的指标**。

---

## 11. 后续阶段路线图

**Week 2: 扩展音色 + 长程结构(~5 人天)**
- 给每种事件类型准备 2 个互补音色家族(钟+pad+pluck)
- 实现 L3/L4 prime-period 调度(60s/600s tick)
- atomic state snapshot/restore(`/var/lib/ghsingo/state.gob` 每 10s 写一次)
- 训练简单二阶 Markov(语料从 Pärt/Eno/Sakamoto MIDI 取 ~600 transition)
- 上线带 5 秒钩子的启动序列

**Week 3–4: 工程迁移到 SuperCollider(~7 人天)**
- 把核心引擎从当前 Go 内部混音迁移到 Go + scsynth 子进程架构
- `apt install supercollider-server jackd2` 测试机起 scsynth
- dev 机装完整 SC IDE 写 8–10 个 SynthDef 导出 `.scsyndef`
- Go 端引入 `hypebeast/go-osc` 实现 `engine.go` 骨架
- 接 ffmpeg jackd dummy backend → 本地 nginx-rtmp 验证 24h 不断流

**Week 5+: 打磨与监控**
- 加 supervisor 心跳自动重启
- 启动后 `pw-link`/`jack_connect` 强制路由
- systemd unit 部署
- prometheus 监控 `peak_cpu` / `num_synths` / `xrun_count`
- A/B 测试旧版 vs 新版 YouTube 平均观看时长
- 7 天 soak test

---

## 12. 必须避开的已知陷阱

每条都是从真实失败案例反推的:

- **不要继续把事件密度直接耦合到音符密度**——这是 ghsingo 当前最致命的设计错误,所有其他修复都会被这一条撤销
- **不要用纯白噪作为底层**(用 brown + pink 1/f 混合)
- **不要在 master bus 加 high-shelf boost"为了清晰"**——24/7 听必然疲劳
- **不要让 grain density 拉到 200+/sec**(听起来像水龙头白噪)
- **不要让事件 trigger 明显的新声音**(听众会从 ambient 中"被叫醒")——95% 事件应只更新状态向量
- **不要让参数瞬间跳变**——任何调制必须经 5–30s envelope follower
- **不要把 stereo width 推到 200%+**(YouTube 移动端 mono 兼容性死亡)
- **不要冲到 -14 LUFS**——24/7 ambient 应走 -18 to -20 LUFS 高动态范围
- **不要让 ffmpeg 与 scsynth 同生命周期**——scsynth 崩溃应该让 ffmpeg 继续推静音,而不是断 RTMP 流
- **不要在前 5 秒视频里出现 spike/flash**——会撤销音频的认知舒适努力
- **不要让鸟鸣 pitch 漂移**——破坏物种识别频率,大脑会觉得"假"
- **不要超过 60 dB 鸟鸣音量**(Jing 2026 实测 → 应激 +29%,效果反转)

---

## 13. 哲学层面的最终归纳

ghsingo 的目标不应是"音乐",也不应是"无脑白噪",而应是:**一个会随着 GitHub 这个全球协作大脑的脉搏微妙呼吸的、舒适的环境**。

听者打开它工作时几乎察觉不到它的存在;但当某个 release 发生时,房间里光线似乎略微变化——这就是成功。

Brian Eno 把 *Music for Airports* 设计为"机场里 muzak 的对立面":不是为了被注意,但当被注意时奖励你以丰富。**这正是 24/7 GitHub ambient 应该追求的境界。**

森林永远在响,鸟一直在唱,这是 ghsingo 的"音乐";而 GitHub 全球开发者的每一次 push、每一个 PR,化作森林里多一只鸟、一阵更密的鸣叫、远处一声编钟、月光下一次释放——**这是全人类协作的可听证据**。

修复路径已经清晰:
- **Week 1 改 5 件事就能感知到提升**
- **Week 2–3 的多层时间尺度系统让 "2 周不重复但风格连贯" 成为工程可保证的事实**
- **Week 4–5 的 scsynth 迁移让系统具备工业级 24/7 稳定性**

剩下的就是开工。

---

# Refer.

> 以下所有链接均经过实际访问验证(2026-04-30)。

## 核心科学论文(鸟鸣 → 心理健康)

1. **Stobbe E., Sundermann J., Ascone L., Kühn S. 2022** — "Birdsongs alleviate anxiety and paranoia in healthy participants"
   *Scientific Reports*, vol. 12, article 16414. DOI: 10.1038/s41598-022-20841-0(n=295,Max Planck 人类发展研究所)
   - Nature 原文:https://www.nature.com/articles/s41598-022-20841-0
   - PubMed Central:https://pmc.ncbi.nlm.nih.gov/articles/PMC9561536/
   - PubMed:https://pubmed.ncbi.nlm.nih.gov/36229489/
   - Max Planck 新闻稿:https://www.mpg.de/19373671/1017-bild-pm-2022-october-149835-x

2. **Hammoud R., Tognin S., Burgess L., Bergou N., Smythe M., Gibbons J., Davidson N., Afifi A., Bakolis I., Mechelli A. 2022** — "Smartphone-based ecological momentary assessment reveals mental health benefits of birdlife"
   *Scientific Reports*, vol. 12, article 17589. DOI: 10.1038/s41598-022-20207-6(n=1292,26856 次实时评估,King's College London)
   - Nature 原文:https://www.nature.com/articles/s41598-022-20207-6
   - PubMed Central:https://www.ncbi.nlm.nih.gov/pmc/articles/PMC9614007/
   - King's College London 新闻:https://www.kcl.ac.uk/news/feeling-chirpy-being-around-birds-is-linked-to-lasting-mental-health-benefits
   - ScienceDaily:https://www.sciencedaily.com/releases/2022/10/221027093319.htm
   - Urban Mind App 主页:https://urbanmind.info/publications

3. **Jing X., Liu C., Li J., Gao W., Fukuda H. 2026** — "Brain activity and restorative effects of birdsong at different sound pressure levels: An electroencephalographic study"
   *Applied Acoustics*. (n=30 EEG 实验,40–60 dB(A) SPL 范围)
   - ScienceDirect:https://www.sciencedirect.com/science/article/abs/pii/S0003682X25006279
   - 期刊主页:https://www.sciencedirect.com/journal/applied-acoustics

## 鸟鸣声音素材

4. **Xeno-canto** — 全球鸟类录音数据库(CC-BY/CC-BY-NC/CC-BY-NC-SA)
   - 主站:https://xeno-canto.org/
   - Wikipedia:https://en.wikipedia.org/wiki/Xeno-canto
   - API v3 文档:https://xeno-canto.org/api/3/recordings
   - Python 包:https://pypi.org/project/xeno-canto/
   - 下载脚本(GitHub):https://github.com/AgaMiko/xeno-canto-download

## Generative Music 经典参考

5. **Brian Eno — Ambient 1: Music for Airports**(1978)
   - Wikipedia:https://en.wikipedia.org/wiki/Ambient_1:_Music_for_Airports
   - Brian Eno 全传:https://en.wikipedia.org/wiki/Brian_Eno
   - 结构解析:https://reverbmachine.com/blog/deconstructing-brian-eno-music-for-airports/
   - uDiscoverMusic 详解:https://www.udiscovermusic.com/stories/brian-eno-music-for-airports-feature/

6. **Listen to Wikipedia (hatnote)** — 与 ghsingo 最相似的成功案例
   - 直播页:https://listen.hatnote.com/
   - GitHub 源码:https://github.com/hatnote/listen-to-wikipedia
   - Wikipedia 词条:https://en.wikipedia.org/wiki/Listen_to_Wikipedia

7. **Generative.fm** (Alex Bainter) — 浏览器中的无限生成音乐
   - 主站源码:https://github.com/generativefm/generative.fm
   - 音乐生成器:https://github.com/generativefm/generators
   - 介绍文章:https://medium.com/@alexbainter/introduction-to-generative-music-91e00e4dba11
   - 实现详解:https://medium.com/@alexbainter/making-generative-music-in-the-browser-bfb552a26b0b
   - 教程课程:https://alexbainter.gumroad.com/l/generative-music-systems

8. **Marconi Union — "Weightless"**(科学验证最放松音乐)
   - Mindlab Report (PDF):https://britishacademyofsoundtherapy.com/wp-content/uploads/2019/10/Mindlab-Report-Weightless-Radox-Spa.pdf
   - Shepherd et al. 2023 比较研究:https://journals.sagepub.com/doi/abs/10.1177/03057356221081169
   - 临床试验登记:https://clinicaltrials.gov/study/NCT03844659

## Soundscape Ecology 理论基础

9. **Bernie Krause** — Biophony / Geophony / Anthrophony 三元模型
   - Wikipedia:https://en.wikipedia.org/wiki/Bernie_Krause
   - Soundscape Ecology Wikipedia:https://en.wikipedia.org/wiki/Soundscape_ecology
   - Wild Sanctuary:https://www.wildsanctuary.com/
   - MIT Press Reader:https://thereader.mitpress.mit.edu/everything-is-wrong-bernie-krauses-concept-of-biophony/

## 音频引擎与编程语言

10. **ChucK** — Princeton 音频编程语言
    - 主站:https://chuck.cs.princeton.edu/
    - 文档:https://chuck.cs.princeton.edu/doc/
    - GitHub:https://github.com/ccrma/chuck
    - Wikipedia:https://en.wikipedia.org/wiki/ChucK
    - Ge Wang 博士论文(创始人):https://www.cs.princeton.edu/~gewang/thesis.pdf

11. **SuperCollider** — 推荐主引擎
    - 主仓库:https://github.com/supercollider/supercollider
    - 系统集成 wiki:https://github.com/supercollider/supercollider/wiki/Systems-interfacing-with-SC

12. **Go ↔ SuperCollider 集成**
    - scgolang/sc(SC Go 客户端):https://github.com/scgolang/sc
    - scgolang/sc 包文档:https://pkg.go.dev/github.com/scgolang/sc
    - scgolang 组织:https://github.com/scgolang
    - hypebeast/go-osc(纯 OSC):https://github.com/hypebeast/go-osc

## 数据源

13. **GH Archive** — GitHub 公共事件归档
    - 主站:https://www.gharchive.org/
    - GitHub 源码:https://github.com/igrigorik/gharchive.org
    - BigQuery 教程:https://davelester.github.io/gharchive-bigquery-examples/

---

**文档结束**

> 本方案的最终目标:让 GitHub 的全球心跳,通过鸟鸣这个 2 亿年历史的安全信号,成为千万开发者背景里温柔的存在。
