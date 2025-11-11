# Part 4: Implementation - Equity Implementation Notes

**Context**: Extracting equity-specific insights from Grinold-Kahn Part 4 (Chapters 14-17) to extend ARBS for equity portfolios.

**ARBS Status**: Already has `Optimizer/MeanVarianceOptimizer.py`, covariance estimation (Ledoit-Wolf), `Analysis/TearSheet.py`. Need to add **equity-specific constraints** and **transaction cost modeling**.

---

## Chapter 14: Portfolio Construction (pages 377-418)

### Key Insight: Implementation as Safeguard Against Poor Research

> "Implementation schemes are, in part, safeguards against poor research." (p. 382)

**Problem**: Alphas are often unreasonable, covariances noisy, transactions costs uncertain. Portfolio construction must handle imperfect inputs.

### Alpha Analysis (Preprocessing)

**Before** portfolio construction, refine alphas to match desired risk/return profile:

#### 1. Scale the Alphas

**Formula**: α = volatility × IC × score

```
Std{α} ≈ volatility × IC
```

**For equities**: If IC = 0.05, typical residual risk = 30%, then:
- Scale of alphas: 1.5%
- Mean alpha: 0%
- 2/3 of stocks: alphas between ±1.5%
- 5% of stocks: alphas > ±3.0%

**ARBS Application**: In `Signals/AlphaGenerator.py`, we already do this:
```python
alpha = IC * volatility * z_score
```
But we should **validate** that input alphas match expected scale.

#### 2. Trim Alpha Outliers

**Rule**: Examine alphas > 3× scale. Either:
- Set to zero (questionable data)
- Trim to ±3× scale (genuine but extreme)

**Extreme approach**: Force alphas into normal distribution (uses only rankings, ignores magnitudes).

#### 3. Neutralization

**Types**:
- **Benchmark-neutral**: α_B = Σ h_Bi × α_i = 0 (no benchmark timing)
- **Cash-neutral**: Σ α_i = 0 (no active cash position)
- **Industry-neutral**: α_industry,avg = 0 for each industry
- **Factor-neutral**: α_factor = 0 for risk factors (size, value, momentum, etc.)

**Formula for benchmark neutralization**:
```
α_i^BN = α_i - β_i × α_B
```

**Formula for industry neutralization**:
```
α_i^IN = α_i - α_industry(i)
where α_industry(j) = Σ_{i in j} (h_Bi / H_industry,j) × α_i  (cap-weighted)
```

**ARBS Application**: Create `Signals/AlphaNeutralizer.py`:
```python
class AlphaNeutralizer:
    def benchmark_neutralize(self, alphas, benchmark_weights, betas):
        alpha_B = np.sum(benchmark_weights * alphas)
        return alphas - betas * alpha_B
    
    def industry_neutralize(self, alphas, benchmark_weights, industries):
        # Calculate industry-average alphas (cap-weighted)
        # Subtract from each stock in that industry
        ...
    
    def factor_neutralize(self, alphas, factor_exposures, V):
        # Project alphas onto factor space, subtract
        ...
```

### Modified Alphas from Constrained Optimization

**Key Result** (Eq 14.1-14.2, p. 383):

Any constrained optimization with result h_PA, active risk ω_PA, IR can be **replicated** by:
- Unconstrained mean-variance optimization
- Modified alphas: **α+ = 2λ_A × V × h_PA**
- Risk aversion: **λ_A = IR / ω_PA**

**Implication**: Constraints **implicitly shrink alphas**. In Table 14.1 example:
- Original alphas: Std = 2.00%
- Modified alphas: Std = 0.57% (71% shrinkage!)
- Constraints effectively reduced IC by 62%

**ARBS Application**: After running constrained optimization, **back out modified alphas** to see what constraints did to your information.

### Constraints for Equity Portfolios

**Table 14.1 constraints** (p. 384):
- No short sales: h_i ≥ 0
- Position limits: h_i - h_Bi ≤ 5% (no more than 5% overweight vs benchmark)

**General equity constraints**:
1. **Long-only**: h_i ≥ 0 for all i
2. **Full investment**: Σ h_i = 1
3. **Beta = 1**: Σ h_i × β_i = 1 (no benchmark timing, unless desired)
4. **Sector-neutral**: Σ_{i in sector s} (h_i - h_Bi) = 0 for each sector s
5. **Position limits**: |h_i - h_Bi| ≤ w_max (e.g., w_max = 0.05 = 5%)
6. **Turnover limit**: Σ |h_i - h_i^old| ≤ TO_max

**ARBS Implementation**: Create `Optimizer/constraints/`:
```
Optimizer/constraints/
├── LongOnlyConstraint.py
├── SectorNeutralConstraint.py
├── PositionLimitConstraint.py
├── TurnoverConstraint.py
└── ConstraintRegistry.py
```

Each constraint as **cvxpy** form for quadratic program.

### Portfolio Construction Techniques Compared

**Test** (Table 14.3, p. 403): S&P 500 stocks, IC=0.1, BR=500 → IR_target = 2.24

| Method | Avg IR | Std IR | Min IR | Max IR |
|--------|--------|--------|--------|--------|
| Screen I (equal-weight) | 0.86 | 0.27 | 0.50 | 1.43 |
| Screen II (cap-weight) | 1.10 | 0.79 | -0.53 | 2.24 |
| Stratification | 1.27 | 0.89 | 0.33 | 2.82 |
| **Quadratic Programming** | **1.88** | **0.40** | **0.98** | **2.51** |

**Conclusion**: QP (mean-variance optimizer) **consistently outperforms**, with:
- Highest average IR
- Lowest volatility of IR across periods
- No negative IR periods

**ARBS**: We already use QP (`MeanVarianceOptimizer.py`). This validates the choice.

### Dispersion for Separate Accounts (p. 402-412)

**Problem**: Multiple clients, same strategy, different portfolios → different returns.

**Sources**:
1. Client-driven: different constraints (can't control)
2. Manager-driven: lack of attention (can control)
3. **Optimal dispersion**: due to transactions costs (unavoidable)

**Bound on tracking error** (Eq 14.12, p. 409):
```
ψ ≤ sqrt(TC / λ_A)
```

where TC = turnover × round-trip cost to reach optimal portfolio Q.

**Example**: λ_A = 0.10, round-trip TC = 2%, turnover = 10% → ψ ≤ 1.00%

**ARBS**: Not immediately relevant (we don't manage separate accounts), but shows **transactions costs create irreducible tracking error**.

---

## Chapter 15: Long/Short Investing (pages 419-444)

### The Surprising Impact of the Long-Only Constraint

**Key Result** (Eq 15.13, Fig 15.5, p. 437):

For typical U.S. equity strategy (500 stocks, 4.5% risk, log-normal cap distribution):
- **Shrinkage factor = 49%**
- Long-only constraint **cuts information ratio in half**!

**Shrinkage formula**:
```
Shrinkage = 1 - C1 × ω_P / sqrt(N) - C2 × ω_P^2 / N
```

Approximately:
```
IR_long-only ≈ IR_long-short × (1 - 0.06 × ω_P × sqrt(N))
```

**Dependence on**:
- **Number of assets N**: More assets → more shrinkage (more opportunities to hit bounds)
- **Active risk ω_P**: Higher risk → more shrinkage (more aggressive positions)
- **Asset volatility**: Lower volatility → more shrinkage (need larger positions for same risk)

**ARBS Implication**: If we build long-only equity optimizer:
- Expect **50% reduction** in realized IR vs unconstrained
- At lower risk (2% active risk), shrinkage only 29%
- **Enhanced indexing** (low active risk) less affected by long-only constraint

### Size Bias from Long-Only Constraint

**Result** (Fig 15.8, p. 442):

Long-only equity portfolios have **negative size bias**:
- 500 stocks, 4.5% risk → **size exposure = -0.65**
- This is **incidental**, not intentional
- Arises because: shortage of negative active positions → underweight large-cap more

**Cost of size bias** (1997-1998 example):
- Size factor return = +1.5% (large outperformed small)
- Loss from size bias = -0.65 × 1.5% = **-98 bps**

**ARBS**: When building long-only equity optimizer, **neutralize size factor** unless you have a size view.

### Capitalization-Weighted Benchmarks

**Gini coefficient** for benchmark concentration (p. 434):
- Equal-weighted: Gini = 0.00
- Frank Russell 1000: Gini = 0.71
- S&P 500: similar

**Model** (log-normal, constant c = 1.55 for U.S. equities):
```
p_n = (n - 0.5) / N
y_n = Φ^{-1}(p_n)
Cap_n ∝ exp(c × y_n)
```

**ARBS**: If we need to simulate cap-weighted equity benchmark, use this model.

---

## Chapter 16: Transaction Costs, Turnover, Trading (pages 445-476)

### Transaction Cost Components

**Four components**:
1. **Commissions**: Easiest to measure, smallest (~5-10 bps)
2. **Bid/ask spread**: Cost of trading 1 share (~10-20 bps for large-cap)
3. **Market impact**: Cost of trading many shares (largest, hardest to measure)
4. **Opportunity cost**: Cost of NOT trading (trades that never execute)

**Rule of thumb**: Round-trip TC ≈ **2% for typical institutional equity** (Loeb 1983).

**Comparison to futures**: Equity TC >> Futures TC (futures have lower spreads, higher liquidity).

### Market Impact: Inventory Risk Model

**Conceptual model** (Eq 16.1-16.4, p. 455):

1. **Time to clear inventory**:
```
τ_clear ≈ V_trade / V_avg_daily
```

2. **Inventory risk**:
```
Risk_inventory = σ_annual × sqrt(τ_clear / 250)
```

3. **Market impact** (price concession):
```
MI ∝ Risk_inventory = σ × sqrt(V_trade / V_avg)
```

4. **Total transaction cost**:
```
TC = c_tc × σ × sqrt(V_trade / V_avg) + commissions
```

**Key insight**: Market impact ∝ **sqrt(volume traded)** (Fig 16.1, p. 457, Loeb 1983).

**Rule of thumb**: Costs ~1 day's volatility to trade 1 day's volume.

If we want c_tc such that typical trade has TC ≈ 2% round-trip:
```
c_tc ≈ 0.02 / (σ × sqrt(typical_trade_fraction))
```

**ARBS Application**: Create `TransactionCosts/InventoryRiskModel.py`:
```python
class InventoryRiskModel:
    def __init__(self, c_tc: float = 0.02):
        self.c_tc = c_tc
    
    def estimate_cost(self, volume_traded, avg_daily_volume, sigma_annual, 
                      commission_bps=5):
        """Estimate one-way transaction cost.
        
        TC = c_tc × σ × sqrt(V_trade / V_avg) + commissions
        """
        if avg_daily_volume == 0:
            return np.inf  # Cannot trade (illiquid)
        
        sqrt_ratio = np.sqrt(volume_traded / avg_daily_volume)
        market_impact = self.c_tc * sigma_annual * sqrt_ratio
        commission = commission_bps / 10000  # bps to decimal
        
        return market_impact + commission
```

**Extension**: BARRA Market Impact Model (structural, p. 457-458):
- Submodels for volatility, volume, trade intensity, elasticity
- Separate buy/sell costs
- Exchange vs OTC
- More accurate but complex

### Measuring Transaction Costs: Implementation Shortfall

**Best approach** (Perold, p. 453):

Compare:
- **Paper portfolio**: Desired portfolio, executed immediately, no TC
- **Actual portfolio**: Real execution, real TC

**Implementation shortfall** = Return(paper) - Return(actual)

Captures:
- Commissions
- Bid/ask spread
- Market impact
- **Opportunity cost** (trades that never executed)

**Wagner estimate**: Opportunity cost often **dominates** all other TC.

**Inferior approach**: VWAP (volume-weighted average price):
- Ignores opportunity costs
- Easy to game
- Crude market impact measurement

**ARBS**: Not immediately needed (we don't execute real trades), but when we do:
- Track paper portfolio from optimizer output
- Compare to actual execution
- Measure shortfall

### Turnover vs Value Added Frontier

**Lower bound** (Eq 16.10, p. 461):
```
VA(TO) ≥ VA_I + (TO / TO_Q)^2 × (VA_Q - VA_I)
```

**Rule of thumb**:
> You can achieve at least 75% of the value added with 50% of the turnover.

**In terms of IR** (footnote 10, p. 461):
```
IR(TO=50%) ≥ sqrt(0.75) × IR(TO=100%) = 87% × IR_max
```

**Example** (Table 16.1, p. 465): S&P 100, TO_Q = 100%

| TO / TO_Q | VA / VA_Q | Implied Round-Trip TC |
|-----------|-----------|----------------------|
| 10% | 39% | 8.66% |
| 20% | 59% | 5.12% |
| 30% | 71% | 3.40% |
| 40% | 80% | 2.50% |
| **50%** | **87%** | **1.90%** |
| 60% | 92% | 1.43% |
| 70% | 96% | 1.02% |
| 100% | 100% | 0.00% |

**Optimal turnover**: Where SLOPE(TO) = TC (marginal value = marginal cost).

**ARBS Application**:
1. For equity strategies, **expect ~2% round-trip TC**
2. Optimal turnover ≈ 50-60% of unconstrained
3. When constraining turnover, can still achieve 85-90% of value

**Heterogeneous TC**: If we can forecast TC differences across stocks:
- Example (p. 467): Half of stocks TC = 1.42%, half TC = 2.26%
- Optimizing with these differences → **30% reduction in costs**
- Same alpha, same risk, much lower TC

**Key lesson**: **Accurate TC forecasts add significant value** in portfolio construction.

### Trade Scheduling as Optimization

**Problem** (Eq 16.12, p. 468): Given:
- Current portfolio
- Target portfolio
- Allowed trading period T

**Objective**:
```
Maximize: α_short-term - λ_A × ω_short-term^2 - MarketImpact
```

**Trade-off**: 
- Execute quickly → low short-term risk, high market impact
- Execute slowly → high short-term risk, low market impact

**Simple example** (Fig 16.5, p. 471): Buy stock over T=5 days

Two regimes:
1. **Market impact dominates**: Uniform trading (evenly spaced trades)
2. **Risk aversion dominates**: Front-loaded trading (75% in first 2 days)

**ARBS**: Not critical for monthly rebalancing, but relevant for:
- Daily rebalancing
- Large portfolio changes
- High-frequency strategies

---

## Chapter 17: Performance Analysis (pages 477-520)

### Goal: Separate Skill from Luck

**Statistical challenge** (Eq 17.1, p. 484):
```
SE(IR) ≈ 1 / sqrt(Y)
```

where Y = years of observation.

**To prove top-quartile skill** (IR=0.5) with 95% confidence (t=2):
```
2 = IR / SE(IR) = 0.5 × sqrt(Y)
→ Y = 16 years
```

**Probability that top-quartile manager has positive alpha** (Fig 17.2, p. 486):
- 1 month: 56%
- 1 year: 75%
- 5 years: 87%

**Implication**: Even skilled managers will have **negative alphas 13% of the time** over 5-year periods.

### Performance Attribution (Factor Decomposition)

**Multiple-factor model** (Eq 17.18, p. 502):
```
r_i(t) = Σ_j x_ij(t) × f_j(t) + u_i(t)
```

**Return attributed to factor j** (Eq 17.19):
```
Return_j = x_Pj(t) × f_j(t)
```

**For active returns** (Eq 17.23, p. 504):
```
r_PA(t) = β_PA × γ_B(t) + Σ_j x_PAj^R(t) × f_j(t) + u_PA(t)
```

where:
- β_PA × γ_B(t): **Active systematic** (benchmark timing)
- Σ_j x_PAj^R(t) × f_j(t): **Active residual common-factor**
- u_PA(t): **Specific asset selection**

**Residual exposures**:
```
x_PAj^R = x_PAj - β_PA × x_Bj
```

**ARBS Application**: Our `Analysis/TearSheet.py` already does some of this, but we should add:

```python
class PerformanceAttribution:
    def attribute_returns(self, portfolio_weights, benchmark_weights,
                          factor_exposures, factor_returns, 
                          specific_returns):
        """Attribute portfolio returns to factors.
        
        Returns
        -------
        attribution : dict
            'active_systematic': β_PA × γ_B
            'factor_j': x_PAj × f_j for each factor
            'specific': u_PA
        """
        active_weights = portfolio_weights - benchmark_weights
        beta_PA = self._calculate_active_beta(...)
        
        # Systematic
        sys_return = beta_PA * benchmark_return
        
        # Factor attribution
        factor_contrib = {}
        for j in factors:
            x_PAj = np.sum(active_weights * factor_exposures[:, j])
            factor_contrib[j] = x_PAj * factor_returns[j]
        
        # Specific
        specific = np.sum(active_weights * specific_returns)
        
        return {
            'active_systematic': sys_return,
            'factors': factor_contrib,
            'specific': specific
        }
```

### Best and Worst Policies (Table 17.5, p. 512)

After attribution, rank factors by:
- Average return over time
- Information ratio (return / risk)
- T-statistic

**Purpose**: Verify that value-added comes from **intended sources**.

Example:
- **Intended**: "I'm a value manager" → value factor should be best policy
- **Actual**: Momentum factor is best policy → strategy drift?

**ARBS**: Add to TearSheet:
```python
def best_worst_policies(self, attribution_history, n=5):
    """Identify best and worst performing policies."""
    for policy, returns in attribution_history.items():
        mean_return = np.mean(returns)
        risk = np.std(returns)
        ir = mean_return / risk
        t_stat = mean_return / (risk / np.sqrt(len(returns)))
    
    # Rank by IR or t-statistic
    ...
```

---

## Application to ARBS Optimizer

### Current State

**Already have**:
- `Optimizer/MeanVarianceOptimizer.py`: Markowitz quadratic program
- `Risk/LedoitWolfShrinkage.py`: Covariance estimation
- `Analysis/TearSheet.py`: Basic performance metrics

### Need to Add

#### 1. Alpha Analysis (`Signals/AlphaNeutralizer.py`)

```python
class AlphaNeutralizer:
    """Preprocess alphas before portfolio construction.
    
    Methods
    -------
    scale: Scale alphas to match IC and volatility
    trim: Trim extreme alphas (> 3σ)
    benchmark_neutralize: Ensure α_B = 0
    industry_neutralize: Ensure α_industry = 0
    factor_neutralize: Ensure α_factor = 0
    """
    
    def scale(self, alphas, IC, volatilities):
        """Scale alphas to α = IC × σ × z."""
        expected_scale = IC * np.mean(volatilities)
        actual_scale = np.std(alphas)
        return alphas * (expected_scale / actual_scale)
    
    def trim(self, alphas, n_sigma=3):
        """Trim alphas beyond ±n_sigma × scale."""
        scale = np.std(alphas)
        threshold = n_sigma * scale
        return np.clip(alphas, -threshold, threshold)
    
    def benchmark_neutralize(self, alphas, benchmark_weights, betas):
        """Subtract β_i × α_B to ensure no benchmark timing."""
        alpha_B = np.sum(benchmark_weights * alphas)
        return alphas - betas * alpha_B
    
    def industry_neutralize(self, alphas, benchmark_weights, industry_map):
        """Subtract industry-average alphas (cap-weighted)."""
        neutralized = alphas.copy()
        for industry in np.unique(industry_map):
            mask = industry_map == industry
            # Cap-weighted average alpha for this industry
            industry_alpha = np.sum(
                benchmark_weights[mask] * alphas[mask]
            ) / np.sum(benchmark_weights[mask])
            neutralized[mask] -= industry_alpha
        return neutralized
```

#### 2. Constraint System (`Optimizer/constraints/`)

**Base class**:
```python
# Optimizer/constraints/BaseConstraint.py
class BaseConstraint(ABC):
    @abstractmethod
    def apply(self, problem_vars, benchmark_weights):
        """Return cvxpy constraint(s)."""
        pass
```

**Implementations**:
```python
# Optimizer/constraints/LongOnlyConstraint.py
class LongOnlyConstraint(BaseConstraint):
    def apply(self, weights, benchmark_weights):
        return [weights >= 0]

# Optimizer/constraints/SectorNeutralConstraint.py
class SectorNeutralConstraint(BaseConstraint):
    def __init__(self, sector_map):
        self.sector_map = sector_map
    
    def apply(self, weights, benchmark_weights):
        constraints = []
        for sector in np.unique(self.sector_map):
            mask = self.sector_map == sector
            active_sector = cp.sum(weights[mask]) - np.sum(benchmark_weights[mask])
            constraints.append(active_sector == 0)
        return constraints

# Optimizer/constraints/PositionLimitConstraint.py
class PositionLimitConstraint(BaseConstraint):
    def __init__(self, max_active_weight=0.05):
        self.max_active_weight = max_active_weight
    
    def apply(self, weights, benchmark_weights):
        active = weights - benchmark_weights
        return [
            active <= self.max_active_weight,
            active >= -self.max_active_weight
        ]
```

**Updated optimizer**:
```python
# Optimizer/MeanVarianceOptimizer.py
class MeanVarianceOptimizer:
    def __init__(self, risk_aversion=0.05, constraints=None):
        self.risk_aversion = risk_aversion
        self.constraints = constraints or []
    
    def optimize(self, alphas, cov_matrix, benchmark_weights, 
                 transaction_costs=None):
        N = len(alphas)
        weights = cp.Variable(N)
        
        # Objective
        alpha_term = weights @ alphas
        risk_term = cp.quad_form(weights, cov_matrix)
        objective = alpha_term - self.risk_aversion * risk_term
        
        # Add transaction costs if provided
        if transaction_costs is not None:
            tc_term = self._transaction_cost_term(weights, transaction_costs)
            objective -= tc_term
        
        # Apply constraints
        constraints = [cp.sum(weights) == 1]  # Full investment
        for constraint in self.constraints:
            constraints.extend(constraint.apply(weights, benchmark_weights))
        
        problem = cp.Problem(cp.Maximize(objective), constraints)
        problem.solve()
        
        return weights.value
```

#### 3. Transaction Cost Model (`TransactionCosts/`)

```python
# TransactionCosts/InventoryRiskModel.py
class InventoryRiskModel:
    """Estimate transaction costs using inventory risk approach.
    
    TC = c × σ × sqrt(V_trade / V_avg) + commissions
    
    References
    ----------
    Grinold & Kahn (1999), Chapter 16, Eq. 16.4
    """
    
    def __init__(self, c_tc=0.02, commission_bps=5):
        self.c_tc = c_tc
        self.commission_bps = commission_bps
    
    def estimate_cost(self, volume_traded, avg_daily_volume, 
                      sigma_annual):
        """Estimate one-way transaction cost (as fraction of price)."""
        if avg_daily_volume == 0:
            return 1.0  # Illiquid, cannot trade
        
        # Market impact
        sqrt_ratio = np.sqrt(volume_traded / avg_daily_volume)
        market_impact = self.c_tc * sigma_annual * sqrt_ratio
        
        # Commissions
        commission = self.commission_bps / 10000
        
        return market_impact + commission
    
    def estimate_portfolio_costs(self, trade_vector, avg_volumes, 
                                  volatilities, current_weights):
        """Estimate total portfolio rebalancing cost.
        
        Parameters
        ----------
        trade_vector : array
            Desired change in weights: w_new - w_old
        avg_volumes : array
            Average daily trading volumes (in shares or $)
        volatilities : array
            Annual volatilities
        current_weights : array
            Current portfolio weights (to convert to volume)
        
        Returns
        -------
        total_cost : float
            Total transaction cost (as fraction of portfolio value)
        """
        costs = np.zeros(len(trade_vector))
        for i, trade in enumerate(trade_vector):
            if trade == 0:
                continue
            
            volume = abs(trade)  # Simplified
            cost = self.estimate_cost(
                volume, avg_volumes[i], volatilities[i]
            )
            costs[i] = cost * abs(trade)
        
        return np.sum(costs)
```

#### 4. Enhanced Performance Attribution

```python
# Analysis/PerformanceAttribution.py
class PerformanceAttribution:
    """Attribute portfolio returns to systematic, factor, and specific components.
    
    Implements Grinold-Kahn Chapter 17 methodology.
    """
    
    def attribute_period(self, portfolio_weights, benchmark_weights,
                         factor_exposures, factor_returns,
                         specific_returns, benchmark_return):
        """Attribute returns for a single period.
        
        Returns
        -------
        attribution : dict
            {
                'active_systematic': β_PA × γ_B,
                'factor_contributions': {factor_name: contribution},
                'specific': u_PA
            }
        """
        active_weights = portfolio_weights - benchmark_weights
        
        # Active beta
        beta_PA = self._calculate_active_beta(
            portfolio_weights, benchmark_weights, factor_exposures
        )
        
        # Systematic
        systematic = beta_PA * benchmark_return
        
        # Factor contributions
        factor_contrib = {}
        for j, factor_name in enumerate(factor_exposures.columns):
            x_PAj = np.sum(active_weights * factor_exposures.iloc[:, j])
            factor_contrib[factor_name] = x_PAj * factor_returns[j]
        
        # Specific
        specific = np.sum(active_weights * specific_returns)
        
        return {
            'active_systematic': systematic,
            'factor_contributions': factor_contrib,
            'specific': specific
        }
    
    def attribute_timeseries(self, attribution_history):
        """Analyze time series of attributions.
        
        Returns
        -------
        analysis : dict
            For each component: mean, std, IR, t-statistic
        """
        results = {}
        
        for component, returns in attribution_history.items():
            mean = np.mean(returns)
            std = np.std(returns)
            ir = mean / std if std > 0 else 0
            t_stat = mean / (std / np.sqrt(len(returns))) if std > 0 else 0
            
            results[component] = {
                'mean_return': mean,
                'risk': std,
                'information_ratio': ir,
                't_statistic': t_stat
            }
        
        return results
```

---

## Constraints for Equity Portfolios (Summary)

### Essential Constraints

1. **Long-only**: `h_i ≥ 0`
2. **Full investment**: `Σ h_i = 1`
3. **Beta = 1**: `Σ h_i × β_i = 1` (no benchmark timing)

### Risk Control Constraints

4. **Sector-neutral**: `Σ_{i ∈ sector s} (h_i - h_Bi) = 0` for each sector
5. **Factor-neutral**: `Σ_i h_i × x_ij = Σ_i h_Bi × x_ij` for each risk factor j
6. **Position limits**: `|h_i - h_Bi| ≤ w_max` (typically w_max = 0.05)

### Transaction Cost Constraints

7. **Turnover limit**: `Σ_i |h_i - h_i^old| ≤ TO_max`
8. **Minimum trade size**: Don't trade if `|h_i - h_i^old| < threshold`

### Implementation in ARBS

**cvxpy formulation**:
```python
import cvxpy as cp

# Decision variable
weights = cp.Variable(N)

# Constraints
constraints = [
    cp.sum(weights) == 1,  # Full investment
    weights >= 0,  # Long-only
]

# Sector-neutral (if desired)
for sector in sectors:
    mask = sector_map == sector
    constraints.append(
        cp.sum(weights[mask]) == np.sum(benchmark_weights[mask])
    )

# Position limits
active = weights - benchmark_weights
constraints.extend([
    active <= max_active_weight,
    active >= -max_active_weight
])

# Objective
alpha_term = weights @ alphas
risk_term = cp.quad_form(weights, cov_matrix)
objective = alpha_term - risk_aversion * risk_term

# Solve
problem = cp.Problem(cp.Maximize(objective), constraints)
problem.solve()
```

---

## Transaction Cost Integration (Summary)

### Model Choice: Inventory Risk (Square Root)

**Formula**:
```
TC_i = c × σ_i × sqrt(V_trade,i / V_avg,i) + commission
```

**Advantages**:
- Matches empirical evidence (Loeb 1983)
- Simple to implement
- Captures key insight: larger trades → higher impact

**Disadvantage**: Doesn't capture all market microstructure effects (but neither do complex models).

### Integration with Optimizer

**Option 1: Piecewise Linear Approximation**

For cvxpy, approximate sqrt function:
```python
# Approximate sqrt(x) as piecewise linear
breakpoints = [0, 0.01, 0.05, 0.10, 0.20, 0.50]
slopes = [...] # Computed from sqrt derivative

tc_cost = sum([slope * cp.max(abs(trade) - bp, 0) 
               for bp, slope in zip(breakpoints, slopes)])
```

**Option 2: Quadratic Approximation**

Approximate market impact as quadratic:
```
MI ≈ a × V_trade + b × V_trade^2
```

Then:
```python
trade = weights - old_weights
tc_cost = cp.sum(a * cp.abs(trade) + b * cp.square(trade))
```

**Option 3: Turnover Constraint (Simplest)**

Don't model TC in objective, just constrain turnover:
```python
constraints.append(cp.sum(cp.abs(weights - old_weights)) <= TO_max)
```

Then find optimal TO_max empirically (where SLOPE(TO) = TC).

---

## Links to Existing Code

### Current ARBS Architecture

```
Query/ → Adapter/ → Returns/ → Volatility/ → Signals/ → Risk/ → Optimizer/ → Portfolio/ → Analysis/
```

### Additions for Equities

```
Signals/
├── AlphaNeutralizer.py          # NEW: Scale, trim, neutralize alphas
└── AlphaGenerator.py             # EXISTS: IC × Vol × Z

Optimizer/
├── MeanVarianceOptimizer.py      # EXISTS: Need to extend with constraints
└── constraints/                  # NEW: Constraint system
    ├── BaseConstraint.py
    ├── LongOnlyConstraint.py
    ├── SectorNeutralConstraint.py
    ├── PositionLimitConstraint.py
    └── TurnoverConstraint.py

TransactionCosts/                 # NEW: TC modeling
├── InventoryRiskModel.py
└── TurnoverOptimizer.py

Analysis/
├── TearSheet.py                  # EXISTS: Need to extend
└── PerformanceAttribution.py     # NEW: Factor attribution
```

---

## Open Questions

### 1. Transaction Cost Model: How Detailed?

**Options**:
- **Simple**: c × σ × sqrt(V_trade / V_avg) + commission
  - Pros: Easy to implement, captures 80% of effect
  - Cons: Ignores time-of-day effects, exchange vs OTC, elasticity
  
- **Structural** (BARRA-style):
  - Pros: More accurate, handles edge cases
  - Cons: Complex, requires more data (trade frequency, elasticity)

**Recommendation**: Start with **simple inventory risk model**. Extend later if needed.

### 2. Constraints: Which to Include by Default?

**Must-have**:
- Long-only
- Full investment

**Optional** (strategy-dependent):
- Sector-neutral (for sector-agnostic strategies)
- Factor-neutral (if no factor views)
- Position limits (if risk control needed)

**Recommendation**: Make constraints **configurable** via StrategyConfig YAML.

### 3. Corporate Actions: How to Handle?

**Splits**: Adjust prices, shares outstanding
**Dividends**: 
- **Total return**: Reinvest dividends (standard)
- **Price return**: Ignore dividends (not recommended)

**ARBS**: Use **total returns** (industry standard). Data provider should handle adjustments.

### 4. Rebalancing Frequency?

**Trade-off**:
- **Daily**: More responsive, higher TC
- **Weekly**: Moderate
- **Monthly**: Lower TC, less responsive

**Rule** (from Ch 14, p. 393): Rebalance when:
```
|MCVA_n| > TC_n
```

where MCVA = marginal contribution to value added.

**For equities**: Monthly or quarterly rebalancing typical (lower TC).

**Recommendation**: Start with **monthly**, make configurable.

---

## Implementation Roadmap

### Phase 1: Alpha Preprocessing (1 week)
- [ ] Implement `AlphaNeutralizer.py`
- [ ] Add scaling, trimming, benchmark/industry neutralization
- [ ] Tests for each method

### Phase 2: Constraint System (2 weeks)
- [ ] Design `BaseConstraint` interface
- [ ] Implement LongOnly, SectorNeutral, PositionLimit
- [ ] Extend `MeanVarianceOptimizer` to accept constraints
- [ ] Tests with various constraint combinations

### Phase 3: Transaction Costs (2 weeks)
- [ ] Implement `InventoryRiskModel`
- [ ] Add TC estimation for individual stocks
- [ ] Add TC integration with optimizer (turnover constraint or objective)
- [ ] Tests comparing different approaches

### Phase 4: Performance Attribution (1 week)
- [ ] Implement `PerformanceAttribution.py`
- [ ] Extend `TearSheet` with factor decomposition
- [ ] Add best/worst policy analysis
- [ ] Tests with synthetic factor returns

### Phase 5: Integration Testing (1 week)
- [ ] End-to-end test: alphas → neutralization → optimization → attribution
- [ ] Verify constraint enforcement
- [ ] Verify TC integration
- [ ] Performance benchmarks

**Total**: ~7 weeks for complete equity extension.

---

## Key Formulas Reference

### Alpha Analysis
- **Alpha structure**: α = IC × σ × z
- **Benchmark neutralization**: α_i^BN = α_i - β_i × α_B
- **Modified alphas**: α+ = 2λ_A × V × h_PA

### Constraints
- **Long-only**: h_i ≥ 0
- **Sector-neutral**: Σ_{i ∈ s} (h_i - h_Bi) = 0
- **Position limit**: |h_i - h_Bi| ≤ w_max

### Transaction Costs
- **Inventory risk**: TC = c × σ × sqrt(V_trade / V_avg) + commission
- **Turnover/VA**: VA(TO) ≥ VA_I + (TO/TO_Q)² × ΔVA_Q
- **Optimal TO**: SLOPE(TO*) = TC

### Performance Attribution
- **Active return**: r_PA = β_PA × γ_B + Σ_j x_PAj^R × f_j + u_PA
- **Residual exposure**: x_PAj^R = x_PAj - β_PA × x_Bj
- **T-statistic**: t = α / (ω / sqrt(T))

---

## References

- Grinold, R.C., and Kahn, R.N. (1999). *Active Portfolio Management*, 2nd ed., Chapter 14-17.
- Loeb, T.F. (1983). "Trading Costs: The Critical Link." *FAJ*.
- Perold, A. (1988). "The Implementation Shortfall." *JPM*.
- BARRA (1997). *Market Impact Model Handbook*.

