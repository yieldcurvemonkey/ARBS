"""Check whether resolve_pricable() flips the notional sign."""

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
    n_open = swap_open.kwargs.get("notional")
    fr_open = swap_open.fixed_rate
    print(f"OPEN  swap.fixed_rate    = {fr_open}")
    print(f"OPEN  swap.notional.real = {getattr(n_open, 'real', n_open)}")
    print(f"OPEN  swap.notional      = {n_open}")

    pricer_close = mdp.get_pricer(q.build_mdp_request(close_asof))

    # Path 1: directly use the open swap (no resolve_pricable)
    vmap_direct = q.build_value_map(
        pricer_or_curve=pricer_close, package=[swap_open], risk_weights=rws,
    )
    print(f"\nDIRECT (use open swap, mark with close pricer)")
    print(f"  NPV = {float(vmap_direct.apply(value=IRSwapValue.NPV)):,.2f}")

    # Path 2: pass through resolve_pricable (what the engine does in mark_to_market)
    resolved_pkg = [pricer_close.resolve_pricable(swap_open, rw) for rw in rws]
    swap_resolved = resolved_pkg[0]
    n_res = swap_resolved.kwargs.get("notional")
    fr_res = swap_resolved.fixed_rate
    print(f"\nVIA resolve_pricable")
    print(f"  resolved.fixed_rate    = {fr_res}")
    print(f"  resolved.notional.real = {getattr(n_res, 'real', n_res)}")
    print(f"  resolved.notional      = {n_res}")

    vmap_via = q.build_value_map(
        pricer_or_curve=pricer_close, package=resolved_pkg, risk_weights=rws,
    )
    print(f"  NPV = {float(vmap_via.apply(value=IRSwapValue.NPV)):,.2f}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
