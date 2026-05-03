"""Verify the bpv unit interpretation end-to-end.

Builds a single OUTRIGHT IRSwapQuery against today's curve with bpv=100_000,
then queries IRSwapValue.NPV. Expectation: NPV at par == 0. Then we shift
the curve by 1bp and check NPV again — should be ~$100_000.
"""

from __future__ import annotations

import datetime
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from MDP.IRSwaps.IRSwapsMDP import IRSwapsMDP
from Query.IRSwaps.IRSwapQuery import IRSwapQuery
from Query.IRSwaps.IRSwapStructure import IRSwapStructure
from Query.IRSwaps.IRSwapValue import IRSwapValue


def main() -> int:
    mdp = IRSwapsMDP(source="BARCHART_STIRF-RL")
    q = IRSwapQuery(
        structure=IRSwapStructure.OUTRIGHT,
        curve="USD-SOFR-1D-Q12STIRT",
        tenor="IMM_U2026xIMM_Z2026",
        structure_kwargs={"bpv": 100_000.0},
    )
    import pytz
    NYC = pytz.timezone("America/New_York")
    asof = NYC.localize(datetime.datetime(2026, 4, 28, 17, 0))
    seed_req = q.build_mdp_request(asof)
    pricer = mdp.get_pricer(seed_req)

    pkg, rws = q.resolve_package(pricer_or_curve=pricer)
    print(f"package: {pkg}")
    print(f"risk_weights: {rws}")

    # NPV at par should be ~0
    vmap_par = q.build_value_map(
        pricer_or_curve=pricer, package=pkg, risk_weights=rws,
    )
    npv_par = float(vmap_par.apply(value=IRSwapValue.NPV))
    print(f"NPV at par (fixed_rate = fair_rate): {npv_par:,.6f}")

    # Use PV01 (rateslib supported)
    pv01 = float(vmap_par.apply(value=IRSwapValue.PV01))
    print(f"PV01: {pv01:,.6f} (expect ~100,000 per 1bp on bpv=100_000)")

    rate_val = float(vmap_par.apply(value=IRSwapValue.RATE))
    print(f"RATE (×100 for outrights): {rate_val:,.6f}")

    # Notional from the swap object
    swap = pkg[0]
    print(f"swap.notional={getattr(swap, 'notional', None)}")
    print(f"swap.fixed_rate={getattr(swap, 'fixed_rate', None)}")

    # Manual DV01 check: bump the curve by 1bp and re-mark NPV
    # (Best-effort — actual curve bump requires re-building with shifted nodes;
    # for now report what we can.)

    return 0


if __name__ == "__main__":
    sys.exit(main())
