"""The constant-maturity BUCKET LADDER: the literal form of the original idea.

Per-CUSIP active weight (RVUtils/ETFRebalance/_run_partial_ic.py) showed a raw IC that
flips sign and collapses to ~0.012 partial IC (t=+3.8 @ 63d) once orthogonalised against
the bond's own richness residual (z_resid). The stated hope of the BUCKET version is
that aggregating removes substitution noise -- a sampling fund holding one of two bonds
three months apart is noise at the CUSIP level and signal at the maturity-slot level.
This script tests that, honestly, against the same control and the same cost hurdle.

Two signals, two different claims
----------------------------------
``bucket_active``: the bucket's fund weight vs the bucket's INDEX weight. Benchmark-
relative, so a bucket that is small because the Treasury stopped issuing into it is not
scored as underweight.

``bucket_hist_z``: the bucket's fund weight vs ITS OWN trailing history. The literal,
original formulation -- and the one the code says is confounded by issuance and roll-
down. Directly tested here (Part 3) by regressing it on bucket age and the bucket's own
index-weight level/trend.
"""

from __future__ import annotations

import argparse
import os
import sys

os.environ.setdefault("ARBS_SUPABASE_ENABLED", "0")
os.environ.setdefault("ARBS_ETF_HOLDINGS_DIR",
                       "C:/Users/chris/clee/ARBS/MDP/ETFHoldings/etf_holdings_cache")
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

pd.set_option("display.width", 240)

HORIZONS = (5, 10, 21, 42, 63)
WIDTHS = (0.25, 0.5, 1.0)
OUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..",
                        "notebooks", "backtests", "etf_rebalance", "_data")
os.makedirs(OUT_DIR, exist_ok=True)


# ============================================================== bucket panel builder


def build_bucket_panel(uni: pd.DataFrame, sp, width_y: float) -> pd.DataFrame:
    """One row per (date, bucket): fund/index weights, resid (median across CUSIPs in
    the bucket), n_bonds, median age -- the object every bucket signal and control is
    built from.
    """
    d = uni.copy()
    d["bucket"] = HP.bucket_index(d["ttm"], sp, width_y=width_y).astype(float)
    d = d[d["bucket"].notna()].copy()
    d["bucket"] = d["bucket"].astype(int)

    g = d.groupby(["date", "bucket"], as_index=False).agg(
        w_f=("w_f", "sum"), w_i=("w_i", "sum"),
        resid_med=("resid_bp", "median"), resid_mean=("resid_bp", "mean"),
        n_bonds=("cusip", "nunique"), age_med=("age", "median"),
        ttm_mid=("ttm", "median"), par=("par", "sum"), idx_dv01=("idx_dv01", "sum"),
    )
    g["active_w"] = g["w_f"] - g["w_i"]
    g["raw_bucket_active"] = -g["active_w"]
    return g.sort_values(["bucket", "date"]).reset_index(drop=True)


def add_hist_z(g: pd.DataFrame, *, col: str = "w_f", out_col: str = "raw_bucket_hist_z",
               lookback: int = 250) -> pd.DataFrame:
    """Bucket's own trailing z of ``col`` -- strictly backward-looking.

    ``col="w_f"`` is the literal original idea (the fund's own weight vs its own
    history). ``col="w_i"`` is the CALENDAR-ONLY null of that idea: the bucket's INDEX
    weight vs its own history needs no holdings file at all, and a tracker's w_f follows
    w_i mechanically, so if hist_z(w_i) earns what hist_z(w_f) earns, the scrape bought
    nothing.
    """
    g = g.sort_values(["bucket", "date"]).copy()
    mp = max(20, lookback // 4)
    prior = g.groupby("bucket")[col].shift(1)
    mu = prior.groupby(g["bucket"]).transform(
        lambda x: x.rolling(lookback, min_periods=mp).mean())
    sd = prior.groupby(g["bucket"]).transform(
        lambda x: x.rolling(lookback, min_periods=mp).std())
    z = (g[col] - mu) / sd.replace(0.0, np.nan)
    g[out_col] = -z
    return g


def add_fwd(g: pd.DataFrame, horizons, *, resid_col: str = "resid_med") -> pd.DataFrame:
    g = g.sort_values(["bucket", "date"]).copy()
    gb = g.groupby("bucket")[resid_col]
    for h in horizons:
        g[f"fwd_{h}"] = -(gb.shift(-h) - g[resid_col])
    return g


def cs_z_by_date(s: pd.Series, dates: pd.Series) -> pd.Series:
    return SIG.cross_sectional_z(s, dates, robust=True).clip(-5, 5)


def orthogonalise(df: pd.DataFrame, target: str, control: str) -> pd.Series:
    out = pd.Series(np.nan, index=df.index)
    for _, g in df.groupby("date", sort=False):
        x = g[control].to_numpy(float)
        y = g[target].to_numpy(float)
        ok = np.isfinite(x) & np.isfinite(y)
        if ok.sum() < 6:
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


def ic_across_dates(d: pd.DataFrame, sig_col: str, ret_col: str, *, min_names: int) -> dict:
    per = []
    for _, g in d.groupby("date", sort=False):
        gg = g.dropna(subset=[sig_col, ret_col])
        if len(gg) < min_names:
            continue
        per.append(IC._spearman(gg[sig_col].to_numpy(float), gg[ret_col].to_numpy(float)))
    v = np.array([x for x in per if np.isfinite(x)], float)
    if v.size < 20:
        return {}
    return {"ic": float(v.mean()), "t": float(v.mean() / (v.std(ddof=1) / np.sqrt(v.size))),
            "n_dates": int(v.size), "hit": float((v > 0).mean())}


def bivariate(d: pd.DataFrame, sig: str, ctrl: str, h: int, *, min_names: int) -> dict:
    b_sig, b_ctl = [], []
    for _, g in d.groupby("date", sort=False):
        y = g[f"fwd_{h}"].to_numpy(float)
        X = np.column_stack([g[sig].to_numpy(float), g[ctrl].to_numpy(float)])
        ok = np.isfinite(y) & np.isfinite(X).all(axis=1)
        if ok.sum() < min_names:
            continue
        A = np.column_stack([np.ones(ok.sum()), X[ok]])
        try:
            beta, *_ = np.linalg.lstsq(A, y[ok], rcond=None)
        except np.linalg.LinAlgError:
            continue
        b_sig.append(beta[1])
        b_ctl.append(beta[2])
    b_sig, b_ctl = np.array(b_sig), np.array(b_ctl)
    if b_sig.size < 20:
        return {}
    return {"n_dates": int(b_sig.size), "beta_signal_bp": float(b_sig.mean()),
            "t_signal": float(b_sig.mean() / (b_sig.std(ddof=1) / np.sqrt(b_sig.size))),
            "beta_resid_bp": float(b_ctl.mean()),
            "t_resid": float(b_ctl.mean() / (b_ctl.std(ddof=1) / np.sqrt(b_ctl.size)))}


def double_sort(d: pd.DataFrame, sig_z: str, ctrl_z: str, h: int, *, n_r: int = 5, n_s: int = 3) -> pd.DataFrame:
    g = d.dropna(subset=[sig_z, ctrl_z, f"fwd_{h}"]).copy()
    if g.empty:
        return pd.DataFrame(), pd.DataFrame()
    g["qr"] = g.groupby("date")[ctrl_z].transform(
        lambda x: pd.qcut(x.rank(method="first"), n_r, labels=False, duplicates="drop")
        if x.notna().sum() >= n_r else np.nan)
    g["qs"] = g.groupby(["date", "qr"])[sig_z].transform(
        lambda x: pd.qcut(x.rank(method="first"), n_s, labels=False, duplicates="drop")
        if x.notna().sum() >= n_s else np.nan)
    tab = g.pivot_table(index="qr", columns="qs", values=f"fwd_{h}", aggfunc="mean")
    cnt = g.pivot_table(index="qr", columns="qs", values=f"fwd_{h}", aggfunc="size")
    return tab, cnt


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--fund", default="TLT")
    ap.add_argument("--start", default="2016-01-01")
    ap.add_argument("--exec-lag", type=int, default=1)
    ap.add_argument("--lag0", action="store_true", help="also run exec_lag=0 diagnostic")
    a = ap.parse_args()

    sp = spec(a.fund)
    print(f"loading panel/floats/holdings for {a.fund} ...", flush=True)
    panel = FP.asof_join(BP.load(), FP.load())
    joined = HP.build([a.fund], panel=panel)
    cfg = EN.merge_config({"fund": a.fund, "universe": {"start": a.start}})
    uni, funnel = EN.prepare_universe(cfg, joined=joined, panel=panel)
    print(f"{a.fund}: {len(uni):,} gated bond-days, {uni['date'].nunique():,} dates, "
          f"{uni['cusip'].nunique():,} cusips\n", flush=True)

    all_ic_rows = []
    all_biv_rows = []
    panels = {}

    for width in WIDTHS:
        g = build_bucket_panel(uni, sp, width)
        g = add_hist_z(g, lookback=250)
        g = add_fwd(g, HORIZONS, resid_col="resid_med")

        # cross-sectional standardisation across buckets, per date
        g["z_bucket_active"] = cs_z_by_date(g["raw_bucket_active"], g["date"])
        g["z_bucket_hist_z"] = cs_z_by_date(g["raw_bucket_hist_z"], g["date"])
        g["z_resid"] = cs_z_by_date(g["resid_med"], g["date"])

        n_buckets_med = int(g.groupby("date")["bucket"].nunique().median())
        min_names = max(5, n_buckets_med // 3)
        print(f"width={width}y: {len(g):,} bucket-days, median {n_buckets_med} buckets/date, "
              f"min_names={min_names}", flush=True)

        # exec_lag shift of the SIGNAL columns (not the control used only for orthog.
        # inside the *same* date -- orthogonalisation is contemporaneous by construction,
        # then the whole partial series is what gets lagged before meeting fwd_h)
        gl = g.sort_values(["bucket", "date"]).copy()
        for lag, tag in ([(a.exec_lag, "lag")] + ([(0, "lag0")] if a.lag0 else [])):
            dd = gl.copy()
            for c in ("z_bucket_active", "z_bucket_hist_z", "z_resid"):
                dd[f"{c}_{tag}"] = dd.groupby("bucket")[c].shift(lag) if lag else dd[c]

            # partial = orthogonalise the (already lagged) signal against the
            # (already lagged) control, date by date -- both on the same causal footing
            for sname, scol in (("bucket_active", f"z_bucket_active_{tag}"),
                                 ("bucket_hist_z", f"z_bucket_hist_z_{tag}")):
                pcol = f"p_{sname}_{tag}"
                dd[pcol] = orthogonalise(dd, scol, f"z_resid_{tag}")
                for h in HORIZONS:
                    for kind, use in (("raw", scol), ("partial", pcol)):
                        r = ic_across_dates(dd, use, f"fwd_{h}", min_names=min_names)
                        if r:
                            all_ic_rows.append({"width": width, "signal": sname,
                                                 "exec_lag": lag, "horizon": h, "kind": kind, **r})
                    bv = bivariate(dd, scol, f"z_resid_{tag}", h, min_names=min_names)
                    if bv and lag == a.exec_lag:
                        all_biv_rows.append({"width": width, "signal": sname, "horizon": h, **bv})

        panels[width] = g

    ic_df = pd.DataFrame(all_ic_rows)
    biv_df = pd.DataFrame(all_biv_rows)
    ic_df.to_csv(os.path.join(OUT_DIR, "ladder_ic.csv"), index=False)
    biv_df.to_csv(os.path.join(OUT_DIR, "ladder_bivariate.csv"), index=False)

    print("\n" + "=" * 110)
    print(f"1. IC BY WIDTH x SIGNAL x HORIZON  (exec_lag={a.exec_lag})")
    print("=" * 110)
    main_ic = ic_df[ic_df["exec_lag"] == a.exec_lag]
    for kind in ("raw", "partial"):
        print(f"\n--- {kind} IC ---")
        piv = main_ic[main_ic["kind"] == kind].pivot_table(
            index=["width", "signal"], columns="horizon", values="ic").round(4)
        print(piv.to_string())
        pivt = main_ic[main_ic["kind"] == kind].pivot_table(
            index=["width", "signal"], columns="horizon", values="t").round(2)
        print("t:")
        print(pivt.to_string())

    if a.lag0:
        print("\n--- LAG-0 DIAGNOSTIC (not tradeable; reads tomorrow's file) ---")
        lag0 = ic_df[(ic_df["exec_lag"] == 0) & (ic_df["kind"] == "partial")]
        print(lag0.pivot_table(index=["width", "signal"], columns="horizon", values="t").round(2).to_string())

    print("\n" + "=" * 110)
    print("BIVARIATE (bp forward richening per unit z, signal AND resid together)")
    print("=" * 110)
    print(biv_df.round(4).to_string(index=False))

    # ---------------------------------------------------------------- double sort
    print("\n" + "=" * 110)
    print("2. DOUBLE SORT for cells with |t_partial| > 3 or |t_raw| > 3")
    print("=" * 110)
    ds_summ = []
    flag = main_ic[(main_ic["t"].abs() > 3)]
    checked = set()
    for _, row in flag.iterrows():
        key = (row["width"], row["signal"], row["horizon"])
        if key in checked:
            continue
        checked.add(key)
        width, sname, h = row["width"], row["signal"], int(row["horizon"])
        g = panels[width]
        gl = g.sort_values(["bucket", "date"]).copy()
        scol = f"z_{sname}"
        gl[f"{scol}_lag"] = gl.groupby("bucket")[scol].shift(a.exec_lag)
        gl["z_resid_lag"] = gl.groupby("bucket")["z_resid"].shift(a.exec_lag)
        tab, cnt = double_sort(gl, f"{scol}_lag", "z_resid_lag", h)
        if tab.empty:
            continue
        spread = (tab[tab.columns.max()] - tab[tab.columns.min()]) if tab.shape[1] >= 2 else pd.Series(dtype=float)
        print(f"\nwidth={width} signal={sname} h={h}d  (rows=resid quintile 0=rich..N=cheap, "
              f"cols=signal tercile 0=low..2=high), bp:")
        print(tab.round(4).to_string())
        print(f"n per cell (min {int(np.nanmin(cnt.to_numpy(float))):,}):")
        print(f"high-minus-low signal within each resid quintile: {spread.round(4).to_dict()}")
        monotone = bool(np.all(np.diff(spread.dropna().to_numpy()) >= -1e-9) or
                        np.all(np.diff(spread.dropna().to_numpy()) <= 1e-9))
        signs = np.sign(spread.dropna().to_numpy())
        sign_consistent = bool(len(set(signs.tolist())) <= 1) if len(signs) else False
        ds_summ.append({"width": width, "signal": sname, "horizon": h,
                         "linear_t": row["t"], "linear_ic": row["ic"],
                         "spread_sign_consistent_across_quintiles": sign_consistent,
                         "spread_values": spread.round(4).to_dict()})
    pd.DataFrame(ds_summ).to_csv(os.path.join(OUT_DIR, "ladder_double_sort.csv"), index=False)
    if not ds_summ:
        print("No cell exceeded |t|>3 in either raw or partial IC -- nothing to confirm.")

    # ---------------------------------------------------------------- part 3: hist_z mechanics
    print("\n" + "=" * 110)
    print("3. bucket_hist_z MECHANICS: how much is age / issuance, not dislocation?")
    print("=" * 110)
    mech_rows = []
    for width in WIDTHS:
        g = panels[width].copy()
        g["d_wi_250"] = g.groupby("bucket")["w_i"].diff(250)
        gg = g.dropna(subset=["raw_bucket_hist_z", "age_med", "w_i", "d_wi_250"])
        if len(gg) < 100:
            continue
        y = gg["raw_bucket_hist_z"].to_numpy(float)
        X = np.column_stack([gg["age_med"].to_numpy(float), gg["w_i"].to_numpy(float),
                              gg["d_wi_250"].to_numpy(float)])
        A = np.column_stack([np.ones(len(y)), X])
        beta, *_ = np.linalg.lstsq(A, y, rcond=None)
        fitted = A @ beta
        ss_res = float(np.sum((y - fitted) ** 2))
        ss_tot = float(np.sum((y - y.mean()) ** 2))
        r2 = 1 - ss_res / ss_tot if ss_tot > 0 else np.nan
        corr_age = float(np.corrcoef(y, gg["age_med"])[0, 1])
        corr_wi = float(np.corrcoef(y, gg["w_i"])[0, 1])
        corr_dwi = float(np.corrcoef(y, gg["d_wi_250"])[0, 1])
        row = {"width": width, "n_obs": len(y), "r2_age_wi_dwi": r2,
               "beta_age": beta[1], "beta_wi_level": beta[2], "beta_d_wi_250": beta[3],
               "corr_age": corr_age, "corr_wi_level": corr_wi, "corr_d_wi_250": corr_dwi}
        mech_rows.append(row)
        print(f"width={width}: R^2(hist_z ~ age_med + w_i level + d_wi_250) = {r2:.3f}  "
              f"n={len(y):,}  corr(age)={corr_age:.3f} corr(w_i)={corr_wi:.3f} corr(d_wi_250)={corr_dwi:.3f}")
    pd.DataFrame(mech_rows).to_csv(os.path.join(OUT_DIR, "ladder_hist_z_mechanics.csv"), index=False)

    # ---------------------------------------------------------------- part 5: flow-day conditioning
    print("\n" + "=" * 110)
    print("5. CONDITIONED ON A REBALANCE ACTUALLY HAPPENING (material total-par change day)")
    print("=" * 110)
    flow_rows = []
    flows = HP.flag_flow_days(joined[joined["ticker"] == a.fund], threshold=0.02)
    flows["d_par"] = flows.groupby("ticker")["fund_par"].diff()
    flows["par_pct"] = flows["d_par"] / flows.groupby("ticker")["fund_par"].shift()
    flow_dates = set(flows.loc[flows["par_pct"].abs() >= 0.01, "date"])
    print(f"flagged {len(flow_dates)} of {flows['date'].nunique()} dates as material "
          f"total-par change (>=1% day/day)")
    for width in WIDTHS:
        g = panels[width].copy()
        gl = g.sort_values(["bucket", "date"]).copy()
        for c in ("z_bucket_active", "z_bucket_hist_z", "z_resid"):
            gl[f"{c}_lag"] = gl.groupby("bucket")[c].shift(a.exec_lag)
        gl_flow = gl[gl["date"].isin(flow_dates)]
        n_buckets_med = int(g.groupby("date")["bucket"].nunique().median())
        min_names = max(5, n_buckets_med // 3)
        for sname, scol in (("bucket_active", "z_bucket_active_lag"), ("bucket_hist_z", "z_bucket_hist_z_lag")):
            pcol = orthogonalise(gl_flow.assign(**{scol: gl_flow[scol]}), scol, "z_resid_lag")
            gl_flow2 = gl_flow.copy()
            gl_flow2["_p"] = pcol
            for h in HORIZONS:
                r_raw = ic_across_dates(gl_flow, scol, f"fwd_{h}", min_names=max(5, min_names // 2))
                r_p = ic_across_dates(gl_flow2, "_p", f"fwd_{h}", min_names=max(5, min_names // 2))
                if r_raw or r_p:
                    flow_rows.append({"width": width, "signal": sname, "horizon": h,
                                       "n_flow_dates": len(flow_dates),
                                       "ic_raw": r_raw.get("ic"), "t_raw": r_raw.get("t"),
                                       "n_obs_raw": r_raw.get("n_dates"),
                                       "ic_partial": r_p.get("ic"), "t_partial": r_p.get("t"),
                                       "n_obs_partial": r_p.get("n_dates")})
    flow_df = pd.DataFrame(flow_rows)
    flow_df.to_csv(os.path.join(OUT_DIR, "ladder_flow_conditioned.csv"), index=False)
    print(flow_df.round(4).to_string(index=False) if not flow_df.empty else "no flow-conditioned rows")

    print("\nDONE.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
