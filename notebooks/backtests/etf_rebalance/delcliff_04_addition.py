"""Step 4: addition side. New 30y original-issue CUSIPs enter TLT (already >=20y ttm at
issuance) at the first month-end after auction. This is NOT a clean test of ETF-driven
richening: a freshly issued 30y bond is also the ON-THE-RUN, and its yield normally
RISES (cheapens) as OTR premium decays through the reopening cycle -- the same
direction any 'TLT support fading' story would predict. There is no calendar-only
control that separates the two here; this is run and reported as auction-cycle-
confounded measurement, not an identified ETF-flow result.
"""
from __future__ import annotations

import os
os.environ.setdefault("ARBS_SUPABASE_ENABLED", "0")

import numpy as np
import pandas as pd

from RVUtils.ETFRebalance import bond_panel as BP
from RVUtils.ETFRebalance import curve as CV

OUT = BP.panel_dir()
OFFSETS = list(range(0, 121, 1))


def main():
    panel = BP.load()
    panel = panel[~panel["yield_gate_fail"]].copy()
    panel_dates = np.array(sorted(panel["date"].unique()))
    idx_of = {d: i for i, d in enumerate(panel_dates)}

    add30 = pd.read_csv(OUT / "delcliff_addition_calendar_30y.csv", parse_dates=["event_date"])
    add30 = add30[add30["usable_window"]].copy()
    print(f"addition events (usable): {len(add30)}", flush=True)

    sub = panel[panel["ttm"].between(15.0, 31.0)].copy()
    resid = CV.fit_residuals(sub, x_axis="ttm", include_coupon=True, robust=True, deg=3)
    piv = resid.pivot_table(index="date", columns="cusip", values="resid_bp").reindex(panel_dates)

    rows = []
    for r in add30.itertuples():
        later = panel_dates[panel_dates >= np.datetime64(r.event_date)]
        if len(later) == 0 or r.cusip not in piv.columns:
            continue
        i0 = idx_of[later[0]]
        base = piv.iloc[i0].get(r.cusip)
        for off in OFFSETS:
            j = i0 + off
            if j >= len(panel_dates):
                continue
            v = piv.iloc[j].get(r.cusip)
            if np.isfinite(v) and np.isfinite(base):
                rows.append({"cusip": r.cusip, "event_date": r.event_date, "off": off,
                             "resid_bp": v, "excess_bp": v - base})

    df = pd.DataFrame(rows)
    df.to_csv(OUT / "delcliff_addition_paths.csv", index=False)
    agg = df.groupby("off")["excess_bp"].agg(["mean", "median", "count"]).reset_index()
    print(agg[agg["off"].isin([0, 10, 20, 30, 45, 60, 90, 120])].to_string(index=False), flush=True)

    for lo, hi in [(0, 60), (60, 120)]:
        e = df[df["off"].between(lo, hi)].groupby(["cusip", "event_date"])["excess_bp"].mean()
        n = e.notna().sum()
        t = float(e.mean() / (e.std(ddof=1) / np.sqrt(n))) if n > 1 else np.nan
        print(f"[{lo}-{hi}bd] mean={e.mean():.3f}bp median={e.median():.3f}bp t={t:.2f} "
              f"n={n} sign+={(e>0).mean()*100:.0f}%", flush=True)


if __name__ == "__main__":
    main()
