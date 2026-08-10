"""Warm every symbol-day the configurable notebook's instrument knob can ask for.

The notebook cannot fetch — Barchart's fetcher hits Jupyter's live event loop and
raises — so a knob is only real if the bar cache already holds its bars. The
manual book runs 2019-2026 and was gated at rank 3 only; the earlier prewarm
covered the score-based book, which starts in 2023. Measured before this ran:

    rank 1  409/688 symbol-days cached      rank 5  409/688
    rank 2  409/688                         rank 6  354/688
    rank 3  688/688  <- the baseline        rank 7  354/688
    rank 4  409/688                         rank 8  354/688

    python _prewarm_manual_ranks.py --ranks 1,2,4,5,6,7,8
"""

from __future__ import annotations

import argparse
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
MAX_STALENESS_MIN = 45


def _p(*a):
    print(*a, flush=True)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--events", default="events_manual_manual.pkl")
    ap.add_argument("--bank", default="FED")
    ap.add_argument("--ranks", default="1,2,4,5,6,7,8")
    args = ap.parse_args()
    ranks = [int(x) for x in args.ranks.split(",") if x.strip()]

    with open(CACHE / args.events, "rb") as f:
        evs = pickle.load(f)[args.bank]["events"]
    cfg = G.CB_CONFIGS[args.bank]
    n0 = G.load_bar_cache(CACHE / "bars.pkl")
    _p(f"bar cache: {n0} symbol-days   events: {len(evs)}   ranks {ranks}")

    barchart = STIRFutureMDP(source="BARCHART_STIRF-RL")
    for rank in ranks:
        variant = G.rebuild_with_contract(evs, cfg, rank)
        want = {(e["symbol"], e["entry_ts"].date()) for e in variant}
        missing = len(want - set(G._BAR_CACHE))
        _p(f"\n=== rank {rank}: {len(variant)} events, {missing} symbol-days to fetch ===")
        if not missing:
            _p("  already complete")
            continue
        before = len(G._BAR_CACHE)
        kept, reasons, _diag = G.gate_events(
            variant, cfg, barchart, max_staleness_min=MAX_STALENESS_MIN,
            show_progress=True)
        _p(f"  +{len(G._BAR_CACHE) - before} symbol-days; {len(kept)} of "
           f"{len(variant)} events survive the gate at this rank")
        for k, v in sorted(reasons.items(), key=lambda x: -x[1]):
            _p(f"      gated {k}: {v}")
        n = G.save_bar_cache(CACHE / "bars.pkl")
        _p(f"  bar cache now {n} symbol-days (checkpointed)")

    n = G.save_bar_cache(CACHE / "bars.pkl")
    _p(f"\nbar cache {n0} -> {n} symbol-days ({n - n0} added)")
    if G.FETCH_FAILURES:
        _p(f"  WARNING: {len(G.FETCH_FAILURES)} fetches FAILED (not empty days)")
        for k, v in list(G.FETCH_FAILURES.items())[:10]:
            _p(f"    {k}: {v}")


if __name__ == "__main__":
    main()
