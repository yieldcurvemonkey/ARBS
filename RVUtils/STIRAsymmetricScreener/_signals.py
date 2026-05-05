"""Signal computation for the STIR Options Asymmetric Screener (spec §2).

Each signal is a function that takes structured inputs (RND, FOMC path,
market data, candidate, config) and returns a ``Signal`` annotation. The
``compute_all_signals`` helper runs every applicable signal for a given
candidate.
"""

from __future__ import annotations

import datetime
import math
from dataclasses import dataclass
from enum import Enum
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

import numpy as np
import pandas as pd

from RVUtils.STIRAsymmetricScreener._carry import CarryRecord
from RVUtils.STIRAsymmetricScreener._market_data import LegMarket, STIRMarketData
from RVUtils.STIRAsymmetricScreener._payoff import PayoffSummary
from RVUtils.STIRAsymmetricScreener._path import (
    FOMCPath,
    cumulative_path_mispricing_bp,
)
from RVUtils.STIRAsymmetricScreener._rnd import (
    RNDRecord,
    payoff_zone_probability,
    sabr_rnd_payoff_zone_diff,
)
from RVUtils.STIRAsymmetricScreener._types import (
    ArchetypeType,
    CandidateDef,
    OptionLeg,
    ScreenerConfig,
)


class SignalKind(Enum):
    PATH_BIAS = "path_bias"
    RR25_ZSCORE = "rr25_zscore"
    TERM_STRUCTURE = "term_structure"
    OI_ANCHOR = "oi_anchor"
    WING_CHEAPNESS = "wing_cheapness"
    ATM_LEVEL = "atm_level"
    CARRY_QUALITY = "carry_quality"
    ASYMMETRY_RATIO = "asymmetry_ratio"
    RND_PROB_EDGE = "rnd_prob_edge"
    SABR_RND_DIVERGENCE = "sabr_rnd_divergence"
    SDR_COMOVEMENT = "sdr_comovement"


@dataclass(frozen=True)
class Signal:
    kind: SignalKind
    triggered: bool
    value: float
    detail: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "kind": self.kind.value,
            "triggered": self.triggered,
            "value": self.value,
            "detail": self.detail,
        }


# --- §2.1 Path mispricing ----------------------------------------------------


def signal_path_bias(
    *,
    fomc_path: FOMCPath,
    fair_path_bp: Sequence[float] = (),
    config: ScreenerConfig,
) -> Signal:
    """Spec §2.1: |market - fair| ≥ 50bp at any horizon ≤ 18m."""
    bias = cumulative_path_mispricing_bp(
        fomc_path=fomc_path, fair_path_bp=fair_path_bp
    )
    triggered = bias >= config.path_bias_threshold_bp
    return Signal(
        kind=SignalKind.PATH_BIAS,
        triggered=triggered,
        value=float(bias),
        detail=f"max_|delta|={bias:.1f}bp; threshold={config.path_bias_threshold_bp}bp",
    )


# --- §2.2 25d-RR Z-score -----------------------------------------------------


def signal_rr25_zscore(
    *,
    candidate: CandidateDef,
    iv_history: Mapping[Tuple[str, datetime.date], pd.DataFrame],
    config: ScreenerConfig,
) -> Signal:
    """Spec §2.2: rolling-1y |Z-score| of 25d-RR (IV(25d call) − IV(25d put))."""
    key = (candidate.underlying, candidate.expiry)
    df = iv_history.get(key)
    if df is None or df.empty or "rr25" not in df.columns:
        return Signal(
            kind=SignalKind.RR25_ZSCORE,
            triggered=False,
            value=float("nan"),
            detail="no_rr25_history",
        )
    series = df["rr25"].astype(float).dropna().tail(252)
    if len(series) < 30:
        return Signal(
            kind=SignalKind.RR25_ZSCORE,
            triggered=False,
            value=float("nan"),
            detail="insufficient_rr25_history",
        )
    current = float(series.iloc[-1])
    mean = float(series.mean())
    sd = float(series.std(ddof=0))
    if sd <= 0:
        return Signal(
            kind=SignalKind.RR25_ZSCORE,
            triggered=False,
            value=0.0,
            detail="zero_variance_rr25",
        )
    z = (current - mean) / sd
    return Signal(
        kind=SignalKind.RR25_ZSCORE,
        triggered=abs(z) >= config.rr_zscore_threshold,
        value=float(z),
        detail=f"current={current:.4f}, mean={mean:.4f}, sd={sd:.4f}",
    )


# --- §2.3 Term-structure vol spreads -----------------------------------------


def signal_term_structure(
    *,
    candidate: CandidateDef,
    md: STIRMarketData,
    config: ScreenerConfig,
) -> Signal:
    """Spec §2.3: percentile rank of front-vs-back ATM IV spread."""
    # Find a same-strike sibling expiry on the same underlying root
    target_root = candidate.underlying[:3]
    target_expiry = candidate.expiry
    siblings = [
        e for e in md.universe
        if e.option_root == target_root and e.expiry > target_expiry
    ]
    if not siblings:
        return Signal(
            kind=SignalKind.TERM_STRUCTURE,
            triggered=False,
            value=float("nan"),
            detail="no_siblings_for_term_structure",
        )
    front_smile = md.smiles.get((candidate.underlying, candidate.expiry))
    back_entry = sorted(siblings, key=lambda e: e.expiry)[0]
    back_smile = md.smiles.get((back_entry.contract, back_entry.expiry))
    if front_smile is None or back_smile is None:
        return Signal(
            kind=SignalKind.TERM_STRUCTURE,
            triggered=False,
            value=float("nan"),
            detail="missing_smile_for_term_structure",
        )
    try:
        atm_front = float(
            front_smile.normal_vol(
                front_smile.params.forward_price,
                strike_space="price",
                vol_units="price",
            )
        )
        atm_back = float(
            back_smile.normal_vol(
                back_smile.params.forward_price,
                strike_space="price",
                vol_units="price",
            )
        )
    except Exception:
        return Signal(
            kind=SignalKind.TERM_STRUCTURE,
            triggered=False,
            value=float("nan"),
            detail="atm_vol_unavailable",
        )
    spread = atm_front - atm_back
    # Without a 2y history we cannot compute a true percentile; emit raw spread
    # and let the user supply history downstream.
    return Signal(
        kind=SignalKind.TERM_STRUCTURE,
        triggered=False,  # threshold-based gating defers to history
        value=float(spread),
        detail=f"atm_front={atm_front:.4f}, atm_back={atm_back:.4f}, spread={spread:.4f}",
    )


# --- §2.4 OI anchors ---------------------------------------------------------


def signal_oi_anchors(
    *,
    candidate: CandidateDef,
    md: STIRMarketData,
    fomc_path: FOMCPath,
    config: ScreenerConfig,
) -> Signal:
    """Spec §2.4: candidate's anchor strike inside ±25bp of FOMC terminal."""
    strikes_in_play = sorted({leg.strike for leg in candidate.legs})
    if not strikes_in_play:
        return Signal(SignalKind.OI_ANCHOR, False, float("nan"), "no_strikes")

    # Pull OI for legs on this expiry
    oi_by_strike: Dict[float, float] = {}
    for (c, exp, right, k), lm in md.leg_market.items():
        if c == candidate.underlying and exp == candidate.expiry:
            oi_by_strike.setdefault(k, 0.0)
            oi_by_strike[k] += float(lm.open_interest) if not math.isnan(lm.open_interest) else 0.0

    # If no OI data: signal not triggered
    if not oi_by_strike or all(v == 0.0 for v in oi_by_strike.values()):
        return Signal(SignalKind.OI_ANCHOR, False, 0.0, "no_oi_data")

    median_oi = float(np.median(list(oi_by_strike.values())))
    anchors = {k for k, v in oi_by_strike.items() if v >= 2.0 * median_oi}
    matches = [k for k in strikes_in_play if k in anchors]

    # FOMC terminal alignment
    terminal_rate = (
        fomc_path.implied_meeting_rates[-1] * 100.0
        if fomc_path.implied_meeting_rates
        else float("nan")
    )
    aligned = False
    if matches and math.isfinite(terminal_rate):
        terminal_price = 100.0 - terminal_rate
        for k in matches:
            if abs(k - terminal_price) <= 0.25:
                aligned = True
                break
    return Signal(
        kind=SignalKind.OI_ANCHOR,
        triggered=aligned,
        value=float(len(matches)),
        detail=f"anchors_in_legs={len(matches)}, aligned_to_terminal={aligned}",
    )


# --- §2.5 Wing cheapness -----------------------------------------------------


def signal_wing_cheapness(
    *,
    candidate: CandidateDef,
    md: STIRMarketData,
    config: ScreenerConfig,
) -> Signal:
    """Spec §2.5: 5d-wing IV vs ATM, percentile ≤ 20% (cheap wings)."""
    smile = md.smiles.get((candidate.underlying, candidate.expiry))
    if smile is None:
        return Signal(SignalKind.WING_CHEAPNESS, False, float("nan"), "no_smile")
    try:
        wing_strike = float(smile.delta_to_strike(0.05, "P"))
        atm_vol = float(
            smile.normal_vol(
                smile.params.forward_price,
                strike_space="price",
                vol_units="price",
            )
        )
        wing_vol = float(
            smile.normal_vol(wing_strike, strike_space="price", vol_units="price")
        )
    except Exception:
        return Signal(
            SignalKind.WING_CHEAPNESS, False, float("nan"), "smile_eval_failed"
        )
    spread = wing_vol - atm_vol
    # Without history, we cannot percentile-rank — emit raw value with
    # triggered=False; downstream user can supply history.
    return Signal(
        kind=SignalKind.WING_CHEAPNESS,
        triggered=False,
        value=float(spread),
        detail=f"5d_wing_vol-atm={spread:.4f}",
    )


# --- §2.6 ATM level ----------------------------------------------------------


def signal_atm_level(
    *,
    candidate: CandidateDef,
    md: STIRMarketData,
    config: ScreenerConfig,
) -> Signal:
    """Spec §2.6: ATM IV percentile vs 1y / 2y window."""
    key = (candidate.underlying, candidate.expiry)
    df = md.iv_history.get(key)
    smile = md.smiles.get(key)
    if smile is None:
        return Signal(SignalKind.ATM_LEVEL, False, float("nan"), "no_smile")
    try:
        atm = float(
            smile.normal_vol(
                smile.params.forward_price,
                strike_space="price",
                vol_units="price",
            )
        )
    except Exception:
        return Signal(SignalKind.ATM_LEVEL, False, float("nan"), "atm_unavailable")
    if df is None or df.empty or "atm_iv" not in df.columns:
        return Signal(
            SignalKind.ATM_LEVEL, False, float(atm), "no_history; raw=" + f"{atm:.4f}"
        )
    series = df["atm_iv"].astype(float).dropna().tail(252)
    if len(series) < 20:
        return Signal(
            SignalKind.ATM_LEVEL, False, float(atm), "insufficient_history"
        )
    pct = float((series < atm).mean())
    triggered = pct <= config.atm_percentile_threshold_low or pct >= config.atm_percentile_threshold_high
    return Signal(
        kind=SignalKind.ATM_LEVEL,
        triggered=triggered,
        value=float(pct),
        detail=f"percentile={pct:.3f}; atm={atm:.4f}",
    )


# --- §2.7 Carry quality ------------------------------------------------------


def signal_carry_quality(
    *,
    carry: CarryRecord,
    config: ScreenerConfig,
) -> Signal:
    """Spec §2.7: positive 3m carry AND positive carry-to-expiry."""
    triggered = carry.carry_3m > 0.0 and carry.carry_to_expiry > 0.0
    return Signal(
        kind=SignalKind.CARRY_QUALITY,
        triggered=triggered,
        value=float(carry.carry_3m),
        detail=f"3m={carry.carry_3m:.3f}, to_expiry={carry.carry_to_expiry:.3f}",
    )


# --- §2.8 Asymmetry ratio ----------------------------------------------------


_ASYMMETRY_THRESHOLDS = {
    ArchetypeType.WING.value: 10.0,
    ArchetypeType.WIDE_VERTICAL.value: 4.0,
    ArchetypeType.RATIO.value: 3.0,
    ArchetypeType.LADDER.value: 2.5,
    ArchetypeType.TREE.value: 4.0,
    ArchetypeType.CONDOR.value: 3.0,
    ArchetypeType.RISK_REVERSAL.value: 0.0,
    ArchetypeType.CONDITIONAL_CURVE.value: 0.0,
}


def signal_asymmetry_ratio(
    *,
    candidate: CandidateDef,
    payoff_summary: PayoffSummary,
    config: ScreenerConfig,
) -> Signal:
    """Spec §2.8: max_payoff / max_loss."""
    if payoff_summary.max_loss_ticks >= 0:
        ratio = float("inf") if payoff_summary.max_payoff_ticks > 0 else 0.0
    else:
        ratio = payoff_summary.max_payoff_ticks / abs(payoff_summary.max_loss_ticks)
    threshold = config.min_payoff_multiple_per_archetype.get(
        candidate.archetype.value,
        _ASYMMETRY_THRESHOLDS.get(candidate.archetype.value, 0.0),
    )
    triggered = ratio >= threshold
    return Signal(
        kind=SignalKind.ASYMMETRY_RATIO,
        triggered=triggered,
        value=float(ratio) if math.isfinite(ratio) else 9999.0,
        detail=f"ratio={ratio:.2f}, threshold={threshold}",
    )


# --- §2.9 RND prob edge ------------------------------------------------------


def signal_rnd_prob_edge(
    *,
    candidate: CandidateDef,
    rnd: Optional[RNDRecord],
    payoff_summary: PayoffSummary,
    conditional_prob_full_payoff: float,
    config: ScreenerConfig,
) -> Signal:
    """Spec §2.9: conditional fair − rnd-implied probability of full payoff."""
    if rnd is None or rnd.density_pdf is None or len(rnd.density_pdf) < 2:
        return Signal(
            SignalKind.RND_PROB_EDGE, False, float("nan"), "no_rnd_density"
        )
    lo_price, hi_price = payoff_summary.payoff_zone_price
    if not (math.isfinite(lo_price) and math.isfinite(hi_price)):
        return Signal(
            SignalKind.RND_PROB_EDGE, False, float("nan"), "no_payoff_zone"
        )
    # Convert to rate space (price → rate flips the order)
    lo_rate = 100.0 - max(lo_price, hi_price)
    hi_rate = 100.0 - min(lo_price, hi_price)
    p_rnd = payoff_zone_probability(
        rnd, density="rnd", lower_rate=lo_rate, upper_rate=hi_rate
    )
    edge = float(conditional_prob_full_payoff) - float(p_rnd)
    triggered = abs(edge) >= config.prob_edge_threshold
    return Signal(
        kind=SignalKind.RND_PROB_EDGE,
        triggered=triggered,
        value=float(edge),
        detail=f"p_rnd={p_rnd:.3f}, p_cond={conditional_prob_full_payoff:.3f}, edge={edge:+.3f}",
    )


# --- §2.9b SABR-RND divergence ----------------------------------------------


def signal_sabr_rnd_divergence(
    *,
    rnd: Optional[RNDRecord],
    payoff_summary: PayoffSummary,
    config: ScreenerConfig,
) -> Signal:
    """Spec §2.9b: |Δ payoff-zone probability| ≥ 5pp."""
    if rnd is None or rnd.sabr_density_on_same_grid is None:
        return Signal(
            SignalKind.SABR_RND_DIVERGENCE,
            False,
            float("nan"),
            "no_sabr_density",
        )
    lo_price, hi_price = payoff_summary.payoff_zone_price
    if not (math.isfinite(lo_price) and math.isfinite(hi_price)):
        return Signal(
            SignalKind.SABR_RND_DIVERGENCE, False, float("nan"), "no_payoff_zone"
        )
    lo_rate = 100.0 - max(lo_price, hi_price)
    hi_rate = 100.0 - min(lo_price, hi_price)
    diff = sabr_rnd_payoff_zone_diff(rnd, lower_rate=lo_rate, upper_rate=hi_rate)
    triggered = (
        math.isfinite(diff)
        and abs(diff * 100.0) >= config.sabr_rnd_payoff_zone_diff_threshold_pp
    )
    return Signal(
        kind=SignalKind.SABR_RND_DIVERGENCE,
        triggered=triggered,
        value=float(diff if math.isfinite(diff) else 0.0),
        detail=f"diff_pp={diff*100.0:.2f}",
    )


# --- §2.10 SDR co-movement ---------------------------------------------------


def signal_sdr_comovement(
    *,
    candidate: CandidateDef,
    sdr_confirmation: bool,
    config: ScreenerConfig,
) -> Signal:
    """Spec §2.10: same-family package recently observed in SDR-or-CME-block tape."""
    return Signal(
        kind=SignalKind.SDR_COMOVEMENT,
        triggered=bool(sdr_confirmation),
        value=1.0 if sdr_confirmation else 0.0,
        detail="confirmed" if sdr_confirmation else "no_recent_match",
    )


# --- Compute all signals -----------------------------------------------------


def compute_all_signals(
    *,
    candidate: CandidateDef,
    md: STIRMarketData,
    rnd: Optional[RNDRecord],
    fomc_path: FOMCPath,
    payoff_summary: PayoffSummary,
    carry: CarryRecord,
    conditional_prob_full_payoff: float = 0.0,
    fair_path_bp: Sequence[float] = (),
    sdr_confirmation: bool = False,
    config: Optional[ScreenerConfig] = None,
) -> Tuple[Signal, ...]:
    if config is None:
        config = ScreenerConfig()

    signals: List[Signal] = []
    signals.append(signal_path_bias(fomc_path=fomc_path, fair_path_bp=fair_path_bp, config=config))
    signals.append(
        signal_rr25_zscore(
            candidate=candidate, iv_history=md.iv_history, config=config
        )
    )
    signals.append(signal_term_structure(candidate=candidate, md=md, config=config))
    signals.append(
        signal_oi_anchors(
            candidate=candidate, md=md, fomc_path=fomc_path, config=config
        )
    )
    signals.append(signal_wing_cheapness(candidate=candidate, md=md, config=config))
    signals.append(signal_atm_level(candidate=candidate, md=md, config=config))
    signals.append(signal_carry_quality(carry=carry, config=config))
    signals.append(
        signal_asymmetry_ratio(
            candidate=candidate, payoff_summary=payoff_summary, config=config
        )
    )
    signals.append(
        signal_rnd_prob_edge(
            candidate=candidate,
            rnd=rnd,
            payoff_summary=payoff_summary,
            conditional_prob_full_payoff=conditional_prob_full_payoff,
            config=config,
        )
    )
    signals.append(
        signal_sabr_rnd_divergence(
            rnd=rnd, payoff_summary=payoff_summary, config=config
        )
    )
    signals.append(
        signal_sdr_comovement(
            candidate=candidate, sdr_confirmation=sdr_confirmation, config=config
        )
    )
    return tuple(signals)
