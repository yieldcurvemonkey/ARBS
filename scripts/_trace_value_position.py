"""Reproduce the engine's value_position path and find the 2x magnitude leak.

Mimics the engine's mark_to_market call flow:
  1. Build position at open via PositionHandler.build_position
  2. Call PositionHandler.value_position at close timestamp

Compares against the manual NPV remark.
"""
from __future__ import annotations
import datetime, sys
from pathlib import Path
import pytz

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from MDP.IRSwaps.IRSwapsMDP import IRSwapsMDP
from Query.IRSwaps.IRSwapQuery import IRSwapQuery
from Query.IRSwaps.IRSwapStructure import IRSwapStructure
from Query.IRSwaps.IRSwapValue import IRSwapValue
from BT.position_handler import PositionHandler
from BT.query_order import QueryOrder
from Query.Base.query_resolution import resolve_query


class _BTStub:
    """Minimal backtest stub to satisfy PositionHandler interface."""

    pass


NYC = pytz.timezone("America/New_York")
mdp = IRSwapsMDP(source="BARCHART_STIRF-RL")

open_dt = NYC.localize(datetime.datetime(2026, 3, 30, 17, 0))
close_dt = NYC.localize(datetime.datetime(2026, 3, 31, 17, 0))

q = IRSwapQuery(
    structure=IRSwapStructure.OUTRIGHT,
    curve="USD-SOFR-1D-Q12STIRT",
    tenor="IMM_U2026xIMM_Z2026",
    structure_kwargs={"bpv": 100_000.0},
)

# === ENGINE PATH ===
handler = PositionHandler()
order = QueryOrder(timestamp=open_dt, query=q, meta={"action": "open"})

pricer_open = mdp.get_pricer(q.build_mdp_request(open_dt))
pricer_close = mdp.get_pricer(q.build_mdp_request(close_dt))

def pricer_provider_open(query):
    return pricer_open
def pricer_provider_close(query):
    return pricer_close

bt = _BTStub()

pos = handler.build_position(order, pricer_provider_open, open_dt, bt)
print(f"BUILD position:")
print(f"  package: {pos.package}")
print(f"  weights: {pos.weights}")
print(f"  source_query.fixed_rate: {pos.package[0].fixed_rate}")
print(f"  source_query.notional.real: {getattr(pos.package[0].kwargs.get('notional'), 'real', pos.package[0].kwargs.get('notional'))}")

# Mark at open (should be ~0)
v0 = handler.value_position(pos, pricer_provider_open, open_dt, bt)
print(f"\nvalue_position @ open: {v0:,.2f}")

# Mark at close
v1 = handler.value_position(pos, pricer_provider_close, close_dt, bt)
print(f"value_position @ close: {v1:,.2f}")

# === MANUAL PATH ===
manual_pkg, manual_rws = q.resolve_package(pricer_or_curve=pricer_open)
manual_swap = manual_pkg[0]
print(f"\nManual swap.fixed_rate: {manual_swap.fixed_rate}")
print(f"Manual swap.notional.real: {getattr(manual_swap.kwargs.get('notional'), 'real', manual_swap.kwargs.get('notional'))}")
manual_v1 = float(q.build_value_map(pricer_or_curve=pricer_close, package=manual_pkg, risk_weights=manual_rws).apply(value=IRSwapValue.NPV))
print(f"Manual NPV @ close (direct): {manual_v1:,.2f}")
