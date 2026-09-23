# 中国古代编钟(Bianzhong)可用采样音色与合成方案调研报告

> 面向:资深 Python/Go 开发者,使用 go-meltysynth 构建 24/7 RTMP 生成式音乐直播流
> 目标格式:SoundFont 2 (.sf2)——go-meltysynth 唯一支持的格式
> 日期:2026-04-25

---

## 0. 执行摘要与推荐路径

**坏消息**:经系统性搜索(GitHub、Gitee、musical-artifacts.com、Polyphone 社区、KVR、中国官方博物馆、学术机构等),**目前不存在任何一个"开源、可直接下载、以 SF2 格式发布"的编钟专用音色库**。唯一高质量的数字化编钟采样是 2022–2023 年腾讯 NExT Studios 与湖北省博物馆合作制作的 613 条单音音源,但这些音源只内嵌于「传统器乐数字化」微信小程序及 QQ 音乐的《古乐疗愈》衍生专辑中,并未公开释出原始 WAV 文件 [[中新社报道](https://www.sd.chinanews.com.cn/2/2023/0309/86574.html)] [[机核 GCORES 幕后报道](https://www.gcores.com/articles/162475)] [[湖北日报](https://epaper.hubeidaily.net/pc/content/202303/06/content_214603.html)]。

**好消息**:对于生成式 24/7 RTMP 音乐直播场景,三条可行路径明确可落地。

**推荐路径(按上手速度排序)**:

| 优先级 | 方案 | 时间成本 | 成品质量 | 法律风险 |
|---|---|---|---|---|
| ⭐⭐⭐ 最快上手 | **程序化加法合成 → 自打包 SF2**(下文 §3.3) | 半天 | 中等(可辨识为"钟") | 无 |
| ⭐⭐ 中期方案 | 从 1978 年首演视频 / YouTube 复制件演奏切片,pyin 估音,用 Polyphone 打包 SF2 | 1–2 天 | 高(真实编钟音色) | 个人非商用合理,直播带广告有风险 |
| ⭐ 长期高保真 | 购买 Kong Audio BianZhong Pro → 在 Kontakt/独立工具导出单音 WAV → 重新打包 SF2 | 1 周 + $109 | 最高 | 商业授权,合规 |

---

## 维度一:现成的编钟 SoundFont (.sf2) 资源盘点

### 1.1 专门的编钟 SF2 音色 —— **无**

使用多种关键词组合("bianzhong soundfont"、"编钟 sf2"、"chinese chime bells sf2"、"曾侯乙 sf2"、"chinese bells sf2")在 GitHub、Gitee、Codeberg、Musical Artifacts、Polyphone Soundfonts、KVR、Synthfont Links 上搜索,**均未找到专门的编钟 SoundFont**。

Musical Artifacts 上相关的钟类 SF2 只包括:
- [bell soundfont (1904 年制钟)](https://www.musical-artifacts.com/artifacts/2632) — CC BY 3.0,西式钟,非编钟。
- [Church Bells soundfonts](https://musical-artifacts.com/artifacts/3447) — 西方教堂钟,非编钟。
- [Bells 标签列表](https://musical-artifacts.com/artifacts?tags=bells) — 含 Asian Bells (XG Map, CC0),但来源不明,非编钟原采样。

结论:**公有领域/CC 许可的编钟 SF2 目前是一个空白**。

### 1.2 中国民乐综合 SoundFont 中的类似音色

| 资源 | 格式 | 是否含编钟 | 许可 | 链接 |
|---|---|---|---|---|
| **DSK Asian DreamZ Vol.1** | SF2(9.26 MB) | ❌ 仅 Pipa/Guzheng/Erhu/Dizi 等,无编钟 | 免费(作者保留) | [rekkerd.org](https://rekkerd.org/dsk-soundfonts/) |
| **Quasar Asian Instruments Soundfonts**(30 × SF2,164 MB) | SF2 | 含 Asian Cymbals / Gong / Belafon,**无专门编钟** | 商业 | [quasarsounds.com](https://quasarsounds.com/listing/asian-instruments-soundfonts-sf2/) |
| **Touhou Soundfont** (THFont.sf2) | SF2 | 仅含 GM 标准 Tubular Bells (#014),音色类似管钟,非编钟 | CC BY 4.0 | [musical-artifacts/433](https://musical-artifacts.com/artifacts/433) |
| **GeneralUser GS v1.471** | SF2(~31 MB) | 含 Tubular Bells、Church Bells、Carillon、Bell Tower 等西式钟 preset | 免费使用(含商用) | [schristiancollins.com](https://www.schristiancollins.com/generaluser.php) / [musical-artifacts/3592](https://musical-artifacts.com/artifacts/3592) |
| **Arachno SoundFont** | SF2 | 同 GM 标准,含 Tubular Bells 等 | 免费 | arachnosoft.com |

### 1.3 GM/GS/XG 标准中可作"替代"的钟类 preset

SoundFont 2 / GM Level 1 标准中,与编钟声学特征(强不谐和泛音、长衰减)最接近的 preset:

- **Program 14 – Tubular Bells**:西式管钟,短促但有金属 ring tone,是最常用的"钟"替代。
- **Program 112 – Tinkle Bell**:亮、短、高频,更像小风铃。
- **Program 9 – Glockenspiel**:金属敲击乐,但泛音更谐和,缺少钟的"嗡鸣尾音"。
- **Program 97 – FX 3 (Crystal)**:常被做成钟 + pad 混合,氛围效果好。

在 GeneralUser GS 中,preset "Bell Tower" 使用了 delay phase(请注意 MuseScore 反馈的 glitch [[MuseScore 论坛](https://musescore.org/en/node/284290)],对连续渲染不利,建议改用 "Tubular Bells" 或 "Carillon")。

**对于用户场景的务实建议**:可以先用 GeneralUser GS 的 Tubular Bells / Carillon 作为 placeholder 启动 24/7 直播,同时并行开发自制编钟 SF2。

### 1.4 大学/研究机构发布的采样资源

- **湖北省博物馆 + 腾讯 NExT Studios(2022–2023)**:采录曾侯乙编钟 1:1 复制件 64 钟体(不含楚惠王镈钟)正鼓部 + 侧鼓部,共 613 条有效单音,677 条原始样本,历时近两个月 [[机核文章](https://www.gcores.com/articles/162475)]。**但未公开 WAV 原始文件**,仅通过微信小程序"传统器乐数字化"、QQ 音乐《古乐疗愈》音乐特辑释出成品 [[腾讯新闻](https://news.qq.com/rain/a/20230222A0761J00)]。这是目前全球最高精度的编钟数字化成果,但受腾讯版权保护。
- **中央音乐学院、中国音乐学院、武汉音乐学院、上海音乐学院**:未发现任何公开可下载的编钟采样数据集。武汉音乐学院李幼平教授的《编钟与交响乐》项目(2022)侧重作曲研究,未发布原始采样 [[武汉市政府](https://www.wuhan.gov.cn/zjwh/whrw/202203/t20220325_1945286.shtml)]。
- **斯坦福 CCRMA Lurie Carillon 项目**:Isaac Levine 等人(2016)录制了密歇根大学 Lurie 60 钟钟琴,并公开了每口钟的**模态参数(frequency / amplitude / decay / phase)CSV 数据**用于加法/模态合成 [[CCRMA Lurie Carillon](https://ccrma.stanford.edu/~kermit/website/bells.html)]。这是西式钟琴,但**其 CSV 模态数据格式可直接作为加法合成模板**。
- **Nature 论文(2024)**:通过 3D 扫描再铸造法再造编钟的研究,提供了历史数据与参数,但无采样 [[npj Heritage Science](https://www.nature.com/articles/s41599-024-04133-8)]。
- **《千古绝响:曾侯乙编钟之声》(1986)**:中国唱片总公司与湖北省博物馆历时 3 个多月录制的**原件唯一录音专辑**,1986 年之后原件被永久封存 [[湖北日报](http://www.cnhubei.com/cmdetail/520656)] [[豆瓣音乐](https://music.douban.com/subject/10483422/)]。这是最重要的历史录音资源。

### 1.5 商业采样库(均非 SF2 格式,需转换)

| 品牌 | 产品 | 格式 | 价格 | 规模 | 注 |
|---|---|---|---|---|---|
| **Kong Audio(空音)** | [BianZhong / BianZhong Pro](https://www.chineekong.com/zhy_bz.htm) | VST/AAX/AU(基于 QIN RV Engine,Windows + macOS) | Pro $129(历史价,现为 $139/$109 bundle) [[chineekong.com/en](https://chineekong.com/en/ancient-chinese-bianzhong-bianqing/)] | 23 钟标准版 / 88 钟 Pro(含一钟双音) | 在湖北编钟乐团复制件现场采样 |
| **Sound Magic** | [BianZhong](https://neovst.com/product/bianzhong/) | VST/AU(32/64 位) | $99–169 | 湖北省博物馆录制 | [KVR 产品页](https://www.kvraudio.com/product/bianzhong-by-sound-magic) |
| **EastWest** | [Silk](https://www.soundsonline.com/world-and-traditional/silk) | Opus/Play | Composer Cloud 订阅 | 丝绸之路主题,含中国乐器,**不单独含编钟** | |
| **Impact Soundworks** | Koto Nation / Meditation | Kontakt (.nki) | $99+ | 日式乐器为主;Meditation 含 gong/glass | 均非编钟 |
| **Soundiron** | [Noah Bells](https://soundiron.com/products/noah-bells) | Kontakt / Decent Sampler | — | 21 个印度 Khadki 铜钟,可近似作声学替代 | 非中式 |

**关于格式转换至 SF2 的可行性**:
- Kong Audio / Sound Magic 均使用**受保护的自定义 VST 引擎**(QIN RV Engine),样本以加密/专有格式存储,**无法直接提取为 WAV**。
- 即使通过 Kontakt 加载可绕转换,其 EULA 通常禁止重新分发单音采样。
- **唯一合规的 SF2 转换路径**是购买授权后通过 DAW 对每个 MIDI note 做"一键一录制",再 Polyphone 打包(详见 §3.3)。这已违背"开源可下载"偏好。

---

## 维度二:从公开音乐专辑自行切分采样的可行性

### 2.1 公认的编钟权威录音清单

| 录音 | 年份 | 发行方 | 获取渠道 | 注 |
|---|---|---|---|---|
| **《千古绝响:曾侯乙编钟之声》**(孤版,原件录音) | 1986 | 中国唱片总公司 × 湖北省博物馆 | [豆瓣条目](https://music.douban.com/subject/10483422/)、网络二手碟、WAV 论坛民间分享(如[享乐音乐网](https://www.xlebbs.com/thread-124826-1-1.html),来源存疑) | **曾侯乙原件唯一录音**;原件 1986 年之后封存 |
| 《千古绝响:曾侯乙编钟》(再版) | 2005-10-12 | 中国唱片公司(表演者:赵维瑞) | [豆瓣条目 1916788](https://music.douban.com/subject/1916788/) | 2005 年再版 |
| 《楚商》《编钟乐舞》系列 | 1980s–1990s | 湖北省博物馆编钟乐团 | 馆内演出、B 站视频(官方账号) | 多为复制件演奏 |
| 《交响曲 1997:天·地·人》 | 1997 | 谭盾指挥;编钟复制件+马友友 | DG 唱片发行 | |
| 1978/1984 年编钟首演录音 | 1978/1984 | 湖北艺术学院(冯光生等演奏) | 央视档案/纪录片片段 | 公开可得的历史素材 |
| "古乐疗愈"音乐特辑(基于腾讯数字化音源) | 2023 | 腾讯游戏 × QQ 音乐 × 国乐家 | QQ 音乐独家 | 已是编曲成品,切片困难 |

### 2.2 中国著作权法下的版权状态分析

**核心条款(2020 年修正、2021-06-01 施行的《著作权法》)** [[中国政府网](https://www.gov.cn/guoqing/2021-10/29/content_5647633.htm)] [[国家版权局](https://www.ncac.gov.cn/xxfb/flfg/flfg_532/202103/t20210309_50530.html)]:

- **第 44 条**:录音录像制作者权**保护期为 50 年,截止于该制品首次制作完成后第 50 年的 12 月 31 日**。
- **第 39 条第 1 款第 5 项**:表演者对录有其表演的录音录像制品享有复制/发行权,保护期同为 50 年,截止于表演发生后第 50 年的 12 月 31 日。

**推论**:
- 1986 年录制的《千古绝响》:表演者权 + 录音制作者权保护期**截止于 2036 年 12 月 31 日**。**截至 2026 年 4 月仍在保护期内**(还有约 10 年)。
- 1978/1984 年首演录音:如有独立发行的录音制品,保护期**已于 2028/2034 年末届满**(部分 1978 年档案已接近进入公有领域,但具体取决于各录音制品的"首次制作完成"日期)。
- **词曲作者权**(如现代编曲《楚商》《春江花月夜》):保护期为作者终生 + 50 年。清代以前的古曲旋律本身在公有领域,但**现代编配版本仍受保护**。

### 2.3 中国合理使用 vs 美国 Fair Use 的关键差异

中国采用**封闭式列举**(第 24 条,原 22 条),共 13 种情形 [[中国政府网](https://www.gov.cn/guoqing/2021-10/29/content_5647633.htm)] [[共产党员网](https://www.12371.cn/2023/08/12/ARTI1691822019254110.shtml)]:

- **第 24 条第 1 项(唯一可能适用于本任务)**:"为**个人**学习、研究或者欣赏,使用他人已经发表的作品"。
- 美国 17 U.S.C. §107 采用**开放式四要素标准法**:使用目的/性质、作品性质、使用量、对市场影响。中国没有一般性"四要素"测试,法官**无权在列举之外创设新合理使用情形** [[汇仲律所](https://www.huizhonglaw.com/Content/2023/12-06/1803006554.html)] [[中国知识产权律师网](https://www.ciplawyer.cn/articles/155828.html)]。

**对用户场景的法律评估**:

| 使用场景 | 合规性评估 |
|---|---|
| 在本地从 1986 年《千古绝响》CD 切片,仅用于个人算法作曲研究、不对外 | 可能适用第 24 条第 1 项合理使用(仍在录音制品保护期内,但"个人学习研究") |
| 切片后打包 SF2 并上传 GitHub 公开分享 | **不构成合理使用**,直接侵犯录音制作者 + 表演者复制权/信息网络传播权 |
| 切片渲染生成新曲,在 24/7 RTMP 直播(含广告变现) | **高风险**:构成商业性使用,不属第 24 条任一情形;北京互联网法院 2017–2022 年判决中短视频二次创作合理使用认定率约 2.1% [[中国知识产权律师网](https://www.ciplawyer.cn/articles/155828.html)];网络直播通常不被认定合理使用 [[汇业律师](https://www.huiyelaw.com/news-1687.html)] |
| 切片自 YouTube/B 站上的 1978 年央视纪录片中的编钟音轨 | 纪录片整体有独立著作权,即使内嵌音频超过录音制品保护期,纪录片本身仍受保护 |

**结论**:若直播含广告或打赏变现,从《千古绝响》(1986)切片不合规。**2036 年后该录音进入公有领域前,应避免用于商用直播**。

### 2.4 技术切分工作流(假设已合法获取素材)

编钟"一钟双音"的关键声学特征 [[华音网](https://www.huain.com/article/other/2021/1211/299.html)]:
- 每口钟可发出**正鼓音**(敲击鼓部正面,激发低基频)和**侧鼓音**(敲击鼓部侧面,激发较高基频),**两音相差大三度或小三度**。
- **双基峰频谱**:在 STFT 短时频谱中,最高峰值在振动后 0.1–0.5 秒内往往是**高次谐波而非基频**(如大铜钟起振后 0.4 s 最高峰为 432.5 Hz 和 897 Hz,而基频 152.5 Hz 在 4 秒后才占优势)。这意味着**简单 pyin F0 检测可能失败**。
- 正、侧鼓之间存在**拍频(beating)**,非严格纯律小三度。

**推荐 Python 工作流**:

```python
# 1. 安装依赖
# pip install librosa soundfile numpy scipy pydub

import librosa, soundfile as sf
import numpy as np
from pathlib import Path

# 2. 载入专辑单曲
y, sr = librosa.load('bianzhong_track.wav', sr=44100, mono=True)

# 3. Onset 检测(打击乐对 onset 非常友好)
onset_frames = librosa.onset.onset_detect(y=y, sr=sr, 
                                           backtrack=True,    # 回溯到 attack 前
                                           units='samples')
# 参考: https://librosa.org/doc/main/generated/librosa.onset.onset_detect.html

# 4. 按 onset 切片(每切片保留 3–5 秒以容纳尾音)
segments = []
for i, start in enumerate(onset_frames):
    end = min(start + int(5.0 * sr), len(y))
    seg = y[start:end]
    segments.append(seg)

# 5. 用 pyin 估计每片的主频(对钟类慎用,建议结合 piptrack)
# 注意: 编钟基频在起振后 1–4 秒才占优,最好取 尾部稳态 的 F0
for i, seg in enumerate(segments):
    tail = seg[int(0.5*sr):]   # 跳过 attack, 取后半段稳态
    f0, voiced_flag, _ = librosa.pyin(
        tail, fmin=librosa.note_to_hz('C2'),    # 编钟音域约 65 Hz – 2000 Hz
        fmax=librosa.note_to_hz('C7'), sr=sr)
    # 取 voiced 帧中位数作为基频估计
    f0_estimate = np.nanmedian(f0[voiced_flag])
    
    # 6. 转换为 MIDI note
    midi_note = int(round(librosa.hz_to_midi(f0_estimate)))
    note_name = librosa.midi_to_note(midi_note)
    
    sf.write(f'bell_{i:03d}_{note_name}_{midi_note}.wav', seg, sr)
```

**识别一钟双音的思路**:
- 对同一次"节目"中连续两次击打(间隔 < 2 秒)的单音,若 F0 差 3–5 个半音,很可能是同一口钟的正鼓/侧鼓音。可用聚类(DBSCAN on [F0, spectral centroid])分组。
- 对 SF2 打包,正鼓音和侧鼓音应作为**两个独立的 Sample**,分别映射到不同的 MIDI note,或用 Bank Select 区分。

文档参考:[librosa onset 切片 Google Groups 讨论](https://groups.google.com/g/librosa/c/lxZDuW36b5k) [[librosa.pyin 文档](https://librosa.org/doc/main/generated/librosa.pyin.html)]。

---

## 维度三:MIDI 合成器路径(无真实采样情况下)

### 3.1 物理建模合成

#### 3.1.1 STK (Synthesis ToolKit) —— Perry Cook & Gary Scavone

- **BandedWG**(Banded Waveguide):Essl & Cook 提出,适用于**具有强不谐和模式**的物体(碗、棒、铃) [[Semantic Scholar](https://www.semanticscholar.org/paper/Physical-wave-propagation-modeling-for-real-time-of-Cook-Essl/619d0e92a9ad73473266c5a57a65e61979038e95/figure/64)]。**编钟的扁椭圆截面对应的模态完全可用 BandedWG 模拟**。
- **ModalBar**:条状打击乐模态合成,同样适配钟类。
- **TubeBell**(FM 风格):STK 的预置 FM 管钟 patch。
- C++ 调用、有 ChucK 绑定 [[ChucK Reference](https://chuck.stanford.edu/doc/reference/)],也有 Csound `wguide2` 等 opcode 的类似实现 [[Cycling '74 教程](https://cycling74.com/tutorials/physical-modeling-synthesis-for-max-users-a-primer)]。

#### 3.1.2 Faust 物理建模库

[Faust `physmodels.lib`](https://faustlibraries.grame.fr/libs/physmodels/) 和 [Faust examples/physicalModeling](https://faustdoc.grame.fr/examples/physicalModeling/) 已**内置多种钟模型**:
```
churchBell, englishBell, frenchBell, germanBell, russianBell, standardBell
```
这些是西方钟模型,但**Faust 代码可参数化修改**:将 modal frequencies ratio 从西方钟的 1.0 : 1.19 : 1.50 : 2.00 : 2.51 改为编钟频率比(见 §3.2),再编译为 WAV 批量输出。

#### 3.1.3 模态合成(最适合编钟)

模态合成把对象分解为**平行的 N 个衰减正弦振子**,每个有 frequency / amplitude / decay time 三个参数 [[Nathan Ho - Exploring Modal Synthesis](https://nathan.ho.name/posts/exploring-modal-synthesis/)]。**编钟的扁椭圆形导致模态之间非简单整数倍关系,是模态合成的教科书案例**。

### 3.2 加法/FM 合成:编钟频谱参数速查

**编钟典型频谱比例**(参考黄翔鹏、陈通等测音研究 [[华音网](https://www.huain.com/article/other/2021/1211/299.html)] [[Shen, Scientific American 1987](https://www.scientificamerican.com/article/acoustics-of-ancient-chinese-bells/)]):

| 分音 | 频率比(相对基频) | 名称 |
|---|---|---|
| 1 | 1.000 | 基频(正鼓音 或 侧鼓音) |
| 2 | ~2.0 (略高于 2) | 二次分音 |
| 3 | ~2.4–2.76 | 不谐和分音 |
| 4 | ~5.4 | 高次 |
| 5 | ~8.9 | 高次 |

对比西方教堂钟的经典 1.0 : 1.19 : 1.50 : 2.00 : 2.51 比例,编钟的**第二分音略低于 2**,且**同时存在正鼓、侧鼓两个基频**在同一钟体内(相差大/小三度)。

**Python 模态合成代码示例(可直接用于生成 SF2 样本)**:

```python
import numpy as np
import soundfile as sf

def synth_bianzhong(f0_hz, duration=5.0, sr=44100, 
                    is_side_tone=False,       # 是否为侧鼓音
                    f0_side_ratio=1.2599):     # 大三度 2^(4/12)
    """
    编钟单音模态合成(正鼓音或侧鼓音独立合成)。
    """
    t = np.linspace(0, duration, int(sr * duration), endpoint=False)
    
    # 编钟典型模态比例(经验值,可按实测调整)
    partials = [
        # (freq_ratio, amplitude, decay_seconds)
        (1.00,  1.00, 4.5),   # 基频(最主要,衰减最慢)
        (2.02,  0.55, 2.8),   # 略不完美的 2 倍
        (2.76,  0.40, 1.8),   # 不谐和分音
        (3.40,  0.30, 1.2),
        (5.40,  0.25, 0.8),
        (8.93,  0.15, 0.5),   # 高频金属感
    ]
    
    # 正鼓/侧鼓音耦合(一钟双音的关键)
    base_freq = f0_hz * (f0_side_ratio if is_side_tone else 1.0)
    
    # 激发瞬态(attack 0–0.1 s 的宽带噪声,模拟木槌击打)
    attack_len = int(0.01 * sr)
    attack = np.random.randn(attack_len) * np.exp(-np.linspace(0, 5, attack_len))
    
    signal = np.zeros_like(t)
    for ratio, amp, decay in partials:
        freq = base_freq * ratio
        # 轻微去谐化制造 "warble"(钟的颤音)
        freq_wobble = freq + np.random.uniform(-0.3, 0.3)
        envelope = np.exp(-t / decay)
        # 随机相位避免相干感
        phase = np.random.uniform(0, 2 * np.pi)
        signal += amp * envelope * np.sin(2 * np.pi * freq_wobble * t + phase)
    
    # 添加 attack 瞬态
    signal[:attack_len] += attack * 0.3
    
    # 归一化
    signal = signal / np.max(np.abs(signal)) * 0.95
    return signal.astype(np.float32)

# 批量生成 24 口钟(C2 – C6 半音阶)正鼓音 + 侧鼓音
import os
os.makedirs('bianzhong_samples', exist_ok=True)
for midi in range(36, 85):  # C2–C6
    f0 = 440.0 * 2 ** ((midi - 69) / 12)
    primary = synth_bianzhong(f0, is_side_tone=False)
    side    = synth_bianzhong(f0, is_side_tone=True)
    sf.write(f'bianzhong_samples/bell_{midi:03d}_primary.wav', primary, 44100)
    sf.write(f'bianzhong_samples/bell_{midi:03d}_side.wav',    side,    44100)
```

**FM 合成路径**:Stanford CCRMA 的 tubular-bell FM 示例 [[CCRMA FM2 教程](https://ccrma.stanford.edu/software/clm/compmus/clm-tutorials/fm2.html)] 用 3 对 C/M pair 组合非整数 harmonicity ratio 产生钟声。对编钟,可尝试 c:m = 1:1.4, 0.65:1.05, 0.22:0.83 组合 + 非谐和索引。`dexed`(DX7 开源复刻)中大量钟类 bank 可作参考。

### 3.3 从 WAV 到 SF2 的打包工具链(关键!)

#### 方案 A:Polyphone 命令行(最推荐)

Polyphone 是开源 SF2 编辑器 [[GitHub davy7125/polyphone](https://github.com/davy7125/polyphone)]。虽无法用 CLI **从零构建** SF2,但可以:

1. 先生成 SFZ 文件(纯文本,容易程序化生成)
2. 用 Polyphone CLI 转换 SFZ → SF2

```bash
# Polyphone CLI 用法(从 Arch Manpage)
# polyphone -1: 转换为 sf2
# polyphone -3: 转换为 sfz

polyphone -1 -i bianzhong.sfz -d ./output -o bianzhong

# 等价 Windows:
"C:\Program Files\Polyphone\polyphone.exe" -1 -i bianzhong.sfz
```

参考 [Polyphone 命令行文档](https://www.polyphone.io/en/documentation/manual/annexes/command-line) 和 [Arch Manpage](https://man.archlinux.org/man/polyphone.1.en)。

**自动生成 SFZ**:

```python
# bianzhong.sfz 示例
sfz_content = """
<control>
default_path=./bianzhong_samples/

<group>
ampeg_attack=0.002
ampeg_release=3.0
loop_mode=no_loop

"""

# 正鼓音 preset (bank 0)
for midi in range(36, 85):
    sfz_content += f"""
<region>
sample=bell_{midi:03d}_primary.wav
pitch_keycenter={midi}
lokey={midi}
hikey={midi}
"""

with open('bianzhong.sfz', 'w') as f:
    f.write(sfz_content)

# 然后:
# polyphone -1 -i bianzhong.sfz -o bianzhong_primary
```

#### 方案 B:Python sf-creator(半自动)

[`paulwellnerbou/sf-creator`](https://github.com/paulwellnerbou/sf-creator) 是一个从 WAV 目录自动生成 SFZ 的 Python 工具(按文件名自动识别音高),然后仍需 Polyphone 转 SF2。

```bash
git clone https://github.com/paulwellnerbou/sf-creator
cd sf-creator
python main.py sfz /path/to/bianzhong_samples/
# 生成 /path/to/bianzhong_samples/soundfont.sfz
polyphone -1 -i /path/to/bianzhong_samples/soundfont.sfz
```

#### 方案 C:C++ SF2cute 库(程序化直写 SF2,最彻底)

[`gocha/sf2cute`](https://github.com/gocha/sf2cute) 是 C++14 SF2 **写入**库,可从代码直接构造 SF2 文件 [[文档](http://gocha.github.io/sf2cute/)]。

```cpp
// 核心 API 示例(摘自官方 examples/write_sf2.cpp)
#include <sf2cute.hpp>
using namespace sf2cute;

SoundFont sf2;
sf2.set_bank_name("Bianzhong");

// 添加 sample
std::shared_ptr<SFSample> sample = sf2.NewSample(
    "Bell_C3_Primary",
    wav_data,       // std::vector<int16_t>
    0, wav_data.size(),
    44100,
    48,             // root MIDI key = C3
    0);

// 添加 instrument
SFInstrumentZone zone(sample, 
    {SFGeneratorItem(SFGenerator::kSampleModes, uint16_t(SampleMode::kNoLoop))},
    {});
auto inst = sf2.NewInstrument("Bianzhong", {std::move(zone)});
auto preset = sf2.NewPreset("Bianzhong", 0, 0, {SFPresetZone(inst)});

std::ofstream ofs("bianzhong.sf2", std::ios::binary);
sf2.Write(ofs);
```

#### 方案 D:Go 生态 —— **当前缺口**

经搜索,**Go 原生没有任何成熟的 SF2 写入库**。
- `sinshu/go-meltysynth` [[GitHub](https://github.com/sinshu/go-meltysynth)] — 只读合成器。
- `danielgatis/go-soundfont` [[GitHub](https://github.com/danielgatis/go-soundfont/blob/main/LICENSE)] — 标题为"synthesizer library",仍为读取为主。

**建议**:Go 项目中继续用 go-meltysynth 做运行时合成,把 SF2 **生成**环节用 Python(Polyphone CLI 包裹)或 C++(sf2cute)外置,通过 `make` / `just` 构建流程调用。

#### 方案 E:Python tinysoundfont & sf2_loader(仅读/播放,不写)

- [`tinysoundfont`](https://pypi.org/project/tinysoundfont/) — 基于 TinySoundFont 的 Python 绑定,能在 Python 中渲染 SF2 音频。
- [`Rainbow-Dreamer/sf2_loader`](https://github.com/Rainbow-Dreamer/sf2_loader) — 配合 `musicpy` 使用,方便测试自制 SF2。
- [`sf2utils`](https://pypi.org/project/sf2utils/) — 解析和元数据查看,**不含写入**。

---

## 资源对比表

| 资源 | 格式 | 许可证 | 文件大小 | 采样质量 | 一钟双音 | go-meltysynth 兼容 | 推荐指数 | 最后更新 |
|---|---|---|---|---|---|---|---|---|
| 自制加法/模态合成 SF2 | SF2 | 自有 | 可控(10–100 MB) | 中等 | ✅ 可控 | ✅ 原生 | ⭐⭐⭐⭐⭐ | N/A |
| Kong Audio BianZhong Pro | VST/AAX/AU | 商业 | ~4 GB | 最高 | ✅ | ❌(需二次导出 WAV→SF2) | ⭐⭐⭐(成本高) | 持续更新 |
| Sound Magic BianZhong | VST/AU | 商业 | — | 高 | ✅ | ❌ | ⭐⭐ | 2020 |
| 腾讯×湖北博编钟 613 条音源 | 腾讯内部(小程序) | 未公开 | — | 最高 | ✅ | ❌(无法获取) | 仅作参考 | 2022–2023 |
| GeneralUser GS(Tubular Bells) | SF2 | 免费,可商用 | 31 MB 全包 | 中等(非编钟) | ❌ | ✅ | ⭐⭐⭐(临时替代) | 2024 |
| Arachno SoundFont | SF2 | 免费 | ~150 MB | 中等 | ❌ | ✅ | ⭐⭐(临时替代) | — |
| DSK Asian DreamZ | SF2 | 免费 | 9.26 MB | 低 | ❌(无编钟) | ✅ | ⭐ | 2008 |
| 《千古绝响》1986 切片 | WAV(自制) | **2036-12-31 前受保护** | 取决于切片 | 最高(原件!) | ✅(需识别) | 需打包 SF2 | ⭐(合规风险) | 1986 |
| STK BandedWG / ModalBar | C++/ChucK | BSD-like | N/A | 高(参数调校后) | ✅ | 间接(先渲染 WAV) | ⭐⭐⭐⭐ | 持续 |
| Faust physmodels churchBell 改造 | Faust dsp | MIT | 源码小 | 中高 | ✅ 可加两套参数 | 间接 | ⭐⭐⭐⭐ | 持续 |

---

## 针对 24/7 RTMP 直播的最终落地建议

基于用户栈(Go / Python / Rust + go-meltysynth)和场景(算法作曲 + 直播流):

### 阶段一(本周):先上线,用替代音色
1. 下载 [GeneralUser GS v1.471](https://www.schristiancollins.com/generaluser.php)(免费可商用)
2. 在 go-meltysynth 中用 Program Change 切换到 Preset 14 (Tubular Bells) 或 Carillon
3. 立即开播,验证整个 RTMP 管线

### 阶段二(2–4 周):自制编钟 SF2
1. 用本文 §3.2 Python 代码生成 ~500 个编钟单音 WAV(24 口钟 × 正鼓/侧鼓 × 多 velocity)
2. 参考 [CCRMA Lurie Carillon 模态 CSV](https://ccrma.stanford.edu/~kermit/website/bells.html) 校准参数,或以 Faust `standardBell` 为起点 fork
3. 用 [`sf-creator`](https://github.com/paulwellnerbou/sf-creator) 生成 SFZ
4. `polyphone -1 -i bianzhong.sfz -o bianzhong.sf2`
5. Go 代码中 `meltysynth.NewSoundFont(...)` 载入

### 阶段三(长期):提升音色真实度
1. 从 B 站/YouTube 合法获取湖北省博物馆编钟乐团**复制件公开演出**片段(非 1986 原件录音,避开 2036 前的版权问题)
2. 使用本文 §2.4 pipeline 切片、估音
3. 将真实样本混入自制 SF2,形成 "hybrid patch"
4. 同时可考虑:对**腾讯"传统器乐数字化"小程序联系授权**,或等待 2036-12-31 后《千古绝响》进入公有领域

### 关于 Go 生态缺口的长期贡献建议
目前 Go 社区缺少原生 SF2 **写入**库——若精力允许,可 fork `go-meltysynth` 的 SF2 parser 并扩展写入能力,将是对整个生成式音乐 Go 社区的重要贡献。参考实现可看 C# 的 [`meltysynth`](https://github.com/sinshu/meltysynth) 和 C++ 的 [sf2cute](https://github.com/gocha/sf2cute)。

---

## 参考资源汇总(已验证 URL)

### SF2 工具与规范
- Polyphone(开源 SF2 编辑器):https://www.polyphone.io/ / https://github.com/davy7125/polyphone
- Polyphone CLI 文档:https://www.polyphone.io/en/documentation/manual/annexes/command-line
- sf2cute(C++14 SF2 写入):https://github.com/gocha/sf2cute
- sf-creator(WAV → SFZ):https://github.com/paulwellnerbou/sf-creator
- sf2utils(Python SF2 解析):https://pypi.org/project/sf2utils/
- sf2_loader(Python SF2 播放):https://github.com/Rainbow-Dreamer/sf2_loader
- tinysoundfont(Python 绑定):https://pypi.org/project/tinysoundfont/
- go-meltysynth(Go SF2 合成):https://github.com/sinshu/go-meltysynth
- TinySoundFont(C/C++ 单头文件):https://github.com/schellingb/TinySoundFont
- GeneralUser GS:https://www.schristiancollins.com/generaluser.php

### 编钟资料
- 曾侯乙编钟 Wikipedia:https://zh.wikipedia.org/zh-hans/%E6%9B%BE%E4%BE%AF%E4%B9%99%E7%BC%96%E9%92%9F
- UNESCO Memory of the World:https://www.unesco.org/en/memory-world/suizhou-bianzhong-marquis-yi-zeng
- 华音网《试探先秦双音编钟》:https://www.huain.com/article/other/2021/1211/299.html
- 腾讯编钟数字化幕后(机核):https://www.gcores.com/articles/162475
- 湖北日报编钟数字化:https://epaper.hubeidaily.net/pc/content/202303/06/content_214603.html
- Shen 1987 Scientific American:https://www.scientificamerican.com/article/acoustics-of-ancient-chinese-bells/
- Nature npj Heritage(3D 扫描再铸造):https://www.nature.com/articles/s41599-024-04133-8
- 《千古绝响》豆瓣:https://music.douban.com/subject/10483422/

### 商业产品
- Kong Audio BianZhong:https://www.chineekong.com/zhy_bz.htm / https://chineekong.com/en/ancient-chinese-bianzhong-bianqing/
- Sound Magic BianZhong:https://neovst.com/product/bianzhong/
- Soundiron Noah Bells(可作参考):https://soundiron.com/products/noah-bells

### 物理建模与合成
- STK(Synthesis ToolKit):https://ccrma.stanford.edu/software/stk/
- Faust physmodels.lib:https://faustlibraries.grame.fr/libs/physmodels/
- Faust physicalModeling examples:https://faustdoc.grame.fr/examples/physicalModeling/
- CCRMA Lurie Carillon 模态数据:https://ccrma.stanford.edu/~kermit/website/bells.html
- Nathan Ho Exploring Modal Synthesis:https://nathan.ho.name/posts/exploring-modal-synthesis/
- Sound on Sound Synthesizing Bells:https://www.soundonsound.com/techniques/synthesizing-bells
- CCRMA Risset Tubular Bell FM:https://ccrma.stanford.edu/software/clm/compmus/clm-tutorials/fm2.html

### 法律法规
- 中华人民共和国著作权法(2020 修正):https://www.gov.cn/guoqing/2021-10/29/content_5647633.htm
- 国家版权局权威版:https://www.ncac.gov.cn/xxfb/flfg/flfg_532/202103/t20210309_50530.html
- 合理使用四要素研究(汇仲律所):https://www.huizhonglaw.com/Content/2023/12-06/1803006554.html
- 短视频二次创作合理使用研究:https://www.ciplawyer.cn/articles/155828.html
- 网络直播音乐作品法律风险(汇业):https://www.huiyelaw.com/news-1687.html

### Librosa 工作流
- librosa.onset.onset_detect:https://librosa.org/doc/main/generated/librosa.onset.onset_detect.html
- librosa.pyin:https://librosa.org/doc/main/generated/librosa.pyin.html
- Google Groups 切片讨论:https://groups.google.com/g/librosa/c/lxZDuW36b5k

---

**最后一句话建议**:在 2036-12-31 《千古绝响》进入公有领域之前,对于一个**商业性 24/7 直播**,**自制物理/模态合成 SF2 + GeneralUser GS 作为 fallback** 是合规且可立即执行的最优解;如果预算允许且可接受商业音源 EULA,可合法购买 Kong Audio BianZhong Pro 并导出为 SF2。两条路都不依赖存疑的版权灰色地带,可无忧运行多年。