# cpebach_wq257_h869_einfall

## Scope
This folder organizes **Carl Philipp Emanuel Bach, Wq 257 / H 869**, titled:

> *Einfall, einen doppelten Contrapunct in der Octave von 6 Tacten zu machen, ohne die Regeln davon zu wissen*

## Source basis
- Bach Digital identifies the work as **Wq 257 / H 869**, keyboard, **ca. 1757**.
- Bach Digital notes that it was published in **Marpurg, Historisch-kritische Beytraege zur Musik, Berlin 1757, pp. 167-181**.
- Bach Digital offers PDF / XML / MEI / JSON-LD export links.

## Gameplay / manual verification rules
This is **not** a 16-column two-dice minuet table. It is better described as a **combinatorial / invertible-counterpoint construction**.

For this package, the manually checkable formation logic is recorded as follows:

1. The system is centered on **6 bars** of material.
2. The musical idea demonstrates a **double counterpoint at the octave**.
3. Human verification must confirm that the encoded material preserves the possibility of the octave exchange / invertible relation described by the title.
4. Because the work is not driven by a single universally standardized modern CLI convention, the package exposes the formation logic as **operation-based** rather than dice-based.

### Supported operation vocabulary
- `orig` — original statement
- `inv8` — octave invertible-counterpoint form
- `permute` — bar/voice permutation where justified by the source encoding

## Directory contents
- `README.md` — human-readable rules and provenance notes.
- `index.json` — work metadata.
- `rules.json` — machine-readable operation model.
- `source_manifest.json` — bibliographic/source tracking.
- `mother_score.musicxml` — **template placeholder** for a future fully encoded mother score.
- `mother_score.mei` — **template placeholder** for a future fully encoded mother score.

## Encoding policy
The title itself defines the critical verification target: a **six-bar design** capable of functioning as **double counterpoint at the octave**.

This package therefore prioritizes:
- stable work identity;
- explicit formation rules in README + JSON;
- placeholders for future diplomatic MEI / MusicXML ingestion from a verified source export.

## CLI-oriented model
Recommended CLI behavior:
- `--work cpebach_wq257_h869_einfall`
- `--mode orig|inv8|permute`
- optional explicit operation sequence such as `--ops orig,inv8,orig,inv8,orig,inv8`
- validation must ensure the encoded source still maps to a **6-bar** unit
