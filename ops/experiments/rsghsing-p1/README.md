# rsghsing P1 experiments (Issue #104)

Proves `rsghsing prepare` is a drop-in replacement for `src/ghsingo/cmd/prepare`:
same GSIN day-pack bytes from the same GH Archive hour packs, and an
idempotent downloader.

| file | what it does |
| ------ | -------------- |
| `daypack_stats.py` | Parses a GSIN day-pack per `src/ghsingo/internal/archive/daypack.go` and emits per-tick / per-type counts + totals as JSON. Events are sorted before hashing, so the JSON is order-independent *within* a tick — that is the parity unit. |
| `parity.sh <date> <hour>` | Feeds the SAME hour pack to Go `prepare` and `rsghsing prepare`, reduces both with `daypack_stats.py`, and diffs. Exit 0 only when the two blobs are identical. |
| `download_idem.sh [date] [hour]` | Runs `rsghsing prepare --hours <h>` twice on the same source dir. Run 1 must download; run 2 must be a no-op (`missing=0 downloaded=0`) with byte-identical raw + day-pack. A third run with `base_url` pointed at a closed port must still succeed, which proves no request is attempted. |
| `configs/ghsingo-p1.toml` | Go-side config (absolute paths, download off, `@@DATE@@`/`@@RAWDIR@@` substituted by `parity.sh`). |
| `configs/rsghsing-download.toml` | Rust-side config with download ON (`@@DATE@@`/`@@BASE_URL@@`/`@@RAWDIR@@` substituted by `download_idem.sh`). |

## Run

```bash
bash ops/experiments/rsghsing-p1/parity.sh 2026-03-28 11
bash ops/experiments/rsghsing-p1/download_idem.sh 2026-03-28 11
```

`parity.sh` seeds `var/rsghsing/archive/raw/<date>-<hour>.json.gz` from
`/opt/src/41490/chao5whistler/ops/assets` when it is not already cached, so it
is re-runnable offline. `download_idem.sh` deliberately clears that file first
so it can prove the cold-cache download path.

All output goes to `/opt/logs/41490/out/rsghsing/p1/`; nothing is written into
the repo.

## Notes

* `rsghsing prepare` resolves relative `[archive]` paths against the config
  file's directory (ghsingo resolves them against the CWD; the two agree when
  the config sits next to the CWD, which is ghsingo's documented invocation).
* Parity depends on reproducing Go's **unstable** `sort.Slice` permutation —
  see `src/rsghsing/src/gosort.rs`.
