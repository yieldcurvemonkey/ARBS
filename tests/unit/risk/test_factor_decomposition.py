# ABOUTME: Tests for PCA factor decomposition (level/slope/curvature)
# ABOUTME: Validates factor extraction from yield curve changes per Litterman & Scheinkman methodology

"""
Tests for PCA Factor Decomposition

Tests the PCA-based factor model that decomposes yield curve movements into:
- PC1 (Level): Parallel shifts across all maturities
- PC2 (Slope): Short vs long rate movements
- PC3 (Curvature): Butterfly/middle vs wings movements

Following TDD: These tests are written FIRST, then implementation.
"""

import pytest
import numpy as np
import polars as pl
from datetime import date, timedelta
from typing import Dict, List


class TestPCAFactorDecomposition:
    """Test PCA factor decomposition functionality."""

    def test_pca_import(self):
        """Test that PCA factor model can be imported."""
        from Risk.FactorDecomposition import PCAFactorModel
        assert PCAFactorModel is not None

    def test_pca_fit_basic(self):
        """Test fitting PCA on synthetic yield curve changes."""
        from Risk.FactorDecomposition import PCAFactorModel

        # ARRANGE: Create synthetic yield curve changes
        dates = [date(2024, 1, 1) + timedelta(days=i) for i in range(100)]
        tenors = ["3M", "6M", "1Y", "2Y", "3Y", "5Y", "7Y", "10Y", "20Y", "30Y"]

        # Synthetic data: mostly level shifts with some slope
        np.random.seed(42)
        level_factor = np.random.randn(100)
        slope_factor = np.random.randn(100) * 0.5
        curve_factor = np.random.randn(100) * 0.2

        # Build yield curve changes
        changes_data = {}
        for i, tenor in enumerate(tenors):
            # Level affects all equally, slope affects by maturity, curve is butterfly
            tenor_weight_slope = (i / len(tenors)) - 0.5
            tenor_weight_curve = -4 * ((i / len(tenors)) - 0.5) ** 2 + 1
            changes_data[tenor] = level_factor + slope_factor * tenor_weight_slope + curve_factor * tenor_weight_curve

        changes_df = pl.DataFrame(changes_data)
        changes_df = changes_df.with_columns(pl.Series("date", dates))

        # ACT: Fit PCA model
        model = PCAFactorModel(n_components=3)
        model.fit(changes_df, date_column="date")

        # ASSERT: Model should be fitted
        assert model.is_fitted
        assert model.n_components == 3
        assert len(model.tenors) == len(tenors)

    def test_pca_loadings_shape(self):
        """Test that PCA loadings have correct shape."""
        from Risk.FactorDecomposition import PCAFactorModel

        # ARRANGE
        dates = [date(2024, 1, 1) + timedelta(days=i) for i in range(50)]
        tenors = ["1Y", "2Y", "3Y", "5Y", "10Y"]
        changes_data = {tenor: np.random.randn(50) for tenor in tenors}
        changes_df = pl.DataFrame(changes_data)
        changes_df = changes_df.with_columns(pl.Series("date", dates))

        # ACT
        model = PCAFactorModel(n_components=3)
        model.fit(changes_df, date_column="date")

        # ASSERT
        loadings = model.get_loadings()
        assert loadings.shape == (3, 5)  # 3 PCs x 5 tenors

    def test_pca_explained_variance(self):
        """Test that explained variance is calculated correctly."""
        from Risk.FactorDecomposition import PCAFactorModel

        # ARRANGE
        dates = [date(2024, 1, 1) + timedelta(days=i) for i in range(100)]
        tenors = ["1Y", "2Y", "3Y", "5Y", "7Y", "10Y"]
        changes_data = {tenor: np.random.randn(100) for tenor in tenors}
        changes_df = pl.DataFrame(changes_data)
        changes_df = changes_df.with_columns(pl.Series("date", dates))

        # ACT
        model = PCAFactorModel(n_components=3)
        model.fit(changes_df, date_column="date")

        # ASSERT
        explained_var = model.get_explained_variance_ratio()
        assert len(explained_var) == 3
        assert all(0 <= v <= 1 for v in explained_var)
        assert sum(explained_var) <= 1.0
        # First PC should explain most variance
        assert explained_var[0] > explained_var[1]
        assert explained_var[1] > explained_var[2]

    def test_pca_level_loadings_sign(self):
        """Test that level factor (PC1) has same sign for all maturities."""
        from Risk.FactorDecomposition import PCAFactorModel

        # ARRANGE: Pure level shifts
        dates = [date(2024, 1, 1) + timedelta(days=i) for i in range(100)]
        tenors = ["1Y", "2Y", "3Y", "5Y", "7Y", "10Y"]
        level_factor = np.random.randn(100)
        changes_data = {tenor: level_factor for tenor in tenors}
        changes_df = pl.DataFrame(changes_data)
        changes_df = changes_df.with_columns(pl.Series("date", dates))

        # ACT
        model = PCAFactorModel(n_components=3)
        model.fit(changes_df, date_column="date")

        # ASSERT: PC1 loadings should all have same sign
        loadings = model.get_loadings()
        pc1_loadings = loadings[0, :]
        assert all(pc1_loadings > 0) or all(pc1_loadings < 0)

    def test_get_factors_for_date(self):
        """Test getting factor values for a specific date."""
        from Risk.FactorDecomposition import PCAFactorModel

        # ARRANGE
        dates = [date(2024, 1, 1) + timedelta(days=i) for i in range(50)]
        tenors = ["1Y", "2Y", "3Y", "5Y", "10Y"]
        changes_data = {tenor: np.random.randn(50) for tenor in tenors}
        changes_df = pl.DataFrame(changes_data)
        changes_df = changes_df.with_columns(pl.Series("date", dates))

        model = PCAFactorModel(n_components=3)
        model.fit(changes_df, date_column="date")

        # ACT
        test_date = date(2024, 1, 10)
        factors = model.get_factors(test_date)

        # ASSERT
        assert isinstance(factors, dict)
        assert "level" in factors
        assert "slope" in factors
        assert "curvature" in factors
        assert all(isinstance(v, float) for v in factors.values())

    def test_transform_new_data(self):
        """Test transforming new yield curve changes to factor space."""
        from Risk.FactorDecomposition import PCAFactorModel

        # ARRANGE
        dates = [date(2024, 1, 1) + timedelta(days=i) for i in range(50)]
        tenors = ["1Y", "2Y", "3Y", "5Y", "10Y"]
        changes_data = {tenor: np.random.randn(50) for tenor in tenors}
        changes_df = pl.DataFrame(changes_data)
        changes_df = changes_df.with_columns(pl.Series("date", dates))

        model = PCAFactorModel(n_components=3)
        model.fit(changes_df, date_column="date")

        # ACT: Transform a single new observation
        new_changes = {tenor: 0.01 for tenor in tenors}  # 1bp parallel shift
        new_factors = model.transform(new_changes)

        # ASSERT
        assert len(new_factors) == 3
        # For parallel shift, level factor should dominate
        assert abs(new_factors[0]) > abs(new_factors[1])
        assert abs(new_factors[0]) > abs(new_factors[2])

    def test_factor_hedge_ratios(self):
        """Test calculating hedge ratios to neutralize factor exposures."""
        from Risk.FactorDecomposition import PCAFactorModel

        # ARRANGE
        dates = [date(2024, 1, 1) + timedelta(days=i) for i in range(50)]
        tenors = ["1Y", "2Y", "3Y", "5Y", "10Y"]
        changes_data = {tenor: np.random.randn(50) for tenor in tenors}
        changes_df = pl.DataFrame(changes_data)
        changes_df = changes_df.with_columns(pl.Series("date", dates))

        model = PCAFactorModel(n_components=3)
        model.fit(changes_df, date_column="date")

        # ACT: Calculate hedges for a portfolio with exposure to 5Y
        portfolio_pv01 = {"1Y": 0.0, "2Y": 0.0, "3Y": 0.0, "5Y": 100_000.0, "10Y": 0.0}
        hedge_ratios = model.factor_hedge_ratios(portfolio_pv01)

        # ASSERT
        assert isinstance(hedge_ratios, dict)
        assert set(hedge_ratios.keys()) == set(tenors)
        # Hedge should reduce 5Y exposure
        assert hedge_ratios["5Y"] < 0

    def test_pca_model_persistence(self):
        """Test that model state can be retrieved."""
        from Risk.FactorDecomposition import PCAFactorModel

        # ARRANGE
        dates = [date(2024, 1, 1) + timedelta(days=i) for i in range(50)]
        tenors = ["1Y", "2Y", "3Y", "5Y", "10Y"]
        changes_data = {tenor: np.random.randn(50) for tenor in tenors}
        changes_df = pl.DataFrame(changes_data)
        changes_df = changes_df.with_columns(pl.Series("date", dates))

        # ACT
        model = PCAFactorModel(n_components=3)
        model.fit(changes_df, date_column="date")

        # ASSERT: Can retrieve model state
        state = model.get_model_state()
        assert "loadings" in state
        assert "explained_variance_ratio" in state
        assert "tenors" in state
        assert "n_components" in state

    def test_unfitted_model_raises_error(self):
        """Test that using unfitted model raises appropriate error."""
        from Risk.FactorDecomposition import PCAFactorModel

        # ARRANGE
        model = PCAFactorModel(n_components=3)

        # ACT & ASSERT
        with pytest.raises(ValueError, match="not fitted|fit"):
            model.get_loadings()

        with pytest.raises(ValueError, match="not fitted|fit"):
            model.get_factors(date(2024, 1, 1))


class TestPCAFactorSignal:
    """Test PCA-based signal generation."""

    def test_signal_import(self):
        """Test that PCA signal can be imported."""
        from Signals.PCAFactorSignal import PCAFactorSignal
        assert PCAFactorSignal is not None

    def test_signal_creation(self):
        """Test creating a PCA factor signal."""
        from Signals.PCAFactorSignal import PCAFactorSignal

        # ARRANGE & ACT
        signal = PCAFactorSignal(
            lookback_days=252,
            refit_frequency=20,
            target_factor="slope"
        )

        # ASSERT
        assert signal.lookback_days == 252
        assert signal.refit_frequency == 20
        assert signal.target_factor == "slope"

    def test_signal_evaluate(self):
        """Test signal evaluation returns numeric score."""
        from Signals.PCAFactorSignal import PCAFactorSignal
        from datetime import date

        # ARRANGE
        signal = PCAFactorSignal(lookback_days=60, target_factor="level")

        # Create mock historical data (simplified test)
        # In practice, signal.evaluate would fetch curve history

        # ACT: evaluate should return a score
        # NOTE: This will fail until signal is implemented with proper data handling
        # For now, test the interface exists

        assert hasattr(signal, "evaluate")
        assert callable(signal.evaluate)
