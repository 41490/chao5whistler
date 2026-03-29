# ghsingo
> ghwhistler->songh->再次优化

## background
231101 ... 手工创建 ghwhistler 工程,
基于 Python + ffmpge, 通过 github-api 预先生成60个1分钟的 gh 事件白噪音视频循环播放完成长时间直播;

260320 ... CodeX 基于 gpt-5.4 快速重构, 使用 rust 技术栈,
使用 https://www.gharchive.org/ 下载的全天历史数据进行 gh 事件白噪音直接合成实时推流,
但是, 反复失败;

260329 .. Claude Code 基于 sonnet 4.5 重构, 使用 golang 技术栈;

## goal

- 支持长期直播, 可能长达几周连续
- 使用昨天的 github 真实历史事件作为随机源数据
- 使用真实的自然采样声音对应 gh 的事件, 先以海洋生物为范畴
- 所有参数使用唯一 .toml 来控制
- 所有行为通过 systemd --user 的服务管理指令来控制, 包含:
  - 定期下载关键 gh 历史事件记录
  - 电影帧马赛克背景图片抽取
  - 生成本地合成视频
  - 推送 youtube rtmps 流数据


## logging
...TBD

## refer.
...TBD

## tracing

- 260329 DAMA init.
