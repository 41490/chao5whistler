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
mix.reverb{enabled,wet,dry,decay_seconds,room_size,damping}
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

取舍：**reverb 输出与输入等长，尾部被渲染边界截断**。`render-audio` 的总时长由
note 序列决定（demo rolls = 12.0 s，最后一个 note_off 恰好落在 12.0 s），因此
render 里不存在“最后一个 note_off 之后”的窗口，reverb 尾巴在物理上被切掉。
这与 stage5 的循环 stream 语义一致（cycle 必须首尾相接），代价是离线 A/B 无法
用“尾部绝对能量”做判定——见 §5 的替代判据。

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
- 计量对象：`offline_audio.wav`（render-audio premix，即 soundscape mix bus 之前）。

## 5. A/B 判定阈值与反例

`tools/verify_academic_profile_ab.py` 对两个**已渲染**目录做机检，无渲染副作用。

| id | 断言 | 阈值来源 |
| --- | --- | --- |
| a | `note_event_sequence.json` / `event_transition_sequence.json` / `realized_fragment_sequence.json` 两侧逐字节一致 | profile 不得改变 note/transition/realization 层 |
| b | premix `dynamic_spread_db(enh) ≥ dynamic_spread_db(dry) + 1.5 dB` | `ab_expectations.dynamic_spread_gain_db_min` |
| c | reverb 尾部存在，且增强侧在补偿渲染总增益后仍高出干侧 ≥ 1.0 dB | `reverb_tail_dbfs_min`（绝对地板）+ 脚本常数（见下） |
| d | 主层 envelope 峰值保留 ≥ 0.8×，且 short-term 波动范围更宽 | 脚本常数 `MELODY_PEAK_RETENTION_MIN` |
| e | premix `integrated_lufs(enh) ∈ lufs_band`，dry 只记录 | `ab_expectations.lufs_band` |

实测（demo rolls，44.1 kHz，FluidR3_GM）：

```text
dry : integrated -22.944 LUFS, spread 3.765 dB, short-term 1.657 dB
enh : integrated -22.137 LUFS, spread 6.392 dB, short-term 3.208 dB
premix spread gain = 2.627 dB >= 1.5 dB
```

`MELODY_PEAK_RETENTION_MIN = 0.8`：允许声部 EQ/pan/velocity 改动把主层压低
约 2 dB；实测 retention = 0.0647 / 0.0553 = 1.17。

反例（必须失败）：

```bash
python3 src/musikalisches/tools/verify_academic_profile_ab.py \
  --dry /tmp/ab63-dry --enhanced /tmp/ab63-dry \
  --profile src/musikalisches/runtime/config/stage5_academic_chapel_synth_profile.json
```

结果：exit 1，失败 b（spread gain 0.0 < 1.5）、c（excess 0.0 < 1.0）、d
（short-term range 相等）。a、e 按设计仍通过——它们不是“增强存在性”的判据。

### 5.1 断言 c 的偏差（重要）

任务书的字面判据是“最后一个 note_off 之后的窗口能量 ≥ `reverb_tail_dbfs_min`，
dry 侧同一位置不得满足”。在 demo rolls 产物上该区域**为空**（§3 截断），
字面判据不可满足，且 dry 侧“同一位置”也不存在，无法形成对照。实现改为：

1. 优先取 `start_seconds >= last_note_off` 的窗口；为空时退回
   **稀疏释放窗口**（同时发声数 ≤ 1 的窗口，68/300 个），这是唯一不被持续音
   掩盖、能观察到尾部的区域。实际使用的区域记在 report 的 `tail_window_basis`。
2. `finalize_audio_render` 会做峰值归一化并施加 `master_trim_db`，两侧总增益不同
   （dry `normalization_gain` 1.0，chapel 0.944061 → −0.5 dB）。直接比较绝对
   尾部能量测到的是增益差而非 reverb。因此断言 c 从 `artifact_summary.json` 读回
   两侧 `audio.normalization_gain` 做补偿，再要求增强侧仍高出 ≥ 1.0 dB。
3. 实测：稀疏窗口 dry −28.612 dBFS、enhanced −26.344 dBFS、补偿 −0.5 dB 后
   excess = +2.768 dB；`reverb_tail_dbfs_min=-45.0` 的绝对地板同时成立。
4. **未满足的部分**：字面要求的“dry 侧低于绝对地板”在稀疏窗口上不成立（两侧
   都有持续音，dry 也在 −28.6 dBFS）。dry 侧的反证由补偿后的 excess 给出，
   report 里以 `reverb_tail_excess_db` 记录，不伪装成绝对地板判定。
   若将来渲染不再截断（例如渲染器追加 tail 长度），窗口选择会自动回到
   `post_last_note_off`，绝对地板判据随即可用。

## 6. 已知偏差

1. **`lufs_band` 校准到 premix 实测**：原声明带 `[-20,-18]` 在任何路径都不可达
   （混音总线还要再施加 `main_gain_db=-1` 并叠加 bed，只会更低），按实测收紧为
   `[-24.0,-21.5]`，并显式标注 `lufs_band_basis=premix_render_offline_audio`。
   仓内 −18..−20 LUFS 约定的落差由 per-registration trim / 响度归一化另行解决，
   不在本 lane 伪达标。
2. **mix_bus `target_rms_min_dbfs` −28 → −30**：先存缺陷修正。原下限对
   ambient/drone 叠加后的总线不可达，会稳定误报；放宽到 −30 dBFS 让门禁恢复
   可满足性。这是一次性校正，不是新契约。
3. **A/B 的动态断言只在 premix 上做**：恒定 bed 抬高相对门，混音后 spread 被压缩
   （实测 4.47 → 3.74 dB），在 final mix 上断言动态会误判。final mix 只用
   mix_bus 既有响度/真峰/削顶字段。

## 7. 后续建议

- **per-registration trim**：把 dry/chapel 的 `master_trim_db` 从固定值改为按
  registration 标定，消除 §6.1 的 −18..−20 LUFS 落差。
- **响度归一化 + 收紧阈值**：在 mix bus 之后做 integrated 归一化，再把
  `target_lufs_min/max` 收窄到 ±1 LU，让 `lufs_band` 成为真正的门禁而不是记录。
- **恒定 bed 压缩动态**：bed 抬高相对门会吃掉 spread；若要保住动态，需要在
  envelope coupling 之外引入 per-layer 的相对门补偿（或对 bed 施加与 envelope
  反向的增益），否则 spread 类判据在 final mix 上永远偏悲观。
- **渲染尾部**：给 `render-audio` 增加可选 tail（例如 `decay_seconds` 的 2–3 倍），
  让 §5.1 的绝对尾部判据回到可用状态；代价是 stream cycle 需要显式裁掉尾部。

## 8. 复现命令

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
