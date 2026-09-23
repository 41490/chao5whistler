# 莫扎特骰子游戏 24/7 直播 — 流量与主机评估

> 基于 YouTube 官方文档的 1080p 直播带宽估算,
> 按不同 FPS 分阶段评估每日流量与主机需求

---

## 1. YouTube 官方直播规格 (2025/2026)

以下数据直接来源于 YouTube 官方帮助文档
`support.google.com/youtube/answer/2853702`:

| 分辨率 / 帧率 | 最低码率 (AV1/H.265) | 最高码率 (AV1/H.265) | 推荐码率 (H.264) |
|---|---|---|---|
| 1080p @60fps | 4 Mbps | 10 Mbps | 12 Mbps |
| 1080p @30fps | 3 Mbps | 8 Mbps | 10 Mbps |
| 720p @60fps | 3 Mbps | 8 Mbps | 6 Mbps |
| 240p–720p @30fps | 3 Mbps | 8 Mbps | 4 Mbps |

其他关键要求:

- 帧率: **最高 60 fps** (文档未明确标注最低 fps, 但表格从 240p@30fps 起)
- 关键帧间隔: **推荐 2 秒, 不超过 4 秒**
- 视频编码: H.264 / H.265 / AV1
- 音频编码: AAC 或 MP3, 立体声 **128 Kbps**
- 协议: RTMP / RTMPS

### 关于最低 FPS

YouTube 官方文档 **没有明确规定最低 FPS 值**。
表格中最低出现的帧率是 30fps。
但实测社区反馈和第三方文档显示:

- YouTube 技术上可以接收低于 30fps 的流 (如 24fps, 15fps, 甚至更低)
- 但 **低于 24fps 的流可能触发"流健康警告"**
- YouTube 的转码系统在 30fps 和 60fps 下工作最优
- 对于我们的场景 (几何图形 + 音乐), 画面变化缓慢, **24fps 甚至 15fps 都可接受**

**结论: 实际可行的最低 fps 约为 15fps, 推荐不低于 24fps, 标准为 30fps。**

---

## 2. 分阶段 FPS 流量估算

### 计算公式

```
每日流量 (GB) = 码率 (Mbps) × 86400 (秒/天) ÷ 8 (bits→Bytes) ÷ 1024 (MB→GB)
             = 码率 (Mbps) × 10.546875
             ≈ 码率 (Mbps) × 10.55
```

加上音频 128 Kbps = 0.128 Mbps, 合并计算。

### 2.1 极限省流方案: 15fps

> 画面以简单几何图形为主, 变化缓慢, 15fps 对观感影响很小

| 参数 | 值 |
|------|------|
| 分辨率 | 1920×1080 |
| 帧率 | 15 fps |
| 视频编码 | H.264 ultrafast |
| 目标视频码率 | 1.5 Mbps (极低, 但几何图形压缩率极高) |
| 音频码率 | 128 Kbps |
| **总码率** | **~1.63 Mbps** |
| **每小时流量** | ~0.73 GB |
| **每日流量** | **~17.2 GB** |
| **每月流量** | **~516 GB** |

为什么 1.5 Mbps 够用? 因为我们的内容是:
- 纯色/渐变背景上的简单几何图形
- 画面大部分区域不变 → H.264 帧间压缩极其高效
- 没有自然场景的高频纹理细节

实测中, 纯几何动画在 1080p 15fps 下 1-2 Mbps 就能获得几乎无损的画质。

### 2.2 经济方案: 24fps

> 接近电影帧率, 流畅度已足够, 是性价比最优的选择

| 参数 | 值 |
|------|------|
| 分辨率 | 1920×1080 |
| 帧率 | 24 fps |
| 视频编码 | H.264 ultrafast |
| 目标视频码率 | 2.5 Mbps |
| 音频码率 | 128 Kbps |
| **总码率** | **~2.63 Mbps** |
| **每小时流量** | ~1.18 GB |
| **每日流量** | **~27.7 GB** |
| **每月流量** | **~832 GB** |

### 2.3 标准方案: 30fps

> YouTube 推荐的标准帧率, 兼容性最好

| 参数 | 值 |
|------|------|
| 分辨率 | 1920×1080 |
| 帧率 | 30 fps |
| 视频编码 | H.264 ultrafast |
| 目标视频码率 | 3.0 Mbps (YouTube 最低线) |
| 音频码率 | 128 Kbps |
| **总码率** | **~3.13 Mbps** |
| **每小时流量** | ~1.41 GB |
| **每日流量** | **~33.0 GB** |
| **每月流量** | **~990 GB ≈ 1 TB** |

如果按 YouTube 推荐的 H.264 码率 (10 Mbps):

| 参数 | 值 |
|------|------|
| 目标视频码率 | 10.0 Mbps (YouTube H.264 推荐) |
| **总码率** | **~10.13 Mbps** |
| **每日流量** | **~106.8 GB** |
| **每月流量** | **~3.2 TB** |

### 2.4 高质量方案: 60fps

> 流畅度最高, 但带宽和 CPU 占用翻倍

| 参数 | 值 |
|------|------|
| 分辨率 | 1920×1080 |
| 帧率 | 60 fps |
| 视频编码 | H.264 ultrafast |
| 目标视频码率 | 4.0 Mbps (YouTube 最低线) |
| 音频码率 | 128 Kbps |
| **总码率** | **~4.13 Mbps** |
| **每小时流量** | ~1.86 GB |
| **每日流量** | **~43.5 GB** |
| **每月流量** | **~1.3 TB** |

如果按 YouTube 推荐的 H.264 码率 (12 Mbps):

| 参数 | 值 |
|------|------|
| 目标视频码率 | 12.0 Mbps |
| **每日流量** | **~128 GB** |
| **每月流量** | **~3.8 TB** |

---

## 3. 综合对比表

| 方案 | FPS | 视频码率 | 总码率 | 每日流量 | 每月流量 | 需要上传带宽 |
|------|-----|---------|--------|---------|---------|------------|
| 极限省流 | 15 | 1.5 Mbps | 1.63 Mbps | ~17 GB | ~516 GB | ≥3 Mbps |
| 经济 | 24 | 2.5 Mbps | 2.63 Mbps | ~28 GB | ~832 GB | ≥5 Mbps |
| **标准 (推荐)** | **30** | **3.0 Mbps** | **3.13 Mbps** | **~33 GB** | **~1 TB** | **≥5 Mbps** |
| 标准 (YouTube推荐码率) | 30 | 10 Mbps | 10.13 Mbps | ~107 GB | ~3.2 TB | ≥15 Mbps |
| 高质量 | 60 | 4.0 Mbps | 4.13 Mbps | ~44 GB | ~1.3 TB | ≥8 Mbps |
| 高质量 (YouTube推荐码率) | 60 | 12 Mbps | 12.13 Mbps | ~128 GB | ~3.8 TB | ≥18 Mbps |

> **上传带宽要求 = 总码率 × 1.5** (留 50% 余量应对网络波动)

---

## 4. 主机评估

### 4.1 CPU 需求 (FFmpeg H.264 编码)

FFmpeg `libx264` 的 CPU 占用取决于 preset 和分辨率:

| preset | 1080p@15fps 单核占用 | 1080p@30fps | 1080p@60fps |
|--------|-------------------|-------------|-------------|
| ultrafast | ~15% | ~25-30% | ~50-60% |
| superfast | ~25% | ~40-50% | ~80-100% |
| veryfast | ~35% | ~60-70% | 需要2核+ |
| medium (默认) | ~50% | ~90-100% | 需要2-3核 |

加上 Rust 程序本身 (rustysynth + tiny-skia) 约 10-20% 单核,
总 CPU 需求:

| 方案 | 推荐最低 CPU | 说明 |
|------|------------|------|
| 15fps ultrafast | 1 vCPU | 总负载约 40% |
| 24fps ultrafast | 1 vCPU | 总负载约 55% |
| **30fps ultrafast** | **1 vCPU** | **总负载约 60%, 推荐 2 vCPU** |
| 60fps ultrafast | 2 vCPU | 总负载约 80% (单核) |

### 4.2 内存需求

| 组件 | 内存占用 |
|------|---------|
| Linux 系统基础 | ~100 MB |
| Rust 程序 (rustysynth + tiny-skia) | ~50 MB |
| SoundFont 文件 (加载到内存) | ~10-60 MB (取决于 SF2 大小) |
| FFmpeg 编码器 | ~50-100 MB |
| 帧缓冲 (1080p RGBA) | ~8 MB (单帧) |
| **总计** | **~300-500 MB** |

**结论: 512 MB 内存勉强可行, 1 GB 内存舒适运行。**

### 4.3 推荐主机配置

#### 方案 A: 极致省钱 (15-24fps)

```
vCPU:    1 核
内存:    512 MB - 1 GB
流量:    500 GB - 1 TB / 月
带宽:    5 Mbps 上传
存储:    10 GB SSD (系统 + 程序)
OS:      Debian 12 / Ubuntu 24.04
```

参考机型与价格:

- **Vultr** High Frequency: 1vCPU/1GB/2TB流量, $6/月
- **Hetzner Cloud** CX22: 2vCPU/4GB/20TB流量, €3.99/月
- **DigitalOcean** Basic: 1vCPU/1GB/1TB流量, $6/月
- **Racknerd** (黑五特惠): 1vCPU/1GB/3TB, ~$10/年
- **BandwagonHost** CN2 GIA: 1vCPU/1GB/1TB, ~$50/年 (对中国大陆友好)

> 注意: 主要瓶颈是**月流量配额**, 不是 CPU 或内存!

#### 方案 B: 标准配置 (30fps)

```
vCPU:    2 核
内存:    1-2 GB
流量:    1-3 TB / 月 (取决于码率选择)
带宽:    10 Mbps 上传
存储:    20 GB SSD
```

参考:

- **Hetzner Cloud** CX22: 2vCPU/4GB/20TB流量, €3.99/月 — **性价比之王**
- **Contabo** VPS S: 4vCPU/8GB/不限流量(200Mbps), €4.99/月
- **Oracle Cloud** ARM Free Tier: 4 OCPU/24GB/免费 — **如果能抢到**

#### 方案 C: 高质量 (60fps)

```
vCPU:    2-4 核
内存:    2-4 GB
流量:    1.5-4 TB / 月
带宽:    20 Mbps 上传
存储:    20 GB SSD
```

---

## 5. 关键洞察与建议

### 5.1 我们的场景非常特殊

莫扎特骰子游戏的直播内容是**简单几何图形 + 古典音乐**:

- 画面复杂度极低 (H.264 压缩效率极高)
- 画面变化缓慢 (帧间差异小)
- 不是游戏/体育等高动态场景

这意味着我们可以大胆使用比 YouTube "推荐值"低得多的码率,
而画质依然优秀。YouTube 推荐的 10 Mbps @1080p30 是为"通用场景"设计的,
对简单几何图形来说, 3 Mbps 就绰绰有余。

### 5.2 最优性价比推荐

```
┌─────────────────────────────────────┐
│ 推荐: 1080p @ 30fps @ 3 Mbps       │
│ 每日流量: ~33 GB                    │
│ 每月流量: ~1 TB                     │
│ 主机: Hetzner CX22 (€3.99/月)      │
│       20TB 流量配额, 完全够用       │
│       2 vCPU, 4GB RAM              │
│       位于欧洲, 到 YouTube 延迟低   │
└─────────────────────────────────────┘
```

### 5.3 如果流量是瓶颈

如果月流量配额吃紧, 有几个压缩手段:

1. **降 FPS 到 24 或 15** — 直接减少 20-50% 流量
2. **用 H.265 替代 H.264** — 同等画质下码率降 30-50%,
   但 CPU 占用翻倍 (需要更多核心)
3. **用 AV1** — 压缩率最优, 但编码极慢, 不推荐实时场景
4. **降分辨率到 720p** — 码率可降到 1.5-2 Mbps,
   每月流量降至 ~500 GB

### 5.4 带宽 vs 流量: 不要混淆

- **带宽** (bandwidth): 瞬时速度, 如 "100 Mbps" — 决定你能不能推得动
- **流量** (transfer): 累计量, 如 "1 TB/月" — 决定你的月账单

许多便宜 VPS 号称 "1 Gbps 带宽" 但只给 1 TB 月流量。
24/7 推流 3 Mbps, 实际只用了 3 Mbps 带宽 (相对 1 Gbps 微不足道),
但月流量恰好用掉 ~1 TB — 刚好卡在配额线上。

选主机时, **月流量配额是第一优先级**, 不是带宽。

---

## 6. FFmpeg 推流命令参考

```bash
# 极限省流: 1080p@15fps, ~1.5Mbps 视频, 适合 500GB/月主机
ffmpeg \
  -f rawvideo -pix_fmt rgba -s 1920x1080 -r 15 -i pipe:0 \
  -f f32le -ar 44100 -ac 2 -i /tmp/audio.pipe \
  -c:v libx264 -preset ultrafast -tune stillimage \
  -b:v 1500k -maxrate 2000k -bufsize 3000k \
  -g 30 -keyint_min 15 \
  -c:a aac -b:a 128k -ar 44100 \
  -f flv "rtmps://a.rtmp.youtube.com/live2/YOUR_KEY"

# 标准方案: 1080p@30fps, ~3Mbps 视频, 适合 1TB/月主机
ffmpeg \
  -f rawvideo -pix_fmt rgba -s 1920x1080 -r 30 -i pipe:0 \
  -f f32le -ar 44100 -ac 2 -i /tmp/audio.pipe \
  -c:v libx264 -preset ultrafast -tune stillimage \
  -b:v 3000k -maxrate 4000k -bufsize 6000k \
  -g 60 -keyint_min 30 \
  -c:a aac -b:a 128k -ar 44100 \
  -f flv "rtmps://a.rtmp.youtube.com/live2/YOUR_KEY"

# 注: -tune stillimage 对我们的几何图形场景特别合适
#     它优化了静态/低运动内容的编码效率
```

---

# Refer.

- **YouTube 官方: 直播编码器设置、码率和分辨率**
  - https://support.google.com/youtube/answer/2853702?hl=en
  - (本文核心数据来源, YouTube Help Center 官方页面)

- **YouTube 官方: RTMPS 加密推流**
  - https://support.google.com/youtube/answer/10364924

- **YouTube 官方: 直播延迟设置**
  - https://support.google.com/youtube/answer/7444635

- **Restream: 直播上传速度指南**
  - https://restream.io/blog/what-is-a-good-upload-speed-for-streaming/

- **Ant Media: 视频分辨率与码率指南**
  - https://antmedia.io/video-resolution-guide-broadcasters/
  - https://antmedia.io/video-bitrate/

- **Dacast: 2026 直播帧率指南**
  - https://www.dacast.com/blog/frame-rate-fps/

- **Resi: 2025 直播编码最佳实践**
  - https://resi.io/blog/encoding-best-practices-for-live-streaming-in-2025/
