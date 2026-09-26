# P5 — `rsghsing sched`：缓冲水位 + systemd units + 并行切换准备（Issue #108）

P4 把"字节泵"做对了（墙钟对齐、零转码、常驻 ffmpeg）；P5 把"谁在什么时候该有哪些文件"
做成一个常驻守护，并把生命周期交给 systemd。**本 Issue 不推流、不 enable 真实服务**：
只验 unit 文件（`systemd-analyze verify`）、混沌脚本干跑和资源门；真实 enable/切换由 CTO 执行
（见文末「并行运行切换清单」）。

## 决策换算（#102 comment-5811679483 已批，本 Issue 只落地不改）

| # | 决策 | 落地 |
| --- | --- | --- |
| 1 | UTC 执行 | `sched` 复用 P4 `stream::schedule` 的 `idx = floor(sod(T)/900)`，调度器与流泵永不失配 |
| 4 | 15 min/段，96 段/天 | 就绪集 = 一天内 96 个 15 min 段 |
| 5 | 段与 raw 只留 1 天 | `retain_days = 1`；当天 + 昨日（正在播放的 D-1）永不删 |
| 10 | systemd 管生命周期 + Rust 管水位 | 4 个 unit + `sched` 守护；**sched 不重启 streamer** |
| 12 | 与 musikalisches/ng46tv 并行 → 资源最小化 | 渲染 `ionice -c3` + `nice -n 10`，并发 ≤2，unit 自身 `Nice=5`/`IOSchedulingClass=idle` |

执行参数：`buffer_segments=4`（就绪 `[idx(now), idx(now)+4]`，最远的就绪段正好在 now+1h）、
`render_jobs=2`、`retain_days=1`、tick 30 s。

## 文件

```text
src/rsghsing/src/sched/water.rs    水位数学（纯函数 + 4 条单测：23:45/00:00 边界、buffer=4、缺段计划）
src/rsghsing/src/sched/queue.rs    渲染派发：限流 <= render_jobs，子进程 ionice -c3 + nice -n10
src/rsghsing/src/sched/retain.rs   保留清理：段目录 + raw 小时包，> retain_days 才删
src/rsghsing/src/sched/metrics.rs  每 tick 一行 JSON（stdout + --metrics-file）
src/rsghsing/src/sched/mod.rs      守护循环 + `--once` 单 tick（混沌脚本用）
ops/systemd/rsghsing-prepare.timer UTC 00:20 触发，Persistent=true
ops/systemd/rsghsing-prepare.service  oneshot + RemainAfterExit，prepare --date yesterday
ops/systemd/rsghsing-sched.service  Type=simple / Restart=always / RestartSec=10
ops/systemd/rsghsing-stream.service Type=simple / Restart=always / RestartSec=5
ops/experiments/rsghsing-p5/chaos.sh        三场景混沌（①②③）
ops/experiments/rsghsing-p5/resource_gate.sh 10min 本地流 + 2 并发渲染的资源门
ops/experiments/rsghsing-p5/unit_dryrun.sh   systemd-analyze verify + ExecStart 干跑（不碰 systemctl）
```

## 运行

```bash
cd src/rsghsing && cargo build --release && cargo test

# 单 tick 干跑（不启动守护）：锚定 2026-03-29T11:00:00Z → 播放 D-1 2026-03-28/seg-44..48
src/rsghsing/target/release/rsghsing sched --once \
  --now 2026-03-29T11:00:00Z \
  --segments-dir /opt/logs/41490/out/rsghsing/p5/segments \
  --archive-dir  /opt/logs/41490/out/rsghsing/p5/raw \
  --metrics-file /opt/logs/41490/out/rsghsing/p5/metrics.jsonl

# 守护模式（= systemd unit 的 ExecStart）
src/rsghsing/target/release/rsghsing sched
```

`--now` 接受 epoch 秒或 `YYYY-MM-DDTHH:MM:SSZ`（UTC，无本地时区换算）。

指标一行示例：

```json
{"date":"2026-03-28","dispatched":[45,46],"freed_bytes":139264,"lead_secs":3600,
 "missing":[],"on_disk":5,"ready":[44,45,46,47,48],"removed":[".../2026-03-26"],
 "rendered":[{"index":45,"secs":359.3}],"rendered_total":5,"removed_total":4,
 "ts":1774782000,"utc":"2026-03-29T11:00:00Z"}
```

## 混沌与资源门

```bash
bash ops/experiments/rsghsing-p5/chaos.sh          # ①②③ 全过才 exit 0
bash ops/experiments/rsghsing-p5/resource_gate.sh  # 10min 流 + 2 并发渲染
bash ops/experiments/rsghsing-p5/unit_dryrun.sh    # verify + ExecStart 干跑
```

两个脚本都只在 **P5 自己的段副本** `/opt/logs/41490/out/rsghsing/p5/segments/` 上做删除/恢复，
P3 原始产物 `/opt/logs/41490/out/rsghsing/p3/segments/`（P4/审计还在用）是只读输入，绝不写入。

| 场景 | 做法 | 判据 |
| --- | --- | --- |
| ① 缺段补渲染 | 删 P5 副本的 `seg-46.ts`（就绪窗口中段） | `sched` 补渲染回 `[44..48]`，`on_disk=5`，`lead_secs=3600` |
| ② streamer 被杀 | SIGKILL streamer → 重启（= systemd `Restart=always` 路径）；再 SIGKILL 它的 ffmpeg 子进程 | 重启后从正确墙钟段续播（`idx=44` + `skip_bytes`），ffmpeg 自动 respawn（`restarts=1`），输出时长不塌 |
| ③ 保留清理 | 造 3 天前/2 天前的段目录与 raw 小时包 | 只删 >1 天的；正在播放的 D-1 与当天一个字节不动 |

资源门判据：直播期全栈（sched 树 + stream 树）单核 CPU ≤30%、RSS ≤400MB、渲染进程 nice ≥10。

## 并行运行切换清单（CTO 执行）

> ghSinging 继续跑，rsghsing 并行观察 N 天；N 天观察在 #102 跟踪，不在本 Issue 验收内。

### 1. enable 步骤

```bash
cd /opt/src/41490/chao5whistler
make -C src/rsghsing install          # release 产物 -> ops/bin/rsghsing
install -d ~/.config/systemd/user
cp ops/systemd/rsghsing-{prepare.timer,prepare.service,sched.service,stream.service} \
   ~/.config/systemd/user/
systemctl --user daemon-reload

# 顺序：先备数据（幂等），再起守护，最后起流泵
systemctl --user start  rsghsing-prepare.service   # oneshot：D-1 daypack
systemctl --user enable --now rsghsing-prepare.timer
systemctl --user enable --now rsghsing-sched.service
systemctl --user enable --now rsghsing-stream.service
```

RTMPS 目标只在 gitignored 的 `src/rsghsing/rsghsing.local.toml`（`[output].mode=rtmps` +
`[output.rtmps].url`）；unit 文件与库里都不出现密钥。

### 2. 观察指标

```bash
journalctl --user -u rsghsing-sched -f    # 水位/队列/清理 + 每 tick 一行 JSON
journalctl --user -u rsghsing-stream -f   # STREAM_SUMMARY / ffmpeg 重启
```

| 指标 | 健康值 | 出处 |
| --- | --- | --- |
| `missing` | 每个 tick 结束后为 `[]` | sched 指标行 |
| `rendered_total` | 每天 ≈ 96（2 jobs 时 ≈ 6h 工作量） | sched 指标行 |
| `removed_total` | 每天 >0（环形清理在工作） | sched 指标行 |
| `on_disk` | 5（= buffer_segments+1） | sched 指标行 |
| 全栈 CPU | ≤30% 单核（P4 实测 0.4%） | `resource_gate.sh` |
| 全栈 RSS | ≤400MB（P4 实测 24MiB） | `resource_gate.sh` |
| 渲染 nice | ≥10 | `ps -o ni` / resource_gate |
| streamer `restarts` | 偶发（网络抖动），不持续增长 | STREAM_SUMMARY |

### 3. 切换判据（并行观察 N 天后）

全部满足才切 ghsingo → rsghsing：

1. `sched` 连续 N 天 `missing` 归零，无 `render segment` 失败（journal 无 `exited with`）；
2. 跨过至少一次 00:00 UTC 换日：新 D-1 的 `seg-00.ts` 先就绪、旧日段才被清（指标行
   `removed` 里不出现正在播放的日期）；
3. 直播期资源门全绿（CPU ≤30% 单核、RSS ≤400MB、渲染 nice ≥10）；
4. `rsghsing-stream.service` 无持续重启风暴（`restarts` 不随时间单调增长）。

### 4. 回滚

回滚 = **ghsingo 继续跑**，不需要任何数据抢救：

```bash
systemctl --user disable --now rsghsing-stream.service
systemctl --user disable --now rsghsing-sched.service
systemctl --user disable --now rsghsing-prepare.timer
# ghsingo 的 unit 不受影响，继续直播；P5 段副本与 raw 保留 retain_days 天
```

段与 raw 都是可再生产物（`prepare` + `render segment` 可从 daypack 重建），回滚不丢数据。
