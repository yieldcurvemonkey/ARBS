"""Robustness pass: is the pooled cross-curve ownership result a band/maturity-sector
artefact, or does it hold bond-by-bond within each band? Also adds band-fixed-effect
controls to the multivariate spec, and a symmetric SOMA denominator for the head-to-head
magnitude comparison.
"""

from __future__ import annotations

import os
import sys
import time

os.environ.setdefault("ARBS_SUPABASE_ENABLED", "0")
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..")))

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from RVUtils.ETFRebalance import bond_panel as BP  # noqa: E402
from RVUtils.ETFRebalance import ic as IC  # noqa: E402
from RVUtils.ETFRebalance import signals as SIG  # noqa: E402

pd.set_option("display.width", 240)
DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_data")


def fm_regress(df, y_col, x_cols, min_n=15):
    rows = []
    for dt, g in df.groupby("date", sort=False):
        cols = [y_col] + x_cols
        gg = g[cols].replace([np.inf, -np.inf], np.nan).dropna()
        if len(gg) < min_n:
            continue
        y = gg[y_col].to_numpy(float)
        X = np.column_stack([np.ones(len(gg))] + [gg[c].to_numpy(float) for c in x_cols])
        try:
            beta, *_ = np.linalg.lstsq(X, y, rcond=None)
        except np.linalg.LinAlgError:
            continue
        rows.append({"date": dt, "n": len(gg), **{f"b_{c}": beta[i + 1] for i, c in enumerate(x_cols)}})
    coefs = pd.DataFrame(rows)
    if coefs.empty:
        return pd.DataFrame()
    out = []
    for c in x_cols:
        v = coefs[f"b_{c}"].dropna().to_numpy(float)
        if v.size < 20:
            continue
        out.append({"x": c, "n_dates": v.size, "mean_beta": float(v.mean()),
                     "t_stat": float(v.mean() / (v.std(ddof=1) / np.sqrt(v.size)))})
    return pd.DataFrame(out)


def main():
    t0 = time.time()
    d = pd.read_parquet(os.path.join(DATA_DIR, "aggown_full_panel.parquet"))
    d["date"] = pd.to_datetime(d["date"])
    d["log_float"] = np.log(d["free_float"].clip(lower=1e6))
    d["otr"] = (d["rank"] == 0).astype(float)
    # symmetric SOMA denominator, for the head-to-head magnitude comparison only
    d["soma_share_tot"] = d["soma_share"]  # already /outstanding_amt (its natural denom)
    d["soma_share_ff_denom"] = (d["soma_holdings"].fillna(0.0) /
                                d["free_float"].replace(0.0, np.nan)).clip(lower=0.0)

    print("=" * 100)
    print("A. PER-BAND contemporaneous univariate: resid_bp ~ ownership_agg, run SEPARATELY "
          "within each band (removes any pure maturity-sector / which-band effect)")
    print("=" * 100)
    rows = []
    for f in ["SHY", "IEI", "IEF", "TLH", "TLT"]:
        sub = d[d["band_fund"] == f]
        tab = fm_regress(sub, "resid_bp", ["ownership_agg"])
        if tab.empty:
            continue
        r = tab.iloc[0]
        print(f"  {f}: beta={r['mean_beta']:.4f} bp/unit (={r['mean_beta']/100:+.5f} bp/1pp)  "
              f"t={r['t_stat']:.2f}  n_dates={r['n_dates']}  n_cusips={sub['cusip'].nunique()}")
        rows.append({"band": f, "beta_bp_per_unit": r["mean_beta"], "bp_per_1pp": r["mean_beta"] / 100,
                     "t_stat": r["t_stat"], "n_dates": r["n_dates"]})
    for f in ["SHY", "IEI", "IEF", "TLH", "TLT"]:
        sub = d[d["band_fund"] == f]
        tab = fm_regress(sub, "resid_bp", ["soma_share"])
        if tab.empty:
            continue
        r = tab.iloc[0]
        print(f"  {f} [SOMA]: beta={r['mean_beta']:.4f} bp/unit (={r['mean_beta']/100:+.5f} bp/1pp)  "
              f"t={r['t_stat']:.2f}  n_dates={r['n_dates']}")
        rows.append({"band": f, "signal": "soma_share", "beta_bp_per_unit": r["mean_beta"],
                     "bp_per_1pp": r["mean_beta"] / 100, "t_stat": r["t_stat"], "n_dates": r["n_dates"]})
    pd.DataFrame(rows).to_csv(os.path.join(DATA_DIR, "aggown_per_band_fm.csv"), index=False)

    print("\n" + "=" * 100)
    print("B. POOLED multivariate WITH band fixed effects (dummies for SHY/IEI/IEF/TLH, TLT baseline)")
    print("=" * 100)
    for b in ["SHY", "IEI", "IEF", "TLH"]:
        d[f"band_{b}"] = (d["band_fund"] == b).astype(float)
    band_dummies = [f"band_{b}" for b in ["SHY", "IEI", "IEF", "TLH"]]
    band_fx_rows = []
    for sig in ["ownership_agg", "soma_share"]:
        tab = fm_regress(d, "resid_bp", [sig, "log_float", "age", "rank", "otr"] + band_dummies)
        print(f"\n{sig} + controls + band dummies -> resid_bp:")
        print(tab.round(5).to_string(index=False))
        tab = tab.copy(); tab["signal"] = sig
        band_fx_rows.append(tab)
    pd.concat(band_fx_rows, ignore_index=True).to_csv(
        os.path.join(DATA_DIR, "aggown_band_fixed_effects.csv"), index=False)

    print("\n" + "=" * 100)
    print("C. Symmetric SOMA denominator check (soma/free_float vs soma/outstanding_amt) "
          "-- does the denominator choice drive the SOMA result?")
    print("=" * 100)
    denom_rows = []
    for sig in ["soma_share_tot", "soma_share_ff_denom"]:
        tab = fm_regress(d, "resid_bp", [sig, "log_float", "age", "rank", "otr"])
        r = tab[tab["x"] == sig].iloc[0]
        print(f"  {sig}: beta={r['mean_beta']:.4f} bp/unit (={r['mean_beta']/100:+.5f} bp/1pp)  t={r['t_stat']:.2f}")
        denom_rows.append({"signal": sig, "beta_bp_per_unit": r["mean_beta"],
                           "bp_per_1pp": r["mean_beta"] / 100, "t_stat": r["t_stat"]})
    pd.DataFrame(denom_rows).to_csv(os.path.join(DATA_DIR, "aggown_soma_denom_check.csv"), index=False)

    # ------------------------------------------------------------------------------
    print("\n" + "=" * 100)
    print("D. JOINT regression -- ownership_agg and soma_share together. free_float = "
          "outstanding - soma_holdings, so ownership_agg = par/(outstanding*(1-soma_share)) "
          "RISES mechanically with soma_share. This is the clean head-to-head.")
    print("=" * 100)
    d["agg_par_over_outstanding"] = (d["agg_par"] / d["outstanding_amt"].replace(0.0, np.nan)).clip(lower=0.0)
    joint = fm_regress(d, "resid_bp",
                       ["ownership_agg", "soma_share", "log_float", "age", "rank", "otr"] + band_dummies)
    print(joint.round(5).to_string(index=False))
    joint2 = fm_regress(d, "resid_bp",
                        ["agg_par_over_outstanding", "soma_share", "log_float", "age", "rank", "otr"] + band_dummies)
    print("\n(ETF ownership scaled by TOTAL outstanding instead of free float, same joint spec):")
    print(joint2.round(5).to_string(index=False))
    joint["variant"] = "ownership_agg(/free_float)"
    joint2["variant"] = "agg_par_over_outstanding"
    pd.concat([joint, joint2], ignore_index=True).to_csv(
        os.path.join(DATA_DIR, "aggown_joint_regression.csv"), index=False)

    # ------------------------------------------------------------------------------
    print("\n" + "=" * 100)
    print("E. PER-YEAR stability -- mean beta and sign, one Fama-MacBeth regression run "
          "PER YEAR, for (a) ETF contemporaneous, (b) SOMA contemporaneous, (c) SOMA "
          "predictive @63d. Guards against a single regime (e.g. 2020-21 QE) driving the result.")
    print("=" * 100)
    d["year"] = d["date"].dt.year
    py_rows = []
    for yr, g in d.groupby("year"):
        for sig in ["ownership_agg", "soma_share"]:
            tab = fm_regress(g, "resid_bp", [sig])
            if tab.empty:
                continue
            r = tab.iloc[0]
            py_rows.append({"year": yr, "test": f"{sig}_contemporaneous_univariate",
                            "bp_per_1pp": r["mean_beta"] / 100, "t_stat": r["t_stat"], "n_dates": r["n_dates"]})
            tabm = fm_regress(g, "resid_bp", [sig, "log_float", "age", "rank", "otr"])
            if tabm.empty:
                continue
            rm = tabm[tabm["x"] == sig].iloc[0]
            py_rows.append({"year": yr, "test": f"{sig}_contemporaneous_multivariate",
                            "bp_per_1pp": rm["mean_beta"] / 100, "t_stat": rm["t_stat"], "n_dates": rm["n_dates"]})
    py = pd.DataFrame(py_rows)
    print(py.pivot_table(index="year", columns="test", values="bp_per_1pp").round(5).to_string())
    print("\nsign count by year (contemporaneous):")
    print(py.assign(sign=lambda x: np.sign(x["bp_per_1pp"])).pivot_table(
        index="test", columns="sign", aggfunc="size", fill_value=0).to_string())
    py.to_csv(os.path.join(DATA_DIR, "aggown_per_year_contemporaneous.csv"), index=False)

    # predictive @63d, per year, using the already-lagged fwd/resid columns is not
    # available here (this script reads the raw panel) -- rebuild fwd_63 and the
    # exec_lag shift locally, restricted to soma_share, to check the ONE surviving
    # predictive result for regime concentration.
    dd = d.sort_values(["cusip", "date"]).copy()
    dd["fwd_63"] = -(dd.groupby("cusip")["resid_bp"].shift(-63) - dd["resid_bp"])
    dd["soma_share_lag1"] = dd.groupby("cusip")["soma_share"].shift(1)
    dd["resid_bp_lag1"] = dd.groupby("cusip")["resid_bp"].shift(1)
    py2_rows = []
    for yr, g in dd.groupby("year"):
        uni = fm_regress(g, "fwd_63", ["soma_share_lag1"])
        multi = fm_regress(g, "fwd_63", ["soma_share_lag1", "resid_bp_lag1", "log_float", "age", "rank", "otr"])
        if not uni.empty:
            r = uni.iloc[0]
            py2_rows.append({"year": yr, "spec": "univariate", "bp_per_1pp_per_63d": r["mean_beta"] / 100,
                             "t_stat": r["t_stat"], "n_dates": r["n_dates"]})
        if not multi.empty:
            r = multi[multi["x"] == "soma_share_lag1"].iloc[0]
            py2_rows.append({"year": yr, "spec": "multivariate", "bp_per_1pp_per_63d": r["mean_beta"] / 100,
                             "t_stat": r["t_stat"], "n_dates": r["n_dates"]})
    py2 = pd.DataFrame(py2_rows)
    print("\nSOMA PREDICTIVE @63d, per year:")
    print(py2.pivot_table(index="year", columns="spec", values=["bp_per_1pp_per_63d", "t_stat"]).round(5).to_string())
    py2.to_csv(os.path.join(DATA_DIR, "aggown_per_year_soma_predictive_63d.csv"), index=False)

    # ------------------------------------------------------------------------------
    print("\n" + "=" * 100)
    print("F. DEGENERATE-REGRESSOR FLAG -- soma_share_chg_21: the float panel is sampled "
          "MONTHLY, so a 21-business-day diff of a mostly-forward-filled series is exactly "
          "zero for most (date,cusip) rows most of the time. Betas of order 1e5-1e6 bp/unit "
          "in the main battery's FM predictive table (soma_share_chg_21 rows) are NOT a real "
          "coefficient estimate -- they are 1/(near-zero variance). Reported informationally, "
          "not as a finding.")
    print("=" * 100)
    nz = (d["soma_share_chg_21"].fillna(0.0) != 0.0).mean()
    print(f"  soma_share_chg_21 nonzero on {nz*100:.2f}% of bond-days -- confirms near-zero "
          f"cross-sectional variance most days; DISCARD any FM beta on this column.")

    print(f"\nruntime {time.time()-t0:.0f}s")


if __name__ == "__main__":
    main()
