# ghsingo v2 soak runbook

## Status

Active spec for issue [#37](../../../) (parent [#28](../../../)). Pairs
with the lifecycle decoupling work in [#36](../../../) and the scsynth
backend in [#35](../../../).

## What we're proving

| target  | matters because                                                |
|---------|----------------------------------------------------------------|
| 24h     | a normal "all-day stream" must hold up                         |
| 7d      | the engine survives heap pressure / clock skew / asset reload  |
| fault   | a forced backend crash must not break the RTMP/FLV pipe        |

## Standing pass criteria

`cmd/soak-analyze` enforces these by default. Every flag has a knob,
documented in `cmd/soak-analyze/main.go --help`.

| metric                     | criterion                                  |
|----------------------------|--------------------------------------------|
| `uptime`                   | last sample ≥ `--min-uptime`               |
| `backend_restarts/h`       | ≤ `--max-restarts-per-hour` (default 1.0) |
| `heap_alloc_bytes` growth  | ≤ `--max-heap-growth-mb` (default 256)    |
| stuck-at-0 `density` window| ≤ `--max-zero-density-secs` (default 600) |
| `section_transitions`      | ≥ 1                                        |

The five together prove: the process kept running, the backend stayed
healthy, memory didn't leak meaningfully, events kept arriving, and the
composer's phrase scheduler kept moving.

## 24h soak procedure

1. **Pre-flight**:
   ```sh
   cd src/ghsingo
   make check-jack-routing             # required deps present?
   make compile-synthdefs               # if running scsynth path
   make build                           # all binaries
   ```

2. **Snapshot baseline** (so we can compare):
   ```sh
   make baseline-30s                    # bell-era reference (frozen, #29)
   make render-audio-v2-profile-30s     # v2 reference (current head)
   ```

3. **Start the long run** (audio-only RTMP/FLV; add an RTMP URL via
   `[output.rtmps].url` in `ghsingo-v2.toml.local` if you want a public
   stream):
   ```sh
   ../../ops/bin/live-v2 \
     --config ghsingo-v2.toml \
     --duration 24h \
     --metrics ../../var/ghsingo/soak/metrics-24h.ndjson \
     --metrics-interval 30s \
     --snapshot ../../var/ghsingo/soak/snapshot-24h.json \
     -o ../../var/ghsingo/soak/24h.flv \
     2>&1 | tee ../../var/ghsingo/soak/live-v2-24h.log
   ```

4. **Inject a fault midway** (optional but recommended — see "Fault
   injection" below).

5. **Tally**:
   ```sh
   ../../ops/bin/soak-analyze \
     --in ../../var/ghsingo/soak/metrics-24h.ndjson \
     --min-uptime 23h
   ```
   Exits 0 = pass.

6. **Archive**:
   ```sh
   tar czf ../../var/ghsingo/soak/24h-$(date +%F).tar.gz \
     ../../var/ghsingo/soak/metrics-24h.ndjson \
     ../../var/ghsingo/soak/snapshot-24h.json \
     ../../var/ghsingo/soak/live-v2-24h.log
   ```

## 7d soak procedure

Identical to 24h with three differences:

- `--duration 168h --min-uptime 167h`
- `--max-heap-growth-mb 1024` (allow more headroom over a week)
- run under `systemd --user` so machine reboots don't kill it:
  ```sh
  make install-units-v2
  systemctl --user enable --now ghsingo-live-v2
  ```

The systemd unit's `Restart=on-failure` recovers from crashes; transient
backend failures are absorbed by `BackendBox` and don't bounce the
service. The metrics file accumulates across restarts because the
recorder appends.

## Fault injection

While a soak is running, in another shell:

```sh
src/ghsingo/scripts/inject-backend-fault.sh
```

This:

1. Finds the running `live-v2` process.
2. Kills its `scsynth` child with SIGTERM (if any).
3. Sends SIGUSR1 to `live-v2`, triggering `BackendBox.Restart()`.

Verify after a minute:

- `backend_restarts` in the metrics file bumped by exactly 1.
- The output FLV has no gap (silence fills the restart window).
- `density` was never stuck at 0 longer than ~5 seconds.

`scripts/inject-backend-fault.sh` is also useful in CI: kick off a
short `--duration 90s` run, inject after 30s, run `soak-analyze` with
`--max-zero-density-secs 10`. PASS proves the recovery path.

## What stays uncovered (#37 follow-ups)

- **Audio capture** is still silent in `live-v2` when running scsynth
  (#35/#36 deferred the JACK loopback ingestion). The metrics + soak
  harness in this issue work for the gov2 path end-to-end; for
  scsynth, only the *control* metrics are valid until the JACK
  ingestion lands. Track in #36 follow-up.
- **State snapshot/restore** writes a composer snapshot every metrics
  tick but `restoreSnapshot` in `cmd/live-v2` is intentionally a stub:
  the bytes are read but not yet pushed back into the inner gov2
  backend (the cleanest path requires a `BackendBox.RestoreInner` API,
  not yet present). Track as #37-followup before the first 7d run.

## Reference: pre-flight matrix

| dep            | who needs it                | how to install                       |
|----------------|------------------------------|--------------------------------------|
| `ffmpeg`       | every render path            | `apt install ffmpeg`                 |
| `fluidsynth`   | bell-era prepare-bells       | `apt install fluidsynth` (legacy)    |
| `scsynth`      | scsynth backend (#35)        | `apt install supercollider-server`   |
| `sclang`       | `make compile-synthdefs`     | `apt install supercollider-language` |
| `jackd2`/pw-jack | scsynth live audio (#36)   | `apt install jackd2` or use pipewire |
