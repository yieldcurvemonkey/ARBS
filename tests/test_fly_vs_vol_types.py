"""Tests for RVUtils.FlyVsVol._types: ContractMarginal, FlyDefinition, config."""
import datetime
from types import SimpleNamespace

import numpy as np
import pytest
from scipy.stats import norm

from RVUtils.FlyVsVol import ContractMarginal, FlyDefinition, FlyVsVolConfig


def normal_marginal(sym: str, mu: float, sigma: float, n: int = 6001, span: float = 6.0):
    grid = np.linspace(mu - span * sigma, mu + span * sigma, n)
    return ContractMarginal(
        symbol=sym, grid_rate=grid, cdf=norm.cdf(grid, mu, sigma), forward_rate=mu
    )


def test_quantile_roundtrip():
    m = normal_marginal("SFRZ26", 4.145, 0.45)
    u = np.linspace(0.05, 0.95, 19)
    np.testing.assert_allclose(m.cdf_at(m.quantile(u)), u, atol=1e-6)


def test_moments_normal():
    m = normal_marginal("SFRZ26", 4.145, 0.45)
    assert m.mean == pytest.approx(4.145, abs=2e-3)
    assert m.median == pytest.approx(4.145, abs=1e-3)
    grid_step = (12 * 0.45) / 6000
    assert m.mode == pytest.approx(4.145, abs=2 * grid_step)


def test_percentile_bounds():
    m = normal_marginal("SFRU26", 3.99, 0.30)
    assert m.percentile(0) == pytest.approx(m.grid_rate[0])
    assert m.percentile(100) == pytest.approx(m.grid_rate[-1])
    assert m.percentile(50) == pytest.approx(3.99, abs=1e-3)


def test_from_bl_result_stub():
    grid = np.linspace(3.0, 5.0, 101)
    cdf = norm.cdf(grid, 4.0, 0.3)
    bl = SimpleNamespace(
        strike_grid_rate=grid,
        rnd_cumulative=cdf,
        input=SimpleNamespace(forward_rate=4.001),
        forward_residual_bp=-1.18,
        pre_normalization_mass=1.013,
        ghost_mass_fraction=0.0006,
        warnings=("bl::something",),
    )
    m = ContractMarginal.from_bl_result("SFRU26", bl, as_of=datetime.date(2026, 7, 27))
    assert m.symbol == "SFRU26"
    assert m.forward_rate == pytest.approx(4.001)
    assert m.forward_residual_bp == pytest.approx(-1.18)
    assert m.pre_normalization_mass == pytest.approx(1.013)
    assert m.ghost_mass_fraction == pytest.approx(0.0006)
    assert m.warnings == ("bl::something",)
    assert m.as_of == datetime.date(2026, 7, 27)
    np.testing.assert_array_equal(m.grid_rate, grid)


def test_marginal_validation():
    with pytest.raises(ValueError):
        ContractMarginal(
            symbol="X",
            grid_rate=np.array([2.0, 1.0, 3.0]),  # not ascending
            cdf=np.array([0.1, 0.5, 1.0]),
            forward_rate=2.0,
        )
    with pytest.raises(ValueError):
        ContractMarginal(
            symbol="X",
            grid_rate=np.array([1.0, 2.0, 3.0]),
            cdf=np.array([0.1, 0.5]),  # length mismatch
            forward_rate=2.0,
        )


def test_fly_definition():
    fly = FlyDefinition(front="SFRU26", belly="SFRZ26", back="SFRH27")
    assert fly.label == "SFRU26-SFRZ26-SFRH27"
    assert fly.symbols == ("SFRU26", "SFRZ26", "SFRH27")


def test_config_defaults():
    cfg = FlyVsVolConfig()
    assert cfg.move_size_bp == 25.0
    assert cfg.n_quantiles == 20001
    assert cfg.max_abs_forward_residual_bp == 2.5
