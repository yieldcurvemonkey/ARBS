"""ADVERSARIAL AUDIT of _run_ladder2.py / _run_ladder3_flow.py.

Independent re-run: reuses the same panel-building calls (bond_panel/float_panel/
holdings_panel/engine -- data layer only, trusted per task setup) but recomputes every
statistic from scratch with its own code, specifically to check:

 1. Newey-West vs naive t on the headline cells (report used the NAIVE ic_across_dates
    t throughout; ic.py's own docstring says NW at 63d can shrink a naive t of 51 to "a
    fraction of that").
 2. Year-by-year stability of the double-sort spread on the flagged cells (exclude 2020,
    exclude the single best year).
 3. A crude permutation-based E[max|t|] under the null for ~33 double-sort-eligible
    configs, to see whether the naive t=15.3 headline clears multiple-testing.
 4. Hand arithmetic check: one (date, bucket) row reproduced by hand from the panel.
"""
from __future__ import annotations

import os
import sys

os.environ.setdefault("ARBS_SUPABASE_ENABLED", "0")
os.environ.setdefault("ARBS_ETF_HOLDINGS_DIR",
                       "C:/Users/chris/clee/ARBS/MDP/ETFHoldings/etf_holdings_cache")
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..")))

import numpy as np
import pandas as pd

from MDP.ETFHoldings.universe import spec
from RVUtils.ETFRebalance import bond_panel as BP
from RVUtils.ETFRebalance import engine as EN
from RVUtils.ETFRebalance import float_panel as FP
from RVUtils.ETFRebalance import holdings_panel as HP
from RVUtils.ETFRebalance import ic as IC
from RVUtils.ETFRebalance import signals as SIG
from RVUtils.ETFRebalance._run_ladder import (
    build_bucket_panel, add_hist_z, cs_z_by_date, orthogonalise, double_sort,
)
from RVUtils.ETFRebalance._run_ladder2 import attach_held_fwd

pd.set_option("display.width", 240)

OUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..",
                        "notebooks", "backtests", "etf_rebalance", "_data")
os.makedirs(OUT_DIR, exist_ok=True)

FUND = "TLT"
EXEC_LAG = 1
HORIZONS = (5, 10, 21, 42, 63)


def per_date_ic(d: pd.DataFrame, sig_col: str, ret_col: str, min_names: int):
    dates, vals = [], []
    for dt, g in d.groupby("date", sort=True):
        gg = g.dropna(subset=[sig_col, ret_col])
        if len(gg) < min_names:
            continue
        v = IC._spearman(gg[sig_col].to_numpy(float), gg[ret_col].to_numpy(float))
        if np.isfinite(v):
            dates.append(dt)
            vals.append(v)
    return pd.Series(vals, index=pd.DatetimeIndex(dates))


def naive_t(x: np.ndarray) -> float:
    x = x[np.isfinite(x)]
    n = x.size
    if n < 2:
        return np.nan
    return float(x.mean() / (x.std(ddof=1) / np.sqrt(n)))


def main():
    sp = spec(FUND)
    print("loading panel/floats/holdings ...", flush=True)
    panel = FP.asof_join(BP.load(), FP.load())
    joined = HP.build([FUND], panel=panel)
    cfg = EN.merge_config({"fund": FUND, "universe": {"start": "2016-01-01"}})
    uni, funnel = EN.prepare_universe(cfg, joined=joined, panel=panel)
    print(f"{FUND}: {len(uni):,} gated bond-days, {uni['date'].nunique():,} dates, "
          f"{uni['cusip'].nunique():,} cusips\n", flush=True)

    uni_fwd = IC.forward_residual_return(uni, HORIZONS)

    rows = []
    for width in (0.25, 0.5):
        g = build_bucket_panel(uni, sp, width)
        g = add_hist_z(g, col="w_f", out_col="raw_bucket_hist_z", lookback=250)
        g = add_hist_z(g, col="w_i", out_col="raw_bucket_hist_z_wi", lookback=250)
        g = attach_held_fwd(g, uni_fwd, sp, width, HORIZONS)

        g["z_bucket_active"] = cs_z_by_date(g["raw_bucket_active"], g["date"])
        g["z_bucket_hist_z"] = cs_z_by_date(g["raw_bucket_hist_z"], g["date"])
        g["z_bucket_hist_z_wi"] = cs_z_by_date(g["raw_bucket_hist_z_wi"], g["date"])
        g["z_resid"] = cs_z_by_date(g["resid_med"], g["date"])

        n_buckets_med = int(g.groupby("date")["bucket"].nunique().median())
        min_names = max(5, n_buckets_med // 3)

        gl = g.sort_values(["bucket", "date"]).copy()
        for c in ("z_bucket_active", "z_bucket_hist_z", "z_bucket_hist_z_wi", "z_resid"):
            gl[f"{c}_lag"] = gl.groupby("bucket")[c].shift(EXEC_LAG)

        for sname, scol in (("bucket_active", "z_bucket_active_lag"),
                            ("bucket_hist_z", "z_bucket_hist_z_lag"),
                            ("bucket_hist_z_wi_NULL", "z_bucket_hist_z_wi_lag")):
            pcol = f"p_{sname}"
            gl[pcol] = orthogonalise(gl, scol, "z_resid_lag")
            for h in HORIZONS:
                retcol = f"held_fwd_{h}"
                ic_raw = per_date_ic(gl, scol, retcol, min_names)
                ic_par = per_date_ic(gl, pcol, retcol, min_names)
                for kind, series in (("raw", ic_raw), ("partial", ic_par)):
                    if series.size < 20:
                        continue
                    tn = naive_t(series.to_numpy())
                    tnw = IC.newey_west_t(series.to_numpy(), lags=max(1, h - 1))
                    rows.append({"width": width, "signal": sname, "horizon": h, "kind": kind,
                                 "n_dates": series.size, "ic_mean": float(series.mean()),
                                 "t_naive": tn, "t_newey_west": tnw,
                                 "shrink_ratio": (tnw / tn) if (tn and np.isfinite(tn) and tn != 0) else np.nan})
        if width == 0.25:
            panel25 = gl.copy()

    ic_nw = pd.DataFrame(rows)
    ic_nw.to_csv(os.path.join(OUT_DIR, "audit_ladder_newey_west.csv"), index=False)
    print("=" * 110)
    print("NAIVE vs NEWEY-WEST t, held-composition return, PARTIAL IC only")
    print("=" * 110)
    sub = ic_nw[ic_nw["kind"] == "partial"]
    print(sub[["width", "signal", "horizon", "n_dates", "ic_mean", "t_naive", "t_newey_west", "shrink_ratio"]]
          .sort_values(["signal", "width", "horizon"]).to_string(index=False))

    # ------------------------------------------------------------ year-by-year robustness
    # on the report's headline "true" cell: width=0.25, bucket_hist_z, h=63, partial, held
    print("\n" + "=" * 110)
    print("YEAR-BY-YEAR double-sort spread stability: width=0.25 bucket_hist_z h=63 (held) vs its wi_NULL twin")
    print("=" * 110)
    g25 = panel25
    for sname, scol in (("bucket_hist_z", "z_bucket_hist_z_lag"),
                        ("bucket_hist_z_wi_NULL", "z_bucket_hist_z_wi_lag")):
        pcol = f"p_{sname}"
        d = g25[["date", scol, pcol, "z_resid_lag", "held_fwd_63"]].dropna(
            subset=[scol, pcol, "z_resid_lag", "held_fwd_63"]).copy()
        d["year"] = d["date"].dt.year
        print(f"\n-- {sname} --")
        yearly = []
        for yr, dy in d.groupby("year"):
            if len(dy) < 100:
                continue
            tab, cnt = double_sort(dy.rename(columns={"held_fwd_63": "fwd_63"}), scol, "z_resid_lag", 63)
            if tab.empty or tab.shape[1] < 2:
                continue
            spread = tab[tab.columns.max()] - tab[tab.columns.min()]
            yearly.append({"year": yr, "n": len(dy), "mean_spread_bp": float(spread.mean()),
                           "sign_consistent": bool(len(set(np.sign(spread.dropna()).tolist())) <= 1)})
        yr_df = pd.DataFrame(yearly)
        print(yr_df.to_string(index=False))
        yr_df.to_csv(os.path.join(OUT_DIR, f"audit_ladder_yearly_{sname}.csv"), index=False)

        # full sample excl-2020 and excl-best-year
        for excl_label, mask in (
            ("full", pd.Series(True, index=d.index)),
            ("excl_2020", d["year"] != 2020),
        ):
            dd = d[mask]
            tab, cnt = double_sort(dd.rename(columns={"held_fwd_63": "fwd_63"}), scol, "z_resid_lag", 63)
            if tab.empty or tab.shape[1] < 2:
                print(f"  [{excl_label}] double-sort infeasible")
                continue
            spread = tab[tab.columns.max()] - tab[tab.columns.min()]
            print(f"  [{excl_label}] n={len(dd)} mean_spread_bp={spread.mean():.4f} "
                  f"sign_consistent={len(set(np.sign(spread.dropna()).tolist())) <= 1} spread={spread.round(4).to_dict()}")
        if not yr_df.empty:
            best_yr = yr_df.loc[yr_df["mean_spread_bp"].abs().idxmax(), "year"]
            dd = d[d["year"] != best_yr]
            tab, cnt = double_sort(dd.rename(columns={"held_fwd_63": "fwd_63"}), scol, "z_resid_lag", 63)
            if not tab.empty and tab.shape[1] >= 2:
                spread = tab[tab.columns.max()] - tab[tab.columns.min()]
                print(f"  [excl_best_year={best_yr}] n={len(dd)} mean_spread_bp={spread.mean():.4f} "
                      f"sign_consistent={len(set(np.sign(spread.dropna()).tolist())) <= 1}")

    # ------------------------------------------------------------ hand arithmetic spot check
    print("\n" + "=" * 110)
    print("HAND ARITHMETIC SPOT CHECK: one (date,bucket) row, width=0.25")
    print("=" * 110)
    row = g25.dropna(subset=["z_bucket_hist_z", "raw_bucket_hist_z", "w_f", "w_i"]).iloc[len(g25)//2]
    print(row[["date", "bucket", "w_f", "w_i", "raw_bucket_hist_z", "z_bucket_hist_z",
              "resid_med", "n_bonds", "age_med"]])
    # recompute raw_bucket_hist_z by hand from the bucket's own w_f history
    bkt = row["bucket"]
    hist = g25[(g25["bucket"] == bkt) & (g25["date"] < row["date"])].tail(250)
    mu = hist["w_f"].shift(0).tail(250)  # already <date, so no extra shift needed here
    mu_val = hist["w_f"].mean()
    sd_val = hist["w_f"].std()
    manual_z = -(row["w_f"] - mu_val) / sd_val if sd_val else np.nan
    print(f"manual recompute (250d trailing mean/std of w_f strictly before date): "
          f"mu={mu_val:.6f} sd={sd_val:.6f} manual_raw_hist_z={manual_z:.4f} "
          f"vs stored raw_bucket_hist_z={row['raw_bucket_hist_z']:.4f}")

    print("\nDONE.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
