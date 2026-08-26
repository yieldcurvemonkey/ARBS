import sys
sys.path.append(r"C:\Users\chris\clee\ARBS")
import pandas as pd, numpy as np
BASE = r"C:\Users\chris\clee\ARBS\notebooks\backtests\intraday_fed_hawk_dove"
ev = pd.read_parquet(BASE + r"\_event_study\event_paths.parquet")
p = ev[(ev.contract_rank == 3)].dropna(subset=["price"])
# distinct price increments actually observed
u = np.sort(p.price.unique())
d = np.diff(u)
d = d[d > 1e-9]
print("rank3 distinct prices:", len(u))
print("smallest observed price gap: %.6f  (=%.3f bp)" % (d.min(), d.min() * 100))
vc = pd.Series(np.round(d, 6)).value_counts().head(6)
print("most common gaps (index pts -> bp):")
for k, v in vc.items():
    print(f"   {k:.4f} -> {k*100:.2f} bp   count {v}")
# same for rank 1 (front) for contrast
p1 = ev[(ev.contract_rank == 1)].dropna(subset=["price"])
u1 = np.sort(p1.price.unique()); d1 = np.diff(u1); d1 = d1[d1 > 1e-9]
print("rank1 smallest gap: %.6f (=%.3f bp)" % (d1.min(), d1.min() * 100))
# per-event 5-min move distribution: how many are exactly 0
piv = p.pivot_table(index="event_id", columns="offset_min", values="rate_bp")
m5 = (piv[5] - piv[0]).dropna()
print("\n5-min rate moves: n=%d  frac exactly 0 = %.3f  frac |move|<=0.5bp = %.3f  std=%.3f"
      % (len(m5), (m5 == 0).mean(), (m5.abs() <= 0.5).mean(), m5.std()))
