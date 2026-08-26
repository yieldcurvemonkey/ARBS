"""Recompute the panel a SECOND, different way and demand the two agree.

s3_panel indexes with np.searchsorted on int64 nanoseconds. An off-by-one there
is invisible - it would just shift every price one minute and still produce a
beautiful chart. So this recomputes the same numbers with pandas slicing on a
tz-aware DatetimeIndex, which shares no code with the first implementation, and
compares them cell by cell.

    python p5_independent_recompute.py --panel _smoke_paths.parquet --bars _smoke_bars.pkl
"""
from __future__ import annotations

import argparse
import datetime
import io
import sys
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.path.append(r"C:\Users\chris\clee\ARBS")
sys.path.append(r"C:\Users\chris\clee\ARBS\notebooks\backtests\intraday_fed_hawk_dove")

import numpy as np
import pandas as pd

import global_hawk_dove_common as G

HERE = Path(r"C:\Users\chris\clee\ARBS\notebooks\backtests\intraday_fed_hawk_dove\_event_study")
STALE_CAP = 15.0


def ref_price(bars: pd.DataFrame, T: pd.Timestamp):
    """The rule, written with pandas slicing instead of searchsorted."""
    if bars is None or len(bars) == 0:
        return np.nan, np.nan
    prior = bars.loc[bars.index < T]          # STRICTLY before T
    if len(prior) == 0:
        return np.nan, np.nan
    lab = prior.index[-1]
    stale = (T - lab).total_seconds() / 60.0 - 1.0    # close is stamped label+1min
    if stale > STALE_CAP:
        return np.nan, stale
    return float(prior["Close"].iloc[-1]), stale


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--panel", default="_smoke_paths.parquet")
    ap.add_argument("--bars", default="_smoke_bars.pkl")
    ap.add_argument("--n", type=int, default=25, help="event-ranks to recompute")
    args = ap.parse_args()

    G.load_bar_cache(HERE / args.bars)
    panel = pd.read_parquet(HERE / args.panel)
    tz = G.CB_CONFIGS["FED"].tz
    print(f"panel {args.panel}: {len(panel):,} rows", flush=True)

    keys = panel[["event_id", "contract_rank"]].drop_duplicates()
    rng = np.random.default_rng(7)
    if len(keys) > args.n:
        keys = keys.iloc[sorted(rng.choice(len(keys), args.n, replace=False))]

    n_cell = n_bad = 0
    bad_rows = []
    for _, k in keys.iterrows():
        sub = panel[(panel["event_id"] == k["event_id"])
                    & (panel["contract_rank"] == k["contract_rank"])].sort_values("offset_min")
        ts = pd.Timestamp(sub["speech_ts"].iloc[0])
        sym = sub["symbol"].iloc[0]
        # gather every calendar day the window can touch, exactly as the panel does
        d0 = (ts + pd.Timedelta(minutes=-120 - STALE_CAP - 1)).date()
        d1 = (ts + pd.Timedelta(minutes=300)).date()
        days = [d0 + datetime.timedelta(days=i) for i in range((d1 - d0).days + 1)]
        frames = [G._BAR_CACHE.get((sym, d)) for d in days]
        # same data-admissibility rule as the panel: a 1-price grid is fabricated,
        # not data. This is a separate concern from the INDEXING rule, which is what
        # this script is independently reimplementing.
        frames = [f for f in frames
                  if f is not None and len(f) and int(f["Close"].nunique()) >= 2]
        bars = pd.concat(frames).sort_index() if frames else pd.DataFrame()

        base_px, _ = ref_price(bars, ts + pd.Timedelta(minutes=-60))
        for _, row in sub.iterrows():
            T = ts + pd.Timedelta(minutes=int(row["offset_min"]))
            px, stale = ref_price(bars, T)
            got = row["price"]
            ok_px = (np.isnan(px) and pd.isna(got)) or (
                not pd.isna(got) and np.isclose(px, got))
            rate = (100.0 - px) * 100.0
            d = rate - (100.0 - base_px) * 100.0 if base_px == base_px else np.nan
            gd = row["d_rate_bp_from_baseline"]
            ok_d = (np.isnan(d) and pd.isna(gd)) or (not pd.isna(gd) and np.isclose(d, gd))
            sgn = int(row["stance_sign"])
            sd = d * sgn if sgn != 0 else np.nan
            gs = row["signed_d_bp"]
            ok_s = (np.isnan(sd) and pd.isna(gs)) or (not pd.isna(gs) and np.isclose(sd, gs))
            n_cell += 3
            for lab, ok, want, got_ in (("price", ok_px, px, got),
                                        ("d_rate", ok_d, d, gd),
                                        ("signed", ok_s, sd, gs)):
                if not ok:
                    n_bad += 1
                    bad_rows.append((int(row["event_id"]), int(row["contract_rank"]),
                                     int(row["offset_min"]), lab, want, got_))

    print(f"recomputed {len(keys)} event-ranks, {n_cell} cells")
    print(f"MISMATCHES: {n_bad}")
    for r in bad_rows[:20]:
        print("   ", r)

    # A test that cannot fail is not a test: shift the reference by one bar and
    # confirm the comparison DOES break.
    print("")
    print("--- is this comparison capable of failing? ---")
    ev0 = keys.iloc[0]
    sub = panel[(panel["event_id"] == ev0["event_id"])
                & (panel["contract_rank"] == ev0["contract_rank"])].sort_values("offset_min")
    ts = pd.Timestamp(sub["speech_ts"].iloc[0])
    sym = sub["symbol"].iloc[0]
    bars = G._BAR_CACHE.get((sym, ts.date()))
    if bars is not None and len(bars):
        n_diff = 0
        for _, row in sub.iterrows():
            T = ts + pd.Timedelta(minutes=int(row["offset_min"]))
            leak = bars.loc[bars.index <= T]          # the <= variant: LEAKS
            v = float(leak["Close"].iloc[-1]) if len(leak) else np.nan
            if not ((np.isnan(v) and pd.isna(row["price"]))
                    or (not pd.isna(row["price"]) and np.isclose(v, row["price"]))):
                n_diff += 1
        print(f"  the leaky '<= T' variant disagrees with the panel on {n_diff} of "
              f"{len(sub)} offsets for event {int(ev0['event_id'])} -> the comparison "
              f"has teeth (0 would mean it can never fail)")
    print("")
    print("VERDICT:", "IDENTICAL" if n_bad == 0 else f"{n_bad} MISMATCHES - investigate")


if __name__ == "__main__":
    main()
