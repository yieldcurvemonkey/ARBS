"""Adversarial pass 10: the report's H1(a) tests a FLY, which cancels the level.

Is there a systematic hour-by-hour drift in the OUTRIGHT long-end yield, and is the
15:00->16:00 hour special?  If it is, the report's "pooled mean seam move +0.00000 bp,
0 of 63 bonds significant" is a fact about the butterfly, not about the 15:00 cash mark
against the 16:00 NAV strike -- which is what H1 claims to test.
"""
from __future__ import annotations
import pathlib, sys
import numpy as np
import pandas as pd

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import etf_tsgrid_lib as L

DATA = L.DATA
m = L.load_matrices()
legs = L.build_legs(m, step=1)
FLY = {h: L.fly_level(m, legs, h) for h in L.CLOCK_HOURS}
elig = legs.valid & np.isfinite(FLY[15]) & np.isfinite(FLY[16])

rows = []
for i, h0 in enumerate(L.CLOCK_HOURS[:-1]):
    h1 = L.CLOCK_HOURS[i + 1]
    d = (m.Y[h1] - m.Y[h0]) * 100.0
    xdate = np.nanmean(d, axis=1)                     # cross-sectional mean per date
    nsig = 0
    for j in range(d.shape[1]):
        v = d[:, j][np.isfinite(d[:, j])]
        if v.size >= 200 and abs(L.newey_west_t(v, 1)) > 2:
            nsig += 1
    fl = -(FLY[h1] - FLY[h0]) * 100.0
    fl = np.where(elig, fl, np.nan)
    rows.append(dict(window="%02d->%02d" % (h0, h1),
                     outright_mean_bp=float(np.nanmean(d)),
                     outright_sd_bp=float(np.nanstd(d)),
                     outright_t_on_dates=float(L.newey_west_t(xdate, 5)),
                     bonds_t_gt2=nsig,
                     fly_mean_bp=float(np.nanmean(fl)),
                     fly_t_on_dates=float(L.newey_west_t(np.nanmean(fl, axis=1), 5))))
t = pd.DataFrame(rows)
t.to_csv(DATA / "adv_ts_hourly_drift.csv", index=False)
print("=== OUTRIGHT yield drift by hour window (94-97 bonds, 1,682 dates) ===")
print(t.round(4).to_string(index=False))
print("\nfull-session 09->17 outright mean %.4f bp (t %.2f)"
      % (np.nanmean((m.Y[17] - m.Y[9]) * 100.0),
         L.newey_west_t(np.nanmean((m.Y[17] - m.Y[9]) * 100.0, axis=1), 5)))
print("overnight 17(t) -> 09(t+1) outright mean %.4f bp"
      % np.nanmean((m.Y[9][1:] - m.Y[17][:-1]) * 100.0))

# sign of the significant bonds in the seam hour
d = (m.Y[16] - m.Y[15]) * 100.0
sg = []
for j in range(d.shape[1]):
    v = d[:, j][np.isfinite(d[:, j])]
    if v.size >= 200:
        sg.append((float(v.mean()), float(L.newey_west_t(v, 1))))
sg = pd.DataFrame(sg, columns=["mean_bp", "t"])
print("\nseam hour per-bond: %d bonds, %d with |t|>2, of those %d negative"
      % (len(sg), int((sg.t.abs() > 2).sum()),
         int(((sg.t.abs() > 2) & (sg.mean_bp < 0)).sum())))

# is the drift a month-end / last-BD thing?
lb = m.is_last_bd & ~m.early_close
print("seam outright mean: all days %.4f bp | last-BD %.4f bp | other %.4f bp"
      % (np.nanmean(d), np.nanmean(d[lb]), np.nanmean(d[~m.is_last_bd])))
