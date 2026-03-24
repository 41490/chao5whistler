# 260324 issue #1 musikalisches stage7 rtmps toolchain ready

## context

本次继续依据 issue #1 的最新推进要求：

- 先移除当前主机上 `ffmpeg` 缺少 `rtmps` output 的 blocker
- 然后把 stage7/stage8 入口收敛到可重复执行的本地运维入口

上一轮已冻结：

- stage7 preflight
- reconnect executor
- pre-stage8 soak gate

但当时真实阻塞仍然存在：

- `/usr/local/bin/ffmpeg` 只有 `rtmp` output
- stage8 真实推流会在 `protocol_support` 阶段被提前拦下

## landed

- 新增 repo-managed ffmpeg 构建脚本：
  - `src/musikalisches/tools/build_stage7_rtmps_ffmpeg.sh`
- 新增 ffmpeg capability 校验器：
  - `src/musikalisches/tools/validate_stage7_ffmpeg_toolchain.py`
- `src/musikalisches/Makefile` 新增：
  - `stage7-ffmpeg-build`
  - `stage7-ffmpeg-check`
  - `stage8-plan-show`
- stage6 / stage7 目标现在默认优先使用：
  - `ops/bin/ffmpeg`
  - `ops/bin/ffprobe`
- `src/musikalisches/README.md` 与 `docs/plans/260322-stage7-stream-bridge-guide.md` 已同步 repo-managed ffmpeg 入口
- 新增 stage8 人工运维草稿：
  - `docs/plans/260324-stage8-real-soak-ops-guide.md`

## validation

已完成：

```bash
make -C src/musikalisches stage7-ffmpeg-build
make -C src/musikalisches stage7-ffmpeg-check
make -C src/musikalisches stage6-video-render
make -C src/musikalisches stage6-video-render-check
make -C src/musikalisches stage7-bridge
make -C src/musikalisches stage7-bridge-check
make -C src/musikalisches stage7-soak-check
```

关键结果：

- `ops/bin/ffmpeg -protocols` 已明确包含：
  - input: `rtmps`
  - output: `rtmps`
- `stage7_ffmpeg_toolchain_validation_report.json` 通过
- `video_render_manifest.json.mp4_generation.ffmpeg_bin` 已切到 `ops/bin/ffmpeg`
- `stream_bridge_manifest.json.live_command.ffmpeg_bin` 已切到 `ops/bin/ffmpeg`
- `stream_bridge_manifest.json.smoke_generation.ffprobe_bin` 已切到 `ops/bin/ffprobe`

额外做了两轮 preflight 受控验证：

1. 假域名：
   - `rtmps://nonexistent.invalid/live2/test-key`
   - `protocol_support` 通过
   - `dns_resolution` 失败
   - 分类为 `network_jitter`
2. 真实 YouTube RTMPS host + 假 key：
   - `rtmps://a.rtmps.youtube.com/live2/test-key`
   - `protocol_support` 通过
   - `dns_resolution` 通过
   - `tcp_connectivity` 通过
   - `publish_probe` 进入远端握手后失败
   - 当前分类为 `handshake_failure`

## conclusion

本机构建与 stage7/stage8 入口层面的 blocker 已移除：

- 已不再受系统 ffmpeg 缺少 `rtmps` output 限制
- stage7 preflight 现可真实进入：
  - protocol check
  - DNS
  - TCP
  - publish probe
- 因此仓库与当前主机都已经具备进入 stage8 人工真实 soak 的条件

仍然保留的外部前提：

- 需要运维侧提供真实 `MUSIKALISCHES_RTMP_URL`
- 真实平台对该 URL 的认证/发布权限结果，只有 stage8 人工实测才能最终确认

## next

建议下一步顺序：

1. 按 `docs/plans/260324-stage8-real-soak-ops-guide.md` 执行真实 preflight
2. 先做 2-5 分钟短时人工 publish 验证
3. 再启动 `8h` 起步的 stage8 soak
4. 汇总：
   - drift
   - reconnect/attempt 次数
   - 退出分类分布
   - preflight / runtime report 样本
