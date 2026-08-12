"""Warm the GSS curve panel and run the butterfly book through QueryDrivenBacktest.

The panel is built in chunks against the resumable per-day cache, so an interrupted run — and on
this upstream interruptions are routine, not exceptional — restarts where it stopped instead of
from zero. Each chunk prints a flushed line, so the log shows progress rather than sitting silent
behind a block-buffered pipe.

Three configurations are run, because two of the deviations from the GSS source are judgement calls
and the honest way to present a judgement call is to show what the other choice costs::

    conda run -n stir python scripts/run_gss_backtest.py --start 2024-09-02 --end 2026-01-02
"""

from __future__ import annotations

import argparse
import datetime
import logging
import os
import sys
import time
from pathlib import Path

os.environ.setdefault("ARBS_SUPABASE_ENABLED", "0")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pandas as pd  # noqa: E402

logging.basicConfig(level=logging.ERROR, format="%(asctime)s %(levelname)s %(message)s")

from BT.gss_fly import CostConfig, FlyConfig, GSSConfig, build_curve_panel, load_repo_from_workbook  # noqa: E402
from BT.gss_fly.data import ust_business_days  # noqa: E402
from BT.gss_fly.backtest import run_gss_backtest  # noqa: E402
from MDP.FixedRateBonds.FixedRateBondsMDP import FixedRateBondsMDP  # noqa: E402

VARIANTS = [
    ("default (all legs charged, corrected wing objective)", lambda: GSSConfig()),
    ("belly-only costs (what the GSS source charges)", lambda: GSSConfig(costs=CostConfig(cost_legs="belly_only"))),
    ("legacy wing objective (the source's z-minus-maturity)", lambda: GSSConfig(fly=FlyConfig(wing_objective="legacy_ttm_bug"))),
]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--start", default="2024-09-02")
    ap.add_argument("--end", default="2026-01-02")
    ap.add_argument("--chunk", type=int, default=25, help="days per progress line")
    ap.add_argument("--cache", default="notebooks/data/gss_fly/panel_cached")
    ap.add_argument("--repo-workbook", default=r"C:/Users/chris/Downloads/gc_repo_hist_example.xlsx")
    ap.add_argument("--panel-only", action="store_true")
    ap.add_argument("--workers", type=int, default=6,
                    help="concurrent day fetches; the work is remote I/O, not compute")
    args = ap.parse_args()

    mdp = FixedRateBondsMDP(source="USTS_FEDINVEST_WSJ_LIVE-QL")
    # NOT bdate_range: that includes market holidays, which the source never serves and the
    # fetcher hangs on rather than refusing. One Labor Day stalled two separate warms.
    days = ust_business_days(args.start, args.end)
    cache = Path(args.cache)
    print(f"PANEL: {len(days)} business days {args.start}..{args.end} -> {cache}", flush=True)

    t0 = time.time()
    panel = None
    for i in range(0, len(days), args.chunk):
        chunk_end = min(i + args.chunk, len(days))
        # `consolidate="never"` is load-bearing: each call asks about a PREFIX of the range, and a
        # prefix that consolidated would be served on every later read as if it were the whole
        # panel. Each call re-reads the day cache and fetches only what is missing; that re-read is
        # cheap next to the fetches it avoids.
        panel = build_curve_panel(days[:chunk_end], mdp, cache_path=cache, show_progress=False,
                                  consolidate="never", workers=args.workers)
        print(f"PANEL: {chunk_end}/{len(days)} days  ({time.time() - t0:.0f}s)  {panel.summary()}", flush=True)

    # One final full-range pass, this time allowed to consolidate if every date resolved.
    panel = build_curve_panel(days, mdp, cache_path=cache, show_progress=False, workers=args.workers)
    if panel is None:
        print("PANEL: nothing built", flush=True)
        return 1
    print(f"PANEL: done {panel.summary()}", flush=True)
    if args.panel_only:
        return 0

    repo = None
    wb = Path(args.repo_workbook)
    if wb.exists():
        try:
            repo = load_repo_from_workbook(wb, "USTREASGC")
            print(f"REPO: {repo}", flush=True)
        except Exception as exc:  # noqa: BLE001
            print(f"REPO: unavailable ({type(exc).__name__}: {exc}) — running unfinanced", flush=True)

    for label, make in VARIANTS:
        try:
            r = run_gss_backtest(panel, mdp, cfg=make(), repo_curve=repo, show_progress=False, strict=False)
            print(f"VARIANT | {label}", flush=True)
            print("   diag " + str({k: r.diagnostics[k] for k in
                                    ("marked_days", "equity_holes", "signal_entries", "closed_positions")}), flush=True)
            sm = r.summary()
            print("   summ " + str({k: (round(v, 1) if isinstance(v, float) else v)
                                    for k, v in sm.items()}), flush=True)
            # the reconciliation, stated rather than assumed
            print(f"   recon carry={sm.get('carry_during_hold_usd', float('nan')):,.0f} "
                  f"+ unwind={sm.get('unwind_proceeds_usd', float('nan')):,.0f} "
                  f"+ fees={sm.get('fees_usd', float('nan')):,.0f} "
                  f"+ open={sm.get('open_mtm_usd', float('nan')):,.0f} "
                  f"=> equity={sm.get('end_equity_usd', float('nan')):,.0f} "
                  f"(gap {sm.get('reconciliation_gap_usd', float('nan')):,.2f})", flush=True)
            print(f"   costs  gross_before_fees={sm.get('gross_before_fees_usd', float('nan')):,.0f} "
                  f"cost_share_of_gross={sm.get('cost_share_of_gross', float('nan')):.1%}", flush=True)
        except Exception as exc:  # noqa: BLE001
            print(f"VARIANT | {label} FAILED {type(exc).__name__}: {exc}", flush=True)
    print("GSSDONE", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
