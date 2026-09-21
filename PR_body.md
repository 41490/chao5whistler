## PR body for #84

**Summary:** Add layer composition pipeline + ffmpeg 参数脚本，将 staff、spectra、dice 三层叠加并注入 L3 进度层。

**Changes:**
- `src/musikalisches/tools/compose_layers.py` — Python 脚本，使用 ffmpeg overlay 合成三层，注入底部进度文本 (`123/45949729863572161` 即 11^16)
- `src/musikalisches/tools/compose_layers.sh` — Shell 脚本，调用 ffmpeg 执行相同合成操作
- `render_staff_30s.py` (保留) — 30秒 staff 渲染脚本，已在工作树中保留，未作为 #84 主要交付但保持兼容

**验收：** 运行 `python3 compose_layers.py --staff test_staff.mp4 --spectra test_spectra.mp4 --dice test_dice.mp4 --output final_test.mp4` 成功生成最终 MP4。

**测试：** 若有相应测试素材，可自行验证输出视频的透明层叠加、15帧透明过门、L3 进度显示正确。