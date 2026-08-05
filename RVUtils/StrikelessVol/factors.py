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
    "WalkForwardFit",
    "changes_regression",
    "expanding_changes_residual",
    "expanding_residual",
    "levels_regression",
    "frequency_ladder",
    "durbin_watson",
    "ar1_phi",
    "ar1_half_life_days",
    "residual_z",
    "drift",
    "positive_residual_clustering",
    "beta_vs_vol_level",
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


@dataclass(frozen=True)
class WalkForwardFit:
    """A causal regression fit: the betas at date ``t`` never saw date ``t``.

    ``betas`` is the per-date coefficient vintage, which is what a hedge
    frozen at the entry date is frozen TO (Task 18 requirement 2). Keeping it
    is the difference between being able to freeze the hedge and only being
    able to claim you did.
    """

    residual: pd.Series = field(repr=False)
    betas: pd.DataFrame = field(repr=False)
    min_periods: int = 252
    refit_every: int = 1
    kind: str = "expanding"
    n_fitted: int = 0


def expanding_residual(
    spread_bp,
    drivers: Dict[str, pd.Series],
    *,
    min_periods: int = 252,
    refit_every: int = 1,
) -> WalkForwardFit:
    """Walk-forward levels residual. **The betas at ``t`` see only data before ``t``.**

    This exists because :func:`levels_regression` fits ONE set of betas on the
    WHOLE requested window and applies them to every date in it, so every point
    of its residual before the end of the sample was computed with coefficients
    that saw data from after that point. Measured directly in Task 15, holding
    entry rule, exit rule and sign identical and changing ONLY the beta
    vintage: an apparent +12.313bp/trade became +3.796bp expanding and
    **+0.127bp gross with the hedge frozen at the entry date**. The look-ahead
    was worth roughly **8.5bp/trade**, which is larger than any edge this study
    has measured. A full-sample residual must never reach a signal.

    The fit at date ``t`` uses ``spread_bp``/``drivers`` strictly BEFORE ``t``
    (``df.iloc[:i]``), so the residual at ``t`` is out-of-sample by
    construction and the causality can be checked mechanically rather than
    asserted -- shock the tail of the input and the head of the residual does
    not move (``backtest.audit_causal_betas``). ``levels_regression``'s
    residual fails that same check by more than a basis point, which is how
    the checker itself was verified against an input whose answer was known.

    ``refit_every`` re-estimates every N-th row and carries the previous
    vintage in between; that is still causal (an older vintage saw strictly
    less), it is only cheaper.
    """
    y = pd.Series(spread_bp).astype(float)
    X = pd.DataFrame({k: pd.Series(v).astype(float) for k, v in drivers.items()})
    return _walk_forward(y, X, min_periods=min_periods, refit_every=refit_every,
                         kind="expanding", what="expanding_residual")


def expanding_changes_residual(
    spread_bp,
    drivers: Dict[str, pd.Series],
    *,
    horizon_days: int = 1,
    min_periods: int = 252,
    refit_every: int = 1,
) -> WalkForwardFit:
    """Walk-forward CHANGES residual -- :func:`changes_regression`, made causal.

    This is the object :func:`drift` is supposed to be fed. It did not exist
    until now, and its absence is why the ``drift_t`` veto leaked: the only
    changes-regression builder in this module was :func:`changes_regression`,
    which fits ONE set of betas on the WHOLE sample, and the study's own
    reference panel built the veto as ``drift(changes_regression(...).residuals)``.
    Measured on the 900-day synthetic frame the audits use, shocking the last
    25% of the spread by +250bp and looking at the FIRST 75% of the sample --
    the head cannot legitimately move at all, because nothing in it happened
    after the shock:

    ============================================  =========  ==============
    changes residual builder                      head move  drift_t head move
    ============================================  =========  ==============
    ``changes_regression(...).residuals``           2.628         6.105
    ``expanding_changes_residual(...).residual``    0.0           0.0
    ============================================  =========  ==============

    ``drift_t`` is what ``strategy.signal_state`` vetoes on, at
    ``drift_t_gate = 2.0``. A veto column that moves **6.1 t-units** in the
    head of the sample when only the tail of its input was shocked is using
    information the trade date did not have, whichever way the veto points --
    and 6.1 is three times the gate. On the unshocked frame the two builders
    happen to disagree about vetoing on only 2 of 585 days (this synthetic
    spread is close to linear in its driver, so a full-sample fit and an
    expanding one nearly coincide); against the cruder causal proxy the review
    used, ``expanding_residual(...).residual.diff()``, the same leaky column
    disagrees on 18 of 585 days with a max t-gap of 1.61. The disagreement
    count is a property of the sample; the head movement is a property of the
    builder, which is why the audit gates on the latter.

    Mechanically identical to :func:`expanding_residual` -- the fit at date
    ``t`` uses only rows strictly BEFORE ``t``, so the head is bit-identical
    under a tail shock and ``backtest.audit_causal_betas`` certifies it -- with
    ``spread_bp`` and every driver differenced at ``horizon_days`` first, which
    is the only difference between a levels fit and a changes fit.

    ``betas`` is the per-date coefficient vintage on the DIFFERENCED
    regressors, so it is not interchangeable with
    :func:`expanding_residual`'s: do not hand this fit to
    ``entry_vintage_signals``, whose hedge is a levels hedge.
    """
    h = int(horizon_days)
    y = pd.Series(spread_bp).astype(float).diff(h)
    X = pd.DataFrame({k: pd.Series(v).astype(float).diff(h)
                      for k, v in drivers.items()})
    return _walk_forward(y, X, min_periods=min_periods, refit_every=refit_every,
                         kind="expanding_changes", what="expanding_changes_residual")


def _walk_forward(
    y: pd.Series,
    X: pd.DataFrame,
    *,
    min_periods: int,
    refit_every: int,
    kind: str,
    what: str,
) -> WalkForwardFit:
    """The shared expanding-window loop. See :func:`expanding_residual`.

    Factored out so the levels and changes walk-forward fits cannot drift
    apart: the causality of both rests on the single line ``hist =
    values[:i]`` -- history strictly before the row being predicted -- and one
    copy of that line is easier to keep honest than two.
    """
    df = pd.concat([y.rename("_y_"), X], axis=1)
    cols = [c for c in df.columns if c != "_y_"]
    if not cols:
        raise ValueError(f"{what} needs at least one driver")

    idx = df.index
    resid = pd.Series(np.nan, index=idx, dtype=float)
    betas = pd.DataFrame(np.nan, index=idx, columns=["const"] + cols, dtype=float)
    vintage = pd.Series(pd.NaT, index=idx, dtype="datetime64[ns]")

    coef = None
    coef_date = None
    n_fitted = 0
    values = df.to_numpy(dtype=float)
    y_col = list(df.columns).index("_y_")
    x_cols = [list(df.columns).index(c) for c in cols]
    for i, ts in enumerate(idx):
        if i >= min_periods and (coef is None or i % max(int(refit_every), 1) == 0):
            hist = values[:i]
            ok = np.isfinite(hist).all(axis=1)
            if ok.sum() >= min_periods:
                h = hist[ok]
                A = np.column_stack([np.ones(len(h))] + [h[:, j] for j in x_cols])
                coef = np.linalg.lstsq(A, h[:, y_col], rcond=None)[0]
                coef_date = idx[i - 1]
                n_fitted += 1
        if coef is None:
            continue
        row = values[i]
        if not np.isfinite(row[[y_col] + x_cols]).all():
            continue
        pred = coef[0] + float(np.dot(coef[1:], row[x_cols]))
        resid.iloc[i] = float(row[y_col]) - pred
        betas.iloc[i] = coef
        vintage.iloc[i] = coef_date

    betas["vintage_date"] = vintage
    resid.attrs["beta_vintage"] = kind
    resid.attrs["causal"] = True
    resid.attrs["min_periods"] = int(min_periods)
    return WalkForwardFit(
        residual=resid, betas=betas, min_periods=int(min_periods),
        refit_every=int(refit_every), kind=kind, n_fitted=n_fitted,
    )


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
    full sample directly.** The causal builders now exist and are the only
    supported inputs: :func:`expanding_residual` for a levels residual and
    :func:`expanding_changes_residual` for a changes residual. Pass one of
    their ``.residual`` series. (This paragraph used to end "no
    expanding/rolling regression fit is provided in this module", which was
    true when written; the levels one landed in Task 18 and the changes one
    with the ``drift_t`` certificate.)
    """
    e = pd.Series(resid).astype(float)
    roll = e.rolling(int(window), min_periods=int(min_periods))
    return (e - roll.mean()) / roll.std(ddof=1)


def drift(changes_resid, *, window: int = 63) -> pd.DataFrame:
    """Signal 2: the vol-orthogonal structural drift, and its significance.

    The rolling mean and the Newey-West t are TRAILING (``min_periods=window``,
    no centring), so this function's own window adds no look-ahead. Its
    ``changes_resid`` argument does: it must come from
    :func:`expanding_changes_residual`, not from
    :func:`changes_regression`, whose betas are fitted on the whole sample.
    ``t_stat`` is what ``strategy.signal_state`` VETOES on, and a full-sample
    source moves it by 6.1 t-units in the head of a sample whose tail alone
    was shocked -- against a gate of 2.0. See
    :func:`expanding_changes_residual` and
    ``backtest.audit_trailing_statistic``.
    """
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


def beta_vs_vol_level(spread_bp, vol_ann, *, window: int = 126) -> pd.DataFrame:
    """H3: convexity is proportional to sigma^2, so the beta should scale in sigma."""
    from RVUtils.regression import rolling_beta_stability

    dy = pd.Series(spread_bp).astype(float).diff()
    dx = pd.Series(vol_ann).astype(float).diff()
    tbl = rolling_beta_stability(dy, dx.rename("vol"), window_beta=int(window))
    out = pd.DataFrame(
        {"beta": tbl["beta_vol"], "vol_level": pd.Series(vol_ann).astype(float)}
    ).dropna()
    if len(out) > 10:
        slope, intercept = np.polyfit(out["vol_level"], out["beta"], 1)
        out.attrs["beta_on_vol_slope"] = float(slope)
        out.attrs["beta_on_vol_intercept"] = float(intercept)
    return out
