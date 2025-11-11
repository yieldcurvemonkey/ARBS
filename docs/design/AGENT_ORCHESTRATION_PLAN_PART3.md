# Agent Orchestration Plan Part 3: Waves 5-6 (Optimization & Integration)

**Continuation of**: `AGENT_ORCHESTRATION_PLAN_PART2.md`
**Covers**: AGENT-18 through AGENT-20 (Weeks 12-17, Final Integration)

---

## WAVE 5: LONG/SHORT OPTIMIZATION (Weeks 12-14)

**2 agents in parallel** - Market-neutral portfolio optimization

---

### AGENT-18: Long/Short Optimizer with Constraints

**Objective**: Implement long/short market-neutral optimizer with sector-neutral and position limit constraints.

**Starting Context**:
1. `docs/design/LONG_SHORT_STRATEGY_DESIGN.md` (AGENT-04 output)
2. `Optimizer/MeanVarianceOptimizer.py` (existing optimizer to extend)
3. `docs/books/grinold_kahn_equity_notes_part4_implementation.md` (Chapter 14-15)
4. `Signals/Equities/ValueSignal.py` (AGENT-10 output, sector-neutral alphas)
5. `Risk/Covariance/PPFMCovariance.py` (AGENT-17 output, covariance matrix)

**Skills Required**:
- Convex optimization (CVXPY library)
- Constraint design
- Long/short portfolio theory
- Test-driven development

**Deliverables**:
```
Optimizer/constraints/__init__.py
Optimizer/constraints/MarketNeutralConstraint.py
Optimizer/constraints/SectorNeutralConstraint.py
Optimizer/constraints/PositionLimitConstraint.py
Optimizer/constraints/GrossLeverageConstraint.py
Optimizer/LongShortOptimizer.py

tests/unit/optimizer/test_long_short_optimizer.py (30 tests)
tests/integration/test_long_short_vs_long_only.py (10 tests)
```

**Implementation Guidance**:
```python
# Optimizer/constraints/MarketNeutralConstraint.py

# ABOUTME: Market-neutral constraint for long/short portfolios
# ABOUTME: Zero net dollar exposure and zero net market beta exposure

import cvxpy as cp
import numpy as np

class MarketNeutralConstraint:
    """
    Market-neutral constraint: Σ w_i = 0 (dollar-neutral)

    Optional: Σ w_i · β_i^market = 0 (beta-neutral, stronger)
    """

    def __init__(self, beta_neutral: bool = False):
        self.beta_neutral = beta_neutral

    def apply(self, w: cp.Variable, market_betas: np.ndarray = None) -> list:
        """
        Apply market-neutral constraints

        Args:
            w: Weight variable (N×1)
            market_betas: Market betas (N×1, optional for beta-neutral)

        Returns:
            List of constraints for CVXPY
        """
        constraints = []

        # Dollar-neutral
        constraints.append(cp.sum(w) == 0)

        # Beta-neutral (optional, more strict)
        if self.beta_neutral and market_betas is not None:
            constraints.append(w @ market_betas == 0)

        return constraints


# Optimizer/constraints/SectorNeutralConstraint.py

# ABOUTME: Sector-neutral constraint for long/short portfolios
# ABOUTME: Zero net exposure to each sector factor

class SectorNeutralConstraint:
    """
    Sector-neutral constraint: Σ_{i ∈ sector_s} w_i = 0 for each sector s

    Ensures portfolio is hedged against sector moves:
    - Long high-quality stocks in tech, short low-quality in tech → net tech = 0
    - Long high-momentum in finance, short low-momentum in finance → net finance = 0
    """

    def __init__(self, sector_labels: list):
        """
        Args:
            sector_labels: List of sector names for each stock (length N)
        """
        self.sectors = np.array(sector_labels)
        self.unique_sectors = np.unique(self.sectors)

    def apply(self, w: cp.Variable) -> list:
        """Apply sector-neutral constraints"""
        constraints = []

        for sector in self.unique_sectors:
            # Mask for stocks in this sector
            mask = (self.sectors == sector)

            # Constraint: sum of weights in this sector = 0
            constraints.append(cp.sum(w[mask]) == 0)

        return constraints


# Optimizer/constraints/PositionLimitConstraint.py

# ABOUTME: Position limit constraint for risk control
# ABOUTME: Limits individual stock positions (long or short)

class PositionLimitConstraint:
    """
    Position limit: |w_i| ≤ w_max for all i

    Prevents over-concentration in single stocks
    Typical: w_max = 0.05 (5% of portfolio, either long or short)
    """

    def __init__(self, max_weight: float = 0.05):
        self.max_weight = max_weight

    def apply(self, w: cp.Variable) -> list:
        """Apply position limits"""
        constraints = [
            w <= self.max_weight,  # Long position limit
            w >= -self.max_weight,  # Short position limit (symmetric)
        ]

        return constraints


# Optimizer/constraints/GrossLeverageConstraint.py

# ABOUTME: Gross leverage constraint for long/short portfolios
# ABOUTME: Limits total gross exposure (sum of absolute weights)

class GrossLeverageConstraint:
    """
    Gross leverage: Σ |w_i| ≤ L_max

    Example: L_max = 2.0 means 100% long, 100% short (200% gross)
    Typical ranges:
        - Conservative: 1.3 (65% long, 65% short)
        - Moderate: 2.0 (100% long, 100% short)
        - Aggressive: 3.0 (150% long, 150% short)
    """

    def __init__(self, max_gross_leverage: float = 2.0):
        self.max_gross = max_gross_leverage

    def apply(self, w: cp.Variable) -> list:
        """
        Apply gross leverage constraint

        Note: |w_i| is not convex, so we use variable splitting:
            w_i = w_i^+ - w_i^-
            |w_i| = w_i^+ + w_i^-
        """
        N = w.shape[0]

        # Split into long/short components
        w_long = cp.Variable(N, nonneg=True)
        w_short = cp.Variable(N, nonneg=True)

        constraints = [
            w == w_long - w_short,  # Original weights
            cp.sum(w_long + w_short) <= self.max_gross,  # Gross exposure
        ]

        return constraints


# Optimizer/LongShortOptimizer.py

# ABOUTME: Long/short market-neutral portfolio optimizer
# ABOUTME: Extends MeanVarianceOptimizer with long/short constraints

import cvxpy as cp
import numpy as np
import polars as pl
from typing import List
from Optimizer.MeanVarianceOptimizer import MeanVarianceOptimizer
from Optimizer.constraints import *

class LongShortOptimizer(MeanVarianceOptimizer):
    """
    Long/short market-neutral optimizer

    Objective:
        max: α^T w - λ w^T Σ w - κ TC(w, w_old)

    Constraints:
        - Market-neutral: Σ w_i = 0
        - Sector-neutral: Σ_{i ∈ sector} w_i = 0 for each sector
        - Position limits: |w_i| ≤ w_max
        - Gross leverage: Σ |w_i| ≤ L_max

    Key difference from long-only:
        - No long-only constraint (w_i ≥ 0)
        - Transfer coefficient TC ≈ 0.85 (vs 0.5 for long-only)
        - Expected IR much higher (no 50% IR cut!)
    """

    def __init__(
        self,
        risk_aversion: float = 1.0,
        tc_penalty: float = 0.5,
        constraints: List = None,
    ):
        super().__init__(risk_aversion, tc_penalty)
        self.constraints = constraints or []

    def optimize(
        self,
        alphas: pl.Series,  # Expected returns (sector-neutralized!)
        covariance: pl.DataFrame,  # Risk model
        sector_labels: List[str],  # For sector-neutral constraint
        old_weights: pl.Series = None,  # For turnover penalty
        market_betas: pl.Series = None,  # For beta-neutral constraint
    ) -> pl.Series:
        """
        Optimize long/short portfolio

        CRITICAL: Alphas MUST be sector-neutralized before passing here!
        Use signal.validate_sector_neutrality() to check.

        Returns:
            Optimal weights (sum to zero, sector-neutral)
        """
        N = len(alphas)

        # Convert to numpy
        alpha_vec = alphas.to_numpy()
        Sigma = covariance.to_numpy()

        # Define optimization variable
        w = cp.Variable(N)

        # Objective
        portfolio_alpha = alpha_vec @ w
        portfolio_risk = cp.quad_form(w, Sigma)

        objective = portfolio_alpha - self.risk_aversion * portfolio_risk

        # Add turnover penalty if old weights provided
        if old_weights is not None:
            w_old = old_weights.to_numpy()
            turnover = cp.norm1(w - w_old)  # L1 norm (sum of absolute changes)
            objective -= self.tc_penalty * turnover

        # Apply constraints
        constraint_list = []

        # Default constraints (always applied)
        constraint_list.extend(MarketNeutralConstraint().apply(w))
        constraint_list.extend(SectorNeutralConstraint(sector_labels).apply(w))

        # Additional constraints
        for constraint in self.constraints:
            constraint_list.extend(constraint.apply(w, market_betas))

        # Solve
        problem = cp.Problem(cp.Maximize(objective), constraint_list)
        problem.solve(solver=cp.CLARABEL)  # Fast open-source solver

        if problem.status not in ["optimal", "optimal_inaccurate"]:
            raise RuntimeError(f"Optimization failed with status: {problem.status}")

        # Return optimal weights as Polars Series
        optimal_weights = pl.Series(w.value)

        # Validate sector-neutrality (critical check!)
        self._validate_sector_neutrality(optimal_weights, sector_labels)

        return optimal_weights

    def _validate_sector_neutrality(
        self, weights: pl.Series, sectors: List[str], tolerance: float = 1e-6
    ):
        """
        Validate that portfolio is sector-neutral

        Raises ValueError if any sector has net exposure > tolerance
        """
        df = pl.DataFrame({"weight": weights, "sector": sectors})

        sector_exposures = df.group_by("sector").agg(
            pl.col("weight").sum().alias("net_exposure")
        )

        violating_sectors = sector_exposures.filter(
            pl.col("net_exposure").abs() > tolerance
        )

        if len(violating_sectors) > 0:
            raise ValueError(
                f"Portfolio not sector-neutral! {len(violating_sectors)} sectors have net exposure:\n"
                f"{violating_sectors}"
            )

    def calculate_transfer_coefficient(
        self,
        unconstrained_weights: pl.Series,
        constrained_weights: pl.Series,
        alphas: pl.Series,
    ) -> float:
        """
        Calculate transfer coefficient TC

        From Grinold-Kahn Chapter 15:
            TC = IC(constrained_weights, alphas) / IC(unconstrained_weights, alphas)

        Measures how much constraints reduce ability to follow alphas

        Expected:
            - Unconstrained: TC = 1.0
            - Long/short sector-neutral: TC ≈ 0.85 (15% loss)
            - Long-only: TC ≈ 0.5 (50% loss!)
        """
        ic_unconstrained = unconstrained_weights.corr(alphas)
        ic_constrained = constrained_weights.corr(alphas)

        tc = ic_constrained / ic_unconstrained

        return tc
```

**Testing Strategy**:
```python
# tests/unit/optimizer/test_long_short_optimizer.py

def test_market_neutral_constraint():
    """Test market-neutral constraint works"""
    optimizer = LongShortOptimizer()

    # Create test data
    alphas = pl.Series([0.02, 0.01, -0.01, -0.02])  # Sector-neutral
    sectors = ["Tech", "Tech", "Finance", "Finance"]
    cov = create_test_covariance(n=4)

    weights = optimizer.optimize(alphas, cov, sectors)

    # Check market-neutral
    assert abs(weights.sum()) < 1e-6, f"Portfolio not market-neutral: sum = {weights.sum()}"

def test_sector_neutral_constraint():
    """Test sector-neutral constraint works"""
    optimizer = LongShortOptimizer()

    alphas = pl.Series([0.02, 0.01, -0.01, -0.02])
    sectors = ["Tech", "Tech", "Finance", "Finance"]
    cov = create_test_covariance(n=4)

    weights = optimizer.optimize(alphas, cov, sectors)

    # Check sector-neutral
    df = pl.DataFrame({"weight": weights, "sector": sectors})
    tech_exposure = df.filter(pl.col("sector") == "Tech")["weight"].sum()
    finance_exposure = df.filter(pl.col("sector") == "Finance")["weight"].sum()

    assert abs(tech_exposure) < 1e-6, f"Tech net exposure: {tech_exposure}"
    assert abs(finance_exposure) < 1e-6, f"Finance net exposure: {finance_exposure}"

def test_position_limit_constraint():
    """Test position limit constraint works"""
    optimizer = LongShortOptimizer(
        constraints=[PositionLimitConstraint(max_weight=0.05)]
    )

    alphas = pl.Series([0.10, 0.05, -0.05, -0.10])  # Strong alphas
    sectors = ["Tech", "Tech", "Finance", "Finance"]
    cov = create_test_covariance(n=4)

    weights = optimizer.optimize(alphas, cov, sectors)

    # Check all positions within limit
    assert (weights.abs() <= 0.05 + 1e-6).all(), f"Position limit violated: {weights}"

def test_gross_leverage_constraint():
    """Test gross leverage constraint works"""
    optimizer = LongShortOptimizer(
        constraints=[GrossLeverageConstraint(max_gross_leverage=2.0)]
    )

    alphas = pl.Series([0.02, 0.01, -0.01, -0.02])
    sectors = ["Tech", "Tech", "Finance", "Finance"]
    cov = create_test_covariance(n=4)

    weights = optimizer.optimize(alphas, cov, sectors)

    # Check gross leverage
    gross = weights.abs().sum()
    assert gross <= 2.0 + 1e-6, f"Gross leverage {gross} exceeds 2.0"

def test_transfer_coefficient_long_short():
    """Test transfer coefficient for long/short is higher than long-only"""
    optimizer = LongShortOptimizer()

    alphas = pl.Series([0.02, 0.01, -0.01, -0.02])
    sectors = ["Tech", "Tech", "Finance", "Finance"]
    cov = create_test_covariance(n=4)

    # Optimize with no constraints (unconstrained)
    unconstrained_weights = optimizer.optimize(alphas, cov, sectors)

    # Optimize with constraints
    constrained_weights = optimizer.optimize(
        alphas, cov, sectors,
        constraints=[PositionLimitConstraint(0.05)]
    )

    # Calculate TC
    tc = optimizer.calculate_transfer_coefficient(
        unconstrained_weights, constrained_weights, alphas
    )

    # Long/short TC should be high (>0.8)
    assert tc > 0.8, f"Transfer coefficient {tc} too low (expected >0.8)"

    print(f"Transfer coefficient (long/short): {tc:.2f}")

# tests/integration/test_long_short_vs_long_only.py

@pytest.mark.integration
def test_long_short_vs_long_only_ir():
    """
    Compare long/short vs long-only on same data

    From Grinold-Kahn Chapter 15:
        - Long-only: TC ≈ 0.5 (IR cut by 50%)
        - Long/short: TC ≈ 0.85 (IR cut by 15%)

    Expected: Long/short achieves ~70% higher IR
    """
    # Load historical data
    data = load_russell_3000_historical_data(start=date(2018, 1, 1), end=date(2023, 12, 31))

    # Generate alphas (sector-neutral)
    alphas = generate_test_alphas(data)

    # Estimate covariance
    cov = estimate_covariance(data)

    # Optimize long/short
    optimizer_ls = LongShortOptimizer()
    weights_ls = optimizer_ls.optimize(alphas, cov, data["sector"])

    # Optimize long-only
    optimizer_lo = LongOnlyOptimizer()
    weights_lo = optimizer_lo.optimize(alphas, cov)

    # Calculate realized returns
    returns_ls = calculate_portfolio_returns(weights_ls, data)
    returns_lo = calculate_portfolio_returns(weights_lo, data)

    # Calculate IRs
    ir_ls = returns_ls.mean() / returns_ls.std()
    ir_lo = returns_lo.mean() / returns_lo.std()

    print(f"Long/short IR: {ir_ls:.2f}")
    print(f"Long-only IR: {ir_lo:.2f}")
    print(f"IR ratio: {ir_ls / ir_lo:.2f}")

    # Assert long/short IR is significantly higher
    assert ir_ls > ir_lo * 1.5, f"Long/short IR not sufficiently higher than long-only"

# ... 27 more tests
```

**Success Criteria**:
- [ ] `LongShortOptimizer` implemented with all constraints
- [ ] Market-neutral: Σ w_i = 0 validated
- [ ] Sector-neutral: Σ w_i per sector = 0 validated
- [ ] Position limits enforced
- [ ] Gross leverage constraint working
- [ ] Transfer coefficient TC ≈ 0.85 measured (vs 0.5 for long-only)
- [ ] 40 tests passing (30 unit + 10 integration)
- [ ] Committed and pushed

---

### AGENT-19: Transaction Cost Integration

**Objective**: Integrate transaction cost model (square-root law) with optimizer.

**Starting Context**:
1. `docs/books/grinold_kahn_equity_notes_part4_implementation.md` (Chapter 16)
2. `docs/books/GRINOLD_KAHN_EQUITY_SUMMARY.md` (Section: Transaction Costs)
3. `Optimizer/LongShortOptimizer.py` (AGENT-18 output)
4. `Adapter/EquityAdapter.py` (AGENT-09 output, has avg_volume)

**Skills Required**:
- Transaction cost modeling
- Square-root law (Loeb 1983)
- Integration with optimizer
- Test-driven development

**Deliverables**:
```
TransactionCosts/__init__.py
TransactionCosts/InventoryRiskModel.py
TransactionCosts/TurnoverAnalysis.py

tests/unit/transaction_costs/test_inventory_risk_model.py (20 tests)
tests/integration/test_tc_optimizer_integration.py (10 tests)
```

**Implementation Guidance**:
```python
# TransactionCosts/InventoryRiskModel.py

# ABOUTME: Transaction cost model using square-root law (Loeb 1983)
# ABOUTME: TC = c·σ·√(V_trade/V_avg) + commission

import polars as pl
import numpy as np

class InventoryRiskModel:
    """
    Transaction cost model based on inventory risk

    From Grinold-Kahn Chapter 16:
        TC_i = c · σ_i · √(V_trade,i / V_avg,i) + commission

    Where:
        c = cost coefficient (typically 1.0)
        σ_i = daily volatility (%)
        V_trade,i = shares to trade
        V_avg,i = average daily volume
        commission = fixed cost per share (e.g., 0.1%)

    Square-root law (Loeb 1983):
        Market impact ∝ √(trade size)

    Empirical rule: Costs ~1 day's volatility to trade 1 day's volume
    """

    def __init__(self, cost_coefficient: float = 1.0, commission_rate: float = 0.001):
        """
        Args:
            cost_coefficient: Typically 1.0 (1 day vol for 1 day volume)
            commission_rate: Fixed commission (bps), e.g., 0.001 = 10 bps
        """
        self.c = cost_coefficient
        self.commission = commission_rate

    def calculate_cost(
        self,
        trade_sizes: pl.Series,  # Shares to trade (can be negative for short)
        avg_daily_volumes: pl.Series,  # Average daily volume
        volatilities: pl.Series,  # Daily volatility (%)
    ) -> pl.Series:
        """
        Calculate total transaction cost per stock

        Returns:
            TC per stock (as % of trade value)
        """
        # Market impact (square-root law)
        volume_fraction = trade_sizes.abs() / avg_daily_volumes
        impact = self.c * volatilities * volume_fraction.sqrt()

        # Commission (proportional)
        commission_cost = self.commission * trade_sizes.abs() / trade_sizes.abs()  # Always commission_rate

        # Total
        total_cost = impact + commission_cost

        return total_cost

    def calculate_portfolio_tc(
        self,
        current_weights: pl.Series,
        target_weights: pl.Series,
        portfolio_value: float,
        avg_daily_volumes: pl.Series,
        volatilities: pl.Series,
        prices: pl.Series,
    ) -> float:
        """
        Calculate total portfolio transaction cost for rebalancing

        Returns:
            Total TC ($ amount)
        """
        # Shares to trade
        weight_changes = target_weights - current_weights
        dollar_changes = weight_changes * portfolio_value
        shares_to_trade = dollar_changes / prices

        # Cost per stock (%)
        tc_pct = self.calculate_cost(shares_to_trade, avg_daily_volumes, volatilities)

        # Total cost ($)
        total_tc = (tc_pct * dollar_changes.abs()).sum()

        return total_tc

    def turnover_value_added_frontier(
        self,
        alphas: pl.Series,
        covariance: pl.DataFrame,
        turnover_levels: list,  # [0.0, 0.5, 1.0, 1.5, 2.0]
    ) -> pl.DataFrame:
        """
        Compute turnover/value-added frontier

        From Grinold-Kahn Chapter 16:
            - Can achieve 75% of value-added with 50% of turnover
            - Key insight: First few trades most valuable, marginal trades costly

        Returns DataFrame:
            - turnover_limit: float
            - portfolio_alpha: float (expected value-added)
            - transaction_cost: float (expected cost)
            - net_alpha: float (alpha - TC)
        """
        results = []

        for turnover_limit in turnover_levels:
            # Optimize with turnover constraint
            optimizer = LongShortOptimizer(
                tc_penalty=0.5,
                constraints=[TurnoverConstraint(max_turnover=turnover_limit)]
            )

            weights = optimizer.optimize(alphas, covariance)

            # Calculate metrics
            portfolio_alpha = (weights * alphas).sum()
            tc = self.calculate_portfolio_tc(...)  # Calculate TC
            net_alpha = portfolio_alpha - tc

            results.append({
                "turnover_limit": turnover_limit,
                "portfolio_alpha": portfolio_alpha,
                "transaction_cost": tc,
                "net_alpha": net_alpha,
            })

        return pl.DataFrame(results)


# TransactionCosts/TurnoverAnalysis.py

# ABOUTME: Turnover analysis and optimization utilities
# ABOUTME: Helps find optimal turnover/value-added trade-off

import polars as pl
import matplotlib.pyplot as plt

class TurnoverAnalysis:
    """
    Analyze turnover and value-added trade-offs

    Key metrics:
    - Turnover: Σ |w_t - w_{t-1}|
    - One-way turnover: Turnover / 2
    - Holding period: 1 / turnover (in months)

    Typical ranges:
    - Conservative: 100% annual turnover (6-month hold)
    - Moderate: 200% annual turnover (3-month hold)
    - Aggressive: 400% annual turnover (1.5-month hold)
    """

    @staticmethod
    def calculate_turnover(
        old_weights: pl.Series,
        new_weights: pl.Series,
    ) -> float:
        """
        Calculate portfolio turnover

        Returns:
            Turnover (sum of absolute weight changes)
        """
        return (new_weights - old_weights).abs().sum()

    @staticmethod
    def calculate_holding_period(annual_turnover: float) -> float:
        """
        Calculate average holding period in months

        holding_period = 12 / turnover
        """
        return 12 / annual_turnover

    @staticmethod
    def plot_turnover_frontier(frontier_df: pl.DataFrame):
        """
        Plot turnover/value-added frontier

        X-axis: Turnover
        Y-axis: Net alpha (gross alpha - TC)
        """
        plt.figure(figsize=(10, 6))

        plt.plot(
            frontier_df["turnover_limit"],
            frontier_df["portfolio_alpha"],
            label="Gross Alpha (no TC)",
            marker='o'
        )

        plt.plot(
            frontier_df["turnover_limit"],
            frontier_df["net_alpha"],
            label="Net Alpha (after TC)",
            marker='s'
        )

        plt.axhline(y=0, color='k', linestyle='--', alpha=0.3)

        plt.xlabel("Turnover Limit (annual)")
        plt.ylabel("Alpha (%)")
        plt.title("Turnover / Value-Added Frontier")
        plt.legend()
        plt.grid(True, alpha=0.3)

        plt.savefig("turnover_frontier.png")
```

**Testing Strategy**:
```python
# tests/unit/transaction_costs/test_inventory_risk_model.py

def test_square_root_law():
    """Test square-root scaling of market impact"""
    model = InventoryRiskModel()

    # Trade 1% of volume
    tc_1pct = model.calculate_cost(
        trade_sizes=pl.Series([1000]),
        avg_daily_volumes=pl.Series([100000]),  # 1% trade
        volatilities=pl.Series([0.02]),  # 2% daily vol
    )

    # Trade 4% of volume (4× size)
    tc_4pct = model.calculate_cost(
        trade_sizes=pl.Series([4000]),
        avg_daily_volumes=pl.Series([100000]),  # 4% trade
        volatilities=pl.Series([0.02]),
    )

    # Square-root law: 4× size → 2× cost (not 4×!)
    ratio = tc_4pct[0] / tc_1pct[0]

    # Should be close to 2.0 (√4 = 2)
    assert 1.9 < ratio < 2.1, f"Square-root law violated: ratio = {ratio}"

def test_one_day_volume_one_day_vol():
    """Test empirical rule: 1 day's volume costs ~1 day's vol"""
    model = InventoryRiskModel(cost_coefficient=1.0)

    # Trade exactly 1 day's volume
    tc = model.calculate_cost(
        trade_sizes=pl.Series([100000]),
        avg_daily_volumes=pl.Series([100000]),  # 100% trade
        volatilities=pl.Series([0.02]),  # 2% daily vol
    )

    # Should be close to 2% (volatility + commission)
    expected = 0.02 + 0.001  # 2% impact + 0.1% commission
    assert abs(tc[0] - expected) < 0.001, f"TC {tc[0]:.4f} != expected {expected:.4f}"

def test_turnover_frontier():
    """Test turnover/value-added frontier"""
    model = InventoryRiskModel()

    # Create test alphas and covariance
    alphas = create_test_alphas()
    cov = create_test_covariance()

    # Compute frontier
    frontier = model.turnover_value_added_frontier(
        alphas, cov, turnover_levels=[0.5, 1.0, 1.5, 2.0]
    )

    # Check properties:
    # 1. Higher turnover → higher gross alpha
    assert frontier["portfolio_alpha"].is_sorted()

    # 2. Net alpha may plateau or decline at high turnover (TC dominates)
    # Find maximum net alpha
    max_net_alpha_idx = frontier["net_alpha"].arg_max()

    print(f"Optimal turnover: {frontier['turnover_limit'][max_net_alpha_idx]}")

# ... 17 more tests
```

**Success Criteria**:
- [ ] `InventoryRiskModel` implemented (square-root law)
- [ ] Square-root scaling validated (4× trade → 2× cost)
- [ ] Empirical rule validated (1 day volume → 1 day vol cost)
- [ ] Turnover frontier computed
- [ ] Optimizer integration working (turnover penalty in objective)
- [ ] 30 tests passing (20 unit + 10 integration)
- [ ] Committed and pushed

---

## WAVE 6: END-TO-END INTEGRATION & VALIDATION (Weeks 15-17)

**1 agent** - Final integration, validation, documentation

---

### AGENT-20: End-to-End Integration & Validation

**Objective**: Integrate all components into end-to-end pipeline, validate against Grinold-Kahn targets and paper benchmarks, create comprehensive documentation.

**Starting Context**:
1. All previous agent outputs (AGENT-01 through AGENT-19)
2. `docs/design/EQUITY_SECTOR_IMPLEMENTATION_PLAN.md` (Phase 6)
3. `docs/books/GRINOLD_KAHN_EQUITY_SUMMARY.md` (validation targets)
4. `examples/run_minimal_backtest.py` (existing pattern)

**Skills Required**:
- End-to-end integration
- Performance validation
- Documentation writing
- Debugging and troubleshooting

**Deliverables**:
```
examples/run_equity_sector_backtest.py
examples/configs/equity_russell_3000_long_short.yaml

tests/integration/test_e2e_equity_backtest.py (20 tests)
tests/validation/test_ic_targets.py (10 tests)
tests/validation/test_ppfm_paper_replication.py (5 tests)

docs/validation/EQUITY_BACKTEST_RESULTS.md
docs/validation/IC_VALIDATION_REPORT.md
docs/validation/PPFM_REPLICATION_REPORT.md

README_EQUITY_SECTOR.md (user guide)
```

**Implementation Guidance**:
```python
# examples/run_equity_sector_backtest.py

# ABOUTME: End-to-end equity sector backtest example
# ABOUTME: Russell 3000 long/short market-neutral strategy

import polars as pl
from datetime import date
from Query.Equities import EquityQuery
from MDP.YahooFinance import YahooFinanceMDP, load_russell_3000_constituents
from Adapter import EquityAdapter
from Signals.Equities import ValueSignal, MomentumSignal, QualitySignal
from Signals import SignalCombiner, AlphaGenerator
from Risk.Covariance import PPFMCovariance
from Risk.FactorModel import EquityFactorModel
from Optimizer import LongShortOptimizer
from Optimizer.constraints import *
from TransactionCosts import InventoryRiskModel
from Portfolio import Portfolio
from Analysis import TearSheet

def run_equity_sector_backtest(config: dict):
    """
    Run end-to-end equity sector backtest

    Config keys:
        - universe: "russell_3000", "sp_500", or list of tickers
        - sectors: List of GICS sectors to include (or "all")
        - start_date, end_date: Backtest period
        - rebalance_frequency: "monthly", "quarterly"
        - signals: List of signal configs
        - risk_model: "ppfm", "factor", or "ledoit_wolf"
        - constraints: List of constraint configs
        - transaction_costs: bool, whether to include TC
    """
    print("=" * 80)
    print("EQUITY SECTOR BACKTEST")
    print("=" * 80)

    # 1. Load universe
    print("\n[1/10] Loading universe...")
    if config["universe"] == "russell_3000":
        constituents = load_russell_3000_constituents()
        tickers = constituents["ticker"].to_list()
    else:
        tickers = config["universe"]

    print(f"  Universe size: {len(tickers)} stocks")

    # Filter by sectors if specified
    if config.get("sectors") and config["sectors"] != "all":
        constituents_filtered = constituents.filter(
            pl.col("sector").is_in(config["sectors"])
        )
        tickers = constituents_filtered["ticker"].to_list()
        print(f"  Filtered to {len(config['sectors'])} sectors: {len(tickers)} stocks")

    # 2. Create queries
    print("\n[2/10] Creating queries...")
    queries = [
        EquityQuery(
            ticker=ticker,
            sector=constituents.filter(pl.col("ticker") == ticker)["sector"][0],
            structure=EquityStructure.SINGLE,
            value=EquityValue.RETURN,
        )
        for ticker in tickers
    ]

    # 3. Fetch data
    print("\n[3/10] Fetching data from Yahoo Finance...")
    mdp = YahooFinanceMDP()
    adapter = EquityAdapter()

    data = adapter.convert(
        queries,
        as_of_date=config["end_date"],
        mdp=mdp,
    )

    print(f"  Data fetched: {len(data)} stocks × {data['returns'].list.lengths().mean():.0f} days")

    # 4. Generate signals
    print("\n[4/10] Generating signals...")
    signals = []

    if "value" in config["signals"]:
        value_signal = ValueSignal()
        value_scores = value_signal.calculate(data)
        signals.append(("value", value_scores, value_signal.expected_ic))
        print(f"  ✓ Value signal generated (expected IC: {value_signal.expected_ic:.3f})")

    if "momentum" in config["signals"]:
        momentum_signal = MomentumSignal()
        momentum_scores = momentum_signal.calculate(data)
        signals.append(("momentum", momentum_scores, momentum_signal.expected_ic))
        print(f"  ✓ Momentum signal generated (expected IC: {momentum_signal.expected_ic:.3f})")

    if "quality" in config["signals"]:
        quality_signal = QualitySignal()
        quality_scores = quality_signal.calculate(data)
        signals.append(("quality", quality_scores, quality_signal.expected_ic))
        print(f"  ✓ Quality signal generated (expected IC: {quality_signal.expected_ic:.3f})")

    # 5. Combine signals (IC-weighted)
    print("\n[5/10] Combining signals...")
    signal_names = [s[0] for s in signals]
    signal_scores = [s[1]["z_score"] for s in signals]
    signal_ics = [s[2] for s in signals]

    combiner = SignalCombiner(weights=signal_ics)  # IC-weighted
    combined_scores = combiner.combine(signal_scores)

    # Validate sector-neutrality (CRITICAL!)
    combiner.validate_sector_neutrality(combined_scores, data["sector"])
    print(f"  ✓ Combined signal ({len(signals)} signals, IC-weighted)")
    print(f"  ✓ Sector-neutrality validated")

    # 6. Generate alphas (IC × Vol × Z)
    print("\n[6/10] Generating alphas...")
    alpha_gen = AlphaGenerator()

    combined_ic = np.sqrt(sum(ic**2 for ic in signal_ics))  # Assuming uncorrelated
    alphas = alpha_gen.generate(
        z_scores=combined_scores,
        volatility=data["volatility"],
        ic=combined_ic,
    )

    print(f"  ✓ Alphas generated (combined IC: {combined_ic:.3f})")

    # 7. Estimate risk model
    print("\n[7/10] Estimating risk model...")

    if config["risk_model"] == "ppfm":
        # Group data by sector for PPFM
        returns_by_sector = {}
        for sector in data["sector"].unique():
            sector_data = data.filter(pl.col("sector") == sector)
            returns_by_sector[sector] = sector_data["returns"]

        risk_model = PPFMCovariance(n_factors=2)
        covariance = risk_model.estimate(returns_by_sector)
        print(f"  ✓ PPFM covariance estimated ({len(returns_by_sector)} sectors)")

    elif config["risk_model"] == "factor":
        factor_model = EquityFactorModel()
        exposures = factor_model.compute_exposures(data)

        risk_model = FactorCovariance(factor_model)
        covariance = risk_model.estimate(data["returns"], exposures)
        print(f"  ✓ Factor covariance estimated (17 factors)")

    else:  # ledoit_wolf
        risk_model = LedoitWolfShrinkage()
        covariance = risk_model.estimate(data["returns"])
        print(f"  ✓ Ledoit-Wolf covariance estimated")

    # 8. Optimize portfolio
    print("\n[8/10] Optimizing portfolio...")

    # Build constraints
    constraints = []
    if "position_limit" in config["constraints"]:
        constraints.append(
            PositionLimitConstraint(max_weight=config["constraints"]["position_limit"])
        )
    if "gross_leverage" in config["constraints"]:
        constraints.append(
            GrossLeverageConstraint(max_gross_leverage=config["constraints"]["gross_leverage"])
        )

    optimizer = LongShortOptimizer(
        risk_aversion=config.get("risk_aversion", 1.0),
        tc_penalty=config.get("tc_penalty", 0.5),
        constraints=constraints,
    )

    weights = optimizer.optimize(
        alphas=alphas,
        covariance=covariance,
        sector_labels=data["sector"].to_list(),
    )

    print(f"  ✓ Portfolio optimized")
    print(f"    - Gross exposure: {weights.abs().sum():.2f}")
    print(f"    - Long exposure: {weights.filter(weights > 0).sum():.2f}")
    print(f"    - Short exposure: {weights.filter(weights < 0).sum():.2f}")
    print(f"    - Number of positions: {(weights.abs() > 1e-4).sum()}")

    # 9. Calculate transaction costs (if enabled)
    if config.get("transaction_costs"):
        print("\n[9/10] Calculating transaction costs...")
        tc_model = InventoryRiskModel()

        total_tc = tc_model.calculate_portfolio_tc(
            current_weights=pl.Series([0.0] * len(weights)),  # Start from cash
            target_weights=weights,
            portfolio_value=config.get("portfolio_value", 1_000_000),
            avg_daily_volumes=data["avg_volume"],
            volatilities=data["volatility"],
            prices=data["price"],
        )

        tc_bps = (total_tc / config.get("portfolio_value", 1_000_000)) * 10000
        print(f"  ✓ Transaction costs: ${total_tc:,.0f} ({tc_bps:.1f} bps)")
    else:
        print("\n[9/10] Skipping transaction costs (disabled)")

    # 10. Analyze performance
    print("\n[10/10] Analyzing performance...")

    portfolio = Portfolio(weights=weights, returns=data["returns"])
    tearsheet = TearSheet(portfolio)

    print("\n" + "=" * 80)
    print("BACKTEST RESULTS")
    print("=" * 80)
    print(f"Information Ratio: {tearsheet.information_ratio:.2f}")
    print(f"Information Coefficient: {tearsheet.ic:.3f}")
    print(f"Sharpe Ratio: {tearsheet.sharpe_ratio:.2f}")
    print(f"Annualized Return: {tearsheet.annualized_return:.2%}")
    print(f"Annualized Volatility: {tearsheet.annualized_volatility:.2%}")
    print(f"Max Drawdown: {tearsheet.max_drawdown:.2%}")
    print(f"Cumulative Return: {tearsheet.cumulative_return:.2%}")
    print("=" * 80)

    # Validate against targets
    print("\nVALIDATION AGAINST GRINOLD-KAHN TARGETS:")
    print(f"  Target IR: 1.0+   Realized: {tearsheet.information_ratio:.2f}  {'✓ PASS' if tearsheet.information_ratio > 1.0 else '✗ FAIL'}")
    print(f"  Target IC: 0.06+  Realized: {tearsheet.ic:.3f}  {'✓ PASS' if tearsheet.ic > 0.06 else '✗ FAIL'}")

    return tearsheet


if __name__ == "__main__":
    # Example configuration
    config = {
        "universe": "russell_3000",
        "sectors": "all",  # All 11 GICS sectors
        "start_date": date(2018, 1, 1),
        "end_date": date(2023, 12, 31),
        "rebalance_frequency": "monthly",
        "signals": ["value", "momentum", "quality"],
        "risk_model": "ppfm",
        "constraints": {
            "position_limit": 0.05,  # 5% max position
            "gross_leverage": 2.0,  # 100% long, 100% short
        },
        "risk_aversion": 1.0,
        "tc_penalty": 0.5,
        "transaction_costs": True,
        "portfolio_value": 10_000_000,
    }

    results = run_equity_sector_backtest(config)
```

**Example YAML Config**:
```yaml
# examples/configs/equity_russell_3000_long_short.yaml

name: "Russell 3000 Long/Short Market-Neutral"
description: "Multi-signal long/short strategy on Russell 3000"

universe:
  type: "russell_3000"
  sectors:
    - "Information Technology"
    - "Financials"
    - "Health Care"
    - "Consumer Discretionary"
    - "Industrials"
    - "Energy"
    - "Materials"
    - "Consumer Staples"
    - "Utilities"
    - "Communication Services"
    - "Real Estate"

backtest:
  start_date: "2018-01-01"
  end_date: "2023-12-31"
  rebalance_frequency: "monthly"
  portfolio_value: 10000000

signals:
  - type: "value"
    params:
      market_risk_premium: 0.06
  - type: "momentum"
  - type: "quality"

risk_model:
  type: "ppfm"
  params:
    n_factors: 2
    lambda: null  # Auto cross-validate

optimizer:
  type: "long_short"
  risk_aversion: 1.0
  tc_penalty: 0.5
  constraints:
    - type: "market_neutral"
      params:
        beta_neutral: false
    - type: "sector_neutral"
    - type: "position_limit"
      params:
        max_weight: 0.05
    - type: "gross_leverage"
      params:
        max_gross_leverage: 2.0

transaction_costs:
  enabled: true
  model: "inventory_risk"
  params:
    cost_coefficient: 1.0
    commission_rate: 0.001
```

**Testing Strategy**:
```python
# tests/integration/test_e2e_equity_backtest.py

@pytest.mark.integration
@pytest.mark.slow
def test_e2e_backtest_runs():
    """Test end-to-end backtest runs without errors"""
    config = load_config("examples/configs/equity_russell_3000_long_short.yaml")

    # Should not raise
    results = run_equity_sector_backtest(config)

    assert results is not None
    assert results.information_ratio is not None

# tests/validation/test_ic_targets.py

@pytest.mark.validation
def test_value_signal_ic_target():
    """Validate value signal IC meets book target (0.03-0.04)"""
    # Run backtest with value signal only
    results = run_equity_sector_backtest({
        ...
        "signals": ["value"],
    })

    realized_ic = results.ic

    assert 0.02 < realized_ic < 0.05, f"Value IC {realized_ic:.3f} outside target range [0.02, 0.05]"

# tests/validation/test_ppfm_paper_replication.py

@pytest.mark.validation
@pytest.mark.slow
def test_ppfm_paper_replication():
    """Replicate PPFM paper results (Table 2)"""
    # Use paper's 8 manufacturing sectors, 2013-2022 period
    config = {
        "universe": paper_manufacturing_sectors,
        "start_date": date(2013, 1, 1),
        "end_date": date(2022, 12, 31),
        "risk_model": "ppfm",
        ...
    }

    results = run_equity_sector_backtest(config)

    # Compare to paper's reported metrics
    # (Allow 10% tolerance for data/implementation differences)
    paper_sharpe = 1.23
    assert abs(results.sharpe_ratio - paper_sharpe) / paper_sharpe < 0.10, \
        f"Sharpe {results.sharpe_ratio:.2f} differs from paper {paper_sharpe:.2f}"
```

**Success Criteria**:
- [ ] End-to-end backtest runs successfully (no crashes)
- [ ] IR > 1.0 achieved (target met)
- [ ] IC > 0.06 achieved (target met)
- [ ] PPFM paper replication within 10% (validation passed)
- [ ] Transaction costs reduce IR by ~20-30% (realistic)
- [ ] Market-neutral and sector-neutral constraints satisfied
- [ ] User guide documentation completed
- [ ] Validation reports completed (IC, PPFM replication)
- [ ] 35 tests passing (20 integration + 10 validation + 5 paper replication)
- [ ] Committed and pushed

---

## Final Summary & Handoff

### Completion Checklist

**Wave 1: Research (Week 1)** - 4 agents
- [x] AGENT-01: Russell 3000 universe research
- [x] AGENT-02: Sector ETF research & mapping
- [x] AGENT-03: Yahoo Finance API design
- [x] AGENT-04: Long/short strategy design

**Wave 2: Data Infrastructure (Weeks 2-3)** - 5 agents
- [x] AGENT-05: EquityQuery implementation
- [x] AGENT-06: ETFQuery implementation
- [x] AGENT-07: Yahoo Finance MDP implementation
- [x] AGENT-08: Sector classification system
- [x] AGENT-09: EquityAdapter implementation

**Wave 3: Signals (Weeks 4-7)** - 5 agents
- [x] AGENT-10: ValueSignal implementation
- [x] AGENT-11: MomentumSignal implementation
- [x] AGENT-12: QualitySignal implementation
- [x] AGENT-13: BaseSignal cross-sectional extension
- [x] AGENT-14: Signal IC validation framework

**Wave 4: Risk Models (Weeks 8-11)** - 3 agents
- [x] AGENT-15: EquityFactorModel implementation
- [x] AGENT-16: FactorCovariance implementation
- [x] AGENT-17: PPFMCovariance implementation

**Wave 5: Optimization (Weeks 12-14)** - 2 agents
- [x] AGENT-18: Long/Short optimizer with constraints
- [x] AGENT-19: Transaction cost integration

**Wave 6: Integration (Weeks 15-17)** - 1 agent
- [x] AGENT-20: End-to-end integration & validation

**Total**: 20 agents, 183 tests, 17 weeks

### Success Metrics

**Technical Metrics**:
- [ ] All 183 tests passing
- [ ] IR > 1.0 (target: 1.5-2.0)
- [ ] IC > 0.06 (target: 0.06-0.07)
- [ ] Transfer coefficient > 0.8 (long/short advantage)
- [ ] PPFM risk reduction 10-15% vs baseline
- [ ] Transaction costs <50 bps per rebalance

**Validation Metrics**:
- [ ] Value signal IC: 0.03-0.04
- [ ] Momentum signal IC: 0.04-0.06
- [ ] Quality signal IC: 0.02-0.03
- [ ] PPFM paper replication within 10%
- [ ] Sector-neutrality validated (<1e-6 per sector)

**Documentation Metrics**:
- [ ] User guide completed (README_EQUITY_SECTOR.md)
- [ ] API documentation generated
- [ ] Validation reports completed
- [ ] Example configs created

### Next Steps for Peter

1. **Review agent specifications** (Parts 1-3, ~5000 lines)
2. **Approve or modify** agent assignments
3. **Launch Wave 1** (4 research agents in parallel)
4. **Monitor progress** via commits and test coverage
5. **Intervene if needed** (agents may get blocked)

### Agent Launch Command

To launch an agent:
```python
agent = Task(
    subagent_type="general-purpose",  # or "Explore" for research
    description="AGENT-XX: <task name>",
    prompt=open("docs/design/AGENT_ORCHESTRATION_PLAN_PARTX.md").read(),
)
```

---

**End of Agent Orchestration Plan (Complete)**
