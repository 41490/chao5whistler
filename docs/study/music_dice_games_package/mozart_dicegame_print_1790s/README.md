# mozart_dicegame_print_1790s

## Scope
This folder tracks the **printed 1790s dice-game tradition** usually catalogued at IMSLP under **Musikalische Würfelspiele, K.Anh.C.30.01 (K.3 Anh. 294d)**.

For the current implementation path, this package is explicitly **not** the 1787 autograph `K.516f` project.

## Stage status

- Canonical work id: `mozart_dicegame_print_1790s`
- Canonical witness: `rellstab_1790`
- Verification witness: `simrock_1793`
- Current plan stage: `stage 4: ingest freeze`

Stage 2 froze the canonical mother-score layer:

- `mother_score.source.k516f.krn` is the frozen Humdrum source used for this stage.
- `mother_score.musicxml` is now the primary ingest-oriented mother score.
- `mother_score.mei` is the aligned archive layer derived from that MusicXML.

Stage 3 froze the rule layer against that mother score:

- `rules.json` now records the complete `16 x 11` selector mapping plus reverse fragment lookup.
- `docs/study/music_source_basis_package/docs/mozart_16x11_table.json` is now explicitly marked as reconciled against the canonical mother score.
- `witness_diff.json` records the initial canonical-versus-verification policy state.

Stage 4 freezes the runtime-ready ingest layer:

- `ingest/fragments.json` now carries normalized fragment timelines with explicit rest closure.
- `ingest/measures.json` preserves the full source measure sequence, including repeated structural `measure 0` boundaries.
- `ingest/validation_report.json` records the stage-4 closure checks and confirms runtime independence from direct mother-score parsing.

The next unresolved step is `stage 5: deterministic offline realization`.

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
- `witness_diff.json` - initial stage-3 witness-diff record with file-level Simrock status.
- `ingest/fragments.json` - runtime-ready fragment timelines normalized from the mother score.
- `ingest/measures.json` - source-measure sequence and normalized per-measure part timelines.
- `ingest/validation_report.json` - stage-4 validation output for ingest closure and selector consistency.

## Selector model

This package models the common printed workflow:

1. Generate a piece of `16` output positions.
2. For each position, roll two six-sided dice and compute a sum in `2..12`.
3. Resolve one fragment from the current position column.
4. Concatenate the `16` selected fragments in position order.

`fragment id == measure number` for measures `1..176` in the stage-2 mother score.

The current `rules.json` and `docs/study/music_source_basis_package/docs/mozart_16x11_table.json` are reconciled against this mother score at stage 3. `Simrock 1793` remains file-level only until a later fragment-addressable witness-diff pass.

Stage 4 makes runtime consumption explicit:

- empty source parts are normalized into explicit rest events
- structural `measure 0` remains traceable in `ingest/measures.json`
- runtime fragment playback can now consume `ingest/*.json` without reparsing `mother_score.musicxml`

## Encoding policy

The frozen order is:

1. source provenance
2. mother-score encoding
3. rules reconciliation
4. ingest normalization
5. realization and audio

## Validation

Refresh the stage-4 ingest artifacts before validating if the mother score or rules changed:

```bash
python src/musikalisches/tools/freeze_ingest.py
```

Then run the stage validators from the repository root:

```bash
python src/musikalisches/tools/validate_source_freeze.py
python src/musikalisches/tools/validate_mother_score.py
python src/musikalisches/tools/validate_rules_freeze.py
python src/musikalisches/tools/validate_ingest_freeze.py
```
