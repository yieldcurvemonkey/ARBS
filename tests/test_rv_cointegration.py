"""Tests for RVUtils.cointegration — TDD: written BEFORE implementation.

Run:
    conda run -n stir python -m pytest tests/test_rv_cointegration.py -v
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from RVUtils.cointegration import (
    engle_granger,
    johansen,
    spread,
    zscore,
    bands,
    make_cointegration_builder,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _random_walk(n: int, rng: np.random.Generator) -> pd.Series:
    """I(1) random walk with a business-day DatetimeIndex."""
    idx = pd.date_range("2015-01-02", periods=n, freq="B")
    return pd.Series(rng.standard_normal(n).cumsum(), index=idx)


def _ou_noise(n: int, rng: np.random.Generator, kappa: float = 0.3, sigma: float = 0.5) -> pd.Series:
    """Stationary OU noise (mean 0)."""
    phi = np.exp(-kappa)
    s_step = sigma * np.sqrt((1.0 - np.exp(-2.0 * kappa)) / (2.0 * kappa))
    x = np.empty(n)
    x[0] = 0.0
    for t in range(1, n):
        x[t] = phi * x[t - 1] + s_step * rng.standard_normal()
    idx = pd.date_range("2015-01-02", periods=n, freq="B")
    return pd.Series(x, index=idx)


# ---------------------------------------------------------------------------
# engle_granger — cointegrated pair
# ---------------------------------------------------------------------------

class TestEngleGrangerCointegrated:
    """y = 2*x + stationary_noise  ->  engle_granger should detect cointegration."""

    @pytest.fixture(scope="class")
    def eg_result(self):
        rng = np.random.default_rng(42)
        n = 1500
        x = _random_walk(n, rng)
        noise = _ou_noise(n, rng, kappa=0.4, sigma=0.4)
        y = 2.0 * x + noise
        return engle_granger(y, x)

    def test_beta_close_to_two(self, eg_result):
        assert eg_result["beta"] == pytest.approx(2.0, abs=0.15)

    def test_alpha_finite(self, eg_result):
        assert np.isfinite(eg_result["alpha"])

    def test_spread_is_series(self, eg_result):
        s = eg_result["spread"]
        assert isinstance(s, pd.Series)
        assert len(s) == 1500

    def test_pvalue_rejects_unit_root(self, eg_result):
        """ADF should reject unit root (p < 0.05) for the cointegrated spread."""
        assert eg_result["pvalue"] < 0.05

    def test_adf_stat_finite(self, eg_result):
        assert np.isfinite(eg_result["adf_stat"])

    def test_half_life_positive_finite(self, eg_result):
        hl = eg_result["half_life"]
        assert np.isfinite(hl)
        assert hl > 0.0

    def test_returns_required_keys(self, eg_result):
        assert set(eg_result) >= {"beta", "alpha", "spread", "adf_stat", "pvalue", "half_life"}


# ---------------------------------------------------------------------------
# engle_granger — TLS hedge
# ---------------------------------------------------------------------------

class TestEngleGrangerTLS:
    """TLS mode should also detect cointegration and return a valid beta."""

    @pytest.fixture(scope="class")
    def eg_tls(self):
        rng = np.random.default_rng(99)
        n = 1500
        x = _random_walk(n, rng)
        noise = _ou_noise(n, rng, kappa=0.4, sigma=0.4)
        y = 2.0 * x + noise
        return engle_granger(y, x, hedge="tls")

    def test_tls_beta_close_to_two(self, eg_tls):
        assert eg_tls["beta"] == pytest.approx(2.0, abs=0.25)

    def test_tls_pvalue_rejects_unit_root(self, eg_tls):
        assert eg_tls["pvalue"] < 0.05


# ---------------------------------------------------------------------------
# engle_granger — INDEPENDENT random walks (spurious regression)
# ---------------------------------------------------------------------------

class TestEngleGrangerSpurious:
    """Two independent I(1) series: ADF should NOT reject unit root in the spread."""

    @pytest.fixture(scope="class")
    def eg_spurious(self):
        # Use a larger n and a seed chosen so the spurious regression is clearly
        # non-cointegrated (pvalue well above 0.05 in expectation).
        rng = np.random.default_rng(1234)
        n = 2000
        y2 = _random_walk(n, rng)
        x2 = _random_walk(n, rng)
        return engle_granger(y2, x2)

    def test_pvalue_cannot_reject_at_5pct(self, eg_spurious):
        """For independent walks, residual contains a unit root -> p > 0.05."""
        assert eg_spurious["pvalue"] > 0.05


# ---------------------------------------------------------------------------
# johansen test
# ---------------------------------------------------------------------------

class TestJohansen:
    """Johansen on cointegrated bivariate system should detect rank >= 1."""

    @pytest.fixture(scope="class")
    def jo_result(self):
        rng = np.random.default_rng(42)
        n = 1500
        x = _random_walk(n, rng)
        noise = _ou_noise(n, rng, kappa=0.4, sigma=0.4)
        y = 2.0 * x + noise
        idx = x.index
        df = pd.DataFrame({"y": y.values, "x": x.values}, index=idx)
        return johansen(df)

    def test_rank_at_least_one(self, jo_result):
        assert jo_result["rank"] >= 1

    def test_coint_vector_first_element_one(self, jo_result):
        vec = jo_result["coint_vector"]
        assert vec[0] == pytest.approx(1.0)

    def test_coint_vector_recovers_hedge_ratio(self, jo_result):
        """Second element of normalized eigenvector ~ -2.0 (since y = 2x)."""
        vec = jo_result["coint_vector"]
        implied_beta = -vec[1]          # vec = [1, -beta] => beta = -vec[1]
        assert implied_beta == pytest.approx(2.0, abs=0.35)

    def test_trace_and_crit_shape(self, jo_result):
        assert len(jo_result["trace_stat"]) == len(jo_result["crit_trace"])
        assert len(jo_result["eigen_stat"]) == len(jo_result["trace_stat"])

    def test_returns_required_keys(self, jo_result):
        assert set(jo_result) >= {"trace_stat", "eigen_stat", "crit_trace", "coint_vector", "rank"}


# ---------------------------------------------------------------------------
# spread() utility
# ---------------------------------------------------------------------------

class TestSpreadUtility:
    def test_basic_spread(self):
        rng = np.random.default_rng(0)
        idx = pd.date_range("2020-01-01", periods=100, freq="B")
        x = pd.Series(rng.standard_normal(100), index=idx)
        y = pd.Series(rng.standard_normal(100), index=idx)
        s = spread(y, x, beta=1.5, alpha=0.5)
        expected = y - 0.5 - 1.5 * x
        pd.testing.assert_series_equal(s, expected)

    def test_spread_default_alpha_zero(self):
        rng = np.random.default_rng(1)
        idx = pd.date_range("2020-01-01", periods=50, freq="B")
        x = pd.Series(rng.standard_normal(50), index=idx)
        y = pd.Series(rng.standard_normal(50), index=idx)
        s = spread(y, x, beta=1.0)
        expected = y - x
        pd.testing.assert_series_equal(s, expected)


# ---------------------------------------------------------------------------
# zscore() utility
# ---------------------------------------------------------------------------

class TestZScore:
    @pytest.fixture(scope="class")
    def sample_series(self):
        rng = np.random.default_rng(10)
        idx = pd.date_range("2020-01-01", periods=300, freq="B")
        return pd.Series(rng.standard_normal(300), index=idx)

    def test_fullsample_mean_near_zero(self, sample_series):
        z = zscore(sample_series)
        assert abs(z.mean()) < 1e-10

    def test_fullsample_std_near_one(self, sample_series):
        # Implementation standardises with ddof=1; sample std (ddof=1) is 1.0 by construction.
        z = zscore(sample_series)
        assert abs(z.std(ddof=1) - 1.0) < 1e-10

    def test_rolling_zscore_shape(self, sample_series):
        z = zscore(sample_series, window=60)
        assert len(z) == len(sample_series)

    def test_rolling_zscore_is_series(self, sample_series):
        z = zscore(sample_series, window=60)
        assert isinstance(z, pd.Series)

    def test_rolling_zscore_has_nans_at_start(self, sample_series):
        z = zscore(sample_series, window=60)
        # First 59 values should be NaN (rolling window not filled)
        assert z.iloc[:59].isna().all()


# ---------------------------------------------------------------------------
# bands() utility
# ---------------------------------------------------------------------------

class TestBands:
    @pytest.fixture(scope="class")
    def sample_series(self):
        rng = np.random.default_rng(20)
        idx = pd.date_range("2020-01-01", periods=300, freq="B")
        return pd.Series(rng.standard_normal(300) * 2 + 1.0, index=idx)

    def test_fullsample_columns(self, sample_series):
        b = bands(sample_series)
        assert set(b.columns) >= {"mean", "upper", "lower"}

    def test_fullsample_upper_gt_mean_gt_lower(self, sample_series):
        b = bands(sample_series)
        assert (b["upper"] > b["mean"]).all()
        assert (b["mean"] > b["lower"]).all()

    def test_fullsample_symmetric(self, sample_series):
        b = bands(sample_series, k=2.0)
        width_up = b["upper"] - b["mean"]
        width_dn = b["mean"] - b["lower"]
        pd.testing.assert_series_equal(width_up, width_dn, check_names=False)

    def test_rolling_bands_shape(self, sample_series):
        b = bands(sample_series, window=60)
        assert b.shape == (300, 3)
        assert set(b.columns) >= {"mean", "upper", "lower"}

    def test_rolling_bands_valid_rows(self, sample_series):
        b = bands(sample_series, window=60)
        valid = b.dropna()
        assert (valid["upper"] > valid["mean"]).all()
        assert (valid["mean"] > valid["lower"]).all()


# ---------------------------------------------------------------------------
# make_cointegration_builder
# ---------------------------------------------------------------------------

class TestCointegrationBuilder:
    @pytest.fixture(scope="class")
    def builder_result(self):
        rng = np.random.default_rng(42)
        n = 1000
        idx = pd.date_range("2018-01-02", periods=n, freq="B")
        x_vals = rng.standard_normal(n).cumsum()
        noise = _ou_noise(n, rng, kappa=0.35, sigma=0.3).values
        y_vals = 2.0 * x_vals + noise
        df = pd.DataFrame({"y": y_vals, "x": x_vals}, index=idx)
        fit, get_spread, get_zscore, get_bands, get_data = make_cointegration_builder(df, "y", "x")
        result = fit()
        return result, get_spread, get_zscore, get_bands, get_data, df

    def test_fit_returns_dict(self, builder_result):
        result, *_ = builder_result
        assert isinstance(result, dict)
        assert "beta" in result

    def test_get_spread_returns_series(self, builder_result):
        _, get_spread, *_ = builder_result
        s = get_spread()
        assert isinstance(s, pd.Series)

    def test_get_zscore_returns_series(self, builder_result):
        _, _, get_zscore, *_ = builder_result
        z = get_zscore()
        assert isinstance(z, pd.Series)

    def test_get_bands_returns_dataframe(self, builder_result):
        _, _, _, get_bands, *_ = builder_result
        b = get_bands()
        assert isinstance(b, pd.DataFrame)
        assert "upper" in b.columns

    def test_get_data_returns_dataframe(self, builder_result):
        *_, get_data, df = builder_result
        d = get_data()
        assert isinstance(d, pd.DataFrame)
        assert len(d) == len(df)

    def test_invalid_hedge_raises(self):
        rng = np.random.default_rng(0)
        n = 100
        idx = pd.date_range("2020-01-01", periods=n, freq="B")
        x = pd.Series(rng.standard_normal(n), index=idx)
        y = pd.Series(rng.standard_normal(n), index=idx)
        with pytest.raises(ValueError):
            engle_granger(y, x, hedge="invalid")
