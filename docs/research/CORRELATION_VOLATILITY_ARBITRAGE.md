# Correlation-Volatility Arbitrage Framework

**Date**: 2025-11-13
**Status**: Research & Implementation Roadmap

---

## Core Insight

**When correlation between assets is high, their implied/realized volatility ratios should converge. Divergence creates arbitrage opportunities.**

This applies equally to:
- **Equity sectors**: XLK (Tech) vs SMH (Semiconductors)
- **Global macro**: EUR vs CHF curves, USD vs GBP butterflies
- **Cross-asset**: Any highly correlated instruments

---

## Mathematical Foundation

### The Arbitrage Condition

For two highly correlated assets A and B:

**Returns relationship**:
```
r_A = β*r_B + ε
```

Where:
- ρ² = correlation² = 1 - var(ε)/var(r_A)
- When ρ → 1, the idiosyncratic component ε → 0

**Volatility decomposition**:
```
Vol_A = β*Vol_B * sqrt(ρ²) + Vol_ε * sqrt(1-ρ²)
```

**Key implication**: When ρ → 1:
```
IV_A/RV_A ≈ IV_B/RV_B
```

The market should price volatility risk premium consistently across highly correlated assets.

**Arbitrage signal**:
```
Signal = (IV_B/RV_B - IV_A/RV_A) * ρ
```

When |Signal| > threshold, trade the volatility spread.

---

## Implementation Framework

### 1. Volatility Ratio Calculator

```python
class VolatilityRatioCalculator:
    """
    Calculate implied/realized volatility ratios for assets.
    """

    def __init__(self, lookback: int = 30, annualization: int = 252):
        self.lookback = lookback
        self.annualization = annualization

    def calculate_ratios(
        self,
        returns: pl.DataFrame,
        implied_vols: Dict[str, float]
    ) -> pl.DataFrame:
        """
        Calculate IV/RV ratios for each asset.

        Args:
            returns: DataFrame with columns [ticker, date, return]
            implied_vols: Dict mapping ticker → implied vol (from options)

        Returns:
            DataFrame with columns [ticker, date, RV, IV, IV_RV_ratio]
        """
        # Calculate realized volatility
        rv = returns.group_by("ticker").agg([
            pl.col("return")
            .rolling_std(self.lookback)
            .mul(np.sqrt(self.annualization))
            .alias("RV")
        ])

        # Add implied vols
        iv_df = pl.DataFrame({
            "ticker": list(implied_vols.keys()),
            "IV": list(implied_vols.values())
        })

        # Join and calculate ratios
        result = rv.join(iv_df, on="ticker").with_columns([
            (pl.col("IV") / pl.col("RV")).alias("IV_RV_ratio")
        ])

        return result
```

### 2. Correlation-Volatility Signal

```python
class CorrelationVolatilitySignal(BaseSignal):
    """
    Generates signals from correlation-volatility divergence.

    Logic:
    - High correlation → IV/RV ratios should converge
    - Divergence → arbitrage opportunity
    - Signal strength proportional to correlation
    """

    def __init__(
        self,
        min_correlation: float = 0.85,
        lookback: int = 60,
        z_threshold: float = 2.0
    ):
        super().__init__()
        self.min_correlation = min_correlation
        self.lookback = lookback
        self.z_threshold = z_threshold

    def calculate(
        self,
        returns: pl.DataFrame,
        vol_ratios: pl.DataFrame,
        pairs: List[Tuple[str, str]]
    ) -> pl.DataFrame:
        """
        Calculate arbitrage signals for asset pairs.

        Args:
            returns: Historical returns
            vol_ratios: IV/RV ratios from VolatilityRatioCalculator
            pairs: List of (asset_A, asset_B) pairs to analyze

        Returns:
            DataFrame with columns [pair, correlation, spread, z_score, signal]
        """
        signals = []

        for asset_A, asset_B in pairs:
            # Calculate correlation
            corr = self._calculate_correlation(returns, asset_A, asset_B)

            if corr < self.min_correlation:
                continue

            # Get IV/RV ratios
            ratio_A = vol_ratios.filter(pl.col("ticker") == asset_A)["IV_RV_ratio"]
            ratio_B = vol_ratios.filter(pl.col("ticker") == asset_B)["IV_RV_ratio"]

            # Calculate spread
            spread = ratio_B - ratio_A

            # Z-score the spread
            z_score = self._calculate_z_score(spread)

            # Signal strength = |z_score| * correlation
            signal_strength = abs(z_score[-1]) * corr

            if signal_strength > self.z_threshold:
                signals.append({
                    "pair": f"{asset_A}/{asset_B}",
                    "asset_A": asset_A,
                    "asset_B": asset_B,
                    "correlation": corr,
                    "spread": spread[-1],
                    "z_score": z_score[-1],
                    "signal": signal_strength,
                    "direction": "sell_B_vol" if z_score[-1] > 0 else "sell_A_vol"
                })

        return pl.DataFrame(signals)

    def _calculate_correlation(
        self,
        returns: pl.DataFrame,
        asset_A: str,
        asset_B: str
    ) -> float:
        """Calculate rolling correlation between two assets."""
        ret_A = returns.filter(pl.col("ticker") == asset_A)["return"]
        ret_B = returns.filter(pl.col("ticker") == asset_B)["return"]

        # Pearson correlation
        return np.corrcoef(ret_A, ret_B)[0, 1]

    def _calculate_z_score(self, spread: pl.Series) -> pl.Series:
        """Z-score normalization of spread."""
        mean = spread.rolling_mean(self.lookback)
        std = spread.rolling_std(self.lookback)
        return (spread - mean) / std
```

### 3. Portfolio Construction with Correlation Constraints

```python
class CorrelationAwarePortfolio:
    """
    Portfolio optimizer that respects correlation constraints.

    Key insight: You can't be short vol in EVERY highly correlated asset.
    """

    def __init__(
        self,
        max_correlated_positions: int = 3,
        correlation_threshold: float = 0.85
    ):
        self.max_correlated_positions = max_correlated_positions
        self.correlation_threshold = correlation_threshold

    def optimize_weights(
        self,
        signals: pl.DataFrame,
        correlation_matrix: np.ndarray,
        tickers: List[str]
    ) -> Dict[str, float]:
        """
        Optimize portfolio weights under correlation constraints.

        Constraint: Limit number of positions in highly correlated clusters.
        """
        # Identify correlation clusters
        clusters = self._identify_correlation_clusters(
            correlation_matrix, tickers
        )

        # Solve constrained optimization
        weights = self._optimize_with_cluster_constraints(
            signals, clusters
        )

        return weights

    def _identify_correlation_clusters(
        self,
        corr_matrix: np.ndarray,
        tickers: List[str]
    ) -> Dict[int, List[str]]:
        """
        Identify clusters of highly correlated assets.

        Uses hierarchical clustering on correlation distance.
        """
        from sklearn.cluster import AgglomerativeClustering

        # Distance = 1 - |correlation|
        distance_matrix = 1 - np.abs(corr_matrix)

        # Cluster
        clustering = AgglomerativeClustering(
            n_clusters=None,
            distance_threshold=1 - self.correlation_threshold,
            metric='precomputed',
            linkage='average'
        )

        labels = clustering.fit_predict(distance_matrix)

        # Group tickers by cluster
        clusters = {}
        for ticker, label in zip(tickers, labels):
            if label not in clusters:
                clusters[label] = []
            clusters[label].append(ticker)

        return clusters

    def _optimize_with_cluster_constraints(
        self,
        signals: pl.DataFrame,
        clusters: Dict[int, List[str]]
    ) -> Dict[str, float]:
        """
        Optimize weights with max positions per cluster constraint.
        """
        import cvxpy as cp

        n = len(signals)
        w = cp.Variable(n)

        # Objective: maximize signal-weighted returns
        objective = cp.Maximize(signals["signal"] @ w)

        # Constraints
        constraints = [
            cp.sum(w) == 0,  # Dollar-neutral
            cp.sum(cp.abs(w)) <= 2.0,  # Gross leverage ≤ 2
        ]

        # Cluster constraints: max N positions per cluster
        for cluster_id, tickers in clusters.items():
            indices = [i for i, t in enumerate(signals["ticker"]) if t in tickers]
            if len(indices) > 0:
                # At most max_correlated_positions active in this cluster
                constraints.append(
                    cp.sum([cp.abs(w[i]) > 0.01 for i in indices])
                    <= self.max_correlated_positions
                )

        # Solve
        problem = cp.Problem(objective, constraints)
        problem.solve()

        # Extract weights
        weights = {}
        for i, ticker in enumerate(signals["ticker"]):
            weights[ticker] = w.value[i]

        return weights
```

---

## Academic Research

### Key Papers

1. **"Implied and Realized Volatility: A Study of the Ratio Distribution"**
   Moghaddam & Serota (2018), arXiv:1810.07735

   - Analyzes IV/RV ratio distributions
   - Shows ratio follows Beta Prime distribution
   - Parameters depend on time horizon and correlation structure

2. **"Dispersion Trading and Correlation Arbitrage"**
   arXiv:1004.0125 (2010)

   - Proves realized correlation = ratio of traded variance products
   - P&L = (ρ_realized - ρ_implied) × avg_variance + volga term
   - Observed spread explained by volga (vol of vol)

3. **"Cross-Section Without Factors: Correlation Risk, Strings and Asset Prices"**
   Distaso, Mele & Vilkov (2020), SSRN

   - Asset premium links to granular exposure to shocks in other assets
   - Average correlation premium exists
   - Theoretical foundation for correlation-driven pricing

4. **"Volatility Dispersion Trading"**
   University of Illinois working paper

   - Sharpe ratios improve to 0.70-0.79 when conditioning on implied correlation
   - Mean difference between implied and realized correlation has diminished since 2001
   - Markets have become more efficient but opportunities remain

---

## Application to ARBS Architecture

### Integration Points

1. **Signals Layer**
   - Add `CorrelationVolatilitySignal` alongside `CarrySignal`, `MomentumSignal`
   - Calculate IV/RV ratios per asset
   - Generate pair-wise arbitrage signals

2. **Risk Layer**
   - Use existing `SectorBasedCovarianceEstimator` for correlation structure
   - `StochasticBlockCovariance` naturally models cross-sector correlations
   - Add correlation cluster detection

3. **Optimizer Layer**
   - Add cluster-aware constraints to `MeanVarianceOptimizer`
   - Implement max positions per correlation cluster
   - Enforce "can't short 5Y in every currency" type constraints

4. **Portfolio Layer**
   - Track correlation exposure per cluster
   - Monitor concentration risk
   - Report cluster attribution

---

## Implementation Roadmap

### Phase 1: Data Infrastructure
- [ ] Add implied volatility data source (options)
- [ ] Implement `VolatilityRatioCalculator`
- [ ] Calculate IV/RV time series
- [ ] Validate against market data

### Phase 2: Signal Generation
- [ ] Implement `CorrelationVolatilitySignal`
- [ ] Add pair selection logic (high correlation threshold)
- [ ] Calculate spread z-scores
- [ ] Generate trading signals

### Phase 3: Risk Management
- [ ] Implement correlation cluster detection
- [ ] Add cluster exposure tracking
- [ ] Integrate with existing `SectorBasedCovarianceEstimator`
- [ ] Validate correlation stability over time

### Phase 4: Portfolio Construction
- [ ] Add cluster constraints to optimizer
- [ ] Implement `CorrelationAwarePortfolio`
- [ ] Test on equity sectors (XLK, XLF, XLE, ...)
- [ ] Test on global macro (EUR, USD, GBP curves)

### Phase 5: Backtesting & Validation
- [ ] Backtest on equity sector ETFs
- [ ] Backtest on currency butterflies
- [ ] Compare to academic results
- [ ] Measure Sharpe ratios, IC, turnover

---

## Equity Sector Example

### Setup
- **Universe**: 11 SPDR sector ETFs (XLK, XLF, XLE, XLV, XLI, XLP, XLY, XLU, XLB, XLRE, XLC)
- **Correlation pairs**: Identify high-correlation pairs (e.g., XLK/SMH, XLY/XLP)
- **Data**: Daily prices + ATM implied vol from options

### Strategy
1. Calculate rolling 60-day correlations between all pairs
2. For pairs with ρ > 0.85:
   - Calculate IV/RV ratio for each ETF
   - Compute spread: IV/RV(B) - IV/RV(A)
   - Z-score the spread (lookback=60)
3. When |z-score| > 2.0:
   - Sell vol on rich side, buy vol on cheap side
   - Delta-hedge with underlying ETFs
   - Size = signal_strength × (1 / number_of_positions_in_cluster)

### Constraints
- Max 3 positions per correlation cluster
- Gross leverage ≤ 2.0
- Dollar-neutral (net exposure = 0)

---

## Global Macro Example

### Setup
- **Universe**: EUR, USD, GBP, CHF, JPY curves (2Y, 5Y, 10Y, 30Y per currency)
- **Correlation pairs**: EUR/CHF (high), USD/GBP (moderate), cross-currency same tenor
- **Data**: Swaption IV + realized curve volatility

### Strategy
1. Calculate correlation between curve points
   - Intra-currency: 5Y vs 10Y (high)
   - Cross-currency: EUR 5Y vs USD 5Y (moderate)
2. Identify IV/RV ratio divergences
3. Trade vol spreads:
   - Sell EUR 5Y vol, buy CHF 5Y vol if spread > threshold
   - Hedge with swaps to remain delta-neutral

### Constraint: The Butterfly Problem
**You cannot be short the 5Y on a 2-5-10 butterfly in EVERY currency.**

Solution: Cluster currencies by correlation, limit positions per cluster.

Example clusters:
- **Cluster 1**: EUR, CHF (high correlation)
- **Cluster 2**: USD, GBP (moderate correlation)
- **Cluster 3**: JPY (low correlation with others)

Constraint: Max 2 butterfly trades per cluster → prevents over-concentration.

---

## Risk Decomposition

### PnL Attribution

```python
def pnl_attribution(positions: Dict) -> Dict[str, float]:
    """
    Decompose P&L into components.
    """
    # Directional (should be ~0 after delta hedging)
    directional = positions['delta'] * price_change

    # Spread mean reversion
    spread = positions['spread'] * (spread_end - spread_start)

    # Volatility arbitrage (IV/RV convergence)
    vol_arb = positions['vega'] * (IV_RV_ratio_end - IV_RV_ratio_start)

    # Correlation risk (if correlation breaks)
    correlation_pnl = positions['cross_gamma'] * (corr_end - corr_start)

    return {
        'directional': directional,  # ~0
        'spread': spread,
        'vol_arb': vol_arb,
        'correlation': correlation_pnl
    }
```

### Key Risks

1. **Correlation breakdown**: Your hedge fails if ρ drops significantly
2. **Vol regime change**: Both IV and RV spike, spread doesn't converge
3. **Liquidity asymmetry**: Can't exit both legs simultaneously
4. **Model risk**: IV/RV ratio convergence assumption fails

### Risk Limits

```python
def risk_limits(correlation: float, iv_rv_spread: float) -> Dict[str, float]:
    """
    Reduce size as correlation drops or spread widens.
    """
    # Correlation adjustment
    if correlation < 0.80:
        size_multiplier = 0.5
    elif correlation < 0.85:
        size_multiplier = 0.75
    else:
        size_multiplier = 1.0

    # Spread adjustment (cut size if spread > 3σ)
    if abs(iv_rv_spread) > 3.0:
        size_multiplier *= 0.5

    return {
        'max_notional': 10_000_000 * size_multiplier,
        'max_vega': 50_000 * size_multiplier,
        'max_gamma': 10_000 * size_multiplier
    }
```

---

## Connection to Existing Framework

### Sector Rotation ↔ Currency Curves

The research document `global_macro_rv_framework.md` establishes the equivalence:

| Equity Domain | Global Macro Domain |
|---------------|---------------------|
| Sector (Tech) | Currency (USD) |
| Stock (AAPL) | Tenor point (2Y) |
| Sector beta | Currency factor |
| Intra-sector correlation | Intra-currency correlation |
| Cross-sector correlation | Cross-currency correlation |

**Key insight**: The same correlation-volatility arbitrage framework applies to both!

### Mean Reversion with Constraints

Both domains face the same constraint:
- **Equities**: Can't short every sector vs SPY simultaneously
- **Macro**: Can't short 5Y in every currency's butterfly

Solution: Cluster by correlation, limit positions per cluster.

---

## Next Steps

1. **Implement `VolatilityRatioCalculator`** (Priority 1)
   - Needs options data source for implied vol
   - Use existing `VolatilityEstimator` for realized vol

2. **Add correlation cluster detection** (Priority 2)
   - Extend `SectorBasedCovarianceEstimator`
   - Implement hierarchical clustering on correlation matrix

3. **Create `CorrelationVolatilitySignal`** (Priority 3)
   - Integrate with existing `BaseSignal` framework
   - Follow TDD: write tests first

4. **Extend optimizer with cluster constraints** (Priority 4)
   - Add constraints to `MeanVarianceOptimizer`
   - Test on synthetic data first

5. **Backtest on equity sectors** (Priority 5)
   - Use SPDR sector ETFs (XLK, XLF, etc.)
   - Measure IC, Sharpe, turnover

---

## References

### Academic Papers
- Moghaddam & Serota (2018), "Implied and Realized Volatility", arXiv:1810.07735
- "Dispersion Trading and Correlation Arbitrage", arXiv:1004.0125
- Distaso, Mele & Vilkov (2020), "Cross-Section Without Factors", SSRN
- García-Medina et al. (2024), "Hierarchical Clustering of S&P 500", arXiv:2412.13944

### ARBS Documentation
- `docs/SECTOR_COVARIANCE_GUIDE.md` - Sector-based covariance estimators
- `docs/MVP_EQUITY_SECTOR_COMPLETE.md` - Equity sector implementation
- `docs/GRINOLD_KAHN_FRAMEWORK.md` - Alpha generation framework
- `docs/SIGNAL_COMBINATION_METHODS.md` - Multi-signal strategies

### Code References
- `Signals/SectorRotation/` - Sector rotation signals
- `Risk/Covariance/SectorBased/` - Sector covariance estimators
- `Risk/Volatility/VolatilityEstimator.py` - Vol estimation base class
- `Optimizer/MeanVarianceOptimizer.py` - Portfolio optimization

---

**Status**: Framework documented, ready for implementation.
