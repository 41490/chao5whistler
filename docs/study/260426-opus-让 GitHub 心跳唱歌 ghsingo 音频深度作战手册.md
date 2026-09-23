# 让 GitHub 心跳唱歌:ghsingo 音频深度作战手册

**TL;DR — 你做的不是 generative music,是 data sonification。** bell-era 的根本病不在"算法不够",而在三件事同时缺位:**没有低频地基与空间感,音色与触发模式过于单一,事件密度直接耦合到音符密度**。修复路径不是换更精致的合成器,而是把事件**从"音的触发器"降级为"慢速状态向量的扰动者"**,在它上面盖一层 Eno-Bainter 风格的多 voice 多 loop 架构;调式从 C 五声切到 **F Lydian / D Dorian 漂移**(A=432Hz);音色至少 3 个互补家族(钟+pad+pluck);所有素材统一送进同一个 ≥3s 的 reverb;事件高峰期不是触发更多音,而是改变和声/调式/纹理。工程上,**Go 主控 + SuperCollider scsynth 子进程 + OSC + JACK → FFmpeg → RTMP** 是 2026 年 24/7 ambient 直播最稳的组合,有 [beats.softwaresoftware.dev](https://beats.softwaresoftware.dev) 这个近邻案例提供踩坑路径。下文给出可立即落地的完整方案、参数表、代码骨架。

---

## 1. bell-era 失败的根本诊断

### 1.1 病根排序

排除"细枝末节"后,真正的致命问题只有三组,每组都是多个症状的合并表现:

**根因 #1 — 没有低频地基与空间感(B2 + C3 + D1 三合一)。** 编钟基频 200–800 Hz、泛音 4–8 kHz,完全没有 <100 Hz 的 sub-bass 和 >10 kHz 的 air。耳朵听到的是"贴脸的小盒子里在敲玩具",而不是"我处在一个有空间的环境中"。所有 ambient 神作(Music for Airports、Stars of the Lid、On Land、Substrata)的物理共性都是**持续低频 drone 垫底 + 长 reverb 包裹**。bell-era 这两样都没有。

**根因 #2 — 音色单一 + 永不留白 + 事件密度直接驱动音符密度(B1 + A3 + E1 三合一)。** 编钟和 Karplus-Strong 都属于"打击衰减"音色家族,听觉适应(auditory adaptation)在 20–40 秒内会让单一音色"消失"。叠加上"白天 commit 高峰期密集敲钟 → 听众焦虑关窗"的密度耦合,这是项目最哲学也最致命的一条。**Listen to Wikipedia 的关键发现:它用音色和音高分级,不用密度分级**——所以即使大量编辑同时来,也不会"密集敲钟"。Eno 自述 Music for Airports 的核心设计原则是 *"a silence at least twice as long as the sound"*。

**根因 #3 — BGM 与编钟无 tonal lock(C4 + C2 + A4)。** `cosmos-leveloop-339.wav` 是预制循环,它的调性几乎一定不与你的 C 五声同步,即使粗听都是"大调感"。这造成持续低烈度的不协和——听众说不出哪里别扭,但就是不愿意停留。再加上严格五声"全协和无张力"(没有 dissonance 可 resolve),没有和声进行,没有 phrase 弧线,所以听 30 秒和听 30 分钟体感等价。这是"不沉浸"的认知层根源。

次要问题(humanization 缺失、八度 voicing 撞车、stereo 全 mono、ducking 缺失)都从属于上述三条,修好主因后会自动改善大半。

### 1.2 一句话归纳

**你做的是"data sonification"(数据声响化),不是"data‑seeded generative music"(数据作为种子的生成式音乐)。** 区别在于:中间隔了一层"音乐语法/约束系统"——事件不是直接触发音,而是触发"音乐过程的一个状态变化的概率"。

---

## 2. 路径 A — 算法作曲方案(可听性优先)

### 2.1 核心范式转变

把 GitHub 事件**从"音的触发器"降级为"多个慢速状态向量的轻微扰动者"**。具体说:不要让 PushEvent 直接 trigger 一个钟声,而是让它把一个"和声密度"参数 +0.02、把一个"高频亮度"参数 +0.005,这些参数随后被独立运行的 voice 系统(Eno 风格的多 loop 衰减层)读取。事件密度激增时,**正确的响应是 SUBTRACT 而非 ADD**——这正是 Xenakis 在 Achorripsis 中用 Poisson λ=0.6 稀疏分布、而不是堆叠音符的洞察。

### 2.2 多层时间尺度参数表(2 周不重复的工程基础)

设计原则:**所有相邻尺度的周期用质数或互质比例,使全系统的同步周期 → 永远**。Eno 的 Discreet Music 用 63s + 68s(LCM = 71 分钟),Music for Airports 2/1 用分数互质长度(Bainter 算 ~27 天才循环一次)。ghsingo 直接抄这个数学:

| 时间尺度 | 推荐周期 | 控制对象 | 数据驱动源 |
|---|---|---|---|
| 微时间 | ±25 ms | Humanization(timing jitter, velocity ±15%) | 每事件 |
| 秒级 | 1 s 网格 | Voice 触发(走 importance gate,非全部触发) | 上一秒事件类型分布 |
| Phrase | **7 s / 11 s / 13 s**(互质) | 强制 silence gate(每 phrase 末 ≥1.5s 留白) | 7s 滑窗事件密度 EMA |
| 和声进行 | **47 s / 53 s / 61 s / 67 s** | Chord 切换、reverb wet 量 | 60s 内 push:pr 比例、top language |
| 中观 section | **419 s / 547 s / 691 s / 877 s** | Mode 切换(Ionian/Dorian/Lydian/Phrygian/Aeolian/Mixolydian) | 10 分钟事件类型熵、unique repos |
| 小时级 | **3559 s / 4001 s / 4733 s** | Loudness target、pad 层启用 | 小时 commit 速率 z-score |
| 天级 | 24 h(86311s 邻近质数偏移) | Palette 切换(白天 vs 夜晚) | UTC 时段 |
| 周级 | 7 d(1/f 噪声驱动) | Timbre family 启用集合 | 周 release 数、热门语言变化 |

L3 + L4 + L5 三层相位组合,**2 周内重复概率 < 10⁻⁵**。这就是工程上"2 周不重复但风格连贯"的数学保证。

### 2.3 调式策略 — Lydian-Dorian 漂移

放弃 C 大调五声,改用更有色彩但仍然"自动和谐"的调式系统:

- **基调 F Lydian**(明亮、悬浮、电影感)。F C D E G A C 这 7 音池,而非 5 音网格。
- **每 47 分钟做一次平行漂移**,序列:F Lydian → D Dorian → A Aeolian → C Lydian → G Mixolydian → 短暂 E Phrygian → 回到 F Lydian。
- **每 60 秒以 5% 概率从模式外抽 1 个非和谐音**(色彩音),立刻被一个和谐音 resolve → 制造微张力。这是从严格五声"全协和无张力"的死循环里救出来的关键。
- 调音用 **A4 = 432Hz**(Marconi Union "Weightless" 实测比 440Hz 更降心率)。
- 三个八度太广,改用 **2.5 个八度,中心 C4–C5**(钢琴中音区,听感最舒适)。

### 2.4 推荐架构 — Bronze-style stems + reactive crossfade(配方 C)

这是把 Brian Eno 的多 loop 衰减、Sigur Rós Liminal 的 stems 重组、Generative.fm 的多 voice 分布三家合成的最稳方案,最适合 ghsingo 因为**流稳定,绝不会出"杂乱无章"**——所有内容都来自精心预制的和声相容素材。

预录制 8 个 stems(每个 ~120 秒,全部互相和声相容):bass_drone_F、pad_chord_F_lyd、pad_chord_D_dor、bell_arpeggio_high、pluck_sparse_mid、vocal_pad_oo、field_recording_rain (very low)、field_recording_room_tone。每个 stem 有 2 个独立循环锚点(loop length 是质数),互相错位。

```pseudo
state = {
  density_target: 0.3,    // 0=只有 bass 一层, 1=全部 8 层
  brightness_target: 0.5, // filter cutoff
  bpm: 60                 // 极慢漂移,Weightless 模式
}

每秒:
  // EMA 平滑驱动,绝不直接驱动
  state.density_target = 0.7 * state.density_target + 0.3 * (event_density_60s / 50)
  state.brightness_target = 0.7 * old + 0.3 * event_type_entropy

  // stem ranking
  for i, stem in stems:
    stem.target_gain = max(0, density - i*0.125) * stem.activation_curve(t)
    crossfade(stem.gain, stem.target_gain, smoothing=0.05)

  // 全局滤波
  master_filter.cutoff = lerp(800Hz, 8kHz, brightness_target)

  // 每 47 分钟切换 stems 集合
  if t % (47*60) == 0: swap to next stems_set

每事件:
  rare (probability = 5%):
    trigger spotlight pluck/bell sample (这是唯一直接事件→音的路径)
```

**这就完成了"事件密度高时不堆音符,而是改变 texture"的核心目标。** 95% 的事件根本不直接发声,只是缓慢地更新两个状态变量;5% 的"幸运事件"作为偶发亮点出现。

### 2.5 算法范式选型矩阵

| 范式 | 适用层 | 关键作用 |
|---|---|---|
| Variable-Order Markov(预训练 Eno+Pärt+Sakamoto MIDI) | 旋律层(L1) | 保证风格连贯;temperature = f(event_density) |
| L-system | 结构层(L2 phrase) | self-similar,生成 phrase 骨架 |
| Cellular Automata Rule 110 | 节奏点状层 | "复杂类",既有规律又有混沌;比 Rule 30 更音乐 |
| HMM(隐藏状态=intro/build/peak/calm) | 中观叙事(L4) | 解决"无叙事弧"问题 |
| Stems crossfade(Bronze 模式) | 全局 texture | 流稳定的兜底 |

推荐**先实现 Bronze stems + 简单状态机**(2 周可上线),Markov 旋律层作为**第二阶段**增强(预训练语料从 Pärt 的 *Spiegel im Spiegel*、Nujabes、Eno *Discreet Music* 各取 ~200 个 pitch transition)。

### 2.6 Listen to Wikipedia 的关键启示(不能错过)

这是与 ghsingo 最像的成功案例,反推它的源代码后发现几个**反直觉但正确**的设计:

第一,**音高反比于事件大小**——大编辑 = 低音,小编辑 = 高音。这违反了"大事件=大音"的直觉,但听感更稳定:大事件是少数,落在低频区给整体作 bass 背景;小事件落在高频如 sparkle。第二,**三个互补音色家族**(celesta=添加,clavichord=删除,string swell=新用户)而不是同一个金属编钟分级。第三,**没有 BGM 循环层**——靠 reverb tail 长 + 触发频率密集,在听者大脑里"积分"成连续氛围。bell-era 加 BGM 反而让点状声音变成"前景上的杂音"(这点 ghsingo 需要重新评估:要么改造 BGM 让它真正是低频 drone,要么去掉)。第四,**no metric grid**——没有 60bpm,事件来一个就触发一个,加 note_overlap 做音重叠管理。

---

## 3. 路径 B — 有机 Soundscape 方案

### 3.1 修复"森林+海洋+宇宙叠加难听"的 12 步

这套步骤直接解决用户当前最痛的问题,可在不换工具的前提下立刻执行:

1. **不要混 3 个完整 soundscape,只挑出每个的"频谱签名"。** 海洋只取 50–300Hz 低吼(LPF @300Hz);森林只取 2–8kHz 的鸟/叶 sibilant(HPF @1.5kHz + LPF @10kHz);宇宙只取 200–1200Hz 的中段嗡鸣 drone。让它们**频段不重叠**——这是 Bernie Krause 的 Acoustic Niche 假说在生产工程上的应用。
2. **每层独立 mono-fy 后再人为立体化**,避免三个 stereo 中央扩散源相位冲突。
3. **每层独立做 -12 LUFS 短期电平归一化**,然后再统一缩到混音 -28 LUFS。
4. **空间分层**:海洋 → mono center 几乎无 reverb;宇宙 → 立体宽 100% + 短 reverb (1.5s);森林鸟 → 立体定位每只不同 pan + 长 reverb (8s+),放最远。
5. **统一 IR(Lustmord 法门,关键中的关键)**:在 master ambient bus 挂一个 convolution reverb,所有源送 20–30% wet。整个 mix 听起来"在同一个真实大空间里"——这是把 3 个不同生态变成 1 个统一生态的最有效手段。推荐 IR:cathedral / large concert hall / small canyon。
6. **Phase 修复**(用 Voxengo PHA-979 检查 stereo phase correlation,100–500Hz 应 >0.3)。
7. **Sidechain ducking 替代 EQ 切割**:森林鸟出现时海洋低吼自动 -2dB,听感是"鸟来时一切让位"——如自然界。
8. **Dynamic EQ 修 masking**(1–4kHz 区被其他层 talking 时主动 -3dB)。
9. **Detuning trick**:把"宇宙嗡鸣"做成两副本,+5 cent 与 -5 cent。原本平直的 drone 立刻"活"过来——Sarah Davachi / Stars of the Lid 常用手段。
10. **Slow LFO automation**(每层 volume/pan/filter 被 0.005–0.05Hz 慢 LFO 调制,3 层用质数比 0.0123 / 0.0179 / 0.0301 Hz 避免周期重合)。
11. **加 noise floor unify**(master 加极轻 vinyl crackle / brown noise 在 -44dB,给统一接地——Burial / The Caretaker 的关键技巧)。
12. **最终 Master EQ**:high-shelf -3dB @ 8kHz(柔化),low-shelf +1.5dB @ 80Hz(温暖),wide bell -1dB @ 2.5kHz(避免疲劳)。

### 3.2 频谱分层(Bernie Krause 三层模型重映射)

| 层 | Krause 类别 | 频段 | 推荐源 | 角色 |
|---|---|---|---|---|
| L0 子底 | (亚-Geophony) | 20–60 Hz | 合成 brown noise + 低频 sine drone | 房间感 |
| L1 Geophony | 风/海/雷 | 60–400 Hz | 海洋/瀑布远雷采样,重 LPF + slow granulate | 永不停的"地形" |
| L2 中低 pad | Synthesis | 200–1200 Hz | 合成器 pad(triangle/square 微叠) | 和声温度 |
| L3 Biophony | 鸟/虫 | 1.5–8 kHz | 鸟鸣/虫鸣,稀疏 granular(0.5–2/s) | 中层 texture |
| L4 air | Geophony | 8–16 kHz | pink-filtered noise + bell shimmer | 空间高度 |
| L5 Anthrophony | 事件 | 自由 | **GitHub 事件**触发的微脉冲(铃铛/铜碗/水滴) | "有人在,但很远" |

任何两层在重叠频段的能量差应 ≥ 6 dB。**绝对不要用纯 white noise 作为底层**——人耳 A-weighting 在 ~3kHz 最敏感,白噪能量集中在那里就是刺耳源。底层用 brown(<200Hz)+ pink(200Hz–4kHz)+ 极轻 pink shelf(>4kHz)的"加强版 1/f"配方。

### 3.3 Granular Synthesis 推荐参数(三个可立即复用的配方)

**Recipe G1 — Forest-cloud(从 30s 鸟鸣 → 无限不重复鸟鸣)**:grain size 45ms, density 8/s(稀疏!),position jitter ±5000ms,position drift 0.001,pitch jitter ±15c,pan jitter ±70%,3 个 pitch-stacked layer(-7 / 0 / +5 半音),Hanning 窗,40% 送长 hall reverb。

**Recipe G2 — Ocean-drone(从 10s 海浪 → 永恒低频 drone)**:grain size 200ms, density 30/s(overlap),position jitter ±300ms,pitch -12 八度,pitch jitter ±3c,pan jitter ±20%,LPF @400Hz Q=0.2。

**Recipe G3 — Cosmos-pad(从 5s synth 嗡鸣 → 无限 evolving pad)**:grain size 80ms, density 50/s,position jitter ±2000ms,position scan 0.0008(near-frozen),5 个 pitch-stacked(-12/-7/0/+12/+19),pan ±100%,70% 送 Valhalla Supermassive Andromeda mode (feedback 95%)。

工具推荐:SuperCollider 的 `GrainBuf` / `TGrains` / `Warp1`(后端首选)、Csound `partikkel`、Ableton Granulator II(M4L 免费快速原型)、PaulStretch(把任意 source 拉伸到 50× 速度生成 raw drone material 的最暴力有效方法)。

### 3.4 事件→Modulation 映射表(核心设计)

**关键洞察:不要让事件触发新声音,让事件调制现有连续 drone 的参数。** 每个事件映射到一个缓慢 envelope 调制(典型 30s–10min),事件越频繁效果越微弱(防疲劳累积):

| 事件类型 | 调制目标 | 调制方式 | 时间常数 | 听感 |
|---|---|---|---|---|
| **PushEvent** | L2 pad filter cutoff | +200Hz envelope | 35s | 云开了一缝阳光 |
| **PR opened** | L3 鸟鸣 granular density | density × 1.5 持续 2min | 120s | 一只新鸟加入 |
| **PR merged** | L4 air shimmer reverb feedback | +5% 持续 3min | 180s | 高频 air 亮起来 |
| **PR closed unmerged** | L1 ocean drone LPF | -100Hz 持续 1min | 60s | 低频沉下去一点 |
| **Issue opened** | L3 远处虫鸣 amplitude | +3dB 短脉冲 | 60s | 远处一声轻响 |
| **IssueComment** | L5 base density(5min 窗口积分) | 调 density | 5min | 越多评论 → 越多远处风铃 |
| **Fork** | L3 鸟鸣 pan position | jump to random,缓慢回中 | 60s | 鸟从一棵树飞到另一棵 |
| **WatchEvent (star)** | L4 single bell + 12s shimmer | one-shot | 12s | 偶尔一声远铃 |
| **Create branch/tag** | L2 pad detune 量 | +3 cent 持续 90s | 90s | 和声更"宽"一点 |
| **ReleaseEvent** | L4 shimmer freeze 30s + L2 pad +5度 | 大事件 | 30–60s | 像日出/钟声/仪式 |

**关键原则**:每个调制路径终端必须有 5–30s 的 envelope follower(SC 的 `Lag.kr`),**永远不要让参数瞬间跳变**;同事件类型 cooldown 30s 内不重新启动 envelope 只增强现有值;数值用对数压缩 `log(1+count)*scale` 防止 burst。

### 3.5 LUFS 与响度目标

24/7 ambient 直播应该走"低响度高动态范围"路线(参考 Biosphere、Hiroshi Yoshimura),**反直觉但正确**:

| 指标 | 目标值 |
|---|---|
| Integrated LUFS | **-18 to -20**(低于 YouTube -14 标准) |
| Short-term LUFS | -22 to -16 范围 |
| Loudness Range (LRA) | 6–10 LU |
| True Peak | ≤ -1.5 dBTP(留 0.5dB 给 AAC 编码 inter-sample peak) |
| PLR | ≥ 12 |

为什么不要冲到 -14:YouTube **只下调不上调**,所以 -14 不会比 -18 更响,只是损失了动态;24/7 长时间播放听者已调高音量,每个 transient 都会更刺耳;长时间听 >-14 LUFS 内容会听觉适应,反而"听不见细节"。

---

## 4. 混合方案(强烈推荐)

**这是 Brian Eno、Marconi Union、Stars of the Lid、Generative.fm 的共同做法,也是 ghsingo 应当采用的最终架构:** 路径 B 的有机 ambient drone 作为永不停止的底层(占据 70% 听感),路径 A 的稀疏旋律事件作为偶发亮点(占据 5–10% 听感),BGM 退化为可选的中频纹理填充(占据 20%)。

```
┌─────────────────────────────────────────┐
│ 路径 A 顶层(稀疏 melodic events,5–10%)│  ← bell/pluck samples,5% 概率触发
├─────────────────────────────────────────┤
│ 路径 A 中层(stems crossfade,20%)      │  ← Bronze-style 8 stems,事件驱动 crossfade
├─────────────────────────────────────────┤
│ 路径 B 中层(granular pad/biophony,30%)│  ← Recipe G1/G2/G3 之一
├─────────────────────────────────────────┤
│ 路径 B 底层(drone + brown/pink,40%)   │  ← 永不停的 sub-bass 地基
└─────────────────────────────────────────┘
       ▲ 全部送一个统一 IR reverb(Lustmord 法门)
```

**事件分配原则**:常见事件(IssueComment、Push)只更新底层和中层的状态向量,不直接发声;罕见事件(Release、PR merged)以 5% 概率触发顶层"亮点"。这同时解决了"密度焦虑"和"音乐感缺失"两个问题——底层永远连续舒适,顶层偶尔有"音乐性"瞬间。

---

## 5. 五秒钩子 — 直播间留人策略

### 5.1 留人门槛的硬性事实

Spotify 数据显示**前 5 秒内跳过率 24.14%,前 30 秒 35.05%**;YouTube 24/7 直播首 60 秒掉 55% 观众,8 秒决策窗。Lofi Girl、Listen to Wikipedia 这类成功流的 5 秒里**同时具备**:明确 tonal center、低频地基、慢变 surface + 小颗粒变化、可一秒识别的视觉品牌、暗示"再听 30 秒会更好"的 promise。bell-era 现状这五条只满足 1.5 条。

### 5.2 ghsingo 启动序列(假设 master tonic 锁在 D)

**0.0–1.0 秒 — 地基立刻铺开**:t=0.000s 同时启动四件事:Drone A(D2 sine 73.42Hz, fade-in 600ms, -22 dBFS, L/R 等量)、Drone B(A2 五度 110.00Hz, fade-in 800ms, -25 dBFS, 稍 R +12% pan 防 mono)、BGM(从循环点 fade-in 1.2s, -18 dBFS, HPF @200Hz)、Vinyl noise floor(-38 dBFS 立刻入,贯穿全程,潜意识"品牌签名")。t=0.700s 第一个 D4 (293.66Hz) tubular bell, velocity 0.6, reverb wet 50%, pan center——这是"明确告诉听众我们是 D 调"的关键音。这 1 秒人耳已接收到:**调性 ✓ 低频地基 ✓ 空间感 ✓ 品牌噪声 ✓ 编钟标志音色 ✓**,所有"立即关窗"因素被规避(无刺耳频段、无突兀响度、无未解决张力)。

**1.0–3.0 秒 — 建立可预测性 + 第一次小惊喜**:开始让真实 GitHub 事件流入,但每秒最多 1 个 voice。t=1.500s F#4 (369.99Hz) 从一个事件触发(F# 是 D 大三度,确认明亮模式);t=2.000s 留白只有 drone+BGM(让听众感受空间);t=2.500s A4 (440Hz) velocity 0.5 L pan -20%(空间扩展信号);t=2.800s high pad layer(D5 sine + soft saw, attack 1.5s)开始很轻 fade-in 目标 -28 dBFS(暗示"还有更多层在后面")。

**3.0–5.0 秒 — 暗示长程结构**:t=3.000s **第一个明显 phrase 边界**——所有事件触发暂停 800ms,只剩 drone+pad+BGM(留白告诉听众"这音乐有呼吸,不是连续轰炸");t=3.800s 第二轮事件流入,音色与第一轮**不完全一样**(暗示 variety);t=4.500s high pad 完全到位 -22 dBFS,4 个层叠加;t=5.000s 移交给长程多层调度。

**5 秒后**:L1/L2 完全接管,60 秒处 L3 第一次更新 reverb wet/palette,600 秒处 L4 第一次切 mode。

### 5.3 持续留人的"周期性 sting"

YouTube 直播观众进入时间不一致,**整个流必须每 30–60 秒就有一次"hook 重启"**——一个轻微 piano motif 或 bell sting,让任何时刻点进来的人都能在 30 秒内得到一次"这是什么"的清晰感。这是 podcast 行业的成熟经验,在 Lofi Girl 直播间也以"每曲 2–4 分钟切换"形式存在。

### 5.4 视觉协同(0–5 秒)

视频 0.0–1.0s 从黑色 fade-in 到主场景,中央显示慢呼吸 logo(scale 0.95→1.0 周期 4s,与 drone fade-in 同步);1.0–3.0s 第一个 GitHub 事件以柔和涟漪出现(类 Listen to Wikipedia 圆圈但更柔和),事件名小字浮现,**视觉 0.05s 后于音频**(给大脑"先听到才看到"的自然顺序);3.0–5.0s 涟漪累积,视觉留白对应音频 phrase 边界。**绝对不要在前 5 秒出现 spike/flash/突然颜色变化**,否则覆盖音频的认知舒适努力。

---

## 6. 工程选型 — Go 主控 + 音频引擎子进程

### 6.1 候选对比结论

经过 ChucK / SuperCollider / Pure Data libpd / Sonic Pi & TidalCycles / FAUST 五大候选的深度对比,得出结论:

**SuperCollider scsynth(独立进程)是最优选**,理由:(1) 唯一一个**架构上为 client/server 设计、本身就被设计为被外部进程通过 OSC 驱动**的成熟引擎(scsynth 完全不知道 sclang 是谁);(2) Linux headless 一等公民;(3) 现成 Go 客户端 `scgolang/sc` 与 `hypebeast/go-osc`;(4) 已有近邻 24/7 案例 [beats.softwaresoftware.dev](https://beats.softwaresoftware.dev)(LLM + scsynth + PipeWire null sink + parec + ffmpeg HTTP MP3);(5) supernova 多核版本可作伸缩选项;(6) DSP 质量行业级,数百个 UGen。

**ChucK 是第二优**(更轻量、`OscIn/OscOut` 内置、`chuck --loop` 单二进制启动),代价是 DSP 生态比 SC 小一个数量级,无社区级 24/7 案例,VM 字节码解释执行单核效率明显低于 scsynth。

**不推荐作为子进程**:Sonic Pi/TidalCycles(它们本身就是 scsynth 的 client,你只是中间多塞一层 Ruby/Haskell);Heavy/Enzien 已停止维护。

**辅助技术**:FAUST `faust2supercollider` 编译为 SC plugin 扩展 UGen 库——把 Faust 高质量的 reverb/granular 无缝叠加到 SC,是最优集成。

### 6.2 推荐的最终架构

```
┌────────────────────────────────────────────────────────────┐
│                   ghsingo Go 主程序                         │
│  ┌──────────┐  ┌──────────┐  ┌─────────────────────────┐  │
│  │ Composer │→ │Sequencer │→ │ Supervisor              │  │
│  │ FSM      │  │ + jitter │  │ (scsynth heartbeat 监控)│  │
│  └──────────┘  └──────────┘  └─────────────────────────┘  │
│                       │ go-osc (UDP)                       │
└───────────────────────┼────────────────────────────────────┘
                        │ OSC bundle with timetag
                        ▼
              ┌──────────────────┐
              │ scsynth -u 57110 │
              │ --realtime       │   ← 子进程,Go 用 exec.CommandContext 管理
              └────────┬─────────┘
                       │ JACK ports (or ALSA loopback in containers)
                       ▼
                ┌─────────────┐
                │ jackd dummy │   ← 无声卡也行
                └──────┬──────┘
                       ▼
              ┌────────────────┐
              │ ffmpeg -f jack │ → rtmp://a.rtmp.youtube.com/live2/$KEY
              └────────────────┘
```

**关键工程要点**:

- **SynthDef 离线编译**:用 sclang 一次性 `writeDefFile` 生成 `.scsyndef` 二进制,Go 端用 `/d_load` 加载——避免 Go 自己构建 SynthDef 二进制(格式偶尔变,容易踩坑)。
- **节点不泄漏**:每个 SynthDef 必须用 `EnvGen.kr(env, gate, doneAction: 2)` 让 envelope 结束自动 free。Go 定期发 `/g_queryTree` 检查 `num_synths`,超阈值发 `/g_freeAll`。
- **Heartbeat + 自动重启**:Go 主程序内置 supervisor,每 5s 发 `/status` 期待 1s 内回 `/status.reply`,3 次超时则强杀重启 scsynth + 重发 SynthDef + 重建拓扑。
- **ffmpeg 与 scsynth 解耦生命周期**:scsynth 重启时 ffmpeg 继续从 JACK/loopback 拉(数据是静音),YouTube 直播不断流,scsynth 恢复后音乐自动接续。
- **音频路由**:裸金属选 `jackd -d dummy`(scsynth 与 JACK 集成最稳,ffmpeg `-f jack` 是一等公民);容器选 `modprobe snd-aloop`(无 jackd 守护进程,容器友好)。**警惕** PipeWire null sink 的 parec 默认连错路由问题(beats.softwaresoftware.dev 踩过的坑),启动后必须用 `pw-link` 强制拓扑。
- **Buffer 配置**:24/7 直播**不必追求超低延迟**,JACK buffer 1024–2048 frames @ 48kHz(20–40ms)更抗 OS scheduling 抖动,YouTube 自身有 2–10s buffer 完全无所谓。

### 6.3 Go 引擎骨架(精简版)

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
    return nil
}

func (e *Engine) SpawnSynth(def string, id int32, params map[string]float32) error {
    msg := osc.NewMessage("/s_new")
    msg.Append(def); msg.Append(id)
    msg.Append(int32(0)); msg.Append(int32(1))  // addAction=head, target=group1
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

对应的 SuperCollider SynthDef(用 sclang 一次性编译):

```supercollider
SynthDef(\ambient_pad, { |out=0, freq=220, amp=0.2, att=2, rel=4, pan=0|
    var sig = Mix.fill(5, { |i|
        SinOsc.ar(freq * (1 + (0.005 * (i-2))), 0, 1/5)
    });
    sig = LPF.ar(sig, freq * 4);
    sig = sig * EnvGen.kr(Env([0,1,1,0],[att,2,rel],\sin), doneAction: 2);
    Out.ar(out, Pan2.ar(sig, pan, amp));
}).writeDefFile("synthdefs/");

SynthDef(\granular_drone, { |out=0, buf=0, rate=1, dens=20, amp=0.2|
    var trig = Dust.kr(dens);
    var pos = LFNoise2.kr(0.1).range(0, BufDur.kr(buf));
    var grain = TGrains.ar(2, trig, buf, rate, pos, 0.2, 0, amp);
    Out.ar(out, grain);
}).writeDefFile("synthdefs/");
```

启动脚本(systemd unit + ffmpeg)和 `pw-link` 路由修复脚本都已在子代理报告中给出,此处省略以保持密度。

---

## 7. 落地清单 — 按优先级的下一步行动

**Week 1 立即提升可听性(~3 人天,不需要新工具,改造现有 ghsingo 即可)**: 用 librosa 分析 `cosmos-leveloop-339.wav` 的 tonic/mode;加 2 个 sine drone(C2 + C3 或与 BGM 同 tonic 的对应音);整体输出加 send → reverb (RT60=4.5s, wet 35%);加 vinyl noise floor 在 -38 dBFS;实现 phrase silence gate(每 8s 末强制 1s rest);加 max-voices-per-second 节流(白天 3,夜晚 1);把调式从 C 五声切到 F Lydian / D Dorian。**仅这一周的工作就能修掉 70% 的"不沉浸"问题。**

**Week 2 扩展音色 + 长程结构(~5 人天)**: 给每种事件类型准备 2 个互补音色家族(钟+pad+pluck);实现 L3/L4 prime-period 调度(60s/600s tick);atomic state snapshot/restore(`/var/lib/ghsingo/state.gob` 每 10s 写一次);训练简单二阶 Markov(语料从 Pärt/Eno/Sakamoto MIDI 取 ~600 transition);**上线带 5 秒钩子的启动序列**。

**Week 3–4 工程迁移到 SuperCollider(~7 人天)**: 把核心引擎从当前 Go 内部混音迁移到 Go + scsynth 子进程架构;`apt install supercollider-server jackd2` 测试机起 scsynth;dev 机装完整 SC IDE 写 8–10 个 SynthDef 导出 `.scsyndef`;Go 端引入 `hypebeast/go-osc` 实现 `engine.go` 骨架;接 ffmpeg jackd dummy backend → 本地 nginx-rtmp 验证 24h 不断流。

**Week 5+ 打磨与监控**: 加 supervisor 心跳自动重启;启动后 `pw-link`/`jack_connect` 强制路由;systemd unit 部署;prometheus 监控 `peak_cpu` / `num_synths` / `xrun_count`;A/B 测试旧版 vs 新版 YouTube 平均观看时长;7 天 soak test。

**第二阶段增强(可选)**:supernova 替换 scsynth 释放多核;FAUST 写 1–2 个高质量 reverb/granular `faust2supercollider` 编译为 SC plugin;ChucK `OscIn` 作为第二条子进程并行跑(同 jack graph),做对位/律动层,scsynth 做 pad/drone 层——**双引擎 ambient 增加生成多样性**。

---

## 8. 必须避开的已知陷阱

每条都是从真实失败案例反推的,直接列表:

- **不要继续把事件密度直接耦合到音符密度**——这是 ghsingo 当前最致命的设计错误,所有其他修复都会被这一条撤销。
- **不要用纯白噪作为底层**(用 brown + pink 1/f 混合)。
- **不要在 master bus 加 high-shelf boost"为了清晰"**——24/7 听必然疲劳。
- **不要让 grain density 拉到 200+/sec**(听起来像水龙头白噪)。
- **不要让事件 trigger 明显的新声音**(听众会从 ambient 中"被叫醒")——95% 事件应只更新状态向量。
- **不要让参数瞬间跳变**——任何调制必须经 5–30s envelope follower(SC 的 `Lag.kr`)。
- **不要把 stereo width 推到 200%+**(YouTube 移动端 mono 兼容性死亡)。
- **不要冲到 -14 LUFS**——24/7 ambient 应走 -18 to -20 LUFS 高动态范围。
- **不要让森林+海洋+宇宙在 master 同跑但都没经过统一 IR reverb**——它们永远不会"在同一空间"。
- **不要用 Reverb 串联但不 LPF reverb input**——高频堆积啸叫(Stars of the Lid 教训)。
- **不要在前 5 秒视频里出现 spike/flash**——会撤销音频的认知舒适努力。
- **不要让 ffmpeg 与 scsynth 同生命周期**——scsynth 崩溃应该让 ffmpeg 继续推静音,而不是断 RTMP 流。
- **不要用 ChucK stdin 做 IPC**——文档不推荐,用 OSC。
- **不要把 Heavy/Enzien Compiler 放进关键路径**——商业版本基本停摆。

---

## 9. 哲学层面的一句话总结

> "The goal is not to retreat from reality into a cocoon of good vibes. The subject of this work is your attention." — about Eliane Radigue

ghsingo 的目标不应是"音乐",也不应是"无脑白噪",而应是:**一个会随着 GitHub 这个全球协作大脑的脉搏微妙呼吸的、舒适的环境**。听者打开它工作时几乎察觉不到它的存在;但当某个 release 发生时,房间里光线似乎略微变化——这就是成功。Brian Eno 把 *Music for Airports* 设计为"机场里 muzak 的对立面":不是为了被注意,但当被注意时奖励你以丰富。**这正是 24/7 GitHub ambient 应该追求的境界,也是现有 bell-era 严格五声+编钟设计因为缺少地基、空间、留白、调式色彩、状态解耦,而尚未达到的境界。**

修复路径已经清晰:**Week 1 改 5 件事就能感知到提升,Week 2–3 的多层时间尺度系统让"2 周不重复但风格连贯"成为工程可保证的事实,Week 4–5 的 scsynth 迁移让系统具备工业级 24/7 稳定性。**剩下的就是开工。