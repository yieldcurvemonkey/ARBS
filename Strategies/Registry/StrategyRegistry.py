# ABOUTME: Registry of pre-built strategy templates for quick strategy creation
# ABOUTME: Provides catalog of common strategy configurations (carry, momentum, multi-signal)
"""
StrategyRegistry - Catalog of Pre-Built Strategy Templates

Provides a catalog of pre-built strategy configurations that users can
instantiate or modify.

Example:
    >>> registry = StrategyRegistry()
    >>> template = registry.get_template('simple_carry')
    >>> strategy = registry.create_strategy('simple_carry', instruments=['SFRZ4', 'SFRH5'])
"""

from typing import Dict, Any, List, Optional
from pathlib import Path
import copy

from Strategies.Config.StrategyConfig import StrategyConfig
from Strategies.Factory.StrategyFactory import StrategyFactory
from Asset.GrinoldKahnPortfolio import GrinoldKahnPortfolio


class StrategyRegistry:
    """
    Registry of pre-built strategy templates.

    Provides common strategy configurations that can be instantiated
    with minimal customization.
    """

    # Pre-built strategy templates
    _TEMPLATES = {
        'simple_carry': {
            'strategy': {
                'name': 'Carry Strategy',
                'type': 'carry',
                'description': 'Long high carry, short low carry'
            },
            'universe': {
                'asset_class': 'futures',
                'instruments': ['SFRZ4', 'SFRH5', 'SFRM5']
            },
            'signals': [
                {'type': 'carry', 'config': {'standardize': True}}
            ],
            'alpha': {
                'IC': 0.05,
                'method': 'static'
            },
            'risk': {
                'covariance': 'ledoit_wolf'
            },
            'optimizer': {
                'type': 'mean_variance',
                'risk_aversion': 1.0,
                'constraints': {
                    'long_only': True,
                    'max_position': 0.30
                }
            },
            'execution': {
                'rebalance_frequency': 'weekly'
            },
            'backtest': {
                'start_date': '2024-01-01',
                'end_date': '2024-12-31',
                'initial_capital': 1000000.0
            }
        },

        'simple_momentum': {
            'strategy': {
                'name': 'Momentum Strategy',
                'type': 'momentum',
                'description': 'Time-series momentum (trend following)'
            },
            'universe': {
                'asset_class': 'futures',
                'instruments': ['SFRZ4', 'SFRH5', 'SFRM5']
            },
            'signals': [
                {'type': 'momentum', 'config': {'lookback_days': 60, 'standardize': True}}
            ],
            'alpha': {
                'IC': 0.05,
                'method': 'static'
            },
            'risk': {
                'covariance': 'ledoit_wolf'
            },
            'optimizer': {
                'type': 'mean_variance',
                'risk_aversion': 1.0,
                'constraints': {
                    'long_only': False,  # Momentum can short
                    'max_position': 0.30
                }
            },
            'execution': {
                'rebalance_frequency': 'weekly'
            },
            'backtest': {
                'start_date': '2024-01-01',
                'end_date': '2024-12-31',
                'initial_capital': 1000000.0
            }
        },

        'multi_signal': {
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
                {'type': 'momentum', 'config': {'lookback_days': 30, 'standardize': True}},
                {'type': 'mean_reversion', 'config': {'lookback_days': 20, 'standardize': True}}
            ],
            'alpha': {
                'IC': 0.05,
                'method': 'static'
            },
            'risk': {
                'covariance': 'ledoit_wolf'
            },
            'optimizer': {
                'type': 'mean_variance',
                'risk_aversion': 1.0,
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
                'initial_capital': 1000000.0
            }
        }
    }

    def __init__(self):
        """Initialize strategy registry."""
        self.factory = StrategyFactory()

    def list_available(self) -> List[str]:
        """
        List all available strategy templates.

        Returns:
            List of template names

        Example:
            >>> registry = StrategyRegistry()
            >>> registry.list_available()
            ['simple_carry', 'simple_momentum', 'multi_signal']
        """
        return list(self._TEMPLATES.keys())

    def get_template(self, name: str) -> Dict[str, Any]:
        """
        Get a strategy template configuration.

        Args:
            name: Template name

        Returns:
            Configuration dictionary (deep copy)

        Raises:
            KeyError: If template doesn't exist

        Example:
            >>> registry = StrategyRegistry()
            >>> template = registry.get_template('simple_carry')
            >>> template['strategy']['name']
            'Carry Strategy'
        """
        if name not in self._TEMPLATES:
            available = ', '.join(self.list_available())
            raise KeyError(f"Unknown template '{name}'. Available: {available}")

        return copy.deepcopy(self._TEMPLATES[name])

    def create_strategy(
        self,
        template_name: str,
        instruments: Optional[List[str]] = None,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        **overrides
    ) -> GrinoldKahnPortfolio:
        """
        Create strategy from template with customization.

        Args:
            template_name: Name of template to use
            instruments: Optional list of instruments (overrides template)
            start_date: Optional start date (overrides template)
            end_date: Optional end date (overrides template)
            **overrides: Additional configuration overrides

        Returns:
            GrinoldKahnPortfolio instance

        Example:
            >>> registry = StrategyRegistry()
            >>> strategy = registry.create_strategy(
            ...     'simple_carry',
            ...     instruments=['SFRZ4', 'SFRH5'],
            ...     start_date='2024-06-01'
            ... )
            >>> strategy.identifier
            'Carry Strategy'
        """
        # Get template
        config_dict = self.get_template(template_name)

        # Apply overrides
        if instruments is not None:
            config_dict['universe']['instruments'] = instruments

        if start_date is not None:
            config_dict['backtest']['start_date'] = start_date

        if end_date is not None:
            config_dict['backtest']['end_date'] = end_date

        # Apply additional overrides
        for key, value in overrides.items():
            if '.' in key:
                # Nested key like 'alpha.IC'
                parts = key.split('.')
                current = config_dict
                for part in parts[:-1]:
                    current = current[part]
                current[parts[-1]] = value
            else:
                config_dict[key] = value

        # Create strategy
        return self.factory.create_from_dict(config_dict)

    @classmethod
    def register_template(cls, name: str, config: Dict[str, Any]) -> None:
        """
        Register a new strategy template.

        Args:
            name: Template name
            config: Strategy configuration dictionary

        Example:
            >>> config = {'strategy': {...}, 'universe': {...}, ...}
            >>> StrategyRegistry.register_template('my_strategy', config)
        """
        # Validate configuration
        try:
            StrategyConfig.from_dict(config)
        except Exception as e:
            raise ValueError(f"Invalid template configuration: {e}")

        cls._TEMPLATES[name] = config

    def save_template_to_yaml(self, template_name: str, output_path: str) -> None:
        """
        Save a template to YAML file.

        Args:
            template_name: Name of template to save
            output_path: Path for output YAML file

        Example:
            >>> registry = StrategyRegistry()
            >>> registry.save_template_to_yaml('simple_carry', 'my_carry.yaml')
        """
        import yaml

        template = self.get_template(template_name)

        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        with open(output_path, 'w') as f:
            yaml.dump(template, f, default_flow_style=False, sort_keys=False)


# Convenience functions

def list_templates() -> List[str]:
    """
    List all available strategy templates.

    Returns:
        List of template names

    Example:
        >>> from Strategies.Registry import list_templates
        >>> list_templates()
        ['simple_carry', 'simple_momentum', 'multi_signal']
    """
    registry = StrategyRegistry()
    return registry.list_available()


def quick_strategy(template_name: str, instruments: List[str], **kwargs) -> GrinoldKahnPortfolio:
    """
    Quickly create a strategy from template.

    Args:
        template_name: Name of template
        instruments: List of instruments
        **kwargs: Additional overrides

    Returns:
        GrinoldKahnPortfolio instance

    Example:
        >>> from Strategies.Registry import quick_strategy
        >>> strategy = quick_strategy('simple_carry', ['SFRZ4', 'SFRH5'])
        >>> strategy.identifier
        'Simple Carry Strategy'
    """
    registry = StrategyRegistry()
    return registry.create_strategy(template_name, instruments=instruments, **kwargs)
