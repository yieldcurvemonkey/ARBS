"""Sanity check: fair-rate of SFRU26 outright at 2026-03-30 and 2026-04-21."""

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


def _rate_at(mdp, asof, tenor):
    q = IRSwapQuery(
        structure=IRSwapStructure.OUTRIGHT,
        curve="USD-SOFR-1D-Q12STIRT",
        tenor=tenor,
        structure_kwargs={"bpv": 100_000.0},
    )
    pricer = mdp.get_pricer(q.build_mdp_request(asof))
    pkg, rws = q.resolve_package(pricer_or_curve=pricer)
    vmap = q.build_value_map(pricer_or_curve=pricer, package=pkg, risk_weights=rws)
    return float(vmap.apply(value=IRSwapValue.RATE)), float(vmap.apply(value=IRSwapValue.NPV))


def main() -> int:
    NYC = pytz.timezone("America/New_York")
    mdp = IRSwapsMDP(source="BARCHART_STIRF-RL")

    for tenor in ("IMM_U2026xIMM_Z2026", "IMM_Z2026xIMM_H2027", "IMM_H2027xIMM_M2027"):
        for d in (datetime.date(2026, 3, 30), datetime.date(2026, 4, 21), datetime.date(2026, 4, 28)):
            asof = NYC.localize(datetime.datetime(d.year, d.month, d.day, 17, 0))
            r, npv = _rate_at(mdp, asof, tenor)
            # RATE is reported × 100 for outrights, so /100 for the actual rate.
            print(f"{tenor} @ {d}: rate={r:.4f} (per IRSwapValue.RATE convention)  NPV(par)={npv:.2f}")
        print("---")
    return 0


if __name__ == "__main__":
    sys.exit(main())
