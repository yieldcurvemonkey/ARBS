"""Critic check: the hawk-dove GAP DiD for fig1, using the PARENT-MATCHED placebo."""
import sys
sys.path.append(r"C:\Users\chris\clee\ARBS")
sys.path.append(r"C:\Users\chris\clee\ARBS\notebooks\backtests\intraday_fed_hawk_dove")
sys.path.append(r"C:\Users\chris\clee\ARBS\notebooks\backtests\intraday_fed_hawk_dove\_event_study")

import numpy as np
from c_common import cluster_ols, load_rank3, wide

ev, pl = load_rank3()
clean = ev[~ev["is_overlapping"]]
ids = set(clean["event_id"].unique())
pl_match = pl[pl["parent_event_id"].isin(ids)]


def gap_did(piv, meta, ppiv, pmeta, o):
    yr, yp = piv[o].to_numpy(), ppiv[o].to_numpy()
    hr = (meta["stance_sign"] == 1).to_numpy().astype(float)
    hp = (pmeta["stance_sign"] == 1).to_numpy().astype(float)
    y = np.concatenate([yr, yp]); h = np.concatenate([hr, hp])
    real = np.concatenate([np.ones(len(yr)), np.zeros(len(yp))])
    day = np.concatenate([meta["date"].astype(str).to_numpy(), pmeta["date"].astype(str).to_numpy()])
    ok = np.isfinite(y)
    X = np.column_stack([np.ones(ok.sum()), h[ok], real[ok], (h * real)[ok]])
    r = cluster_ols(y[ok], X, day[ok], names=["const", "hawk", "real", "hxr"])
    return r["hxr"]["coef"], r["hxr"]["t"], r["n"]


piv, meta = wide(clean)
for lab, p in (("FULL placebo book (2,931 signed)", pl), ("PARENT-MATCHED placebo", pl_match)):
    ppiv, pmeta = wide(p)
    print(f"\n{lab}:  n_signed_pseudo = {len(ppiv)}")
    for o in (30, 240, 300):
        c, t, n = gap_did(piv, meta, ppiv, pmeta, o)
        print(f"   gap DiD at {o:+4d} min = {c:+.4f} bp   t = {t:+.3f}   n = {n}")
