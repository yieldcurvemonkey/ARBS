# Grinold-Kahn Implementation Gap Analysis

**Document Status**: Analysis Complete
**Date Written**: 2025-11-11
**Implementation Status**: Phase 1 Complete (Returns infrastructure, AlphaGenerator, VolatilityEstimator)
**Last Updated**: 2025-11-11

---

## Current State vs Framework Requirements

### ✅ What We Have (Implemented)

#### 1. **Signal Layer** (Partially Complete)
```python
# ✅ Implemented
Signals/Base/BaseSignal.py         # Abstract interface
Signals/Futures/CarrySignal.py     # Carry signal for futures
Signals/Utils/IC.py                # Information Coefficient calculation
```

**Status**: Foundation complete, but needs integration with returns-first architecture.

#### 2. **Risk Layer** (Complete)
```python
# ✅ Implemented
Risk/Covariance/LedoitWolfShrinkage.py  # Shrinkage estimator
Risk/Covariance/SampleCovariance.py      # Sample covariance
Risk/Covariance/CovarianceComparison.py  # Comparison utilities
```

**Status**: Fully implemented with 22 tests passing.

#### 3. **Optimizer Layer** (Complete)
```python
# ✅ Implemented
Optimizer/MeanVarianceOptimizer.py  # Markowitz optimization
```

**Status**: Fully implemented with 18 tests passing. Supports:
- Mean-variance objective: `α'w - λ/2 × w'Σw`
- Budget constraints
- Position limits
- Risk aversion parameter

#### 4. **Backtest Layer** (Complete but needs refactoring)
```python
# ✅ Implemented (but works with prices, not returns)
Backtest/MinimalBacktest.py
```

**Status**: End-to-end backtest working (169 tests), but needs refactoring to be returns-first.

---

### ❌ What We're Missing

#### 1. **Returns-First Data Architecture**

**Problem**: Current system works with prices, converts to returns internally.

**Framework Requirement** (line 139):
```python
def estimate(
    self,
    returns: pd.DataFrame,  # <-- RETURNS as input!
    method: str = "sample",
) -> np.ndarray:
```

**What We Need**:
```python
# Data layer should provide returns directly
class ReturnsCalculator:
    """Convert prices → returns ONCE at data layer."""

    def calculate_returns(
        self,
        prices: Dict[str, float],
        previous_prices: Dict[str, float],
        method: str = "percent"  # or "log"
    ) -> Dict[str, float]:
        """
        Calculate returns from price changes.

        Args:
            prices: Current prices
            previous_prices: Previous prices
            method: "percent" or "log"

        Returns:
            Dict mapping asset → return
        """
        returns = {}
        for asset, curr_price in prices.items():
            prev_price = previous_prices.get(asset, 0.0)
            if prev_price > 0:
                if method == "percent":
                    returns[asset] = (curr_price - prev_price) / prev_price
                elif method == "log":
                    returns[asset] = np.log(curr_price / prev_price)
            else:
                returns[asset] = 0.0
        return returns
```

#### 2. **Signal → Alpha Conversion**

**Framework Requirement** (line 38-40):
```python
Alpha[i] = IC × Vol[i] × Z-Score[i]
```

**What We Have**:
- Signals produce Z-scores ✅
- But no explicit conversion to alphas (expected returns)

**What We Need**:
```python
class AlphaGenerator:
    """Convert signal Z-scores to expected returns (alphas)."""

    def __init__(self, IC: float = 0.05, vol_estimator: VolatilityEstimator = None):
        """
        Initialize alpha generator.

        Args:
            IC: Information Coefficient (forecast skill)
            vol_estimator: Estimator for asset volatilities
        """
        self.IC = IC
        self.vol_estimator = vol_estimator or RealizedVolatility()

    def signals_to_alphas(
        self,
        signals: Dict[str, float],  # Z-scores
        returns_history: pd.DataFrame,
        as_of: date
    ) -> Dict[str, float]:
        """
        Convert signal Z-scores to expected returns (alphas).

        Formula: α_i = IC × σ_i × z_i

        Args:
            signals: Map from asset → Z-score
            returns_history: Historical returns for vol estimation
            as_of: Current date

        Returns:
            Map from asset → expected return (alpha)
        """
        volatilities = self.vol_estimator.estimate(returns_history)

        alphas = {}
        for asset, z_score in signals.items():
            vol = volatilities.get(asset, returns_history[asset].std())
            alphas[asset] = self.IC * vol * z_score

        return alphas
```

**Why This Matters**:
- Signals are just rankings/scores (dimensionless Z-scores)
- Alphas are expected RETURNS (have units: %)
- Optimizer needs alphas (returns), not raw signals
- IC × Vol scaling makes signals comparable across assets

#### 3. **Volatility Estimation**

**Framework Requirement** (line 40, 50-51):
```python
# Needed for alpha calculation
Vol[i] = volatility of instrument i

# Needed for covariance
Cov[i,j] = Corr[i,j] × Vol[i] × Vol[j]
```

**What We Need**:
```python
class VolatilityEstimator(ABC):
    """Estimate asset volatilities from returns."""

    @abstractmethod
    def estimate(self, returns: pd.DataFrame) -> Dict[str, float]:
        """
        Estimate volatility for each asset.

        Args:
            returns: Historical returns (DataFrame)

        Returns:
            Map from asset → annualized volatility
        """
        pass


class RealizedVolatility(VolatilityEstimator):
    """Simple realized volatility estimator."""

    def __init__(self, lookback: int = 60, annualization_factor: float = 252):
        self.lookback = lookback
        self.annualization_factor = annualization_factor

    def estimate(self, returns: pd.DataFrame) -> Dict[str, float]:
        """
        Calculate realized volatility from historical returns.

        Vol = StdDev(returns) × sqrt(252)  # Annualized
        """
        recent_returns = returns.tail(self.lookback)
        vols = recent_returns.std() * np.sqrt(self.annualization_factor)
        return vols.to_dict()


class EWMAVolatility(VolatilityEstimator):
    """Exponentially weighted volatility (more responsive)."""

    def __init__(self, halflife: int = 30, annualization_factor: float = 252):
        self.halflife = halflife
        self.annualization_factor = annualization_factor

    def estimate(self, returns: pd.DataFrame) -> Dict[str, float]:
        """
        EWMA volatility: more weight to recent observations.
        """
        ewm_std = returns.ewm(halflife=self.halflife).std().iloc[-1]
        vols = ewm_std * np.sqrt(self.annualization_factor)
        return vols.to_dict()
```

#### 4. **Integrated Strategy Class**

**Framework Requirement** (lines 513-553):
```python
class GrinoldKahnStrategy:
    def on_date(self, as_of: date):
        # 1. Calculate signals (Z-scores)
        # 2. Convert to alphas (expected returns)
        # 3. Estimate covariance (from returns)
        # 4. Optimize portfolio
        # 5. Generate trades
```

**What We Need**:
```python
class GrinoldKahnPortfolio(Asset):
    """
    Portfolio following Grinold-Kahn framework.

    Combines:
    - Signals (Z-scores)
    - Alpha generation (IC × Vol × Z)
    - Risk model (covariance of returns)
    - Mean-variance optimization

    This IS-A Asset (implements Asset interface), so it can be:
    - Used in nested portfolios
    - Backtested like any other asset
    - Composed with other strategies
    """

    def __init__(
        self,
        signals: List[BaseSignal],
        risk_model: CovarianceEstimator,
        optimizer: MeanVarianceOptimizer,
        alpha_generator: AlphaGenerator,
        rebalance_frequency: str = "monthly"
    ):
        self.signals = signals
        self.risk_model = risk_model
        self.optimizer = optimizer
        self.alpha_generator = alpha_generator
        self.rebalance_freq = rebalance_frequency

    def generate_weights(
        self,
        contracts: List[str],
        returns_history: pd.DataFrame,
        as_of: date
    ) -> Dict[str, float]:
        """
        Generate optimal portfolio weights for given date.

        Grinold-Kahn workflow:
        1. Calculate signal Z-scores
        2. Convert Z-scores → alphas (IC × Vol × Z)
        3. Estimate covariance from returns
        4. Optimize: max α'w - λ/2 × w'Σw
        5. Return optimal weights

        Args:
            contracts: List of contracts in universe
            returns_history: Historical returns (DataFrame)
            as_of: Current date

        Returns:
            Dict mapping contract → weight
        """
        # Step 1: Calculate signals (Z-scores)
        signal_scores = {}
        for signal in self.signals:
            scores = signal.calculate(contracts, as_of)
            signal_scores.update(scores)

        # Step 2: Convert signals → alphas (expected returns)
        alphas = self.alpha_generator.signals_to_alphas(
            signal_scores,
            returns_history,
            as_of
        )

        # Step 3: Estimate covariance from returns
        cov_matrix = self.risk_model.fit(returns_history)

        # Step 4: Optimize portfolio
        # Convert dicts → arrays in correct order
        assets = list(alphas.keys())
        alpha_vec = np.array([alphas[a] for a in assets])

        # Get covariance submatrix for these assets
        cov_df = pd.DataFrame(cov_matrix, index=returns_history.columns, columns=returns_history.columns)
        cov_sub = cov_df.loc[assets, assets].values

        # Optimize
        weight_vec = self.optimizer.optimize(alpha_vec, cov_sub)

        # Convert back to dict
        weights = {asset: weight for asset, weight in zip(assets, weight_vec)}

        return weights

    def calculate_return(
        self,
        returns: Dict[str, float],  # <-- RETURNS, not prices!
        weights: Dict[str, float]
    ) -> float:
        """
        Calculate portfolio return from constituent returns.

        Formula: r_portfolio = Σ w_i × r_i

        Args:
            returns: Realized returns for each asset
            weights: Portfolio weights

        Returns:
            Portfolio return
        """
        portfolio_return = 0.0
        for asset, weight in weights.items():
            asset_return = returns.get(asset, 0.0)
            portfolio_return += weight * asset_return
        return portfolio_return
```

---

## Critical Architectural Changes Needed

### 1. Returns as Primary Data Structure

**Old (current)**:
```python
# Backtest stores prices
all_prices.append({'date': as_of, 'SFRZ4': 95.0, 'SFRH5': 94.9})

# Portfolio works with prices
portfolio.calculate_return(prev_prices, curr_prices)
```

**New (returns-first)**:
```python
# Backtest stores returns
returns = calculator.calculate_returns(prices, previous_prices)
return_history.append({'date': as_of, 'SFRZ4': 0.0105, 'SFRH5': 0.0053})

# Portfolio works with returns
portfolio.calculate_return(returns, weights)
```

### 2. Signal → Alpha Pipeline

**Old (missing)**:
```python
# Signals produce Z-scores, but no conversion to alphas
carry_signals = {'SFRZ4': 1.5, 'SFRH5': -0.8}  # Z-scores
# ??? → How do these become expected returns for optimizer?
```

**New (explicit)**:
```python
# Signals → Z-scores
signals = carry_signal.calculate(contracts, as_of)
# {'SFRZ4': 1.5, 'SFRH5': -0.8}

# Z-scores → Alphas (expected returns)
alphas = alpha_generator.signals_to_alphas(signals, returns_history, as_of)
# {'SFRZ4': 0.0015, 'SFRH5': -0.0008}  # Expected returns in %

# Alphas → Weights
weights = optimizer.optimize(alphas, cov_matrix)
```

### 3. Backtest Integration

**Old**:
```python
class MinimalBacktest:
    def run(self, contracts, dates):
        for as_of in dates:
            prices = get_prices(contracts, as_of)
            # Calculate signals from prices
            # Optimize
            # Track positions
```

**New**:
```python
class GrinoldKahnBacktest:
    def run(self, strategy: GrinoldKahnPortfolio, contracts, dates):
        returns_history = []

        for as_of in dates:
            # Get prices and convert to returns ONCE
            prices = get_prices(contracts, as_of)
            if previous_prices:
                returns = calculator.calculate_returns(prices, previous_prices)
                returns_history.append(returns)

                # Generate weights using Grinold-Kahn
                weights = strategy.generate_weights(
                    contracts,
                    pd.DataFrame(returns_history),
                    as_of
                )

                # Calculate portfolio return
                port_return = strategy.calculate_return(returns, weights)

            previous_prices = prices
```

---

## Implementation Priority

### Phase 1: Returns Infrastructure (Highest Priority)
1. **ReturnsCalculator** - Convert prices → returns at data layer
2. **Refactor Portfolio** - Accept returns dict instead of price dicts
3. **Refactor MinimalBacktest** - Maintain return history, not price history
4. **Update all tests** - Use returns instead of prices

**Why First**: Foundation for everything else. Nothing works correctly until this is done.

### Phase 2: Alpha Generation (High Priority)
1. **VolatilityEstimator** - RealizedVolatility and EWMAVolatility
2. **AlphaGenerator** - Convert signals (Z-scores) → alphas (returns)
3. **Integration tests** - Verify signal → alpha → weights pipeline

**Why Second**: Connects signals to optimizer. Without this, we can't use signals properly.

### Phase 3: Grinold-Kahn Strategy (Medium Priority)
1. **GrinoldKahnPortfolio** - Integrated strategy class
2. **Backtest integration** - Run full Grinold-Kahn workflow
3. **Performance attribution** - Decompose returns

**Why Third**: Brings everything together into usable strategy.

### Phase 4: Additional Signals (Lower Priority)
1. **RollDownSignal** - Roll-down from curve steepness
2. **CurveSteepnessSignal** - Mean reversion on curve
3. **Multi-signal combination** - Combine multiple signals

**Why Last**: Can add more signals once framework is solid.

---

## Next Immediate Steps

1. **Create ReturnsCalculator** with tests
2. **Refactor Portfolio.calculate_return()** to accept returns dict
3. **Create VolatilityEstimator** hierarchy
4. **Create AlphaGenerator** with IC × Vol × Z formula
5. **Update MinimalBacktest** to work with returns
6. **Integration test**: Signal → Alpha → Weights → Portfolio Return

**Goal**: Complete returns-first architecture in next session, then build Grinold-Kahn strategy on top.

---

## Implementation Status (Updated 2025-11-11)

### Completed
- ✅ ReturnsCalculator (16 tests)
- ✅ VolatilityEstimator (18 tests)
- ✅ AlphaGenerator (16 tests)
- ✅ TearSheet (19 tests)
- ✅ Portfolio.calculate_return() refactored to accept returns
- ✅ MinimalBacktest uses ReturnsCalculator and AlphaGenerator
- ✅ Returns-first architecture implemented
- ✅ MomentumSignal (trend-following signal)
- ✅ MeanReversionSignal (statistical arbitrage signal)
- ✅ SignalCombiner (multi-signal combination framework, 156 tests)

### Remaining
- [ ] GrinoldKahnPortfolio integrated strategy class
- [ ] Additional signals (RollDownSignal, CurveSteepnessSignal, Curve Positioning)
- [ ] Performance attribution decomposition

Total: 502 tests passing
