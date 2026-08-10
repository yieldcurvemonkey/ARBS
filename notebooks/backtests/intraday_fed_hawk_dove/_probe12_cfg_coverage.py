"""How much of the config space can a NOTEBOOK actually run offline?

The notebook cannot fetch (Barchart's fetcher hits the live asyncio loop and
raises). So every knob the config exposes is only real if the bar cache already
holds the (symbol, day) pairs it would ask for. This measures that, per knob,
rather than assuming it.
"""

from __future__ import annotations

import datetime
import io
import pickle
import sys
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.path.insert(0, r"C:\Users\chris\clee\ARBS-gcb")
sys.path.insert(0, str(Path(__file__).parent))

import global_hawk_dove_common as G

HERE = Path(__file__).parent
CACHE = HERE / "_global_cache"

n = G.load_bar_cache(CACHE / "bars.pkl")
print(f"bar cache: {n} symbol-days")

with open(CACHE / "events_manual_manual.pkl", "rb") as f:
    blob = pickle.load(f)
evs = blob["FED"]["events"]
print(f"manual FED gated events: {len(evs)}")
print(f"  window {min(e['speech_ts'] for e in evs).date()} -> "
      f"{max(e['speech_ts'] for e in evs).date()}")

cfg = G.CB_CONFIGS["FED"]
cached = set(G._BAR_CACHE)

print("\n--- contract-rank knob: (symbol, day) coverage in cache ---")
for rank in range(1, 9):
    var = G.rebuild_with_contract(evs, cfg, rank)
    keys = {(e["symbol"], e["entry_ts"].date()) for e in var}
    have = {k for k in keys if k in cached}
    nonempty = sum(1 for k in have if len(G._BAR_CACHE[k]))
    print(f"  rank {rank}: {len(have)}/{len(keys)} cached  "
          f"({nonempty} non-empty)   e.g. {sorted(keys)[0][0]}")

print("\n--- offset knob: does re-timing ask for new symbol-days? ---")
base = {(e["symbol"], e["entry_ts"].date()) for e in evs}
for em, xm in [(-120, 240), (-15, 60), (-45, 180), (-5, 30), (-180, 360)]:
    var = G.rebuild_with_offsets(evs, cfg, datetime.timedelta(minutes=em),
                                 datetime.timedelta(minutes=xm))
    keys = {(e["symbol"], e["entry_ts"].date()) for e in var}
    print(f"  T{em:+d}/T{xm:+d}: {len(var)} events, "
          f"{len(keys - cached)} symbol-days NOT cached, "
          f"{len(keys - base)} outside the baseline day-set")

print("\n--- what the FED cache actually holds, by root ---")
from collections import Counter
c = Counter()
for sym, day in cached:
    root = "".join(ch for ch in sym[:3] if not ch.isdigit())
    c[root[:2] if root[:2] in ("GE", "SR", "IM", "J8", "RG", "J2", "TV") else root] += 1
for k, v in c.most_common(12):
    print(f"  {k:6s} {v}")
