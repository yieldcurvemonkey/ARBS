import datetime
import numpy as np
import pandas as pd
import pytest

from RVUtils.ImpliedDistribution import (
    AnnotatedResult,
    BreedenLitzenbergerResult,
    RNDInput,
    ViewMetadata,
)
from RVUtils.SFRConvexScreener import Leg
from RVUtils.SFRConvexScreener._distributions import (
    PerContractDistribution,
    extract_bl_marginals,
    payoff_pdf_common_state,
    payoff_pdf_historical_gaussian_copula,
    payoff_pdf_perfect_correlation,
)


def _bl_with_uniform(symbol: str, mean: float = 3.5) -> BreedenLitzenbergerResult:
    grid = np.linspace(mean - 1.0, mean + 1.0, 1001)
    density = np.full_like(grid, 0.5)
    cdf = np.linspace(0.0, 1.0, 1001)
    return BreedenLitzenbergerResult(
        input=RNDInput(
            symbol=symbol, as_of=datetime.date(2026, 4, 28),
            forward_price=100 - mean, forward_rate=mean, time_to_expiry=0.5,
            expiry_date=datetime.date(2026, 12, 14), discount_factor=1.0,
            strikes_price=np.array([95.0]), call_premiums=np.array([0.5]),
            strike_source="test",
        ),
        strike_grid_rate=grid,
        rnd_density=density,
        rnd_cumulative=cdf,
        bin_edges_rate=np.array([mean - 0.5, mean + 0.5]),
        bin_probabilities=np.array([1.0]),
        bin_labels=[f"{mean:.2f}"],
        mean_rate=mean,
        std_rate=1.0 / np.sqrt(3.0),
        skewness=0.0, kurtosis=1.8,
        smoothing_param=1e-4, n_ghost_points=10, spline_residual=0.0,
    )


def test_per_contract_distribution_holds_grid_and_density():
    bl = _bl_with_uniform("SFRZ26", 3.5)
    d = PerContractDistribution(symbol="SFRZ26", bl=bl)
    grid, density = d.rate_grid, d.density
    assert len(grid) == 1001
    # Uniform on [2.5, 4.5] integrates to 1
    assert np.isclose(np.trapezoid(density, grid), 1.0, atol=1e-3)


def test_extract_bl_marginals_skips_failures():
    """If extractor.extract raises, log warning and continue."""
    bl_z = _bl_with_uniform("SFRZ26", 3.5)
    bl_h = _bl_with_uniform("SFRH27", 3.6)
    fake_smiles = {"SFRZ26": object(), "SFRH27": object(), "SFRM27": object()}

    class _FakeID:
        def extract(self, smile):
            from RVUtils.ImpliedDistribution import ImpliedDistributionSnapshot

            if smile is fake_smiles["SFRM27"]:
                raise RuntimeError("induced failure")
            sym = "SFRZ26" if smile is fake_smiles["SFRZ26"] else "SFRH27"
            bl = bl_z if sym == "SFRZ26" else bl_h
            return ImpliedDistributionSnapshot(
                symbol=sym, as_of=datetime.date(2026, 4, 28),
                bl_result=bl, gm_result=None,
            )

    out = extract_bl_marginals(fake_smiles, dist_extractor=_FakeID())
    assert "SFRZ26" in out and "SFRH27" in out
    assert "SFRM27" not in out


def test_payoff_pdf_common_state_returns_array_with_finite_support():
    from unittest.mock import MagicMock

    fake_outcomes = np.array([-5.0, 0.0, 7.0])
    fake_probs = np.array([0.3, 0.4, 0.3])
    snap = MagicMock(spec=["linear_combination_distribution"])
    snap.linear_combination_distribution.return_value = AnnotatedResult(
        data=pd.DataFrame({"value": fake_outcomes, "probability": fake_probs}),
        metadata=ViewMetadata(support="exact"),
    )

    legs = (
        Leg(contract="SFRZ26", weight=1, price=96.5, dv01=25),
        Leg(contract="SFRH27", weight=-2, price=96.6, dv01=25),
        Leg(contract="SFRM27", weight=1, price=96.7, dv01=25),
    )
    outcomes_bp, probs = payoff_pdf_common_state(legs, joint=snap)

    snap.linear_combination_distribution.assert_called_once()
    args, kwargs = snap.linear_combination_distribution.call_args
    weights = args[0] if args else kwargs.get("weights")
    assert weights == {"SFRZ26": 1, "SFRH27": -2, "SFRM27": 1}
    np.testing.assert_allclose(probs.sum(), 1.0, atol=1e-9)
    np.testing.assert_allclose(outcomes_bp, fake_outcomes * 100.0)


def test_payoff_pdf_common_state_accepts_linear_combination_column():
    """The real implementation in `_joint_analytics.py` uses
    `value_name='linear_combination'` for linear-combination distributions —
    `payoff_pdf_common_state` must handle either column name."""
    from unittest.mock import MagicMock

    fake_outcomes = np.array([-5.0, 0.0, 7.0])
    fake_probs = np.array([0.3, 0.4, 0.3])
    snap = MagicMock(spec=["linear_combination_distribution"])
    snap.linear_combination_distribution.return_value = AnnotatedResult(
        data=pd.DataFrame({"linear_combination": fake_outcomes, "probability": fake_probs}),
        metadata=ViewMetadata(support="exact"),
    )

    legs = (
        Leg(contract="A", weight=1, price=96.5, dv01=25),
        Leg(contract="B", weight=-1, price=96.6, dv01=25),
    )
    outcomes_bp, probs = payoff_pdf_common_state(legs, joint=snap)
    np.testing.assert_allclose(outcomes_bp, fake_outcomes * 100.0)
    np.testing.assert_allclose(probs.sum(), 1.0, atol=1e-9)


def test_payoff_pdf_gaussian_copula_recovers_expected_mean_for_independent_uniform():
    """Independent uniform marginals: 1*X1 - 1*X2 has mean 0, std sqrt(2/3)% ≈ 81.6 bp."""
    rng = np.random.default_rng(seed=42)
    bl_a = _bl_with_uniform("SFRZ26", 0.0)
    bl_b = _bl_with_uniform("SFRH27", 0.0)
    marginals = {
        "SFRZ26": PerContractDistribution(symbol="SFRZ26", bl=bl_a),
        "SFRH27": PerContractDistribution(symbol="SFRH27", bl=bl_b),
    }
    legs = (
        Leg(contract="SFRZ26", weight=1, price=99.0, dv01=25),
        Leg(contract="SFRH27", weight=-1, price=99.0, dv01=25),
    )
    corr = pd.DataFrame(np.eye(2), index=["SFRZ26", "SFRH27"], columns=["SFRZ26", "SFRH27"])
    samples_bp = payoff_pdf_historical_gaussian_copula(
        legs, marginals=marginals, corr_matrix=corr, n_sim=20_000, rng=rng,
    )
    assert abs(samples_bp.mean()) < 5.0
    assert 70.0 < samples_bp.std() < 95.0


def test_payoff_pdf_outright_returns_marginal_centred_at_forward():
    """The outright payoff PDF is the BL marginal recentred so that
    payoff = (rate - forward) * weight * 100, in bp."""
    from RVUtils.SFRConvexScreener._distributions import payoff_pdf_outright

    bl = _bl_with_uniform("SFRZ26", 3.5)  # uniform on [2.5, 4.5]
    marginals = {"SFRZ26": PerContractDistribution(symbol="SFRZ26", bl=bl)}

    leg_pay = Leg(contract="SFRZ26", weight=1.0, price=96.5, dv01=25)
    outcomes_bp, probs = payoff_pdf_outright(leg_pay, marginals=marginals)
    # Uniform centred at 3.5 → payoffs uniform on [-100, +100] bp
    assert outcomes_bp.min() < -90
    assert outcomes_bp.max() > 90
    assert abs((outcomes_bp * probs).sum()) < 1.0  # mean ~ 0
    assert abs(probs.sum() - 1.0) < 1e-6

    # Receiver convention (weight=-1) flips the sign
    leg_recv = Leg(contract="SFRZ26", weight=-1.0, price=96.5, dv01=25)
    outcomes_bp_r, _ = payoff_pdf_outright(leg_recv, marginals=marginals)
    np.testing.assert_allclose(np.sort(outcomes_bp), -np.sort(outcomes_bp_r)[::-1])


def test_payoff_pdf_perfect_correlation_uses_front_marginal_only():
    """All legs move with the same shift — fly P&L = 0 since sum(weights) = 0."""
    bl = _bl_with_uniform("SFRZ26", 3.5)
    marginals = {
        "SFRZ26": PerContractDistribution(symbol="SFRZ26", bl=bl),
        "SFRH27": PerContractDistribution(symbol="SFRH27", bl=bl),
        "SFRM27": PerContractDistribution(symbol="SFRM27", bl=bl),
    }
    legs = (
        Leg(contract="SFRZ26", weight=1, price=96.5, dv01=25),
        Leg(contract="SFRH27", weight=-2, price=96.5, dv01=25),
        Leg(contract="SFRM27", weight=1, price=96.5, dv01=25),
    )
    outcomes_bp, probs = payoff_pdf_perfect_correlation(legs, marginals=marginals)
    np.testing.assert_allclose(outcomes_bp, np.zeros_like(outcomes_bp), atol=1e-6)
    np.testing.assert_allclose(probs.sum(), 1.0, atol=1e-6)
