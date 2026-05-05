"""Top-level orchestrator for the STIR Options Asymmetric Screener.

``build_snapshot(config, as_of)`` wires every phase together and emits
a ``ScreenerSnapshot`` ranked by composite asymmetry score.
"""

from __future__ import annotations

import datetime
import logging
import math
from dataclasses import replace
from typing import Any, Callable, List, Mapping, Optional, Sequence, Tuple

import numpy as np

from RVUtils.STIRAsymmetricScreener._carry import CarryRecord, compute_carry
from RVUtils.STIRAsymmetricScreener._catalysts import (
    Catalyst,
    catalysts_inside_window,
    load_catalyst_calendar,
)
from RVUtils.STIRAsymmetricScreener._enumerate import ENUMERATOR_BY_ARCHETYPE
from RVUtils.STIRAsymmetricScreener._enumerate.conditional_curve import (
    enumerate_conditional_curve,
)
from RVUtils.STIRAsymmetricScreener._gates import GATE_BY_ARCHETYPE
from RVUtils.STIRAsymmetricScreener._greeks import compute_greeks
from RVUtils.STIRAsymmetricScreener._market_data import (
    STIRMarketData,
    load_market_data,
)
from RVUtils.STIRAsymmetricScreener._path import (
    FOMCPath,
    extract_fomc_path,
)
from RVUtils.STIRAsymmetricScreener._payoff import (
    PayoffSummary,
    breakevens,
    max_payoff_loss,
)
from RVUtils.STIRAsymmetricScreener._rnd import (
    RNDRecord,
    extract_per_expiry_rnd,
    payoff_zone_probability,
)
from RVUtils.STIRAsymmetricScreener._scoring import (
    composite_asymmetry_score,
    normalize_carry_quality,
    normalize_liquidity,
    normalize_payoff_multiple,
    normalize_probability_edge,
)
from RVUtils.STIRAsymmetricScreener._sdr import is_sdr_confirmed
from RVUtils.STIRAsymmetricScreener._signals import (
    SignalKind,
    compute_all_signals,
)
from RVUtils.STIRAsymmetricScreener._types import (
    ArchetypeType,
    CandidateDef,
    CandidateResult,
    ScreenerConfig,
    ScreenerSnapshot,
)

logger = logging.getLogger(__name__)


def _net_premium_ticks_for_candidate(candidate: CandidateDef, *, smile) -> float:
    """Compute net entry premium in ticks using SABR-modeled prices.

    Falls back to leg-observed premiums when present; uses Bachelier
    pricing under the smile otherwise.
    """
    from RVUtils.ImpliedDistribution._bachelier import (
        bachelier_call_prices_vectorized,
    )

    forward = float(smile.params.forward_price)
    tte = float(smile.params.time_to_expiry)
    strikes = np.array([leg.strike for leg in candidate.legs], dtype=float)
    vols = np.asarray(
        smile.normal_vol(strikes, strike_space="price", vol_units="price"),
        dtype=float,
    )
    vols = np.maximum(vols, 1e-8)
    call_prices = bachelier_call_prices_vectorized(strikes, forward, vols, tte, 1.0)
    total_price = 0.0
    for i, leg in enumerate(candidate.legs):
        if not math.isnan(leg.premium_ticks):
            # Use observed premium when available
            total_price += float(leg.quantity) * (leg.premium_ticks / 100.0)
            continue
        if leg.right == "C":
            leg_price = float(call_prices[i])
        else:
            leg_price = float(call_prices[i] - (forward - leg.strike))
        total_price += float(leg.quantity) * leg_price
    return total_price * 100.0


def _aggregate_oi_for_candidate(candidate: CandidateDef, md: STIRMarketData) -> float:
    """Sum |open_interest| across the candidate's legs (anywhere on this contract)."""
    total = 0.0
    for leg in candidate.legs:
        lm = md.leg_market.get((leg.contract, leg.expiry, leg.right, leg.strike))
        if lm is not None and not math.isnan(lm.open_interest):
            total += float(lm.open_interest)
    return total


def _aggregate_bid_ask_pct(candidate: CandidateDef, md: STIRMarketData) -> float:
    """Average (ask-bid)/mid across candidate legs."""
    pcts: List[float] = []
    for leg in candidate.legs:
        lm = md.leg_market.get((leg.contract, leg.expiry, leg.right, leg.strike))
        if lm is None:
            continue
        if math.isnan(lm.bid) or math.isnan(lm.ask):
            continue
        mid = (lm.bid + lm.ask) * 0.5
        if mid <= 0:
            continue
        pcts.append((lm.ask - lm.bid) / mid)
    if not pcts:
        return float("nan")
    return float(sum(pcts) / len(pcts))


def _build_candidate_result(
    *,
    candidate: CandidateDef,
    md: STIRMarketData,
    rnd: Optional[RNDRecord],
    fomc_path: FOMCPath,
    smile,
    payoff: PayoffSummary,
    greeks,
    carry: CarryRecord,
    signals,
    sdr_confirmation: bool,
    catalysts_in_window: int,
    composite,
    failed_gates: Tuple[str, ...],
) -> CandidateResult:
    # Structure-level path scenario
    path_scenario = ""
    path_delta_required_bp = 0.0
    if fomc_path.implied_meeting_rates:
        last_rate = fomc_path.implied_meeting_rates[-1]
        terminal_price = 100.0 - last_rate * 100.0
        # Direction: payoff zone to terminal price
        lo_p, hi_p = payoff.payoff_zone_price
        if math.isfinite(lo_p) and math.isfinite(hi_p):
            mid = 0.5 * (lo_p + hi_p)
            path_delta_required_bp = (mid - terminal_price) * -100.0
            path_scenario = f"payoff_at_~{mid:.4f}_from_terminal_{terminal_price:.4f}"

    # Probabilities — payoff zone in rate space
    p_rnd = float("nan")
    p_sabr = float("nan")
    p_div = float("nan")
    if rnd is not None and math.isfinite(payoff.payoff_zone_price[0]):
        lo_rate = 100.0 - max(payoff.payoff_zone_price)
        hi_rate = 100.0 - min(payoff.payoff_zone_price)
        p_rnd = payoff_zone_probability(rnd, density="rnd", lower_rate=lo_rate, upper_rate=hi_rate)
        if rnd.sabr_density_on_same_grid is not None:
            p_sabr = payoff_zone_probability(rnd, density="sabr", lower_rate=lo_rate, upper_rate=hi_rate)
            if math.isfinite(p_sabr) and math.isfinite(p_rnd):
                p_div = abs(p_rnd - p_sabr)

    # Triggers
    triggers = tuple(s.kind.value for s in signals if s.triggered)

    # Liquidity score component
    oi_total = _aggregate_oi_for_candidate(candidate, md)
    bid_ask_pct = _aggregate_bid_ask_pct(candidate, md)
    liquidity = normalize_liquidity(open_interest_total=oi_total, bid_ask_pct=bid_ask_pct)

    return CandidateResult(
        candidate_def=candidate,
        ref_underlying_price=float(smile.params.forward_price),
        net_premium=float(_net_premium_ticks_for_candidate(candidate, smile=smile)),
        max_payoff=float(payoff.max_payoff_ticks),
        max_loss=float(payoff.max_loss_ticks),
        breakevens=tuple(breakevens(candidate.legs, net_premium_ticks=_net_premium_ticks_for_candidate(candidate, smile=smile))),
        payoff_zone=tuple(payoff.payoff_zone_price),
        delta=float(greeks.delta_dv01),
        gamma=float(greeks.gamma_per_bp_squared),
        vega=float(greeks.vega_per_volpoint),
        theta=float(greeks.theta_per_day),
        vega_aged_1m=float(greeks.vega_aged_1m),
        theta_to_expiry=float(greeks.theta_aged_3m),
        carry_3m=float(carry.carry_3m),
        carry_to_expiry=float(carry.carry_to_expiry),
        asymmetry_ratio=float(
            payoff.max_payoff_ticks / abs(payoff.max_loss_ticks)
            if payoff.max_loss_ticks < 0
            else 9999.0
        ),
        implied_prob_full_payoff_rnd=float(p_rnd) if math.isfinite(p_rnd) else float("nan"),
        implied_prob_full_payoff_sabr=float(p_sabr) if math.isfinite(p_sabr) else float("nan"),
        prob_density_divergence=float(p_div) if math.isfinite(p_div) else float("nan"),
        conditional_prob_full_payoff=0.0,  # default; user-supplied via signal injection
        prob_edge=0.0,
        prob_source="rnd" if rnd is not None and rnd.stability_flag == "stable" else "sabr_fallback",
        path_scenario=path_scenario,
        path_delta_required_bp=float(path_delta_required_bp),
        triggers=triggers,
        catalyst_count=int(catalysts_in_window),
        liquidity_score=float(liquidity),
        sdr_confirmation=bool(sdr_confirmation),
        composite_score=float(composite.composite),
        failed_gates=failed_gates,
        composite_components={
            "payoff_multiple": composite.payoff_multiple_score,
            "probability_edge": composite.probability_edge_score,
            "carry_quality": composite.carry_quality_score,
            "liquidity": composite.liquidity_score,
        },
        payoff_multiple_score=composite.payoff_multiple_score,
        probability_edge_score=composite.probability_edge_score,
        carry_quality_score=composite.carry_quality_score,
        liquidity_score_component=composite.liquidity_score,
    )


def build_snapshot(
    config: ScreenerConfig,
    *,
    as_of: datetime.date,
    md: Optional[STIRMarketData] = None,
    smile_loader: Optional[Callable[..., Any]] = None,
    curve_loader: Optional[Callable[..., Any]] = None,
    fomc_schedule_loader: Optional[Callable[..., Any]] = None,
    leg_quote_loader: Optional[Callable[..., Any]] = None,
    history_loader: Optional[Callable[..., Any]] = None,
    block_trade_loader: Optional[Callable[..., Any]] = None,
    fair_path_bp: Sequence[float] = (),
    conditional_prob_fn: Optional[Callable[..., float]] = None,
) -> ScreenerSnapshot:
    """Run the full screener pipeline and return a ranked snapshot."""

    # 1. Market data
    if md is None:
        md = load_market_data(
            config,
            as_of=as_of,
            smile_loader=smile_loader,
            curve_loader=curve_loader,
            fomc_schedule_loader=fomc_schedule_loader,
            leg_quote_loader=leg_quote_loader,
            history_loader=history_loader,
        )

    warnings = list(md.warnings)

    # 2. RND per universe entry
    rnds: dict = {}
    for entry in md.universe:
        smile = md.smiles.get((entry.contract, entry.expiry))
        if smile is None:
            continue
        try:
            rnd = extract_per_expiry_rnd(
                smile=smile,
                leg_market=md.leg_market,
                config=config,
                as_of=as_of,
            )
            rnds[(entry.contract, entry.expiry)] = rnd
        except Exception as exc:  # noqa: BLE001
            warnings.append(f"rnd_failed:{entry.contract}:{exc}")

    # 3. FOMC path
    spot_target = float(getattr(md.curve_handle, "spot_target", 0.0445))  # ~445bp default
    try:
        fomc_path = extract_fomc_path(
            as_of=as_of,
            curve_handle=md.curve_handle,
            fomc_schedule=md.fomc_schedule,
            spot_target=spot_target,
        )
    except Exception as exc:  # noqa: BLE001
        warnings.append(f"fomc_path_failed:{exc}")
        fomc_path = FOMCPath(
            as_of=as_of,
            meetings=tuple(),
            meeting_labels=tuple(),
            spot_target=spot_target,
            implied_meeting_rates=tuple(),
            cumulative_change_bp=tuple(),
            marginal_change_bp=tuple(),
        )

    # 4. Catalysts
    try:
        catalysts = load_catalyst_calendar(
            as_of=as_of, lookahead_days=config.dte_ceiling + 30
        )
    except Exception as exc:  # noqa: BLE001
        warnings.append(f"catalysts_failed:{exc}")
        catalysts = tuple()

    # 5. Per-archetype enumeration + per-candidate evaluation
    results: List[CandidateResult] = []
    for entry in md.universe:
        smile = md.smiles.get((entry.contract, entry.expiry))
        if smile is None:
            continue
        rnd = rnds.get((entry.contract, entry.expiry))
        catalysts_count = len(
            catalysts_inside_window(
                as_of=as_of,
                expiry=entry.expiry,
                catalysts=catalysts,
                impact="high",
            )
        )

        for archetype in config.archetypes:
            try:
                if archetype is ArchetypeType.CONDITIONAL_CURVE:
                    defs = enumerate_conditional_curve(
                        entry,
                        rnd=rnd,
                        fomc_path=fomc_path,
                        config=config,
                        all_entries=md.universe,
                    )
                elif archetype is ArchetypeType.RISK_REVERSAL:
                    defs = ENUMERATOR_BY_ARCHETYPE[archetype](
                        entry, rnd=rnd, fomc_path=fomc_path, smile=smile, config=config
                    )
                else:
                    defs = ENUMERATOR_BY_ARCHETYPE[archetype](
                        entry, rnd=rnd, fomc_path=fomc_path, config=config
                    )
            except Exception as exc:  # noqa: BLE001
                warnings.append(f"enumerate_failed:{archetype.value}:{exc}")
                continue

            for cdef in defs:
                try:
                    net_premium = _net_premium_ticks_for_candidate(cdef, smile=smile)
                    payoff = max_payoff_loss(
                        cdef.legs, net_premium_ticks=net_premium
                    )
                    greeks = compute_greeks(
                        legs=cdef.legs,
                        smile=smile,
                        as_of_tte=float(smile.params.time_to_expiry),
                    )
                    carry = compute_carry(
                        legs=cdef.legs,
                        smile=smile,
                        base_tte=float(smile.params.time_to_expiry),
                        net_premium_ticks=net_premium,
                    )
                    sdr_conf = is_sdr_confirmed(
                        candidate=cdef,
                        as_of=as_of,
                        block_trade_loader=block_trade_loader,
                    )
                    cond_prob = 0.0
                    if conditional_prob_fn is not None:
                        try:
                            cond_prob = float(
                                conditional_prob_fn(candidate=cdef, payoff=payoff, rnd=rnd)
                            )
                        except Exception:
                            cond_prob = 0.0
                    signals = compute_all_signals(
                        candidate=cdef,
                        md=md,
                        rnd=rnd,
                        fomc_path=fomc_path,
                        payoff_summary=payoff,
                        carry=carry,
                        conditional_prob_full_payoff=cond_prob,
                        fair_path_bp=fair_path_bp,
                        sdr_confirmation=sdr_conf,
                        config=config,
                    )
                    gate = GATE_BY_ARCHETYPE[archetype](
                        candidate=cdef,
                        signals=signals,
                        payoff=payoff,
                        greeks=greeks,
                        carry=carry,
                        rnd=rnd,
                        config=config,
                    )
                    if not gate.passed:
                        continue

                    # Composite score
                    asymm_ratio = (
                        payoff.max_payoff_ticks / abs(payoff.max_loss_ticks)
                        if payoff.max_loss_ticks < 0
                        else 9999.0
                    )
                    pm = normalize_payoff_multiple(asymm_ratio)
                    pe = normalize_probability_edge(cond_prob)
                    cq = normalize_carry_quality(carry.carry_3m, net_premium)
                    oi = _aggregate_oi_for_candidate(cdef, md)
                    ba = _aggregate_bid_ask_pct(cdef, md)
                    lq = normalize_liquidity(oi, ba)
                    score = composite_asymmetry_score(
                        payoff_multiple=pm,
                        probability_edge=pe,
                        carry_quality=cq,
                        liquidity=lq,
                        weights=config.composite_weights,
                    )

                    result = _build_candidate_result(
                        candidate=cdef,
                        md=md,
                        rnd=rnd,
                        fomc_path=fomc_path,
                        smile=smile,
                        payoff=payoff,
                        greeks=greeks,
                        carry=carry,
                        signals=signals,
                        sdr_confirmation=sdr_conf,
                        catalysts_in_window=catalysts_count,
                        composite=score,
                        failed_gates=gate.failed_gates,
                    )
                    results.append(result)
                except Exception as exc:  # noqa: BLE001
                    warnings.append(
                        f"candidate_eval_failed:{cdef.candidate_id}:{exc}"
                    )
                    continue

    # 6. Sort by composite, attach ranks
    results.sort(key=lambda r: -r.composite_score)
    ranked: List[CandidateResult] = [
        replace(r, rank=i + 1) for i, r in enumerate(results)
    ]

    return ScreenerSnapshot(
        as_of=as_of,
        results=tuple(ranked),
        config_summary={
            "underlyings": list(config.underlyings),
            "include_midcurves": config.include_midcurves,
            "include_serials": config.include_serials,
            "include_weeklies": config.include_weeklies,
            "dte_floor": config.dte_floor,
            "dte_ceiling": config.dte_ceiling,
            "archetypes": [a.value for a in config.archetypes],
        },
        run_warnings=tuple(warnings),
    )
