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
