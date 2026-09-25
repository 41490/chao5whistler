# rsghsing P3 — 15-min TS segment rendering (Issue #106)

Produces `render segment --index N` → a 900 s (15-min) MPEG-TS segment:
h264 1280×720 30 fps CBR ~2500 kbps + AAC 128 kbps, with absolute PTS and a
per-segment discontinuity (P0-D3), plus a per-event manifest cross-checkable
against the daypack slice.

## Scripts

* `bench_1h.sh` — renders 4 consecutive segments (1 h, indices 44–47), times the
  wall clock, verifies ffprobe params + manifest + a 2- and 4-segment byte-concat
  smoke (P0-D3), and emits 3 screenshots + a contact sheet to
  `/opt/logs/41490/out/rsghsing/p3/`. Exit 0 only if every check passes. The 4
  segments render as parallel jobs (the per-segment loop is single-threaded, so
  jobs scale across cores without touching the 2×-realtime throughput).
* `manifest_check.py <seg.ts>` — parses the daypack, validates the manifest event
  multiset (type + absolute tick) and each event's `offset_ms` against the segment
  window. Run standalone per segment.

## P0-D3 — the locked ffmpeg recipe (two-stage)

The video path streams raw RGBA (`rawvideo`) into libx264; audio is pre-rendered
by the P2 engine to a `f32le` temp and muxed in the same pass.

**Stage 1 — clean encode (PTS from 0):**

```
ffmpeg -f rawvideo -pix_fmt rgba -s 1280x720 -r 30 -i pipe:0 \
       -f f32le -ar 44100 -ac 2 -i <audio.f32> \
       -map 0:v -map 1:a \
       -af "aresample=async=1:first_pts=0,atrim=end_sample=39689216" \
       -c:v libx264 -preset veryfast \
         -b:v 2500k -maxrate 2500k -bufsize 2500k -g 60 \
         -pix_fmt yuv420p -bf 0 -x264-params nal-hrd=cbr:force-cfr=1 \
       -c:a aac -b:a 128k \
       -avoid_negative_ts make_zero -muxdelay 0 -muxpreload 0 \
       -f mpegts -mpegts_flags +initial_discontinuity+resend_headers clean.ts
```

**Stage 2 — shift onto the absolute timeline (`-c copy`):**

```
ffmpeg -y -i clean.ts -c copy \
       -mpegts_flags +initial_discontinuity+resend_headers \
       -output_ts_offset <index*900> seg-NN.ts
```

### Why these flags (each earned by experiment)

* **`-bf 0`** — no B-frames ⇒ video DTS is monotonic; a byte-concat of adjacent
  segments never trips the muxer's DTS check.
* **`-x264-params nal-hrd=cbr:force-cfr=1`** — a solid background compresses to
  ~85 kbps and blows the 2400 kbps floor; HRD=CBR forces ~2500 kbps (measured
  2501–2502 kbps).
* **`atrim=end_sample=39689216`** — AAC pads the last frame, so audio would run
  ~0.005 s past 900 s and overlap the next segment's start (non-monotonic DTS on
  concat). Trimming to `floor(900·44100/1024)·1024` = 38759 whole AAC frames ends
  audio at 899.97 s, strictly inside the segment.
* **`aresample=async=1:first_pts=0`** — cleans the AAC priming gap so the first
  audio PTS is 0 in the clean stage.
* **Two-stage, not `-output_ts_offset` in one pass** — `-avoid_negative_ts
  make_zero` resets PTS to 0 and cancels `-output_ts_offset`. Encoding clean then
  re-muxing with `-c copy -output_ts_offset` preserves the monotonic DTS *and*
  lands the segment at its absolute `index*900` (a uniform +1.42 s presentation
  delay from the AAC/encoder start; spacing is exactly 900 s).
* **`-mpegts_flags +initial_discontinuity+resend_headers`** — stamps the
  per-segment discontinuity the P0-D3 smoke relies on.
* **mpegts has no stream-level avg bitrate** — measured via
  `ffprobe -show_entries packet=size` summed per stream.

## P3 result table (2026-03-28, indices 44–47)

| seg  | dur_s     | r_frame | WxH      | v_kbps | a_kbps | fmt    | manifest |
|------|-----------|---------|----------|--------|--------|--------|----------|
| 44   | 900.023   | 30/1    | 1280×720 | 2501   | 130    | mpegts | PASS 2722 |
| 45   | 900.023   | 30/1    | 1280×720 | 2501   | 130    | mpegts | PASS 2790 |
| 46   | 900.023   | 30/1    | 1280×720 | 2502   | 130    | mpegts | PASS 2686 |
| 47   | 900.023   | 30/1    | 1280×720 | 2501   | 130    | mpegts | PASS 2658 |

* **Wall clock (4 segments, parallel jobs):** 436 s total (per-seg ~418–436 s),
  budget 1800 s ⇒ **PASS**. Single segment ≈ 3.2× realtime.
* **P0-D3 concat smoke:** `concat:seg44|seg45` CLEAN, `concat:seg44..47` CLEAN
  (no corrupt / non-monotonic).
* **Manifest:** each segment's event multiset matches the daypack slice
  `[index*900, (index+1)*900)` and every `offset_ms` matches.
* **Screenshots:** `/opt/logs/41490/out/rsghsing/p3/shot_{head,mid,tail}.png` +
  `contact_sheet.png` (relative seek at 1 / 450 / 898 s; frames differ — floaters
  animate).

## Reproduce

```
cargo build --release            # in src/rsghsing
bash ops/experiments/rsghsing-p3/bench_1h.sh          # full bench, exit 0 = green
python3 ops/experiments/rsghsing-p3/manifest_check.py <seg.ts>   # per segment
```
