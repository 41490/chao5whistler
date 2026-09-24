#!/usr/bin/env python3
"""Parse a GSIN day-pack (src/ghsingo/internal/archive/daypack.go format) and
emit per-tick / per-type counts as JSON.

    daypack_stats.py <day.bin> [out.json]

Layout (little-endian): magic "GSIN" | version u16 | date u32 (YYYYMMDD) |
total_ticks u32 | reserved 2B, then per tick: count u8 followed by `count`
events of type_id u8 | weight u8 | text_len u8 | text bytes.

The JSON is order-independent within a tick (events are sorted before
hashing), so `parity.sh` can diff the Go and Rust outputs and call them equal
when the event sets match tick for tick.
"""

import hashlib
import json
import struct
import sys
from pathlib import Path

HEADER_SIZE = 16
MAX_EVENTS_PER_TICK = 4
TYPE_NAMES = ["PushEvent", "CreateEvent", "IssuesEvent",
              "PullRequestEvent", "ForkEvent", "ReleaseEvent"]


def read_daypack(path):
    buf = Path(path).read_bytes()
    if len(buf) < HEADER_SIZE:
        raise SystemExit(f"{path}: too short for a GSIN header ({len(buf)}B)")
    magic = buf[0:4]
    if magic != b"GSIN":
        raise SystemExit(f"{path}: bad magic {magic!r}, want b'GSIN'")
    version, date, total_ticks = struct.unpack_from("<HII", buf, 4)
    ticks = []
    pos = HEADER_SIZE
    for tick in range(total_ticks):
        n = buf[pos]
        pos += 1
        if n > MAX_EVENTS_PER_TICK:
            raise SystemExit(f"{path}: tick {tick} count {n} > {MAX_EVENTS_PER_TICK}")
        events = []
        for _ in range(n):
            type_id, weight, text_len = buf[pos], buf[pos + 1], buf[pos + 2]
            pos += 3
            text = buf[pos:pos + text_len]
            pos += text_len
            events.append((type_id, weight, text))
        if events:
            ticks.append((tick, events))
    if pos != len(buf):
        raise SystemExit(f"{path}: {len(buf) - pos} trailing bytes after {total_ticks} ticks")
    return version, date, total_ticks, ticks


def stats(path):
    version, date, total_ticks, ticks = read_daypack(path)
    by_type = {name: 0 for name in TYPE_NAMES}
    rows = []
    digest = hashlib.sha256()
    total = 0
    for tick, events in ticks:
        counts = [0] * len(TYPE_NAMES)
        for type_id, weight, text in sorted(events):
            counts[type_id] += 1
            digest.update(f"{tick}:{type_id}:{weight}:".encode())
            digest.update(text)
            digest.update(b"\n")
        for i, c in enumerate(counts):
            by_type[TYPE_NAMES[i]] += c
        total += len(events)
        rows.append([tick, *counts, len(events)])
    return {
        "version": version,
        "date": date,
        "total_ticks": total_ticks,
        "total_events": total,
        "ticks_with_events": len(ticks),
        "empty_ticks": total_ticks - len(ticks),
        "by_type": by_type,
        "ticks": rows,
        "events_sha256": digest.hexdigest(),
    }


if __name__ == "__main__":
    if len(sys.argv) < 2:
        raise SystemExit(__doc__)
    out = stats(sys.argv[1])
    if len(sys.argv) > 2:
        text = json.dumps(out, indent=1, sort_keys=True) + "\n"
        Path(sys.argv[2]).write_text(text)
    else:
        print(json.dumps({k: v for k, v in out.items() if k != "ticks"}, indent=2, sort_keys=True))
