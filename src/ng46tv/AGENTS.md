# ng46tv — Agent Notes

仓库级约定见根目录 [../../AGENTS.md](../../AGENTS.md)（jj 工作流、rtk 前缀、gh 路由等一律遵循）。

## 测试/运行输出目录约定（强制）

- **所有测试、下载、验证等运行输出一律写入绝对路径 `/opt/logs/41490/out/`。**
- 仓库内 `ops/out` 已是软链接 → `/opt/logs/41490/out/`，仅为兼容存量引用。
- **真实输出时不得再使用 `ops/out/` 或 `opt/out/` 相对路径**：下载目录、`--output-dir`、日志重定向等一律直接使用 `/opt/logs/41490/out/<子路径>`（如 `/opt/logs/41490/out/ng46tv`）。
