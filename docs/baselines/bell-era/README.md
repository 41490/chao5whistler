# bell-era baseline (REMOVED)

## Status

`REMOVED — 2026-04-26 (issue #38).`

This directory used to host the freeze documentation for the three
`bell-era` profiles (`default` / `mallet` / `organ`). #38 deleted the
runtime code and configuration that backed them. This file remains
only as a tombstone so historical commit messages and PRs that link
here keep landing somewhere meaningful.

## What was removed

| asset                                       | gone in #38                          |
|---------------------------------------------|--------------------------------------|
| `src/ghsingo/ghsingo.toml` (bell-era)       | yes — replaced by the v2 profile     |
| `src/ghsingo/ghsingo-mallet.toml`           | yes                                  |
| `src/ghsingo/ghsingo-organ.toml`            | yes                                  |
| `src/ghsingo/cmd/live/`                     | yes                                  |
| `src/ghsingo/cmd/render-audio/`             | yes                                  |
| `src/ghsingo/cmd/migrate-config/`           | yes (one-shot tool, no longer needed) |
| `src/ghsingo/internal/audio/cluster.go`     | yes                                  |
| `src/ghsingo/internal/audio/beat.go`        | yes                                  |
| `src/ghsingo/internal/audio/mixer.go`       | yes (helpers moved to `wav.go` / `pitch.go`) |
| `src/ghsingo/scripts/render-baseline.sh`    | yes                                  |
| `src/ghsingo/ops/systemd/ghsingo-live.service` | yes — the v2 unit lives at `ghsingo-live-v2.service` |
| `internal/config` legacy structs            | `[audio.bgm]` / `[audio.bells]` / `[audio.cluster]` / `[audio.beat]` / `[audio.voices]` are gone |
| `make prepare-bells-mallet/organ/all`       | yes                                  |
| `make run-live` / `run-live-5m` / `render-audio-5m` | yes                          |
| `make baseline*`                            | yes (the bell-era reports were the only consumers) |

## What stayed

Asset *files* under `ops/assets/sounds/bells/` (the GM 14 Tubular Bells
WAV bank rendered by `make prepare-bells`) remain — the v2 ambient
engine reuses them as the accent voice library via `[assets.accents]`.
The GM 12 Marimba and GM 19 Church Organ banks are now orphaned but
the file tree is gitignored, so they require no cleanup.

## Where to read about the v2 mainline

- [docs/ambient/config.md](../../ambient/config.md) — toml schema reference.
- [docs/ambient/assets.md](../../ambient/assets.md) — asset taxonomy.
- [docs/ambient/soak-runbook.md](../../ambient/soak-runbook.md) — 24h / 7d procedure.
