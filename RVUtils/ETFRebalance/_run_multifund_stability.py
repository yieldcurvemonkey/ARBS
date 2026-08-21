"""Per-year IC stability for one (fund, signal, horizon) cell -- the winner only.

A t-stat pooled across 8-10 years can be entirely one or two good years. This recomputes
the partial IC split by calendar year for a single named cell, and reports the sign
count, which is the non-parametric check the house discipline asks for.
"""

from __future__ import annotations

import argparse
import os
import sys

os.environ.setdefault("ARBS_SUPABASE_ENABLED", "0")
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..")))

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from MDP.ETFHoldings.universe import spec  # noqa: E402
from RVUtils.ETFRebalance import bond_panel as BP  # noqa: E402
from RVUtils.ETFRebalance import engine as EN  # noqa: E402
from RVUtils.ETFRebalance import float_panel as FP  # noqa: E402
from RVUtils.ETFRebalance import holdings_panel as HP  # noqa: E402
from RVUtils.ETFRebalance import ic as IC  # noqa: E402
from RVUtils.ETFRebalance import signals as SIG  # noqa: E402

OUTDIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..",
                      "notebooks", "backtests", "etf_rebalance", "_data")


def orthogonalise(df, target, control):
    out = pd.Series(np.nan, index=df.index)
    for _, g in df.groupby("date", sort=False):
        x = g[control].to_numpy(float)
        y = g[target].to_numpy(float)
        ok = np.isfinite(x) & np.isfinite(y)
        if ok.sum() < 8:
            continue
        xc = x[ok] - x[ok].mean()
        den = float(np.dot(xc, xc))
        if den <= 0:
            continue
        b = float(np.dot(xc, y[ok] - y[ok].mean()) / den)
        r = np.full(len(g), np.nan)
        r[ok] = y[ok] - (y[ok].mean() + b * xc)
        out.loc[g.index] = r
    return out


def spearman_ic_by_year(d, sig_col, ret_col, min_names=8):
    rows = {}
    for (yr,), g in d.groupby([d["date"].dt.year], sort=True):
        per = []
        for _, gg in g.groupby("date", sort=False):
            if len(gg) < min_names:
                continue
            per.append(IC._spearman(gg[sig_col].to_numpy(float), gg[ret_col].to_numpy(float)))
        v = np.array([x for x in per if np.isfinite(x)], float)
        if v.size < 5:
            continue
        rows[int(yr)] = {"ic_mean": float(v.mean()), "n_dates": v.size,
                         "t": float(v.mean() / (v.std(ddof=1) / np.sqrt(v.size))) if v.size > 1 else np.nan}
    return rows


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--fund", required=True)
    ap.add_argument("--signal", required=True)
    ap.add_argument("--horizon", type=int, required=True)
    ap.add_argument("--exec-lag", type=int, default=1)
    a = ap.parse_args()

    sp = spec(a.fund)
    panel = FP.asof_join(BP.load(), FP.load())
    joined = HP.build([a.fund], panel=panel)
    from MDP.ETFHoldings import store as HS
    cov = HS.coverage(a.fund)
    first_date = cov["first"].min()
    valid_dates = set(pd.to_datetime(joined.loc[joined["ticker"] == a.fund, "date"].unique()))

    cfg = EN.merge_config({"fund": a.fund, "universe": {"start": first_date.strftime("%Y-%m-%d")}})
    uni, _ = EN.prepare_universe(cfg, joined=joined, panel=panel)
    uni = uni[uni["date"].isin(valid_dates)].copy()

    kw = {"flow": {"window": 5}, "active_chg": {"window": 5}, "ownership_chg": {"window": 21}}
    d = uni.copy()
    for name in (a.signal, "resid"):
        raw = SIG.REGISTRY[name](d, **kw.get(name, {}))
        d[f"z_{name}"] = SIG.cross_sectional_z(raw, d["date"], robust=True).clip(-5, 5)

    d = IC.forward_residual_return(d, [a.horizon])
    d = d.sort_values(["cusip", "date"])
    for c in (f"z_{a.signal}", "z_resid"):
        d[c] = d.groupby("cusip")[c].shift(a.exec_lag)

    pcol = f"p_{a.signal}"
    d[pcol] = orthogonalise(d, f"z_{a.signal}", "z_resid")

    by_year_raw = spearman_ic_by_year(d, f"z_{a.signal}", f"fwd_{a.horizon}")
    by_year_partial = spearman_ic_by_year(d, pcol, f"fwd_{a.horizon}")

    print(f"{a.fund} / {a.signal} / {a.horizon}d -- per-year IC (exec_lag={a.exec_lag})")
    rows = []
    for yr in sorted(set(by_year_raw) | set(by_year_partial)):
        r = by_year_raw.get(yr, {})
        p = by_year_partial.get(yr, {})
        rows.append({"year": yr, "raw_ic": r.get("ic_mean"), "raw_n": r.get("n_dates"),
                     "partial_ic": p.get("ic_mean"), "partial_n": p.get("n_dates")})
        print(f"  {yr}: raw_ic={r.get('ic_mean')}  n={r.get('n_dates')}   "
              f"partial_ic={p.get('ic_mean')}  n={p.get('n_dates')}")

    out = pd.DataFrame(rows)
    pos = int((out["partial_ic"] > 0).sum())
    tot = int(out["partial_ic"].notna().sum())
    print(f"\nsign test on partial IC: {pos}/{tot} years positive")
    out.to_csv(os.path.join(OUTDIR, f"multifund_stability_{a.fund}_{a.signal}_{a.horizon}.csv"), index=False)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
