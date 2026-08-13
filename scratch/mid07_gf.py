"""Good Friday: the two years disagree in mid06. Look at the raw histograms.

2026-04-01 -> tape modal effective 2026-04-03 (Good Friday IS settlement)
2025-04-16 -> tape modal effective 2025-04-21 (Good Friday is NOT)

One of those readings is contaminated. Print the full effective-date
distribution for the Good Friday weeks of 2025 and 2026 and decide.
"""
import os
os.environ.setdefault("ARBS_SUPABASE_ENABLED", "0")
os.environ["ARBS_CITIVELO_QUOTES_OFFLINE"] = "1"
import pathlib
import sys
import warnings

REPO = str(pathlib.Path(__file__).resolve().parents[1])
if REPO not in sys.path:
    sys.path.insert(0, REPO)

import pandas as pd
import psycopg2

from SDRUtils._swappulse_scripts._tape_tables import LEGS_TABLE
from SDRUtils._swappulse_scripts.ingest_usdswaps_tape import resolve_pg_url

warnings.simplefilter("ignore")
pd.set_option("display.width", 200)
pd.set_option("display.max_rows", 400)

SQL = f"""
SELECT (execution_timestamp AT TIME ZONE 'America/New_York')::date AS et_date,
       effective_date, count(*) AS n
FROM {LEGS_TABLE}
WHERE (execution_timestamp AT TIME ZONE 'America/New_York')::date
      BETWEEN %(a)s AND %(b)s
  AND economic_class = 'ECONOMIC_FLOW'
  AND rate_index_clean = 'SOFR'
  AND special_tenor_type = 'STANDARD'
  AND (forward_start_years IS NULL OR abs(forward_start_years) < 0.02)
  AND effective_date IS NOT NULL
  AND effective_date >= (execution_timestamp AT TIME ZONE 'America/New_York')::date
  AND tenor_label IN ('2Y','3Y','5Y','7Y','10Y','20Y','30Y')
GROUP BY 1,2 ORDER BY 1,2
"""
conn = psycopg2.connect(resolve_pg_url())
for a, b, label in (("2025-04-14", "2025-04-23", "Good Friday 2025 = 04-18"),
                    ("2026-03-30", "2026-04-08", "Good Friday 2026 = 04-03"),
                    ("2024-03-25", "2024-04-03", "Good Friday 2024 = 03-29")):
    df = pd.read_sql(SQL, conn, params={"a": a, "b": b})
    print(f"\n===== {label}")
    if df.empty:
        print("  (no rows)")
        continue
    p = df.pivot(index="et_date", columns="effective_date",
                 values="n").fillna(0).astype(int)
    print(p.to_string())

# Does the curve store even hold a Good Friday partition?
print("\n===== does Citi publish a curve on Good Friday?")
from SDRUtils.dealer_direction import midprice, snapshot
from SDRUtils.stir_flow.pricing import NY
pricer = midprice.SessionBranchPricer(source=snapshot.CURVE_SOURCE)
for d in ("2025-04-18", "2026-04-03", "2024-03-29", "2026-07-03"):
    for h in (9, 13):
        t = pd.Timestamp(f"{d} {h:02d}:30:00", tz=NY)
        try:
            m = pricer.mark_curve("USD-SOFR-1D", t)
            print(f"  {t}  ref={m.handle.reference_date().date()} "
                  f"lag={m.lag_seconds}s")
        except Exception as exc:
            print(f"  {t}  MISS {type(exc).__name__}: {str(exc)[:60]}")
    pricer.clear()

# and how many prints does the tape carry on those days?
print("\n===== tape print counts on Good Fridays")
df = pd.read_sql(f"""
SELECT (execution_timestamp AT TIME ZONE 'America/New_York')::date AS et_date,
       count(*) n
FROM {LEGS_TABLE}
WHERE (execution_timestamp AT TIME ZONE 'America/New_York')::date
      IN ('2025-04-18','2026-04-03','2024-03-29','2026-07-03','2025-04-17','2026-04-02')
  AND economic_class = 'ECONOMIC_FLOW' AND rate_index_clean = 'SOFR'
GROUP BY 1 ORDER BY 1""", conn)
print(df.to_string())
conn.close()
