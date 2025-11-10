# ABOUTME: Backtest module for portfolio strategy testing
# ABOUTME: Implements minimal backtest loop integrating Query→Adapter→Signals→Risk→Optimizer
"""
Backtest Module

Integrates all components for end-to-end strategy backtesting:
1. Query Layer: Get contract prices
2. Adapter: Format for signals
3. Signals: Generate alphas
4. Risk: Estimate covariance
5. Optimizer: Calculate weights
6. Backtest: Track positions and P&L

Modules:
- MinimalBacktest: Core backtest loop
- Base: Abstract base classes

Usage:
    from Backtest.MinimalBacktest import MinimalBacktest

    # Create backtest
    backtest = MinimalBacktest(
        mdp=market_data_provider,
        risk_aversion=1.0,
        long_only=True,
    )

    # Run backtest
    contracts = ['SFRZ4', 'SFRH5', 'SFRM5']
    dates = pd.date_range('2024-01-01', '2024-12-31', freq='W')
    result = backtest.run(contracts, dates)

    # Analyze results
    print(f"Sharpe: {result.sharpe_ratio:.2f}")
    print(f"IC: {result.ic:.3f}")
    print(f"Total Return: {result.total_return:.2%}")

MVP Goal: Measure correctly, not necessarily profitably
- If strategy loses money, that's fine
- We measure it accurately
- No IC requirement for success
"""

__version__ = "0.1.0"
