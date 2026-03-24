"""Rolling PCA engine for relative value analysis on swap curves.

Implements out-of-sample rolling PCA: on date T, the estimation window is
[T - window, T-1], and T's residual is computed by projecting T's actual
rates onto the fitted principal components. Never includes T in estimation.

Supports:
- PCA on levels or daily changes
- Covariance or correlation matrix
- Full-curve or trade-tenors-only scope
- PC3-based butterfly weights (normalized to belly)
- Ornstein-Uhlenbeck half-life estimation
- Augmented Dickey-Fuller stationarity tests
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd
from sklearn.decomposition import PCA

logger = logging.getLogger(__name__)


@dataclass
class PCARVConfig:
    """Configuration for rolling PCA engine."""
    pca_window_days: int = 130
    pca_input: str = "levels"           # "levels" or "changes"
    n_components: int = 3
    pca_scope: str = "full_curve"       # "full_curve" or "trade_tenors_only"
    use_correlation: bool = False       # False=covariance, True=correlation
    zscore_lookback_days: int = 130


@dataclass
class PCARVResult:
    """Output of rolling PCA analysis."""
    residuals: pd.DataFrame             # [dates x tenors] out-of-sample residuals
    zscores: pd.DataFrame               # [dates x tenors] Z-scored residuals
    loadings: Dict[pd.Timestamp, np.ndarray]  # date -> (n_tenors x n_components)
    variance_explained: pd.DataFrame    # [dates x n_components]
    reconstructed: pd.DataFrame         # [dates x tenors] 3-PC reconstructed values


def rolling_pca(rates: pd.DataFrame, config: PCARVConfig) -> PCARVResult:
    """Run rolling PCA on swap rate data.

    Parameters
    ----------
    rates : DataFrame
        [dates x tenors] matrix of swap rates. Index must be a DatetimeIndex
        or similar. Columns are tenor labels.
    config : PCARVConfig
        PCA configuration parameters.

    Returns
    -------
    PCARVResult with residuals, Z-scores, loadings, variance_explained,
    and reconstructed values. First `pca_window_days` rows are NaN (warm-up).
    """
    if config.pca_input == "changes":
        data = rates.diff().iloc[1:]
    else:
        data = rates.copy()

    n_dates = len(data)
    n_tenors = data.shape[1]
    window = config.pca_window_days
    n_comp = min(config.n_components, n_tenors)

    residuals = pd.DataFrame(np.nan, index=data.index, columns=data.columns)
    reconstructed = pd.DataFrame(np.nan, index=data.index, columns=data.columns)
    zscores = pd.DataFrame(np.nan, index=data.index, columns=data.columns)
    ve_cols = [f"PC{i+1}" for i in range(n_comp)]
    variance_explained = pd.DataFrame(np.nan, index=data.index, columns=ve_cols)
    loadings_dict: Dict[pd.Timestamp, np.ndarray] = {}

    for i in range(window, n_dates):
        # Estimation window: [i-window, i-1] — strictly out-of-sample
        train = data.iloc[i - window : i].values
        today = data.iloc[i].values

        if np.any(np.isnan(train)) or np.any(np.isnan(today)):
            continue

        if config.use_correlation:
            std = train.std(axis=0, ddof=1)
            std[std == 0] = 1.0
            mean = train.mean(axis=0)
            train_normed = (train - mean) / std
            today_normed = (today - mean) / std
        else:
            mean = train.mean(axis=0)
            train_normed = train - mean
            today_normed = today - mean

        pca = PCA(n_components=n_comp)
        pca.fit(train_normed)

        # Reconstruct today using the fitted PCA
        scores_today = pca.transform(today_normed.reshape(1, -1))
        recon_normed = pca.inverse_transform(scores_today).flatten()

        if config.use_correlation:
            recon = recon_normed * std + mean
        else:
            recon = recon_normed + mean

        dt = data.index[i]
        if config.pca_input == "changes":
            # For changes mode, residual is the unexplained change
            actual_rate = rates.iloc[rates.index.get_loc(dt)].values
            # Reconstruct: mean of changes + PC-explained portion
            residuals.loc[dt] = today - recon_normed.flatten() - mean
            reconstructed.loc[dt] = actual_rate - residuals.loc[dt].values
        else:
            residuals.loc[dt] = rates.loc[dt].values - recon
            reconstructed.loc[dt] = recon

        variance_explained.loc[dt] = pca.explained_variance_ratio_[:n_comp]
        loadings_dict[dt] = pca.components_.T  # (n_tenors x n_comp)

    # Z-score the residuals using rolling lookback
    zs_window = config.zscore_lookback_days
    for col in residuals.columns:
        r = residuals[col]
        roll_mean = r.rolling(window=zs_window, min_periods=max(zs_window // 2, 20)).mean()
        roll_std = r.rolling(window=zs_window, min_periods=max(zs_window // 2, 20)).std()
        roll_std = roll_std.replace(0.0, np.nan)
        zscores[col] = (r - roll_mean) / roll_std

    return PCARVResult(
        residuals=residuals,
        zscores=zscores,
        loadings=loadings_dict,
        variance_explained=variance_explained,
        reconstructed=reconstructed,
    )


def pca_fly_weights(
    rates_3tenor: pd.DataFrame,
    config: PCARVConfig,
) -> pd.DataFrame:
    """Compute PCA-based butterfly weights from PC3 loadings.

    Runs rolling PCA on exactly 3 tenors (left wing, belly, right wing).
    Takes the PC3 loadings and normalizes so the belly weight = 1.0.
    The wing weights are the hedge ratios per unit of belly DV01.

    Parameters
    ----------
    rates_3tenor : DataFrame
        [dates x 3] rates for [left_wing, belly, right_wing].
    config : PCARVConfig

    Returns
    -------
    DataFrame [dates x 3] with columns matching input, values are normalized
    PC3 loadings. Belly column is always +1.0 or -1.0. NaN during warm-up.
    """
    assert rates_3tenor.shape[1] == 3, "Expecting exactly 3 tenors for fly weights"

    result = rolling_pca(rates_3tenor, config)
    weights = pd.DataFrame(np.nan, index=rates_3tenor.index, columns=rates_3tenor.columns)

    for dt, ldg in result.loadings.items():
        # ldg shape: (3, n_components) — take the 3rd component (index 2)
        if ldg.shape[1] < 3:
            continue
        pc3 = ldg[:, 2]  # 3 loadings for PC3
        belly_loading = pc3[1]
        if abs(belly_loading) < 1e-12:
            continue
        normalized = pc3 / belly_loading
        # Convention: belly weight positive (=1.0), wings may be negative
        if normalized[1] < 0:
            normalized = -normalized
        weights.loc[dt] = normalized

    return weights


def ou_half_life(series: pd.Series) -> float:
    """Estimate Ornstein-Uhlenbeck half-life via AR(1) regression.

    Fits: x(t) - x(t-1) = a + b * x(t-1) + eps
    Half-life = -ln(2) / ln(1 + b)

    Returns half-life in the same units as the series frequency (business days).
    """
    x = series.dropna().values
    if len(x) < 10:
        return np.nan
    dx = np.diff(x)
    x_lag = x[:-1]
    # OLS: dx = a + b * x_lag
    X = np.column_stack([np.ones(len(x_lag)), x_lag])
    try:
        beta = np.linalg.lstsq(X, dx, rcond=None)[0]
    except np.linalg.LinAlgError:
        return np.nan
    b = beta[1]
    if b >= 0:
        return np.inf  # not mean-reverting
    return -np.log(2) / np.log(1 + b)


def adf_test(series: pd.Series) -> Dict[str, float]:
    """Run augmented Dickey-Fuller test on a series.

    Returns dict with keys: statistic, pvalue, half_life.
    """
    from statsmodels.tsa.stattools import adfuller

    clean = series.dropna()
    if len(clean) < 20:
        return {"statistic": np.nan, "pvalue": np.nan, "half_life": np.nan}
    result = adfuller(clean.values, autolag="AIC")
    return {
        "statistic": float(result[0]),
        "pvalue": float(result[1]),
        "half_life": ou_half_life(clean),
    }
