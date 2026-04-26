# ghsingo config schema v2

## Status

Active spec for issue [#33](../../../) (parent [#28](../../../)).
Bell-era schema (frozen by [#29](../../../)) lives in
[`docs/baselines/bell-era/`](../baselines/bell-era/) and is kept loadable
only so legacy profiles still produce baseline reports until
[#38](../../../) deletes them.

## Engine selection

Every profile MUST declare its engine in `[meta]`:

```toml
[meta]
profile = "ambient-v2"
engine  = "v2"     # required for the v2 mainline
```

Resolution rules (`config.Config.ResolvedEngine`):

- explicit `engine = "v1"` -> v1
- explicit `engine = "v2"` -> v2
- missing or unknown -> v1 (safe default; bell-era loaders keep working)

`engine = "v2"` is **mutually exclusive** with `legacy = true`. The Loader
rejects the combination at parse time.

## v2 schema reference

```toml
[meta]
profile = "<name>"
engine  = "v2"
# legacy = true is rejected for engine=v2

[archive]                  # unchanged from v1
[archive.download]         # unchanged from v1

[events]                   # unchanged from v1
[events.weights]           # unchanged from v1

[audio]                    # only sample_rate / channels / master_gain_db
sample_rate = 44100
channels    = 2

[composer]                 # NEW — see internal/composer/composer.go
ema_alpha             = 0.06
density_saturation    = 12.0
brightness_saturation = 80.0
phrase_ticks          = 16
accent_cooldown_ticks = 3
accent_base_prob      = 0.10
seed                  = 0  # 0 -> time.Now()

[mixer]                    # NEW — see internal/audio/mixer_v2.go
master_gain    = 0.55
drone_gain     = 1.0
bed_gain       = 1.0
tonal_bed_gain = 0.575
accent_gain    = 1.0
wet_continuous = 0.06
wet_accent     = 0.45
accent_max     = 4

[assets.tonal_bed]         # NEW — replaces [audio.bgm] (which was BGM)
wav_path = "../../ops/assets/sounds/ambient/tonal-bed.wav"
gain_db  = -4.8

[assets.accents]           # NEW — replaces [audio.bells]
bank_dir    = "../../ops/assets/sounds/bells/sampled"
synth_decay = 0.996

[video]                    # unchanged from v1
[video.palette]
[video.motion]
[video.text]
[video.background]
[video.event_colors]

[output]                   # unchanged from v1
[output.local]
[output.rtmps]

[observe]                  # unchanged from v1
```

## Removed in v2

These bell-era fields are NOT read by the v2 path. The Loader rejects
`[audio.cluster]` under `engine = "v2"`; the rest are silently ignored
when the engine is v2 (kept parseable so a partial migration still
loads).

| field                  | reason                                        |
|------------------------|-----------------------------------------------|
| `[audio.cluster]`      | trigger-centric model replaced by composer    |
| `[audio.bells]`        | renamed to `[assets.accents]`                 |
| `[audio.beat]`         | beat density is a v1 modulation; v2 has none  |
| `[audio.voices]`       | per-event voice samples; v2 stems happen via accents |
| `[audio.bgm]`          | BGM is no longer a role; cosmos -> tonal-bed  |

## Migration

Use the `migrate-config` helper to translate any bell-era profile to the
v2 shape:

```sh
cd src/ghsingo
go run ./cmd/migrate-config --in ghsingo.toml --out /tmp/v2.toml
diff -u ghsingo-v2.toml /tmp/v2.toml
```

The tool:

- preserves `[archive]` / `[events]` / `[video]` / `[output]` / `[observe]`
  exactly
- writes `[composer]` and `[mixer]` from vetted defaults (the bell-era
  values rarely transfer meaningfully — review them after migration)
- maps `[audio.bgm].wav_path` to `[assets.tonal_bed].wav_path` (default
  `ops/assets/sounds/ambient/tonal-bed.wav`) and carries the dB value
- maps `[audio.bells].bank_dir` to `[assets.accents].bank_dir`
- refuses to migrate a profile that already declares `engine = "v2"`

`make migrate-default-to-v2` runs this end-to-end against the frozen
default and shows a diff against the canonical `ghsingo-v2.toml`.

## Override semantics

`render-audio-v2`'s mixer-override helper applies any non-zero `[mixer]`
field on top of the in-code defaults. Omitting a field keeps the engine
default. This means a minimal v2 profile can be:

```toml
[meta]
profile = "minimal"
engine  = "v2"

# (everything else inherits defaults)
```

…but it MUST still provide `[archive]`, `[events]`, `[video]`,
`[output]`, `[observe]` — those are required by validation regardless of
engine.

## Removal boundary

[#38](../../../) removes the bell-era code paths. After that lands:

- `[audio.bells]` / `[audio.cluster]` / `[audio.bgm]` / `[audio.beat]`
  / `[audio.voices]` are removed from `internal/config`.
- `migrate-config` itself is deleted (its only caller was the bell-era
  -> v2 transition; nothing should be running v1 by then).
- `ghsingo.toml` / `ghsingo-mallet.toml` / `ghsingo-organ.toml` are
  deleted; `ghsingo-v2.toml` is renamed to `ghsingo.toml`.
