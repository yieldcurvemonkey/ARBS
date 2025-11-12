"""
Sector Rotation Strategy - Complete Example

Demonstrates the full pipeline from Yang & Shi (2023):
1. Load sector returns data
2. Calculate momentum and reversion factors
3. Generate signals with cross-sectional normalization
4. Construct long/short portfolio
5. Analyze performance

This example uses mock data. Replace with real data for production backtests.
"""

from datetime import date, timedelta
import numpy as np
import polars as pl

# Import sector rotation components
from Signals.SectorRotation.MomentumFactor import MomentumFactor
from Signals.SectorRotation.ReversionFactor import ReversionFactor
from Signals.SectorRotation.CrossSectionalNeutralizer import CrossSectionalNeutralizer
from Signals.SectorRotation.SectorMomentumSignal import SectorMomentumSignal
from Signals.SectorRotation.SectorReversionSignal import SectorReversionSignal
from Signals.SectorRotation.SectorLongShortPortfolio import SectorLongShortPortfolio


def generate_mock_sector_returns(n_days=200):
    """
    Generate mock daily returns for 11 GICS sectors.

    In production, replace this with real data from:
    - Query/Equities (for sector ETFs)
    - Adapter/EquityAdapter (for returns calculation)
    - Or external data provider (Bloomberg, FactSet, etc.)
    """
    # 11 GICS Level 1 sectors
    tickers = ["XLE", "XLB", "XLI", "XLY", "XLP", "XLV", "XLF", "XLK", "XLC", "XLU", "XLRE"]

    # Mock characteristics (different for each sector)
    sector_characteristics = {
        "XLE": {"drift": -0.0001, "vol": 0.02},    # Energy: volatile, underperforming
        "XLB": {"drift": 0.0001, "vol": 0.015},    # Materials: moderate
        "XLI": {"drift": 0.0002, "vol": 0.012},    # Industrials: steady growth
        "XLY": {"drift": 0.0003, "vol": 0.015},    # Consumer Discretionary: strong
        "XLP": {"drift": 0.0001, "vol": 0.008},    # Consumer Staples: defensive
        "XLV": {"drift": 0.0002, "vol": 0.010},    # Health Care: steady
        "XLF": {"drift": 0.0002, "vol": 0.018},    # Financials: moderate vol
        "XLK": {"drift": 0.0005, "vol": 0.020},    # Technology: high growth
        "XLC": {"drift": 0.0003, "vol": 0.014},    # Communication: moderate
        "XLU": {"drift": 0.0001, "vol": 0.009},    # Utilities: defensive
        "XLRE": {"drift": 0.0002, "vol": 0.011},   # Real Estate: moderate
    }

    # Generate dates
    start_date = date(2022, 1, 1)
    dates = [start_date + timedelta(days=i) for i in range(n_days)]

    # Generate returns for each sector
    all_returns = []
    for ticker in tickers:
        char = sector_characteristics[ticker]
        np.random.seed(hash(ticker) % 10000)  # Reproducible but different per sector

        # Generate returns: drift + noise
        returns = char["drift"] + char["vol"] * np.random.randn(n_days)

        sector_df = pl.DataFrame({
            "ticker": [ticker] * n_days,
            "date": dates,
            "return": returns
        })
        all_returns.append(sector_df)

    # Combine all sectors
    combined_df = pl.concat(all_returns)
    return combined_df


def run_momentum_strategy_example():
    """Example: Momentum-only strategy (MOM_7M)."""
    print("\n" + "=" * 70)
    print("EXAMPLE 1: Momentum-Only Strategy (MOM_7M)")
    print("=" * 70)

    # 1. Generate mock data
    print("\n1. Generating mock sector returns data...")
    returns_df = generate_mock_sector_returns(n_days=200)
    tickers = returns_df["ticker"].unique().sort().to_list()
    target_date = returns_df["date"].max()
    print(f"   - Generated {len(returns_df)} return observations")
    print(f"   - Sectors: {', '.join(tickers)}")
    print(f"   - Target date: {target_date}")

    # 2. Create momentum signal
    print("\n2. Creating momentum signal (MOM_7M)...")
    signal = SectorMomentumSignal(
        lookback_months=7,  # Paper's optimal configuration
        exclusion_pct=0.10,  # Exclude recent 10%
        standardize=True     # Z-score standardization
    )
    print(f"   - Lookback: 7 months (147 trading days)")
    print(f"   - Exclusion: 10% (15 days)")

    # 3. Generate signals for all sectors
    print("\n3. Generating signals for all sectors...")
    sectors_data = []
    for ticker in tickers:
        sector_returns = returns_df.filter(pl.col("ticker") == ticker)
        sectors_data.append(sector_returns)

    z_scores = signal.generate_batch(
        inst_data_list=sectors_data,
        market_data=None,
        as_of=target_date
    )
    print(f"   - Generated {len(z_scores)} z-scores")
    print(f"   - Mean: {np.mean(z_scores):.6f} (should be ~0)")
    print(f"   - Std: {np.std(z_scores, ddof=1):.6f} (should be ~1)")

    # Display signals
    print("\n   Sector Rankings (by momentum z-score):")
    signals_df = pl.DataFrame({
        "ticker": tickers,
        "z_score": z_scores
    }).sort("z_score", descending=True)

    for row in signals_df.iter_rows(named=True):
        print(f"   {row['ticker']:6s}: {row['z_score']:+.3f}")

    # 4. Construct portfolio
    print("\n4. Constructing long/short portfolio...")
    portfolio = SectorLongShortPortfolio(n_long=3, n_short=3)
    weights = portfolio.construct_weights(tickers, z_scores)

    print("   - Long top 3 sectors (highest momentum)")
    print("   - Short bottom 3 sectors (lowest momentum)")
    print("   - Equal-weighted within buckets")

    # Display portfolio
    print("\n   Portfolio Weights:")
    weights_df = portfolio.weights_to_dataframe(weights).sort("weight", descending=True)

    for row in weights_df.iter_rows(named=True):
        position = "LONG" if row["weight"] > 0 else ("SHORT" if row["weight"] < 0 else "ZERO")
        print(f"   {row['ticker']:6s}: {row['weight']:+.4f} ({position})")

    # Portfolio statistics
    stats = portfolio.get_portfolio_statistics(weights)
    print(f"\n   Portfolio Statistics:")
    print(f"   - Total long:      {stats['total_long']:.4f}")
    print(f"   - Total short:     {stats['total_short']:.4f}")
    print(f"   - Net exposure:    {stats['net_exposure']:.6f} (dollar-neutral)")
    print(f"   - Gross exposure:  {stats['gross_exposure']:.4f}")

    print("\n✓ Momentum strategy example complete!")
    return weights


def run_reversion_strategy_example():
    """Example: Reversion-only strategy (REV_30D)."""
    print("\n" + "=" * 70)
    print("EXAMPLE 2: Reversion-Only Strategy (REV_30D)")
    print("=" * 70)

    # 1. Generate mock data
    print("\n1. Generating mock sector returns data...")
    returns_df = generate_mock_sector_returns(n_days=60)
    tickers = returns_df["ticker"].unique().sort().to_list()
    target_date = returns_df["date"].max()

    # 2. Create reversion signal
    print("\n2. Creating reversion signal (REV_30D)...")
    signal = SectorReversionSignal(
        lookback_days=30,  # Paper's optimal configuration
        standardize=True
    )
    print(f"   - Lookback: 30 days (contrarian)")

    # 3. Generate signals
    print("\n3. Generating signals for all sectors...")
    sectors_data = []
    for ticker in tickers:
        sector_returns = returns_df.filter(pl.col("ticker") == ticker)
        sectors_data.append(sector_returns)

    z_scores = signal.generate_batch(
        inst_data_list=sectors_data,
        market_data=None,
        as_of=target_date
    )

    # Display signals
    print("\n   Sector Rankings (by reversion z-score):")
    signals_df = pl.DataFrame({
        "ticker": tickers,
        "z_score": z_scores
    }).sort("z_score", descending=True)

    for row in signals_df.iter_rows(named=True):
        signal_interpretation = "BUY (oversold)" if row["z_score"] > 0 else "SELL (overbought)"
        print(f"   {row['ticker']:6s}: {row['z_score']:+.3f} ({signal_interpretation})")

    # 4. Construct portfolio
    print("\n4. Constructing long/short portfolio (contrarian)...")
    portfolio = SectorLongShortPortfolio(n_long=3, n_short=3)
    weights = portfolio.construct_weights(tickers, z_scores)

    print("   - Long most oversold (highest reversion signal)")
    print("   - Short most overbought (lowest reversion signal)")

    # Display portfolio
    print("\n   Portfolio Weights:")
    weights_df = portfolio.weights_to_dataframe(weights).sort("weight", descending=True)

    for row in weights_df.iter_rows(named=True):
        position = "LONG" if row["weight"] > 0 else ("SHORT" if row["weight"] < 0 else "ZERO")
        print(f"   {row['ticker']:6s}: {row['weight']:+.4f} ({position})")

    print("\n✓ Reversion strategy example complete!")
    return weights


def run_combined_strategy_example():
    """Example: Combined momentum + reversion strategy."""
    print("\n" + "=" * 70)
    print("EXAMPLE 3: Combined Strategy (Momentum + Reversion)")
    print("=" * 70)

    # 1. Generate mock data
    print("\n1. Generating mock sector returns data...")
    returns_df = generate_mock_sector_returns(n_days=200)
    tickers = returns_df["ticker"].unique().sort().to_list()
    target_date = returns_df["date"].max()

    # 2. Generate momentum signals
    print("\n2. Generating momentum signals...")
    mom_signal = SectorMomentumSignal(lookback_months=7)
    sectors_data = [returns_df.filter(pl.col("ticker") == t) for t in tickers]
    mom_z_scores = mom_signal.generate_batch(sectors_data, None, target_date)

    # 3. Generate reversion signals
    print("3. Generating reversion signals...")
    rev_signal = SectorReversionSignal(lookback_days=30)
    rev_z_scores = rev_signal.generate_batch(sectors_data, None, target_date)

    # 4. Combine signals (equal weighting)
    print("4. Combining signals (50% momentum, 50% reversion)...")
    combined_z_scores = 0.5 * mom_z_scores + 0.5 * rev_z_scores

    # Re-standardize combined signals
    combined_z_scores = (combined_z_scores - np.mean(combined_z_scores)) / np.std(combined_z_scores, ddof=1)

    # Display combined signals
    print("\n   Combined Sector Rankings:")
    signals_df = pl.DataFrame({
        "ticker": tickers,
        "momentum": mom_z_scores,
        "reversion": rev_z_scores,
        "combined": combined_z_scores
    }).sort("combined", descending=True)

    print(f"   {'Ticker':<8} {'Momentum':<10} {'Reversion':<10} {'Combined':<10}")
    print(f"   {'-'*8} {'-'*10} {'-'*10} {'-'*10}")
    for row in signals_df.iter_rows(named=True):
        print(f"   {row['ticker']:<8} {row['momentum']:+.3f}      {row['reversion']:+.3f}      {row['combined']:+.3f}")

    # 5. Construct portfolio
    print("\n5. Constructing portfolio from combined signals...")
    portfolio = SectorLongShortPortfolio(n_long=3, n_short=3)
    weights = portfolio.construct_weights(tickers, combined_z_scores)

    # Display portfolio
    print("\n   Final Portfolio Weights:")
    weights_df = portfolio.weights_to_dataframe(weights).sort("weight", descending=True)

    for row in weights_df.iter_rows(named=True):
        position = "LONG" if row["weight"] > 0 else ("SHORT" if row["weight"] < 0 else "ZERO")
        print(f"   {row['ticker']:6s}: {row['weight']:+.4f} ({position})")

    print("\n✓ Combined strategy example complete!")
    return weights


def main():
    """Run all examples."""
    print("\n" + "=" * 70)
    print("SECTOR ROTATION STRATEGY - COMPLETE EXAMPLES")
    print("Based on Yang & Shi (2023)")
    print("=" * 70)

    # Run all three examples
    run_momentum_strategy_example()
    run_reversion_strategy_example()
    run_combined_strategy_example()

    print("\n" + "=" * 70)
    print("ALL EXAMPLES COMPLETE")
    print("=" * 70)
    print("\nNext Steps:")
    print("1. Replace mock data with real sector returns (Query/Equities)")
    print("2. Add fundamental signals (FundamentalProcessor + FundamentalSignal)")
    print("3. Implement backtest with performance metrics (TearSheet)")
    print("4. Validate Sharpe ratios vs paper benchmarks")
    print("\nPaper Targets:")
    print("- MOM_7M: Sharpe 0.62 (2017-2022)")
    print("- REV_30D: Sharpe 0.87 (2002-2022)")
    print("- Combined: Sharpe 2.21 (Sept 2020-Sept 2021)")


if __name__ == "__main__":
    main()
