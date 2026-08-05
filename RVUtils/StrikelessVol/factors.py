"""The factor model: what moves the ultra-long forward slope.

Inference runs on CHANGES with HAC (Newey-West) standard errors. Levels
regressions are computed too, because they are the RV anchor the residual
z-score is built on, but they are returned with ``anchor_only=True``: in the
2026 sample the levels Durbin-Watson is ~0.2, so their t-statistics are not
evidence of anything and no consumer may treat them as such.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Optional, Sequence

import numpy as np
import pandas as pd
import statsmodels.api as sm

__all__ = [
    "RegressionResult",
    "changes_regression",
    "levels_regression",
    "frequency_ladder",
    "durbin_watson",
    "ar1_phi",
    "ar1_half_life_days",
    "residual_z",
    "drift",
    "positive_residual_clustering",
]


@dataclass(frozen=True)
class RegressionResult:
    betas: Dict[str, float]
    tstats: Dict[str, float]
    intercept: float
    r_squared: float
    durbin_watson: float
    n: int
    kind: str
    anchor_only: bool
    residuals: pd.Series = field(repr=False)


def durbin_watson(resid) -> float:
    e = pd.Series(resid).astype(float).dropna().to_numpy()
    if e.size < 3:
        return float("nan")
    de = np.diff(e)
    return float((de @ de) / (e @ e))


def _fit(y: pd.Series, X: pd.DataFrame, *, kind: str, anchor_only: bool,
         hac_lags: Optional[int]) -> RegressionResult:
    data = pd.concat([y.rename("_y_"), X], axis=1).dropna()
    if len(data) < 10:
        raise ValueError(f"only {len(data)} aligned observations")
    cols = [c for c in data.columns if c != "_y_"]
    Xm = sm.add_constant(data[cols])
    model = sm.OLS(data["_y_"], Xm).fit()
    lags = hac_lags if hac_lags is not None else max(1, int(round(len(data) ** 0.25)))
    robust = model.get_robustcov_results(cov_type="HAC", maxlags=lags)
    return RegressionResult(
        betas={c: float(model.params[c]) for c in cols},
        tstats={c: float(robust.tvalues[list(Xm.columns).index(c)]) for c in cols},
        intercept=float(model.params["const"]),
        r_squared=float(model.rsquared),
        durbin_watson=durbin_watson(model.resid),
        n=int(len(data)),
        kind=kind,
        anchor_only=anchor_only,
        residuals=model.resid,
    )


def changes_regression(
    spread_bp: pd.Series,
    drivers: Dict[str, pd.Series],
    *,
    horizon_days: int = 1,
    hac_lags: Optional[int] = None,
) -> RegressionResult:
    """d(spread) on d(drivers) at ``horizon_days``. This is where inference lives."""
    y = pd.Series(spread_bp).astype(float).diff(horizon_days)
    X = pd.DataFrame(
        {k: pd.Series(v).astype(float).diff(horizon_days) for k, v in drivers.items()}
    )
    return _fit(y, X, kind="changes", anchor_only=False, hac_lags=hac_lags)


def levels_regression(
    spread_bp: pd.Series, drivers: Dict[str, pd.Series],
    *, hac_lags: Optional[int] = None,
) -> RegressionResult:
    """Levels fit. RV anchor only -- never inference. See the module docstring."""
    y = pd.Series(spread_bp).astype(float)
    X = pd.DataFrame({k: pd.Series(v).astype(float) for k, v in drivers.items()})
    return _fit(y, X, kind="levels", anchor_only=True, hac_lags=hac_lags)


def frequency_ladder(
    spread_bp: pd.Series,
    drivers: Dict[str, pd.Series],
    horizons: Sequence[int] = (1, 5, 21),
) -> pd.DataFrame:
    """H1: is the funding factor a weekly/monthly effect invisible daily?"""
    rows = []
    for h in horizons:
        res = changes_regression(spread_bp, drivers, horizon_days=int(h))
        rec = {"horizon_days": int(h), "r_squared": res.r_squared, "n": res.n,
               "durbin_watson": res.durbin_watson}
        for k in drivers:
            rec[f"beta_{k}"] = res.betas[k]
            rec[f"t_{k}"] = res.tstats[k]
        rows.append(rec)
    return pd.DataFrame(rows)


def ar1_phi(resid) -> float:
    """OLS AR(1) coefficient of a residual series."""
    e = pd.Series(resid).astype(float).dropna()
    if len(e) < 20:
        return float("nan")
    x, y = e.shift(1).dropna(), e.iloc[1:]
    return float(np.polyfit(x.to_numpy(), y.to_numpy(), 1)[0])


def ar1_half_life_days(
    resid, *, adf_pvalue_threshold: float = 0.05,
    n_cointegrating_vars: Optional[int] = None,
) -> float:
    """Business days to halve. Infinite for a unit root.

    "Unit root" is decided by an Augmented Dickey-Fuller test
    (``RVUtils.regression.residual_diagnostics``), not by a ``phi >= 1.0``
    boundary comparison alone: finite-sample OLS estimates of phi for a
    genuine unit-root process are biased downward and essentially never land
    exactly at or above 1.0 in practice (a true random walk of 3000
    observations recovers phi ~= 0.998, not 1.0), so a boundary check by
    itself reports a large-but-finite "half life" for a residual that does
    not actually mean-revert -- exactly the failure this function exists to
    prevent. ``phi >= 1.0`` (or non-finite/non-positive phi) is kept as a
    cheap short-circuit for when the point estimate itself is already at or
    past the boundary; whenever phi is interior, the ADF p-value is what
    decides -- failing to reject the unit-root null (p > ``adf_pvalue_threshold``,
    default 0.05) returns infinity regardless of how plausible phi looks.

    **Critical-value warning for regression residuals -- read before passing
    a ``levels_regression``/``changes_regression`` residual (Task 15's
    primary intended input for this whole module):** the default ADF
    p-value uses STANDARD, single-series critical values. If ``resid`` is
    the residual of an OLS regression estimated **on the same data**, OLS
    has already minimised that residual's in-sample variance
    ("superconsistency"), which makes it look more stationary than it is
    under the null of no cointegration -- standard critical values are
    miscalibrated for this case and systematically over-reject the unit
    root. Measured on a placebo (a random walk regressed on an unrelated
    random walk, i.e. no true relationship at all): the standard-ADF gate
    at ``adf_pvalue_threshold=0.05`` opened in ~20% of trials, four times
    the nominal rate (Task 15 round-4 report). The correct values are
    Engle-Granger's (Engle & Granger 1987; MacKinnon 1994/2010), which
    depend on the number of I(1) series in the cointegrating regression
    (the dependent variable plus its regressors). Pass
    ``n_cointegrating_vars=k+1`` (``k`` = number of regressors, NOT
    counting the constant -- e.g. ``k=1`` for a single-driver
    ``levels_regression``, so ``n_cointegrating_vars=2``) whenever
    ``resid`` comes from an estimated regression, and this function uses
    ``statsmodels.tsa.stattools.mackinnonp`` with the correct ``N`` in
    place of the default single-series p-value -- verified to reproduce
    ``statsmodels.tsa.stattools.coint``'s own end-to-end Engle-Granger
    p-value to within a few thousandths on real data. Left at the default
    (``None``), this function silently uses the wrong critical values for
    a regression residual -- **that is a known, documented limitation, not
    a bug fixed by omission: callers that know they are testing a
    cointegrating-regression residual must pass this parameter.**
    """
    phi = ar1_phi(resid)
    if not np.isfinite(phi) or phi <= 0.0 or phi >= 1.0:
        return float("inf")

    from RVUtils.regression import residual_diagnostics

    diag = residual_diagnostics(resid)
    adf_p = diag.get("adf_pvalue", float("nan"))
    if n_cointegrating_vars is not None:
        adf_stat = diag.get("adf_stat", float("nan"))
        if np.isfinite(adf_stat):
            from statsmodels.tsa.adfvalues import mackinnonp

            adf_p = float(mackinnonp(adf_stat, regression="c", N=int(n_cointegrating_vars)))
        else:
            adf_p = float("nan")
    if not np.isfinite(adf_p) or adf_p > float(adf_pvalue_threshold):
        return float("inf")
    return float(np.log(0.5) / np.log(phi))


def residual_z(resid, *, window: int = 252, min_periods: int = 126) -> pd.Series:
    """Rolling z on the residual's OWN dispersion.

    Not the OLS standard error: that is sigma/sqrt(n), it shrinks with sample
    size, and bands built on it tighten as history accumulates until the rule
    fires constantly.

    The rolling window here (``e.rolling(...)``, a trailing/causal window by
    pandas construction) is NOT the source of look-ahead risk in this
    function -- it is causal by construction, on its own. **The look-ahead
    risk lives entirely upstream, in how ``resid`` itself was built (Task 15
    round 4).** ``levels_regression``/``changes_regression`` fit a SINGLE
    set of betas on the WHOLE requested window; every point of the returned
    residual is computed with betas that saw data from after that point, in
    a normal walk-forward/live-trading sense. Feeding a full-sample-fit
    residual into ``residual_z`` produces a z-score no live book could ever
    have computed on the date it is dated -- this was measured directly: a
    naive full-sample expectancy calculation this way overstated realised,
    entry-vintage-frozen-beta P&L by roughly 8bp/trade on one window. **This
    function requires its ``resid`` argument to already come from a causal
    (expanding-window or rolling-window) regression fit -- never pass a
    ``levels_regression``/``changes_regression`` residual computed on the
    full sample directly.** No expanding/rolling regression fit is provided
    in this module as of Task 15; building one (and re-deriving ``resid``
    causally before it ever reaches this function) is recorded as a Task 18
    requirement, not implemented here.
    """
    e = pd.Series(resid).astype(float)
    roll = e.rolling(int(window), min_periods=int(min_periods))
    return (e - roll.mean()) / roll.std(ddof=1)


def drift(changes_resid, *, window: int = 63) -> pd.DataFrame:
    """Signal 2: the vol-orthogonal structural drift, and its significance."""
    from RVUtils.SFRRVLab.stats import nw_tstat

    e = pd.Series(changes_resid).astype(float)
    mean = e.rolling(int(window), min_periods=int(window)).mean()
    t = e.rolling(int(window), min_periods=int(window)).apply(
        lambda w: nw_tstat(w, lags=5), raw=False
    )
    return pd.DataFrame({"mean_bp_per_day": mean, "t_stat": t})


def positive_residual_clustering(resid, *, window: int = 21) -> pd.Series:
    """Share of positive residuals in the window -- the regime tell (H4)."""
    e = pd.Series(resid).astype(float)
    return (e > 0).rolling(int(window), min_periods=int(window)).mean()
