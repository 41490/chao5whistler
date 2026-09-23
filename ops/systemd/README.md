# songh systemd --user

本目录提供 `songh` 的 `systemd --user` 运行封装。

目标：

- 不再要求 operator 手工 `export SONGH_RTMP_URL`
- 通过一个 TOML 文件固定 `prepare / 300s / 8h / forever` 入口
- 把 stage7 live runtime 的准备、短时验证和长期运行都收进 `systemctl --user`

## 文件

- `songh.toml`
  默认配置模板；应复制到本机私有路径后填入真实 `stream_url`
- `install_user_units.py`
  读取 TOML，渲染并安装 `systemd --user` unit
- `run_songh_user_service.py`
  实际 unit 入口；支持 `prepare` 和 `run` 两类 mode

## 安装

先准备一份本机配置，例如：

```bash
cp ops/systemd/songh.toml ~/.config/songh/songh-systemd.toml
chmod 600 ~/.config/songh/songh-systemd.toml
```

至少替换：

- `service.stream_url`

然后安装：

```bash
make -C src/songh systemd-user-install \
  SYSTEMD_CONFIG="$HOME/.config/songh/songh-systemd.toml"
```

默认会写入：

```text
~/.config/systemd/user
```

当前会生成 4 个 unit：

- `songh-live-prepare.service`
- `songh-live-300s.service`
- `songh-live-8h.service`
- `songh-live-forever.service`

安装过程只写 unit 并执行 `systemctl --user daemon-reload`，不会自动启动。

## 使用

准备 stage7 工件并做本地 smoke：

```bash
systemctl --user start songh-live-prepare.service
```

300 秒真实平台短时验证：

```bash
systemctl --user start songh-live-300s.service
```

8 小时 soak：

```bash
systemctl --user start songh-live-8h.service
```

持续运行：

```bash
systemctl --user start songh-live-forever.service
```

## 观察日志

```bash
journalctl --user -u songh-live-prepare.service -f
```

```bash
journalctl --user -u songh-live-300s.service -f
```

```bash
journalctl --user -u songh-live-8h.service -f
```

```bash
journalctl --user -u songh-live-forever.service -f
```

运行期间还应结合 stage7 工件目录下的 JSON 报告排障：

- `ops/out/songh-stage7-stream-bridge/stage7_bridge_validation_report.json`
- `ops/out/songh-stage7-stream-bridge/logs/stage7_bridge_preflight_report.json`
- `ops/out/songh-stage7-stream-bridge/logs/stage7_bridge_runtime_report.json`
- `ops/out/songh-stage7-stream-bridge/logs/stage7_bridge_exit_report.json`
