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
```

其中：

- `stage5-build` 会重建 release 二进制
- `stage5-test` 会跑 Rust 测试
- `stage7-ffmpeg-check` 会确认 `ops/bin/ffmpeg` / `ops/bin/ffprobe` 具备 `rtmps` output、`libx264` 和本地 `flv` smoke 编码能力
- `stage7-all` 会串起 stage5 音频、stage6 视频、stage7 bridge 的默认构建与校验

如果你只想做日常快速回归，不重建 release，也可以直接执行：

```bash
make -C src/musikalisches stage7-ffmpeg-check
make -C src/musikalisches stage7-all
```

## 2. 检查通过的判据

以下报告文件都应为 `status = passed`：

- `ops/out/ffmpeg-rtmps-check/stage7_ffmpeg_toolchain_validation_report.json`
- `ops/out/video-stub/stage6_validation_report.json`
- `ops/out/video-render/stage6_render_validation_report.json`
- `ops/out/stream-bridge/stage7_bridge_validation_report.json`
- `ops/out/stream-bridge/stage7_soak_validation_report.json`

可直接用下面的命令快速查看：

```bash
python3 - <<'PY'
import json
from pathlib import Path

files = [
    "ops/out/ffmpeg-rtmps-check/stage7_ffmpeg_toolchain_validation_report.json",
    "ops/out/video-stub/stage6_validation_report.json",
    "ops/out/video-render/stage6_render_validation_report.json",
    "ops/out/stream-bridge/stage7_bridge_validation_report.json",
    "ops/out/stream-bridge/stage7_soak_validation_report.json",
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
make -C src/musikalisches stage6-video-render
make -C src/musikalisches stage6-video-render-check
```

默认输出目录：

```text
ops/out/video-render
```

重点文件：

- `ops/out/video-render/offline_preview.mp4`
- `ops/out/video-render/offline_frame_sequence.json`
- `ops/out/video-render/video_render_manifest.json`
- `ops/out/video-render/stage6_render_validation_report.json`

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

最小检查方法：

```bash
sed -n '1,260p' ops/out/stream-bridge/logs/stage7_bridge_preflight_report.json
sed -n '1,220p' ops/out/stream-bridge/logs/stage7_bridge_runtime_report.json
sed -n '1,220p' ops/out/stream-bridge/logs/stage7_bridge_exit_report.json
```

如果需要做真实平台长时 soak，直接按 `docs/plans/260324-stage8-real-soak-ops-guide.md` 执行。

## 8. 一句话结论

日常直播前至少要确认两件事：

- `make -C src/musikalisches stage7-ffmpeg-check && make -C src/musikalisches stage7-all` 全部通过
- 在 `src/musikalisches/runtime/config/stage7_default_bridge_profile.json` 约定的环境变量 `MUSIKALISCHES_RTMP_URL` 中，提供完整的真实 `rtmps://.../<stream-key>` 地址

满足这两点后，执行 `ops/out/stream-bridge/run_stage7_stream_bridge.sh` 才会开始真实推流。
