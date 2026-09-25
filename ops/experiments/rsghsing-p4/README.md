# P4 — `rsghsing stream`：UTC 墙钟对齐的 TS 字节泵（Issue #107）

长跑接力进程。壁钟 `T` 播放 **D-1**（daypack 日期）的 `seg-<floor(sod(T)/900)>.ts`，
按实时速率把字节写进**唯一一个常驻** `ffmpeg -f mpegts -i pipe:0 -c copy -f flv <target>`。
零转码、零 segment 拼接进程；切换只发生在输出死亡时（backoff → respawn → 按墙钟位置续传）。

## 采用的决策基线

| # | 决策 | 取值 | 理由 |
| --- | ------ | ------ | ------ |
| 1 | 播放位置 | `idx = floor(seconds_of_day(T_utc) / 900)`，UTC | 卷轴网格本身就是 UTC 对齐的 15 分钟格；本地时区会引入不可复现的偏移 |
| 2 | 日期语义 | 播放 **D-1** 的 daypack；`00:00:00Z` 翻页到新 D-1 的 `idx=0` | 录制管线在整点后仍有一段时间产出 D-1 的段 |
| 3 | 转码 | `-c copy`（h264+aac 直通），单 TS 输入 | 决策基线 #3；不再做 rawvideo/f32le 配对渲染 |
| 4 | segments_dir | 按 **D-1 数据日期** 建目录（`<dir>/<D-1>/seg-NN.ts`） | 与 P3 落盘结构一致，`--segments-dir` 指到 `p3/segments` 根 |

## 文件

```
src/rsghsing/src/stream/schedule.rs   墙钟 → 段映射（纯函数 + 单元测试）
src/rsghsing/src/stream/pump.rs       可注入时钟的实时字节泵（缺段等待，不跳段）
src/rsghsing/src/stream/ffmpeg.rs     ffmpeg 会话：spawn/finish/abort + 日志脱敏
src/rsghsing/src/stream/mod.rs        入口、参数、重启循环、STREAM_SUMMARY
ops/experiments/rsghsing-p4/soak_local.sh       ≥60min 本地浸泡（4 判定）
ops/experiments/rsghsing-p4/rtmps_preflight.sh  60s RTMPS 实推（第 5 判定）
```

## 运行

```bash
# 本地浸泡（默认 3600s，锚定 2026-03-29T11:00:00Z → 播放 2026-03-28 的 seg-44..47）
bash ops/experiments/rsghsing-p4/soak_local.sh

# RTMPS 实推 60s（url/key 只来自 gitignored 的 rsghsing.local.toml，不回显）
bash ops/experiments/rsghsing-p4/rtmps_preflight.sh

# 手动：任意时刻 / 任意模式
src/rsghsing/target/release/rsghsing stream --now 2026-03-29T11:00:00Z \
  --segments-dir /opt/logs/41490/out/rsghsing/p3/segments --duration 60 \
  --output local --local-path /tmp/x.flv
```

`--now` 接受 epoch 秒或 `YYYY-MM-DDTHH:MM:SSZ`（UTC，无本地时区换算）。
RTMPS 模式只从 `[output].rtmps.url` 取目标，该字段仅存在于本地 overlay；ffmpeg 的
stderr 在落盘前会把 url/key 替换成 `rtmps-url`，日志里不会出现密钥。

## 实跑结果（2026-09-25，输出目录 `/opt/logs/41490/out/rsghsing/p4/`）

### 本地 60 min soak（跨 3 个边界）

UTC 窗口 `2026-09-25T13:17:38Z .. 2026-09-25T14:17:38Z`（3600 s），锚定
`--now 2026-03-29T11:00:00Z` → 播放 `2026-03-28/seg-44..47.ts`（D-1 daypack）。

| 判定 | 结果 |
| --- | --- |
| 进程树 | rsghsing(pump) + **唯一一个** ffmpeg，`restarts=0` |
| 边界 | segments 44→45→46→47，`boundaries=3`（11:15 / 11:30 / 11:45） |
| 总时长 | 输出 3600.023 s vs 墙钟 3600 s（err +0.023 s） |
| 帧数 | 108000 = 30×3600（err 0） |
| decode 异常 | 0 行 |
| 时间戳空洞 | 最大 pts 间隔 34.0 ms（@1024.023 s，即 11:17 边界处） |
| 字节 | 1,238,851,756（4×309.7 MB，`-c copy` 直通） |

资源（`/proc` 采样 360 点，10 s 间隔，整棵树）：

| 进程 | CPU%（单核） | RSS avg | RSS peak |
| --- | --- | --- | --- |
| rsghsing（泵） | 0.17 | 4.3 MiB | 4.3 MiB |
| ffmpeg（`-c copy`） | 0.26 | 19.9 MiB | 24.2 MiB |
| **合计** | **0.43** | **24.2 MiB** | **28.5 MiB** |

P0 基线（relay ffmpeg）：CPU 0.1% 单核，RSS avg 17.1 MiB / peak 19.9 MiB。
P4 多出的部分来自 TS 解复用 + FLV 封装，转码仍为零。

### RTMPS 60 s 实推

UTC 窗口 `2026-09-25T13:32:03Z .. 2026-09-25T13:33:03Z`，同一常驻 ffmpeg 会话，
输出 `rtmps://...`（url/key 只来自 gitignored overlay）。ffmpeg 最后一条 stats
`time=00:01:60.97`，即 60 s 窗内持续写入、无一行 error；日志中 url/key 出现次数 **0**
（落盘前被替换为 `rtmps-url`）。资源：泵 0.2% / 4.5 MiB，ffmpeg 2.4% / 18.2 MiB avg
（TLS 加密 + 上行是那 2% 的去处）。

## 已知边界（ponytail 角）

* pacing 按"字节占比 × 900 s"推进，假设段近似 CBR（P3 是 2501k/130k CBR）；
   VBR 段会漂移，届时换 PTS 驱动 pacing。
* 缺段 = 等待 + 计数，永不跳段（水位是 P5 的事）。窗口末端探测下一段会产生一次
   `missing_secs≈0` 的等待，不影响内容，soak 判据只对 >1 s 的真实卡顿判失败。
* 信号只做"收尾"：SIGINT/SIGTERM 让当前 chunk 写完再 finalize，ffmpeg 退出码非零
   且已写入 0 字节时会明确报"没有字节被泵出"，而不是把退出码抛给用户。
