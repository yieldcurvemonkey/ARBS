"""Critic check: how big is the PRE-event wander relative to the post-event 'effect'?"""
import sys
sys.path.append(r"C:\Users\chris\clee\ARBS")
sys.path.append(r"C:\Users\chris\clee\ARBS\notebooks\backtests\intraday_fed_hawk_dove")
sys.path.append(r"C:\Users\chris\clee\ARBS\notebooks\backtests\intraday_fed_hawk_dove\_event_study")

import numpy as np
import pandas as pd
from c_common import OFFSETS, arm_paths, load_rank3, wide

ev, pl = load_rank3()
PRE = [o for o in OFFSETS if o < 0]

for name, sub in (("fig1 non-overlapping", ev[~ev["is_overlapping"]]), ("fig1b all", ev)):
    piv, meta = wide(sub)
    h = arm_paths(piv, meta, 1)
    d = arm_paths(piv, meta, -1)
    gap_pre = (h["mean"] - d["mean"]).loc[PRE]
    gap_post = (h["mean"] - d["mean"]).loc[[o for o in OFFSETS if o > 0]]
    print(f"\n=== {name} ===")
    print("  hawk arm  pre-event range (bp):", f"{h['mean'].loc[PRE].min():+.3f} .. {h['mean'].loc[PRE].max():+.3f}")
    print("  dove arm  pre-event range (bp):", f"{d['mean'].loc[PRE].min():+.3f} .. {d['mean'].loc[PRE].max():+.3f}")
    print("  hawk-dove GAP pre-event  (bp):", f"{gap_pre.min():+.3f} .. {gap_pre.max():+.3f}  |max| = {gap_pre.abs().max():.3f}")
    print("  hawk-dove GAP post-event (bp):", f"{gap_post.min():+.3f} .. {gap_post.max():+.3f}  |max| = {gap_post.abs().max():.3f}")
    print("  gap at +240 (the headline)   :", f"{(h['mean']-d['mean']).loc[240]:+.3f}")
    print("  ratio  max|pre gap| / |gap@240| :", f"{gap_pre.abs().max()/abs((h['mean']-d['mean']).loc[240]):.2f}x")
    print("  dove arm n priced by offset:", d["n"].loc[[-120, -60, 0, 240, 300]].to_dict())
