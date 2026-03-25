"""Traffic light indicator for regime detection.

Monitors rolling regression beta stability to detect regime shifts.
Formula: indicator = sqrt(Z_body^2 + Z_curve^2)

Reference: J.P. Morgan "RV on the EUR swap yield curve" (Apr 2021), Exhibit 14.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


@dataclass
class RegimeFilterConfig:
    """Configuration for traffic light regime filter."""
    beta_vol_window_days: int = 65
    beta_vol_zscore_window_days: int = 130
    threshold: float = 3.0


def traffic_light(
    betas_body: pd.Series,
    betas_curve: pd.Series,
    config: RegimeFilterConfig,
) -> pd.DataFrame:
    """Compute the traffic light regime indicator.

    Returns DataFrame with columns ["indicator", "regime"].
    """
    vol_w = config.beta_vol_window_days
    zs_w = config.beta_vol_zscore_window_days
    min_vol = max(vol_w // 2, 10)
    min_zs = max(zs_w // 2, 20)

    vol_body = betas_body.rolling(window=vol_w, min_periods=min_vol).std()
    vol_curve = betas_curve.rolling(window=vol_w, min_periods=min_vol).std()

    def _zscore(s):
        m = s.rolling(window=zs_w, min_periods=min_zs).mean()
        sd = s.rolling(window=zs_w, min_periods=min_zs).std().replace(0.0, np.nan)
        return (s - m) / sd

    z_body = _zscore(vol_body)
    z_curve = _zscore(vol_curve)

    indicator = np.sqrt(z_body ** 2 + z_curve ** 2)
    regime = pd.Series("green", index=indicator.index)
    regime[indicator > config.threshold] = "red"
    regime[indicator.isna()] = np.nan

    return pd.DataFrame({"indicator": indicator, "regime": regime}, index=indicator.index)
