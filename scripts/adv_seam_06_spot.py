r"""End-to-end arithmetic spot check from the raw minute tape, plus the
seam-vs-control idio test the report did not run, plus a month-end recheck.
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

COST = 0.535
MIN_BONDS = 12
cache = CitiVeloTagCache()
panel = pd.read_parquet(DATA / "adv_seam_panel.parquet")
uni = pd.read_csv(DATA / "intraday_universe.csv")

# ------------------------------------------------------------ 1. SPOT CHECK
# pick a month-end date that MI01 covers, and the bond with the largest |idio|
mi_days = set(pd.to_datetime(pd.read_csv(DATA / "adv_mi01_days.csv").iloc[:, 0]))
cand = [d for d in panel["date"].unique()
        if pd.Timestamp(d) in mi_days
        and (pd.Timestamp(d).to_period("M").to_timestamp("M") - pd.Timestamp(d)).days <= 2]
D0 = pd.Timestamp(sorted(cand)[len(cand) // 2])
print(f"=== 1. ARITHMETIC SPOT CHECK on {D0.date()} (a month-end date in MI01) ===")

g = panel[panel["date"] == D0].dropna(subset=["seam", "ttm"]).sort_values("ttm")
y = g["seam"].to_numpy(float)
raw = g["ttm"].to_numpy(float)
x = (raw - raw.mean()) / raw.std()
A = np.column_stack([np.ones_like(x), x, x ** 2])
b, *_ = np.linalg.lstsq(A, y, rcond=None)
g = g.assign(idio=y - A @ b)
print(f"cross-section: {len(g)} bonds  level {y.mean():+.4f} bp  "
      f"idio sd {g['idio'].std(ddof=0):.4f} bp")

pick = g.loc[g["idio"].abs().idxmax()]
isin = pick["isin"]
print(f"\nbond with the largest |idio|: {isin} ({pick['cusip']}) ttm {pick['ttm']:.2f}")
print(f"  panel y15 {pick['y15']:.6f}%  y16 {pick['y16']:.6f}%  "
      f"seam {pick['seam']:+.4f} bp  idio {pick['idio']:+.4f} bp")

mi = cache.read(f"RATES.BOND.{isin}.YIELD", "MI01", "CLOSE").dropna()
mid = pd.DatetimeIndex(mi.index)
day = mi[mid.normalize() == D0]
dix = pd.DatetimeIndex(day.index)
w14 = day[(dix.hour == 14)]
w15 = day[(dix.hour == 15)]
print(f"\n  RAW MI01 tape, hour 14 window: {len(w14)} prints, last "
      f"{w14.index[-1]} = {float(w14.iloc[-1]):.6f}%")
print(f"      last three: {[(str(t)[11:16], round(float(v),6)) for t, v in w14.tail(3).items()]}")
print(f"  RAW MI01 tape, hour 15 window: {len(w15)} prints, last "
      f"{w15.index[-1]} = {float(w15.iloc[-1]):.6f}%")
print(f"      last three: {[(str(t)[11:16], round(float(v),6)) for t, v in w15.tail(3).items()]}")
hand_seam = (float(w15.iloc[-1]) - float(w14.iloc[-1])) * 100.0
print(f"\n  BY HAND from the minute tape: ({float(w15.iloc[-1]):.6f} - "
      f"{float(w14.iloc[-1]):.6f}) x 100 = {hand_seam:+.4f} bp")
print(f"  panel says {pick['seam']:+.4f} bp   -> "
      f"{'MATCH' if abs(hand_seam - pick['seam']) < 1e-6 else 'MISMATCH'}")

hr = cache.read(f"RATES.BOND.{isin}.YIELD", "HOURLY", "CLOSE").dropna()
print(f"  hourly bar stamped 14: {float(hr.loc[D0 + pd.Timedelta(hours=14)]):.6f}%  "
      f"stamped 15: {float(hr.loc[D0 + pd.Timedelta(hours=15)]):.6f}%")

# refit the cross-section with the hand value substituted, confirm the residual
y2 = g["seam"].to_numpy(float).copy()
y2[g.index.get_indexer([pick.name])[0]] = hand_seam
b2, *_ = np.linalg.lstsq(A, y2, rcond=None)
r2 = (y2 - A @ b2)[g.index.get_indexer([pick.name])[0]]
print(f"  refit residual with the hand value: {r2:+.4f} bp vs panel "
      f"{pick['idio']:+.4f} bp")
print(f"  |idio| / round trip = {abs(pick['idio'])/COST:.3f}x   "
      f"(this is the DAY'S LARGEST single-bond idio)")

# ------------------------------- 2. is the seam's idio dispersion special at all?
print("\n=== 2. SEAM vs CONTROL idio dispersion, paired by date ===")


def per_date_sd(col):
    rows = []
    for d, gg in panel.groupby("date", sort=True):
        gg = gg.dropna(subset=[col, "ttm"])
        if len(gg) < MIN_BONDS:
            continue
        yy = gg[col].to_numpy(float)
        rr = gg["ttm"].to_numpy(float)
        xx = (rr - rr.mean()) / max(1e-9, rr.std())
        AA = np.column_stack([np.ones_like(xx), xx, xx ** 2])
        bb, *_ = np.linalg.lstsq(AA, yy, rcond=None)
        rows.append({"date": d, "sd": float(np.std(yy - AA @ bb))})
    return pd.DataFrame(rows).set_index("date")["sd"]


S = pd.DataFrame({c: per_date_sd(c) for c in ("seam", "c1314", "c1415", "c1617")}).dropna()


def nw_t(v, lags=None):
    v = np.asarray(v, float)
    n = len(v)
    if lags is None:
        lags = int(np.floor(4 * (n / 100.0) ** (2.0 / 9.0)))
    e = v - v.mean()
    s = float(np.dot(e, e) / n)
    for L in range(1, lags + 1):
        s += 2.0 * (1.0 - L / (lags + 1.0)) * float(np.dot(e[L:], e[:-L]) / n)
    se = float(np.sqrt(max(s, 0.0) / n))
    return v.mean(), se, v.mean() / se


rows = []
for c in ("c1314", "c1415", "c1617"):
    d = (S["seam"] - S[c]).to_numpy()
    m, se, t = nw_t(d)
    rows.append({"vs": c, "seam_median": S["seam"].median(), "ctl_median": S[c].median(),
                 "mean_diff_bp": m, "nw_t": t, "ratio_median": S["seam"].median() / S[c].median()})
T = pd.DataFrame(rows)
print(T.round(4).to_string(index=False))
T.to_csv(DATA / "adv_seam_vs_controls_test.csv", index=False)
print("-> the seam's IDIO dispersion is the largest of the four, by 5-15%. "
      "The report compared mean|dy| (level-dominated) and called them indistinguishable.")

# --------------------------------------------------- 3. month-end idio recheck
print("\n=== 3. MONTH-END idio dispersion, independently ===")
dts = pd.DatetimeIndex(S.index)
me = pd.Series(dts).dt.to_period("M").dt.to_timestamp("M")
cal = (me.to_numpy() - dts.to_numpy()).astype("timedelta64[D]").astype(int)
is_me = pd.Series(cal <= 2, index=dts)
print(f"month-end dates {int(is_me.sum())}  ordinary {int((~is_me).sum())}")
print(f"median idio sd: month-end {S['seam'][is_me.to_numpy()].median():.4f} bp  "
      f"other {S['seam'][~is_me.to_numpy()].median():.4f} bp  ratio "
      f"{S['seam'][is_me.to_numpy()].median()/S['seam'][~is_me.to_numpy()].median():.3f}")
print(f"month-end idio sd / cost = "
      f"{S['seam'][is_me.to_numpy()].median()/COST:.3f}x")
lvl = panel.groupby("date")["seam"].mean()
print(f"month-end mean seam LEVEL {lvl[is_me.to_numpy()].mean():+.4f} bp  "
      f"other {lvl[~is_me.to_numpy()].mean():+.4f} bp")
m, se, t = nw_t((lvl[is_me.to_numpy()] - lvl[~is_me.to_numpy()].mean()).to_numpy())
print(f"  difference t (NW, month-end series vs other mean) = {t:+.2f}")
