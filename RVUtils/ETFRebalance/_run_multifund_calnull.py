"""Calendar-only null (deletion, addition) per fund -- needs no holdings file at all.

If a holdings-based cell in the main multifund run looks better than dead, this is the
comparison it must survive: does the calendar-only signal earn the same thing without
ever reading a scraped document? If so the scrape bought nothing for that cell.
"""

from __future__ import annotations

import os
import sys

os.environ.setdefault("ARBS_SUPABASE_ENABLED", "0")
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..")))

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from MDP.ETFHoldings import store as HS  # noqa: E402
from MDP.ETFHoldings.universe import spec  # noqa: E402
from RVUtils.ETFRebalance import bond_panel as BP  # noqa: E402
from RVUtils.ETFRebalance import engine as EN  # noqa: E402
from RVUtils.ETFRebalance import float_panel as FP  # noqa: E402
from RVUtils.ETFRebalance import holdings_panel as HP  # noqa: E402
from RVUtils.ETFRebalance import ic as IC  # noqa: E402
from RVUtils.ETFRebalance import signals as SIG  # noqa: E402

pd.set_option("display.width", 220)

HORIZONS = (5, 10, 21, 42, 63)
FUNDS = ["TLT", "TLH", "IEF", "IEI", "GOVT", "SHY"]
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


def spearman_ic(d, sig_col, ret_col, min_names=8):
    per = []
    for _, g in d.groupby("date", sort=False):
        if len(g) < min_names:
            continue
        per.append(IC._spearman(g[sig_col].to_numpy(float), g[ret_col].to_numpy(float)))
    return np.array([x for x in per if np.isfinite(x)], float)


def main() -> int:
    panel = FP.asof_join(BP.load(), FP.load())
    rows = []

    for fund in FUNDS:
        sp = spec(fund)
        cov = HS.coverage(fund)
        if cov.empty:
            continue
        first_date = cov["first"].min()

        joined = HP.build([fund], panel=panel)
        valid_dates = set(pd.to_datetime(joined.loc[joined["ticker"] == fund, "date"].unique()))

        cfg = EN.merge_config({"fund": fund, "universe": {"start": first_date.strftime("%Y-%m-%d")}})
        uni, _ = EN.prepare_universe(cfg, joined=joined, panel=panel)
        uni = uni[uni["date"].isin(valid_dates)].copy()
        if uni.empty or uni["date"].nunique() < 60:
            continue
        print(f"{fund}: {len(uni):,} bond-days, {uni['date'].nunique():,} dates")

        kw = {"deletion": {"band_low": sp.band_low or 0.0, "horizon_m": 3},
              "addition": {"band_high": sp.band_high or np.inf}}
        d = uni.copy()
        for name in ["deletion", "addition", "resid"]:
            raw = SIG.REGISTRY[name](d, **kw.get(name, {}))
            d[f"z_{name}"] = SIG.cross_sectional_z(raw, d["date"], robust=True).clip(-5, 5)

        d = IC.forward_residual_return(d, HORIZONS)
        lagcols = ["z_deletion", "z_addition", "z_resid"]
        d = d.sort_values(["cusip", "date"])
        for c in lagcols:
            d[c] = d.groupby("cusip")[c].shift(1)  # exec_lag=1

        for c in ("deletion", "addition"):
            col, pcol = f"z_{c}", f"p_{c}"
            d[pcol] = orthogonalise(d, col, "z_resid")
            n_finite = d[col].notna().groupby(d["date"]).sum()
            n_usable_dates = int((n_finite > 0).sum())
            for h in HORIZONS:
                for lbl, use in (("raw", col), ("partial", pcol)):
                    v = spearman_ic(d, use, f"fwd_{h}")
                    if v.size < 20:
                        rows.append({"fund": fund, "signal": c, "kind": lbl, "horizon": h,
                                     "ic": np.nan, "t": np.nan, "n_dates": v.size,
                                     "n_usable_dates_signal": n_usable_dates})
                        continue
                    rows.append({
                        "fund": fund, "signal": c, "kind": lbl, "horizon": h,
                        "ic": float(v.mean()),
                        "t": float(v.mean() / (v.std(ddof=1) / np.sqrt(v.size))),
                        "n_dates": v.size, "n_usable_dates_signal": n_usable_dates,
                    })

    out = pd.DataFrame(rows)
    out.to_csv(os.path.join(OUTDIR, "multifund_calendar_null.csv"), index=False)
    print("\n" + "=" * 100)
    print("CALENDAR-ONLY NULL (deletion, addition) -- raw + partial IC, exec_lag=1")
    print("=" * 100)
    if not out.empty:
        print(out.pivot_table(index=["fund", "signal", "kind"], columns="horizon", values="ic").round(4).to_string())
        print("\nt across dates:")
        print(out.pivot_table(index=["fund", "signal", "kind"], columns="horizon", values="t").round(2).to_string())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
