# Grinold-Kahn Portfolio Management Framework for ARBS

**Purpose**: Implement quantitative portfolio construction for futures/swaps using Fundamental Law of Active Management

**Date**: 2025-11-10

---

## Overview

Grinold-Kahn framework provides a systematic approach to alpha generation and portfolio construction:

**Fundamental Law**: `IR = IC × √BR`
- **IR** (Information Ratio) = Excess Return / Tracking Error
- **IC** (Information Coefficient) = Correlation(forecast, actual)
- **BR** (Breadth) = Number of independent bets per year

**Goal**: Maximize risk-adjusted returns through:
1. Signal generation (alphas)
2. Risk model (covariance matrix)
3. Portfolio optimization

---

## 1. Core Components

### A. Signal/Alpha Generation

**Signals for Rates Products**:
- **Carry**: Expected P&L from time decay (curve slope)
- **Roll-Down**: Capital gain from rolling down the curve
- **Curve Positioning**: Steepeners, flatteners, butterflies
- **Relative Value**: Cheap/rich analysis (futures vs swaps basis)
- **Mean Reversion**: Deviation from historical relationships
- **Momentum**: Trend in rate changes

**Alpha Formula**:
```python
Alpha[i] = IC × Vol[i] × Z-Score[i]
```
Where:
- IC = forecast skill (typically 0.05-0.15 for quant strategies)
- Vol[i] = volatility of instrument i
- Z-Score[i] = standardized signal strength

### B. Risk Model (Covariance Matrix)

**For Rates Products**:
```python
Cov[i,j] = Corr[i,j] × Vol[i] × Vol[j]
```

**Rate Correlations**:
- Same tenor, different time: ~0.95-0.99 (very high)
- Adjacent tenors (2Y vs 5Y): ~0.85-0.95
- Far tenors (2Y vs 30Y): ~0.60-0.80
- Futures vs Swaps (same tenor): ~0.98-0.99

**Volatility**:
- Front end (1M-2Y): Higher vol in Fed hiking/cutting cycles
- Belly (3Y-7Y): Moderate vol
- Long end (10Y-30Y): Lower vol, more stable

### C. Portfolio Optimization

**Objective**: Maximize risk-adjusted return
```python
maximize: α'w - (λ/2) × w'Σw
subject to:
  - sum(w) = 1 (fully invested, or =0 for dollar-neutral)
  - |w[i]| ≤ w_max (position limits)
  - sum(|DV01[i] × w[i]|) ≤ DV01_limit
```

Where:
- α = vector of alphas
- w = vector of weights
- Σ = covariance matrix
- λ = risk aversion parameter

---

## 2. Implementation Architecture

### Phase 1: Alpha/Signal Module

```
Signals/
  Base/
    BaseSignal.py           # Abstract signal interface
  Carry/
    CarrySignal.py          # Carry = (forward - spot) / time
  RollDown/
    RollDownSignal.py       # Roll-down = curve steepness
  Curve/
    SteepenerSignal.py      # 2s5s, 5s10s positioning
    FlatenerSignal.py
    ButterflySignal.py
  Basis/
    FuturesSwapBasis.py     # Futures vs swap basis
  ```

**Signal Interface**:
```python
class BaseSignal(ABC):
    @abstractmethod
    def calculate(self, market_data: MarketData, as_of: date) -> Dict[str, float]:
        """
        Calculate signal for each instrument.

        Returns:
            Dict mapping instrument -> z-score (standardized signal)
        """
        pass

    @abstractmethod
    def backtest(self, start: date, end: date) -> BacktestResult:
        """Test signal performance historically."""
        pass
```

### Phase 2: Risk Module

```
Risk/
  Covariance/
    CovarianceEstimator.py  # Build covariance from historical data
    ExponentialWeighting.py # EWMA for covariance
  Volatility/
    VolatilityModel.py      # GARCH, realized vol, etc.
```

**Covariance Interface**:
```python
class CovarianceEstimator:
    def estimate(
        self,
        returns: pd.DataFrame,  # Columns = instruments, rows = dates
        method: str = "sample",  # "sample", "ewma", "ledoit_wolf"
        halflife: int = 60,      # For EWMA
    ) -> np.ndarray:
        """
        Estimate covariance matrix from returns.

        Returns:
            N×N covariance matrix
        """
        pass
```

### Phase 3: Portfolio Optimizer

```
Portfolio/
  Optimizer/
    MeanVarianceOptimizer.py   # Classic Markowitz
    RobustOptimizer.py         # Robust to estimation error
    BlackLitterman.py          # Combine views with market equilibrium
  Constraints/
    DV01Constraint.py          # Total DV01 limit
    PositionLimitConstraint.py # Max weight per instrument
    TurnoverConstraint.py      # Limit trading costs
```

**Optimizer Interface**:
```python
class MeanVarianceOptimizer:
    def optimize(
        self,
        alphas: np.ndarray,        # Expected excess returns
        covariance: np.ndarray,    # Risk model
        risk_aversion: float = 1.0,
        constraints: List[Constraint] = None,
    ) -> OptimizationResult:
        """
        Find optimal portfolio weights.

        Returns:
            Weights, expected return, expected risk, Sharpe ratio
        """
        pass
```

### Phase 4: Backtest Integration

**Connect to Existing Backtest Engine**:
```python
class QuantPortfolioStrategy(BaseStrategy):
    """
    Quant portfolio strategy using Grinold-Kahn framework.
    """
    def __init__(
        self,
        signals: List[BaseSignal],
        risk_model: CovarianceEstimator,
        optimizer: Optimizer,
        rebalance_frequency: str = "monthly",
    ):
        self.signals = signals
        self.risk_model = risk_model
        self.optimizer = optimizer
        self.rebalance_freq = rebalance_frequency

    def generate_trades(self, as_of: date) -> List[Trade]:
        # 1. Calculate all signals
        signal_scores = {}
        for signal in self.signals:
            scores = signal.calculate(self.market_data, as_of)
            signal_scores.update(scores)

        # 2. Convert to alphas (expected returns)
        alphas = self._signals_to_alphas(signal_scores)

        # 3. Estimate covariance
        historical_returns = self._get_returns_window(as_of, lookback=252)
        covariance = self.risk_model.estimate(historical_returns)

        # 4. Optimize portfolio
        target_weights = self.optimizer.optimize(alphas, covariance)

        # 5. Generate rebalancing trades
        current_weights = self._get_current_weights()
        trades = self._rebalance(current_weights, target_weights)

        return trades
```

---

## 3. Practical Signals for Rates

### Carry Signal

**Definition**: Expected return from holding position, assuming no rate changes

**Formula**:
```
Carry[t, T] = (Forward Rate[t, T] - Spot Rate[t]) × (T - t)
```

**For Futures**:
```python
def futures_carry(front_contract, back_contract):
    """
    Carry from rolling futures position.

    Positive carry = contango (back > front)
    Negative carry = backwardation (front > back)
    """
    calendar_spread = price(back) - price(front)
    days_to_roll = days_until_expiry(front)

    carry_bps_daily = (calendar_spread / days_to_roll) * 10000
    return carry_bps_daily
```

**For Swaps**:
```python
def swap_carry(swap, horizon="1M"):
    """
    Carry = change in swap MTM from time decay only.
    """
    # Freeze curve, roll forward in time
    forward_rate = curve.forward_rate(effective + horizon, maturity)
    spot_rate = curve.spot_rate(effective, maturity)

    carry = (forward_rate - spot_rate) × DV01
    return carry
```

### Roll-Down Signal

**Definition**: P&L from rolling down static yield curve

**Formula**:
```
Roll-Down = DV01 × (Forward Rate - Spot Rate)
```

**Implementation**:
```python
def roll_down_signal(instrument, horizon="1M"):
    """
    Expected P&L from rolling down curve.
    Positive when curve is steep (upward sloping).
    """
    dv01 = instrument.dv01()
    current_rate = curve.rate(instrument.maturity)

    # Roll instrument forward in time
    rolled_maturity = instrument.maturity - horizon
    forward_rate = curve.rate(rolled_maturity)

    roll_down = dv01 * (forward_rate - current_rate) * 10000  # In bps
    return roll_down
```

### Curve Signal (Steepener/Flattener)

**Definition**: Relative value across curve

**Formula**:
```
Steepness = Rate[Long] - Rate[Short]
Z-Score = (Current Steepness - Historical Mean) / Historical StdDev
```

**Implementation**:
```python
def curve_steepness_signal(short_tenor="2Y", long_tenor="10Y", lookback=252):
    """
    Mean-reversion signal on curve steepness.
    Positive = curve is flat relative to history → expect steepening
    """
    current_spread = rate(long_tenor) - rate(short_tenor)

    historical_spreads = get_historical_spreads(short_tenor, long_tenor, lookback)
    mean_spread = historical_spreads.mean()
    std_spread = historical_spreads.std()

    z_score = (mean_spread - current_spread) / std_spread  # Inverted for mean reversion
    return z_score
```

### Basis Signal (Futures vs Swaps)

**Definition**: Convexity-adjusted basis between futures and swaps

**Formula**:
```
Basis = Futures Implied Rate - Swap Rate - Convexity Adjustment
Z-Score = (Current Basis - Fair Basis) / Historical StdDev
```

**Implementation**:
```python
def futures_swap_basis_signal(pack, matched_swap, lookback=252):
    """
    Arbitrage signal between futures pack and matched swap.
    """
    # Calculate current basis
    pack_price = avg([price(fut) for fut in pack])
    pack_rate = 100 - pack_price
    swap_rate = rate(matched_swap)
    convexity_adj = estimate_convexity(pack, matched_swap)  # ~1bp/quarter

    basis = pack_rate - swap_rate - convexity_adj

    # Compare to historical
    historical_basis = get_historical_basis(pack, matched_swap, lookback)
    mean_basis = historical_basis.mean()
    std_basis = historical_basis.std()

    z_score = (basis - mean_basis) / std_basis
    return z_score
```

---

## 4. Covariance Matrix Construction

### Historical Estimation

**Sample Covariance** (simple but noisy):
```python
def sample_covariance(returns: pd.DataFrame) -> np.ndarray:
    """
    Classic covariance estimator.
    Works well with T >> N (many observations, few assets).
    """
    return returns.cov().values
```

**Exponentially Weighted Moving Average (EWMA)**:
```python
def ewma_covariance(returns: pd.DataFrame, halflife=60) -> np.ndarray:
    """
    Give more weight to recent observations.
    Better captures regime changes.
    """
    lambda_ = 0.5 ** (1 / halflife)  # Decay factor

    # EWMA formula: Σ_t = λ × Σ_{t-1} + (1-λ) × r_t × r_t'
    cov = returns.ewm(halflife=halflife).cov().iloc[-len(returns):]
    return cov.values
```

**Shrinkage Estimator** (Ledoit-Wolf):
```python
def shrinkage_covariance(returns: pd.DataFrame) -> np.ndarray:
    """
    Shrink sample covariance toward structured target.
    Reduces estimation error when T ≈ N.
    """
    from sklearn.covariance import LedoitWolf

    lw = LedoitWolf()
    cov = lw.fit(returns).covariance_
    return cov
```

### Factor Model Approach

**Principal Component Analysis (PCA)** for rates:
```python
def pca_covariance(returns: pd.DataFrame, n_factors=3) -> np.ndarray:
    """
    Model returns as: r = B × f + ε
    where f = factors (level, slope, curvature)

    Reduces dimensionality: N × N → N × K (K factors)
    """
    from sklearn.decomposition import PCA

    pca = PCA(n_components=n_factors)
    factors = pca.fit_transform(returns)
    factor_loadings = pca.components_.T  # N × K
    factor_cov = np.cov(factors.T)  # K × K

    # Reconstruct: Σ = B × Σ_f × B' + Diag(σ_ε²)
    cov = factor_loadings @ factor_cov @ factor_loadings.T
    cov += np.diag(returns.var() - np.diag(cov))  # Add residual variance

    return cov
```

**For Rates**: 3-factor model captures ~99% of variance
- Factor 1: Level (parallel shift) - 85%
- Factor 2: Slope (steepening/flattening) - 10%
- Factor 3: Curvature (butterfly) - 4%

---

## 5. Portfolio Optimization

### Mean-Variance Optimization

**Quadratic Programming**:
```python
from scipy.optimize import minimize

def mean_variance_optimize(
    alphas: np.ndarray,  # Expected returns (N × 1)
    covariance: np.ndarray,  # Risk model (N × N)
    risk_aversion: float = 1.0,
) -> np.ndarray:
    """
    Solve: max α'w - (λ/2) × w'Σw
    """
    N = len(alphas)

    def objective(w):
        return -(alphas @ w - 0.5 * risk_aversion * w @ covariance @ w)

    # Constraints
    constraints = [
        {'type': 'eq', 'fun': lambda w: np.sum(w) - 1},  # Fully invested
    ]

    # Bounds
    bounds = [(-0.2, 0.2) for _ in range(N)]  # Max 20% per position

    result = minimize(
        objective,
        x0=np.ones(N) / N,  # Equal weight initial guess
        method='SLSQP',
        bounds=bounds,
        constraints=constraints,
    )

    return result.x
```

### Adding DV01 Constraint

```python
def dv01_neutral_optimize(
    alphas: np.ndarray,
    covariance: np.ndarray,
    dv01s: np.ndarray,  # DV01 of each instrument
    dv01_limit: float = 0.0,  # Target net DV01
    risk_aversion: float = 1.0,
) -> np.ndarray:
    """
    Optimize with DV01 constraint:
    sum(w[i] × DV01[i]) ≈ DV01_limit
    """
    N = len(alphas)

    def objective(w):
        return -(alphas @ w - 0.5 * risk_aversion * w @ covariance @ w)

    constraints = [
        {'type': 'eq', 'fun': lambda w: np.sum(w) - 1},  # Fully invested
        {'type': 'eq', 'fun': lambda w: dv01s @ w - dv01_limit},  # DV01 neutral
    ]

    bounds = [(-0.2, 0.2) for _ in range(N)]

    result = minimize(objective, x0=np.ones(N)/N, method='SLSQP',
                     bounds=bounds, constraints=constraints)

    return result.x
```

---

## 6. Backtest Integration

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

## 7. Implementation Roadmap

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
- ✅ Connected to backtest engine (MinimalBacktest)
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

## 8. Success Metrics

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

## 9. Example: Simple 2-Signal Strategy

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

---

## 10. Next Steps

1. **Implement base signal class** - abstract interface
2. **Build carry signal** - most robust/documented
3. **Test with single-signal backtest** - validate IC > 0
4. **Add covariance estimator** - start with simple sample cov
5. **Implement optimizer** - mean-variance with DV01 constraint
6. **Integrate with existing backtest** - modify EventDrivenBacktest
7. **Add performance attribution** - understand return sources
8. **Iterate and improve** - add more signals, refine risk model

Focus on **simplicity and robustness** first, then add complexity.
