"""Requirement 3, end to end: the SAME unit through BOTH curve sources.

The tie-out is two measurements that each vary one thing (LEDGER D11): hold the
Barchart curve constant and swap old code for new, then hold the new code
constant and swap Barchart for the Citi minute curve. The second half has been
exercised all day; the first has only ever run against a fake, and the legacy
branch is the one with the different constructor path (no snapshot policy, one
pricer, ``.meta()`` with no snapshot keys).

So: one real leg, both sources, same instant. What must hold is not that the two
mids agree -- F-20 says they will not, by about half a basis point -- but that
the legacy path *runs*, labels itself ``LEGACY_NO_SNAPSHOT_POLICY``, and reports
its null lag as policy rather than as a fault.
"""
from __future__ import annotations

import datetime
import os
import sys

os.environ.setdefault("ARBS_SUPABASE_ENABLED", "0")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import pandas as pd

from dd_measure import LEG_COLS, connect, read_sql, unit_from_leg
from SDRUtils._swappulse_scripts._tape_tables import LEGS_TABLE
from SDRUtils.dealer_direction import midprice, snapshot


def main() -> None:
    conn = connect()
    legs = read_sql(conn, f"""
        SELECT {LEG_COLS} FROM {LEGS_TABLE} l
        WHERE l.as_of_date = DATE '2026-04-01'
          AND l.economic_class='ECONOMIC_FLOW' AND l.contributes_to_flow
          AND l.rate_index_clean = 'SOFR'
          AND coalesce(l.trade_type,'') = 'OUTRIGHT'
          AND NOT coalesce(l.is_off_market,false)
          AND l.tenor_years BETWEEN 1.5 AND 2.5
          AND l.execution_timestamp::time BETWEEN TIME '14:00' AND TIME '18:00'
        ORDER BY l.execution_timestamp LIMIT 4""")
    conn.close()
    print(f"{len(legs)} candidate legs\n")

    citi = midprice.UnitRepricer.for_source(snapshot.CURVE_SOURCE)
    legacy = midprice.UnitRepricer.for_source(snapshot.LEGACY_CURVE_SOURCE)
    print(f"legacy pricer: source={legacy.pricer.source!r} "
          f"snapshot_governed={legacy.pricer.snapshot_governed} "
          f"policies={legacy.pricer.policies} "
          f"curve_for(SOFR)={legacy.pricer.curve_for('SOFR')!r}")
    print(f"citi   pricer: source={citi.pricer.source!r} "
          f"snapshot_governed={citi.pricer.snapshot_governed} "
          f"policies={citi.pricer.policies} "
          f"curve_for(SOFR)={citi.pricer.curve_for('SOFR')!r}\n")

    ok = True
    for _, r in legs.iterrows():
        unit, snap, _ = unit_from_leg(r, with_upfront=False)
        printed = float(r["fixed_rate"]) * 100.0
        out = {}
        for name, rep in (("citi", citi), ("legacy", legacy)):
            o = rep.price_unit(unit)
            out[name] = o
            if o.failure is None:
                print(f"  {r['trade_id']} {r['tenor_label']:>4s} "
                      f"{pd.Timestamp(snap).tz_convert(snapshot.NY):%Y-%m-%d %H:%M} "
                      f"{name:7s} curve={o.pricing.curve_name:34s} "
                      f"policy={o.pricing.snapshot_policy:24s} "
                      f"lag={o.pricing.snapshot_lag_seconds!s:6s} "
                      f"mid={o.pricing.leg_mid_pct[0]:.5f}%  "
                      f"diff={(printed - o.pricing.leg_mid_pct[0])*100:+7.3f}bp  "
                      f"dv01={o.pricing.structure_dv01:,.0f}")
            else:
                print(f"  {r['trade_id']} {name:7s} FAILED {o.failure}: "
                      f"{(o.failure_detail or '')[:100]}")
                ok = False
        lg = out["legacy"]
        if lg.failure is None:
            checks = {
                "policy is LEGACY_NO_SNAPSHOT_POLICY":
                    lg.pricing.snapshot_policy == midprice.POLICY_NONE,
                "lag is None (no snapshot machinery to report one)":
                    lg.pricing.snapshot_lag_seconds is None,
                "no LagTelemetryMissing flag was needed":
                    midprice.FLAG_NO_LAG_TELEMETRY not in lg.flags,
                "the legacy curve name came from stir_flow.config":
                    lg.pricing.curve_name == "USD-SOFR-1D-Q12xM12STIRT",
            }
            for k, v in checks.items():
                print(f"      {'ok ' if v else 'FAIL'} {k}")
                ok = ok and v
        print()

    ds = [(printed_diff(r, citi), printed_diff(r, legacy)) for _, r in legs.iterrows()]
    ds = [(a, b) for a, b in ds if a is not None and b is not None]
    if ds:
        gap = [b - a for a, b in ds]
        print(f"legacy minus citi (printed-mid), bp: "
              f"{['%+.3f' % g for g in gap]}  "
              f"-> the old mid sits BELOW the print by that much more, which is "
              f"F-20's ~0.5 bp level bias with the opposite sign convention on "
              f"(printed - mid)")
    print(f"\nboth sources usable end to end: {ok}")


def printed_diff(r, rep):
    unit, _, _ = unit_from_leg(r, with_upfront=False)
    o = rep.price_unit(unit)
    if o.failure is not None:
        return None
    return (float(r["fixed_rate"]) * 100.0 - o.pricing.leg_mid_pct[0]) * 100.0


if __name__ == "__main__":
    main()
