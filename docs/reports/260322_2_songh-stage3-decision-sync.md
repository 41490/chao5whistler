# 260322 issue #2 songh stage3 decision sync

## context

本次推进依据以下两条 issue 评论冻结：

- stage3 方案草稿：
  - <https://github.com/41490/chao5whistler/issues/2#issuecomment-4104758776>
- 当前最后回复：
  - <https://github.com/41490/chao5whistler/issues/2#issuecomment-4107174806>

最终确认的关键点：

- D1: `runtime.clock` 需要同时支持 `realtime` 与 `fast`
- D2: 后续 runtime engine 需要按可用 day-pack 自动轮换
- D3: dedupe 语义以 replay 秒为准
- D4: fallback 事件应绑定当前 `second_of_day`
- D5: 同秒排序规则冻结为 `weight_desc -> event_id_asc`
- 目标输出规格优先资源节省：
  - `1280x720`
  - `30 fps`
  - `H.264 ultrafast`
  - `128 kbps`

## landed in this sync

- `src/songh` 配置 schema 已允许 `runtime.clock = "fast"`
- `replay.selection_order` 默认值与校验规则已改为：
  - `["weight_desc", "event_id_asc"]`
- `video.canvas` 默认值已从 `1920x1080` 调整为 `1280x720`
- 新增 `[outputs.encode]` 冻结输出目标：
  - `video_codec = "h264"`
  - `video_preset = "ultrafast"`
  - `audio_bitrate_kbps = 128`
- tracked template / toml spec / README 已同步更新
- replay 单测已补稳定 tie-break 覆盖

## not finished yet

这次同步的是“冻结决策进入配置与 replay 规则”，不是完整的 live runtime engine。

仍待继续推进的主体工作：

1. 把 stage3 从 `sample-replay` 扩成持续输出 `ReplayTick` 的 runtime engine
2. 把跨 day-pack 自动轮换接到真实引擎
3. 把 fallback 事件生成接到同一 tick 契约
4. 再进入 audio / video / ffmpeg tee muxer 主链路

## validation

计划验证命令：

```bash
/home/zoomq/.cargo/bin/cargo test --manifest-path src/songh/Cargo.toml
```

如果运行环境缺少 `cargo` PATH，需要显式使用上面的绝对路径。
