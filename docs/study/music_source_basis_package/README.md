# mother_score 填写依据与 Rust 转换示例

本包整理的是两个目录的“母谱填写依据”：

- `mozart_dicegame_print_1790s`
- `cpebach_wq257_h869_einfall`

内容包括：

- 经过检验的资料网页清单（`docs/source_pages.md`）
- Mozart 1790s 印刷型的 16×11 规则表（`docs/mozart_16x11_table.json`）
- Rust 数据类型与转换示例（`rust/examples/*.rs`）
- Cargo 示例（`rust/Cargo.toml`）

注意：

1. 对 `mother_score.mei` / `mother_score.musicxml`，**应以原始或近原始谱面来源为底本**，而不是用“和声骨架 + 受控随机变化”去重建。
2. 对 Mozart 的 1790s 印刷型，建议把 **印刷扫描页** 作为底本，把 **Humdrum/CCARH 的 16×11 映射表** 作为校验层。
3. 对 C. P. E. Bach 的 `Einfall`，建议把 **Bach Digital 的作品页及其导出入口** 作为第一依据；若要做外交式转写，应再对照 Marpurg 1757 的刊载页次（Bach Digital 明示为 pp.167–181）。
