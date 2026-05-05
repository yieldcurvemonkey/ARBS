"""Regime classifier for SR3-vs-ZQ screener.

V1 thresholded classifier calibrated from 18-date backfill quantiles
(scripts/_sr3_zq_extended_backfill.py output, 2026-05-05):

    Regime quantiles (residual_ratio / skew / tail+50bp p50):
        calm    (n=3): 27.3 / +0.22 / 0.073
        stress  (n=3): 96.8 / -0.76 / 0.353
        pivot   (n=4): 12.3 / -1.69 / 0.042
        hike    (n=7): 30.7 / -0.81 / 0.118  (range 17-747 on ratio)

Classification rules (priority order):
    1. residual_ratio >= 60 OR tail+50bp >= 0.20  ⇒  STRESS
       (stress p25 = 84 / 0.20; buffer below to catch high-vol hikes
        like Jul22 ratio=130, May23 ratio=109. Trade-flag-equivalent.)
    2. skew <= -1.0                                ⇒  PIVOT
       (pivot p75 = -1.37; hike p75 = -0.24 well above -1.0)
    3. skew in (-1.0, -0.2) AND ratio in [10, 60]  ⇒  HIKE
       (catches moderate hike-cycle dates like Dec22, Nov22, Jun22)
    4. otherwise                                    ⇒  CALM
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

    # Priority 1: stress (residual_ratio extreme OR tail mass extreme).
    # Note: peak-hike-cycle dates (Jul22 ratio=130, May23 ratio=109) also
    # land here. That's correct — those dates are vol-stress-equivalent
    # and the trade flags fire identically.
    if (
        residual_ratio >= config.regime_residual_ratio_stress_p25
        or tail_upper_50bp >= config.regime_tail_upper_50bp_stress_p25
    ):
        return RegimeBucket.STRESS

    # Priority 2: pivot (heavy negative skew, market priced directional move)
    if skew <= config.regime_skew_pivot_p75:
        return RegimeBucket.PIVOT

    # Priority 3: hike (moderate negative skew + moderate residual ratio).
    # Hike p25-p75 skew = (-1.03, -0.24); residual_ratio p25-p75 = (17, 121).
    # Window picks moderate-vol hikes (Dec22, Nov22, Jun22); high-vol hikes
    # collapse into stress (priority 1) which is fine for trading flags.
    if -1.0 < skew < -0.2 and 10.0 <= residual_ratio <= 60.0:
        return RegimeBucket.HIKE

    return RegimeBucket.CALM
