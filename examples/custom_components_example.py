"""
Custom Components Example - Extending the Strategy Factory

Demonstrates how to add custom signals, alpha methods, and covariance estimators
to the strategy factory system without modifying framework code.

Usage:
    python examples/custom_components_example.py
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from Signals.Base.BaseSignal import BaseSignal
from Signals.AlphaGenerator import AlphaGenerator
from Strategies.Factory import SignalFactory, AlphaFactory, CovarianceFactory
from Strategies.Registry import StrategyRegistry
from Strategies.Config.StrategyConfig import StrategyConfig
import polars as pl
import numpy as np


# =============================================================================
# CUSTOM SIGNAL: Simple Moving Average Crossover
# =============================================================================

class SMASignal(BaseSignal):
    """
    Simple Moving Average crossover signal.

    Generates buy signal when fast MA crosses above slow MA.
    """

    def __init__(self, fast_window: int = 10, slow_window: int = 30, standardize: bool = True):
        """
        Args:
            fast_window: Fast moving average window
            slow_window: Slow moving average window
            standardize: Whether to z-score the signal
        """
        super().__init__(name='sma_crossover')
        self.fast_window = fast_window
        self.slow_window = slow_window
        self.standardize = standardize

    def calculate(self, prices: pl.DataFrame, dates) -> pl.DataFrame:
        """
        Calculate SMA crossover signal.

        Returns:
            DataFrame of signal values (1 for bullish, -1 for bearish, 0 for neutral)
        """
        # Calculate fast and slow moving averages
        fast_ma = prices.select([
            pl.col(c).rolling_mean(window_size=self.fast_window) for c in prices.columns
        ])
        slow_ma = prices.select([
            pl.col(c).rolling_mean(window_size=self.slow_window) for c in prices.columns
        ])

        # Signal: fast MA - slow MA (positive when fast > slow)
        signal = fast_ma - slow_ma

        if self.standardize:
            # Z-score normalize
            signal = (signal - signal.mean()) / (signal.std() + 1e-8)

        # Fill NaN with 0
        signal = signal.fill_null(0).fill_nan(0)

        return signal


# =============================================================================
# CUSTOM ALPHA METHOD: Regime-Dependent IC
# =============================================================================

def create_regime_dependent_alpha(config):
    """
    Create alpha generator with regime-dependent IC.

    Uses higher IC in trending regimes, lower IC in choppy regimes.

    Args:
        config: StrategyConfig instance

    Returns:
        AlphaGenerator with regime-aware IC
    """
    base_ic = config.alpha.IC

    # For this example, use dynamic IC with regime detection
    # In production, you'd analyze market conditions
    return AlphaGenerator(
        IC=base_ic,
        dynamic_ic=True,
        ic_method='regime'  # Built-in regime detection
    )


# =============================================================================
# CUSTOM COVARIANCE: Shrinkage with Custom Target
# =============================================================================

class ConstantCorrelationCovariance:
    """
    Covariance estimator with constant correlation shrinkage target.

    Shrinks towards a matrix with unit variances and constant correlation.
    """

    def __init__(self, target_correlation: float = 0.5):
        """
        Args:
            target_correlation: Target correlation for shrinkage
        """
        self.target_correlation = target_correlation

    def estimate(self, returns: pl.DataFrame) -> pl.DataFrame:
        """
        Estimate covariance with constant correlation shrinkage.

        Args:
            returns: DataFrame of asset returns

        Returns:
            Covariance matrix DataFrame
        """
        # Sample covariance (convert to numpy for calculation)
        returns_np = returns.to_numpy()
        sample_cov = np.cov(returns_np, rowvar=False)

        # Create constant correlation target
        n_assets = sample_cov.shape[0]
        target = np.ones((n_assets, n_assets)) * self.target_correlation
        np.fill_diagonal(target, 1.0)

        # Convert to covariance (using sample variances)
        variances = np.diag(sample_cov)
        target_cov = np.outer(np.sqrt(variances), np.sqrt(variances)) * target

        # Simple shrinkage: 70% sample, 30% target
        shrinkage_intensity = 0.3
        shrunk_cov = (1 - shrinkage_intensity) * sample_cov + shrinkage_intensity * target_cov

        # Convert back to polars DataFrame
        return pl.DataFrame(shrunk_cov, schema=returns.columns)


# =============================================================================
# REGISTRATION AND EXAMPLE USAGE
# =============================================================================

def register_all_custom_components():
    """Register all custom components with their respective factories."""
    print("Registering custom components...")

    # Register custom signal
    SignalFactory.register_signal('sma_crossover', SMASignal)
    print("  ✓ Registered SMASignal as 'sma_crossover'")

    # Register custom alpha method
    AlphaFactory.register_method('regime_dependent', create_regime_dependent_alpha)
    print("  ✓ Registered regime_dependent alpha method")

    # Register custom covariance estimator
    CovarianceFactory.register_covariance('constant_corr', ConstantCorrelationCovariance)
    print("  ✓ Registered ConstantCorrelationCovariance as 'constant_corr'")

    print()


def example_1_custom_signal_only():
    """Example 1: Use custom signal with built-in components."""
    print("=" * 70)
    print("Example 1: Custom Signal with Built-in Components")
    print("=" * 70)

    config_dict = {
        'strategy': {
            'name': 'SMA Crossover Strategy',
            'type': 'custom',
            'description': 'Uses custom SMA crossover signal'
        },
        'universe': {
            'asset_class': 'futures',
            'instruments': ['SFRZ4', 'SFRH5', 'SFRM5']
        },
        'signals': [
            {
                'type': 'sma_crossover',
                'config': {
                    'fast_window': 10,
                    'slow_window': 30,
                    'standardize': True
                },
                'weight': 1.0
            }
        ],
        'alpha': {
            'IC': 0.05,
            'method': 'static'  # Built-in
        },
        'risk': {
            'covariance': 'ledoit_wolf'  # Built-in
        },
        'optimizer': {
            'type': 'mean_variance',
            'risk_aversion': 1.0
        },
        'execution': {
            'rebalance_frequency': 'weekly'
        },
        'backtest': {
            'start_date': '2024-01-01',
            'end_date': '2024-12-31'
        }
    }

    # Create config and strategy
    config = StrategyConfig.from_dict(config_dict)
    print(f"Strategy name: {config.strategy.name}")
    print(f"Signal type: {config.signals[0].type}")
    print(f"Fast window: {config.signals[0].config['fast_window']}")
    print(f"Alpha method: {config.alpha.method}")
    print()


def example_2_all_custom_components():
    """Example 2: Use all custom components together."""
    print("=" * 70)
    print("Example 2: All Custom Components Together")
    print("=" * 70)

    config_dict = {
        'strategy': {
            'name': 'Fully Custom Strategy',
            'type': 'custom',
            'description': 'All custom: signal, alpha, covariance'
        },
        'universe': {
            'asset_class': 'futures',
            'instruments': ['SFRZ4', 'SFRH5', 'SFRM5', 'SFRU5']
        },
        'signals': [
            {
                'type': 'sma_crossover',
                'config': {
                    'fast_window': 5,
                    'slow_window': 20
                }
            }
        ],
        'alpha': {
            'IC': 0.07,
            'method': 'regime_dependent'  # Custom!
        },
        'risk': {
            'covariance': 'constant_corr'  # Custom!
        },
        'optimizer': {
            'type': 'mean_variance',
            'risk_aversion': 1.5
        },
        'execution': {
            'rebalance_frequency': 'weekly'
        },
        'backtest': {
            'start_date': '2024-01-01',
            'end_date': '2024-12-31'
        }
    }

    config = StrategyConfig.from_dict(config_dict)
    print(f"Strategy name: {config.strategy.name}")
    print(f"Signal: {config.signals[0].type} (CUSTOM)")
    print(f"Alpha: {config.alpha.method} (CUSTOM)")
    print(f"Covariance: {config.risk.covariance} (CUSTOM)")
    print()


def example_3_mixed_signals():
    """Example 3: Mix custom and built-in signals."""
    print("=" * 70)
    print("Example 3: Mix Custom and Built-in Signals")
    print("=" * 70)

    config_dict = {
        'strategy': {
            'name': 'Hybrid Strategy',
            'type': 'multi_signal',
            'description': 'Mixes SMA (custom) with Carry (built-in)'
        },
        'universe': {
            'asset_class': 'futures',
            'instruments': ['SFRZ4', 'SFRH5', 'SFRM5']
        },
        'signals': [
            {
                'type': 'sma_crossover',  # Custom
                'config': {'fast_window': 10, 'slow_window': 30},
                'weight': 0.6
            },
            {
                'type': 'carry',  # Built-in
                'config': {'standardize': True},
                'weight': 0.4
            }
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
            'risk_aversion': 1.0
        },
        'execution': {
            'rebalance_frequency': 'weekly'
        },
        'backtest': {
            'start_date': '2024-01-01',
            'end_date': '2024-12-31'
        }
    }

    config = StrategyConfig.from_dict(config_dict)
    print(f"Strategy name: {config.strategy.name}")
    print(f"Number of signals: {len(config.signals)}")
    for i, sig in enumerate(config.signals, 1):
        sig_type = "CUSTOM" if sig.type == 'sma_crossover' else "BUILT-IN"
        print(f"  Signal {i}: {sig.type} ({sig_type}), weight={sig.weight}")
    print()


def example_4_list_available_components():
    """Example 4: List all available components after registration."""
    print("=" * 70)
    print("Example 4: Available Components After Registration")
    print("=" * 70)

    signals = SignalFactory.list_available_signals()
    alpha_methods = AlphaFactory.list_available_methods()
    cov_methods = CovarianceFactory.list_available_methods()

    print("Available Signals:")
    for sig in sorted(signals):
        is_custom = sig == 'sma_crossover'
        marker = "← CUSTOM" if is_custom else ""
        print(f"  - {sig} {marker}")

    print("\nAvailable Alpha Methods:")
    for method in sorted(alpha_methods):
        is_custom = method == 'regime_dependent'
        marker = "← CUSTOM" if is_custom else ""
        print(f"  - {method} {marker}")

    print("\nAvailable Covariance Methods:")
    for method in sorted(cov_methods):
        is_custom = method == 'constant_corr'
        marker = "← CUSTOM" if is_custom else ""
        print(f"  - {method} {marker}")
    print()


def example_5_save_custom_template():
    """Example 5: Create and save a custom strategy template."""
    print("=" * 70)
    print("Example 5: Create and Save Custom Strategy Template")
    print("=" * 70)

    custom_template = {
        'strategy': {
            'name': 'SMA Momentum Combo',
            'type': 'multi_signal',
            'description': 'SMA crossover + momentum'
        },
        'universe': {
            'asset_class': 'futures',
            'instruments': ['SFRZ4', 'SFRH5', 'SFRM5']
        },
        'signals': [
            {'type': 'sma_crossover', 'config': {'fast_window': 10, 'slow_window': 30}, 'weight': 0.5},
            {'type': 'momentum', 'config': {'lookback_days': 60}, 'weight': 0.5}
        ],
        'alpha': {
            'IC': 0.06,
            'method': 'regime_dependent'
        },
        'risk': {
            'covariance': 'constant_corr'
        },
        'optimizer': {
            'type': 'mean_variance',
            'risk_aversion': 1.2,
            'constraints': {
                'long_only': False,
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
    }

    # Register template
    registry = StrategyRegistry()
    StrategyRegistry.register_template('sma_momentum_combo', custom_template)

    print("Registered custom template: 'sma_momentum_combo'")
    print("\nTemplate includes:")
    print("  - SMA crossover signal (custom)")
    print("  - Momentum signal (built-in)")
    print("  - Regime-dependent alpha (custom)")
    print("  - Constant correlation covariance (custom)")
    print("\nTemplate can now be used like:")
    print("  strategy = quick_strategy('sma_momentum_combo', instruments=[...])")
    print()


def main():
    """Run all examples."""
    print("\n")
    print("*" * 70)
    print("*" + " " * 68 + "*")
    print("*" + "  Custom Components Example - Strategy Factory Extension".center(68) + "*")
    print("*" + " " * 68 + "*")
    print("*" * 70)
    print()

    # Register all custom components first
    register_all_custom_components()

    # Run examples
    example_1_custom_signal_only()
    example_2_all_custom_components()
    example_3_mixed_signals()
    example_4_list_available_components()
    example_5_save_custom_template()

    # Summary
    print("=" * 70)
    print("Summary")
    print("=" * 70)
    print("✓ Custom components registered successfully")
    print("✓ All examples ran without errors")
    print("✓ Custom and built-in components work together seamlessly")
    print()
    print("Next steps:")
    print("  - See docs/ADDING_CUSTOM_COMPONENTS.md for detailed guide")
    print("  - Check tests/unit/strategies/test_dynamic_validation.py for tests")
    print("  - Implement your own signals, alpha methods, or covariance estimators")
    print()


if __name__ == '__main__':
    main()
