"""Verify the curve actually differs across dates."""

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

    for d in (datetime.date(2026, 3, 30), datetime.date(2026, 4, 21), datetime.date(2026, 4, 28)):
        asof = NYC.localize(datetime.datetime(d.year, d.month, d.day, 17, 0))
        q = IRSwapQuery(
            structure=IRSwapStructure.OUTRIGHT,
            curve="USD-SOFR-1D-Q12STIRT",
            tenor="IMM_U2026xIMM_Z2026",
            structure_kwargs={"bpv": 100_000.0},
        )
        req = q.build_mdp_request(asof)
        print(f"Date {d} -> request {req}")
        pricer = mdp.get_pricer(req)
        print(f"  pricer id: {id(pricer)}")
        # Reference date
        ref = pricer.reference_date() if hasattr(pricer, "reference_date") else "n/a"
        print(f"  pricer.reference_date() = {ref}")
        # Build a fresh par swap on this date
        pkg, rws = q.resolve_package(pricer_or_curve=pricer)
        vmap = q.build_value_map(pricer_or_curve=pricer, package=pkg, risk_weights=rws)
        print(f"  par_rate (fresh) = {float(vmap.apply(value=IRSwapValue.RATE)):.4f}")
        print(f"  swap.fixed_rate  = {getattr(pkg[0], 'fixed_rate', None)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
