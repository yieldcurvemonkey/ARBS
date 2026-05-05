"""λ-grid optimization for SR3 RND smoothing parameter.

Picks the λ that minimizes a composite stability score:
    score = neg_density_pct + 0.5 × smoothing_sensitivity_pp + 5 × is_extrap_dominated

Used by the orchestrator before computing variance/skew/tail signals.
"""

from __future__ import annotations

import datetime
from typing import Dict, Optional, Tuple

from RVUtils.STIRAsymmetricScreener._rnd import (
    RNDRecord,
    extract_per_expiry_rnd,
)
from RVUtils.STIRAsymmetricScreener._types import ScreenerConfig as _AsymConfig


def _score_lambda(
    *,
    smile,
    leg_market,
    as_of: datetime.date,
    smoothing_param: float,
) -> Tuple[float, RNDRecord]:
    cfg_local = _AsymConfig()
    cfg_local.rnd_smoothing_param = smoothing_param
    rnd = extract_per_expiry_rnd(
        smile=smile, leg_market=leg_market, config=cfg_local, as_of=as_of
    )
    score = (
        rnd.negative_density_pct
        + 0.5 * rnd.smoothing_sensitivity_pp
        + (5.0 if rnd.extrapolation_dominated else 0.0)
    )
    return float(score), rnd


def optimize_smoothing_lambda(
    *,
    smile,
    as_of: datetime.date,
    grid: Tuple[float, ...] = (1e-5, 5e-5, 1e-4, 5e-4, 1e-3),
    leg_market: Optional[dict] = None,
) -> Tuple[float, RNDRecord, Dict[float, float]]:
    """Pick the λ that minimizes the composite stability score.

    Returns ``(best_lambda, best_rnd, scores_by_lambda)``.
    """
    if leg_market is None:
        leg_market = {}

    scores: Dict[float, float] = {}
    best_lambda: Optional[float] = None
    best_score = float("inf")
    best_rnd = None
    for lam in grid:
        try:
            score, rnd = _score_lambda(
                smile=smile, leg_market=leg_market,
                as_of=as_of, smoothing_param=lam,
            )
            scores[lam] = score
            if score < best_score:
                best_score = score
                best_lambda = lam
                best_rnd = rnd
        except Exception:
            scores[lam] = float("inf")
    if best_lambda is None or best_rnd is None:
        raise RuntimeError("All λ values failed in grid")
    return best_lambda, best_rnd, scores
