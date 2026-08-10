"""Finish warming the RAW book, and re-fetch the days whose fetch FAILED.

Two separate gaps after `_prewarm_manual_ranks.py`:

1. It warmed from the post-gate book (788 events, 688 symbol-days). The raw
   pre-overlap book has 695 — 7 days belonging to events the rank-3 gate dropped.
   Missing days make ``check_coverage`` refuse a rank outright, so a handful of
   them costs a whole instrument.

2. Two fetches raised ConnectionError rather than returning no data:
   GEZ20 on 2020-06-30 and 2020-07-14. An exception and a quiet day both land in
   the cache as an empty frame, and once the process that knew the difference
   exits, the next one logs them as `no_bars_that_day` — a failure reported as a
   fact about the market. Evict those keys so they are fetched again.

    python _topup_raw_ranks.py
"""

from __future__ import annotations

import argparse
import datetime
import io
import pickle
import sys
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.path.insert(0, r"C:\Users\chris\clee\ARBS-gcb")
sys.path.insert(0, str(Path(__file__).parent))

from MDP.STIRFutures.STIRFutureMDP import STIRFutureMDP

import global_hawk_dove_common as G

HERE = Path(__file__).parent
CACHE = HERE / "_global_cache"

FAILED = [("GEZ20", datetime.date(2020, 6, 30)),
          ("GEZ20", datetime.date(2020, 7, 14))]


def _p(*a):
    print(*a, flush=True)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--ranks", default="1,2,3,4,5,6")
    args = ap.parse_args()
    ranks = [int(x) for x in args.ranks.split(",") if x.strip()]

    n0 = G.load_bar_cache(CACHE / "bars.pkl")
    for k in FAILED:
        if k in G._BAR_CACHE:
            del G._BAR_CACHE[k]
            _p(f"evicted failed fetch {k}")

    with open(CACHE / "events_manual_raw.pkl", "rb") as f:
        evs = pickle.load(f)["FED"]["events"]
    cfg = G.CB_CONFIGS["FED"]
    barchart = STIRFutureMDP(source="BARCHART_STIRF-RL")
    _p(f"bar cache {n0}   raw events {len(evs)}   ranks {ranks}")

    for rank in ranks:
        variant = G.rebuild_with_contract(evs, cfg, rank)
        want = {(e["symbol"], e["entry_ts"].date()) for e in variant}
        missing = want - set(G._BAR_CACHE)
        _p(f"\n=== rank {rank}: {len(missing)} of {len(want)} symbol-days to fetch ===")
        if not missing:
            _p("  complete")
            continue
        todo = [e for e in variant
                if (e["symbol"], e["entry_ts"].date()) in missing]
        before = len(G._BAR_CACHE)
        G.gate_events(todo, cfg, barchart, max_staleness_min=45, show_progress=True)
        _p(f"  +{len(G._BAR_CACHE) - before} symbol-days")
        G.save_bar_cache(CACHE / "bars.pkl")

    n = G.save_bar_cache(CACHE / "bars.pkl")
    _p(f"\nbar cache {n0} -> {n}")
    if G.FETCH_FAILURES:
        _p(f"  WARNING: {len(G.FETCH_FAILURES)} fetches FAILED")
        for k, v in G.FETCH_FAILURES.items():
            _p(f"    {k}: {v[:90]}")
    else:
        _p("  no fetch failures")

    for rank in ranks:
        variant = G.rebuild_with_contract(evs, cfg, rank)
        want = {(e["symbol"], e["entry_ts"].date()) for e in variant}
        _p(f"  rank {rank}: {len(want - set(G._BAR_CACHE))} still missing")


if __name__ == "__main__":
    main()
