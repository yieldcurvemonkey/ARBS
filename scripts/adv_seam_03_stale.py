r"""Staleness: does the seam's idiosyncratic dispersion live only on stale marks?

The hourly bar stamped H is the LAST MI01 print inside [H, H+1) (established at
0.994 on 277,944 discriminating cells by adv_seam_02). How old that print is at
the hour boundary is not knowable from the hourly layer -- only MI01 says.

Three things measured here, on the MI01-covered subset:
  A. age census: minutes between the last print in [14,15) and 15:00, and between
     the last print in [15,16) and 16:00.
  B. the report's idio decomposition re-run on FRESH cells only (both marks <=5
     minutes old), which SELECTS liquid bonds and active days and is therefore an
     adversarial UPPER bound on dispersion.
  C. a seam built directly on MI01 clock times (asof 15:00:00, asof 16:00:00) on
     the same cells, so the hourly proxy can be compared to the thing it proxies.
"""
from __future__ import annotations

import pathlib
import sys

import numpy as np
import pandas as pd

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
DATA = ROOT / "notebooks/backtests/etf_rebalance/_data"

from MDP.CitiVelocityExcel.cache import CitiVeloTagCache  # noqa: E402

MIN_BONDS = 12
COST = 0.535


def fit_idio(g: pd.DataFrame, col: str, deg: int = 2) -> np.ndarray:
    y = g[col].to_numpy(float)
    raw = g["ttm"].to_numpy(float)
    x = (raw - raw.mean()) / max(1e-9, raw.std())
    A = np.column_stack([x ** k for k in range(deg + 1)])
    beta, *_ = np.linalg.lstsq(A, y, rcond=None)
    return y - A @ beta


def per_date_idio(panel: pd.DataFrame, col: str, deg: int = 2) -> pd.DataFrame:
    rows, obs = [], []
    for d, g in panel.groupby("date", sort=True):
        g = g.dropna(subset=[col, "ttm"])
        if len(g) < MIN_BONDS:
            continue
        r = fit_idio(g, col, deg)
        rows.append({"date": d, "n": len(g), "sd_idio_bp": float(np.std(r)),
                     "level_bp": float(g[col].mean())})
        o = g[["date", "isin", "ttm"]].copy()
        o["idio"] = r
        obs.append(o)
    return pd.DataFrame(rows), (pd.concat(obs, ignore_index=True) if obs else pd.DataFrame())


cache = CitiVeloTagCache()
uni = pd.read_csv(DATA / "intraday_universe.csv").set_index("isin")
isins = list(uni.index.astype(str))

recs = []
for isin in isins:
    tag = f"RATES.BOND.{isin}.YIELD"
    mi = cache.read(tag, "MI01", "CLOSE")
    if mi is None or mi.empty:
        continue
    mi = mi.dropna()
    idx = pd.DatetimeIndex(mi.index)
    v = mi.to_numpy(float)
    days = idx.normalize()
    minute = idx.hour * 60 + idx.minute
    for day in pd.unique(days):
        sel = days == day
        mm = minute[sel]
        vv = v[sel]
        rec = {"isin": isin, "date": pd.Timestamp(day)}
        ok = True
        for H, lab in ((15, "15"), (16, "16")):
            w = (mm >= (H - 1) * 60) & (mm < H * 60)
            if not w.any():
                ok = False
                break
            last = int(np.max(mm[w]))
            rec[f"y{lab}"] = float(vv[w][np.argmax(mm[w])])
            rec[f"age{lab}"] = H * 60 - last          # minutes before H:00
            rec[f"n{lab}"] = int(w.sum())
        # MI01 direct: last print at or before H:00:00 exactly (no window floor)
        for H, lab in ((15, "15"), (16, "16")):
            w = mm <= H * 60
            if w.any():
                rec[f"asof{lab}"] = float(vv[w][np.argmax(mm[w])])
                rec[f"asof_age{lab}"] = H * 60 - int(np.max(mm[w]))
        if ok:
            recs.append(rec)
M = pd.DataFrame(recs)
M["maturity_date"] = pd.to_datetime(M["isin"].map(uni["maturity_date"]))
M["issue_date"] = pd.to_datetime(M["isin"].map(uni["issue_date"]))
M["ttm"] = (M["maturity_date"] - M["date"]).dt.days / 365.25
M = M[(M["date"] >= M["issue_date"]) & (M["ttm"] > 0)]
M["seam_hr"] = (M["y16"] - M["y15"]) * 100.0
M["seam_mi"] = (M["asof16"] - M["asof15"]) * 100.0
print(f"MI01 bond-days with both hourly windows populated: {len(M):,}  "
      f"dates {M['date'].nunique()}  bonds {M['isin'].nunique()}")

# drop the report's early-close dates so the comparison is like for like
adv = pd.read_parquet(DATA / "adv_seam_panel.parquet")
keep_dates = set(pd.DatetimeIndex(adv["date"].unique()))
M = M[M["date"].isin(keep_dates)]
print(f"after dropping 14:00-close dates: {len(M):,}  dates {M['date'].nunique()}")

print("\n=== A. AGE CENSUS (minutes between last print and the hour boundary) ===")
for c in ("age15", "age16"):
    q = M[c].describe(percentiles=[0.25, 0.5, 0.75, 0.9, 0.95, 0.99])
    print(f"{c}: " + "  ".join(f"{k}={v:.2f}" for k, v in q.items()))
for thr in (1, 2, 5, 10, 20):
    f = ((M["age15"] <= thr) & (M["age16"] <= thr)).mean()
    print(f"  both marks fresher than {thr:>2d} min: {f:.4f}")
print("prints per hour window: median n15 %.0f  n16 %.0f"
      % (M["n15"].median(), M["n16"].median()))

# hourly-vs-MI01 tie out of the proxy itself
tie = M.dropna(subset=["seam_hr", "seam_mi"])
print(f"\nseam(hourly windows) vs seam(MI01 asof clock): corr "
      f"{np.corrcoef(tie['seam_hr'], tie['seam_mi'])[0,1]:.4f}  "
      f"mean|diff| {np.abs(tie['seam_hr']-tie['seam_mi']).mean():.4f} bp")

print("\n=== B. IDIO DISPERSION, ALL vs FRESH-ONLY, same universe of dates ===")
out = []
for lab, sub in (("all MI01 cells", M),
                 ("fresh <=5min", M[(M["age15"] <= 5) & (M["age16"] <= 5)]),
                 ("fresh <=2min", M[(M["age15"] <= 2) & (M["age16"] <= 2)]),
                 ("fresh <=1min", M[(M["age15"] <= 1) & (M["age16"] <= 1)]),
                 ("STALE >5min either", M[(M["age15"] > 5) | (M["age16"] > 5)])):
    for col in ("seam_hr", "seam_mi"):
        pd_, po = per_date_idio(sub, col)
        if len(pd_) == 0:
            out.append({"subset": lab, "col": col, "dates": 0})
            continue
        pooled = float(np.std(po["idio"]))
        out.append({"subset": lab, "col": col, "dates": len(pd_),
                    "median_n_bonds": float(pd_["n"].median()),
                    "sd_idio_median_bp": float(pd_["sd_idio_bp"].median()),
                    "sd_idio_pooled_bp": pooled,
                    "mean_abs_move_bp": float(sub[col].abs().mean()),
                    "median_vs_cost": float(pd_["sd_idio_bp"].median()) / COST,
                    "pooled_vs_cost": pooled / COST})
B = pd.DataFrame(out)
print(B.round(4).to_string(index=False))
B.to_csv(DATA / "adv_seam_staleness.csv", index=False)

print("\n=== C. TTM >= 20 restriction (the bonds a TLT fly actually trades) ===")
out2 = []
for lab, sub in (("all ttm", M), ("ttm>=20", M[M["ttm"] >= 20.0]),
                 ("ttm>=20 & fresh<=5", M[(M["ttm"] >= 20.0) & (M["age15"] <= 5) & (M["age16"] <= 5)])):
    pd_, po = per_date_idio(sub, "seam_hr")
    if len(pd_) == 0:
        continue
    out2.append({"subset": lab, "dates": len(pd_), "median_n": float(pd_["n"].median()),
                 "sd_idio_median_bp": float(pd_["sd_idio_bp"].median()),
                 "sd_idio_pooled_bp": float(np.std(po["idio"])),
                 "median_vs_cost": float(pd_["sd_idio_bp"].median()) / COST})
print(pd.DataFrame(out2).round(4).to_string(index=False))
pd.DataFrame(out2).to_csv(DATA / "adv_seam_ttm20.csv", index=False)

M.to_parquet(DATA / "adv_seam_mi01_cells.parquet", index=False)
print("\nwrote adv_seam_mi01_cells.parquet, adv_seam_staleness.csv, adv_seam_ttm20.csv")
