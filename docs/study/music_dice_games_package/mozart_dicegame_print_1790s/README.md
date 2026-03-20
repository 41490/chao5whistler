# mozart_dicegame_print_1790s

## Scope
This folder tracks the **printed 1790s dice-game tradition** usually catalogued at IMSLP under **Musikalische Würfelspiele, K.Anh.C.30.01 (K.3 Anh. 294d)**.

For the current implementation path, this package is explicitly **not** the 1787 autograph `K.516f` project.

## Stage status

- Canonical work id: `mozart_dicegame_print_1790s`
- Canonical witness: `rellstab_1790`
- Verification witness: `simrock_1793`
- Current plan stage: `stage 2: mother-score freeze`

Stage 2 freezes the canonical mother-score layer:

- `mother_score.source.k516f.krn` is the frozen Humdrum source used for this stage.
- `mother_score.musicxml` is now the primary ingest-oriented mother score.
- `mother_score.mei` is the aligned archive layer derived from that MusicXML.

The next unresolved step is `stage 3: rules reconciliation`.

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
- `mother_score.source.k516f.krn` - frozen canonical digital source aligned to the Rellstab witness.
- `mother_score.musicxml` - stage-2 frozen mother score for ingest.
- `mother_score.mei` - stage-2 aligned archive representation.

## Selector model

This package models the common printed workflow:

1. Generate a piece of `16` output positions.
2. For each position, roll two six-sided dice and compute a sum in `2..12`.
3. Resolve one fragment from the current position column.
4. Concatenate the `16` selected fragments in position order.

`fragment id == measure number` for measures `1..176` in the stage-2 mother score.

Important: the current `rules.json` and `docs/study/music_source_basis_package/docs/mozart_16x11_table.json` are not yet reconciled against this mother score. That reconciliation belongs to stage 3.

## Encoding policy

The frozen order is:

1. source provenance
2. mother-score encoding
3. rules reconciliation
4. ingest normalization
5. realization and audio

## Validation

Run the stage validators from the repository root:

```bash
python src/musikalisches/tools/validate_source_freeze.py
python src/musikalisches/tools/validate_mother_score.py
```
