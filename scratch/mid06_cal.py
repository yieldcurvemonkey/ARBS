"""MEASUREMENT 3c -- pin the spot rule against the whole tape, three candidates.

mid05 showed rateslib's `nyc` disagrees with the market on two counts:
  * it holds Good Friday (2026-04-03) as a holiday; USD SOFR settles that day
  * a Sunday-evening / holiday-Monday ET execution date is not rolled forward
    before the two business days are added.

Candidates, scored on the MODAL effective_date of spot STANDARD SOFR legs per
ET execution date, over the whole minute-store span:

  A  add_tenor(et, "2b", mf, nyc)                 -- what calendar_advance does
  B  add_tenor(rollfwd_nyc(et), "2b", mf, nyc)
  C  add_tenor(rollfwd_usd(et), "2b", mf, USDCAL) -- nyc minus Good Friday

Also: which base date the CURVE itself carries, at instants spanning a whole
tape day including the previous evening. If `reference_date()` already rolls,
the grid can key spot off the curve instead of off a wall clock.
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
pd.set_option("display.width", 240)
pd.set_option("display.max_rows", 500)

NYC = rl.get_calendar("nyc")


def _good_fridays(lo=2015, hi=2075):
    out = []
    for y in range(lo, hi):
        e = _easter(y)
        out.append(e - datetime.timedelta(days=2))
    return out


def _easter(y):
    a = y % 19
    b, c = divmod(y, 100)
    d, e = divmod(b, 4)
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = divmod(c, 4)
    l = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l) // 451
    month = (h + l - 7 * m + 114) // 31
    day = ((h + l - 7 * m + 114) % 31) + 1
    return datetime.date(y, month, day)


GF = set(_good_fridays())
_nyc_hols = [pd.Timestamp(x).date() for x in NYC.holidays]
USD_HOLS = [d for d in _nyc_hols if d not in GF]
print(f"nyc holidays: {len(_nyc_hols)}   Good Fridays removed: "
      f"{len(_nyc_hols) - len(USD_HOLS)}")
USDCAL = rl.Cal([datetime.datetime(d.year, d.month, d.day) for d in USD_HOLS],
                [5, 6])
print("USDCAL 2026:", [str(d) for d in USD_HOLS if d.year == 2026])
print("USDCAL business on 2026-04-03 (Good Friday)?",
      USDCAL.is_bus_day(datetime.datetime(2026, 4, 3)))


def _dt(d):
    return datetime.datetime(d.year, d.month, d.day)


def roll_fwd(d, cal):
    x = _dt(d)
    while not cal.is_bus_day(x):
        x += datetime.timedelta(days=1)
    return x


def rule_A(d):
    return rl.add_tenor(_dt(d), "2b", "mf", NYC).date()


def rule_B(d):
    return rl.add_tenor(roll_fwd(d, NYC), "2b", "mf", NYC).date()


def rule_C(d):
    return rl.add_tenor(roll_fwd(d, USDCAL), "2b", "mf", USDCAL).date()


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
    AND effective_date IS NOT NULL AND expiration_date IS NOT NULL
    AND effective_date >= (execution_timestamp AT TIME ZONE 'America/New_York')::date
    AND tenor_label IN ('2Y','3Y','5Y','7Y','10Y','20Y','30Y')
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
df = pd.read_sql(SQL, conn, params={"s": "2024-07-01", "e": "2026-08-07"})
conn.close()

df["A"] = df["et_date"].map(rule_A)
df["B"] = df["et_date"].map(rule_B)
df["C"] = df["et_date"].map(rule_C)
df["dow"] = pd.to_datetime(df["et_date"]).dt.day_name().str[:3]
df["share"] = (df["n_modal"] / df["tot"]).round(3)

# Only score days where the modal date is a real convention, not an IMM week
# with no majority. A day whose top effective date is 6% of the day is not
# evidence about a spot rule either way, and scoring it would let an IMM roll
# outvote the convention.
clean = df[df["share"] >= 0.40]
print(f"\n{len(df)} ET dates, {len(clean)} with modal share >= 0.40")
for k in ("A", "B", "C"):
    hit = (clean["modal_eff"] == clean[k])
    wt = clean.loc[hit, "n_modal"].sum() / clean["n_modal"].sum()
    print(f"  rule {k}: {hit.sum():4d}/{len(clean)} days "
          f"({100*hit.mean():5.1f}%)   modal-weighted {100*wt:5.1f}%")

bad = clean[clean["modal_eff"] != clean["C"]]
print(f"\nrule C misses ({len(bad)}):")
print(bad[["et_date", "dow", "modal_eff", "A", "B", "C", "n_modal", "tot",
           "share"]].to_string())

print("\ndays excluded as non-modal (share < 0.40):")
print(df[df["share"] < 0.40][["et_date", "dow", "modal_eff", "C", "n_modal",
                              "tot", "share"]].to_string())

# ---------------------------------------------------------------- curve base
print("\n" + "=" * 78)
print("WHAT BASE DATE THE CURVE ITSELF CARRIES")
from SDRUtils.dealer_direction import midprice, snapshot
from SDRUtils.stir_flow.pricing import NY

pricer = midprice.SessionBranchPricer(source=snapshot.CURVE_SOURCE)
for day, hours in (("2026-04-01", [1, 6, 9, 13, 16, 17, 20, 22]),
                   ("2026-04-02", [1, 9, 16, 20, 22]),
                   ("2026-03-29", [20, 21, 22]),      # Sunday evening
                   ("2026-05-25", [9, 13, 20])):      # Memorial Day
    for h in hours:
        t = pd.Timestamp(f"{day} {h:02d}:30:00", tz=NY)
        try:
            m = pricer.mark_curve("USD-SOFR-1D", t)
            ref = m.handle.reference_date().date()
            print(f"  {t}  policy={m.policy[:6]:>6} lag={m.lag_seconds:>8.0f}s "
                  f" ref={ref}  ruleC(ref)={rule_C(ref)}  "
                  f"ruleC(ET date)={rule_C(t.date())}")
        except Exception as exc:
            print(f"  {t}  MISS {type(exc).__name__}: {str(exc)[:70]}")
    pricer.clear()
