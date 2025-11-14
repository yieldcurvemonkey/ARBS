# ABOUTME: Backtest module for portfolio strategy testing
# ABOUTME: Unified backtest implementation supporting query and DataFrame workflows
"""
Backtest Module

Unified backtest system supporting multiple workflows with a single interface:
1. Query-Based Workflow: MDP + Adapter → Signals → Portfolio
2. DataFrame-Based Workflow: Returns → Signals → Portfolio
3. Hybrid Workflow: Combine both approaches

Components:
- Backtest: Unified backtest class supporting all workflows
- BaseBacktest: Abstract base class
- BacktestResult: Performance metrics and results

Workflow Selection:

Query-Based (Futures/Swaps):
    from Backtest.Backtest import Backtest
    from Adapter.FuturesAdapter import FuturesAdapter
    from Signals.Futures.CarrySignal import CarrySignal

    backtest = Backtest(
        mdp=market_data_provider,
        adapter=FuturesAdapter(mdp),  # Query → DataFrame bridge
        signals=CarrySignal(),
        risk_aversion=1.0,
        long_only=True,
    )
    result = backtest.run(contracts=['SFRZ4', 'SFRH5'], dates=[...])

DataFrame-Based (Equities/ETFs):
    from Backtest.Backtest import Backtest
    from Signals.Futures.MomentumSignal import MomentumSignal

    backtest = Backtest(
        signals=MomentumSignal(lookback=20),
        risk_aversion=2.0,
        long_only=True,
    )
    result = backtest.run_from_dataframe(returns_df, dates=[...])

Multi-Signal Strategy:
    from Signals.SignalCombiner import SignalCombiner

    backtest = Backtest(
        mdp=mdp,
        adapter=FuturesAdapter(mdp),
        signals=[
            CarrySignal(name='carry'),
            MomentumSignal(lookback=20, name='momentum')
        ],
        signal_combiner=SignalCombiner(method='equal'),
        risk_aversion=1.5,
    )
    result = backtest.run(contracts=[...], dates=[...])

Pipeline:
1. Data: MDP/Adapter (query) or DataFrame (pre-computed returns)
2. Signals: Generate raw signals (z-scores)
3. Alpha: Scale signals → expected returns (IC × Vol × Z)
4. Risk: Estimate covariance matrix
5. Optimizer: Calculate optimal weights
6. Portfolio: Track positions and P&L

Key Features:
- Single class for all workflows (query, DataFrame, hybrid)
- Component injection (signals, risk models, optimizers)
- Multi-signal support with automatic combiner
- Grinold-Kahn compliant architecture
- Comprehensive performance metrics

Examples:
- examples/backtest_query_workflow.py - Query workflow patterns
- examples/backtest_hybrid_workflow.py - Hybrid workflow patterns
- examples/run_backtest.py - Basic futures carry example

Documentation:
- docs/BACKTEST_UNIFIED_API.md - Complete API reference

MVP Philosophy:
- Goal: Accurate measurement, not profitability
- If strategy loses money, that's fine - we measure it correctly
- No IC requirement for success

Version: 0.1.0 (Unified API)
"""

__version__ = "0.1.0"
