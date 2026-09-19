# Musikalisches Usage

本文档对应 `docs/plans/260324-stage8-real-soak-ops-guide.md`，面向直播前的日常人工操作。

目标有 3 个：

- 确认 stage5/stage6/stage7 工具都能正常构建并通过校验
- 在正式直播前先生成本地离线 `.mp4` 和本地 smoke `.flv`，人工检查音乐和动画片段
- 在拿到真实直播地址后，明确应该修改哪个配置、设置哪个环境变量，才能开始推流

## 1. 日常直播前最小检查顺序

建议每次直播前至少执行一次：

```bash
make -C src/musikalisches stage5-build
make -C src/musikalisches stage5-test
make -C src/musikalisches stage7-ffmpeg-check
make -C src/musikalisches stage7-all
make -C src/musikalisches stage8-readiness-check
```

其中：

- `stage5-build` 会重建 release 二进制
- `stage5-test` 会跑 Rust 测试
- `stage7-ffmpeg-check` 会确认 `ops/bin/ffmpeg` / `ops/bin/ffprobe` 具备 `rtmps` output、`libx264` 和本地 `flv` smoke 编码能力
- `stage7-all` 会串起 `stage5-sf2 + stage6-video-render-sf2 + stage7 bridge` 的默认 live 构建与校验
- `stage8-readiness-check` 会把真实 live soak 前的 stage7 contract、repo toolchain、运行入口脚本和 stage8 ops 约定收成独立 readiness report
- 默认 formal live baseline 已冻结为 `stage5-sf2`，且每个组合保留 `16` cycles

如果你只想做日常快速回归，不重建 release，也可以直接执行：

```bash
make -C src/musikalisches stage7-ffmpeg-check
make -C src/musikalisches stage7-all
```

如果这次是继续推进 issue #9 的多层声景链路，在进入 stage5 mix bus 之前，先单独冻结并校验资产包：

```bash
make -C src/musikalisches soundscape-assets-generate
make -C src/musikalisches soundscape-assets-check
```

这一步只验证 manifest / license / hash / loop duration contract，不会改动现有 stage7 live 基线。

从 issue #9 `P3` 开始，`stage5-stream` / `stage5-sf2` 默认还会继续做一层 soundscape mix bus：

- 会按 `combination_id` 从 curated registration 池里选一个 organ profile
- 会从 `soundscape_asset_pack_v1.json` 中确定一组 `drone + ambient`
- 会把三层结果统一混进 stage5 的 `offline_audio.wav`
- 会额外生成 `soundscape_selection.json`

## 2. 检查通过的判据

以下报告文件都应为 `status = passed`：

- `ops/out/ffmpeg-rtmps-check/stage7_ffmpeg_toolchain_validation_report.json`
- `ops/out/video-stub-sf2/stage6_validation_report.json`
- `ops/out/video-render-sf2/stage6_render_validation_report.json`
- `ops/out/stream-bridge/stage7_bridge_validation_report.json`
- `ops/out/stream-bridge/stage7_soak_validation_report.json`
- `ops/out/stream-bridge/stage8_ops_readiness_report.json`

可直接用下面的命令快速查看：

```bash
python3 - <<'PY'
import json
from pathlib import Path

files = [
    "ops/out/ffmpeg-rtmps-check/stage7_ffmpeg_toolchain_validation_report.json",
    "ops/out/video-stub-sf2/stage6_validation_report.json",
    "ops/out/video-render-sf2/stage6_render_validation_report.json",
    "ops/out/stream-bridge/stage7_bridge_validation_report.json",
    "ops/out/stream-bridge/stage7_soak_validation_report.json",
    "ops/out/stream-bridge/stage8_ops_readiness_report.json",
]
for item in files:
    path = Path(item)
    if not path.exists():
        print(f"MISSING {item}")
        continue
    payload = json.loads(path.read_text(encoding="utf-8"))
    print(f"{item}: {payload.get('status')}")
PY
```

只要有任意一个不是 `passed`，都不应直接进入正式直播。

## 3. 直播前如何生成离线 `.mp4`

生成本地离线预览视频：

```bash
make -C src/musikalisches stage5-sf2 LOOP_COUNT=16
make -C src/musikalisches stage5-sf2-check
make -C src/musikalisches stage6-video-render-sf2
make -C src/musikalisches stage6-video-render-check-sf2
```

默认输出目录：

```text
ops/out/video-render-sf2
```

重点文件：

- `ops/out/stream-sf2/soundscape_selection.json`
- `ops/out/video-render-sf2/offline_preview.mp4`
- `ops/out/video-render-sf2/offline_frame_sequence.json`
- `ops/out/video-render-sf2/video_render_manifest.json`
- `ops/out/video-render-sf2/stage6_render_validation_report.json`

其中 `ops/out/stream-sf2/soundscape_selection.json` 会记录本次 stage5 实际选中的：

- `registration`
- `drone asset`
- `ambient asset`
- `mix_bus` peak / RMS / gain guardrail 摘要

注意：

- `offline_preview.mp4` 是离线人工预览视频，当前主要用于检查动画和画面节奏
- 该 `mp4` 是 stage6 产物，不是正式直播输出
- 当前 `offline_preview.mp4` 是 video-only 预览，不含正式直播音轨
- 默认规格是 `1280x720 @ 30fps`

关于“看起来卡住 5 分钟”：

- `stage6-video-render` 会生成整段帧序列，再调用 `ffmpeg` 编码 `offline_preview.mp4`
- 你这次的默认输出是 `1440` 帧、`1280x720@30`，属于正常的离线编码工作量
- 脚本只在编码完成后统一打印 `stage6 video render built` 摘要，所以中间几分钟没有新输出，不代表死锁

## 4. 直播前如何生成本地 `.flv` smoke

生成 stage7 本地 smoke：

```bash
make -C src/musikalisches stage7-bridge
make -C src/musikalisches stage7-bridge-check
make -C src/musikalisches stage7-soak-check
```

默认输出目录：

```text
ops/out/stream-bridge
```

重点文件：

- `ops/out/stream-bridge/stage7_bridge_smoke.flv`
- `ops/out/stream-bridge/stream_bridge_manifest.json`
- `ops/out/stream-bridge/run_stage7_stream_bridge.sh`
- `ops/out/stream-bridge/stage7_bridge_validation_report.json`
- `ops/out/stream-bridge/stage7_soak_validation_report.json`

`stage7_bridge_smoke.flv` 的用途是本地验证 stage7 的音视频封装链路是否正常，不等价于真实推流。
当前默认 smoke 输入来自 `ops/out/stream-sf2/offline_audio.wav` 与 `ops/out/video-render-sf2/offline_preview.mp4`。

## 5. 正式推流前要改哪个配置

默认推流配置文件是：

```text
src/musikalisches/runtime/config/stage7_default_bridge_profile.json
```

关键字段在 `ingest` 段：

```json
{
  "protocol": "rtmps",
  "container": "flv",
  "stream_url_env": "MUSIKALISCHES_RTMP_URL",
  "stream_url_example": "rtmps://a.rtmps.youtube.com/live2/<stream-key>"
}
```

这表示：

- 默认协议是 `rtmps`
- 默认封装是 `flv`
- 真实直播地址不是写死在仓库里，而是通过环境变量 `MUSIKALISCHES_RTMP_URL` 注入

也就是说，要开始真实推流，必须提供完整直播 URL，例如：

```bash
export MUSIKALISCHES_RTMP_URL='rtmps://a.rtmps.youtube.com/live2/<stream-key>'
```

如果平台规格不同，应该复制一份新的 bridge profile，再通过 `STAGE7_BRIDGE_PROFILE=/path/to/profile.json` 覆盖默认 profile，而不是直接把密钥写进仓库文件。

## 6. 正式开始推流

在已经通过 stage7 校验、并且拿到真实直播 URL 后，按下面顺序执行：

```bash
make -C src/musikalisches stage7-ffmpeg-check
make -C src/musikalisches stage5-sf2 LOOP_COUNT=16
make -C src/musikalisches stage5-sf2-check
make -C src/musikalisches stage6-video-render-sf2
make -C src/musikalisches stage6-video-render-check-sf2
make -C src/musikalisches stage7-bridge
make -C src/musikalisches stage7-bridge-check
make -C src/musikalisches stage7-soak-check
```

然后设置环境变量并启动。真实 URL 只通过环境变量注入，不要写进仓库文件：

```bash
export MUSIKALISCHES_RTMP_URL='rtmps://a.rtmp.youtube.com/live2/<stream-key>'
export MUSIKALISCHES_STAGE7_LOOP_MODE=infinite
ops/out/stream-bridge/run_stage7_stream_bridge.sh
```

如果只做短时受控预检，可临时加 `MUSIKALISCHES_STAGE7_MAX_RUNTIME_SECONDS=120`；正式直播不要设置（见下面预算语义）。

常用可选变量：

- `MUSIKALISCHES_STAGE7_LOOP_MODE=once|infinite`
- `MUSIKALISCHES_STAGE7_MAX_RUNTIME_SECONDS=<n>`
- `MUSIKALISCHES_STAGE7_RUNTIME_BIN=/abs/path/to/musikalisches-stage7-runtime`
- `LIVE_LOOP_COUNT=16` 只影响默认 live-source 重建；formal live 基线建议保持 `16`

语义说明：

- `MUSIKALISCHES_STAGE7_MAX_RUNTIME_SECONDS` 表示整体 wrapper runtime budget
- 默认入口会优先尝试 Rust runtime；若 repo 下没有已构建的 `musikalisches-stage7-runtime`，才会回退到 Python runtime
- redaction / failure classification 已内建在 runtime 内；live-host 不再需要额外部署 `classify_stage7_bridge_failure.py`
- 如果目标是长期无人值守直播，应保留 `MUSIKALISCHES_STAGE7_LOOP_MODE=infinite`，并且不要设置 `MUSIKALISCHES_STAGE7_MAX_RUNTIME_SECONDS`
- 如果设置了 runtime budget，达到上限后以受控方式退出属于预期行为，不代表隐藏错误

默认 live 入口脚本会先做 4 项 preflight：

- `protocol_support`
- `dns_resolution`
- `tcp_connectivity`
- `publish_probe`

只有 preflight 通过后，才应该进入正式长时直播或 stage8 soak。

### 6.1 人工启动直播运行手册（真实 URL）

前置条件：上面的 stage7 校验链全部 passed，且手里有可撤销的真实 stream key。

**第一步：注入 secret（仓库外，600 权限）**

真实 URL 不得写入仓库文件、不得出现在 shell 历史之外的其他文件。约定存放在 `~/.stage8_ingest.env`：

```bash
umask 077
printf "%s\n" "MUSIKALISCHES_RTMP_URL='rtmps://a.rtmp.youtube.com/live2/<stream-key>'" \
  > ~/.stage8_ingest.env
chmod 600 ~/.stage8_ingest.env
```

runtime 内建 redaction：URL 值在所有日志/报告中会被替换为 `<redacted:MUSIKALISCHES_RTMP_URL>`，已由 stage8 验收实测验证。

**第二步：启动**

```bash
cd /opt/src/41490/chao5whistler
set -a; source ~/.stage8_ingest.env; set +a
export MUSIKALISCHES_STAGE7_LOOP_MODE=infinite
ops/out/stream-bridge/run_stage7_stream_bridge.sh        # 前台

# 或后台保活：
nohup ops/out/stream-bridge/run_stage7_stream_bridge.sh \
  > ops/out/stream-bridge/logs/stage8_soak_console.log 2>&1 &
echo $! > ops/out/stream-bridge/logs/stage8_soak.pid
```

**第三步：运行中观察**

```bash
# 实时推流进度（每 0.5s 更新的单行 sidecar）
tail -f ops/out/stream-bridge/logs/stage7_bridge_live_progress.txt

# 尝试次数 / 退出分类
sed -n '1,220p' ops/out/stream-bridge/logs/stage7_bridge_runtime_report.json
```

正常状态：sidecar 的 `time=` 与墙钟同步推进（1x），`fps≈30`，无重试记录。

**第四步：停止**

- 前台：`Ctrl-C`
- 后台：`kill -INT "$(cat ops/out/stream-bridge/logs/stage8_soak.pid)"`

SIGINT 会优雅退出并分类为 `interrupted`（不会误重试），exit report 可审计。

**约束与语义**

- **同一 stream key 同时只能有一个发布者**：重复启动会被平台拒绝或顶掉现有流；启动前先确认没有残留 ffmpeg（`pgrep -f ops/bin/ffmpeg`）。
- 正式直播**不要设置** `MUSIKALISCHES_STAGE7_MAX_RUNTIME_SECONDS`；它是整体 wrapper 预算，到点受控退出（`runtime_limit_reached`）属预期而非故障。
- 每次启动都会自动执行 4 项 preflight；失败时控制台首行给出 `preflight failed: <check_id>`，首查 `logs/stage7_bridge_preflight_report.json`。
- 若事件侧排障需要重启推流，重启后 YouTube 侧预览可能需要 10–30s 恢复。

### 6.2 YouTube 后台一直显示“直播准备中”的排障

仓库侧已实测排除媒体层问题（stage8 验收证据，2026-09-19）：跨 192s 循环边界的本地 FLV 捕获中，视频 6000 包 / 音频 8615 包 DTS 全程单调，192.02s 恰为关键帧，编码参数为 YouTube 标准配置（H.264 720p30 CFR + AAC 128k 44.1kHz stereo，GOP 2s，无 B 帧）。

若 ffmpeg 侧 sidecar 正常推进但后台长时间停在“准备中”，按以下顺序在 YouTube Studio 排查：

1. **看“直播控制室”的流健康面板**：
   - 显示“极佳/良好”且码率约 4100 kbps → 数据已到达，只是广播未开始：点击**开始直播**或开启**自动开始**。
   - 显示“无数据” → 平台没有在解码这个事件的数据，进入下一步。
2. **核对 stream key 是否与所看事件一致**：直播控制室事件页显示的默认流密钥必须与 `MUSIKALISCHES_RTMP_URL` 中的 key 完全一致。历史上仓库文档曾泄漏过另一个 key（已在 260319 前移除，但 git 历史仍可见，应到 YouTube Studio 轮换），以 issue #66 评论提供的 key 为准。
3. **确认频道直播权限**：新频道需完成 24h 激活；未激活时后台会有资格提示。
4. 以上都正常仍无预览时，抓取本地证据后到 issue #66 附上：`logs/stage7_bridge_runtime_report.json`、sidecar 快照、流健康面板截图。

## 7. 运行中和结束后看哪些日志

正式推流时，重点看这些文件：

- `ops/out/stream-bridge/logs/stage7_bridge_preflight.stderr.log`
- `ops/out/stream-bridge/logs/stage7_bridge_preflight_report.json`
- `ops/out/stream-bridge/logs/stage7_bridge_latest.stderr.log`
- `ops/out/stream-bridge/logs/stage7_bridge_exit_report.json`
- `ops/out/stream-bridge/logs/stage7_bridge_runtime_report.json`

当前 wrapper 和 runtime 在失败或 budget 到时退出时，也会直接向控制台打印最小摘要和以上 report/log 路径。
如果是 preflight 失败，控制台首行会固定打印 `preflight failed: <check_id>; see ...preflight_report.json and ...preflight.stderr.log`。
人工排障时先看 `stage7_bridge_preflight_report.json`，再看 `stage7_bridge_preflight.stderr.log`。

最小检查方法：

```bash
sed -n '1,260p' ops/out/stream-bridge/logs/stage7_bridge_preflight_report.json
sed -n '1,220p' ops/out/stream-bridge/logs/stage7_bridge_runtime_report.json
sed -n '1,220p' ops/out/stream-bridge/logs/stage7_bridge_exit_report.json
```

如果要把这次真实 preflight / soak 收成可回填 issue 的独立样本包，执行：

```bash
make -C src/musikalisches stage8-sample-retain STAGE8_RUN_LABEL=<label>
```

默认会生成：

- `ops/out/stream-bridge/stage8-samples/<label>/operator_summary_template.md`
- `ops/out/stream-bridge/stage8-samples/<label>/attempt_log_index.json`
- `ops/out/stream-bridge/stage8-samples/<label>/runtime_artifact_digest.json`
- `ops/out/stream-bridge/stage8-samples/<label>/stage8_sample_retention_report.json`

如果需要做真实平台长时 soak，直接按 `docs/plans/260324-stage8-real-soak-ops-guide.md` 执行。

## 8. 一句话结论

日常直播前至少要确认两件事：

- `make -C src/musikalisches stage7-ffmpeg-check && make -C src/musikalisches stage7-all` 全部通过
- 在 `src/musikalisches/runtime/config/stage7_default_bridge_profile.json` 约定的环境变量 `MUSIKALISCHES_RTMP_URL` 中，提供完整的真实 `rtmps://.../<stream-key>` 地址

满足这两点后，执行 `ops/out/stream-bridge/run_stage7_stream_bridge.sh` 才会开始真实推流。
