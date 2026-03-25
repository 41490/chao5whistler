# stage7 stream bridge guide

这一步冻结的是 `FFmpeg / RTMPS bridge` contract，并把进入 stage 8 前必须具备的 loop / failure taxonomy / soak gate 一并落到仓库工件里。

当前默认目标：

- 协议：`RTMPS`
- mux/container：`flv`
- 视频：`1280x720 @ 30fps`
- 视频编码：`H.264 / libx264`
- preset：`ultrafast`
- 视频码率：`4000 Kbps CBR`
- keyframe：`2 seconds`
- 音频：`AAC stereo`
- 音频采样率：`44.1 KHz`
- 音频码率：`128 Kbps`

本地工件入口：

```bash
make -C src/musikalisches stage7-ffmpeg-check
make -C src/musikalisches stage7-bridge
make -C src/musikalisches stage7-bridge-check
make -C src/musikalisches stage7-preflight-regression-check
make -C src/musikalisches stage7-soak-check
```

默认输入：

- stage5 音频工件：`ops/out/stream-demo`
- stage6 视频工件：`ops/out/video-render`

默认输出：

- `ops/out/stream-bridge`

生成内容：

- `stage7_bridge_profile.json`
- `stream_bridge_manifest.json`
- `stream_bridge_ffmpeg_args.json`
- `stage7_failure_taxonomy.json`
- `stage7_soak_plan.json`
- `run_stage7_stream_bridge.sh`
- `stage7_bridge_smoke.flv`
- `stage7_bridge_validation_report.json`
- `stage7_soak_validation_report.json`

当前补齐的 pre-stage8 优化：

- `repo-managed ffmpeg`: 仓库内可直接构建 `ops/bin/ffmpeg` / `ops/bin/ffprobe`，固定 `libx264 + openssl + rtmps` 能力，避免系统包缺项
- `loop bridge`: 默认 live mode 为 `infinite`，通过 `MUSIKALISCHES_STAGE7_LOOP_MODE` 在 `once` / `infinite` 间切换
- `rtmps preflight`: 正式推流前先检查 `ffmpeg` 协议支持、DNS、TCP 连通性，以及一次轻量 publish probe，把配置/认证错误前置暴露
- `preflight regression harness`: 自动回归 `target_scheme / protocol_support / dns_resolution / tcp_connectivity / publish_probe` 五条 fail 路径，防止控制台摘要或 report/log 指针再次退化
- `reconnect executor`: 运行时真正执行 backoff / retry budget / 连续 retryable failure 上限，而不再只把策略停在 soak plan
- `failure taxonomy`: 运行时会写 redacted `stderr`、`exit report` 与 aggregate runtime report，至少区分 `handshake_failure` / `auth_failure` / `network_jitter` / `remote_disconnect` / `ingest_configuration_failure`
- `soak gate`: 基于 bridge manifest 生成 `stage7_soak_plan.json`，并以 `stage7-soak-check` 验证进入 stage 8 前的最小条件
- `artifact_integrity + tolerance`: stage7 manifest 现同步冻结 `stage7_bridge_profile.json` / `stream_bridge_ffmpeg_args.json` / `run_stage7_stream_bridge.sh` / `stage7_failure_taxonomy.json` / `stage7_soak_plan.json` 以及 `stage7_bridge_smoke.flv` 的文件级 `sha256` / `size_bytes`，并把 smoke 输出的 frame count / fps / duration / keyframe cadence / stream layout 容差显式写入 manifest，和 stage6 `offline_preview.mp4` 的验收口径对齐
- `bridge consistency`: stage7 manifest 现显式冻结 stage6 `offline_preview.mp4` 的 probe 摘要、`sha256` 链接、以及到 stage7 `stage7_bridge_smoke.flv` 的 comparison tolerance / stream delta，validator 会直接比较两阶段的 width / height / fps / frame count / duration / keyframe cadence / stream layout
- `stage8 ops contract`: stage7 manifest 现额外冻结 `stage8_ops` 区块，明确 real soak guide、entry script、required env vars、background files、required runtime reports 与 readiness report 文件名

运行脚本约定：

- 必需：`MUSIKALISCHES_RTMP_URL`
- 可选：`MUSIKALISCHES_STAGE7_LOOP_MODE=once|infinite`
- 可选：`MUSIKALISCHES_STAGE7_MAX_RUNTIME_SECONDS=<n>`
- 默认优先使用 `ops/bin/ffmpeg` / `ops/bin/ffprobe`，如存在
- 默认 bridge profile 固定为 `RTMPS` 语义；本地自动回归仅在临时 profile 中使用 `rtmp://127.0.0.1` 来模拟 preflight fail 分支

示例：

```bash
export MUSIKALISCHES_RTMP_URL='rtmps://...'
export MUSIKALISCHES_STAGE7_LOOP_MODE=infinite
export MUSIKALISCHES_STAGE7_MAX_RUNTIME_SECONDS=60
ops/out/stream-bridge/run_stage7_stream_bridge.sh
```

运行后的观测文件：

- `ops/out/stream-bridge/logs/stage7_bridge_preflight.stderr.log`
- `ops/out/stream-bridge/logs/stage7_bridge_preflight_report.json`
- `ops/out/stream-bridge/logs/stage7_bridge_latest.stderr.log`
- `ops/out/stream-bridge/logs/stage7_bridge_exit_report.json`
- `ops/out/stream-bridge/logs/stage7_bridge_runtime_report.json`
- `ops/out/stage7-preflight-regressions/stage7_preflight_regression_report.json`

控制台约定：

- preflight fail 时，控制台首行固定输出 `preflight failed: <check_id>; see ...preflight_report.json and ...preflight.stderr.log`
- wrapper 非零退出时，会提示先查 `stage7_bridge_preflight_report.json`，再看 `stage7_bridge_runtime_report.json` 与 `stage7_bridge_latest.stderr.log`
- 人工排障顺序固定为：先 `stage7_bridge_preflight_report.json`，后 `stage7_bridge_preflight.stderr.log`

边界：

- 默认流程只做本地 `flv` smoke，不默认发起真实推流
- 真正的直播 URL 不进入仓库文件，也不写入 manifest
- `stage7_soak_check` 现在验证的是进入 stage 8 前的 readiness contract，不是 8h-24h 实际长跑结果本身
- stage 8 人工真实 soak 流程草稿见：`docs/plans/260324-stage8-real-soak-ops-guide.md`

当前 manifest 重点检查项：

- `stream_bridge_manifest.json > artifact_integrity`
  - 校验 stage7 关键工件和 smoke 输出是否可逐文件对账
- `stream_bridge_manifest.json > video_input`
  - 保留来自 stage6 `offline_preview.mp4` 的 artifact integrity 与 tolerance contract 摘要
- `stream_bridge_manifest.json > smoke_generation`
  - 显式冻结：
    - `expected_frame_count`
    - `frame_count_tolerance`
    - `expected_fps`
    - `fps_tolerance`
    - `expected_duration_seconds`
    - `duration_tolerance_seconds`
    - `expected_keyframe_interval_frames`
    - `keyframe_interval_tolerance_frames`
    - `expected_stream_layout`
- `stream_bridge_manifest.json > bridge_consistency`
  - 显式冻结：
    - `source_video_sha256`
    - `source_probe_summary`
    - `comparison_tolerance`
    - `expected_stream_delta`
    - `expected_matches`
- `stream_bridge_manifest.json > stage8_ops`
  - 显式冻结：
    - `guide_file`
    - `entry_script_file`
    - `required_env_vars`
    - `background_files`
    - `required_runtime_reports`
    - `readiness_report_file`
