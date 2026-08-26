"""Cross-sectional and walk-forward residuals on the kink grid, in bp.

C1 module of the CvxSuite (docs/cvxsuite/DESIGN.md section 3).  Imports repo
kernels only (``RVUtils.df_based_pca_risk_model``, ``RVUtils.ConvexityRV.holee``)
-- never another ``RVUtils.CvxSuite`` module.

What lives here
---------------
*   :func:`hat_matrix` / :func:`fit_diagnostics` / :func:`xsec_residuals` --
    per-day cross-sectional fair-value residuals as an EXACT LINEAR PROJECTION:
    ``residual = (I - H) @ levels`` with a hat matrix that depends only on the
    fit abscissae.  This is a NEW float-k generalization of
    ``RVUtils.INGCurve.xsec.fit_matrix``.  The INGCurve original is a pinned
    registration (F-ING-v2, ledger L-0035: integer ks, knots (1, 3, 7, 15, 29),
    PERCENT in / bp out) and is neither edited nor imported here; its guard
    mechanics are reimplemented verbatim -- at least 8 strictly increasing ks,
    boundary knots clamped into the observed k-range, interior knots required
    strictly inside it, and a Schoenberg-Whitney rank assert so the model dof
    cannot silently change.
*   :func:`walk_forward_pca_residuals` -- monthly-frozen n-PC residuals,
    generalizing the ``RVUtils.INGCurve.screen.rolling_pc1_residuals`` pattern
    (fit strictly BEFORE each refit-period start, mean and loadings frozen
    within the period, NaN ramp-in below ``min_window``) to ``n_pcs`` factors
    via ``df_based_pca_risk_model.fit_curve_pca_from_timeseries(
    use_changes=False, matrix="cov")``.  Per-refit eigenvectors are greedily
    |cos|-matched to the previous refit before sign alignment -- the greedy
    match (reimplemented from ``ConvexityRV.factor_neutral_sizing._match_pcs``,
    tied out in tests) catches ROTATIONS (PC2/PC3 swapping rank on a short
    window), which sign-only alignment (``pca_rv.align_eigenvectors``) cannot.
    The matched |cos| per PC is reported as ``cos_prev`` -- the feed for
    ``gates.eigenvector_gap_gate``.
*   :func:`sign_agreement` -- cross-model agreement map (+1 both cheap, -1 both
    rich, 0 disagree/small, NaN where either input is missing).
*   :func:`convexity_adjustment_bp` / :func:`adjusted_levels` -- Ho-Lee
    forward-segment convexity adjustment, delegated to
    ``ConvexityRV.holee.ho_lee_ca_bp`` (see the function docstring for the
    model choice and the Salomon zero-coupon comparison).

Unit conventions (binding, DESIGN.md section 1)
-----------------------------------------------
bp in, bp out, EVERYWHERE in this module.  The nearby wrong path:
``INGCurve.xsec.xsec_residuals`` takes PERCENT and multiplies by 100 on the way
out; copying a panel between the two silently rescales every residual by 100x.
The level entry points here therefore carry a percent/decimal confusion guard:
they raise ``ValueError`` when the panel-wide median |level| is below
``min_median_abs_bp`` (default 20.0 -- reasoning, not measurement: any nominal
swap-forward panel quoted in percent has median |level| below ~10, while a full
USD forward grid in bp keeps its median well above 20 even across ZIRP because
the long-end forwards never printed below ~100 bp; pass
``min_median_abs_bp=0`` to disable deliberately).

Sign convention: residual > 0 = actual above fair value = CHEAP (for yields) --
the ``CurvePCAModel.residual`` convention ("> 0 => actual above PCA fair value
(cheap for yields)").

What this is NOT
----------------
*   NOT the registered F-ING-v2 fit: different default knots (1, 3, 7, 15, 27
    per DESIGN.md section 6 vs the registration's (1, 3, 7, 15, 29)), float fit
    abscissae, bp-in units, and no ledger registration.  Changing THIS module's
    defaults is a CvxSuite config change, not an INGCurve registration change.
*   NOT ``pca_rv.make_pca_rv_builder`` residuals: that builder's ``fit()`` is
    FULL-SAMPLE (look-ahead in residuals) unless ``fixed_loadings_date`` is
    passed.  Everything here is walk-forward by construction: mutating rows
    after a refit period cannot change any residual inside or before it
    (tested).
*   ``convexity_adjustment_bp`` is NOT the Citi PACK convention
    (``holee`` ``convention="citi"``, mean(T1^2)) -- see its docstring.

Grid note: with the DESIGN section 6 knots (1, 3, 7, 15, 27) and the KINK_GRID
fit abscissae 0.5 .. 45 years, the boundary knots lie INSIDE the observed
range, so no clamping occurs and the points beyond k = 27 (30y10y, 40y10y
midpoints 35 and 45) sit on the cubic extension of the last spline segment.
The projection stays exact (a global cubic is reproduced everywhere,
verified in tests), but leverage there is high -- ``fit_diagnostics`` exposes
per-k leverage precisely so the screen can print it.
"""

from __future__ import annotations

from typing import Dict, Iterable, Mapping, Sequence, Tuple, Union

import numpy as np
import pandas as pd

from RVUtils.df_based_pca_risk_model import fit_curve_pca_from_timeseries

__all__ = [
    "DEFAULT_KNOTS",
    "DEFAULT_DEGREE",
    "VARIANTS",
    "hat_matrix",
    "fit_diagnostics",
    "xsec_residuals",
    "walk_forward_pca_residuals",
    "sign_agreement",
    "convexity_adjustment_bp",
    "adjusted_levels",
]

#: CvxSuite fit configuration (DESIGN.md section 6: "xsec variant 'spline' with
#: knots (1,3,7,15,27)").  Deliberately NOT the INGCurve registration
#: (1, 3, 7, 15, 29) -- the kink grid extends to a 45y midpoint and its own
#: config is frozen in the DESIGN, not in the F-ING-v2 ledger.
DEFAULT_KNOTS: Tuple[float, ...] = (1.0, 3.0, 7.0, 15.0, 27.0)
DEFAULT_DEGREE = 3
VARIANTS = ("poly", "spline")


# ---------------------------------------------------------------------------
# hat matrices (float-k reimplementation of the INGCurve.xsec mechanics)
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

    Same mechanics as ``INGCurve.xsec._spline_hat`` (reimplemented, float ks):
    boundary knots are clamped INTO the observed k-range (``lo = max(knots[0],
    min(ks))``, ``hi = min(knots[-1], max(ks))``); interior knots must fall
    strictly inside ``(lo, hi)`` (``ValueError`` otherwise -- the configured
    knot set does not apply to that grid); data outside ``[lo, hi]`` is
    evaluated on the cubic extension of the end segments
    (``extrapolate=True``), which preserves exact cubic reproduction.  A design
    matrix with rank below the basis count raises ``AssertionError``
    (Schoenberg-Whitney guard: the fit must not silently change dof).
    Returns ``(H, knots_used)``.
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
            f"[{lo}, {hi}] - the configured knot set does not apply to this grid"
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


def _as_k_grid(ks: Iterable[float]) -> np.ndarray:
    ks_arr = np.asarray([float(k) for k in ks], dtype=float)
    if ks_arr.size < 8 or np.any(np.diff(ks_arr) <= 0):
        raise ValueError(
            "ks must be a strictly increasing grid with at least 8 points, "
            f"got {ks_arr.tolist()}"
        )
    return ks_arr


def hat_matrix(
    ks: Sequence[float],
    variant: str = "spline",
    *,
    degree: int = DEFAULT_DEGREE,
    knots: Sequence[float] = DEFAULT_KNOTS,
) -> np.ndarray:
    """Hat (projection) matrix H of the smooth fit on the float grid ``ks``.

    ``residual_vector = (I - H) @ level_vector`` for every day.  Both variants
    are LINEAR PROJECTIONS, so planted-shock arithmetic is exact: a +b bp bump
    on point j moves residual_i by ``b * (I - H)[i, j]``; H reproduces any
    cubic exactly and ``I - H`` annihilates the whole fit space (both tested).

    ``variant``: ``"poly"`` (OLS cubic in standardized k, model dof = degree+1)
    or ``"spline"`` (LSQ cubic B-spline on fixed knots, model dof = 4 +
    n_interior_knots).  Guards are the INGCurve.xsec mechanics, reimplemented
    for float ks -- see :mod:`RVUtils.CvxSuite.residuals` module docstring.
    """
    ks_arr = _as_k_grid(ks)
    if variant == "poly":
        return _poly_hat(ks_arr, degree)
    if variant == "spline":
        return _spline_hat(ks_arr, knots)[0]
    raise ValueError(f"unknown variant {variant!r}; registered: {VARIANTS}")


def fit_diagnostics(
    ks: Sequence[float],
    variant: str = "spline",
    *,
    degree: int = DEFAULT_DEGREE,
    knots: Sequence[float] = DEFAULT_KNOTS,
) -> Dict[str, object]:
    """Leverages / dof of the fit -- the scale-matching handle for placebos.

    Returns ``{"variant", "ks", "model_dof" (= trace(H)), "resid_dof",
    "leverage" (per-k diagonal of H), "knots_used", "poly_degree"}``.  The
    leverage map is the visibility handle for the KINK_GRID points beyond the
    last knot (35, 45) which sit on the cubic extension -- print it, do not
    hide it.
    """
    ks_arr = _as_k_grid(ks)
    if variant == "spline":
        H, knots_used = _spline_hat(ks_arr, knots)
    else:
        H = hat_matrix(ks_arr, variant, degree=degree, knots=knots)
        knots_used = None
    return {
        "variant": variant,
        "ks": [float(k) for k in ks_arr],
        "model_dof": float(np.trace(H)),
        "resid_dof": float(len(ks_arr) - np.trace(H)),
        "leverage": {float(k): float(h) for k, h in zip(ks_arr, np.diag(H))},
        "knots_used": knots_used,
        "poly_degree": degree if variant == "poly" else None,
    }


# ---------------------------------------------------------------------------
# percent/decimal-vs-bp confusion guard
# ---------------------------------------------------------------------------

def _assert_bp_scale(
    levels: pd.DataFrame, min_median_abs_bp: float, where: str
) -> None:
    """Raise loudly when a "bp" panel looks like percent or decimal units.

    The guard is the module's decided percent-vs-bp tripwire (tested with a
    negative control): panel-wide ``median(|level|) < min_median_abs_bp``
    raises, naming the offending median.  ``min_median_abs_bp <= 0`` disables
    (an explicit, spelled-out escape hatch -- never a silent one).
    """
    if not (min_median_abs_bp > 0):
        return
    arr = levels.to_numpy(dtype=float)
    if arr.size == 0 or np.all(np.isnan(arr)):
        raise ValueError(f"{where}: levels_bp is empty or all-NaN")
    med = float(np.nanmedian(np.abs(arr)))
    if med < min_median_abs_bp:
        raise ValueError(
            f"{where}: panel median |level| = {med:.6g} is below the bp-scale "
            f"guard ({min_median_abs_bp:g}); the input looks like percent or "
            "decimal units, not bp. Multiply by 100 (percent) or 1e4 (decimal), "
            "or pass min_median_abs_bp=0 to disable the guard deliberately."
        )


# ---------------------------------------------------------------------------
# per-day cross-sectional residuals
# ---------------------------------------------------------------------------

def xsec_residuals(
    levels_bp: pd.DataFrame,
    ks: Sequence[float],
    variant: str,
    *,
    degree: int = DEFAULT_DEGREE,
    knots: Sequence[float] = DEFAULT_KNOTS,
    min_median_abs_bp: float = 20.0,
) -> pd.DataFrame:
    """Per-day cross-sectional fair-value residuals.  bp in, bp out.

    ``levels_bp``: date x point panel in BP (columns are leg labels, e.g.
    "7y1y"); ``ks``: the fit abscissae in years, one per column IN COLUMN
    ORDER (the ``grids.k_coord`` midpoints for the kink grid).  For each day
    ``residual = (I - H) @ row`` -- no unit conversion (the INGCurve original
    multiplies percent by 100 here; this module does NOT, and the bp-scale
    guard raises if fed percent).  Days with ANY NaN level get ALL-NaN
    residuals: partial-grid days are never silently refit on a different
    universe.
    """
    ks_list = [float(k) for k in ks]
    if len(ks_list) != levels_bp.shape[1]:
        raise ValueError(
            f"ks has {len(ks_list)} entries but levels_bp has "
            f"{levels_bp.shape[1]} columns; they must align 1:1 in column order"
        )
    _assert_bp_scale(levels_bp, min_median_abs_bp, "xsec_residuals")
    H = hat_matrix(ks_list, variant, degree=degree, knots=knots)
    F = levels_bp.to_numpy(dtype=float)
    M = np.eye(len(ks_list)) - H
    resid = F @ M.T  # bp in -> bp out; M symmetric, .T for clarity
    bad = np.isnan(F).any(axis=1)
    resid[bad] = np.nan
    return pd.DataFrame(resid, index=levels_bp.index, columns=levels_bp.columns)


# ---------------------------------------------------------------------------
# walk-forward PCA residuals (monthly-frozen loadings, n_pcs factors)
# ---------------------------------------------------------------------------

def _greedy_match_pcs(
    V_new: np.ndarray, V_ref: np.ndarray
) -> Tuple[np.ndarray, np.ndarray]:
    """Permutation and signs mapping ``V_new``'s columns onto ``V_ref``'s roles.

    Reimplementation (kept import-light) of
    ``ConvexityRV.factor_neutral_sizing._match_pcs`` -- importing that module
    pulls ``strat1_curve_gamma`` -> rateslib (~1.4 s measured), which a pure
    statistics module must not require.  Tied out against the original in
    ``tests/test_cvx_suite_residuals.py``.

    Sign-only alignment (``pca_rv.align_eigenvectors``) fixes the common case;
    the dangerous case is a ROTATION -- on a short window PC2 and PC3 can swap
    rank, and an eigenvalue-ordered pick would call curvature "slope".  So
    columns are matched greedily on |cos| first, then sign-aligned.
    ``perm[j]`` = index of the ``V_new`` column filling reference role j;
    aligned loadings = ``V_new[:, perm] * signs``.
    """
    k = V_ref.shape[1]
    C = np.abs(V_new.T @ V_ref)  # new x ref
    perm = np.full(k, -1, dtype=int)
    for _ in range(k):
        i, j = np.unravel_index(np.argmax(C), C.shape)
        perm[j] = i
        C[i, :] = -1.0
        C[:, j] = -1.0
    signs = np.array(
        [1.0 if (V_new[:, perm[j]] @ V_ref[:, j]) >= 0 else -1.0 for j in range(k)]
    )
    return perm, signs


def walk_forward_pca_residuals(
    levels_bp: pd.DataFrame,
    *,
    n_pcs: int = 2,
    window: int = 756,
    min_window: int = 504,
    refit: str = "M",
    min_median_abs_bp: float = 20.0,
) -> Tuple[pd.DataFrame, Dict[pd.Timestamp, Dict[str, object]]]:
    """Walk-forward n-PC residuals of bp LEVELS with refit-frozen loadings.

    The ``INGCurve.screen.rolling_pc1_residuals`` pattern, generalized to
    ``n_pcs`` factors through ``fit_curve_pca_from_timeseries(
    use_changes=False, sort_by_tenor=False, matrix="cov", pin_signs=True)``
    (``sort_by_tenor=False`` is load-bearing: kink-grid labels like "7y1y" are
    not TB tenor strings and the TB sorter would scramble them):

    *   For each calendar period of ``refit`` (default "M", monthly; any
        ``pd.PeriodIndex`` alias works), PCA is fit on up to ``window`` rows
        strictly BEFORE the period start.  Rows with any NaN are dropped by
        the fitter; the ``min_window`` ramp-in is counted on those COMPLETE
        rows (stricter than the screen original, which counts raw rows) --
        below it the period's residuals are NaN and it gets NO ``info`` entry.
    *   The window mean and the first ``n_pcs`` loadings are FROZEN for every
        day of the period.  Residual (bp) = ``c - A @ (A.T @ c)`` with
        ``c = row - mean``; days with any NaN level get all-NaN residuals.
        Causality is structural: mutating rows at or after a period start
        cannot change any residual before it (tested by mutation).
    *   ``info[period_first_trading_day] = {"loadings", "mean", "explained",
        "cos_prev"}``.  Loadings are stored AFTER greedy |cos| matching + sign
        alignment against the PREVIOUS refit (chained reference), so a stable
        market keeps stable columns; the residual itself is invariant to that
        relabeling (span(A) is unchanged by permutation/sign).  ``explained``
        is the per-PC eigenvalue share of TOTAL variance, permuted alongside.
        ``cos_prev[PCj]`` = matched |cos| vs the previous refit -- NaN on the
        first refit (the eigenvector-gap gate must tolerate NaN there).

    Returns ``(residuals_bp, info)``.  bp in, bp out; the bp-scale guard of
    this module applies (``min_median_abs_bp``).

    NOT ``pca_rv.make_pca_rv_builder``: that ``fit()`` is full-sample
    (look-ahead) unless ``fixed_loadings_date`` is passed.
    """
    if not isinstance(levels_bp.index, pd.DatetimeIndex):
        raise TypeError(
            "walk_forward_pca_residuals needs a DatetimeIndex "
            f"(got {type(levels_bp.index).__name__}) - refit periods are calendar periods"
        )
    n, m = levels_bp.shape
    if not 1 <= int(n_pcs) <= m:
        raise ValueError(f"n_pcs must be in [1, {m}] for a {m}-column panel, got {n_pcs}")
    if int(min_window) > int(window):
        raise ValueError(
            f"min_window ({min_window}) > window ({window}): no refit could ever qualify"
        )
    _assert_bp_scale(levels_bp, min_median_abs_bp, "walk_forward_pca_residuals")
    n_pcs = int(n_pcs)

    x = levels_bp.to_numpy(dtype=float)
    idx = levels_bp.index
    cols = list(levels_bp.columns)
    resid = np.full((n, m), np.nan)
    info: Dict[pd.Timestamp, Dict[str, object]] = {}
    pcs = [f"PC{j + 1}" for j in range(n_pcs)]

    periods = idx.to_period(refit)
    starts = np.flatnonzero(np.r_[True, periods[1:] != periods[:-1]])
    prev_V: np.ndarray | None = None  # previous refit's ALIGNED kept loadings
    for si, start in enumerate(starts):
        end = starts[si + 1] if si + 1 < len(starts) else n
        lo = max(0, start - int(window))
        win_df = levels_bp.iloc[lo:start]
        if int(win_df.dropna(how="any").shape[0]) < int(min_window):
            continue  # ramp-in: NaN residuals, no info entry
        model, _scores = fit_curve_pca_from_timeseries(
            win_df,
            use_changes=False,
            sort_by_tenor=False,
            matrix="cov",
            pin_signs=True,
        )
        # matrix="cov" => unit scales; the vectorized arithmetic below relies on it.
        if model.scales is not None and not np.allclose(
            model.scales.to_numpy(dtype=float), 1.0
        ):
            raise AssertionError(
                "cov-PCA returned non-unit scales - upstream contract changed"
            )
        mean = model.mean.reindex(cols).to_numpy(dtype=float)
        V_full = model.loadings.reindex(cols).to_numpy(dtype=float)
        lam = model.eigenvalues.to_numpy(dtype=float)
        A = V_full[:, :n_pcs]  # residual depends on span(A) only

        block = x[start:end] - mean[None, :]
        r = block - (block @ A) @ A.T
        r[np.isnan(x[start:end]).any(axis=1)] = np.nan  # partial days: all-NaN
        resid[start:end] = r

        if prev_V is None:
            V_al = A.copy()
            cos_prev: Dict[str, float] = {p: float("nan") for p in pcs}
            lam_kept = lam[:n_pcs].copy()
        else:
            perm, signs = _greedy_match_pcs(A, prev_V)
            V_al = A[:, perm] * signs[None, :]
            cos_prev = {
                pcs[j]: float(abs(A[:, perm[j]] @ prev_V[:, j])) for j in range(n_pcs)
            }
            lam_kept = lam[:n_pcs][perm]
        prev_V = V_al.copy()
        info[idx[start]] = {
            "loadings": pd.DataFrame(V_al, index=cols, columns=pcs),
            "mean": pd.Series(mean, index=cols, name="mean"),
            "explained": pd.Series(
                lam_kept / lam.sum(), index=pcs, name="explained"
            ),
            "cos_prev": cos_prev,
        }

    return pd.DataFrame(resid, index=idx, columns=cols), info


# ---------------------------------------------------------------------------
# cross-model sign agreement
# ---------------------------------------------------------------------------

def sign_agreement(
    a_bp: pd.DataFrame, b_bp: pd.DataFrame, *, min_abs_bp: float = 0.5
) -> pd.DataFrame:
    """Agreement map of two residual panels: +1 both cheap, -1 both rich, else 0.

    Cheap = residual > 0 (the ``CurvePCAModel.residual`` convention: actual
    above fair value).  A cell is +1 when BOTH residuals are strictly above
    ``+min_abs_bp``, -1 when both are strictly below ``-min_abs_bp``, and 0
    when they disagree or either is small (|r| <= min_abs_bp).  Cells where
    EITHER input is NaN are NaN -- "no data" is not "assessed, no agreement"
    (the never-silent-zero rule).

    ``b_bp`` is reindexed onto ``a_bp``'s index and columns; entries absent
    from ``b_bp`` become NaN.  Units: both inputs bp.
    """
    if min_abs_bp < 0:
        raise ValueError(f"min_abs_bp must be >= 0, got {min_abs_bp}")
    b = b_bp.reindex(index=a_bp.index, columns=a_bp.columns)
    av = a_bp.to_numpy(dtype=float)
    bv = b.to_numpy(dtype=float)
    out = np.zeros(av.shape, dtype=float)
    out[(av > min_abs_bp) & (bv > min_abs_bp)] = 1.0
    out[(av < -min_abs_bp) & (bv < -min_abs_bp)] = -1.0
    out[np.isnan(av) | np.isnan(bv)] = np.nan
    return pd.DataFrame(out, index=a_bp.index, columns=a_bp.columns)


# ---------------------------------------------------------------------------
# Ho-Lee forward-segment convexity adjustment
# ---------------------------------------------------------------------------

def convexity_adjustment_bp(sigma_bp_year: float, t1: float, t2: float) -> float:
    """Ho-Lee convexity depression of the quoted t1 -> t2 forward, in bp.

    Delegates to ``ConvexityRV.holee.ho_lee_ca_bp(sigma_bp, t1, t2)`` =
    ``0.5 * sigma^2 * t1 * t2`` (bp in / bp out, vol in bp/yr).  POSITIVE
    number = the amount the QUOTED forward is DEPRESSED by convexity;
    ``adjusted forward = quoted + CA`` (:func:`adjusted_levels`).

    Model choice (documented, per DESIGN.md section 3): the plain TWO-TIME
    Ho-Lee form for a t1 -> t2 forward segment.  This is NOT the ``holee``
    pack ``convention="citi"`` (mean(T1^2)) -- that convention reproduces
    Citi's printed implied vols on 8 published SCREENS (fit ratio median
    0.9998-1.0004, holee.py module docstring) but it is a PACK-of-futures
    convention; the two-time primitive used here takes no convention argument,
    so the "DEFAULT_CONVENTION drift" hazard (ca_valuation.py: pass
    ``convention=`` explicitly at every pack call site) cannot bite.

    Salomon zero-coupon alternative (Ilmanen, "Understanding the Yield
    Curve", Salomon Brothers: convexity bias ~ 0.5 * Cx * sigma^2 with
    Cx ~ duration^2 / 100, sigma in %/yr, result in %): at the segment
    midpoint duration D = (t1 + t2)/2 the two forms are 0.5*sigma^2*((t1+t2)/2)^2
    vs 0.5*sigma^2*t1*t2 -- identical at D = sqrt(t1*t2), and by AM-GM the
    midpoint form is an upper bound.  One numeric comparison, hand-checkable:
    sigma = 80 bp/yr, t1 = 25, t2 = 30 (the 25y5y kink point):
    Ho-Lee two-time = 0.5*(80/1e4)^2*25*30*1e4 = 240.0 bp; Salomon midpoint
    zero (D = 27.5) = 0.5*(27.5^2/100)*(0.8)^2 = 2.42% = 242.0 bp -- within
    1% here, the gap growing with segment width.

    NaN ``sigma_bp_year`` returns NaN (a missing vol day is data, not a bug);
    a negative sigma, ``t1 < 0`` or ``t2 <= t1`` raises ``ValueError``.
    """
    t1 = float(t1)
    t2 = float(t2)
    sig = float(sigma_bp_year)
    if np.isnan(t1) or np.isnan(t2) or not (0.0 <= t1 < t2):
        raise ValueError(
            f"need 0 <= t1 < t2 for a forward segment, got t1={t1}, t2={t2}"
        )
    if np.isnan(sig):
        return float("nan")
    if sig < 0.0:
        raise ValueError(f"sigma_bp_year must be >= 0, got {sig}")
    # Lazy import: ConvexityRV.__init__ imports curve_ops -> rateslib
    # (~1.3 s measured); a stats module must not levy that on every import.
    from RVUtils.ConvexityRV.holee import ho_lee_ca_bp

    return float(ho_lee_ca_bp(sig, t1, t2))


def adjusted_levels(
    levels_bp: pd.DataFrame,
    ca_bp: Union[pd.DataFrame, pd.Series],
    *,
    min_median_abs_bp: float = 20.0,
) -> pd.DataFrame:
    """Convexity-adjusted levels: ``quoted + CA``, both in bp.

    ``ca_bp`` positive = quoted forward depressed (the
    :func:`convexity_adjustment_bp` sign), so ADDING it restores the
    convexity-free comparable level the kink screen ranks on.

    *   ``ca_bp`` a Series: static per-point CA indexed by column label; every
        ``levels_bp`` column must be present (``ValueError`` naming the missing
        ones -- a silently NaN'd column would erase a grid point).
    *   ``ca_bp`` a DataFrame: date-varying CA; all columns must be present,
        dates are reindexed onto ``levels_bp`` and dates absent from ``ca_bp``
        yield NaN adjusted levels -- an unavailable adjustment is an
        unavailable level, NEVER silently zero (no fillna anywhere).
    """
    _assert_bp_scale(levels_bp, min_median_abs_bp, "adjusted_levels")
    if isinstance(ca_bp, pd.Series):
        missing = [c for c in levels_bp.columns if c not in ca_bp.index]
        if missing:
            raise ValueError(f"ca_bp Series is missing columns {missing}")
        return levels_bp.add(ca_bp.reindex(levels_bp.columns), axis="columns")
    if isinstance(ca_bp, pd.DataFrame):
        missing = [c for c in levels_bp.columns if c not in ca_bp.columns]
        if missing:
            raise ValueError(f"ca_bp frame is missing columns {missing}")
        ca = ca_bp.reindex(index=levels_bp.index, columns=levels_bp.columns)
        return levels_bp + ca
    raise TypeError(
        f"ca_bp must be a pandas Series or DataFrame, got {type(ca_bp).__name__}"
    )
