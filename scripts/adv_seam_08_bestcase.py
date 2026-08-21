r"""The best-case trade the report never priced: fade the seam's idiosyncratic
butterfly move over the clean overnight leg.

The report established a CLEAN idio reversal of ~11% and left it as a percentage.
A percentage of a 0.08 bp dispersion is not a trade; this prices it in bp against
the 0.535 bp measured round trip, three ways, each deliberately generous:
  (a) every fly, sized by sign only;
  (b) the top-decile fly by |seam idio| on each date;
  (c) the single largest |seam idio| fly on each date -- maximum selection.
The exit leg is 17:00 -> next 10:00, which shares NO mark with the seam, so no
part of the measured P&L is the seam's own mark noise reversing on itself.
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
dates = pd.DatetimeIndex(sorted(p["date"].unique()))
nxt = pd.Series(dates[1:], index=dates[:-1])
p["next_date"] = p["date"].map(nxt)
nx = p[["date", "isin", "y10"]].rename(columns={"date": "next_date", "y10": "y10_next"})
p = p.merge(nx, on=["next_date", "isin"], how="left")
p["seam"] = (p["y16"] - p["y15"]) * 100
p["exit"] = (p["y10_next"] - p["y17"]) * 100


def idio_col(g, col):
    y = g[col].to_numpy(float)
    r = g["ttm"].to_numpy(float)
    x = (r - r.mean()) / max(1e-9, r.std())
    A = np.column_stack([np.ones_like(x), x, x ** 2])
    b, *_ = np.linalg.lstsq(A, y, rcond=None)
    return y - A @ b


trades = []
for d, g in p.groupby("date", sort=True):
    g = g.dropna(subset=["seam", "exit", "ttm"]).sort_values("ttm").reset_index(drop=True)
    if len(g) < MIN_BONDS:
        continue
    si = idio_col(g, "seam")
    xi = idio_col(g, "exit")
    n = len(g)
    for k in (1, 2, 3):
        i = np.arange(0, n - 2 * k)
        if len(i) == 0:
            continue
        s = si[i + k] - 0.5 * si[i] - 0.5 * si[i + 2 * k]
        x = xi[i + k] - 0.5 * xi[i] - 0.5 * xi[i + 2 * k]
        trades.append(pd.DataFrame({"date": d, "k": k, "seam_fly": s, "exit_fly": x}))
T = pd.concat(trades, ignore_index=True)
print(f"fly-dates: {len(T):,} over {T['date'].nunique()} dates")

# fade: if the seam CHEAPENED the fly (positive), expect it to richen back ->
# gross = -sign(seam) * exit
T["gross_bp"] = -np.sign(T["seam_fly"]) * T["exit_fly"]
T["absseam"] = T["seam_fly"].abs()


def nwt(v):
    v = np.asarray(v, float)
    n = len(v)
    lags = int(np.floor(4 * (n / 100.0) ** (2.0 / 9.0)))
    e = v - v.mean()
    s = float(np.dot(e, e) / n)
    for L in range(1, lags + 1):
        s += 2 * (1 - L / (lags + 1.0)) * float(np.dot(e[L:], e[:-L]) / n)
    return v.mean(), v.mean() / np.sqrt(s / n), n


rows = []
# (a) all flies, per-date mean then NW t on the date series
a = T.groupby("date")["gross_bp"].mean()
m, t, n = nwt(a.to_numpy())
rows.append({"selection": "(a) every fly, sign only", "gross_bp_per_trade": m,
             "nw_t": t, "dates": n, "trades_per_date": len(T) / T["date"].nunique()})

# (b) top-decile by |seam idio| within date
T["rk"] = T.groupby("date")["absseam"].rank(pct=True)
b = T[T["rk"] >= 0.90].groupby("date")["gross_bp"].mean()
m, t, n = nwt(b.to_numpy())
rows.append({"selection": "(b) top decile |seam idio|", "gross_bp_per_trade": m,
             "nw_t": t, "dates": n,
             "trades_per_date": float(T[T['rk'] >= 0.90].groupby('date').size().mean())})

# (c) the single largest per date
c = T.loc[T.groupby("date")["absseam"].idxmax()]
m, t, n = nwt(c["gross_bp"].to_numpy())
rows.append({"selection": "(c) largest |seam idio| only", "gross_bp_per_trade": m,
             "nw_t": t, "dates": n, "trades_per_date": 1.0})

# (d) month-end only, top decile  -- where the ETF story says it should live
me = pd.Series(pd.DatetimeIndex(T["date"]))
cal = (me.dt.to_period("M").dt.to_timestamp("M") - me).dt.days
T["is_me"] = (cal <= 2).to_numpy()
dsub = T[(T["rk"] >= 0.90) & T["is_me"]].groupby("date")["gross_bp"].mean()
m, t, n = nwt(dsub.to_numpy())
rows.append({"selection": "(d) month-end, top decile", "gross_bp_per_trade": m,
             "nw_t": t, "dates": n, "trades_per_date": np.nan})

R = pd.DataFrame(rows)
R["cost_bp"] = COST
R["net_bp"] = R["gross_bp_per_trade"] - COST
R["gross_vs_cost"] = R["gross_bp_per_trade"] / COST
R["breakeven_cost_multiple"] = R["gross_bp_per_trade"] / COST
print("\n=== BEST-CASE SEAM-FADE BUTTERFLY, gross bp per trade vs 0.535 bp cost ===")
print(R.round(5).to_string(index=False))
R.to_csv(DATA / "adv_seam_bestcase_trade.csv", index=False)

print(f"\nex-post ceiling: mean |exit_fly| on the top-decile set = "
      f"{T.loc[T['rk']>=0.90,'exit_fly'].abs().mean():.4f} bp "
      f"({T.loc[T['rk']>=0.90,'exit_fly'].abs().mean()/COST:.3f}x cost) -- that is a "
      "PERFECT-DIRECTION bound, not an edge.")
