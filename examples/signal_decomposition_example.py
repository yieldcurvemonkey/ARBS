# ABOUTME: Demonstrates how to decompose existing signals into weighted components using DecomposableSignal framework
# ABOUTME: Shows CarrySignal decomposition into front carry, back carry, and term structure slope with custom weighting
"""
Signal Decomposition Example - Extending Signals with Component Analysis

Demonstrates how to decompose existing signals (CarrySignal, MomentumSignal, MeanReversionSignal)
into interpretable components using the DecomposableSignal framework.

Key Benefits:
- Maintains backward compatibility with existing signals
- Enables component-level analysis and weighting
- Provides transparency into what drives signal performance
- Allows for dynamic component weighting based on market regime

Usage:
    python examples/signal_decomposition_example.py
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from datetime import date
from typing import Dict, Optional, Any
import pandas as pd
import numpy as np

from Signals.Base.BaseSignal import BaseSignal
from Signals.Futures.CarrySignal import CarrySignal
from Signals.decomposable_signal import DecomposableSignal


# =============================================================================
# EXAMPLE 1: Decomposable Carry Signal
# =============================================================================

class DecomposableCarrySignal(CarrySignal, DecomposableSignal):
    """
    Carry signal decomposed into interpretable components.

    Components:
    1. Front Carry: Carry from front contract (near-term positioning)
    2. Back Carry: Carry from back contract (far-term positioning)
    3. Term Structure Slope: Difference between front and back (curve steepness)

    This decomposition allows traders to:
    - Weight near-term vs far-term carry differently
    - Isolate curve steepness effects
    - Adjust strategy based on market regime
    """

    def __init__(
        self,
        name: str = "decomposable_carry",
        component_weights: Optional[Dict[str, float]] = None,
        **kwargs
    ):
        """
        Initialize decomposable carry signal.

        Args:
            name: Signal name
            component_weights: Optional weights for components.
                             If None, equal weights used (1/3 each).
                             Example: {
                                 'front_carry': 0.5,
                                 'back_carry': 0.3,
                                 'term_structure_slope': 0.2
                             }
            **kwargs: Additional args passed to CarrySignal
        """
        CarrySignal.__init__(self, name=name, **kwargs)
        DecomposableSignal.__init__(self, component_weights=component_weights)

        # Store market data for component calculation
        self._last_inst_data = None
        self._last_market_data = None
        self._last_as_of = None

    def _calculate_raw_signal(
        self,
        inst_data: pd.DataFrame,
        market_data: Optional[Any],
        as_of: date,
    ) -> float:
        """
        Calculate raw carry signal (delegates to parent CarrySignal).

        Also stores data for component calculation.
        """
        # Store for component calculation
        self._last_inst_data = inst_data
        self._last_market_data = market_data
        self._last_as_of = as_of

        # Use parent implementation
        return super()._calculate_raw_signal(inst_data, market_data, as_of)

    def get_components(self) -> Dict[str, pd.DataFrame]:
        """
        Get carry signal components.

        Returns:
            Dict with three components:
            - 'front_carry': Near-term carry (annualized)
            - 'back_carry': Far-term carry (annualized)
            - 'term_structure_slope': Front carry - Back carry
        """
        if self._last_inst_data is None:
            raise ValueError("Must call _calculate_raw_signal before get_components")

        inst_data = self._last_inst_data
        as_of = self._last_as_of

        # Extract prices
        front_price = inst_data.iloc[0]["price"]
        next_price = inst_data.iloc[0].get("next_price", np.nan)
        roll_date = inst_data.iloc[0].get("roll_date", None)

        if pd.isna(next_price) or roll_date is None:
            # Return zero components if data missing
            zero_df = pd.DataFrame(0.0, index=[as_of], columns=['signal'])
            return {
                'front_carry': zero_df.copy(),
                'back_carry': zero_df.copy(),
                'term_structure_slope': zero_df.copy()
            }

        # Calculate days to roll
        days_to_roll = max((roll_date - as_of).days, 1)

        # Component 1: Front Carry
        # Simplified front carry (assumes flat forward curve from front contract)
        front_carry_raw = front_price * 0.01  # Simplified: 1% of front price
        front_carry_annualized = (
            front_carry_raw / days_to_roll
        ) * 10000 * self.business_days_per_year

        # Component 2: Back Carry
        # Simplified back carry (assumes flat forward curve from back contract)
        back_carry_raw = next_price * 0.01  # Simplified: 1% of back price
        back_carry_annualized = (
            back_carry_raw / days_to_roll
        ) * 10000 * self.business_days_per_year

        # Component 3: Term Structure Slope
        # Measures curve steepness (front - back)
        calendar_spread = front_price - next_price
        slope_annualized = (
            calendar_spread / days_to_roll
        ) * 10000 * self.business_days_per_year

        # Create DataFrames (shape: dates x assets)
        # For this example, single date and single asset
        front_df = pd.DataFrame(front_carry_annualized, index=[as_of], columns=['signal'])
        back_df = pd.DataFrame(back_carry_annualized, index=[as_of], columns=['signal'])
        slope_df = pd.DataFrame(slope_annualized, index=[as_of], columns=['signal'])

        return {
            'front_carry': front_df,
            'back_carry': back_df,
            'term_structure_slope': slope_df
        }


# =============================================================================
# EXAMPLE 2: How to Decompose Other Signals
# =============================================================================

def decompose_momentum_signal_guide():
    """
    Guide for decomposing MomentumSignal into components.

    Recommended Components:
    1. Short-term momentum (1-month lookback): Captures recent price action
    2. Medium-term momentum (3-month lookback): Captures intermediate trends
    3. Long-term momentum (12-month lookback): Captures major trends

    Implementation Pattern:
        class DecomposableMomentumSignal(MomentumSignal, DecomposableSignal):
            def get_components(self) -> Dict[str, pd.DataFrame]:
                # Calculate momentum at different lookback periods
                short_term = self._calculate_momentum(lookback_days=21)
                medium_term = self._calculate_momentum(lookback_days=63)
                long_term = self._calculate_momentum(lookback_days=252)

                return {
                    'short_term_momentum': short_term,
                    'medium_term_momentum': medium_term,
                    'long_term_momentum': long_term
                }

    Component Weights Example:
        # Emphasize recent momentum
        weights = {
            'short_term_momentum': 0.5,
            'medium_term_momentum': 0.3,
            'long_term_momentum': 0.2
        }

        signal = DecomposableMomentumSignal(component_weights=weights)
    """
    print("\n=== Momentum Signal Decomposition Guide ===")
    print("Components: short_term (21d), medium_term (63d), long_term (252d)")
    print("Use case: Weight recent vs historical momentum differently")
    print("Example weights: {'short_term_momentum': 0.5, 'medium_term_momentum': 0.3, 'long_term_momentum': 0.2}")


def decompose_mean_reversion_signal_guide():
    """
    Guide for decomposing MeanReversionSignal into components.

    Recommended Components:
    1. Price deviation from mean: Distance from moving average
    2. Velocity component: Rate of mean reversion
    3. Volatility-adjusted deviation: Deviation scaled by volatility

    Implementation Pattern:
        class DecomposableMeanReversionSignal(MeanReversionSignal, DecomposableSignal):
            def get_components(self) -> Dict[str, pd.DataFrame]:
                # Calculate mean reversion components
                price_deviation = self._calculate_price_deviation()
                reversion_velocity = self._calculate_reversion_velocity()
                vol_adjusted = self._calculate_vol_adjusted_deviation()

                return {
                    'price_deviation': price_deviation,
                    'reversion_velocity': reversion_velocity,
                    'vol_adjusted_deviation': vol_adjusted
                }

    Component Weights Example:
        # Emphasize volatility-adjusted signals
        weights = {
            'price_deviation': 0.2,
            'reversion_velocity': 0.3,
            'vol_adjusted_deviation': 0.5
        }

        signal = DecomposableMeanReversionSignal(component_weights=weights)
    """
    print("\n=== Mean Reversion Signal Decomposition Guide ===")
    print("Components: price_deviation, reversion_velocity, vol_adjusted_deviation")
    print("Use case: Separate magnitude vs speed of mean reversion")
    print("Example weights: {'price_deviation': 0.2, 'reversion_velocity': 0.3, 'vol_adjusted_deviation': 0.5}")


# =============================================================================
# MAIN DEMONSTRATION
# =============================================================================

def create_sample_data() -> pd.DataFrame:
    """Create sample futures data for demonstration."""
    return pd.DataFrame({
        'price': [94.50],
        'next_price': [94.45],
        'roll_date': [date(2025, 12, 15)]
    })


def demonstrate_backward_compatibility():
    """Show that existing CarrySignal still works without decomposition."""
    print("\n" + "="*70)
    print("DEMONSTRATION 1: Backward Compatibility")
    print("="*70)

    # Original CarrySignal usage (unchanged)
    carry_signal = CarrySignal(
        name="futures_carry",
        standardize=True,
        annualize=True
    )

    # Calculate signal
    sample_data = create_sample_data()
    signal_value = carry_signal._calculate_raw_signal(
        inst_data=sample_data,
        market_data=None,
        as_of=date(2025, 11, 1)
    )

    print(f"\nOriginal CarrySignal:")
    print(f"  Signal name: {carry_signal.name}")
    print(f"  Signal value: {signal_value:.2f} bps/year")
    print(f"  Standardize: {carry_signal.standardize}")
    print("\nResult: Original CarrySignal works exactly as before!")


def demonstrate_decomposition():
    """Show new DecomposableCarrySignal with component breakdown."""
    print("\n" + "="*70)
    print("DEMONSTRATION 2: Signal Decomposition")
    print("="*70)

    # Create decomposable carry signal with equal weights
    decomposable_carry = DecomposableCarrySignal(
        name="decomposable_carry",
        standardize=True,
        annualize=True
    )

    # Calculate signal and components
    sample_data = create_sample_data()
    signal_value = decomposable_carry._calculate_raw_signal(
        inst_data=sample_data,
        market_data=None,
        as_of=date(2025, 11, 1)
    )

    # Get individual components
    components = decomposable_carry.get_components()

    print(f"\nDecomposableCarrySignal:")
    print(f"  Signal name: {decomposable_carry.name}")
    print(f"  Total signal value: {signal_value:.2f} bps/year")
    print(f"\nComponent Breakdown:")
    for component_name, component_df in components.items():
        component_value = component_df.iloc[0, 0]
        print(f"  {component_name}: {component_value:.2f} bps/year")

    # Get composite signal (weighted sum of components)
    composite = decomposable_carry.get_composite_signal()
    composite_value = composite.iloc[0, 0]

    print(f"\nComposite Signal (equal weights):")
    print(f"  Value: {composite_value:.2f} bps/year")
    print(f"  Weights: {decomposable_carry.component_weights}")


def demonstrate_custom_weighting():
    """Show custom component weighting."""
    print("\n" + "="*70)
    print("DEMONSTRATION 3: Custom Component Weighting")
    print("="*70)

    # Define custom weights (emphasize term structure slope)
    custom_weights = {
        'front_carry': 0.3,
        'back_carry': 0.2,
        'term_structure_slope': 0.5
    }

    # Create decomposable carry signal with custom weights
    decomposable_carry = DecomposableCarrySignal(
        name="weighted_carry",
        component_weights=custom_weights,
        standardize=True,
        annualize=True
    )

    # Calculate signal
    sample_data = create_sample_data()
    signal_value = decomposable_carry._calculate_raw_signal(
        inst_data=sample_data,
        market_data=None,
        as_of=date(2025, 11, 1)
    )

    # Get components
    components = decomposable_carry.get_components()

    print(f"\nCustom Weighted Carry Signal:")
    print(f"  Signal name: {decomposable_carry.name}")
    print(f"\nComponent Values:")
    for component_name, component_df in components.items():
        component_value = component_df.iloc[0, 0]
        weight = custom_weights[component_name]
        weighted_value = component_value * weight
        print(f"  {component_name}:")
        print(f"    Raw value: {component_value:.2f} bps/year")
        print(f"    Weight: {weight:.1f}")
        print(f"    Weighted: {weighted_value:.2f} bps/year")

    # Get composite signal
    composite = decomposable_carry.get_composite_signal()
    composite_value = composite.iloc[0, 0]

    print(f"\nComposite Signal (custom weights):")
    print(f"  Value: {composite_value:.2f} bps/year")
    print(f"\nInterpretation: This weighting emphasizes term structure slope (50%)")
    print("over near-term and far-term carry, useful when curve steepness is")
    print("the primary driver of carry strategy performance.")


def demonstrate_dynamic_weighting():
    """Show how weights can be adjusted dynamically."""
    print("\n" + "="*70)
    print("DEMONSTRATION 4: Dynamic Weight Adjustment")
    print("="*70)

    # Create signal with initial weights
    decomposable_carry = DecomposableCarrySignal(
        name="dynamic_carry",
        component_weights={'front_carry': 0.6, 'back_carry': 0.3, 'term_structure_slope': 0.1},
        standardize=True,
        annualize=True
    )

    # Calculate initial signal
    sample_data = create_sample_data()
    decomposable_carry._calculate_raw_signal(sample_data, None, date(2025, 11, 1))

    initial_composite = decomposable_carry.get_composite_signal()
    initial_value = initial_composite.iloc[0, 0]

    print(f"\nInitial Configuration:")
    print(f"  Weights: {decomposable_carry.component_weights}")
    print(f"  Composite Signal: {initial_value:.2f} bps/year")

    # Change weights dynamically (e.g., based on market regime)
    print(f"\nMarket Regime Change Detected → Adjusting Weights")
    decomposable_carry._component_weights = {
        'front_carry': 0.2,
        'back_carry': 0.2,
        'term_structure_slope': 0.6
    }

    new_composite = decomposable_carry.get_composite_signal()
    new_value = new_composite.iloc[0, 0]

    print(f"\nNew Configuration:")
    print(f"  Weights: {decomposable_carry.component_weights}")
    print(f"  Composite Signal: {new_value:.2f} bps/year")
    print(f"  Change: {new_value - initial_value:+.2f} bps/year")

    print(f"\nUse Case: Dynamically adjust weights based on:")
    print("  - Market regime (trending vs mean-reverting)")
    print("  - Volatility environment (low vol vs high vol)")
    print("  - Historical component IC (which components predicting better)")


def main():
    """Run all demonstrations."""
    print("\n" + "="*70)
    print("SIGNAL DECOMPOSITION FRAMEWORK DEMONSTRATION")
    print("="*70)
    print("\nThis example shows how to decompose existing signals into")
    print("interpretable components while maintaining backward compatibility.")

    # Run demonstrations
    demonstrate_backward_compatibility()
    demonstrate_decomposition()
    demonstrate_custom_weighting()
    demonstrate_dynamic_weighting()

    # Show guides for other signals
    print("\n" + "="*70)
    print("GUIDES FOR DECOMPOSING OTHER SIGNALS")
    print("="*70)
    decompose_momentum_signal_guide()
    decompose_mean_reversion_signal_guide()

    # Summary
    print("\n" + "="*70)
    print("SUMMARY")
    print("="*70)
    print("\nKey Benefits of Signal Decomposition:")
    print("  1. Maintains backward compatibility with existing signals")
    print("  2. Provides transparency into signal drivers")
    print("  3. Enables component-level analysis and attribution")
    print("  4. Allows dynamic weighting based on market conditions")
    print("  5. Facilitates regime-dependent signal strategies")
    print("\nNext Steps:")
    print("  - Implement DecomposableMomentumSignal following the pattern above")
    print("  - Implement DecomposableMeanReversionSignal following the pattern above")
    print("  - Backtest component-weighted strategies vs equal-weighted baseline")
    print("  - Analyze which components have highest IC in different regimes")
    print("\n" + "="*70)


if __name__ == "__main__":
    main()
