# ABOUTME: Integration tests for sector-based covariance factory registration
# ABOUTME: Tests YAML strategy creation and parameter passing for all 3 models
"""
Factory Integration Tests for Sector-Based Covariance Models

Tests that all 3 sector-based covariance models can be:
1. Registered in the factory
2. Created from YAML configuration
3. Instantiated with correct parameters
4. Used in strategy creation
"""

import pytest
from pathlib import Path
import sys
import tempfile

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from Strategies.Factory.CovarianceFactory import CovarianceFactory
from Strategies.Config.StrategyConfig import StrategyConfig
from Risk.Covariance.SectorBased.BlockDiagonal.BlockDiagonalCovariance import (
    BlockDiagonalCovariance,
)
from Risk.Covariance.SectorBased.TwoStep.TwoStepCovariance import TwoStepCovariance
from Risk.Covariance.SectorBased.StochasticBlock.StochasticBlockCovariance import (
    StochasticBlockCovariance,
)


class TestCovarianceFactoryRegistration:
    """Tests for covariance factory registration."""

    def test_block_diagonal_registered(self):
        """Test that BlockDiagonalCovariance is registered."""
        available = CovarianceFactory.list_available_methods()
        assert "block_diagonal" in available

    def test_two_step_registered(self):
        """Test that TwoStepCovariance is registered."""
        available = CovarianceFactory.list_available_methods()
        assert "two_step" in available

    def test_stochastic_block_registered(self):
        """Test that StochasticBlockCovariance is registered."""
        available = CovarianceFactory.list_available_methods()
        assert "stochastic_block" in available


class TestCovarianceCreationFromConfig:
    """Tests for creating covariance estimators from config."""

    def test_create_block_diagonal_default(self):
        """Test creating BlockDiagonalCovariance with default parameters."""
        config_dict = {
            "strategy": {"name": "Test", "type": "carry"},
            "universe": {"asset_class": "futures", "instruments": "sp500"},
            "signals": [{"type": "carry"}],
            "risk": {
                "covariance": "block_diagonal",
            },
            "backtest": {"start_date": "2020-01-01", "end_date": "2024-01-01"},
        }

        config = StrategyConfig.from_dict(config_dict)
        estimator = CovarianceFactory.create_covariance_estimator(config)

        assert isinstance(estimator, BlockDiagonalCovariance)

    def test_create_block_diagonal_with_params(self):
        """Test creating BlockDiagonalCovariance with custom parameters."""
        config_dict = {
            "strategy": {"name": "Test", "type": "carry"},
            "universe": {"asset_class": "futures", "instruments": "sp500"},
            "signals": [{"type": "carry"}],
            "risk": {
                "covariance": "block_diagonal",
                "covariance_config": {
                    "n_factors": 5,
                    "clustering_method": "predefined",
                    "shrinkage_method": "ledoit_wolf",
                    "bias_correction": True,
                },
            },
            "backtest": {"start_date": "2020-01-01", "end_date": "2024-01-01"},
        }

        config = StrategyConfig.from_dict(config_dict)
        estimator = CovarianceFactory.create_covariance_estimator(config)

        assert isinstance(estimator, BlockDiagonalCovariance)
        assert estimator.n_factors == 5
        assert estimator.clustering_method == "predefined"
        assert estimator.shrinkage_method == "ledoit_wolf"
        assert estimator.bias_correction == True

    def test_create_two_step_default(self):
        """Test creating TwoStepCovariance with default parameters."""
        config_dict = {
            "strategy": {"name": "Test", "type": "carry"},
            "universe": {"asset_class": "futures", "instruments": "sp500"},
            "signals": [{"type": "carry"}],
            "risk": {
                "covariance": "two_step",
            },
            "backtest": {"start_date": "2020-01-01", "end_date": "2024-01-01"},
        }

        config = StrategyConfig.from_dict(config_dict)
        estimator = CovarianceFactory.create_covariance_estimator(config)

        assert isinstance(estimator, TwoStepCovariance)

    def test_create_two_step_with_params(self):
        """Test creating TwoStepCovariance with custom parameters."""
        config_dict = {
            "strategy": {"name": "Test", "type": "carry"},
            "universe": {"asset_class": "futures", "instruments": "sp500"},
            "signals": [{"type": "carry"}],
            "risk": {
                "covariance": "two_step",
                "covariance_config": {
                    "n_clusters": 10,
                    "linkage_method": "ward",
                    "rmt_filter": True,
                },
            },
            "backtest": {"start_date": "2020-01-01", "end_date": "2024-01-01"},
        }

        config = StrategyConfig.from_dict(config_dict)
        estimator = CovarianceFactory.create_covariance_estimator(config)

        assert isinstance(estimator, TwoStepCovariance)
        assert estimator.n_clusters == 10
        assert estimator.linkage_method == "ward"
        assert estimator.rmt_filter == True

    def test_create_stochastic_block_default(self):
        """Test creating StochasticBlockCovariance with default parameters."""
        config_dict = {
            "strategy": {"name": "Test", "type": "carry"},
            "universe": {"asset_class": "futures", "instruments": "sp500"},
            "signals": [{"type": "carry"}],
            "risk": {
                "covariance": "stochastic_block",
            },
            "backtest": {"start_date": "2020-01-01", "end_date": "2024-01-01"},
        }

        config = StrategyConfig.from_dict(config_dict)
        estimator = CovarianceFactory.create_covariance_estimator(config)

        assert isinstance(estimator, StochasticBlockCovariance)

    def test_create_stochastic_block_with_params(self):
        """Test creating StochasticBlockCovariance with custom parameters."""
        config_dict = {
            "strategy": {"name": "Test", "type": "carry"},
            "universe": {"asset_class": "futures", "instruments": "sp500"},
            "signals": [{"type": "carry"}],
            "risk": {
                "covariance": "stochastic_block",
                "covariance_config": {
                    "allow_inter_block": True,
                    "alpha": 0.7,
                    "shrinkage_per_block": True,
                },
            },
            "backtest": {"start_date": "2020-01-01", "end_date": "2024-01-01"},
        }

        config = StrategyConfig.from_dict(config_dict)
        estimator = CovarianceFactory.create_covariance_estimator(config)

        assert isinstance(estimator, StochasticBlockCovariance)
        assert estimator.allow_inter_block == True
        assert estimator.alpha == 0.7
        assert estimator.shrinkage_per_block == True


class TestYAMLStrategyTemplates:
    """Tests for YAML strategy templates."""

    def test_load_block_diagonal_yaml(self):
        """Test loading block_diagonal strategy from YAML."""
        yaml_path = "config/strategies/sector_rotation_block_diagonal.yaml"

        # Check file exists
        assert Path(yaml_path).exists(), f"YAML file not found: {yaml_path}"

        # Load config
        config = StrategyConfig.from_yaml(yaml_path)

        # Verify covariance method
        assert config.risk.covariance == "block_diagonal"
        assert config.risk.covariance_config["n_factors"] == 5
        assert config.risk.covariance_config["clustering_method"] == "predefined"

        # Create estimator
        estimator = CovarianceFactory.create_covariance_estimator(config)
        assert isinstance(estimator, BlockDiagonalCovariance)

    def test_load_two_step_yaml(self):
        """Test loading two_step strategy from YAML."""
        yaml_path = "config/strategies/sector_rotation_two_step.yaml"

        # Check file exists
        assert Path(yaml_path).exists(), f"YAML file not found: {yaml_path}"

        # Load config
        config = StrategyConfig.from_yaml(yaml_path)

        # Verify covariance method
        assert config.risk.covariance == "two_step"
        assert config.risk.covariance_config["n_clusters"] == 10
        assert config.risk.covariance_config["linkage_method"] == "ward"
        assert config.risk.covariance_config["rmt_filter"] == True

        # Create estimator
        estimator = CovarianceFactory.create_covariance_estimator(config)
        assert isinstance(estimator, TwoStepCovariance)

    def test_load_stochastic_block_yaml(self):
        """Test loading stochastic_block strategy from YAML."""
        yaml_path = "config/strategies/macro_stochastic_block.yaml"

        # Check file exists
        assert Path(yaml_path).exists(), f"YAML file not found: {yaml_path}"

        # Load config
        config = StrategyConfig.from_yaml(yaml_path)

        # Verify covariance method
        assert config.risk.covariance == "stochastic_block"
        assert config.risk.covariance_config["allow_inter_block"] == True
        assert config.risk.covariance_config["alpha"] == 0.7

        # Create estimator
        estimator = CovarianceFactory.create_covariance_estimator(config)
        assert isinstance(estimator, StochasticBlockCovariance)

    def test_all_yaml_templates_load_successfully(self):
        """Test that all YAML templates load without errors."""
        yaml_files = [
            "config/strategies/sector_rotation_block_diagonal.yaml",
            "config/strategies/sector_rotation_two_step.yaml",
            "config/strategies/macro_stochastic_block.yaml",
        ]

        for yaml_path in yaml_files:
            print(f"\nTesting {yaml_path}...")

            # Load config
            config = StrategyConfig.from_yaml(yaml_path)

            # Create estimator
            estimator = CovarianceFactory.create_covariance_estimator(config)

            # Verify it's a valid covariance estimator
            assert hasattr(estimator, "fit")
            assert callable(estimator.fit)

            print(f"  ✓ {config.strategy.name} loaded successfully")
            print(f"  ✓ Covariance: {config.risk.covariance}")


if __name__ == "__main__":
    # Run tests manually
    print("=" * 70)
    print("Testing Factory Registration...")
    print("=" * 70)

    test_reg = TestCovarianceFactoryRegistration()
    test_reg.test_block_diagonal_registered()
    test_reg.test_two_step_registered()
    test_reg.test_stochastic_block_registered()
    print("✓ All models registered\n")

    print("=" * 70)
    print("Testing Creation from Config...")
    print("=" * 70)

    test_create = TestCovarianceCreationFromConfig()
    test_create.test_create_block_diagonal_with_params()
    test_create.test_create_two_step_with_params()
    test_create.test_create_stochastic_block_with_params()
    print("✓ All models created successfully\n")

    print("=" * 70)
    print("Testing YAML Templates...")
    print("=" * 70)

    test_yaml = TestYAMLStrategyTemplates()
    test_yaml.test_all_yaml_templates_load_successfully()
    print("\n✓ All YAML templates loaded successfully\n")

    print("=" * 70)
    print("All Factory Integration Tests Passed!")
    print("=" * 70)
