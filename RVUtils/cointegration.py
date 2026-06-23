"""Cointegration / mean-reversion pair utilities (data-agnostic).

Public API
----------
engle_granger(y, x, *, hedge="ols", trend="c") -> dict
johansen(df, *, det_order=0, k_ar_diff=1) -> dict
spread(y, x, beta, alpha=0.0) -> pd.Series
zscore(s, window=None) -> pd.Series
bands(s, k=2.0, window=None) -> pd.DataFrame
make_cointegration_builder(df, y_col, x_col) -> (fit, get_spread, get_zscore, get_bands, get_data)

Design mirrors pca_rv.py (builder closure style); reuses calibrate_ou from
mean_reversion.py and get_tls_hedge_ratio from arbl_hedge_ratios.py.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import statsmodels.api as sm
from statsmodels.tsa.stattools import adfuller
from statsmodels.tsa.vector_ar.vecm import coint_johansen

from RVUtils.mean_reversion import calibrate_ou
from RVUtils.arbl_hedge_ratios import get_tls_hedge_ratio


# ---------------------------------------------------------------------------
# Core utilities
# ---------------------------------------------------------------------------

def spread(y: pd.Series, x: pd.Series, beta: float, alpha: float = 0.0) -> pd.Series:
    """Compute spread: y - alpha - beta*x.

    Parameters
    ----------
    y, x : pd.Series
        Price/rate series (need not share index; aligned on intersection if different).
    beta : float
        Hedge ratio.
    alpha : float
        Intercept / carry offset (default 0).

    Returns
    -------
    pd.Series
        Spread series indexed like y (assumes y and x already aligned, or y alone).
    """
    return y - alpha - beta * x


def zscore(s: pd.Series, window: int | None = None) -> pd.Series:
    """Standardise a series.

    Parameters
    ----------
    s : pd.Series
    window : int or None
        If None, full-sample (s - mean) / std.
        If int, rolling window with min_periods=window.

    Returns
    -------
    pd.Series
    """
    if window is None:
        return (s - s.mean()) / s.std(ddof=1)
    r = s.rolling(int(window), min_periods=int(window))
    return (s - r.mean()) / r.std(ddof=1)


def bands(s: pd.Series, k: float = 2.0, window: int | None = None) -> pd.DataFrame:
    """Compute mean +/- k*std bands.

    Parameters
    ----------
    s : pd.Series
    k : float
        Number of standard deviations for band width (default 2).
    window : int or None
        If None, full-sample (constant bands).
        If int, rolling window with min_periods=window.

    Returns
    -------
    pd.DataFrame with columns {mean, upper, lower}.
    """
    if window is None:
        mu = pd.Series(s.mean(), index=s.index)
        sigma = pd.Series(s.std(ddof=1), index=s.index)
    else:
        r = s.rolling(int(window), min_periods=int(window))
        mu = r.mean()
        sigma = r.std(ddof=1)
    return pd.DataFrame({"mean": mu, "upper": mu + k * sigma, "lower": mu - k * sigma})


# ---------------------------------------------------------------------------
# Engle-Granger two-step cointegration test
# ---------------------------------------------------------------------------

def engle_granger(
    y: pd.Series,
    x: pd.Series,
    *,
    hedge: str = "ols",
    trend: str = "c",
) -> dict:
    """Engle-Granger two-step cointegration test for a pair (y, x).

    Step 1 — Estimate hedge ratio (OLS or TLS).
    Step 2 — Run ADF on the residual spread.

    Parameters
    ----------
    y, x : pd.Series
        The two series to test.  Aligned on their common DatetimeIndex.
    hedge : {"ols", "tls"}
        Hedge ratio method.  "ols" uses statsmodels OLS of y on [const, x];
        "tls" uses orthogonal/Total Least Squares via scipy.odr (reuses
        arbl_hedge_ratios.get_tls_hedge_ratio).
    trend : str
        ADF regression type passed to adfuller (default "c" = constant).

    Returns
    -------
    dict with keys:
        beta        - hedge ratio (float)
        alpha       - intercept (float; 0.0 for tls without constant)
        spread      - pd.Series of residuals y - alpha - beta*x
        adf_stat    - ADF test statistic (float)
        pvalue      - MacKinnon approximate p-value (float)
        half_life   - OU half-life of the spread in periods (float, may be NaN)
    """
    if hedge not in ("ols", "tls"):
        raise ValueError(f"hedge must be 'ols' or 'tls', got {hedge!r}")

    # Align on common index
    common = y.index.intersection(x.index)
    y_a = y.loc[common].astype(float)
    x_a = x.loc[common].astype(float)

    if hedge == "ols":
        X = sm.add_constant(x_a.values, prepend=True)
        ols_res = sm.OLS(y_a.values, X).fit()
        alpha = float(ols_res.params[0])
        beta = float(ols_res.params[1])
    else:  # tls
        pair_df = pd.DataFrame({"y": y_a.values, "x": x_a.values}, index=common)
        ratios_dict, _, _, _ = get_tls_hedge_ratio(pair_df, dependent_variable="y", add_constant=False)
        # ratios_dict = {"y": 1.0, "x": beta_tls}
        beta = float(ratios_dict["x"])
        alpha = 0.0

    sp = spread(y_a, x_a, beta=beta, alpha=alpha)
    sp.name = "spread"

    adf_result = adfuller(sp.dropna().values, regression=trend)
    adf_stat = float(adf_result[0])
    pvalue = float(adf_result[1])

    ou_params = calibrate_ou(sp.dropna())
    half_life = ou_params["half_life"]

    return {
        "beta": beta,
        "alpha": alpha,
        "spread": sp,
        "adf_stat": adf_stat,
        "pvalue": pvalue,
        "half_life": half_life,
    }


# ---------------------------------------------------------------------------
# Johansen multivariate cointegration test
# ---------------------------------------------------------------------------

def johansen(
    df: pd.DataFrame,
    *,
    det_order: int = 0,
    k_ar_diff: int = 1,
) -> dict:
    """Johansen cointegration test on a multivariate system.

    Parameters
    ----------
    df : pd.DataFrame
        Wide DataFrame (rows = dates, columns = series), all I(1).
    det_order : int
        Deterministic specification passed to coint_johansen:
        -1 = no constant, 0 = restricted constant, 1 = unrestricted constant.
    k_ar_diff : int
        Number of lagged differences in the VECM representation (default 1).

    Returns
    -------
    dict with keys:
        trace_stat   - np.ndarray of trace test statistics
        eigen_stat   - np.ndarray of maximum-eigenvalue statistics
        crit_trace   - np.ndarray of 95% critical values for trace test
        coint_vector - np.ndarray, first cointegrating eigenvector normalized
                       so the first element = 1.0
        rank         - int, number of trace stats exceeding their 95% crit value
    """
    data = df.dropna().astype(float)
    res = coint_johansen(data.values, det_order, k_ar_diff)

    trace_stat = res.lr1               # shape (k,)
    eigen_stat = res.lr2               # shape (k,)
    crit_trace = res.cvt[:, 1]        # 95% column (index 1: 90/95/99)

    # Rank: count how many trace stats exceed 95% critical value
    rank = int(np.sum(trace_stat > crit_trace))

    # First cointegrating eigenvector (first column of evec), normalize so first element = 1
    evec = res.evec[:, 0]
    coint_vector = evec / evec[0]

    return {
        "trace_stat": trace_stat,
        "eigen_stat": eigen_stat,
        "crit_trace": crit_trace,
        "coint_vector": coint_vector,
        "rank": rank,
    }


# ---------------------------------------------------------------------------
# Builder (closure factory)
# ---------------------------------------------------------------------------

def make_cointegration_builder(
    df: pd.DataFrame,
    y_col: str,
    x_col: str,
    *,
    hedge: str = "ols",
    trend: str = "c",
    zscore_window: int | None = None,
    bands_k: float = 2.0,
    bands_window: int | None = None,
):
    """Thin closure-based builder for a single cointegrated pair.

    Parameters
    ----------
    df : pd.DataFrame
        Must contain y_col and x_col.
    y_col, x_col : str
        Column names for the dependent and independent variable.
    hedge : str
        Passed to engle_granger.
    trend : str
        Passed to engle_granger.
    zscore_window : int or None
        Default window for get_zscore().
    bands_k : float
        Default k for get_bands().
    bands_window : int or None
        Default window for get_bands().

    Returns
    -------
    (fit, get_spread, get_zscore, get_bands, get_data)

    fit() -> dict
        Run engle_granger and cache the result; returns the result dict.
    get_spread() -> pd.Series
        Return the fitted spread (requires fit() first).
    get_zscore(window=None) -> pd.Series
        Return z-scored spread.
    get_bands(k=bands_k, window=bands_window) -> pd.DataFrame
        Return mean/upper/lower bands.
    get_data() -> pd.DataFrame
        Return the input DataFrame slice [y_col, x_col].
    """
    _data = df[[y_col, x_col]].copy()
    _state: dict = {"result": None}

    def fit() -> dict:
        eg = engle_granger(_data[y_col], _data[x_col], hedge=hedge, trend=trend)
        _state["result"] = eg
        return eg

    def _require() -> dict:
        if _state["result"] is None:
            raise RuntimeError("Call fit() before using the cointegration builder.")
        return _state["result"]

    def get_spread() -> pd.Series:
        return _require()["spread"]

    def get_zscore(window: int | None = zscore_window) -> pd.Series:
        sp = _require()["spread"]
        return zscore(sp.dropna(), window=window)

    def get_bands(k: float = bands_k, window: int | None = bands_window) -> pd.DataFrame:
        sp = _require()["spread"]
        return bands(sp.dropna(), k=k, window=window)

    def get_data() -> pd.DataFrame:
        return _data.copy()

    return fit, get_spread, get_zscore, get_bands, get_data
