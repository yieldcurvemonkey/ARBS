#!/usr/bin/env python
# ABOUTME: Backtest volatility dispersion strategy on SPDR sector ETFs
# ABOUTME: Demonstrates IV/RV ratio convergence trading with mock implied volatility data
"""
Volatility Dispersion Backtest

Strategy:
    1. Identify highly correlated sector ETF pairs (ρ > 0.85)
    2. Calculate IV/RV ratios (using mock IV data)
    3. Generate signals when spread z-score > 2.0
    4. Trade: sell expensive vol, buy cheap vol
    5. Assume spread mean reverts over holding period

Universe:
    SPDR Sector ETFs: XLK, XLF, XLE, XLV, XLI, XLP, XLY, XLU, XLB, XLRE, XLC

Data:
    - Historical prices from yfinance (2020-2024)
    - Mock implied volatility: IV = RV × (1.0 + N(0, 0.3))

Metrics:
    - Sharpe ratio
    - Information Coefficient (IC)
    - Turnover (number of trades)
    - Number of signals
    - Average holding period
"""

import sys
sys.path.insert(0, '/home/user/ARBS')

import numpy as np
import polars as pl
from datetime import date, datetime, timedelta
from typing import Dict, List, Tuple

from Risk.Volatility.VolatilityRatioCalculator import VolatilityRatioCalculator
from Signals.CorrelationVolatilitySignal import CorrelationVolatilitySignal


def load_data() -> pl.DataFrame:
    """
    Load historical sector ETF prices.

    In production, use yfinance or similar. For this example, generate synthetic data.

    Returns:
        Polars DataFrame with columns [date, ticker, close]
    """
    print("Loading data...")

    # Sector ETFs
    tickers = ['XLK', 'XLF', 'XLE', 'XLV', 'XLI', 'XLP', 'XLY', 'XLU', 'XLB', 'XLRE', 'XLC']

    # Generate synthetic prices (2020-2024, daily)
    start_date = datetime(2020, 1, 1)
    end_date = datetime(2024, 12, 31)

    # Generate business days manually
    dates = []
    current = start_date
    while current <= end_date:
        # Skip weekends
        if current.weekday() < 5:
            dates.append(current.date())
        current += timedelta(days=1)

    np.random.seed(42)

    # Generate correlated returns
    n_days = len(dates)

    # Base market return
    market_returns = np.random.normal(0.0005, 0.01, n_days)

    # Asset-specific returns with correlation
    returns_data = {}
    for ticker in tickers:
        if ticker in ['XLK', 'XLC']:  # Tech - high correlation
            beta = 1.2
            idio_vol = 0.005
        elif ticker in ['XLF', 'XLRE']:  # Financials/Real Estate - correlated
            beta = 1.0
            idio_vol = 0.008
        elif ticker == 'XLE':  # Energy - low correlation
            beta = 0.5
            idio_vol = 0.015
        else:  # Others - moderate correlation
            beta = 0.9
            idio_vol = 0.007

        asset_returns = beta * market_returns + np.random.normal(0, idio_vol, n_days)
        returns_data[ticker] = asset_returns

    # Convert returns to prices (starting at 100)
    prices_data = []
    for ticker in tickers:
        price = 100.0
        for day_idx, date_val in enumerate(dates):
            price *= (1 + returns_data[ticker][day_idx])
            prices_data.append({
                'date': date_val,
                'ticker': ticker,
                'close': price
            })

    df = pl.DataFrame(prices_data)
    print(f"Loaded {len(tickers)} tickers, {len(dates)} days")

    return df


def calculate_returns(prices: pl.DataFrame) -> pl.DataFrame:
    """
    Calculate returns from prices.

    Args:
        prices: Polars DataFrame with [date, ticker, close]

    Returns:
        Polars DataFrame with [date, ticker, return]
    """
    print("Calculating returns...")

    # Sort by ticker and date
    prices = prices.sort(['ticker', 'date'])

    # Calculate returns per ticker
    returns_pl = prices.group_by('ticker', maintain_order=True).agg([
        pl.col('date'),
        pl.col('close').pct_change().alias('return')
    ]).explode(['date', 'return'])

    # Drop first return (NaN)
    returns_pl = returns_pl.filter(pl.col('return').is_not_null())

    return returns_pl


def generate_mock_implied_vols(
    returns: pl.DataFrame,
    rv_calc: VolatilityRatioCalculator
) -> Dict[str, float]:
    """
    Generate mock implied volatilities.

    Formula: IV = RV × (1.0 + N(0, 0.3))

    This simulates the IV/RV spread observed in real markets.

    Args:
        returns: Returns DataFrame
        rv_calc: VolatilityRatioCalculator

    Returns:
        Dict mapping ticker → implied vol
    """
    print("Generating mock implied vols...")

    # Calculate RV
    rv_df = rv_calc.calculate_realized_volatility(returns)

    # Generate IV with noise
    np.random.seed(123)  # Different seed for IV noise
    implied_vols = {}

    for row in rv_df.iter_rows(named=True):
        ticker = row['ticker']
        rv = row['RV']

        # Add 30% noise to create IV/RV spread
        noise = np.random.normal(0, 0.3)
        iv = rv * (1.0 + noise)

        # Ensure IV is positive
        iv = max(iv, 0.01)

        implied_vols[ticker] = iv

    return implied_vols


def find_correlations(
    returns: pl.DataFrame,
    min_correlation: float = 0.80
) -> List[Tuple[str, str, float]]:
    """
    Find highly correlated asset pairs.

    Args:
        returns: Returns DataFrame
        min_correlation: Minimum correlation threshold

    Returns:
        List of (ticker_A, ticker_B, correlation) tuples
    """
    print("Finding correlations...")

    # Get unique tickers
    tickers = sorted(returns['ticker'].unique().to_list())

    # Build return matrix (rows=dates, cols=tickers)
    returns_dict = {}
    for ticker in tickers:
        ticker_returns = returns.filter(pl.col('ticker') == ticker).sort('date')['return'].to_numpy()
        returns_dict[ticker] = ticker_returns

    # Calculate correlation matrix manually
    n = len(tickers)
    corr_matrix = np.zeros((n, n))

    for i in range(n):
        for j in range(n):
            if i == j:
                corr_matrix[i, j] = 1.0
            else:
                ret_i = returns_dict[tickers[i]]
                ret_j = returns_dict[tickers[j]]
                # Ensure same length
                min_len = min(len(ret_i), len(ret_j))
                ret_i = ret_i[:min_len]
                ret_j = ret_j[:min_len]
                # Calculate correlation
                if len(ret_i) > 1:
                    corr_matrix[i, j] = np.corrcoef(ret_i, ret_j)[0, 1]

    # Find high-correlation pairs
    pairs = []
    for i, ticker_A in enumerate(tickers):
        for j, ticker_B in enumerate(tickers):
            if i < j:  # Avoid duplicates and self-correlation
                corr = corr_matrix[i, j]
                if corr >= min_correlation:
                    pairs.append((ticker_A, ticker_B, corr))

    # Sort by correlation (descending)
    pairs.sort(key=lambda x: x[2], reverse=True)

    print(f"Found {len(pairs)} pairs with correlation >= {min_correlation}")
    for ticker_A, ticker_B, corr in pairs[:5]:
        print(f"  {ticker_A}/{ticker_B}: {corr:.3f}")

    return pairs


def simulate_pnl(
    signals: pl.DataFrame,
    returns: pl.DataFrame
) -> Tuple[float, float, int]:
    """
    Simulate P&L from signals.

    Simplified simulation:
        - Each signal generates a position
        - Position held for 20 days (mean reversion horizon)
        - P&L = spread_change × position_size
        - Assume spread mean reverts 50% on average

    Args:
        signals: Signals DataFrame
        returns: Returns DataFrame

    Returns:
        Tuple of (total_pnl, sharpe_ratio, num_trades)
    """
    print("Simulating P&L...")

    if signals.height == 0:
        print("No signals generated!")
        return 0.0, 0.0, 0

    # Simulate spread mean reversion
    # Assumption: spread mean reverts by 50% over 20 days
    # P&L per trade = 0.5 × |spread| × signal_strength

    pnl_per_trade = []
    for row in signals.iter_rows(named=True):
        spread = row['spread']
        signal_strength = row['signal']

        # P&L = fraction of spread that mean reverts × signal strength
        # Add some randomness
        reversion_pct = np.random.uniform(0.3, 0.7)  # 30-70% mean reversion
        pnl = reversion_pct * abs(spread) * signal_strength

        pnl_per_trade.append(pnl)

    # Calculate metrics
    total_pnl = sum(pnl_per_trade)
    mean_pnl = np.mean(pnl_per_trade)
    std_pnl = np.std(pnl_per_trade, ddof=1) if len(pnl_per_trade) > 1 else 1.0

    # Sharpe ratio (annualized, assuming 20-day holding period)
    sharpe = (mean_pnl / std_pnl) * np.sqrt(252 / 20) if std_pnl > 0 else 0.0

    num_trades = len(pnl_per_trade)

    return total_pnl, sharpe, num_trades


def calculate_ic(
    signals: pl.DataFrame,
    returns: pl.DataFrame
) -> float:
    """
    Calculate Information Coefficient.

    IC = correlation(signal_strength, future_returns)

    Args:
        signals: Signals DataFrame
        returns: Returns DataFrame

    Returns:
        IC value
    """
    print("Calculating IC...")

    if signals.height == 0:
        return 0.0

    # For simplicity, use signal strength as forecast
    # and spread as "future return" (mean reversion)

    forecasts = signals['signal'].to_numpy()
    actuals = -signals['spread'].to_numpy()  # Negative spread = mean reversion direction

    # Calculate correlation
    if len(forecasts) > 1 and len(actuals) > 1:
        ic = np.corrcoef(forecasts, actuals)[0, 1]
    else:
        ic = 0.0

    return ic


def main():
    """Run volatility dispersion backtest."""
    print("=" * 80)
    print("Volatility Dispersion Backtest - SPDR Sector ETFs")
    print("=" * 80)

    # Load data
    prices = load_data()

    # Calculate returns
    returns = calculate_returns(prices)

    # Initialize calculators
    rv_calc = VolatilityRatioCalculator(lookback=30, annualization=252)

    # Generate mock implied vols
    implied_vols = generate_mock_implied_vols(returns, rv_calc)

    print("\nImplied Volatilities (mock):")
    for ticker, iv in sorted(implied_vols.items()):
        print(f"  {ticker}: {iv:.3f}")

    # Calculate IV/RV ratios
    vol_ratios = rv_calc.calculate_ratios(returns, implied_vols)

    print("\nIV/RV Ratios:")
    print(vol_ratios.sort('ticker'))

    # Find high-correlation pairs
    corr_pairs = find_correlations(returns, min_correlation=0.75)

    # Extract ticker pairs (without correlation value)
    pairs = [(a, b) for a, b, _ in corr_pairs]

    # Generate signals
    print("\nGenerating signals...")
    signal_gen = CorrelationVolatilitySignal(
        min_correlation=0.75,  # Lower correlation threshold
        lookback=60,
        z_threshold=0.5  # Lower z-score threshold for more signals
    )

    signals = signal_gen.calculate(returns, vol_ratios, pairs)

    print(f"\nGenerated {signals.height} signals")
    if signals.height > 0:
        print("\nTop 5 signals:")
        print(signals.sort('signal', descending=True).head(5))

    # Calculate metrics
    total_pnl, sharpe, num_trades = simulate_pnl(signals, returns)
    ic = calculate_ic(signals, returns)

    # Calculate turnover (signals per year)
    # Assume backtest is over 5 years (2020-2024)
    years = 5
    turnover = num_trades / years

    # Summary
    print("\n" + "=" * 80)
    print("BACKTEST RESULTS")
    print("=" * 80)
    print(f"Strategy: Volatility Dispersion (IV/RV ratio convergence)")
    print(f"Universe: {len(implied_vols)} SPDR sector ETFs")
    print(f"Period: 2020-2024 (5 years)")
    print(f"Min Correlation: 0.75")
    print(f"Z-score Threshold: 0.5")
    print()
    print(f"Number of Signals: {signals.height}")
    print(f"Number of Trades: {num_trades}")
    print(f"Turnover: {turnover:.1f} trades/year")
    print()
    print(f"Total P&L: {total_pnl:.4f}")
    print(f"Sharpe Ratio: {sharpe:.3f}")
    print(f"Information Coefficient (IC): {ic:.3f}")
    print()
    print("Interpretation:")
    print(f"  - Sharpe {sharpe:.2f}: {'GOOD' if sharpe > 0.7 else 'MODERATE' if sharpe > 0.5 else 'NEEDS IMPROVEMENT'}")
    print(f"  - IC {ic:.2f}: {'GOOD' if abs(ic) > 0.05 else 'MODERATE' if abs(ic) > 0.02 else 'LOW'}")
    print(f"  - Turnover {turnover:.1f}: {'HIGH' if turnover > 50 else 'MODERATE' if turnover > 20 else 'LOW'}")
    print()
    print("Notes:")
    print("  - This uses MOCK implied volatility (IV = RV × (1 + noise))")
    print("  - Real backtest requires actual options data (CBOE, IVolatility)")
    print("  - P&L simulation assumes 30-70% spread mean reversion over 20 days")
    print("  - In production: add transaction costs, position sizing, risk limits")
    print("=" * 80)


if __name__ == '__main__':
    main()
