"""Battery of tests on the aggregate ETF-ownership (scarcity) panel built by
``_run_aggregate_ownership.py``: IC (raw + partial vs resid), bivariate regression,
double sort, Fama-MacBeth multivariate regression with mechanical controls, and the
SOMA (Fed) benchmark for the same battery.
"""

from __future__ import annotations

import argparse
import os
import sys
import time

os.environ.setdefault("ARBS_SUPABASE_ENABLED", "0")
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..")))

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from RVUtils.ETFRebalance import bond_panel as BP  # noqa: E402
from RVUtils.ETFRebalance import curve as CV  # noqa: E402
from RVUtils.ETFRebalance import ic as IC  # noqa: E402
from RVUtils.ETFRebalance import signals as SIG  # noqa: E402

pd.set_option("display.width", 240)
pd.set_option("display.max_columns", 30)

DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_data")
HORIZONS = (5, 10, 21, 42, 63)
LEVEL_SIGNALS = ["ownership_agg", "soma_share"]
CHANGE_SIGNALS = ["ownership_agg_chg_21", "ownership_agg_chg_63", "soma_share_chg_21"]
ALL_SIGNALS = LEVEL_SIGNALS + CHANGE_SIGNALS


def orthogonalise(df: pd.DataFrame, target: str, control: str) -> pd.Series:
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


def bivariate(df: pd.DataFrame, sig: str, ctrl: str, h: int) -> dict:
    b_sig, b_ctl = [], []
    for _, g in df.groupby("date", sort=False):
        y = g[f"fwd_{h}"].to_numpy(float)
        X = np.column_stack([g[sig].to_numpy(float), g[ctrl].to_numpy(float)])
        ok = np.isfinite(y) & np.isfinite(X).all(axis=1)
        if ok.sum() < 10:
            continue
        A = np.column_stack([np.ones(ok.sum()), X[ok]])
        try:
            beta, *_ = np.linalg.lstsq(A, y[ok], rcond=None)
        except np.linalg.LinAlgError:
            continue
        b_sig.append(beta[1]); b_ctl.append(beta[2])
    b_sig, b_ctl = np.array(b_sig), np.array(b_ctl)
    if b_sig.size < 20:
        return {}
    return {"signal": sig, "horizon": h, "n_dates": b_sig.size,
            "beta_signal_bp": float(b_sig.mean()),
            "t_signal": float(b_sig.mean() / (b_sig.std(ddof=1) / np.sqrt(b_sig.size))),
            "beta_resid_bp": float(b_ctl.mean()),
            "t_resid": float(b_ctl.mean() / (b_ctl.std(ddof=1) / np.sqrt(b_ctl.size)))}


def fm_regress(df: pd.DataFrame, y_col: str, x_cols: list[str], *, min_n: int = 15):
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
        return pd.DataFrame(), coefs
    out = []
    for c in x_cols:
        v = coefs[f"b_{c}"].dropna().to_numpy(float)
        if v.size < 20:
            continue
        out.append({"x": c, "n_dates": v.size, "mean_beta": float(v.mean()),
                     "se": float(v.std(ddof=1) / np.sqrt(v.size)),
                     "t_stat": float(v.mean() / (v.std(ddof=1) / np.sqrt(v.size)))})
    return pd.DataFrame(out), coefs


def double_sort(df: pd.DataFrame, sig: str, h: int, *, n_ctrl: int = 5, n_sig: int = 3) -> pd.DataFrame:
    g = df.dropna(subset=[f"z_{sig}", "z_resid", f"fwd_{h}"]).copy()
    if g.empty:
        return pd.DataFrame()
    g["qr"] = g.groupby("date")["z_resid"].transform(
        lambda x: pd.qcut(x.rank(method="first"), n_ctrl, labels=False, duplicates="drop"))
    g["qs"] = g.groupby(["date", "qr"])[f"z_{sig}"].transform(
        lambda x: pd.qcut(x.rank(method="first"), n_sig, labels=False, duplicates="drop"))
    tab = g.pivot_table(index="qr", columns="qs", values=f"fwd_{h}", aggfunc="mean")
    cnt = g.pivot_table(index="qr", columns="qs", values=f"fwd_{h}", aggfunc="size")
    return tab, cnt


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--exec-lag", type=int, default=1)
    ap.add_argument("--prefix", default="aggown")
    a = ap.parse_args()
    t0 = time.time()

    d = pd.read_parquet(os.path.join(DATA_DIR, f"{a.prefix}_full_panel.parquet"))
    d["date"] = pd.to_datetime(d["date"])
    print(f"loaded {len(d):,} rows, {d['date'].nunique():,} dates, {d['cusip'].nunique():,} cusips")

    print("\n" + "=" * 100)
    print("0. RESIDUAL QC -- does the per-band local fit reproduce the known baseline "
          "(sd~1.1bp, autocorr~0.958, half-life~17d on the TLT band)?")
    print("=" * 100)
    for f in ["SHY", "IEI", "IEF", "TLH", "TLT"]:
        rq = CV.residual_quality(d[d["band_fund"] == f])
        hl = CV.half_life_days(d[d["band_fund"] == f])
        print(f"  {f}: median sd_bp={rq['sd_bp'].median():.3f}  "
              f"median autocorr_1={rq['autocorr_1'].median():.3f}  "
              f"median half_life={hl.replace([np.inf], np.nan).median():.1f}d  "
              f"n_cusips={len(rq)}")

    # --- standardise -----------------------------------------------------------------
    d["z_resid"] = SIG.cross_sectional_z(d["resid_bp"], d["date"], robust=True).clip(-5, 5)
    for c in ALL_SIGNALS:
        d[f"z_{c}"] = SIG.cross_sectional_z(d[c], d["date"], robust=True).clip(-5, 5)
    d["z_log_float"] = SIG.cross_sectional_z(d["log_float"], d["date"], robust=True).clip(-5, 5)
    d["z_age"] = SIG.cross_sectional_z(d["age"], d["date"], robust=True).clip(-5, 5)
    d["z_rank"] = SIG.cross_sectional_z(d["rank"].astype(float), d["date"], robust=True).clip(-5, 5)

    d = IC.forward_residual_return(d, HORIZONS, resid_col="resid_bp")
    zcols = [f"z_{c}" for c in ALL_SIGNALS] + ["z_resid", "z_log_float", "z_age", "z_rank"]
    rawcols = ALL_SIGNALS + ["log_float", "age", "rank", "otr", "resid_bp"]
    if a.exec_lag:
        d = d.sort_values(["cusip", "date"])
        for c in zcols + rawcols:
            d[c] = d.groupby("cusip")[c].shift(a.exec_lag)

    print("\n" + "=" * 100)
    print(f"1. RAW vs PARTIAL IC (partial = orthogonalised vs z_resid), exec_lag={a.exec_lag}")
    print("=" * 100)
    rows = []
    for c in ALL_SIGNALS:
        col, pcol = f"z_{c}", f"p_{c}"
        d[pcol] = orthogonalise(d, col, "z_resid")
        for h in HORIZONS:
            for lbl, use in (("raw", col), ("partial", pcol)):
                per = []
                for _, g in d.groupby("date", sort=False):
                    if len(g) < 8:
                        continue
                    per.append(IC._spearman(g[use].to_numpy(float), g[f"fwd_{h}"].to_numpy(float)))
                v = np.array([x for x in per if np.isfinite(x)], float)
                if v.size < 20:
                    continue
                rows.append({"signal": c, "kind": lbl, "horizon": h,
                             "ic": float(v.mean()),
                             "t": float(v.mean() / (v.std(ddof=1) / np.sqrt(v.size))),
                             "n_dates": v.size})
    ic = pd.DataFrame(rows)
    print("\nIC:")
    print(ic.pivot_table(index=["signal", "kind"], columns="horizon", values="ic").round(4).to_string())
    print("\nt across dates:")
    print(ic.pivot_table(index=["signal", "kind"], columns="horizon", values="t").round(2).to_string())
    ic.to_csv(os.path.join(DATA_DIR, f"{a.prefix}_ic.csv"), index=False)

    print("\n" + "=" * 100)
    print("2. LAG-0 DIAGNOSTIC (mislabelled, informational only -- reads tomorrow's file)")
    print("=" * 100)
    d0 = d.copy()  # reuse frame but recompute unlagged z for comparison at h=21
    d0["date"] = pd.to_datetime(d0["date"])  # no-op, keep dtype
    du = pd.read_parquet(os.path.join(DATA_DIR, f"{a.prefix}_full_panel.parquet"))
    du["date"] = pd.to_datetime(du["date"])
    du["z_resid"] = SIG.cross_sectional_z(du["resid_bp"], du["date"], robust=True).clip(-5, 5)
    du["z_ownership_agg"] = SIG.cross_sectional_z(du["ownership_agg"], du["date"], robust=True).clip(-5, 5)
    du = IC.forward_residual_return(du, [21, 63], resid_col="resid_bp")
    for h in (21, 63):
        per = []
        for _, g in du.groupby("date", sort=False):
            if len(g) < 8:
                continue
            per.append(IC._spearman(g["z_ownership_agg"].to_numpy(float), g[f"fwd_{h}"].to_numpy(float)))
        v = np.array([x for x in per if np.isfinite(x)], float)
        print(f"  ownership_agg lag-0 IC @ {h}d: {v.mean():.4f}  t={v.mean()/(v.std(ddof=1)/np.sqrt(v.size)):.2f}")

    print("\n" + "=" * 100)
    print("3. BIVARIATE REGRESSION -- forward bp per unit z, signal AND resid together")
    print("=" * 100)
    biv = pd.DataFrame([r for c in ALL_SIGNALS for h in HORIZONS
                        if (r := bivariate(d, f"z_{c}", "z_resid", h))])
    print(biv.round(4).to_string(index=False))
    biv.to_csv(os.path.join(DATA_DIR, f"{a.prefix}_bivariate.csv"), index=False)

    print("\n" + "=" * 100)
    print("4. DOUBLE SORT -- mean forward bp by (resid quintile x signal tercile)")
    print("=" * 100)
    ds_rows = []
    for c, h in (("ownership_agg", 63), ("ownership_agg", 21), ("soma_share", 63)):
        tab, cnt = double_sort(d, c, h)
        if tab.empty:
            continue
        print(f"\n{c} @ {h}d  (rows=resid quintile 0=rich..4=cheap, cols=signal tercile 0=low..2=high), bp:")
        print(tab.round(4).to_string())
        spread = (tab[tab.columns.max()] - tab[tab.columns.min()])
        print(f"  high-minus-low signal within each resid quintile: {spread.round(4).to_dict()}")
        for qr, val in spread.items():
            ds_rows.append({"signal": c, "horizon": h, "resid_quintile": qr, "high_minus_low_bp": val})
    pd.DataFrame(ds_rows).to_csv(os.path.join(DATA_DIR, f"{a.prefix}_double_sort.csv"), index=False)

    print("\n" + "=" * 100)
    print("5. FAMA-MACBETH -- CONTEMPORANEOUS: resid_bp ~ level signal + mechanical controls")
    print("   (does scarcity go with richness, after float size / age / rank / OTR?)")
    print("=" * 100)
    fm_rows = []
    for sig in LEVEL_SIGNALS:
        uni, _ = fm_regress(d, "resid_bp", [sig])
        multi, _ = fm_regress(d, "resid_bp", [sig, "log_float", "age", "rank", "otr"])
        for spec_name, tab in (("univariate", uni), ("multivariate", multi)):
            if tab.empty:
                continue
            tab = tab.copy(); tab["signal"] = sig; tab["spec"] = spec_name; tab["y"] = "resid_bp (contemporaneous)"
            fm_rows.append(tab)
    fm_contemp = pd.concat(fm_rows, ignore_index=True) if fm_rows else pd.DataFrame()
    print(fm_contemp.round(5).to_string(index=False) if not fm_contemp.empty else "none")
    fm_contemp.to_csv(os.path.join(DATA_DIR, f"{a.prefix}_fm_contemporaneous.csv"), index=False)

    print("\n" + "=" * 100)
    print("6. FAMA-MACBETH -- PREDICTIVE: fwd_h ~ level/chg signal + resid + controls")
    print("=" * 100)
    fm2_rows = []
    for sig in ALL_SIGNALS:
        for h in (21, 63):
            uni, _ = fm_regress(d, f"fwd_{h}", [sig])
            multi, _ = fm_regress(d, f"fwd_{h}", [sig, "resid_bp", "log_float", "age", "rank", "otr"])
            for spec_name, tab in (("univariate", uni), ("multivariate", multi)):
                if tab.empty:
                    continue
                tab = tab.copy(); tab["signal"] = sig; tab["horizon"] = h; tab["spec"] = spec_name
                fm2_rows.append(tab)
    fm2 = pd.concat(fm2_rows, ignore_index=True) if fm2_rows else pd.DataFrame()
    print(fm2.round(5).to_string(index=False) if not fm2.empty else "none")
    fm2.to_csv(os.path.join(DATA_DIR, f"{a.prefix}_fm_predictive.csv"), index=False)

    print("\n" + "=" * 100)
    print("7. bp of richness per 1 percentage point of ownership (from step 5, raw units)")
    print("=" * 100)
    conv_rows = []
    for sig in LEVEL_SIGNALS:
        uni, _ = fm_regress(d, "resid_bp", [sig])
        multi, _ = fm_regress(d, "resid_bp", [sig, "log_float", "age", "rank", "otr"])
        for spec_name, tab in (("univariate", uni), ("multivariate", multi)):
            if tab.empty:
                continue
            row = tab[tab["x"] == sig].iloc[0]
            bp_per_pp = row["mean_beta"] / 100.0
            print(f"  {sig} [{spec_name}]: {bp_per_pp:+.4f} bp of resid per 1pp ownership, "
                  f"t={row['t_stat']:.2f}, n_dates={row['n_dates']}")
            conv_rows.append({"signal": sig, "spec": spec_name, "bp_per_1pp": bp_per_pp,
                              "t_stat": row["t_stat"], "n_dates": row["n_dates"]})
    pd.DataFrame(conv_rows).to_csv(os.path.join(DATA_DIR, f"{a.prefix}_bp_per_pp.csv"), index=False)

    print(f"\ntotal runtime: {time.time()-t0:.0f}s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
