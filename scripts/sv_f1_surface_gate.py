"""F1 oracle gate — swaption ATM surface residual mean-reversion (family F1).

The BofA prior-killer is built in BEFORE any residual is computed: raw vol-grid
PC residual RV "is trading fundamentally a rate dynamic and not a vol dynamic"
(US Vol Primer p.14), so each cell's daily change is first regressed on the
first three PCs of the par-curve's daily changes (walk-forward, trailing 756d,
refit monthly), and the residual is what remains — a vol-specific move.

Gate per cell (17 expiries x 9 tenors, ATM, 2015-10+): cumulative residual z
vs trailing 252d; on |z| >= 1.5 fire days, the 5/21bd perfect-direction
reversion of the residual vs the CM-1 measured round trip for that expiry
bucket. Reported by BofA cluster (ULC/URC/LLC/IV/LRC). Descriptive: nothing
selects a strategy. Trial ledger: 0 (gate).

Run: conda run -n stir python scripts/sv_f1_surface_gate.py
"""
import os

os.environ.setdefault("ARBS_SUPABASE_ENABLED", "0")

import pathlib
import sys

_REPO = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO))

import numpy as np
import pandas as pd

DATA = _REPO / "notebooks" / "data" / "citivelo_rv"
GRID = ["2Y", "3Y", "5Y", "7Y", "10Y", "15Y", "20Y", "30Y"]
PCA_WIN = 756
Z_WIN = 252
FIRE_Z = 1.5
HORIZONS = [5, 21]

#: CM-1 measured ATM half-spreads (annual bp) by expiry bucket -> ROUND TRIP x2
CM1_RT = {"1M": 1.42, "2M": 0.76, "3M": 0.76, "6M": 0.50, "9M": 0.42, "1Y": 0.42,
          "18M": 0.46, "2Y": 0.46, "3Y": 0.34, "4Y": 0.34, "5Y": 0.34,
          "7Y": 0.34, "10Y": 0.34, "12Y": 0.34, "15Y": 0.34, "20Y": 0.34, "30Y": 0.34}
# beyond 5Y expiry the SDR sample thins; 3-5Y bucket value is EXTENDED as an
# assumption (flagged) — long-expiry cells are dealer-extrapolated anyway.

_EXP_Y = {"1M": 1/12, "2M": 2/12, "3M": 0.25, "6M": 0.5, "9M": 0.75, "1Y": 1.0,
          "18M": 1.5, "2Y": 2.0, "3Y": 3.0, "4Y": 4.0, "5Y": 5.0, "7Y": 7.0,
          "10Y": 10.0, "12Y": 12.0, "15Y": 15.0, "20Y": 20.0, "30Y": 30.0}
_TEN_Y = {"1Y": 1.0, "2Y": 2.0, "3Y": 3.0, "5Y": 5.0, "7Y": 7.0, "10Y": 10.0,
          "15Y": 15.0, "20Y": 20.0, "30Y": 30.0}


def cluster(exp: str, ten: str) -> str:
    e, t = _EXP_Y[exp], _TEN_Y[ten]
    if e <= 1.0:
        return "ULC" if t <= 3 else "URC"
    if t <= 3:
        return "LLC"
    return "IV" if e <= 4 else "LRC"


def main() -> None:
    vol = pd.read_parquet(DATA / "vol_panel.parquet")
    atm = vol[vol["offset_bp"] == 0.0].copy()
    atm["cell"] = atm["expiry"] + "x" + atm["tenor"]
    mat = atm.pivot_table(index="date", columns="cell", values="vol_bp", aggfunc="last").sort_index()
    mat.index = pd.to_datetime(mat.index)

    par = pd.read_parquet(DATA / "par_grid_USD_SOFR.parquet")[GRID].dropna(how="any")
    par.index = pd.to_datetime(par.index)
    common = mat.index.intersection(par.index)
    mat, par = mat.loc[common], par.loc[common]
    dv = mat.diff()
    dr = (par.diff() * 100.0)  # bp

    # walk-forward rate PCs + betas, refit monthly
    resid = pd.DataFrame(index=mat.index, columns=mat.columns, dtype=float)
    months = pd.Series(mat.index, index=mat.index).dt.to_period("M")
    uniq = months.unique()
    for mi, m in enumerate(uniq):
        block = months == m
        first = mat.index[block][0]
        hist_end = mat.index[mat.index < first]
        if len(hist_end) < PCA_WIN // 2:
            continue
        hist = dr.loc[hist_end[-PCA_WIN:]].dropna()
        if len(hist) < PCA_WIN // 2:
            continue
        C = np.cov(hist.T)
        w, V = np.linalg.eigh(C)
        pcs_load = V[:, ::-1][:, :3]                     # top-3 rate PCs
        f_hist = hist.to_numpy() @ pcs_load              # factor history
        dv_hist = dv.loc[hist.index]
        betas = {}
        for c in mat.columns:
            y = dv_hist[c].to_numpy()
            mask = np.isfinite(y)
            if mask.sum() < 200:
                betas[c] = np.zeros(3)
                continue
            X = f_hist[mask]
            b, *_ = np.linalg.lstsq(X, y[mask], rcond=None)
            betas[c] = b
        f_now = dr.loc[block].to_numpy() @ pcs_load
        for j, c in enumerate(mat.columns):
            resid.loc[block, c] = dv.loc[block, c].to_numpy() - f_now @ betas[c]

    cum = resid.cumsum()
    mu = cum.rolling(Z_WIN, min_periods=126).mean()
    sd = cum.rolling(Z_WIN, min_periods=126).std()
    z = (cum - mu) / sd

    rows = []
    for c in mat.columns:
        exp, ten = c.split("x")
        rt = CM1_RT[exp]
        zc = z[c]
        fire = zc.abs() >= FIRE_Z
        n_fired = int(fire.sum())
        if n_fired < 20:
            continue
        rec = {"cell": c, "cluster": cluster(exp, ten), "n": int(zc.notna().sum()),
               "n_fired": n_fired, "rt_bp": rt,
               "resid_sd_bp": float(resid[c].std() * np.sqrt(252))}
        for h in HORIZONS:
            fwd = cum[c].shift(-h) - cum[c]
            # perfect-direction capture: reversion toward the mean
            move = (np.sign(mu[c] - cum[c]) * fwd)[fire].dropna()
            rec[f"oracle_med_{h}bd"] = float(move.abs().median()) if len(move) else np.nan
            rec[f"rev_med_{h}bd"] = float(move.median()) if len(move) else np.nan
            rec[f"rev_frac_pos_{h}bd"] = float((move > 0).mean()) if len(move) else np.nan
        rows.append(rec)

    rep = pd.DataFrame(rows)
    rep["pond_boat_21"] = rep["oracle_med_21bd"] / rep["rt_bp"]
    rep["rev_boat_21"] = rep["rev_med_21bd"] / rep["rt_bp"]
    rep.to_parquet(DATA / "f1_surface_gate.parquet", index=False)
    pd.set_option("display.width", 220)
    agg = rep.groupby("cluster")[["n_fired", "rt_bp", "oracle_med_21bd", "rev_med_21bd",
                                  "rev_frac_pos_21bd", "pond_boat_21", "rev_boat_21"]].median()
    print(agg.to_string(float_format=lambda x: f"{x:7.3f}"))
    print("\ntop cells by REV/boat (actual median reversion vs round trip):")
    print(rep.nlargest(10, "rev_boat_21")[["cell", "cluster", "n_fired", "rev_med_21bd",
                                           "rt_bp", "rev_boat_21", "rev_frac_pos_21bd"]]
          .to_string(index=False, float_format=lambda x: f"{x:6.3f}"))
    print("\nwrote f1_surface_gate.parquet")


if __name__ == "__main__":
    main()
