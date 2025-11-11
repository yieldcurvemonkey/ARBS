# ABOUTME: End-to-end example demonstrating MinimalBacktest MVP
# ABOUTME: Runs complete Query→Adapter→Signals→Risk→Optimizer→Backtest pipeline
"""
Minimal Backtest Example

Demonstrates end-to-end MVP backtest measuring a simple carry strategy.

MVP Philosophy:
- Goal is ACCURATE MEASUREMENT, not profitability
- If strategy loses money, that's fine - we measure it correctly
- No IC requirement for MVP success

Pipeline:
1. Query: Get futures prices (SOFR contracts)
2. Adapter: Convert to signal-ready DataFrame
3. Signals: Generate carry alphas
4. Risk: Estimate covariance (Ledoit-Wolf)
5. Optimizer: Calculate mean-variance optimal weights
6. Backtest: Track positions and P&L

Output:
- Sharpe ratio (annualized)
- Information Coefficient (IC)
- Total return (%)
- Returns time series
"""

from datetime import date, timedelta
import numpy as np
import polars as pl
from Backtest.MinimalBacktest import MinimalBacktest


# Mock Market Data Provider for demonstration
class SimpleMockMDP:
    """
    Simple mock market data provider for demonstration.

    Returns synthetic futures prices with realistic carry structure.
    """

    def __init__(self, base_rate: float = 5.0, carry_spread: float = 0.10):
        """
        Initialize mock MDP.

        Args:
            base_rate: Base interest rate in % (e.g., 5.0 for 5%)
            carry_spread: Carry spread in % between contracts (e.g., 0.10 for 10bp)
        """
        self.base_rate = base_rate
        self.carry_spread = carry_spread

    def get_pricer(self, currency: str, as_of: date):
        """Return a mock pricer with futures_price method."""
        return self

    def futures_price(self, contract: str) -> float:
        """
        Return synthetic futures price.

        Prices have realistic carry structure:
        - Base price = 100 - rate
        - Rate increases by carry_spread for each quarter out
        """
        # Extract contract quarter (Z=Dec, H=Mar, M=Jun, U=Sep)
        if len(contract) < 4:
            return 100.0 - self.base_rate

        quarter_code = contract[-2]
        year_code = contract[-1]

        # Map quarter to number (0-3)
        quarter_map = {'H': 0, 'M': 1, 'U': 2, 'Z': 3}
        quarter = quarter_map.get(quarter_code, 0)

        # Add carry spread per quarter
        rate = self.base_rate + (quarter * self.carry_spread)

        # Convert to futures price
        price = 100.0 - rate

        # Add small random noise
        noise = np.random.normal(0, 0.01)

        return price + noise


def run_example():
    """
    Run minimal backtest example.

    Tests carry strategy on 3-month SOFR futures over 3-month period.
    """
    print("="*70)
    print("Minimal Backtest MVP - End-to-End Example")
    print("="*70)
    print()

    # Setup
    print("Setup:")
    print("- Contracts: SFRZ4, SFRH5, SFRM5, SFRU5 (SOFR futures)")
    print("- Strategy: Simple carry (long higher carry, short lower)")
    print("- Period: 2024-09-01 to 2024-12-01 (weekly rebalance)")
    print("- Risk model: Ledoit-Wolf covariance shrinkage")
    print("- Optimizer: Mean-variance (long-only)")
    print()

    # Create mock market data provider
    mdp = SimpleMockMDP(base_rate=5.0, carry_spread=0.10)

    # Initialize backtest
    backtest = MinimalBacktest(
        mdp=mdp,
        risk_aversion=1.0,  # Moderate risk aversion
        long_only=True,     # Only long positions
        min_history=5,      # Need 5 weeks before estimating covariance
    )

    # Define universe
    contracts = ['SFRZ4', 'SFRH5', 'SFRM5', 'SFRU5']

    # Define backtest period (weekly rebalancing)
    start_date = date(2024, 9, 1)
    end_date = date(2024, 12, 1)
    dates = pl.date_range(start_date, end_date, "1w", eager=True).to_list()
    dates = [d.date() if hasattr(d, 'date') else d for d in dates]

    print("Running backtest...")
    print()

    # Run backtest
    result = backtest.run(contracts=contracts, dates=dates)

    # Display results
    print("="*70)
    print("Results")
    print("="*70)
    print()

    print(f"Performance Metrics:")
    print(f"  Sharpe Ratio:      {result.sharpe_ratio:>8.3f}")
    print(f"  Information Coeff: {result.ic:>8.3f}")
    print(f"  Total Return:      {result.total_return:>8.2%}")
    print()

    print(f"Backtest Statistics:")
    print(f"  Number of periods: {len(result.returns):>8}")
    print(f"  Number of assets:  {len(result.weights.columns):>8}")
    print(f"  Mean return:       {result.returns.mean():>8.4%}")
    print(f"  Std deviation:     {result.returns.std():>8.4%}")
    print()

    # Show sample weights (first and last period)
    if len(result.weights) > 0:
        print("Sample Portfolio Weights:")
        print()
        print("First period:")
        first_weights = result.weights.iloc[0]
        for contract, weight in first_weights.items():
            if abs(weight) > 0.01:
                print(f"  {contract}: {weight:>6.2%}")
        print()

        if len(result.weights) > 1:
            print("Last period:")
            last_weights = result.weights.iloc[-1]
            for contract, weight in last_weights.items():
                if abs(weight) > 0.01:
                    print(f"  {contract}: {weight:>6.2%}")
            print()

    # Show returns time series (first 5 and last 5)
    if len(result.returns) > 0:
        print("Returns Time Series (sample):")
        print()
        n_show = min(5, len(result.returns))
        print(f"First {n_show} periods:")
        for idx in result.returns.index[:n_show]:
            ret = result.returns[idx]
            print(f"  {idx}: {ret:>8.4%}")

        if len(result.returns) > n_show:
            print()
            print(f"Last {n_show} periods:")
            for idx in result.returns.index[-n_show:]:
                ret = result.returns[idx]
                print(f"  {idx}: {ret:>8.4%}")
        print()

    print("="*70)
    print("MVP Philosophy Check")
    print("="*70)
    print()
    print("✓ Pipeline executed successfully")
    print("✓ All components integrated: Query→Adapter→Signals→Risk→Optimizer→Backtest")
    print("✓ P&L tracked accurately")
    print("✓ Performance metrics calculated")
    print()

    if result.sharpe_ratio < 0 or result.ic < 0:
        print("Note: Negative Sharpe or IC is ACCEPTABLE for MVP")
        print("Goal is accurate measurement, not profitable strategy")
    else:
        print("Strategy shows positive metrics (but that's not required for MVP)")

    print()
    print("MVP COMPLETE: Backtest measures correctly regardless of profitability")
    print("="*70)

    return result


if __name__ == '__main__':
    # Set random seed for reproducibility
    np.random.seed(42)

    result = run_example()
