# musikalisches runtime

Stage 5 starts here.

Build from the repository root:

```bash
cargo build --release
install -m 755 target/release/musikalisches ops/bin/musikalisches
```

Generate a deterministic M1 sample artifact set:

```bash
cargo run -- render-audio \
  --work mozart_dicegame_print_1790s \
  --demo-rolls \
  --output-dir ops/out/m1-demo
```

Or provide an explicit roll sequence:

```bash
cargo run -- render-audio \
  --work mozart_dicegame_print_1790s \
  --rolls 2,3,4,5,6,7,8,9,10,11,12,7,6,5,4,3 \
  --output-dir ops/out/m1-explicit
```

Artifacts written per run:

- `render_request.json`
- `realized_fragment_sequence.json`
- `note_event_sequence.json`
- `m1_validation_report.json`
- `offline_audio.wav`
