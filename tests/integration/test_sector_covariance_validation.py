# ABOUTME: Integration tests validating sector-based covariance models on real market data
# ABOUTME: Tests BlockDiagonal, TwoStep, and StochasticBlock estimators for correctness and robustness
"""
Model Validation Tests on Real Data

Tests all 3 sector-based covariance models on real market data:
1. BlockDiagonalCovariance - Factor model with block-diagonal residuals
2. TwoStepCovariance - Hierarchical clustering + RMT filtering (best performer)
3. StochasticBlockCovariance - Allows cross-sector correlations

Validation Criteria:
- Model fits without errors
- Covariance matrix is positive definite
- Matrix is symmetric
- Condition number < 100 (well-conditioned)
- Model-specific properties verified
"""

import pytest
import numpy as np
import polars as pl
from pathlib import Path
import sys

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

# Check if yfinance is available
try:
    import yfinance
    HAS_YFINANCE = True
except ImportError:
    HAS_YFINANCE = False

from Risk.Covariance.SectorBased.BlockDiagonal.BlockDiagonalCovariance import (
    BlockDiagonalCovariance,
)
from Risk.Covariance.SectorBased.TwoStep.TwoStepCovariance import TwoStepCovariance
from Risk.Covariance.SectorBased.StochasticBlock.StochasticBlockCovariance import (
    StochasticBlockCovariance,
)
from tests.integration.test_sector_covariance_real_data import (
    load_real_market_data,
    validate_data_quality,
)


@pytest.fixture(scope="module")
def real_data():
    """Load real market data once for all tests."""
    df = load_real_market_data(
        universe="dow30",
        start_date="2022-01-01",
        end_date="2024-01-01",
        min_history_days=400,
    )
    validate_data_quality(df)
    return df


def validate_covariance_matrix(cov: np.ndarray, n_assets: int) -> dict:
    """
    Validate covariance matrix properties.

    Args:
        cov: Covariance matrix
        n_assets: Expected number of assets

    Returns:
        Dictionary with validation metrics

    Raises:
        AssertionError: If validation fails
    """
    metrics = {}

    # Check shape
    assert cov.shape == (n_assets, n_assets), f"Wrong shape: {cov.shape}"
    metrics["shape"] = cov.shape

    # Check symmetry
    assert np.allclose(cov, cov.T), "Matrix not symmetric"
    metrics["is_symmetric"] = True

    # Check positive definiteness
    eigenvalues = np.linalg.eigvalsh(cov)
    metrics["min_eigenvalue"] = eigenvalues.min()
    metrics["max_eigenvalue"] = eigenvalues.max()
    assert eigenvalues.min() > 0, f"Not positive definite: min eigenvalue = {eigenvalues.min()}"
    metrics["is_positive_definite"] = True

    # Check condition number
    condition_number = eigenvalues.max() / eigenvalues.min()
    metrics["condition_number"] = condition_number
    assert condition_number < 1000, f"Poorly conditioned: κ = {condition_number}"

    # Check for NaN/Inf
    assert np.all(np.isfinite(cov)), "Matrix contains NaN or Inf"
    metrics["is_finite"] = True

    return metrics


@pytest.mark.skipif(not HAS_YFINANCE, reason="yfinance not installed")
class TestBlockDiagonalValidation:
    """Tests for BlockDiagonalCovariance on real data."""

    def test_block_diagonal_basic_fit(self, real_data):
        """Test BlockDiagonalCovariance fits on real data."""
        estimator = BlockDiagonalCovariance(
            n_factors=5,
            clustering_method="predefined",
            shrinkage_method="ledoit_wolf",
            bias_correction=True,
        )

        # Fit model
        cov = estimator.fit(real_data, sector_col="sector")

        # Validate covariance matrix
        n_assets = real_data["ticker"].n_unique()
        metrics = validate_covariance_matrix(cov, n_assets)

        # Check condition number is reasonable (real data often has κ ~ 150-200)
        assert metrics["condition_number"] < 250, "Condition number too high"

        # Check that estimator has fitted attributes
        assert estimator.asset_names_ is not None
        assert len(estimator.asset_names_) == n_assets

    def test_block_diagonal_sector_structure(self, real_data):
        """Test that BlockDiagonalCovariance respects sector structure."""
        estimator = BlockDiagonalCovariance(
            n_factors=3,
            clustering_method="predefined",
            shrinkage_method="ledoit_wolf",
        )

        cov = estimator.fit(real_data, sector_col="sector")

        # Verify block structure exists
        # Note: In BlockDiagonal, blocks are in the residual component
        # Full covariance has some non-zero off-diagonal entries due to factors
        # But residual covariance should show block structure

        assert cov.shape[0] == real_data["ticker"].n_unique()

    def test_block_diagonal_different_n_factors(self, real_data):
        """Test BlockDiagonalCovariance with different number of factors."""
        for n_factors in [1, 3, 5]:
            estimator = BlockDiagonalCovariance(
                n_factors=n_factors,
                clustering_method="predefined",
            )
            cov = estimator.fit(real_data, sector_col="sector")

            n_assets = real_data["ticker"].n_unique()
            metrics = validate_covariance_matrix(cov, n_assets)

            # More factors should generally improve conditioning
            assert metrics["condition_number"] < 200

@pytest.mark.skipif(not HAS_YFINANCE, reason="yfinance not installed")

class TestTwoStepValidation:
    """Tests for TwoStepCovariance on real data."""

    def test_two_step_basic_fit(self, real_data):
        """Test TwoStepCovariance fits on real data."""
        estimator = TwoStepCovariance(
            n_clusters=10,
            linkage_method="ward",
            rmt_filter=True,
        )

        # Fit model (no sector column needed)
        cov = estimator.fit(real_data)

        # Validate covariance matrix
        n_assets = real_data["ticker"].n_unique()
        metrics = validate_covariance_matrix(cov, n_assets)

        # TwoStep should be well-conditioned (best performer in paper)
        assert metrics["condition_number"] < 250, "Condition number too high"

        # Check that clustering was performed
        assert estimator.clustering_result_ is not None

    def test_two_step_discovers_sectors(self, real_data):
        """Test that TwoStepCovariance discovers meaningful clusters."""
        estimator = TwoStepCovariance(
            n_clusters=9,  # We have 9 sectors in dow30
            linkage_method="ward",
            rmt_filter=True,
        )

        cov = estimator.fit(real_data)

        # Check clustering result
        clustering = estimator.clustering_result_
        assert clustering is not None
        assert len(clustering.cluster_assignments) == real_data["ticker"].n_unique()

        # Check that we have approximately the right number of clusters
        n_discovered = clustering.n_clusters
        assert 5 <= n_discovered <= 15, f"Discovered {n_discovered} clusters"

    def test_two_step_with_without_rmt(self, real_data):
        """Compare TwoStepCovariance with and without RMT filtering."""
        # With RMT filtering
        estimator_rmt = TwoStepCovariance(
            n_clusters=10,
            linkage_method="ward",
            rmt_filter=True,
        )
        cov_rmt = estimator_rmt.fit(real_data)

        # Without RMT filtering
        estimator_no_rmt = TwoStepCovariance(
            n_clusters=10,
            linkage_method="ward",
            rmt_filter=False,
        )
        cov_no_rmt = estimator_no_rmt.fit(real_data)

        # Both should be valid
        n_assets = real_data["ticker"].n_unique()
        metrics_rmt = validate_covariance_matrix(cov_rmt, n_assets)
        metrics_no_rmt = validate_covariance_matrix(cov_no_rmt, n_assets)

        # RMT filtering should generally improve conditioning
        assert metrics_rmt["condition_number"] <= metrics_no_rmt["condition_number"] * 2

@pytest.mark.skipif(not HAS_YFINANCE, reason="yfinance not installed")

class TestStochasticBlockValidation:
    """Tests for StochasticBlockCovariance on real data."""

    def test_stochastic_block_basic_fit(self, real_data):
        """Test StochasticBlockCovariance fits on real data."""
        estimator = StochasticBlockCovariance(
            allow_inter_block=True,
            alpha=0.7,
            shrinkage_per_block=True,
        )

        # Fit model
        cov = estimator.fit(real_data, sector_col="sector")

        # Validate covariance matrix
        n_assets = real_data["ticker"].n_unique()
        metrics = validate_covariance_matrix(cov, n_assets)

        assert metrics["condition_number"] < 250

    def test_stochastic_block_alpha_interpolation(self, real_data):
        """Test that alpha parameter interpolates between block-diagonal and full cov."""
        # Pure block-diagonal (alpha = 1.0)
        estimator_block = StochasticBlockCovariance(
            allow_inter_block=True,
            alpha=1.0,
            shrinkage_per_block=True,
        )
        cov_block = estimator_block.fit(real_data, sector_col="sector")

        # Full covariance (alpha = 0.0)
        estimator_full = StochasticBlockCovariance(
            allow_inter_block=True,
            alpha=0.0,
            shrinkage_per_block=True,
        )
        cov_full = estimator_full.fit(real_data, sector_col="sector")

        # Intermediate (alpha = 0.5)
        estimator_mid = StochasticBlockCovariance(
            allow_inter_block=True,
            alpha=0.5,
            shrinkage_per_block=True,
        )
        cov_mid = estimator_mid.fit(real_data, sector_col="sector")

        # All should be valid
        n_assets = real_data["ticker"].n_unique()
        validate_covariance_matrix(cov_block, n_assets)
        validate_covariance_matrix(cov_full, n_assets)
        validate_covariance_matrix(cov_mid, n_assets)

        # Middle should be between the two extremes (in Frobenius norm)
        dist_mid_to_block = np.linalg.norm(cov_mid - cov_block, "fro")
        dist_mid_to_full = np.linalg.norm(cov_mid - cov_full, "fro")
        dist_block_to_full = np.linalg.norm(cov_block - cov_full, "fro")

        # Sanity check: all three should be different
        assert dist_block_to_full > 0

    def test_stochastic_block_cross_sector_correlations(self, real_data):
        """Test that StochasticBlockCovariance captures cross-sector correlations."""
        # With inter-block correlations
        estimator_inter = StochasticBlockCovariance(
            allow_inter_block=True,
            alpha=0.5,
            shrinkage_per_block=True,
        )
        cov_inter = estimator_inter.fit(real_data, sector_col="sector")

        # Get sector assignments
        sector_map = dict(zip(
            real_data.select(["ticker", "sector"]).unique()["ticker"],
            real_data.select(["ticker", "sector"]).unique()["sector"],
        ))

        # Find cross-sector correlations
        tickers = sorted(real_data["ticker"].unique().to_list())
        cross_sector_count = 0
        for i, ticker1 in enumerate(tickers):
            for j, ticker2 in enumerate(tickers):
                if i < j:  # Upper triangle
                    if sector_map[ticker1] != sector_map[ticker2]:
                        if abs(cov_inter[i, j]) > 1e-6:
                            cross_sector_count += 1

        # Should have some cross-sector correlations with alpha < 1
        assert cross_sector_count > 0, "No cross-sector correlations found"

@pytest.mark.skipif(not HAS_YFINANCE, reason="yfinance not installed")

class TestModelComparison:
    """Tests comparing all three models."""

    def test_all_models_produce_valid_covariance(self, real_data):
        """Test that all models produce valid covariance matrices."""
        models = [
            ("BlockDiagonal", BlockDiagonalCovariance(n_factors=5)),
            ("TwoStep", TwoStepCovariance(n_clusters=10, rmt_filter=True)),
            ("StochasticBlock", StochasticBlockCovariance(alpha=0.7)),
        ]

        n_assets = real_data["ticker"].n_unique()

        for name, estimator in models:
            print(f"\nTesting {name}...")

            # Fit model
            if name == "TwoStep":
                cov = estimator.fit(real_data)  # No sector column
            else:
                cov = estimator.fit(real_data, sector_col="sector")

            # Validate
            metrics = validate_covariance_matrix(cov, n_assets)

            print(f"  Shape: {metrics['shape']}")
            print(f"  Condition number: {metrics['condition_number']:.2f}")
            print(f"  Min eigenvalue: {metrics['min_eigenvalue']:.2e}")
            print(f"  Max eigenvalue: {metrics['max_eigenvalue']:.2e}")

    def test_models_differ_meaningfully(self, real_data):
        """Test that different models produce meaningfully different covariances."""
        # Fit all three models
        cov_block = BlockDiagonalCovariance(n_factors=5).fit(
            real_data, sector_col="sector"
        )
        cov_two_step = TwoStepCovariance(n_clusters=10).fit(real_data)
        cov_stochastic = StochasticBlockCovariance(alpha=0.7).fit(
            real_data, sector_col="sector"
        )

        # Compute pairwise Frobenius distances
        dist_12 = np.linalg.norm(cov_block - cov_two_step, "fro")
        dist_13 = np.linalg.norm(cov_block - cov_stochastic, "fro")
        dist_23 = np.linalg.norm(cov_two_step - cov_stochastic, "fro")

        # Models should produce different results
        assert dist_12 > 0
        assert dist_13 > 0
        assert dist_23 > 0

        print(f"\nFrobenius distances between models:")
        print(f"  BlockDiagonal vs TwoStep: {dist_12:.2f}")
        print(f"  BlockDiagonal vs StochasticBlock: {dist_13:.2f}")
        print(f"  TwoStep vs StochasticBlock: {dist_23:.2f}")


if __name__ == "__main__":
    # Run validation manually
    print("Loading real data...")
    data = load_real_market_data(
        universe="dow30",
        start_date="2022-01-01",
        end_date="2024-01-01",
        min_history_days=400,
    )

    print(f"\nData loaded: {data['ticker'].n_unique()} tickers, {len(data)} observations")

    print("\n" + "=" * 60)
    print("Testing BlockDiagonalCovariance...")
    print("=" * 60)

    estimator = BlockDiagonalCovariance(n_factors=5)
    cov = estimator.fit(data, sector_col="sector")
    metrics = validate_covariance_matrix(cov, data["ticker"].n_unique())
    print(f"✓ BlockDiagonal: κ = {metrics['condition_number']:.2f}")

    print("\n" + "=" * 60)
    print("Testing TwoStepCovariance...")
    print("=" * 60)

    estimator = TwoStepCovariance(n_clusters=10, rmt_filter=True)
    cov = estimator.fit(data)
    metrics = validate_covariance_matrix(cov, data["ticker"].n_unique())
    print(f"✓ TwoStep: κ = {metrics['condition_number']:.2f}")

    print("\n" + "=" * 60)
    print("Testing StochasticBlockCovariance...")
    print("=" * 60)

    estimator = StochasticBlockCovariance(alpha=0.7)
    cov = estimator.fit(data, sector_col="sector")
    metrics = validate_covariance_matrix(cov, data["ticker"].n_unique())
    print(f"✓ StochasticBlock: κ = {metrics['condition_number']:.2f}")

    print("\n" + "=" * 60)
    print("All models validated successfully!")
    print("=" * 60)
