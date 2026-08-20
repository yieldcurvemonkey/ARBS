"""Is today's 95% breadth typical, or is 2026 unusually full-replication?

The multi-issuer probe found TLT holding 38 of 40 eligible 20y+ bonds, SPTL 40 of 40 and
VGLT 39 of 40. If that holds through history it is the mechanical reason the single-fund
study died: a fund that already owns every eligible bond is not choosing which bonds to
buy, so there is no queue of forced purchases to anticipate. The "manager must buy the
underweight name" story needs the manager to be ABSENT from names, and these managers are
not absent from anything.

But breadth is exactly the kind of quantity that drifts. TLT was a smaller fund in 2016,
the 20y point did not exist between 1986 and 2020, and a fund that sampled aggressively
early would leave a very different signal in the early sample. One date cannot settle it,
and the whole cross-issuer history question rides on the answer, so measure it on the ten
years of daily TLT holdings already on disk.
"""
from __future__ import annotations

import os
import sys

os.environ.setdefault("ARBS_SUPABASE_ENABLED", "0")
os.environ.setdefault("ARBS_ETF_HOLDINGS_DIR",
                      "C:/Users/chris/clee/ARBS/MDP/ETFHoldings/etf_holdings_cache")
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                                "..", "..", "..")))

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from RVUtils.ETFRebalance import bond_panel as BP  # noqa: E402
from RVUtils.ETFRebalance import float_panel as FP  # noqa: E402
from RVUtils.ETFRebalance import holdings_panel as HP  # noqa: E402

BAND_LO = 20.0


def main() -> None:
    panel = BP.load()
    floats = FP.load()
    panel = FP.asof_join(panel, floats)
    panel["priced"] = panel["ytm"].notna() & ~panel["yield_gate_fail"].fillna(True)

    uni = panel[panel["ttm"].ge(BAND_LO) & panel["priced"]].copy()
    uni["cusip"] = uni["cusip"].astype(str)
    elig = uni.groupby("date").agg(eligible=("cusip", "nunique"),
                                   float_bn=("free_float", lambda s: s.sum() / 1e9))

    h = HP.load_holdings(["TLT"])
    h["cusip"] = h["cusip"].astype(str)
    h = h[h["par"] > 0]
    # A holding only counts against the eligible board if it IS on the board that day.
    m = uni[["date", "cusip", "free_float"]].merge(
        h[["date", "cusip", "par"]], on=["date", "cusip"], how="left")
    m["par"] = m["par"].fillna(0.0)

    g = m.groupby("date").agg(
        held=("par", lambda s: int((s > 0).sum())),
        par_bn=("par", lambda s: s.sum() / 1e9),
    )
    t = elig.join(g, how="inner")

    # Restrict to dates the fund actually HAS a holdings file for. Without this the
    # statistic silently averages real breadth against days with no document at all: the
    # first pass reported 2017 breadth as 0.0% across 250 days, which is not a fund that
    # held nothing -- it is a store holding only 123 of ~250 days for that year, and the
    # median of a year that is more than half empty is zero. The gap is real and worth
    # fixing, but it is a coverage defect and must not be reported as portfolio breadth.
    have = set(pd.to_datetime(h["date"].unique()))
    missing = [d for d in t.index if d not in have]
    if missing:
        print(f"NOTE: {len(missing)} panel dates have no TLT holdings file and are "
              f"excluded from breadth ({pd.Timestamp(min(missing)).date()} .. "
              f"{pd.Timestamp(max(missing)).date()}).")
        by_year = pd.Series([pd.Timestamp(d).year for d in missing]).value_counts().sort_index()
        print("  missing days by year: " + ", ".join(f"{y}:{n}" for y, n in by_year.items()))
        print()
    t = t[[d in have for d in t.index]]
    t["breadth_pct"] = 100.0 * t["held"] / t["eligible"]
    t["own_pct"] = 100.0 * t["par_bn"] / t["float_bn"]

    yr = t.groupby(t.index.year).agg(
        eligible=("eligible", "median"), held=("held", "median"),
        breadth_pct=("breadth_pct", "median"), own_pct=("own_pct", "median"),
        n_days=("held", "size"))
    print("TLT breadth of the eligible 20y+ board, by year")
    print(yr.to_string(float_format=lambda v: f"{v:,.1f}"))
    print()
    print(f"breadth over the whole sample: min {t['breadth_pct'].min():.1f}%  "
          f"p10 {t['breadth_pct'].quantile(.1):.1f}%  median {t['breadth_pct'].median():.1f}%  "
          f"max {t['breadth_pct'].max():.1f}%")
    print(f"days below 80% breadth: {int((t['breadth_pct'] < 80).sum())} of {len(t)} "
          f"({100.0 * (t['breadth_pct'] < 80).mean():.1f}%)")
    print(f"days below 50% breadth: {int((t['breadth_pct'] < 50).sum())} of {len(t)}")
    print()

    # The bonds TLT does NOT hold: are they a persistent exclusion or a churn?
    miss = m[m["par"].eq(0)]
    if len(miss):
        per_cusip = miss.groupby("cusip").size().sort_values(ascending=False)
        onboard = m.groupby("cusip").size()
        frac = (per_cusip / onboard.reindex(per_cusip.index)).sort_values(ascending=False)
        print("bonds TLT skipped, as a fraction of the days they were eligible (top 10)")
        print(frac.head(10).to_string(float_format=lambda v: f"{v:.2f}"))
        print(f"\nmedian skip fraction across all bonds ever eligible: "
              f"{frac.reindex(onboard.index).fillna(0.0).median():.3f}")

    out = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_data")
    t.to_csv(os.path.join(out, "tlt_breadth_history.csv"))
    print("\nwrote _data/tlt_breadth_history.csv")


if __name__ == "__main__":
    main()
