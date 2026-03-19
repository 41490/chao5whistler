# 经过检验的资料网页

## A. Mozart: `mozart_dicegame_print_1790s`

### 1) IMSLP 总页（版本与印刷信息）
- 页面：Musikalische Würfelspiele, K.Anh.C.30.01 (Mozart, Wolfgang Amadeus)
- URL: https://imslp.org/wiki/Musikalische_W%C3%BCrfelspiele%2C_K.Anh.C.30.01_%28Mozart%2C_Wolfgang_Amadeus%29
- 用途：
  - 确认这是 1790s 印刷传统条目，而非 K.516f 手稿条目
  - 确认可用的早期印刷扫描（Rellstab ca.1790；Simrock 1793）
  - 确认 “Instructions and 176 measures ...” 的作品形态

建议底本优先级：
1. Berlin: Rellstab, n.d. [ca.1790]（Walzer oder Schleifer）
2. Bonn: N. Simrock, 1793（多语种版）

### 2) Humdrum 在线页（规则说明）
- 页面：Musikalisches Würfelspiel
- URL: https://dice.humdrum.org/
- 用途：
  - 明确“roll two dice ... do this sixteen times”
  - 说明这是 16 次选择、每次按 2–12 的和从每列中取一个片段
  - 页面同时指向 IMSLP 扫描与 Humdrum digital score

### 3) CCARH / Music 253 Labs（完整 16×11 表）
- 页面：Music 253 Labs
- URL: https://www.ccarh.org/courses/253/lab/kerndice/
- 用途：
  - 给出 A1–A8 / B1–B8 的 16 列 × 11 个掷骰和结果的完整映射
  - 给出 Humdrum 文件与 MIDI 文件对应入口
  - 适合作为 rules.json / index.json 的校验层

## B. C. P. E. Bach: `cpebach_wq257_h869_einfall`

### 1) Bach Digital 作品页（首选）
- 页面：Einfall einen doppelten Contrapunct in der Octave von 6 Tacten zu machen, ohne die Regeln davon zu wissen
- URL: https://www.bach-digital.de/receive/BachDigitalWork_work_00010280
- 用途：
  - 确认作品身份：Wq 257 / H 869
  - 确认年代：ca. 1757
  - 确认刊载出处：Marpurg, Historische-kritische Beyträge zur Musik, Berlin 1757, S. 167–181
  - 页面公开暴露 PDF / XML / MEI / JSON-LD 导出入口

### 2) Bach Digital PDF 导出页（元数据页）
- URL: https://www.bach-digital.de/receive/BachDigitalWork_work_00010280?XSL.Style=pdf
- 用途：
  - 固定作品元数据快照
  - 便于把 catalog / date / comment 等信息固化进 source_manifest

### 3) Marpurg 期刊总条目（辅助定位）
- 页面：Historisch-Kritische Beyträge zur Aufnahme der Musik (Marpurg, Friedrich Wilhelm)
- URL: https://imslp.org/wiki/Historisch-Kritische_Beytr%C3%A4ge_zur_Aufnahme_der_Musik_%28Marpurg%2C_Friedrich_Wilhelm%29
- 用途：
  - 辅助确认该刊物的卷册体系与可获得扫描
  - 不能替代 Bach Digital 对该作品的作品级指认

## 使用建议

### Mozart
- `mother_score.musicxml`：
  最好先逐片段转写自 Rellstab ca.1790 的扫描；再用 Simrock 1793 复核版式与个别音值/装饰。
- `mother_score.mei`：
  由 MusicXML 转成初稿，再补入 `sourceDesc` / `revisionDesc` / 每片段稳定 xml:id。
- `rules.json`：
  用 CCARH 的 16×11 表。

### C. P. E. Bach
- `mother_score.musicxml`：
  以 Bach Digital 暴露的 XML / MEI 为首选机器源；必要时再回看 1757 刊载页。
- `mother_score.mei`：
  若 Bach Digital 的 MEI 可直接使用，应优先保留其 MEI 作为主记录。
- `rules.json`：
  不应仿造 Mozart 的 16×11 掷骰表，而应按“六小节材料 + 可逆对位 / 置换关系”建模。
