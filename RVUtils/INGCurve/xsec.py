"""F-ING-v2: per-day CROSS-SECTIONAL fair-value curve residuals (ledger L-0035).

WHY THIS MODULE EXISTS (the v1 fidelity gap, ledger row L-0015): v1's
:mod:`RVUtils.INGCurve.screen` built the residual as a walk-forward
time-series PC1 deviation.  That construction FAILED to reproduce ING's
published 2020-01-15 worked example ("Rates Strategy: Deconstructing the EUR
yield curve", 2020-01-15): ING's value-vs-carry frontier that day has slope
~-1.27 with R^2 ~0.93; the v1 residual read R^2 0.03.  ING's fair value is a
PER-DAY CROSS-SECTIONAL construction - a smooth curve fitted through that
day's non-overlapping 1y forward strip, with value = deviation from the fit -
not a time-series factor model.

This module keeps v1's bootstrap / forward strip / roll-down / percentile /
frontier machinery (imported, not copied) and replaces ONLY the residual:

    residual_k = f(k) - smooth_fit(k)   [bp],  fitted per day, k cross-section

Two registered fit variants, kept separate everywhere (the fit choice is
exactly what a later placebo battery must scale-match):

*   ``poly``   - ordinary least squares cubic polynomial in k
                 (:data:`POLY_DEGREE` = 3, pinned).
*   ``spline`` - least-squares cubic B-spline with FIXED knots
                 :data:`SPLINE_KNOTS` = (1, 3, 7, 15, 29); boundary knots are
                 clamped to the data's k-range (on the primary panel k starts
                 at 2, so the lower boundary knot clamps 1 -> 2 - documented,
                 deterministic, no free parameter).

Both fits are LINEAR PROJECTIONS of the day's forward vector: residual
= (I - H) f with a hat matrix H that depends only on the k-grid.  H is
exposed (:func:`fit_matrix`, :func:`fit_diagnostics`) so tests can assert
exact hat-matrix identities and so the placebo battery can scale-match the
smoother (leverages, model dof = trace(H)).

FIT UNIVERSE (deviation from the naive "k=1..29" reading, stated): the
primary panel fits k = 2..29 on EVERY day.  1F1Y is unobservable before the
RFR launch in this data (no sub-2Y par print; v1's finding) and the
bootstrap's constructed 1Y anchor moves f(1) by tens of bp - including a
construction point in the fit would distort every residual, and switching
the fit universe at the splice date would contaminate trailing percentile
windows that span it.  1F1Y residuals are available only as labeled side
numbers from separate builds (printed-only modern days, or the uniform
always-extrapolate construction).

The per-day construction has NO ramp-in and NO time dependence: permuting
the other rows of the panel cannot change a day's residual (tested).  Only
the trailing percentile ranks (reused from v1) look backward.

Episode machinery: :func:`episode_reversion_gate` counts NON-OVERLAPPING
dislocation episodes only - once a tenor fires at its trailing 5th/95th
percentile, the next event for that tenor counts only after the episode
resolves (residual crosses its trailing median) or ``episode_cap`` (63)
business days elapse.  This fixes v1's inflated event counts (L-0015 (a)).

Everything here is descriptive screening - no strategy config is examined
and no trial is consumed (L-0035 accounting).

All rate inputs are PERCENT; residual outputs are bp.
"""

from __future__ import annotations

from typing import Dict, Iterable, Optional, Sequence, Tuple

import numpy as np
import pandas as pd

# Reuse v1's machinery by IMPORT (never copy the bootstrap).
from RVUtils.INGCurve.screen import (  # noqa: F401  (re-exported for runners)
    INTEGER_TENORS,
    annual_forwards,
    bootstrap_discounts,
    daily_frontier,
    forward_labels,
    integer_par_grid,
    residual_percentiles,
    rolldown_3m,
)

__all__ = [
    "POLY_DEGREE",
    "SPLINE_KNOTS",
    "VARIANTS",
    "fit_matrix",
    "fit_diagnostics",
    "xsec_residuals",
    "episode_reversion_gate",
    # v1 re-exports (unchanged machinery)
    "INTEGER_TENORS",
    "annual_forwards",
    "bootstrap_discounts",
    "daily_frontier",
    "forward_labels",
    "integer_par_grid",
    "residual_percentiles",
    "rolldown_3m",
]

#: Registered fit configuration (F-ING-v2, ledger L-0035).  Changing either
#: constant is a REGISTRATION CHANGE, not a tuning knob; the test suite pins
#: both the constants and the realized model dof (trace of the hat matrix).
POLY_DEGREE = 3
SPLINE_KNOTS = (1.0, 3.0, 7.0, 15.0, 29.0)
VARIANTS = ("poly", "spline")


# ---------------------------------------------------------------------------
# hat matrices
# ---------------------------------------------------------------------------

def _poly_hat(ks: np.ndarray, degree: int) -> np.ndarray:
    """OLS hat matrix for a degree-``degree`` polynomial in k (standardized)."""
    t = (ks - ks.mean()) / ks.std()
    X = np.vander(t, degree + 1, increasing=True)
    return X @ np.linalg.pinv(X)


def _bspline_design(x: np.ndarray, t: np.ndarray, k: int = 3) -> np.ndarray:
    """Cubic B-spline design matrix at points ``x`` for knot vector ``t``."""
    from scipy.interpolate import BSpline

    try:
        return BSpline.design_matrix(x, t, k, extrapolate=True).toarray()
    except (AttributeError, TypeError):  # older scipy: build column by column
        n = len(t) - k - 1
        B = np.empty((x.size, n))
        for i in range(n):
            c = np.zeros(n)
            c[i] = 1.0
            B[:, i] = BSpline(t, c, k, extrapolate=True)(x)
        return B


def _spline_hat(
    ks: np.ndarray, knots: Sequence[float]
) -> Tuple[np.ndarray, Tuple[float, ...]]:
    """LSQ cubic-spline hat matrix with fixed knots, boundaries clamped.

    ``knots`` are the registered knots (first/last = boundary).  Boundary
    knots are clamped to the observed k-range; interior knots must fall
    strictly inside it.  Returns ``(H, knots_used)``.
    """
    knots = tuple(float(v) for v in knots)
    if len(knots) < 2 or any(b <= a for a, b in zip(knots, knots[1:])):
        raise ValueError(f"knots must be strictly increasing, got {knots}")
    lo = max(knots[0], float(ks.min()))
    hi = min(knots[-1], float(ks.max()))
    interior = [v for v in knots[1:-1] if lo < v < hi]
    if len(interior) != len(knots) - 2:
        dropped = [v for v in knots[1:-1] if not (lo < v < hi)]
        raise ValueError(
            f"interior knots {dropped} fall outside the data k-range "
            f"[{lo}, {hi}] - the registered knot set does not apply to this grid"
        )
    knots_used = (lo, *interior, hi)
    t = np.r_[[lo] * 4, interior, [hi] * 4]
    B = _bspline_design(ks.astype(float), t, 3)
    n_basis = B.shape[1]
    rank = np.linalg.matrix_rank(B)
    if rank != n_basis:
        raise AssertionError(
            f"spline design matrix rank {rank} < {n_basis} basis functions - "
            "knot placement leaves an unidentified basis (Schoenberg-Whitney); "
            "the fit would silently change dof"
        )
    return B @ np.linalg.pinv(B), knots_used


def fit_matrix(
    ks: Iterable[int],
    variant: str,
    degree: int = POLY_DEGREE,
    knots: Sequence[float] = SPLINE_KNOTS,
) -> np.ndarray:
    """Hat (projection) matrix H of the registered smooth fit on grid ``ks``.

    ``residual_vector = (I - H) @ forward_vector`` for every day - the fits
    are linear, so planted-shock arithmetic is exact:
    a +b bump on tenor j moves residual_i by ``b * (I - H)[i, j]``.
    """
    ks = np.asarray(list(ks), dtype=float)
    if ks.size < 8 or np.any(np.diff(ks) <= 0):
        raise ValueError("ks must be an increasing grid with at least 8 points")
    if variant == "poly":
        return _poly_hat(ks, degree)
    if variant == "spline":
        return _spline_hat(ks, knots)[0]
    raise ValueError(f"unknown variant {variant!r}; registered: {VARIANTS}")


def fit_diagnostics(
    ks: Iterable[int],
    variant: str,
    degree: int = POLY_DEGREE,
    knots: Sequence[float] = SPLINE_KNOTS,
) -> Dict[str, object]:
    """Leverages / dof of the fit - the scale-matching handle for placebos."""
    ks_arr = np.asarray(list(ks), dtype=float)
    if variant == "spline":
        H, knots_used = _spline_hat(ks_arr, knots)
    else:
        H = fit_matrix(ks_arr, variant, degree=degree, knots=knots)
        knots_used = None
    return {
        "variant": variant,
        "ks": [int(k) for k in ks_arr],
        "model_dof": float(np.trace(H)),
        "resid_dof": float(len(ks_arr) - np.trace(H)),
        "leverage": {int(k): float(h) for k, h in zip(ks_arr, np.diag(H))},
        "knots_used": knots_used,
        "poly_degree": degree if variant == "poly" else None,
    }


# ---------------------------------------------------------------------------
# per-day cross-sectional residuals
# ---------------------------------------------------------------------------

def xsec_residuals(
    forwards_pct: pd.DataFrame,
    variant: str,
    degree: int = POLY_DEGREE,
    knots: Sequence[float] = SPLINE_KNOTS,
) -> pd.DataFrame:
    """Per-day cross-sectional fair-value residuals, in bp.

    ``forwards_pct``: date x k forward strip in PERCENT (columns = integer
    forward-start years, e.g. the k >= 2 slice of
    ``annual_forwards(bootstrap_discounts(dense), include_spot=True)``).

    For each day the registered smooth curve is fitted through f(k) across
    the columns and ``residual_k = (f(k) - fit(k)) * 100``.  Days with any
    NaN forward get all-NaN residuals (the projection needs the full
    cross-section; partial-grid days are not silently refit on a different
    universe).
    """
    ks = list(forwards_pct.columns)
    H = fit_matrix(ks, variant, degree=degree, knots=knots)
    F = forwards_pct.to_numpy(dtype=float)
    M = np.eye(len(ks)) - H
    resid = (F @ M.T) * 100.0  # percent -> bp; M symmetric, .T for clarity
    bad = np.isnan(F).any(axis=1)
    resid[bad] = np.nan
    return pd.DataFrame(resid, index=forwards_pct.index, columns=ks)


# ---------------------------------------------------------------------------
# non-overlapping episode reversion gate
# ---------------------------------------------------------------------------

def episode_reversion_gate(
    residuals_bp: pd.DataFrame,
    rank: pd.DataFrame,
    p50: pd.DataFrame,
    low: float = 0.05,
    high: float = 0.95,
    horizons: Tuple[int, ...] = (21, 63),
    episode_cap: int = 63,
    revert_frac: float = 0.5,
    restrict_mask: Optional[pd.Series] = None,
) -> Tuple[pd.DataFrame, pd.DataFrame]:
    """NON-OVERLAPPING dislocation episodes per tenor (fixes v1's L-0015 (a)).

    An episode OPENS on the first day t0 where the trailing rank is
    <= ``low`` or >= ``high`` (rank, residual and trailing median all
    non-NaN) while no episode is open for that tenor.  It RESOLVES on the
    first later day where the residual crosses its (current, updating)
    trailing median - ``sign(r_u - p50_u)`` flips or hits zero - or after
    ``episode_cap`` business days, whichever comes first.  Days inside an
    open episode can NOT open a new one; the scan resumes the day after
    resolution.  Episodes still open at the end of the sample are recorded
    as ``resolved_by='censored'``.

    Dislocation ``d = r_t0 - p50_t0``; reversion at horizon h is
    ``sign(d) * (r_t0 - r_{t0+h})`` (toward the fire-date trailing median;
    can exceed |d| on overshoot).  Episodes whose ``t0 + max(horizons)``
    falls beyond the sample are counted (``n_episodes``) but EXCLUDED from
    every reversion statistic (``n_complete``).

    ``restrict_mask``: optional bool Series over dates; when given, ONLY
    episodes whose fire date has ``mask == True`` enter the per-tenor stats
    (episode detection itself always runs on the full panel - restricting
    the mask must not let a mid-episode day open a "new" episode).

    Returns ``(per_tenor_stats, episodes)``:

    *   ``per_tenor_stats``: one row per tenor ('kF1Y') - n_episodes,
        n_complete, med_abs_dislocation_bp, med_reversion_{h}bd,
        frac_revert_gt{f}pct_{cap}bd, frac_median_cross, med_episode_len_bd.
    *   ``episodes``: one row per episode - tenor, fire/resolve dates,
        dislocation, per-horizon reversion, resolved_by, episode_len_bd,
        in_restriction.
    """
    max_h = max(horizons)
    idx = residuals_bp.index
    n = len(idx)
    if restrict_mask is not None:
        mask_arr = restrict_mask.reindex(idx).fillna(False).to_numpy(dtype=bool)
    else:
        mask_arr = np.ones(n, dtype=bool)

    ep_rows = []
    for c in residuals_bp.columns:
        r = residuals_bp[c].to_numpy(dtype=float)
        rk = rank[c].to_numpy(dtype=float)
        med = p50[c].to_numpy(dtype=float)
        label = f"{c}F1Y" if not str(c).endswith("F1Y") else str(c)
        t = 0
        while t < n:
            fire = (
                not np.isnan(rk[t])
                and not np.isnan(r[t])
                and not np.isnan(med[t])
                and (rk[t] <= low or rk[t] >= high)
            )
            if not fire:
                t += 1
                continue
            d = r[t] - med[t]
            if d == 0.0:  # rank extreme but exactly at median: not a dislocation
                t += 1
                continue
            sgn = np.sign(d)
            end = None
            resolved_by = "censored"
            for u in range(t + 1, min(t + episode_cap, n - 1) + 1):
                if not np.isnan(r[u]) and not np.isnan(med[u]):
                    if sgn * (r[u] - med[u]) <= 0.0:
                        end = u
                        resolved_by = "median_cross"
                        break
            if end is None:
                if t + episode_cap <= n - 1:
                    end = t + episode_cap
                    resolved_by = "cap"
                else:
                    end = n - 1  # censored at sample end
            row = {
                "tenor": label,
                "fire_date": idx[t],
                "resolve_date": idx[end],
                "dislocation_bp": float(d),
                "rank_at_fire": float(rk[t]),
                "side": "cheap" if sgn > 0 else "rich",
                "resolved_by": resolved_by,
                "episode_len_bd": int(end - t),
                "complete": bool(t + max_h <= n - 1),
                "in_restriction": bool(mask_arr[t]),
            }
            for h in horizons:
                if t + h <= n - 1:
                    row[f"reversion_{h}bd"] = float(sgn * (r[t] - r[t + h]))
                else:
                    row[f"reversion_{h}bd"] = np.nan
            ep_rows.append(row)
            t = end + 1

    episodes = pd.DataFrame(ep_rows)
    stat_rows = []
    tenor_labels = [
        f"{c}F1Y" if not str(c).endswith("F1Y") else str(c)
        for c in residuals_bp.columns
    ]
    for label in tenor_labels:
        if len(episodes):
            sub = episodes[(episodes["tenor"] == label) & episodes["in_restriction"]]
        else:
            sub = episodes
        comp = sub[sub["complete"]] if len(sub) else sub
        row = {
            "tenor": label,
            "n_episodes": int(len(sub)),
            "n_complete": int(len(comp)),
        }
        if len(comp):
            absd = comp["dislocation_bp"].abs()
            row["med_abs_dislocation_bp"] = float(absd.median())
            for h in horizons:
                row[f"med_reversion_{h}bd"] = float(comp[f"reversion_{h}bd"].median())
            frac_key = (
                f"frac_revert_gt{int(revert_frac * 100)}pct_{max_h}bd"
            )
            row[frac_key] = float(
                (comp[f"reversion_{max_h}bd"] / absd > revert_frac).mean()
            )
            row["frac_median_cross"] = float(
                (comp["resolved_by"] == "median_cross").mean()
            )
            row["med_episode_len_bd"] = float(comp["episode_len_bd"].median())
        else:
            row["med_abs_dislocation_bp"] = np.nan
            for h in horizons:
                row[f"med_reversion_{h}bd"] = np.nan
            row[f"frac_revert_gt{int(revert_frac * 100)}pct_{max_h}bd"] = np.nan
            row["frac_median_cross"] = np.nan
            row["med_episode_len_bd"] = np.nan
        stat_rows.append(row)
    per_tenor = pd.DataFrame(stat_rows).set_index("tenor")
    return per_tenor, episodes
