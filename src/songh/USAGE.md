# songh Usage

本文档面向 `songh` stage7 live runtime 的人工操作。

## 1. 当前状态

以 2026-03-26 远端 `main` 为准，`songh` 当前状态已经不是旧的“loop stage6 `offline_preview.mp4` 推流 baseline”。

当前事实：

- 远端 `main` 当前指向 `62786763edcce1c82b66fa90a9cb852838feaf3c`
- 对应提交标题：`feat(songh): add live stage7 runtime and fallback`
- `ops/out/songh-stage7-stream-bridge/stream_bridge_manifest.json` 当前已是 `schema_version = stage7.stream_bridge.v2`
- manifest 中 `live_runtime.generator_mode = tick_live_generator`
- `run-stream-bridge` 当前会由 Rust 持续生成 raw RGBA frame + PCM chunk，经 FIFO 送给 ffmpeg，而不是靠 `-stream_loop offline_preview.mp4`
- fallback synthetic 已接到 replay/audio/video/live runtime

当前仓库里已有的样本工件状态：

- `ops/out/songh-stage7-stream-bridge/stage7_bridge_validation_report.json` 当前为 `status = passed`
- `ops/out/songh-stage7-stream-bridge/logs/stage7_bridge_preflight_report.json` 当前样本为一次预期失败的本地验证：
  - `target = rtmp://127.0.0.1:9/<redacted>`
  - `failed_check_id = tcp_connectivity`
- `ops/out/songh-stage7-stream-bridge/logs/stage7_bridge_runtime_report.json` 对应记录为：
  - `status = preflight_failed`
  - `attempts_total = 0`

这说明：

- stage7 构建与本地 smoke 基线已冻结
- preflight 报告链路已经可用
- 但正式平台的 `300s / 8h / forever` 仍需要 operator 提供真实 `RTMP/RTMPS` ingest URL

## 2. 日常准备顺序

每次要开播或做真实平台验证前，建议至少先做一次：

```bash
cargo test --manifest-path src/songh/Cargo.toml
make -C src/songh stage7-build-fixture
```

如果只关心 stage7 侧的 live 工件刷新，第二条通常已经够用；它会重新生成：

- `ops/out/songh-stage7-stream-bridge/offline_preview.mp4`
- `ops/out/songh-stage7-stream-bridge/stage7_bridge_smoke.flv`
- `ops/out/songh-stage7-stream-bridge/stream_bridge_manifest.json`
- `ops/out/songh-stage7-stream-bridge/stream_bridge_ffmpeg_args.json`
- `ops/out/songh-stage7-stream-bridge/stage7_failure_taxonomy.json`
- `ops/out/songh-stage7-stream-bridge/stage7_bridge_validation_report.json`

通过判据：

- `ops/out/songh-stage7-stream-bridge/stage7_bridge_validation_report.json`
  - 必须是 `status = passed`

可快速检查：

```bash
python3 - <<'PY'
import json
from pathlib import Path

path = Path("ops/out/songh-stage7-stream-bridge/stage7_bridge_validation_report.json")
payload = json.loads(path.read_text(encoding="utf-8"))
print(payload["status"])
PY
```

## 2a. 编码参数变更后：重新 prepare + 300s 推流验证

当 `OutputEncodeConfig`（GOP / 码率 / 采样率等）或 ffmpeg 参数构建逻辑发生变更后，
已冻结的 stage7 产物（`stream_bridge_ffmpeg_args.json` 等）不会自动更新。
必须手动重新 prepare 并验证，否则推流仍使用旧参数。

### 步骤 1：重新编译

```bash
cargo build --manifest-path src/songh/Cargo.toml
```

确认编译成功，无 error。

### 步骤 2：重新 prepare stage7 工件

```bash
make -C src/songh stage7-build-fixture
```

或通过 systemd：

```bash
systemctl --user start songh-live-prepare.service
journalctl --user -u songh-live-prepare.service -f
```

完成后检查冻结产物已刷新：

```bash
# 确认 validation 通过
python3 -c "
import json, pathlib
r = json.loads(pathlib.Path('ops/out/songh-stage7-stream-bridge/stage7_bridge_validation_report.json').read_text())
print('validation:', r['status'])
assert r['status'] == 'passed', 'validation must be passed before streaming'
"

# 确认 ffmpeg args 包含新参数（如 -g 60）
grep -o '\-g [0-9]*' ops/out/songh-stage7-stream-bridge/stream_bridge_ffmpeg_args.json
# 预期输出：-g 60
```

### 步骤 3：确认 stream_url 配置

检查私有配置中的 `stream_url`：

```bash
grep stream_url ~/.config/songh/songh-systemd.toml
```

YouTube RTMPS 正确格式为：

```
rtmps://a.rtmps.youtube.com/live2/<stream-key>
```

注意子域名是 `a.rtmps.youtube.com`（带 `s`），不是 `a.rtmp.youtube.com`。

### 步骤 4：300s 推流验证

```bash
systemctl --user start songh-live-300s.service
```

同时打开两个窗口：

**窗口 A — 观察 ffmpeg 日志：**

```bash
journalctl --user -u songh-live-300s.service -f
```

正常情况下 ffmpeg 无 stderr 输出（`-loglevel error`）。如果看到输出，说明有编码或连接问题。

**窗口 B — 观察 YouTube：**

1. 打开 YouTube Studio → 直播控制室
2. 确认"直播状态"从"离线"变为"实时"
3. 确认预览画面正常显示（约 10-30 秒延迟）
4. 观察码率指示器稳定在 ~4000 kbps

### 步骤 5：检查报告

300 秒结束后（或手动 `systemctl --user stop songh-live-300s.service`），查看报告：

```bash
# preflight 报告 — 所有 check 应为 passed
python3 -c "
import json, pathlib
r = json.loads(pathlib.Path('ops/out/songh-stage7-stream-bridge/logs/stage7_bridge_preflight_report.json').read_text())
for c in r.get('checks', []):
    print(f\"  {c['check_id']}: {c['status']}\")
"

# runtime 报告 — status 应为 completed 或 budget_exhausted
python3 -c "
import json, pathlib
r = json.loads(pathlib.Path('ops/out/songh-stage7-stream-bridge/logs/stage7_bridge_runtime_report.json').read_text())
print('status:', r['status'])
print('attempts:', r.get('attempts_total', 0))
print('seconds_generated:', r.get('seconds_generated', 0))
"
```

验证通过标准：

- preflight 所有 check 为 `passed`
- runtime status 为 `completed` 或 `budget_exhausted`（300s 到期正常退出）
- YouTube 侧确认收到并显示了画面

## 3. 不用手工 export 的 systemd 入口

`songh` 已补 `systemd --user` 封装，operator 不再需要手工 `export SONGH_RTMP_URL`。

仓库内模板：

```text
ops/systemd/songh.toml
```

推荐先复制到私有路径再写入真实 ingest URL：

```bash
mkdir -p ~/.config/songh
cp ops/systemd/songh.toml ~/.config/songh/songh-systemd.toml
chmod 600 ~/.config/songh/songh-systemd.toml
```

至少替换：

- `service.stream_url`

然后安装 unit：

```bash
make -C src/songh systemd-user-install \
  SYSTEMD_CONFIG="$HOME/.config/songh/songh-systemd.toml"
```

默认会注册 4 个 unit：

- `songh-live-prepare.service`
- `songh-live-300s.service`
- `songh-live-8h.service`
- `songh-live-forever.service`

## 4. 用 systemd 做准备和本地检验

准备 stage7 工件并刷新本地 smoke：

```bash
systemctl --user start songh-live-prepare.service
```

这个 unit 内部会执行 `build-stream-bridge`，并要求：

- `ops/out/songh-stage7-stream-bridge/stream_bridge_manifest.json` 存在
- `ops/out/songh-stage7-stream-bridge/stage7_bridge_validation_report.json` 为 `passed`

观察 prepare 日志：

```bash
journalctl --user -u songh-live-prepare.service -f
```

## 5. 用 systemd 做 300 秒真实平台短时验证

短时验证入口：

```bash
systemctl --user start songh-live-300s.service
```

这个 unit 的语义是：

- loop mode 固定为 `infinite`
- runtime budget 固定为 `300` 秒
- 运行前会先确认本地 `stage7_bridge_validation_report.json` 仍然是 `passed`

建议在平台侧同时观察是否真正收到流。

日志入口：

```bash
journalctl --user -u songh-live-300s.service -f
```

JSON 报告入口：

- `ops/out/songh-stage7-stream-bridge/logs/stage7_bridge_preflight_report.json`
- `ops/out/songh-stage7-stream-bridge/logs/stage7_bridge_runtime_report.json`
- `ops/out/songh-stage7-stream-bridge/logs/stage7_bridge_exit_report.json`

## 6. 用 systemd 做 8 小时和持续直播

8 小时 soak：

```bash
systemctl --user start songh-live-8h.service
```

持续直播：

```bash
systemctl --user start songh-live-forever.service
```

这两个 unit 的差别只在 runtime budget：

- `songh-live-8h.service`
  - `max_runtime_seconds = 28800`
- `songh-live-forever.service`
  - 不设置 runtime budget

统一观察方式：

```bash
journalctl --user -u songh-live-8h.service -f
```

```bash
journalctl --user -u songh-live-forever.service -f
```

## 7. 排障顺序

发生失败时，固定按下面顺序看：

1. `journalctl --user -u songh-live-300s.service -n 200 --no-pager`
2. `ops/out/songh-stage7-stream-bridge/logs/stage7_bridge_preflight_report.json`
3. `ops/out/songh-stage7-stream-bridge/logs/stage7_bridge_runtime_report.json`
4. `ops/out/songh-stage7-stream-bridge/logs/stage7_bridge_exit_report.json`
5. `ops/out/songh-stage7-stream-bridge/logs/stage7_bridge_latest.stderr.log`

常见含义：

- `failed_check_id = protocol_support`
  - ffmpeg 不支持目标协议
- `failed_check_id = dns_resolution`
  - 域名无法解析
- `failed_check_id = tcp_connectivity`
  - TCP 无法建立连接
- `failed_check_id = publish_probe`
  - 已过 DNS/TCP，但平台握手/认证/ingest 行为失败

## 8. 当前边界

当前 `songh` 已经具备：

- 真正的按 tick stage7 live runtime
- fallback synthetic 接线
- 本地 smoke 工件
- preflight / runtime / exit 报告
- `systemd --user` 下的 `prepare / 300s / 8h / forever` 固定入口

当前仍未覆盖：

- 真实平台短时 publish 的仓库内成功样本
- 类似 `musikalisches stage8-readiness-check` 的独立 readiness gate
- 更真实的 voice/sample backend
