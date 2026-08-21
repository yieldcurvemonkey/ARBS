r"""The task's own timezone test: a known 13:00 New York auction, at minute resolution.

Hourly bars cannot tell 13:00 from 13:30, and both are inside the same bar. The
minute tape can, and a thirty-year auction closing at 13:00 New York produces the
sharpest single-minute feature the long end sees on a non-release day.

Reads the targeted window warmed by ``etf_auction_window_warm.py``. Compares the
auction day's minute-of-day activity against the surrounding non-auction days in
the SAME window, so the answer is a ratio and not a level - a level would just
re-measure the ordinary intraday shape.
"""

from __future__ import annotations

import argparse
import pathlib

import numpy as np
import pandas as pd

DATA = pathlib.Path(__file__).resolve().parents[1] / "notebooks/backtests/etf_rebalance/_data"

from MDP.CitiVelocityExcel.cache import CitiVeloTagCache  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--auctions", nargs="+", default=["2026-08-13", "2026-05-13"])
    args = ap.parse_args()
    auctions = {pd.Timestamp(a).date() for a in args.auctions}

    cache = CitiVeloTagCache()
    uni = pd.read_csv(DATA / "intraday_universe.csv")
    uni["maturity_date"] = pd.to_datetime(uni["maturity_date"])
    picks = uni.sort_values("maturity_date", ascending=False).head(40)

    parts = []
    for isin in picks["isin"].astype(str):
        s = cache.read(f"RATES.BOND.{isin}.YIELD", "MI01", "CLOSE")
        if s is None or s.empty:
            continue
        s = s.dropna()
        idx = pd.DatetimeIndex(s.index)
        keep = pd.Series(idx.date).isin(
            auctions | {d + pd.Timedelta(days=k) for d in auctions
                        for k in (-2, -1, 1, 2)}).to_numpy()
        s = s[keep]
        if len(s) < 10:
            continue
        d = s.diff()
        day = pd.Series(s.index).dt.date.to_numpy()
        same = np.r_[False, day[1:] == day[:-1]]
        d = d[same]
        if d.empty:
            continue
        parts.append(pd.DataFrame({
            "date": pd.Series(d.index).dt.date.to_numpy(),
            "mod": d.index.hour * 60 + d.index.minute,
            "bp": np.abs(d.to_numpy()) * 100.0,
        }))
    if not parts:
        print("NO minute data in the auction windows - warm them first.")
        return 1
    allf = pd.concat(parts, ignore_index=True)
    allf["is_auction"] = allf["date"].isin(auctions)
    print(f"{allf['date'].nunique()} days in the windows, "
          f"{int(allf['is_auction'].sum()):,} auction-day minute steps, "
          f"{int((~allf['is_auction']).sum()):,} other")

    # Five-minute buckets: a single minute is too thin to rank reliably.
    allf["bucket"] = (allf["mod"] // 5) * 5
    g = allf.groupby(["bucket", "is_auction"])["bp"].mean().unstack()
    g.columns = ["other", "auction"]
    g["ratio"] = g["auction"] / g["other"]
    g["hhmm"] = [f"{b // 60:02d}:{b % 60:02d}" for b in g.index]
    g = g.dropna()
    pd.set_option("display.width", 200)
    # RANK BY ABSOLUTE ACTIVITY, not by ratio. Overnight buckets have a baseline
    # of ~0.006 bp, so any flicker there produces an enormous ratio: the first
    # version of this test reported its peak at 19:00 off a denominator of
    # 0.0061 bp, which is a division artefact and not an event. The ratio is
    # still shown, as the excess AT the bucket that actually carries the move.
    top_abs = g.sort_values("auction", ascending=False).head(10)
    print("\nAUCTION-DAY ACTIVITY, top 10 five-minute buckets by ABSOLUTE mean "
          "|1-min move| (bp):")
    print(top_abs[["hhmm", "auction", "other", "ratio"]].round(4).to_string())
    peak = int(g["auction"].idxmax())
    print(f"\nPEAK auction-day activity at stamp {peak // 60:02d}:{peak % 60:02d} "
          f"(ratio {g.loc[peak, 'ratio']:.2f}x the non-auction days in the same windows).")
    print(f"If the stamps were UTC that same instant would be labelled "
          f"{(peak // 60 + 4) % 24:02d}:{peak % 60:02d} or "
          f"{(peak // 60 + 5) % 24:02d}:{peak % 60:02d}.")
    print("A 30-year auction closes at 13:00 New York; the 08:30 New York data "
          "release also falls on these days and is the long end's other daily spike.")
    thirteen = g[(g.index >= 780) & (g.index < 795)]
    if len(thirteen):
        print(f"\n13:00-13:15 buckets: auction-day mean {thirteen['auction'].mean():.4f} bp "
              f"vs {thirteen['other'].mean():.4f} bp on the other days in the same "
              f"windows = {thirteen['auction'].mean() / thirteen['other'].mean():.2f}x")
    g.to_csv(DATA / "intraday_auction_minute_profile.csv")
    print("\nwrote intraday_auction_minute_profile.csv")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
