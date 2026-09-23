# 260325 issue #2 songh live-test gap audit

基线评论:

- issue #2 comment `4126474259`
- 时间: `2026-03-25T13:07:11Z`
- 结论基线: `songh` 已完成 `stage6 offline av preview render`，还未进入 live bridge

本次清查范围:

- `src/songh/README.md`
- `src/songh/src/config/*`
- `src/songh/src/archive/*`
- `src/songh/src/replay/*`
- `src/songh/src/text/*`
- `src/songh/src/audio/*`
- `src/songh/src/video/*`
- `src/songh/src/av/*`

## 当前整体进展

`src/songh` 当前已形成从归档数据到离线 A/V 预览的最小闭环，完成度可归纳为:

- stage1: config loader / schema / validate 已完成
- stage2: gharchive day-pack seed / prepare / validate 已完成
- stage3: second-of-day replay engine 已完成
- stage4: video frame-plan / PNG render / golden checks 已完成
- stage5: offline audio render / background WAV mix / WAV golden checks 已完成
- stage6: offline preview mp4 render / ffprobe contract 已完成

代码事实:

- `render-av-sample` 已存在，并通过 `ffmpeg` 生成 `offline_preview.mp4`
- `ReplayEngine` 已支持跨 midnight 切换到下一个 complete day-pack
- 文本模板、10 类主事件、固定权重、10 分钟 dedupe、720p/30fps 默认值都已落实到 config schema + validate
- `audio.background.wav` 已进入离线混音链路

## 本次验证

已执行:

- `cargo test --manifest-path src/songh/Cargo.toml`
- `make -C src/songh stage6-manual`

结果:

- `29 tests` 全通过
- `stage6-manual` 全流程通过
- 当前机器已生成:
  - `ops/out/songh-stage6-av-sample/offline_preview.mp4`
  - `ops/out/songh-stage6-av-sample/ffprobe.json`

## 与基线评论的一致性

和 `4126474259` 的判断一致，当前 `songh` 的完成面仍然是:

- 已有离线 A/V 预览闭环
- 尚未有真实 live bridge
- 尚未有 RTMP/RTMPS 推流 smoke
- 尚未有真实直播前的 preflight / reconnect / failure taxonomy / runtime report

换言之，`songh` 目前证明的是“能稳定离线生成内容”，不是“能进行真实直播测试”。

## 真实直播测试前仍缺的落地项

按阻塞程度排序:

1. stage7 live bridge
   - 需要把 stage6 产物接到真正的 `ffmpeg` live bridge
   - 输出目标必须同时覆盖 `RTMP/RTMPS + 本地 .flv`
   - 当前 `src/songh` 只有离线 mp4 合流，没有 live flv bridge

2. live runtime loop
   - 需要长时间运行的 runtime，而不是一次性 `render-av-sample`
   - 需要按秒推进 replay / rollover / fallback，连续产出音频和视频
   - 当前实现是 sample/render job，不是常驻直播进程

3. fallback synthetic runtime
   - config 中已有 `random_fallback` / `fallback.*` 规格
   - `RuntimeEventSource::FallbackSynthetic` 已定义
   - 但 `ReplayEngine` 当前只从 archive day-pack 取事件，`ReplayTick.is_fallback` 固定为 `false`
   - 这意味着 archive 断档或 live 长跑缺包时，还没有真实 fallback 行为

4. live output contract
   - 需要冻结 live `ffmpeg args`、container=`flv`、keyframe cadence、stream layout
   - 需要本地 smoke flv 与 probe/validator
   - 当前 stage6 只冻结了 mp4 preview contract

5. preflight and failure handling
   - 需要真实推流前检查: protocol support / DNS / TCP / publish probe
   - 需要失败分类: handshake/auth/network/config
   - 需要 retry/backoff/reconnect 与 runtime report
   - 当前 `src/songh` 没有这层

6. real-ops boundary
   - 需要 secret 注入约定
   - 需要 operator runbook
   - 需要短时 publish 验证和长时 soak 的留样工件
   - 当前这些能力在仓库里主要存在于 `src/musikalisches`，不在 `src/songh`

7. voice backend quality
   - 当前 stage5 仍是 deterministic synth baseline
   - 在开始真实直播前，最好至少补一版更接近目标听感的 voice/sample backend
   - 这不是“能不能开播”的硬阻塞，但会直接影响真实测试价值

## 结论

`src/songh` 当前处于:

- 已完成 `stage6 offline preview baseline`
- 未完成 `stage7 live bridge baseline`

因此，若要开展真实直播测试，最小必需闭环应是:

1. 在 `src/songh` 内补 live bridge 与常驻 runtime
2. 打通 `RTMP/RTMPS + 本地 .flv` 双输出
3. 落地 preflight / reconnect / failure taxonomy / runtime report
4. 补 archive 缺失时的真实 fallback runtime
5. 先做本地 live smoke，再做真实平台短时 publish，最后才进入长时 soak

建议把下一条子 Issue 聚焦为:

- `songh` 从 stage6 离线预览推进到 stage7 直播桥接与真实直播前置校验
