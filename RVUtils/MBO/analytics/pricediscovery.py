"""Where the price is made: Hasbrouck information share and Gonzalo-Granger
component share, for two or more quotes of one underlying.

The question is narrow and the statistics answering it are narrower still.  Given
several prices that must converge -- ZNU6 outright against the ZNU6-ZNZ6 implied
leg, a listed spread against the arithmetic of its legs, the same contract on two
venues -- which of them moves first, and by how much of the total?

Both estimators here come out of one vector error-correction model, and both are
**undefined unless the prices are cointegrated**.  That is not a technicality.  Fit
a VECM to two unrelated random walks and every step of the arithmetic still runs:
you get an adjustment matrix, a null space, a Cholesky factor and two numbers that
sum to one.  They mean nothing.  :func:`vecm_fit` therefore tests first and raises,
rather than handing back a share of a common efficient price that does not exist.

**The two statistics answer different questions and are meant to disagree.**
Hasbrouck's share asks what fraction of the *variance* of the efficient-price
innovation is attributable to each market; Gonzalo-Granger's asks each market's
weight in the *composition* of the common permanent component, and it is a
function of the error-correction loadings alone -- it never looks at the
innovation covariance.  Baillie, Booth, Tse and Zabotina's analytic example makes
the gap concrete: with equal adjustment speeds and innovation correlation 0.9, the
Hasbrouck bounds are [0.05, 0.95] while the component share sits at exactly 0.50.
A reader who sees those two lines and calls one of them wrong has misread both.

**Hasbrouck's share is not a number, it is an interval.**  When the innovation
covariance is not diagonal -- and on any real data at any feasible sampling
frequency it is not -- the share depends on the Cholesky ordering of the price
vector.  Hasbrouck sampled at one second hoping the contemporaneous correlation
would vanish; it does not.  :func:`information_share` therefore returns the lower
bound, the upper bound and their midpoint together, and flags when the interval is
too wide to carry information.  Reporting the midpoint alone, or one ordering's
number as "the" information share, is the classic misuse of this statistic.

**Neither statistic is a clean "who moves first" when the series carry unequal
noise.**  Putnins shows that both IS and CS are consistent with the
first-to-reflect-information reading only when the price series have equal levels
of microstructure noise; otherwise they measure a blend of leadership and
noise-avoidance.  A wide SR3 book against a tight ZN book is exactly that case, so
a bare IS comparison across those two is not evidence about information flow.  His
information leadership share is the fix, and it is not implemented here.

**On the sampling grid.**  Unlike Hayashi-Yoshida in
:mod:`~RVUtils.MBO.analytics.leadlag`, this model needs one common regular clock,
because a VECM is a regression on lags and a lag has to mean something.  Use
:func:`RVUtils.MBO.store.panel.panel` with a single field, and be aware that the
grid interval is a real choice: too coarse and the adjustment happens inside one
bar so every share collapses toward the noise; too fine and the innovation
correlation rises and the bounds open to [0, 1].
"""
from __future__ import annotations

import itertools
from typing import Dict, List, Optional, Sequence, Tuple

import numpy as np
import pandas as pd
from statsmodels.tsa.stattools import adfuller

__all__ = [
    "UNINFORMATIVE_BOUND_WIDTH",
    "component_share",
    "information_share",
    "vecm_fit",
]


#: Width of the Hasbrouck interval above which it is flagged as carrying no
#: information.  In the Baillie et al. bivariate model the width equals the
#: innovation correlation exactly, so 0.5 flags a pair whose innovations correlate
#: above 0.5 at the chosen sampling interval.  It is a judgment call, stated as
#: one rather than dressed up as a theorem: the honest reading is the interval
#: itself, and this flag only saves a reader from quoting a midpoint that the data
#: never pinned down.
UNINFORMATIVE_BOUND_WIDTH = 0.5

#: Widest panel the bounds are enumerated over.  The search costs
#: ``n * 2^(n-1)`` Cholesky factorisations, so this is where it stops being free;
#: beyond it :func:`information_share` refuses rather than quietly switching to a
#: heuristic subset of orderings that would report a narrower interval than the
#: truth.
_MAX_ENUMERATED_SERIES = 12

_IS_BOUND_COLUMNS: Tuple[Tuple[str, str], ...] = (
    ("is_lower", "float64"),
    ("is_upper", "float64"),
    ("is_mid", "float64"),
    ("bound_width", "float64"),
    ("bounds_uninformative", "bool"),
)
_IS_ORDERED_COLUMNS: Tuple[Tuple[str, str], ...] = (
    ("is_ordered", "float64"),
    ("order_position", "int64"),
)
_CS_COLUMNS: Tuple[Tuple[str, str], ...] = (
    ("cs", "float64"),
    ("alpha_perp", "float64"),
    ("cs_out_of_range", "bool"),
)


def _empty(columns: Sequence[Tuple[str, str]]) -> pd.DataFrame:
    """An empty frame with the real columns and dtypes, never a bare DataFrame."""
    out = pd.DataFrame(
        {name: pd.Series(dtype=dtype) for name, dtype in columns},
        index=pd.Index([], dtype=object, name="series"),
    )
    return out


def _is_empty_panel(panel: pd.DataFrame) -> bool:
    if not isinstance(panel, pd.DataFrame):
        raise TypeError(
            f"panel must be a DataFrame of aligned prices, one column per series, "
            f"not {type(panel).__name__}; RVUtils.MBO.store.panel.panel(..., "
            f"fields=('mid',)) returns one."
        )
    return panel.shape[0] == 0 or panel.shape[1] == 0


def _prepare(panel: pd.DataFrame) -> Tuple[np.ndarray, Tuple[str, ...]]:
    """Validate the panel and return contiguous float prices plus series names.

    Accepts the ``(field, symbol)`` MultiIndex that
    :func:`RVUtils.MBO.store.panel.panel` produces, provided exactly one field is
    present.  Two fields are refused rather than silently flattened, because a
    panel carrying both ``bid`` and ``ask`` would be read as four cointegrated
    series and the resulting share would be split between a symbol and its own
    other side.
    """
    df = panel
    if isinstance(df.columns, pd.MultiIndex):
        fields = list(dict.fromkeys(df.columns.get_level_values(0)))
        if len(fields) != 1:
            raise ValueError(
                f"panel carries {len(fields)} fields {fields}; price discovery is "
                f"defined on ONE price per series. Rebuild the panel with a single "
                f"field, e.g. panel(..., fields=('mid',)), or slice it: "
                f"panel['mid']."
            )
        df = df.droplevel(0, axis=1)

    columns = [str(c) for c in df.columns]
    if len(set(columns)) != len(columns):
        dupes = sorted({c for c in columns if columns.count(c) > 1})
        raise ValueError(
            f"duplicate series names {dupes} in the panel; a series cannot lead "
            f"itself. De-duplicate the columns before asking who moved first."
        )
    if len(columns) < 2:
        raise ValueError(
            f"price discovery needs at least two series, got {columns}. Pass the "
            f"outright and its implied quote, or a spread and its legs, in one "
            f"panel."
        )

    try:
        values = df.to_numpy(dtype=np.float64)
    except (TypeError, ValueError) as exc:
        raise ValueError(
            f"panel must hold numeric prices; column dtypes are "
            f"{dict(df.dtypes)}. Convert before fitting."
        ) from exc

    finite = np.isfinite(values).all(axis=1)
    if not finite.any():
        raise ValueError(
            "no row of the panel has a price for every series. A panel is NaN "
            "before an instrument's first quote, so check the session bounds and "
            "that every symbol traded on the requested dates."
        )
    first = int(np.argmax(finite))
    if not finite[first:].all():
        gaps = int((~finite[first:]).sum())
        raise ValueError(
            f"the panel has {gaps} interior rows with a missing price. A VECM is a "
            f"regression on LAGS, so dropping those rows would silently treat the "
            f"hole as one sampling interval and shrink the estimated adjustment "
            f"speed toward zero. Forward-fill the panel, or restrict the dates or "
            f"session so the gap is outside the sample."
        )
    return np.ascontiguousarray(values[first:]), tuple(columns)


def _cointegration_pvalues(values: np.ndarray, columns: Tuple[str, ...],
                           lags: int) -> Dict[str, float]:
    """Augmented Dickey-Fuller p-value for each imposed spread.

    The cointegrating vectors are known here, not estimated: two quotes of one
    underlying are tied by ``(1, -1)`` and nothing else, which is why the
    Hasbrouck basis is imposed rather than fitted.  That has a consequence for the
    test.  The Engle-Granger critical values exist because estimating the
    cointegrating vector by least squares makes the residual look more stationary
    than it is; with the vector imposed there is no such pre-test, so the standard
    Dickey-Fuller distribution -- what :func:`statsmodels.tsa.stattools.adfuller`
    returns -- is the correct one, not an approximation to it.

    The lag order is tied to the VECM's own lag order rather than chosen by AIC,
    so the guard cannot pass on one call and fail on the next because an
    information criterion picked differently on a sample one bar longer.

    The degenerate case is caught RELATIVE to the price level rather than by
    testing the spread's variance against zero, and the difference matters.  Two
    columns that are the same instrument offset by a constant do not subtract to
    exactly that constant in floating point: the residue is a few units in the
    last place of the price, which is not zero, so an exact test lets it through
    and the Dickey-Fuller test then runs on pure rounding noise.  It does not
    fail; it returns a confident-looking p-value near one and the caller is told
    the pair is not cointegrated, which is a wrong diagnosis of a real problem.
    """
    scale = max(float(np.max(np.abs(values))), 1.0)
    pvalues: Dict[str, float] = {}
    for k in range(1, values.shape[1]):
        name = f"{columns[0]}-{columns[k]}"
        spread = values[:, 0] - values[:, k]
        if float(np.std(spread)) <= _MIN_SPREAD_VARIATION_RATIO * scale:
            raise ValueError(
                f"{columns[0]} and {columns[k]} differ by a constant at every "
                f"observation, so their spread has no variance and neither series "
                f"can be said to lead. Check you did not pass the same instrument "
                f"twice under two names, or a derived column alongside the price it "
                f"was derived from."
            )
        pvalue = adfuller(spread, maxlag=max(int(lags), 0),
                          regression="c", autolag=None)[1]
        pvalues[name] = float(pvalue)
    return pvalues


def _usable_rows(n_obs: int, n: int, lags: int) -> Tuple[int, int]:
    """Rows the VECM can actually use, and regressors per equation, or raise.

    Checked before the cointegration test rather than after, because a sample too
    short to fit the model is also too short for the unit-root test to have any
    power, and being told a genuinely cointegrated pair "is not cointegrated" sends
    the reader looking for the wrong problem.
    """
    rows = n_obs - 1 - lags
    k = 1 + (n - 1) + n * lags
    if rows < k + n + 10:
        raise ValueError(
            f"{max(rows, 0)} usable observations for {k} regressors per equation: "
            f"the residual covariance would be singular or all but. Lengthen the "
            f"sample, use a finer grid, or drop the lag order below {lags}."
        )
    return rows, k


def _ols(values: np.ndarray, lags: int) -> Dict[str, np.ndarray]:
    """Equation-by-equation OLS for the VECM with the Hasbrouck basis imposed.

    Every equation has the identical regressor matrix ``[1, Z_{t-1}, dP_{t-1},
    ..., dP_{t-lags}]``, and a seemingly-unrelated system with identical
    regressors is estimated exactly by OLS equation by equation -- there is
    nothing generalised least squares would add.

    The intercept is free rather than restricted to ``A * mu`` inside the
    cointegrating relation as Hasbrouck writes it.  The free form NESTS the
    restricted one, so it cannot bias the adjustment matrix when Hasbrouck's
    specification is right; what it buys is protection when it is not.  A session
    that trended has a drift, and a restricted intercept has nowhere to put it
    except into the adjustment coefficients, which is precisely the quantity both
    shares are built from.
    """
    n_obs, n = values.shape
    theta = np.zeros((n, n - 1), dtype=np.float64)
    theta[0, :] = 1.0
    theta[1:, :] = -np.eye(n - 1)

    d_p = np.diff(values, axis=0)            # d_p[t] is P_{t+1} - P_t
    z = values @ theta                       # levels of every imposed spread
    _, k = _usable_rows(n_obs, n, lags)
    rows = np.arange(lags, n_obs - 1)

    blocks: List[np.ndarray] = [np.ones((rows.size, 1)), z[rows]]
    for j in range(1, lags + 1):
        blocks.append(d_p[rows - j])
    x = np.concatenate(blocks, axis=1)
    y = d_p[rows]

    beta_hat, _, rank, _ = np.linalg.lstsq(x, y, rcond=None)
    if rank < k:
        raise ValueError(
            f"the VECM design matrix is rank {rank} of {k}: two of the regressors "
            f"are collinear, which happens when a series never moves over the "
            f"sample or when two series are identical. Check every column of the "
            f"panel actually quotes."
        )
    resid = y - x @ beta_hat
    sigma = resid.T @ resid / float(rows.size - k)

    alpha = beta_hat[1:n, :].T.copy()                    # (n, n-1)
    gammas = np.empty((lags, n, n), dtype=np.float64)
    for j in range(lags):
        off = 1 + (n - 1) + j * n
        gammas[j] = beta_hat[off:off + n, :].T
    gamma_1 = np.eye(n) - gammas.sum(axis=0)     # empty sum is zero at lags=0

    return {
        "beta": theta,
        "alpha": alpha,
        "mu": beta_hat[0, :].copy(),
        "gamma": gammas,
        "gamma_1": gamma_1,
        "sigma": sigma,
        "resid": resid,
        "nobs": int(rows.size),
        "n_regressors": int(k),
    }


def _common_factor(alpha: np.ndarray, gamma_1: np.ndarray
                   ) -> Tuple[np.ndarray, np.ndarray, float, bool]:
    """The long-run weights, from the left null space of the adjustment matrix.

    Because ``theta' Psi(1) = 0``, the long-run impact matrix has rank one and
    factors as ``1_n psi'`` -- one common trend, which is the whole content of the
    claim that these prices share an efficient price.  Johansen's factorisation
    gives ``Psi(1) = beta_perp (alpha_perp' Gamma(1) beta_perp)^-1 alpha_perp'``,
    and with the Hasbrouck basis ``beta_perp`` is the vector of ones exactly.  So
    ``psi`` is ``alpha_perp`` rescaled by a scalar.

    That scalar cancels out of every share this module reports, since both IS and
    CS are ratios homogeneous of degree zero in ``psi``.  It is computed anyway
    and reported, because ``psi`` is then the actual Beveridge-Nelson weight
    vector rather than an arbitrary multiple of it, and a reader comparing this
    fit against a textbook wants the real thing.
    """
    n = alpha.shape[0]
    u, s, _ = np.linalg.svd(alpha)
    tol = float(s.max()) * max(alpha.shape) * np.finfo(np.float64).eps
    rank = int((s > tol).sum())
    if rank < n - 1:
        raise ValueError(
            f"the adjustment matrix has rank {rank}, not {n - 1}: the common trend "
            f"is not identified, so no share of it can be reported. This is what a "
            f"panel looks like when no series error-corrects to the spread -- the "
            f"prices drift apart and nothing pulls them back -- or when two series "
            f"adjust identically. Widen the sample or check the pair really is one "
            f"underlying."
        )
    alpha_perp = np.ascontiguousarray(u[:, n - 1])
    # Deterministic sign.  Immaterial to every share reported here (both are
    # invariant to the sign of psi), but a vector whose sign flips with the SVD's
    # mood makes two runs look like two answers.
    if alpha_perp[int(np.argmax(np.abs(alpha_perp)))] < 0:
        alpha_perp = -alpha_perp

    denom = float(alpha_perp @ gamma_1 @ np.ones(n))
    scale = float(np.linalg.norm(gamma_1)) * n * np.finfo(np.float64).eps
    normalised = abs(denom) > max(scale, 1e-300)
    psi = alpha_perp / denom if normalised else alpha_perp.copy()
    return psi, alpha_perp, denom, normalised


def vecm_fit(panel: pd.DataFrame, lags: int = 5,
             coint_pvalue: float = 0.05) -> dict:
    """Fit the vector error-correction model both price-discovery shares are read from.

    Returns the cointegrating basis, the adjustment matrix, the short-run
    coefficients, the residual covariance and the long-run weight vector -- the
    single fit that :func:`information_share` and :func:`component_share` both
    consume, so that two shares reported side by side are guaranteed to describe
    the same model rather than two fits that happened to be run with different
    lag orders.

    Keys: ``beta`` (the imposed cointegrating basis) and ``beta_perp``; ``alpha``
    (adjustment) and ``alpha_perp``; ``mu``, ``gamma`` and ``gamma_1``; ``sigma``
    and ``resid``; ``psi`` with ``psi_scale`` and ``psi_normalised``; plus
    ``columns``, ``lags``, ``nobs``, ``n_regressors`` and ``coint_pvalues``.

    **statsmodels is used for the cointegration test and deliberately not for the
    fit.**  ``statsmodels.tsa.vector_ar.vecm.VECM`` estimates the cointegrating
    vectors by Johansen maximum likelihood.  Here they are not unknown: prices of
    one underlying are tied by ``(1, -1)``, which is Hasbrouck's own basis
    ``Theta' = (1 : -I)``, and estimating a parameter you already know only adds
    sampling noise to every quantity downstream of it.  So the system is fitted by
    ordinary least squares on the imposed basis, exactly as the model is written,
    and statsmodels supplies :func:`~statsmodels.tsa.stattools.adfuller` for the
    guard -- the one step where the null distribution is easy to get wrong.

    ``lags`` is the number of lagged difference terms, ``K - 1`` in Hasbrouck's
    notation, so ``lags=0`` is a pure error-correction model with no short-run
    dynamics.

    Raises rather than returning a fit when the prices fail the cointegration
    test at ``coint_pvalue``.  An empty panel raises here too: unlike the share
    functions, which return an empty typed frame, there is no such thing as an
    empty model, and returning a dict of empty arrays would let a caller reach
    ``fit['sigma']`` and get something shaped like an answer.
    """
    if not isinstance(lags, (int, np.integer)) or isinstance(lags, bool) or lags < 0:
        raise ValueError(f"lags must be a non-negative integer, got {lags!r}")
    if _is_empty_panel(panel):
        raise ValueError(
            "cannot fit a VECM to an empty panel. Check the dates, the session "
            "bounds and the symbols; information_share and component_share return "
            "an empty frame for this input rather than raising."
        )
    values, columns = _prepare(panel)
    lags = int(lags)
    _usable_rows(values.shape[0], values.shape[1], lags)

    pvalues = _cointegration_pvalues(values, columns, lags)
    failed = {k: v for k, v in pvalues.items() if v > coint_pvalue}
    if failed:
        detail = ", ".join(f"{k} p={v:.3f}" for k, v in sorted(failed.items()))
        raise ValueError(
            f"these prices are not cointegrated ({detail}; the unit root in the "
            f"spread is not rejected at {coint_pvalue}). Hasbrouck and "
            f"Gonzalo-Granger shares are shares OF A COMMON EFFICIENT PRICE, and "
            f"without cointegration there is no common efficient price to share. "
            f"Both statistics would still compute and would still sum to one, "
            f"which is why this raises instead. Check the panel really holds two "
            f"views of the SAME underlying, and that the sample is long enough for "
            f"the test to see the mean reversion."
        )

    fit = _ols(values, lags)
    psi, alpha_perp, denom, normalised = _common_factor(fit["alpha"], fit["gamma_1"])
    fit.update({
        "psi": psi,
        "alpha_perp": alpha_perp,
        "beta_perp": np.ones(values.shape[1]),
        "psi_scale": denom,
        "psi_normalised": normalised,
        "columns": columns,
        "lags": lags,
        "coint_pvalues": pvalues,
    })
    return fit


def _shares_for_order(psi: np.ndarray, sigma: np.ndarray,
                      perm: Sequence[int]) -> np.ndarray:
    """Hasbrouck shares under one Cholesky ordering, back in original series order.

    ``IS_i = ((psi' F)_i)^2 / (psi' Sigma psi)`` with ``F`` the lower triangular
    Cholesky factor of the permuted covariance.  The factor is re-derived here by
    :func:`numpy.linalg.cholesky` and never written out in closed form: the
    bivariate factor as printed in the secondary literature carries a
    ``(1 - rho)^(1/2)`` where ``FF' = Sigma`` requires ``(1 - rho^2)^(1/2)``, and
    copying it would misprice every share on a correlated pair.
    """
    idx = np.asarray(perm, dtype=np.intp)
    f = np.linalg.cholesky(sigma[np.ix_(idx, idx)])
    v = psi[idx] @ f
    total = float(psi @ sigma @ psi)
    if not np.isfinite(total) or total <= 0.0:
        raise ValueError(
            "the efficient-price innovation has non-positive variance, so there is "
            "no variance to share out. The residual covariance is degenerate; "
            "check the panel for a series that never moved."
        )
    out = np.empty(idx.size, dtype=np.float64)
    out[idx] = (v * v) / total
    return out


def _orderings(n: int) -> List[Tuple[int, ...]]:
    """Cholesky orderings that between them attain both bounds, for any ``n``.

    Up to four series every permutation is enumerated, which is what the
    literature prescribes and cheap enough to do.  Beyond that ``n!`` is not, so
    the enumeration exploits a property of the Cholesky factorisation: a series'
    share depends only on the SET of series ordered ahead of it, never on the
    order within that set.  Sequential orthogonalisation makes the ``k``-th
    factor the innovation of series ``i`` residualised on exactly the series
    preceding it, and residualising on a set does not care in what sequence the
    set is written.  So enumerating ``(subset, i, rest)`` for every series and
    every subset of the others reaches every value ``n!`` orderings can produce,
    in ``n * 2^(n-1)`` fits instead of ``n!``.

    **What is NOT done here, and why.**  The standard shortcut in the literature
    is to take the upper bound from placing the series first and the lower from
    placing it last, i.e. two orderings.  That is exact for two series -- there
    are only two orderings -- and false in general.  Over random covariance and
    weight vectors at three series it picks the wrong extreme for roughly two
    thirds of systems, and still for about a third when the weights and every
    covariance are positive.  The rule needs the cross term
    ``2 psi_1 psi_2 sigma_12`` to have a sign it is not entitled to, and a fitted
    panel supplies negative long-run weights readily -- any market that is
    estimated to adjust the "wrong" way produces one.  Enumerating is cheap;
    assuming is wrong.
    """
    if n <= 4:
        return list(itertools.permutations(range(n)))
    if n > _MAX_ENUMERATED_SERIES:
        raise ValueError(
            f"{n} series would need {n * 2 ** (n - 1)} Cholesky orderings to bound "
            f"the information share exactly. Price discovery over more than "
            f"{_MAX_ENUMERATED_SERIES} quotes of one underlying is almost certainly "
            f"the wrong question anyway; narrow the panel, or pin a single ordering "
            f"with order=... and read the docstring on why that is not a bound."
        )
    out = set()
    for i in range(n):
        others = [j for j in range(n) if j != i]
        for size in range(n):
            for pre in itertools.combinations(others, size):
                rest = [j for j in others if j not in pre]
                out.add(tuple(list(pre) + [i] + rest))
    return sorted(out)


#: Smallest eigenvalue the innovation CORRELATION matrix may have.  Scale-free, so
#: it means the same thing whether prices are in ticks or basis points.  A
#: correlation of 0.9 leaves an eigenvalue of 0.1 and a correlation of 0.9999
#: leaves 1e-4, both far above this: near-singular is a legitimate answer here and
#: is reported as an interval approaching [0, 1], not refused.
_MIN_CORRELATION_EIGENVALUE = 1e-8

#: Smallest share of the largest innovation variance a series may carry and still
#: be treated as an independently quoted price rather than a derived leg.
_MIN_INNOVATION_VARIANCE_RATIO = 1e-12

#: Spread standard deviation, as a fraction of the price level, below which two
#: columns are taken to be one instrument written twice.  Relative because
#: subtracting a constant offset in floating point leaves rounding residue, not
#: zero.
_MIN_SPREAD_VARIATION_RATIO = 1e-11


def _check_cholesky(sigma: np.ndarray, columns: Tuple[str, ...]) -> None:
    """Refuse a covariance that has no usable Cholesky factor, on purpose.

    The test is on the smallest eigenvalue of the correlation matrix and NOT on
    whether :func:`numpy.linalg.cholesky` happens to raise.  An exactly singular
    covariance -- which is what two series driven by one innovation produce --
    leaves a final pivot that is zero in exact arithmetic and a rounding residue
    in floating point.  Whether that residue lands just above or just below zero
    decides whether LAPACK raises, so relying on the exception makes the guard a
    coin flip; when it lands above, the factor is real but its last column is
    numerical dust, and the share computed from it is arbitrarily large nonsense
    that still sums to one with its partner.
    """
    diag = np.diag(sigma)
    if not np.all(np.isfinite(diag)) or np.any(diag <= 0.0):
        floor = 0.0
    else:
        # Relative, not against zero.  A series that is an exact linear function of
        # the regressors leaves a residual of rounding dust rather than nothing, so
        # its variance comes back as something like 1e-30 -- positive, so an
        # against-zero test passes it, and the correlation matrix built from it is
        # then dominated by round-off. Every share downstream is still finite and
        # still sums to one, which is precisely the shape of answer this module
        # exists not to hand back.
        floor = _MIN_INNOVATION_VARIANCE_RATIO * float(diag.max())
    if not np.all(np.isfinite(diag)) or np.any(diag <= floor):
        dead = [c for c, v in zip(columns, diag) if not (v > floor)]
        raise ValueError(
            f"series {dead} have no innovation of their own: their residual "
            f"variance is negligible beside the rest of the panel, so they are an "
            f"exact function of the other prices rather than an independent quote "
            f"of the same underlying, and price discovery cannot attribute anything "
            f"to them. Check those columns really quote over the session requested "
            f"and are not a leg derived arithmetically from the others."
        )
    corr = sigma / np.sqrt(np.outer(diag, diag))
    smallest = float(np.linalg.eigvalsh(corr)[0])
    if smallest > _MIN_CORRELATION_EIGENVALUE:
        try:
            np.linalg.cholesky(sigma)
            return
        except np.linalg.LinAlgError:
            pass
    off = corr - np.eye(len(columns))
    worst = int(np.argmax(np.abs(off)))
    i, j = divmod(worst, len(columns))
    raise ValueError(
        f"the residual covariance is singular (smallest correlation eigenvalue "
        f"{smallest:.3e}), so no Cholesky ordering exists and the Hasbrouck share "
        f"is undefined. The most correlated pair is {columns[i]}/{columns[j]} at "
        f"{off.flat[worst]:+.6f}. Two series driven by one innovation are one "
        f"series: check for a duplicated column, or a derived leg that is an exact "
        f"linear function of the others rather than an independently quoted price. "
        f"This is NOT the wide-bounds case -- innovations that merely correlate "
        f"strongly still factor, and report an interval close to [0, 1]."
    )


def information_share(panel: pd.DataFrame, order: Optional[Sequence[str]] = None,
                      lags: int = 5, coint_pvalue: float = 0.05) -> pd.DataFrame:
    """Hasbrouck (1995) information share, as an interval rather than a number.

    Each series' share of the variance of the efficient-price innovation, read off
    the VECM through its Wold and Beveridge-Nelson representations.  Because the
    long-run impact matrix has rank one, all the information about which market
    moves the common trend is in one vector ``psi``, and the share is that
    vector's contribution through a Cholesky factor of the innovation covariance.

    **The Cholesky factorisation makes the answer depend on the order the series
    are written in, and reporting one number hides that.**  So this returns
    ``is_lower``, ``is_upper`` and ``is_mid`` over every ordering that can change
    the answer, and flags an interval wider than
    :data:`UNINFORMATIVE_BOUND_WIDTH`.  Quoting a point estimate without the
    bounds is the classic misuse of this statistic, and the interval is not a
    nicety: in the Baillie et al. bivariate model with equal adjustment speeds and
    innovation correlation 0.9 it runs from 0.05 to 0.95, so the same fit supports
    "this market does everything" and "this market does nothing" depending only on
    which name was typed first.

    ``is_mid`` is Baillie et al.'s suggestion and is reported for continuity with
    the literature, not endorsed: Lien and Shrestha point out it corresponds to no
    factor structure, and for three or more series the midpoints do not generally
    sum to one.  Shares within any SINGLE ordering do sum to one exactly.

    The bounds are found by enumeration rather than by the usual shortcut of
    reading the upper bound off the series placed first and the lower off the
    series placed last -- see :func:`_orderings` for the measurement showing that
    shortcut picks the wrong extreme most of the time once there are three
    series.

    ``order`` pins one Cholesky ordering, given as a permutation of the panel's
    column names, and returns just that ordering's shares in ``is_ordered`` with
    the position each series took.  It is there for reproducing a published
    ordering or for inspecting the mechanism, and the deliberately different
    column name is so that a pinned result cannot be mistaken for a bound.
    """
    if _is_empty_panel(panel):
        return _empty(_IS_ORDERED_COLUMNS if order is not None else _IS_BOUND_COLUMNS)

    fit = vecm_fit(panel, lags=lags, coint_pvalue=coint_pvalue)
    columns = fit["columns"]
    psi = fit["psi"]
    sigma = fit["sigma"]
    _check_cholesky(sigma, columns)

    if order is not None:
        wanted = [str(c) for c in order]
        if sorted(wanted) != sorted(columns):
            raise ValueError(
                f"order {wanted} is not a permutation of the panel's series "
                f"{list(columns)}. Pass every column name exactly once, or leave "
                f"order=None to get the bounds over all orderings."
            )
        perm = [columns.index(c) for c in wanted]
        shares = _shares_for_order(psi, sigma, perm)
        position = np.empty(len(columns), dtype=np.int64)
        position[np.asarray(perm, dtype=np.intp)] = np.arange(len(columns))
        return pd.DataFrame(
            {"is_ordered": shares, "order_position": position},
            index=pd.Index(list(columns), dtype=object, name="series"),
        )

    grid = np.vstack([_shares_for_order(psi, sigma, p)
                      for p in _orderings(len(columns))])
    lower = grid.min(axis=0)
    upper = grid.max(axis=0)
    width = upper - lower
    return pd.DataFrame(
        {
            "is_lower": lower,
            "is_upper": upper,
            "is_mid": 0.5 * (lower + upper),
            "bound_width": width,
            "bounds_uninformative": width > UNINFORMATIVE_BOUND_WIDTH,
        },
        index=pd.Index(list(columns), dtype=object, name="series"),
    )


def component_share(panel: pd.DataFrame, lags: int = 5,
                    coint_pvalue: float = 0.05) -> pd.DataFrame:
    """Gonzalo-Granger permanent-transitory component share, from the same VECM.

    Each series' weight in the common permanent component, ``CS_j = alpha_perp_j /
    sum_k alpha_perp_k``, where ``alpha_perp`` spans the left null space of the
    error-correction loadings.  A market that does not adjust to the spread is a
    market the others come to, and that is the whole content of the statistic.

    **It is not a worse-behaved Hasbrouck share, it is a different question.**  It
    is a function of the adjustment loadings ALONE and ignores the innovation
    covariance entirely.  That is why it needs no Cholesky ordering, has no bounds
    and is unique -- and equally why it cannot distinguish two markets that adjust
    at the same speed but whose innovations differ in size.  Where Hasbrouck asks
    what fraction of the efficient-price innovation VARIANCE came from a market,
    Gonzalo-Granger asks that market's weight in the COMPOSITION of the
    innovation.  In the Baillie et al. example the component share is pinned at
    0.50 while the Hasbrouck interval spans [0.05, 0.95].  Those two lines
    disagreeing is the model working, not a bug, and a study that reports only
    whichever of them was more flattering has thrown away the comparison that
    makes the pair worth computing.

    ``cs_out_of_range`` marks a share outside [0, 1].  It is left in rather than
    clipped: the shares still sum to one by construction, so a negative one means
    the fit says a market moves AWAY from the spread, which is either a real and
    interesting reading or a sign the lag order is wrong -- and clipping would
    disguise both as a market that simply contributes nothing.
    """
    if _is_empty_panel(panel):
        return _empty(_CS_COLUMNS)

    fit = vecm_fit(panel, lags=lags, coint_pvalue=coint_pvalue)
    columns = fit["columns"]
    alpha_perp = fit["alpha_perp"]
    total = float(alpha_perp.sum())
    if abs(total) <= np.sqrt(np.finfo(np.float64).eps) * float(
            np.linalg.norm(alpha_perp)):
        raise ValueError(
            "the common-factor weights sum to zero, so the Gonzalo-Granger share "
            "has no denominator and no market can be given a fraction of the "
            "permanent component. This happens when the adjustment loadings offset "
            "exactly; the Hasbrouck share via information_share is still defined "
            "here, as is the raw alpha_perp on the vecm_fit result."
        )
    cs = alpha_perp / total
    return pd.DataFrame(
        {
            "cs": cs,
            "alpha_perp": alpha_perp,
            "cs_out_of_range": (cs < 0.0) | (cs > 1.0),
        },
        index=pd.Index(list(columns), dtype=object, name="series"),
    )
