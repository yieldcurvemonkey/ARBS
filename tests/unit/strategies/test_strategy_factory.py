# ABOUTME: Unit tests for StrategyFactory and SignalFactory
# ABOUTME: Tests creation of signals and complete strategies from configuration
"""
Tests for StrategyFactory and SignalFactory

Tests instantiation of signals and portfolios from configuration.
"""

import pytest
from datetime import date

from Strategies.Factory.SignalFactory import SignalFactory, get_signal_defaults
from Strategies.Factory.StrategyFactory import StrategyFactory, create_strategy
from Strategies.Config.StrategyConfig import StrategyConfig, SignalConfig
from Signals.Futures.CarrySignal import CarrySignal
from Signals.Futures.MomentumSignal import MomentumSignal
from Signals.Futures.MeanReversionSignal import MeanReversionSignal
from Asset.GrinoldKahnPortfolio import GrinoldKahnPortfolio


class TestSignalFactory:
    """Test SignalFactory."""

    def test_create_carry_signal(self):
        """Should create CarrySignal from configuration."""
        config = SignalConfig(type='carry', config={'standardize': True})
        signal = SignalFactory.create_signal(config)

        assert isinstance(signal, CarrySignal)
        assert signal.standardize == True

    def test_create_momentum_signal(self):
        """Should create MomentumSignal from configuration."""
        config = SignalConfig(
            type='momentum',
            config={'lookback_days': 30, 'standardize': True}
        )
        signal = SignalFactory.create_signal(config)

        assert isinstance(signal, MomentumSignal)
        assert signal.lookback_days == 30
        assert signal.standardize == True

    def test_create_mean_reversion_signal(self):
        """Should create MeanReversionSignal from configuration."""
        config = SignalConfig(
            type='mean_reversion',
            config={'lookback_days': 20, 'method': 'zscore'}
        )
        signal = SignalFactory.create_signal(config)

        assert isinstance(signal, MeanReversionSignal)
        assert signal.lookback_days == 20
        assert signal.method == 'zscore'

    def test_create_multiple_signals(self):
        """Should create multiple signals from list."""
        configs = [
            SignalConfig(type='carry'),
            SignalConfig(type='momentum', config={'lookback_days': 60}),
            SignalConfig(type='mean_reversion')
        ]

        signals = SignalFactory.create_signals(configs)

        assert len(signals) == 3
        assert isinstance(signals[0], CarrySignal)
        assert isinstance(signals[1], MomentumSignal)
        assert isinstance(signals[2], MeanReversionSignal)

    def test_unknown_signal_type(self):
        """Unknown signal type should raise ValueError."""
        config = SignalConfig(type='carry')  # Valid initially
        config.type = 'unknown_type'  # Bypass validation

        with pytest.raises(ValueError, match="Unknown signal type"):
            SignalFactory.create_signal(config)

    def test_invalid_signal_config(self):
        """Invalid configuration parameters should raise ValueError."""
        config = SignalConfig(
            type='momentum',
            config={'invalid_param': True}
        )

        with pytest.raises(ValueError, match="Invalid configuration"):
            SignalFactory.create_signal(config)

    def test_list_available_signals(self):
        """Should list all registered signals."""
        available = SignalFactory.list_available_signals()

        assert 'carry' in available
        assert 'momentum' in available
        assert 'mean_reversion' in available

    def test_get_signal_defaults(self):
        """Should return default parameters for signal types."""
        carry_defaults = get_signal_defaults('carry')
        assert 'standardize' in carry_defaults
        assert carry_defaults['standardize'] == True

        momentum_defaults = get_signal_defaults('momentum')
        assert 'lookback_days' in momentum_defaults
        assert momentum_defaults['lookback_days'] == 60


class TestStrategyFactory:
    """Test StrategyFactory."""

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

    @pytest.fixture
    def multi_signal_config_dict(self):
        """Multi-signal configuration."""
        return {
            'strategy': {
                'name': 'Multi-Signal Strategy',
                'type': 'multi_signal'
            },
            'universe': {
                'asset_class': 'futures',
                'instruments': ['SFRZ4', 'SFRH5', 'SFRM5']
            },
            'signals': [
                {'type': 'carry', 'config': {'standardize': True}},
                {'type': 'momentum', 'config': {'lookback_days': 30}},
                {'type': 'mean_reversion', 'config': {'lookback_days': 20}}
            ],
            'alpha': {
                'IC': 0.08,
                'method': 'static'
            },
            'risk': {
                'covariance': 'ledoit_wolf'
            },
            'optimizer': {
                'type': 'mean_variance',
                'risk_aversion': 1.5,
                'constraints': {
                    'long_only': False,
                    'max_position': 0.25
                }
            },
            'execution': {
                'rebalance_frequency': 'weekly'
            },
            'backtest': {
                'start_date': '2024-01-01',
                'end_date': '2024-12-31',
                'initial_capital': 2000000.0
            }
        }

    def test_create_from_dict_minimal(self, minimal_config_dict):
        """Should create strategy from minimal configuration."""
        factory = StrategyFactory()
        strategy = factory.create_from_dict(minimal_config_dict)

        assert isinstance(strategy, GrinoldKahnPortfolio)
        assert strategy.identifier == 'Test Strategy'
        assert len(strategy.signals) == 1
        assert isinstance(strategy.signals[0], CarrySignal)

    def test_create_from_dict_multi_signal(self, multi_signal_config_dict):
        """Should create multi-signal strategy."""
        factory = StrategyFactory()
        strategy = factory.create_from_dict(multi_signal_config_dict)

        assert isinstance(strategy, GrinoldKahnPortfolio)
        assert strategy.identifier == 'Multi-Signal Strategy'
        assert len(strategy.signals) == 3

        # Verify signal types
        assert isinstance(strategy.signals[0], CarrySignal)
        assert isinstance(strategy.signals[1], MomentumSignal)
        assert isinstance(strategy.signals[2], MeanReversionSignal)

        # Verify configuration applied
        assert strategy.alpha_generator.IC == 0.08
        assert strategy.optimizer.risk_aversion == 1.5
        assert strategy.optimizer.long_only == False

    def test_create_with_dynamic_ic(self):
        """Should create strategy with dynamic IC."""
        config_dict = {
            'strategy': {'name': 'Dynamic IC', 'type': 'carry'},
            'universe': {'asset_class': 'futures', 'instruments': ['SFRZ4']},
            'signals': [{'type': 'carry'}],
            'alpha': {
                'IC': 0.05,
                'method': 'rolling',
                'ic_lookback': 90
            },
            'backtest': {'start_date': '2024-01-01', 'end_date': '2024-12-31'}
        }

        factory = StrategyFactory()
        strategy = factory.create_from_dict(config_dict)

        assert strategy.alpha_generator.dynamic_ic == True
        assert strategy.alpha_generator.ic_method == 'rolling'
        assert strategy.alpha_generator.ic_lookback == 90

    def test_create_with_sample_covariance(self):
        """Should create strategy with sample covariance."""
        config_dict = {
            'strategy': {'name': 'Sample Cov', 'type': 'carry'},
            'universe': {'asset_class': 'futures', 'instruments': ['SFRZ4']},
            'signals': [{'type': 'carry'}],
            'risk': {'covariance': 'sample'},
            'backtest': {'start_date': '2024-01-01', 'end_date': '2024-12-31'}
        }

        factory = StrategyFactory()
        strategy = factory.create_from_dict(config_dict)

        from Risk.Covariance.SampleCovariance import SampleCovariance
        assert isinstance(strategy.risk_model, SampleCovariance)

    def test_create_from_yaml(self, minimal_config_dict, tmp_path):
        """Should create strategy from YAML file."""
        import yaml

        # Write YAML file
        yaml_file = tmp_path / "test_strategy.yaml"
        with open(yaml_file, 'w') as f:
            yaml.dump(minimal_config_dict, f)

        # Create strategy
        factory = StrategyFactory()
        strategy = factory.create_from_yaml(str(yaml_file))

        assert isinstance(strategy, GrinoldKahnPortfolio)
        assert strategy.identifier == 'Test Strategy'

    def test_convenience_function(self, minimal_config_dict, tmp_path):
        """Convenience create_strategy function should work."""
        import yaml

        yaml_file = tmp_path / "test.yaml"
        with open(yaml_file, 'w') as f:
            yaml.dump(minimal_config_dict, f)

        strategy = create_strategy(str(yaml_file))

        assert isinstance(strategy, GrinoldKahnPortfolio)
        assert strategy.identifier == 'Test Strategy'


class TestEdgeCases:
    """Test edge cases and error handling."""

    def test_empty_instruments_list(self):
        """Empty instruments list should raise ValueError."""
        config_dict = {
            'strategy': {'name': 'Test', 'type': 'carry'},
            'universe': {'asset_class': 'futures', 'instruments': []},  # Empty
            'signals': [{'type': 'carry'}],
            'backtest': {'start_date': '2024-01-01', 'end_date': '2024-12-31'}
        }

        with pytest.raises(ValueError, match="instruments list cannot be empty"):
            StrategyConfig.from_dict(config_dict)

    def test_invalid_rebalance_frequency(self):
        """Invalid rebalance frequency should raise ValueError."""
        config_dict = {
            'strategy': {'name': 'Test', 'type': 'carry'},
            'universe': {'asset_class': 'futures', 'instruments': ['SFRZ4']},
            'signals': [{'type': 'carry'}],
            'execution': {'rebalance_frequency': 'invalid'},  # Invalid
            'backtest': {'start_date': '2024-01-01', 'end_date': '2024-12-31'}
        }

        with pytest.raises(ValueError, match="Invalid rebalance_frequency"):
            StrategyConfig.from_dict(config_dict)

    def test_negative_transaction_costs(self):
        """Negative transaction costs should raise ValueError."""
        config_dict = {
            'strategy': {'name': 'Test', 'type': 'carry'},
            'universe': {'asset_class': 'futures', 'instruments': ['SFRZ4']},
            'signals': [{'type': 'carry'}],
            'execution': {'transaction_costs': -0.001},  # Negative
            'backtest': {'start_date': '2024-01-01', 'end_date': '2024-12-31'}
        }

        with pytest.raises(ValueError, match="transaction_costs must be non-negative"):
            StrategyConfig.from_dict(config_dict)
