"""Deflated Sharpe Ratio (DSR) — Bailey & Lopez de Prado (2014).

Adjusts an observed (per-period) Sharpe for:
  1. Multiple-testing bias from running N strategy trials,
  2. Non-normality of returns (skewness, kurtosis), and
  3. Backtest length T.

References
----------
Bailey, D. H. and Lopez de Prado, M. (2014). "The Deflated Sharpe Ratio:
Correcting for Selection Bias, Backtest Overfitting and Non-Normality."
Journal of Portfolio Management, 40 (5), pp. 94-107.

Notes
-----
All Sharpe quantities inside this module are **per period** (e.g. per business
day) — NOT annualised. Annualise only for display.

The variance of the Sharpe estimator follows Mertens (2002) / Lo (2002):

    sigma^2(SR_hat) = (1 - skew * SR + (kurt - 1) / 4 * SR^2) / (T - 1)

where `kurt` is **raw** Pearson kurtosis (3.0 for a normal distribution), not
excess.

The expected maximum Sharpe under the null (no skill) across N independent
trials is:

    E[max SR] = sqrt(V[SR]) * ((1 - gamma) * Phi^-1(1 - 1/N)
                              +     gamma  * Phi^-1(1 - 1/(N*e)))

where gamma is the Euler-Mascheroni constant and Phi^-1 is the inverse
standard-normal CDF. `V[SR]` is the cross-trial variance of observed Sharpes.
"""
from __future__ import annotations

from typing import Iterable, Optional, Sequence

import numpy as np
import pandas as pd
from scipy.stats import norm


EULER_MASCHERONI = 0.5772156649015329


# ─────────────────────────────────────────────────────────────────────
# Per-trial statistics
# ─────────────────────────────────────────────────────────────────────

def sharpe_stats(returns: Iterable[float]) -> dict:
    """Per-period Sharpe + raw skew/kurtosis + sample size T.

    Parameters
    ----------
    returns : iterable of per-period returns (or P&L deltas — only the ratio
        mean/std matters).

    Returns
    -------
    {"sr": float, "T": int, "skew": float, "kurt": float}
        `sr` is mean / sample-std (ddof=1). `kurt` is Pearson raw (3.0 for
        a normal distribution). For T < 3 or zero variance, returns
        sr=0, skew=0, kurt=3.
    """
    r = np.asarray(list(returns), dtype=float)
    r = r[np.isfinite(r)]
    T = int(r.size)
    if T < 3:
        return {"sr": 0.0, "T": T, "skew": 0.0, "kurt": 3.0}

    mean = float(r.mean())
    sd_sample = float(r.std(ddof=1))
    # Tolerance relative to magnitude — handles floating-point noise on
    # constant inputs without masking real low-variance series.
    sd_floor = max(abs(mean), 1.0) * 1e-12
    if sd_sample <= sd_floor:
        return {"sr": 0.0, "T": T, "skew": 0.0, "kurt": 3.0}

    sr = mean / sd_sample
    sd_pop = float(r.std(ddof=0))
    if sd_pop <= sd_floor:
        return {"sr": float(sr), "T": T, "skew": 0.0, "kurt": 3.0}

    centered = r - mean
    skew = float((centered ** 3).mean() / sd_pop ** 3)
    kurt = float((centered ** 4).mean() / sd_pop ** 4)
    return {"sr": float(sr), "T": T, "skew": skew, "kurt": kurt}


def sharpe_estimator_variance(sr: float, skew: float, kurt: float, T: int) -> float:
    """Variance of the Sharpe estimator (Mertens / Lo).

    sigma^2(SR) = (1 - skew * SR + (kurt - 1) / 4 * SR^2) / (T - 1)
    """
    if T < 2:
        return float("nan")
    var = (1.0 - skew * sr + (kurt - 1.0) / 4.0 * sr * sr) / (T - 1)
    return float(var)


# ─────────────────────────────────────────────────────────────────────
# Multiple-testing benchmark
# ─────────────────────────────────────────────────────────────────────

def expected_max_sharpe_null(n_trials: int, sr_variance: float) -> float:
    """Expected max Sharpe under the null over N trials.

    Two-term approximation to E[max{SR_i}] when the N SRs are i.i.d. with
    mean 0 and variance `sr_variance`. Mean-zero assumption is the null
    (no skill); the cross-trial dispersion captures how lucky the best
    trial is expected to look by chance.

    Parameters
    ----------
    n_trials : Number of independent strategy trials.
    sr_variance : Cross-trial variance of per-period Sharpes.

    Returns
    -------
    Expected per-period Sharpe of the best trial under the null. Returns
    0.0 if `n_trials < 2` or `sr_variance <= 0`.
    """
    if n_trials < 2 or sr_variance <= 0 or not np.isfinite(sr_variance):
        return 0.0
    sd = float(np.sqrt(sr_variance))
    gamma = EULER_MASCHERONI
    n = float(n_trials)
    term1 = (1.0 - gamma) * norm.ppf(1.0 - 1.0 / n)
    term2 = gamma * norm.ppf(1.0 - 1.0 / (n * np.e))
    return float(sd * (term1 + term2))


# ─────────────────────────────────────────────────────────────────────
# DSR — single strategy
# ─────────────────────────────────────────────────────────────────────

def deflated_sharpe(
    returns: Iterable[float],
    n_trials: int,
    *,
    sr_benchmark: Optional[float] = None,
    sr_variance: Optional[float] = None,
    annualisation: float = 252.0,
) -> dict:
    """Compute the Deflated Sharpe Ratio for a single return stream.

    Parameters
    ----------
    returns : per-period (e.g. daily) returns or P&L deltas.
    n_trials : Number of strategy trials in the search (multiple-testing
        adjustment). Pass 1 to skip the multiple-testing adjustment.
    sr_benchmark : Optional explicit benchmark Sharpe (per period). If
        omitted, uses `expected_max_sharpe_null(n_trials, sr_variance)`.
    sr_variance : Cross-trial variance of per-period Sharpes. Required if
        `sr_benchmark` is None and `n_trials > 1`.
    annualisation : Periods per year for reporting annualised Sharpe
        (cosmetic; does not affect DSR).

    Returns
    -------
    dict with keys:
        sr              per-period Sharpe
        sr_annualised   sr * sqrt(annualisation)
        sr0             benchmark used
        sigma_sr        std of SR estimator (per period)
        dsr_z           (sr - sr0) / sigma_sr
        dsr_prob        Phi(dsr_z) — probability true SR exceeds sr0
        skew, kurt, T
    """
    stats = sharpe_stats(returns)
    sr = stats["sr"]
    T = stats["T"]
    skew = stats["skew"]
    kurt = stats["kurt"]

    if sr_benchmark is None:
        sr0 = expected_max_sharpe_null(n_trials, sr_variance or 0.0)
    else:
        sr0 = float(sr_benchmark)

    if T < 3:
        return {
            "sr": sr, "sr_annualised": sr * np.sqrt(annualisation),
            "sr0": sr0, "sigma_sr": float("nan"),
            "dsr_z": 0.0, "dsr_prob": 0.5,
            "skew": skew, "kurt": kurt, "T": T,
        }

    var_sr = sharpe_estimator_variance(sr, skew, kurt, T)
    if not np.isfinite(var_sr) or var_sr <= 0:
        var_sr = 1e-12
    sigma_sr = float(np.sqrt(var_sr))

    dsr_z = (sr - sr0) / sigma_sr
    dsr_prob = float(norm.cdf(dsr_z))

    return {
        "sr": sr,
        "sr_annualised": float(sr * np.sqrt(annualisation)),
        "sr0": sr0,
        "sigma_sr": sigma_sr,
        "dsr_z": float(dsr_z),
        "dsr_prob": dsr_prob,
        "skew": skew,
        "kurt": kurt,
        "T": T,
    }


# ─────────────────────────────────────────────────────────────────────
# DSR — grid-level gate
# ─────────────────────────────────────────────────────────────────────

def apply_dsr_gate(
    results: pd.DataFrame,
    *,
    returns_col: str = "daily_pnl",
    n_trials: Optional[int] = None,
    threshold: float = 0.95,
    sr_benchmark: Optional[float] = None,
    annualisation: float = 252.0,
) -> pd.DataFrame:
    """Apply the DSR gate to a grid of backtest results.

    For each row, reads the per-period return series from `returns_col`,
    computes per-period Sharpe + skew + kurtosis, then computes the DSR
    probability against a benchmark shared across the grid.

    The benchmark `sr0` defaults to `expected_max_sharpe_null(n_trials,
    sr_var)` where `sr_var` is the **cross-trial empirical variance** of
    per-period Sharpes — i.e. the gate uses the dispersion actually seen
    in this search rather than an external estimate.

    Parameters
    ----------
    results : DataFrame with one row per trial. Must contain `returns_col`
        whose entries are iterables of per-period returns.
    returns_col : Column name holding per-trial return series.
    n_trials : Override for the multiple-testing N. Defaults to len(results).
    threshold : Pass gate iff `dsr_prob >= threshold`. Default 0.95.
    sr_benchmark : Override the benchmark Sharpe (per period). If None,
        compute from the grid's cross-trial SR variance.
    annualisation : Periods per year for reporting annualised Sharpe.

    Returns
    -------
    Copy of `results` with appended columns:
        sr_per_period, T_obs, skew, kurt, sigma_sr,
        dsr_sr0, dsr_z, dsr_prob, dsr_pass.
    """
    if returns_col not in results.columns:
        raise KeyError(f"results must contain column {returns_col!r}")

    if n_trials is None:
        n_trials = len(results)

    sr_list: list[float] = []
    T_list: list[int] = []
    skew_list: list[float] = []
    kurt_list: list[float] = []

    for raw in results[returns_col]:
        if raw is None:
            stats = {"sr": 0.0, "T": 0, "skew": 0.0, "kurt": 3.0}
        else:
            stats = sharpe_stats(raw)
        sr_list.append(stats["sr"])
        T_list.append(stats["T"])
        skew_list.append(stats["skew"])
        kurt_list.append(stats["kurt"])

    sr_arr = np.asarray(sr_list, dtype=float)
    T_arr = np.asarray(T_list, dtype=int)
    valid = np.isfinite(sr_arr) & (T_arr >= 3)

    if sr_benchmark is None:
        if valid.sum() >= 2:
            sr_var = float(np.var(sr_arr[valid], ddof=1))
        else:
            sr_var = 0.0
        sr0 = expected_max_sharpe_null(n_trials, sr_var)
    else:
        sr0 = float(sr_benchmark)

    dsr_z_list: list[float] = []
    dsr_prob_list: list[float] = []
    sigma_list: list[float] = []

    for sr, T, skew, kurt in zip(sr_list, T_list, skew_list, kurt_list):
        if T < 3:
            sigma_list.append(float("nan"))
            dsr_z_list.append(float("nan"))
            dsr_prob_list.append(float("nan"))
            continue
        var_sr = sharpe_estimator_variance(sr, skew, kurt, T)
        if not np.isfinite(var_sr) or var_sr <= 0:
            var_sr = 1e-12
        sigma = float(np.sqrt(var_sr))
        z = (sr - sr0) / sigma
        sigma_list.append(sigma)
        dsr_z_list.append(float(z))
        dsr_prob_list.append(float(norm.cdf(z)))

    out = results.copy()
    out["sr_per_period"] = sr_list
    out["T_obs"] = T_list
    out["skew"] = skew_list
    out["kurt"] = kurt_list
    out["sigma_sr"] = sigma_list
    out["dsr_sr0"] = sr0
    out["dsr_z"] = dsr_z_list
    out["dsr_prob"] = dsr_prob_list
    prob_arr = np.asarray(dsr_prob_list, dtype=float)
    out["dsr_pass"] = np.where(np.isfinite(prob_arr), prob_arr >= threshold, False)
    return out


__all__ = [
    "EULER_MASCHERONI",
    "sharpe_stats",
    "sharpe_estimator_variance",
    "expected_max_sharpe_null",
    "deflated_sharpe",
    "apply_dsr_gate",
]
