# Issue #73: keyless weaver 失败率与门禁分布审计

## 结论

2026-09-18 在 main/origin `b088def9` 上完成真实 stage5/stage6 + fake bridge 有界运行：生成 **9 个不同 combination**，消费并 checkpoint **7 个**，剩余 2 个 published。进程退出码与 weaver exit report 均为 **0 / ok**。mix SystemExit **0/9 (0%)**，stage5 失败 **0/9**，独立 M1 校验失败 **0/9**，bridge 消费失败 **0/7**。

本次未发现需要修复的新门禁缺陷；8 个数值阈值均未落入样本 min/max 区间。**代码及配置零改动、免守卫**：仅改本报告和 runbook 指针，按任务要求跳过 `check-mana-grant-scope.py`。保留 RMS 下限 **-28.0 dBFS**，不沿用 #63 放宽到 -30 的结论。

## 环境与执行

- 工作区：`/opt/src/41490/chao5whistler-73-weaver-failure-audit`。
- adapter：`src/musikalisches/runtime/config/weaver_dry_run_adapter.json`；真实 `build_stage5_unique_stream.py` / `apply_soundscape_mix`，未调用 `fake_weaver_render.py`。
- SoundFont 自动解析：`/usr/share/sounds/sf2/FluidR3_GM.sf2`，source=`system`。未改 SoundFont 或 bed WAV。
- 默认 soundscape profile：逐组合 trim 生效，`envelope_coupling.enabled=true`、`depth_db=6.0`；全部门禁保持 main 原值。
- ledger 开始时间 `2026-09-18T15:36:05Z`，退出报告时间 `2026-09-18T16:06:11Z`；生成累计 `1788.412393s`。外层 2400 秒 timeout 未触发。

实际执行参数（stdout/stderr 保存到 `$STATE/run.log`，shell 状态保存到 `$STATE/process_exit_code.txt`）：

```bash
STATE=/tmp/mana73-weaver-state
BUFFER=/tmp/mana73-weaver-buffer
WORK=/tmp/mana73-weaver-work
mkdir -p "$STATE" "$BUFFER" "$WORK"
timeout 2400s cargo run --bin musikalisches-weaver -- \
  --adapter-config src/musikalisches/runtime/config/weaver_dry_run_adapter.json \
  --state-dir "$STATE" --buffer-dir "$BUFFER" --work-dir "$WORK" \
  --stage5-ledger "$STATE/stage5_combination_ledger.json" \
  --consume-count 7 --buffer-depth 3 --low-water 2 \
  --loop-count 1 --play-seconds 0
```

显式覆盖 `--stage5-ledger`：只改 `--state-dir` 不会重定位独立 stage5 ledger。state、buffer、work、两种 ledger 全部隔离。

## 逐组合证据

顺序为 ledger 生成顺序。S5 是 stage5 step exit code；M1 是额外执行 `validate_m1_artifacts.py --require-selection --require-soundscape` 的实际退出码。原生 step 日志不单独保存成功退出码；S5=0 由 `StepOutcome::succeeded()` 与发布控制流、ledger `attempts=1`、完整 stage5 日志联合确认，并非拿 weaver 总退出码替代各步退出码。

| # | combination_id | record_id | 状态 | S5 | M1 | peak_amplitude | rms_dbfs | integrated_lufs | true_peak_dbtp | clipping_detected |
| --- | --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| 1 | `9,11,4,11,6,8,5,2,12,4,3,9,10,9,6,9` | `rec-1789745765202-683916-0` | checkpointed | 0 | 0 | 0.388012 | -22.991130 | -19.098 | -8.223 | false |
| 2 | `7,3,10,7,8,10,9,9,6,5,7,11,8,9,10,7` | `rec-1789745969816-683916-1` | checkpointed | 0 | 0 | 0.448683 | -22.817480 | -19.123 | -6.961 | false |
| 3 | `8,12,10,2,3,11,5,7,9,6,5,7,6,10,11,12` | `rec-1789746151377-683916-2` | checkpointed | 0 | 0 | 0.378674 | -23.071051 | -19.090 | -8.435 | false |
| 4 | `2,10,5,5,7,2,10,2,8,12,11,4,6,5,12,6` | `rec-1789746367682-683916-3` | checkpointed | 0 | 0 | 0.371258 | -23.003662 | -19.107 | -8.606 | false |
| 5 | `4,7,9,5,4,5,5,2,3,9,8,11,6,9,3,3` | `rec-1789746559726-683916-4` | checkpointed | 0 | 0 | 0.359111 | -22.955054 | -19.096 | -8.895 | false |
| 6 | `5,9,5,6,11,3,8,8,3,4,3,9,8,10,6,2` | `rec-1789746768200-683916-5` | checkpointed | 0 | 0 | 0.476424 | -22.724924 | -19.125 | -6.440 | false |
| 7 | `9,6,11,8,8,10,2,12,3,2,5,9,12,4,10,9` | `rec-1789746960096-683916-6` | checkpointed | 0 | 0 | 0.470687 | -22.859458 | -19.124 | -6.545 | false |
| 8 | `6,11,9,2,2,6,8,11,5,6,12,9,5,6,11,10` | `rec-1789747143881-683916-7` | published | 0 | 0 | 0.397382 | -22.985244 | -19.104 | -8.016 | false |
| 9 | `10,3,10,3,8,4,8,6,11,3,9,5,9,7,5,6` | `rec-1789747356211-683916-8` | published | 0 | 0 | 0.355388 | -22.447512 | -19.093 | -8.986 | false |

registration 覆盖：`church_reed_duo` 4 个（1/3/5/8），`processional_reeds_pair` 4 个（2/6/7/9），`bright_chapel_principal` 1 个（4）。9 个 stage6 stub/render/check 均成功；前 7 个执行 bridge_build/bridge_run，后 2 个未消费，不算 bridge 样本。

### 实际输出路径

以下规则精确定位每一行的产物。原始产物保留在本机 `/tmp`，不会随文档提交持久化。

- `/tmp/mana73-weaver-state/`：`weaver_exit_report.json`、`weaver_throughput_report.json`、`weaver_asset_ledger.json`、`stage5_combination_ledger.json`、`bridge_journal.jsonl`、`run.log`、`process_exit_code.txt`。
- 每行日志：`/tmp/mana73-weaver-state/logs/<record_id>/stage5_audio.log`；额外 M1 校验日志为同目录 `m1_audit.log`。
- 完整原始音频产物：`/tmp/mana73-weaver-work/<record_id>/audio/`，含 `soundscape_selection.json`、`m1_validation_report.json`、`offline_audio.wav`；stage6 在相邻 `stub/`、`video/`。
- 发布路径：`/tmp/mana73-weaver-buffer/comb-<combination_id 将逗号换成连字符>/`，直接含 selection、M1 report、WAV、manifest。例如第 1 行为 `/tmp/mana73-weaver-buffer/comb-9-11-4-11-6-8-5-2-12-4-3-9-10-9-6-9/`。
- peak/RMS 来自 `soundscape_selection.json` 的 `mix_bus`；LUFS/true-peak/clipping 来自独立校验后的 work `m1_validation_report.json` 的 `summary`，并有 `m1_audit.log` 印证。校验使用 work 音频，避免改动已发布资产的摘要契约。

## 失败率与分布

检索全部 stage5 日志中的硬中断消息，包括可能存在的 attempt 归档：

| mix SystemExit 消息 | 命中数 | 组合失败率 |
| --- | ---: | ---: |
| `soundscape RMS guardrail` | 0 | 0/9 |
| `soundscape peak guardrail` | 0 | 0/9 |
| `soundscape mix bus checks failed` | 0 | 0/9 |
| 去重 mix 中断合计 | 0 | 0/9 (0%) |

exit report 的 `failed_records=[]`；throughput 的 `failed_records=0`、`recovered_records=0`。ledger 9 条均 `attempts=1`，没有失败后重试成功造成的漏计。

“分布内部”仅指本次合法生成、独立校验通过的 9 个样本的 min/max 区间，不宣称穷举全部合法组合。所有数值门禁均 9/9 通过、0/9 越界：

| 门禁 | 当前阈值 | 实测 min | 实测 max | N | 落在样本分布内部 | 建议值 |
| --- | ---: | ---: | ---: | ---: | --- | ---: |
| `target_peak_min_amplitude` | 0.12 | 0.355388 | 0.476424 | 9 | 否，下方 | 0.12 |
| `target_peak_max_amplitude` | 0.92 | 0.355388 | 0.476424 | 9 | 否，上方 | 0.92 |
| `peak_ceiling_amplitude` | 0.92 | 0.355388 | 0.476424 | 9 | 否，上方 | 0.92 |
| `target_rms_min_dbfs` | -28.0 | -23.071051 | -22.447512 | 9 | 否，下方 | -28.0 |
| `target_rms_max_dbfs` | -10.0 | -23.071051 | -22.447512 | 9 | 否，上方 | -10.0 |
| `target_lufs_min` | -20.0 | -19.125 | -19.090 | 9 | 否，下方 | -20.0 |
| `target_lufs_max` | -18.0 | -19.125 | -19.090 | 9 | 否，上方 | -18.0 |
| `true_peak_ceiling_dbtp` | -0.5 | -8.986 | -6.440 | 9 | 否，上方 | -0.5 |

`require_no_clipping=true`：9/9 `clipping_detected=false`。RMS 下限余量 `4.928949 dB`；LUFS 下限余量 `0.875 LU`、上限余量 `1.090 LU`；true-peak 上限余量 `5.940 dB`。peak ceiling 是混音归一化上限，表内为交付 PCM 的 peak，不冒充 limiter 前分布。

LUFS、true-peak、clipping 由 `validate_m1_artifacts.py` 检查，不属于 mix 函数内的三种 SystemExit。对每个完整 work/audio 目录另行执行校验，9 次均 exit 0，不以 mix fail=0 代替响度验收。

## 吞吐与限制

`generation_assets_per_minute=0.301944`，`playback_assets_per_minute=396.003756`，`required_playback_assets_per_minute=5.0`，资产时长 12 秒；`sustainable_live=false`、`verdict=cannot_sustain_live`。`play-seconds=0` 使 fake 消费接近即时，不代表真实播放吞吐；同时本机生成吞吐也低于 5/min。这是容量信号，不是 mix 失败，不宣称通过可持续直播验收。

覆盖范围是 loop-count=1、系统 FluidR3、默认 profile 的有限样本，不能证明全部组合、长 loop 或其他 SoundFont 零失败。若假设独立同分布，0/9 的单侧 95% 二项失败率上界仍约 28.3%；满足 ≥7 样本要求不等于统计证明总体失败率低于 1/7。

## 决策

1. 按 recommended 自决：保留 -28 RMS 和其他门禁；实测无理由放宽或收紧。不改编排、不加依赖、不做 #66 RTMPS soak。
2. 纳入所有 9 个生成组合，不丢弃缓冲样本；消费分母单列 7。
3. 不重跑 `7e437ac`；不以 #63 的 -28.034991 样本替代现行 #75 trim + #72 coupling 下的证据。无修复，故无修复前后对照。
4. 图索引来自另一工作区，generation=`2026-09-17T13:46:28Z`，coverage 提示 metadata_changed/not_tracked；控制流结论回退核对本工作区源码与日志，不依赖旧图行号。
5. Rust 入口 primary LSP clean；验收主体为真实 bounded dry-run、9 次 M1 校验及证据一致性检查。无代码/配置改动，跳过授权路径守卫。运行期间出现的非目标 `.mana/run-73/brief.md` 保留，不纳入文档提交。
