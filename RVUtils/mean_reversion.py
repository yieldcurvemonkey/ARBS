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

    if case not in ("symmetric", "long_only"):
        raise ValueError("case must be 'symmetric' or 'long_only'")

    c = float(cost)

    # Both cases share the same cycle time T(a) = E[tau(-a -> +a)] (the
    # long-only cycle 0 -> -a -> 0 telescopes to the same series) and differ
    # only in the profit per cycle: 2a - c symmetric, a - c long-only. So both
    # maximise (a - c_eff)/T(a).
    c_eff = c if case == "long_only" else c / 2.0

    def foc(a_val):
        return _passage_T(a_val, n_terms) - (a_val - c_eff) * _passage_Tp(a_val, n_terms)

    if c_eff <= 0.0:
        # With no cost the objective is maximised as the band width goes to
        # zero -- trade continuously. foc(a) < 0 for every a > 0, so brentq has
        # no root; the old fallback returned the constant 1.0 here, which sat
        # ABOVE the solved value at cost 0.01 (0.017) and broke monotonicity.
        a_star = 0.0
    else:
        lo, hi = max(c_eff * 1e-6, 1e-9), 12.0
        try:
            a_star = brentq(foc, lo, hi)
        except ValueError:
            a_star = max(c_eff, 1e-9)

    if case == "long_only":
        return (float(a_star), 0.0)
    return (float(a_star), float(-a_star))


def _passage_kmax(z: float, n_terms: Optional[int] = None) -> int:
    """Enough terms for the passage series at standardized level ``z``.

    ``term_k ~ exp(k*log(sqrt2*z) + lgamma(k/2) - lgamma(k+1))`` peaks near
    ``k = 2*z**2`` and only then decays superexponentially, so a fixed 50-term
    truncation silently under-sums for |z| beyond about 3.
    """
    if n_terms is not None:
        return int(n_terms)
    return int(min(340, max(80, 6.0 * (2.0 * z * z) + 60)))


def _passage_T(a: float, n_terms: Optional[int] = None) -> float:
    """``E[tau(-a -> +a)]`` for the standardized OU, in units of ``1/kappa``.

    ``T(a) = sum_{k odd} (sqrt2 a)^k * Gamma(k/2) / k!`` -- the even terms of the
    two-sided series cancel exactly. Summed in log space.
    """
    from scipy.special import gammaln

    if not np.isfinite(a) or a <= 0:
        return float("nan")
    la = np.log(np.sqrt(2.0) * a)
    kmax = _passage_kmax(a, n_terms)
    total = 0.0
    for k in range(1, kmax + 1, 2):
        total += np.exp(k * la + gammaln(k / 2.0) - gammaln(k + 1.0))
    return float(total)


def _passage_Tp(a: float, n_terms: Optional[int] = None) -> float:
    """``dT/da`` = ``sqrt2 * sum_{k odd} (sqrt2 a)^(k-1) Gamma(k/2)/(k-1)!``."""
    from scipy.special import gammaln

    if not np.isfinite(a) or a <= 0:
        return float("nan")
    la = np.log(np.sqrt(2.0) * a)
    kmax = _passage_kmax(a, n_terms)
    total = 0.0
    for k in range(1, kmax + 1, 2):
        total += np.exp((k - 1) * la + gammaln(k / 2.0) - gammaln(float(k)))
    return float(np.sqrt(2.0) * total)


def ou_band_levels(params: dict, cost: float, case: str = "symmetric",
                   n_terms: int = 50) -> dict:
    """:func:`optimal_ou_thresholds` in the series' own units.

    ``optimal_ou_thresholds`` works entirely in sigma_eq units and never reads
    ``kappa``/``sigma``; this wrapper is where they earn their place. ``cost`` is
    a round-trip cost in the units of the series (bp for a fly), converted to
    sigma_eq units before solving and converted back afterwards.

    Returns ``{sigma_eq, entry_z, exit_z, entry_level, exit_level,
    expected_hold, ret_per_period}`` -- the last two being what makes the band
    actionable: the expected time to traverse it and the expected profit per
    unit time at the optimum.
    """
    kappa = float(params.get("kappa", np.nan))
    sigma = float(params.get("sigma", np.nan))
    mu = float(params.get("mu", np.nan))
    nan = {"sigma_eq": np.nan, "entry_z": np.nan, "exit_z": np.nan,
           "entry_level": np.nan, "exit_level": np.nan,
           "expected_hold": np.nan, "ret_per_period": np.nan}
    if not (np.isfinite(kappa) and kappa > 0 and np.isfinite(sigma) and sigma > 0
            and np.isfinite(mu)):
        return nan
    sigma_eq = sigma / np.sqrt(2.0 * kappa)
    if not np.isfinite(sigma_eq) or sigma_eq <= 0:
        return nan
    c_z = float(cost) / sigma_eq
    a_z, b_z = optimal_ou_thresholds(kappa, sigma, c_z, case=case, n_terms=n_terms)
    return _band_report(mu, sigma_eq, a_z, b_z, kappa, float(cost))


def _band_report(mu: float, sigma_eq: float, a_z: float, b_z: float,
                 kappa: float, cost: float) -> dict:
    """Package a (entry, exit) band in sigma_eq units into level-unit output.

    ``expected_hold`` is entry -> exit; ``ret_per_period`` divides the net width
    by the full **cycle** time E[tau(-a -> +a)], which is what "per unit time"
    has to mean for a repeatable program (both the symmetric and the long-only
    cycles telescope to that same series).
    """
    if not np.isfinite(a_z) or a_z <= 0:
        return {"sigma_eq": float(sigma_eq), "entry_z": float(a_z), "exit_z": float(b_z),
                "entry_level": float(mu + a_z * sigma_eq) if np.isfinite(a_z) else np.nan,
                "exit_level": float(mu + b_z * sigma_eq) if np.isfinite(b_z) else np.nan,
                "expected_hold": np.nan, "ret_per_period": np.nan}
    hold = (expected_passage_time(-a_z, a_z, kappa=kappa) if b_z < 0
            else expected_passage_time(-a_z, 0.0, kappa=kappa))
    cycle = expected_passage_time(-a_z, a_z, kappa=kappa)
    width = (a_z - b_z) * sigma_eq
    ret = ((width - cost) / cycle) if (np.isfinite(cycle) and cycle > 0) else np.nan
    return {
        "sigma_eq": float(sigma_eq),
        "entry_z": float(a_z), "exit_z": float(b_z),
        "entry_level": float(mu + a_z * sigma_eq),
        "exit_level": float(mu + b_z * sigma_eq),
        "expected_hold": float(hold), "ret_per_period": float(ret),
    }


def expected_passage_time(a: float, m: float, *, kappa: float = 1.0,
                          n_terms: Optional[int] = None) -> float:
    """Expected first-passage time of a standardized OU from ``a`` up to ``m``.

    Bertram (2010): for ``dz = -z dt + sqrt(2) dW`` (unit stationary variance),

        E[tau] = 1/2 * sum_{k>=1} [ (sqrt2 m)^k - (sqrt2 a)^k ] / k! * Gamma(k/2)

    The Gamma is in the **numerator**. Verified by Monte Carlo on the
    standardized OU: E[tau(-1 -> +1)] measures 3.042 against 2.995 from this
    series (the residual is Euler overshoot at dt = 5e-4). The variant with
    Gamma in the denominator -- which the previously shipped
    ``optimal_ou_thresholds`` used -- gives 1.366 for the same passage.

    ``a`` and ``m`` are in sigma_eq units; the result is divided by ``kappa`` so
    it comes back in the series' own time units (business days when the OU was
    calibrated on daily data).
    """
    from scipy.special import gammaln

    if not np.isfinite(a) or not np.isfinite(m) or m <= a:
        return float("nan")
    sqrt2 = np.sqrt(2.0)
    kmax = _passage_kmax(max(abs(a), abs(m)), n_terms)
    total = 0.0
    for k in range(1, kmax + 1):
        lg = gammaln(k / 2.0) - gammaln(k + 1.0)
        term = 0.0
        for x, sgn in ((m, 1.0), (a, -1.0)):
            v = sqrt2 * x
            if v == 0.0:
                continue
            s = 1.0 if v > 0 else (1.0 if k % 2 == 0 else -1.0)
            term += sgn * s * np.exp(k * np.log(abs(v)) + lg)
        total += term
    tau = 0.5 * total
    if not np.isfinite(tau) or tau <= 0 or not (kappa > 0):
        return float("nan")
    return float(tau / kappa)


def bertram_thresholds(params: dict, cost: float, *, case: str = "symmetric",
                       n_terms: Optional[int] = None, grid: int = 400,
                       max_z: float = 5.0) -> dict:
    """Bertram-style optimal trading levels by direct maximisation.

    Maximises expected profit per unit time,
    ``mu(a) = (width(a) - cost) / E[T(a)]``, over the entry threshold on a grid
    rather than through the first-order condition, so the objective value is
    available and a degenerate optimum is visible instead of silently becoming
    a fallback constant. Same return shape as :func:`ou_band_levels`.
    """
    kappa = float(params.get("kappa", np.nan))
    sigma = float(params.get("sigma", np.nan))
    mu = float(params.get("mu", np.nan))
    nan = {"sigma_eq": np.nan, "entry_z": np.nan, "exit_z": np.nan,
           "entry_level": np.nan, "exit_level": np.nan,
           "expected_hold": np.nan, "ret_per_period": np.nan}
    if not (np.isfinite(kappa) and kappa > 0 and np.isfinite(sigma) and sigma > 0
            and np.isfinite(mu)):
        return nan
    sigma_eq = sigma / np.sqrt(2.0 * kappa)
    c_z = float(cost) / sigma_eq
    best = None
    for a_z in np.linspace(1e-3, float(max_z), int(grid)):
        cycle = expected_passage_time(-a_z, a_z, kappa=1.0, n_terms=n_terms)
        if not np.isfinite(cycle) or cycle <= 0:
            continue
        b_z = -a_z if case == "symmetric" else 0.0
        obj = ((a_z - b_z) - c_z) / cycle
        if best is None or obj > best[0]:
            best = (obj, a_z, b_z)
    if best is None:
        return nan
    _, a_z, b_z = best
    return _band_report(mu, sigma_eq, a_z, b_z, kappa, float(cost))


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


def adf_pvalue(series: pd.Series, regression: str = "c") -> float:
    """ADF p-value, NaN when it cannot be computed.

    The repo carried seven mutually incompatible ``adfuller`` call conventions
    (three without ``autolag``, two with a hand-set ``maxlag``), so p-values
    were not comparable across modules. This is the canonical call:
    ``autolag="AIC"``, no ``maxlag`` override.
    """
    from statsmodels.tsa.stattools import adfuller

    y = pd.Series(series).dropna().astype(float)
    if len(y) < 10:
        return float("nan")
    try:
        return float(adfuller(y.values, regression=regression, autolag="AIC")[1])
    except Exception:
        return float("nan")


# ============================================================================
# Canonical half-life / z-score
# ============================================================================

def half_life(series: pd.Series, *, dt: float = 1.0) -> float:
    """AR(1) half-life in periods; NaN when the series is not mean-reverting.

    The single definition. Eleven independent implementations existed across
    the repo with three different non-reverting sentinels (NaN, inf, 1.0) and
    two different regression forms; every one of them is this number.
    """
    return calibrate_ou(series, dt=dt)["half_life"]


def rolling_ar1(series: pd.Series, window: int, *, min_periods: Optional[int] = None,
                dt: float = 1.0) -> pd.DataFrame:
    """Rolling AR(1) fit by closed-form OLS on rolling sums.

    Returns a frame with ``phi``, ``intercept``, ``mu``, ``kappa``,
    ``half_life``, ``sigma`` and ``sigma_eq``, one row per input bar, using only
    data up to and including that bar.

    This is the vectorised replacement for looping ``calibrate_ou`` over every
    window, which is O(n*window) and was the dominant cost of any per-fly
    rolling fit. Measured on 2,074 bars x 26 keys at window 120:
    **0.091s here vs 5.66s for the loop, a 62x speedup**
    (``notebooks/rv/_profile_meanrev.py``).
    """
    y = pd.Series(series).astype(float)
    w = int(window)
    mp = int(min_periods) if min_periods is not None else w
    x = y.shift(1)
    ok = x.notna() & y.notna()
    xv = x.where(ok)
    yv = y.where(ok)
    one = ok.astype(float)

    r = lambda s: s.rolling(w, min_periods=mp)          # noqa: E731
    n = r(one).sum()
    sx = r(xv.fillna(0.0)).sum()
    sy = r(yv.fillna(0.0)).sum()
    sxx = r((xv * xv).fillna(0.0)).sum()
    sxy = r((xv * yv).fillna(0.0)).sum()
    syy = r((yv * yv).fillna(0.0)).sum()

    den = n * sxx - sx * sx
    den = den.where(den.abs() > 1e-12)
    phi = (n * sxy - sx * sy) / den
    alpha = (sy - phi * sx) / n

    # residual variance from the same sufficient statistics
    sse = syy - 2 * alpha * sy - 2 * phi * sxy + n * alpha**2 + 2 * alpha * phi * sx + phi**2 * sxx
    # ddof=1 on the residuals, matching calibrate_ou exactly (it uses
    # np.var(eps, ddof=1)). n-2 is the textbook choice for a two-parameter fit,
    # but the point of this function is to BE calibrate_ou, vectorised.
    dof = (n - 1).where(n > 2)
    s2 = (sse / dof).clip(lower=0.0)

    # min_periods must count usable PAIRS, not raw bars: the first bar of the
    # window has no predecessor, so a naive rolling(w) fit at bar w-1 quietly
    # uses w-1 pairs and disagrees with calibrate_ou on the same slice.
    enough = n >= float(mp)
    phi = phi.where(enough)
    alpha = alpha.where(enough)
    s2 = s2.where(enough)

    valid = phi.notna() & (phi > 0) & (phi < 1)
    kappa = (-np.log(phi.where(valid))) / float(dt)
    mu = alpha / (1.0 - phi.where(valid))
    sigma = np.sqrt((s2 * (2.0 * kappa) / (1.0 - phi.where(valid) ** 2)).clip(lower=0.0))
    hl = np.log(2.0) / kappa
    sigma_eq = sigma / np.sqrt(2.0 * kappa)
    return pd.DataFrame({
        "phi": phi, "intercept": alpha, "mu": mu, "kappa": kappa,
        "half_life": hl, "sigma": sigma, "sigma_eq": sigma_eq,
        "n_obs": n,
    }, index=y.index)


def rolling_half_life(series: pd.Series, window: int = 120, *,
                      min_periods: Optional[int] = None, dt: float = 1.0) -> pd.Series:
    """Rolling AR(1) half-life, NaN where the window is not mean-reverting."""
    out = rolling_ar1(series, window, min_periods=min_periods, dt=dt)["half_life"]
    out.name = "half_life"
    return out


def rolling_zscore(series: pd.Series, window: int, *,
                   min_periods: Optional[int] = None, ddof: int = 0,
                   exclude_current: bool = False) -> pd.Series:
    """Canonical trailing z-score.

    ``exclude_current=True`` computes the mean and standard deviation on the
    window ending at ``t-1``, so the statistic a signal is compared against does
    not contain the observation being judged. That self-inclusion shrinks |z| by
    roughly 1/window and is not look-ahead, but it is an ablation worth having;
    the default reproduces the repo's existing behaviour.
    """
    s = pd.Series(series).astype(float)
    w = int(window)
    mp = int(min_periods) if min_periods is not None else w
    base = s.shift(1) if exclude_current else s
    r = base.rolling(w, min_periods=mp)
    mu = r.mean()
    sd = r.std(ddof=ddof)
    return (s - mu) / sd.where(sd > 1e-12)


# ============================================================================
# Long-memory / random-walk diagnostics
# ============================================================================

def hurst_exponent(series: pd.Series, *, max_lag: int = 100, min_lag: int = 2,
                   method: str = "std") -> float:
    """Hurst exponent. H < 0.5 mean-reverting, 0.5 random walk, > 0.5 trending.

    ``method="std"`` regresses ``log std(x_{t+l} - x_t)`` on ``log l``; the
    slope **is** H. (The prior implementation in ``plt_timeseries`` returned
    ``2 * slope`` and measured H = 1.035 on a pure random walk.)

    ``method="rs"`` is the rescaled-range estimator, which is defined on the
    **increments** and is applied to ``diff(series)`` internally, so both
    methods take the level series as input and agree on a random walk.

    One property worth knowing before using this as a regime filter: under
    ``std`` a *deterministic* drift cancels in ``x_{t+l} - x_t``, so a series
    that is a straight line plus small noise reads H ~ 0, not H ~ 1. The
    estimator sees stochastic persistence, not visible trend.
    """
    y = pd.Series(series).dropna().astype(float).to_numpy()
    n = y.size
    if n < 20:
        return float("nan")
    hi = int(min(max_lag, n // 2))
    if hi <= min_lag:
        return float("nan")
    lags = np.arange(int(min_lag), hi + 1)

    if method == "std":
        tau = np.array([np.std(y[l:] - y[:-l], ddof=0) for l in lags], dtype=float)
    elif method == "rs":
        x = np.diff(y)
        m = x.size
        tau = []
        for l in lags:
            k = m // l
            if k < 1:
                tau.append(np.nan)
                continue
            rs = []
            for j in range(k):
                seg = x[j * l:(j + 1) * l]
                z = np.cumsum(seg - seg.mean())
                s = seg.std(ddof=0)
                if s > 0:
                    rs.append((z.max() - z.min()) / s)
            tau.append(np.mean(rs) if rs else np.nan)
        tau = np.asarray(tau, dtype=float)
    else:
        raise ValueError("method must be 'std' or 'rs'")

    ok = np.isfinite(tau) & (tau > 0)
    if ok.sum() < 3:
        return float("nan")
    slope = np.polyfit(np.log(lags[ok]), np.log(tau[ok]), 1)[0]
    return float(slope)


def rolling_hurst(series: pd.Series, window: int = 252, *, max_lag: int = 20,
                  method: str = "std", step: int = 1) -> pd.Series:
    """Trailing Hurst exponent (``step`` > 1 computes every k-th bar and ffills)."""
    y = pd.Series(series).astype(float)
    out = pd.Series(np.nan, index=y.index, dtype=float, name="hurst")
    w = int(window)
    for i in range(w - 1, len(y), int(step)):
        out.iloc[i] = hurst_exponent(y.iloc[i - w + 1:i + 1], max_lag=max_lag,
                                     method=method)
    return out.ffill() if step > 1 else out


def variance_ratio(series: pd.Series, k: int = 5, *, on_changes: bool = True) -> float:
    """Lo-MacKinlay variance ratio ``Var(k-period)/(k * Var(1-period))``.

    VR < 1 is mean reversion, VR = 1 a random walk, VR > 1 trending. Overlapping
    k-period sums with the standard unbiased corrections. ``on_changes`` is the
    right default for a spread/fly level series (a log return makes no sense for
    something that crosses zero).
    """
    y = pd.Series(series).dropna().astype(float).to_numpy()
    x = np.diff(y) if on_changes else y
    n, q = x.size, int(k)
    if q < 2 or n < 2 * q:
        return float("nan")
    mu = x.mean()
    var1 = np.sum((x - mu) ** 2) / (n - 1)
    if var1 <= 0:
        return float("nan")
    xq = np.convolve(x, np.ones(q), mode="valid")           # overlapping sums
    # The Lo-MacKinlay denominator m = q(n-q+1)(1-q/n) already carries the
    # factor q, so varq is a PER-PERIOD variance and the ratio must not divide
    # by q a second time.
    m = q * (n - q + 1) * (1.0 - q / n)
    varq = np.sum((xq - q * mu) ** 2) / m
    return float(varq / var1)


def variance_ratio_stat(series: pd.Series, k: int = 5, *,
                        heteroskedastic: bool = True) -> dict:
    """Variance ratio with the Lo-MacKinlay z-statistic and two-sided p-value.

    ``heteroskedastic=True`` uses the robust variance so a conditionally
    heteroskedastic random walk is not rejected as mean-reverting -- which
    matters here because SR3 fly vol changes by an order of magnitude between
    ZIRP and the hiking cycle.
    """
    from scipy.stats import norm

    y = pd.Series(series).dropna().astype(float).to_numpy()
    x = np.diff(y)
    n, q = x.size, int(k)
    nan = {"vr": np.nan, "z": np.nan, "pvalue": np.nan, "n": int(n)}
    if q < 2 or n < 2 * q:
        return nan
    vr = variance_ratio(pd.Series(y), q)
    if not np.isfinite(vr):
        return nan
    mu = x.mean()
    e = x - mu
    if not heteroskedastic:
        v = 2.0 * (2.0 * q - 1.0) * (q - 1.0) / (3.0 * q * n)
    else:
        d0 = float(np.sum(e ** 2))
        v = 0.0
        for j in range(1, q):
            num = float(np.sum((e[j:] ** 2) * (e[:-j] ** 2)))
            dj = num * n / (d0 ** 2) if d0 > 0 else np.nan
            v += ((2.0 * (q - j) / q) ** 2) * dj
        v = v / n
    if not np.isfinite(v) or v <= 0:
        return nan
    z = (vr - 1.0) / np.sqrt(v)
    return {"vr": float(vr), "z": float(z),
            "pvalue": float(2.0 * (1.0 - norm.cdf(abs(z)))), "n": int(n)}


# ============================================================================
# Exact OU MLE
# ============================================================================

def ou_mle(series: pd.Series, *, dt: float = 1.0) -> dict:
    """Exact maximum-likelihood OU calibration (sufficient-statistic form).

    ``calibrate_ou`` fits the AR(1) analogue by OLS; this is the closed-form MLE
    of the same process. Same return keys, so the two are drop-in comparable and
    the fit method becomes a sweepable axis rather than an assumption. (The
    formula was previously reachable only as a closure inside
    ``simulate_mean_reversion_ou``.)
    """
    y = pd.Series(series).dropna().astype(float).to_numpy()
    nan = {"mu": np.nan, "kappa": np.nan, "sigma": np.nan, "phi": np.nan,
           "intercept": np.nan, "half_life": np.nan}
    n = y.size - 1
    if n < 4:
        return nan
    sx, sy = y[:-1].sum(), y[1:].sum()
    sxx = float(y[:-1] @ y[:-1])
    sxy = float(y[:-1] @ y[1:])
    syy = float(y[1:] @ y[1:])
    den = n * (sxx - sxy) - (sx ** 2 - sx * sy)
    if abs(den) < 1e-12:
        return nan
    mu = (sy * sxx - sx * sxy) / den
    ratio = (sxy - mu * sx - mu * sy + n * mu ** 2) / (sxx - 2 * mu * sx + n * mu ** 2)
    if not (0.0 < ratio < 1.0):
        return {**nan, "mu": float(mu)}
    kappa = -np.log(ratio) / float(dt)
    alpha = ratio
    s_tilde = (1.0 / n) * (syy - 2 * alpha * sxy + sxx * alpha ** 2
                           - 2 * mu * (1 - alpha) * (sy - alpha * sx)
                           + n * mu ** 2 * (1 - alpha) ** 2)
    s2 = s_tilde * 2 * kappa / (1 - alpha ** 2)
    return {"mu": float(mu), "kappa": float(kappa),
            "sigma": float(np.sqrt(max(0.0, s2))), "phi": float(alpha),
            "intercept": float(mu * (1 - alpha)),
            "half_life": float(np.log(2.0) / kappa)}


# ============================================================================
# Kalman filters (first-party; no new dependencies)
# ============================================================================

def kalman_local_level(series: pd.Series, *, q: float = 1e-4, r: float = 1.0,
                       p0: Optional[float] = None) -> pd.DataFrame:
    """Local-level (random walk + noise) Kalman filter -- a dynamic fair value.

    State ``m_t = m_{t-1} + w_t`` (Var ``q``), observation ``y_t = m_t + v_t``
    (Var ``r``). Returns ``prior`` (the one-step-ahead fair value, which uses
    only information through ``t-1``), ``filtered``, ``pred_var``,
    ``innovation`` and ``z`` = innovation / sqrt(pred_var).

    ``z`` is the tradeable signal: it is the deviation of today's print from a
    fair value formed **before** seeing it, so it carries no same-bar
    self-inclusion. ``q/r`` is the only knob -- larger means a faster-adapting
    fair value and a shorter memory.
    """
    y = pd.Series(series).astype(float)
    vals = y.to_numpy()
    n = vals.size
    prior = np.full(n, np.nan)
    filt = np.full(n, np.nan)
    pvar = np.full(n, np.nan)
    innov = np.full(n, np.nan)
    m, p = np.nan, float(p0 if p0 is not None else max(r, 1.0) * 10.0)
    for i in range(n):
        yi = vals[i]
        if not np.isfinite(m):
            if np.isfinite(yi):
                m = yi
            continue
        m_pred = m
        p_pred = p + q
        prior[i] = m_pred
        pvar[i] = p_pred + r
        if not np.isfinite(yi):
            m, p = m_pred, p_pred
            continue
        e = yi - m_pred
        innov[i] = e
        k = p_pred / (p_pred + r)
        m = m_pred + k * e
        p = (1.0 - k) * p_pred
        filt[i] = m
    out = pd.DataFrame({"prior": prior, "filtered": filt, "pred_var": pvar,
                        "innovation": innov}, index=y.index)
    out["z"] = out["innovation"] / np.sqrt(out["pred_var"].where(out["pred_var"] > 0))
    return out


def kalman_hedge_ratio(y: pd.Series, X: pd.DataFrame, *, delta: float = 1e-4,
                       r: float = 1e-3, add_constant: bool = True) -> pd.DataFrame:
    """Time-varying regression coefficients by Kalman filter (Chan's formulation).

    State = the regression coefficients, evolving as a random walk with
    covariance ``delta/(1-delta) * I``; observation ``y_t = x_t' beta_t + v_t``
    with variance ``r``. Returns one column per regressor (prefixed ``beta_``),
    plus ``pred``, ``resid`` (= innovation) and ``z`` (innovation standardised
    by its own predicted variance).

    For a butterfly this fits the belly on its two wings and lets the hedge
    ratios drift, which is the honest alternative to asserting 1/-2/1 -- and
    ``z`` is again a pre-observation residual, so it is safe to trade on.
    """
    Xd = pd.DataFrame(X).astype(float).copy()
    if add_constant:
        Xd.insert(0, "const", 1.0)
    yv = pd.Series(y).astype(float).reindex(Xd.index)
    cols = list(Xd.columns)
    k = len(cols)
    vw = float(delta) / (1.0 - float(delta))
    beta = np.zeros(k)
    P = np.eye(k) * 1.0
    Vw = np.eye(k) * vw
    n = len(Xd)
    betas = np.full((n, k), np.nan)
    pred = np.full(n, np.nan)
    resid = np.full(n, np.nan)
    qv = np.full(n, np.nan)
    Xa = Xd.to_numpy()
    ya = yv.to_numpy()
    for i in range(n):
        x = Xa[i]
        if not np.isfinite(x).all() or not np.isfinite(ya[i]):
            continue
        R = P + Vw
        yhat = float(x @ beta)
        Q = float(x @ R @ x) + float(r)
        e = float(ya[i] - yhat)
        pred[i], resid[i], qv[i] = yhat, e, Q
        Kg = (R @ x) / Q
        beta = beta + Kg * e
        P = R - np.outer(Kg, x @ R)
        betas[i] = beta
    out = pd.DataFrame(betas, index=Xd.index,
                       columns=[f"beta_{c}" for c in cols])
    out["pred"] = pred
    out["resid"] = resid
    out["pred_var"] = qv
    out["z"] = out["resid"] / np.sqrt(out["pred_var"].where(out["pred_var"] > 0))
    return out
