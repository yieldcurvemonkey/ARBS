"""
Tests for AlphaFactory - registry-based alpha generator creation.

Tests cover:
- Built-in IC methods (static, rolling, ewma, regime)
- Custom method registration
- Error handling
- Registry listing
"""

import pytest
from Strategies.Factory.AlphaFactory import AlphaFactory
from Strategies.Config.StrategyConfig import StrategyConfig
from Signals.AlphaGenerator import AlphaGenerator


def test_alpha_factory_static():
    """Test static IC method."""
    config_dict = {
        'strategy': {'name': 'Test', 'type': 'carry'},
        'universe': {'asset_class': 'futures', 'instruments': ['SFRZ4']},
        'signals': [{'type': 'carry'}],
        'alpha': {'IC': 0.05, 'method': 'static'},
        'backtest': {'start_date': '2024-01-01', 'end_date': '2024-12-31'}
    }
    config = StrategyConfig.from_dict(config_dict)
    alpha_gen = AlphaFactory.create_alpha_generator(config)

    assert isinstance(alpha_gen, AlphaGenerator)
    assert alpha_gen.IC == 0.05
    assert not alpha_gen.dynamic_ic


def test_alpha_factory_rolling():
    """Test rolling IC method."""
    config_dict = {
        'strategy': {'name': 'Test', 'type': 'carry'},
        'universe': {'asset_class': 'futures', 'instruments': ['SFRZ4']},
        'signals': [{'type': 'carry'}],
        'alpha': {'IC': 0.05, 'method': 'rolling', 'ic_lookback': 90},
        'backtest': {'start_date': '2024-01-01', 'end_date': '2024-12-31'}
    }
    config = StrategyConfig.from_dict(config_dict)
    alpha_gen = AlphaFactory.create_alpha_generator(config)

    assert isinstance(alpha_gen, AlphaGenerator)
    assert alpha_gen.IC == 0.05
    assert alpha_gen.dynamic_ic
    assert alpha_gen.ic_method == 'rolling'
    assert alpha_gen.ic_lookback == 90


def test_alpha_factory_ewma():
    """Test EWMA IC method."""
    config_dict = {
        'strategy': {'name': 'Test', 'type': 'carry'},
        'universe': {'asset_class': 'futures', 'instruments': ['SFRZ4']},
        'signals': [{'type': 'carry'}],
        'alpha': {'IC': 0.06, 'method': 'ewma', 'ic_halflife': 45},
        'backtest': {'start_date': '2024-01-01', 'end_date': '2024-12-31'}
    }
    config = StrategyConfig.from_dict(config_dict)
    alpha_gen = AlphaFactory.create_alpha_generator(config)

    assert isinstance(alpha_gen, AlphaGenerator)
    assert alpha_gen.IC == 0.06
    assert alpha_gen.dynamic_ic
    assert alpha_gen.ic_method == 'ewma'
    assert alpha_gen.ic_halflife == 45


def test_alpha_factory_regime():
    """Test regime-based IC method."""
    config_dict = {
        'strategy': {'name': 'Test', 'type': 'carry'},
        'universe': {'asset_class': 'futures', 'instruments': ['SFRZ4']},
        'signals': [{'type': 'carry'}],
        'alpha': {'IC': 0.05, 'method': 'regime'},
        'backtest': {'start_date': '2024-01-01', 'end_date': '2024-12-31'}
    }
    config = StrategyConfig.from_dict(config_dict)
    alpha_gen = AlphaFactory.create_alpha_generator(config)

    assert isinstance(alpha_gen, AlphaGenerator)
    assert alpha_gen.IC == 0.05
    assert alpha_gen.dynamic_ic
    assert alpha_gen.ic_method == 'regime'


def test_alpha_factory_custom_method():
    """Test registering and using custom IC method.

    Uses mock config objects to test factory in isolation.
    """
    def custom_creator(config) -> AlphaGenerator:
        # Custom method doubles the IC
        return AlphaGenerator(IC=config.alpha.IC * 2)

    # Register custom method
    AlphaFactory.register_method('double_ic', custom_creator)

    # Create a mock config object to test factory directly
    from dataclasses import dataclass

    @dataclass
    class MockAlpha:
        IC: float
        method: str

    @dataclass
    class MockConfig:
        alpha: MockAlpha

    mock_config = MockConfig(alpha=MockAlpha(IC=0.05, method='double_ic'))
    alpha_gen = AlphaFactory.create_alpha_generator(mock_config)

    # Should have doubled IC
    assert alpha_gen.IC == 0.10


def test_alpha_factory_unknown_method():
    """Test error on unknown IC method.

    Uses mock config to verify error handling.
    """
    from dataclasses import dataclass

    @dataclass
    class MockAlpha:
        IC: float
        method: str

    @dataclass
    class MockConfig:
        alpha: MockAlpha

    mock_config = MockConfig(alpha=MockAlpha(IC=0.05, method='nonexistent'))

    with pytest.raises(ValueError, match="Unknown IC method"):
        AlphaFactory.create_alpha_generator(mock_config)


def test_alpha_factory_list_methods():
    """Test listing available IC methods."""
    methods = AlphaFactory.list_available_methods()

    # Should have all built-in methods
    assert 'static' in methods
    assert 'rolling' in methods
    assert 'ewma' in methods
    assert 'regime' in methods
    assert len(methods) >= 4


def test_alpha_factory_error_message_includes_available():
    """Test that error message includes available methods."""
    from dataclasses import dataclass

    @dataclass
    class MockAlpha:
        IC: float
        method: str

    @dataclass
    class MockConfig:
        alpha: MockAlpha

    mock_config = MockConfig(alpha=MockAlpha(IC=0.05, method='bad_method'))

    with pytest.raises(ValueError) as exc_info:
        AlphaFactory.create_alpha_generator(mock_config)

    error_message = str(exc_info.value)
    assert 'Available methods' in error_message
    assert 'static' in error_message


def test_alpha_factory_registry_isolation():
    """Test that registry modifications are persistent."""
    # Register a custom method
    def test_method(config) -> AlphaGenerator:
        return AlphaGenerator(IC=0.99)

    AlphaFactory.register_method('test_isolation', test_method)

    # Method should be available after registration
    methods = AlphaFactory.list_available_methods()
    assert 'test_isolation' in methods

    # Can create alpha generator with the method
    from dataclasses import dataclass

    @dataclass
    class MockAlpha:
        IC: float
        method: str

    @dataclass
    class MockConfig:
        alpha: MockAlpha

    mock_config = MockConfig(alpha=MockAlpha(IC=0.05, method='test_isolation'))
    alpha_gen = AlphaFactory.create_alpha_generator(mock_config)
    assert alpha_gen.IC == 0.99
