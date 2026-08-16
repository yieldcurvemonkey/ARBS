"""Adversarial check of the CURVE/FLY structure-price formula. READ ONLY.

Per as_of_date: pull rate-rule units + their legs, LEFT JOIN the 1-min par grid
on (rate_index, ts=curve_timestamp, effective_date, maturity_date=expiration_date).

Writes one parquet per day-chunk under scratch/wfstr_out/ so the analysis can be
re-run without re-querying.

usage:  wfstr_core.py <start> <end> [--every N]
"""
from __future__ import annotations
import os, sys, time, warnings
os.environ.setdefault('ARBS_SUPABASE_ENABLED', '0')
sys.path.insert(0, r'C:\Users\chris\clee\ARBS-fe')
warnings.filterwarnings('ignore')
import psycopg2
import pandas as pd
import numpy as np
from SDRUtils._swappulse_scripts.ingest_usdswaps_tape import resolve_pg_url

OUT = r'C:\Users\chris\clee\ARBS-fe\scratch\wfstr_out'
os.makedirs(OUT, exist_ok=True)

SQL = """
WITH u AS (
    SELECT package_id, as_of_date, kind, n_legs, rule, deviation_bps,
           rate_index, curve_timestamp, dealer_sign, dealer_direction,
           mid_bias_bps, p, signed_weight, in_dead_zone, special_tenor_type,
           venue_class, series, structure_dv01, code_vintage, tau_bps,
           exclusion_reason
    FROM arbs_dd_unit_v1
    WHERE as_of_date = %(d)s
      AND kind IN ('CURVE','FLY','OUTRIGHT')
      AND deviation_bps IS NOT NULL
      AND curve_timestamp IS NOT NULL
),
lg AS (
    SELECT u.*, l.trade_id, l.leg_order, l.fixed_rate,
           l.effective_date, l.expiration_date, l.tenor_label,
           l.tenor_display, l.forward_start_years, l.is_off_market,
           l.is_mac, l.tenor_years, l.ctid::text AS phys
    FROM u JOIN arbs_usd_swap_tape_legs_v3 l
      ON l.package_id = u.package_id AND l.as_of_date = u.as_of_date
)
SELECT lg.*, g.mid_pct, g.tenor_label AS grid_tenor, g.pv01 AS grid_pv01
FROM lg
LEFT JOIN arbs_dd_curve_mid_v1 g
       ON g.grid_date BETWEEN %(d)s::date - 1 AND %(d)s::date + 1
      AND g.rate_index = lg.rate_index
      AND g.ts = lg.curve_timestamp
      AND g.effective_date = lg.effective_date
      AND g.maturity_date = lg.expiration_date
"""


def main():
    start, end = sys.argv[1], sys.argv[2]
    every = 1
    if '--every' in sys.argv:
        every = int(sys.argv[sys.argv.index('--every') + 1])
    conn = psycopg2.connect(resolve_pg_url())
    conn.set_session(readonly=True)
    days = pd.read_sql(
        "SELECT DISTINCT as_of_date d FROM arbs_dd_unit_v1 "
        "WHERE as_of_date BETWEEN %(a)s AND %(b)s ORDER BY 1",
        conn, params={'a': start, 'b': end})['d'].tolist()
    days = days[::every]
    print(f"{len(days)} days {days[0]} .. {days[-1]}", flush=True)
    buf, nb = [], 0
    t0 = time.time()
    for i, d in enumerate(days):
        tag = str(d)
        f = os.path.join(OUT, f"{tag}.parquet")
        if os.path.exists(f):
            continue
        t1 = time.time()
        df = pd.read_sql(SQL, conn, params={'d': d})
        df.to_parquet(f)
        print(f"[{i+1}/{len(days)}] {d} rows={len(df):6d} "
              f"{time.time()-t1:5.1f}s  tot={time.time()-t0:6.0f}s", flush=True)
    conn.close()


if __name__ == '__main__':
    main()
