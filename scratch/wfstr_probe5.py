"""How much does a 1-minute LOCF cost, for the structures we care about?"""
import os, sys
os.environ.setdefault('ARBS_SUPABASE_ENABLED', '0')
sys.path.insert(0, '.')
from SDRUtils._swappulse_scripts.ingest_usdswaps_tape import resolve_pg_url
import psycopg2, pandas as pd, numpy as np
pd.set_option('display.width', 200)

conn = psycopg2.connect(resolve_pg_url())
with conn.cursor() as c:
    c.execute("SET statement_timeout = '600s'")

DAYS = ["2025-04-09", "2026-01-20", "2026-06-18", "2026-07-29"]
PAIRS = [("2Y", "10Y"), ("5Y", "10Y"), ("10Y", "30Y"), ("5Y", "30Y"), ("2Y", "5Y")]
rows = []
for d in DAYS:
    g = pd.read_sql("""SELECT tenor_label, ts, mid_pct FROM arbs_dd_curve_mid_v1
                       WHERE rate_index='SOFR' AND grid_date=%(d)s""",
                    conn, params={"d": d})
    w = g.pivot(index="ts", columns="tenor_label", values="mid_pct").sort_index()
    for a, b in PAIRS:
        s = (w[b] - w[a]) * 100.0
        for k in (1, 5, 15):
            dd = s.diff(k).abs().dropna()
            rows.append(dict(day=d, pair=f"{a}/{b}", step=f"{k}min",
                             med=dd.median(), p95=dd.quantile(.95), max=dd.max()))
conn.close()

r = pd.DataFrame(rows)
print("=== |change in grid-built spread| over k minutes (bp) ===")
print(r.groupby(["pair", "step"]).agg(med=("med", "mean"), p95=("p95", "mean"),
                                      max=("max", "max")).round(4).to_string())
print("\n=== pooled over pairs ===")
print(r.groupby("step").agg(med=("med", "mean"), p95=("p95", "mean"),
                            max=("max", "max")).round(4).to_string())
