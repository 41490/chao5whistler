# Soundscape Seed Assets

本目录承载 issue #9 P2 的最小可用多层声景资产包。

当前冻结约束：

- 每个直播可用素材都必须有对应 manifest
- 许可证白名单先只允许 `CC0` / `public_domain` / `pixabay_no_attribution`
- P2 只冻结最小 seed pack：`ambient` 1 个、`drone` 1 个
- P3 之前，stage5 还不会直接消费“裸目录随机 wav”，必须通过 manifest/index 接入
- 从 P3 开始，stage5 默认通过 `stage5_default_soundscape_profile.json` 消费这里的 manifest 化资产池，并把选中的 `ambient + drone` 下沉到 `offline_audio.wav`

目录约定：

- `ambient/`: 环境底床 loop
- `drone/`: pedal / drone loop
- `impulse/`: 预留给后续卷积响应，不在 P2 使用
- `manifests/`: per-asset manifest、asset-pack index、validator report

常用命令：

```bash
make -C src/musikalisches soundscape-assets-generate
make -C src/musikalisches soundscape-assets-check
```

当前仓库内的 seed assets 为 repo-generated deterministic loops，目的是先冻结资产 contract、license manifest 和 validator，而不是在 P2 就把最终艺术素材选定。
