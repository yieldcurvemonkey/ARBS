# ABOUTME: Hybrid workflow example combining query and DataFrame approaches
# ABOUTME: Demonstrates flexible data sourcing and signal generation across workflows

"""
Hybrid Workflow Example

Demonstrates hybrid workflows that combine query-based and DataFrame-based approaches.
This is useful for:
- Multi-asset strategies (futures + equities)
- Combining real-time (query) and batch (DataFrame) data
- Testing signal portability across data sources

Hybrid Patterns:
1. Query → DataFrame → Signals (convert query data to DataFrame workflow)
2. Mixed signals (some from queries, some from DataFrames)
3. Sequential workflows (query data, then DataFrame processing)

Key Insight:
Both workflows use the same signal interface, making signals portable
across data sources.
"""

import numpy as np
import polars as pl
from datetime import date, timedelta
from typing import List, Dict

from Backtest.Backtest import Backtest
from Adapter.FuturesAdapter import FuturesAdapter
from Signals.Futures.CarrySignal import CarrySignal
from Signals.Futures.MomentumSignal import MomentumSignal


# Mock Market Data Provider
class MockFuturesMDP:
    """Mock futures MDP."""

    def __init__(self, base_rate: float = 5.0):
        self.base_rate = base_rate

    def get_pricer(self, currency: str, as_of: date):
        return self

    def futures_price(self, contract: str) -> float:
        """Return synthetic futures price."""
        base = 95.0
        if len(contract) >= 4:
            quarter_map = {'H': 0, 'M': 1, 'U': 2, 'Z': 3}
            position = quarter_map.get(contract[-2], 0)
            carry = position * 0.05
            price = base + carry
        else:
            price = base
        noise = np.random.normal(0, 0.01)
        return price + noise


class QueryToDataFrameConverter:
    """
    Converter that bridges query-based data to DataFrame workflow.

    This demonstrates how to convert query results to DataFrame format
    for use with DataFrame-based signals.
    """

    def __init__(self, mdp, adapter):
        """
        Initialize converter.

        Args:
            mdp: Market data provider
            adapter: Adapter for query conversion
        """
        self.mdp = mdp
        self.adapter = adapter
        self.price_history: Dict[str, List[float]] = {}
        self.date_history: List[date] = []

    def query_to_returns(self, queries, as_of: date) -> pl.DataFrame:
        """
        Convert query results to returns DataFrame.

        Args:
            queries: List of queries to execute
            as_of: Date for query evaluation

        Returns:
            DataFrame with columns: [date, ticker, return]
        """
        # Get prices via adapter
        df = self.adapter.convert(queries, as_of)

        returns_data = []

        if isinstance(df, pl.DataFrame):
            for row in df.iter_rows(named=True):
                contract = row['contract']
                price = row['price']

                # Calculate return if we have history
                if contract in self.price_history and len(self.price_history[contract]) > 0:
                    prev_price = self.price_history[contract][-1]
                    ret = (price - prev_price) / prev_price
                else:
                    ret = 0.0

                # Update history
                if contract not in self.price_history:
                    self.price_history[contract] = []
                self.price_history[contract].append(price)

                returns_data.append({
                    'date': as_of,
                    'ticker': contract,
                    'return': ret
                })

        self.date_history.append(as_of)

        return pl.DataFrame(returns_data)


def example_query_to_dataframe_conversion():
    """
    Example 1: Convert query data to DataFrame workflow.

    Shows how to bridge query-based data retrieval with
    DataFrame-based signal processing.
    """
    print("=" * 80)
    print("Example 1: Query → DataFrame Conversion (Hybrid Workflow)")
    print("=" * 80)
    print()

    print("Workflow:")
    print("  1. Use queries to get futures prices (query-based)")
    print("  2. Convert to returns DataFrame")
    print("  3. Run signals on DataFrame (DataFrame-based)")
    print("  4. Combine best of both approaches")
    print()

    # Create MDP and adapter
    mdp = MockFuturesMDP(base_rate=5.0)
    adapter = FuturesAdapter(mdp)

    # Create converter
    converter = QueryToDataFrameConverter(mdp, adapter)

    # Define queries
    from Query.Futures.FuturesQuery import FuturesQuery
    from Query.Futures.FuturesStructure import FuturesStructure

    contracts = ['SFRZ4', 'SFRH5', 'SFRM5']
    queries = [
        FuturesQuery(structure=FuturesStructure.OUTRIGHT, contract=c)
        for c in contracts
    ]

    # Generate returns over time
    start_date = date(2024, 9, 1)
    dates = [start_date + timedelta(weeks=i) for i in range(15)]

    all_returns = []
    for d in dates:
        returns_df = converter.query_to_returns(queries, d)
        all_returns.append(returns_df)

    # Combine into single DataFrame
    combined_returns = pl.concat(all_returns)

    print(f"Generated {len(combined_returns)} return observations")
    print(f"Covering {len(dates)} periods")
    print()

    # Now use DataFrame workflow
    backtest = Backtest(
        signals=MomentumSignal(lookback_days=20),
        risk_aversion=1.0,
        long_only=True,
        min_history=5,
    )

    result = backtest.run_from_dataframe(combined_returns, dates[5:])  # Skip warmup

    print("Results (DataFrame workflow on query-sourced data):")
    print("-" * 80)
    print(f"Sharpe Ratio:         {result.sharpe_ratio:>10.3f}")
    print(f"Information Coeff:    {result.ic:>10.3f}")
    print(f"Total Return:         {result.total_return:>10.2%}")
    print(f"Number of Periods:    {len(result.returns):>10}")
    print()

    print("Key Insight:")
    print("  ✓ Query-based data retrieval (flexible, real-time)")
    print("  ✓ DataFrame-based signal processing (efficient, vectorized)")
    print("  ✓ Best of both worlds!")
    print()

    return result


def example_multi_asset_strategy():
    """
    Example 2: Multi-asset strategy combining futures and equities.

    Demonstrates running separate backtests on different asset classes
    and combining results.
    """
    print("=" * 80)
    print("Example 2: Multi-Asset Strategy (Hybrid Workflow)")
    print("=" * 80)
    print()

    print("Strategy:")
    print("  - Futures: Trade SOFR futures with carry signal")
    print("  - Equities: Trade stocks with momentum signal")
    print("  - Combine: Weight based on Sharpe ratios")
    print()

    # Futures backtest (query workflow)
    print("Running futures backtest (query workflow)...")
    mdp = MockFuturesMDP(base_rate=5.0)
    adapter = FuturesAdapter(mdp)

    futures_backtest = Backtest(
        mdp=mdp,
        adapter=adapter,
        signals=CarrySignal(),
        risk_aversion=1.0,
        long_only=True,
        min_history=5,
    )

    futures_contracts = ['SFRZ4', 'SFRH5', 'SFRM5']
    dates = [date(2024, 9, 1) + timedelta(weeks=i) for i in range(12)]

    futures_result = futures_backtest.run(futures_contracts, dates)

    # Equities backtest (DataFrame workflow)
    print("Running equities backtest (DataFrame workflow)...")

    # Generate synthetic equity returns
    tickers = ['AAPL', 'MSFT', 'GOOGL']
    equity_returns_data = []
    np.random.seed(42)

    for d in dates:
        for ticker in tickers:
            equity_returns_data.append({
                'date': d,
                'ticker': ticker,
                'return': np.random.normal(0.002, 0.02)  # 20bps mean, 2% vol
            })

    equity_returns_df = pl.DataFrame(equity_returns_data)

    equity_backtest = Backtest(
        signals=MomentumSignal(lookback_days=20),
        risk_aversion=1.5,
        long_only=True,
        min_history=5,
    )

    equity_result = equity_backtest.run_from_dataframe(equity_returns_df, dates)

    # Display results
    print()
    print("Results:")
    print("=" * 80)
    print()
    print("Futures Portfolio (Query Workflow):")
    print(f"  Sharpe Ratio:      {futures_result.sharpe_ratio:>10.3f}")
    print(f"  Total Return:      {futures_result.total_return:>10.2%}")
    print(f"  IC:                {futures_result.ic:>10.3f}")
    print()

    print("Equity Portfolio (DataFrame Workflow):")
    print(f"  Sharpe Ratio:      {equity_result.sharpe_ratio:>10.3f}")
    print(f"  Total Return:      {equity_result.total_return:>10.2%}")
    print(f"  IC:                {equity_result.ic:>10.3f}")
    print()

    # Calculate combined portfolio (simple equal weight for demo)
    if len(futures_result.returns) > 0 and len(equity_result.returns) > 0:
        min_len = min(len(futures_result.returns), len(equity_result.returns))
        futures_rets = futures_result.returns[:min_len].to_numpy()
        equity_rets = equity_result.returns[:min_len].to_numpy()

        combined_rets = 0.5 * futures_rets + 0.5 * equity_rets
        combined_sharpe = (np.mean(combined_rets) / np.std(combined_rets)) * np.sqrt(52)
        combined_return = np.prod(1 + combined_rets) - 1

        print("Combined Portfolio (50% Futures / 50% Equity):")
        print(f"  Sharpe Ratio:      {combined_sharpe:>10.3f}")
        print(f"  Total Return:      {combined_return:>10.2%}")
        print()

    print("Key Insight:")
    print("  ✓ Different workflows for different asset classes")
    print("  ✓ Query workflow for futures (real-time pricing)")
    print("  ✓ DataFrame workflow for equities (batch returns)")
    print("  ✓ Combine at portfolio level")
    print()

    return futures_result, equity_result


def example_signal_portability():
    """
    Example 3: Signal portability across workflows.

    Demonstrates that the same signal can work with both
    query-based and DataFrame-based data.
    """
    print("=" * 80)
    print("Example 3: Signal Portability (Hybrid Workflow)")
    print("=" * 80)
    print()

    print("Concept:")
    print("  Signals are agnostic to data source")
    print("  Same MomentumSignal works with:")
    print("    - Query workflow (futures)")
    print("    - DataFrame workflow (equities)")
    print()

    # Test 1: MomentumSignal with query workflow
    print("Test 1: MomentumSignal + Query Workflow")
    mdp = MockFuturesMDP(base_rate=5.0)
    adapter = FuturesAdapter(mdp)

    query_backtest = Backtest(
        mdp=mdp,
        adapter=adapter,
        signals=MomentumSignal(lookback_days=20, name='momentum'),
        risk_aversion=1.0,
        long_only=True,
        min_history=5,
    )

    contracts = ['SFRZ4', 'SFRH5']
    dates = [date(2024, 9, 1) + timedelta(weeks=i) for i in range(10)]

    query_result = query_backtest.run(contracts, dates)

    print(f"  Result: Sharpe = {query_result.sharpe_ratio:.3f}, Return = {query_result.total_return:.2%}")
    print()

    # Test 2: MomentumSignal with DataFrame workflow
    print("Test 2: MomentumSignal + DataFrame Workflow")

    # Generate synthetic returns
    returns_data = []
    np.random.seed(42)
    for d in dates:
        for ticker in ['AAPL', 'MSFT']:
            returns_data.append({
                'date': d,
                'ticker': ticker,
                'return': np.random.normal(0.001, 0.02)
            })

    returns_df = pl.DataFrame(returns_data)

    df_backtest = Backtest(
        signals=MomentumSignal(lookback_days=20, name='momentum'),
        risk_aversion=1.0,
        long_only=True,
        min_history=5,
    )

    df_result = df_backtest.run_from_dataframe(returns_df, dates)

    print(f"  Result: Sharpe = {df_result.sharpe_ratio:.3f}, Return = {df_result.total_return:.2%}")
    print()

    print("Key Insight:")
    print("  ✓ Same signal implementation")
    print("  ✓ Works with both workflows")
    print("  ✓ Signal logic independent of data source")
    print("  ✓ Maximizes code reuse")
    print()

    return query_result, df_result


def main():
    """Run all hybrid workflow examples."""
    np.random.seed(42)

    print()
    print("Hybrid Workflow Examples")
    print("=" * 80)
    print()
    print("These examples demonstrate hybrid workflows that combine")
    print("query-based and DataFrame-based approaches.")
    print()
    print("Key Benefits:")
    print("  - Flexibility: Use best data source for each asset class")
    print("  - Portability: Signals work across workflows")
    print("  - Integration: Combine different data pipelines")
    print()
    print("Press Ctrl+C to skip examples")
    print()

    try:
        # Example 1: Query to DataFrame conversion
        result1 = example_query_to_dataframe_conversion()

        input("\nPress Enter to continue to Example 2...")

        # Example 2: Multi-asset strategy
        futures_result, equity_result = example_multi_asset_strategy()

        input("\nPress Enter to continue to Example 3...")

        # Example 3: Signal portability
        query_result, df_result = example_signal_portability()

        # Summary
        print()
        print("=" * 80)
        print("Summary")
        print("=" * 80)
        print()
        print("Hybrid workflows provide maximum flexibility:")
        print()
        print("1. Query → DataFrame Conversion")
        print("   - Use queries for data retrieval")
        print("   - Process with DataFrame signals")
        print("   - Best of both worlds")
        print()
        print("2. Multi-Asset Strategies")
        print("   - Different workflows for different assets")
        print("   - Futures via queries (real-time pricing)")
        print("   - Equities via DataFrame (batch returns)")
        print("   - Combine at portfolio level")
        print()
        print("3. Signal Portability")
        print("   - Same signal code works everywhere")
        print("   - Maximizes code reuse")
        print("   - Simplifies testing and validation")
        print()
        print("The unified Backtest class supports all patterns!")
        print("=" * 80)

    except KeyboardInterrupt:
        print("\n\nExamples interrupted.")
        print()


if __name__ == '__main__':
    main()
