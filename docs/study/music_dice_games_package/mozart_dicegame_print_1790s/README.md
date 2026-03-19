# mozart_dicegame_print_1790s

## Scope
This folder organizes the **printed 1790s dice-game tradition** usually catalogued at IMSLP under **Musikalische Würfelspiele, K.Anh.C.30.01 (K.3 Anh. 294d)**, distinct from the 1787 autograph K.516f tradition.

## Source basis
- IMSLP general work page: printed editions ca. 1790; several editions published between 1790 and 1806, not all attributed to Mozart.
- Early printed witnesses listed there include:
  - **Rellstab, Berlin, ca. 1790**: *Walzer oder Schleifer*
  - **N. Simrock, Bonn, 1793**: *Englische Contretänze* and *Walzer oder Schleifer*
- Humdrum dice-game implementation page: describes the familiar 16-step selection procedure using the sum of two dice.

## Gameplay / manual verification rules
This package models the **common printed minuet/dance-style workflow** used in modern dice-game reconstructions:

1. Generate a piece of **16 output positions**.
2. For each output position, roll **two six-sided dice** and compute the **sum 2..12**.
3. Use that sum to select **one candidate measure from the column corresponding to the current position**.
4. Repeat this **16 times**, once for each position.
5. Concatenate the selected measures in order.

### Allowed selector values
- Standard selector domain: **2..12**
- In the common 16-column table tradition, most columns allow 11 choices (for sums 2 through 12).
- Output position **8** is historically exceptional in the better-known table tradition and often has a single fixed option in modern reconstructions.
- Final position handling may vary slightly by edition; therefore this package stores the gameplay model separately from any future full diplomatic encoding.

## Directory contents
- `README.md` — human-readable rules and provenance notes.
- `index.json` — work metadata.
- `rules.json` — machine-readable gameplay model.
- `source_manifest.json` — bibliographic/source tracking.
- `mother_score.musicxml` — **template placeholder** for a future fully encoded mother score.
- `mother_score.mei` — **template placeholder** for a future fully encoded mother score.

## Encoding policy
Because the exact printed witness to privilege (Rellstab ca. 1790 vs. Simrock 1793 vs. another edition) materially affects the definitive measure table, this package currently treats the mother-score files as **schema-complete placeholders** rather than claiming a fully diplomatic transcription.

The intended future workflow is:
- choose one printed witness as canonical;
- encode its measure table in MusicXML / MEI;
- verify every table cell against the printed source;
- keep `rules.json` synchronized with the encoded source.

## CLI-oriented model
Recommended CLI behavior:
- `--work mozart_dicegame_print_1790s`
- `--rolls 7,9,3,...` or `--selectors 7,9,3,...`
- exactly **16** selector values required
- each selector must be in **[2,12]**
- fixed/edition-specific constraints should be validated against `rules.json`
