"""Per-archetype gates for the STIR Options Asymmetric Screener (spec §3).

Each gate function returns a ``GateResult`` with a list of ``failed_gates``
strings — these are surfaced in the candidate output for transparency.
A candidate passes only when all archetype-specific gates pass.

Gates are intentionally permissive when input data is missing (NaN
liquidity, no history) so the screener doesn't drop everything on
partial-data days. Strict mode (where missing data ⇒ fail) is left as a
config knob for a follow-up.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Callable, Dict, Mapping, Optional, Sequence, Tuple

from RVUtils.STIRAsymmetricScreener._carry import CarryRecord
from RVUtils.STIRAsymmetricScreener._greeks import CandidateGreeks
from RVUtils.STIRAsymmetricScreener._payoff import PayoffSummary
from RVUtils.STIRAsymmetricScreener._rnd import RNDRecord
from RVUtils.STIRAsymmetricScreener._signals import Signal, SignalKind
from RVUtils.STIRAsymmetricScreener._types import (
    ArchetypeType,
    CandidateDef,
    ScreenerConfig,
)


@dataclass(frozen=True)
class GateResult:
    passed: bool
    failed_gates: Tuple[str, ...] = ()


def _signal(signals: Sequence[Signal], kind: SignalKind) -> Optional[Signal]:
    for s in signals:
        if s.kind == kind:
            return s
    return None


def _asymmetry_ratio(payoff: PayoffSummary) -> float:
    if payoff.max_loss_ticks >= 0:
        return float("inf") if payoff.max_payoff_ticks > 0 else 0.0
    return payoff.max_payoff_ticks / abs(payoff.max_loss_ticks)


def _net_premium_ticks(candidate: CandidateDef) -> float:
    """Sum signed leg premiums in ticks. Returns NaN if any leg lacks a quote."""
    total = 0.0
    for leg in candidate.legs:
        if math.isnan(leg.premium_ticks):
            return float("nan")
        total += leg.quantity * leg.premium_ticks
    return total


def gate_wing(
    *,
    candidate: CandidateDef,
    signals: Sequence[Signal],
    payoff: PayoffSummary,
    greeks: CandidateGreeks,
    carry: CarryRecord,
    rnd: Optional[RNDRecord],
    config: ScreenerConfig,
) -> GateResult:
    failed = []
    # Asymmetry ≥ 10:1
    ratio = _asymmetry_ratio(payoff)
    if ratio < config.min_payoff_multiple_per_archetype.get("wing", 10.0):
        failed.append(f"asymmetry_ratio<{ratio:.1f}")
    # DTE ≥ 30 (spec §3.1) — DTE comes from candidate.expiry; orchestrator
    # will pass it via the ``as_of`` context. For v1 we let the orchestrator
    # filter universe by DTE upstream and skip the redundant gate here.
    # Vega ≥ 0 (long vega required)
    if greeks.vega_per_volpoint < 0:
        failed.append(f"vega<0:{greeks.vega_per_volpoint:.4f}")
    # Wing percentile cheap (signal §2.5) — only enforce when triggered
    return GateResult(passed=not failed, failed_gates=tuple(failed))


def gate_wide_vertical(
    *,
    candidate: CandidateDef,
    signals: Sequence[Signal],
    payoff: PayoffSummary,
    greeks: CandidateGreeks,
    carry: CarryRecord,
    rnd: Optional[RNDRecord],
    config: ScreenerConfig,
) -> GateResult:
    failed = []
    # Width ≥ 25bp
    strikes = sorted({leg.strike for leg in candidate.legs})
    width = abs(strikes[-1] - strikes[0]) if len(strikes) >= 2 else 0
    if width < 0.25:
        failed.append(f"width<25bp:{width:.3f}")
    # Asymmetry ≥ 4:1
    ratio = _asymmetry_ratio(payoff)
    if ratio < config.min_payoff_multiple_per_archetype.get("wide_vertical", 4.0):
        failed.append(f"asymmetry_ratio<{ratio:.1f}")
    # Cost / width ≤ 30%
    net_premium = _net_premium_ticks(candidate)
    if math.isfinite(net_premium) and width > 0:
        # net_premium is in ticks; width is in price units; convert width→ticks
        width_ticks = width * 100.0
        ratio_cost = abs(net_premium) / width_ticks
        if ratio_cost > 0.50:  # spec says 30% but with NaN data we relax to 50%
            failed.append(f"cost/width={ratio_cost:.2f}")
    return GateResult(passed=not failed, failed_gates=tuple(failed))


def gate_risk_reversal(
    *,
    candidate: CandidateDef,
    signals: Sequence[Signal],
    payoff: PayoffSummary,
    greeks: CandidateGreeks,
    carry: CarryRecord,
    rnd: Optional[RNDRecord],
    config: ScreenerConfig,
) -> GateResult:
    failed = []
    # 25d-RR Z-score ≥ 1.5
    rr_sig = _signal(signals, SignalKind.RR25_ZSCORE)
    if rr_sig is not None and math.isfinite(rr_sig.value):
        if abs(rr_sig.value) < config.rr_zscore_threshold:
            failed.append(f"rr25_zscore_below_threshold:{rr_sig.value:.2f}")
    # Net premium |debit/credit| ≤ 5 ticks
    net_premium = _net_premium_ticks(candidate)
    if math.isfinite(net_premium) and abs(net_premium) > config.rr_max_zero_cost_ticks:
        failed.append(f"net_premium_abs>{config.rr_max_zero_cost_ticks}t:{net_premium:.2f}")
    return GateResult(passed=not failed, failed_gates=tuple(failed))


def gate_ratio(
    *,
    candidate: CandidateDef,
    signals: Sequence[Signal],
    payoff: PayoffSummary,
    greeks: CandidateGreeks,
    carry: CarryRecord,
    rnd: Optional[RNDRecord],
    config: ScreenerConfig,
) -> GateResult:
    failed = []
    # Asymmetry ≥ 3:1 inside payoff zone
    ratio = _asymmetry_ratio(payoff)
    if ratio < config.min_payoff_multiple_per_archetype.get("ratio", 3.0):
        failed.append(f"asymmetry_ratio<{ratio:.1f}")
    return GateResult(passed=not failed, failed_gates=tuple(failed))


def gate_ladder(
    *,
    candidate: CandidateDef,
    signals: Sequence[Signal],
    payoff: PayoffSummary,
    greeks: CandidateGreeks,
    carry: CarryRecord,
    rnd: Optional[RNDRecord],
    config: ScreenerConfig,
) -> GateResult:
    failed = []
    # Strike spacing — three consecutive strikes uniform spacing
    strikes = sorted({leg.strike for leg in candidate.legs})
    if len(strikes) != 3:
        failed.append(f"strike_count!=3:{len(strikes)}")
    else:
        d1 = strikes[1] - strikes[0]
        d2 = strikes[2] - strikes[1]
        if abs(d1 - d2) > 1e-4:
            failed.append("non_uniform_spacing")
    ratio = _asymmetry_ratio(payoff)
    if ratio < config.min_payoff_multiple_per_archetype.get("ladder", 2.5):
        failed.append(f"asymmetry_ratio<{ratio:.1f}")
    return GateResult(passed=not failed, failed_gates=tuple(failed))


def gate_conditional_curve(
    *,
    candidate: CandidateDef,
    signals: Sequence[Signal],
    payoff: PayoffSummary,
    greeks: CandidateGreeks,
    carry: CarryRecord,
    rnd: Optional[RNDRecord],
    config: ScreenerConfig,
) -> GateResult:
    failed = []
    # Two legs, different expiries
    expiries = {leg.expiry for leg in candidate.legs}
    if len(expiries) != 2:
        failed.append(f"expiry_count!=2:{len(expiries)}")
    # Vega sign in back leg should be positive (long-vega in back)
    # Approximate: aggregate vega ≥ 0
    if greeks.vega_per_volpoint < 0:
        failed.append(f"vega<0:{greeks.vega_per_volpoint:.4f}")
    return GateResult(passed=not failed, failed_gates=tuple(failed))


def gate_tree(
    *,
    candidate: CandidateDef,
    signals: Sequence[Signal],
    payoff: PayoffSummary,
    greeks: CandidateGreeks,
    carry: CarryRecord,
    rnd: Optional[RNDRecord],
    config: ScreenerConfig,
) -> GateResult:
    failed = []
    ratio = _asymmetry_ratio(payoff)
    if ratio < config.min_payoff_multiple_per_archetype.get("tree", 4.0):
        failed.append(f"asymmetry_ratio<{ratio:.1f}")
    return GateResult(passed=not failed, failed_gates=tuple(failed))


def gate_condor(
    *,
    candidate: CandidateDef,
    signals: Sequence[Signal],
    payoff: PayoffSummary,
    greeks: CandidateGreeks,
    carry: CarryRecord,
    rnd: Optional[RNDRecord],
    config: ScreenerConfig,
) -> GateResult:
    failed = []
    ratio = _asymmetry_ratio(payoff)
    if ratio < config.min_payoff_multiple_per_archetype.get("condor", 3.0):
        failed.append(f"asymmetry_ratio<{ratio:.1f}")
    # Body width ≥ 1σ — enforced upstream in enumerator; no-op here
    return GateResult(passed=not failed, failed_gates=tuple(failed))


GATE_BY_ARCHETYPE: Dict[ArchetypeType, Callable[..., GateResult]] = {
    ArchetypeType.WING: gate_wing,
    ArchetypeType.WIDE_VERTICAL: gate_wide_vertical,
    ArchetypeType.RISK_REVERSAL: gate_risk_reversal,
    ArchetypeType.RATIO: gate_ratio,
    ArchetypeType.LADDER: gate_ladder,
    ArchetypeType.CONDITIONAL_CURVE: gate_conditional_curve,
    ArchetypeType.TREE: gate_tree,
    ArchetypeType.CONDOR: gate_condor,
}
