# rsghsing P0 — 基线与消融测量（Issue #103）

只读测量 + 原型脚本。**不改任何既有 ghsingo 源码/配置**；唯一新增的源码文件是
`src/ghsingo/internal/video/renderer_bench_test.go`（add-only bench，任务 3b 用）。

## 运行

```bash
bash ops/experiments/rsghsing-p0/run_all.sh      # 全量，约 15 分钟，可重跑
bash ops/experiments/rsghsing-p0/verify_relay.sh # 接力验收（退出码 0 = 通过）
```

产物一律写 `/opt/logs/41490/out/rsghsing/p0/`（`relay.flv` / `relay.log` /
`segments/` / 各 `*.csv` `*.json` `*.log`），仓库内不落生成物。

## 组成

| 文件 | 作用 |
| --- | --- |
| `run_all.sh` | 任务 1–4 全流程 + 四块摘要（`BASELINE` / `DOWNLOAD` / `THROUGHPUT_VERDICT:` / `S1_RELAY`） |
| `verify_relay.sh` | 接力验收：段时长和 vs `relay.flv` ≤0.2s、日志无异常、A+V 双流 |
| `sample_proc.py` | `/proc` 采样器，替代本机缺失的 `pidstat -rud`（RSS + CPU%，单核归一） |
| `pump.py` | 按墙钟配速的字节泵：预渲染 `.ts` 段 → 持久 `ffmpeg -c copy -f flv` |
| `configs/ghsingo-p0.toml` | ghsingo 配置副本：绝对输入路径 + 输出全部指向 `/opt/logs/...`，`[schedule] timezone="UTC"` 预留键 |

## 环境变量（默认值即本次交付所用）

`LIVE_SECS=300`（任务 1，≥5m）、`RENDER_SECS=300`（任务 3c/4 源片段）、
`ENC_SECS=600`（任务 3a）、`SEG_SECS=150`（任务 4 段长；生产目标 900s/15min）。

## 已知边界

- 本机无 `sysstat`，CPU/RSS 用 `/proc` 直读（数值同 `pidstat -rud`）。
- 无外网，任务 2 使用既有样本 `ops/assets/2026-03-28-{0..23}.json.gz`（Issue 允许），
  下载步骤本身未测。
- 任务 4 为原型规模：2×150s，纯色背景（决策基线 #7）+ 任务 3c 的真实 v2 音频。
