"""Traffic light indicator for regime detection.

Monitors rolling regression beta stability to detect regime shifts that
invalidate mean-reversion assumptions. When betas are volatile, residuals
that appear to be dislocations are actually structural shifts.

Formula: indicator = sqrt(Z_body^2 + Z_curve^2)
Where Z_x = (rolling_std(beta_x, 3M) - mean) / std over 6M lookback.

Reference: J.P. Morgan "RV on the EUR swap yield curve" (Apr 2021),
Exhibit 14 — "traffic light indicator".
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
    beta_vol_window_days: int = 65      # 3M rolling std of betas
    beta_vol_zscore_window_days: int = 130  # 6M Z-score of beta vol
    threshold: float = 3.0              # indicator > threshold → "red"


def traffic_light(
    betas_body: pd.Series,
    betas_curve: pd.Series,
    config: RegimeFilterConfig,
) -> pd.DataFrame:
    """Compute the traffic light regime indicator.

    Parameters
    ----------
    betas_body : Series
        Rolling regression beta of fly vs body yield.
    betas_curve : Series
        Rolling regression beta of fly vs wing curve.
    config : RegimeFilterConfig

    Returns
    -------
    DataFrame with columns ["indicator", "regime"].
    indicator: float (the sqrt(Z^2 + Z^2) metric).
    regime: "green" if below threshold, "red" if above.
    """
    vol_w = config.beta_vol_window_days
    zs_w = config.beta_vol_zscore_window_days
    min_periods_vol = max(vol_w // 2, 10)
    min_periods_zs = max(zs_w // 2, 20)

    # Step 1: 3M rolling std of each beta
    vol_body = betas_body.rolling(window=vol_w, min_periods=min_periods_vol).std()
    vol_curve = betas_curve.rolling(window=vol_w, min_periods=min_periods_vol).std()

    # Step 2: 6M Z-score of each beta volatility
    def _zscore(s: pd.Series) -> pd.Series:
        m = s.rolling(window=zs_w, min_periods=min_periods_zs).mean()
        sd = s.rolling(window=zs_w, min_periods=min_periods_zs).std()
        sd = sd.replace(0.0, np.nan)
        return (s - m) / sd

    z_body = _zscore(vol_body)
    z_curve = _zscore(vol_curve)

    # Step 3: Combine
    indicator = np.sqrt(z_body ** 2 + z_curve ** 2)
    regime = pd.Series("green", index=indicator.index)
    regime[indicator > config.threshold] = "red"
    regime[indicator.isna()] = np.nan

    return pd.DataFrame({"indicator": indicator, "regime": regime}, index=indicator.index)
