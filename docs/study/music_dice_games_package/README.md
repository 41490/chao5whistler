# music_dice_games_package

This zip contains two normalized research directories:

- `mozart_dicegame_print_1790s`
- `cpebach_wq257_h869_einfall`

## Design choice
Per your requested structure:
- **MEI / MusicXML** are included as the intended mother-score layer
- **JSON** is used for metadata, indexing, and rule validation
- each directory has a **README.md** describing the gameplay / formation logic for manual cross-checking against `rules.json`

## Important status note
The package now has split maturity:

- `mozart_dicegame_print_1790s` has completed source freeze, mother-score freeze, stage-3 rules reconciliation, and stage-4 ingest freeze against the canonical `rellstab_1790` witness.
- `cpebach_wq257_h869_einfall` remains a research-and-ingest scaffold awaiting fuller source ingest work.
