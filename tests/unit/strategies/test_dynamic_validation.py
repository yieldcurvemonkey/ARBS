# ABOUTME: Tests for dynamic strategy validation
# ABOUTME: Validates runtime verification of strategy component extensions
"""
Test dynamic validation - verify custom types work after registration.

Tests that StrategyConfig validation queries factory registries,
allowing custom component types to pass validation.
"""

import pytest
from Strategies.Factory.SignalFactory import SignalFactory
from Strategies.Factory.AlphaFactory import AlphaFactory
from Strategies.Factory.CovarianceFactory import CovarianceFactory
from Strategies.Config.StrategyConfig import StrategyConfig
from Signals.Base.BaseSignal import BaseSignal
from Signals.AlphaGenerator import AlphaGenerator
import polars as pl


class CustomTestSignal(BaseSignal):
    """Custom signal for testing dynamic validation."""
    def __init__(self):
        super().__init__(name='custom_test_signal')

    def calculate(self, prices, dates):
        return pl.DataFrame({col: [0.0] * len(dates) for col in prices.columns})


def test_custom_signal_type_passes_validation_after_registration():
    """Test that custom signal types pass validation after registration."""
    # Register custom signal
    SignalFactory.register_signal('custom_test_signal', CustomTestSignal)

    # Validation should accept registered custom types
    config_dict = {
        'strategy': {'name': 'Test', 'type': 'custom'},
        'universe': {'asset_class': 'futures', 'instruments': ['SFRZ4']},
        'signals': [{'type': 'custom_test_signal'}],  # Custom type!
        'backtest': {'start_date': '2024-01-01', 'end_date': '2024-12-31'}
    }

    # Should not raise ValueError
    config = StrategyConfig.from_dict(config_dict)
    assert config.signals[0].type == 'custom_test_signal'


def test_custom_alpha_method_passes_validation_after_registration():
    """Test that custom alpha methods pass validation after registration."""
    # Register custom alpha method
    def custom_alpha_creator(config) -> AlphaGenerator:
        return AlphaGenerator(IC=0.10)

    AlphaFactory.register_method('custom_alpha_method', custom_alpha_creator)

    # Validation should accept registered custom methods
    config_dict = {
        'strategy': {'name': 'Test', 'type': 'carry'},
        'universe': {'asset_class': 'futures', 'instruments': ['SFRZ4']},
        'signals': [{'type': 'carry'}],
        'alpha': {'IC': 0.05, 'method': 'custom_alpha_method'},  # Custom method!
        'backtest': {'start_date': '2024-01-01', 'end_date': '2024-12-31'}
    }

    # Should not raise ValueError
    config = StrategyConfig.from_dict(config_dict)
    assert config.alpha.method == 'custom_alpha_method'


def test_custom_covariance_passes_validation_after_registration():
    """Test that custom covariance methods pass validation after registration."""
    # Create and register custom covariance estimator
    class CustomCovariance:
        def __init__(self):
            pass

    CovarianceFactory.register_covariance('custom_cov_method', CustomCovariance)

    # Validation should accept registered custom methods
    config_dict = {
        'strategy': {'name': 'Test', 'type': 'carry'},
        'universe': {'asset_class': 'futures', 'instruments': ['SFRZ4']},
        'signals': [{'type': 'carry'}],
        'risk': {'covariance': 'custom_cov_method'},  # Custom method!
        'backtest': {'start_date': '2024-01-01', 'end_date': '2024-12-31'}
    }

    # Should not raise ValueError
    config = StrategyConfig.from_dict(config_dict)
    assert config.risk.covariance == 'custom_cov_method'


def test_unregistered_signal_type_fails_validation():
    """Test that unregistered signal types still fail validation."""
    config_dict = {
        'strategy': {'name': 'Test', 'type': 'custom'},
        'universe': {'asset_class': 'futures', 'instruments': ['SFRZ4']},
        'signals': [{'type': 'nonexistent_signal'}],  # Not registered!
        'backtest': {'start_date': '2024-01-01', 'end_date': '2024-12-31'}
    }

    with pytest.raises(ValueError, match="Invalid signal type"):
        StrategyConfig.from_dict(config_dict)


def test_unregistered_alpha_method_fails_validation():
    """Test that unregistered alpha methods still fail validation."""
    config_dict = {
        'strategy': {'name': 'Test', 'type': 'carry'},
        'universe': {'asset_class': 'futures', 'instruments': ['SFRZ4']},
        'signals': [{'type': 'carry'}],
        'alpha': {'IC': 0.05, 'method': 'nonexistent_method'},  # Not registered!
        'backtest': {'start_date': '2024-01-01', 'end_date': '2024-12-31'}
    }

    with pytest.raises(ValueError, match="Invalid IC method"):
        StrategyConfig.from_dict(config_dict)


def test_error_messages_include_registration_instructions():
    """Test that error messages tell users how to register custom types."""
    config_dict = {
        'strategy': {'name': 'Test', 'type': 'carry'},
        'universe': {'asset_class': 'futures', 'instruments': ['SFRZ4']},
        'signals': [{'type': 'carry'}],
        'alpha': {'IC': 0.05, 'method': 'bad_method'},
        'backtest': {'start_date': '2024-01-01', 'end_date': '2024-12-31'}
    }

    with pytest.raises(ValueError) as exc_info:
        StrategyConfig.from_dict(config_dict)

    error_message = str(exc_info.value)
    assert 'AlphaFactory.register_method()' in error_message
    assert 'Available methods' in error_message
