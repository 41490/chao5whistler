# chao5whistler/src/musikalisches
> 莫扎特印刷骰子游戏实现入口

## current frozen target

- `work_id`: `mozart_dicegame_print_1790s`
- `canonical_witness_id`: `rellstab_1790`
- `verification_witness_id`: `simrock_1793`
- current plan stage: `stage 1: source freeze`
- first runtime milestone: `offline realization + offline audio render`

## boundary

当前入口针对的是 **1790s printed dice-game tradition**，不是 `K.516f autograph`。

因此这里的推进顺序是：

1. source provenance
2. mother-score engineering
3. rules reconciliation
4. ingest contract
5. Rust runtime implementation

在 stage 5 之前，不应把这里描述成“已经开始实现 K.516f 无限直播工具”。

## implementation gate

只有满足以下条件，才允许正式进入 Rust 编码：

1. canonical witness 已冻结
2. `mother_score.musicxml` 不再是 placeholder
3. `rules.json` 与 `16x11` 表完成核对
4. ingest 输出契约已冻结

当前这个目录主要承载执行入口说明和本地校验工具。
