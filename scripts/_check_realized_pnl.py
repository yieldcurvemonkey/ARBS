"""Reproduce the $10.5M realised P&L anomaly outside the engine.

Builds an outright IRS at 2026-03-30 with bpv=100_000 and fixed_rate=fair_rate
(par swap), then re-marks the position's NPV against the curve as of 2026-04-21
and 2026-04-28. Compares with the engine's realised P&L log.

Goal: distinguish between three hypotheses:
  (a) curve actually moved ~100bp (realised matches our manual NPV)
  (b) the swap's fixed_rate is set/stored in the wrong unit (10x or 100x)
  (c) the engine resolves the position against a different curve at unwind
"""

from __future__ import annotations

import datetime
import sys
from pathlib import Path

import pytz

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from MDP.IRSwaps.IRSwapsMDP import IRSwapsMDP
from Query.IRSwaps.IRSwapQuery import IRSwapQuery
from Query.IRSwaps.IRSwapStructure import IRSwapStructure
from Query.IRSwaps.IRSwapValue import IRSwapValue
from Query.Base.query_resolution import resolve_query


def main() -> int:
    NYC = pytz.timezone("America/New_York")
    mdp = IRSwapsMDP(source="BARCHART_STIRF-RL")

    open_dt = NYC.localize(datetime.datetime(2026, 3, 30, 17, 0))
    close_dt = NYC.localize(datetime.datetime(2026, 4, 21, 17, 0))
    final_dt = NYC.localize(datetime.datetime(2026, 4, 28, 17, 0))

    tenor = "IMM_U2026xIMM_Z2026"

    # 1) Build at 2026-03-30 (par swap)
    q0 = IRSwapQuery(
        structure=IRSwapStructure.OUTRIGHT,
        curve="USD-SOFR-1D-Q12STIRT",
        tenor=tenor,
        structure_kwargs={"bpv": 100_000.0},
    )
    pricer_open = mdp.get_pricer(q0.build_mdp_request(open_dt))
    q0_resolved = resolve_query(q0, timestamp=open_dt, pricer_or_curve=pricer_open)
    pkg_open, rws_open = q0_resolved.resolve_package(pricer_or_curve=pricer_open)
    swap_open = pkg_open[0]
    print(f"OPEN @ 2026-03-30")
    print(f"  swap.fixed_rate = {getattr(swap_open, 'fixed_rate', None)}")
    print(f"  swap.notional   = {getattr(swap_open, 'notional', None)}")
    vmap_open = q0_resolved.build_value_map(
        pricer_or_curve=pricer_open, package=pkg_open, risk_weights=rws_open,
    )
    print(f"  NPV (par)      = {float(vmap_open.apply(value=IRSwapValue.NPV)):,.2f}")
    print(f"  PV01            = {float(vmap_open.apply(value=IRSwapValue.PV01)):,.2f}")
    print(f"  fair_rate(open) = {float(vmap_open.apply(value=IRSwapValue.RATE)):.4f}")

    # 2) Re-mark at 2026-04-21 against same swap (preserved fixed_rate)
    pricer_close = mdp.get_pricer(q0_resolved.build_mdp_request(close_dt))
    q1 = resolve_query(q0_resolved, timestamp=close_dt, pricer_or_curve=pricer_close)
    pkg_close, rws_close = q1.resolve_package(pricer_or_curve=pricer_close)
    print(f"\nMARK @ 2026-04-21 (fixed_rate preserved from open)")
    print(f"  swap_close.fixed_rate = {getattr(pkg_close[0], 'fixed_rate', None)}")
    vmap_close = q1.build_value_map(
        pricer_or_curve=pricer_close, package=pkg_close, risk_weights=rws_close,
    )
    print(f"  NPV (today vs entry rate) = {float(vmap_close.apply(value=IRSwapValue.NPV)):,.2f}")
    print(f"  fair_rate(close)         = {float(vmap_close.apply(value=IRSwapValue.RATE)):.4f}")

    # 3) Final mark at 2026-04-28
    pricer_final = mdp.get_pricer(q0_resolved.build_mdp_request(final_dt))
    q2 = resolve_query(q0_resolved, timestamp=final_dt, pricer_or_curve=pricer_final)
    pkg_final, rws_final = q2.resolve_package(pricer_or_curve=pricer_final)
    vmap_final = q2.build_value_map(
        pricer_or_curve=pricer_final, package=pkg_final, risk_weights=rws_final,
    )
    print(f"\nMARK @ 2026-04-28")
    print(f"  NPV (today vs entry rate) = {float(vmap_final.apply(value=IRSwapValue.NPV)):,.2f}")
    print(f"  fair_rate(final)          = {float(vmap_final.apply(value=IRSwapValue.RATE)):.4f}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
