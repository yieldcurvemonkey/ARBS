"""Adversarial pass 2: FALSE-DEAD check.

Is the holdings pipeline actually carrying information into this intraday panel, or is
DEAD manufactured by a broken join?  Positive control: at mark_hour=16 the intraday panel
should reproduce the daily study's own IC for active_w (-0.015 .. -0.022 at 1-5d).
Also asserts the lag semantics: row t must hold a holdings file stamped <= t-1 bd.
"""
from __future__ import annotations
import pathlib, sys
import numpy as np
import pandas as pd
from scipy import stats

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import etf_tsgrid_lib as L

DATA = L.DATA
m = L.load_matrices()
print("matrices: %d dates %s..%s, %d cusips" % (len(m.dates), m.dates.min().date(),
                                                m.dates.max().date(), len(m.cusips)))

# ---------------------------------------------------------------- holdings file sanity
act = pd.read_parquet(DATA / "fundfig_active_TLT.parquet")
print("\nfundfig_active_TLT cols:", list(act.columns))
print("dates %s..%s  n=%d" % (act.date.min().date(), act.date.max().date(), act.date.nunique()))
sub = act[act.cusip.isin(set(m.cusips))]
print("rows for panel cusips: %d over %d dates" % (len(sub), sub.date.nunique()))
hf = sub.groupby("date")["held"].mean()
print("held fraction among panel cusips: med %.3f p10 %.3f p90 %.3f" %
      (hf.median(), hf.quantile(.1), hf.quantile(.9)))
own = sub.loc[sub.held, "ownership"]
print("ownership among held: med %.4f p90 %.4f max %.4f" % (own.median(), own.quantile(.9), own.max()))
print("active_w among held: med %.6f sd %.6f" % (sub.loc[sub.held, "active_w"].median(),
                                                 sub.loc[sub.held, "active_w"].std()))

# ---------------------------------------------------------------- lag semantics assert
raw = L.build_signal_matrices(m, fund="TLT")
hd = pd.DatetimeIndex(np.sort(sub["date"].unique()))
A = raw["active_w"]
A1 = L.lag_matrix(A, 1)
# for a handful of dates, find which holdings date the lagged row corresponds to
piv = sub.pivot_table(index="date", columns="cusip", values="active_w", aggfunc="last")
piv = piv.reindex(columns=m.cusips)
bad = 0
checked = 0
rng = np.random.default_rng(7)
for di in rng.choice(np.arange(400, len(m.dates)), 60, replace=False):
    row = A1[di]
    fin = np.isfinite(row)
    if fin.sum() < 5:
        continue
    # which holdings date matches this row exactly?
    diffs = (piv.to_numpy() - (-row)[None, :])   # A = -ACT
    match = np.nanmax(np.abs(diffs), axis=1)
    j = int(np.nanargmin(match))
    src = piv.index[j]
    checked += 1
    if not (src <= m.dates[di] - pd.Timedelta(days=1)):
        bad += 1
        print("  LAG VIOLATION panel %s <- holdings %s" % (m.dates[di].date(), src.date()))
print("\nlag=1 semantics: %d/%d sampled rows source a holdings file stamped <= t-1 day"
      % (checked - bad, checked))

# ---------------------------------------------------------------- positive control IC
def spearman_ic(Z, FWD):
    out = []
    for d in range(Z.shape[0]):
        z, f = Z[d], FWD[d]
        ok = np.isfinite(z) & np.isfinite(f)
        if ok.sum() < 12 or np.unique(z[ok]).size < 5:
            continue
        out.append(stats.spearmanr(z[ok], f[ok]).statistic)
    return np.array(out)

rows = []
for h in (16, 15, 10):
    R = m.RES[h]
    for hor in (1, 5, 21, 63):
        F = np.full_like(R, np.nan)
        F[:-hor] = R[hor:] - R[:-hor]          # forward change in richness residual
        for s in ("active_w", "active_rel", "ownership", "bucket_hist_z", "not_held"):
            Z = L.lag_matrix(raw[s], 1)
            ic = spearman_ic(Z, F)
            if ic.size < 50:
                rows.append(dict(hour=h, hor=hor, signal=s, n=ic.size, ic=np.nan,
                                 t_naive=np.nan, t_nw=np.nan))
                continue
            rows.append(dict(hour=h, hor=hor, signal=s, n=ic.size, ic=float(ic.mean()),
                             t_naive=float(ic.mean() / (ic.std(ddof=1) / np.sqrt(ic.size))),
                             t_nw=float(L.newey_west_t(ic, max(1, hor)))))
ic = pd.DataFrame(rows)
ic.to_csv(DATA / "adv_ts_poscontrol_ic.csv", index=False)
print("\n--- positive control: mean cross-sectional Spearman IC, signal(lag1) vs forward d(resid) ---")
print(ic.to_string(index=False))
