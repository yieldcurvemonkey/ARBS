"""Tests for RVUtils.CvxSuite.residuals.

Pure-logic tests on synthetic panels -- no local store, panel file or market
data is touched, so nothing here carries an integration/slow mark.

Style per the suite rules: known-answer anchors are pinned on published /
hand-derivable numbers (OLS-cubic dof = 4, cubic-spline dof = 4 + interior
knots, Ho-Lee 0.5*sigma^2*t1*t2 = 240.0 bp at (80 bp/yr, 25, 30), the Salomon
midpoint-zero 242.0 bp); EVERY planted answer carries a negative control that
must fail; error paths are asserted to raise loudly or yield NaN, never a
silent zero.
"""

from __future__ import annotations

import os

os.environ.setdefault("ARBS_SUPABASE_ENABLED", "0")

import numpy as np
import pandas as pd
import pytest

from RVUtils.CvxSuite.residuals import (
    DEFAULT_KNOTS,
    _greedy_match_pcs,
    adjusted_levels,
    convexity_adjustment_bp,
    fit_diagnostics,
    hat_matrix,
    sign_agreement,
    walk_forward_pca_residuals,
    xsec_residuals,
)

#: KINK_GRID-like float fit abscissae (k = fwd + tenor/2, years): spot-1y
#: midpoint 0.5 through the 40y10y midpoint 45.  Non-uniform, extends BEYOND
#: the default knot boundaries (0.5 < 1 and 45 > 27) on purpose -- the cubic
#: extension must stay an exact projection out there.
KS = (
    0.5, 1.5, 2.5, 3.5, 4.5, 5.5, 6.5, 7.5, 8.5, 9.5,
    11.0, 13.5, 17.5, 22.5, 27.5, 35.0, 45.0,
)
LABELS = [f"k{v:g}" for v in KS]


def _cubic(k) -> np.ndarray:
    """An arbitrary global cubic in k, level ~ hundreds of bp."""
    k = np.asarray(k, dtype=float)
    return 320.0 + 14.0 * k - 0.55 * k**2 + 0.006 * k**3


# ---------------------------------------------------------------------------
# hat_matrix: guards
# ---------------------------------------------------------------------------

def test_hat_matrix_guards():
    """Input guards raise loudly (the INGCurve.xsec mechanics, float ks)."""
    with pytest.raises(ValueError, match="at least 8"):
        hat_matrix(KS[:7], "spline")
    bad = list(KS)
    bad[3], bad[4] = bad[4], bad[3]  # non-increasing
    with pytest.raises(ValueError, match="strictly increasing"):
        hat_matrix(bad, "spline")
    dup = list(KS)
    dup[5] = dup[4]  # duplicate
    with pytest.raises(ValueError, match="strictly increasing"):
        hat_matrix(dup, "poly")
    with pytest.raises(ValueError, match="unknown variant"):
        hat_matrix(KS, "loess")
    # interior knots outside a narrow grid: the configured knot set does not apply
    narrow = np.linspace(10.0, 11.0, 9)
    with pytest.raises(ValueError, match="interior knots"):
        hat_matrix(narrow, "spline", knots=DEFAULT_KNOTS)


@pytest.mark.parametrize("variant", ["poly", "spline"])
def test_hat_matrix_reproduces_any_cubic_exactly(variant):
    """H reproduces a global cubic exactly; (I-H) annihilates it.

    Both fit spaces contain all cubics (poly: degree 3; spline: every cubic
    spline space contains the cubics, and extrapolate=True continues the end
    pieces polynomially, so the reproduction holds at k = 0.5, 35 and 45
    beyond the knot boundaries too).

    MUTATION: lower the B-spline order 3 -> 2 in _spline_hat (or degree 3 -> 2
    in _poly_hat) -- cubics leave the fit space and the allclose fails.
    """
    H = hat_matrix(KS, variant)
    f = _cubic(KS)
    assert np.allclose(H @ f, f, rtol=1e-9, atol=1e-6)
    M = np.eye(len(KS)) - H
    assert np.allclose(M @ f, 0.0, atol=1e-6)
    # negative control: a NON-cubic vector must NOT be reproduced (else H ~ I
    # and the "fit" fits nothing)
    g = f + 5.0 * np.eye(len(KS))[7]
    assert not np.allclose(H @ g, g, atol=1e-3)


@pytest.mark.parametrize("variant", ["poly", "spline"])
def test_hat_matrix_is_exact_linear_projection(variant):
    """H is an orthogonal projector: idempotent, symmetric, (I-H)H = 0.

    (I-H) annihilating the ENTIRE fit space is (I-H)@H == 0 -- H z spans the
    fit space over all z.

    MUTATION: regularize the fit (X @ inv(X'X + lambda I) @ X') -- idempotence
    H@H == H fails.
    """
    H = hat_matrix(KS, variant)
    assert np.allclose(H @ H, H, atol=1e-9)
    assert np.allclose(H, H.T, atol=1e-9)
    M = np.eye(len(KS)) - H
    assert np.abs(M @ H).max() < 1e-9


def test_fit_diagnostics_dof_known_answers():
    """Model dof anchors: OLS cubic trace(H) = 4; cubic spline = 4 + n_interior.

    Both are textbook (trace of a projector = dim of its range; the cubic
    B-spline space on m interior knots has dimension 4 + m, Schoenberg).  With
    the DESIGN section 6 knots (1,3,7,15,27): 3 interior knots -> dof 7.

    MUTATION: silently drop an unidentified basis column instead of raising in
    _spline_hat (or change the knot set) -- the model_dof pin fails.
    """
    dp = fit_diagnostics(KS, "poly")
    assert dp["model_dof"] == pytest.approx(4.0, abs=1e-8)
    assert dp["poly_degree"] == 3

    ds = fit_diagnostics(KS, "spline")
    assert ds["model_dof"] == pytest.approx(7.0, abs=1e-8)
    assert ds["resid_dof"] == pytest.approx(len(KS) - 7.0, abs=1e-8)
    # boundary knots are INSIDE the observed 0.5..45 range: no clamping
    assert ds["knots_used"] == (1.0, 3.0, 7.0, 15.0, 27.0)
    assert set(ds["leverage"]) == {float(k) for k in KS}
    # negative control (must fail = must NOT equal the 5-knot answer): dropping
    # one interior knot changes the dof to 6 -- the anchor detects a knot change
    d4 = fit_diagnostics(KS, "spline", knots=(1.0, 3.0, 7.0, 27.0))
    assert d4["model_dof"] == pytest.approx(6.0, abs=1e-8)
    assert d4["model_dof"] != pytest.approx(7.0, abs=1e-3)


def test_fit_diagnostics_boundary_clamp():
    """The documented clamp: a boundary knot outside the data moves onto it.

    On an ING-style integer grid starting at k=2 with lower boundary knot 1,
    the clamp is 1 -> 2 (the xsec docstring's own worked case, reproduced by
    the float reimplementation).
    """
    ks = [float(k) for k in range(2, 30)]
    d = fit_diagnostics(ks, "spline", knots=(1.0, 3.0, 7.0, 15.0, 27.0))
    assert d["knots_used"][0] == 2.0
    assert d["knots_used"][-1] == 27.0


def test_schoenberg_whitney_assert_fires_on_dead_span():
    """A basis with no data anywhere in its support -> AssertionError, not a fit.

    Grid clustered at [0.5, 4.9] and [9.5, 12]; interior knots (5,6,7,8,9) put
    one cubic basis function's entire support [5, 9] inside the data gap: its
    design column is identically zero, rank < n_basis.

    MUTATION: delete the rank assert in _spline_hat -- pinv would silently
    build a lower-dof projector and this pytest.raises fails.
    """
    ks = (0.5, 1.5, 2.5, 3.5, 4.9, 9.5, 10.5, 11.5, 12.0)
    with pytest.raises(AssertionError, match="Schoenberg-Whitney"):
        hat_matrix(ks, "spline", knots=(0.4, 5.0, 6.0, 7.0, 8.0, 9.0, 12.5))
    # positive control: same grid, no dead span -> a valid projector
    H = hat_matrix(ks, "spline", knots=(0.4, 5.0, 12.5))
    assert H.shape == (9, 9)
    assert np.allclose(H @ H, H, atol=1e-9)


# ---------------------------------------------------------------------------
# xsec_residuals
# ---------------------------------------------------------------------------

def _base_panel(n_days: int = 2, seed: int = 11) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    f0 = _cubic(KS) + rng.normal(0.0, 2.0, len(KS))  # non-cubic content
    idx = pd.bdate_range("2026-08-03", periods=n_days)
    return pd.DataFrame(np.tile(f0, (n_days, 1)), index=idx, columns=LABELS)


@pytest.mark.parametrize("variant", ["poly", "spline"])
def test_xsec_planted_bump_moves_residual_by_I_minus_H(variant):
    """A +5 bp bump on point j moves residual_i by exactly 5*(I-H)[i, j].

    The projection is linear, so the planted-shock arithmetic is exact -- this
    is the load-bearing identity of the whole cross-sectional screen.

    MUTATION 1: return the FIT (F @ H.T) instead of the residual -- the
    negative control (delta vs 5*H[:, j]) stops failing and the planted
    equality fails.
    MUTATION 2: copy INGCurve.xsec's percent->bp `* 100.0` -- delta reads
    500*(I-H)[:, j] and the equality fails.
    """
    j = 4
    levels = _base_panel(2)
    levels.iloc[1, j] += 5.0
    resid = xsec_residuals(levels, KS, variant)
    H = hat_matrix(KS, variant)
    M = np.eye(len(KS)) - H
    delta = (resid.iloc[1] - resid.iloc[0]).to_numpy()
    assert np.allclose(delta, 5.0 * M[:, j], atol=1e-8)
    # negative controls -- each must fail
    assert not np.allclose(delta, 5.0 * H[:, j], atol=1e-6)      # fit, not residual
    assert not np.allclose(delta, 500.0 * M[:, j], atol=1e-6)    # percent-style x100
    assert not np.allclose(delta, 5.0 * M[:, j + 1], atol=1e-6)  # wrong column


def test_xsec_residuals_no_time_dependence():
    """Permuting/bumping other days cannot change a day's residual.

    MUTATION: make the fit pool days (e.g. fit on the panel mean) -- the
    equality of day-0 residuals across the two panels fails.
    """
    levels = _base_panel(3)
    r0 = xsec_residuals(levels, KS, "spline")
    bumped = levels.copy()
    bumped.iloc[2, 5] += 25.0  # single-point shock: NOT in the fit space
    r1 = xsec_residuals(bumped, KS, "spline")
    pd.testing.assert_frame_equal(r0.iloc[:2], r1.iloc[:2], check_exact=True)
    # positive control: the bumped day itself DID change
    assert not np.allclose(r0.iloc[2], r1.iloc[2], atol=1e-6)


def test_xsec_residuals_nan_day_is_all_nan():
    """Any NaN level -> ALL-NaN residual row; other days untouched."""
    levels = _base_panel(2)
    levels.iloc[1, 3] = np.nan
    resid = xsec_residuals(levels, KS, "spline")
    assert resid.iloc[1].isna().all()
    assert resid.iloc[0].notna().all()


def test_xsec_residuals_ks_column_mismatch_raises():
    levels = _base_panel(2)
    with pytest.raises(ValueError, match="align 1:1"):
        xsec_residuals(levels, KS[:-1], "spline")


def test_xsec_residuals_percent_guard():
    """bp-scale guard: a percent panel raises loudly, naming the median.

    This is the module's decided percent-vs-bp confusion control (the
    INGCurve original takes percent; feeding it here rescales every residual
    100x if unguarded).

    MUTATION: delete the _assert_bp_scale call in xsec_residuals -- the
    pytest.raises fails.
    """
    levels = _base_panel(2)
    with pytest.raises(ValueError, match="median"):
        xsec_residuals(levels / 100.0, KS, "spline")  # percent units
    # positive control: bp panel passes
    assert xsec_residuals(levels, KS, "spline").notna().all().all()
    # explicit escape hatch: disabling is deliberate, not silent
    out = xsec_residuals(levels / 100.0, KS, "spline", min_median_abs_bp=0.0)
    assert out.shape == levels.shape
    # all-NaN input is refused, not returned as an empty success
    with pytest.raises(ValueError, match="all-NaN"):
        xsec_residuals(levels * np.nan, KS, "spline")


# ---------------------------------------------------------------------------
# walk_forward_pca_residuals
# ---------------------------------------------------------------------------

WF_KW = dict(n_pcs=2, window=252, min_window=126, refit="M")


@pytest.fixture(scope="module")
def wf_panel() -> pd.DataFrame:
    """Synthetic 6-leg bp panel from an exact 2-factor model + small idio noise."""
    rng = np.random.default_rng(20260826)
    idx = pd.bdate_range("2022-01-03", periods=600)
    m = 6
    v1 = np.ones(m) / np.sqrt(m)
    s = np.linspace(-1.0, 1.0, m)
    s = s - (s @ v1) * v1
    v2 = s / np.linalg.norm(s)
    # Wide eigengap (step-vol ratio 6.0 : 0.8) so the principal axes within the
    # factor plane are pinned; a closer ratio lets window-realized moments
    # rotate PC2 between refits (a real effect cos_prev exists to flag -- it
    # gets its own planted-rotation test below).
    s1 = np.cumsum(rng.normal(0.0, 6.0, len(idx)))
    s2 = np.cumsum(rng.normal(0.0, 0.8, len(idx)))
    eps = rng.normal(0.0, 0.3, (len(idx), m))
    X = 300.0 + np.outer(s1, v1) + np.outer(s2, v2) + eps
    cols = ["1y1y", "3y1y", "5y1y", "7y1y", "10y2y", "15y5y"]
    return pd.DataFrame(X, index=idx, columns=cols)


@pytest.fixture(scope="module")
def wf_run(wf_panel):
    return walk_forward_pca_residuals(wf_panel, **WF_KW)


def test_walk_forward_ramp_in_is_nan_and_uninformed(wf_panel, wf_run):
    """Months with < min_window complete trailing rows: NaN residuals, NO info.

    MUTATION: drop the min_window check -- early months get residuals from a
    thin covariance and the all-NaN assert fails.
    """
    resid, info = wf_run
    assert len(info) > 5
    first_key = min(info)
    before = resid.loc[: first_key - pd.Timedelta(days=1)]
    assert len(before) >= 100  # a real ramp-in region exists in this setup
    assert before.isna().all().all()
    after = resid.loc[first_key:]
    assert after.notna().all().all()


def test_walk_forward_causality_future_mutation(wf_panel, wf_run):
    """Mutating FUTURE rows cannot change any earlier residual (bit-identical).

    MUTATION: let the fit window touch the refit period (x[lo:start] ->
    x[lo:start+1]) or score with a refit-period mean -- the exact frame
    equality up to the cut fails.
    """
    resid0, info0 = wf_run
    keys = sorted(info0)
    cut = wf_panel.index.get_loc(keys[7])  # start of a later refit period
    rng = np.random.default_rng(4)
    mutated = wf_panel.copy()
    mutated.iloc[cut:] += rng.normal(0.0, 40.0, (len(mutated) - cut, mutated.shape[1]))
    resid1, info1 = walk_forward_pca_residuals(mutated, **WF_KW)
    pd.testing.assert_frame_equal(resid0.iloc[:cut], resid1.iloc[:cut], check_exact=True)
    # and the refits strictly before the cut are identical too
    for k in keys:
        if k < keys[7]:
            pd.testing.assert_frame_equal(
                info0[k]["loadings"], info1[k]["loadings"], check_exact=True
            )


def test_walk_forward_frozen_reconstruction(wf_panel, wf_run):
    """Within a refit period every residual reproduces from the FROZEN info.

    r_t = c_t - A (A' c_t), c_t = x_t - mean, with A and mean from that
    period's info entry.  Also proves the greedy alignment is span-preserving
    (A stored is permuted/sign-flipped; A A' is invariant).

    MUTATION: refit inside the month (rolling daily loadings) -- late-month
    rows stop matching the frozen reconstruction.
    """
    resid, info = wf_run
    keys = sorted(info)
    key = keys[5]
    per = wf_panel.index.to_period("M")
    block = np.flatnonzero(per == key.to_period("M"))
    A = info[key]["loadings"].to_numpy(dtype=float)
    mean = info[key]["mean"].to_numpy(dtype=float)
    C = wf_panel.to_numpy(dtype=float)[block] - mean[None, :]
    manual = C - (C @ A) @ A.T
    assert np.allclose(resid.to_numpy()[block], manual, atol=1e-9)


def test_walk_forward_planted_dislocation_exact(wf_panel, wf_run):
    """A +5 bp one-day bump on leg j moves that day's residual by
    exactly 5*(I - A A')[:, j] -- and changes nothing earlier.

    The fit for the bump's own month ends strictly before the month, so A and
    mean are unchanged and the linear-projection arithmetic is exact (the
    hat-matrix planted-bump identity, PCA edition).

    MUTATION: include the scored month in the fit window -- A changes, the
    exact identity fails.
    """
    resid0, info0 = wf_run
    keys = sorted(info0)
    key = keys[5]
    t_pos = wf_panel.index.get_loc(key) + 3
    assert wf_panel.index[t_pos].to_period("M") == key.to_period("M")
    j = 2
    bumped = wf_panel.copy()
    bumped.iloc[t_pos, j] += 5.0
    resid1, info1 = walk_forward_pca_residuals(bumped, **WF_KW)

    A = info0[key]["loadings"].to_numpy(dtype=float)
    m = A.shape[0]
    P = np.eye(m) - A @ A.T
    delta = (resid1.iloc[t_pos] - resid0.iloc[t_pos]).to_numpy()
    assert np.allclose(delta, 5.0 * P[:, j], atol=1e-9)
    # negative controls -- each must fail
    assert not np.allclose(delta, 5.0 * (A @ A.T)[:, j], atol=1e-6)  # the FIT leg
    assert not np.allclose(delta, np.zeros(m), atol=1e-6)            # bump visible
    # the bump's month info is identical (fit strictly before the month)
    pd.testing.assert_frame_equal(
        info0[key]["loadings"], info1[key]["loadings"], check_exact=True
    )
    # nothing before the bump day moved
    pd.testing.assert_frame_equal(
        resid0.iloc[:t_pos], resid1.iloc[:t_pos], check_exact=True
    )

    # The same identity at the PERIOD-START day pins the fit window's right
    # edge exactly.  MUTATION: let the fit window touch its own period
    # (x[lo:start] -> x[lo:start+1]) -- the bump folds into A and mean, the
    # stored loadings differ between runs and the exact identity fails.
    # (Verified: this bump catches that off-by-one; the earlier-rows check
    # above does not, because the leak is confined to the period itself.)
    t0 = wf_panel.index.get_loc(key)
    bumped0 = wf_panel.copy()
    bumped0.iloc[t0, j] += 5.0
    resid2, info2 = walk_forward_pca_residuals(bumped0, **WF_KW)
    delta0 = (resid2.iloc[t0] - resid0.iloc[t0]).to_numpy()
    assert np.allclose(delta0, 5.0 * P[:, j], atol=1e-9)
    pd.testing.assert_frame_equal(
        info0[key]["loadings"], info2[key]["loadings"], check_exact=True
    )


def test_walk_forward_full_rank_residual_is_zero(wf_panel):
    """n_pcs = n_columns reconstructs completely: residual ~ 0 (not NaN)."""
    resid, info = walk_forward_pca_residuals(
        wf_panel, n_pcs=6, window=252, min_window=126, refit="M"
    )
    live = resid.dropna(how="all")
    assert len(live) > 200
    assert np.nanmax(np.abs(live.to_numpy())) < 1e-8


def test_walk_forward_info_contract(wf_run, wf_panel):
    """info entries: aligned loadings, frozen mean, per-PC explained, cos_prev.

    cos_prev is NaN on the FIRST refit (nothing to match) and ~1 on a
    stationary factor structure afterwards; explained shares are ordered
    PC1 > PC2 here and sum below 1 (idio noise holds back the rest).

    MUTATION: compare cos BEFORE greedy matching (raw eigh column order) -- a
    rank swap would print a spurious low cos; on this stable panel the >= 0.9
    bound also catches an accidental cos-vs-angle confusion (values ~ 0.03).
    """
    resid, info = wf_run
    keys = sorted(info)
    first = info[keys[0]]
    assert all(np.isnan(v) for v in first["cos_prev"].values())
    for k in keys[1:]:
        e = info[k]
        assert list(e["loadings"].columns) == ["PC1", "PC2"]
        assert list(e["loadings"].index) == list(wf_panel.columns)
        assert list(e["mean"].index) == list(wf_panel.columns)
        assert set(e["cos_prev"]) == {"PC1", "PC2"}
        for v in e["cos_prev"].values():
            assert 0.9 <= v <= 1.0 + 1e-12
        expl = e["explained"]
        assert list(expl.index) == ["PC1", "PC2"]
        assert expl["PC1"] > expl["PC2"] > 0.0
        assert float(expl.sum()) < 1.0 + 1e-9
        # loadings are orthonormal columns
        G = e["loadings"].to_numpy().T @ e["loadings"].to_numpy()
        assert np.allclose(G, np.eye(2), atol=1e-9)
    # exact identity: cos_prev IS the |dot| of consecutive STORED loadings
    # (data-independent -- holds whatever the market does)
    for k_prev, k in zip(keys, keys[1:]):
        Vp = info[k_prev]["loadings"].to_numpy()
        Vn = info[k]["loadings"].to_numpy()
        for j, p in enumerate(["PC1", "PC2"]):
            assert info[k]["cos_prev"][p] == pytest.approx(
                abs(float(Vn[:, j] @ Vp[:, j])), abs=1e-12
            )


def test_walk_forward_nan_rows_and_complete_row_counting(wf_panel, wf_run):
    """Partial-NaN days and NaN-starved fit windows behave as documented.

    One leg goes dark for rows 200..449.  Asserted against the clean run:
    (i) an informed month inside the dark stretch keeps its info entry but
    prints ALL-NaN residual rows (a partial grid day is never scored on a
    smaller universe); (ii) months whose trailing window falls below
    min_window COMPLETE rows lose their info entry and print NaN -- min_window
    counts complete (dropna'd) rows, the documented strictness over the
    screen original's raw-row count; (iii) refits resume once complete rows
    re-accumulate; (iv) months entirely before the stretch are bit-identical.

    MUTATION: count min_window on RAW window rows (len(win_df)) instead of
    complete rows -- the raw count is always 252 here, no month is ever
    starved, and the `missing` assert fails.
    """
    resid0, info0 = wf_run
    keys0 = sorted(info0)
    a, b = 200, 450
    panel = wf_panel.copy()
    panel.iloc[a:b, 3] = np.nan
    resid1, info1 = walk_forward_pca_residuals(panel, **WF_KW)
    keys1 = sorted(info1)
    assert set(keys1) <= set(keys0)

    # (ii) the stretch starves some refit windows of complete rows
    missing = [k for k in keys0 if k not in info1]
    assert missing, "the NaN stretch must starve at least one refit window"
    per = wf_panel.index.to_period("M")
    for k in missing:
        assert resid1.loc[per == k.to_period("M")].isna().all().all()

    # (iii) refits resume after the stretch (complete rows re-accumulate)
    assert keys0[-1] in info1

    # (i) an informed month wholly inside the stretch: info present, rows NaN
    pos = {k: wf_panel.index.get_loc(k) for k in keys1}
    inside = [k for k in keys1 if a <= pos[k] and pos[k] + 23 <= b]
    assert inside, "expected at least one informed month inside the stretch"
    blk = per == inside[0].to_period("M")
    assert resid1.loc[blk].isna().all().all()
    assert resid0.loc[blk].notna().all().all()  # the clean run scored them

    # (iv) rows strictly before the stretch are untouched
    pd.testing.assert_frame_equal(
        resid0.iloc[:a], resid1.iloc[:a], check_exact=True
    )


def test_walk_forward_cos_prev_flags_a_planted_rotation():
    """A mid-sample change of the second factor's SHAPE trips cos_prev[PC2]
    below the DESIGN gate threshold (0.90) while PC1 stays pinned -- the
    eigenvector-gap gate's feed doing its one job.

    Construction: factor 2 moves along v2 (slope shape) until day 320, then
    freezes and a NEW factor moves along v3 (curvature shape, v2 . v3 = 0).
    Measured behavior worth knowing at the composition layer: because monthly
    refit windows OVERLAP (~92% at window=252), a 90-degree factor swap is
    SMEARED into a run of moderate step-rotations (min step-cos 0.875 on this
    construction), not one catastrophic dip -- so the per-refit cos must be
    compared to the gate threshold, and the cumulative first-to-last rotation
    (|cos| < 0.3 here) is what proves the full swap.

    MUTATION: compare each refit's loadings to THEMSELVES instead of the
    previous refit (cos_prev identically 1.0) -- the `< 0.90` dip assert
    fails.
    """
    rng = np.random.default_rng(99)
    idx = pd.bdate_range("2022-01-03", periods=700)
    n, m, sw = len(idx), 6, 320
    v1 = np.ones(m) / np.sqrt(m)
    s = np.linspace(-1.0, 1.0, m)
    s = s - (s @ v1) * v1
    v2 = s / np.linalg.norm(s)
    c = np.array([1.0, -0.2, -0.8, -0.8, -0.2, 1.0])
    c = c - (c @ v1) * v1 - (c @ v2) * v2
    v3 = c / np.linalg.norm(c)
    s1 = np.cumsum(rng.normal(0.0, 6.0, n))
    step2 = rng.normal(0.0, 1.0, n)
    step2[sw:] = 0.0                      # factor 2 freezes at the switch
    step3 = rng.normal(0.0, 1.0, n)
    step3[:sw] = 0.0                      # factor 3 wakes at the switch
    X = (
        300.0
        + np.outer(s1, v1)
        + np.outer(np.cumsum(step2), v2)
        + np.outer(np.cumsum(step3), v3)
        + rng.normal(0.0, 0.1, (n, m))
    )
    panel = pd.DataFrame(X, index=idx, columns=[f"l{i}" for i in range(m)])
    _, info = walk_forward_pca_residuals(
        panel, n_pcs=2, window=252, min_window=126, refit="M"
    )
    keys = sorted(info)
    pc1 = np.array([info[k]["cos_prev"]["PC1"] for k in keys[1:]])
    pc2 = np.array([info[k]["cos_prev"]["PC2"] for k in keys[1:]])
    assert (pc1 > 0.9).all()          # the level factor never rotates
    assert pc2.min() < 0.90           # the transition trips the gate default
    assert pc2[-1] > 0.95             # and the new regime re-stabilises
    # the cumulative rotation is a genuine factor swap: first vs last stored
    # PC2 loadings are near-orthogonal (v2 -> v3)
    p2_first = info[keys[0]]["loadings"]["PC2"].to_numpy()
    p2_last = info[keys[-1]]["loadings"]["PC2"].to_numpy()
    assert abs(float(p2_first @ p2_last)) < 0.3
    # negative control -- must fail for PC1: no swap there
    p1_first = info[keys[0]]["loadings"]["PC1"].to_numpy()
    p1_last = info[keys[-1]]["loadings"]["PC1"].to_numpy()
    assert abs(float(p1_first @ p1_last)) > 0.95


def test_walk_forward_deterministic(wf_panel, wf_run):
    resid0, info0 = wf_run
    resid1, info1 = walk_forward_pca_residuals(wf_panel, **WF_KW)
    pd.testing.assert_frame_equal(resid0, resid1, check_exact=True)
    k = sorted(info0)[3]
    pd.testing.assert_frame_equal(
        info0[k]["loadings"], info1[k]["loadings"], check_exact=True
    )


def test_walk_forward_quarterly_refit(wf_panel, wf_run):
    """refit is a pandas period alias: "Q" refits less often than "M"."""
    _, info_m = wf_run
    _, info_q = walk_forward_pca_residuals(
        wf_panel, n_pcs=2, window=252, min_window=126, refit="Q"
    )
    assert 0 < len(info_q) < len(info_m)


def test_walk_forward_error_paths(wf_panel):
    with pytest.raises(ValueError, match="n_pcs"):
        walk_forward_pca_residuals(wf_panel, n_pcs=7, window=252, min_window=126)
    with pytest.raises(ValueError, match="n_pcs"):
        walk_forward_pca_residuals(wf_panel, n_pcs=0, window=252, min_window=126)
    with pytest.raises(ValueError, match="min_window"):
        walk_forward_pca_residuals(wf_panel, n_pcs=2, window=100, min_window=200)
    with pytest.raises(ValueError, match="median"):
        walk_forward_pca_residuals(wf_panel / 100.0, **WF_KW)  # percent units
    bad = wf_panel.reset_index(drop=True)
    with pytest.raises(TypeError, match="DatetimeIndex"):
        walk_forward_pca_residuals(bad, **WF_KW)


def test_greedy_match_pcs_ties_out_and_recovers_rotation():
    """The small reimplementation matches ConvexityRV's _match_pcs exactly.

    Known answer: a column permutation with sign flips is fully recovered
    (aligned == reference).  The tie-out also runs on a noisy rotation.

    MUTATION: match on raw dot instead of |cos| (drop the abs) -- the
    sign-flipped scramble stops being recovered and the tie-out fails.
    """
    fns = pytest.importorskip("RVUtils.ConvexityRV.factor_neutral_sizing")
    rng = np.random.default_rng(7)
    V = np.linalg.qr(rng.normal(size=(8, 8)))[0][:, :3]
    scram = V[:, [2, 0, 1]] * np.array([-1.0, 1.0, -1.0])
    p_mine, s_mine = _greedy_match_pcs(scram, V)
    p_ref, s_ref = fns._match_pcs(scram, V)
    assert np.array_equal(p_mine, p_ref)
    assert np.allclose(s_mine, s_ref)
    assert np.allclose(scram[:, p_mine] * s_mine, V, atol=1e-12)
    # negative control: the UNpermuted columns do not reproduce the reference
    assert not np.allclose(scram, V, atol=1e-6)
    # noisy rotation still ties out
    noisy = scram + rng.normal(0.0, 0.05, scram.shape)
    p2m, s2m = _greedy_match_pcs(noisy, V)
    p2r, s2r = fns._match_pcs(noisy, V)
    assert np.array_equal(p2m, p2r)
    assert np.allclose(s2m, s2r)


# ---------------------------------------------------------------------------
# sign_agreement
# ---------------------------------------------------------------------------

def test_sign_agreement_truth_table():
    """+1 both cheap, -1 both rich, 0 disagree/small, NaN where data missing.

    Cheap = residual > 0 (CurvePCAModel.residual convention).  Threshold is
    STRICT: exactly +/- min_abs_bp counts as small.

    MUTATION 1: flip the cheap/rich convention (both_cheap -> -1) -- the
    (+2,+2) cell fails.
    MUTATION 2: use >= at the threshold -- the (+0.5,+0.5) boundary cell
    fails.
    MUTATION 3: return 0 where an input is NaN (silent zero) -- the NaN cells
    fail.
    """
    idx = pd.to_datetime(["2026-08-24", "2026-08-25"])
    cols = list("abcde")
    a = pd.DataFrame(
        [[2.0, -2.0, 2.0, 2.0, 0.5],
         [0.6, 2.0, np.nan, 0.0, -2.0]],
        index=idx, columns=cols,
    )
    b = pd.DataFrame(
        [[2.0, -2.0, -2.0, 0.4, 0.5],
         [0.6, np.nan, 2.0, 0.0, 2.0]],
        index=idx, columns=cols,
    )
    out = sign_agreement(a, b, min_abs_bp=0.5)
    expect = pd.DataFrame(
        [[1.0, -1.0, 0.0, 0.0, 0.0],
         [1.0, np.nan, np.nan, 0.0, 0.0]],
        index=idx, columns=cols,
    )
    pd.testing.assert_frame_equal(out, expect)


def test_sign_agreement_alignment_and_errors():
    """b is reindexed onto a; absent cells are NaN, not zero."""
    idx = pd.to_datetime(["2026-08-24"])
    a = pd.DataFrame([[2.0, 2.0]], index=idx, columns=["x", "y"])
    b = pd.DataFrame([[2.0, 9.0]], index=idx, columns=["y", "z"])  # no "x"
    out = sign_agreement(a, b)
    assert np.isnan(out.loc[idx[0], "x"])  # b has no "x" -> NaN, never 0
    assert out.loc[idx[0], "y"] == 1.0
    with pytest.raises(ValueError, match="min_abs_bp"):
        sign_agreement(a, b, min_abs_bp=-1.0)


# ---------------------------------------------------------------------------
# convexity_adjustment_bp / adjusted_levels
# ---------------------------------------------------------------------------

def test_convexity_adjustment_known_answer_and_delegation():
    """Hand-derivable pin: 0.5*(80/1e4)^2*25*30*1e4 = 240.0 bp, via holee.

    Salomon zero-coupon alternative (half Cx sigma^2, Cx ~ duration^2/100) at
    the segment midpoint D = 27.5y reads 242.0 bp -- within 1%, and above by
    AM-GM (midpoint square >= t1*t2).

    MUTATION: replace t1*t2 with t2*t2 (288.0) or with the holee pack "citi"
    single-time T1^2 form (200.0) -- the 240.0 pin fails.
    """
    ca = convexity_adjustment_bp(80.0, 25.0, 30.0)
    assert ca == pytest.approx(240.0, rel=1e-12)

    from RVUtils.ConvexityRV.holee import ho_lee_ca_bp

    assert ca == ho_lee_ca_bp(80.0, 25.0, 30.0)  # exact delegation

    salomon_midpoint_bp = 0.5 * (27.5**2 / 100.0) * 0.8**2 * 100.0  # % -> bp
    assert salomon_midpoint_bp == pytest.approx(242.0, rel=1e-12)
    assert ca < salomon_midpoint_bp
    assert abs(ca - salomon_midpoint_bp) / salomon_midpoint_bp < 0.01
    # negative controls -- wrong time forms must NOT hit the pin
    assert ca != pytest.approx(0.5 * (80.0 / 1e4) ** 2 * 30.0 * 30.0 * 1e4)  # 288
    assert ca != pytest.approx(0.5 * (80.0 / 1e4) ** 2 * 25.0 * 25.0 * 1e4)  # 200


def test_convexity_adjustment_monotone_in_sigma_and_times():
    """CA strictly increases in sigma, in t2 and in t1; zero vol -> zero CA.

    MUTATION: divide by t2 anywhere (an accidental "per-year" form) -- the t2
    monotonicity fails.
    """
    by_sigma = [convexity_adjustment_bp(s, 25.0, 30.0) for s in (10, 20, 40, 80, 160)]
    assert all(b > a for a, b in zip(by_sigma, by_sigma[1:]))
    by_t2 = [convexity_adjustment_bp(80.0, 25.0, t2) for t2 in (26, 28, 30, 35, 40)]
    assert all(b > a for a, b in zip(by_t2, by_t2[1:]))
    by_t1 = [convexity_adjustment_bp(80.0, t1, 45.0) for t1 in (5, 10, 20, 40)]
    assert all(b > a for a, b in zip(by_t1, by_t1[1:]))
    assert convexity_adjustment_bp(0.0, 25.0, 30.0) == 0.0


def test_convexity_adjustment_error_paths():
    """NaN vol -> NaN (missing data); impossible segment/vol -> loud raise."""
    assert np.isnan(convexity_adjustment_bp(float("nan"), 25.0, 30.0))
    with pytest.raises(ValueError, match="t1"):
        convexity_adjustment_bp(80.0, 30.0, 25.0)  # t2 < t1
    with pytest.raises(ValueError, match="t1"):
        convexity_adjustment_bp(80.0, 25.0, 25.0)  # zero-width segment
    with pytest.raises(ValueError, match="t1"):
        convexity_adjustment_bp(80.0, -1.0, 25.0)
    with pytest.raises(ValueError, match="sigma"):
        convexity_adjustment_bp(-80.0, 25.0, 30.0)
    with pytest.raises(ValueError, match="t1"):
        convexity_adjustment_bp(80.0, float("nan"), 30.0)


def test_adjusted_levels_series_and_frame():
    """adjusted = quoted + CA; positive CA RAISES the level (depression undone).

    MUTATION: subtract the CA instead of adding -- the +12 pin fails.
    """
    idx = pd.bdate_range("2026-08-20", periods=3)
    levels = pd.DataFrame(
        {"20y5y": [400.0, 401.0, 402.0], "25y5y": [390.0, 391.0, 392.0]}, index=idx
    )
    ca_s = pd.Series({"20y5y": 12.0, "25y5y": 30.0})
    out = adjusted_levels(levels, ca_s)
    assert out.loc[idx[0], "20y5y"] == pytest.approx(412.0)
    assert out.loc[idx[2], "25y5y"] == pytest.approx(422.0)

    ca_f = pd.DataFrame(
        {"20y5y": [12.0, np.nan], "25y5y": [30.0, 31.0]}, index=idx[:2]
    )  # last date entirely absent; one NaN cell
    out2 = adjusted_levels(levels, ca_f)
    assert out2.loc[idx[0], "20y5y"] == pytest.approx(412.0)
    assert np.isnan(out2.loc[idx[1], "20y5y"])   # NaN CA -> NaN, never quoted+0
    assert out2.loc[idx[1], "25y5y"] == pytest.approx(422.0)
    assert out2.loc[idx[2]].isna().all()         # missing CA date -> NaN row


def test_adjusted_levels_error_paths():
    """Missing columns raise (a silently NaN'd grid point is data loss).

    MUTATION: fillna(0.0) on the CA inside adjusted_levels -- the NaN asserts
    in the frame test above fail.
    """
    idx = pd.bdate_range("2026-08-20", periods=2)
    levels = pd.DataFrame(
        {"20y5y": [400.0, 401.0], "25y5y": [390.0, 391.0]}, index=idx
    )
    with pytest.raises(ValueError, match="25y5y"):
        adjusted_levels(levels, pd.Series({"20y5y": 12.0}))
    with pytest.raises(ValueError, match="25y5y"):
        adjusted_levels(levels, pd.DataFrame({"20y5y": [12.0, 12.0]}, index=idx))
    with pytest.raises(TypeError, match="Series or DataFrame"):
        adjusted_levels(levels, np.array([12.0, 30.0]))
    with pytest.raises(ValueError, match="median"):
        adjusted_levels(levels / 100.0, pd.Series({"20y5y": 12.0, "25y5y": 30.0}))
