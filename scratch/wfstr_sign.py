"""dealer_direction sign identity, per side, on the FULL rate-rule population."""
import os, sys, warnings
os.environ.setdefault('ARBS_SUPABASE_ENABLED', '0')
sys.path.insert(0, r'C:\Users\chris\clee\ARBS-fe')
warnings.filterwarnings('ignore')
import psycopg2, pandas as pd
from SDRUtils._swappulse_scripts.ingest_usdswaps_tape import resolve_pg_url
pd.set_option('display.width', 250); pd.set_option('display.max_rows', 200)
conn = psycopg2.connect(resolve_pg_url()); conn.set_session(readonly=True)
q = lambda s, p=None: pd.read_sql(s, conn, params=p)

BASE = ("FROM arbs_dd_unit_v1 WHERE rule='RATE_VS_MID' "
        "AND exclusion_reason IS NULL AND deviation_bps IS NOT NULL")

print("=== A. dealer_direction  <->  dealer_sign  (all rate-rule kinds) ===")
print(q(f"SELECT kind, dealer_direction, dealer_sign, count(*) n {BASE} "
        f"GROUP BY 1,2,3 ORDER BY 1,2,3").to_string())

print("\n=== B. dealer_sign vs sign(deviation_bps - mid_bias_bps), PER SIDE ===")
print(q(f"""SELECT kind, dealer_sign,
                   sign(deviation_bps - mid_bias_bps)::int s_bias,
                   sign(deviation_bps)::int s_raw,
                   count(*) n
            {BASE} GROUP BY 1,2,3,4 ORDER BY 1,2,3,4""").to_string())

print("\n=== C. per-side mismatch counts (bias-corrected identity) ===")
print(q(f"""SELECT kind, dealer_sign,
                   count(*) n,
                   count(*) FILTER (WHERE sign(deviation_bps - mid_bias_bps)::int
                                          <> dealer_sign) n_mismatch_bias,
                   count(*) FILTER (WHERE sign(deviation_bps)::int
                                          <> dealer_sign) n_mismatch_raw,
                   count(*) FILTER (WHERE mid_bias_bps IS NULL) n_nullbias
            {BASE} GROUP BY 1,2 ORDER BY 1,2""").to_string())

print("\n=== D. signed_weight / p consistency with dealer_sign, per side ===")
print(q(f"""SELECT kind, dealer_sign, count(*) n,
                   count(*) FILTER (WHERE sign(signed_weight)::int <> dealer_sign) n_sw_bad,
                   count(*) FILTER (WHERE (p > 0.5) <> (dealer_sign = 1)) n_p_bad,
                   count(*) FILTER (WHERE in_dead_zone) n_dead
            {BASE} GROUP BY 1,2 ORDER BY 1,2""").to_string())

print("\n=== E. mid_bias_bps magnitude (why raw-sign disagrees) ===")
print(q(f"""SELECT kind, count(DISTINCT mid_bias_bps) n_distinct,
                   min(mid_bias_bps) mn, avg(mid_bias_bps) av, max(mid_bias_bps) mx
            {BASE} GROUP BY 1""").to_string())

print("\n=== F. CURVE tie units (both legs same expiration) under the rate rule ===")
print(q("""
WITH t AS (
  SELECT u.package_id, u.deviation_bps, u.rule, u.dealer_sign,
         count(DISTINCT l.expiration_date) nexp,
         count(DISTINCT l.effective_date) neff,
         count(*) nlegs,
         min(l.trade_id) tid_lo, max(l.trade_id) tid_hi,
         count(DISTINCT l.fixed_rate) nrate
  FROM arbs_dd_unit_v1 u JOIN arbs_usd_swap_tape_legs_v3 l
    ON l.package_id = u.package_id AND l.as_of_date = u.as_of_date
  WHERE u.kind = 'CURVE' AND u.deviation_bps IS NOT NULL
  GROUP BY 1,2,3,4)
SELECT rule, nexp = 1 same_exp, neff = 1 same_eff, nrate = 1 same_rate,
       count(*) n, count(*) FILTER (WHERE abs(deviation_bps) > 1e-9) n_dev_nonzero
FROM t GROUP BY 1,2,3,4 ORDER BY 1,2,3,4""").to_string())

conn.close()
