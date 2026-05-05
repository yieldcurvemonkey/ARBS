"""Composite asymmetry score for the STIR Options Asymmetric Screener (spec §4)."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Mapping


@dataclass(frozen=True)
class ScoreBreakdown:
    payoff_multiple_score: float
    probability_edge_score: float
    carry_quality_score: float
    liquidity_score: float
    composite: float


def _safe_norm(value: float, scale: float, *, sign: int = 1) -> float:
    """Map a value to [0, 1] via a soft saturating function.

    sign=1 means higher value ⇒ higher score; sign=-1 inverts.
    """
    if not math.isfinite(value):
        return 0.0
    if scale <= 0:
        return 0.0
    x = value * sign
    if x <= 0:
        return 0.0
    return float(min(1.0, x / scale))


def composite_asymmetry_score(
    *,
    payoff_multiple: float,
    probability_edge: float,
    carry_quality: float,
    liquidity: float,
    weights: Mapping[str, float],
) -> ScoreBreakdown:
    """Combine four sub-component scores per spec §4.

    Inputs are pre-normalized to [0, 1] (use the helpers below to map raw
    numbers into that range). Weights default to spec §4 (.30/.30/.20/.20).
    """
    # Normalize weights to sum to 1
    total_w = sum(weights.values()) or 1.0
    w = {k: v / total_w for k, v in weights.items()}

    composite = (
        w.get("payoff_multiple", 0.30) * payoff_multiple
        + w.get("probability_edge", 0.30) * probability_edge
        + w.get("carry_quality", 0.20) * carry_quality
        + w.get("liquidity", 0.20) * liquidity
    )
    return ScoreBreakdown(
        payoff_multiple_score=float(payoff_multiple),
        probability_edge_score=float(probability_edge),
        carry_quality_score=float(carry_quality),
        liquidity_score=float(liquidity),
        composite=float(composite),
    )


# --- Normalizers --------------------------------------------------------------


def normalize_payoff_multiple(asymmetry_ratio: float) -> float:
    """Map asymmetry ratio (0..30+) to [0, 1] with soft saturation at 10."""
    return _safe_norm(asymmetry_ratio, 10.0)


def normalize_probability_edge(prob_edge: float) -> float:
    """Map probability edge (-1..+1) to [0, 1]; positive edge = better."""
    if not math.isfinite(prob_edge):
        return 0.0
    if prob_edge <= 0:
        return 0.0
    return float(min(1.0, prob_edge / 0.30))


def normalize_carry_quality(carry_3m: float, premium_ticks: float) -> float:
    """Map 3m-carry to [0, 1]; positive carry = better."""
    if not math.isfinite(carry_3m) or premium_ticks == 0 or not math.isfinite(premium_ticks):
        return 0.5  # neutral when premium unavailable
    if abs(premium_ticks) < 1e-6:
        return 0.5
    ratio = carry_3m / abs(premium_ticks)
    if ratio <= 0:
        return 0.0
    return float(min(1.0, ratio / 0.10))


def normalize_liquidity(open_interest_total: float, bid_ask_pct: float) -> float:
    """Map OI + bid-ask into [0, 1]."""
    if not math.isfinite(open_interest_total) or open_interest_total <= 0:
        return 0.0
    oi_score = min(1.0, open_interest_total / 5000.0)
    if math.isfinite(bid_ask_pct) and bid_ask_pct > 0:
        ba_score = max(0.0, min(1.0, 1.0 - bid_ask_pct / 0.25))
    else:
        ba_score = 0.5
    return float(0.5 * oi_score + 0.5 * ba_score)
