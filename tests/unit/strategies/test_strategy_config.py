# ABOUTME: Unit tests for StrategyConfig YAML parser and validator
# ABOUTME: Tests configuration loading, validation, and error handling
"""
Tests for StrategyConfig

Tests YAML parsing, validation, and configuration object creation.
"""

import pytest
import yaml
from pathlib import Path
import tempfile

from Strategies.Config.StrategyConfig import (
    StrategyConfig,
    SignalConfig,
    AlphaConfig,
    RiskConfig,
    OptimizerConfig,
    OptimizerConstraints,
    ExecutionConfig,
    BacktestConfig,
    UniverseConfig,
    StrategyMetadata
)


class TestSignalConfig:
    """Test SignalConfig validation."""

    def test_valid_signal_config(self):
        """Valid signal configuration should succeed."""
        config = SignalConfig(type='carry', config={'standardize': True})
        assert config.type == 'carry'
        assert config.config == {'standardize': True}
        assert config.weight == 1.0

    def test_invalid_signal_type(self):
        """Invalid signal type should raise ValueError."""
        with pytest.raises(ValueError, match="Invalid signal type"):
            SignalConfig(type='invalid_type')

    def test_negative_weight(self):
        """Negative weight should raise ValueError."""
        with pytest.raises(ValueError, match="weight must be non-negative"):
            SignalConfig(type='carry', weight=-1.0)


class TestAlphaConfig:
    """Test AlphaConfig validation."""

    def test_valid_alpha_config(self):
        """Valid alpha configuration should succeed."""
        config = AlphaConfig(IC=0.05, method='static')
        assert config.IC == 0.05
        assert config.method == 'static'

    def test_invalid_ic_range(self):
        """IC outside (0, 1) should raise ValueError."""
        with pytest.raises(ValueError, match="IC must be between"):
            AlphaConfig(IC=1.5)

        with pytest.raises(ValueError, match="IC must be between"):
            AlphaConfig(IC=0.0)

    def test_invalid_method(self):
        """Invalid IC method should raise ValueError."""
        with pytest.raises(ValueError, match="Invalid IC method"):
            AlphaConfig(method='invalid')


class TestRiskConfig:
    """Test RiskConfig validation."""

    def test_valid_risk_config(self):
        """Valid risk configuration should succeed."""
        config = RiskConfig(covariance='ledoit_wolf')
        assert config.covariance == 'ledoit_wolf'

    def test_invalid_covariance(self):
        """Invalid covariance method should raise ValueError."""
        with pytest.raises(ValueError, match="Invalid covariance method"):
            RiskConfig(covariance='invalid')

    def test_negative_volatility_target(self):
        """Negative volatility target should raise ValueError."""
        with pytest.raises(ValueError, match="Volatility target must be positive"):
            RiskConfig(volatility_target=-0.1)


class TestOptimizerConfig:
    """Test OptimizerConfig validation."""

    def test_valid_optimizer_config(self):
        """Valid optimizer configuration should succeed."""
        constraints = OptimizerConstraints(long_only=True, max_position=0.30)
        config = OptimizerConfig(risk_aversion=1.0, constraints=constraints)
        assert config.risk_aversion == 1.0
        assert config.constraints.max_position == 0.30

    def test_negative_risk_aversion(self):
        """Negative risk aversion should raise ValueError."""
        with pytest.raises(ValueError, match="risk_aversion must be positive"):
            OptimizerConfig(risk_aversion=-1.0)

    def test_invalid_max_position(self):
        """Invalid max_position should raise ValueError."""
        with pytest.raises(ValueError, match="max_position must be between"):
            OptimizerConstraints(max_position=1.5)


class TestBacktestConfig:
    """Test BacktestConfig validation."""

    def test_valid_backtest_config(self):
        """Valid backtest configuration should succeed."""
        config = BacktestConfig(
            start_date='2024-01-01',
            end_date='2024-12-31',
            initial_capital=1000000.0
        )
        assert config.start_date == '2024-01-01'
        assert config.end_date == '2024-12-31'

    def test_invalid_date_format(self):
        """Invalid date format should raise ValueError."""
        with pytest.raises(ValueError, match="Invalid date format"):
            BacktestConfig(
                start_date='2024/01/01',  # Wrong format
                end_date='2024-12-31'
            )

    def test_start_after_end(self):
        """Start date after end date should raise ValueError."""
        with pytest.raises(ValueError, match="start_date must be before end_date"):
            BacktestConfig(
                start_date='2024-12-31',
                end_date='2024-01-01'
            )

    def test_negative_capital(self):
        """Negative initial capital should raise ValueError."""
        with pytest.raises(ValueError, match="initial_capital must be positive"):
            BacktestConfig(
                start_date='2024-01-01',
                end_date='2024-12-31',
                initial_capital=-100
            )


class TestStrategyConfig:
    """Test complete StrategyConfig."""

    @pytest.fixture
    def minimal_config_dict(self):
        """Minimal valid configuration."""
        return {
            'strategy': {
                'name': 'Test Strategy',
                'type': 'carry'
            },
            'universe': {
                'asset_class': 'futures',
                'instruments': ['SFRZ4', 'SFRH5']
            },
            'signals': [
                {'type': 'carry'}
            ],
            'backtest': {
                'start_date': '2024-01-01',
                'end_date': '2024-12-31'
            }
        }

    def test_from_dict_minimal(self, minimal_config_dict):
        """Minimal configuration should succeed with defaults."""
        config = StrategyConfig.from_dict(minimal_config_dict)

        assert config.strategy.name == 'Test Strategy'
        assert config.strategy.type == 'carry'
        assert len(config.universe.instruments) == 2
        assert len(config.signals) == 1
        assert config.alpha.IC == 0.05  # Default
        assert config.risk.covariance == 'ledoit_wolf'  # Default

    def test_missing_required_key(self):
        """Missing required key should raise ValueError."""
        with pytest.raises(ValueError, match="Missing required configuration key"):
            StrategyConfig.from_dict({'strategy': {'name': 'Test', 'type': 'carry'}})

    def test_empty_signals(self):
        """Empty signals list should raise ValueError."""
        config_dict = {
            'strategy': {'name': 'Test', 'type': 'carry'},
            'universe': {'asset_class': 'futures', 'instruments': ['SFRZ4']},
            'signals': [],  # Empty!
            'backtest': {'start_date': '2024-01-01', 'end_date': '2024-12-31'}
        }

        with pytest.raises(ValueError, match="At least one signal is required"):
            StrategyConfig.from_dict(config_dict)

    def test_to_dict_roundtrip(self, minimal_config_dict):
        """Configuration should survive to_dict → from_dict roundtrip."""
        config1 = StrategyConfig.from_dict(minimal_config_dict)
        config_dict = config1.to_dict()
        config2 = StrategyConfig.from_dict(config_dict)

        assert config1.strategy.name == config2.strategy.name
        assert config1.alpha.IC == config2.alpha.IC
        assert config1.universe.instruments == config2.universe.instruments

    def test_from_yaml_file(self, minimal_config_dict, tmp_path):
        """Should load configuration from YAML file."""
        # Create temporary YAML file
        yaml_file = tmp_path / "test_strategy.yaml"
        with open(yaml_file, 'w') as f:
            yaml.dump(minimal_config_dict, f)

        # Load configuration
        config = StrategyConfig.from_yaml(str(yaml_file))

        assert config.strategy.name == 'Test Strategy'
        assert len(config.signals) == 1

    def test_from_yaml_nonexistent_file(self):
        """Loading from non-existent file should raise FileNotFoundError."""
        with pytest.raises(FileNotFoundError):
            StrategyConfig.from_yaml('/nonexistent/file.yaml')


class TestComplexConfiguration:
    """Test complex multi-signal configuration."""

    @pytest.fixture
    def complex_config_dict(self):
        """Complex multi-signal configuration."""
        return {
            'strategy': {
                'name': 'Multi-Signal Strategy',
                'type': 'multi_signal',
                'description': 'Carry + Momentum + Mean Reversion'
            },
            'universe': {
                'asset_class': 'futures',
                'instruments': ['SFRZ4', 'SFRH5', 'SFRM5', 'SFRU5']
            },
            'signals': [
                {'type': 'carry', 'config': {'standardize': True}},
                {'type': 'momentum', 'config': {'lookback_days': 30}},
                {'type': 'mean_reversion', 'config': {'lookback_days': 20}}
            ],
            'alpha': {
                'IC': 0.08,
                'method': 'rolling',
                'ic_lookback': 90
            },
            'risk': {
                'covariance': 'sample',
                'lookback': 120
            },
            'optimizer': {
                'type': 'mean_variance',
                'risk_aversion': 2.0,
                'constraints': {
                    'long_only': False,
                    'max_position': 0.25,
                    'leverage': 1.5
                }
            },
            'execution': {
                'rebalance_frequency': 'monthly',
                'transaction_costs': 0.0005
            },
            'backtest': {
                'start_date': '2023-01-01',
                'end_date': '2024-12-31',
                'initial_capital': 5000000.0
            }
        }

    def test_complex_configuration(self, complex_config_dict):
        """Complex configuration should parse correctly."""
        config = StrategyConfig.from_dict(complex_config_dict)

        assert config.strategy.name == 'Multi-Signal Strategy'
        assert len(config.signals) == 3
        assert config.signals[0].type == 'carry'
        assert config.signals[1].type == 'momentum'
        assert config.signals[2].type == 'mean_reversion'

        assert config.alpha.IC == 0.08
        assert config.alpha.method == 'rolling'
        assert config.alpha.ic_lookback == 90

        assert config.risk.covariance == 'sample'
        assert config.risk.lookback == 120

        assert config.optimizer.risk_aversion == 2.0
        assert config.optimizer.constraints.long_only == False
        assert config.optimizer.constraints.leverage == 1.5

        assert config.execution.rebalance_frequency == 'monthly'
        assert config.execution.transaction_costs == 0.0005

        assert config.backtest.initial_capital == 5000000.0
