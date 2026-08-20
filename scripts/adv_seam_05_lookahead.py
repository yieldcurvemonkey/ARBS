r"""Lookahead audit + independent replication of the winning holdings cell +
multiple-testing null + FOMC flag reconciliation.
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


def nw_t(x, lags=None):
    v = pd.Series(x).dropna().to_numpy(float)
    n = len(v)
    if n < 8:
        return np.nan, np.nan, np.nan, n
    if lags is None:
        lags = int(np.floor(4 * (n / 100.0) ** (2.0 / 9.0)))
    e = v - v.mean()
    s = float(np.dot(e, e) / n)
    for L in range(1, max(1, lags) + 1):
        if L >= n:
            break
        s += 2.0 * (1.0 - L / (lags + 1.0)) * float(np.dot(e[L:], e[:-L]) / n)
    se = float(np.sqrt(max(s, 0.0) / n))
    return float(v.mean()), se, (v.mean() / se if se > 0 else np.nan), n


panel = pd.read_parquet(DATA / "adv_seam_panel.parquet")
panel["cusip"] = panel["cusip"].astype(str)

# idio seam, deg 2, my own fit
rows = []
for d, g in panel.groupby("date", sort=True):
    g = g.dropna(subset=["seam", "ttm"])
    if len(g) < MIN_BONDS:
        continue
    y = g["seam"].to_numpy(float)
    raw = g["ttm"].to_numpy(float)
    x = (raw - raw.mean()) / max(1e-9, raw.std())
    A = np.column_stack([np.ones_like(x), x, x ** 2])
    b, *_ = np.linalg.lstsq(A, y, rcond=None)
    o = g[["date", "cusip", "ttm", "y15", "cpn"]].copy()
    o["idio_seam"] = y - A @ b
    rows.append(o)
obs = pd.concat(rows, ignore_index=True)
print(f"idio_seam obs: {len(obs):,} on {obs['date'].nunique()} dates")

# --------------------------------------------------------- 1. EXEC LAG AUDIT
act = pd.read_parquet(DATA / "fundfig_active_TLT.parquet")
act["date"] = pd.to_datetime(act["date"])
act["cusip"] = act["cusip"].astype(str)
act = act[act["date"] >= panel["date"].min() - pd.Timedelta(days=10)]

dates = np.sort(act["date"].unique())
nxt = {d: (dates[i + 1] if i + 1 < len(dates) else pd.NaT) for i, d in enumerate(dates)}
a1 = act.copy()
a1["trade_date"] = a1["date"].map(nxt)
a1 = a1[a1["trade_date"].notna()]
gap = (pd.to_datetime(a1["trade_date"]) - a1["date"]).dt.days
print("\n=== 1. EXEC LAG AUDIT (holdings as_of -> trade date), exec_lag=1 ===")
print("calendar-day gap distribution:")
print(gap.value_counts().sort_index().head(10).to_string())
print("min gap (days):", int(gap.min()), " -> strictly positive:", bool((gap > 0).all()))
bd = np.busday_count(a1["date"].values.astype("datetime64[D]"),
                     pd.to_datetime(a1["trade_date"]).values.astype("datetime64[D]"))
print("business-day gap: min", int(bd.min()), "median", int(np.median(bd)),
      "frac >=1:", float((bd >= 1).mean()))

# Do the holdings dates actually precede the mark dates they get joined to?
j = obs.merge(a1[["date", "trade_date", "cusip", "w_f", "active_w", "ownership", "held"]]
              .rename(columns={"date": "asof_date", "trade_date": "date"}),
              on=["date", "cusip"], how="inner")
print(f"joined bond-dates: {len(j):,} on {j['date'].nunique()} dates")
print("asof_date STRICTLY before mark date on all rows:",
      bool((j["asof_date"] < j["date"]).all()))
print("max asof_date:", j["asof_date"].max(), " max mark date:", j["date"].max())

# ------------------------------- 2. independent replication of the winning cell
# richness residual at the 15:00 mark, my own robust-free OLS cubic + coupon
res = []
for d, g in obs.groupby("date", sort=True):
    g = g.dropna(subset=["y15", "ttm", "cpn"])
    if len(g) < MIN_BONDS:
        continue
    y = g["y15"].to_numpy(float) * 100.0
    t = g["ttm"].to_numpy(float)
    t = (t - t.mean()) / max(1e-9, t.std())
    c = g["cpn"].to_numpy(float)
    c = (c - c.mean()) / max(1e-9, c.std())
    A = np.column_stack([np.ones_like(t), t, t ** 2, t ** 3, c])
    b, *_ = np.linalg.lstsq(A, y, rcond=None)
    o = g[["date", "cusip"]].copy()
    o["resid_bp"] = y - A @ b
    res.append(o)
rich = pd.concat(res, ignore_index=True)
print(f"\nmy 15:00 richness residual: {len(rich):,} obs, sd {rich['resid_bp'].std():.3f} bp")

j = j.merge(rich, on=["date", "cusip"], how="left")


def z(s):
    sd = s.std()
    return (s - s.mean()) / sd if sd and np.isfinite(sd) and sd > 0 else s * np.nan


print("\n=== 2. INDEPENDENT FAMA-MACBETH REPLICATION (exec_lag=1) ===")
out = []
for sig in ("w_f", "active_w", "ownership"):
    for ctrl in (False, True):
        m = j.dropna(subset=["idio_seam", sig] + (["resid_bp"] if ctrl else []))
        m = m.copy()
        m["zs"] = m.groupby("date")[sig].transform(z)
        if ctrl:
            m["zr"] = m.groupby("date")["resid_bp"].transform(z)
        coefs = []
        for d, g in m.groupby("date", sort=True):
            g = g.dropna(subset=["zs"] + (["zr"] if ctrl else []))
            if len(g) < 15:
                continue
            cols = [np.ones(len(g)), g["zs"].to_numpy(float)]
            if ctrl:
                cols.append(g["zr"].to_numpy(float))
            X = np.column_stack(cols)
            if np.linalg.matrix_rank(X) < X.shape[1]:
                continue
            b, *_ = np.linalg.lstsq(X, g["idio_seam"].to_numpy(float), rcond=None)
            coefs.append({"date": d, "b": b[1]})
        C = pd.DataFrame(coefs)
        mm, se, t, n = nw_t(C["b"])
        out.append({"signal": sig, "richness_ctrl": ctrl, "bp_per_1sd": mm,
                    "nw_t": t, "dates": n, "abs_vs_cost": abs(mm) / COST})
O = pd.DataFrame(out)
print(O.round(5).to_string(index=False))
O.to_csv(DATA / "adv_seam_fm_replication.csv", index=False)

theirs = pd.read_csv(DATA / "seam_holdings_fama_macbeth.csv")
tw = theirs[(theirs["signal"] == "w_f") & (theirs["exec_lag"] == 1)
            & (theirs["spec"] == "+ richness control")
            & (theirs["y"].str.startswith("15:00"))]
print("\ntheir w_f / +richness / lag1 / seam cell:")
print(tw[["bp_per_1sd", "nw_t", "dates"]].round(5).to_string(index=False))

# --------------------------------------------- 3. multiple-testing null, measured
print("\n=== 3. MULTIPLE TESTING ===")
n_cells = len(theirs)
print(f"holdings cells in their csv: {n_cells}")
rng = np.random.default_rng(7)
for N in (n_cells, 236):
    mx = np.abs(rng.standard_normal((20000, N))).max(axis=1)
    print(f"  N={N:>3d} independent: E[max|t|]={mx.mean():.3f}  "
          f"p95={np.quantile(mx,0.95):.3f}  sqrt(2 ln N)={np.sqrt(2*np.log(N)):.3f}")
print(f"  their largest |NW t| = {theirs['nw_t'].abs().max():.3f}")

# a real null: shuffle the signal WITHIN each date, keeping the panel structure
print("\n  measured null: signal permuted within date, 200 draws of the max |t| "
      "over the 3 signals x 2 specs grid re-run here")
m = j.dropna(subset=["idio_seam", "w_f", "resid_bp"]).copy()
m["zr"] = m.groupby("date")["resid_bp"].transform(z)
maxts = []
for k in range(200):
    mm2 = m.copy()
    mm2["zs"] = (mm2.groupby("date")["w_f"]
                    .transform(lambda s: pd.Series(rng.permutation(s.to_numpy()), index=s.index)))
    mm2["zs"] = mm2.groupby("date")["zs"].transform(z)
    coefs = []
    for d, g in mm2.groupby("date", sort=True):
        g = g.dropna(subset=["zs", "zr"])
        if len(g) < 15:
            continue
        X = np.column_stack([np.ones(len(g)), g["zs"].to_numpy(float), g["zr"].to_numpy(float)])
        b, *_ = np.linalg.lstsq(X, g["idio_seam"].to_numpy(float), rcond=None)
        coefs.append(b[1])
    _, _, t, _ = nw_t(pd.Series(coefs))
    maxts.append(abs(t))
maxts = np.array(maxts)
print(f"  permutation |t| for ONE cell: mean {maxts.mean():.3f}  p95 "
      f"{np.quantile(maxts,0.95):.3f}  max {maxts.max():.3f}")
print(f"  fraction of permutations with |t| >= 2.473: {(maxts>=2.473).mean():.3f}")
pd.DataFrame({"perm_abs_t": maxts}).to_csv(DATA / "adv_seam_permutation_null.csv", index=False)

# ------------------------------------------------ 4. FOMC flag reconciliation
from SDRUtils.analytics.fomc import load_fomc_schedule  # noqa: E402

fo = pd.DatetimeIndex(sorted(set(pd.to_datetime(
    load_fomc_schedule("USD-SOFR-1D")["effective_date"]))))
pd_dates = pd.DatetimeIndex(sorted(panel["date"].unique()))
inrange = fo[(fo >= pd_dates.min()) & (fo <= pd_dates.max())]
print("\n=== 4. FOMC FLAG RECONCILIATION ===")
print(f"registry meetings in panel span: {len(inrange)}")
print(f"of which present in the clean panel: {int(pd_dates.isin(inrange).sum())}")
missing = [d for d in inrange if d not in set(pd_dates)]
print(f"missing from clean panel: {len(missing)} -> {[str(d.date()) for d in missing]}")
raw = pd.read_parquet(DATA / "seam_panel.parquet")
raw_dates = set(pd.DatetimeIndex(raw["date"].unique()))
print("of the missing, present in the RAW (pre-early-close-drop) panel:",
      [str(d.date()) for d in missing if d in raw_dates])
print("panel span:", pd_dates.min().date(), "..", pd_dates.max().date(),
      " (registry earliest", fo.min().date(), ")")
