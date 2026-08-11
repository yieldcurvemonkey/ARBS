"""Stage 2 - pull ~20 real ECONOMIC_FLOW prints spread across the Citi session.

Writes ``scratch/out_sample20.csv``. For each print it records the classifier's
curve instant (``snap_timestamp``), whether Citi could have published then
(``citi_session.publishes``) and whether the local store actually reaches it
(``density.day_density(...).covers``).

Deliberately NOT a single ORDER BY random(): the sample must contain the cases
the design is sensitive to (hour 00 ET, Friday, Fed Funds), and a uniform draw
over a tape that is 94.7 % in-session would not reliably contain them.
"""
from __future__ import annotations

import datetime
import os
import sys
import warnings

os.environ.setdefault("ARBS_SUPABASE_ENABLED", "0")

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd
import psycopg2

from MDP.IRSwaps.CITIVELO_EXCEL import citi_session
from MDP.IRSwaps.CITIVELO_EXCEL.density import day_density
from Caching.curve_store import CurveStore
from SDRUtils._swappulse_scripts._tape_tables import LEGS_TABLE
from SDRUtils._swappulse_scripts.ingest_usdswaps_tape import resolve_pg_url
from SDRUtils.stir_flow.pricing import snap_timestamp

CURVE_FOR = {"SOFR": "USD-SOFR-1D", "FED_FUNDS": "USD-FEDFUNDS-1D"}

pd.set_option("display.width", 250)
pd.set_option("display.max_columns", 40)

BASE_COLS = """
    trade_id, as_of_date, execution_timestamp, original_execution_timestamp,
    effective_date, expiration_date, notional, fixed_rate, tenor_years,
    rate_index_clean, trade_type, tenor_label, is_block, is_new_risk,
    is_off_market, other_payment_amount
"""

# Anything structured, off-market, or not a plain fixed-vs-OIS outright is out.
FILTER = f"""
    economic_class = 'ECONOMIC_FLOW' AND contributes_to_flow
    AND rate_index_clean IN ('SOFR','FED_FUNDS')
    AND fixed_rate IS NOT NULL AND effective_date IS NOT NULL
    AND expiration_date IS NOT NULL AND notional IS NOT NULL
    AND NOT is_mac AND NOT is_off_market AND NOT is_spreadover
    AND NOT is_asset_swap AND NOT coalesce(is_unwind, false)
    AND coalesce(trade_type,'') = 'OUTRIGHT'
    AND tenor_years BETWEEN 0.5 AND 31
    AND as_of_date BETWEEN '2026-04-01' AND '2026-08-05'
"""


def q(conn, sql, params=None):
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        return pd.read_sql(sql, conn, params=params)


def main() -> None:
    conn = psycopg2.connect(resolve_pg_url())

    print("=== trade_type distribution among flow legs in window ===")
    print(q(conn, f"""
        SELECT coalesce(trade_type,'<null>') tt, rate_index_clean, count(*) n
        FROM {LEGS_TABLE}
        WHERE economic_class='ECONOMIC_FLOW' AND contributes_to_flow
          AND rate_index_clean IN ('SOFR','FED_FUNDS')
          AND as_of_date BETWEEN '2026-04-01' AND '2026-08-05'
        GROUP BY 1,2 ORDER BY 3 DESC LIMIT 15""").to_string())

    # One print per ET hour of the snapped instant, deterministic pick.
    sql = f"""
    WITH base AS (
      SELECT {BASE_COLS},
        coalesce(original_execution_timestamp, execution_timestamp) AT TIME ZONE 'America/New_York' AS et_naive
      FROM {LEGS_TABLE} WHERE {FILTER}
    ), tagged AS (
      SELECT *, extract(hour from et_naive)::int AS et_hour,
             extract(dow  from et_naive)::int AS et_dow,
             row_number() OVER (PARTITION BY extract(hour from et_naive)::int, rate_index_clean
                                ORDER BY trade_id) AS rn
      FROM base
    )
    SELECT * FROM tagged WHERE rn <= 2
    """
    pool = q(conn, sql)
    print(f"\npool rows = {len(pool)}")
    print(pool.groupby(["et_hour", "rate_index_clean"]).size().to_string())

    # Friday prints (dow 5) - forced in explicitly.
    fri = q(conn, f"""
      WITH base AS (
        SELECT {BASE_COLS},
          coalesce(original_execution_timestamp, execution_timestamp) AT TIME ZONE 'America/New_York' AS et_naive
        FROM {LEGS_TABLE} WHERE {FILTER}
      )
      SELECT *, extract(hour from et_naive)::int AS et_hour,
                extract(dow from et_naive)::int AS et_dow
      FROM base
      WHERE extract(dow from et_naive)::int = 5
        AND extract(hour from et_naive)::int IN (10, 15)
      ORDER BY trade_id LIMIT 4""")
    print(f"\nfriday rows = {len(fri)}")

    # Hour 00 ET - forced in explicitly (the case the branch exists for).
    h00 = q(conn, f"""
      WITH base AS (
        SELECT {BASE_COLS},
          coalesce(original_execution_timestamp, execution_timestamp) AT TIME ZONE 'America/New_York' AS et_naive
        FROM {LEGS_TABLE} WHERE {FILTER}
      )
      SELECT *, extract(hour from et_naive)::int AS et_hour,
                extract(dow from et_naive)::int AS et_dow
      FROM base
      WHERE extract(hour from et_naive)::int = 0
      ORDER BY trade_id LIMIT 4""")
    print(f"hour-00 rows = {len(h00)}")

    ff = q(conn, f"""
      WITH base AS (
        SELECT {BASE_COLS},
          coalesce(original_execution_timestamp, execution_timestamp) AT TIME ZONE 'America/New_York' AS et_naive
        FROM {LEGS_TABLE} WHERE {FILTER} AND rate_index_clean = 'FED_FUNDS'
      )
      SELECT *, extract(hour from et_naive)::int AS et_hour,
                extract(dow from et_naive)::int AS et_dow
      FROM base ORDER BY trade_id LIMIT 3""")
    print(f"fed funds rows = {len(ff)}")
    conn.close()

    # Assemble: one per hour bucket first, then the forced cases.
    # Prefer SOFR per hour bucket (it is 97 % of the tape); Fed Funds is forced
    # in separately below so both assets are still exercised.
    pool["_pref"] = (pool["rate_index_clean"] != "SOFR").astype(int)
    hourly = (pool.sort_values(["et_hour", "_pref", "rn"])
                  .groupby("et_hour", as_index=False).head(1))
    sample = pd.concat([hourly, h00, fri, ff], ignore_index=True)
    sample = sample.drop_duplicates(subset=["trade_id"]).reset_index(drop=True)

    store = CurveStore.default()
    out = []
    for _, r in sample.iterrows():
        curve = CURVE_FOR[r["rate_index_clean"]]
        asset = f"{curve}-CITIVELOEXCELMIN"
        snap = snap_timestamp(r["original_execution_timestamp"], r["execution_timestamp"])
        snap_ts = pd.Timestamp(snap)
        pubs = citi_session.publishes(curve, snap_ts)
        local_date = snap_ts.tz_convert("America/New_York").date()
        dens = day_density(store, asset, local_date)
        # covers() with the default 5-minute tolerance, and again with 2 hours
        # so a nightly-hole request is distinguishable from a dead day.
        cov5 = dens.covers(snap_ts) if dens.present else False
        cov2h = dens.covers(snap_ts, tolerance=datetime.timedelta(hours=2)) if dens.present else False
        out.append({
            "trade_id": r["trade_id"],
            "as_of_date": r["as_of_date"],
            "index": r["rate_index_clean"],
            "curve": curve,
            "tenor_label": r["tenor_label"],
            "tenor_years": float(r["tenor_years"]),
            "effective_date": r["effective_date"],
            "expiration_date": r["expiration_date"],
            "notional": float(r["notional"]),
            "fixed_rate": float(r["fixed_rate"]),
            "exec_ts": r["execution_timestamp"],
            "orig_exec_ts": r["original_execution_timestamp"],
            "snap_et": snap_ts.tz_convert("America/New_York").isoformat(),
            "snap_utc": snap_ts.tz_convert("UTC").isoformat(),
            "et_hour": int(r["et_hour"]),
            "et_dow": int(r["et_dow"]),
            "publishes": bool(pubs),
            "day_n_snapshots": int(dens.n_snapshots),
            "day_first_utc": dens.first_utc,
            "day_last_utc": dens.last_utc,
            "day_max_gap_s": dens.max_gap_s,
            "covers_5min": bool(cov5),
            "covers_2h": bool(cov2h),
        })
    df = pd.DataFrame(out).sort_values(["et_hour", "index"]).reset_index(drop=True)
    df.to_csv("C:/Users/chris/clee/ARBS-dd/scratch/out_sample20.csv", index=False)
    print(f"\n=== sample ({len(df)} prints) ===")
    print(df[["trade_id", "index", "tenor_label", "snap_et", "et_dow", "publishes",
              "day_n_snapshots", "covers_5min", "covers_2h", "fixed_rate"]].to_string())
    print("\ncounts: publishes True/False =",
          int(df["publishes"].sum()), "/", int((~df["publishes"]).sum()),
          "| covers_5min True/False =",
          int(df["covers_5min"].sum()), "/", int((~df["covers_5min"]).sum()))
    print("hour-00 prints:", int((df["et_hour"] == 0).sum()),
          "| friday prints:", int((df["et_dow"] == 5).sum()),
          "| fed funds:", int((df["index"] == "FED_FUNDS").sum()))


if __name__ == "__main__":
    main()
