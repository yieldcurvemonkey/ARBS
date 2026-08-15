"""Pin the CURVE/FLY traded-level / mid / deviation_bps relation.

Checker validated on OUTRIGHT first (known answer: dev == (fr*100 - mid_pct)*100
EXACT) -- see wfstr06: 7296/7296 exact when the grid row's effective_date and
maturity_date both equal the leg's.

The mid is built with an orientation I CONTROL (canonical expiration sort), so a
wrong traded orientation does NOT cancel against it: it shows up as ~2x the
spread, not as 2x the deviation.
"""
import os, sys, warnings
os.environ.setdefault('ARBS_SUPABASE_ENABLED', '0')
sys.path.insert(0, '.')
warnings.filterwarnings('ignore')
from SDRUtils._swappulse_scripts.ingest_usdswaps_tape import resolve_pg_url
import psycopg2
import pandas as pd
import numpy as np

KIND = sys.argv[1] if len(sys.argv) > 1 else 'CURVE'
NL = 2 if KIND == 'CURVE' else 3

conn = psycopg2.connect(resolve_pg_url())
conn.set_session(readonly=True)

SQL = """
WITH u AS (
  SELECT package_id, as_of_date, curve_timestamp, rate_index, deviation_bps,
         dealer_direction, dealer_sign, n_legs, structure_dv01, tau_bps,
         mid_bias_bps, special_tenor_type, venue_class
  FROM arbs_dd_unit_v1
  WHERE kind=%(kind)s AND rule='RATE_VS_MID' AND exclusion_reason IS NULL
    AND n_legs=%(nl)s AND curve_timestamp IS NOT NULL
    AND deviation_bps IS NOT NULL
    AND as_of_date >= %(d0)s AND as_of_date < %(d1)s
), l AS (
  SELECT u.package_id, u.as_of_date, u.deviation_bps, u.dealer_direction,
         u.dealer_sign, u.rate_index, u.curve_timestamp, u.tau_bps,
         u.mid_bias_bps, u.venue_class,
         g.fixed_rate::float8 AS fr, m.mid_pct, g.tenor_label,
         g.tenor_years::float8 AS ty, g.forward_start_years::float8 AS fsy,
         row_number() OVER (PARTITION BY u.package_id, u.as_of_date
             ORDER BY g.expiration_date, g.effective_date, g.trade_id, g.leg_order) AS r_canon,
         row_number() OVER (PARTITION BY u.package_id, u.as_of_date
             ORDER BY g.leg_order, g.expiration_date, g.effective_date, g.trade_id) AS r_lo,
         row_number() OVER (PARTITION BY u.package_id, u.as_of_date
             ORDER BY g.tenor_years, g.expiration_date, g.effective_date, g.trade_id) AS r_ty
  FROM u
  JOIN arbs_usd_swap_tape_legs_v3 g
    ON g.package_id=u.package_id AND g.as_of_date=u.as_of_date
  JOIN arbs_dd_curve_mid_v1 m
    ON m.grid_date=u.as_of_date AND m.rate_index=u.rate_index
   AND m.tenor_label=g.tenor_label AND m.ts=u.curve_timestamp
   AND m.effective_date=g.effective_date AND m.maturity_date=g.expiration_date
  WHERE NOT g.is_off_market
)
SELECT package_id, as_of_date, deviation_bps, dealer_direction, dealer_sign,
       rate_index, tau_bps, mid_bias_bps, venue_class,
       count(*) AS nl,
       bool_and(r_canon = r_lo) AS lo_agrees,
       bool_and(r_canon = r_ty) AS ty_agrees,
       max(fr)      FILTER (WHERE r_canon=1) AS fr0,
       max(fr)      FILTER (WHERE r_canon=2) AS fr1,
       max(fr)      FILTER (WHERE r_canon=3) AS fr2,
       max(mid_pct) FILTER (WHERE r_canon=1) AS m0,
       max(mid_pct) FILTER (WHERE r_canon=2) AS m1,
       max(mid_pct) FILTER (WHERE r_canon=3) AS m2,
       max(tenor_label) FILTER (WHERE r_canon=1) AS tl0,
       max(tenor_label) FILTER (WHERE r_canon=2) AS tl1,
       max(tenor_label) FILTER (WHERE r_canon=3) AS tl2,
       max(fr)      FILTER (WHERE r_ty=1) AS ty_fr0,
       max(fr)      FILTER (WHERE r_ty=2) AS ty_fr1,
       max(fr)      FILTER (WHERE r_ty=3) AS ty_fr2,
       max(fsy) AS max_fsy
FROM l
GROUP BY 1,2,3,4,5,6,7,8,9
HAVING count(*) = %(nl)s
"""

months = pd.date_range('2024-07-01', '2026-09-01', freq='MS')
frames = []
for d0, d1 in zip(months[:-1], months[1:]):
    df = pd.read_sql(SQL, conn, params={
        'kind': KIND, 'nl': NL,
        'd0': d0.date().isoformat(), 'd1': d1.date().isoformat()})
    if len(df):
        frames.append(df)
    print(f"  {d0.date()}  n={len(df)}", flush=True)
conn.close()

d = pd.concat(frames, ignore_index=True)
print(f"\n=== {KIND}: {len(d):,} grid-clean units, "
      f"{d.as_of_date.min()} .. {d.as_of_date.max()}, "
      f"{d.as_of_date.nunique()} days ===")

PCT = 100.0        # fixed_rate is a FRACTION -> percent
BP = 100.0         # percent -> bp

def price(r, w):
    return sum(wi * ri for wi, ri in zip(w, r)) * BP

if KIND == 'CURVE':
    r_pct = [d.fr0 * PCT, d.fr1 * PCT]
    m_pct = [d.m0, d.m1]
    cands = {
        'A_canon_back_minus_front (-1,+1)': (-1.0, 1.0),
        'B_reversed              (+1,-1)': (1.0, -1.0),
    }
else:
    r_pct = [d.fr0 * PCT, d.fr1 * PCT, d.fr2 * PCT]
    m_pct = [d.m0, d.m1, d.m2]
    cands = {
        'A_canon_belly_idx1 (-1,+2,-1)': (-1.0, 2.0, -1.0),
        'B_negated          (+1,-2,+1)': (1.0, -2.0, 1.0),
        'C_belly_idx0       (+2,-1,-1)': (2.0, -1.0, -1.0),
        'D_belly_idx2       (-1,-1,+2)': (-1.0, -1.0, 2.0),
    }

# the mid is ALWAYS built canonical (-1,+1) / (-1,+2,-1): orientation I control
W_MID = (-1.0, 1.0) if KIND == 'CURVE' else (-1.0, 2.0, -1.0)
m_struct = price(m_pct, W_MID)

print(f"\nmid structure (canonical orientation) bp: "
      f"median {np.median(m_struct):.2f}  p5 {np.percentile(m_struct,5):.2f}  "
      f"p95 {np.percentile(m_struct,95):.2f}")
print(f"|deviation_bps|: median {d.deviation_bps.abs().median():.4f}  "
      f"p99 {d.deviation_bps.abs().quantile(0.99):.4f}")

print(f"\n{'candidate':<34s} {'med|err|':>12s} {'max|err|':>12s} {'p99|err|':>12s} {'n_exact':>9s}")
res = {}
for name, w in cands.items():
    t = price(r_pct, w)
    err = (t - m_struct - d.deviation_bps).abs()
    res[name] = err
    print(f"{name:<34s} {err.median():>12.3e} {err.max():>12.3e} "
          f"{err.quantile(0.99):>12.3e} {int((err<1e-6).sum()):>9d}")

# leg-order-column variants, canonical weights
if KIND == 'CURVE':
    t_ty = price([d.ty_fr0 * PCT, d.ty_fr1 * PCT], W_MID)
else:
    t_ty = price([d.ty_fr0 * PCT, d.ty_fr1 * PCT, d.ty_fr2 * PCT], W_MID)
err_ty = (t_ty - m_struct - d.deviation_bps).abs()
print(f"\nordering by tenor_years instead of expiration (canonical weights): "
      f"med {err_ty.median():.3e}  max {err_ty.max():.3e}  "
      f"n_exact {int((err_ty<1e-6).sum())}/{len(d)}")
print(f"  units where leg_order rank != expiration rank: "
      f"{int((~d.lo_agrees).sum())}/{len(d)}")
print(f"  units where tenor_years rank != expiration rank: "
      f"{int((~d.ty_agrees).sum())}/{len(d)}")

best = min(res, key=lambda k: res[k].median())
err = res[best]
print(f"\nBEST: {best}")
print(f"  n={len(d)}  med|err|={err.median():.3e}  max|err|={err.max():.6f}  "
      f"exact(<1e-6)={int((err<1e-6).sum())}/{len(d)} "
      f"({100*(err<1e-6).mean():.2f}%)")
print(f"  n_days={d.as_of_date.nunique()}  "
      f"months={pd.to_datetime(d.as_of_date).dt.to_period('M').nunique()}")
print("  by rate_index:", d.groupby('rate_index').size().to_dict())

# dealer_direction identity
t = price(r_pct, cands[best] if best in cands else W_MID)
sub = d[d.deviation_bps.abs() > 1e-12]
ok = ((sub.deviation_bps > 0) & (sub.dealer_direction == 'RECEIVED')) | \
     ((sub.deviation_bps < 0) & (sub.dealer_direction == 'PAID'))
print(f"\ndealer_direction identity  sign(dev)>0 <=> RECEIVED : "
      f"{int(ok.sum())}/{len(sub)} ({100*ok.mean():.3f}%)")
print("  dealer_direction values:", d.dealer_direction.value_counts().to_dict())
bad = sub[~ok]
if len(bad):
    print(f"  mismatches |dev| median {bad.deviation_bps.abs().median():.4f} "
          f"max {bad.deviation_bps.abs().max():.4f}")
    print("  mismatch dir counts:", bad.dealer_direction.value_counts().to_dict())
print("  dealer_sign vs direction:",
      d.groupby(['dealer_direction', 'dealer_sign']).size().to_dict())

# mid recoverability
mid_rec = price(r_pct, cands[best] if best in cands else W_MID) - d.deviation_bps
print(f"\nmid recovered = traded_bp - deviation_bps :  "
      f"max|mid_rec - m_grid| = {np.abs(mid_rec - m_struct).max():.3e} bp")

d.to_parquet(f'scratch/wfstr07_{KIND}.parquet')
print(f"\nsaved scratch/wfstr07_{KIND}.parquet")
