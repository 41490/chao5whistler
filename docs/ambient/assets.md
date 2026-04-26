# ghsingo v2 ambient asset taxonomy

## Status

Active spec for issue [#32](../../../) (parent [#28](../../../)). The
v1 bell-era assets are documented separately under
[../baselines/bell-era/](../baselines/bell-era/).

## Layer roles

The v2 ambient engine has four roles. Each role has a fixed lifetime
contract — "always on" or "sparse" — which determines what kind of
asset is allowed in the slot.

| layer  | role        | lifetime    | source                  | example asset                           |
|--------|-------------|-------------|-------------------------|-----------------------------------------|
| L0     | drone       | always on   | synth (`DroneVoice`)    | n/a (built in)                          |
| L0.5   | tonal-bed   | always on   | sample (`TonalBedVoice`) | `ops/assets/sounds/ambient/tonal-bed.wav` |
| L1     | bed         | always on   | synth (`BedVoice`)      | n/a (built in)                          |
| L2     | accent      | sparse      | sample bank             | `ops/assets/sounds/bells/sampled/`      |
| (all)  | space       | always on   | shared reverb send      | n/a (built in)                          |

## What changed from bell-era

| concern           | bell-era                            | v2                                   |
|-------------------|-------------------------------------|--------------------------------------|
| `cosmos-leveloop` | "BGM" (the floor)                   | tonal-bed (one of three floor layers) |
| pre-processing    | direct play, peak loudnorm          | down-pitched 1 octave + lowpass + R128 |
| reverb            | accents only                        | shared send: drone/bed/tonal + accents |
| bells             | the engine                          | accent voice library                 |
| bgm `gain_db`     | dominant -4.8 dB                    | reused as tonal-bed gain (-4.8 dB)   |

The legacy `cosmos-leveloop-339.wav` is no longer treated as music
foreground. `make prepare-tonal-bed` derives a quieter, low-pitched,
band-limited variant (`ops/assets/sounds/ambient/tonal-bed.wav`) so it
sits *under* the accent layer rather than competing with it.

## Asset constraints (tonal-compatible profile)

Any asset placed in the v2 default profile MUST satisfy:

1. **Tonal lock**: the sample must not impose its own pitched key on
   top of the composer's mode drift. Pure noise / drones / pads pass;
   melodic loops fail.
2. **Loop-friendly**: end matches start within a 50 ms crossfade
   window — the `TonalBedVoice` crossfade is exactly that wide.
3. **Loudness ceiling**: integrated loudness ≤ -23 LUFS so layer
   stacking doesn't blow past the master's headroom budget.
4. **Bandlimit**: lowpass below ~3 kHz so the accent layer (above
   ~1 kHz) stays the brightest band on the spectrum.

`scripts/prepare-tonal-bed.sh` enforces (3) and (4) automatically. (1)
and (2) are the responsibility of the source material.

## Source -> output mapping

| source                             | role transition          | command                      |
|------------------------------------|--------------------------|------------------------------|
| `cosmos-leveloop-339.mp3`          | BGM -> tonal-bed         | `make prepare-tonal-bed`     |
| `ocean_v3events/*.wav`             | event voices -> normalized event voices (legacy bell-era; v2 may reuse as accents in #33) | `make normalize-voices` |
| GM 14 / 12 / 19 SoundFonts         | bell banks (legacy) | `make prepare-bells-all`     |

## Known limitations

- v2 does not yet have a stems family (short rhythmic samples). The
  accent layer is still served by the bell banks. Adding stems is
  trivial structurally — the same `BellBank` slot just needs a
  parallel pool — but the asset selection itself is deferred until
  #33's config schema lands so each profile can name its own family.
- Master is conservatively trimmed to keep true-peak under -1.5 dBTP.
  This produces a quieter integrated loudness (~-25 LUFS) than the
  bell-era baseline (-18 LUFS). Loudness re-tune is gated on #33
  exposing the master/layer dials in toml.

## Removal boundary

When #38 deletes the bell-era code paths it should NOT delete the
`ops/assets/sounds/bells/sampled/` directory — those samples are
re-used by v2 as the accent voice bank. The `mallet/` and `organ/`
banks are A/B-only and may be removed.
