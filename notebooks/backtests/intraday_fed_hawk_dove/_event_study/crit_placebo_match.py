"""Critic check: is fig1's placebo band drawn from the SAME book as its 224 clean events?"""
import sys
sys.path.append(r"C:\Users\chris\clee\ARBS")
sys.path.append(r"C:\Users\chris\clee\ARBS\notebooks\backtests\intraday_fed_hawk_dove")
sys.path.append(r"C:\Users\chris\clee\ARBS\notebooks\backtests\intraday_fed_hawk_dove\_event_study")

import numpy as np
import pandas as pd
from c_common import HERE, OFFSETS, cluster_mean_se, cluster_ols, load_rank3, wide

ev, pl = load_rank3()
print("real rows", ev.shape, "placebo rows", pl.shape)
print("ev cols:", list(ev.columns))
print("pl cols:", list(pl.columns))

clean = ev[~ev["is_overlapping"]]
print("\nclean signed events:", clean["event_id"].nunique(),
      " days:", clean["date"].nunique())
print("all signed events  :", ev["event_id"].nunique(), " days:", ev["date"].nunique())
print("placebo pseudo     :", pl["event_id"].nunique(), " days:", pl["date"].nunique())

if "parent_event_id" in pl.columns:
    ids = set(clean["event_id"].unique())
    sub = pl[pl["parent_event_id"].isin(ids)]
    print("\nplacebos whose PARENT is one of the 224 clean events:",
          sub["event_id"].nunique(), " on days:", sub["date"].nunique())
    print("placebos whose parent is an OVERLAPPING event      :",
          pl[~pl["parent_event_id"].isin(ids)]["event_id"].nunique())

    # what the band / excess looks like restricted vs full
    for name, plx in (("FULL placebo (what fig1 draws)", pl),
                      ("PARENT-MATCHED placebo (224 parents)", sub)):
        ppiv, pmeta = wide(plx)
        piv, meta = wide(clean)
        for o in (240,):
            st = cluster_mean_se(ppiv[o].to_numpy(), pmeta["date"].to_numpy())
            m, se = st["mean"], st["se"]
            yr = piv[o].to_numpy() * meta["stance_sign"].to_numpy()
            yp = ppiv[o].to_numpy() * pmeta["stance_sign"].to_numpy()
            y = np.concatenate([yr, yp])
            real = np.concatenate([np.ones(len(yr)), np.zeros(len(yp))])
            day = np.concatenate([meta["date"].astype(str).to_numpy(),
                                  pmeta["date"].astype(str).to_numpy()])
            ok = np.isfinite(y)
            X = np.column_stack([np.ones(ok.sum()), real[ok]])
            r = cluster_ols(y[ok], X, day[ok], names=["const", "is_real"])
            print(f"\n{name}: n_pseudo={plx['event_id'].nunique()}")
            print(f"   placebo pooled mean at +240 = {m:+.4f} bp, se = {se:.4f}  (2SE band half-width {2*se:.3f})")
            print(f"   excess (real - placebo) at +240 = {r['is_real']['coef']:+.4f} bp  t = {r['is_real']['t']:+.3f}")
