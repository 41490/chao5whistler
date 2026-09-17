# musikalisches weaver runbook (issue #62)

`musikalisches-weaver` 是常驻 supervisor：它在 stage5/stage6 与 stage7 bridge 之间维持一个**预生成资产缓冲池**，按完整 asset 边界交接，消费成功后才 checkpoint。Rust 只做编排，stage5/stage6 仍调用既有 Python 工具。

- binary：`musikalisches-weaver`（`src/musikalisches/runtime/src/weaver_main.rs`）
- 编排实现：`src/musikalisches/runtime/src/weaver/`
- 默认 adapter：`src/musikalisches/runtime/config/weaver_default_adapter.json`
- dry-run adapter（无 key）：`src/musikalisches/runtime/config/weaver_dry_run_adapter.json`
- 本地 fake bridge：`src/musikalisches/tools/fake_weaver_bridge.py`

## 1. 架构

```text
                 ┌──────────────── producer（refill）────────────────┐
stage5 ledger ──► │ stage5_audio → stage6_stub → stage6_video        │
（唯一分配器）     │        ↓ 临时目录 + rename（原子发布）            │
                 └──────────────► buffer pool（N=3）─────────────────┘
                                        │ 完整 asset
                                        ▼
                 consumer：bridge_build → bridge_run（once）
                                        │ 成功
                                        ▼
                        consumed → checkpointed（写 weaver ledger）
```

- **缓冲池 = weaver ledger 中状态为 `published` 的记录**，不是单独的数据结构。
- 初始深度 `N = 3`（`--buffer-depth`）；深度 `< 2`（`--low-water`）触发补充。
- 发布单元是一个目录，rename 进 `--buffer-dir` 后 bridge 才可能看到；半成品只存在于 `.tmp-publish-*`，启动时会清理。
- 缓冲耗尽时**明确失败**（exit 4），绝不静默重复已播组合；重复组合在 ledger 层被直接拒绝。
- 首版不做实时音视频拼接，只在完整 asset 边界切换；也不做实时编码。

## 2. ledger 状态机与启动恢复

weaver 自己的状态文件默认 `ops/out/state/musikalisches/weaver/weaver_asset_ledger.json`，与 stage5 的 `stage5_stream_sf2_combination_ledger.json` **完全分离**（后者仍是“分配了哪些组合”的唯一事实来源，由 Python 工具写入）。

```text
reserved ──► rendering ──► published ──► consumed ──► checkpointed
    │             │
    └─────────────┴──► failed（retryable）
```

| 迁移 | 触发点 |
| --- | --- |
| `reserved` | `begin_reservation()`：开始生成前先落盘，崩溃后可见 |
| `rendering` | stage5 成功、从 `combination_selection.json` 读到 `combination_id` 之后 |
| `published` | 资产原子发布完成、ledger 指向最终目录 |
| `consumed` | bridge 退出码 0 |
| `checkpointed` | 消费后立刻 checkpoint |
| `failed` | 任一步骤失败 / 启动回收 / 资产目录丢失 |

启动恢复语义（`recover_stale` + `drop_missing_assets`）：

- `reserved` / `rendering` 且 `updated_at` 超过 `--reservation-timeout-seconds`（默认 1800s）→ 置 `failed` 且 `retryable=true`，`recovered_from` 记录原状态。
- `consumed` 但未 `checkpointed` → **提升为 `checkpointed`**：bridge 已经接受过这个资产，重放会造成重复播出。
- `published` 但资产目录不存在 → 置 `failed`（`asset_dir_missing`），该槽位重新生成；旧组合视为已丢失（不会重播、也不会重复）。
- `checkpointed` 记录永不重新生成、永不重复确认。
- 所有状态写入都是“临时文件 + `rename`”，崩溃后不会读到半写状态。
- 重试一律清空该记录的 work 目录后从 stage5 重新分配新组合：不冒险复用半成品。

## 3. adapter 配置

代码里没有任何 Makefile 目标名或工具硬编码；每个外部命令都是 adapter JSON 里的一个命名 step：

```json
{
  "adapter_id": "weaver_default_adapter_v1",
  "steps": {
    "stage5_audio": { "program": "python3", "args": ["src/musikalisches/tools/build_stage5_unique_stream.py", "--work-id", "{work_id}", "--output-dir", "{audio_dir}", "--ledger-path", "{stage5_ledger}", "--loop-count", "{loop_count}", "--soundfont", "{soundfont}", "--soundscape-profile", "{soundscape_profile}"] },
    "stage6_stub":  { "program": "python3", "args": ["src/musikalisches/tools/build_stage6_video_stub.py", "{audio_dir}", "{stub_dir}"] },
    "stage6_video": { "program": "python3", "args": ["src/musikalisches/tools/build_stage6_video_render.py", "--ffmpeg-bin", "ffmpeg", "{stub_dir}", "{video_dir}"] },
    "bridge_build": { "program": "python3", "args": ["src/musikalisches/tools/build_stage7_stream_bridge.py", "--ffmpeg-bin", "ffmpeg", "--ffprobe-bin", "ffprobe", "{audio_dir}", "{video_dir}", "{bridge_dir}"] },
    "bridge_run":   { "program": "cargo", "args": ["run", "--bin", "musikalisches-stage7-runtime", "--", "--artifact-dir", "{bridge_dir}", "--stream-url-env", "MUSIKALISCHES_RTMP_URL", "--loop-mode", "once"] }
  }
}
```

- 必需 step：`stage5_audio`、`stage6_video`、`bridge_run`；可选 step：`stage6_stub`、`bridge_build`。
- 占位符：`{work_id}`、`{repo_root}`、`{state_dir}`、`{buffer_dir}`、`{work_dir}`、`{stage5_ledger}`、`{soundfont}`、`{soundscape_profile}`、`{loop_count}`、`{play_seconds}`、`{bridge_journal}`、`{report_path}`、`{exit_report_path}`，以及每个资产的 `{record_id}`、`{audio_dir}`、`{stub_dir}`、`{video_dir}`、`{asset_dir}`、`{combination_id}`、`{bridge_dir}`。
- 未知占位符 = 配置错误（直接失败，不会静默展开成空串）；`{a b}` 这类非标识符花括号原样透传。
- `{soundfont}` 在启动时解析成绝对路径，优先级与 `make stage5-sf2` 完全一致：`--soundfont` → `$MUSIKALISCHES_SOUNDFONT` → `<repo_root>/ops/assets/soundfonts/default.sf2` → 系统候选（`/usr/share/sounds/sf2/FluidR3_GM.sf2`、`TimGM6mb.sf2`、`FluidR3Mono_GM.sf2`、`/usr/local/share/sounds/sf2/default.sf2`）。仓库本身**不携带** SoundFont（`ops/assets/**` 被 `.gitignore` 忽略），所以不要假定某个固定路径存在。全部候选都落空时，weaver 以 exit 2（`usage_error`）快速失败，并在错误里列出 `MUSIKALISCHES_SOUNDFONT`、repo 默认路径和全部系统候选。启动横幅会打印实际选中的路径与来源（`explicit` / `env` / `repo_default` / `system`）。
- 每步 stdout/stderr 落到 `<state-dir>/logs/<record_id>/<step>.log`；`--step-timeout-seconds` 控制单步超时（0 关闭）。

**换成 fake**：把 `bridge_run` 指向本地 fake bridge 即可，其余保持真实：

```bash
cargo run --bin musikalisches-weaver -- \
  --adapter-config src/musikalisches/runtime/config/weaver_dry_run_adapter.json \
  --state-dir ops/out/state/musikalisches/weaver \
  --buffer-dir ops/out/weaver-buffer \
  --work-dir ops/out/weaver-work \
  --consume-count 3 --buffer-depth 3 --low-water 2
```

`fake_weaver_bridge.py` 会校验 `weaver_asset_manifest.json` 里每个文件的 sha256、把消费追加到 `--bridge-journal`，并在 `--play-seconds` 内模拟实时播放。它不需要任何 YouTube key，也不会向任何 repo 文件写入 RTMPS URL 或密钥。

## 4. 退出码与失败分类

| exit code | `exit_class` | 含义 | 观测点 |
| --- | --- | --- | --- |
| 0 | `ok` | 达到 `--consume-count` / `--once` 后正常退出 | `weaver_exit_report.json` |
| 1 | `internal_error` | 非预期 IO / 状态错误 | stderr + exit report |
| 2 | `usage_error` | 参数、adapter 配置错误 | stderr |
| 3 | `production_failure` | 连续 `--max-generation-failures` 次生成失败 | exit report + `<state-dir>/logs/` |
| 4 | `buffer_exhausted` | 缓冲为空且无法补充 | exit report |
| 5 | `bridge_failure` | 连续 `--max-bridge-attempts` 次桥接失败 | exit report + bridge step 日志 |

三类关键失败各自独立，不会互相掩盖：生成失败不会动已 `consumed` 的记录；桥接失败只增加 `bridge_attempts`，资产保持 `published`（不丢）；缓冲耗尽只在确实没有可用资产且无法补充时发生。

`weaver_exit_report.json` 每次运行都会写，含 `exit_class`、`exit_code`、`message`、`failed_records` 明细。

## 5. 吞吐测量与“无法维持直播”判定

`weaver_throughput_report.json`（默认在 state-dir）至少包含：

- `generation_assets_per_minute` / `generation_seconds` / `generated_assets`（stage5+stage6 生成吞吐）
- `playback_assets_per_minute` / `playback_seconds` / `consumed_assets`（实测播放吞吐）
- `required_playback_assets_per_minute`（由资产时长推出的实时需求，供对照）
- `buffer_depth_min` / `buffer_depth_max` / `buffer_depth_samples` / `buffer_depth_target` / `low_water`
- `distinct_consumed_combination_ids`、`checkpointed_records`、`failed_records`、`recovered_records`

判定规则：

- `generation_assets_per_minute < playback_assets_per_minute` → `sustainable_live=false`、`verdict="cannot_sustain_live"`，notes 与 stderr 显式打印 “cannot sustain live … refuses to mask the shortfall with repeated combinations”。
- 任一侧无样本（生成 0 秒或未消费）→ `verdict="insufficient_samples"`，不假装可持续。
- 否则 `verdict="can_sustain_live"`。

这是硬门槛：吞吐不足时 Weaver 报告不可维持，**不会**用重复组合掩盖。

## 6. 端到端 smoke（无 YouTube key）

```bash
# 1) 全量回归（含 7 条 weaver 端到端断言）
cargo test --manifest-path Cargo.toml
make -C src/musikalisches weaver-test

# 2) keyless dry run：真实 stage5/stage6 + 真实 bridge contract，本地 fake bridge 消费 3 个资产
make -C src/musikalisches weaver-dry-run WEAVER_CONSUME_COUNT=3 WEAVER_PLAY_SECONDS=2

# 3) 查看吞吐报告与消费流水
make -C src/musikalisches weaver-report
tail -n 5 ops/out/state/musikalisches/weaver/bridge_journal.jsonl

# 4) 查看 weaver ledger 状态分布
python3 - <<'PY'
import json, collections
ledger = json.load(open("ops/out/state/musikalisches/weaver/weaver_asset_ledger.json"))
print(collections.Counter(r["state"] for r in ledger["records"]))
print([r["combination_id"] for r in ledger["records"] if r["state"] == "checkpointed"])
PY

# 5) 崩溃/重启语义：先消费 1 个，再重启消费 1 个；checkpointed 不重复、published 不丢失
make -C src/musikalisches weaver-dry-run WEAVER_CONSUME_COUNT=1 WEAVER_PLAY_SECONDS=1
make -C src/musikalisches weaver-dry-run WEAVER_CONSUME_COUNT=1 WEAVER_PLAY_SECONDS=1
wc -l ops/out/state/musikalisches/weaver/bridge_journal.jsonl   # 每行一个组合，无重复
```

真实推流（需要自己的 ingest key，仓库内不存任何 URL/密钥）：

```bash
export MUSIKALISCHES_RTMP_URL='rtmps://<your-ingest-endpoint>/<your-key>'
cargo run --bin musikalisches-weaver -- --consume-count 3   # 默认 adapter
unset MUSIKALISCHES_RTMP_URL
```

## 7. 已知限制

- 补充是**同步**的：refill 在消费循环里阻塞执行，没有独立 producer 线程；生成延迟过高时会直接体现在 `cannot_sustain_live` 判定里。
- stage5 依赖一个 SoundFont：仓库不提供，必须通过 `--soundfont`、`MUSIKALISCHES_SOUNDFONT`、`ops/assets/soundfonts/default.sf2` 或系统 GM 音色之一满足（见 §3）。
- 实时编码、音视频内部拼接、跨 asset 无缝过渡均未实现（首版按 issue #62 决策只做预生成缓冲池）。
- 重试不复用失败尝试的中间产物，被放弃的组合会保留在 stage5 ledger 里但不会出现在直播中。
- `--consume-count` 缺省表示常驻运行，目前不处理 SIGINT 的优雅收尾（下次启动由恢复逻辑兜底）。
