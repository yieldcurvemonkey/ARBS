"""Rolling OLS regression for relative value analysis (JPM approach).

Regresses a 50:50 butterfly against body yield and wing-to-wing curve
using a rolling window. The residual is the trade signal; the betas
are hedge ratios that strip out level and slope exposure.

Reference: J.P. Morgan "RV on the EUR swap yield curve" (Apr 2021).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Dict

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


@dataclass
class RegressionRVConfig:
    """Configuration for rolling regression RV analysis."""
    window_days: int = 130
    min_rsq: float = 0.60
    zscore_lookback_days: int = 130


@dataclass
class RegressionRVResult:
    """Output of rolling regression analysis."""
    residuals: pd.Series
    zscores: pd.Series
    intercepts: pd.Series
    fitted: pd.Series
    betas_body: pd.Series
    betas_curve: pd.Series
    rsq: pd.Series
    hedge_ratios: pd.DataFrame  # [dates x 2] columns: left_weight, right_weight


def rolling_regression(
    fly: pd.Series,
    body: pd.Series,
    curve: pd.Series,
    config: RegressionRVConfig,
) -> RegressionRVResult:
    """Run rolling OLS regression: fly = a + b_body * body + b_curve * curve + eps.

    Parameters
    ----------
    fly : Series
        50:50 butterfly spread series (e.g., 0.5*left + 0.5*right - belly).
    body : Series
        Body (belly) yield series.
    curve : Series
        Wing-to-wing curve series (e.g., right_wing - left_wing).
    config : RegressionRVConfig

    Returns
    -------
    RegressionRVResult with residuals, Z-scores, rolling betas, R-squared,
    and derived hedge ratios.
    """
    idx = fly.index
    n = len(idx)
    w = config.window_days

    residuals = pd.Series(np.nan, index=idx)
    intercepts = pd.Series(np.nan, index=idx)
    fitted = pd.Series(np.nan, index=idx)
    betas_body = pd.Series(np.nan, index=idx)
    betas_curve = pd.Series(np.nan, index=idx)
    rsq = pd.Series(np.nan, index=idx)

    fly_vals = fly.values
    body_vals = body.values
    curve_vals = curve.values

    for i in range(w, n):
        # Train on [i-w, i-1], predict on i (out-of-sample)
        y_train = fly_vals[i - w : i]
        X_train = np.column_stack([
            np.ones(w),
            body_vals[i - w : i],
            curve_vals[i - w : i],
        ])

        if np.any(np.isnan(y_train)) or np.any(np.isnan(X_train)):
            continue

        try:
            beta, res, rank, sv = np.linalg.lstsq(X_train, y_train, rcond=None)
        except np.linalg.LinAlgError:
            continue

        # Out-of-sample residual
        y_hat = beta[0] + beta[1] * body_vals[i] + beta[2] * curve_vals[i]
        intercepts.iloc[i] = beta[0]
        fitted.iloc[i] = y_hat
        residuals.iloc[i] = fly_vals[i] - y_hat
        betas_body.iloc[i] = beta[1]
        betas_curve.iloc[i] = beta[2]

        # R-squared (in-sample)
        y_hat_train = X_train @ beta
        ss_res = np.sum((y_train - y_hat_train) ** 2)
        ss_tot = np.sum((y_train - y_train.mean()) ** 2)
        rsq.iloc[i] = 1.0 - ss_res / ss_tot if ss_tot > 0 else 0.0

    # Z-score the residuals
    zs_window = config.zscore_lookback_days
    min_periods = min(zs_window, max(zs_window // 2, 20))
    roll_mean = residuals.rolling(window=zs_window, min_periods=min_periods).mean()
    roll_std = residuals.rolling(window=zs_window, min_periods=min_periods).std()
    roll_std = roll_std.replace(0.0, np.nan)
    zscores = (residuals - roll_mean) / roll_std

    # Derive hedge ratios from betas
    # For a fly: left_w * left + 1.0 * belly + right_w * right
    # OLS betas give the relationship between the 50:50 fly and body/curve
    # Hedge ratio transformation: left = 0.5 - beta_curve, right = 0.5 + beta_curve
    hedge_ratios = pd.DataFrame(
        {
            "left_weight": 0.5 - betas_curve,
            "right_weight": 0.5 + betas_curve,
        },
        index=idx,
    )

    return RegressionRVResult(
        residuals=residuals,
        zscores=zscores,
        intercepts=intercepts,
        fitted=fitted,
        betas_body=betas_body,
        betas_curve=betas_curve,
        rsq=rsq,
        hedge_ratios=hedge_ratios,
    )
