"""Decompose grid-run trade PnL by proximity to IMM (3rd Wed of Mar/Jun/Sep/Dec)
and FOMC dates.

The Q12STIRT curve treats SFRn as a CONSTANT-MATURITY rank — when the front
contract expires on the 3rd Wed IMM date, what was rank-2 becomes rank-1.
That introduces a *discontinuity* in the rate timeseries that intraday
samples interpret as a real overnight move and the strategy fades/follows
spuriously.  If a large fraction of the headline PnL is concentrated in
±1 day of IMM rolls, the result is partly an artefact.
"""
from __future__ import annotations

import datetime as dt
import sys
from pathlib import Path
from typing import List

import numpy as np
import pandas as pd

sys.path.insert(0, r"C:\Users\chris\clee\ARBS")

# ---- IMM 3rd-Wed enumeration ----
def imm_third_wed(year: int, month: int) -> dt.date:
    d = dt.date(year, month, 1)
    first_wed = d + dt.timedelta(days=(2 - d.weekday()) % 7)
    return first_wed + dt.timedelta(days=14)

def imm_dates(start: dt.date, end: dt.date) -> List[dt.date]:
    out = []
    for y in range(start.year - 1, end.year + 2):
        for m in (3, 6, 9, 12):
            d = imm_third_wed(y, m)
            if start <= d <= end:
                out.append(d)
    return sorted(out)


def fomc_dates_safe() -> List[dt.date]:
    try:
        from SDRUtils.analytics.seasonality import get_fomc_dates
        return get_fomc_dates()
    except Exception:
        return []


def days_to_nearest(dates: List[dt.date]):
    sa = np.sort(np.array([np.datetime64(d) for d in dates]))
    def f(d):
        d64 = np.datetime64(d)
        if len(sa) == 0:
            return None
        # nearest absolute delta in days
        deltas = (sa - d64).astype("timedelta64[D]").astype(int)
        return int(np.min(np.abs(deltas)))
    return f


def main():
    trades_path = Path(r"C:\Users\chris\clee\ARBS\BT\results\asia_fade_grid\all_trades.parquet")
    if not trades_path.exists():
        sys.exit(f"missing {trades_path}")

    t = pd.read_parquet(trades_path)
    if "date" in t.columns:
        t["date"] = pd.to_datetime(t["date"])
    if "package" not in t.columns:
        sys.exit("no 'package' column in all_trades.parquet")

    # PnL columns: framework gives 'net_usd' / 'gross_usd' with sign matching
    # the polarity selected when the engine ran (default "fade").
    # apply_filter() flips for momentum at grid time; here we'll show both
    # by reporting |net_usd| × +1 (fade) and |net_usd| × -1 (momentum) only
    # where useful.  For attribution we group on raw net_usd as built.
    if "net_usd" not in t.columns:
        sys.exit("no 'net_usd' column in all_trades.parquet")

    start = t["date"].min().date()
    end   = t["date"].max().date()
    print(f"Loaded {len(t):,} trades, {start} → {end}, packages={t['package'].nunique()}")

    imm = imm_dates(start, end)
    fomc = [d for d in fomc_dates_safe() if start <= d <= end]
    print(f"IMM dates in window: {len(imm)}")
    print(f"FOMC dates in window: {len(fomc)}")

    t["days_to_imm"]  = t["date"].dt.date.apply(days_to_nearest(imm))
    t["days_to_fomc"] = t["date"].dt.date.apply(days_to_nearest(fomc))

    def bucket_imm(d):
        if d is None: return "n/a"
        if d == 0: return "0  (IMM)"
        if d == 1: return "±1"
        if d == 2: return "±2"
        if d <= 5: return "±3-5"
        if d <= 10: return "±6-10"
        return "≥11"
    def bucket_fomc(d):
        if d is None: return "n/a"
        if d == 0: return "0  (FOMC)"
        if d == 1: return "±1"
        if d == 2: return "±2"
        if d <= 5: return "±3-5"
        if d <= 10: return "±6-10"
        return "≥11"
    t["imm_bucket"]  = t["days_to_imm"].apply(bucket_imm)
    t["fomc_bucket"] = t["days_to_fomc"].apply(bucket_fomc)

    # ── For each package, summarise FADE and MOMENTUM PnL split by IMM bucket
    def fmt_pct(n, d):
        return f"{(n/d*100):+5.1f}%" if d else "  n/a"

    print()
    print("=" * 120)
    print("  IMM-PROXIMITY PnL DECOMPOSITION (per package)")
    print("=" * 120)
    bucket_order_imm = ["0  (IMM)", "±1", "±2", "±3-5", "±6-10", "≥11"]
    pkgs = sorted(t["package"].unique())

    for pkg in pkgs:
        sub = t[t["package"] == pkg]
        if sub.empty:
            continue
        # base sign from raw column == as-built ("fade" by default in events)
        total_fade = sub["net_usd"].sum()
        total_mom  = -sub["net_usd"].sum()
        n          = len(sub)
        print(f"\n  ── {pkg}    n={n:,}    FADE_total=${total_fade:+,.0f}    MOM_total=${total_mom:+,.0f}")
        print(f"      {'bucket':<11} {'n':>6}  {'%n':>6}  {'fade $':>14}  {'%fade':>7}  {'mom $':>14}  {'%mom':>7}")
        for b in bucket_order_imm:
            g = sub[sub["imm_bucket"] == b]
            if g.empty:
                continue
            f_ = g["net_usd"].sum()
            m_ = -g["net_usd"].sum()
            print(f"      {b:<11} {len(g):>6}  {len(g)/n*100:>5.1f}%  "
                  f"${f_:>+13,.0f}  {fmt_pct(f_, total_fade)}  "
                  f"${m_:>+13,.0f}  {fmt_pct(m_, total_mom)}")

    # ── Overall: PnL share concentrated at IMM ±1 vs everywhere else
    print()
    print("=" * 120)
    print("  HEADLINE: share of PnL concentrated at IMM dates  (per package)")
    print("=" * 120)
    print(f"  {'package':<22}  {'pol':>5}  {'n':>6}  {'IMM±1 n':>9}  {'IMM±1 %':>8}  {'IMM±1 $':>14}  {'IMM±1 % of total':>18}")
    for pkg in pkgs:
        sub = t[t["package"] == pkg]
        if sub.empty:
            continue
        for pol, sign in [("fade", +1), ("mom",  -1)]:
            total = (sub["net_usd"] * sign).sum()
            if abs(total) < 1:
                continue
            near = sub[sub["days_to_imm"] <= 1]
            near_pnl = (near["net_usd"] * sign).sum()
            print(f"  {pkg:<22}  {pol:>5}  {len(sub):>6}  {len(near):>9}  "
                  f"{len(near)/len(sub)*100:>7.1f}%  ${near_pnl:>+13,.0f}  {near_pnl/total*100:>17.1f}%")

    # ── Same for FOMC
    print()
    print("=" * 120)
    print("  HEADLINE: share of PnL concentrated at FOMC dates  (per package)")
    print("=" * 120)
    print(f"  {'package':<22}  {'pol':>5}  {'n':>6}  {'FOMC±1 n':>10}  {'FOMC±1 %':>9}  {'FOMC±1 $':>14}  {'FOMC±1 % of total':>19}")
    for pkg in pkgs:
        sub = t[t["package"] == pkg]
        if sub.empty:
            continue
        for pol, sign in [("fade", +1), ("mom",  -1)]:
            total = (sub["net_usd"] * sign).sum()
            if abs(total) < 1:
                continue
            near = sub[sub["days_to_fomc"] <= 1]
            near_pnl = (near["net_usd"] * sign).sum()
            print(f"  {pkg:<22}  {pol:>5}  {len(sub):>6}  {len(near):>10}  "
                  f"{len(near)/len(sub)*100:>8.1f}%  ${near_pnl:>+13,.0f}  {near_pnl/total*100:>18.1f}%")


if __name__ == "__main__":
    main()
