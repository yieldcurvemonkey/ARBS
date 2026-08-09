"""Copula bounds on the sum of FOMC meeting outcomes, and the lambda coordinate.

ZQ fed funds futures pin the *marginal* hike probability at each FOMC meeting. SR3 options
give the full risk-neutral law of the day-weighted *sum* of those meetings. Marginals fix
``E[K]``. They do not fix ``Var(K)``: the free parameter is the coupling between meetings,
and that parameter is the trade.

    lambda = +1   comonotone    one uniform drives every meeting -- "the Fed hikes at all,
                                or it does not"; the sum is maximally two-state
    lambda =  0   independent   meetings are separate coin flips -- "one hike, timing
                                uncertain"; the sum diffuses
    lambda = -1   min-variance  the LP optimum -- "one and done"

Because any payoff LINEAR in ``K`` is copula-free, there is no copula-free arbitrage between
the ZQ strip and SR3 options: lambda is not a mispricing, it is an unobservable the market
must price. That splits cleanly into two tiers and only two:

* HARD -- ``Var_RND`` outside ``[Var_min, Var_com]`` is a genuine static arbitrage. Rare,
  cheap to check daily, and checked by :func:`variance_bounds_violation`.
* SOFT -- inside the interval, lambda versus a prior is a view trade.

The one-parameter family
------------------------
:func:`mixture_sum_distribution` interpolates by MIXING COUPLINGS, not by mixing some ad-hoc
parameter: a convex combination of couplings is itself a coupling, so every lambda in
``[-1, +1]`` is attainable by an actual joint law with the right marginals, and ``E[K]`` is
constant along the whole family. That matters for the diagnostic the framework rests on --
if the observed RND lay inside this family, ``lambda_wing`` and ``lambda_var`` would agree
exactly. They are emitted separately precisely so that their DISAGREEMENT is visible, and it
means the RND has left the one-parameter family. That is information, not something to
average away.
"""

from __future__ import annotations

import itertools
import math
from dataclasses import dataclass
from typing import Optional, Sequence, Tuple

import numpy as np

__all__ = [
    "CouplingBounds",
    "comonotone_sum_distribution",
    "independent_sum_distribution",
    "extremal_sum_distribution",
    "mixture_sum_distribution",
    "coupling_bounds",
    "wing_mass",
    "sum_variance",
    "lambda_from_statistic",
    "variance_bounds_violation",
    "categorical_comonotone_sum",
    "categorical_independent_sum",
    "categorical_min_variance_sum",
    "three_point_marginal",
    "fold_to_binary_support",
]

#: 2**n joint cells are enumerated for the LP, so the meeting count has to stay small. Every
#: SR3 contract window carries 2-4 FOMC meetings; 16 is a backstop, not a working limit.
_MAX_LP_MEETINGS = 16


def _validate(marginals: Sequence[float]) -> np.ndarray:
    p = np.asarray(marginals, dtype=float)
    if p.ndim != 1 or p.size == 0:
        raise ValueError("marginals must be a non-empty 1-D sequence of probabilities")
    if not np.all(np.isfinite(p)):
        raise ValueError("marginals must all be finite")
    if np.any(p < -1e-12) or np.any(p > 1.0 + 1e-12):
        raise ValueError(f"marginals must lie in [0, 1], got {p.tolist()}")
    return np.clip(p, 0.0, 1.0)


def comonotone_sum_distribution(marginals: Sequence[float]) -> np.ndarray:
    """Law of ``K = sum_i B_i`` under the comonotone (upper Frechet) coupling.

    Every meeting is driven by the same uniform, ``B_i = 1{U <= p_i}``, so ``K`` counts how
    many thresholds ``U`` fell below: ``P(K >= k)`` is simply the k-th largest marginal, and
    the atom probabilities are the successive differences of the sorted survival levels.

    Returns an array of length ``n + 1`` indexed by ``k``.
    """
    p = _validate(marginals)
    n = p.size
    # Survival levels, descending: P(K >= 1) >= P(K >= 2) >= ... >= P(K >= n).
    survival = np.sort(p)[::-1]
    padded = np.concatenate([[1.0], survival, [0.0]])
    probs = padded[:-1] - padded[1:]
    return _clean(probs, n)


def independent_sum_distribution(marginals: Sequence[float]) -> np.ndarray:
    """Law of ``K = sum_i B_i`` under independence: the Bernoulli convolution."""
    p = _validate(marginals)
    probs = np.array([1.0])
    for p_i in p:
        shifted = np.concatenate([[0.0], probs])
        probs = np.concatenate([probs, [0.0]]) * (1.0 - p_i) + shifted * p_i
    return _clean(probs, p.size)


def _clean(probs: np.ndarray, n: int) -> np.ndarray:
    out = np.asarray(probs, dtype=float)
    if out.size != n + 1:
        raise AssertionError(f"expected {n + 1} atoms, built {out.size}")
    out = np.clip(out, 0.0, None)
    total = float(out.sum())
    if total <= 0.0:
        raise AssertionError("degenerate sum distribution")
    return out / total


@dataclass(frozen=True)
class ExtremalSolution:
    """Outcome of the LP over joint laws with fixed marginals."""

    probs: np.ndarray
    variance: float
    feasible: bool
    status: str


def extremal_sum_distribution(
    marginals: Sequence[float],
    *,
    objective: str = "min_variance",
) -> ExtremalSolution:
    """Extremal law of ``K`` over every coupling with the given Bernoulli marginals.

    ``Var(K) = E[K^2] - E[K]^2`` and ``E[K] = sum_i p_i`` is the same under every coupling,
    so minimising the variance is minimising ``E[K^2]``, which is LINEAR in the joint
    distribution over the ``2^n`` cells. Hence an exact LP rather than a heuristic bound --
    the naive "concentrate on the two integers either side of the mean" law is frequently
    not attainable, and using it where it is infeasible would manufacture a lambda.

    ``objective="max_variance"`` is included because its answer is known in closed form (it
    is the comonotone coupling), which makes it a standing check on the LP itself.
    """
    p = _validate(marginals)
    n = p.size
    if objective not in {"min_variance", "max_variance"}:
        raise ValueError(f"objective must be 'min_variance' or 'max_variance', got {objective!r}")
    if n > _MAX_LP_MEETINGS:
        raise ValueError(
            f"{n} meetings would need 2**{n} LP columns; cap is {_MAX_LP_MEETINGS}. "
            "Aggregate meetings before calling."
        )

    if n == 1:
        probs = np.array([1.0 - p[0], p[0]])
        return ExtremalSolution(probs, float(sum_variance(probs)), True, "trivial")

    from scipy.optimize import linprog

    cells = np.array(list(itertools.product([0, 1], repeat=n)), dtype=float)  # (2**n, n)
    k_of_cell = cells.sum(axis=1)
    cost = k_of_cell ** 2
    if objective == "max_variance":
        cost = -cost

    # sum(pi) == 1, and for each meeting i the cells with bit i set carry mass p_i.
    a_eq = np.vstack([np.ones((1, cells.shape[0])), cells.T])
    b_eq = np.concatenate([[1.0], p])

    res = linprog(cost, A_eq=a_eq, b_eq=b_eq, bounds=(0.0, 1.0), method="highs")
    if not res.success:
        # Marginals in [0,1] always admit the independent coupling, so infeasibility here is
        # numerical, not structural. Fall back to the coupling we can always name.
        fallback = independent_sum_distribution(p)
        return ExtremalSolution(fallback, float(sum_variance(fallback)), False, str(res.message))

    joint = np.clip(np.asarray(res.x, dtype=float), 0.0, None)
    probs = np.zeros(n + 1, dtype=float)
    np.add.at(probs, k_of_cell.astype(int), joint)
    probs = _clean(probs, n)
    return ExtremalSolution(probs, float(sum_variance(probs)), True, "optimal")


def mixture_sum_distribution(marginals: Sequence[float], lam: float) -> np.ndarray:
    """The one-parameter coupling family evaluated at ``lam``.

    ``lam`` in ``[0, 1]`` mixes independent into comonotone; ``lam`` in ``[-1, 0]`` mixes
    independent into the LP min-variance coupling. A mixture of couplings is a coupling, so
    every point of the family is realisable and every point has the same ``E[K]``.
    """
    lam = float(lam)
    if not -1.0 - 1e-12 <= lam <= 1.0 + 1e-12:
        raise ValueError(f"lam must lie in [-1, 1], got {lam}")
    lam = min(max(lam, -1.0), 1.0)
    base = independent_sum_distribution(marginals)
    if lam >= 0.0:
        other = comonotone_sum_distribution(marginals)
        return (1.0 - lam) * base + lam * other
    other = extremal_sum_distribution(marginals, objective="min_variance").probs
    return (1.0 + lam) * base + (-lam) * other


def wing_mass(probs: Sequence[float]) -> float:
    """``P(K = 0) + P(K = n)``: the mass in the two extreme atoms.

    Preferred over a peak COUNT because it is threshold-free. A peak count depends on a
    prominence cutoff, and reporting it as evidence hides that dependence.
    """
    arr = np.asarray(probs, dtype=float)
    if arr.size < 2:
        raise ValueError("need at least two atoms for a wing mass")
    return float(arr[0] + arr[-1])


def sum_variance(probs: Sequence[float]) -> float:
    """``Var(K)`` for a law supported on ``0..n``, in units of (whole meeting moves)^2."""
    arr = np.asarray(probs, dtype=float)
    k = np.arange(arr.size, dtype=float)
    total = float(arr.sum())
    if total <= 0.0:
        return float("nan")
    arr = arr / total
    mean = float(np.dot(k, arr))
    return float(np.dot(k * k, arr) - mean * mean)


def lambda_from_statistic(
    observed: float,
    *,
    independent: float,
    comonotone: float,
    min_variance: Optional[float] = None,
) -> float:
    """Place an observed statistic on the lambda coordinate.

    Normalised so that independent maps to 0, comonotone to +1, and -- when a min-variance
    anchor is supplied -- the LP optimum to -1. The two sides are scaled separately because
    the interval is not symmetric about the independent point; pretending it is would report
    a lambda whose magnitude means different things above and below zero.

    Returns NaN when the relevant anchor is degenerate, never a fabricated 0.
    """
    obs = float(observed)
    ind = float(independent)
    if not math.isfinite(obs) or not math.isfinite(ind):
        return float("nan")

    if obs >= ind:
        span = float(comonotone) - ind
        if not math.isfinite(span) or abs(span) < 1e-12:
            return float("nan")
        return (obs - ind) / span

    if min_variance is None:
        return float("nan")
    span = ind - float(min_variance)
    if not math.isfinite(span) or abs(span) < 1e-12:
        return float("nan")
    return (obs - ind) / span


@dataclass(frozen=True)
class CouplingBounds:
    """Every anchor needed to place one session's RND on the lambda coordinate."""

    marginals: Tuple[float, ...]
    expected_k: float

    probs_comonotone: np.ndarray
    probs_independent: np.ndarray
    probs_min_variance: np.ndarray

    wing_comonotone: float
    wing_independent: float
    wing_min_variance: float

    var_comonotone: float
    var_independent: float
    var_min_variance: float

    lp_feasible: bool
    lp_status: str

    def lambda_wing(self, observed_wing_mass: float) -> float:
        return lambda_from_statistic(
            observed_wing_mass,
            independent=self.wing_independent,
            comonotone=self.wing_comonotone,
            min_variance=self.wing_min_variance,
        )

    def lambda_var(self, observed_variance: float) -> float:
        return lambda_from_statistic(
            observed_variance,
            independent=self.var_independent,
            comonotone=self.var_comonotone,
            min_variance=self.var_min_variance,
        )


def coupling_bounds(marginals: Sequence[float]) -> CouplingBounds:
    """Build the comonotone / independent / min-variance anchors for one meeting set."""
    p = _validate(marginals)
    comon = comonotone_sum_distribution(p)
    indep = independent_sum_distribution(p)
    lp = extremal_sum_distribution(p, objective="min_variance")
    return CouplingBounds(
        marginals=tuple(float(x) for x in p),
        expected_k=float(p.sum()),
        probs_comonotone=comon,
        probs_independent=indep,
        probs_min_variance=lp.probs,
        wing_comonotone=wing_mass(comon),
        wing_independent=wing_mass(indep),
        wing_min_variance=wing_mass(lp.probs),
        var_comonotone=sum_variance(comon),
        var_independent=sum_variance(indep),
        var_min_variance=lp.variance,
        lp_feasible=lp.feasible,
        lp_status=lp.status,
    )


# ---------------------------------------------------------------------------------------
# Categorical marginals: what happens to lambda when 50bp moves are live
# ---------------------------------------------------------------------------------------
# The binary framing is what makes ZQ pin each marginal EXACTLY. Admit a 50bp move and ZQ
# gives only the MEAN of each marginal, not its shape -- one equation, two unknowns per
# meeting. Marginal shape and copula then stop being separately identified from ZQ + SR3
# alone, and the extra dispersion that size uncertainty puts into the sum gets booked as
# dependence. The bias runs one way: UPWARD. These functions exist to measure how big it is,
# not to pretend it away.


def _validate_categorical(marginals: Sequence[Sequence[float]]) -> List[np.ndarray]:
    out: List[np.ndarray] = []
    for i, row in enumerate(marginals):
        arr = np.asarray(row, dtype=float)
        if arr.ndim != 1 or arr.size < 1:
            raise ValueError(f"marginal {i} must be a non-empty 1-D pmf over step counts 0..m")
        if np.any(arr < -1e-12) or not np.isfinite(arr).all():
            raise ValueError(f"marginal {i} must be a finite non-negative pmf, got {arr.tolist()}")
        total = float(arr.sum())
        if abs(total - 1.0) > 1e-6:
            raise ValueError(f"marginal {i} must sum to 1, got {total}")
        out.append(np.clip(arr, 0.0, None) / total)
    return out


def categorical_comonotone_sum(marginals: Sequence[Sequence[float]]) -> np.ndarray:
    """Law of ``sum_i X_i`` under the comonotone coupling, ``X_i`` supported on ``0..m_i``.

    One uniform drives everything: ``X_i = F_i^{-1}(U)``. Partition ``[0, 1]`` at every CDF
    breakpoint of every marginal; on each cell all the ``X_i`` are constant, so the sum is
    constant and the cell's width is that sum's probability.
    """
    pmfs = _validate_categorical(marginals)
    cdfs = [np.cumsum(p) for p in pmfs]
    breaks = np.unique(np.clip(np.concatenate([np.array([0.0, 1.0])] + cdfs), 0.0, 1.0))
    n_max = int(sum(len(p) - 1 for p in pmfs))
    out = np.zeros(n_max + 1, dtype=float)
    for lo, hi in zip(breaks[:-1], breaks[1:]):
        width = float(hi - lo)
        if width <= 0.0:
            continue
        mid = 0.5 * (lo + hi)
        total = int(sum(int(np.searchsorted(c, mid, side="left")) for c in cdfs))
        out[min(total, n_max)] += width
    return out / out.sum()


def categorical_independent_sum(marginals: Sequence[Sequence[float]]) -> np.ndarray:
    """Law of ``sum_i X_i`` under independence: repeated convolution of the pmfs."""
    pmfs = _validate_categorical(marginals)
    probs = np.array([1.0])
    for pmf in pmfs:
        probs = np.convolve(probs, pmf)
    return probs / probs.sum()


def categorical_min_variance_sum(marginals: Sequence[Sequence[float]]) -> ExtremalSolution:
    """Minimum-variance coupling of categorical marginals, by LP over the product cells."""
    from scipy.optimize import linprog

    pmfs = _validate_categorical(marginals)
    sizes = [len(p) for p in pmfs]
    n_cells = int(np.prod(sizes))
    if n_cells > 200_000:
        raise ValueError(f"{n_cells} LP columns is too many; aggregate meetings first")

    cells = np.array(list(itertools.product(*[range(s) for s in sizes])), dtype=float)
    k_of_cell = cells.sum(axis=1)
    n_max = int(sum(s - 1 for s in sizes))

    rows: List[np.ndarray] = [np.ones(n_cells)]
    rhs: List[float] = [1.0]
    for i, pmf in enumerate(pmfs):
        for v in range(len(pmf) - 1):  # the last value is implied by the rest plus the total
            rows.append((cells[:, i] == v).astype(float))
            rhs.append(float(pmf[v]))

    res = linprog(k_of_cell ** 2, A_eq=np.vstack(rows), b_eq=np.array(rhs),
                  bounds=(0.0, 1.0), method="highs")
    if not res.success:
        fallback = categorical_independent_sum(marginals)
        return ExtremalSolution(fallback, float(sum_variance(fallback)), False, str(res.message))

    joint = np.clip(np.asarray(res.x, dtype=float), 0.0, None)
    probs = np.zeros(n_max + 1, dtype=float)
    np.add.at(probs, k_of_cell.astype(int), joint)
    probs = probs / probs.sum()
    return ExtremalSolution(probs, float(sum_variance(probs)), True, "optimal")


def three_point_marginal(expected_steps: float, size_mix: float) -> np.ndarray:
    """A ``{0, 25, 50}`` marginal with the mean ZQ pins and a chosen 50bp share.

    ``expected_steps`` is the meeting's expected move in units of 25bp (so ZQ's number),
    ``size_mix`` in ``[0, 1]`` is the fraction of that expected move delivered as 50bp steps
    rather than 25bp ones. ``size_mix = 0`` returns the binary marginal exactly. Raises when
    the requested mix is not a probability -- there is no silent clipping, because a clipped
    marginal no longer has the mean ZQ pinned.
    """
    e = float(expected_steps)
    s = float(size_mix)
    if not 0.0 <= s <= 1.0:
        raise ValueError(f"size_mix must lie in [0, 1], got {s}")
    p2 = s * e / 2.0
    p1 = e - 2.0 * p2
    p0 = 1.0 - p1 - p2
    if min(p0, p1, p2) < -1e-12:
        raise ValueError(
            f"size_mix={s} with expected_steps={e} implies a negative probability "
            f"({p0:.3f}, {p1:.3f}, {p2:.3f}); ZQ's mean cannot be met with this mix"
        )
    return np.clip(np.array([p0, p1, p2], dtype=float), 0.0, None)


def fold_to_binary_support(probs: Sequence[float], n_binary: int) -> np.ndarray:
    """Fold a law on ``0..m`` onto the binary lattice's ``0..n`` support by absorbing the top.

    A three-point marginal can reach beyond the binary lattice, and the observed density is
    bucketed with its own tails absorbed into the end atoms. Folding the model the same way
    is what keeps the comparison like for like.
    """
    arr = np.asarray(probs, dtype=float)
    n = int(n_binary)
    if arr.size <= n + 1:
        out = np.zeros(n + 1, dtype=float)
        out[: arr.size] = arr
        return out
    out = arr[: n + 1].copy()
    out[-1] += float(arr[n + 1 :].sum())
    return out


def variance_bounds_violation(observed_variance: float, bounds: CouplingBounds, *, tol: float = 0.0) -> float:
    """Signed distance outside ``[Var_min, Var_com]``; 0.0 when inside.

    Positive means the RND carries more variance than ANY coupling of these marginals can
    produce, negative means less. Either is a genuine static arbitrage against the ZQ strip
    rather than a view -- the HARD tier. NaN in gives NaN out.
    """
    obs = float(observed_variance)
    if not math.isfinite(obs):
        return float("nan")
    if obs > bounds.var_comonotone + tol:
        return obs - bounds.var_comonotone
    if obs < bounds.var_min_variance - tol:
        return obs - bounds.var_min_variance
    return 0.0
