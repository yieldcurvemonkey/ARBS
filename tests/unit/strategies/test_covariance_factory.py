"""
Tests for CovarianceFactory - registry-based covariance estimator creation.

Tests cover:
- Built-in covariance methods (ledoit_wolf, sample, constant_correlation)
- Custom covariance registration
- Error handling
- Registry listing
"""

import pytest
from Strategies.Factory.CovarianceFactory import CovarianceFactory
from Strategies.Config.StrategyConfig import StrategyConfig
from Risk.Covariance.LedoitWolfShrinkage import LedoitWolfShrinkage
from Risk.Covariance.SampleCovariance import SampleCovariance


def test_covariance_factory_ledoit_wolf():
    """Test Ledoit-Wolf covariance estimator."""
    config_dict = {
        'strategy': {'name': 'Test', 'type': 'carry'},
        'universe': {'asset_class': 'futures', 'instruments': ['SFRZ4']},
        'signals': [{'type': 'carry'}],
        'risk': {'covariance': 'ledoit_wolf'},
        'backtest': {'start_date': '2024-01-01', 'end_date': '2024-12-31'}
    }
    config = StrategyConfig.from_dict(config_dict)
    cov_estimator = CovarianceFactory.create_covariance_estimator(config)

    assert isinstance(cov_estimator, LedoitWolfShrinkage)


def test_covariance_factory_sample():
    """Test sample covariance estimator."""
    config_dict = {
        'strategy': {'name': 'Test', 'type': 'carry'},
        'universe': {'asset_class': 'futures', 'instruments': ['SFRZ4']},
        'signals': [{'type': 'carry'}],
        'risk': {'covariance': 'sample'},
        'backtest': {'start_date': '2024-01-01', 'end_date': '2024-12-31'}
    }
    config = StrategyConfig.from_dict(config_dict)
    cov_estimator = CovarianceFactory.create_covariance_estimator(config)

    assert isinstance(cov_estimator, SampleCovariance)


def test_covariance_factory_constant_correlation():
    """Test constant correlation covariance estimator."""
    config_dict = {
        'strategy': {'name': 'Test', 'type': 'carry'},
        'universe': {'asset_class': 'futures', 'instruments': ['SFRZ4']},
        'signals': [{'type': 'carry'}],
        'risk': {'covariance': 'constant_correlation'},
        'backtest': {'start_date': '2024-01-01', 'end_date': '2024-12-31'}
    }
    config = StrategyConfig.from_dict(config_dict)
    cov_estimator = CovarianceFactory.create_covariance_estimator(config)

    # Constant correlation currently uses Ledoit-Wolf
    assert isinstance(cov_estimator, LedoitWolfShrinkage)


def test_covariance_factory_custom_estimator():
    """Test registering and using custom covariance estimator.

    Tests factory directly since StrategyConfig validation
    will be updated in Phase 1.4.
    """
    # Create a custom covariance estimator
    class CustomCovariance:
        def __init__(self):
            self.custom_param = True

    # Register custom estimator
    CovarianceFactory.register_covariance('custom_cov', CustomCovariance)

    # Create a mock config object to test factory directly
    from dataclasses import dataclass

    @dataclass
    class MockRisk:
        covariance: str

    @dataclass
    class MockConfig:
        risk: MockRisk

    mock_config = MockConfig(risk=MockRisk(covariance='custom_cov'))
    cov_estimator = CovarianceFactory.create_covariance_estimator(mock_config)

    assert isinstance(cov_estimator, CustomCovariance)
    assert cov_estimator.custom_param is True


def test_covariance_factory_unknown_method():
    """Test error on unknown covariance method.

    Tests factory directly to verify error handling.
    """
    from dataclasses import dataclass

    @dataclass
    class MockRisk:
        covariance: str

    @dataclass
    class MockConfig:
        risk: MockRisk

    mock_config = MockConfig(risk=MockRisk(covariance='nonexistent'))

    with pytest.raises(ValueError, match="Unknown covariance method"):
        CovarianceFactory.create_covariance_estimator(mock_config)


def test_covariance_factory_list_methods():
    """Test listing available covariance methods."""
    methods = CovarianceFactory.list_available_methods()

    # Should have all built-in methods
    assert 'ledoit_wolf' in methods
    assert 'sample' in methods
    assert 'constant_correlation' in methods
    assert len(methods) >= 3


def test_covariance_factory_error_message_includes_available():
    """Test that error message includes available methods."""
    from dataclasses import dataclass

    @dataclass
    class MockRisk:
        covariance: str

    @dataclass
    class MockConfig:
        risk: MockRisk

    mock_config = MockConfig(risk=MockRisk(covariance='bad_method'))

    with pytest.raises(ValueError) as exc_info:
        CovarianceFactory.create_covariance_estimator(mock_config)

    error_message = str(exc_info.value)
    assert 'Available methods' in error_message
    assert 'ledoit_wolf' in error_message


def test_covariance_factory_registry_isolation():
    """Test that registry modifications are persistent."""
    # Create a custom covariance estimator
    class TestCovariance:
        def __init__(self):
            self.test_value = 42

    # Register custom estimator
    CovarianceFactory.register_covariance('test_isolation', TestCovariance)

    # Method should be available after registration
    methods = CovarianceFactory.list_available_methods()
    assert 'test_isolation' in methods

    # Can create covariance estimator with the method
    from dataclasses import dataclass

    @dataclass
    class MockRisk:
        covariance: str

    @dataclass
    class MockConfig:
        risk: MockRisk

    mock_config = MockConfig(risk=MockRisk(covariance='test_isolation'))
    cov_estimator = CovarianceFactory.create_covariance_estimator(mock_config)

    assert isinstance(cov_estimator, TestCovariance)
    assert cov_estimator.test_value == 42
