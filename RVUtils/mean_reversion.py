from datetime import timedelta
from typing import Optional

import numpy as np
import pandas as pd


def simulate_mean_reversion_ou(df: pd.DataFrame, steps: Optional[int] = 252) -> pd.DataFrame:
    def count_while(steps, monte_carlo_df, mean, simulations):
        results = []
        for j in range(simulations):
            i = 0
            while (monte_carlo_df[i, j] < mean) and (i < (steps - 1)):
                i += 1
            results.append(i)
        return np.mean(results)

    def ou_monte_carlo(start_value, mean, sigma, lambda_param, simulations, steps):
        monte_carlo_df = np.zeros((steps, simulations))
        for j in range(simulations):
            sim_path = [start_value]
            for i in range(1, steps):
                w = np.random.normal()
                sim_path.append(sim_path[i - 1] * np.exp(-lambda_param) + mean * (1 - np.exp(-lambda_param)) + np.sqrt(sigma) * w)
            monte_carlo_df[:, j] = sim_path
        return monte_carlo_df

    def get_first_passage_time(start_value, mean, sigma, lambda_param):
        simulations = 150
        monte_carlo_df = ou_monte_carlo(start_value, mean, sigma, lambda_param, simulations, steps)
        return count_while(100, monte_carlo_df, mean, simulations)

    def get_mean_reversion_params(df: pd.DataFrame):
        n = len(df) - 1
        s = df.sum().iloc[0]
        sx = s - df.iloc[-1, 0]
        sy = s - df.iloc[0, 0]
        sxy = (df.iloc[:, 0] * df.iloc[:, 0].shift(1)).sum()
        syy = (df.iloc[1:, 0] ** 2).sum()
        sxx = (df.iloc[:-1, 0] ** 2).sum()

        mean = (sy * sxx - sx * sxy) / (n * (sxx - sxy) - (sx**2 - sx * sy))
        lambda_param = -np.log((sxy - mean * sx - mean * sy + n * mean**2) / (sxx - 2 * mean * sx + n * mean**2))
        alpha = np.exp(-lambda_param)
        sigma_tilde = (1 / n) * (syy - 2 * alpha * sxy + sxx * alpha**2 - 2 * mean * (1 - alpha) * (sy - alpha * sx) + n * mean**2 * (1 - alpha) ** 2)
        sigma_squared = sigma_tilde * 2 * lambda_param / (1 - alpha**2)
        return mean, lambda_param, sigma_squared

    mean, lambda_param, sigma_squared = get_mean_reversion_params(df)
    start_value = df.iloc[-1, 0]

    date_array = [df.index[-1] + timedelta(days=t) for t in range(steps)]
    expected_values = []
    upper_1_sigma, lower_1_sigma = [], []
    upper_2_sigma, lower_2_sigma = [], []

    for t in range(steps):
        if t == 0:
            value = start_value * np.exp(-lambda_param) + mean * (1 - np.exp(-lambda_param))
        else:
            value = expected_values[-1] * np.exp(-lambda_param) + mean * (1 - np.exp(-lambda_param))
        expected_values.append(value)

        drift_variance = (sigma_squared / (2 * lambda_param)) * (1 - np.exp(-2 * lambda_param * (t + 1)))
        standard_deviation = np.sqrt(drift_variance)

        upper_1_sigma.append(value + standard_deviation)
        lower_1_sigma.append(value - standard_deviation)
        upper_2_sigma.append(value + 2 * standard_deviation)
        lower_2_sigma.append(value - 2 * standard_deviation)

    forecast_df = pd.DataFrame(
        {
            "date": date_array,
            "mean_reversion": expected_values,
            "+1_sigma": upper_1_sigma,
            "-1_sigma": lower_1_sigma,
            "+2_sigma": upper_2_sigma,
            "-2_sigma": lower_2_sigma,
        }
    ).set_index("date")

    return forecast_df, get_first_passage_time(start_value, mean, sigma_squared, lambda_param)


# ============================================================================
# OU calibration / analytics (data-agnostic; used across the RV toolkit)
# ============================================================================

def calibrate_ou(series: pd.Series, *, dt: float = 1.0, demean: bool = False) -> dict:
    """Calibrate an Ornstein-Uhlenbeck process dx = kappa(mu - x)dt + sigma dW
    to a single series via the discrete AR(1) analogue x_t = a + phi*x_{t-1} + e.

    Returns dict {mu, kappa, sigma, phi, intercept, half_life}; values are NaN
    when the series is too short or not mean-reverting (phi outside (0,1)).
    """
    y = pd.Series(series).dropna().astype(float)
    nan = {"mu": np.nan, "kappa": np.nan, "sigma": np.nan, "phi": np.nan, "intercept": np.nan, "half_life": np.nan}
    if len(y) < 5:
        return nan
    if demean:
        y = y - y.mean()
    y0 = y.shift(1).dropna()
    y1 = y.loc[y0.index]
    X = np.column_stack([np.ones(len(y0)), y0.values])
    try:
        a, b = np.linalg.lstsq(X, y1.values, rcond=None)[0]
    except Exception:
        return nan
    phi = float(b)
    if not (0.0 < phi < 1.0) or not np.isfinite(phi):
        return {"mu": np.nan, "kappa": np.nan, "sigma": np.nan, "phi": phi, "intercept": float(a), "half_life": np.nan}
    kappa = -np.log(phi) / float(dt)
    mu = a / (1.0 - phi)
    eps = y1.values - (a + b * y0.values)
    s2 = float(np.var(eps, ddof=1))
    sigma = float(np.sqrt(max(0.0, s2 * (2.0 * kappa) / (1.0 - phi**2))))
    half_life = float(np.log(2.0) / kappa)
    return {"mu": float(mu), "kappa": float(kappa), "sigma": sigma, "phi": phi, "intercept": float(a), "half_life": half_life}


def ou_conditional(x0: float, params: dict, horizon: float) -> dict:
    """Conditional moments of OU at `horizon` given current value x0.

    mean = mu + (x0-mu) e^{-kappa h};  var = sigma^2/(2 kappa) (1 - e^{-2 kappa h}).
    """
    kappa = params.get("kappa", np.nan)
    mu = params.get("mu", np.nan)
    sigma = params.get("sigma", np.nan)
    if not (np.isfinite(kappa) and kappa > 0 and np.isfinite(mu) and np.isfinite(sigma)):
        return {"mean": np.nan, "var": np.nan, "std": np.nan}
    h = float(horizon)
    mean = mu + (x0 - mu) * np.exp(-kappa * h)
    var = (sigma**2) / (2.0 * kappa) * (1.0 - np.exp(-2.0 * kappa * h))
    var = max(0.0, float(var))
    return {"mean": float(mean), "var": var, "std": float(np.sqrt(var))}


def ou_ex_ante_sharpe(x0: float, params: dict, horizon: float, *, annualize: bool = True, periods: int = 252) -> float:
    """Ex-ante Sharpe ratio of the mean-reversion move over `horizon`.

    SR = (E[x_{t+h}] - x0) / std(x_{t+h}); optionally annualised by sqrt(periods/horizon).
    Note (Huggins-Schaller): annualised SR declines with horizon for OU.
    """
    cond = ou_conditional(x0, params, horizon)
    if not np.isfinite(cond["std"]) or cond["std"] <= 0:
        return np.nan
    sr = (cond["mean"] - x0) / cond["std"]
    if annualize:
        sr *= np.sqrt(float(periods) / float(horizon))
    return float(sr)


def first_passage_time(x0: float, target: float, params: dict, *, sims: int = 2000, steps: int = 252, dt: float = 1.0) -> float:
    """Monte-Carlo expected first-passage time (in steps) from x0 to `target`
    under the calibrated OU. Paths that never reach target contribute `steps`.
    Seed numpy (np.random.seed) before calling for reproducibility.
    """
    kappa = params.get("kappa", np.nan)
    mu = params.get("mu", np.nan)
    sigma = params.get("sigma", np.nan)
    if not (np.isfinite(kappa) and kappa > 0 and np.isfinite(sigma) and sigma >= 0 and np.isfinite(mu)):
        return np.nan
    phi = np.exp(-kappa * dt)
    s_step = sigma * np.sqrt(max(0.0, (1.0 - np.exp(-2.0 * kappa * dt)) / (2.0 * kappa)))
    x = np.full(int(sims), float(x0))
    hit = np.full(int(sims), float(steps))
    done = np.zeros(int(sims), dtype=bool)
    up = x0 <= target
    for t in range(1, int(steps) + 1):
        x = mu + phi * (x - mu) + s_step * np.random.standard_normal(int(sims))
        newly = (~done) & ((x >= target) if up else (x <= target))
        hit[newly] = t
        done |= newly
        if done.all():
            break
    return float(np.mean(hit))


# ============================================================================
# Optimal OU entry/exit bands (Zeng-Lee 2014, spec B)
# ============================================================================

def optimal_ou_thresholds(
    kappa: float,
    sigma: float,
    cost: float,
    case: str = "symmetric",
    n_terms: int = 50,
) -> tuple:
    """Optimal OU entry/exit thresholds maximizing expected P&L per unit time.

    For the standardized OU (sigma_eq = sigma / sqrt(2*kappa)), expected passage
    times use the truncated series. Returns (a_star, b_star) in sigma_eq units.
    """
    from scipy.optimize import brentq
    from scipy.special import gamma as gammafn
    import math

    if case not in ("symmetric", "long_only"):
        raise ValueError("case must be 'symmetric' or 'long_only'")

    c = float(cost)
    sqrt2 = np.sqrt(2.0)

    def _series_sum(a_val):
        total = 0.0
        sa = sqrt2 * a_val
        for n in range(n_terms):
            m = 2 * n + 1
            term = sa ** m / (math.factorial(m) * gammafn(m / 2.0))
            total += term
            if abs(term) < 1e-15:
                break
        return total

    def _series_sum_deriv(a_val):
        total = 0.0
        sa = sqrt2 * a_val
        for n in range(n_terms):
            m = 2 * n
            term = sa ** m / (math.factorial(m) * gammafn((m + 1) / 2.0))
            total += term
            if abs(term) < 1e-15:
                break
        return sqrt2 * total

    if case == "long_only":
        def foc(a_val):
            S = _series_sum(a_val)
            Sp = _series_sum_deriv(a_val)
            return 0.5 * S - (a_val - c) * (sqrt2 / 2.0) * Sp

        try:
            a_star = brentq(foc, max(c + 0.01, 0.01), 20.0)
        except ValueError:
            a_star = max(c + 0.5, 1.0)
        return (float(a_star), 0.0)

    else:
        def foc(a_val):
            S = _series_sum(a_val)
            Sp = _series_sum_deriv(a_val)
            return 0.5 * S - (a_val - c / 2.0) * (sqrt2 / 2.0) * Sp

        try:
            a_star = brentq(foc, max(c / 2.0 + 0.01, 0.01), 20.0)
        except ValueError:
            a_star = max(c / 2.0 + 0.5, 1.0)
        return (float(a_star), float(-a_star))


# ============================================================================
# OU S-score (Avellaneda-Lee, spec D)
# ============================================================================

def ou_sscore(series: pd.Series, window: int = None, demean: bool = False) -> pd.Series:
    """Avellaneda-Lee S-score: s = (X - mu) / sigma_eq.

    sigma_eq = sigma / sqrt(2*kappa) is the equilibrium standard deviation.
    Full-sample if window is None; rolling if window is set.
    """
    y = pd.Series(series).dropna().astype(float)
    out = pd.Series(np.nan, index=y.index, dtype=float, name="sscore")

    if window is None:
        params = calibrate_ou(y, demean=demean)
        mu = params["mu"]
        kappa = params["kappa"]
        sigma = params["sigma"]
        if np.isfinite(kappa) and kappa > 0 and np.isfinite(sigma) and sigma > 0:
            sigma_eq = sigma / np.sqrt(2.0 * kappa)
            out = (y - mu) / sigma_eq
            out.name = "sscore"
        return out

    w = int(window)
    for t in range(w, len(y) + 1):
        chunk = y.iloc[t - w : t]
        params = calibrate_ou(chunk, demean=demean)
        mu = params["mu"]
        kappa = params["kappa"]
        sigma = params["sigma"]
        if np.isfinite(kappa) and kappa > 0 and np.isfinite(sigma) and sigma > 0:
            sigma_eq = sigma / np.sqrt(2.0 * kappa)
            out.iloc[t - 1] = (y.iloc[t - 1] - mu) / sigma_eq
    return out


# ============================================================================
# ADF gate (spec E)
# ============================================================================

def adf_gate(series: pd.Series, pval: float = 0.10, regression: str = "c") -> bool:
    """ADF stationarity gate: True if ADF p-value < pval (series is stationary)."""
    from statsmodels.tsa.stattools import adfuller

    y = pd.Series(series).dropna().astype(float)
    if len(y) < 10:
        return False
    try:
        result = adfuller(y.values, regression=regression, autolag="AIC")
        return bool(result[1] < pval)
    except Exception:
        return False
