#!/usr/bin/env python3
"""P3 manifest cross-check (Issue #106, acceptance 2).

Usage: manifest_check.py <seg-NN.ts>   [--daypack <path/to/day.bin>]

Loads the sibling <seg>.manifest.json and verifies, against the GSIN daypack
window [window_start_sec, window_end_sec):
  * the multiset of (type, daypack_tick) equals the daypack slice, and
  * every event's offset_ms == (daypack_tick - window_start_sec) * 1000.
Exit 0 on match, 1 otherwise. The manifest is the renderer's own output, so a
mismatch means the segment does not faithfully represent the daypack window.
"""
import json
import os
import struct
import sys
from collections import Counter

NAMES = {0: "PushEvent", 1: "CreateEvent", 2: "IssuesEvent",
         3: "PullRequestEvent", 4: "ForkEvent", 5: "ReleaseEvent"}


def parse_daypack(buf):
    if buf[0:4] != b"GSIN":
        raise SystemExit("FAIL: bad daypack magic")
    total = struct.unpack("<I", buf[10:14])[0]
    pos = 16
    ticks = []
    for _ in range(total):
        n = buf[pos]
        pos += 1
        evs = []
        for _ in range(n):
            tid, w, tl = buf[pos], buf[pos + 1], buf[pos + 2]
            pos += 3
            text = buf[pos:pos + tl]
            pos += tl
            evs.append((tid, w, text))
        ticks.append(evs)
    return ticks


def find_daypack(date, override):
    if override:
        return override if os.path.exists(override) else None
    cands = [os.environ.get("RSGHSING_DAYPACK")]
    d = os.getcwd()
    for _ in range(6):
        cands.append(os.path.join(d, "var/rsghsing/daypack", date, "day.bin"))
        d = os.path.dirname(d) or "/"
    cands.append(os.path.join("var/rsghsing/daypack", date, "day.bin"))
    for c in cands:
        if c and os.path.exists(c):
            return c
    return None


def main(argv):
    args = [a for a in argv[1:] if not a.startswith("--")]
    override = None
    if "--daypack" in argv:
        override = argv[argv.index("--daypack") + 1]
    if not args:
        print("usage: manifest_check.py <seg.ts> [--daypack path]")
        return 2
    seg = args[0]
    man = seg[:-3] + ".manifest.json" if seg.endswith(".ts") else seg + ".manifest.json"
    if not os.path.exists(man):
        print(f"FAIL: manifest not found: {man}")
        return 1
    m = json.load(open(man))
    ws, we, date = m["window_start_sec"], m["window_end_sec"], m["daypack_date"]

    dp = find_daypack(date, override)
    if not dp:
        print(f"FAIL: daypack for {date} not found (set --daypack or RSGHSING_DAYPACK)")
        return 1
    ticks = parse_daypack(open(dp, "rb").read())

    expected = Counter()
    for tick in range(ws, we):
        for (tid, _w, _t) in ticks[tick]:
            expected[(NAMES.get(tid, "?"), tick)] += 1
    got = Counter((e["type"], e["daypack_tick"]) for e in m["events"])

    ok = True
    if expected != got:
        ok = False
        miss = list((expected - got).items())[:5]
        extra = list((got - expected).items())[:5]
        print(f"FAIL: event set mismatch vs daypack [{ws},{we}). missing={miss} extra={extra}")
    for e in m["events"]:
        if e["offset_ms"] != (e["daypack_tick"] - ws) * 1000:
            ok = False
            print(f"FAIL: bad offset_ms for {e}")
            break
        if not (0 <= e["offset_ms"] < 900_000):
            ok = False
            print(f"FAIL: offset out of segment range: {e}")
            break
    if we - ws != 900 or ws != m.get("segment_index", -1) * 900:
        ok = False
        print(f"FAIL: window/index inconsistent: ws={ws} we={we} idx={m.get('segment_index')}")

    if ok:
        print(f"PASS: {len(m['events'])} events match daypack [{ws},{we}) of {date}; "
              f"offsets correct (daypack={dp})")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
