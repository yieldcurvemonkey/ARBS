# ABOUTME: Query-based workflow example for unified backtest
# ABOUTME: Demonstrates using Backtest with MDP, adapter, and queries for futures trading

"""
Query-Based Workflow Example

Demonstrates the query-based workflow for the unified Backtest class.
This workflow is ideal for:
- Futures and swaps trading
- Real-time market data via adapters
- Query-driven data retrieval

Workflow:
1. Define queries (contracts to trade)
2. Create Market Data Provider (MDP)
3. Create adapter (Query → DataFrame bridge)
4. Configure backtest with signals
5. Run backtest via run() method
6. Analyze results

This example uses a simple mock MDP for demonstration.
In production, use real MDPs like IRSwapsMDP or futures data providers.
"""

import numpy as np
import polars as pl
from datetime import date, timedelta
from Backtest.Backtest import Backtest
from Adapter.FuturesAdapter import FuturesAdapter
from Signals.Futures.CarrySignal import CarrySignal
from Signals.Futures.MomentumSignal import MomentumSignal


# Mock Market Data Provider
class MockFuturesMDP:
    """
    Mock futures market data provider.

    Provides realistic futures prices with:
    - Carry structure (contango curve)
    - Time evolution
    - Multiple contract support
    """

    def __init__(self, base_rate: float = 5.0, carry_spread_bps: float = 10.0):
        """
        Initialize mock MDP.

        Args:
            base_rate: Base interest rate (%)
            carry_spread_bps: Carry spread between contracts (bps)
        """
        self.base_rate = base_rate
        self.carry_spread_bps = carry_spread_bps / 10000.0  # Convert bps to decimal

    def get_pricer(self, currency: str, as_of: date):
        """Return mock pricer."""
        return self

    def futures_price(self, contract: str) -> float:
        """
        Get futures price for contract.

        Args:
            contract: Contract code (e.g., 'SFRZ4')

        Returns:
            Futures price (IMM index: 100 - rate)
        """
        # Parse contract quarter
        if len(contract) < 4:
            return 100.0 - self.base_rate

        quarter_code = contract[-2]
        year_code = contract[-1]

        # Map quarter to position (0-3)
        quarter_map = {'H': 0, 'M': 1, 'U': 2, 'Z': 3}
        position = quarter_map.get(quarter_code, 0)

        # Calculate rate with carry
        rate = self.base_rate + (position * self.carry_spread_bps * 100)

        # Convert to IMM index
        price = 100.0 - rate

        # Add small noise
        noise = np.random.normal(0, 0.005)

        return price + noise


def example_single_signal_carry():
    """
    Example 1: Single signal (carry) query workflow.

    Uses CarrySignal to trade SOFR futures based on carry.
    """
    print("=" * 80)
    print("Example 1: Single Signal Carry Strategy (Query Workflow)")
    print("=" * 80)
    print()

    # Setup market data
    print("Setup:")
    print("- MDP: Mock futures data provider")
    print("- Adapter: FuturesAdapter (Query → DataFrame)")
    print("- Signal: CarrySignal (trade based on carry)")
    print("- Contracts: SOFR futures (SFRZ4, SFRH5, SFRM5, SFRU5)")
    print("- Period: 3 months, weekly rebalancing")
    print()

    # Create MDP
    mdp = MockFuturesMDP(base_rate=5.0, carry_spread_bps=10.0)

    # Create adapter
    adapter = FuturesAdapter(mdp)

    # Create backtest
    backtest = Backtest(
        mdp=mdp,
        adapter=adapter,
        signals=CarrySignal(),
        risk_aversion=1.0,
        long_only=True,
        min_history=4,  # Need 4 weeks before optimizing
    )

    # Define universe
    contracts = ['SFRZ4', 'SFRH5', 'SFRM5', 'SFRU5']

    # Define dates (weekly rebalancing)
    start_date = date(2024, 9, 1)
    end_date = date(2024, 12, 1)
    dates = pl.date_range(start_date, end_date, "1w", eager=True).to_list()
    dates = [d.date() if hasattr(d, 'date') else d for d in dates]

    print("Running backtest...")
    result = backtest.run(contracts=contracts, dates=dates)

    # Display results
    print()
    print("Results:")
    print("-" * 80)
    print(f"Sharpe Ratio:         {result.sharpe_ratio:>10.3f}")
    print(f"Information Coeff:    {result.ic:>10.3f}")
    print(f"Total Return:         {result.total_return:>10.2%}")
    print(f"Mean Return:          {result.returns.mean():>10.4%}")
    print(f"Std Deviation:        {result.returns.std():>10.4%}")
    print(f"Number of Periods:    {len(result.returns):>10}")
    print()

    # Show sample weights
    if len(result.weights) > 0:
        print("Sample Portfolio Weights (first rebalance):")
        first_row = result.weights[0]
        for col in result.weights.columns:
            if col == 'date':
                continue
            weight = first_row[col][0] if hasattr(first_row[col], '__getitem__') else first_row[col]
            if abs(weight) > 0.001:
                print(f"  {col:10s}: {weight:>8.2%}")
        print()

    return result


def example_multi_signal():
    """
    Example 2: Multi-signal query workflow.

    Combines CarrySignal and MomentumSignal.
    """
    print("=" * 80)
    print("Example 2: Multi-Signal Strategy (Query Workflow)")
    print("=" * 80)
    print()

    print("Setup:")
    print("- Signals: CarrySignal + MomentumSignal")
    print("- Combiner: Equal-weight combination")
    print("- Contracts: SOFR futures")
    print()

    # Create MDP
    mdp = MockFuturesMDP(base_rate=5.0, carry_spread_bps=10.0)

    # Create adapter
    adapter = FuturesAdapter(mdp)

    # Create backtest with multiple signals
    backtest = Backtest(
        mdp=mdp,
        adapter=adapter,
        signals=[
            CarrySignal(name='carry'),
            MomentumSignal(lookback_days=20, name='momentum')
        ],
        risk_aversion=1.5,
        long_only=True,
        min_history=5,
    )

    # Define universe
    contracts = ['SFRZ4', 'SFRH5', 'SFRM5']

    # Define dates
    start_date = date(2024, 9, 1)
    end_date = date(2024, 11, 1)
    dates = pl.date_range(start_date, end_date, "1w", eager=True).to_list()
    dates = [d.date() if hasattr(d, 'date') else d for d in dates]

    print("Running backtest...")
    result = backtest.run(contracts=contracts, dates=dates)

    # Display results
    print()
    print("Results:")
    print("-" * 80)
    print(f"Sharpe Ratio:         {result.sharpe_ratio:>10.3f}")
    print(f"Information Coeff:    {result.ic:>10.3f}")
    print(f"Total Return:         {result.total_return:>10.2%}")
    print(f"Number of Periods:    {len(result.returns):>10}")
    print()

    # Show signal contribution (both signals combined)
    print("Multi-Signal Configuration:")
    print(f"  Signal 1: carry (CarrySignal)")
    print(f"  Signal 2: momentum (MomentumSignal)")
    print(f"  Combiner: Equal-weight")
    print()

    return result


def example_custom_risk_parameters():
    """
    Example 3: Query workflow with custom risk parameters.

    Shows how to configure risk aversion and constraints.
    """
    print("=" * 80)
    print("Example 3: Custom Risk Parameters (Query Workflow)")
    print("=" * 80)
    print()

    print("Setup:")
    print("- Risk aversion: 3.0 (conservative)")
    print("- Constraint: Long-only")
    print("- Min history: 10 periods (more stable covariance)")
    print()

    # Create MDP
    mdp = MockFuturesMDP(base_rate=5.0, carry_spread_bps=10.0)

    # Create adapter
    adapter = FuturesAdapter(mdp)

    # Create backtest with custom parameters
    backtest = Backtest(
        mdp=mdp,
        adapter=adapter,
        signals=CarrySignal(),
        risk_aversion=3.0,  # More conservative
        long_only=True,
        min_history=10,  # More stable covariance estimate
        IC=0.10,  # Higher expected IC
    )

    # Define universe
    contracts = ['SFRZ4', 'SFRH5', 'SFRM5', 'SFRU5', 'SFRZ5']

    # Define dates
    start_date = date(2024, 6, 1)
    end_date = date(2024, 12, 1)
    dates = pl.date_range(start_date, end_date, "1w", eager=True).to_list()
    dates = [d.date() if hasattr(d, 'date') else d for d in dates]

    print("Running backtest...")
    result = backtest.run(contracts=contracts, dates=dates)

    # Display results
    print()
    print("Results:")
    print("-" * 80)
    print(f"Sharpe Ratio:         {result.sharpe_ratio:>10.3f}")
    print(f"Information Coeff:    {result.ic:>10.3f}")
    print(f"Total Return:         {result.total_return:>10.2%}")
    print(f"Number of Periods:    {len(result.returns):>10}")
    print()

    # Analyze risk characteristics
    if len(result.weights) > 0:
        print("Risk Characteristics:")

        # Portfolio concentration
        weights_array = []
        for row in result.weights.iter_rows(named=True):
            row_weights = [v for k, v in row.items() if k != 'date' and abs(v) > 0.001]
            if row_weights:
                weights_array.append(row_weights)

        if weights_array:
            mean_max_weight = np.mean([max(w) for w in weights_array])
            mean_num_positions = np.mean([len([x for x in w if abs(x) > 0.01]) for w in weights_array])

            print(f"  Average max position:  {mean_max_weight:>8.2%}")
            print(f"  Average # positions:   {mean_num_positions:>8.1f}")
        print()

    return result


def main():
    """Run all examples."""
    # Set random seed for reproducibility
    np.random.seed(42)

    print()
    print("Query-Based Workflow Examples")
    print("=" * 80)
    print()
    print("These examples demonstrate the query-based workflow for the")
    print("unified Backtest class. This workflow uses:")
    print("  1. Market Data Provider (MDP) - provides real-time/historical data")
    print("  2. Adapter - converts query results to DataFrame format")
    print("  3. Backtest.run() - executes backtest via query workflow")
    print()
    print("Press Ctrl+C to skip examples")
    print()

    try:
        # Example 1: Single signal
        result1 = example_single_signal_carry()

        input("\nPress Enter to continue to Example 2...")

        # Example 2: Multi-signal
        result2 = example_multi_signal()

        input("\nPress Enter to continue to Example 3...")

        # Example 3: Custom risk parameters
        result3 = example_custom_risk_parameters()

        # Summary
        print()
        print("=" * 80)
        print("Summary")
        print("=" * 80)
        print()
        print("All examples demonstrate the query-based workflow:")
        print("  ✓ MDP provides market data")
        print("  ✓ Adapter converts queries to DataFrame")
        print("  ✓ Signals generate alphas")
        print("  ✓ Backtest optimizes and tracks P&L")
        print()
        print("Key advantages of query workflow:")
        print("  - Real-time data via adapters")
        print("  - Flexible query-based data retrieval")
        print("  - Suitable for futures and swaps")
        print("  - Integrates with existing MDP infrastructure")
        print()
        print("=" * 80)

    except KeyboardInterrupt:
        print("\n\nExamples interrupted.")
        print()


if __name__ == '__main__':
    main()
