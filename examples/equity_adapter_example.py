"""
Example: Using EquityAdapter to convert queries to DataFrames

This example demonstrates how to use EquityAdapter to:
1. Convert EquityQuery/ETFQuery objects to signal-ready DataFrames
2. Calculate returns from prices
3. Include sector and weight information
"""

from datetime import date
from Adapter.EquityAdapter import EquityAdapter
from Query.Equities.EquityQuery import EquityQuery
from Query.Equities.ETFQuery import ETFQuery
from Query.Equities.EquityStructure import EquityStructure
from Query.Equities.EquityValue import EquityValue


def main():
    """Example usage of EquityAdapter."""

    # Note: In production, you would use YahooFinanceMDP
    # from MDP.YahooFinanceMDP import YahooFinanceMDP
    # mdp = YahooFinanceMDP()

    # For this example, we'll show the structure with a mock MDP
    print("EquityAdapter Example")
    print("=" * 50)

    # Create queries for individual stocks
    stock_queries = [
        EquityQuery(
            ticker="AAPL",
            sector="Information Technology",
            structure=EquityStructure.SINGLE,
            value=EquityValue.RETURN,
            lookback_days=252,  # 1 year
            weight=1.0,
        ),
        EquityQuery(
            ticker="MSFT",
            sector="Information Technology",
            structure=EquityStructure.SINGLE,
            value=EquityValue.RETURN,
            lookback_days=252,
            weight=1.0,
        ),
        EquityQuery(
            ticker="JPM",
            sector="Financials",
            structure=EquityStructure.SINGLE,
            value=EquityValue.RETURN,
            lookback_days=252,
            weight=1.0,
        ),
    ]

    # Create query for sector ETF
    etf_query = ETFQuery(
        ticker="XLK",
        sector="Information Technology",
        value=EquityValue.RETURN,
        lookback_days=252,
        weight=-1.0,  # Short for hedging
    )

    print("\nCreated Queries:")
    print(f"  - {len(stock_queries)} stock queries")
    print(f"  - 1 ETF query")

    # In production, you would:
    # 1. Initialize adapter with YahooFinanceMDP
    # adapter = EquityAdapter(mdp)
    #
    # 2. Convert queries to DataFrame
    # as_of_date = date(2024, 12, 31)
    # df = adapter.convert(stock_queries + [etf_query], as_of_date)
    #
    # 3. Use the DataFrame with signals
    # print("\nOutput DataFrame Schema:")
    # print(df.columns)
    # >>> ['ticker', 'date', 'close', 'return', 'sector', 'weight']
    #
    # print("\nSample Data:")
    # print(df.head(10))
    # >>> shape: (10, 6)
    # >>> ┌────────┬────────────┬────────┬──────────┬──────────────────────────┬────────┐
    # >>> │ ticker │ date       │ close  │ return   │ sector                   │ weight │
    # >>> ├────────┼────────────┼────────┼──────────┼──────────────────────────┼────────┤
    # >>> │ AAPL   │ 2024-01-02 │ 185.64 │ null     │ Information Technology   │ 1.0    │
    # >>> │ AAPL   │ 2024-01-03 │ 184.25 │ -0.0075  │ Information Technology   │ 1.0    │
    # >>> │ AAPL   │ 2024-01-04 │ 181.91 │ -0.0127  │ Information Technology   │ 1.0    │
    # >>> │ ...    │ ...        │ ...    │ ...      │ ...                      │ ...    │
    # >>> └────────┴────────────┴────────┴──────────┴──────────────────────────┴────────┘

    print("\nExpected Output Schema:")
    print("  - ticker: str (e.g., 'AAPL', 'MSFT', 'XLK')")
    print("  - date: date (trading dates)")
    print("  - close: float (adjusted closing price)")
    print("  - return: float (simple return, null for first date)")
    print("  - sector: str (GICS Level 1 sector)")
    print("  - weight: float (portfolio weight from query)")

    print("\nUsage Notes:")
    print("  1. Adapter handles both EquityQuery and ETFQuery")
    print("  2. Returns are calculated automatically when value=RETURN")
    print("  3. First return is null (no prior price)")
    print("  4. Sector and weight come from query metadata")
    print("  5. Output is ready for ReturnsCalculator/SignalGenerator")


if __name__ == "__main__":
    main()
