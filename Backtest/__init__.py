# ABOUTME: Backtest module for portfolio strategy testing
# ABOUTME: Generic and minimal backtest implementations with configurable components
"""
Backtest Module

Integrates all components for end-to-end strategy backtesting:
1. Query Layer: Get contract prices
2. Adapter: Format for signals
3. Signals: Generate alphas
4. Risk: Estimate covariance
5. Optimizer: Calculate weights
6. Backtest: Track positions and P&L

Classes:
- Backtest: Generic backtest with configurable signals and adapters (RECOMMENDED)
- MinimalBacktest: Futures carry backtest (specific use case)
- Base: Abstract base classes

Usage (Generic Backtest):
    from Backtest.Backtest import Backtest
    from Adapter.FuturesAdapter import FuturesAdapter
    from Signals.Futures.CarrySignal import CarrySignal

    # Futures carry strategy
    backtest = Backtest(
        mdp=market_data_provider,
        adapter=FuturesAdapter(mdp),
        signals=CarrySignal(),
        risk_aversion=1.0,
        long_only=True,
    )
    result = backtest.run(contracts=['SFRZ4', 'SFRH5'], dates=[...])

    # Equity momentum strategy
    backtest = Backtest(
        signals=MomentumSignal(lookback=20),
        risk_aversion=3.0,
    )
    result = backtest.run_from_dataframe(returns_df, dates=[...])

    # Multi-signal strategy
    backtest = Backtest(
        mdp=mdp,
        adapter=FuturesAdapter(mdp),
        signals=[CarrySignal(), MomentumSignal()],
        signal_combiner=SignalCombiner(method='ic_weighted'),
    )
    result = backtest.run(contracts=[...], dates=[...])

Usage (MinimalBacktest - Futures Only):
    from Backtest.MinimalBacktest import MinimalBacktest

    backtest = MinimalBacktest(
        mdp=market_data_provider,
        risk_aversion=1.0,
        long_only=True,
    )
    result = backtest.run(contracts=['SFRZ4', 'SFRH5'], dates=[...])

MVP Goal: Measure correctly, not necessarily profitably
- If strategy loses money, that's fine
- We measure it accurately
- No IC requirement for success
"""

__version__ = "0.1.0"
