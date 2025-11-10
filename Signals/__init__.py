# ABOUTME: Alpha signal generation module implementing Grinold-Kahn framework
# ABOUTME: Provides standardized signal generation, IC calculation, and signal quality evaluation
"""
Alpha Signal Generation Module

Implements the Grinold-Kahn signal framework for active portfolio management.

Modules:
- Base: Abstract base classes (BaseSignal)
- Futures: Futures-specific signals (CarrySignal)
- Utils: Signal utilities (IC calculation)

Usage:
    from Signals.Futures.CarrySignal import CarrySignal
    from Signals.Utils.IC import calculate_ic

    # Create signal
    signal = CarrySignal(name="futures_carry", standardize=True)

    # Generate alphas for multiple contracts
    alphas = signal.generate_batch(inst_data_list, market_data, as_of)

    # Calculate IC
    ic = signal.calculate_ic(forecasts, actuals)
"""

__version__ = "0.1.0"
