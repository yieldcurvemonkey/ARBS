"""Adversarial pass 9: panel accounting, H1 seam, the time-of-day pond, early closes."""
from __future__ import annotations
import pathlib, sys
import numpy as np
import pandas as pd

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import etf_tsgrid_lib as L

DATA = L.DATA
p = pd.read_parquet(DATA / "tsgrid_intraday_panel.parquet")
print("panel rows %d  dates %d  cusips %d  hours %s"
      % (len(p), p.date.nunique(), p.cusip.nunique(), sorted(p.hour.unique())))
print("bonds priced per (date,hour): med %.1f" % p.groupby(["date", "hour"]).size().median())
print("early-close dates in panel: %d ; last-BD dates: %d"
      % (p.loc[p.early_close, "date"].nunique(), p.loc[p.is_last_bd, "date"].nunique()))
# are early closes DROPPED from the grid?  (they are flagged only)
print("early-close dates that are also last-BD: %d"
      % p.loc[p.early_close & p.is_last_bd, "date"].nunique())

# degenerate hourly dates flagged in pass 4
for d in ["2020-03-07", "2026-01-16", "2026-03-29"]:
    n = int((p.date == d).sum())
    print("  degenerate hourly date %s -> %d panel rows" % (d, n))

m = L.load_matrices()
legs = L.build_legs(m, step=1)
FLY = {h: L.fly_level(m, legs, h) for h in L.CLOCK_HOURS}

# ---------------------------------------------------------------- H1(a) the seam move
print("\n=== H1(a) 15:00 -> 16:00 seam, per bond ===")
seam = (m.Y[16] - m.Y[15]) * 100.0             # bp
ok = np.isfinite(seam)
print("bond-dates with both marks: %d ; pooled mean %.6f bp ; sd %.4f bp"
      % (ok.sum(), np.nanmean(seam), np.nanstd(seam)))
rows = []
for j, c in enumerate(m.cusips):
    v = seam[:, j][np.isfinite(seam[:, j])]
    if v.size < 100:
        continue
    rows.append(dict(cusip=c, n=v.size, mean_bp=float(v.mean()),
                     t_nw=float(L.newey_west_t(v, 5))))
sb = pd.DataFrame(rows)
print("bonds with >=100 obs: %d ; |t_nw|>2: %d (chance ~%.1f) ; median |mean| %.5f bp"
      % (len(sb), int((sb.t_nw.abs() > 2).sum()), 0.05 * len(sb), sb.mean_bp.abs().median()))
sb.to_csv(DATA / "adv_ts_h1a_seam.csv", index=False)

# richness level shift over the seam
rs = m.RES[16] - m.RES[15]
rows = []
for j, c in enumerate(m.cusips):
    v = rs[:, j][np.isfinite(rs[:, j])]
    if v.size < 100:
        continue
    rows.append(dict(cusip=c, n=v.size, mean_bp=float(v.mean()),
                     t_nw=float(L.newey_west_t(v, 5))))
rsb = pd.DataFrame(rows)
print("richness shift 15->16: bonds %d ; |t|>2: %d ; median |mean| %.5f bp"
      % (len(rsb), int((rsb.t_nw.abs() > 2).sum()), rsb.mean_bp.abs().median()))

# ---------------------------------------------------------------- the pond
print("\n=== the perfect-foresight pond by hour window ===")
rows = []
for i, h0 in enumerate(L.CLOCK_HOURS[:-1]):
    h1 = L.CLOCK_HOURS[i + 1]
    ret = -(FLY[h1] - FLY[h0]) * 100.0
    el = legs.valid & np.isfinite(FLY[h0]) & np.isfinite(FLY[h1])
    pf = L.perfect_foresight_per_date(ret, el, n=3)
    mv = np.abs(np.where(el, ret, np.nan))
    rows.append(dict(window="%02d->%02d" % (h0, h1), pond_bp=float(np.nanmean(pf)),
                     mean_abs_move=float(np.nanmean(mv)),
                     stale_at_h1=float(m.STALE[h1].mean()),
                     n_dates=int(np.isfinite(pf).sum())))
pond = pd.DataFrame(rows)
pond["pond_over_cost"] = pond.pond_bp / 0.7896
pond["ic_to_break_even"] = 0.7896 / pond.pond_bp
print(pond.round(4).to_string(index=False))
pond.to_csv(DATA / "adv_ts_pond.csv", index=False)
print("peak/trough %.3f" % (pond.pond_bp.max() / pond.pond_bp.min()))

# whole-session pond and the seam pond
for a, b in [(9, 16), (15, 16), (9, 17)]:
    ret = -(FLY[b] - FLY[a]) * 100.0
    el = legs.valid & np.isfinite(FLY[a]) & np.isfinite(FLY[b])
    pf = L.perfect_foresight_per_date(ret, el, n=3)
    print("  pond %02d->%02d = %.4f bp = %.3fx the 0.790bp round trip"
          % (a, b, np.nanmean(pf), np.nanmean(pf) / 0.7896))

# last-BD seam perfect foresight
ret = -(FLY[16] - FLY[15]) * 100.0
el = legs.valid & np.isfinite(FLY[15]) & np.isfinite(FLY[16])
pf = L.perfect_foresight_per_date(ret, el, n=3)
lb = m.is_last_bd & ~m.early_close
print("  last-BD seam pond (early closes excluded) = %.4f bp on %d days = %.3fx cost"
      % (np.nanmean(pf[lb]), int(np.isfinite(pf[lb]).sum()), np.nanmean(pf[lb]) / 0.7896))
print("  last-BD seam pond INCLUDING early closes  = %.4f bp on %d days"
      % (np.nanmean(pf[m.is_last_bd]), int(np.isfinite(pf[m.is_last_bd]).sum())))
