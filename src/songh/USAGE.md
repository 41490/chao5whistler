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
