# chao5whistler/src/musikalisches
> 莫扎特印刷骰子游戏实现入口

## current frozen target

- `work_id`: `mozart_dicegame_print_1790s`
- `canonical_witness_id`: `rellstab_1790`
- `verification_witness_id`: `simrock_1793`
- current plan stage: `stage 3: rules freeze`
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

当前仍未完成：

- normalized ingest 产物
- runtime

在 stage 5 之前，不应把这里描述成“已经开始实现 K.516f 无限直播工具”。

## implementation gate

只有满足以下条件，才允许正式进入 stage 5 runtime Rust 编码：

1. canonical witness 已冻结
2. `mother_score.musicxml` 不再是 placeholder
3. `rules.json` 与 `16x11` 表完成核对
4. ingest 输出契约已冻结

当前 1-3 已满足，下一门槛是 stage 4 ingest 输出契约冻结。

当前这个目录主要承载执行入口说明和本地校验工具。
