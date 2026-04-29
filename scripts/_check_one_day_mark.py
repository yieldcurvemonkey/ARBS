"""Check 3/30 vs 3/31 mark for SFRU26 outright."""
from __future__ import annotations
import datetime, sys
from pathlib import Path
import pytz

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from MDP.IRSwaps.IRSwapsMDP import IRSwapsMDP
from Query.IRSwaps.IRSwapQuery import IRSwapQuery
from Query.IRSwaps.IRSwapStructure import IRSwapStructure
from Query.IRSwaps.IRSwapValue import IRSwapValue


NYC = pytz.timezone("America/New_York")
mdp = IRSwapsMDP(source="BARCHART_STIRF-RL")
q = IRSwapQuery(
    structure=IRSwapStructure.OUTRIGHT,
    curve="USD-SOFR-1D-Q12STIRT",
    tenor="IMM_U2026xIMM_Z2026",
    structure_kwargs={"bpv": 100_000.0},
)

po = mdp.get_pricer(q.build_mdp_request(NYC.localize(datetime.datetime(2026, 3, 30, 17, 0))))
pkg, rws = q.resolve_package(pricer_or_curve=po)
print(f"OPEN 3/30  fair_rate = {float(q.build_value_map(pricer_or_curve=po, package=pkg, risk_weights=rws).apply(value=IRSwapValue.RATE)):.4f}")

pc = mdp.get_pricer(q.build_mdp_request(NYC.localize(datetime.datetime(2026, 3, 31, 17, 0))))
fresh_pkg, _ = q.resolve_package(pricer_or_curve=pc)
print(f"3/31 fresh fair_rate = {float(q.build_value_map(pricer_or_curve=pc, package=fresh_pkg, risk_weights=rws).apply(value=IRSwapValue.RATE)):.4f}")

# Direct mark of opened swap against 3/31 pricer
print(f"Direct  NPV (same swap, 3/31 pricer): {float(q.build_value_map(pricer_or_curve=pc, package=pkg, risk_weights=rws).apply(value=IRSwapValue.NPV)):,.2f}")
# Via resolve_pricable (engine path)
resolved = [pc.resolve_pricable(p, rw) for p, rw in zip(pkg, rws)]
print(f"resolve NPV (engine path):              {float(q.build_value_map(pricer_or_curve=pc, package=resolved, risk_weights=rws).apply(value=IRSwapValue.NPV)):,.2f}")
print(f"resolved.fixed_rate = {resolved[0].fixed_rate}")
print(f"resolved.notional.real = {getattr(resolved[0].kwargs.get('notional'), 'real', resolved[0].kwargs.get('notional'))}")
