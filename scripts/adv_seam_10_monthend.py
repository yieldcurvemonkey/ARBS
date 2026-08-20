r"""Close the last checklist gap: re-run the k=0 month-end event point estimates
from my own idio panel, uncontrolled, with no matching machinery of theirs.
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

COST = 0.535
MIN_BONDS = 12

p = pd.read_parquet(DATA / "adv_seam_panel.parquet")
p["cusip"] = p["cusip"].astype(str)
rows = []
for d, g in p.groupby("date", sort=True):
    g = g.dropna(subset=["seam", "ttm"])
    if len(g) < MIN_BONDS:
        continue
    y = g["seam"].to_numpy(float)
    r = g["ttm"].to_numpy(float)
    x = (r - r.mean()) / max(1e-9, r.std())
    A = np.column_stack([np.ones_like(x), x, x ** 2])
    b, *_ = np.linalg.lstsq(A, y, rcond=None)
    o = g[["date", "cusip", "ttm"]].copy()
    o["idio"] = y - A @ b
    rows.append(o)
obs = pd.concat(rows, ignore_index=True)

ev = pd.read_csv(DATA / "seam_monthend_events.csv", parse_dates=["date"])
ev["cusip"] = ev["cusip"].astype(str)
print(f"their event file: {len(ev)} events "
      f"({(ev['kind']=='addition').sum()} add / {(ev['kind']=='deletion').sum()} del)")

m = ev.merge(obs, on=["date", "cusip"], how="left")
print(f"events landing on a bond-date my panel carries: {m['idio'].notna().sum()} of {len(m)}")

print("\n=== k=0 RAW idio seam move, uncontrolled, my own fit ===")
out = []
for kind, g in m.dropna(subset=["idio"]).groupby("kind"):
    v = g["idio"].to_numpy(float)
    se = v.std(ddof=1) / np.sqrt(len(v))
    out.append({"kind": kind, "n": len(v), "mean_idio_bp": v.mean(), "sd_bp": v.std(ddof=1),
                "se_bp": se, "t": v.mean() / se, "abs_vs_cost": abs(v.mean()) / COST,
                "mde_at_t2_bp": 2 * se, "mde_vs_cost": 2 * se / COST})
# and the non-event bonds on the SAME dates, as the crudest possible control
ekeys = set(map(tuple, ev[["date", "cusip"]].itertuples(index=False, name=None)))
same = obs[obs["date"].isin(set(ev["date"]))].copy()
same["is_ev"] = [tuple(x) in ekeys for x in same[["date", "cusip"]].itertuples(index=False, name=None)]
ctl = same.loc[~same["is_ev"], "idio"].to_numpy(float)
se = ctl.std(ddof=1) / np.sqrt(len(ctl))
out.append({"kind": "non-event bonds, same dates", "n": len(ctl), "mean_idio_bp": ctl.mean(),
            "sd_bp": ctl.std(ddof=1), "se_bp": se, "t": ctl.mean() / se,
            "abs_vs_cost": abs(ctl.mean()) / COST, "mde_at_t2_bp": 2 * se,
            "mde_vs_cost": 2 * se / COST})
O = pd.DataFrame(out)
print(O.round(5).to_string(index=False))
O.to_csv(DATA / "adv_seam_monthend_k0.csv", index=False)

theirs = pd.read_csv(DATA / "seam_monthend_event_study.csv")
print("\ntheir event-study file columns:", list(theirs.columns)[:12])
k0 = theirs[theirs.get("k", pd.Series(dtype=float)) == 0] if "k" in theirs.columns else theirs
print(k0.head(6).round(5).to_string(index=False))
