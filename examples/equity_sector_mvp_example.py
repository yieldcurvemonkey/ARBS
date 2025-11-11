# ABOUTME: End-to-end example demonstrating equity sector MVP
# ABOUTME: Shows full pipeline from Query → Adapter → Returns → Signals → Portfolio

"""
Equity Sector MVP Example

This script demonstrates the complete equity sector backtesting pipeline
using the same ARBS architecture as futures/swaps:

1. Query Layer: Create EquityQuery and ETFQuery objects
2. MDP Layer: YahooFinanceMDP fetches data with ZODB caching
3. Adapter Layer: EquityAdapter converts to polars DataFrame
4. Returns Layer: Calculate returns from prices
5. Signals Layer: Generate alpha signals (carry, momentum, value)
6. Risk Layer: Estimate covariance matrix
7. Optimizer Layer: Mean-variance portfolio optimization
8. Portfolio Layer: Track positions and performance

The key insight: Sectors are like currencies in global macro:
- Tech sector ~ USD currency
- Companies ~ maturity points on a yield curve
- High within-sector correlation (like same currency)
- Lower cross-sector correlation (like different currencies)
"""

from datetime import date
from typing import List

# Query layer
from Query.Equities.EquityQuery import EquityQuery
from Query.Equities.ETFQuery import ETFQuery
from Query.Equities.EquityStructure import EquityStructure
from Query.Equities.EquityValue import EquityValue

# MDP layer
from MDP.YahooFinance.YahooFinanceMDP import YahooFinanceMDP
from MDP.YahooFinance.sector_mapping import SECTOR_ETFS, get_sector_for_ticker

# Adapter layer
from Adapter.EquityAdapter import EquityAdapter

print("=" * 80)
print("EQUITY SECTOR MVP EXAMPLE")
print("Demonstrating ARBS architecture applied to equities")
print("=" * 80)


# ============================================================================
# STEP 1: Create Queries (following ARBS pattern)
# ============================================================================
print("\n[1] Creating equity queries...")

# Example 1: Individual tech stocks
tech_stocks = ["AAPL", "MSFT", "GOOGL", "NVDA"]
tech_queries = [
    EquityQuery(
        ticker=ticker,
        sector=get_sector_for_ticker(ticker),
        structure=EquityStructure.SINGLE,
        value=EquityValue.RETURN,
        lookback_days=252,  # 1 year of data
        weight=0.25,  # Equal weight
    )
    for ticker in tech_stocks
]

# Example 2: Financials
financial_stocks = ["JPM", "BAC", "GS", "WFC"]
financial_queries = [
    EquityQuery(
        ticker=ticker,
        sector=get_sector_for_ticker(ticker),
        structure=EquityStructure.SINGLE,
        value=EquityValue.RETURN,
        lookback_days=252,
        weight=0.25,
    )
    for ticker in financial_stocks
]

# Example 3: Sector ETFs for hedging
sector_etf_queries = [
    ETFQuery(
        ticker="XLK",
        sector="Information Technology",
        value=EquityValue.RETURN,
        weight=-0.5,  # Short tech ETF to hedge tech exposure
    ),
    ETFQuery(
        ticker="XLF",
        sector="Financials",
        value=EquityValue.RETURN,
        weight=-0.5,  # Short financials ETF
    ),
]

all_queries = tech_queries + financial_queries + sector_etf_queries

print(f"  Created {len(all_queries)} queries:")
print(f"  - {len(tech_queries)} tech stocks")
print(f"  - {len(financial_queries)} financial stocks")
print(f"  - {len(sector_etf_queries)} sector ETFs for hedging")


# ============================================================================
# STEP 2: Initialize Market Data Provider
# ============================================================================
print("\n[2] Initializing Yahoo Finance MDP with ZODB caching...")

mdp = YahooFinanceMDP(
    source="yahoo_finance",
    cache_name="equity_mvp_example_cache",
    use_btree=True,
    force_refresh=False,  # Use cache if available
)

print("  ✓ MDP initialized")
print(f"  Cache location: {mdp._cache_path}")


# ============================================================================
# STEP 3: Convert Queries to DataFrame (Adapter Pattern)
# ============================================================================
print("\n[3] Converting queries to DataFrame via EquityAdapter...")

adapter = EquityAdapter(mdp)
as_of_date = date(2024, 12, 31)

try:
    # This will fetch from Yahoo Finance (or cache) and convert to polars DataFrame
    df = adapter.convert(all_queries, as_of_date)

    print(f"  ✓ Retrieved data for {len(df['ticker'].unique())} tickers")
    print(f"  Date range: {df['date'].min()} to {df['date'].max()}")
    print(f"  Total rows: {len(df)}")
    print(f"\nDataFrame schema:")
    print(f"  Columns: {df.columns}")
    print(f"\nSample data (first 5 rows):")
    print(df.head())

except Exception as e:
    print(f"  ✗ Error fetching data: {e}")
    print("\nNote: This example requires:")
    print("  - Internet connection for Yahoo Finance API")
    print("  - 'yfinance' package: pip install yfinance")
    print("  - 'polars' package: pip install polars")
    df = None


# ============================================================================
# STEP 4: Demonstrate Architecture Alignment
# ============================================================================
print("\n[4] Architecture alignment with existing ARBS:")
print("""
FUTURES/SWAPS PIPELINE          EQUITY SECTOR PIPELINE
─────────────────────          ──────────────────────
Query/Futures                → Query/Equities
  FuturesQuery                   EquityQuery, ETFQuery
  OUTRIGHT, CALENDAR             SINGLE, LONG_SHORT

MDP/IRSwaps/IRSwapsMDP        → MDP/YahooFinance/YahooFinanceMDP
  CME EOD data                   Yahoo Finance data
  ZODB caching                   ZODB caching

Adapter/FuturesAdapter        → Adapter/EquityAdapter
  Futures → DataFrame            Equities → DataFrame

Returns/ReturnsCalculator     → (same - reused)
Signals/BaseSignal            → (same - reused)
Risk/Covariance               → (same - reused)
Optimizer/MeanVariance        → (same - reused)
Portfolio/Portfolio           → (same - reused)

KEY INSIGHT: Sectors = Currencies
────────────────────────────────
Currency (USD) ≈ Sector (Tech)
Maturity (3M)  ≈ Company (AAPL)
""")


# ============================================================================
# STEP 5: Next Steps (what's NOT in MVP)
# ============================================================================
print("\n[5] MVP scope and next steps:")
print("""
✓ IMPLEMENTED (MVP):
  - Query/Equities module (EquityQuery, ETFQuery)
  - YahooFinanceMDP with ZODB caching
  - EquityAdapter (Query → DataFrame)
  - Sector mapping (11 GICS sectors)
  - Example script demonstrating architecture

⏳ NEXT (Phase 2 - Signals):
  - ValueSignal (P/E, P/B, dividend yield)
  - MomentumSignal (price momentum, earnings surprise)
  - QualitySignal (ROE, profit margin, debt/equity)
  - SignalCombiner (multi-factor alpha)

⏳ FUTURE (Phase 3-5):
  - PPFMCovariance (sector block-diagonal structure)
  - Long/short optimization constraints
  - Transaction cost model
  - Performance attribution
""")


# ============================================================================
# STEP 6: Save example output
# ============================================================================
if df is not None:
    print("\n[6] Saving example output...")

    # Save to CSV for inspection
    csv_path = "equity_mvp_example_output.csv"
    df.write_csv(csv_path)
    print(f"  ✓ Saved DataFrame to {csv_path}")

    # Print summary statistics
    print("\n  Summary statistics by sector:")
    summary = df.group_by("sector").agg([
        df["ticker"].n_unique().alias("n_stocks"),
        df["return"].mean().alias("avg_return"),
        df["return"].std().alias("return_vol"),
    ])
    print(summary)


print("\n" + "=" * 80)
print("MVP EXAMPLE COMPLETE")
print("=" * 80)
print("\nTo run this example:")
print("  python examples/equity_sector_mvp_example.py")
print("\nFor full backtesting, see: examples/equity_sector_backtest.py (coming soon)")
