"""Regime classifier for SR3-vs-ZQ screener.

V1 thresholded classifier from the 18-date backfill quantiles:
    - residual_ratio > 50: stress flag
    - tail+50bp >= 0.20: stress flag
    - skew <= -1.0: pivot flag (directional move priced)
    - skew >= 0.20: calm baseline
    - residual_ratio in [10, 30] AND skew negative ≈ -0.5: hike

When multiple flags fire, priority: stress > pivot > hike > calm.
"""

from __future__ import annotations

import math
from typing import Optional

from RVUtils.SR3ZQDistributionScreener._types import (
    DistributionScreenerConfig,
    RegimeBucket,
)


def classify_regime(
    *,
    residual_ratio: float,
    skew: float,
    tail_upper_50bp: float,
    config: Optional[DistributionScreenerConfig] = None,
) -> RegimeBucket:
    if config is None:
        config = DistributionScreenerConfig()

    if not math.isfinite(residual_ratio):
        residual_ratio = 0.0
    if not math.isfinite(skew):
        skew = 0.0
    if not math.isfinite(tail_upper_50bp):
        tail_upper_50bp = 0.0

    # Priority 1: stress (residual_ratio extreme OR tail mass extreme)
    if (
        residual_ratio >= config.regime_residual_ratio_stress_p25
        or tail_upper_50bp >= config.regime_tail_upper_50bp_stress_p25
    ):
        return RegimeBucket.STRESS

    # Priority 2: pivot (heavy negative skew, market priced directional move)
    if skew <= config.regime_skew_pivot_p75:
        return RegimeBucket.PIVOT

    # Priority 3: hike (negative skew but moderate, hike-cycle signature)
    # Hike has skew ≈ -0.45, residual_ratio ≈ 11. Calm has skew ≈ +0.35.
    if skew < 0 and skew > config.regime_skew_pivot_p75 and 5.0 <= residual_ratio <= 30.0:
        return RegimeBucket.HIKE

    return RegimeBucket.CALM
