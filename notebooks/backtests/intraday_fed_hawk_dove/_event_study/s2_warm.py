"""STAGE 2 - warm the minute-bar cache for every (symbol, day) the panel indexes.

The multi-day span fetch is NOT bar-for-bar identical to `_day_bars` (see
s2a_batch_test.py: single-bar disagreements on 5 of 35 days, once with a real
11:10 intraday bar present per-day and absent in the span), so this stays on the
one function the panel is required to use, one day at a time.

    python s2_warm.py --dry-run            size the job, fetch nothing
    python s2_warm.py --scope real         real events, ranks 1-5
    python s2_warm.py --scope placebo3     placebo, rank 3 only
    python s2_warm.py --scope placebo_rest placebo, ranks 1,2,4,5
"""
from __future__ import annotations

import argparse
import datetime
import gc
import io
import pickle
import sys
import time
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.path.append(r"C:\Users\chris\clee\ARBS")
sys.path.append(r"C:\Users\chris\clee\ARBS\notebooks\backtests\intraday_fed_hawk_dove")

import pandas as pd

from MDP.STIRFutures.STIRFutureMDP import STIRFutureMDP
import global_hawk_dove_common as G

HERE = Path(r"C:\Users\chris\clee\ARBS\notebooks\backtests\intraday_fed_hawk_dove\_event_study")
GCB_BARS = Path(r"C:\Users\chris\clee\ARBS-gcb\notebooks\backtests\intraday_fed_hawk_dove"
                r"\_global_cache\bars.pkl")
LOCAL_BARS = HERE / "bars_event_study.pkl"

OFFSETS = [-120, -90, -60, -45, -30, -20, -15, -10, -5, 0,
           5, 10, 15, 20, 30, 45, 60, 90, 120, 180, 240, 300]
RANKS = [1, 2, 3, 4, 5]
STALE_CAP_MIN = 15
CHECKPOINT_EVERY = 200


def required_keys(ev: pd.DataFrame, ranks) -> set:
    """(symbol, calendar day) for every day the [-120-stale, +300] window touches.

    An evening speech runs its far offsets into the NEXT calendar day and
    `_day_bars` fetches one day, so the next day must be warmed too or the far
    offsets show up as a fake coverage cliff.
    """
    cfg = G.CB_CONFIGS["FED"]
    keys = set()
    # -1 so this matches s3_panel exactly: at offset -120 a bar labelled T-136 is
    # still usable (its close is stamped T-135, i.e. 15 min stale), so the day
    # holding it must be warmed. Without the -1 the two disagree for a speech at
    # exactly 02:15 local, and s3 would read a day s2 never fetched - which looks
    # like "no bars that day" rather than a missing fetch.
    lo = datetime.timedelta(minutes=min(OFFSETS) - STALE_CAP_MIN - 1)
    hi = datetime.timedelta(minutes=max(OFFSETS))
    for ts in ev["speech_ts"]:
        ts = pd.Timestamp(ts).to_pydatetime()
        d0, d1 = (ts + lo).date(), (ts + hi).date()
        days = [d0 + datetime.timedelta(days=i) for i in range((d1 - d0).days + 1)]
        for rank in ranks:
            sym = G.nth_quarterly_contract(cfg.root_for(ts.date()), ts.date(), rank)
            for d in days:
                keys.add((sym, d))
    return keys


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--scope", default="real",
                    choices=["real", "placebo3", "placebo_rest", "all"])
    args = ap.parse_args()

    ev = pd.read_parquet(HERE / "events.parquet")
    pl = pd.read_parquet(HERE / "placebo_events.parquet")
    print(f"real events {len(ev)}   placebo events {len(pl)}", flush=True)

    need_real = required_keys(ev, RANKS)
    need_pl3 = required_keys(pl, [3])
    need_plrest = required_keys(pl, [1, 2, 4, 5])
    print(f"required symbol-days: real(r1-5) {len(need_real)}   "
          f"placebo(r3) {len(need_pl3)}   placebo(r1,2,4,5) {len(need_plrest)}", flush=True)
    print(f"union {len(need_real | need_pl3 | need_plrest)}", flush=True)

    want = {"real": need_real, "placebo3": need_pl3, "placebo_rest": need_plrest,
            "all": need_real | need_pl3 | need_plrest}[args.scope]

    # ------------------------------------------------------ seed from the caches
    t0 = time.time()
    if LOCAL_BARS.exists():
        n = G.load_bar_cache(LOCAL_BARS)
        print(f"local cache  : {n} symbol-days ({time.time()-t0:.0f}s)", flush=True)
    still = want - set(G._BAR_CACHE)
    if still and GCB_BARS.exists():
        t0 = time.time()
        print(f"reading ARBS-gcb bars.pkl READ-ONLY ({GCB_BARS.stat().st_size/1e6:.0f} MB) ...",
              flush=True)
        with open(GCB_BARS, "rb") as f:
            gcb = pickle.load(f)
        hit = {k: v for k, v in gcb.items() if k in still}
        print(f"  gcb holds {len(gcb)} symbol-days; {len(hit)} of the {len(still)} "
              f"still needed ({time.time()-t0:.0f}s)", flush=True)
        G._BAR_CACHE.update(hit)
        del gcb, hit
        gc.collect()

    # real-event days first, then placebo rank 3, then the rest, so a run that is
    # cut short still leaves the headline panel buildable
    def _prio(k):
        return (0 if k in need_real else 1 if k in need_pl3 else 2, k[0], k[1])

    missing = sorted(want - set(G._BAR_CACHE), key=_prio)
    print(f"scope {args.scope!r}: {len(want)} needed, {len(want)-len(missing)} cached, "
          f"{len(missing)} TO FETCH", flush=True)
    print(f"  fetch order: real {sum(1 for k in missing if k in need_real)}, "
          f"then placebo-r3 {sum(1 for k in missing if k not in need_real and k in need_pl3)}, "
          f"then placebo-rest "
          f"{sum(1 for k in missing if k not in need_real and k not in need_pl3)}", flush=True)
    if missing:
        by_sym = pd.Series([s for s, _ in missing]).value_counts()
        print(f"  missing spans {len(by_sym)} symbols, "
              f"{by_sym.head(5).to_dict()} ... (top 5)", flush=True)
        yrs = pd.Series([d.year for _, d in missing]).value_counts().sort_index()
        print(f"  missing by year: {yrs.to_dict()}", flush=True)

    if args.dry_run:
        print("DRY RUN - nothing fetched", flush=True)
        return
    if not missing:
        print("nothing to do", flush=True)
        G.save_bar_cache(LOCAL_BARS)
        return

    mdp = STIRFutureMDP(source="BARCHART_STIRF-RL")
    fetcher = mdp._get_barchart_fetcher(required_concurrency=6)
    tz = G.CB_CONFIGS["FED"].tz

    t0 = time.time()
    for i, (sym, day) in enumerate(missing, 1):
        G._BAR_CACHE[(sym, day)] = G._day_bars(fetcher, sym, day, tz)
        if i % CHECKPOINT_EVERY == 0 or i == len(missing):
            n = G.save_bar_cache(LOCAL_BARS)
            el = time.time() - t0
            print(f"  {i}/{len(missing)}  {el/60:.1f} min elapsed, "
                  f"{el/i:.2f}s/fetch, eta {(len(missing)-i)*el/i/60:.0f} min; "
                  f"cache {n}; failures {len(G.FETCH_FAILURES)}", flush=True)

    # ------------------------------------------------------------ retry failures
    if G.FETCH_FAILURES:
        bad = sorted(G.FETCH_FAILURES)
        print(f"\n{len(bad)} FAILED fetches - retrying once", flush=True)
        G.FETCH_FAILURES.clear()
        for sym, day in bad:
            G._BAR_CACHE[(sym, day)] = G._day_bars(fetcher, sym, day, tz)
        G.save_bar_cache(LOCAL_BARS)
        print(f"after retry: {len(G.FETCH_FAILURES)} still failing", flush=True)
        for k, v in list(G.FETCH_FAILURES.items())[:15]:
            print(f"    {k}: {v}", flush=True)

    n = G.save_bar_cache(LOCAL_BARS)
    empty = sum(1 for k in want if len(G._BAR_CACHE.get(k, [])) == 0)
    print(f"\nDONE scope={args.scope}  cache {n} symbol-days; "
          f"{empty}/{len(want)} in-scope keys are EMPTY frames "
          f"(genuinely no bars, e.g. weekends / CME halt)", flush=True)
    print(f"residual FETCH_FAILURES: {len(G.FETCH_FAILURES)} "
          f"({len(G.FETCH_FAILURES)/max(len(want),1):.2%} of scope)", flush=True)


if __name__ == "__main__":
    main()
