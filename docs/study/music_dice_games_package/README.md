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
The package is **ready as a research-and-ingest scaffold**, but the `mother_score.mei` and `mother_score.musicxml` files are currently **template placeholders** rather than full diplomatic encodings.

That limitation is intentional: in the current environment, I could verify bibliographic/source facts and formation rules, but I could not reliably fetch the full authoritative machine-readable source files for packaging without risking inaccurate transcription.
