# mozart_dicegame_print_1790s

## Scope
This folder tracks the **printed 1790s dice-game tradition** usually catalogued at IMSLP under **Musikalische Würfelspiele, K.Anh.C.30.01 (K.3 Anh. 294d)**.

For the current implementation path, this package is explicitly **not** the 1787 autograph `K.516f` project.

## Stage status

- Canonical work id: `mozart_dicegame_print_1790s`
- Canonical witness: `rellstab_1790`
- Verification witness: `simrock_1793`
- Current plan stage: `stage 1: source freeze`

Stage 1 freezes provenance and locating contracts. It does **not** claim that the mother-score files are already diplomatic transcriptions.

## Source basis

- IMSLP work page: freeze the printed-tradition object and witness file ids.
- Rellstab, Berlin, ca. 1790: frozen as the canonical witness.
- N. Simrock, Bonn, 1793: frozen as the verification witness.
- Humdrum dice-game page: freeze the 16-step selector procedure.
- CCARH Music 253 Labs table: cross-check the complete `16x11` fragment lookup.

## Directory contents

- `README.md` - human-readable scope and stage notes.
- `index.json` - work metadata.
- `rules.json` - machine-readable gameplay model.
- `source_manifest.json` - witness-level source freeze record.
- `page_trace.json` - page-level provenance for the canonical witness plus file-level trace for the verification witness.
- `fragment_identity_map.json` - canonical fragment-to-page/row/slot locating draft for fragments `1..176`.
- `mother_score.musicxml` - stage-2 placeholder for the future diplomatic mother score.
- `mother_score.mei` - stage-2 placeholder for the future diplomatic mother score.

## Selector model

This package models the common printed workflow:

1. Generate a piece of `16` output positions.
2. For each position, roll two six-sided dice and compute a sum in `2..12`.
3. Resolve one fragment from the current position column.
4. Concatenate the `16` selected fragments in position order.

The `16x11` selector table remains the rule-layer truth for runtime realization. Stage 1 only ensures that every fragment id in that table can now be traced back to a canonical witness page location.

## Encoding policy

The mother-score files remain placeholders until stage 2.

The frozen order is:

1. source provenance
2. mother-score encoding
3. rules reconciliation
4. ingest normalization
5. realization and audio

## Validation

Run the stage-1 validator from the repository root:

```bash
python src/musikalisches/tools/validate_source_freeze.py
```
