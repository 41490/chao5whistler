# Stage8 Real Soak Ops Guide

日期: `2026-03-24`  
主机: `x86_64-unknown-linux-gnu`

## 1. 目标

本指南用于在当前仓库内组织 stage8 的人工真实检验。

目标分 3 步：

1. 确认本地 `ffmpeg/ffprobe` 具备 `rtmps` output
2. 用真实平台 host 做短时 preflight / publish 验证
3. 启动 `8h` 起步的真实 soak，并留存运维样本

## 2. 进入前提

必须先满足：

- 仓库位于最新 `main`
- `ops/bin/ffmpeg` 与 `ops/bin/ffprobe` 已准备好
- `stage7-bridge-check` 通过
- `stage7-soak-check` 通过
- `stage8-readiness-check` 通过
- 运维已拿到真实 `MUSIKALISCHES_RTMP_URL`

建议先确认当前 bookmark：

```bash
jj log -r 'main | @ | @-' --limit 5
```

## 3. 本地 toolchain 构建与确认

构建 repo-managed ffmpeg：

```bash
make -C src/musikalisches stage7-ffmpeg-build
```

校验 capability：

```bash
make -C src/musikalisches stage7-ffmpeg-check
```

人工确认关键点：

```bash
ops/bin/ffmpeg -protocols | sed -n '1,120p'
ops/bin/ffmpeg -version | sed -n '1,4p'
```

必须看到：

- output protocols 包含 `rtmps`
- configure line 包含 `--enable-openssl`
- configure line 包含 `--enable-libx264`

## 4. 重新生成 stage6 / stage7 工件

```bash
make -C src/musikalisches stage6-video-render
make -C src/musikalisches stage6-video-render-check
make -C src/musikalisches stage7-bridge
make -C src/musikalisches stage7-bridge-check
make -C src/musikalisches stage7-soak-check
make -C src/musikalisches stage8-readiness-check
```

建议额外核对 manifest：

```bash
python3 - <<'PY'
import json
from pathlib import Path
video = json.loads(Path("ops/out/video-render/video_render_manifest.json").read_text())
bridge = json.loads(Path("ops/out/stream-bridge/stream_bridge_manifest.json").read_text())
print("stage6 ffmpeg_bin =", video["mp4_generation"].get("ffmpeg_bin"))
print("stage6 ffprobe_bin =", video["mp4_generation"].get("ffprobe_bin"))
print("stage7 live ffmpeg_bin =", bridge["live_command"].get("ffmpeg_bin"))
print("stage7 smoke ffmpeg_bin =", bridge["smoke_generation"].get("ffmpeg_bin"))
print("stage7 smoke ffprobe_bin =", bridge["smoke_generation"].get("ffprobe_bin"))
PY
```

预期：

- 都指向 `ops/bin/ffmpeg` / `ops/bin/ffprobe`
- `ops/out/stream-bridge/stage8_ops_readiness_report.json` 为 `status = passed`

## 5. 短时 preflight 验证

### 5.1 假域名回归

这一步只用于确认当前错误已越过 `protocol_support`。

```bash
export MUSIKALISCHES_RTMP_URL='rtmps://nonexistent.invalid/live2/test-key'
export MUSIKALISCHES_STAGE7_MAX_RUNTIME_SECONDS=10
ops/out/stream-bridge/run_stage7_stream_bridge.sh || true
sed -n '1,220p' ops/out/stream-bridge/logs/stage7_bridge_preflight_report.json
```

预期：

- `protocol_support = passed`
- `dns_resolution = failed`
- 分类为 `network_jitter`
- 控制台首行直接出现 `preflight failed: dns_resolution; see ...stage7_bridge_preflight_report.json and ...stage7_bridge_preflight.stderr.log`

### 5.2 真实平台 host 短时试探

先用平台真实 host + 无效 key 做一次 publish probe，确认 DNS/TCP/远端握手路径可达：

```bash
export MUSIKALISCHES_RTMP_URL='rtmps://a.rtmps.youtube.com/live2/test-key'
export MUSIKALISCHES_STAGE7_MAX_RUNTIME_SECONDS=10
ops/out/stream-bridge/run_stage7_stream_bridge.sh || true
sed -n '1,260p' ops/out/stream-bridge/logs/stage7_bridge_preflight_report.json
sed -n '1,160p' ops/out/stream-bridge/logs/stage7_bridge_preflight.stderr.log
```

预期至少满足：

- `protocol_support = passed`
- `dns_resolution = passed`
- `tcp_connectivity = passed`
- `publish_probe` 进入远端后才失败

说明：

- 如果这里失败于 `handshake_failure` 或 `auth_failure`，已经说明本机 RTMPS 栈工作正常，剩下是平台侧 URL/证书/权限细节
- 如果这里退回 `ingest_configuration_failure`，说明本地 ffmpeg 构建没有真正生效
- 这里保留 `MUSIKALISCHES_STAGE7_MAX_RUNTIME_SECONDS=10` 只是为了受控预检；它的语义是整体 wrapper runtime budget，不是长期直播参数

## 6. 真实 URL 人工 preflight

拿到真实 `MUSIKALISCHES_RTMP_URL` 后，先做短时人工预检：

```bash
export MUSIKALISCHES_RTMP_URL='rtmps://...<real-ingest>...'
export MUSIKALISCHES_STAGE7_LOOP_MODE=infinite
export MUSIKALISCHES_STAGE7_MAX_RUNTIME_SECONDS=120
ops/out/stream-bridge/run_stage7_stream_bridge.sh || true
```

立刻检查：

```bash
sed -n '1,260p' ops/out/stream-bridge/logs/stage7_bridge_preflight_report.json
sed -n '1,220p' ops/out/stream-bridge/logs/stage7_bridge_runtime_report.json
sed -n '1,200p' ops/out/stream-bridge/logs/stage7_bridge_latest.stderr.log
sed -n '1,220p' ops/out/stream-bridge/logs/stage7_bridge_exit_report.json
```

控制台首查约定：

- 如果命令直接失败，先看控制台首行的 `preflight failed: <check_id>` 或 `stage7 summary: ...`
- 真正打开文件时，第一优先级是 `stage7_bridge_preflight_report.json`
- 第二优先级是 `stage7_bridge_preflight.stderr.log`

判定：

- 若 `preflight_report.status = preflight_passed`，即可进入正式 soak
- 若 `exit_class_id = auth_failure`，先修正真实 key / 权限
- 若 `exit_class_id = handshake_failure`，先排查平台 TLS / 证书 / 入口 host
- 若 `exit_class_id = network_jitter`，先排查出口网络

## 7. 正式 stage8 soak

### 7.1 启动

推荐先跑 `8h`：

```bash
export MUSIKALISCHES_RTMP_URL='rtmps://...<real-ingest>...'
export MUSIKALISCHES_STAGE7_LOOP_MODE=infinite
ops/out/stream-bridge/run_stage7_stream_bridge.sh
```

如需后台保活并留控制台日志：

```bash
export MUSIKALISCHES_RTMP_URL='rtmps://...<real-ingest>...'
export MUSIKALISCHES_STAGE7_LOOP_MODE=infinite
nohup ops/out/stream-bridge/run_stage7_stream_bridge.sh \
  > ops/out/stream-bridge/logs/stage8_soak_console.log 2>&1 &
echo $! > ops/out/stream-bridge/logs/stage8_soak.pid
```

说明：

- 正式 stage8 soak 不建议设置 `MUSIKALISCHES_STAGE7_MAX_RUNTIME_SECONDS`
- 若必须做定时演练，请显式认识到它会在预算到时退出，且这属于预期行为

### 7.2 运行中观察

推荐观察命令：

```bash
tail -n 80 ops/out/stream-bridge/logs/stage7_bridge_latest.stderr.log
```

```bash
sed -n '1,220p' ops/out/stream-bridge/logs/stage7_bridge_exit_report.json
```

```bash
ps -fp "$(cat ops/out/stream-bridge/logs/stage8_soak.pid)"
```

### 7.3 停止

前台运行：

- 直接 `Ctrl-C`

后台运行：

```bash
kill -INT "$(cat ops/out/stream-bridge/logs/stage8_soak.pid)"
```

## 8. 结束后汇总

结束后必须留存：

```bash
sed -n '1,260p' ops/out/stream-bridge/logs/stage7_bridge_preflight_report.json
sed -n '1,260p' ops/out/stream-bridge/logs/stage7_bridge_runtime_report.json
sed -n '1,260p' ops/out/stream-bridge/logs/stage7_bridge_exit_report.json
```

如有多次重连，还应检查：

```bash
find ops/out/stream-bridge/logs -maxdepth 1 -name 'stage7_bridge_attempt_*' | sort
```

建议人工记录以下 8 项：

1. 使用的真实 ingest 平台与 host
2. preflight 是否一次通过
3. soak 计划时长与实际运行时长
4. 退出分类 `exit_class_id`
5. `attempts_total`
6. 是否出现 retry/backoff
7. 是否观察到 drift / 卡顿 / 远端断流
8. 现场控制台日志与报告文件位置

## 9. 最小结论模板

建议在 issue 中按以下格式汇报：

```text
- stage8 soak host: <platform/host>
- preflight: passed/failed
- runtime duration: <seconds/hours>
- attempts_total: <n>
- final_exit_class_id: <class>
- drift observation: none / <details>
- operator notes: <details>
```
