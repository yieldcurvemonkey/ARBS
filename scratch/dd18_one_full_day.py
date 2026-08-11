"""Does the per-day scope actually bound anything, and what does a real day cost?

dd12's draw averaged 1.8 legs per day, so its "peak 5 handles" says nothing
about the thing the scope exists for: ~795 distinct SOFR curve-minutes a day,
610 days, ~500k rl.Curve objects in ``CurvePricer._handles`` with nothing ever
evicting them.

This prices **every** eligible SOFR and Fed Funds flow leg on one ordinary
trading day, reports the handle count as it grows and after the scope exits, and
gives the real per-day wall clock the 610-day projection needs.
"""
from __future__ import annotations

import os
import sys
import time

os.environ.setdefault("ARBS_SUPABASE_ENABLED", "0")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import pandas as pd

from dd_measure import LEG_COLS, connect, read_sql, unit_from_leg
from SDRUtils._swappulse_scripts._tape_tables import LEGS_TABLE
from SDRUtils.dealer_direction import midprice, snapshot

pd.set_option("display.width", 240)

DAY = "2026-04-01"      # an ordinary Wednesday, dense in the minute store


def main() -> None:
    conn = connect()
    legs = read_sql(conn, f"""
        SELECT {LEG_COLS} FROM {LEGS_TABLE} l
        WHERE l.as_of_date = %(d)s
          AND l.economic_class='ECONOMIC_FLOW' AND l.contributes_to_flow
          AND l.rate_index_clean IN ('SOFR','FED_FUNDS')
          AND l.fixed_rate IS NOT NULL AND l.effective_date IS NOT NULL
          AND l.expiration_date IS NOT NULL AND l.notional IS NOT NULL
        ORDER BY l.execution_timestamp, l.trade_id""", {"d": DAY})
    conn.close()
    print(f"{DAY}: {len(legs)} eligible flow legs "
          f"({legs['rate_index_clean'].value_counts().to_dict()})")

    rep = midprice.UnitRepricer.for_source(snapshot.CURVE_SOURCE)
    t0 = time.perf_counter()
    ok = 0
    reasons: dict = {}
    marks = []
    with rep.day_scope():
        for i, (_, r) in enumerate(legs.iterrows(), 1):
            unit, _, _ = unit_from_leg(r)
            out = rep.price_unit(unit)
            if out.failure is None:
                ok += 1
            else:
                reasons[out.failure] = reasons.get(out.failure, 0) + 1
            if i % 500 == 0 or i == len(legs):
                marks.append((i, rep.pricer.n_handles, time.perf_counter() - t0))
        peak = rep.pricer.n_handles
    after = rep.pricer.n_handles
    dt = time.perf_counter() - t0

    print("\n  legs priced |  handles held |  elapsed s")
    for i, h, e in marks:
        print(f"  {i:11d} | {h:13d} | {e:9.1f}")
    print(f"\n  peak handles inside the scope: {peak}; after exit: {after}")
    print(f"  {ok}/{len(legs)} legs priced ({ok/len(legs):.1%}) in {dt:.0f}s "
          f"({dt/len(legs)*1000:.1f} ms/leg)")
    if reasons:
        print(f"  failures: {reasons}")
    print(f"\n  610-day single-process projection: {dt*610/3600:.1f} h, and "
          f"{peak * 610:,} handles WITHOUT the per-day scope (with it: {peak}).")


if __name__ == "__main__":
    main()
