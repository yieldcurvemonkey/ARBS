"""Lead-lag detection (data-agnostic).

Which leg leads informs execution timing and hedging variable choice.
Sources: BSIC "Beyond Traditional Lead-Lag Detection Methods" (Levy area);
standard cross-correlation and Granger causality.
"""
from __future__ import annotations

import numpy as np
import pandas as pd


def levy_area(x: pd.Series, y: pd.Series, window: int) -> pd.Series:
    """Rolling signed Levy area between two series.

    A_t = 0.5 * sum_{i in window} (x_i * dy_i - y_i * dx_i).
    Sign > 0 => x leads y over the window.
    """
    x = x.dropna()
    y = y.dropna()
    common = x.index.intersection(y.index)
    xv, yv = x.loc[common].values, y.loc[common].values
    dx = np.diff(xv)
    dy = np.diff(yv)
    increments = 0.5 * (xv[:-1] * dy - yv[:-1] * dx)

    w = int(window)
    n = len(increments)
    out = np.full(n, np.nan)
    for t in range(w - 1, n):
        out[t] = np.sum(increments[t - w + 1 : t + 1])

    idx = common[1:]
    return pd.Series(out, index=idx, name="levy_area")


def levy_area_signal(
    x: pd.Series,
    y: pd.Series,
    window: int = 10,
    theta_entry: float = 1.5,
    theta_exit: float = 0.5,
    ep: int = 1,
    xp: int = 1,
) -> pd.Series:
    """Entry/exit signals from Levy area with persistence.

    Normalizes the Levy area by its rolling std, then applies threshold logic:
    +1 when normalized area > theta_entry, -1 when < -theta_entry,
    0 when |area| < theta_exit. Position persists between entry/exit.
    """
    la = levy_area(x, y, window)
    roll_std = la.rolling(window * 5, min_periods=window).std(ddof=1)
    z = la / roll_std.replace(0, np.nan)

    pos = pd.Series(0, index=z.index, dtype=int, name="levy_signal")
    current = 0
    for i in range(len(z)):
        zv = z.iloc[i]
        if np.isnan(zv):
            pos.iloc[i] = current
            continue
        if current == 0:
            if zv > theta_entry:
                current = ep
            elif zv < -theta_entry:
                current = -xp
        elif current > 0:
            if zv < theta_exit:
                current = 0
        elif current < 0:
            if zv > -theta_exit:
                current = 0
        pos.iloc[i] = current
    return pos


def xcorr_lead_lag(x: pd.Series, y: pd.Series, max_lag: int) -> dict:
    """Find the lag (in periods) maximizing cross-correlation of changes.

    Positive lag means x leads y (y is shifted forward relative to x).
    Returns {"lag": int, "corr": float}.
    """
    x, y = x.dropna(), y.dropna()
    common = x.index.intersection(y.index)
    dx = np.diff(x.loc[common].values)
    dy = np.diff(y.loc[common].values)
    max_lag = int(max_lag)

    best_lag, best_corr = 0, -np.inf
    for lag in range(-max_lag, max_lag + 1):
        if lag >= 0:
            a, b = dx[: len(dx) - lag] if lag > 0 else dx, dy[lag:] if lag > 0 else dy
        else:
            a, b = dx[-lag:], dy[: len(dy) + lag]
        if len(a) < 3:
            continue
        c = float(np.corrcoef(a, b)[0, 1])
        if np.isfinite(c) and c > best_corr:
            best_corr = c
            best_lag = lag
    return {"lag": best_lag, "corr": float(best_corr)}


def granger_lead_lag(x: pd.Series, y: pd.Series, max_lag: int) -> dict:
    """Granger causality test: does x Granger-cause y?

    Tests lags 1..max_lag, returns the lag with minimum p-value.
    Returns {"lag": int, "pvalue": float}.
    """
    from statsmodels.tsa.stattools import grangercausalitytests

    x, y = x.dropna(), y.dropna()
    common = x.index.intersection(y.index)
    data = np.column_stack([y.loc[common].values, x.loc[common].values])

    results = grangercausalitytests(data, maxlag=int(max_lag), verbose=False)
    best_lag, best_p = 1, 1.0
    for lag, res in results.items():
        p = res[0]["ssr_ftest"][1]
        if p < best_p:
            best_p = p
            best_lag = lag
    return {"lag": int(best_lag), "pvalue": float(best_p)}
