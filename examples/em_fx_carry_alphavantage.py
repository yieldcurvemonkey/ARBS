# ABOUTME: EM FX carry strategy using real AlphaVantage data
# ABOUTME: Demonstrates EMFXCarrySignal with live FX spot rates and interest rate differentials

"""
EM FX Carry Strategy with AlphaVantage Data

Demonstrates complete workflow for EM FX carry trading using real market data:
1. Fetch FX spot rates from AlphaVantage
2. Get central bank policy rates
3. Calculate carry signals (interest differential adjusted for FX vol)
4. Generate dollar-neutral portfolio weights
5. Analyze expected performance

Setup:
    1. Get free AlphaVantage API key: https://www.alphavantage.co/support/#api-key
    2. Set environment variable:
       export ALPHAVANTAGE_API_KEY="your_key_here"
    3. Run: python em_fx_carry_alphavantage.py

Academic Foundation:
    - Lustig, Roussanov, Verdelhan (2011): "Common Risk Factors in Currency Markets"
    - Burnside, Eichenbaum, Rebelo (2011): "Carry Trade and Momentum in Currency Markets"
    - UIP violation: High-yield currencies don't depreciate as much as theory predicts
"""

import sys
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

import os
import numpy as np
import polars as pl
from datetime import date, timedelta
from typing import Dict, List

# MDP and Signal imports
from MDP.AlphaVantage.AlphaVantageFXMDP import AlphaVantageFXMDP
from Signals.EMFXCarrySignal import EMFXCarrySignal


def example_1_fetch_fx_data():
    """
    Example 1: Fetch FX Spot Rates from AlphaVantage

    Demonstrates fetching historical FX data for EM currencies.
    """
    print("="*80)
    print("EXAMPLE 1: Fetch FX Spot Rates from AlphaVantage")
    print("="*80)
    print()

    # Check for API key
    api_key = os.getenv("ALPHAVANTAGE_API_KEY")
    if not api_key:
        print("ERROR: ALPHAVANTAGE_API_KEY environment variable not set!")
        print("Get free API key: https://www.alphavantage.co/support/#api-key")
        print("Set via: export ALPHAVANTAGE_API_KEY='your_key'")
        print()
        return None

    print("AlphaVantage Setup:")
    print(f"  API Key: {'*' * 10}{api_key[-4:]}")
    print(f"  Tier: Free (5 calls/min, 500 calls/day)")
    print()

    # Create MDP
    print("Creating AlphaVantage FX MDP...")
    mdp = AlphaVantageFXMDP(api_key=api_key, tier="free")
    print("✓ MDP created")
    print()

    # Define EM currencies to fetch
    currencies = ["BRL", "TRY", "MXN", "ZAR"]
    end_date = date.today()
    start_date = end_date - timedelta(days=365)  # 1 year of history

    print(f"Fetching FX data for: {', '.join(currencies)}")
    print(f"Date range: {start_date} to {end_date}")
    print(f"Expected API calls: {len(currencies)}")
    print(f"Estimated time: ~{len(currencies) * 12}s (rate limiting)")
    print()

    # Fetch data
    try:
        request = {
            "currencies": currencies,
            "start_date": start_date,
            "end_date": end_date,
            "include_interest_rates": True,
            "interval": "daily",
        }

        print("Fetching data (this may take a minute with rate limiting)...")
        fx_data = mdp.get_pricer(request)

        print("✓ Data fetched successfully!")
        print()

        # Display summary
        df = fx_data.data
        print("Data Summary:")
        print("-"*80)
        print(f"Total observations: {len(df):,}")
        print(f"Currencies: {df['currency'].n_unique()}")
        print(f"Date range: {df['date'].min()} to {df['date'].max()}")
        print(f"Days of history: {(df['date'].max() - df['date'].min()).days}")
        print()

        # Show sample data
        print("Sample Data (most recent 5 days for BRL):")
        print("-"*80)
        sample = df.filter(pl.col("currency") == "BRL").head(5)
        print(sample)
        print()

        return fx_data

    except Exception as e:
        print(f"✗ Error fetching data: {e}")
        print()
        return None


def example_2_calculate_carry_signals(fx_data: Dict):
    """
    Example 2: Calculate Carry Signals

    Uses EMFXCarrySignal to compute risk-adjusted carry signals.
    """
    if fx_data is None:
        print("Skipping Example 2 (no FX data)")
        return None

    print("="*80)
    print("EXAMPLE 2: Calculate Carry Signals")
    print("="*80)
    print()

    print("Carry Trade Logic:")
    print("  1. Interest differential: target_rate - USD_rate")
    print("  2. FX volatility: Annualized std dev of log returns")
    print("  3. Carry-to-risk: carry / FX_vol (Sharpe-like ratio)")
    print("  4. Z-score normalization across currencies")
    print()

    # Create carry signal
    carry_signal = EMFXCarrySignal(
        funding_currency='USD',
        lookback_days=60,
        risk_adjust=True,
        normalization='z_score',
        long_threshold=0.5,
        short_threshold=-0.5,
    )

    print("Signal Configuration:")
    print(f"  Funding currency: {carry_signal.funding_currency}")
    print(f"  Lookback: {carry_signal.lookback_days} days")
    print(f"  Risk adjust: {carry_signal.risk_adjust}")
    print(f"  Normalization: {carry_signal.normalization}")
    print(f"  Long threshold: {carry_signal.long_threshold}")
    print(f"  Short threshold: {carry_signal.short_threshold}")
    print()

    # Prepare data for signal evaluation
    df = fx_data.data

    # Build currency_data dict for evaluate_multiple
    currencies = df["currency"].unique().to_list()
    currency_data = {}

    for currency in currencies:
        currency_df = df.filter(pl.col("currency") == currency)

        # Rename columns to match EMFXCarrySignal expectations
        currency_df = currency_df.select([
            pl.col("date"),
            pl.col("fx_rate"),
            pl.col("interest_rate").fill_null(0.0),
            pl.col("usd_rate").fill_null(0.055),
        ])

        currency_data[currency] = currency_df

    # Evaluate signals
    print("Evaluating carry signals...")
    eval_date = df["date"].max()
    signals = carry_signal.evaluate_multiple(eval_date, currency_data)

    print(f"✓ Signals calculated as of {eval_date}")
    print()

    # Display signals
    print("Carry Signals (z-score normalized):")
    print("-"*80)
    print(f"{'Currency':<10} {'Signal':<10} {'Direction':<15} {'Position'}")
    print("-"*80)

    for currency, signal_value in sorted(signals.items(), key=lambda x: x[1], reverse=True):
        direction = "LONG " if signal_value > carry_signal.long_threshold else \
                   "SHORT" if signal_value < carry_signal.short_threshold else \
                   "NEUTRAL"

        position = "✓" if abs(signal_value) > 0.5 else "-"

        print(f"{currency:<10} {signal_value:>8.3f}  {direction:<15} {position}")

    print()

    return signals, carry_signal, currency_data


def example_3_portfolio_construction(signals: Dict, carry_signal: EMFXCarrySignal):
    """
    Example 3: Portfolio Construction

    Generate dollar-neutral portfolio weights from carry signals.
    """
    if signals is None:
        print("Skipping Example 3 (no signals)")
        return None

    print("="*80)
    print("EXAMPLE 3: Portfolio Construction")
    print("="*80)
    print()

    print("Portfolio Constraints:")
    print("  - Dollar-neutral: sum(weights) = 0")
    print("  - Long high-carry currencies (z-score > 0.5)")
    print("  - Short low-carry currencies (z-score < -0.5)")
    print("  - Proportional to signal strength")
    print()

    # Generate weights
    weights = carry_signal.generate_portfolio_weights(signals, equal_weight=False)

    print("Portfolio Weights (signal-proportional):")
    print("-"*80)
    print(f"{'Currency':<10} {'Weight':<10} {'Gross':<10} {'Direction'}")
    print("-"*80)

    total_long = 0.0
    total_short = 0.0

    for currency, weight in sorted(weights.items(), key=lambda x: abs(x[1]), reverse=True):
        if abs(weight) > 0.001:
            direction = "LONG" if weight > 0 else "SHORT"
            gross = abs(weight)

            if weight > 0:
                total_long += weight
            else:
                total_short += abs(weight)

            print(f"{currency:<10} {weight:>8.2%}  {gross:>8.2%}  {direction}")

    print("-"*80)
    print(f"{'TOTAL':<10} {sum(weights.values()):>8.2%}  {sum(abs(w) for w in weights.values()):>8.2%}")
    print()

    print("Portfolio Statistics:")
    print("-"*80)
    print(f"  Long exposure:  {total_long:>8.2%}")
    print(f"  Short exposure: {total_short:>8.2%}")
    print(f"  Gross exposure: {total_long + total_short:>8.2%}")
    print(f"  Net exposure:   {total_long - total_short:>8.2%} (should be ~0)")
    print(f"  Number of long positions:  {sum(1 for w in weights.values() if w > 0.01)}")
    print(f"  Number of short positions: {sum(1 for w in weights.values() if w < -0.01)}")
    print()

    return weights


def example_4_expected_performance(weights: Dict, currency_data: Dict):
    """
    Example 4: Expected Performance Analysis

    Calculate expected carry returns and risks.
    """
    if weights is None:
        print("Skipping Example 4 (no weights)")
        return

    print("="*80)
    print("EXAMPLE 4: Expected Performance Analysis")
    print("="*80)
    print()

    # Get interest rates from currency data
    from MDP.AlphaVantage.AlphaVantageFXMDP import DEFAULT_INTEREST_RATES
    usd_rate = DEFAULT_INTEREST_RATES["USD"]

    print("Expected Carry Returns:")
    print("-"*80)
    print(f"{'Currency':<10} {'Rate':<8} {'Carry':<8} {'Weight':<10} {'Contribution'}")
    print("-"*80)

    total_carry = 0.0

    for currency, weight in sorted(weights.items(), key=lambda x: abs(x[1]), reverse=True):
        if abs(weight) > 0.001:
            interest_rate = DEFAULT_INTEREST_RATES.get(currency, 0.0)
            carry = interest_rate - usd_rate
            contribution = weight * carry

            total_carry += contribution

            print(f"{currency:<10} {interest_rate*100:>6.2f}%  {carry*100:>6.2f}%  {weight:>8.2%}  {contribution*100:>8.2f}%")

    print("-"*80)
    print(f"{'TOTAL':<10} {'':>6}  {'':>6}  {'':>8}  {total_carry*100:>8.2f}%")
    print()

    # Calculate historical FX volatility
    print("Historical FX Volatility:")
    print("-"*80)

    fx_vols = {}
    for currency, df in currency_data.items():
        if len(df) > 20:
            # Calculate log returns
            rates = df.sort("date")["fx_rate"].to_numpy()
            log_returns = np.diff(np.log(rates))

            # Annualized volatility
            vol_daily = np.std(log_returns, ddof=1)
            vol_annual = vol_daily * np.sqrt(252)

            fx_vols[currency] = vol_annual

            weight = weights.get(currency, 0.0)
            if abs(weight) > 0.001:
                print(f"{currency:<10} {vol_annual*100:>8.2f}%  (weight: {weight:>6.2%})")

    print()

    # Expected Sharpe estimate
    portfolio_vol = np.sqrt(sum((weights.get(c, 0.0) ** 2) * (fx_vols.get(c, 0.15) ** 2) for c in weights.keys()))

    print("Expected Performance Metrics:")
    print("-"*80)
    print(f"  Expected Carry:       {total_carry*100:>8.2f}% (before FX moves)")
    print(f"  Estimated Vol:        {portfolio_vol*100:>8.2f}% (ignoring correlations)")
    print(f"  Estimated Sharpe:     {total_carry/portfolio_vol if portfolio_vol > 0 else 0.0:>8.2f}")
    print()

    print("Risk Factors:")
    print("-"*80)
    print("  ⚠ Negative skew: Carry crash risk during risk-off events")
    print("  ⚠ USD strength: When USD rallies, all EM depreciate")
    print("  ⚠ VIX spike: Volatility surge triggers de-risking")
    print("  ⚠ Country risk: Political instability, inflation, defaults")
    print()

    print("Risk Mitigation:")
    print("  ✓ Diversification: Multiple EM currencies")
    print("  ✓ Vol targeting: Scale down in high-vol regimes")
    print("  ✓ Dollar-neutral: Reduces directional USD risk")
    print("  ✓ Signal-based: Risk-adjusted (carry-to-risk ratio)")
    print()


def example_5_top_carry_currencies(signals: Dict, carry_signal: EMFXCarrySignal):
    """
    Example 5: Top Carry Currencies

    Identify highest carry opportunities.
    """
    if signals is None:
        print("Skipping Example 5 (no signals)")
        return

    print("="*80)
    print("EXAMPLE 5: Top Carry Currencies")
    print("="*80)
    print()

    # Get top 3 carry currencies
    top_currencies = carry_signal.get_top_carry_currencies(signals, top_n=3)

    print("Top 3 Carry Opportunities:")
    print("-"*80)

    from MDP.AlphaVantage.AlphaVantageFXMDP import DEFAULT_INTEREST_RATES, EM_CURRENCY_PAIRS
    usd_rate = DEFAULT_INTEREST_RATES["USD"]

    for i, currency in enumerate(top_currencies, 1):
        signal_value = signals[currency]
        interest_rate = DEFAULT_INTEREST_RATES.get(currency, 0.0)
        carry = interest_rate - usd_rate
        pair = EM_CURRENCY_PAIRS.get(currency, f"USD/{currency}")

        print(f"{i}. {currency} ({pair})")
        print(f"   Signal:        {signal_value:>8.3f} (z-score)")
        print(f"   Interest rate: {interest_rate*100:>8.2f}%")
        print(f"   Carry:         {carry*100:>8.2f}% (vs USD {usd_rate*100:.2f}%)")
        print()


def main():
    """Run all EM FX carry examples with AlphaVantage data."""
    print("\n")
    print("#"*80)
    print("# EM FX CARRY STRATEGY WITH ALPHAVANTAGE DATA")
    print("#"*80)
    print("\n")

    print("This script demonstrates:")
    print("  1. Fetching real FX spot rates from AlphaVantage")
    print("  2. Calculating carry signals (interest differential + vol adjustment)")
    print("  3. Generating dollar-neutral portfolio weights")
    print("  4. Analyzing expected performance and risks")
    print()

    print("Requirements:")
    print("  - AlphaVantage API key (free): https://www.alphavantage.co/support/#api-key")
    print("  - Set ALPHAVANTAGE_API_KEY environment variable")
    print()

    print("Note: Free tier rate limits (5 calls/min) means this will take 1-2 minutes.")
    print("Press Ctrl+C to cancel")
    print()

    try:
        # Example 1: Fetch FX data
        fx_data = example_1_fetch_fx_data()
        if fx_data is None:
            print("Exiting due to missing API key or fetch error")
            return

        input("\nPress Enter to continue to Example 2...")

        # Example 2: Calculate signals
        result = example_2_calculate_carry_signals(fx_data)
        if result is None:
            return
        signals, carry_signal, currency_data = result

        input("\nPress Enter to continue to Example 3...")

        # Example 3: Portfolio construction
        weights = example_3_portfolio_construction(signals, carry_signal)

        input("\nPress Enter to continue to Example 4...")

        # Example 4: Expected performance
        example_4_expected_performance(weights, currency_data)

        input("\nPress Enter to continue to Example 5...")

        # Example 5: Top currencies
        example_5_top_carry_currencies(signals, carry_signal)

        # Summary
        print()
        print("="*80)
        print("SUMMARY")
        print("="*80)
        print()
        print("✓ Successfully demonstrated EM FX carry strategy with real data!")
        print()
        print("What we accomplished:")
        print("  1. Fetched FX spot rates from AlphaVantage (4 currencies)")
        print("  2. Calculated risk-adjusted carry signals")
        print("  3. Generated dollar-neutral portfolio")
        print("  4. Analyzed expected performance")
        print("  5. Identified top carry opportunities")
        print()
        print("Next Steps:")
        print("  - Run with more currencies (expand EM universe)")
        print("  - Implement forward rates for UIP violation detection")
        print("  - Add crash protection (VIX monitoring, stop-loss)")
        print("  - Backtest on historical data")
        print("  - Combine with momentum and mean reversion strategies")
        print()
        print("="*80)
        print()

    except KeyboardInterrupt:
        print("\n\nExamples interrupted.")
        print()
    except Exception as e:
        print(f"\n\n✗ Error: {e}")
        import traceback
        traceback.print_exc()
        print()


if __name__ == '__main__':
    main()
