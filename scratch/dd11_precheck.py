"""Known-answer pre-checks before any of the three measurements is trusted.

Each one is a way the study could measure something other than what it claims:

  C1  does ``citi_session.publishes`` even know the Fed Funds curve name? If it
      does not, every FF print reads "out of session" and the bias study
      silently measures the 2 h hole policy instead of the strict one.
  C2  how many minute snapshots does the FF store actually hold over the tape
      span? A sparse store masquerades as a curve bias.
  C3  how many FF on-market outrights survive the dd06 filters, and at which
      tenors? FF is 70k legs and skews short, so SOFR's 0.5y floor may starve
      the draw.
  C4  the four dd09 cases whose answers are already known, re-run through the
      SHIPPED module rather than through dd_common's parallel wiring.
"""
from __future__ import annotations

import os
import sys

os.environ.setdefault("ARBS_SUPABASE_ENABLED", "0")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import csv
import datetime
import warnings

import pandas as pd

pd.set_option("display.width", 240)


def main() -> None:
    from MDP.IRSwaps.CITIVELO_EXCEL.citi_session import publishes
    from SDRUtils.dealer_direction import midprice, snapshot

    print("=== C1: does the session model know the Fed Funds curve? ===")
    probes = {
        "Wed 14:30 ET": pd.Timestamp("2026-04-01 14:30", tz=snapshot.NY),
        "Wed 09:05 ET": pd.Timestamp("2026-04-01 09:05", tz=snapshot.NY),
        "Wed 00:30 ET": pd.Timestamp("2026-04-01 00:30", tz=snapshot.NY),
        "Sat 12:00 ET": pd.Timestamp("2026-04-04 12:00", tz=snapshot.NY),
    }
    for label, t in probes.items():
        print(f"  {label:14s} SOFR={publishes('USD-SOFR-1D', t)!s:5s} "
              f"FEDFUNDS={publishes('USD-FEDFUNDS-1D', t)!s:5s}")

    print("\n=== C2: minute-store day coverage over the tape span ===")
    for curve in ("USD-SOFR-1D", "USD-FEDFUNDS-1D"):
        path = f"C:/Users/chris/clee/ARBS-dd/scratch/out_coverage_{curve}-CITIVELOEXCELMIN.csv"
        with open(path) as fh:
            rows = [r for r in csv.DictReader(fh)
                    if "2024-03-01" <= r["date"] <= "2026-08-07"]
        snaps = [int(r["n_snapshots"]) for r in rows]
        weekdays = [r for r in rows
                    if datetime.date.fromisoformat(r["date"]).weekday() < 5]
        print(f"  {curve:18s} {len(rows)} stored days in span "
              f"({len(weekdays)} weekdays); snapshots/day "
              f"min {min(snaps)} median {sorted(snaps)[len(snaps)//2]} max {max(snaps)}")

    print("\n=== C3: the Fed Funds draw population ===")
    import psycopg2

    from SDRUtils._swappulse_scripts._tape_tables import LEGS_TABLE
    from SDRUtils._swappulse_scripts.ingest_usdswaps_tape import resolve_pg_url

    base = f"""
      FROM {LEGS_TABLE}
      WHERE economic_class='ECONOMIC_FLOW' AND contributes_to_flow
        AND rate_index_clean = 'FED_FUNDS'
        AND coalesce(trade_type,'') = 'OUTRIGHT'
        AND NOT is_off_market AND NOT is_mac AND NOT is_spreadover
        AND NOT is_asset_swap AND NOT coalesce(is_unwind,false)
        AND coalesce(is_new_risk, true)
        AND fixed_rate IS NOT NULL AND effective_date IS NOT NULL
        AND expiration_date IS NOT NULL AND notional IS NOT NULL
    """
    conn = psycopg2.connect(resolve_pg_url())
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        tot = pd.read_sql(f"SELECT count(*) n {base}", conn)["n"].iloc[0]
        bands = pd.read_sql(f"""
          SELECT width_bucket(tenor_years, ARRAY[0.08,0.25,0.5,1,2,3,5,10,31]) b,
                 count(*) n, min(tenor_years) lo, max(tenor_years) hi
          {base} GROUP BY 1 ORDER BY 1""", conn)
        strict = pd.read_sql(
            f"SELECT count(*) n {base} AND tenor_years BETWEEN 0.5 AND 31", conn
        )["n"].iloc[0]
        wide = pd.read_sql(
            f"SELECT count(*) n {base} AND tenor_years BETWEEN 0.08 AND 31", conn
        )["n"].iloc[0]
        span = pd.read_sql(f"SELECT min(as_of_date) a, max(as_of_date) b, "
                           f"count(distinct as_of_date) d {base}", conn)
    conn.close()
    print(f"  total FF on-market outrights: {tot}   "
          f"tenor>=0.5y: {strict}   tenor>=0.08y: {wide}")
    print(f"  span {span['a'].iloc[0]} .. {span['b'].iloc[0]} over {span['d'].iloc[0]} days")
    print(bands.to_string(index=False))

    print("\n=== C4: the four dd09 cases through the SHIPPED module ===")
    rep = midprice.UnitRepricer.for_source(snapshot.CURVE_SOURCE)
    br = rep.pricer
    snap = pd.Timestamp("2026-04-01 14:30:00", tz=snapshot.NY)
    cases = {
        "spot 5Y": (datetime.date(2026, 4, 3), datetime.date(2031, 4, 3), 3.631286),
        "fwd 1Yx5Y": (datetime.date(2027, 4, 5), datetime.date(2032, 4, 5), 3.672519),
        "past-start 2024-06-12": (datetime.date(2024, 6, 12), datetime.date(2029, 6, 12), 3.699197),
        "past-start 2020-01-15": (datetime.date(2020, 1, 15), datetime.date(2030, 1, 15), 3.603318),
    }
    ok = True
    for label, (eff, mat, known) in cases.items():
        lp = br.price_leg("USD-SOFR-1D", snap, eff, mat, 1e7, fixed_rate=0.04)
        agree = abs(lp.mid_pct - known) < 1e-5
        ok = ok and agree
        print(f"  {label:24s} mid={lp.mid_pct:.6f}% (dd09 {known:.6f}) "
              f"stratum={midprice.start_class(eff, snap):13s} "
              f"{'ok' if agree else 'DISAGREES'}")
    print(f"  shipped module reproduces the probe: {ok}")


if __name__ == "__main__":
    main()
