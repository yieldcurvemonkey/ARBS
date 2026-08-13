"""Probe 16: what one real tape day costs through the shipped krd.py.

Every eligible SOFR and Fed Funds flow leg on one ordinary trading day, in
execution order, through ``KrdProjector.krd_frame`` under the day scope -- the
real per-day wall clock the 610-day projection needs, plus the solver count the
block choice turns on.
"""
from __future__ import annotations

import os
import sys
import time

os.environ.setdefault("ARBS_SUPABASE_ENABLED", "0")
sys.path.insert(0, "C:/Users/chris/clee/ARBS-dd")
sys.path.insert(0, "C:/Users/chris/clee/ARBS-dd/scratch")

import pandas as pd

from dd_measure import LEG_COLS, connect, read_sql, unit_from_leg
from SDRUtils._swappulse_scripts._tape_tables import LEGS_TABLE
from SDRUtils.dealer_direction import conventions as conv
from SDRUtils.dealer_direction import krd as K
from SDRUtils.dealer_direction import types as T
from SDRUtils.dealer_direction.midprice import SessionBranchPricer

pd.set_option("display.width", 240)
DAY = os.environ.get("DDKRD_DAY", "2026-04-01")
BLOCKS = [int(x) for x in os.environ.get("DDKRD_BLOCKS", "60,30").split(",")]


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

    # Sort on the PRICING clock, not on #96: a row that does not mint a new UTI
    # prices on #30, and on 2026-04-01 that leaves 167 of 4,329 legs (3.9%) out
    # of order when the SQL sorts by execution_timestamp -- each of which the
    # lookahead guard then refuses.
    units, calls = [], []
    staged = []
    for _, r in legs.iterrows():
        u, snap, _ = unit_from_leg(r)
        staged.append((snap, u))
    staged.sort(key=lambda x: pd.Timestamp(x[0]))
    for _, u in staged:
        units.append(u)
        calls.append(T.DirectionCall(
            unit_key=u.unit_key, rule=conv.RULE_RATE, deviation_bps=1.0,
            p=0.9, signed_weight=conv.signed_weight(0.9), dealer_sign=1,
            tau_bucket="SOFR_5Y", tau_bps=0.35))
    print(f"  sorted on the pricing clock ({len(units)} units)")

    for block in BLOCKS:
        proj = K.KrdProjector(SessionBranchPricer(), block_minutes=block)
        t0 = time.perf_counter()
        with proj.day_scope():
            frame, failures = proj.krd_frame(units, calls)
            n_models = proj.n_models
            n_handles = proj.pricer.n_handles
        dt = time.perf_counter() - t0
        ok = frame["unit_key"].nunique() if len(frame) else 0
        print(f"\n  block={block:4d} min   {dt:7.1f} s   "
              f"{dt / max(len(units), 1) * 1000:6.2f} ms/unit   "
              f"solvers={n_models:4d}  curve handles={n_handles:5d}")
        print(f"    {ok}/{len(units)} units projected ({ok/len(units):.1%}), "
              f"{len(frame):,} risk rows ({len(frame)/max(ok,1):.1f} per unit)")
        if len(failures):
            print(f"    failures: "
                  f"{failures['failure_reason'].value_counts().to_dict()}")
            print("    first detail: " + str(failures['failure_detail'].iloc[0])[:160])
        print(f"    610-day single-process projection: {dt * 610 / 3600:5.2f} h")
        # what the solvers alone cost, so the block choice is priced
        print(f"    of which solver builds ~= {n_models * 0.30:6.1f} s "
              f"({n_models * 0.30 * 610 / 3600:.2f} h over 610 days)")


if __name__ == "__main__":
    main()
