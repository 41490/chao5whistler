Drop a default SoundFont here as:

- `ops/assets/soundfonts/default.sf2`

Runtime resolution order is:

1. `--soundfont /path/to/file.sf2`
2. `MUSIKALISCHES_SOUNDFONT`
3. `ops/assets/soundfonts/default.sf2`
4. Common system paths, preferring `/usr/share/sounds/sf2/FluidR3_GM.sf2`

If no `.sf2` is found, `musikalisches render-audio` falls back to the built-in deterministic additive renderer.
