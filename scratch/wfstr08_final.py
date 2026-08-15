import os, sys, warnings
os.environ.setdefault('ARBS_SUPABASE_ENABLED', '0')
sys.path.insert(0, '.')
warnings.filterwarnings('ignore')
from SDRUtils._swappulse_scripts.ingest_usdswaps_tape import resolve_pg_url
import psycopg2
import pandas as pd
import numpy as np

# ---- 1. dealer_direction identity uses the BIAS-CORRECTED deviation ----
for kind in ('CURVE', 'FLY'):
    d = pd.read_parquet(f'scratch/wfstr07_{kind}.parquet')
    raw = np.sign(d.deviation_bps)
    corr = np.sign(d.deviation_bps - d.mid_bias_bps.fillna(0.0))
    want = np.where(d.dealer_direction == 'RECEIVED', 1, -1)
    print(f"\n=== {kind}  n={len(d)} ===")
    print(f"  sign(dev)              matches dealer_direction: "
          f"{(raw == want).mean()*100:.3f}%")
    print(f"  sign(dev - mid_bias)   matches dealer_direction: "
          f"{(corr == want).mean()*100:.3f}%  "
          f"({int((corr != want).sum())} misses)")
    print(f"  mid_bias_bps: median {d.mid_bias_bps.median():.5f}  "
          f"min {d.mid_bias_bps.min():.5f}  max {d.mid_bias_bps.max():.5f}  "
          f"nulls {int(d.mid_bias_bps.isna().sum())}")
    miss = d[corr != want]
    if len(miss):
        print(f"  residual misses |dev-b0| max {(miss.deviation_bps-miss.mid_bias_bps).abs().max():.3e}")

# ---- 2. ordering blast radius on the FULL kept population ----
conn = psycopg2.connect(resolve_pg_url())
conn.set_session(readonly=True)
cur = conn.cursor()

cur.execute("""
WITH u AS (
  SELECT package_id, as_of_date, kind FROM arbs_dd_unit_v1
  WHERE kind IN ('CURVE','FLY') AND rule='RATE_VS_MID' AND exclusion_reason IS NULL
), l AS (
  SELECT u.kind, g.package_id, g.as_of_date,
    row_number() OVER (PARTITION BY g.package_id, g.as_of_date
      ORDER BY g.expiration_date, g.effective_date, g.trade_id, g.leg_order) AS r_canon,
    row_number() OVER (PARTITION BY g.package_id, g.as_of_date
      ORDER BY g.leg_order, g.expiration_date, g.effective_date, g.trade_id) AS r_lo,
    row_number() OVER (PARTITION BY g.package_id, g.as_of_date
      ORDER BY g.tenor_years, g.expiration_date, g.effective_date, g.trade_id) AS r_ty,
    row_number() OVER (PARTITION BY g.package_id, g.as_of_date
      ORDER BY g.expiration_date) AS r_exp_only
  FROM arbs_usd_swap_tape_legs_v3 g
  JOIN u ON u.package_id=g.package_id AND u.as_of_date=g.as_of_date
)
SELECT kind, count(*) AS n_units,
  count(*) FILTER (WHERE NOT lo_ok) AS units_legorder_differs,
  count(*) FILTER (WHERE NOT ty_ok) AS units_tenoryears_differs
FROM (
  SELECT kind, package_id, as_of_date,
         bool_and(r_canon=r_lo) lo_ok, bool_and(r_canon=r_ty) ty_ok
  FROM l GROUP BY 1,2,3
) t GROUP BY 1
""")
print("\n=== ordering blast radius (ALL kept RATE_VS_MID units) ===")
print("  kind | n_units | leg_order differs | tenor_years differs")
for r in cur.fetchall():
    print(f"  {r[0]} | {r[1]} | {r[2]} ({100*r[2]/r[1]:.2f}%) | {r[3]} ({100*r[3]/r[1]:.2f}%)")

# concrete examples where tenor_years ordering flips the sign
cur.execute("""
WITH u AS (
  SELECT package_id, as_of_date, kind, deviation_bps FROM arbs_dd_unit_v1
  WHERE kind='CURVE' AND rule='RATE_VS_MID' AND exclusion_reason IS NULL
), l AS (
  SELECT u.package_id, u.as_of_date, u.deviation_bps, g.tenor_display,
         g.tenor_years, g.forward_start_years, g.expiration_date,
         g.effective_date, g.fixed_rate,
    row_number() OVER (PARTITION BY g.package_id, g.as_of_date
      ORDER BY g.expiration_date, g.effective_date, g.trade_id, g.leg_order) AS r_canon,
    row_number() OVER (PARTITION BY g.package_id, g.as_of_date
      ORDER BY g.tenor_years, g.expiration_date, g.effective_date, g.trade_id) AS r_ty
  FROM arbs_usd_swap_tape_legs_v3 g
  JOIN u ON u.package_id=g.package_id AND u.as_of_date=g.as_of_date
)
SELECT package_id, as_of_date,
  string_agg(tenor_display || ' (ty=' || tenor_years || ', fwd=' ||
             forward_start_years || ', exp=' || expiration_date || ', r=' ||
             round(fixed_rate::numeric*10000,2) || 'bp)', '  ||  ' ORDER BY r_canon) AS legs_in_canonical_order,
  round((max(fixed_rate::numeric) FILTER (WHERE r_canon=2)
       - max(fixed_rate::numeric) FILTER (WHERE r_canon=1))*10000, 3) AS traded_bp_canon,
  round((max(fixed_rate::numeric) FILTER (WHERE r_ty=2)
       - max(fixed_rate::numeric) FILTER (WHERE r_ty=1))*10000, 3) AS traded_bp_tenorsort,
  round(deviation_bps::numeric, 4) AS dev
FROM l
GROUP BY 1,2,deviation_bps
HAVING bool_or(r_canon <> r_ty)
LIMIT 6
""")
print("\n=== CURVE units where tenor_years sort DISAGREES with expiration sort ===")
for r in cur.fetchall():
    print(f"  {r[1]} {r[0][:22]}")
    print(f"     {r[2]}")
    print(f"     traded_bp canonical={r[3]}  tenor-sorted={r[4]}  dev={r[5]}")

conn.close()
