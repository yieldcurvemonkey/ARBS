"""Rolling OLS regression for relative value analysis (JPM approach).

Regresses a 50:50 butterfly against body yield and wing-to-wing curve
using a rolling window. The residual is the trade signal; the betas
are hedge ratios that strip out level and slope exposure.

Reference: J.P. Morgan "RV on the EUR swap yield curve" (Apr 2021).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

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


# ---------------------------------------------------------------------------
# Entry snapshot & frozen residuals for OOS tracking
# ---------------------------------------------------------------------------


@dataclass
class EntrySnapshot:
    """Frozen regression parameters at trade entry for OOS residual computation."""
    intercept: float
    beta_body: float
    beta_curve: float
    residual_mean: float
    residual_std: float


def frozen_residual(
    snapshot: EntrySnapshot,
    fly_t: float,
    body_t: float,
    curve_t: float,
) -> float:
    """Compute out-of-sample residual using frozen entry betas.

    e_oos(t) = fly(t) - a_entry - b_body_entry * body(t) - b_curve_entry * curve(t)
    """
    return fly_t - snapshot.intercept - snapshot.beta_body * body_t - snapshot.beta_curve * curve_t


def compute_residual_stats(
    residuals: pd.Series,
    window: int,
) -> pd.DataFrame:
    """Compute rolling mean and std of residuals."""
    min_periods = min(window, max(window // 2, 20))
    roll_mean = residuals.rolling(window=window, min_periods=min_periods).mean()
    roll_std = residuals.rolling(window=window, min_periods=min_periods).std()
    return pd.DataFrame({"mean": roll_mean, "std": roll_std}, index=residuals.index)


def build_entry_snapshots(
    result: RegressionRVResult,
    stats: pd.DataFrame,
) -> Dict[pd.Timestamp, EntrySnapshot]:
    """Build dict of date -> EntrySnapshot from rolling regression output."""
    snapshots = {}
    for dt in result.residuals.dropna().index:
        intercept = result.intercepts.loc[dt]
        beta_body = result.betas_body.loc[dt]
        beta_curve = result.betas_curve.loc[dt]
        if pd.isna(intercept) or pd.isna(beta_body) or pd.isna(beta_curve):
            continue
        res_mean = stats.loc[dt, "mean"] if dt in stats.index and pd.notna(stats.loc[dt, "mean"]) else 0.0
        res_std = stats.loc[dt, "std"] if dt in stats.index and pd.notna(stats.loc[dt, "std"]) else np.nan
        snapshots[dt] = EntrySnapshot(
            intercept=float(intercept),
            beta_body=float(beta_body),
            beta_curve=float(beta_curve),
            residual_mean=float(res_mean),
            residual_std=float(res_std) if np.isfinite(res_std) else np.nan,
        )
    return snapshots


# ---------------------------------------------------------------------------
# JPM Fly Universe
# ---------------------------------------------------------------------------


@dataclass
class JPMFlyUniverse:
    """Configurable butterfly universe for JPM RV backtest."""
    standard_flies: List[Tuple[str, str, str]]
    forward_starts: List[Optional[str]]  # None = spot
    gap_5y_flies: List[Tuple[str, str, str]]  # Category 2
    gap_mm_flies: List[Tuple[str, str, str]]  # Category 3

    def _fly_id(self, category: str, fwd: Optional[str], left: str, belly: str, right: str) -> str:
        fwd_str = "spot" if fwd is None else fwd.replace("x", "").lower()
        return f"jpm_rv_{category}_{fwd_str}_{left}_{belly}_{right}"

    def all_fly_ids(self) -> Dict[str, str]:
        """Return dict of fly_id -> category for all flies in the universe."""
        result = {}
        for fwd in self.forward_starts:
            cat_name = "standard_spot" if fwd is None else f"standard_{fwd.lower()}_fwd"
            for left, belly, right in self.standard_flies:
                fid = self._fly_id(cat_name, fwd, left, belly, right)
                result[fid] = cat_name
        for left, belly, right in self.gap_5y_flies:
            fid = self._fly_id("gap_5y", None, left, belly, right)
            result[fid] = "gap_5y"
        for left, belly, right in self.gap_mm_flies:
            fid = self._fly_id("gap_mm", None, left, belly, right)
            result[fid] = "gap_mm"
        return result

    def iter_flies(self):
        """Yield (fly_id, category, fwd_start, left, belly, right) for each fly."""
        for fwd in self.forward_starts:
            cat_name = "standard_spot" if fwd is None else f"standard_{fwd.lower()}_fwd"
            for left, belly, right in self.standard_flies:
                fid = self._fly_id(cat_name, fwd, left, belly, right)
                yield fid, cat_name, fwd, left, belly, right
        for left, belly, right in self.gap_5y_flies:
            fid = self._fly_id("gap_5y", None, left, belly, right)
            yield fid, "gap_5y", None, left, belly, right
        for left, belly, right in self.gap_mm_flies:
            fid = self._fly_id("gap_mm", None, left, belly, right)
            yield fid, "gap_mm", None, left, belly, right


def default_fly_universe() -> JPMFlyUniverse:
    """Default USD SOFR fly universe adapted from JPM EUR paper."""
    return JPMFlyUniverse(
        standard_flies=[
            ("2Y", "3Y", "5Y"), ("2Y", "5Y", "7Y"), ("2Y", "5Y", "10Y"),
            ("2Y", "7Y", "12Y"), ("2Y", "10Y", "30Y"), ("3Y", "5Y", "10Y"),
            ("3Y", "7Y", "15Y"), ("5Y", "7Y", "10Y"), ("5Y", "10Y", "15Y"),
            ("5Y", "10Y", "30Y"), ("7Y", "10Y", "15Y"), ("10Y", "15Y", "20Y"),
            ("10Y", "20Y", "30Y"),
        ],
        forward_starts=[None, "1Y", "2Y", "5Y"],
        gap_5y_flies=[
            ("5Yx5Y", "10Yx5Y", "15Yx5Y"),
            ("10Yx5Y", "15Yx5Y", "20Yx5Y"),
            ("15Yx5Y", "20Yx5Y", "25Yx5Y"),
            ("20Yx5Y", "25Yx5Y", "30Yx5Y"),
        ],
        gap_mm_flies=[
            ("1Yx1Y", "2Yx1Y", "3Yx1Y"),
            ("1Yx1Y", "3Yx1Y", "5Yx1Y"),
            ("2Yx2Y", "4Yx2Y", "6Yx2Y"),
            ("2Yx2Y", "6Yx2Y", "10Yx2Y"),
        ],
    )


# ---------------------------------------------------------------------------
# Signal table builder
# ---------------------------------------------------------------------------


@dataclass
class RegressionSignalTable:
    """Pre-computed regression signals for all flies."""
    residuals: Dict[str, pd.Series]
    zscores: Dict[str, pd.Series]
    rsq: Dict[str, pd.Series]
    betas_body: Dict[str, pd.Series]
    betas_curve: Dict[str, pd.Series]
    intercepts: Dict[str, pd.Series]
    fly_series: Dict[str, pd.Series]
    body_series: Dict[str, pd.Series]
    curve_series: Dict[str, pd.Series]
    fly_categories: Dict[str, str]
    residual_stats: Dict[str, pd.DataFrame]
    entry_snapshots: Dict[str, Dict[pd.Timestamp, EntrySnapshot]]


def _make_tenor_key(fwd: Optional[str], tenor: str) -> str:
    """Build rate panel lookup key for a tenor with optional forward start."""
    if fwd is None:
        return tenor
    return f"{fwd}x{tenor}"


def build_jpm_signal_table(
    rate_panels: Dict[str, pd.Series],
    universe: JPMFlyUniverse,
    config: RegressionRVConfig,
) -> RegressionSignalTable:
    """Build signal table for all flies from rate panels.

    Parameters
    ----------
    rate_panels : dict of tenor_key -> pd.Series
        Rate time series keyed by tenor string (e.g., "5Y", "1Yx5Y").
    universe : JPMFlyUniverse
    config : RegressionRVConfig

    Returns
    -------
    RegressionSignalTable
    """
    residuals = {}
    zscores = {}
    rsq_dict = {}
    betas_body_dict = {}
    betas_curve_dict = {}
    intercepts_dict = {}
    fly_dict = {}
    body_dict = {}
    curve_dict = {}
    stats_dict = {}
    snapshots_dict = {}
    categories = {}

    for fid, cat, fwd, left, belly, right in universe.iter_flies():
        left_key = _make_tenor_key(fwd, left) if "x" not in left else left
        belly_key = _make_tenor_key(fwd, belly) if "x" not in belly else belly
        right_key = _make_tenor_key(fwd, right) if "x" not in right else right

        if left_key not in rate_panels or belly_key not in rate_panels or right_key not in rate_panels:
            logger.debug("Skipping %s: missing rate data for %s/%s/%s", fid, left_key, belly_key, right_key)
            continue

        left_rates = rate_panels[left_key]
        belly_rates = rate_panels[belly_key]
        right_rates = rate_panels[right_key]

        # Align indices
        common_idx = left_rates.index.intersection(belly_rates.index).intersection(right_rates.index)
        if len(common_idx) < config.window_days + 50:
            logger.debug("Skipping %s: insufficient data (%d days)", fid, len(common_idx))
            continue

        lr = left_rates.loc[common_idx]
        br = belly_rates.loc[common_idx]
        rr = right_rates.loc[common_idx]

        # 50:50 fly, body yield, wing curve
        fly = 0.5 * lr + 0.5 * rr - br
        body = br
        curve = rr - lr

        result = rolling_regression(fly, body, curve, config)

        stats = compute_residual_stats(result.residuals, config.zscore_lookback_days)
        snaps = build_entry_snapshots(result, stats)

        residuals[fid] = result.residuals
        zscores[fid] = result.zscores
        rsq_dict[fid] = result.rsq
        betas_body_dict[fid] = result.betas_body
        betas_curve_dict[fid] = result.betas_curve
        intercepts_dict[fid] = result.intercepts
        fly_dict[fid] = fly
        body_dict[fid] = body
        curve_dict[fid] = curve
        stats_dict[fid] = stats
        snapshots_dict[fid] = snaps
        categories[fid] = cat

    return RegressionSignalTable(
        residuals=residuals,
        zscores=zscores,
        rsq=rsq_dict,
        betas_body=betas_body_dict,
        betas_curve=betas_curve_dict,
        intercepts=intercepts_dict,
        fly_series=fly_dict,
        body_series=body_dict,
        curve_series=curve_dict,
        fly_categories=categories,
        residual_stats=stats_dict,
        entry_snapshots=snapshots_dict,
    )
