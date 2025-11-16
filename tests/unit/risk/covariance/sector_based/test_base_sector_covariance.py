# ABOUTME: Tests for SectorBasedCovarianceEstimator abstract base class
# ABOUTME: Validates common sector-based functionality across all implementations
"""
Tests for SectorBasedCovarianceEstimator

Tests common functionality shared by all sector-based covariance models:
- Data validation
- Wide format conversion
- Sector assignment determination
- Positive definiteness enforcement
"""

from typing import Optional

import numpy as np
import polars as pl
import pytest

from Risk.Covariance.SectorBased.BaseSectorCovarianceEstimator import SectorBasedCovarianceEstimator


# Create concrete implementation for testing abstract class
class MockSectorCovariance(SectorBasedCovarianceEstimator):
    """Concrete implementation for testing abstract base class."""

    def _fit_impl(self, returns: pl.DataFrame, sector_col: Optional[str] = "sector") -> np.ndarray:
        """Mock fit method."""
        # Convert to wide format
        returns_wide, tickers = self._convert_to_wide_format(returns)
        self.asset_names_ = tickers

        # Determine sector assignments
        self.sector_mapping_ = self._determine_sector_assignments(returns_wide, tickers, returns, sector_col)

        # Create mock covariance (just identity for testing)
        n = len(tickers)
        return np.eye(n)


class TestSectorBasedCovarianceEstimator:
    """Test suite for SectorBasedCovarianceEstimator base class."""

    @pytest.fixture
    def sample_returns_long(self):
        """Create sample returns in long format."""
        return pl.DataFrame(
            {
                "ticker": ["AAPL", "MSFT", "JPM", "AAPL", "MSFT", "JPM"],
                "date": ["2024-01-01", "2024-01-01", "2024-01-01", "2024-01-02", "2024-01-02", "2024-01-02"],
                "return": [0.01, 0.02, 0.005, 0.015, -0.01, -0.002],
                "sector": ["Tech", "Tech", "Finance", "Tech", "Tech", "Finance"],
            }
        )

    @pytest.fixture
    def estimator(self):
        """Create mock estimator for testing."""
        return MockSectorCovariance(clustering_method="predefined")

    def test_initialization(self):
        """Test basic initialization."""
        est = MockSectorCovariance(clustering_method="predefined")
        assert est.clustering_method == "predefined"
        assert est.sector_mapping_ is None

    def test_validate_sector_input_valid(self, estimator, sample_returns_long):
        """Test validation passes for valid data."""
        # Should not raise
        estimator._validate_sector_input(sample_returns_long, "sector")

    def test_validate_sector_input_missing_sector_col(self, estimator, sample_returns_long):
        """Test validation fails when sector column missing."""
        with pytest.raises(ValueError, match="sector_col must be provided"):
            estimator._validate_sector_input(sample_returns_long, None)

    def test_validate_sector_input_missing_required_columns(self, estimator):
        """Test validation fails when required columns missing."""
        bad_data = pl.DataFrame({"ticker": ["AAPL"], "date": ["2024-01-01"]})

        with pytest.raises(ValueError, match="Missing required columns"):
            estimator._validate_sector_input(bad_data, "sector")

    def test_convert_to_wide_format(self, estimator):
        """Test long to wide format conversion."""
        long_data = pl.DataFrame(
            {
                "ticker": ["A", "B", "A", "B"],
                "date": ["2024-01-01", "2024-01-01", "2024-01-02", "2024-01-02"],
                "return": [0.01, 0.02, 0.015, 0.025],
            }
        )

        wide, tickers = estimator._convert_to_wide_format(long_data)

        assert wide.shape == (2, 2)  # 2 dates × 2 tickers
        assert set(tickers) == {"A", "B"}
        assert isinstance(wide, np.ndarray)

    def test_determine_sector_assignments_predefined(self, estimator, sample_returns_long):
        """Test predefined sector assignment."""
        # Convert to wide first
        wide, tickers = estimator._convert_to_wide_format(sample_returns_long)

        sector_map = estimator._determine_sector_assignments(wide, tickers, sample_returns_long, "sector")

        assert sector_map["AAPL"] == "Tech"
        assert sector_map["MSFT"] == "Tech"
        assert sector_map["JPM"] == "Finance"

    def test_determine_sector_assignments_hierarchical(self, sample_returns_long):
        """Test hierarchical sector discovery."""
        est = MockSectorCovariance(clustering_method="hierarchical")

        # Create simple returns matrix
        wide = np.array([[0.01, 0.02, 0.005], [0.015, 0.018, 0.003]])
        tickers = ["AAPL", "MSFT", "JPM"]

        sector_map = est._determine_sector_assignments(wide, tickers, sample_returns_long, None)

        # Should have cluster assignments
        assert len(sector_map) == 3
        assert all(ticker in sector_map for ticker in tickers)
        assert all("Cluster" in val for val in sector_map.values())

    def test_ensure_positive_definite_already_positive(self, estimator):
        """Test PD enforcement on already positive definite matrix."""
        cov = np.array([[1.0, 0.5], [0.5, 1.0]])

        cov_pd = estimator._ensure_positive_definite(cov)

        # Should be unchanged (already PD)
        eigenvalues = np.linalg.eigvalsh(cov_pd)
        assert np.all(eigenvalues > 0)

    def test_ensure_positive_definite_negative_eigenvalues(self, estimator):
        """Test PD enforcement clips negative eigenvalues."""
        # Create matrix with negative eigenvalue
        eigenvalues = np.array([2.0, -0.1])
        eigenvectors = np.array([[1, 0], [0, 1]])
        cov = eigenvectors @ np.diag(eigenvalues) @ eigenvectors.T

        cov_pd = estimator._ensure_positive_definite(cov, min_eigenvalue=1e-8)

        # Should have all positive eigenvalues
        new_eigenvalues = np.linalg.eigvalsh(cov_pd)
        assert np.all(new_eigenvalues >= 1e-8)

    def test_ensure_positive_definite_preserves_symmetry(self, estimator):
        """Test PD enforcement preserves symmetry."""
        cov = np.array([[1.0, 0.5, 0.3], [0.5, 1.0, 0.4], [0.3, 0.4, 1.0]])

        cov_pd = estimator._ensure_positive_definite(cov)

        # Check symmetry
        assert np.allclose(cov_pd, cov_pd.T)

    def test_get_sector_mapping_before_fit(self, estimator):
        """Test getting sector mapping before fit raises error."""
        with pytest.raises(ValueError, match="Must call fit"):
            estimator.get_sector_mapping()

    def test_get_sector_mapping_after_fit(self, estimator, sample_returns_long):
        """Test getting sector mapping after fit."""
        estimator.fit(sample_returns_long)

        sector_map = estimator.get_sector_mapping()

        assert sector_map["AAPL"] == "Tech"
        assert sector_map["MSFT"] == "Tech"
        assert sector_map["JPM"] == "Finance"

    def test_get_sector_groups(self, estimator, sample_returns_long):
        """Test getting sector groups after fit."""
        estimator.fit(sample_returns_long)

        groups = estimator.get_sector_groups()

        assert "Tech" in groups
        assert "Finance" in groups
        assert set(groups["Tech"]) == {"AAPL", "MSFT"}
        assert set(groups["Finance"]) == {"JPM"}

    def test_integration_predefined_sectors(self, estimator, sample_returns_long):
        """Test full integration with predefined sectors."""
        cov = estimator.fit(sample_returns_long, sector_col="sector")

        # Check outputs
        assert cov.shape == (3, 3)  # 3 unique tickers
        assert estimator.asset_names_ is not None
        assert estimator.sector_mapping_ is not None

    def test_integration_hierarchical_clustering(self, sample_returns_long):
        """Test full integration with hierarchical clustering."""
        est = MockSectorCovariance(clustering_method="hierarchical")
        cov = est.fit(sample_returns_long)

        # Check outputs
        assert cov.shape == (3, 3)
        assert est.asset_names_ is not None
        assert est.sector_mapping_ is not None
        assert all("Cluster" in val for val in est.sector_mapping_.values())
