"""Tests for RVUtils.FlyVsVol.metrics: path metrics + snapshot builder."""
import datetime

import numpy as np
import pytest
from scipy.stats import norm

from RVUtils.FlyVsVol import ContractMarginal, FlyVsVolConfig
from RVUtils.FlyVsVol.coupling import comonotone_grid
from RVUtils.FlyVsVol.metrics import build_fly_snapshot, path_metrics

MUS = (3.99, 4.145, 4.225)
SIGMAS = (0.30, 0.45, 0.82)
FLY_BP = (2 * MUS[1] - MUS[0] - MUS[2]) * 100  # +7.5


def normal_marginal(sym, mu, sigma, n=6001, span=6.0, **kw):
    grid = np.linspace(mu - span * sigma, mu + span * sigma, n)
    return ContractMarginal(
        symbol=sym, grid_rate=grid, cdf=norm.cdf(grid, mu, sigma), forward_rate=mu, **kw
    )


@pytest.fixture()
def legs():
    return [
        normal_marginal(s, m, sg)
        for s, m, sg in zip(("F", "B", "K"), MUS, SIGMAS)
    ]


@pytest.fixture()
def pd_result(legs):
    return path_metrics(comonotone_grid(legs, n=20001))


def test_tie_out_mean(pd_result):
    assert pd_result.e_phi_bp == pytest.approx(FLY_BP, abs=0.05)


def test_dn_table_sums_to_1(pd_result):
    assert sum(pd_result.dn_table.values()) == pytest.approx(1.0, abs=1e-9)
    assert sum(pd_result.p_dn_pos + pd_result.p_dn_neg + pd_result.p_dn_zero
               for _ in (0,)) == pytest.approx(1.0, abs=1e-9)


def test_dn_mean_consistency(pd_result):
    table_mean = sum(j * p for j, p in pd_result.dn_table.items())
    assert table_mean == pytest.approx(pd_result.e_n1 - pd_result.e_n2, abs=1e-9)


def test_tail_slope_normals(pd_result):
    s_eff = 2 * SIGMAS[1] - SIGMAS[0] - SIGMAS[2]
    expected = s_eff / SIGMAS[2]  # d(phi)/d(back) in bp per bp
    assert pd_result.tail_slope_upper == pytest.approx(expected, rel=0.05)
    assert pd_result.tail_slope_lower == pytest.approx(expected, rel=0.05)


def test_equal_sigmas_degenerate():
    legs = [normal_marginal(s, m, 0.40) for s, m in zip(("F", "B", "K"), MUS)]
    res = path_metrics(comonotone_grid(legs, n=20001))
    phi_spread = res.phi_quantiles_bp[95] - res.phi_quantiles_bp[5]
    assert phi_spread < 0.2
    assert res.p_phi_gt0 == pytest.approx(1.0, abs=1e-6)  # fly is +7.5bp determinate


def test_snapshot_symmetric_no_tail_rent():
    legs = [normal_marginal(s, m, 0.40) for s, m in zip(("F", "B", "K"), MUS)]
    snap = build_fly_snapshot(*legs, as_of=datetime.date(2026, 7, 27))
    assert snap.fly_bp == pytest.approx(FLY_BP, abs=1e-9)
    assert snap.tail_rent_bp == pytest.approx(0.0, abs=0.1)
    assert snap.fly_mean_bp == pytest.approx(FLY_BP, abs=0.05)
    assert snap.heuristic_prob == pytest.approx(FLY_BP / 25.0)
    assert snap.quality_ok
    assert snap.copula is None


def test_snapshot_with_copula(legs):
    corr = np.full((3, 3), 0.95)
    np.fill_diagonal(corr, 1.0)
    snap = build_fly_snapshot(*legs, corr=corr, rng=np.random.default_rng(5))
    assert snap.copula is not None
    assert snap.copula.e_phi_bp == pytest.approx(FLY_BP, abs=0.6)


def test_quality_gate_flags():
    bad = normal_marginal("F", MUS[0], SIGMAS[0], forward_residual_bp=-4.0,
                          pre_normalization_mass=1.05)
    ok_b = normal_marginal("B", MUS[1], SIGMAS[1])
    ok_k = normal_marginal("K", MUS[2], SIGMAS[2])
    snap = build_fly_snapshot(bad, ok_b, ok_k)
    assert not snap.quality_ok
    joined = " ".join(snap.quality_flags)
    assert "forward_residual" in joined and "mass" in joined and "F" in joined


def test_to_row_keys(legs):
    snap = build_fly_snapshot(*legs, as_of=datetime.date(2026, 7, 27))
    row = snap.to_row()
    for key in ("label", "fly_bp", "tail_rent_bp", "heuristic_prob", "prob_delta",
                "heuristic_gap", "phi_iqr_bp", "tail_slope_upper", "quality_ok"):
        assert key in row
    assert row["label"] == "F-B-K"
    assert row["heuristic_gap"] == pytest.approx(
        snap.heuristic_prob - snap.comonotone.prob_delta
    )
