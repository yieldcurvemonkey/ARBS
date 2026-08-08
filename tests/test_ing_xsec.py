"""Synthetic-only tests for the F-ING-v2 cross-sectional fair-value screen.

Fast, no data files, no network.  Planted values only:

(i)   exact-polynomial day -> residuals ~0 (both fit variants);
(ii)  planted +20bp bump on one tenor -> recovered via the EXACT hat-matrix
      identity residual = b * (I - H) e_j (the fits are linear projections);
(iii) the frontier regression on a constructed day with known slope
      reproduces it;
(iv)  mutation checks: the registered fit configuration is pinned by named
      assertions on the constants AND on the realized model dof (trace H) -
      a changed fit degree / knot set fails here even if the constant is
      edited to match;
(v)   per-day locality: permuting other days cannot change a day's residual
      (the exact property v1's time-series PC1 residual lacked);
(vi)  the episode gate counts NON-overlapping episodes only.
"""

import os

os.environ.setdefault("ARBS_SUPABASE_ENABLED", "0")

import numpy as np
import pandas as pd
import pytest

from RVUtils.INGCurve import xsec


KS = list(range(2, 30))  # the primary-panel fit universe


def _cubic_panel(days=5, ks=KS, coefs=(2.0, 0.08, -0.004, 0.00006)):
    """Forward panel lying EXACTLY on a cubic in k (percent)."""
    idx = pd.bdate_range("2024-01-01", periods=days)
    k = np.asarray(ks, dtype=float)
    a0, a1, a2, a3 = coefs
    f = a0 + a1 * k + a2 * k**2 + a3 * k**3
    return pd.DataFrame(np.tile(f, (days, 1)), index=idx, columns=ks)


# ---------------------------------------------------------------------------
# (iv) registration pins - mutation checks
# ---------------------------------------------------------------------------

def test_registered_fit_config_pinned():
    assert xsec.POLY_DEGREE == 3, (
        "F-ING-v2 registered poly variant is a CUBIC (degree 3) - "
        "fit degree changed (registration change, not a tuning knob)"
    )
    assert tuple(xsec.SPLINE_KNOTS) == (1.0, 3.0, 7.0, 15.0, 29.0), (
        "F-ING-v2 registered spline knots are (1,3,7,15,29) - knot set changed"
    )
    assert xsec.VARIANTS == ("poly", "spline")


def test_realized_model_dof_pinned():
    """trace(H) is the REALIZED dof - catches an internal degree/knot mutation
    even if the module constants are edited to look unchanged."""
    H_poly = xsec.fit_matrix(KS, "poly")
    assert abs(np.trace(H_poly) - 4.0) < 1e-8, (
        f"poly hat-matrix trace {np.trace(H_poly):.3f} != 4 "
        "(cubic = 4 coefficients) - fit degree changed"
    )
    H_spl = xsec.fit_matrix(KS, "spline")
    assert abs(np.trace(H_spl) - 7.0) < 1e-8, (
        f"spline hat-matrix trace {np.trace(H_spl):.3f} != 7 "
        "(3 interior knots + 4) - knot set changed"
    )
    # both are orthogonal projections: H = H^T = H^2
    for H in (H_poly, H_spl):
        np.testing.assert_allclose(H, H.T, atol=1e-10)
        np.testing.assert_allclose(H @ H, H, atol=1e-10)


def test_spline_boundary_clamp_documented():
    """On the primary panel (k>=2) the lower boundary knot clamps 1 -> 2."""
    diag = xsec.fit_diagnostics(KS, "spline")
    assert diag["knots_used"] == (2.0, 3.0, 7.0, 15.0, 29.0)
    assert abs(diag["model_dof"] - 7.0) < 1e-8
    # full registered range when k=1 is present
    diag_full = xsec.fit_diagnostics(range(1, 30), "spline")
    assert diag_full["knots_used"] == (1.0, 3.0, 7.0, 15.0, 29.0)


def test_unknown_variant_rejected():
    with pytest.raises(ValueError, match="unknown variant"):
        xsec.fit_matrix(KS, "quartic")


# ---------------------------------------------------------------------------
# (i) exact-polynomial day -> residuals ~ 0
# ---------------------------------------------------------------------------

def test_exact_cubic_zero_residual_both_variants():
    fwd = _cubic_panel()
    for variant in xsec.VARIANTS:
        resid = xsec.xsec_residuals(fwd, variant)
        assert np.abs(resid.to_numpy()).max() < 1e-8, (
            f"{variant}: a curve EXACTLY on a cubic must have ~0 residual "
            "(a cubic polynomial lies in both fit spaces)"
        )


def test_quartic_curvature_not_absorbed():
    """A quartic term must LEAVE a residual - if this passes at ~0 the fit
    degree was silently raised (the mutation the registration pins against)."""
    fwd = _cubic_panel()
    k = np.asarray(KS, dtype=float)
    fwd.iloc[:, :] += 2e-5 * (k - 15.0) ** 4  # percent; ~50bp at the wings
    for variant in xsec.VARIANTS:
        resid = xsec.xsec_residuals(fwd, variant)
        assert np.abs(resid.to_numpy()).max() > 0.5, (
            f"{variant}: quartic curvature was absorbed by the fit - "
            "fit degree / knot set changed"
        )


# ---------------------------------------------------------------------------
# (ii) planted bump - exact hat-matrix identity
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("variant", xsec.VARIANTS)
def test_planted_bump_recovered_exactly(variant):
    """+20bp on tenor j: residual row == clean row + 20 * (I-H)[:, j], exactly.

    The fits are linear projections, so no tolerance-tuning: the bumped
    tenor's residual is 20*(1 - H_jj) and every other tenor's leakage is
    -20*H_ij.  Also asserts the bump is the argmax and materially recovered.
    """
    fwd = _cubic_panel()
    bump_k, bump_bp = 12, 20.0
    j = KS.index(bump_k)
    bumped = fwd.copy()
    bumped.iloc[2, j] += bump_bp / 100.0  # bp -> percent

    H = xsec.fit_matrix(KS, variant)
    M = np.eye(len(KS)) - H
    resid = xsec.xsec_residuals(bumped, variant)
    clean = xsec.xsec_residuals(fwd, variant)

    expected = clean.iloc[2].to_numpy() + bump_bp * M[:, j]
    np.testing.assert_allclose(resid.iloc[2].to_numpy(), expected, atol=1e-8)
    # materially recovered at the bumped tenor, and it is the extreme
    got = resid.iloc[2, j]
    assert got == pytest.approx(bump_bp * (1.0 - H[j, j]), abs=1e-8)
    assert got > 10.0, f"{variant}: bump under-recovered ({got:.2f}bp of 20)"
    assert resid.iloc[2].abs().idxmax() == bump_k
    # other days untouched (per-day construction)
    np.testing.assert_allclose(
        resid.drop(resid.index[2]).to_numpy(),
        clean.drop(clean.index[2]).to_numpy(),
        atol=1e-10,
    )


# ---------------------------------------------------------------------------
# (v) per-day locality - the property v1 lacked
# ---------------------------------------------------------------------------

def test_residual_is_per_day_only():
    """Shuffling / shocking OTHER days cannot change a day's residual."""
    rng = np.random.default_rng(11)
    fwd = _cubic_panel(days=8)
    fwd.iloc[:, :] += 0.01 * rng.standard_normal(fwd.shape)  # percent noise
    day = fwd.index[4]
    for variant in xsec.VARIANTS:
        base = xsec.xsec_residuals(fwd, variant).loc[day]
        shuffled = fwd.sample(frac=1.0, random_state=3)
        got = xsec.xsec_residuals(shuffled, variant).loc[day]
        np.testing.assert_allclose(got.to_numpy(), base.to_numpy(), atol=1e-12)
        shocked = fwd.copy()
        shocked.loc[shocked.index != day] += 5.0  # +500bp everywhere else
        got2 = xsec.xsec_residuals(shocked, variant).loc[day]
        np.testing.assert_allclose(got2.to_numpy(), base.to_numpy(), atol=1e-12)


def test_nan_day_stays_nan():
    fwd = _cubic_panel()
    fwd.iloc[1, 5] = np.nan
    resid = xsec.xsec_residuals(fwd, "poly")
    assert resid.iloc[1].isna().all()
    assert not resid.iloc[0].isna().any()


# ---------------------------------------------------------------------------
# (iii) frontier on a constructed day with known slope
# ---------------------------------------------------------------------------

def test_frontier_recovers_constructed_slope():
    """residual = -1.27 * roll + c exactly -> slope -1.27, R2 = 1 (v2 path:
    xsec residuals of a constructed strip, v1 rolldown, v1 frontier)."""
    idx = pd.bdate_range("2020-01-15", periods=1)
    ks_all = list(range(0, 30))
    # strip whose ROLL (0.25 * first difference * 100) varies across k:
    k = np.arange(30, dtype=float)
    f = 1.0 + 0.05 * k + 0.002 * k**2 - 0.00004 * k**3  # smooth cubic strip
    fwd_all = pd.DataFrame([f], index=idx, columns=ks_all)
    roll = xsec.rolldown_3m(fwd_all)  # bp/3m, k=1..29
    # CONSTRUCT residuals exactly on the line (the planted frontier):
    resid = -1.27 * roll + 3.0
    fr = xsec.daily_frontier(resid, roll, ks=range(2, 16))
    assert fr["slope"].iloc[0] == pytest.approx(-1.27, rel=1e-9)
    assert fr["intercept"].iloc[0] == pytest.approx(3.0, rel=1e-9)
    assert fr["r2"].iloc[0] == pytest.approx(1.0, rel=1e-9)
    assert int(fr["n"].iloc[0]) == 14


# ---------------------------------------------------------------------------
# (vi) episode gate: non-overlap, resolution, censoring
# ---------------------------------------------------------------------------

def _gate_inputs(x, fire_days, n=None):
    """Residual series x with hand-set ranks: 0.99 on fire_days, 0.5 else."""
    n = len(x) if n is None else n
    idx = pd.bdate_range("2021-01-01", periods=n)
    r = pd.DataFrame({5: np.asarray(x, dtype=float)}, index=idx)
    rk = pd.DataFrame({5: np.full(n, 0.5)}, index=idx)
    for t in fire_days:
        rk.iloc[t, 0] = 0.99
    med = pd.DataFrame({5: np.zeros(n)}, index=idx)
    return r, rk, med


def test_episode_gate_merges_overlapping_fires():
    """Three fire DAYS inside one unresolved dislocation = ONE episode; a
    fresh fire after the median cross = a second episode."""
    n = 250
    x = np.zeros(n)
    x[100:110] = 20.0     # dislocation; rank fires on 100, 102, 104
    x[110] = -1.0         # crosses the median (0) -> resolves at 110
    x[150] = 15.0         # fresh dislocation after resolution
    x[151] = -0.5         # resolves immediately
    r, rk, med = _gate_inputs(x, fire_days=[100, 102, 104, 150])
    stats, eps = xsec.episode_reversion_gate(
        r, rk, med, horizons=(21, 63), episode_cap=63
    )
    assert stats.loc["5F1Y", "n_episodes"] == 2, (
        "overlapping fire days must collapse into ONE episode (v1's L-0015(a))"
    )
    assert list(eps["resolved_by"]) == ["median_cross", "median_cross"]
    assert eps["episode_len_bd"].tolist() == [10, 1]
    # reversion at 21bd from the first fire (t=100): x back at 0 -> +20bp
    assert eps["reversion_21bd"].iloc[0] == pytest.approx(20.0)
    assert stats.loc["5F1Y", "med_abs_dislocation_bp"] == pytest.approx(17.5)
    assert stats.loc["5F1Y", "frac_revert_gt50pct_63bd"] == 1.0


def test_episode_gate_cap_and_censoring():
    """Never-crossing dislocation resolves by cap; a fire too close to the
    sample end is counted but excluded from reversion stats."""
    n = 200
    x = np.zeros(n)
    x[50:] = 25.0          # steps up and NEVER crosses back
    r, rk, med = _gate_inputs(x, fire_days=[50, 150, 190])
    stats, eps = xsec.episode_reversion_gate(
        r, rk, med, horizons=(21, 63), episode_cap=63
    )
    # ep1: cap at 50+63=113; next fire 150 opens ep2 whose cap (213) is past
    # the sample end -> censored; the 190 fire is inside ep2's open window
    assert stats.loc["5F1Y", "n_episodes"] == 2
    assert eps["resolved_by"].tolist() == ["cap", "censored"]
    assert eps["complete"].tolist() == [True, False]
    assert stats.loc["5F1Y", "n_complete"] == 1
    # no reversion at all: sign(d)*(r_t0 - r_t0+h) = 0
    assert eps["reversion_63bd"].iloc[0] == pytest.approx(0.0)
    assert stats.loc["5F1Y", "frac_revert_gt50pct_63bd"] == 0.0


def test_episode_gate_restriction_mask():
    """restrict_mask filters STATS by fire date but cannot create episodes."""
    n = 250
    x = np.zeros(n)
    x[100] = 20.0
    x[101] = -1.0
    x[150] = 15.0
    x[151] = -0.5
    r, rk, med = _gate_inputs(x, fire_days=[100, 150])
    mask = pd.Series(False, index=r.index)
    mask.iloc[140:] = True  # only the second episode is "post-splice"
    stats, eps = xsec.episode_reversion_gate(
        r, rk, med, horizons=(21, 63), restrict_mask=mask
    )
    assert len(eps) == 2                      # detection sees both
    assert eps["in_restriction"].tolist() == [False, True]
    assert stats.loc["5F1Y", "n_episodes"] == 1   # stats keep only the second
    assert stats.loc["5F1Y", "med_abs_dislocation_bp"] == pytest.approx(15.0)


def test_episode_gate_rich_side_sign():
    """A NEGATIVE dislocation reverting up scores positive reversion."""
    n = 250
    x = np.zeros(n)
    x[100:105] = -18.0
    x[105] = 0.5
    r, rk, med = _gate_inputs(x, fire_days=[100])
    rk.iloc[100, 0] = 0.01  # rich-side fire
    stats, eps = xsec.episode_reversion_gate(r, rk, med, horizons=(21, 63))
    assert eps["side"].iloc[0] == "rich"
    assert eps["dislocation_bp"].iloc[0] == pytest.approx(-18.0)
    assert eps["reversion_21bd"].iloc[0] == pytest.approx(18.0)
