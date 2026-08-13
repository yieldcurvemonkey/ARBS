"""Known-answer tests for the ported mean-variance optimizer.

The optimum is derived from the code's own objective convention, not assumed from a textbook.
``__setup_problem_arrays_d1`` builds ``P = 0.5·λ·Σ`` and ``q = -α``, and cvxopt's ``qp`` minimises
``½x'Px + q'x``. So the problem actually solved is

    min  0.25·λ·x'Σx − α'x        =>        x* = 2·Σ⁻¹α / λ

which carries a factor of two against the usual ``Σ⁻¹α/λ``. That factor is the convention of this
code and every test below is written against it.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from RVUtils.PortfolioOpt import Optimizer, Panel3D


def _dates(n: int) -> pd.DatetimeIndex:
    return pd.bdate_range("2026-01-05", periods=n)


def _panel(dates, cov: np.ndarray, assets) -> Panel3D:
    return Panel3D({d: pd.DataFrame(cov, index=assets, columns=assets) for d in dates})


# ------------------------------------------------- the two-asset minimum
def test_single_asset_problem_is_refused():
    """``mean_variance_one_period`` returns NaN for n < 2. Inherited contract, not a port defect.

    The original bails before building the problem arrays when there is only one active asset, so
    a one-instrument book silently produces no holdings. Pinned here because it is the kind of
    thing that would otherwise be discovered as a flat equity curve.
    """
    dates, assets = _dates(3), ["A"]
    alphas = pd.DataFrame({"A": [0.02] * 3}, index=dates)
    h = Optimizer().mean_variance(alphas, _panel(dates, np.array([[0.01]]), assets), risk_aversion=2.0)
    assert h["A"].isna().all()


def test_two_asset_diagonal_matches_the_closed_form():
    """A diagonal Σ separates, so each asset gets 2a_i/(λσ_i²) exactly.

    a=0.02, σ²=0.01, λ=2 -> 2·0.02/(2·0.01) = 2.0 on both.
    """
    dates, assets = _dates(3), ["A", "B"]
    alphas = pd.DataFrame({"A": [0.02] * 3, "B": [0.02] * 3}, index=dates)
    cov = _panel(dates, np.diag([0.01, 0.01]), assets)

    h = Optimizer().mean_variance(alphas, cov, risk_aversion=2.0)
    assert np.allclose(h.iloc[-1].to_numpy(), [2.0, 2.0], atol=1e-6)


def test_risk_aversion_scales_the_position_inversely():
    dates, assets = _dates(3), ["A", "B"]
    alphas = pd.DataFrame({"A": [0.02] * 3, "B": [0.02] * 3}, index=dates)
    cov = _panel(dates, np.diag([0.01, 0.01]), assets)
    opt = Optimizer()

    lo = opt.mean_variance(alphas, cov, risk_aversion=2.0)["A"].iloc[-1]
    hi = opt.mean_variance(alphas, cov, risk_aversion=8.0)["A"].iloc[-1]
    assert hi == pytest.approx(lo / 4.0, rel=1e-5)


def test_sign_of_alpha_flips_the_position():
    dates, assets = _dates(3), ["A", "B"]
    cov = _panel(dates, np.diag([0.01, 0.01]), assets)
    opt = Optimizer()
    up = opt.mean_variance(pd.DataFrame({"A": [0.02] * 3, "B": [0.02] * 3}, index=dates), cov, risk_aversion=2.0)
    dn = opt.mean_variance(pd.DataFrame({"A": [-0.02] * 3, "B": [-0.02] * 3}, index=dates), cov, risk_aversion=2.0)
    assert up["A"].iloc[-1] == pytest.approx(-dn["A"].iloc[-1], rel=1e-6)


# ---------------------------------------------------------------- two assets
def test_diagonal_covariance_separates():
    """A diagonal Σ makes the problem separable: each asset gets 2a_i/(λσ_i²)."""
    dates, assets = _dates(3), ["A", "B"]
    alphas = pd.DataFrame({"A": [0.02] * 3, "B": [0.01] * 3}, index=dates)
    cov = _panel(dates, np.diag([0.01, 0.04]), assets)

    h = Optimizer().mean_variance(alphas, cov, risk_aversion=2.0)
    assert h["A"].iloc[-1] == pytest.approx(2 * 0.02 / (2 * 0.01), rel=1e-5)
    assert h["B"].iloc[-1] == pytest.approx(2 * 0.01 / (2 * 0.04), rel=1e-5)


def test_full_covariance_matches_the_matrix_solution():
    """x* = 2Σ⁻¹α/λ for a genuinely correlated pair."""
    dates, assets = _dates(3), ["A", "B"]
    sigma = np.array([[0.010, 0.006], [0.006, 0.020]])
    a = np.array([0.02, 0.01])
    alphas = pd.DataFrame({"A": [a[0]] * 3, "B": [a[1]] * 3}, index=dates)

    h = Optimizer().mean_variance(alphas, _panel(dates, sigma, assets), risk_aversion=2.0)
    expected = 2.0 * np.linalg.solve(sigma, a) / 2.0
    assert np.allclose(h.iloc[-1].to_numpy(), expected, atol=1e-5)


def test_correlation_shrinks_a_paired_bet():
    """Two positively correlated assets with the same alpha should be held smaller than one."""
    dates, assets = _dates(3), ["A", "B"]
    alphas = pd.DataFrame({"A": [0.02] * 3, "B": [0.02] * 3}, index=dates)
    indep = _panel(dates, np.diag([0.01, 0.01]), assets)
    corr = _panel(dates, np.array([[0.01, 0.009], [0.009, 0.01]]), assets)
    opt = Optimizer()
    assert opt.mean_variance(alphas, corr, risk_aversion=2.0)["A"].iloc[-1] < opt.mean_variance(
        alphas, indep, risk_aversion=2.0
    )["A"].iloc[-1]


# ------------------------------------------------------------ costs / bands
def test_transaction_costs_shrink_the_position():
    dates, assets = _dates(4), ["A", "B"]
    alphas = pd.DataFrame({"A": [0.02] * 4, "B": [0.02] * 4}, index=dates)
    cov = _panel(dates, np.diag([0.01, 0.01]), assets)
    opt = Optimizer()

    free = opt.mean_variance(alphas, cov, risk_aversion=2.0)["A"].iloc[-1]
    costed = opt.mean_variance(
        alphas, cov, risk_aversion=2.0, transaction_costs=0.005, transaction_cost_aversion=1.0
    )["A"].iloc[-1]
    assert 0 < costed < free


def test_a_cost_above_the_alpha_holds_the_position_at_zero():
    """With no initial holding and a cost that dominates the signal, do not trade at all."""
    dates, assets = _dates(4), ["A", "B"]
    alphas = pd.DataFrame({"A": [0.001] * 4, "B": [0.001] * 4}, index=dates)
    cov = _panel(dates, np.diag([0.01, 0.01]), assets)
    h = Optimizer().mean_variance(
        alphas, cov, risk_aversion=2.0, transaction_costs=0.5, transaction_cost_aversion=10.0
    )
    assert np.allclose(h[["A", "B"]].to_numpy(), 0.0, atol=1e-6)


def test_zero_alpha_gives_zero_holdings():
    dates, assets = _dates(3), ["A", "B"]
    alphas = pd.DataFrame({"A": [0.0] * 3, "B": [0.0] * 3}, index=dates)
    h = Optimizer().mean_variance(alphas, _panel(dates, np.diag([0.01, 0.02]), assets), risk_aversion=2.0)
    assert np.allclose(h.to_numpy(), 0.0, atol=1e-8)


def test_output_shape_and_index_are_preserved():
    dates, assets = _dates(6), ["A", "B", "C"]
    rng = np.random.default_rng(3)
    alphas = pd.DataFrame(rng.normal(scale=0.01, size=(6, 3)), index=dates, columns=assets)
    cov = _panel(dates, np.diag([0.01, 0.02, 0.03]), assets)
    h = Optimizer().mean_variance(alphas, cov, risk_aversion=5.0)
    assert list(h.columns) == assets
    assert len(h) == len(dates)
    assert np.isfinite(h.to_numpy()).all()


# ------------------------------------------------------------------ Panel3D
def test_panel3d_roundtrip_and_ffill():
    dates = _dates(4)
    frames = {dates[0]: pd.DataFrame(np.eye(2)), dates[2]: pd.DataFrame(2 * np.eye(2))}
    p = Panel3D(frames).reindex(dates).fillna(method="ffill", axis=0)
    assert np.allclose(p.loc[dates[1]].to_numpy(), np.eye(2))       # carried from date 0
    assert np.allclose(p.loc[dates[3]].to_numpy(), 2 * np.eye(2))   # carried from date 2
    assert p.shape[0] == 4


def test_panel3d_rejects_unknown_fill():
    p = Panel3D({_dates(1)[0]: pd.DataFrame(np.eye(2))})
    with pytest.raises(NotImplementedError):
        p.fillna(method="bfill")
