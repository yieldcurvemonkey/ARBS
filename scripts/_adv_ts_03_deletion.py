"""Adversarial pass 3: what IS `deletion` orthogonalised?

The report's only null-clearing cell is `deletion` orth=True, and `deletion` raw never
appears in the grid at all.  Hypothesis: with <=5 distinct raw levels, orthogonalize()
returns z - mean - b*RESZ, whose cross-sectional VARIATION is dominated by -b*RESZ.  If
so the t=4.58 is the richness control passing through orthogonalize() with a sign, not a
calendar effect -- a mechanical identification, sharper than the report's account.
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
raw = L.build_signal_matrices(m, fund="TLT")
DEL = raw["deletion"]

print("deletion raw: distinct values overall =", np.unique(DEL[np.isfinite(DEL)]))
nd = np.array([np.unique(r[np.isfinite(r)]).size for r in DEL])
print("distinct per date: med %d max %d  (MIN_DISTINCT_SCORES=%d)" %
      (np.median(nd), nd.max(), L.MIN_DISTINCT_SCORES))
print("fraction of bond-dates with deletion != 0: %.4f" % np.nanmean(DEL != 0))

MARK, ENTRY, HOLD, EXIT, LAG = 15, 15, 1, 15, 1
Ml = L.lag_matrix(DEL, LAG)
Zbase = L._xsec_z(Ml)
CTRL = m.RESZ[MARK]
Z = L.orthogonalize(Zbase, CTRL)

# (1) how much of the orthogonalised score is just -b*richness?
r2, frac0, bs = [], [], []
for d in range(Z.shape[0]):
    z, c, zb = Z[d], CTRL[d], Zbase[d]
    ok = np.isfinite(z) & np.isfinite(c)
    if ok.sum() < 20:
        continue
    r2.append(stats.spearmanr(z[ok], c[ok]).statistic)
    x = c[ok] - c[ok].mean()
    b = float(x @ (zb[ok] - zb[ok].mean())) / float(x @ x)
    bs.append(b)
    frac0.append(float((Ml[d][ok] == 0).mean()))
r2 = np.array(r2); bs = np.array(bs); frac0 = np.array(frac0)
print("\nSpearman(deletion-orth score, RESZ) per date: med %.4f  |med| %.4f  p5 %.3f p95 %.3f"
      % (np.median(r2), np.median(np.abs(r2)), np.percentile(r2, 5), np.percentile(r2, 95)))
print("regression slope b of deletion_z on RESZ: med %.4f  sign +%.2f" % (np.median(bs), (bs > 0).mean()))
print("share of bonds with deletion==0 on a date: med %.3f" % np.median(frac0))

# (2) of the bonds actually SELECTED at that cell, how many have deletion == 0?
elig = (L.build_legs(m, step=1).valid & np.isfinite(L.fly_level(m, L.build_legs(m, step=1), MARK))
        & np.isfinite(L.fly_level(m, L.build_legs(m, step=1), ENTRY)))
perm = np.random.default_rng(L.TIE_SEED).permutation(m.T.shape[1]).astype(float)
sel = L.select(Z, elig, n=3, rng_perm=perm)
rows = np.where(sel.usable)[0]
picked = np.concatenate([sel.top[rows].ravel(), sel.bot[rows].ravel()])
prows = np.repeat(rows, 3)
prows = np.concatenate([prows, prows])
dv = Ml[prows, picked]
print("\nselected legs: %d, of which deletion==0: %.4f" % (dv.size, float(np.mean(dv == 0))))
print("  top legs deletion==0: %.4f   bot legs deletion==0: %.4f"
      % (float(np.mean(Ml[np.repeat(rows,3), sel.top[rows].ravel()] == 0)),
         float(np.mean(Ml[np.repeat(rows,3), sel.bot[rows].ravel()] == 0))))

# (3) is the cell's daily P&L the richness control's daily P&L?
legs = L.build_legs(m, step=1)
FLY = {h: L.fly_level(m, legs, h) for h in L.CLOCK_HOURS}
COST = L.package_cost_bp(m, legs, anchor="measured")
fe = FLY[EXIT]
sh = np.full_like(fe, np.nan); sh[:-HOLD] = fe[HOLD:]
ret = -(sh - FLY[ENTRY]) * 100.0
g_del, c_del, n_del = L.cell_pnl(ret, COST, sel)

sel_res = L.select(m.RESZ[MARK], elig, n=3, rng_perm=perm)
g_res, _, n_res = L.cell_pnl(ret, COST, sel_res)

fin = np.isfinite(g_del)
print("\nRE-COMPUTED deletion-orth cell mark15/entry15/hold1/exit15 lag1:")
print("  n_dates %d  n_trades %d  gross %.6f bp  HAC t %.3f  cost %.4f  breakeven %.4fx"
      % (fin.sum(), n_del.sum(), np.average(g_del[fin], weights=n_del[fin]),
         L.newey_west_t(g_del, 1), np.average(c_del[fin], weights=n_del[fin]),
         np.average(g_del[fin], weights=n_del[fin]) / np.average(c_del[fin], weights=n_del[fin])))
both = np.isfinite(g_del) & np.isfinite(g_res)
print("  corr(deletion-orth daily pnl, richness-control daily pnl) = %.4f on %d dates"
      % (np.corrcoef(g_del[both], g_res[both])[0, 1], both.sum()))
print("  overlap of selected legs with the richness control's legs: top %.3f bot %.3f"
      % (float(np.mean([len(set(sel.top[d]) & set(sel_res.top[d])) / 3 for d in rows])),
         float(np.mean([len(set(sel.bot[d]) & set(sel_res.bot[d])) / 3 for d in rows]))))

out = pd.DataFrame(dict(metric=["spearman_score_vs_resz_med", "sel_legs_deletion_zero_frac",
                                "corr_pnl_vs_richness_control", "gross_bp", "hac_t",
                                "cost_bp", "breakeven_x"],
                        value=[float(np.median(r2)), float(np.mean(dv == 0)),
                               float(np.corrcoef(g_del[both], g_res[both])[0, 1]),
                               float(np.average(g_del[fin], weights=n_del[fin])),
                               float(L.newey_west_t(g_del, 1)),
                               float(np.average(c_del[fin], weights=n_del[fin])),
                               float(np.average(g_del[fin], weights=n_del[fin]) /
                                     np.average(c_del[fin], weights=n_del[fin]))]))
out.to_csv(DATA / "adv_ts_deletion_orth_dissection.csv", index=False)
print(out.to_string(index=False))
