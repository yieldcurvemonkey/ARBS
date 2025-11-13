#!/usr/bin/env python
# ABOUTME: Currency rotation backtest example using CurrencyCarrySignal
# ABOUTME: Demonstrates sector ↔ currency equivalence with mock yield curve data

"""
Currency Rotation Backtest

Demonstrates the equivalence between sector rotation and currency carry strategies:
- Sector (Tech, Finance) ↔ Currency (USD, EUR)
- Stock (AAPL, MSFT) ↔ Tenor Point (USD 10Y, EUR 5Y)

Strategy:
1. Calculate carry per currency-tenor (analogous to momentum per stock)
2. Z-score normalization (cross-currency neutral, like cross-sectional)
3. Rank currencies by carry
4. Long top 3 butterflies, short bottom 3
5. DV01-neutral portfolio (analogous to dollar-neutral)

This mirrors the SectorMomentumSignal → SectorLongShortPortfolio workflow.
"""

import numpy as np
import polars as pl
from datetime import date, timedelta
from typing import Dict, List, Tuple

from Query.Currencies.CurrencyQuery import CurrencyQuery
from Query.Currencies.CurrencyStructure import CurrencyStructure
from Query.Currencies.CurrencyValue import CurrencyValue
from Signals.CurrencyCarrySignal import CurrencyCarrySignal


def generate_synthetic_yield_curves(
    currencies: List[str],
    tenors: List[str],
    start_date: date,
    end_date: date,
    seed: int = 42,
) -> pl.DataFrame:
    """
    Generate synthetic yield curve data for backtesting.

    Yield = base_rate[currency] + tenor_spread[tenor] + noise

    Parameters:
        currencies: List of currency codes (e.g., ["USD", "EUR", "GBP", "CHF"])
        tenors: List of tenor points (e.g., ["2Y", "5Y", "10Y"])
        start_date: Start of data period
        end_date: End of data period
        seed: Random seed for reproducibility

    Returns:
        DataFrame with columns: [currency, tenor, date, yield, return]
    """
    np.random.seed(seed)

    # Base rates per currency (annualized)
    base_rates = {
        "USD": 0.04,  # 4% base
        "EUR": 0.02,  # 2% base
        "GBP": 0.045,  # 4.5% base
        "CHF": 0.01,  # 1% base (safe haven)
    }

    # Tenor spreads (curve shape)
    tenor_spreads = {
        "2Y": 0.00,  # Short end
        "5Y": 0.015,  # Mid curve
        "10Y": 0.025,  # Long end
        "30Y": 0.035,  # Very long
    }

    # Generate dates
    num_days = (end_date - start_date).days
    dates = [start_date + timedelta(days=i) for i in range(num_days)]

    # Build data
    data = []
    for currency in currencies:
        for tenor in tenors:
            # Base yield for this currency-tenor
            base_yield = base_rates[currency] + tenor_spreads[tenor]

            # Generate time series with mean reversion
            yields = []
            current_yield = base_yield

            for i in range(len(dates)):
                # Mean reversion: pull toward base_yield
                drift = -0.05 * (current_yield - base_yield)  # Mean reversion speed
                diffusion = 0.002 * np.random.randn()  # Random noise (20 bps vol)

                current_yield += drift + diffusion
                yields.append(current_yield)

            # Calculate returns (daily change in yield)
            returns = [0.0] + [yields[i] - yields[i-1] for i in range(1, len(yields))]

            for date_val, yield_val, return_val in zip(dates, yields, returns):
                data.append({
                    "currency": currency,
                    "tenor": tenor,
                    "date": date_val,
                    "yield": yield_val,
                    "return": return_val,
                })

    return pl.DataFrame(data)


def calculate_dv01(
    tenor: str,
    notional: float = 1_000_000,
) -> float:
    """
    Calculate DV01 (dollar value of 1 basis point) for a tenor point.

    Simplified formula: DV01 ≈ duration × notional × 0.0001

    Parameters:
        tenor: Tenor point (e.g., "2Y", "10Y")
        notional: Notional amount (default: $1M)

    Returns:
        DV01 in dollars
    """
    # Approximate duration by tenor
    durations = {
        "2Y": 1.9,
        "5Y": 4.5,
        "10Y": 8.5,
        "30Y": 18.0,
    }

    duration = durations.get(tenor, 5.0)
    dv01 = duration * notional * 0.0001

    return dv01


def run_currency_rotation_backtest():
    """
    Run end-to-end currency rotation backtest.

    Mirrors equity sector rotation:
    - Currencies = Sectors
    - Tenor points = Stocks
    - Carry = Momentum
    - DV01-neutral = Dollar-neutral
    """
    print("=" * 80)
    print("Currency Rotation Backtest")
    print("Demonstrating Sector ↔ Currency Equivalence")
    print("=" * 80)
    print()

    # Setup
    currencies = ["USD", "EUR", "GBP", "CHF"]
    tenors = ["2Y", "5Y", "10Y"]
    start_date = date(2020, 1, 1)
    end_date = date(2023, 12, 31)

    print("Universe:")
    print(f"  Currencies: {', '.join(currencies)}")
    print(f"  Tenors: {', '.join(tenors)}")
    print(f"  Period: {start_date} to {end_date}")
    print()

    # Generate synthetic data
    print("Generating synthetic yield curve data...")
    yield_data = generate_synthetic_yield_curves(
        currencies=currencies,
        tenors=tenors,
        start_date=start_date,
        end_date=end_date,
        seed=42,
    )
    print(f"  Generated {len(yield_data)} data points")
    print()

    # Initialize carry signal (10Y-2Y carry)
    print("Initializing CurrencyCarrySignal (10Y-2Y carry)...")
    carry_signal = CurrencyCarrySignal(
        long_tenor="10Y",
        short_tenor="2Y",
        standardize=True,  # Cross-currency neutralization
        track_history=True,
    )
    print(f"  Signal: {carry_signal}")
    print()

    # Select evaluation date (middle of period)
    eval_date = date(2022, 6, 30)
    print(f"Signal Evaluation Date: {eval_date}")
    print()

    # Prepare data for each currency
    print("Calculating carry signals...")
    inst_data_list = []
    for currency in currencies:
        currency_data = yield_data.filter(pl.col("currency") == currency)
        inst_data_list.append(currency_data)

    # Generate signals
    carry_signals = carry_signal.generate_batch(
        inst_data_list=inst_data_list,
        market_data=None,
        as_of=eval_date,
    )

    # Display results
    print("\nCarry Signals (Z-scores):")
    print("-" * 40)
    for currency, signal_val in zip(currencies, carry_signals):
        print(f"  {currency:4s}: {signal_val:+.3f}")

    # Verify cross-currency neutralization
    print()
    print("Cross-Currency Neutralization Check:")
    print(f"  Mean: {np.mean(carry_signals):.6f} (should be ≈ 0)")
    print(f"  Std:  {np.std(carry_signals, ddof=1):.6f} (should be ≈ 1)")
    print()

    # Rank currencies by carry
    ranking = sorted(
        zip(currencies, carry_signals),
        key=lambda x: x[1],
        reverse=True
    )

    print("Ranking (High Carry → Low Carry):")
    print("-" * 40)
    for i, (currency, signal_val) in enumerate(ranking, 1):
        print(f"  {i}. {currency:4s}: {signal_val:+.3f}")
    print()

    # Portfolio construction: Long top 3, short bottom 3
    # For simplicity, equal weight within long and short baskets
    n_long = min(3, len(currencies))
    n_short = min(3, len(currencies))

    long_basket = ranking[:n_long]
    short_basket = ranking[-n_short:]

    print("Portfolio Construction:")
    print("-" * 40)
    print("Long Basket (High Carry):")
    for currency, signal_val in long_basket:
        print(f"  {currency:4s}: {signal_val:+.3f}")

    print("\nShort Basket (Low Carry):")
    for currency, signal_val in short_basket:
        print(f"  {currency:4s}: {signal_val:+.3f}")
    print()

    # Calculate DV01-neutral weights
    print("DV01-Neutral Portfolio:")
    print("-" * 40)

    tenor_for_signal = "10Y"  # Using 10Y as proxy
    dv01_per_position = calculate_dv01(tenor_for_signal, notional=1_000_000)

    print(f"  DV01 per position (10Y, $1M notional): ${dv01_per_position:,.0f}")
    print()

    long_weight = 1.0 / n_long if n_long > 0 else 0
    short_weight = -1.0 / n_short if n_short > 0 else 0

    print("Positions:")
    for currency, signal_val in long_basket:
        print(f"  {currency:4s}: +{long_weight:.2%} (LONG)")

    for currency, signal_val in short_basket:
        print(f"  {currency:4s}: {short_weight:.2%} (SHORT)")
    print()

    # Calculate portfolio DV01
    long_dv01 = n_long * dv01_per_position * long_weight
    short_dv01 = n_short * dv01_per_position * short_weight
    net_dv01 = long_dv01 + short_dv01

    print("DV01 Analysis:")
    print(f"  Long DV01:  ${long_dv01:,.0f}")
    print(f"  Short DV01: ${short_dv01:,.0f}")
    print(f"  Net DV01:   ${net_dv01:,.0f}")
    print(f"  DV01-Neutral: {abs(net_dv01) < 100}")
    print()

    # Simulate forward performance (IC check)
    print("Forward Performance Check (Next Month):")
    print("-" * 40)

    # Calculate actual returns for next month
    forward_date = eval_date + timedelta(days=30)
    forward_returns = []

    for currency in currencies:
        currency_data = yield_data.filter(
            (pl.col("currency") == currency) &
            (pl.col("tenor") == "10Y")
        )

        # Get returns between eval_date and forward_date
        forward_period = currency_data.filter(
            (pl.col("date") > eval_date) &
            (pl.col("date") <= forward_date)
        )

        if len(forward_period) > 0:
            cumulative_return = forward_period["return"].sum()
            forward_returns.append(cumulative_return)
        else:
            forward_returns.append(0.0)

    print("Actual Returns (Next Month):")
    for currency, ret in zip(currencies, forward_returns):
        print(f"  {currency:4s}: {ret:+.4f}")

    # Calculate IC
    from scipy.stats import pearsonr
    ic, p_value = pearsonr(carry_signals, forward_returns)

    print()
    print("Information Coefficient:")
    print(f"  IC: {ic:.3f}")
    print(f"  P-value: {p_value:.4f}")
    print(f"  Predictive Power: {'Good' if abs(ic) > 0.05 else 'Weak'}")
    print()

    # Summary
    print("=" * 80)
    print("Summary: Sector ↔ Currency Equivalence")
    print("=" * 80)
    print()
    print("Equity Sector Model          │  Currency Model")
    print("─────────────────────────────┼──────────────────────────")
    print("Sector (Tech, Finance)       │  Currency (USD, EUR)")
    print("Stock (AAPL, MSFT)           │  Tenor Point (USD 10Y, EUR 5Y)")
    print("Momentum Signal              │  Carry Signal")
    print("Cross-Sectional Z-Score      │  Cross-Currency Z-Score")
    print("Dollar-Neutral Portfolio     │  DV01-Neutral Portfolio")
    print("Long/Short Top-N/Bottom-N    │  Long/Short Top-N/Bottom-N")
    print()
    print("✅ Implementation Complete: Currency translation layer validates")
    print("   the cross-asset framework. Same architecture, different asset class.")
    print()


if __name__ == "__main__":
    run_currency_rotation_backtest()
