"""Build a par swap at 3/30, then mark its NPV against the 4/21 curve.

Mimics what the engine does on unwind: keep the same swap (with fixed_rate
locked at construction) but mark NPV using the new pricer.
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


def main() -> int:
    NYC = pytz.timezone("America/New_York")
    mdp = IRSwapsMDP(source="BARCHART_STIRF-RL")

    open_asof = NYC.localize(datetime.datetime(2026, 3, 30, 17, 0))
    close_asof = NYC.localize(datetime.datetime(2026, 4, 21, 17, 0))

    q = IRSwapQuery(
        structure=IRSwapStructure.OUTRIGHT,
        curve="USD-SOFR-1D-Q12STIRT",
        tenor="IMM_U2026xIMM_Z2026",
        structure_kwargs={"bpv": 100_000.0},
    )

    pricer_open = mdp.get_pricer(q.build_mdp_request(open_asof))
    pkg_open, rws = q.resolve_package(pricer_or_curve=pricer_open)
    swap_open = pkg_open[0]
    print(f"Built at 3/30: fixed_rate={swap_open.fixed_rate}, notional={swap_open.kwargs.get('notional')}")
    vmap_open = q.build_value_map(pricer_or_curve=pricer_open, package=pkg_open, risk_weights=rws)
    print(f"  NPV at 3/30 (par)   = {float(vmap_open.apply(value=IRSwapValue.NPV)):,.2f}")
    print(f"  par_rate at 3/30    = {float(vmap_open.apply(value=IRSwapValue.RATE)):.4f}")

    # Re-mark with 4/21 pricer using SAME swap (preserve fixed_rate)
    pricer_close = mdp.get_pricer(q.build_mdp_request(close_asof))
    print(f"\nMarked at 4/21 against same swap:")
    vmap_close = q.build_value_map(pricer_or_curve=pricer_close, package=pkg_open, risk_weights=rws)
    npv_close = float(vmap_close.apply(value=IRSwapValue.NPV))
    print(f"  NPV at 4/21         = {npv_close:,.2f}")
    print(f"  par_rate at 4/21    = {float(vmap_close.apply(value=IRSwapValue.RATE)):.4f}")
    print(f"  Δrate (4/21 - 3/30) = {float(vmap_close.apply(value=IRSwapValue.RATE)) - float(vmap_open.apply(value=IRSwapValue.RATE)):.4f}%")
    print(f"  Δrate in bp        = {(float(vmap_close.apply(value=IRSwapValue.RATE)) - float(vmap_open.apply(value=IRSwapValue.RATE))) * 100:.2f}")
    print(f"  Expected NPV (PAY,bpv=100k): -Δrate_bp × 100,000 = {-((float(vmap_close.apply(value=IRSwapValue.RATE)) - float(vmap_open.apply(value=IRSwapValue.RATE))) * 100) * 100_000:,.0f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
