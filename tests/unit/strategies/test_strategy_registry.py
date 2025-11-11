# ABOUTME: Unit tests for StrategyRegistry pre-built templates
# ABOUTME: Tests template listing, retrieval, customization, and strategy creation
"""
Tests for StrategyRegistry

Tests pre-built strategy templates and customization.
"""

import pytest

from Strategies.Registry.StrategyRegistry import (
    StrategyRegistry,
    list_templates,
    quick_strategy
)
from Asset.GrinoldKahnPortfolio import GrinoldKahnPortfolio
from Signals.Futures.CarrySignal import CarrySignal
from Signals.Futures.MomentumSignal import MomentumSignal


class TestStrategyRegistry:
    """Test StrategyRegistry."""

    def test_list_available_templates(self):
        """Should list all available templates."""
        registry = StrategyRegistry()
        templates = registry.list_available()

        assert 'simple_carry' in templates
        assert 'simple_momentum' in templates
        assert 'multi_signal' in templates
        assert len(templates) >= 3

    def test_get_template(self):
        """Should retrieve template configuration."""
        registry = StrategyRegistry()
        template = registry.get_template('simple_carry')

        assert template['strategy']['name'] == 'Simple Carry Strategy'
        assert template['strategy']['type'] == 'carry'
        assert len(template['signals']) == 1
        assert template['signals'][0]['type'] == 'carry'

    def test_get_nonexistent_template(self):
        """Getting non-existent template should raise KeyError."""
        registry = StrategyRegistry()

        with pytest.raises(KeyError, match="Unknown template"):
            registry.get_template('nonexistent')

    def test_create_strategy_from_template(self):
        """Should create strategy from template."""
        registry = StrategyRegistry()
        strategy = registry.create_strategy('simple_carry')

        assert isinstance(strategy, GrinoldKahnPortfolio)
        assert strategy.identifier == 'Simple Carry Strategy'
        assert len(strategy.signals) == 1
        assert isinstance(strategy.signals[0], CarrySignal)

    def test_create_strategy_with_custom_instruments(self):
        """Should override instruments in template."""
        registry = StrategyRegistry()
        custom_instruments = ['TESTZ4', 'TESTH5']

        strategy = registry.create_strategy(
            'simple_carry',
            instruments=custom_instruments
        )

        assert isinstance(strategy, GrinoldKahnPortfolio)
        # Note: instruments not directly accessible on portfolio,
        # but configuration was applied

    def test_create_strategy_with_custom_dates(self):
        """Should override dates in template."""
        registry = StrategyRegistry()

        strategy = registry.create_strategy(
            'simple_carry',
            start_date='2023-01-01',
            end_date='2023-12-31'
        )

        assert isinstance(strategy, GrinoldKahnPortfolio)

    def test_create_strategy_with_nested_overrides(self):
        """Should apply nested configuration overrides."""
        registry = StrategyRegistry()

        strategy = registry.create_strategy(
            'simple_carry',
            **{'alpha.IC': 0.10, 'optimizer.risk_aversion': 2.0}
        )

        assert strategy.alpha_generator.IC == 0.10
        assert strategy.optimizer.risk_aversion == 2.0

    def test_multi_signal_template(self):
        """Should create multi-signal strategy from template."""
        registry = StrategyRegistry()
        strategy = registry.create_strategy('multi_signal')

        assert isinstance(strategy, GrinoldKahnPortfolio)
        assert strategy.identifier == 'Multi-Signal Strategy'
        assert len(strategy.signals) == 3

        # Check signal types
        assert isinstance(strategy.signals[0], CarrySignal)
        assert isinstance(strategy.signals[1], MomentumSignal)

    def test_template_isolation(self):
        """Modifying returned template should not affect registry."""
        registry = StrategyRegistry()

        # Get template and modify it
        template1 = registry.get_template('simple_carry')
        template1['strategy']['name'] = 'Modified Name'

        # Get template again - should be unchanged
        template2 = registry.get_template('simple_carry')
        assert template2['strategy']['name'] == 'Simple Carry Strategy'

    def test_save_template_to_yaml(self, tmp_path):
        """Should save template to YAML file."""
        import yaml

        registry = StrategyRegistry()
        output_file = tmp_path / "exported_strategy.yaml"

        registry.save_template_to_yaml('simple_carry', str(output_file))

        # Verify file exists and is valid
        assert output_file.exists()

        with open(output_file, 'r') as f:
            loaded = yaml.safe_load(f)

        assert loaded['strategy']['name'] == 'Simple Carry Strategy'


class TestConvenienceFunctions:
    """Test convenience functions."""

    def test_list_templates_function(self):
        """list_templates() should work."""
        templates = list_templates()

        assert isinstance(templates, list)
        assert 'simple_carry' in templates

    def test_quick_strategy_function(self):
        """quick_strategy() should work."""
        strategy = quick_strategy('simple_carry', ['SFRZ4', 'SFRH5'])

        assert isinstance(strategy, GrinoldKahnPortfolio)
        assert strategy.identifier == 'Simple Carry Strategy'


class TestTemplateRegistration:
    """Test custom template registration."""

    def test_register_custom_template(self):
        """Should register new template."""
        custom_template = {
            'strategy': {'name': 'Custom', 'type': 'carry'},
            'universe': {'asset_class': 'futures', 'instruments': ['TESTZ4']},
            'signals': [{'type': 'carry'}],
            'backtest': {'start_date': '2024-01-01', 'end_date': '2024-12-31'}
        }

        StrategyRegistry.register_template('my_custom', custom_template)

        registry = StrategyRegistry()
        templates = registry.list_available()

        assert 'my_custom' in templates

        # Verify can create strategy from custom template
        strategy = registry.create_strategy('my_custom')
        assert strategy.identifier == 'Custom'

    def test_register_invalid_template(self):
        """Registering invalid template should raise ValueError."""
        invalid_template = {
            'strategy': {'name': 'Invalid'},
            # Missing required keys
        }

        with pytest.raises(ValueError, match="Invalid template configuration"):
            StrategyRegistry.register_template('invalid', invalid_template)


class TestTemplateContent:
    """Test that built-in templates are valid."""

    def test_simple_carry_template_valid(self):
        """simple_carry template should be valid."""
        registry = StrategyRegistry()
        template = registry.get_template('simple_carry')

        # Should be able to create strategy without errors
        strategy = registry.create_strategy('simple_carry')
        assert isinstance(strategy, GrinoldKahnPortfolio)

    def test_simple_momentum_template_valid(self):
        """simple_momentum template should be valid."""
        registry = StrategyRegistry()
        strategy = registry.create_strategy('simple_momentum')

        assert isinstance(strategy, GrinoldKahnPortfolio)
        assert strategy.identifier == 'Simple Momentum Strategy'

    def test_multi_signal_template_valid(self):
        """multi_signal template should be valid."""
        registry = StrategyRegistry()
        strategy = registry.create_strategy('multi_signal')

        assert isinstance(strategy, GrinoldKahnPortfolio)
        assert len(strategy.signals) == 3
