"""MEASUREMENT 3b -- the spot date. FIND the convention, do not assert one.

The probe in mid04 got `calendar_advance(2026-04-01, "2b") = 2026-04-06`,
while every spot 2026-04-01 print on the tape carries `effective_date =
2026-04-03`. One of those is wrong for USD SOFR and the grid has to use the
market's, because the whole point is that the grid and the direction
annotations drawn on it agree.

So: per tape day, the MODAL effective_date of spot STANDARD SOFR legs, beside
rateslib's own `nyc` answer.
"""
import os
os.environ.setdefault("ARBS_SUPABASE_ENABLED", "0")
os.environ["ARBS_CITIVELO_QUOTES_OFFLINE"] = "1"
import datetime
import pathlib
import sys
import warnings

REPO = str(pathlib.Path(__file__).resolve().parents[1])
if REPO not in sys.path:
    sys.path.insert(0, REPO)

import pandas as pd
import psycopg2
import rateslib as rl

from SDRUtils._swappulse_scripts._tape_tables import LEGS_TABLE
from SDRUtils._swappulse_scripts.ingest_usdswaps_tape import resolve_pg_url

warnings.simplefilter("ignore")
pd.set_option("display.width", 220)
pd.set_option("display.max_rows", 400)

cal = rl.get_calendar("nyc")
print("rateslib nyc holidays 2026 Q1-Q2:")
hs = [d for d in getattr(cal, "holidays", [])
      if datetime.date(2026, 1, 1) <= pd.Timestamp(d).date() <= datetime.date(2026, 7, 31)]
for d in hs:
    print("   ", pd.Timestamp(d).date(), pd.Timestamp(d).day_name())
print("is 2026-04-03 (Good Friday) a business day on nyc? ",
      cal.is_bus_day(datetime.datetime(2026, 4, 3)))

# Every ET *execution* date on the tape, its modal spot effective date, and
# rateslib's. Grouped on the ET date of execution, NOT as_of_date: as_of is a
# UTC date and the 20:00-23:59 ET prints of the previous evening land on it.
SQL = f"""
WITH e AS (
  SELECT (execution_timestamp AT TIME ZONE 'America/New_York')::date AS et_date,
         effective_date, count(*) AS n
  FROM {LEGS_TABLE}
  WHERE as_of_date BETWEEN %(s)s AND %(e)s
    AND economic_class = 'ECONOMIC_FLOW'
    AND rate_index_clean = 'SOFR'
    AND special_tenor_type = 'STANDARD'
    AND (forward_start_years IS NULL OR abs(forward_start_years) < 0.02)
    AND effective_date IS NOT NULL
    AND expiration_date IS NOT NULL
    AND tenor_label IN ('2Y','5Y','10Y','30Y')
  GROUP BY 1, 2
), r AS (
  SELECT et_date, effective_date, n,
         row_number() OVER (PARTITION BY et_date ORDER BY n DESC) rk,
         sum(n) OVER (PARTITION BY et_date) tot
  FROM e
)
SELECT et_date, effective_date AS modal_eff, n AS n_modal, tot
FROM r WHERE rk = 1 ORDER BY et_date
"""
conn = psycopg2.connect(resolve_pg_url())
df = pd.read_sql(SQL, conn, params={"s": "2026-01-01", "e": "2026-08-07"})
conn.close()

def rl_spot(d):
    return rl.add_tenor(datetime.datetime(d.year, d.month, d.day),
                        tenor="2b", modifier="mf", calendar="nyc").date()

df["rl_2b"] = df["et_date"].map(rl_spot)
df["agree"] = df["modal_eff"] == df["rl_2b"]
df["share"] = (df["n_modal"] / df["tot"]).round(3)
df["dow"] = pd.to_datetime(df["et_date"]).dt.day_name().str[:3]

print(f"\n{len(df)} ET execution dates; modal spot vs rateslib 2b/nyc")
print(f"AGREE on {df['agree'].sum()} / {len(df)} days "
      f"({100*df['agree'].mean():.1f}%)")
print(f"weighted modal share of all spot legs: "
      f"{df['n_modal'].sum()/df['tot'].sum():.3f}")
print("\nDISAGREEMENTS:")
print(df.loc[~df["agree"], ["et_date", "dow", "modal_eff", "rl_2b",
                            "n_modal", "tot", "share"]].to_string())
print("\ndays with modal share < 0.80 (convention not clean):")
print(df.loc[df["share"] < 0.80, ["et_date", "dow", "modal_eff", "rl_2b",
                                  "n_modal", "tot", "share"]].to_string())
print("\nfirst 20 rows:")
print(df.head(20).to_string())
