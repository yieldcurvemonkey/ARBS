"""Critic check: are the two numbers in fig1's annotation box the same quantity?"""
import sys
sys.path.append(r"C:\Users\chris\clee\ARBS")
sys.path.append(r"C:\Users\chris\clee\ARBS\notebooks\backtests\intraday_fed_hawk_dove")
sys.path.append(r"C:\Users\chris\clee\ARBS\notebooks\backtests\intraday_fed_hawk_dove\_event_study")

import numpy as np
from c_common import OFFSETS, cluster_ols, load_rank3, wide

ev, pl = load_rank3()


def gap(piv, meta, o):
    v = piv[o].to_numpy()
    hk = (meta["stance_sign"] == 1).to_numpy().astype(float)
    ok = np.isfinite(v)
    X = np.column_stack([np.ones(ok.sum()), hk[ok]])
    r = cluster_ols(v[ok], X, meta["date"].to_numpy()[ok], names=["const", "hawk"])
    return r["hawk"]["coef"], r["hawk"]["t"], r["n"]


def excess(piv, meta, ppiv, pmeta, o):
    yr = piv[o].to_numpy() * meta["stance_sign"].to_numpy()
    yp = ppiv[o].to_numpy() * pmeta["stance_sign"].to_numpy()
    y = np.concatenate([yr, yp])
    real = np.concatenate([np.ones(len(yr)), np.zeros(len(yp))])
    day = np.concatenate([meta["date"].astype(str).to_numpy(), pmeta["date"].astype(str).to_numpy()])
    ok = np.isfinite(y)
    X = np.column_stack([np.ones(ok.sum()), real[ok]])
    r = cluster_ols(y[ok], X, day[ok], names=["const", "is_real"])
    return r["is_real"]["coef"], r["is_real"]["t"], r["n"]


def gap_did(piv, meta, ppiv, pmeta, o):
    """The DiD of the HAWK-DOVE GAP: (hawk-dove | real) - (hawk-dove | placebo)."""
    yr, yp = piv[o].to_numpy(), ppiv[o].to_numpy()
    hr = (meta["stance_sign"] == 1).to_numpy().astype(float)
    hp = (pmeta["stance_sign"] == 1).to_numpy().astype(float)
    y = np.concatenate([yr, yp])
    h = np.concatenate([hr, hp])
    real = np.concatenate([np.ones(len(yr)), np.zeros(len(yp))])
    day = np.concatenate([meta["date"].astype(str).to_numpy(), pmeta["date"].astype(str).to_numpy()])
    ok = np.isfinite(y)
    X = np.column_stack([np.ones(ok.sum()), h[ok], real[ok], (h * real)[ok]])
    r = cluster_ols(y[ok], X, day[ok], names=["const", "hawk", "real", "hawk_x_real"])
    return r["hawk_x_real"]["coef"], r["hawk_x_real"]["t"], r["n"]


for name, sub in (("NON-OVERLAPPING (fig1)", ev[~ev["is_overlapping"]]), ("ALL (fig1b)", ev)):
    piv, meta = wide(sub)
    ppiv, pmeta = wide(pl)
    g, tg, ng = gap(piv, meta, 240)
    e, te, ne = excess(piv, meta, ppiv, pmeta, 240)
    d, td, nd = gap_did(piv, meta, ppiv, pmeta, 240)
    print(f"\n{name}")
    print(f"  hawk-dove GAP           = {g:+.4f} bp  t={tg:+.4f}  n={ng}")
    print(f"  SIGNED-COMPOSITE excess = {e:+.4f} bp  t={te:+.4f}  n={ne}   <- what the box calls 'the excess'")
    print(f"  GAP excess (true DiD)   = {d:+.4f} bp  t={td:+.4f}  n={nd}   <- the placebo-adjusted version of the GAP")
    print(f"  ratio gap/composite     = {g/e:.2f}x")
