r"""Independent recompute of the level/slope/idio decomposition, plus the number
the report should have quoted for a THREE-LEG structure.

The report's deciding number is the MEDIAN per-date idiosyncratic sd of a single
bond. Two things push that up and are checked here:
  * median vs mean vs pooled across dates -- a median of a per-date dispersion is
    the smallest of the natural summaries;
  * a butterfly holds three bonds. With weights (-1/2, +1, -1/2) on independent
    idios the structure's idio sd is sqrt(1 + 1/4 + 1/4) = 1.2247x a single bond's.
    That is the quantity to put next to a THREE-LEG round trip.
Both are adversarial: they make the pond bigger, not smaller.
"""
from __future__ import annotations

import itertools
import pathlib
import sys

import numpy as np
import pandas as pd

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
DATA = ROOT / "notebooks/backtests/etf_rebalance/_data"

COST = 0.535
MIN_BONDS = 12

panel = pd.read_parquet(DATA / "adv_seam_panel.parquet")
print("panel:", len(panel), panel["date"].nunique(), "dates")

COLS = {"seam": "15->16 SEAM", "c1314": "13->14", "c1415": "14->15", "c1617": "16->17"}


def run(col: str, deg: int, coupon: bool, sub: pd.DataFrame | None = None):
    p = panel if sub is None else sub
    rows, resid = [], []
    for d, g in p.groupby("date", sort=True):
        need = [col, "ttm"] + (["cpn"] if coupon else [])
        g = g.dropna(subset=need)
        if len(g) < MIN_BONDS:
            continue
        y = g[col].to_numpy(float)
        raw = g["ttm"].to_numpy(float)
        x = (raw - raw.mean()) / max(1e-9, raw.std())
        cols = [x ** k for k in range(deg + 1)]
        if coupon:
            c = g["cpn"].to_numpy(float)
            cols.append((c - c.mean()) / max(1e-9, c.std()))
        A = np.column_stack(cols)
        beta, *_ = np.linalg.lstsq(A, y, rcond=None)
        r = y - A @ beta
        tot = float(np.mean(y ** 2))
        after_level = float(np.mean((y - y.mean()) ** 2))
        rows.append({"date": d, "n": len(g), "level_bp": float(y.mean()),
                     "sd_idio_bp": float(np.std(r)),
                     "var_total": tot, "var_after_level": after_level,
                     "var_idio": float(np.mean(r ** 2))})
        o = g[["date", "isin", "ttm"]].copy()
        o["idio"] = r
        resid.append(o)
    per_date = pd.DataFrame(rows)
    per_obs = pd.concat(resid, ignore_index=True)
    return per_date, per_obs


print("\n=== TIE-OUT: basis robustness table (their seam_basis_robustness.csv) ===")
rows = []
for deg in (1, 2, 3, 4):
    for coupon in (False, True):
        pdte, pobs = run("seam", deg, coupon)
        rows.append({"deg": deg, "coupon": coupon, "dates": len(pdte),
                     "sd_idio_median_bp": float(pdte["sd_idio_bp"].median()),
                     "sd_idio_mean_bp": float(pdte["sd_idio_bp"].mean()),
                     "sd_idio_p75_bp": float(pdte["sd_idio_bp"].quantile(0.75)),
                     "sd_idio_p90_bp": float(pdte["sd_idio_bp"].quantile(0.90)),
                     "sd_idio_pooled_bp": float(np.std(pobs["idio"]))})
R = pd.DataFrame(rows)
R["median_vs_cost"] = R["sd_idio_median_bp"] / COST
R["mean_vs_cost"] = R["sd_idio_mean_bp"] / COST
R["pooled_vs_cost"] = R["sd_idio_pooled_bp"] / COST
print(R.round(4).to_string(index=False))
R.to_csv(DATA / "adv_seam_basis_robustness.csv", index=False)

print("\n=== variance shares, deg 2, no coupon ===")
pdte, pobs = run("seam", 2, False)
tot = pdte["var_total"].sum()
print(f"level share      {(tot - pdte['var_after_level'].sum())/tot:.6f}")
print(f"slope+curv share {(pdte['var_after_level'].sum() - pdte['var_idio'].sum())/tot:.6f}")
print(f"idio share       {pdte['var_idio'].sum()/tot:.6f}")
print(f"level sd across dates {pdte['level_bp'].std():.4f} bp")

print("\n=== controls, deg 2 ===")
ctl = []
for col, lab in COLS.items():
    pd_, po_ = run(col, 2, False)
    ctl.append({"window": lab, "dates": len(pd_),
                "sd_idio_median_bp": float(pd_["sd_idio_bp"].median()),
                "sd_idio_pooled_bp": float(np.std(po_["idio"])),
                "level_sd_bp": float(pd_["level_bp"].std())})
C = pd.DataFrame(ctl)
C["median_vs_cost"] = C["sd_idio_median_bp"] / COST
print(C.round(4).to_string(index=False))
C.to_csv(DATA / "adv_seam_controls.csv", index=False)

# ------------------------------------------------- three-leg structure, measured
print("\n=== A BUTTERFLY, not a single bond: measured, not assumed ===")
pdte1, pobs1 = run("seam", 1, False)          # the report's most generous basis
grid = []
rng = np.random.default_rng(0)
for d, g in pobs1.groupby("date", sort=True):
    g = g.sort_values("ttm").reset_index(drop=True)
    if len(g) < 9:
        continue
    idio = g["idio"].to_numpy(float)
    n = len(g)
    # every consecutive (i, i+k, i+2k) triple for k = 1..3 -> a real fly in ttm order
    vals = []
    for k in (1, 2, 3):
        i = np.arange(0, n - 2 * k)
        if len(i) == 0:
            continue
        vals.append(idio[i + k] - 0.5 * idio[i] - 0.5 * idio[i + 2 * k])
    if not vals:
        continue
    v = np.concatenate(vals)
    grid.append({"date": d, "n_flies": len(v), "fly_idio_sd_bp": float(np.std(v)),
                 "fly_idio_mean_abs_bp": float(np.abs(v).mean()),
                 "frac_gt_cost": float((np.abs(v) > COST).mean()),
                 "max_abs_bp": float(np.abs(v).max())})
F = pd.DataFrame(grid)
print(f"dates {len(F)}  median flies/date {F['n_flies'].median():.0f}")
print(f"fly idio sd        median {F['fly_idio_sd_bp'].median():.4f} bp  "
      f"mean {F['fly_idio_sd_bp'].mean():.4f}  p90 {F['fly_idio_sd_bp'].quantile(.9):.4f}")
print(f"                   = {F['fly_idio_sd_bp'].median()/COST:.3f}x cost (median), "
      f"{F['fly_idio_sd_bp'].mean()/COST:.3f}x (mean)")
print(f"fly mean |idio|    median across dates {F['fly_idio_mean_abs_bp'].median():.4f} bp "
      f"= {F['fly_idio_mean_abs_bp'].median()/COST:.3f}x cost")
print(f"implied ratio fly_sd / single_bond_sd = "
      f"{F['fly_idio_sd_bp'].median()/pdte1['sd_idio_bp'].median():.3f} (theory 1.2247 if independent)")
print(f"\nEX-POST opportunity (a PERFECT-FORESIGHT bound, not tradeable):")
print(f"  fraction of flies whose |seam idio| exceeds the {COST} bp round trip: "
      f"{F['frac_gt_cost'].mean():.4f}")
print(f"  best fly per date, median |idio| {F['max_abs_bp'].median():.4f} bp "
      f"= {F['max_abs_bp'].median()/COST:.3f}x cost")
F.to_csv(DATA / "adv_seam_fly_dispersion.csv", index=False)

# ------------------------------------------- persistence of the per-bond idio
print("\n=== per-bond persistence (is there anything to predict?) ===")
pobs2 = run("seam", 2, False)[1]
pobs2["half"] = (pobs2["date"] >= pobs2["date"].median()).astype(int)
m = pobs2.groupby(["isin", "half"])["idio"].mean().unstack()
m = m.dropna()
print(f"bonds in both halves: {len(m)}  split-half corr of mean idio seam: "
      f"{m.corr().iloc[0,1]:+.4f}")
print(f"per-bond mean idio: sd across bonds {m.stack().std():.4f} bp")
# odd/even day split as a second, less regime-confounded split
pobs2["oe"] = pd.DatetimeIndex(pobs2["date"]).dayofyear % 2
m2 = pobs2.groupby(["isin", "oe"])["idio"].mean().unstack().dropna()
print(f"odd/even-day split-half corr: {m2.corr().iloc[0,1]:+.4f}  (n={len(m2)})")
