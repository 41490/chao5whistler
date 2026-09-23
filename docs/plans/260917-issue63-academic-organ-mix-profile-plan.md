# issue #63 — academic organ mix profile：plan / 实现记录

范围：`src/musikalisches` 的 stage5 synth profile 扩展（profile-dsp lane）、
BS.1770 响度计量与门禁（loudness-mix lane）、A/B 机检（ab-verify lane）。
本文件是这三条 lane 合并后的单一事实记录：契约、取舍、阈值来源、已知偏差。

## 1. 交付物

| 路径 | lane | 内容 |
| --- | --- | --- |
| `runtime/src/lib.rs` | profile-dsp | `mix` / voice_group 新字段、Schroeder reverb、master trim、CC7/CC10/CC91 |
| `runtime/config/stage5_academic_organ_dry_synth_profile.json` | profile-dsp | 显式 dry 基线（reverb off、velocity 平、无 EQ/pan/automation） |
| `runtime/config/stage5_academic_chapel_synth_profile.json` | profile-dsp | enhanced：短 chapel reverb + velocity 曲线 + 声部 EQ/pan + 轻 gain automation |
| `tools/loudness_meter.py` | loudness-mix | stdlib BS.1770-4 计量（integrated / short-term / dBTP / clipping / spread） |
| `runtime/config/stage5_default_soundscape_profile.json` | loudness-mix | mix_bus 响度与真峰门禁、envelope coupling |
| `tools/validate_m1_artifacts.py` | loudness-mix | 把计量写进 `m1_validation_report.json` 并对 mix_bus 门禁断言 |
| `tools/build_stage5_unique_stream.py` | loudness-mix | envelope-coupled bed gain |
| `tools/verify_academic_profile_ab.py` | ab-verify | dry/enhanced 产物目录 A/B 机检（本 lane） |

## 2. profile 契约

顶层新增可选 `mix` 块，voice_group 新增可选字段；**全部缺省即旧行为**，
`skip_serializing_if` 保证既有 profile 产物逐字节不变（有单测覆盖）。

```text
mix.reverb{enabled,wet,dry,decay_seconds,room_size,damping,render_tail_seconds}
mix.master_trim_db
mix.dynamic{velocity_depth,phrase_period_quarters,beat_accent_pattern}
mix.ab_expectations{dynamic_spread_gain_db_min,reverb_tail_dbfs_min,lufs_band,lufs_band_basis}
voice_group.{velocity_curve,eq{gain_db,tilt},pan,gain_automation{depth_db,period_quarters}}
```

应用点：

- `build_synth_event_sequence`：per-event velocity 写 `note_on` 的 `data2`；
  profile opt-in 时追加 CC7/CC10/CC91 setup。
- `render_fallback_pcm`：EQ gain/tilt、pan、gain automation。
- `apply_synth_event`：SoundFont 路径下发 CC7/CC10/CC91。
- `finalize_audio_render`：reverb 与 master trim。

`mix.ab_expectations` 只在 Python 侧被读取，Rust 侧不执行门禁——阈值属于验收契约，
不属于渲染契约。

## 3. reverb 算法与截断取舍

Freeverb 风格 Schroeder：4 个并行阻尼 comb（1116/1188/1277/1356 采样，按
`room_size` 与采样率缩放，feedback 由 `decay_seconds` 反推，clamp 0.98）+ 2 个
allpass（556/441），干湿按 `dry`/`wet` 混合。纯算法，无 IR 资产、无新增 crate。

Issue #71 已采用渲染追加 tail：`apply_reverb` 仍保持等长，但调用前给 PCM
追加 `round(render_tail_seconds * sample_rate)` 个零输入帧，只在 enabled 且 tail > 0
时执行。尾巴只加在完整组合末尾，不改变 note/realization/cycle 时长。
字段必须有限且非负，默认 0.0 且零值不序列化；默认与 dry 仍为 12.0 s。
`AudioRenderSummary` 的 frames/duration 是实际 WAV 长度，分析窗口覆盖全部 PCM；
`StreamLoopPlan.render_tail_seconds` 是下游尾长的权威来源，total_duration 仍指组合。
单测覆盖零值逐字节序列化、禁用/零值不扩展与 WAV summary 自洽。

## 4. 响度计量与门禁来源

- 计量：`tools/loudness_meter.py`，`MEASUREMENT_ID=bs1770_4_kweighting_stdlib_v1`。
  K-weighting 按采样率重推（高架 ~1682 Hz + RLB 高通 ~38 Hz，transposed direct
  form II 单趟输出平方累积和，不分配滤波缓冲）；integrated 用 400 ms 块 / 75 %
  重叠 / −70 LUFS 绝对门 + −10 LU 相对门；short-term 为 3 s 滑窗 / 100 ms hop；
  dBTP 是采样峰值估计（不做 4× 过采样，作为门禁只会偏保守）；clipping 为
  ≥3 个连续满量程样本；`dynamic_spread_db` 为 400 ms 窗 RMS 的 p95−p5。
  `--self-test` 钉住 1 kHz −20 dBFS RMS → −19.994 LUFS，并断言静音块被门控、
  1.5× 削顶正弦被标记。
- 门禁：`stage5_default_soundscape_profile.json` 的 `mix_bus_profile`
  （`target_lufs_min/max`、`true_peak_ceiling_dbtp`、`require_no_clipping`、
  `envelope_coupling`），由 `validate_m1_artifacts.py` 读回并断言，阈值不重复硬编码。
- 计量对象：`offline_audio.wav` 的 note-active 区 `[0,last_note_off)`（render-audio premix，即 soundscape mix bus 之前）；尾区只由 c 判定。脚本报告的 `duration_seconds` 是该 note-active 区时长。

## 5. A/B 判定阈值与反例

`tools/verify_academic_profile_ab.py` 对两个**已渲染**目录做机检，无渲染副作用。

| id | 断言 | 阈值来源 |
| --- | --- | --- |
| a | `note_event_sequence.json` / `event_transition_sequence.json` / `realized_fragment_sequence.json` 两侧逐字节一致 | profile 不得改变 note/transition/realization 层 |
| b | note-active premix `dynamic_spread_db(enh) ≥ dynamic_spread_db(dry) + 1.5 dB` | `ab_expectations.dynamic_spread_gain_db_min` |
| c | enhanced 存在 `start_seconds >= last_note_off` 窗口，最大窗口 RMS dBFS ≥ −45；无尾区即 FAIL | `ab_expectations.reverb_tail_dbfs_min`，无 dry/增益补偿 |
| d | 主层 envelope 峰值保留 ≥ 0.8×，且 note-active short-term 波动范围更宽 | 脚本常数 `MELODY_PEAK_RETENTION_MIN` |
| e | note-active premix `integrated_lufs(enh) ∈ lufs_band`，不含尾部，dry 只记录 | `ab_expectations.lufs_band` |

实测（demo rolls，44.1 kHz，FluidR3_GM）：

```text
dry : integrated -18.994 LUFS, spread 3.765 dB, short-term 1.657 dB
enh : integrated -18.997 LUFS, spread 6.392 dB, short-term 3.208 dB
premix spread gain = 2.627 dB >= 1.5 dB（note-active 区）
尾区不参与 b/d/e；c 单独使用完整分析窗口判定绝对 dBFS 地板。
```

`MELODY_PEAK_RETENTION_MIN = 0.8`：允许声部 EQ/pan/velocity 改动把主层压低
约 2 dB；实测 retention = 0.0647 / 0.0553 = 1.17。

反例（必须失败）：

```bash
python3 src/musikalisches/tools/verify_academic_profile_ab.py \
  --dry /tmp/ab63-dry --enhanced /tmp/ab63-dry \
  --profile src/musikalisches/runtime/config/stage5_academic_chapel_synth_profile.json
```

结果：exit 1，失败 b（spread gain 0.0 < 1.5）、c（no observable tail region.）、d
（short-term range 相等）。a、e 按设计仍通过——它们不是“增强存在性”的判据。

### 5.1 断言 c 的偏差：Issue #71 已解决

已删除稀疏窗口回退和 normalization gain 补偿，仅取增强侧最后 note_off 之后的
完整窗口，使用最大窗口 RMS 的绝对 dBFS 判断尾巴是否存在，不要求衰减末端维持地板。
无窗口明确报 `c: no observable tail region.`；dry 不参与补偿或同位置比较。
chapel 选择 2.0 s：实测 50 个 40 ms 尾窗口，首窗 [12.0,12.04] s RMS
−36.159 dBFS ≥ −45.0；末窗 [13.96,14.0] s RMS 0.000002（约 −114 dBFS），
已充分衰减。WAV 为 617400 帧 / 14.0 s；dry 为 529200 帧 / 12.0 s，无尾窗。
正例 a–e 全 PASS，dry/dry 反例 b/c/d FAIL。追加尾区使全 WAV 的 spread 增大，
b 仍按原契约记录完整 premix WAV，不将其解释为纯演奏段动态增益。

stream 时长门禁读取 `stream_loop_plan.json.render_tail_seconds`，比较
combination + tail，容差保持 ±0.01，并记录 expected_tail_seconds。
`validate_m1_artifacts.py` 原时长比较均为组合对组合、WAV 对 WAV，无需放宽；
其 setup 计数修正为 program-change + control-change，以接受 chapel CC7/10/91。

## 6. 已知偏差

1. **`lufs_band` 校准到 premix 实测**：原声明带 `[-20,-18]` 在任何路径都不可达
   （混音总线还要再施加 `main_gain_db=-1` 并叠加 bed，只会更低），按实测收紧为
   `[-20.0,-18.0]`，并显式标注 `lufs_band_basis=premix_render_offline_audio_note_region`；b/d/e 均只量 note-active 区，不含尾部。
   仓内 −18..−20 LUFS 约定的落差由 per-registration trim / 响度归一化另行解决，
   不在本 lane 伪达标。**该偏差已由 issue #70 解决：见 §9。**
2. **mix_bus `target_rms_min_dbfs` −28 → −30**：先存缺陷修正。原下限对
   ambient/drone 叠加后的总线不可达，会稳定误报；放宽到 −30 dBFS 让门禁恢复
   可满足性。这是一次性校正，不是新契约。
3. **A/B 的动态断言只在 premix 上做**：恒定 bed 抬高相对门，混音后 spread 被压缩
   （实测 4.47 → 3.74 dB），在 final mix 上断言动态会误判。final mix 只用
   mix_bus 既有响度/真峰/削顶字段。

## 7. 后续建议

- **per-registration trim**：把 dry/chapel 的 `master_trim_db` 从固定值改为按
  registration 标定，消除 §6.1 的 −18..−20 LUFS 落差。**已在 issue #70 落地，见 §9。**
- **响度归一化 + 收紧阈值**：在 mix bus 之后做 integrated 归一化，再把
  `target_lufs_min/max` 收窄到 ±1 LU，让 `lufs_band` 成为真正的门禁而不是记录。
- **恒定 bed 压缩动态**：bed 抬高相对门会吃掉 spread；若要保住动态，需要在
  envelope coupling 之外引入 per-layer 的相对门补偿（或对 bed 施加与 envelope
  反向的增益），否则 spread 类判据在 final mix 上永远偏悲观。
- **渲染尾部：Issue #71 已采用方案 1**。完整组合末尾追加零输入并送入 reverb，
  chapel 设置 `render_tail_seconds=2.0`；不采用仅分析器标注方案。
  cycle 保持原语义，交付 WAV 包含 tail，门禁按组合 + tail 检查，不裁掉尾巴。

## 8. 复现命令

Issue #71 验收：`/tmp/ab71-enh` / `/tmp/ab71-dry`；正例 report
`/tmp/ab71-positive.json` 五项 PASS，反例 `/tmp/ab71-negative.json` b/c/d FAIL。
`cargo test --manifest-path Cargo.toml`：73 passed（63 unit + 10 e2e）；
`make -C src/musikalisches stage5-golden`：4/4。默认 LOOP_COUNT=16 stream/check
通过，8467200 帧 / 192 s，−19.033 LUFS。chapel LOOP_COUNT=1 stream/check
通过，`/tmp/ab71-stream-tail/m1_validation_report.json` 的时长门禁记录
actual=expected=14.0、expected_tail_seconds=2.0，最终 −19.031 LUFS。
默认 demo 与 b7f1ca90 独立构建产物目录 `diff -qr` 无差异（含 WAV/JSON）。

```bash
cargo run -- render-audio --work mozart_dicegame_print_1790s --demo-rolls \
  --synth-profile src/musikalisches/runtime/config/stage5_academic_organ_dry_synth_profile.json \
  --output-dir /tmp/ab63-dry
cargo run -- render-audio --work mozart_dicegame_print_1790s --demo-rolls \
  --synth-profile src/musikalisches/runtime/config/stage5_academic_chapel_synth_profile.json \
  --output-dir /tmp/ab63-enh
python3 src/musikalisches/tools/verify_academic_profile_ab.py \
  --dry /tmp/ab63-dry --enhanced /tmp/ab63-enh \
  --profile src/musikalisches/runtime/config/stage5_academic_chapel_synth_profile.json \
  --report /tmp/ab63-report.json
```

## 9. issue #70 — per-registration 静态 trim 与门禁收紧

目标：把最终混音 WAV（交付面）的 integrated loudness 收进 **−18…−20 LUFS**，
并把 `mix_bus_profile` 的响度门禁同步收紧。CTO 定稿：采用 **per-registration
静态 trim**（不用实测 LUFS 归一化），trim 写成 profile 常量。

### 9.1 trim 字段与施加点

`stage5_default_soundscape_profile.json` 的 `main_registration_profiles[]` 新增
可选 `gain_db`（缺省 `0.0`，向后兼容）。`build_stage5_unique_stream.py`：

- `resolve_registration_choice` 把 `gain_db` 带进 `registration_choice`；CLI
  `--synth-profile` 覆盖路径固定 `0.0`（覆盖 profile 时不做标定）。
- `apply_soundscape_mix` 在 dB 域串联：
  `main_layer_gain_db = main_gain_db + registration_trim_db`，再换算成线性增益乘进
  main organ 层（bed 增益不变）。
- 日志：`soundscape_selection.json` 的 main 层条目记录生效的 `gain_db`、
  `main_gain_db`、`registration_trim_db`；`registration` 块记录 `gain_db`。

### 9.2 trim 依据与实测分布

标定流程（每 registration 以 `--synth-profile` 覆盖 + soundscape profile 渲染，
`LOOP_COUNT=4`，用 `tools/loudness_meter.py` 量最终 `offline_audio.wav`）：

```text
registration              trim=0 实测      trim 终值   4-cycle 终值分布 (n)
church_reed_duo           -23.448          4.83       [-19.813, -18.650] (11)
bright_chapel_principal   -22.246          3.43       [-19.448, -18.479] (13)
processional_reeds_pair   -24.575          6.36       [-19.900, -18.467] (12)
```

trim 取 `−19.0 − 该 registration 实测中心`，使分布中心落在 −19.0、两侧各留
~1.0 dB。36 个 4-cycle 样本（3 个 registration）全部落 `[-20,-18]`，每
registration spread ≤ 1.43 dB；16-cycle 样本与 4-cycle 相差 < 0.4 dB（长 loop
只是重复同一 cycle，不改变内容响度）。

已知残差：追加批次（另 45 个 4-cycle 样本）中出现 1 例 `church_reed_duo`
= −20.048 LUFS（越下限 0.048 dB）。这是组合内容响度 spread（约 1.4 dB）与 2 dB
门禁带叠加后的尾部，不是 trim 标定错误；静态 per-registration trim 无法逐组合
补偿。该组合会被 `validate_m1_artifacts.py` 如实判失败，不做伪达标。

### 9.3 门禁阈值前后对照

| 字段 | issue #63 值 | issue #70 值 |
| --- | --- | --- |
| `target_lufs_min` | −27.0 | **−20.0** |
| `target_lufs_max` | −12.0 | **−18.0** |
| `target_rms_min_dbfs` | −30.0 | **−28.0**（收回 #63 的一次性放宽） |
| `true_peak_ceiling_dbtp` | −0.5 | −0.5（不变） |
| `require_no_clipping` | true | true（不变） |
| `peak_ceiling_amplitude` | 0.92 | 0.92（不变） |

### 9.4 academic profile 同步收紧

- `stage5_academic_organ_dry_synth_profile.json`：`mix.master_trim_db` `0.0 → 3.95`
  （premix integrated −22.944 → **−18.994**）。
- `stage5_academic_chapel_synth_profile.json`：`mix.master_trim_db` `−0.5 → 2.64`
  （premix −22.137 → **−18.997**）；`ab_expectations.lufs_band`
  `[-24.0,-21.5] → [-20.0,-18.0]`（basis 仍为 `premix_render_offline_audio`）。

抬 trim 后两侧 `normalization_gain` 均为 1.0（峰值 < 0.95，不再触发渲染器峰值
归一化），A/B 五条断言全过：

```text
a_sequence_identity      PASS
b_premix_dynamic_spread  PASS  (gain 2.627 dB >= 1.5)
c_reverb_tail            PASS  (excess 2.768 dB, compensation -1.31 dB)
d_melody_unmasked        PASS  (retention 1.066 >= 0.8; range 3.208 > 1.657)
e_lufs_band              PASS  (enhanced -18.997 in [-20.0,-18.0])
```

反例（`--enhanced /tmp/i70-dry`）exit 1，失败 b/c/d（与 #63 一致）。

### 9.5 issue #70 验收记录

```text
(a) 4-cycle, 3 个不同 combination 覆盖 3 registration（官方 stage5-stream + stage5-stream-check）:
    church_reed_duo         -19.119 LUFS  tp -7.382 dBTP  clip False
    processional_reeds_pair -18.086 LUFS  tp -6.715 dBTP  clip False
    bright_chapel_principal -18.941 LUFS  tp -7.490 dBTP  clip False
    其余 7 个已跑 combination 亦全部落带。
(b) LOOP_COUNT=16 stage5-stream + stage5-stream-check: exit 0
    church_reed_duo -19.465 LUFS  tp -7.278 dBTP  clip False
(c) A/B 正例 exit 0；反例 exit 1
(d) cargo test: 70 passed / 0 failed, exit 0；stage5-golden: 4/4
(e) check-mana-grant-scope: exit 0
```

## 10. issue #75 — 逐组合一次性前馈响度标定（方案 A）

### 10.1 方案定稿

CTO intake 定稿方案 A，解除 #70「不做实测归一化」限制，边界严格执行：

- **测量对象**：渲染完成、叠加 bed 之前、未过限幅器的主层 `offline_audio.wav`
  （Rust `render-audio` 输出）。施加点在 `apply_soundscape_mix` 读入主层 PCM 之后、
  混音之前，直接调用 `tools/loudness_meter.py` 的 `measure_pcm`（复用 API，零实现拷贝）。
- **一次性前馈**：`combination_trim_db = COMBINATION_TARGET_LUFS - measured_main_lufs + bed_offset_db`，
  其中 `COMBINATION_TARGET_LUFS = -19.0`（`target_lufs_min/max` 带心中点，带门禁不动）。
  `main_layer_gain_db = main_gain_db + combination_trim_db` —— **替换**（而非叠加）
  registration 常量 trim，仍是单增益级；无迭代收敛；最终混音不再测量回改。
- **回退**：`measured_main_lufs is None`（如全静默渲染）时 `trim_source="fallback"`，
  退回 registration `gain_db` 常量（#74 语义，向后兼容）；CLI 覆盖路径在此分支额外
  向 stderr 告警。`trim_source` / `measured_main_lufs` / `combination_trim_db` /
  `bed_offset_db` 写入 `soundscape_selection.json`（main 层条目 + `mix_bus` 块）供审计。

### 10.2 `bed_offset_db` 实测标定

**语义**：设 K 为「混音链路固定偏移」—— `final = measured_main + combination_trim + K`，
K 包含 `mix_bus_profile.main_gain_db = -1.0` 的串联、drone/ambient 叠加的净功率贡献、
`post_mix_gain`（本工作点恒为 1.0）与 int16 量化。公式要求
`bed_offset_db = -K̄`（注意**取负**：K 使 final 偏低，需在 trim 中补回）。

**方法**：`bed_offset_db` 缺省 0.0（向后兼容），渲染 12 个 4-cycle 全新组合
（4 并行 worker × 独立 ledger，3 registration 覆盖），逐样本计算
`δ_i = final_integrated_lufs - (measured_main_lufs + combination_trim_db)`。

**结果**：δ ∈ [-0.793, -0.781]，mean = **-0.787 dB**，stdev 0.0037
（12/12 validator exit 0）。写入 `mix_bus_profile.bed_offset_db = 0.787`。

**校准教训（如实记录）**：首轮标定曾把 δ 本身（-0.787）直接写入 profile，
60 样本验证批次随之系统性落在 -20.53 LUFS（±0.01，全部越下限）。以单样本
probe 定位：`post_mix_gain=1.0`、final peak 0.326 << ceiling 0.92，排除
「ceiling clamp 激活的工作点」假设；真实主项是 `main_gain_db=-1.0` 串联偏移。
修正为 `bed_offset_db = -δ = +0.787` 后单样本归位 -19.035，60 样本归位 -19.035 ± 0.01。

### 10.3 分布前后对照

**修复前**（#74 per-registration 静态 trim）：

- issue #75 记录：81 个 4-cycle 样本出现 1 例 `church_reed_duo = -20.048 LUFS`
  （越下限 0.048 dB，≈1.2%）；单 registration 内组合内容响度 spread ≈ 1.2–1.4 dB。
- 本 lane 复现批次（独立 ledger、base 代码 `941d7c7`，4-cycle）：n=200，
  唯一越带样本 min = **-20.122**（run #185，`church_reed_duo`，组合
  `4,10,11,7,11,3,2,9,6,7,5,9,5,9,2,3`，越下限 0.122 dB），与 issue #75 记录的
  -20.048 尾部同型（0.5% vs 1.2%，同量级）。

**修复后**（逐组合前馈标定，`bed_offset_db=0.787`）：

- **60 个全新组合**（4 独立 ledger × 15，与复现/校准批次组合零重叠，
  3 registration 各 20）：
  `integrated_lufs` min / max / mean = **-19.053 / -19.029 / -19.035**
  （全带宽仅 0.024 dB），**100% 落 [-20.0, -18.0]**；`clipping_detected=false` ×60；
  `true_peak_dbtp` max = -6.143 ≤ -0.5；`trim_source=measured` ×60；
  逐样本 `validate_m1_artifacts.py` exit 0 ×60。
- 官方链路 `LOOP_COUNT=16 make stage5-stream && stage5-stream-check`：exit 0，
  final = **-19.037** LUFS。
- **复现组合回归**：同一组合 `4,10,11,7,11,3,2,9,6,7,5,9,5,9,2,3`
  （定点重渲染，fixed-rolls harness）：base 实现 -20.122 越带 → 新实现
  **-19.038** 落带，`trim_source=measured`、validate exit 0。

残差归零机理：静态 trim 只补偿 registration 均值，组合内容 spread（1.2–1.4 dB）
原样漏进门禁带；前馈 trim 把**每个组合**的主层钉到 -19.0 + bed_offset，
spread 被前馈抵消，仅剩链路偏移的逐组合微差（<0.05 dB）。

### 10.4 CLI 覆盖边角定稿

定稿选择：**集中 gain 解析（仍得到组合 trim）**。`--synth-profile` 覆盖与默认
registration 池共用 `apply_soundscape_mix` 内的唯一 trim 解析点；测量可用时覆盖
路径同样得到 `trim_source=measured` 的组合 trim，#70 时代「固定 `gain_db: 0.0`
静默关闭标定」的行为不复存在。测量不可用时显式告警（stderr）+ `trim_source=fallback`
留输出证据。拒绝「显式拒绝该参数」选项：`--synth-profile` 是 academic A/B 与
weaver 适配层的合法入口，拒绝会破坏既有用法。

**证据**：`--synth-profile stage5_default_synth_profile.json` 渲染样本 →
`selection_source=cli_override`、`trim_source=measured`、`combination_trim_db=5.188`、
final = **-19.047** LUFS 落带、`validate_m1_artifacts.py` exit 0、无 fallback 告警。

### 10.5 issue #75 验收记录

```text
(a) cargo test: exit 0（0 failed）
(b) make stage5-golden: 4/4 passed（demo / all_sevens / high_low / ascending_twice）
(c) verify_academic_profile_ab.py: 正例 exit 0（5 断言 PASS）/ 反例 exit 1
(d) LOOP_COUNT=16 stage5-stream && stage5-stream-check: exit 0，final -19.037 LUFS
(e) check-mana-grant-scope --base origin/main（4 allow-path）: exit 0，
    改动仅 src/musikalisches/{tools/build_stage5_unique_stream.py,
    runtime/config/stage5_default_soundscape_profile.json, README.md}
(f) 60 全新组合: 100% 落带（见 §10.3）
(g) profile 键变更清单: mix_bus_profile 新增 bed_offset_db（唯一新键，
    缺省 0.0 向后兼容）；其余键值未动；registration gain_db 保留为回退常量
```

## 11. issue #72 — 同组合 envelope coupling 对照与默认决策

### 11.1 实验边界

本 lane 工作目录 `/opt/src/41490/chao5whistler-72-envelope-coupling`，
基线 `a1a6efee`。仅首次抽取 combination；纯主层与 on 复用相同 rolls、
registration、44.1 kHz、120 BPM、40 ms 分析窗、4 cycles / 48 s。
独立 ledger `/tmp/mana72-ledger.json` 仅有一条记录，仓内默认 ledger 未使用。

```json
{
  "combination_id": "4,4,2,11,11,8,6,6,10,2,4,3,7,5,11,9",
  "rolls": [4,4,2,11,11,8,6,6,10,2,4,3,7,5,11,9],
  "registration_id": "church_reed_duo",
  "synth_profile_id": "stage5_default_dual_voice_organ_family",
  "main_layer_gain_db": 4.71,
  "main_envelope_peak": 0.051795
}
```

纯主层是 runtime 原始 premix，不再叠 bed 或施加 mix_bus trim；off/on
都从该主层混音，主层增益一致。纯主层 LUFS 不作为交付带门禁。
三个目录的 `analysis_window_sequence.json` 相同（混音保留主层分析），
峰值均为 0.051795，不能将它误解为混音后重测的 envelope。
on/off 的 `selected_asset_ids` 相同，on 不是在 off WAV 上重复叠加。

### 11.2 命令与原始摘要

首次命令在默认仍为 off 时运行，exit 0；之后未再运行随机构建器做三组比较：

```bash
python3 src/musikalisches/tools/build_stage5_unique_stream.py \
  --work-id mozart_dicegame_print_1790s --loop-count 4 \
  --ledger-path /tmp/mana72-ledger.json --output-dir /tmp/mana72-off \
  --soundscape-profile src/musikalisches/runtime/config/stage5_default_soundscape_profile.json
cargo run -- render-audio --work mozart_dicegame_print_1790s \
  --rolls 4,4,2,11,11,8,6,6,10,2,4,3,7,5,11,9 --loop-count 4 \
  --analysis-window-ms 40 --tempo-bpm 120 --sample-rate 44100 \
  --synth-profile src/musikalisches/runtime/config/stage5_default_synth_profile.json \
  --output-dir /tmp/mana72-main
```

重混使用以下 API 调用（exit 0）。临时 profile 仅将 enabled 从 false 改 true，
其余字段不变；复现历史 off 时应使用 `a1a6efee` 的 profile，当前默认已改 on。
`render-audio` 本身不叠 soundscape，因此纯主层无需构建器的 `--no-soundscape`。

```python
# PYTHONPATH=src/musikalisches/tools python3
from pathlib import Path
import shutil
import build_stage5_unique_stream as b

off, main, on = map(Path, ('/tmp/mana72-off', '/tmp/mana72-main', '/tmp/mana72-on'))
selection = b.load_json(off / b.SELECTION_FILE)
registration = b.load_json(off / b.SOUNDSCAPE_SELECTION_FILE)['registration']
assert selection['rolls'] == [4,4,2,11,11,8,6,6,10,2,4,3,7,5,11,9]
assert (off / 'analysis_window_sequence.json').read_bytes() == (main / 'analysis_window_sequence.json').read_bytes()
b.augment_selection_artifact(main, selection)
shutil.copytree(main, on)
profile = b.load_json(b.DEFAULT_SOUNDSCAPE_PROFILE)
assert profile['mix_bus_profile']['envelope_coupling'] == {'enabled': False, 'depth_db': 6.0}
profile['mix_bus_profile']['envelope_coupling']['enabled'] = True
profile_path = Path('/tmp/mana72-on-profile.json')
b.write_json(profile_path, profile)
b.apply_soundscape_mix(artifact_dir=on, selection=selection,
    soundscape_profile=b.load_soundscape_profile(profile_path), registration_choice=registration)
assert b.load_json(on / b.SOUNDSCAPE_SELECTION_FILE)['selected_asset_ids'] == b.load_json(off / b.SOUNDSCAPE_SELECTION_FILE)['selected_asset_ids']
```

三条 CLI 各 exit 0，计量对象均为完整 `offline_audio.wav`：

```bash
python3 src/musikalisches/tools/loudness_meter.py /tmp/mana72-main/offline_audio.wav
python3 src/musikalisches/tools/loudness_meter.py /tmp/mana72-off/offline_audio.wav
python3 src/musikalisches/tools/loudness_meter.py /tmp/mana72-on/offline_audio.wav
```

| 组 | integrated LUFS | spread dB | short-term min / max LUFS | true peak dBTP | clipping |
| --- | ---: | ---: | --- | ---: | --- |
| 纯主层 | -23.923 | 6.814 | -25.404 / -23.027 | -11.658 | false |
| off | -19.030 | 6.041 | -20.354 / -18.202 | -6.819 | false |
| on, depth=6 | -19.102 | 6.544 | -20.504 / -18.241 | -6.824 | false |

CLI JSON 原始字段摘要（表格之外的共同字段及增益摘要）：

```json
{
  "common_meter_fields": {
    "measurement": "bs1770_4_kweighting_stdlib_v1",
    "sample_rate": 44100, "channels": 2, "frames": 2116800,
    "duration_seconds": 48.0, "block_count": 477, "gated_block_count": 477,
    "short_term_window_count": 451, "longest_clip_run_samples": 0,
    "clipped_sample_count": 0
  },
  "off_gain_db_summary": {
    "drone": {"min_db": -15.0, "max_db": -15.0, "mean_db": -15.0},
    "ambient": {"min_db": -20.0, "max_db": -20.0, "mean_db": -20.0}
  },
  "on_gain_db_summary": {
    "drone": {"min_db": -20.467709, "max_db": -15.0, "mean_db": -17.287577},
    "ambient": {"min_db": -25.467709, "max_db": -20.0, "mean_db": -22.287577}
  }
}
```

### 11.3 决策

**默认开启，depth_db 保持 6.0。** 按 brief 的 recommended 规则自决：
`6.544 >= 6.041`、`-19.102 ∈ [-20,-18]`、`clipping_detected=false`，全部满足。
耦合赚回 0.503 dB，即恒定 bed 损失 0.773 dB 的约 65.1%；仍比纯主层低
0.270 dB，不声称完全恢复。只改默认 enabled，不改 trim、bed 资产或实现。
这是一组固定 combination 的实证，不推广为所有组合 spread 必然改善；
另用官方 16-cycle 链路验证当前默认可交付，不把其不同组合当 A/B 数据。
计量器的 true_peak 是采样峰值估计，不声称测得过采样 inter-sample peak。

### 11.4 验收

均在本 worktree 执行。A/B dry/enhanced 按 README 单独渲染 demo rolls，
不与上述 coupling 三组混用。

```bash
cargo test --manifest-path Cargo.toml
cargo run -- render-audio --work mozart_dicegame_print_1790s --demo-rolls \
  --synth-profile src/musikalisches/runtime/config/stage5_academic_organ_dry_synth_profile.json \
  --output-dir /tmp/mana72-ab-dry
cargo run -- render-audio --work mozart_dicegame_print_1790s --demo-rolls \
  --synth-profile src/musikalisches/runtime/config/stage5_academic_chapel_synth_profile.json \
  --output-dir /tmp/mana72-ab-enhanced
python3 src/musikalisches/tools/verify_academic_profile_ab.py \
  --dry /tmp/mana72-ab-dry --enhanced /tmp/mana72-ab-enhanced \
  --profile src/musikalisches/runtime/config/stage5_academic_chapel_synth_profile.json \
  --report /tmp/mana72-ab-positive.json
python3 src/musikalisches/tools/verify_academic_profile_ab.py \
  --dry /tmp/mana72-ab-dry --enhanced /tmp/mana72-ab-dry \
  --profile src/musikalisches/runtime/config/stage5_academic_chapel_synth_profile.json \
  --report /tmp/mana72-ab-negative.json
STAGE5_LEDGER_PATH=/tmp/mana72-stream-ledger.json LOOP_COUNT=16 \
  make -C src/musikalisches stage5-stream && make -C src/musikalisches stage5-stream-check
python3 ops/scripts/check-mana-grant-scope.py --base origin/main \
  --allow-path src/musikalisches/ --allow-path docs/plans/ \
  --allow-path Cargo.toml --allow-path Cargo.lock
```

| 验收 | exit | 关键输出 |
| --- | ---: | --- |
| cargo test | 0 | 63 unit + 10 e2e passed，0 failed |
| dry / enhanced 渲染 | 0 / 0 | 两目录成功输出 WAV、分析与事件 JSON |
| A/B 正例 | 0 | a/b/c/d/e 全 PASS |
| A/B 反例 | 1（预期） | b: 0.0 < 1.5；c: no observable tail region；d: 1.657 不大于 1.657 |
| 16-cycle stream / check | 0 / 0 | M1 passed；8467200 frames；-19.123 LUFS；5.280 dB spread；-7.034 dBTP；clip false |
| grant scope | 0 | 仅授权路径，见本地提交差异 |

16-cycle 独立 ledger 为 `/tmp/mana72-stream-ledger.json`，组合
`10,3,4,10,9,10,8,11,6,6,12,6,10,10,2,4`，Processional Reeds Pair。
Git worktree 不支持 `jj git init --colocate`；改用 `jj git init --git-repo .`
初始化本目录 jj，以指定 bookmark 本地提交，不 push。
