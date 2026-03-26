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

然后设置环境变量并启动：

```bash
export MUSIKALISCHES_RTMP_URL='rtmps://a.rtmp.youtube.com/live2/brqs-rf5v-pr2e-kb0z-7swa'
export MUSIKALISCHES_STAGE7_LOOP_MODE=infinite
export MUSIKALISCHES_STAGE7_MAX_RUNTIME_SECONDS=120
ops/out/stream-bridge/run_stage7_stream_bridge.sh
```

```bash
export MUSIKALISCHES_RTMP_URL='rtmps://...<real-ingest>...'
export MUSIKALISCHES_STAGE7_LOOP_MODE=infinite
export MUSIKALISCHES_STAGE7_MAX_RUNTIME_SECONDS=120
ops/out/stream-bridge/run_stage7_stream_bridge.sh
```

常用可选变量：

- `MUSIKALISCHES_STAGE7_LOOP_MODE=once|infinite`
- `MUSIKALISCHES_STAGE7_MAX_RUNTIME_SECONDS=<n>`
- `LIVE_LOOP_COUNT=16` 只影响默认 live-source 重建；formal live 基线建议保持 `16`

语义说明：

- `MUSIKALISCHES_STAGE7_MAX_RUNTIME_SECONDS` 表示整体 wrapper runtime budget
- 如果目标是长期无人值守直播，应保留 `MUSIKALISCHES_STAGE7_LOOP_MODE=infinite`，并且不要设置 `MUSIKALISCHES_STAGE7_MAX_RUNTIME_SECONDS`
- 如果设置了 runtime budget，达到上限后以受控方式退出属于预期行为，不代表隐藏错误

默认 live 入口脚本会先做 4 项 preflight：

- `protocol_support`
- `dns_resolution`
- `tcp_connectivity`
- `publish_probe`

只有 preflight 通过后，才应该进入正式长时直播或 stage8 soak。

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
