# bell-era baseline (frozen)

## Status

`FROZEN — 2026-04-26 (issue #29).`

This directory documents the *frozen* `bell-era` audio profiles for `ghsingo`.
They are kept solely as A/B reference for the ambient-engine refactor planned
in [#28](../../../). They will be deleted by [#38](../../../) once the v2
state-vector composer mainline is stable.

## What is frozen

| profile  | config                                | bell program       | bank dir                                    |
|----------|----------------------------------------|--------------------|---------------------------------------------|
| default  | `src/ghsingo/ghsingo.toml`             | GM 14 Tubular Bells| `ops/assets/sounds/bells/sampled`           |
| mallet   | `src/ghsingo/ghsingo-mallet.toml`      | GM 12 Marimba      | `ops/assets/sounds/bells/mallet`            |
| organ    | `src/ghsingo/ghsingo-organ.toml`       | GM 19 Church Organ | `ops/assets/sounds/bells/organ`             |

Each `[meta]` block now carries `legacy = true`. New work MUST NOT extend
these files; new musical work happens in the v2 composer (#30+).

## How to (re)produce the baseline report

```sh
cd src/ghsingo
make baseline-30s    # or: make baseline-5m
```

Outputs land in `ops/out/baseline/`:

- `REPORT.md` — A/B table: LUFS / LRA / true peak / strikes·s⁻¹ / release·s⁻¹
- `<profile>.m4a` — rendered audio, fed by the latest daypack under `var/ghsingo/daypack/`
- `<profile>.report.json` — combined loudness + sidecar metrics
- `<profile>.m4a.metrics.json` — raw render-audio sidecar (trigger counts)

`make baseline-30s` is the cheap variant; `make baseline-5m` matches the
existing `render-audio-5m` cadence.

## Metric definitions

| metric                          | source                                      |
|---------------------------------|---------------------------------------------|
| integrated LUFS                 | `ffmpeg loudnorm` (input_i)                 |
| LRA                             | `ffmpeg loudnorm` (input_lra)               |
| true peak (dBTP)                | `ffmpeg loudnorm` (input_tp)                |
| effective strike rate per sec   | `(lead_strikes + background_strikes) / duration_secs` |
| release accent rate per sec     | `release_accents / duration_secs`           |
| ticks                           | total per-second cluster ticks processed    |

`lead_strikes` are triggers at full `lead_velocity`; `background_strikes` are
the conductor-mode quiet-bed triggers. `release_accents` are triggers with
`WithOcean = true` (always-fire `ReleaseEvent`).

## Removal boundary (#38)

Once the v2 composer + scsynth backend land and 24h soak passes, [#38] will:

1. Delete `ghsingo-mallet.toml`, `ghsingo-organ.toml`.
2. Delete `ghsingo.toml`'s `[audio.bells]`, `[audio.cluster]`, and bell-bank
   plumbing in `cmd/render-audio` / `cmd/live`.
3. Delete `internal/audio/cluster.go`, `internal/audio/bellbank.go`,
   `scripts/render-bells.sh`, and the `prepare-bells*` Makefile targets.
4. Move this README to a top-level `docs/baselines/CHANGELOG.md` entry
   describing what was removed and why.

Until then, treat this baseline as a comparison-only artifact: do **not**
patch numbers, do **not** retune velocities, do **not** swap soundfonts.
