# Equity Sector Portfolio Implementation Plan

**Date**: 2025-11-11
**Status**: Final Plan (Post Grinold-Kahn Book Study)
**Branch**: `claude/equity-sector-portfolio-planning-011CV2pP4NRAwS4k6wTNsm1u`
**Timeline**: 17 weeks (4 months)

---

## Executive Summary

### Goal
Extend ARBS from futures/swaps to **sector-based equity portfolios** using Grinold-Kahn methodology combined with PPFM (Projection-Penalized Factor Model) multi-sector covariance estimation.

### Key Insight
**ARBS is already Grinold-Kahn compliant!** The returns-first architecture, IC × Vol × Z formula, and mean-variance optimization are exact matches to the book. We're bringing ARBS back to its native domain (equities).

### Critical Success Factors
1. **Polars-native from day 1** - No pandas migration later
2. **Cross-sectional signals** - Rank within universe, not time-series
3. **Constraints matter** - Long-only cuts IR by ~50%
4. **Breadth advantage** - 8× more bets than futures (2,000 vs 240/year)
5. **Lower IC per bet** - 0.03-0.06 vs 0.08-0.15, but compensated by breadth

### Target Metrics
- **Information Ratio**: 1.0+ (vs top-quartile benchmark of 0.5)
- **IC** (Value): 0.03-0.04
- **IC** (Momentum): 0.04-0.06
- **IC** (Quality): 0.02-0.03
- **Combined IC**: 0.06-0.07
- **Breadth**: 2,000 bets/year (500 stocks × 4 quarters)

---

## Phase 1: Query & Data Infrastructure (Weeks 1-3)

### Objectives
- Create equity query layer parallel to FuturesQuery
- Integrate Yahoo Finance as data provider
- Build adapter converting queries → Polars DataFrames

### Components to Create

#### 1.1 EquityQuery Structure

**File**: `Query/Equities/EquityQuery.py`

```python
# ABOUTME: Query structure for equity instruments
# ABOUTME: Parallel design to FuturesQuery with sector support

@dataclass
class EquityQuery(BaseQuery):
    ticker: str
    sector: str  # GICS Level 1 (11 sectors)
    structure: EquityStructure
    value: EquityValue
    lookback_days: int = 252  # 1 year default
    weight: float = 1.0
    metadata: dict = field(default_factory=dict)

    def build_mdp_request(self, as_of_date: date) -> dict:
        """Convert to MDP request format"""
        return {
            "ticker": self.ticker,
            "start_date": as_of_date - timedelta(days=self.lookback_days),
            "end_date": as_of_date,
            "fields": ["price", "dividend", "split_factor", "fundamentals"],
        }
```

**File**: `Query/Equities/EquityStructure.py`

```python
# ABOUTME: Enumeration of equity structure types (single, basket, long/short)
# ABOUTME: Analogous to OUTRIGHT, CALENDAR, FLY for futures

class EquityStructure(Enum):
    SINGLE = "single"  # Single stock position
    SECTOR_BASKET = "sector_basket"  # Equal-weight basket within sector
    LONG_SHORT = "long_short"  # Pairs trade
    MARKET_NEUTRAL = "market_neutral"  # Long sector, short market
```

**File**: `Query/Equities/EquityValue.py`

```python
# ABOUTME: Enumeration of equity value types (price, return, yield)
# ABOUTME: Analogous to PRICE, YIELD for swaps

class EquityValue(Enum):
    PRICE = "price"
    RETURN = "return"
    LOG_RETURN = "log_return"
    DIVIDEND_YIELD = "dividend_yield"
    EARNINGS_YIELD = "earnings_yield"  # E/P ratio
    VOLATILITY = "volatility"
```

#### 1.2 Yahoo Finance Market Data Provider

**File**: `MDP/YahooFinance/YahooFinanceMDP.py`

```python
# ABOUTME: Yahoo Finance data provider for equity prices, dividends, fundamentals
# ABOUTME: Handles rate limiting, caching, sector classification

import yfinance as yf
import polars as pl
from typing import List
from datetime import date

class YahooFinanceMDP(MarketDataProvider):
    def __init__(self, cache_backend: str = "zodb"):
        self.cache = self._init_cache(cache_backend)

    def get_equity_data(
        self,
        tickers: List[str],
        start_date: date,
        end_date: date,
        fields: List[str] = ["price", "dividend"],
    ) -> pl.DataFrame:
        """
        Fetch equity data from Yahoo Finance

        Returns Polars DataFrame:
            - ticker: str
            - date: date
            - price: float (adjusted for splits/dividends)
            - dividend: float
            - volume: int
            - sector: str (GICS Level 1)
        """
        # Check cache first
        cache_key = self._cache_key(tickers, start_date, end_date)
        if cached := self.cache.get(cache_key):
            return cached

        # Batch API call (max 100 tickers per call for rate limiting)
        data_frames = []
        for batch in self._batch_tickers(tickers, batch_size=100):
            batch_data = yf.download(
                tickers=batch,
                start=start_date,
                end=end_date,
                progress=False,
                threads=True,
            )
            data_frames.append(self._to_polars(batch_data))

        # Combine and cache
        result = pl.concat(data_frames)
        result = self._add_sector_classification(result)
        self.cache.set(cache_key, result)

        return result

    def _add_sector_classification(self, df: pl.DataFrame) -> pl.DataFrame:
        """Add GICS sector from Yahoo Finance info"""
        sector_map = {}
        for ticker in df["ticker"].unique():
            info = yf.Ticker(ticker).info
            sector_map[ticker] = info.get("sector", "Unknown")

        return df.with_columns(
            pl.col("ticker").map_dict(sector_map).alias("sector")
        )
```

**File**: `MDP/YahooFinance/sector_mapping.py`

```python
# ABOUTME: GICS sector classification mapping
# ABOUTME: 11 GICS Level 1 sectors used throughout ARBS

GICS_SECTORS = {
    10: "Energy",
    15: "Materials",
    20: "Industrials",
    25: "Consumer Discretionary",
    30: "Consumer Staples",
    35: "Health Care",
    40: "Financials",
    45: "Information Technology",
    50: "Communication Services",
    55: "Utilities",
    60: "Real Estate",
}

def get_sector_tickers(sector_name: str, universe: str = "sp500") -> List[str]:
    """Get all tickers in a GICS sector"""
    # Implementation: Query S&P 500 constituents by sector
    pass
```

#### 1.3 EquityAdapter

**File**: `Adapter/EquityAdapter.py`

```python
# ABOUTME: Adapter converting EquityQuery to standardized Polars DataFrame
# ABOUTME: Output format compatible with ReturnsCalculator

class EquityAdapter(BaseAdapter):
    def convert(
        self,
        queries: List[EquityQuery],
        as_of_date: date,
        mdp: YahooFinanceMDP,
    ) -> pl.DataFrame:
        """
        Convert EquityQuery list to standardized format

        Output schema:
            - ticker: str
            - sector: str
            - returns: List[float] (historical returns array)
            - price: float (current price)
            - market_cap: float
            - fundamentals: dict (E/P, B/P, ROE, etc.)
        """
        # Build MDP requests
        tickers = [q.ticker for q in queries]
        start_date = min(q.as_of_date - timedelta(days=q.lookback_days) for q in queries)

        # Fetch data
        raw_data = mdp.get_equity_data(tickers, start_date, as_of_date)

        # Compute returns
        returns_df = raw_data.group_by("ticker").agg(
            pl.col("price").pct_change().alias("returns")
        )

        # Add metadata
        result = returns_df.join(
            raw_data.group_by("ticker").agg(
                pl.col("sector").first(),
                pl.col("price").last().alias("price"),
                pl.col("volume").mean().alias("avg_volume"),
            ),
            on="ticker",
        )

        return result
```

### Deliverables
- ✅ `Query/Equities/` module (3 files)
- ✅ `MDP/YahooFinance/` module (2 files)
- ✅ `Adapter/EquityAdapter.py` (1 file)

### Testing Strategy
```python
# tests/unit/query/test_equity_query.py (15 tests)
def test_equity_query_creation():
    query = EquityQuery(ticker="AAPL", sector="Information Technology", ...)
    assert query.ticker == "AAPL"

# tests/integration/test_yahoo_finance_mdp.py (10 tests)
def test_fetch_sp500_data():
    mdp = YahooFinanceMDP()
    data = mdp.get_equity_data(["AAPL", "MSFT"], start_date, end_date)
    assert isinstance(data, pl.DataFrame)
    assert "sector" in data.columns

# tests/integration/test_equity_adapter.py (8 tests)
def test_adapter_polars_output():
    queries = [EquityQuery(...), EquityQuery(...)]
    df = adapter.convert(queries, as_of_date, mdp)
    assert isinstance(df, pl.DataFrame)  # Ensure Polars, not pandas!
```

### Success Criteria
- [ ] Can query S&P 500 constituents by sector
- [ ] Yahoo Finance data cached (sub-second on cache hit)
- [ ] Adapter outputs Polars DataFrame (NO pandas!)
- [ ] Missing data handled gracefully (forward fill, then drop)
- [ ] 33 tests passing

---

## Phase 2: Equity Signals (Weeks 4-7)

### Objectives
- Implement 3 core equity signals (Value, Momentum, Quality)
- Extend BaseSignal with cross-sectional methods
- Validate IC targets from book

### Components to Create

#### 2.1 ValueSignal (DDM + E/P)

**File**: `Signals/Equities/ValueSignal.py`

```python
# ABOUTME: Value signal based on dividend discount model and earnings yield
# ABOUTME: Expected IC: 0.03-0.04, Horizon: 12-24 months (Grinold-Kahn Ch 9)

class ValueSignal(BaseSignal):
    """
    Value signal combining DDM and E/P ratio

    Formula (from Grinold-Kahn Ch 9):
        α_value = d/p + g - β·f_B

    Where:
        d/p = dividend yield
        g = (1 - payout_ratio) × ROE
        β = equity beta
        f_B = market risk premium (default: 6%)
    """

    def __init__(self, market_risk_premium: float = 0.06):
        super().__init__(name="value", expected_ic=0.03)
        self.f_B = market_risk_premium

    def calculate(self, data: pl.DataFrame) -> pl.DataFrame:
        """
        Compute value z-scores cross-sectionally

        Input columns:
            - ticker, sector, dividend_yield, roe, payout_ratio, beta

        Output:
            - ticker, z_score (sector-neutral)
        """
        # DDM alpha
        ddm_alpha = (
            data["dividend_yield"]
            + data["roe"] * (1 - data["payout_ratio"])
            - data["beta"] * self.f_B
        )

        # Convert to sector-neutral z-scores
        z_scores = self._to_sector_neutral_scores(ddm_alpha, data["sector"])

        return pl.DataFrame({"ticker": data["ticker"], "z_score": z_scores})

    def _to_sector_neutral_scores(
        self, signal: pl.Series, sectors: pl.Series
    ) -> pl.Series:
        """Compute z-scores within each sector"""
        df = pl.DataFrame({"signal": signal, "sector": sectors})
        return (
            df.group_by("sector")
            .agg((pl.col("signal") - pl.col("signal").mean()) / pl.col("signal").std())
            .explode("signal")["signal"]
        )
```

#### 2.2 MomentumSignal (12-month return)

**File**: `Signals/Equities/MomentumSignal.py`

```python
# ABOUTME: Momentum signal based on 12-month return (skip last month)
# ABOUTME: Expected IC: 0.04-0.06, Horizon: 3-6 months (Grinold-Kahn Ch 11)

class MomentumSignal(BaseSignal):
    """
    Momentum signal: 12-month return (skip last month)

    From Grinold-Kahn Ch 11: Skip last month to avoid reversal effect
    """

    def __init__(self):
        super().__init__(name="momentum", expected_ic=0.05)

    def calculate(self, data: pl.DataFrame) -> pl.DataFrame:
        """
        Compute momentum z-scores cross-sectionally

        Input columns:
            - ticker, sector, returns (list of daily returns)

        Output:
            - ticker, z_score (sector-neutral)
        """
        # Calculate 12-month return (skip last 21 days)
        momentum_returns = data["returns"].list.slice(offset=0, length=-21).list.sum()

        # Convert to sector-neutral z-scores
        z_scores = self._to_sector_neutral_scores(momentum_returns, data["sector"])

        return pl.DataFrame({"ticker": data["ticker"], "z_score": z_scores})
```

#### 2.3 QualitySignal (ROE + Debt/Equity)

**File**: `Signals/Equities/QualitySignal.py`

```python
# ABOUTME: Quality signal based on ROE and balance sheet strength
# ABOUTME: Expected IC: 0.02-0.03, Horizon: 24+ months (Grinold-Kahn Ch 9)

class QualitySignal(BaseSignal):
    """
    Quality signal: ROE, Debt/Equity (inverted), Earnings stability
    """

    def __init__(self):
        super().__init__(name="quality", expected_ic=0.025)

    def calculate(self, data: pl.DataFrame) -> pl.DataFrame:
        """
        Compute quality z-scores cross-sectionally

        Input columns:
            - ticker, sector, roe, debt_to_equity, earnings_std

        Output:
            - ticker, z_score (sector-neutral)
        """
        # Quality composite
        quality_score = (
            data["roe"] * 0.5  # High ROE good
            - data["debt_to_equity"] * 0.3  # High debt bad
            - data["earnings_std"] * 0.2  # High volatility bad
        )

        # Convert to sector-neutral z-scores
        z_scores = self._to_sector_neutral_scores(quality_score, data["sector"])

        return pl.DataFrame({"ticker": data["ticker"], "z_score": z_scores})
```

#### 2.4 Extend BaseSignal for Cross-Sectional

**File**: `Signals/BaseSignal.py` (ADD method)

```python
class BaseSignal:
    # ... existing methods ...

    def to_cross_sectional_scores(
        self, signal: pl.Series, groupby_col: pl.Series = None
    ) -> pl.Series:
        """
        Convert signal to cross-sectional z-scores

        From Grinold-Kahn Ch 11: Equity signals are cross-sectional
        (rank within universe) not time-series (compare to own history)

        If groupby_col provided (e.g., sector), compute z-scores within groups
        """
        if groupby_col is None:
            # Global z-scores
            return (signal - signal.mean()) / signal.std()
        else:
            # Group-specific z-scores (e.g., sector-neutral)
            df = pl.DataFrame({"signal": signal, "group": groupby_col})
            return (
                df.group_by("group")
                .agg((pl.col("signal") - pl.col("signal").mean()) / pl.col("signal").std())
                .explode("signal")["signal"]
            )
```

### Deliverables
- ✅ `Signals/Equities/ValueSignal.py`
- ✅ `Signals/Equities/MomentumSignal.py`
- ✅ `Signals/Equities/QualitySignal.py`
- ✅ `BaseSignal.to_cross_sectional_scores()` method

### Testing Strategy
```python
# tests/unit/signals/test_value_signal.py (20 tests)
def test_value_signal_ddm_formula():
    signal = ValueSignal()
    data = pl.DataFrame({
        "ticker": ["AAPL", "MSFT"],
        "dividend_yield": [0.005, 0.01],
        "roe": [0.30, 0.25],
        "payout_ratio": [0.20, 0.25],
        "beta": [1.2, 1.1],
        "sector": ["Information Technology", "Information Technology"],
    })
    result = signal.calculate(data)
    assert result["z_score"].mean() < 0.01  # Approximately zero mean

# tests/integration/test_signal_ic.py (15 tests)
def test_value_signal_ic():
    """Validate IC is in expected range (0.03-0.04)"""
    signal = ValueSignal()
    forecasts = signal.calculate(historical_data)
    realized_returns = get_realized_returns(historical_data, horizon="12M")
    ic = calculate_ic(forecasts, realized_returns)
    assert 0.02 < ic < 0.05  # Expected range from book
```

### Success Criteria
- [ ] Value signal IC: 0.03-0.04 (on historical data)
- [ ] Momentum signal IC: 0.04-0.06
- [ ] Quality signal IC: 0.02-0.03
- [ ] Sector-neutral scores: mean ≈ 0, std ≈ 1 within each sector
- [ ] 55 tests passing

---

## Phase 3: Multi-Factor Risk Model (Weeks 8-11)

### Objectives
- Implement 17-factor model (11 sectors + 6 styles)
- Create factor covariance estimator (V = X·F·X^T + Δ)
- Integrate PPFM for multi-sector covariance

### Components to Create

#### 3.1 EquityFactorModel

**File**: `Risk/FactorModel/EquityFactorModel.py`

```python
# ABOUTME: 17-factor equity model (11 GICS sectors + 6 style factors)
# ABOUTME: Factor structure from Grinold-Kahn Ch 3

class EquityFactorModel:
    """
    17-factor model for equities:
        - 11 GICS sectors (dummy variables)
        - 6 styles (standardized exposures)

    From Grinold-Kahn Ch 3: r_n = Σ_k X_{n,k} · b_k + u_n
    """

    SECTOR_FACTORS = [
        "Energy", "Materials", "Industrials", "Consumer Discretionary",
        "Consumer Staples", "Health Care", "Financials", "Information Technology",
        "Communication Services", "Utilities", "Real Estate",
    ]

    STYLE_FACTORS = [
        "Size",  # log(market_cap)
        "Value",  # B/P ratio
        "Momentum",  # 12-month return
        "Quality",  # ROE
        "Low Volatility",  # inverse of volatility
        "Dividend Yield",  # dividend / price
    ]

    def compute_exposures(self, data: pl.DataFrame) -> pl.DataFrame:
        """
        Compute factor exposures X (N×K matrix)

        Input:
            - ticker, sector, market_cap, book_value, price, roe, volatility, dividend

        Output:
            - ticker + 17 columns (one per factor)
            - Sector exposures: 0/1 dummy variables
            - Style exposures: Standardized (mean=0, std=1)
        """
        N = len(data)
        exposures = pl.DataFrame({"ticker": data["ticker"]})

        # Sector exposures (dummy variables)
        for sector in self.SECTOR_FACTORS:
            exposures = exposures.with_columns(
                (data["sector"] == sector).cast(pl.Float64).alias(sector)
            )

        # Style exposures (standardized)
        exposures = exposures.with_columns(
            self._standardize(np.log(data["market_cap"])).alias("Size"),
            self._standardize(data["book_value"] / data["price"]).alias("Value"),
            self._standardize(data["12m_return"]).alias("Momentum"),
            self._standardize(data["roe"]).alias("Quality"),
            self._standardize(1 / data["volatility"]).alias("Low Volatility"),
            self._standardize(data["dividend"] / data["price"]).alias("Dividend Yield"),
        )

        return exposures

    def _standardize(self, series: pl.Series) -> pl.Series:
        """Standardize to mean=0, std=1"""
        return (series - series.mean()) / series.std()
```

#### 3.2 FactorCovariance

**File**: `Risk/Covariance/FactorCovariance.py`

```python
# ABOUTME: Factor covariance estimator (V = X·F·X^T + Δ)
# ABOUTME: Reduces parameters from N² to N·K + K² (Grinold-Kahn Ch 3)

class FactorCovariance:
    """
    Covariance decomposition: V = X · F · X^T + Δ

    Where:
        X: N×K exposures
        F: K×K factor covariance
        Δ: N×N specific risk (diagonal)
    """

    def estimate(
        self,
        returns: pl.DataFrame,  # N×T returns matrix
        exposures: pl.DataFrame,  # N×K exposures
    ) -> pl.DataFrame:
        """
        Estimate full covariance matrix

        Returns N×N covariance (Polars DataFrame)
        """
        N, K = exposures.shape
        T = returns.shape[1]

        # Estimate factor returns (K×T)
        X = exposures.to_numpy()
        R = returns.to_numpy()
        factor_returns = np.linalg.lstsq(X, R, rcond=None)[0]  # K×T

        # Estimate factor covariance F (K×K)
        F = np.cov(factor_returns)

        # Estimate specific returns (N×T)
        specific_returns = R - X @ factor_returns

        # Estimate specific risk Δ (N×N diagonal)
        specific_var = np.var(specific_returns, axis=1)
        Delta = np.diag(specific_var)

        # Full covariance
        V = X @ F @ X.T + Delta

        return pl.DataFrame(V, schema=[f"asset_{i}" for i in range(N)])
```

#### 3.3 PPFMCovariance

**File**: `Risk/Covariance/PPFMCovariance.py`

```python
# ABOUTME: Projection-Penalized Factor Model covariance (from paper)
# ABOUTME: Learns sector relatedness via joint estimation across sectors

class PPFMCovariance:
    """
    PPFM: Multi-sector covariance with projection penalty

    From paper (arXiv:2507.16433):
        L = Σ_m [fit_error_m] + λ Σ_{m,m'} ||P^(m) - P^(m')||_F^2

    Where P^(m) = projection matrix for sector m factors
    """

    def estimate(
        self,
        returns_by_sector: Dict[str, pl.DataFrame],  # {sector: returns_df}
        K: int = 2,  # Factors per sector
        lambda_reg: float = None,  # Auto cross-validate if None
    ) -> pl.DataFrame:
        """
        Estimate multi-sector covariance via PPFM

        Returns full N×N covariance matrix (all stocks, all sectors)
        """
        # Algorithm 2 from paper
        # 1. Initialize factors F^(m) via PCA per sector
        # 2. Iterate: update F^(m) with projection penalty
        # 3. Convergence check (ΔL < tolerance)
        # 4. Reconstruct covariance Σ^(m) = B^(m) Σ_f B^(m)^T + Σ_e^(m)
        # 5. Assemble full block matrix

        # See detailed notes in:
        # docs/books/grinold_kahn_equity_notes_part3_forecasting.md
        # docs/design/GRINOLD_KAHN_KNOWLEDGE_GRAPH.md

        pass  # Implementation follows paper Algorithm 2
```

### Deliverables
- ✅ `Risk/FactorModel/EquityFactorModel.py`
- ✅ `Risk/Covariance/FactorCovariance.py`
- ✅ `Risk/Covariance/PPFMCovariance.py`

### Success Criteria
- [ ] Factor model: 500² → 37,225 parameters (93% reduction)
- [ ] FactorCovariance: Positive definite, condition number < 100
- [ ] PPFM: Converges in <10 iterations
- [ ] PPFM vs Ledoit-Wolf: 10-15% risk reduction (from paper)
- [ ] 45 tests passing

---

## Phase 4: Optimization with Constraints (Weeks 12-14)

### Objectives
- Implement modular constraint system
- Measure transfer coefficient (TC) impact
- Integrate transaction costs

### Components to Create

#### 4.1 Constraint System

**Files**: `Optimizer/constraints/*.py`

```python
# LongOnly.py
class LongOnlyConstraint:
    """h_i ≥ 0 for all i"""
    def apply(self, problem):
        problem.add_constraint(problem.weights >= 0)

# SectorNeutral.py
class SectorNeutralConstraint:
    """Σ_{i ∈ sector} (h_i - h_Bi) = 0"""
    def apply(self, problem, sector_exposures):
        for sector in sectors:
            mask = sector_exposures == sector
            problem.add_constraint(
                problem.weights[mask].sum() == benchmark_weights[mask].sum()
            )

# PositionLimit.py
class PositionLimitConstraint:
    """|h_i - h_Bi| ≤ w_max"""
    def apply(self, problem, limit=0.05):
        problem.add_constraint(
            abs(problem.weights - benchmark_weights) <= limit
        )

# TurnoverLimit.py
class TurnoverConstraint:
    """Σ |h_i - h_old| ≤ TO_max"""
    def apply(self, problem, old_weights, max_turnover):
        problem.add_constraint(
            (abs(problem.weights - old_weights)).sum() <= max_turnover
        )
```

#### 4.2 Transaction Cost Model

**File**: `TransactionCosts/InventoryRiskModel.py`

```python
# ABOUTME: Square-root market impact model (Grinold-Kahn Ch 16)
# ABOUTME: TC = c·σ·√(V_trade/V_avg) + commission

class InventoryRiskModel:
    """
    From Grinold-Kahn Ch 16: TC ∝ √(trade_size / avg_volume)

    Rule: Costs ~1 day's volatility to trade 1 day's volume
    """

    def calculate_cost(
        self,
        trade_size: pl.Series,  # Shares to trade
        avg_daily_volume: pl.Series,
        volatility: pl.Series,  # Daily vol (%)
        cost_coefficient: float = 1.0,
        commission_rate: float = 0.001,  # 10 bps
    ) -> pl.Series:
        """Calculate total transaction cost per stock"""
        # Market impact (square-root law)
        volume_fraction = trade_size.abs() / avg_daily_volume
        impact = cost_coefficient * volatility * volume_fraction.sqrt()

        # Commission (proportional)
        commission = commission_rate * trade_size.abs()

        return impact + commission
```

### Deliverables
- ✅ `Optimizer/constraints/` (4 constraint types)
- ✅ `TransactionCosts/InventoryRiskModel.py`
- ✅ Transfer coefficient analysis tool

### Success Criteria
- [ ] Unconstrained: TC = 1.0 (baseline)
- [ ] Long-only: TC ≈ 0.5-0.6 (IR cut by ~50%)
- [ ] Long-only + sector-neutral: TC ≈ 0.4-0.5
- [ ] Transaction cost integration reduces turnover by 30-40%
- [ ] 30 tests passing

---

## Phase 5: Analysis & Attribution (Weeks 15-17)

### Objectives
- Factor decomposition of returns
- Extend TearSheet with equity-specific metrics
- Validate against paper benchmarks

### Components to Create

#### 5.1 FactorAttribution

**File**: `Analysis/FactorAttribution.py`

```python
# ABOUTME: Factor-based performance attribution (Grinold-Kahn Ch 17)
# ABOUTME: Decompose returns into factor bets + stock selection

class FactorAttribution:
    """
    Decompose active returns: r_A = Σ_k β_k·f_k + Σ_n w_n·u_n
                                   [factor bets]   [selection]
    """

    def decompose_returns(
        self,
        portfolio_returns: pl.Series,
        factor_exposures: pl.DataFrame,  # β matrix (N×K)
        factor_returns: pl.Series,  # f vector (K×1)
        specific_returns: pl.DataFrame,  # u matrix (N×T)
        weights: pl.Series,
    ) -> dict:
        """Factor + selection decomposition"""
        factor_contrib = (factor_exposures @ factor_returns).sum()
        selection_contrib = (weights * specific_returns).sum()

        return {
            "factor": factor_contrib,
            "selection": selection_contrib,
            "total": portfolio_returns,
        }
```

### Deliverables
- ✅ `Analysis/FactorAttribution.py`
- ✅ Extended `TearSheet` with factor charts

### Success Criteria
- [ ] Factor decomposition sums to total return
- [ ] IC, IR, Sharpe validated against book targets
- [ ] Paper replication: PPFM within 10% of reported metrics
- [ ] 20 tests passing

---

## End-to-End Integration

### Example Backtest

**File**: `examples/run_equity_sector_backtest.py`

```python
# ABOUTME: End-to-end equity sector backtest example
# ABOUTME: Tech vs Finance sector rotation with multi-signal approach

from Query.Equities import EquityQuery, EquityStructure, EquityValue
from MDP.YahooFinance import YahooFinanceMDP
from Adapter import EquityAdapter
from Signals.Equities import ValueSignal, MomentumSignal, QualitySignal
from Signals import SignalCombiner, AlphaGenerator
from Risk.Covariance import PPFMCovariance
from Optimizer import MeanVarianceOptimizer
from Optimizer.constraints import LongOnlyConstraint, SectorNeutralConstraint
from Portfolio import Portfolio
from Analysis import TearSheet

# 1. Query S&P 500 stocks in Tech and Finance sectors
queries = [
    *[EquityQuery(ticker=t, sector="Information Technology") for t in get_sector_tickers("Information Technology")],
    *[EquityQuery(ticker=t, sector="Financials") for t in get_sector_tickers("Financials")],
]

# 2. Fetch data
mdp = YahooFinanceMDP()
data = EquityAdapter().convert(queries, as_of_date, mdp)

# 3. Generate signals
value = ValueSignal().calculate(data)
momentum = MomentumSignal().calculate(data)
quality = QualitySignal().calculate(data)

# 4. Combine signals (IC-weighted)
combined = SignalCombiner(weights=[0.30, 0.50, 0.20]).combine([value, momentum, quality])

# 5. Generate alphas (IC × Vol × Z)
alphas = AlphaGenerator().generate(combined, volatility=data["volatility"], ic=0.06)

# 6. Estimate covariance (PPFM)
cov = PPFMCovariance().estimate(returns_by_sector={"Tech": ..., "Finance": ...})

# 7. Optimize (with constraints)
optimizer = MeanVarianceOptimizer(risk_aversion=1.0)
optimizer.add_constraint(LongOnlyConstraint())
optimizer.add_constraint(SectorNeutralConstraint())
weights = optimizer.optimize(alphas, cov)

# 8. Construct portfolio
portfolio = Portfolio(weights, returns=data["returns"])

# 9. Analyze
tearsheet = TearSheet(portfolio)
print(f"IR: {tearsheet.information_ratio:.2f}")  # Target: 1.0+
print(f"IC: {tearsheet.ic:.3f}")  # Target: 0.06
print(f"Sharpe: {tearsheet.sharpe:.2f}")
```

---

## Validation & Success Metrics

### Phase 1: Data Infrastructure
- [ ] Yahoo Finance API: <5 sec for 100 stocks (cached: <1 sec)
- [ ] Polars DataFrames throughout (NO pandas!)
- [ ] Sector classification: 100% coverage for S&P 500

### Phase 2: Signals
- [ ] Value IC: 0.03-0.04 (historical validation)
- [ ] Momentum IC: 0.04-0.06
- [ ] Quality IC: 0.02-0.03
- [ ] Combined IC: 0.06-0.07

### Phase 3: Risk Models
- [ ] Factor model: 93% parameter reduction vs full covariance
- [ ] PPFM convergence: <10 iterations, <1 min runtime
- [ ] PPFM vs Ledoit-Wolf: 10-15% risk reduction

### Phase 4: Optimization
- [ ] Long-only TC: 0.5-0.6 (measured vs unconstrained)
- [ ] Transaction costs: 75% of value-added with 50% of turnover

### Phase 5: Analysis
- [ ] End-to-end backtest: IR 1.0+ (target)
- [ ] Factor attribution: Explains >90% of active return
- [ ] Paper replication: Within 10% of reported PPFM metrics

---

## Timeline Summary

| Phase | Weeks | Components | Tests |
|-------|-------|------------|-------|
| 1. Query & Data | 1-3 | 6 files | 33 |
| 2. Signals | 4-7 | 4 files | 55 |
| 3. Risk Models | 8-11 | 3 files | 45 |
| 4. Optimization | 12-14 | 5 files | 30 |
| 5. Analysis | 15-17 | 2 files | 20 |
| **Total** | **17 weeks** | **20 files** | **183 tests** |

---

## Dependencies & Risks

### Critical Dependencies
1. **Polars migration** must complete first (blocking all equity work)
2. **Yahoo Finance** rate limits (mitigate with caching)
3. **Fundamental data** availability (P/E, ROE, etc.) from Yahoo Finance

### Risk Mitigation

| Risk | Probability | Impact | Mitigation |
|------|-------------|--------|------------|
| Polars migration breaks existing code | MEDIUM | HIGH | Comprehensive test suite, gradual rollout |
| Yahoo Finance rate limits | MEDIUM | MEDIUM | Aggressive caching, batch API calls |
| IC targets not met | MEDIUM | MEDIUM | Have fallback signals, document when to use |
| PPFM doesn't improve over baselines | LOW | LOW | Keep Ledoit-Wolf fallback, document trade-offs |

---

## Documentation References

All documentation from Grinold-Kahn book study:

1. **Executive Summary**: `docs/books/GRINOLD_KAHN_EQUITY_SUMMARY.md` (800+ lines)
2. **Knowledge Graph**: `docs/design/GRINOLD_KAHN_KNOWLEDGE_GRAPH.md` (concept-to-code mapping)
3. **Part 1 Notes**: `docs/books/grinold_kahn_equity_notes_part1_foundations.md` (728 lines)
4. **Part 2 Notes**: `docs/books/grinold_kahn_equity_notes_part2_valuation.md` (1,477 lines)
5. **Part 3 Notes**: `docs/books/grinold_kahn_equity_notes_part3_forecasting.md` (1,616 lines)
6. **Part 4 Notes**: `docs/books/grinold_kahn_equity_notes_part4_implementation.md` (1,072 lines)
7. **Framework**: `docs/GRINOLD_KAHN_FRAMEWORK.md` (Section 8: Equity Implementation)

**Total**: 4,893 lines of detailed analysis + 800-line summary + knowledge graph

---

**End of Equity Sector Implementation Plan**
