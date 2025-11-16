# Portfolio Construction Workflow

**Purpose**: End-to-end workflow for Grinold-Kahn portfolio construction in ARBS

**Date**: 2025-11-14

---

## 1. Backtest Integration

### Strategy Workflow

```python
class GrinoldKahnStrategy:
    def __init__(self, config):
        self.signals = self._load_signals(config)
        self.risk_model = CovarianceEstimator(method="ewma", halflife=60)
        self.optimizer = MeanVarianceOptimizer(risk_aversion=2.0)
        self.rebalance_freq = config.rebalance_frequency

    def on_date(self, as_of: date):
        """Called each day by backtest engine."""

        # Check if rebalance day
        if not self._is_rebalance_day(as_of):
            return []

        # 1. Calculate signals
        signal_scores = {}
        for signal in self.signals:
            scores = signal.calculate(as_of)
            signal_scores.update(scores)

        # 2. Convert to alphas
        alphas = self._scores_to_alphas(signal_scores)

        # 3. Estimate covariance
        returns = self._get_returns_history(as_of, lookback=252)
        cov = self.risk_model.estimate(returns)

        # 4. Get DV01s
        dv01s = self._get_dv01s(as_of)

        # 5. Optimize
        target_weights = self.optimizer.optimize(
            alphas, cov, dv01s, dv01_limit=0
        )

        # 6. Generate trades
        current_weights = self._get_current_weights()
        trades = self._rebalance_trades(current_weights, target_weights)

        return trades
```

### Performance Attribution

```python
def attribute_performance(portfolio_returns, factor_returns):
    """
    Decompose returns into:
    - Alpha (stock selection)
    - Factor exposures (systematic)
    - Residual (unexplained)
    """
    # Regression: r_p = α + Σ(β_i × f_i) + ε
    from sklearn.linear_model import LinearRegression

    model = LinearRegression()
    model.fit(factor_returns, portfolio_returns)

    alpha = model.intercept_
    factor_betas = model.coef_
    residual_vol = np.std(portfolio_returns - model.predict(factor_returns))

    return {
        'alpha': alpha,
        'factor_betas': factor_betas,
        'residual_vol': residual_vol,
        'r_squared': model.score(factor_returns, portfolio_returns),
    }
```

---

## 2. Implementation Roadmap

### Phase 1: Signals ✅ COMPLETE (2025-11-11)
- ✅ Implemented basic signals (carry, momentum, mean reversion)
- ✅ Backtest each signal independently
- ✅ Measure IC for each signal
- ✅ SignalCombiner for multi-signal strategies (156 tests)

### Phase 2: Risk Model ✅ COMPLETE (2025-11-11)
- ✅ Historical covariance estimation (sample, EWMA)
- ✅ Ledoit-Wolf shrinkage estimator
- ✅ Validated with historical data (22 tests)

### Phase 3: Optimizer ✅ COMPLETE (2025-11-11)
- ✅ Mean-variance optimization (Markowitz 1952)
- ✅ Budget, leverage, position constraints
- ✅ Scales to 50+ assets (18 tests)

### Phase 4: Integration ✅ COMPLETE (2025-11-11)
- ✅ Connected to backtest engine (Backtest)
- ✅ TearSheet performance analysis (Sharpe, Sortino, Calmar, drawdowns)
- ✅ End-to-end returns-first architecture (8 integration tests)

### Phase 5: Advanced (Ongoing)
- [ ] Additional curve positioning signals (steepeners, flatteners, butterflies)
- [ ] Basis arbitrage signals (futures vs swaps)
- [ ] Machine learning for alpha combination
- [ ] Transaction cost modeling
- [ ] DV01 constraints for fixed income risk limits
- [ ] Robust optimization

---

## 3. Success Metrics

**Signal Quality**:
- IC (Information Coefficient) > 0.05
- Hit rate > 52%
- Signal decay (half-life < 20 days)

**Portfolio Performance**:
- Sharpe Ratio > 1.0
- Max Drawdown < 10%
- Turnover < 200% per year

**Risk Management**:
- DV01 limits respected 100% of time
- No position > 20% of portfolio
- Correlation to benchmarks < 0.3

---

## 4. Example Strategies

### Simple 2-Signal Strategy

```python
# Signal 1: Carry
carry = FuturesCarry(contracts=["SFRZ4", "SFRH5", "SFRM5", "SFRU5"])

# Signal 2: Curve steepness mean reversion
steepener = CurveSteepness(short="2Y", long="10Y", lookback=252)

# Combine signals
strategy = GrinoldKahnStrategy(
    signals=[carry, steepener],
    risk_model=EWMACov(halflife=60),
    optimizer=MeanVarianceOptimizer(risk_aversion=2.0),
    rebalance_frequency="monthly",
)

# Backtest
results = backtest(
    strategy=strategy,
    start_date=date(2020, 1, 1),
    end_date=date(2024, 12, 31),
    initial_capital=1_000_000,
)

# Analyze
print(f"Sharpe: {results.sharpe_ratio:.2f}")
print(f"Ann Return: {results.annualized_return:.2%}")
print(f"Max DD: {results.max_drawdown:.2%}")
print(f"IC: {results.information_coefficient:.3f}")
```

### Futures Carry Strategy (Query-Based Workflow)

```python
from Backtest.Backtest import Backtest
from Adapter.FuturesAdapter import FuturesAdapter
from Signals.Futures.CarrySignal import CarrySignal

backtest = Backtest(
    mdp=market_data_provider,
    adapter=FuturesAdapter(mdp),
    signals=CarrySignal()
)
result = backtest.run(contracts=['SFRZ4', 'SFRH5'], dates=[...])
```

### Equity Momentum Strategy (DataFrame-Based Workflow)

```python
from Backtest.Backtest import Backtest
from Signals.Futures.MomentumSignal import MomentumSignal

backtest = Backtest(
    signals=MomentumSignal(lookback=20),
    risk_aversion=3.0
)
result = backtest.run_from_dataframe(returns_df, dates=[...])
```

### Multi-Signal Strategy

```python
from Backtest.Backtest import Backtest
from Signals.SignalCombiner import SignalCombiner

backtest = Backtest(
    mdp=mdp,
    adapter=FuturesAdapter(mdp),
    signals=[CarrySignal(), MomentumSignal()],
    signal_combiner=SignalCombiner(method='ic_weighted')
)
result = backtest.run(contracts=[...], dates=[...])
```

---

## 5. Component Integration

### Complete End-to-End Flow

```
Query Layer:     FuturesQuery → MockFuture objects
       ↓
Adapter Layer:   FuturesAdapter → DataFrame (returns, metadata)
       ↓
Returns:         ReturnsCalculator → standardized returns matrix
       ↓
Volatility:      VolatilityEstimator → volatility forecasts
       ↓
Signals:         CarrySignal → raw signals (z-scores)
       ↓
Alpha:           AlphaGenerator → scaled alphas (IC × Vol × Z)
       ↓
Risk:            LedoitWolfShrinkage → covariance matrix Σ
       ↓
Optimizer:       MeanVarianceOptimizer → portfolio weights
       ↓
Portfolio:       Portfolio(returns) → composite asset with nested tracking
       ↓
Analysis:        TearSheet → IC/Sharpe/returns analysis
       ↓
Result:          BacktestResult (returns, IC, Sharpe, total return)
```

### Key Design Decisions
- Single Backtest class supports all workflows (query-based and DataFrame-based)
- Component injection enables testing without full integration
- Two workflows support different data availability patterns
- Signal combiner auto-created for multiple signals with equal-weight default

---

## 6. Next Steps

1. **Implement base signal class** - abstract interface
2. **Build carry signal** - most robust/documented
3. **Test with single-signal backtest** - validate IC > 0
4. **Add covariance estimator** - start with simple sample cov
5. **Implement optimizer** - mean-variance with DV01 constraint
6. **Integrate with existing backtest** - modify EventDrivenBacktest
7. **Add performance attribution** - understand return sources
8. **Iterate and improve** - add more signals, refine risk model

Focus on **simplicity and robustness** first, then add complexity.

---

**Related Documentation**:
- `GRINOLD_KAHN_FRAMEWORK.md` - Complete framework overview
- `GRINOLD_KAHN_DETAILED_SPECS.md` - Technical specifications
- `CLAUDE.md` - Implementation status and architecture
