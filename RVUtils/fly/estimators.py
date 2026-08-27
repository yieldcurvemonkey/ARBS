"""The linear algebra behind :mod:`RVUtils.fly`.

Everything here works on a leg panel ``Y`` (``T x n``, one column per leg, in
leg order) and a *signed* base weight vector ``x`` - signed meaning the vector
that actually multiplies the leg rates, so an ARBS fly arrives as
``(-1, +2, -1)`` and a curve as ``(-1, +1)``, never as the unsigned
``risk_weights`` magnitudes the structure builders carry.

That distinction matters. ``Query/IRSwaps/IRSwapValue.py``'s
``_swap_structure_sign_mapper`` force-flips a fly's wings negative and its belly
positive whatever the builder produced. That is right for a hand-specified
package and wrong for a fitted one: a PCA hedge on a steep curve can legitimately
want a wing on the same side as the belly, and silently flipping it would turn
the hedge into an anti-hedge. These estimators therefore keep the sign the solve
produced and the caller recombines the legs directly rather than routing back
through the pricer's sign map. Sign flips relative to the base are counted and
reported rather than corrected.
"""
from __future__ import annotations

import warnings
from typing import Dict, List, Optional, Sequence, Tuple

import numpy as np
import pandas as pd

from RVUtils.fly.schema import WeightingSchema

__all__ = [
    "combine",
    "default_anchor",
    "default_factors",
    "pc_exposure",
    "second_moment",
    "pc_loadings",
    "weights_from_moment",
    "solve_weights",
]


def pc_exposure(weights, Q: np.ndarray, k: int = 3) -> np.ndarray:
    """The package's exposure to each of the first ``k`` components, ``w' E``.

    The thing a neutrality claim is checked against. Zero in a slot means the
    package carries no risk to that component; on a ``pcaneutral`` fit the first
    ``n_pc`` slots come back at machine zero and the rest do not - that residual
    is the trade.
    """
    E = pc_loadings(np.asarray(Q, dtype=float), int(k))
    return np.asarray(weights, dtype=float) @ E


def default_anchor(n_legs: int) -> int:
    """Which leg the normalisation pins.

    Odd leg counts pin the middle - the belly of a fly, the centre of a condor's
    ladder - because that is the leg a trader sizes off and the one the Stack
    Exchange answer holds at 2. Even leg counts pin the back leg, which makes a
    two-leg schema reproduce the ordinary beta-weighted curve ``(-beta, +1)``.
    """
    if n_legs < 2:
        raise ValueError("a weighting schema needs at least two legs")
    return n_legs // 2 if n_legs % 2 else n_legs - 1


def default_factors(n_legs: int) -> np.ndarray:
    """Factor portfolios for ``method="beta"``, as an ``n x m`` matrix.

    Three legs give dm63's pair exactly: the wing curve ``(-1, 0, 1)`` (his
    ``2s10s``) and the belly outright ``(0, 1, 0)`` (his ``5y``). Regressing the
    fly on those two and trading the residual is his
    ``(-(1 - b1), 2 - b2, -(1 + b1))``.

    Two legs give the front leg alone, so ``w = x - beta f`` collapses to the
    textbook beta-weighted curve. Four or more legs fall back to a level/slope
    pair, because there is no canonical desk convention past a fly and a made-up
    one would be worse than an obvious one.
    """
    if n_legs == 2:
        return np.array([[1.0], [0.0]])
    if n_legs == 3:
        return np.array([[-1.0, 0.0], [0.0, 1.0], [1.0, 0.0]])
    level = np.full(n_legs, 1.0 / n_legs)
    slope = np.linspace(-1.0, 1.0, n_legs)
    return np.column_stack([level, slope])


def second_moment(X: np.ndarray, *, center: bool = True, matrix: str = "cov") -> np.ndarray:
    """The ``n x n`` matrix the weighting solves against.

    ``center=True`` demeans first, giving the ordinary sample covariance and an
    OLS-with-intercept ``beta``. ``center=False`` gives the raw second moment
    ``X'X / (T - 1)``, which is what ``np.linalg.pinv(X) @ y`` computes in the
    Stack Exchange snippet - identical on zero-mean changes, different on levels
    or on a drifting sample.
    """
    A = np.asarray(X, dtype=float)
    if A.ndim != 2:
        raise ValueError("expected a 2-D matrix of observations")
    rows = A.shape[0]
    if rows < 2:
        raise ValueError("need at least two observations for a second moment")
    if center:
        A = A - A.mean(axis=0, keepdims=True)
    Q = (A.T @ A) / float(rows - 1)
    if matrix == "corr":
        scales = np.sqrt(np.diag(Q))
        scales = np.where(scales > 0.0, scales, 1.0)
        Q = Q / np.outer(scales, scales)
    return Q


def pc_loadings(Q: np.ndarray, k: int = 1) -> np.ndarray:
    """The ``k`` leading eigenvectors of ``Q``, orthonormal, descending, sign-pinned.

    Signs are pinned so each component's largest-magnitude loading is positive -
    the same convention as ``df_based_pca_risk_model.fit_curve_pca_from_timeseries
    (pin_signs=True)``. Pinning makes a single fit reproducible; it is not
    continuity across refits, and a rolling PCA can still flip a component
    between windows when two eigenvalues cross. Every method here is invariant
    to a component's sign (``x_i / p_i`` and ``P P' x`` both are), so the flip
    does not reach the weights.
    """
    eigenvalues, eigenvectors = np.linalg.eigh(np.asarray(Q, dtype=float))
    order = np.argsort(eigenvalues)[::-1]
    V = eigenvectors[:, order[: int(k)]]
    for j in range(V.shape[1]):
        column = V[:, j]
        if column[np.argmax(np.abs(column))] < 0:
            V[:, j] = -column
    return V


# --------------------------------------------------------------------------- #
# per-method solves
# --------------------------------------------------------------------------- #


def _solve_pca(Q: np.ndarray, x: np.ndarray, schema: WeightingSchema) -> np.ndarray:
    """Attack68 method 1: divide the base risks by the PC1 loadings.

    ``w_i = x_i / p_i``. For a zero-sum base this is PC1-neutral outright, since
    ``sum_i (x_i / p_i) p_i = sum_i x_i``. It has one failure mode, raised on the
    thread by Thrastylon: a leg whose PC1 loading is near zero sends its weight
    to infinity. ``eps`` is the floor, relative to the largest loading.
    """
    p = pc_loadings(Q, 1)[:, 0]
    floor = schema.eps * float(np.max(np.abs(p)))
    if np.any(np.abs(p) <= max(floor, np.finfo(float).tiny)):
        raise np.linalg.LinAlgError(
            "a PC1 loading is numerically zero; 'pca' cannot divide by it. "
            "Use method='pca_proj', which projects instead of dividing."
        )
    return x / p


def _solve_pca_proj(Q: np.ndarray, x: np.ndarray, schema: WeightingSchema) -> np.ndarray:
    """Attack68's 2021 addendum: the minimal risk change that zeroes PC risk.

    Minimise ``d' I d`` subject to ``(x + d)' P = 0``. The KKT system

    ``[[2I, P], [P', 0]] [d; lam] = [0; -x' P]``

    solves to ``d = -P (P'P)^-1 P' x``, i.e. ``w`` is ``x`` projected onto the
    orthogonal complement of the neutralised components. With orthonormal ``P``
    that is just ``w = x - P P' x``. On the thread's own PC1
    ``(0.660, 0.604, 0.447)`` and base ``(-1, 2, -1)`` this returns
    ``(-1.1002, 2, -1.0780)`` after the belly is rescaled to 2.
    """
    k = min(schema.resolved_n_pc, Q.shape[0] - 1)
    if k < 1:
        raise ValueError("n_pc must leave at least one degree of freedom")
    P = pc_loadings(Q, k)
    return x - P @ (P.T @ x)


def _solve_pcaneutral(Q: np.ndarray, x: np.ndarray, schema: WeightingSchema) -> np.ndarray:
    """Pin the anchor leg; make the package EXACTLY neutral to the first k PCs.

    This is the construction in Attack68's *"Construct a butterfly interest rate
    portfolio to eliminate PCA exposures"*. With the belly fixed at -1 and the
    wings free, requiring ``S' E_1,2 = [0, 0]`` is a 2x2 linear system in the two
    wing weights, which that answer inverts in closed form. Written for a general
    leg count and a general k it is::

        (x_H + d_H)' E_k[H]  =  -x_a * E_k[a]

    a ``k x (n-1)`` system for the free legs ``H``. Three legs and two components
    make it square and the answer unique - which is the fact the companion
    thread *"Hedging a trade for PCA component neutrality"* pins down: *"in a 3
    instrument configuration if PC1 and PC2 are made neutral the only valid
    solution is for the trade to be a multiple of PC3."* ``tests/test_fly_weighting.py``
    checks that this really does come back proportional to PC3 rather than
    taking the thread's word for it.

    With more legs than constraints the system is under-determined and the
    minimum-norm ``lstsq`` solution is taken - the SMALLEST CHANGE to the trade
    you asked for, the same tie-break the companion thread argues for.

    Differs from ``pca_proj`` in what is held: this pins the anchor and moves
    everything else, so the belly's risk is exactly what you specified. On a
    three-leg fly the two agree up to scale, because both land on the only
    PC1/PC2-neutral direction there is.

    Both threads carry the same warning, and it is the reason for the guards
    below: *"these weights might be very unstable depending upon small
    correlation/covariance changes."*
    """
    n = len(x)
    k = schema.resolved_n_pc
    a = schema.anchor if schema.anchor is not None else default_anchor(n)
    if not (0 <= a < n):
        raise ValueError(f"anchor {a} is outside the {n} legs")
    if k > n - 1:
        raise ValueError(
            f"'pcaneutral' pins one leg and spends one degree of freedom per component, so it needs "
            f"n_pc <= n_legs - 1; got n_pc={k} for {n} legs. Two components need three legs."
        )

    E = pc_loadings(Q, k)                      # n x k
    hedge = [i for i in range(n) if i != a]
    A = E[hedge].T                             # k x (n-1)
    target = -float(x[a]) * E[a] - A @ x[hedge]

    singular = np.linalg.svd(A, compute_uv=False)
    if singular[-1] <= 1e-10 * singular[0]:
        raise np.linalg.LinAlgError(
            "the free legs' loadings on the neutralised components are collinear in this window; "
            "no weighting makes the package neutral to all of them"
        )

    delta, *_ = np.linalg.lstsq(A, target, rcond=None)
    w = np.empty(n, dtype=float)
    w[a] = x[a]
    w[hedge] = np.asarray(x)[hedge] + delta
    return w


def _solve_beta(Q: np.ndarray, x: np.ndarray, schema: WeightingSchema) -> np.ndarray:
    """dm63's multivariable least squares, in weight space.

    Regressing the package series ``Y x`` on the factor series ``Y F`` gives
    ``beta = ((YF)'(YF))^-1 (YF)'(Yx) = (F' Q F)^-1 F' Q x``, and the residual
    the trade is meant to harvest is ``Y (x - F beta)``. So the weights are
    ``w = x - F beta`` - no need to form the series at all.
    """
    F = np.asarray(schema.factors, dtype=float).T if schema.factors is not None else default_factors(len(x))
    if F.ndim != 2 or F.shape[0] != len(x):
        raise ValueError(f"factors must be m vectors of length {len(x)}, got shape {F.shape}")
    A = F.T @ Q @ F
    b = F.T @ Q @ x
    if np.linalg.cond(A) > 1e10:
        raise np.linalg.LinAlgError("factor portfolios are collinear in this window; beta is undefined")
    return x - F @ np.linalg.solve(A, b)


def _solve_minvar(Q: np.ndarray, x: np.ndarray, schema: WeightingSchema) -> np.ndarray:
    """Attack68 method 2: pin the anchor leg, minimise the package's variance.

    With the anchor's risk held at ``x_a``, the remaining legs solve
    ``w_H = -Q_HH^-1 Q_Ha x_a``, which is the GLS hedge of the anchor onto the
    others. It is the lowest-variance package containing that anchor position by
    construction, in sample; the thread's own out-of-sample test found it a
    close second to the regression weights.
    """
    n = len(x)
    a = schema.anchor if schema.anchor is not None else default_anchor(n)
    if not (0 <= a < n):
        raise ValueError(f"anchor {a} is outside the {n} legs")
    hedge = [i for i in range(n) if i != a]
    Q_hh = Q[np.ix_(hedge, hedge)]
    q_ha = Q[np.ix_(hedge, [a])].ravel()
    if np.linalg.cond(Q_hh) > 1e10:
        raise np.linalg.LinAlgError("the hedge legs are collinear in this window; min-variance is undefined")
    w = np.empty(n, dtype=float)
    w[a] = x[a]
    w[hedge] = -np.linalg.solve(Q_hh, q_ha * float(x[a]))
    return w


_SOLVERS = {
    "pca": _solve_pca,
    "pca_proj": _solve_pca_proj,
    "pcaneutral": _solve_pcaneutral,
    "beta": _solve_beta,
    "minvar": _solve_minvar,
}


def _normalize(w: np.ndarray, x: np.ndarray, schema: WeightingSchema) -> np.ndarray:
    """Put the solved weights on the same scale as the base package."""
    if schema.normalize == "none":
        return w
    if schema.normalize == "l1":
        gross = float(np.sum(np.abs(w)))
        if gross <= 0.0:
            raise np.linalg.LinAlgError("degenerate solve: all weights are zero")
        return w * (float(np.sum(np.abs(x))) / gross)
    a = schema.anchor if schema.anchor is not None else default_anchor(len(x))
    if abs(w[a]) < np.finfo(float).eps:
        raise np.linalg.LinAlgError(f"degenerate solve: anchor leg {a} came out at zero weight")
    return w * (float(x[a]) / float(w[a]))


def weights_from_moment(
    Q: np.ndarray,
    base: Sequence[float],
    schema: WeightingSchema,
) -> np.ndarray:
    """One weight vector from one second-moment matrix. Raises on a bad solve.

    This is the whole numeric core; everything above it is windowing. Kept
    public so a caller can reproduce a single day's weights - or feed a
    hand-built covariance, which is how the Stack Exchange numbers are pinned in
    ``tests/test_fly_weighting.py``.
    """
    x = np.asarray(base, dtype=float)
    if schema.is_identity:
        return x.copy()
    Q = np.asarray(Q, dtype=float)
    if Q.shape != (len(x), len(x)):
        raise ValueError(f"moment matrix {Q.shape} does not match {len(x)} legs")
    if not np.all(np.isfinite(Q)):
        raise np.linalg.LinAlgError("moment matrix contains non-finite entries")

    w = _normalize(_SOLVERS[schema.method](Q, x, schema), x, schema)

    anchor = schema.anchor if schema.anchor is not None else default_anchor(len(x))
    scale = abs(float(w[anchor]))
    if scale > 0.0 and float(np.max(np.abs(w))) > schema.max_abs_ratio * scale:
        raise np.linalg.LinAlgError(
            f"solve produced a weight more than {schema.max_abs_ratio}x the anchor leg "
            f"({np.max(np.abs(w)):.4g} vs {scale:.4g}); refusing to return it"
        )
    if not np.all(np.isfinite(w)):
        raise np.linalg.LinAlgError("solve produced non-finite weights")
    return w


# --------------------------------------------------------------------------- #
# windowing
# --------------------------------------------------------------------------- #


def _window_starts(index: pd.Index, schema: WeightingSchema, n_valid: int, valid_pos: np.ndarray) -> np.ndarray:
    """First usable-row offset for each usable row, per the window kind."""
    window = schema.window
    if window.kind in ("static", "expanding"):
        return np.zeros(n_valid, dtype=int)
    if window.kind == "obs":
        return np.maximum(np.arange(n_valid) - window.size + 1, 0)
    stamps = pd.DatetimeIndex(pd.to_datetime(index[valid_pos]))
    cutoffs = stamps - window.offset
    # (t - offset, t]: searchsorted "right" excludes the cutoff itself.
    return np.searchsorted(stamps.values, cutoffs.values, side="right")


def solve_weights(
    legs: pd.DataFrame,
    base: Sequence[float],
    schema: WeightingSchema,
) -> pd.DataFrame:
    """The ``T x n`` weight frame for ``legs`` under ``schema``.

    ``legs`` is the leg panel in leg order, in whatever units the legs are
    quoted; ``base`` is the signed base weight vector. The result is indexed
    like ``legs`` and columned like ``legs``, with ``NaN`` rows wherever the
    window had too little data or the solve was rejected.

    Two properties worth stating because they are easy to assume wrongly:

    * The weights multiply the leg **levels** to form the package series. When
      the weights move, part of the resulting series' change is the weights
      moving rather than the market - fine for monitoring a rich/cheap
      residual, wrong as a P&L. For a P&L take the weight frame from
      ``df.attrs["fly_weights"]`` and form ``w[t-1] . dy[t]`` yourself.
    * With ``schema.window`` static the single fit uses the whole panel,
      including rows after each date it is applied to.
    """
    if not isinstance(legs, pd.DataFrame):
        raise TypeError("legs must be a DataFrame with one column per leg")
    x = np.asarray(base, dtype=float)
    n = legs.shape[1]
    if len(x) != n:
        raise ValueError(f"base has {len(x)} weights for {n} leg columns")

    out = pd.DataFrame(np.nan, index=legs.index, columns=legs.columns, dtype=float)
    if schema.is_identity:
        out.loc[:, :] = x
        out.attrs["fit_rows"] = int(len(legs))
        out.attrs["rejected_rows"] = 0
        return out
    if legs.empty:
        return out

    Y = legs.to_numpy(dtype=float)
    if schema.basis == "chgs":
        X_all = np.full_like(Y, np.nan)
        d = schema.diff_periods
        if len(Y) > d:
            X_all[d:] = Y[d:] - Y[:-d]
    else:
        X_all = Y

    valid = np.isfinite(X_all).all(axis=1)
    valid_pos = np.flatnonzero(valid)
    n_valid = int(valid_pos.size)
    min_obs = schema.min_obs if schema.min_obs is not None else max(2 * n + 1, 10)
    if n_valid < min_obs:
        warnings.warn(
            f"RVUtils.fly: only {n_valid} usable rows for a {n}-leg '{schema.label}' fit "
            f"(need {min_obs}); every weight is NaN.",
            RuntimeWarning,
            stacklevel=2,
        )
        return out

    Xv = X_all[valid_pos]
    rejected: List[str] = []

    if schema.window.is_static:
        try:
            w = weights_from_moment(second_moment(Xv, center=schema.center, matrix=schema.matrix), x, schema)
        except (np.linalg.LinAlgError, ValueError) as exc:
            raise np.linalg.LinAlgError(f"RVUtils.fly '{schema.label}' static fit failed: {exc}") from exc
        solved = np.tile(w, (n_valid, 1))
    else:
        starts = _window_starts(legs.index, schema, n_valid, valid_pos)
        solved = np.full((n_valid, n), np.nan)
        last: Optional[np.ndarray] = None
        for i in range(n_valid):
            if schema.refit_every > 1 and (i % schema.refit_every) and last is not None:
                solved[i] = last
                continue
            a = int(starts[i])
            block = Xv[a : i + 1]
            if block.shape[0] < min_obs:
                last = None
                continue
            try:
                last = weights_from_moment(
                    second_moment(block, center=schema.center, matrix=schema.matrix), x, schema
                )
            except (np.linalg.LinAlgError, ValueError) as exc:
                last = None
                if len(rejected) < 3:
                    rejected.append(str(exc))
                continue
            solved[i] = last

    frame = pd.DataFrame(solved, index=legs.index[valid_pos], columns=legs.columns)
    if schema.lag:
        frame = frame.shift(schema.lag)
    out.loc[frame.index, :] = frame.to_numpy()

    fitted = int(np.isfinite(out.to_numpy()).all(axis=1).sum())
    if rejected:
        warnings.warn(
            f"RVUtils.fly '{schema.label}': {n_valid - fitted} of {n_valid} windows produced no weights. "
            f"First reasons: {'; '.join(rejected)}",
            RuntimeWarning,
            stacklevel=2,
        )

    flips = _sign_flips(out, x)
    anchor = schema.anchor if schema.anchor is not None else default_anchor(n)
    values = out.to_numpy(dtype=float)
    finite = np.isfinite(values).all(axis=1)
    worst = (
        float(np.nanmax(np.abs(values[finite]) / abs(x[anchor]))) if finite.any() and x[anchor] else float("nan")
    )
    out.attrs["fit_rows"] = fitted
    out.attrs["rejected_rows"] = int(n_valid - fitted)
    out.attrs["sign_flips"] = flips
    out.attrs["max_abs_ratio_seen"] = worst

    if np.isfinite(worst) and worst > schema.warn_abs_ratio:
        loud = int((np.abs(values[finite]).max(axis=1) / abs(x[anchor]) > schema.warn_abs_ratio).sum())
        hint = (
            " Dividing by a small PC1 loading is what does this; method='pca_proj' projects instead "
            "and does not blow up."
            if schema.method == "pca"
            else ""
        )
        warnings.warn(
            f"RVUtils.fly '{schema.label}': {loud} of {fitted} fitted windows put a leg more than "
            f"{schema.warn_abs_ratio}x the anchor weight (worst {worst:.2f}x). Those days dominate whatever "
            f"you build from this.{hint}",
            RuntimeWarning,
            stacklevel=2,
        )
    if flips:
        warnings.warn(
            f"RVUtils.fly '{schema.label}': legs {sorted(flips)} took the opposite sign to the base package "
            "on at least one date. That is kept, not corrected - a fitted hedge is allowed to want it - "
            "but it means the structure is no longer a conventional fly on those dates.",
            RuntimeWarning,
            stacklevel=2,
        )
    return out


def _sign_flips(frame: pd.DataFrame, base: np.ndarray) -> Dict[str, int]:
    """How many dates each leg's fitted weight opposed its base sign."""
    values = frame.to_numpy(dtype=float)
    flips: Dict[str, int] = {}
    for j, column in enumerate(frame.columns):
        if base[j] == 0.0:
            continue
        opposed = np.isfinite(values[:, j]) & (np.sign(values[:, j]) == -np.sign(base[j]))
        count = int(opposed.sum())
        if count:
            flips[str(column)] = count
    return flips


def combine(
    legs: pd.DataFrame,
    weight_frame: pd.DataFrame,
    multiplier: float = 1.0,
    mode: str = "level",
) -> pd.Series:
    """Turn a leg panel and a weight path into ONE series.

    ``mode`` is :attr:`WeightingSchema.resolved_combine_mode`:

    ``"level"``
        ``multiplier * sum_i w_i(t) * leg_i(t)``. Exact, and correct when the
        weights do not move.
    ``"pnl"``
        ``anchor + cumsum(multiplier * sum_i w_i(t-1) * dleg_i(t))``. The
        weights held over each move, so none of the series is weight drift. See
        the ``combine_mode`` docs on :class:`~RVUtils.fly.schema.WeightingSchema`
        for why that distinction is worth 180 bp/day of spurious volatility on a
        monthly-refit fly.
    ``"current"``
        ``multiplier * sum_i w_i(T) * leg_i(t)`` - the last fitted weights over
        the whole history.
    """
    n = len(legs.columns)
    aligned = weight_frame.reindex(index=legs.index, columns=legs.columns)
    scale = float(multiplier)

    if mode == "level":
        return (legs * aligned).sum(axis=1, min_count=n) * scale

    if mode == "current":
        fitted = aligned.dropna(how="any")
        if fitted.empty:
            return pd.Series(np.nan, index=legs.index)
        last = fitted.iloc[-1]
        return (legs * last).sum(axis=1, min_count=n) * scale

    if mode != "pnl":
        raise ValueError(f"combine mode must be level/pnl/current, got {mode!r}")

    # Difference across the DENSE rows, not the raw index. A frame joined with
    # another product carries that product's calendar, and a date with no leg
    # mark is not a day the position went flat - the move simply lands on the
    # next date there IS a mark. Differencing the raw index would drop it.
    dense = legs.notna().all(axis=1)
    L = legs[dense]
    W = aligned[dense]
    if len(L) < 2:
        return pd.Series(np.nan, index=legs.index)

    steps = (L.diff() * W.shift(1)).sum(axis=1, min_count=n) * scale
    first = steps.first_valid_index()
    if first is None:
        return pd.Series(np.nan, index=legs.index)

    start = L.index.get_loc(first) - 1
    anchor = float((L.iloc[start] * W.iloc[start]).sum() * scale)

    path = pd.Series(np.nan, index=L.index, dtype=float)
    tail = steps.iloc[start + 1 :]
    gaps = int(tail.isna().sum())
    path.iloc[start] = anchor
    path.iloc[start + 1 :] = anchor + tail.fillna(0.0).cumsum().to_numpy()

    if gaps:
        # A skipped step is a move the series does not contain. Say so rather
        # than let a hole read as a flat day.
        warnings.warn(
            f"RVUtils.fly: {gaps} of {len(tail)} steps had no weights and were carried flat in the "
            "'pnl' series.",
            RuntimeWarning,
            stacklevel=2,
        )
    return path.reindex(legs.index)
