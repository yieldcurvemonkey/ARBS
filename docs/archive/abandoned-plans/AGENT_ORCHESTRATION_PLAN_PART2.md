# Agent Orchestration Plan Part 2: Waves 3-6 (Signal Generation through Integration)

**Continuation of**: `AGENT_ORCHESTRATION_PLAN.md`
**Covers**: AGENT-10 through AGENT-20 (Weeks 4-17)

---

## WAVE 3: SIGNAL GENERATION (Weeks 4-7)

**5 agents in parallel** - Cross-sectional equity signals

---

### AGENT-10: ValueSignal Implementation

**Objective**: Implement value signal using DDM (Dividend Discount Model) and E/P ratio for long/short stock selection.

**Starting Context**:
1. `docs/books/grinold_kahn_equity_notes_part2_valuation.md` (lines 1-400, Chapter 9)
2. `docs/books/GRINOLD_KAHN_EQUITY_SUMMARY.md` (Section: Value Signals)
3. `Signals/BaseSignal.py` (base class to inherit)
4. `Signals/Futures/CarrySignal.py` (pattern reference)
5. `Adapter/EquityAdapter.py` (AGENT-09 output, understand input format)

**Skills Required**:
- Financial modeling (DDM, E/P ratio)
- Cross-sectional signal construction
- Polars DataFrames
- Test-driven development

**Deliverables**:
```
Signals/Equities/__init__.py
Signals/Equities/ValueSignal.py

tests/unit/signals/test_value_signal.py (25 tests)
tests/integration/test_value_signal_ic.py (5 tests)
```

**Implementation Guidance**:
```python
# Signals/Equities/ValueSignal.py

# ABOUTME: Value signal using DDM and earnings yield for long/short selection
# ABOUTME: Expected IC: 0.03-0.04, Horizon: 12-24 months (Grinold-Kahn Ch 9)

import polars as pl
from Signals.BaseSignal import BaseSignal

class ValueSignal(BaseSignal):
    """
    Value signal for equities (long/short market-neutral)

    From Grinold-Kahn Chapter 9:
        α_value = d/p + g - β·f_B

    Where:
        d/p = dividend yield
        g = (1 - payout_ratio) × ROE  (growth rate)
        β = equity beta
        f_B = market risk premium (default: 6%)

    For long/short:
        - Sector-neutralize alphas (zero mean per sector)
        - Long top quintile, short bottom quintile within each sector
    """

    def __init__(self, market_risk_premium: float = 0.06):
        super().__init__(
            name="value",
            expected_ic=0.035,  # Book target: 0.03-0.04
            information_horizon=18,  # 18 months half-life
        )
        self.f_B = market_risk_premium

    def calculate(self, data: pl.DataFrame) -> pl.DataFrame:
        """
        Calculate value signal scores

        Input (from EquityAdapter):
            - ticker, sector, returns, price, fundamentals (dict), market_cap

        Output:
            - ticker, z_score (sector-neutral, ready for long/short)
        """
        # Extract fundamentals
        dividend_yield = data["fundamentals"].struct.field("dividend_yield")
        roe = data["fundamentals"].struct.field("roe")
        payout_ratio = data["fundamentals"].struct.field("payout_ratio")
        beta = data["fundamentals"].struct.field("beta")

        # DDM alpha formula
        growth_rate = (1 - payout_ratio) * roe
        ddm_alpha = dividend_yield + growth_rate - beta * self.f_B

        # Alternative: E/P ratio (simpler, more robust)
        earnings_yield = data["fundamentals"].struct.field("earnings") / data["price"]

        # Combine DDM and E/P (50/50 weight)
        value_score = 0.5 * ddm_alpha + 0.5 * earnings_yield

        # Sector-neutralize (CRITICAL for long/short!)
        z_scores = self._to_sector_neutral_scores(value_score, data["sector"])

        return pl.DataFrame({
            "ticker": data["ticker"],
            "z_score": z_scores,
            "raw_value_score": value_score,  # For debugging
        })

    def _to_sector_neutral_scores(
        self, signal: pl.Series, sectors: pl.Series
    ) -> pl.Series:
        """
        Compute z-scores within each sector (zero mean per sector)

        This ensures long/short portfolio is sector-neutral:
        - If tech stocks have high value scores, we long top tech, short bottom tech
        - Net tech exposure = zero
        """
        df = pl.DataFrame({"signal": signal, "sector": sectors})

        # Compute z-scores within groups
        z_scores = (
            df
            .group_by("sector")
            .agg(
                ((pl.col("signal") - pl.col("signal").mean()) /
                 pl.col("signal").std()).alias("z_score")
            )
            .explode("z_score")
        )

        return z_scores["z_score"]

    def validate_sector_neutrality(self, scores_df: pl.DataFrame, sectors: pl.Series) -> bool:
        """
        Validate that scores have zero mean within each sector

        Critical check for long/short strategy!
        """
        df = pl.DataFrame({"score": scores_df["z_score"], "sector": sectors})

        sector_means = df.group_by("sector").agg(
            pl.col("score").mean().alias("mean")
        )

        # Check all sector means ≈ 0 (within tolerance)
        all_near_zero = (sector_means["mean"].abs() < 1e-10).all()

        if not all_near_zero:
            raise ValueError("Scores not sector-neutral! Check _to_sector_neutral_scores()")

        return True
```

**Testing Strategy**:
```python
# tests/unit/signals/test_value_signal.py

def test_value_signal_sector_neutrality():
    """Test that value scores are sector-neutral (zero mean per sector)"""
    signal = ValueSignal()

    # Create test data with clear value differences within sectors
    data = pl.DataFrame({
        "ticker": ["AAPL", "MSFT", "GOOGL", "JPM", "BAC", "WFC"],
        "sector": ["Tech", "Tech", "Tech", "Finance", "Finance", "Finance"],
        "price": [150, 300, 2000, 150, 30, 50],
        "fundamentals": [
            {"dividend_yield": 0.005, "roe": 0.30, "payout_ratio": 0.20, "beta": 1.2, "earnings": 10},
            {"dividend_yield": 0.01, "roe": 0.25, "payout_ratio": 0.25, "beta": 1.1, "earnings": 15},
            {"dividend_yield": 0.0, "roe": 0.20, "payout_ratio": 0.0, "beta": 1.3, "earnings": 50},
            {"dividend_yield": 0.02, "roe": 0.15, "payout_ratio": 0.40, "beta": 1.5, "earnings": 10},
            {"dividend_yield": 0.03, "roe": 0.12, "payout_ratio": 0.50, "beta": 1.4, "earnings": 5},
            {"dividend_yield": 0.025, "roe": 0.10, "payout_ratio": 0.45, "beta": 1.3, "earnings": 7},
        ],
        ...
    })

    result = signal.calculate(data)

    # Check sector neutrality
    tech_mean = result.filter(pl.col("ticker").is_in(["AAPL", "MSFT", "GOOGL"]))["z_score"].mean()
    finance_mean = result.filter(pl.col("ticker").is_in(["JPM", "BAC", "WFC"]))["z_score"].mean()

    assert abs(tech_mean) < 1e-10, f"Tech sector mean not zero: {tech_mean}"
    assert abs(finance_mean) < 1e-10, f"Finance sector mean not zero: {finance_mean}"

    # Check spread within sector (should have positive and negative scores)
    tech_scores = result.filter(pl.col("ticker").is_in(["AAPL", "MSFT", "GOOGL"]))["z_score"]
    assert tech_scores.min() < 0 and tech_scores.max() > 0, "No spread within tech sector"

def test_value_signal_ic_expectation():
    """Test IC is in expected range (0.03-0.04) on historical data"""
    signal = ValueSignal()

    # Load historical data (252 days, ~100 stocks)
    historical_data = load_test_data("historical_value_signal_data.parquet")

    # Generate forecasts
    forecasts = signal.calculate(historical_data)

    # Calculate realized returns (12-month forward)
    realized_returns = calculate_forward_returns(historical_data, horizon_months=12)

    # Compute IC
    ic = forecasts["z_score"].corr(realized_returns)

    assert 0.02 < ic < 0.05, f"IC {ic:.3f} outside expected range [0.02, 0.05]"

# ... 23 more tests
```

**Success Criteria**:
- [ ] `ValueSignal` implemented with DDM + E/P
- [ ] Sector-neutral z-scores (zero mean per sector)
- [ ] Validation method confirms neutrality
- [ ] 30 tests passing (25 unit + 5 integration)
- [ ] IC validation: 0.03-0.04 on historical data
- [ ] Committed and pushed

---

### AGENT-11: MomentumSignal Implementation

**Objective**: Implement momentum signal (12-month return, skip last month) for long/short selection.

**Starting Context**:
1. `docs/books/grinold_kahn_equity_notes_part3_forecasting.md` (lines 1-400, Chapter 11)
2. `docs/books/GRINOLD_KAHN_EQUITY_SUMMARY.md` (Section: Momentum Signals)
3. `Signals/BaseSignal.py`
4. `Signals/Equities/ValueSignal.py` (AGENT-10 output, pattern reference)
5. `Signals/Futures/MomentumSignal.py` (existing momentum, but time-series not cross-sectional!)

**Skills Required**:
- Cross-sectional momentum (different from futures time-series!)
- Returns calculation
- Polars DataFrames
- Test-driven development

**Deliverables**:
```
Signals/Equities/MomentumSignal.py

tests/unit/signals/test_momentum_signal.py (20 tests)
tests/integration/test_momentum_signal_ic.py (5 tests)
```

**Implementation Guidance**:
```python
# Signals/Equities/MomentumSignal.py

# ABOUTME: Momentum signal using 12-month return (skip last month) for long/short
# ABOUTME: Expected IC: 0.04-0.06, Horizon: 3-6 months (Grinold-Kahn Ch 11)

import polars as pl
from Signals.BaseSignal import BaseSignal

class MomentumSignal(BaseSignal):
    """
    Momentum signal for equities (cross-sectional, sector-neutral)

    From Grinold-Kahn Chapter 11:
        - Use 12-month return (t-252 to t-21)
        - Skip last month (t-21 to t) to avoid reversal effect
        - Sector-neutralize for long/short market-neutral strategy

    Key difference from Futures momentum:
        - Futures: Time-series (compare to own history)
        - Equities: Cross-sectional (rank within universe)
    """

    def __init__(self):
        super().__init__(
            name="momentum",
            expected_ic=0.05,  # Book target: 0.04-0.06
            information_horizon=4,  # 4 months half-life
        )

    def calculate(self, data: pl.DataFrame) -> pl.DataFrame:
        """
        Calculate momentum signal scores

        Input (from EquityAdapter):
            - ticker, sector, returns (List[float] of daily returns)

        Output:
            - ticker, z_score (sector-neutral)
        """
        # Calculate 12-month return (skip last 21 days)
        momentum_returns = (
            data
            .with_columns(
                pl.col("returns")
                .list.slice(offset=0, length=-21)  # Skip last month
                .list.eval(pl.element().add(1).product().sub(1))  # Compound return
                .alias("momentum_12m")
            )
        )

        # Sector-neutralize
        z_scores = self._to_sector_neutral_scores(
            momentum_returns["momentum_12m"],
            momentum_returns["sector"]
        )

        return pl.DataFrame({
            "ticker": data["ticker"],
            "z_score": z_scores,
            "raw_momentum_12m": momentum_returns["momentum_12m"],
        })

    def _to_sector_neutral_scores(
        self, signal: pl.Series, sectors: pl.Series
    ) -> pl.Series:
        """Sector-neutralize (same as ValueSignal)"""
        df = pl.DataFrame({"signal": signal, "sector": sectors})

        z_scores = (
            df
            .group_by("sector")
            .agg(
                ((pl.col("signal") - pl.col("signal").mean()) /
                 pl.col("signal").std()).alias("z_score")
            )
            .explode("z_score")
        )

        return z_scores["z_score"]
```

**Testing Strategy**:
```python
# tests/unit/signals/test_momentum_signal.py

def test_momentum_12m_calculation():
    """Test 12-month return calculation (skip last month)"""
    signal = MomentumSignal()

    # Create test data: 252 trading days of returns
    daily_returns = [0.01] * 231 + [0.00] * 21  # Positive for 11 months, flat for last month

    data = pl.DataFrame({
        "ticker": ["TEST"],
        "sector": ["Technology"],
        "returns": [daily_returns],
    })

    result = signal.calculate(data)

    # 11 months of 1% daily returns ≈ (1.01)^231 - 1 ≈ 8.93
    expected_return = (1.01 ** 231) - 1
    assert abs(result["raw_momentum_12m"][0] - expected_return) < 0.01

def test_skip_last_month_effect():
    """Verify last month is skipped (avoid reversal)"""
    signal = MomentumSignal()

    # Strong momentum for 11 months, then reversal in last month
    daily_returns = [0.01] * 231 + [-0.05] * 21  # Reversal in last month

    data = pl.DataFrame({
        "ticker": ["TEST"],
        "sector": ["Technology"],
        "returns": [daily_returns],
    })

    result = signal.calculate(data)

    # Should ignore last month's reversal
    # Result should still be positive (based on 11 months)
    assert result["raw_momentum_12m"][0] > 0

def test_momentum_sector_neutrality():
    """Test momentum scores are sector-neutral"""
    signal = MomentumSignal()

    # Create data with different momentum across sectors
    data = pl.DataFrame({
        "ticker": ["AAPL", "MSFT", "GOOGL", "JPM", "BAC", "WFC"],
        "sector": ["Tech", "Tech", "Tech", "Finance", "Finance", "Finance"],
        "returns": [
            [0.01] * 252,  # Strong momentum
            [0.005] * 252,  # Medium momentum
            [0.002] * 252,  # Weak momentum
            [0.01] * 252,  # Strong momentum
            [0.005] * 252,  # Medium momentum
            [0.002] * 252,  # Weak momentum
        ],
    })

    result = signal.calculate(data)

    # Check sector means ≈ 0
    tech_mean = result.filter(pl.col("ticker").is_in(["AAPL", "MSFT", "GOOGL"]))["z_score"].mean()
    finance_mean = result.filter(pl.col("ticker").is_in(["JPM", "BAC", "WFC"]))["z_score"].mean()

    assert abs(tech_mean) < 1e-10
    assert abs(finance_mean) < 1e-10

# ... 17 more tests
```

**Success Criteria**:
- [ ] `MomentumSignal` implemented (12-month, skip last month)
- [ ] Sector-neutral z-scores
- [ ] Last month skipped correctly (reversal avoided)
- [ ] 25 tests passing
- [ ] IC validation: 0.04-0.06 on historical data
- [ ] Committed and pushed

---

### AGENT-12: QualitySignal Implementation

**Objective**: Implement quality signal (ROE, debt/equity, earnings stability) for long/short selection.

**Starting Context**:
1. `docs/books/grinold_kahn_equity_notes_part2_valuation.md` (Chapter 9, quality metrics)
2. `docs/books/GRINOLD_KAHN_EQUITY_SUMMARY.md` (Section: Quality Signals)
3. `Signals/BaseSignal.py`
4. `Signals/Equities/ValueSignal.py` (AGENT-10 output, pattern)

**Skills Required**:
- Fundamental analysis (ROE, leverage, stability)
- Composite signal construction
- Polars DataFrames
- Test-driven development

**Deliverables**:
```
Signals/Equities/QualitySignal.py

tests/unit/signals/test_quality_signal.py (20 tests)
tests/integration/test_quality_signal_ic.py (5 tests)
```

**Implementation Guidance**:
```python
# Signals/Equities/QualitySignal.py

# ABOUTME: Quality signal using ROE, debt/equity, earnings stability for long/short
# ABOUTME: Expected IC: 0.02-0.03, Horizon: 24+ months (Grinold-Kahn Ch 9)

import polars as pl
from Signals.BaseSignal import BaseSignal

class QualitySignal(BaseSignal):
    """
    Quality signal composite (sector-neutral for long/short)

    Metrics:
        1. ROE (Return on Equity) - higher is better
        2. Debt/Equity ratio - lower is better (inverted)
        3. Earnings stability - lower volatility is better (inverted)

    Weights:
        - ROE: 50%
        - Debt/Equity: 30%
        - Earnings stability: 20%
    """

    def __init__(self):
        super().__init__(
            name="quality",
            expected_ic=0.025,  # Book target: 0.02-0.03
            information_horizon=24,  # 24 months (very persistent!)
        )

    def calculate(self, data: pl.DataFrame) -> pl.DataFrame:
        """
        Calculate quality signal scores

        Input:
            - ticker, sector, fundamentals (roe, debt_to_equity, earnings_std)

        Output:
            - ticker, z_score (sector-neutral)
        """
        # Extract fundamentals
        roe = data["fundamentals"].struct.field("roe")
        debt_to_equity = data["fundamentals"].struct.field("debt_to_equity")
        earnings_std = data["fundamentals"].struct.field("earnings_std")

        # Standardize each metric within sector FIRST (before combining)
        roe_z = self._standardize_within_sector(roe, data["sector"])
        debt_z = -self._standardize_within_sector(debt_to_equity, data["sector"])  # Invert
        stability_z = -self._standardize_within_sector(earnings_std, data["sector"])  # Invert

        # Combine with weights
        quality_score = (
            0.50 * roe_z +
            0.30 * debt_z +
            0.20 * stability_z
        )

        # Already sector-neutral (since each component was standardized within sector)
        z_scores = (quality_score - quality_score.mean()) / quality_score.std()

        return pl.DataFrame({
            "ticker": data["ticker"],
            "z_score": z_scores,
            "roe_z": roe_z,
            "debt_z": debt_z,
            "stability_z": stability_z,
        })

    def _standardize_within_sector(
        self, metric: pl.Series, sectors: pl.Series
    ) -> pl.Series:
        """Standardize metric to z-scores within each sector"""
        df = pl.DataFrame({"metric": metric, "sector": sectors})

        z_scores = (
            df
            .group_by("sector")
            .agg(
                ((pl.col("metric") - pl.col("metric").mean()) /
                 pl.col("metric").std()).alias("z_score")
            )
            .explode("z_score")
        )

        return z_scores["z_score"]
```

**Testing Strategy**:
```python
# tests/unit/signals/test_quality_signal.py

def test_quality_composite_weights():
    """Test composite quality score uses correct weights"""
    signal = QualitySignal()

    data = pl.DataFrame({
        "ticker": ["TEST1", "TEST2"],
        "sector": ["Technology", "Technology"],
        "fundamentals": [
            {"roe": 0.30, "debt_to_equity": 0.5, "earnings_std": 0.01},
            {"roe": 0.10, "debt_to_equity": 2.0, "earnings_std": 0.10},
        ],
    })

    result = signal.calculate(data)

    # TEST1 should have higher quality score (high ROE, low debt, low std)
    assert result.filter(pl.col("ticker") == "TEST1")["z_score"][0] > \
           result.filter(pl.col("ticker") == "TEST2")["z_score"][0]

def test_quality_sector_neutrality():
    """Test quality scores are sector-neutral"""
    signal = QualitySignal()

    # Create data with systematically different quality across sectors
    data = pl.DataFrame({
        "ticker": ["AAPL", "MSFT", "GOOGL", "JPM", "BAC", "WFC"],
        "sector": ["Tech", "Tech", "Tech", "Finance", "Finance", "Finance"],
        "fundamentals": [
            {"roe": 0.30, "debt_to_equity": 0.5, "earnings_std": 0.01},  # High quality tech
            {"roe": 0.25, "debt_to_equity": 0.7, "earnings_std": 0.02},  # Medium quality tech
            {"roe": 0.20, "debt_to_equity": 1.0, "earnings_std": 0.05},  # Low quality tech
            {"roe": 0.15, "debt_to_equity": 2.0, "earnings_std": 0.03},  # High quality finance (relative)
            {"roe": 0.12, "debt_to_equity": 3.0, "earnings_std": 0.04},  # Medium
            {"roe": 0.10, "debt_to_equity": 5.0, "earnings_std": 0.10},  # Low
        ],
    })

    result = signal.calculate(data)

    # Check sector means ≈ 0
    tech_mean = result.filter(pl.col("ticker").is_in(["AAPL", "MSFT", "GOOGL"]))["z_score"].mean()
    finance_mean = result.filter(pl.col("ticker").is_in(["JPM", "BAC", "WFC"]))["z_score"].mean()

    assert abs(tech_mean) < 1e-10
    assert abs(finance_mean) < 1e-10

# ... 18 more tests
```

**Success Criteria**:
- [ ] `QualitySignal` implemented (ROE, debt, stability composite)
- [ ] Sector-neutral z-scores
- [ ] Weights: 50% ROE, 30% debt, 20% stability
- [ ] 25 tests passing
- [ ] IC validation: 0.02-0.03 on historical data
- [ ] Committed and pushed

---

### AGENT-13: BaseSignal Cross-Sectional Extension

**Objective**: Extend `BaseSignal` with cross-sectional methods and sector-neutralization utilities.

**Starting Context**:
1. `Signals/BaseSignal.py` (existing base class)
2. `Signals/Equities/ValueSignal.py` (AGENT-10 output, uses sector-neutralization)
3. `Signals/Equities/MomentumSignal.py` (AGENT-11 output)
4. `Signals/Equities/QualitySignal.py` (AGENT-12 output)
5. `docs/books/grinold_kahn_equity_notes_part3_forecasting.md` (Chapter 11, cross-sectional vs time-series)

**Skills Required**:
- Object-oriented design (inheritance)
- Cross-sectional signal theory
- Code refactoring
- Test-driven development

**Deliverables**:
```
Signals/BaseSignal.py (MODIFY, add methods)

tests/unit/signals/test_base_signal_cross_sectional.py (15 tests)
```

**Implementation Guidance**:
```python
# Signals/BaseSignal.py (ADD these methods)

class BaseSignal:
    # ... existing methods ...

    def to_cross_sectional_scores(
        self,
        signal: pl.Series,
        groupby_col: pl.Series = None,
    ) -> pl.Series:
        """
        Convert signal to cross-sectional z-scores

        From Grinold-Kahn Chapter 11:
            - Equity signals are cross-sectional (rank within universe)
            - NOT time-series (compare to own history)

        Args:
            signal: Raw signal values
            groupby_col: Optional grouping (e.g., sector for sector-neutral)

        Returns:
            Z-scores (mean=0, std=1 overall, or within groups)
        """
        if groupby_col is None:
            # Global z-scores (market-neutral but not sector-neutral)
            return (signal - signal.mean()) / signal.std()
        else:
            # Group-specific z-scores (sector-neutral)
            df = pl.DataFrame({"signal": signal, "group": groupby_col})

            z_scores = (
                df
                .group_by("group")
                .agg(
                    ((pl.col("signal") - pl.col("signal").mean()) /
                     pl.col("signal").std()).alias("z_score")
                )
                .explode("z_score")
            )

            return z_scores["z_score"]

    def validate_sector_neutrality(
        self,
        scores: pl.Series,
        sectors: pl.Series,
        tolerance: float = 1e-10,
    ) -> bool:
        """
        Validate that scores have zero mean within each sector

        Critical for long/short sector-neutral strategies!

        Args:
            scores: Signal scores to validate
            sectors: Sector labels for each score
            tolerance: Maximum allowed absolute mean per sector

        Raises:
            ValueError if any sector mean exceeds tolerance

        Returns:
            True if all sector means ≈ 0
        """
        df = pl.DataFrame({"score": scores, "sector": sectors})

        sector_stats = df.group_by("sector").agg([
            pl.col("score").mean().alias("mean"),
            pl.col("score").std().alias("std"),
        ])

        violating_sectors = sector_stats.filter(
            pl.col("mean").abs() > tolerance
        )

        if len(violating_sectors) > 0:
            violations = violating_sectors.select([
                pl.col("sector"),
                pl.col("mean"),
            ]).to_dicts()

            raise ValueError(
                f"Sector neutrality violated! {len(violating_sectors)} sectors have non-zero mean:\n"
                f"{violations}"
            )

        return True

    def calculate_breadth(
        self,
        universe_size: int,
        rebalance_frequency: str = "monthly",
    ) -> int:
        """
        Calculate effective breadth (BR) for this signal

        From Grinold-Kahn Chapter 6: IR = IC × √BR

        Args:
            universe_size: Number of assets in universe
            rebalance_frequency: "daily", "weekly", "monthly", "quarterly"

        Returns:
            Breadth (number of independent bets per year)
        """
        freq_map = {
            "daily": 252,
            "weekly": 52,
            "monthly": 12,
            "quarterly": 4,
            "annual": 1,
        }

        rebalances_per_year = freq_map.get(rebalance_frequency)
        if rebalances_per_year is None:
            raise ValueError(f"Unknown rebalance frequency: {rebalance_frequency}")

        return universe_size * rebalances_per_year
```

**Testing Strategy**:
```python
# tests/unit/signals/test_base_signal_cross_sectional.py

def test_to_cross_sectional_scores_global():
    """Test global cross-sectional z-scores (market-neutral)"""
    signal = BaseSignal(name="test")

    raw_signal = pl.Series([1.0, 2.0, 3.0, 4.0, 5.0])

    z_scores = signal.to_cross_sectional_scores(raw_signal)

    # Check properties
    assert abs(z_scores.mean()) < 1e-10  # Mean ≈ 0
    assert abs(z_scores.std() - 1.0) < 1e-10  # Std ≈ 1
    assert z_scores.min() < 0 and z_scores.max() > 0  # Has negative and positive

def test_to_cross_sectional_scores_sector_neutral():
    """Test sector-neutral cross-sectional z-scores"""
    signal = BaseSignal(name="test")

    raw_signal = pl.Series([1.0, 2.0, 3.0, 10.0, 20.0, 30.0])  # Tech: 1-3, Finance: 10-30
    sectors = pl.Series(["Tech", "Tech", "Tech", "Finance", "Finance", "Finance"])

    z_scores = signal.to_cross_sectional_scores(raw_signal, sectors)

    # Check sector neutrality
    df = pl.DataFrame({"z_score": z_scores, "sector": sectors})
    tech_mean = df.filter(pl.col("sector") == "Tech")["z_score"].mean()
    finance_mean = df.filter(pl.col("sector") == "Finance")["z_score"].mean()

    assert abs(tech_mean) < 1e-10
    assert abs(finance_mean) < 1e-10

def test_validate_sector_neutrality_pass():
    """Test validation passes for sector-neutral scores"""
    signal = BaseSignal(name="test")

    # Create perfectly sector-neutral scores
    scores = pl.Series([-1.0, 0.0, 1.0, -1.0, 0.0, 1.0])
    sectors = pl.Series(["Tech", "Tech", "Tech", "Finance", "Finance", "Finance"])

    # Should not raise
    assert signal.validate_sector_neutrality(scores, sectors) == True

def test_validate_sector_neutrality_fail():
    """Test validation fails for non-neutral scores"""
    signal = BaseSignal(name="test")

    # Create non-neutral scores (tech biased positive)
    scores = pl.Series([1.0, 1.0, 1.0, -1.0, -1.0, -1.0])
    sectors = pl.Series(["Tech", "Tech", "Tech", "Finance", "Finance", "Finance"])

    # Should raise ValueError
    with pytest.raises(ValueError, match="Sector neutrality violated"):
        signal.validate_sector_neutrality(scores, sectors)

def test_calculate_breadth():
    """Test breadth calculation for different frequencies"""
    signal = BaseSignal(name="test")

    # Russell 3000, quarterly rebalancing
    br = signal.calculate_breadth(universe_size=3000, rebalance_frequency="quarterly")
    assert br == 3000 * 4  # 12,000 bets/year

    # S&P 500, monthly rebalancing
    br = signal.calculate_breadth(universe_size=500, rebalance_frequency="monthly")
    assert br == 500 * 12  # 6,000 bets/year

# ... 10 more tests
```

**Success Criteria**:
- [ ] `to_cross_sectional_scores()` method added to `BaseSignal`
- [ ] `validate_sector_neutrality()` method added
- [ ] `calculate_breadth()` method added
- [ ] All existing tests still pass (no regressions!)
- [ ] 15 new tests passing
- [ ] ValueSignal, MomentumSignal, QualitySignal refactored to use new methods
- [ ] Committed and pushed

---

### AGENT-14: Signal IC Validation Framework

**Objective**: Create framework for validating signal ICs on historical data.

**Starting Context**:
1. `Signals/Equities/ValueSignal.py` (AGENT-10 output)
2. `Signals/Equities/MomentumSignal.py` (AGENT-11 output)
3. `Signals/Equities/QualitySignal.py` (AGENT-12 output)
4. `docs/books/grinold_kahn_equity_notes_part3_forecasting.md` (Chapter 12, IC calculation)
5. `Analysis/TearSheet.py` (existing IC calculation, may need extension)

**Skills Required**:
- IC calculation and validation
- Historical data handling
- Statistical testing
- Polars DataFrames

**Deliverables**:
```
tests/validation/signal_ic_validation.py

tests/validation/test_value_signal_ic.py (5 tests)
tests/validation/test_momentum_signal_ic.py (5 tests)
tests/validation/test_quality_signal_ic.py (5 tests)

docs/validation/SIGNAL_IC_RESULTS.md (validation report)
```

**Implementation Guidance**:
```python
# tests/validation/signal_ic_validation.py

# ABOUTME: Framework for validating signal ICs on historical Russell 3000 data
# ABOUTME: Compares realized ICs to Grinold-Kahn book targets

import polars as pl
from datetime import date, timedelta
from typing import Dict, List
from Signals.Equities import ValueSignal, MomentumSignal, QualitySignal

class SignalICValidator:
    """
    Validate signal ICs on historical data

    Process:
    1. Load historical Russell 3000 data (2018-2023, 5 years)
    2. Generate signal forecasts at each monthly rebalance
    3. Calculate realized returns over signal horizon
    4. Compute IC (correlation between forecast and realized)
    5. Compare to book targets
    """

    def __init__(self, start_date: date, end_date: date, horizon_months: int):
        self.start_date = start_date
        self.end_date = end_date
        self.horizon_months = horizon_months

    def validate_signal_ic(
        self,
        signal: BaseSignal,
        data: pl.DataFrame,
        target_ic_range: tuple[float, float],
    ) -> Dict:
        """
        Validate IC for a signal

        Args:
            signal: Signal to validate
            data: Historical data (ticker, date, returns, fundamentals, sector)
            target_ic_range: Expected IC range from book (e.g., (0.03, 0.04) for value)

        Returns:
            Dict with:
                - realized_ic: float (average IC over validation period)
                - ic_time_series: List[float] (IC at each rebalance)
                - t_statistic: float (IC significance)
                - passes: bool (IC in target range)
        """
        # Monthly rebalances
        rebalance_dates = self._get_monthly_rebalances(self.start_date, self.end_date)

        ics = []
        for rebalance_date in rebalance_dates:
            # Get data as of rebalance date
            data_snapshot = data.filter(pl.col("date") <= rebalance_date)

            # Generate forecasts
            forecasts = signal.calculate(data_snapshot)

            # Calculate realized returns over horizon
            future_date = rebalance_date + timedelta(days=self.horizon_months * 30)
            realized_returns = self._calculate_forward_returns(
                data, rebalance_date, future_date
            )

            # Compute IC
            ic = forecasts["z_score"].corr(realized_returns)
            ics.append(ic)

        # Average IC
        realized_ic = pl.Series(ics).mean()

        # T-statistic (is IC significantly different from zero?)
        t_stat = realized_ic * (len(ics) ** 0.5) / pl.Series(ics).std()

        # Check if in target range
        passes = target_ic_range[0] <= realized_ic <= target_ic_range[1]

        return {
            "signal_name": signal.name,
            "realized_ic": realized_ic,
            "ic_time_series": ics,
            "t_statistic": t_stat,
            "target_ic_range": target_ic_range,
            "passes": passes,
            "num_observations": len(ics),
        }

    def _get_monthly_rebalances(self, start: date, end: date) -> List[date]:
        """Generate list of month-end dates"""
        dates = []
        current = start
        while current <= end:
            # Last business day of month
            dates.append(current.replace(day=28) + timedelta(days=4) - timedelta(days=current.day))
            current += timedelta(days=32)
            current = current.replace(day=1)
        return dates

    def _calculate_forward_returns(
        self,
        data: pl.DataFrame,
        start_date: date,
        end_date: date,
    ) -> pl.Series:
        """Calculate returns from start_date to end_date for each ticker"""
        start_prices = data.filter(pl.col("date") == start_date)["price"]
        end_prices = data.filter(pl.col("date") == end_date)["price"]

        returns = (end_prices - start_prices) / start_prices
        return returns
```

**Testing Strategy**:
```python
# tests/validation/test_value_signal_ic.py

@pytest.mark.validation
@pytest.mark.slow
def test_value_signal_ic_validation():
    """Validate ValueSignal IC on historical data (2018-2023)"""
    validator = SignalICValidator(
        start_date=date(2018, 1, 1),
        end_date=date(2023, 12, 31),
        horizon_months=12,  # Value signal has 12-24 month horizon
    )

    # Load historical Russell 3000 data
    data = load_russell_3000_historical_data()  # From cached parquet

    signal = ValueSignal()

    result = validator.validate_signal_ic(
        signal=signal,
        data=data,
        target_ic_range=(0.03, 0.04),  # From Grinold-Kahn book
    )

    # Check results
    print(f"Value Signal IC Validation:")
    print(f"  Realized IC: {result['realized_ic']:.4f}")
    print(f"  Target Range: {result['target_ic_range']}")
    print(f"  T-statistic: {result['t_statistic']:.2f}")
    print(f"  Passes: {result['passes']}")

    # Assert IC is statistically significant
    assert result['t_statistic'] > 2.0, "IC not statistically significant"

    # Warn if IC outside target (but don't fail)
    if not result['passes']:
        warnings.warn(
            f"Value signal IC {result['realized_ic']:.4f} outside target range {result['target_ic_range']}"
        )

# Similar tests for momentum and quality signals...
```

**Success Criteria**:
- [ ] `SignalICValidator` framework implemented
- [ ] Historical Russell 3000 data loaded (2018-2023)
- [ ] IC validation for Value, Momentum, Quality signals
- [ ] 15 validation tests
- [ ] Validation report document created (`SIGNAL_IC_RESULTS.md`)
- [ ] All signals have IC t-statistic > 2.0 (statistically significant)
- [ ] Committed and pushed

---

## WAVE 4: RISK MODELS (Weeks 8-11)

**3 agents in parallel** - Multi-factor covariance estimation

---

### AGENT-15: EquityFactorModel Implementation

**Objective**: Implement 17-factor equity model (11 GICS sectors + 6 style factors).

**Starting Context**:
1. `docs/books/grinold_kahn_equity_notes_part1_foundations.md` (Chapter 3, factor models)
2. `docs/books/GRINOLD_KAHN_EQUITY_SUMMARY.md` (Section: Multi-Factor Risk Model)
3. `docs/design/EQUITY_SECTOR_IMPLEMENTATION_PLAN.md` (Phase 3, Section 3.1)
4. `Adapter/EquityAdapter.py` (AGENT-09 output, data format)

**Skills Required**:
- Factor model theory (APT)
- Matrix operations (exposures X matrix)
- Polars DataFrames
- Test-driven development

**Deliverables**:
```
Risk/FactorModel/__init__.py
Risk/FactorModel/EquityFactorModel.py

tests/unit/risk/test_equity_factor_model.py (25 tests)
```

**Implementation Guidance**:
```python
# Risk/FactorModel/EquityFactorModel.py

# ABOUTME: 17-factor equity risk model (11 sectors + 6 styles)
# ABOUTME: Computes factor exposures X matrix (N×17) for Russell 3000

import polars as pl
import numpy as np
from typing import List

class EquityFactorModel:
    """
    17-factor equity risk model

    Factors:
        - 11 GICS sectors (dummy variables, 0/1)
        - 6 style factors (standardized, mean=0 std=1):
            1. Size (log market cap)
            2. Value (book-to-price ratio)
            3. Momentum (12-month return)
            4. Quality (ROE)
            5. Low Volatility (inverse volatility)
            6. Dividend Yield

    From Grinold-Kahn Chapter 3:
        r_n = Σ_k X_{n,k} · b_k + u_n

    Where:
        X: N×K exposures (3000 stocks × 17 factors)
        b: K×1 factor returns
        u: N×1 specific returns

    Efficiency: 3000² = 9M parameters → 3000×17 + 17² + 3000 = 54,289 (99.4% reduction!)
    """

    SECTOR_FACTORS = [
        "Energy",
        "Materials",
        "Industrials",
        "Consumer Discretionary",
        "Consumer Staples",
        "Health Care",
        "Financials",
        "Information Technology",
        "Communication Services",
        "Utilities",
        "Real Estate",
    ]

    STYLE_FACTORS = [
        "Size",
        "Value",
        "Momentum",
        "Quality",
        "Low Volatility",
        "Dividend Yield",
    ]

    def compute_exposures(self, data: pl.DataFrame) -> pl.DataFrame:
        """
        Compute factor exposures X (N×17 matrix)

        Input (from EquityAdapter):
            - ticker, sector, price, market_cap, fundamentals, returns

        Output:
            - ticker + 17 factor columns (11 sectors + 6 styles)
            - Sector exposures: 0/1 (dummy variables)
            - Style exposures: Standardized (mean=0, std=1)
        """
        N = len(data)
        exposures = pl.DataFrame({"ticker": data["ticker"]})

        # 1. Sector exposures (dummy variables)
        for sector in self.SECTOR_FACTORS:
            exposures = exposures.with_columns(
                (data["sector"] == sector).cast(pl.Float64).alias(sector)
            )

        # 2. Style exposures (standardized)

        # Size: log(market_cap)
        size_raw = np.log(data["market_cap"])
        exposures = exposures.with_columns(
            self._standardize(size_raw).alias("Size")
        )

        # Value: book-to-price ratio
        book_to_price = (
            data["fundamentals"].struct.field("book_value") / data["price"]
        )
        exposures = exposures.with_columns(
            self._standardize(book_to_price).alias("Value")
        )

        # Momentum: 12-month return
        momentum_12m = data["fundamentals"].struct.field("12m_return")
        exposures = exposures.with_columns(
            self._standardize(momentum_12m).alias("Momentum")
        )

        # Quality: ROE
        roe = data["fundamentals"].struct.field("roe")
        exposures = exposures.with_columns(
            self._standardize(roe).alias("Quality")
        )

        # Low Volatility: inverse of volatility
        volatility = data["fundamentals"].struct.field("volatility")
        low_vol = 1 / volatility
        exposures = exposures.with_columns(
            self._standardize(low_vol).alias("Low Volatility")
        )

        # Dividend Yield
        div_yield = data["fundamentals"].struct.field("dividend_yield")
        exposures = exposures.with_columns(
            self._standardize(div_yield).alias("Dividend Yield")
        )

        return exposures

    def _standardize(self, series: pl.Series) -> pl.Series:
        """Standardize to mean=0, std=1"""
        return (series - series.mean()) / series.std()

    def get_exposure_matrix(self, exposures_df: pl.DataFrame) -> np.ndarray:
        """
        Convert exposures DataFrame to numpy matrix (for covariance calc)

        Returns:
            X: N×17 numpy array
        """
        # Drop ticker column, keep only factor columns
        factor_cols = self.SECTOR_FACTORS + self.STYLE_FACTORS
        X = exposures_df.select(factor_cols).to_numpy()

        return X

    def validate_exposures(self, exposures_df: pl.DataFrame) -> bool:
        """
        Validate exposures satisfy constraints

        Checks:
        1. Each stock has exactly one sector exposure = 1
        2. Style factors have mean ≈ 0, std ≈ 1
        """
        # Check sector exposures sum to 1
        sector_sums = exposures_df.select(self.SECTOR_FACTORS).sum(axis=1)
        assert (sector_sums == 1).all(), "Sector exposures don't sum to 1!"

        # Check style factors standardized
        for style in self.STYLE_FACTORS:
            mean = exposures_df[style].mean()
            std = exposures_df[style].std()

            assert abs(mean) < 1e-10, f"{style} mean not zero: {mean}"
            assert abs(std - 1.0) < 1e-3, f"{style} std not 1.0: {std}"

        return True
```

**Testing Strategy**:
```python
# tests/unit/risk/test_equity_factor_model.py

def test_factor_model_sector_exposures():
    """Test sector dummy variables"""
    model = EquityFactorModel()

    data = pl.DataFrame({
        "ticker": ["AAPL", "MSFT", "JPM"],
        "sector": ["Information Technology", "Information Technology", "Financials"],
        "price": [150, 300, 150],
        "market_cap": [3e12, 2.5e12, 500e9],
        "fundamentals": [...],
        "returns": [...],
    })

    exposures = model.compute_exposures(data)

    # Check AAPL has tech exposure = 1, others = 0
    assert exposures.filter(pl.col("ticker") == "AAPL")["Information Technology"][0] == 1.0
    assert exposures.filter(pl.col("ticker") == "AAPL")["Financials"][0] == 0.0

    # Check sector exposures sum to 1
    sector_cols = model.SECTOR_FACTORS
    for ticker in ["AAPL", "MSFT", "JPM"]:
        sector_sum = exposures.filter(pl.col("ticker") == ticker).select(sector_cols).sum(axis=1)[0]
        assert sector_sum == 1.0

def test_factor_model_style_standardization():
    """Test style factors are standardized"""
    model = EquityFactorModel()

    data = create_test_data(n_stocks=1000)  # Large sample for stats

    exposures = model.compute_exposures(data)

    # Check each style factor
    for style in model.STYLE_FACTORS:
        mean = exposures[style].mean()
        std = exposures[style].std()

        assert abs(mean) < 1e-10, f"{style} mean not zero: {mean}"
        assert abs(std - 1.0) < 1e-3, f"{style} std not 1.0: {std}"

def test_factor_model_matrix_dimensions():
    """Test exposure matrix has correct dimensions"""
    model = EquityFactorModel()

    data = create_test_data(n_stocks=500)
    exposures = model.compute_exposures(data)

    X = model.get_exposure_matrix(exposures)

    assert X.shape == (500, 17), f"Wrong shape: {X.shape}"

# ... 22 more tests
```

**Success Criteria**:
- [ ] `EquityFactorModel` implemented (17 factors)
- [ ] Sector exposures: 0/1 dummy variables (sum to 1 per stock)
- [ ] Style exposures: Standardized (mean=0, std=1)
- [ ] Exposure matrix X: N×17 numpy array
- [ ] Validation method checks constraints
- [ ] 25 tests passing
- [ ] Committed and pushed

---

### AGENT-16: FactorCovariance Implementation

**Objective**: Implement factor covariance estimator (V = X·F·X^T + Δ).

**Starting Context**:
1. `docs/books/grinold_kahn_equity_notes_part1_foundations.md` (Chapter 3, covariance decomposition)
2. `Risk/FactorModel/EquityFactorModel.py` (AGENT-15 output, X matrix)
3. `Risk/Covariance/SampleCovariance.py` (existing pattern)
4. `Risk/Covariance/LedoitWolfShrinkage.py` (existing shrinkage)

**Skills Required**:
- Covariance estimation
- Matrix operations
- Linear regression (factor returns estimation)
- Polars/NumPy

**Deliverables**:
```
Risk/Covariance/FactorCovariance.py

tests/unit/risk/test_factor_covariance.py (25 tests)
tests/integration/test_factor_vs_sample_covariance.py (5 tests)
```

**Implementation Guidance**:
```python
# Risk/Covariance/FactorCovariance.py

# ABOUTME: Factor covariance estimator (V = X·F·X^T + Δ)
# ABOUTME: Reduces parameters from N² to N·K + K² + N (99%+ reduction for large N)

import numpy as np
import polars as pl
from typing import Tuple
from Risk.Covariance.BaseCovariance import BaseCovariance
from Risk.FactorModel.EquityFactorModel import EquityFactorModel

class FactorCovariance(BaseCovariance):
    """
    Factor-based covariance estimator

    From Grinold-Kahn Chapter 3:
        V = X · F · X^T + Δ

    Where:
        X: N×K factor exposures
        F: K×K factor covariance
        Δ: N×N specific risk (diagonal matrix)

    Parameters reduced:
        Full: N² (e.g., 3000² = 9M)
        Factor: N·K + K² + N (e.g., 3000·17 + 17² + 3000 = 54,289)
        Reduction: 99.4%!
    """

    def __init__(self, factor_model: EquityFactorModel):
        self.factor_model = factor_model

    def estimate(
        self,
        returns: pl.DataFrame,  # N×T returns matrix
        exposures: pl.DataFrame,  # N×K exposures (from FactorModel)
    ) -> pl.DataFrame:
        """
        Estimate covariance matrix using factor decomposition

        Steps:
        1. Estimate factor returns b (K×T) via regression
        2. Estimate factor covariance F (K×K)
        3. Estimate specific returns u (N×T) as residuals
        4. Estimate specific variances Δ (N×N diagonal)
        5. Combine: V = X·F·X^T + Δ

        Returns:
            V: N×N covariance matrix (Polars DataFrame)
        """
        N = len(returns)
        K = len(self.factor_model.SECTOR_FACTORS) + len(self.factor_model.STYLE_FACTORS)
        T = returns.shape[1]

        # Convert to numpy for matrix ops
        X = self.factor_model.get_exposure_matrix(exposures)  # N×K
        R = returns.to_numpy()  # N×T

        # 1. Estimate factor returns via regression: R = X·b + u
        #    Solve: b = (X^T X)^(-1) X^T R
        b = np.linalg.lstsq(X, R, rcond=None)[0]  # K×T

        # 2. Estimate factor covariance F (K×K)
        F = np.cov(b)  # K×K

        # 3. Estimate specific returns u (N×T)
        u = R - X @ b  # N×T

        # 4. Estimate specific variances Δ (diagonal)
        specific_vars = np.var(u, axis=1)  # N×1
        Delta = np.diag(specific_vars)  # N×N (diagonal)

        # 5. Combine: V = X·F·X^T + Δ
        V = X @ F @ X.T + Delta  # N×N

        # Convert to Polars DataFrame
        tickers = returns.columns
        V_df = pl.DataFrame(V, schema=tickers)

        return V_df

    def estimate_factor_returns(
        self,
        returns: pl.DataFrame,
        exposures: pl.DataFrame,
    ) -> Tuple[np.ndarray, np.ndarray]:
        """
        Estimate factor returns and specific returns

        Returns:
            (factor_returns, specific_returns)
            - factor_returns: K×T
            - specific_returns: N×T
        """
        X = self.factor_model.get_exposure_matrix(exposures)
        R = returns.to_numpy()

        # Factor returns via regression
        b = np.linalg.lstsq(X, R, rcond=None)[0]  # K×T

        # Specific returns (residuals)
        u = R - X @ b  # N×T

        return b, u

    def validate_positive_definite(self, V: pl.DataFrame) -> bool:
        """
        Validate covariance matrix is positive definite

        Critical for optimization (ensures unique solution)
        """
        V_np = V.to_numpy()
        eigenvalues = np.linalg.eigvalsh(V_np)

        min_eigenvalue = eigenvalues.min()
        if min_eigenvalue <= 0:
            raise ValueError(f"Covariance matrix not positive definite! Min eigenvalue: {min_eigenvalue}")

        return True
```

**Testing Strategy**:
```python
# tests/unit/risk/test_factor_covariance.py

def test_factor_covariance_dimensions():
    """Test covariance matrix has correct dimensions"""
    model = EquityFactorModel()
    cov_estimator = FactorCovariance(model)

    data = create_test_data(n_stocks=100, n_days=252)
    exposures = model.compute_exposures(data)

    V = cov_estimator.estimate(data["returns"], exposures)

    assert V.shape == (100, 100)

def test_factor_covariance_positive_definite():
    """Test covariance matrix is positive definite"""
    model = EquityFactorModel()
    cov_estimator = FactorCovariance(model)

    data = create_test_data(n_stocks=100, n_days=252)
    exposures = model.compute_exposures(data)

    V = cov_estimator.estimate(data["returns"], exposures)

    # Check all eigenvalues > 0
    eigenvalues = np.linalg.eigvalsh(V.to_numpy())
    assert (eigenvalues > 0).all(), f"Negative eigenvalue: {eigenvalues.min()}"

def test_factor_vs_sample_covariance():
    """Compare factor covariance to sample covariance"""
    model = EquityFactorModel()
    factor_cov = FactorCovariance(model)
    sample_cov = SampleCovariance()

    data = create_test_data(n_stocks=100, n_days=252)
    exposures = model.compute_exposures(data)

    V_factor = factor_cov.estimate(data["returns"], exposures)
    V_sample = sample_cov.estimate(data["returns"])

    # Factor covariance should be smoother (lower condition number)
    cond_factor = np.linalg.cond(V_factor.to_numpy())
    cond_sample = np.linalg.cond(V_sample.to_numpy())

    assert cond_factor < cond_sample, "Factor cov should have lower condition number"

# ... 22 more tests
```

**Success Criteria**:
- [ ] `FactorCovariance` implemented (V = X·F·X^T + Δ)
- [ ] Factor returns estimated via regression
- [ ] Positive definiteness validated
- [ ] Condition number < 100 (vs ~1000 for sample covariance)
- [ ] 30 tests passing (25 unit + 5 integration)
- [ ] Committed and pushed

---

### AGENT-17: PPFMCovariance Implementation

**Objective**: Implement PPFM (Projection-Penalized Factor Model) multi-sector covariance.

**Starting Context**:
1. `docs/papers/multi_sector_portfolio_optimization_2507.16433.pdf` (full paper, Algorithm 2)
2. `docs/books/grinold_kahn_equity_notes_part1_foundations.md` (Chapter 3, covariance)
3. `docs/design/EQUITY_SECTOR_IMPLEMENTATION_PLAN.md` (Phase 3, Section 3.3)
4. `Risk/Covariance/FactorCovariance.py` (AGENT-16 output, baseline)
5. `Risk/FactorModel/EquityFactorModel.py` (AGENT-15 output, exposures)

**Skills Required**:
- Advanced linear algebra (projection matrices, eigenvectors)
- Iterative optimization
- Cross-validation
- NumPy/SciPy

**Deliverables**:
```
Risk/Covariance/PPFMCovariance.py

tests/unit/risk/test_ppfm_covariance.py (30 tests)
tests/integration/test_ppfm_vs_baselines.py (10 tests)
tests/validation/test_ppfm_paper_replication.py (5 tests)
```

**Implementation Guidance** (see separate document due to complexity):
```python
# Risk/Covariance/PPFMCovariance.py

# ABOUTME: Projection-Penalized Factor Model covariance (from paper arXiv:2507.16433)
# ABOUTME: Learns sector relatedness via joint estimation across sectors

import numpy as np
import polars as pl
from typing import Dict, Optional, Tuple
from Risk.Covariance.BaseCovariance import BaseCovariance

class PPFMCovariance(BaseCovariance):
    """
    PPFM: Multi-sector covariance with projection penalty

    From paper (Algorithm 2, page 14):
        Jointly estimate factors F^(m) for each sector m
        Penalize differences between sector projection matrices P^(m)
        Learn optimal sector relatedness via λ (cross-validated)

    Objective (Equation 2.8):
        L = Σ_m [1/T ||R^(m) - B^(m) F^(m)||^2] +
            λ/T Σ_{m,m'} ||P^(m) - P^(m')||_F^2

    Where:
        R^(m): Returns for sector m (p_m × T)
        B^(m): Factor loadings (p_m × K)
        F^(m): Factor time series (K × T)
        P^(m): Projection matrix F^(m) (F^(m)^T F^(m))^(-1) F^(m)^T

    Key insight: If sectors related, P^(m) ≈ P^(m') (similar factor structure)
    """

    def __init__(
        self,
        n_factors: int = 2,
        lambda_reg: Optional[float] = None,  # None = cross-validate
        max_iter: int = 100,
        tolerance: float = 1e-6,
    ):
        self.K = n_factors
        self.lambda_reg = lambda_reg
        self.max_iter = max_iter
        self.tolerance = tolerance

    def estimate(
        self,
        returns_by_sector: Dict[str, pl.DataFrame],  # {sector: returns_df}
    ) -> pl.DataFrame:
        """
        Estimate multi-sector covariance via PPFM

        Args:
            returns_by_sector: {sector_name: returns_dataframe}
                Example: {
                    "Information Technology": pl.DataFrame(...),  # 450 stocks × 252 days
                    "Financials": pl.DataFrame(...),  # 510 stocks × 252 days
                    ...
                }

        Returns:
            Full N×N covariance matrix (all stocks, all sectors)
        """
        M = len(returns_by_sector)  # Number of sectors

        # Cross-validate λ if not provided
        if self.lambda_reg is None:
            self.lambda_reg = self._cross_validate_lambda(returns_by_sector)

        # Initialize factors F^(m) via PCA per sector
        F_dict, B_dict = self._initialize_factors(returns_by_sector)

        # Iterate until convergence
        for iteration in range(self.max_iter):
            # Update factors F^(m) with projection penalty
            F_dict_new = self._update_factors(returns_by_sector, F_dict, B_dict)

            # Update loadings B^(m)
            B_dict_new = self._update_loadings(returns_by_sector, F_dict_new)

            # Check convergence
            delta_L = self._compute_objective_change(
                returns_by_sector, F_dict, B_dict, F_dict_new, B_dict_new
            )

            if delta_L < self.tolerance:
                print(f"PPFM converged after {iteration+1} iterations")
                break

            F_dict, B_dict = F_dict_new, B_dict_new

        # Reconstruct sector covariances Σ^(m) = B^(m) Σ_f B^(m)^T + Σ_e^(m)
        sector_covariances = self._reconstruct_covariances(
            returns_by_sector, F_dict, B_dict
        )

        # Assemble full block-diagonal covariance matrix
        full_cov = self._assemble_full_covariance(sector_covariances)

        return full_cov

    def _initialize_factors(
        self,
        returns_by_sector: Dict[str, pl.DataFrame],
    ) -> Tuple[Dict, Dict]:
        """
        Initialize F^(m) and B^(m) via PCA per sector

        From paper: F^(m,0) = √T · eigenvectors_K(R^(m)^T R^(m))
        """
        F_dict = {}
        B_dict = {}

        for sector, returns_df in returns_by_sector.items():
            R = returns_df.to_numpy()  # p_m × T
            T = R.shape[1]

            # Compute R^T R (T × T covariance in time dimension)
            RTR = R.T @ R  # T × T

            # Compute top K eigenvectors
            eigenvalues, eigenvectors = np.linalg.eigh(RTR)
            # Sort by descending eigenvalue
            idx = eigenvalues.argsort()[::-1]
            top_K_eigenvectors = eigenvectors[:, idx[:self.K]]  # T × K

            # Scale by √T
            F_init = np.sqrt(T) * top_K_eigenvectors  # T × K
            F_dict[sector] = F_init.T  # Store as K × T

            # Initialize B^(m) = T^(-1) R^(m) F^(m)
            B_init = (1/T) * R @ F_init  # p_m × K
            B_dict[sector] = B_init

        return F_dict, B_dict

    def _update_factors(
        self,
        returns_by_sector: Dict[str, pl.DataFrame],
        F_dict: Dict,
        B_dict: Dict,
    ) -> Dict:
        """
        Update factors F^(m) with projection penalty

        From paper (Algorithm 2, step 2a):
            V^(m) = T^(-1) R^(m)^T R^(m) - λ T^(-1) Σ_{m'≠m} (I_T - 2P^(m'))
            F^(m) = √T · eigenvectors_K(V^(m))
        """
        F_dict_new = {}
        M = len(returns_by_sector)

        # Compute all projection matrices P^(m)
        P_dict = {}
        for sector, F in F_dict.items():
            P_dict[sector] = self._compute_projection_matrix(F)

        for sector, returns_df in returns_by_sector.items():
            R = returns_df.to_numpy()
            T = R.shape[1]

            # Compute V^(m)
            RTR = R.T @ R  # T × T
            V = (1/T) * RTR  # T × T

            # Add projection penalty
            for other_sector, P_other in P_dict.items():
                if other_sector != sector:
                    V -= (self.lambda_reg / T) * (np.eye(T) - 2 * P_other)

            # Update F^(m) via eigendecomposition
            eigenvalues, eigenvectors = np.linalg.eigh(V)
            idx = eigenvalues.argsort()[::-1]
            top_K = eigenvectors[:, idx[:self.K]]

            F_new = np.sqrt(T) * top_K  # T × K
            F_dict_new[sector] = F_new.T  # Store as K × T

        return F_dict_new

    def _compute_projection_matrix(self, F: np.ndarray) -> np.ndarray:
        """
        Compute projection matrix P = F (F^T F)^(-1) F^T

        Args:
            F: K × T factor matrix

        Returns:
            P: T × T projection matrix
        """
        K, T = F.shape
        F_T = F.T  # T × K

        # P = F^T (F F^T)^(-1) F
        FFT = F @ F_T  # K × K
        FFT_inv = np.linalg.inv(FFT + 1e-6 * np.eye(K))  # Regularize

        P = F_T @ FFT_inv @ F  # T × T

        return P

    def _update_loadings(
        self,
        returns_by_sector: Dict[str, pl.DataFrame],
        F_dict: Dict,
    ) -> Dict:
        """
        Update loadings B^(m) = T^(-1) R^(m) F^(m)
        """
        B_dict = {}

        for sector, returns_df in returns_by_sector.items():
            R = returns_df.to_numpy()  # p_m × T
            F = F_dict[sector]  # K × T
            T = R.shape[1]

            B = (1/T) * R @ F.T  # p_m × K
            B_dict[sector] = B

        return B_dict

    def _reconstruct_covariances(
        self,
        returns_by_sector: Dict[str, pl.DataFrame],
        F_dict: Dict,
        B_dict: Dict,
    ) -> Dict[str, np.ndarray]:
        """
        Reconstruct sector covariances Σ^(m) = B^(m) Σ_f B^(m)^T + Σ_e^(m)

        From paper (Equation 2.11)
        """
        cov_dict = {}

        for sector, returns_df in returns_by_sector.items():
            R = returns_df.to_numpy()
            B = B_dict[sector]  # p_m × K
            F = F_dict[sector]  # K × T

            # Factor covariance Σ_f (K × K)
            Sigma_f = np.cov(F)  # K × K

            # Specific returns u = R - B F
            u = R - B @ F  # p_m × T

            # Specific covariance Σ_e (p_m × p_m, diagonal)
            specific_vars = np.var(u, axis=1)  # p_m
            Sigma_e = np.diag(specific_vars)  # p_m × p_m

            # Total covariance
            Sigma = B @ Sigma_f @ B.T + Sigma_e  # p_m × p_m

            cov_dict[sector] = Sigma

        return cov_dict

    def _assemble_full_covariance(
        self,
        sector_covariances: Dict[str, np.ndarray],
    ) -> pl.DataFrame:
        """Assemble block-diagonal full covariance matrix"""
        # Stack sector covariances along diagonal
        blocks = list(sector_covariances.values())
        full_cov = scipy.linalg.block_diag(*blocks)

        # Convert to Polars (with ticker column names)
        return pl.DataFrame(full_cov)

    def _cross_validate_lambda(
        self,
        returns_by_sector: Dict[str, pl.DataFrame],
        n_folds: int = 5,
    ) -> float:
        """
        Cross-validate λ via grid search

        From paper (Equation 2.13): Minimize out-of-sample portfolio risk
        """
        lambda_grid = [0, 0.1, 0.5, 1, 2, 5, 10, 20, 50]

        best_lambda = None
        best_risk = float('inf')

        for lambda_candidate in lambda_grid:
            # ... implement K-fold CV ...
            # Compute out-of-sample risk for each fold
            # Average across folds
            avg_risk = ...

            if avg_risk < best_risk:
                best_risk = avg_risk
                best_lambda = lambda_candidate

        return best_lambda
```

**Success Criteria**:
- [ ] PPFM algorithm implemented (Algorithm 2 from paper)
- [ ] Converges in <10 iterations (typical)
- [ ] Cross-validation for λ working
- [ ] Outperforms FactorCovariance by 10-15% risk reduction
- [ ] Paper replication: Within 10% of Table 2 results
- [ ] 45 tests passing (30 unit + 10 integration + 5 validation)
- [ ] Committed and pushed

---

## WAVE 5: LONG/SHORT OPTIMIZATION (Weeks 12-14)

(Continue with AGENT-18, AGENT-19...)

---

## WAVE 6: END-TO-END INTEGRATION (Weeks 15-17)

(AGENT-20...)

---

**End of Part 2**

(Peter, I'll create the remaining sections (Waves 5-6) in a follow-up commit. This covers the critical middle waves with detailed specifications for each agent.)
