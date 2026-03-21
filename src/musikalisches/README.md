# chao5whistler/src/musikalisches
> 莫扎特印刷骰子游戏实现入口

## current frozen target

- `work_id`: `mozart_dicegame_print_1790s`
- `canonical_witness_id`: `rellstab_1790`
- `verification_witness_id`: `simrock_1793`
- current plan stage: `stage 5: milestone M1`
- first runtime milestone: `offline realization + offline audio render`

## boundary

当前入口针对的是 **1790s printed dice-game tradition**，不是 `K.516f autograph`。

因此这里的推进顺序是：

1. source provenance
2. mother-score engineering
3. rules reconciliation
4. ingest contract
5. Rust runtime implementation

当前已完成：

- canonical provenance 冻结
- canonical mother score 冻结
- rules freeze 与 `16x11` 规则表对账完成
- `witness_diff.json` 初版已建立，且保持 `rellstab_1790` 为唯一 canonical runtime 定义
- `ingest/fragments.json` / `ingest/measures.json` / `ingest/validation_report.json` 已冻结
- ingest 已把空 part 显式补成 rest timeline，runtime 不再需要直接解析 `mother_score.musicxml`
- Rust CLI crate 已建立：`cargo run -- render-audio ...`
- runtime 已可输出 realized fragment sequence / note-event sequence / event-transition sequence / synth-event sequence / stream-loop plan / analyzer clock+envelope / offline WAV / M1 validation report
- stage 5 已加入 golden roll cases 与小型 artifact summary，便于回归和 review
- note-event / transition 契约已显式带出 `voice_group` 元数据，可为后续合成器/分析器对接保留分组边界
- `render-audio` 已可在提供 `--soundfont` 时走 `rustysynth` 真实合成；未提供时按 `--soundfont` > `MUSIKALISCHES_SOUNDFONT` > repo/system default 的顺序发现，找不到才回退到内置 deterministic fallback
- stage 5 已补 `loop_count` 连续播放骨架、`synth_profile` 路由配置、以及统一 analyzer 时钟输出，便于进入视频/直播链路前先做人工检验
- stage 6 已补 analyzer -> video stub 预演入口，可把 stage 5 分析输出转成 Solarized Dark 的视觉 stub 契约与静态预览

当前仍未完成：

- stage 6 视觉层
- stage 7 FFmpeg / RTMP bridge
- stage 8 soak / operations

在 stage 5 之前，不应把这里描述成“已经开始实现 K.516f 无限直播工具”。

## implementation gate

只有满足以下条件，才允许正式进入 stage 5 runtime Rust 编码：

1. canonical witness 已冻结
2. `mother_score.musicxml` 不再是 placeholder
3. `rules.json` 与 `16x11` 表完成核对
4. ingest 输出契约已冻结

当前 1-4 已满足，且 stage 5 的最小 M1 pipeline 已可运行。

当前这个目录主要承载执行入口说明和本地校验工具。

统一的人肉检验入口已整理到：

```bash
make -C src/musikalisches help
```

## stage 4 refresh

如需重新生成并校验 stage 4 ingest 产物：

```bash
python src/musikalisches/tools/freeze_ingest.py
python src/musikalisches/tools/validate_ingest_freeze.py
```

## stage 5 M1

构建 release binary：

```bash
bash src/musikalisches/tools/build_release_bins.sh
```

生成一套本地 M1 样例产物：

```bash
cargo run -- render-audio \
  --work mozart_dicegame_print_1790s \
  --demo-rolls \
  --loop-count 4 \
  --output-dir ops/out/m1-demo
```

如有 SoundFont，可走真实合成路径：

```bash
cargo run -- render-audio \
  --work mozart_dicegame_print_1790s \
  --demo-rolls \
  --soundfont /path/to/piano.sf2 \
  --loop-count 4 \
  --output-dir ops/out/m1-sf2
```

如需覆盖默认路由 profile：

```bash
cargo run -- render-audio \
  --work mozart_dicegame_print_1790s \
  --demo-rolls \
  --synth-profile /path/to/profile.json \
  --output-dir ops/out/m1-custom-profile
```

验收这套样例产物：

```bash
python src/musikalisches/tools/validate_m1_artifacts.py ops/out/m1-demo
```

人工构建与分流输出检验说明见：

```text
docs/plans/260321-stage5-build-and-manual-test-guide.md
```

## stage 6 preflight

从 stage 5 analyzer 产物生成视觉 stub：

```bash
make -C src/musikalisches stage6-video-stub
make -C src/musikalisches stage6-video-check
```

默认输出：

```text
ops/out/video-stub
```

说明文档见：

```text
docs/plans/260321-stage6-video-stub-guide.md
```

运行 stage 5 golden regression：

```bash
cargo test
```

或通过 CLI 写出 golden verification report：

```bash
cargo run -- verify-golden \
  --work mozart_dicegame_print_1790s \
  --output-dir ops/out/golden-check
```
