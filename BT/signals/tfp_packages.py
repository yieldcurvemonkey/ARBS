"""
TFP Swap Spread Package Trading Signals.

Generates all C(6,2)=15 curve pairs and C(6,3)=20 butterfly flies from
the regression tenor set [2Y, 3Y, 5Y, 7Y, 10Y, 30Y], computes OU-calibrated
mean-reversion signals on deviation differentials, optionally computes
PCA-weighted position sizing via Ledoit-Wolf shrinkage, and provides a fast
vectorized P&L preview.
"""

from __future__ import annotations

import datetime
import logging
from dataclasses import dataclass
from itertools import combinations
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd
from sklearn.covariance import LedoitWolf

from BT.signals.tfp_swap_spread import CT_MAP, REGRESSION_TENORS

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# 1. Package dataclass and universe generator
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Package:
    """A tradeable spread package (curve or butterfly)."""

    name: str  # e.g. '2s10s', '2s5s10s'
    legs: Tuple[str, ...]
    weights: Tuple[int, ...]  # curves: (-1, +1), flies: (+1, -2, +1)
    kind: str  # 'curve' or 'fly'


def _tenor_label(tenor: str) -> str:
    """Convert tenor string to short label: '2Y' -> '2', '30Y' -> '30'."""
    return tenor.replace("Y", "").lower()


def generate_universe(tenors: Optional[List[str]] = None) -> List[Package]:
    """Generate all C(n,2) curves and C(n,3) flies from the tenor set.

    Parameters
    ----------
    tenors : list of str, optional
        Tenor labels to use. Defaults to REGRESSION_TENORS.

    Returns
    -------
    list of Package
        All curve pairs and butterfly flies.
    """
    if tenors is None:
        tenors = list(REGRESSION_TENORS)

    packages: List[Package] = []

    # Curves: all C(n,2) pairs
    for short_leg, long_leg in combinations(tenors, 2):
        name = f"{_tenor_label(short_leg)}s{_tenor_label(long_leg)}s"
        packages.append(
            Package(
                name=name,
                legs=(short_leg, long_leg),
                weights=(-1, 1),
                kind="curve",
            )
        )

    # Flies: all C(n,3) butterflies
    for wing1, belly, wing2 in combinations(tenors, 3):
        name = f"{_tenor_label(wing1)}s{_tenor_label(belly)}s{_tenor_label(wing2)}s"
        packages.append(
            Package(
                name=name,
                legs=(wing1, belly, wing2),
                weights=(1, -2, 1),
                kind="fly",
            )
        )

    return packages


# ---------------------------------------------------------------------------
# 2. OU parameter calibration
# ---------------------------------------------------------------------------

def _ou_params(series: pd.Series) -> dict:
    """Calibrate Ornstein-Uhlenbeck parameters via AR(1) MLE.

    Model: y_t = a + b * y_{t-1} + eps

    Derived parameters:
        mu = a / (1 - b)
        theta = -ln(b)
        sigma = sqrt(var(eps) * 2 * theta / (1 - b^2))
        half_life = ln(2) / theta

    Returns
    -------
    dict
        Keys: mu, theta, sigma, half_life. NaN on failure.
    """
    nan_result = {"mu": np.nan, "theta": np.nan, "sigma": np.nan, "half_life": np.nan}

    s = series.dropna()
    if len(s) < 10:
        return nan_result

    y = s.values[1:]
    x = s.values[:-1]

    n = len(y)
    sx = x.sum()
    sy = y.sum()
    sxx = (x * x).sum()
    sxy = (x * y).sum()

    denom = n * sxx - sx * sx
    if abs(denom) < 1e-15:
        return nan_result

    b = (n * sxy - sx * sy) / denom
    a = (sy - b * sx) / n

    # b must be in (0, 1) for mean-reversion
    if b <= 0 or b >= 1:
        return nan_result

    mu = a / (1 - b)
    theta = -np.log(b)
    half_life = np.log(2) / theta

    residuals = y - (a + b * x)
    var_eps = np.var(residuals, ddof=1)
    sigma = np.sqrt(var_eps * 2 * theta / (1 - b * b))

    return {"mu": mu, "theta": theta, "sigma": sigma, "half_life": half_life}


# ---------------------------------------------------------------------------
# 3. Signal computation with OU exits
# ---------------------------------------------------------------------------

def compute_package_signals(
    history: pd.DataFrame,
    packages: List[Package],
    *,
    z_window: int = 60,
    z_entry: float = 1.5,
    ou_exit: bool = True,
    ou_window: int = 252,
    fixed_z_exit: float = 0.5,
    max_hold: int = 60,
) -> Tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Compute OU-calibrated mean-reversion signals for each package.

    Parameters
    ----------
    history : DataFrame
        Must contain columns like 'dev_2Y', 'dev_3Y', etc. (deviation series).
    packages : list of Package
        Package universe to compute signals for.
    z_window : int
        Rolling z-score window.
    z_entry : float
        Z-score threshold for entry.
    ou_exit : bool
        If True, exit when dev_diff crosses OU mu. If False, exit at fixed_z_exit.
    ou_window : int
        Trailing window for OU calibration.
    fixed_z_exit : float
        Z-score exit threshold (used when ou_exit=False).
    max_hold : int
        Maximum holding period in days.

    Returns
    -------
    (dev_diffs, zscores, signals) : tuple of DataFrames
        Each DataFrame has columns = package names, index = history index.
    """
    dev_diffs = pd.DataFrame(index=history.index)
    zscores = pd.DataFrame(index=history.index)
    signals = pd.DataFrame(index=history.index, dtype=float)

    for pkg in packages:
        # Compute weighted deviation differential
        dd = pd.Series(0.0, index=history.index)
        valid = True
        for tenor, weight in zip(pkg.legs, pkg.weights):
            col = f"dev_{tenor}"
            if col not in history.columns:
                valid = False
                break
            dd = dd + weight * history[col]

        if not valid:
            dev_diffs[pkg.name] = np.nan
            zscores[pkg.name] = np.nan
            signals[pkg.name] = 0.0
            continue

        dev_diffs[pkg.name] = dd

        # Rolling z-score
        roll_mean = dd.rolling(z_window, min_periods=max(10, z_window // 2)).mean()
        roll_std = dd.rolling(z_window, min_periods=max(10, z_window // 2)).std()
        z = (dd - roll_mean) / roll_std.replace(0, np.nan)
        zscores[pkg.name] = z

        # Generate signals with entry/exit logic
        sig = pd.Series(0.0, index=history.index)
        position = 0.0
        hold_count = 0

        for i in range(len(history)):
            z_val = z.iloc[i]

            if np.isnan(z_val):
                sig.iloc[i] = 0.0
                continue

            if position == 0.0:
                # Entry logic
                if z_val > z_entry:
                    position = -1.0  # mean-revert: sell rich
                    hold_count = 1
                elif z_val < -z_entry:
                    position = 1.0  # mean-revert: buy cheap
                    hold_count = 1
            else:
                hold_count += 1
                should_exit = False

                # Max hold stop
                if hold_count >= max_hold:
                    should_exit = True
                elif ou_exit:
                    # OU-based exit: cross the long-run mean
                    start_idx = max(0, i - ou_window)
                    ou = _ou_params(dd.iloc[start_idx:i])
                    mu = ou["mu"]
                    if not np.isnan(mu):
                        if position > 0 and dd.iloc[i] >= mu:
                            should_exit = True
                        elif position < 0 and dd.iloc[i] <= mu:
                            should_exit = True
                else:
                    # Fixed z-score exit
                    if position > 0 and z_val >= -fixed_z_exit:
                        should_exit = True
                    elif position < 0 and z_val <= fixed_z_exit:
                        should_exit = True

                if should_exit:
                    position = 0.0
                    hold_count = 0

            sig.iloc[i] = position

        signals[pkg.name] = sig

    return dev_diffs, zscores, signals


# ---------------------------------------------------------------------------
# 4. PCA weighting via Ledoit-Wolf
# ---------------------------------------------------------------------------

def compute_pca_weights(
    dev_diffs: pd.DataFrame,
    *,
    cov_window: int = 90,
    n_components: int = 3,
    method: str = "inverse_vol",
) -> pd.DataFrame:
    """Compute PCA-based position weights using Ledoit-Wolf shrinkage.

    Parameters
    ----------
    dev_diffs : DataFrame
        Daily deviation differentials (date x package_name).
    cov_window : int
        Rolling window for covariance estimation.
    n_components : int
        Number of PCA components to retain (used for GMV/MSR methods).
    method : str
        Weighting method: 'inverse_vol', 'gmv', 'msr', 'equal'.

    Returns
    -------
    DataFrame
        Weights (date x package_name), normalized to sum abs = 1.
    """
    changes = dev_diffs.diff().dropna()
    weights = pd.DataFrame(np.nan, index=changes.index, columns=changes.columns)

    n_cols = len(changes.columns)

    for i in range(cov_window, len(changes)):
        window_data = changes.iloc[i - cov_window : i].dropna(axis=1, how="any")
        if window_data.shape[1] < 2 or window_data.shape[0] < cov_window // 2:
            continue

        try:
            lw = LedoitWolf().fit(window_data.values)
            cov_matrix = lw.covariance_
        except Exception:
            continue

        cols = window_data.columns
        n = len(cols)

        if method == "equal":
            w = np.ones(n) / n
        elif method == "inverse_vol":
            vols = np.sqrt(np.diag(cov_matrix))
            vols = np.where(vols > 1e-10, vols, 1e-10)
            w = 1.0 / vols
            w = w / np.sum(np.abs(w))
        elif method == "gmv":
            # Global minimum variance: w = Sigma^-1 @ 1 / (1^T @ Sigma^-1 @ 1)
            try:
                inv_cov = np.linalg.inv(cov_matrix)
                ones = np.ones(n)
                w = inv_cov @ ones
                w = w / np.sum(np.abs(w))
            except np.linalg.LinAlgError:
                continue
        elif method == "msr":
            # Maximum Sharpe ratio: w = Sigma^-1 @ mu
            try:
                inv_cov = np.linalg.inv(cov_matrix)
                mu = window_data.mean().values
                w = inv_cov @ mu
                w_sum = np.sum(np.abs(w))
                if w_sum > 1e-10:
                    w = w / w_sum
                else:
                    w = np.ones(n) / n
            except np.linalg.LinAlgError:
                continue
        else:
            raise ValueError(f"Unknown method: {method}")

        # Assign weights for this date
        date_idx = changes.index[i]
        for j, col in enumerate(cols):
            weights.loc[date_idx, col] = w[j]

    # Fill remaining columns with 0
    weights = weights.fillna(0.0)
    return weights


# ---------------------------------------------------------------------------
# 5. Event extraction
# ---------------------------------------------------------------------------

def extract_package_events(
    signals: pd.DataFrame,
    pkg: Package,
    bt_start: datetime.date,
    bt_end: datetime.date,
) -> List[dict]:
    """Convert signal column to entry/exit events.

    IMPORTANT: All dates are converted to datetime.date objects, not Timestamps.
    This is required for DateTriggerRequirements compatibility.

    Parameters
    ----------
    signals : DataFrame
        Signals DataFrame with package names as columns.
    pkg : Package
        The package to extract events for.
    bt_start : date
        Backtest start date.
    bt_end : date
        Backtest end date.

    Returns
    -------
    list of dict
        Each event: {entry_date, exit_date, direction, pkg, tag, legs, weights}
    """
    if pkg.name not in signals.columns:
        return []

    sig = signals[pkg.name].copy()

    # Filter to backtest window
    idx_dates = pd.to_datetime(sig.index)
    mask = (idx_dates >= pd.Timestamp(bt_start)) & (idx_dates <= pd.Timestamp(bt_end))
    sig = sig.loc[mask]

    events: List[dict] = []
    in_trade = False
    entry_date = None
    direction = 0

    for idx_val, val in sig.items():
        # Convert index to datetime.date (critical: not Timestamp)
        if isinstance(idx_val, pd.Timestamp):
            current_date = idx_val.date()
        elif isinstance(idx_val, datetime.datetime):
            current_date = idx_val.date()
        elif isinstance(idx_val, datetime.date):
            current_date = idx_val
        else:
            current_date = pd.Timestamp(idx_val).date()

        if not in_trade:
            if val != 0.0:
                in_trade = True
                entry_date = current_date
                direction = int(val)
        else:
            if val == 0.0 or (val != 0.0 and int(val) != direction):
                # Exit
                events.append(
                    {
                        "entry_date": entry_date,
                        "exit_date": current_date,
                        "direction": direction,
                        "pkg": pkg.name,
                        "tag": f"tfp_{pkg.kind}_{pkg.name}",
                        "legs": list(pkg.legs),
                        "weights": list(pkg.weights),
                    }
                )
                in_trade = False
                # Check if new trade starts on this bar
                if val != 0.0:
                    in_trade = True
                    entry_date = current_date
                    direction = int(val)

    # Close open trade at end
    if in_trade and entry_date is not None:
        last_date = current_date  # noqa: F821
        events.append(
            {
                "entry_date": entry_date,
                "exit_date": last_date,
                "direction": direction,
                "pkg": pkg.name,
                "tag": f"tfp_{pkg.kind}_{pkg.name}",
                "legs": list(pkg.legs),
                "weights": list(pkg.weights),
            }
        )

    return events


# ---------------------------------------------------------------------------
# 6. Vectorized preview
# ---------------------------------------------------------------------------

def vectorized_preview(
    history: pd.DataFrame,
    packages: List[Package],
    signals: pd.DataFrame,
    dev_diffs: pd.DataFrame,
    bt_start: datetime.date,
    bt_end: datetime.date,
    *,
    pca_weights: Optional[pd.DataFrame] = None,
) -> pd.DataFrame:
    """Fast vectorized P&L preview for all packages.

    Daily P&L: -signal * delta(weighted deviation diff), optionally scaled by PCA weights.

    Parameters
    ----------
    history : DataFrame
        Full history with deviation columns.
    packages : list of Package
        Package universe.
    signals : DataFrame
        Signal DataFrame (date x package_name).
    dev_diffs : DataFrame
        Deviation differentials (date x package_name).
    bt_start : date
        Backtest start date.
    bt_end : date
        Backtest end date.
    pca_weights : DataFrame, optional
        PCA weights (date x package_name). If None, equal weight.

    Returns
    -------
    DataFrame
        Summary with columns: Package, Kind, Legs, Sharpe, Total_bp, MaxDD_bp, Trades, OU_HL
    """
    # Filter to backtest window
    idx_dates = pd.to_datetime(signals.index)
    mask = (idx_dates >= pd.Timestamp(bt_start)) & (idx_dates <= pd.Timestamp(bt_end))

    sig_bt = signals.loc[mask]
    dd_bt = dev_diffs.loc[mask]
    dd_delta = dd_bt.diff()

    results = []
    for pkg in packages:
        if pkg.name not in sig_bt.columns:
            continue

        s = sig_bt[pkg.name]
        d = dd_delta[pkg.name]

        # Daily P&L: sell rich (signal=-1) profits when dev_diff falls
        daily_pnl = -s.shift(1) * d

        # Apply PCA weights if provided
        if pca_weights is not None and pkg.name in pca_weights.columns:
            w_aligned = pca_weights[pkg.name].reindex(daily_pnl.index).ffill().fillna(1.0 / max(len(packages), 1))
            daily_pnl = daily_pnl * w_aligned * len(packages)

        daily_pnl = daily_pnl.fillna(0.0)
        cum_pnl = daily_pnl.cumsum()

        # Metrics
        total_bp = cum_pnl.iloc[-1] if len(cum_pnl) > 0 else 0.0
        max_dd = (cum_pnl - cum_pnl.cummax()).min() if len(cum_pnl) > 0 else 0.0
        std = daily_pnl.std()
        sharpe = (daily_pnl.mean() / std * np.sqrt(252)) if std > 1e-10 else 0.0

        # Trade count: number of signal changes from 0 to non-zero
        trade_starts = ((s != 0) & (s.shift(1).fillna(0) == 0)).sum()

        # OU half-life on full series
        dd_full = dev_diffs[pkg.name].dropna()
        ou = _ou_params(dd_full)
        half_life = ou["half_life"]

        results.append(
            {
                "Package": pkg.name,
                "Kind": pkg.kind,
                "Legs": ", ".join(pkg.legs),
                "Sharpe": round(sharpe, 2),
                "Total_bp": round(total_bp, 2),
                "MaxDD_bp": round(max_dd, 2),
                "Trades": int(trade_starts),
                "OU_HL": round(half_life, 1) if not np.isnan(half_life) else np.nan,
            }
        )

    return pd.DataFrame(results)
