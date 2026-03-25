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

Extends patterns from RVUtils/df_based_pca_risk_model.py (CurvePCAModel,
eigh decomposition) with rolling window capability.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Dict

import numpy as np
import pandas as pd

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
    eigenvalues: Dict[pd.Timestamp, np.ndarray]  # date -> (n_components,) eigenvalues
    variance_explained: pd.DataFrame    # [dates x n_components]
    reconstructed: pd.DataFrame         # [dates x tenors] 3-PC reconstructed values
    scores: Dict[pd.Timestamp, np.ndarray]  # date -> (n_components,) PC scores for date T


def rolling_pca(rates: pd.DataFrame, config: PCARVConfig) -> PCARVResult:
    """Run rolling PCA on swap rate data.

    Parameters
    ----------
    rates : DataFrame
        [dates x tenors] matrix of swap rates. Index must be DatetimeIndex.
    config : PCARVConfig

    Returns
    -------
    PCARVResult with residuals, Z-scores, loadings, eigenvalues,
    variance_explained, reconstructed, and scores. First `pca_window_days`
    rows are NaN (warm-up).
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
    eigenvalues_dict: Dict[pd.Timestamp, np.ndarray] = {}
    scores_dict: Dict[pd.Timestamp, np.ndarray] = {}

    for i in range(window, n_dates):
        # Estimation window: [i-window, i-1] — strictly out-of-sample
        train = data.iloc[i - window : i].values
        today = data.iloc[i].values

        if np.any(np.isnan(train)) or np.any(np.isnan(today)):
            continue

        # Demean
        mean = train.mean(axis=0)
        train_centered = train - mean
        today_centered = today - mean

        if config.use_correlation:
            std = train.std(axis=0, ddof=1)
            std[std == 0] = 1.0
            train_centered = train_centered / std
            today_centered = today_centered / std

        # Covariance matrix and eigen-decomposition (symmetric -> eigh)
        cov = (train_centered.T @ train_centered) / (window - 1)
        evals_all, evecs_all = np.linalg.eigh(cov)

        # Sort descending
        idx_sort = np.argsort(evals_all)[::-1]
        evals_all = evals_all[idx_sort]
        evecs_all = evecs_all[:, idx_sort]

        # Retain n_comp
        evals = evals_all[:n_comp]
        evecs = evecs_all[:, :n_comp]  # (n_tenors x n_comp)

        # Project today onto PCs
        scores_today = today_centered @ evecs  # (n_comp,)
        recon_centered = scores_today @ evecs.T  # (n_tenors,)

        if config.use_correlation:
            recon = recon_centered * std + mean
        else:
            recon = recon_centered + mean

        dt = data.index[i]

        if config.pca_input == "changes":
            # For changes mode: residual is unexplained change
            residuals.loc[dt] = today_centered - recon_centered
            actual_rate = rates.loc[dt].values if dt in rates.index else today + mean
            reconstructed.loc[dt] = actual_rate - residuals.loc[dt].values
        else:
            residuals.loc[dt] = rates.loc[dt].values - recon
            reconstructed.loc[dt] = recon

        total_var = evals_all.sum()
        variance_explained.loc[dt] = evals / total_var if total_var > 0 else np.zeros(n_comp)
        loadings_dict[dt] = evecs.copy()  # (n_tenors x n_comp)
        eigenvalues_dict[dt] = evals.copy()  # (n_comp,)
        scores_dict[dt] = scores_today.copy()  # (n_comp,)

    # Z-score the residuals using rolling lookback
    zs_window = config.zscore_lookback_days
    min_periods = max(zs_window // 2, 20)
    for col in residuals.columns:
        r = residuals[col]
        roll_mean = r.rolling(window=zs_window, min_periods=min_periods).mean()
        roll_std = r.rolling(window=zs_window, min_periods=min_periods).std()
        roll_std = roll_std.replace(0.0, np.nan)
        zscores[col] = (r - roll_mean) / roll_std

    return PCARVResult(
        residuals=residuals,
        zscores=zscores,
        loadings=loadings_dict,
        eigenvalues=eigenvalues_dict,
        variance_explained=variance_explained,
        reconstructed=reconstructed,
        scores=scores_dict,
    )


def pca_fly_weights(
    rates_3tenor: pd.DataFrame,
    config: PCARVConfig,
) -> pd.DataFrame:
    """Compute PCA-based butterfly weights from PC3 loadings.

    Runs rolling PCA on exactly 3 tenors (left wing, belly, right wing).
    Takes the PC3 loadings and normalizes so the belly weight = 1.0.
    The wing weights are the hedge ratios per unit of belly DV01.

    From Standard Chartered (Lee, Davies, Fernandez 2013):
        weight(left_wing) = eig(1,3) / eig(2,3)
        weight(right_wing) = eig(3,3) / eig(2,3)

    From ASM Quant Macro (bquanttrading 2015):
        Take PC3 loadings [L_left, L_belly, L_right], normalize to belly.

    Parameters
    ----------
    rates_3tenor : DataFrame [dates x 3] for [left_wing, belly, right_wing].
    config : PCARVConfig

    Returns
    -------
    DataFrame [dates x 3] with belly column = +/-1.0. NaN during warm-up.
    """
    assert rates_3tenor.shape[1] == 3, "Expecting exactly 3 tenors for fly weights"

    result = rolling_pca(rates_3tenor, config)
    weights = pd.DataFrame(np.nan, index=rates_3tenor.index, columns=rates_3tenor.columns)

    for dt, ldg in result.loadings.items():
        if ldg.shape[1] < 3:
            continue
        pc3 = ldg[:, 2]  # 3 loadings for PC3
        belly_loading = pc3[1]
        if abs(belly_loading) < 1e-12:
            continue
        normalized = pc3 / belly_loading
        # Convention: belly weight positive (=1.0)
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
    X = np.column_stack([np.ones(len(x_lag)), x_lag])
    try:
        beta = np.linalg.lstsq(X, dx, rcond=None)[0]
    except np.linalg.LinAlgError:
        return np.nan
    b = beta[1]
    if b >= 0:
        return np.inf  # not mean-reverting
    return -np.log(2) / np.log(1 + b)


def ou_params(series: pd.Series) -> Dict[str, float]:
    """Fit full Ornstein-Uhlenbeck process parameters.

    dX = mu * (theta - X) * dt + sigma * dW

    Returns dict with keys: mu (mean-reversion speed), theta (long-run mean),
    sigma (volatility), half_life, investment_horizon_875 (87.5% life = 3 half-lives).
    """
    x = series.dropna().values
    if len(x) < 20:
        return {k: np.nan for k in ["mu", "theta", "sigma", "half_life", "investment_horizon_875"]}

    dx = np.diff(x)
    x_lag = x[:-1]
    X = np.column_stack([np.ones(len(x_lag)), x_lag])
    try:
        beta = np.linalg.lstsq(X, dx, rcond=None)[0]
    except np.linalg.LinAlgError:
        return {k: np.nan for k in ["mu", "theta", "sigma", "half_life", "investment_horizon_875"]}

    a, b = beta[0], beta[1]
    if b >= 0:
        return {"mu": 0.0, "theta": np.nan, "sigma": np.nan,
                "half_life": np.inf, "investment_horizon_875": np.inf}

    mu = -b  # mean-reversion speed (per period)
    theta = -a / b  # long-run mean
    residuals = dx - X @ beta
    sigma = residuals.std()
    half_life = np.log(2) / mu
    # 87.5% life = ln(8) / mu (Standard Chartered convention: 3 half-lives)
    investment_horizon = np.log(8) / mu

    return {
        "mu": float(mu),
        "theta": float(theta),
        "sigma": float(sigma),
        "half_life": float(half_life),
        "investment_horizon_875": float(investment_horizon),
    }


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
