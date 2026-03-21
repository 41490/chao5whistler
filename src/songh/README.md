# chao5whistler/src/songh

当前目录按 issue #2 的实现顺序推进 `songh`。

当前已进入：

- stage 1: `config loader / schema / validate`

当前阶段统一人工检验入口：

```bash
make -C src/songh stage1-manual
```

当前阶段自动回归入口：

```bash
make -C src/songh stage1-all
```

下一阶段预告：

- stage 2: `gharchive day-pack downloader + normalize pipeline`
