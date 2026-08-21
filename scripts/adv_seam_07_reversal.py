r"""Independent check of the reversal claims, including the test the report did
not run: is the CLEAN idio reversal different from its own disjoint placebo?
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

MIN_BONDS = 12
p = pd.read_parquet(DATA / "adv_seam_panel.parquet")

# next trading date's 10:00 and 16:00, aligned on the dates the panel carries
dates = pd.DatetimeIndex(sorted(p["date"].unique()))
nxt = pd.Series(dates[1:], index=dates[:-1])
p["next_date"] = p["date"].map(nxt)
nx = p[["date", "isin", "y10", "y16"]].rename(
    columns={"date": "next_date", "y10": "y10_next", "y16": "y16_next"})
p = p.merge(nx, on=["next_date", "isin"], how="left")

p["seam"] = (p["y16"] - p["y15"]) * 100
p["on_1700_1000n"] = (p["y10_next"] - p["y17"]) * 100
p["on_1600_1000n"] = (p["y10_next"] - p["y16"]) * 100
p["c1314"] = (p["y14"] - p["y13"]) * 100
p["c1516"] = p["seam"]


def idio(col):
    out = []
    for d, g in p.groupby("date", sort=True):
        g = g.dropna(subset=[col, "ttm"])
        if len(g) < MIN_BONDS:
            continue
        y = g[col].to_numpy(float)
        r = g["ttm"].to_numpy(float)
        x = (r - r.mean()) / max(1e-9, r.std())
        A = np.column_stack([np.ones_like(x), x, x ** 2])
        b, *_ = np.linalg.lstsq(A, y, rcond=None)
        o = g[["date", "isin"]].copy()
        o[col + "_i"] = y - A @ b
        out.append(o)
    return pd.concat(out, ignore_index=True)


def beta_and_perdate(a, b_):
    ia, ib = idio(a), idio(b_)
    m = ia.merge(ib, on=["date", "isin"], how="inner").dropna()
    x = m[a + "_i"].to_numpy(float)
    y = m[b_ + "_i"].to_numpy(float)
    beta = float(np.polyfit(x, y, 1)[0])
    per = []
    for d, g in m.groupby("date"):
        if len(g) < MIN_BONDS:
            continue
        xx = g[a + "_i"].to_numpy(float)
        yy = g[b_ + "_i"].to_numpy(float)
        if xx.std() == 0:
            continue
        per.append(float(np.polyfit(xx, yy, 1)[0]))
    per = np.array(per)
    n = len(per)
    lags = int(np.floor(4 * (n / 100.0) ** (2.0 / 9.0)))
    e = per - per.mean()
    s = float(np.dot(e, e) / n)
    for L in range(1, lags + 1):
        s += 2 * (1 - L / (lags + 1.0)) * float(np.dot(e[L:], e[:-L]) / n)
    se = np.sqrt(s / n)
    return beta, len(m), per, per.mean(), per.mean() / se, n


print("=== IDIO reversal, independently ===")
rows = []
for lab, a, b_ in (("seam -> next10 (shares y16)", "seam", "on_1600_1000n"),
                   ("seam -> next10 from 17:00 (CLEAN)", "seam", "on_1700_1000n"),
                   ("placebo 13->14 then 15->16 (DISJOINT)", "c1314", "c1516")):
    beta, n, per, pm, t, nd = beta_and_perdate(a, b_)
    rows.append({"pair": lab, "pooled_beta": beta, "pct_reversed": -100 * beta,
                 "n_obs": n, "per_date_beta_mean": pm, "per_date_nw_t": t, "dates": nd})
    globals()["per_" + lab.split()[0] + ("_c" if "CLEAN" in lab else "")] = per
R = pd.DataFrame(rows)
print(R.round(4).to_string(index=False))
R.to_csv(DATA / "adv_seam_reversal.csv", index=False)

# THE TEST THE REPORT DID NOT RUN: clean seam reversal vs disjoint placebo
_, _, per_clean, _, _, _ = beta_and_perdate("seam", "on_1700_1000n")
_, _, per_plac, _, _, _ = beta_and_perdate("c1314", "c1516")
k = min(len(per_clean), len(per_plac))
d = per_clean[:k] - per_plac[:k]
n = len(d)
lags = int(np.floor(4 * (n / 100.0) ** (2.0 / 9.0)))
e = d - d.mean()
s = float(np.dot(e, e) / n)
for L in range(1, lags + 1):
    s += 2 * (1 - L / (lags + 1.0)) * float(np.dot(e[L:], e[:-L]) / n)
t = d.mean() / np.sqrt(s / n)
print(f"\nCLEAN idio reversal MINUS disjoint placebo, per-date paired: "
      f"{d.mean():+.4f} beta, NW t {t:+.2f}, n {n}")
print("  -> the report quoted 10.9% clean against a 3.5% disjoint placebo but "
      "never tested the difference.")
