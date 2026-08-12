"""Probabilistic and Deflated Sharpe ratios (Bailey & López de Prado).

The Sharpe of the best configuration in a parameter sweep is not evidence of skill: search N
configurations over a short sample and the *maximum* observed Sharpe is large even when every one
of them has zero true edge. The Deflated Sharpe asks the only useful question -- is this Sharpe
larger than the largest one the search would have produced by chance?

THE FORMULAE, EXACTLY AS IMPLEMENTED
------------------------------------
Everything below is from Bailey & López de Prado, *The Deflated Sharpe Ratio: Correcting for
Selection Bias, Backtest Overfitting and Non-Normality*, Journal of Portfolio Management (2014),
https://www.davidhbailey.com/dhbpapers/deflated-sharpe.pdf -- equation numbers are the paper's.

**Probabilistic Sharpe Ratio** -- the probability that the true Sharpe exceeds a benchmark ``SR*``,
given the observed Sharpe and the higher moments of the return series (paper Eq. 2 with a general
threshold; originally Bailey & López de Prado 2012a)::

                     ⎡        (SR̂ − SR*)·√(T − 1)        ⎤
    PSR(SR*) = Z ⎢ ────────────────────────────────── ⎥
                     ⎣ √(1 − γ₃·SR̂ + ((γ₄ − 1)/4)·SR̂²) ⎦

``Z`` is the standard normal CDF, ``T`` the number of observations, ``γ₃`` the skew and ``γ₄`` the
**non-excess** kurtosis (3.0 for a normal, not 0.0). The denominator is ``√(T−1)·σ̂(SR̂)``, Lo's
(2002) asymptotic standard error of the Sharpe estimator. Negative skew and fat tails inflate it,
which is the economic point: a Sharpe earned by selling tails is worth less than the same number
earned symmetrically.

**Expected maximum Sharpe under the null** -- the bar the winner of a search must clear
(paper Eq. 1, proved in A.1 Eq. 5-6)::

    E[max{SR̂ₙ}] ≈ E[{SR̂ₙ}] + √V[{SR̂ₙ}] · [ (1 − γ)·Z⁻¹(1 − 1/N) + γ·Z⁻¹(1 − 1/(N·e)) ]

``γ ≈ 0.5772`` is Euler-Mascheroni, ``e`` Euler's number, ``V[{SR̂ₙ}]`` the variance of the Sharpes
*across the trials*, and ``N`` the number of **independent** trials. The approximation is derived
for ``N ≫ 1``; see :func:`expected_max_sharpe` for what happens at small ``N``.

**Deflated Sharpe Ratio** -- PSR evaluated at that bar (paper Eq. 2)::

    DSR ≡ PSR(SR₀),    SR₀ = √V[{SR̂ₙ}] · [ (1 − γ)·Z⁻¹(1 − 1/N) + γ·Z⁻¹(1 − 1/(N·e)) ]

Note ``SR₀`` drops the ``E[{SR̂ₙ}]`` term of Eq. 1. That is not an omission -- it is the null
hypothesis. DSR tests ``H₀: true SR = 0``, under which the trials' mean Sharpe is zero. Pass
``mean_sharpe=`` to :func:`expected_max_sharpe` if you want the Eq. 1 form for its own sake, but
understand that feeding the *observed* trial mean into a DSR turns it into a "better than my own
peers" test, which is a different and much weaker claim.

CONFIGS TRIED IS NOT TRIALS RUN
-------------------------------
``N`` above is the number of *independent* trials. A grid of 400 configurations differing by one
knob is nowhere near 400 independent experiments -- neighbouring settings hold nearly the same
positions and their P&L series are highly correlated. Using the raw count overstates ``SR₀`` and so
understates the DSR. :func:`effective_trials` estimates ``N`` from the correlation between the
trials' own return series, by one of several methods; read its docstring before choosing, because
the paper's own method is measurably wrong by up to an order of magnitude.

UNITS -- THE MOST COMMON WAY TO GET A CONFIDENT WRONG ANSWER
------------------------------------------------------------
``SR̂``, ``SR*``, ``V[{SR̂ₙ}]`` and ``T`` must all be on the **same per-observation** frequency.
Annualising one and not another silently rescales the whole test. A daily backtest reporting an
annualised Sharpe of 2.0 has a per-period Sharpe of ``2.0/√252 ≈ 0.126``, and its cross-trial
*variance* rescales by ``1/252``, not by ``1/√252``. Pass ``periods_per_year=`` to the grid helpers
and they will do both conversions for you; every function without that argument assumes you have
already converted. :func:`annualised_to_per_period` is the explicit converter.

Verified against the paper's own worked example (p.9-10): ``N=100``, ``V[{SR̂ₙ}]=1/2`` annualised,
``T=1250``, ``γ₃=−3``, ``γ₄=10``, annualised ``SR̂=2.5`` over 250 obs/yr gives ``SR₀ = 0.1132`` and
``DSR = 0.9004``; ``N=46`` gives ``DSR = 0.9505``; and with normal moments ``N=88`` gives
``DSR = 0.9505``. All three are reproduced to four decimals in
``tests/statistical_finance/test_deflated_sharpe.py``.
"""

from __future__ import annotations

import logging
import math
from typing import Iterable, Optional, Sequence

import numpy as np
from scipy import stats

logger = logging.getLogger(__name__)

__all__ = [
    "EULER_MASCHERONI", "MIN_OBS", "sharpe_moments", "probabilistic_sharpe_ratio",
    "sharpe_std_error", "expected_max_sharpe", "deflated_sharpe_ratio", "effective_trials",
    "effective_trials_from_corr", "deflated_sharpe_of_best", "deflated_sharpe_from_sharpes",
    "min_track_record_length", "annualised_to_per_period",
]

EULER_MASCHERONI = 0.5772156649015329

#: Below this many observations the higher moments are too noisy for the correction to mean
#: anything, and the formula returns NaN rather than a number that looks usable.
MIN_OBS = 20

#: Eq. 5 is increasing in N throughout (both inverse-CDF arguments rise with N) but is NEGATIVE
#: below roughly N = 1.28, where it would express "the best of 1.1 trials scores below the mean".
#: Used as the left edge when inverting the relation, and as the reason for the floor in
#: :func:`expected_max_sharpe`.
_N_MONOTONE_FLOOR = 1.35

_EFFECTIVE_N_METHODS = ("bailey", "evt_mc", "equicorrelation", "participation", "independent")


# --------------------------------------------------------------------------- moments
def sharpe_moments(returns: Sequence[float]) -> dict:
    """Per-period Sharpe plus the skew and NON-excess kurtosis the PSR needs.

    The Sharpe uses the unbiased standard deviation (``ddof=1``); the third and fourth moments are
    the plain plug-in (biased, "population") estimators, which is what the Lo/Bailey derivation is
    written in and what ``scipy.stats.skew``/``kurtosis`` return by default.

    Beware: ``pandas.Series.skew()`` and ``.kurt()`` are bias-CORRECTED and return *excess*
    kurtosis. Feeding those into :func:`probabilistic_sharpe_ratio` gives a different -- wrong --
    answer. Use this function, or ``scipy.stats.kurtosis(x, fisher=False)``.
    """
    r = np.asarray(list(returns), dtype=float)
    r = r[np.isfinite(r)]
    n = len(r)
    if n < 3:
        return {"n": n, "sharpe": np.nan, "skew": np.nan, "kurtosis": np.nan}
    sd = r.std(ddof=1)
    if sd == 0:
        return {"n": n, "sharpe": np.nan, "skew": np.nan, "kurtosis": np.nan}
    z = (r - r.mean()) / sd
    return {
        "n": n,
        "sharpe": float(r.mean() / sd),
        "skew": float((z ** 3).mean()),
        "kurtosis": float((z ** 4).mean()),   # non-excess: 3.0 for a normal sample
    }


def annualised_to_per_period(sharpe: float, periods_per_year: float) -> float:
    """Convert an annualised Sharpe to the per-observation Sharpe the formulae require.

    Sharpes scale with ``√periods``; their VARIANCE across trials therefore scales with ``periods``.
    That asymmetry is why this is a named function rather than an inline division.
    """
    return float(sharpe) / math.sqrt(float(periods_per_year))


# ------------------------------------------------------------------------------- PSR
def _variance_term(sharpe: float, skew: float, kurtosis: float) -> float:
    """``1 − γ₃·SR̂ + ((γ₄−1)/4)·SR̂²`` -- the squared, ``(T−1)``-scaled standard error of SR̂.

    For any genuine distribution this is non-negative: Pearson's inequality gives
    ``γ₄ ≥ γ₃² + 1``, and at that boundary the expression collapses to the perfect square
    ``(1 − γ₃·SR̂/2)²``. It can only go negative when the supplied moments are mutually
    inconsistent -- a sample too short to estimate them, or excess kurtosis passed where non-excess
    was wanted. That is worth surfacing rather than papering over, so callers get NaN.
    """
    return 1.0 - skew * sharpe + ((kurtosis - 1.0) / 4.0) * sharpe ** 2


def probabilistic_sharpe_ratio(
    returns_or_sharpe,
    *,
    n_obs: Optional[int] = None,
    skew: Optional[float] = None,
    kurtosis: Optional[float] = None,
    benchmark: float = 0.0,
) -> float:
    """P(true Sharpe > ``benchmark``). All Sharpes per-period.

    The first argument is either a scalar Sharpe -- in which case ``n_obs`` is required and
    ``skew``/``kurtosis`` default to the normal values (0.0, 3.0) -- or an array of returns, from
    which all four are estimated by :func:`sharpe_moments`.

    Returns NaN rather than a number when the sample is shorter than :data:`MIN_OBS` (the moment
    correction is meaningless there), or when the variance term is non-positive, which signals
    mutually inconsistent moments rather than a small probability.
    """
    if np.ndim(returns_or_sharpe) > 0:
        m = sharpe_moments(returns_or_sharpe)
        sharpe = m["sharpe"]
        n_obs = m["n"] if n_obs is None else n_obs
        skew = m["skew"] if skew is None else skew
        kurtosis = m["kurtosis"] if kurtosis is None else kurtosis
    else:
        sharpe = float(returns_or_sharpe)
    skew = 0.0 if skew is None else float(skew)
    kurtosis = 3.0 if kurtosis is None else float(kurtosis)

    if not np.isfinite(sharpe) or n_obs is None or n_obs < MIN_OBS:
        return float("nan")
    if not np.isfinite(benchmark):
        return float("nan")
    var_term = _variance_term(sharpe, skew, kurtosis)
    if not np.isfinite(var_term) or var_term <= 0:
        logger.debug("PSR variance term non-positive (%.4g) -- moments are mutually inconsistent "
                     "(Pearson requires kurtosis >= skew^2 + 1); returning NaN", var_term)
        return float("nan")
    zscore = (sharpe - benchmark) * math.sqrt(n_obs - 1) / math.sqrt(var_term)
    return float(stats.norm.cdf(zscore))


def sharpe_std_error(sharpe: float, *, n_obs: int, skew: float = 0.0,
                     kurtosis: float = 3.0) -> float:
    """Lo (2002) asymptotic standard error of the Sharpe estimator, ``σ̂(SR̂)``.

        σ̂(SR̂) = √( (1 − γ₃·SR̂ + ((γ₄−1)/4)·SR̂²) / (T − 1) )

    Useful on its own: it is what tells you a Sharpe of 0.9 over 332 daily observations has a
    standard error around 0.055 per period, so the confidence interval on the annualised number is
    roughly ±1.7.
    """
    if n_obs is None or n_obs < 2 or not np.isfinite(sharpe):
        return float("nan")
    var_term = _variance_term(sharpe, skew, kurtosis)
    if not np.isfinite(var_term) or var_term <= 0:
        return float("nan")
    return float(math.sqrt(var_term / (n_obs - 1)))


def min_track_record_length(sharpe: float, *, skew: float = 0.0, kurtosis: float = 3.0,
                            benchmark: float = 0.0, confidence: float = 0.95) -> float:
    """Observations needed before ``SR̂`` beats ``benchmark`` at ``confidence`` (Bailey & LdP 2012a).

        MinTRL = 1 + [1 − γ₃·SR̂ + ((γ₄−1)/4)·SR̂²] · (Z⁻¹(α) / (SR̂ − SR*))²

    Returns ``inf`` when ``SR̂ ≤ SR*``: no amount of data makes a losing strategy significant. This
    is the question to ask *before* running a grid search -- if MinTRL exceeds the sample you have,
    the search cannot produce a defensible answer no matter what it finds.
    """
    if not np.isfinite(sharpe) or sharpe <= benchmark:
        return float("inf")
    var_term = _variance_term(sharpe, skew, kurtosis)
    if not np.isfinite(var_term) or var_term <= 0:
        return float("nan")
    z = stats.norm.ppf(confidence)
    return float(1.0 + var_term * (z / (sharpe - benchmark)) ** 2)


# ------------------------------------------------------------------------- SR0 / trials
def _emax_z(n_trials):
    """The bracketed standardised term of Eq. 5, for scalar or array ``n_trials``."""
    n = np.asarray(n_trials, dtype=float)
    with np.errstate(divide="ignore", invalid="ignore"):
        a = stats.norm.ppf(1.0 - 1.0 / n)
        b = stats.norm.ppf(1.0 - 1.0 / (n * math.e))
    return (1.0 - EULER_MASCHERONI) * a + EULER_MASCHERONI * b


def expected_max_sharpe(n_trials: float, var_sharpe: float, *,
                        mean_sharpe: float = 0.0) -> float:
    """``SR₀`` -- the Sharpe the best of ``n_trials`` zero-skill strategies is expected to show.

    This is the benchmark the observed Sharpe has to beat. It grows with the number of trials and
    with how much the trials' Sharpes scatter, which is why a wide, noisy search is *harder* to
    draw a conclusion from, not easier.

    ``mean_sharpe`` defaults to 0 because DSR tests ``H₀: true SR = 0`` -- see the module docstring
    before changing it.

    Two guards the published formula needs and does not state. Eq. 5 is derived for ``N ≫ 1`` and
    misbehaves below about ``N = 1.35``: at ``N = 1.1`` it returns ``−0.064·√V``, a *negative* bar,
    which would make the deflated ratio LARGER than the undeflated one and run the whole correction
    backwards. The result is therefore floored at ``mean_sharpe`` -- the expected maximum of one or
    more draws can never sit below the distribution's own mean. ``n_trials`` is also accepted as a
    float, because an effective-trial count is not an integer and rounding one down to 1 silently
    sets ``SR₀`` to exactly zero, removing the deflation entirely.

    Accuracy: against simulation the approximation is ~8% low at ``N=2``, within ~1% by ``N=3``, and
    the paper's own Exhibit 3.1 puts the error under 0.05·√V for ``N<50`` and 0.006·√V by ``N=1000``.
    """
    if n_trials is None or not np.isfinite(n_trials) or n_trials < 1:
        return float("nan")
    if not np.isfinite(var_sharpe) or var_sharpe < 0:
        return float("nan")
    if n_trials == 1 or var_sharpe == 0:
        return float(mean_sharpe)
    raw = float(mean_sharpe) + math.sqrt(var_sharpe) * float(_emax_z(n_trials))
    return float(max(raw, float(mean_sharpe)))


def _average_off_diagonal(corr: np.ndarray) -> float:
    m = corr.shape[0]
    off = corr[~np.eye(m, dtype=bool)]
    off = off[np.isfinite(off)]
    if not len(off):
        return 0.0
    return float(np.clip(off.mean(), 0.0, 1.0))


def _invert_expected_max(target: float, m_trials: int) -> float:
    """Smallest ``N`` whose Eq. 5 standardised maximum equals ``target``. Clipped to ``[1, M]``."""
    if not np.isfinite(target):
        return float(m_trials)
    grid = np.geomspace(_N_MONOTONE_FLOOR, max(float(m_trials), _N_MONOTONE_FLOOR * 1.01), 4096)
    f = _emax_z(grid)                      # strictly increasing on this range
    if target <= f[0]:
        return 1.0
    if target >= f[-1]:
        return float(m_trials)
    return float(np.clip(np.interp(target, f, grid), 1.0, float(m_trials)))


def effective_trials_from_corr(corr: np.ndarray, *, method: str = "bailey",
                               draws: int = 20_000,
                               rng: Optional[np.random.Generator] = None) -> float:
    """Independent-trial count implied by a correlation matrix of the trials' returns.

    ``method`` selects how the reduction from ``M`` correlated trials to ``N`` independent ones is
    made. They do NOT agree, and the disagreement is large enough to change a verdict:

    ``"bailey"`` (default)
        The paper's Eq. 9, ``N̄ = ρ̄ + (1 − ρ̄)·M`` -- a straight-line interpolation between the two
        endpoints it must satisfy (``ρ̄=0 → M``, ``ρ̄=1 → 1``). The paper offers no derivation and
        calls it "intuitive and convenient"; measured against simulation it OVER-counts badly, by
        roughly 10x at ``M=300, ρ̄=0.8`` (true 5.9, Eq. 9 says 60.8). Over-counting raises ``SR₀``
        and so makes the test HARSHER, which is the safe direction for a tool whose job is to stop
        you fooling yourself. It is the default for that reason and for fidelity to the reference.

    ``"evt_mc"``
        Simulate the maximum of a mean-zero, unit-variance Gaussian vector with this exact
        correlation matrix, then invert Eq. 5 for the ``N`` that reproduces the simulated
        ``E[max]``. Makes no equicorrelation assumption and is accurate by construction; this is
        the method to use when the honest number matters more than matching the paper. Stochastic:
        pass ``rng`` for reproducibility.

    ``"equicorrelation"``
        ``M^(1−ρ̄)``, the closed-form extreme-value result. If ``xᵢ = √ρ̄·Z + √(1−ρ̄)·εᵢ`` then
        ``E[max xᵢ] = √(1−ρ̄)·E[max εᵢ] ≈ √(1−ρ̄)·√(2·ln M)``, and equating that to ``√(2·ln N)``
        gives ``N = M^(1−ρ̄)``. Derived rather than interpolated, but assumes every pair shares one
        average correlation, and it under-counts relative to ``evt_mc``.

    ``"participation"``
        ``(Σλ)² / Σλ²`` over the eigenvalues -- the participation ratio, an effective rank. Correct
        at both endpoints and cheap, but it measures dimensionality, not the behaviour of a maximum,
        and under-counts the most of the four.

    ``"independent"``
        ``M``. No adjustment; the most conservative choice and the right one when you have no
        correlation information at all.

    The paper's own caveat applies to every correlation-based method here: when ``M`` is large
    relative to the sample length ``T`` the correlation matrix is ill-conditioned and its average is
    itself an overfit. A warning is logged when that bites.
    """
    if method not in _EFFECTIVE_N_METHODS:
        raise ValueError(f"method must be one of {_EFFECTIVE_N_METHODS}, got {method!r}")
    corr = np.asarray(corr, dtype=float)
    m = corr.shape[0]
    if m <= 1:
        return float(max(m, 1))
    if method == "independent":
        return float(m)

    rho = _average_off_diagonal(corr)
    if method == "bailey":
        return float(np.clip(rho + (1.0 - rho) * m, 1.0, float(m)))
    if method == "equicorrelation":
        return float(np.clip(m ** (1.0 - rho), 1.0, float(m)))

    # Both remaining methods need the spectrum. Project to the nearest PSD matrix first: with
    # M > T the sample correlation is rank-deficient and eigenvalues come back slightly negative.
    eigvals, eigvecs = np.linalg.eigh(corr)
    eigvals = np.clip(eigvals, 0.0, None)

    if method == "participation":
        total = eigvals.sum()
        sq = (eigvals ** 2).sum()
        if sq <= 0:
            return float(m)
        return float(np.clip(total ** 2 / sq, 1.0, float(m)))

    # method == "evt_mc"
    rng = rng or np.random.default_rng()
    load = eigvecs * np.sqrt(eigvals)                      # M x M, corr ≈ load @ load.T
    scale = np.sqrt(np.clip((load ** 2).sum(axis=1), 1e-300, None))
    total, done = 0.0, 0
    block = max(1, min(int(draws), max(1, 4_000_000 // max(m, 1))))
    while done < draws:
        k = min(block, draws - done)
        x = (rng.standard_normal((k, m)) @ load.T) / scale   # unit-variance, correlation `corr`
        total += float(x.max(axis=1).sum())
        done += k
    return _invert_expected_max(total / draws, m)


def effective_trials(trial_returns: Iterable[Sequence[float]], *, method: str = "bailey",
                     draws: int = 20_000,
                     rng: Optional[np.random.Generator] = None) -> float:
    """Independent-trial count implied by the correlation between the trials' return series.

    A parameter sweep's configurations are not independent experiments -- neighbouring settings hold
    nearly the same positions and their P&L series are highly correlated. Counting them all as
    separate trials overstates ``SR₀`` and makes the DSR needlessly harsh; counting them as one
    removes the multiple-testing correction entirely. See :func:`effective_trials_from_corr` for
    what ``method`` does and why the methods disagree by an order of magnitude.

    Series of unequal length are truncated to the shortest. Constant or non-finite series are
    dropped, since a strategy that never traded is not a trial.
    """
    series = [np.asarray(list(s), dtype=float) for s in trial_returns]
    series = [s for s in series if len(s) > 2 and np.isfinite(s).all() and s.std(ddof=1) > 0]
    n = len(series)
    if n <= 1:
        return float(max(n, 1))
    width = min(len(s) for s in series)
    mat = np.vstack([s[:width] for s in series])
    if n > width / 2:
        logger.warning("effective_trials: %d trials over %d observations -- the correlation matrix "
                       "is ill-conditioned and rho-bar is itself overfit (Bailey & LdP A.3)",
                       n, width)
    corr = np.corrcoef(mat)
    corr = np.nan_to_num(corr, nan=0.0, posinf=0.0, neginf=0.0)
    np.fill_diagonal(corr, 1.0)
    return effective_trials_from_corr(corr, method=method, draws=draws, rng=rng)


# ------------------------------------------------------------------------------- DSR
def deflated_sharpe_ratio(
    returns: Sequence[float],
    *,
    n_trials: float,
    var_sharpe: float,
    mean_sharpe: float = 0.0,
) -> dict:
    """DSR for one strategy, given the search that produced it.

    ``var_sharpe`` is the variance of the **per-period** Sharpes across the trials, and ``n_trials``
    the number of INDEPENDENT ones (:func:`effective_trials`). Both may be floats.

    The returned ``psr_vs_zero`` is the same probability without the multiple-testing bar. The gap
    between the two is the price of the search, and reporting the pair is more informative than
    reporting either alone.
    """
    m = sharpe_moments(returns)
    sr0 = expected_max_sharpe(n_trials, var_sharpe, mean_sharpe=mean_sharpe)
    dsr = probabilistic_sharpe_ratio(m["sharpe"], n_obs=m["n"], skew=m["skew"],
                                     kurtosis=m["kurtosis"], benchmark=sr0)
    return {**m, "sr0": sr0, "n_trials": n_trials, "var_sharpe": var_sharpe, "dsr": dsr,
            "psr_vs_zero": probabilistic_sharpe_ratio(m["sharpe"], n_obs=m["n"], skew=m["skew"],
                                                      kurtosis=m["kurtosis"], benchmark=0.0),
            "sharpe_std_error": sharpe_std_error(m["sharpe"], n_obs=m["n"], skew=m["skew"],
                                                 kurtosis=m["kurtosis"])}


def deflated_sharpe_of_best(
    trial_returns: Sequence[Sequence[float]],
    *,
    use_effective_n: bool = True,
    method: str = "bailey",
    rng: Optional[np.random.Generator] = None,
) -> dict:
    """DSR of the best trial in a sweep, with everything estimated from the sweep itself.

    This is the honest way to report a grid search: the winner is judged against the distribution
    of its own competitors, so a large ``N`` and a wide scatter of Sharpes make the bar higher
    rather than the result better.

    ``sharpe_spread`` and ``var_sharpe`` are the ill-conditioning diagnostics. A sweep whose
    Sharpes barely move is well conditioned in its parameters and cheap to deflate; a sweep whose
    Sharpes scatter widely is telling you the result is a property of the knobs rather than of the
    market, and ``SR₀`` rises accordingly. The deflation and the sensitivity are the same number.
    """
    series = [np.asarray(list(s), dtype=float) for s in trial_returns]
    moments = [sharpe_moments(s) for s in series]
    sharpes = np.array([m["sharpe"] for m in moments], dtype=float)
    ok = np.isfinite(sharpes)
    if not ok.any():
        return {"dsr": float("nan"), "reason": "no trial produced a finite Sharpe"}

    var_sr = float(np.var(sharpes[ok], ddof=1)) if ok.sum() > 1 else 0.0
    n_raw = int(ok.sum())
    kept = [s for s, keep in zip(series, ok) if keep]
    n_eff = effective_trials(kept, method=method, rng=rng) if use_effective_n else float(n_raw)

    best_idx = int(np.nanargmax(np.where(ok, sharpes, -np.inf)))
    out = deflated_sharpe_ratio(series[best_idx], n_trials=n_eff, var_sharpe=var_sr)
    out.update({"best_index": best_idx, "n_trials_raw": n_raw, "n_trials_effective": float(n_eff),
                "effective_n_method": method if use_effective_n else "independent",
                "best_sharpe": float(sharpes[best_idx]),
                "sharpe_spread": float(np.nanmax(sharpes[ok]) - np.nanmin(sharpes[ok]))})
    return out


def deflated_sharpe_from_sharpes(
    sharpes: Sequence[float],
    *,
    n_obs: int,
    skew: float = 0.0,
    kurtosis: float = 3.0,
    n_trials: Optional[float] = None,
    periods_per_year: Optional[float] = None,
    best: Optional[int] = None,
) -> dict:
    """DSR of the best config in a grid search, from the per-config Sharpes alone.

    The common case: a sweep leaves you a summary row per configuration, not the P&L series. Give
    it the list of Sharpes and it uses their observed cross-config variance as ``V[{SR̂ₙ}]`` and
    ``N = len(sharpes)``.

    ``periods_per_year`` -- pass it if and only if ``sharpes`` are ANNUALISED. The Sharpes are then
    divided by ``√periods_per_year`` and, because variance scales with the square, ``V[{SR̂ₙ}]`` is
    computed on the converted values. ``n_obs`` is always the number of observations in the sample,
    never the number of years.

    ``skew`` and ``kurtosis`` are those of the WINNING config's return series. They default to the
    normal values, which makes the DSR OPTIMISTIC for the negatively-skewed, fat-tailed P&L that
    mean-reversion books actually produce -- supply the real moments when you have them.

    Two honest limitations, both inherent to the method rather than to this implementation. Without
    the per-config return series there is no way to estimate the correlation between trials, so
    ``N`` is the raw config count: correct only if the configs are independent, and conservative
    (too harsh) otherwise -- use :func:`deflated_sharpe_of_best` if you kept the series. And the
    observed cross-config variance is inflated by estimation noise in each Sharpe, so ``V[{SR̂ₙ}]``
    is biased up and ``SR₀`` with it.
    """
    sr = np.asarray(list(sharpes), dtype=float)
    sr = sr[np.isfinite(sr)]
    if sr.size == 0:
        return {"dsr": float("nan"), "reason": "no finite Sharpe supplied"}
    if periods_per_year is not None:
        sr = sr / math.sqrt(float(periods_per_year))

    best_idx = int(np.argmax(sr)) if best is None else int(best)
    best_sr = float(sr[best_idx])
    var_sr = float(np.var(sr, ddof=1)) if sr.size > 1 else 0.0
    n = float(sr.size) if n_trials is None else float(n_trials)

    sr0 = expected_max_sharpe(n, var_sr)
    return {
        "dsr": probabilistic_sharpe_ratio(best_sr, n_obs=n_obs, skew=skew, kurtosis=kurtosis,
                                          benchmark=sr0),
        "psr_vs_zero": probabilistic_sharpe_ratio(best_sr, n_obs=n_obs, skew=skew,
                                                  kurtosis=kurtosis, benchmark=0.0),
        "best_index": best_idx,
        "best_sharpe": best_sr,
        "sr0": sr0,
        "var_sharpe": var_sr,
        "n_trials": n,
        "n_obs": int(n_obs),
        "skew": float(skew),
        "kurtosis": float(kurtosis),
        "periods_per_year": periods_per_year,
        "sharpe_spread": float(sr.max() - sr.min()),
        "min_track_record_length": min_track_record_length(best_sr, skew=skew, kurtosis=kurtosis,
                                                           benchmark=sr0),
    }
