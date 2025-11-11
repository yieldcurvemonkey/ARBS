# Agent Orchestration Plan: Equity Sector Portfolio Implementation

**Date**: 2025-11-11
**Universe**: Russell 3000 + Sector ETFs
**Strategy**: Long/Short (Market-Neutral)
**Timeline**: 17 weeks
**Branch**: `claude/equity-sector-portfolio-planning-011CV2pP4NRAwS4k6wTNsm1u`

---

## Executive Summary

This plan orchestrates **20 AI agents** to implement equity sector portfolios in ARBS. Each agent:
- **Starts from zero** (no assumed context beyond what's specified)
- Works **independently** on orthogonal tasks
- Has **clear success criteria**
- **Commits and pushes** their work when complete
- Can execute in **parallel waves** where dependencies allow

**Key decisions**:
- **Universe**: Russell 3000 (3,000 stocks) + 11 sector ETFs
- **Strategy**: Long/short market-neutral (no long-only constraint)
- **Data**: Yahoo Finance (free, sufficient for MVP)
- **Framework**: Polars-native (no pandas)

---

## Wave-Based Execution Strategy

### Wave 1: Foundational Research & Design (Week 1)
**4 agents in parallel** - Pure research, no code

| Agent ID | Task | Estimated Time |
|----------|------|----------------|
| AGENT-01 | Russell 3000 Universe Research | 2 days |
| AGENT-02 | Sector ETF Research & Mapping | 2 days |
| AGENT-03 | Yahoo Finance API Design | 2 days |
| AGENT-04 | Long/Short Strategy Design | 2 days |

### Wave 2: Data Infrastructure (Weeks 2-3)
**5 agents in parallel** - Query layer and data providers

| Agent ID | Task | Estimated Time |
|----------|------|----------------|
| AGENT-05 | EquityQuery Implementation | 3 days |
| AGENT-06 | ETFQuery Implementation | 3 days |
| AGENT-07 | Yahoo Finance MDP Implementation | 5 days |
| AGENT-08 | Sector Classification System | 3 days |
| AGENT-09 | EquityAdapter Implementation | 4 days |

### Wave 3: Signal Generation (Weeks 4-7)
**5 agents in parallel** - Cross-sectional equity signals

| Agent ID | Task | Estimated Time |
|----------|------|----------------|
| AGENT-10 | ValueSignal Implementation | 5 days |
| AGENT-11 | MomentumSignal Implementation | 5 days |
| AGENT-12 | QualitySignal Implementation | 5 days |
| AGENT-13 | BaseSignal Cross-Sectional Extension | 3 days |
| AGENT-14 | Signal IC Validation Framework | 4 days |

### Wave 4: Risk Models (Weeks 8-11)
**3 agents in parallel** - Multi-factor covariance

| Agent ID | Task | Estimated Time |
|----------|------|----------------|
| AGENT-15 | EquityFactorModel Implementation | 7 days |
| AGENT-16 | FactorCovariance Implementation | 7 days |
| AGENT-17 | PPFMCovariance Implementation | 10 days |

### Wave 5: Long/Short Optimization (Weeks 12-14)
**2 agents in parallel** - Market-neutral optimization

| Agent ID | Task | Estimated Time |
|----------|------|----------------|
| AGENT-18 | Long/Short Optimizer with Constraints | 10 days |
| AGENT-19 | Transaction Cost Integration | 7 days |

### Wave 6: Analysis & Integration (Weeks 15-17)
**1 agent** - End-to-end integration and validation

| Agent ID | Task | Estimated Time |
|----------|------|----------------|
| AGENT-20 | End-to-End Integration & Validation | 15 days |

---

## Detailed Agent Specifications

### WAVE 1: FOUNDATIONAL RESEARCH

---

#### AGENT-01: Russell 3000 Universe Research

**Objective**: Research Russell 3000 index, document constituent data availability, and create universe definition.

**Starting Context** (agent reads these files):
1. `docs/books/GRINOLD_KAHN_EQUITY_SUMMARY.md` (pages discussing universe selection)
2. `docs/design/EQUITY_SECTOR_IMPLEMENTATION_PLAN.md` (Section: Universe)
3. `README.md` (understand ARBS architecture)

**External Research Required**:
- Russell 3000 index methodology (FTSE Russell website)
- Constituent list availability (free sources: Wikipedia, ETF holdings)
- GICS sector classification for Russell 3000 stocks
- Market cap distribution (large/mid/small cap breakdown)
- Data availability via Yahoo Finance (test 50 random tickers)

**Skills Required**:
- Research & analysis
- Data source evaluation
- Documentation writing (markdown)

**Deliverables**:
```
docs/research/RUSSELL_3000_UNIVERSE.md

Contents:
- Index methodology summary
- Constituent list source (free, reliable, updateable)
- GICS sector breakdown (count by sector)
- Market cap distribution
- Yahoo Finance coverage validation (% available)
- Recommended universe size for MVP (full 3000 or top 1000?)
- Rebalancing frequency (Russell rebalances quarterly)
```

**Success Criteria**:
- [ ] Document exists with all sections
- [ ] Constituent list source identified (free, reliable)
- [ ] GICS sector breakdown documented (11 sectors)
- [ ] Yahoo Finance coverage >95% for Russell 3000
- [ ] MVP recommendation (pragmatic starting point)
- [ ] Committed and pushed to branch

**Example Output**:
```markdown
# Russell 3000 Universe Research

## Index Methodology
- Russell 3000 = largest 3,000 US stocks by market cap (~98% of US equity market)
- Reconstituted annually (June), ranked by market cap as of May
- Float-adjusted market cap weighting

## Constituent List Source
**Recommended**: iShares IWV (Russell 3000 ETF) holdings CSV (free, daily updates)
- URL: https://www.ishares.com/us/products/239714/ishares-russell-3000-etf
- Format: CSV with ticker, name, weight, sector
- Update frequency: Daily
- Historical archives: Yes (monthly)

## GICS Sector Breakdown (as of 2025-01-01)
| Sector | Count | % |
|--------|-------|---|
| Information Technology | 450 | 15% |
| Health Care | 420 | 14% |
| Financials | 510 | 17% |
...

## Yahoo Finance Coverage
Tested 300 random Russell 3000 tickers:
- Available: 294 (98%)
- Missing: 6 (recent IPOs, delistings)
- Recommendation: Use 98% that are available, handle missing gracefully

## MVP Recommendation
**Start with Russell 1000** (top 1000 stocks by market cap)
- Rationale: 92% of Russell 3000 market cap, easier to manage
- Can expand to full 3000 in Phase 2
```

---

#### AGENT-02: Sector ETF Research & Mapping

**Objective**: Research sector ETFs (SPDR Select Sector or iShares), document characteristics, and create mapping to GICS sectors.

**Starting Context**:
1. `docs/books/GRINOLD_KAHN_EQUITY_SUMMARY.md` (factor models)
2. `docs/design/EQUITY_SECTOR_IMPLEMENTATION_PLAN.md` (multi-factor risk model section)
3. `docs/research/RUSSELL_3000_UNIVERSE.md` (AGENT-01 output, read after they finish)

**External Research Required**:
- SPDR Select Sector ETFs (XLK, XLF, XLE, etc.) - 11 ETFs
- iShares Sector ETFs alternative
- Liquidity (average daily volume)
- Expense ratios
- Tracking error vs sector indices
- How to integrate ETFs with individual stocks (separate or combined?)

**Skills Required**:
- ETF research
- Financial product analysis
- Documentation writing

**Deliverables**:
```
docs/research/SECTOR_ETF_MAPPING.md

Contents:
- 11 Sector ETFs (tickers, names, AUM, expense ratio, liquidity)
- GICS sector mapping (which ETF maps to which sector)
- Use cases: hedging, sector bets, liquidity
- Integration strategy: Handle ETFs separately or as mega-stocks?
- Recommendation for ARBS
```

**Success Criteria**:
- [ ] 11 sector ETFs documented (SPDR or iShares)
- [ ] GICS mapping complete (1:1 mapping)
- [ ] Liquidity analysis (all >$100M avg daily volume)
- [ ] Integration strategy proposed
- [ ] Committed and pushed

**Example Output**:
```markdown
# Sector ETF Research & Mapping

## SPDR Select Sector ETFs (Recommended)

| Ticker | Name | GICS Sector | AUM | Expense Ratio | Avg Daily Volume |
|--------|------|-------------|-----|---------------|------------------|
| XLK | Technology Select Sector | Information Technology | $60B | 0.10% | $5B |
| XLF | Financial Select Sector | Financials | $45B | 0.10% | $3B |
| XLE | Energy Select Sector | Energy | $35B | 0.10% | $2B |
...

## Integration Strategy for ARBS

**Recommendation**: Treat ETFs as "synthetic sector portfolios"
- Use ETFs for **sector hedging** (go long individual stocks, short sector ETF)
- Market-neutral: Long undervalued stocks in sector, short sector ETF
- Advantage: Sector ETFs have high liquidity, low transaction costs

**Implementation**:
- Query layer: Separate `ETFQuery` class (similar to `EquityQuery`)
- Adapter: Convert ETF to returns like individual stock
- Signals: ETFs don't get value/quality signals, only momentum
- Risk model: ETFs have factor exposures = pure sector (β_sector = 1.0)

## Use Case Examples

**Long/Short Sector-Neutral**:
- Long: AAPL, MSFT, GOOGL (high quality tech stocks)
- Short: XLK (hedge out tech sector exposure)
- Result: Bet on stock selection within tech, hedged against sector moves
```

---

#### AGENT-03: Yahoo Finance API Design

**Objective**: Design Yahoo Finance data provider interface, document API limitations, caching strategy, and rate limiting.

**Starting Context**:
1. `MDP/IRSwaps/IRSwapsMDP.py` (existing MDP pattern)
2. `MDP/MarketDataProvider.py` (base class)
3. `docs/design/EQUITY_SECTOR_IMPLEMENTATION_PLAN.md` (Phase 1: Yahoo Finance MDP)

**External Research Required**:
- `yfinance` library documentation (Python)
- API rate limits (requests per minute)
- Available fields (price, dividend, splits, fundamentals)
- Data quality issues (missing data, stale data)
- Alternative libraries (yahoo-fin, yahooquery)
- Caching backends (ZODB vs parquet vs SQLite)

**Skills Required**:
- API design
- Data engineering
- Performance optimization
- Documentation

**Deliverables**:
```
docs/design/YAHOO_FINANCE_MDP_DESIGN.md

Contents:
- API interface specification (methods, parameters, returns)
- Rate limiting strategy (batch requests, exponential backoff)
- Caching strategy (what to cache, how long, storage backend)
- Error handling (missing tickers, API failures, stale data)
- Data quality checks (outlier detection, gap filling)
- Polars-native return types
- Performance targets (<5 sec for 100 stocks, <1 sec cached)
```

**Success Criteria**:
- [ ] Complete API interface designed
- [ ] Rate limiting strategy specified
- [ ] Caching strategy defined (ZODB recommended)
- [ ] Error handling documented
- [ ] Polars-native (NO pandas in returns)
- [ ] Committed and pushed

**Example Output**:
```markdown
# Yahoo Finance MDP Design

## API Interface

```python
class YahooFinanceMDP(MarketDataProvider):
    def get_prices(
        tickers: List[str],
        start_date: date,
        end_date: date,
        adjusted: bool = True,  # Adjust for splits/dividends
    ) -> pl.DataFrame:
        """
        Returns Polars DataFrame:
            - ticker: str
            - date: date
            - open, high, low, close, volume: float
        """

    def get_fundamentals(
        tickers: List[str],
        fields: List[str] = ["pe_ratio", "dividend_yield", "roe", "debt_to_equity"],
    ) -> pl.DataFrame:
        """
        Returns Polars DataFrame:
            - ticker: str
            - <field>: float (one column per field)
        """

    def get_sector_info(tickers: List[str]) -> pl.DataFrame:
        """
        Returns Polars DataFrame:
            - ticker: str
            - sector: str (GICS Level 1)
            - industry: str (GICS Level 2)
        """
```

## Rate Limiting Strategy

**yfinance Limits**: ~2000 requests/hour, ~48k requests/day
**Mitigation**:
1. Batch requests (max 100 tickers per call)
2. Exponential backoff on 429 (Too Many Requests)
3. Cache aggressively (30-day TTL for fundamentals, 1-day for prices)

## Caching Strategy

**Backend**: ZODB (already used in ARBS)
**Structure**:
```
cache/
  yahoo_finance/
    prices/
      AAPL_2024-01-01_2024-12-31.pkl
    fundamentals/
      AAPL_2024-12-31.pkl
```

**TTL (Time To Live)**:
- Prices: 1 day (refresh daily)
- Fundamentals: 30 days (slow-moving)
- Sector info: 90 days (very stable)

**Cache key**: `{ticker}_{start_date}_{end_date}_{data_type}`

## Error Handling

| Error | Handling |
|-------|----------|
| Ticker not found | Log warning, return None for that ticker |
| API rate limit (429) | Exponential backoff, retry up to 4 times |
| Network timeout | Retry up to 2 times, then fail gracefully |
| Stale data (>7 days old) | Re-fetch if detected |
| Missing fundamental data | Use sector median as fallback |
```

---

#### AGENT-04: Long/Short Strategy Design

**Objective**: Design long/short market-neutral strategy, document optimization approach, and specify constraints.

**Starting Context**:
1. `docs/books/GRINOLD_KAHN_EQUITY_SUMMARY.md` (Chapter 15: Long/Short)
2. `docs/books/grinold_kahn_equity_notes_part4_implementation.md` (lines 1-400)
3. `docs/design/EQUITY_SECTOR_IMPLEMENTATION_PLAN.md` (Phase 4: Optimization)
4. `Optimizer/MeanVarianceOptimizer.py` (existing optimizer)

**Skills Required**:
- Portfolio optimization theory
- Constraint design
- Long/short strategy knowledge
- Documentation

**Deliverables**:
```
docs/design/LONG_SHORT_STRATEGY_DESIGN.md

Contents:
- Market-neutral definition (zero net exposure, zero sector exposure)
- Optimization objective (maximize alpha, minimize risk, penalize transaction costs)
- Constraints (market-neutral, sector-neutral, position limits, leverage limits)
- Alpha preprocessing (sector-neutralize signals)
- Expected impact on IR vs long-only
- Integration with existing MeanVarianceOptimizer
```

**Success Criteria**:
- [ ] Market-neutral strategy clearly defined
- [ ] Constraints specified mathematically
- [ ] Alpha preprocessing documented
- [ ] Expected IR impact analyzed (no 50% cut like long-only!)
- [ ] Integration plan with existing optimizer
- [ ] Committed and pushed

**Example Output**:
```markdown
# Long/Short Market-Neutral Strategy Design

## Definition

**Market-neutral**: Zero net market exposure
```
Σ_i h_i = 0  (dollar-neutral)
Σ_i h_i · β_i^market = 0  (beta-neutral)
```

**Sector-neutral**: Zero net exposure to each sector
```
Σ_{i ∈ sector_s} h_i = 0  for each sector s
```

## Optimization Objective

```
max: α^T h - λ h^T Σ h - κ · TC(h, h_old)
```

Where:
- α = signal alphas (sector-neutralized)
- Σ = covariance matrix
- λ = risk aversion parameter (default: 1.0)
- κ = transaction cost penalty (default: 0.5)
- TC = transaction cost function

## Constraints

### 1. Market-Neutral
```python
# Dollar-neutral
problem.add_constraint(weights.sum() == 0)

# Beta-neutral (optional, stronger)
problem.add_constraint((weights * market_betas).sum() == 0)
```

### 2. Sector-Neutral
```python
# Zero net exposure per sector
for sector in sectors:
    mask = (sector_exposures == sector)
    problem.add_constraint(weights[mask].sum() == 0)
```

### 3. Position Limits
```python
# Individual position limit (e.g., ±5% of portfolio)
problem.add_constraint(abs(weights) <= 0.05)
```

### 4. Gross Leverage Limit
```python
# Gross exposure (sum of absolute positions)
problem.add_constraint(abs(weights).sum() <= 2.0)  # 2× gross (100% long, 100% short)
```

## Alpha Preprocessing (CRITICAL!)

**Sector-neutralize signals BEFORE optimization**:

```python
def sector_neutralize(alphas: pl.Series, sectors: pl.Series) -> pl.Series:
    """Remove sector means to ensure zero net exposure per sector"""
    df = pl.DataFrame({"alpha": alphas, "sector": sectors})
    sector_means = df.group_by("sector").agg(pl.col("alpha").mean())

    # Subtract sector mean from each alpha
    return df.join(sector_means, on="sector").select(
        pl.col("alpha") - pl.col("alpha_mean")
    )
```

**Why?** If signals have sector biases (e.g., positive mean for tech), optimizer will tilt long tech. Sector-neutralizing ensures pure stock selection.

## Expected IR Impact

**From Grinold-Kahn Chapter 15**:
- Long-only: Transfer coefficient TC ≈ 0.5-0.6 (IR cut by ~50%)
- **Long/short unconstrained: TC ≈ 0.9-1.0** (minimal IR loss!)
- Long/short sector-neutral: TC ≈ 0.8-0.9 (still much better than long-only)

**Expected IR**:
```
IC_combined = 0.06
BR = 3000 (Russell 3000 universe)
TC = 0.85 (sector-neutral long/short)

IR = 0.06 × √3000 × 0.85 = 2.78 (theoretical)
IR_realized ≈ 1.5-2.0 (accounting for estimation error, transaction costs)
```

**Target**: IR > 1.0 (much higher than long-only 0.5 benchmark!)

## Integration with Existing Optimizer

**Extend `MeanVarianceOptimizer`**:
```python
# Optimizer/MeanVarianceOptimizer.py (modify)

def optimize(
    self,
    alphas: pl.Series,
    covariance: pl.DataFrame,
    constraints: List[Constraint],  # NEW: modular constraints
    old_weights: pl.Series = None,  # For turnover penalty
) -> pl.Series:
    """
    Mean-variance optimization with constraints

    NEW: Accepts list of Constraint objects
    - MarketNeutralConstraint()
    - SectorNeutralConstraint(sector_exposures)
    - PositionLimitConstraint(max_weight=0.05)
    - GrossLeverageConstraint(max_gross=2.0)
    """
    # Build CVXPY problem
    w = cp.Variable(len(alphas))

    # Objective
    objective = alphas @ w - self.risk_aversion * cp.quad_form(w, covariance)
    if old_weights is not None:
        objective -= self.tc_penalty * cp.norm1(w - old_weights)

    # Apply constraints
    constraint_list = []
    for constraint in constraints:
        constraint_list.extend(constraint.apply(w))

    # Solve
    problem = cp.Problem(cp.Maximize(objective), constraint_list)
    problem.solve()

    return pl.Series(w.value)
```
```

---

### WAVE 2: DATA INFRASTRUCTURE

---

#### AGENT-05: EquityQuery Implementation

**Objective**: Implement `EquityQuery` class for individual stock queries.

**Starting Context**:
1. `Query/Futures/FuturesQuery.py` (pattern to mirror)
2. `Query/Base/BaseQuery.py` (base class to inherit)
3. `docs/design/EQUITY_SECTOR_IMPLEMENTATION_PLAN.md` (Phase 1, Section 1.1)
4. `docs/research/RUSSELL_3000_UNIVERSE.md` (AGENT-01 output)
5. `docs/research/SECTOR_ETF_MAPPING.md` (AGENT-02 output)

**Skills Required**:
- Python dataclasses
- Object-oriented design
- Test-driven development (TDD)
- Polars DataFrames

**Deliverables**:
```
Query/Equities/__init__.py
Query/Equities/EquityQuery.py
Query/Equities/EquityStructure.py
Query/Equities/EquityValue.py

tests/unit/query/test_equity_query.py (20 tests)
```

**Implementation Guidance**:
```python
# Query/Equities/EquityQuery.py

# ABOUTME: Query structure for individual equity instruments
# ABOUTME: Supports Russell 3000 stocks with GICS sector classification

from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Dict
from Query.Base.BaseQuery import BaseQuery
from Query.Equities.EquityStructure import EquityStructure
from Query.Equities.EquityValue import EquityValue

@dataclass
class EquityQuery(BaseQuery):
    """
    Query for individual stock data

    Example:
        query = EquityQuery(
            ticker="AAPL",
            sector="Information Technology",
            structure=EquityStructure.SINGLE,
            value=EquityValue.RETURN,
            lookback_days=252,  # 1 year
        )
    """
    ticker: str
    sector: str  # GICS Level 1 (11 sectors)
    structure: EquityStructure
    value: EquityValue
    lookback_days: int = 252  # Default: 1 year
    weight: float = 1.0
    metadata: Dict = field(default_factory=dict)

    def build_mdp_request(self, as_of_date: date) -> dict:
        """
        Convert to market data provider request

        Returns:
            dict with keys: ticker, start_date, end_date, fields
        """
        start_date = as_of_date - timedelta(days=self.lookback_days)

        fields = ["price", "volume"]
        if self.value in [EquityValue.DIVIDEND_YIELD, EquityValue.EARNINGS_YIELD]:
            fields.extend(["dividend", "earnings"])

        return {
            "ticker": self.ticker,
            "start_date": start_date,
            "end_date": as_of_date,
            "fields": fields,
        }

    def validate(self) -> bool:
        """Validate query parameters"""
        if not self.ticker or len(self.ticker) == 0:
            raise ValueError("Ticker cannot be empty")
        if self.lookback_days < 1:
            raise ValueError("Lookback days must be positive")
        return True
```

**Testing Strategy**:
```python
# tests/unit/query/test_equity_query.py

import pytest
from datetime import date
from Query.Equities import EquityQuery, EquityStructure, EquityValue

def test_equity_query_creation():
    """Test basic query creation"""
    query = EquityQuery(
        ticker="AAPL",
        sector="Information Technology",
        structure=EquityStructure.SINGLE,
        value=EquityValue.RETURN,
    )
    assert query.ticker == "AAPL"
    assert query.sector == "Information Technology"
    assert query.lookback_days == 252  # Default

def test_build_mdp_request():
    """Test MDP request building"""
    query = EquityQuery(
        ticker="MSFT",
        sector="Information Technology",
        structure=EquityStructure.SINGLE,
        value=EquityValue.RETURN,
        lookback_days=100,
    )

    as_of = date(2025, 1, 1)
    request = query.build_mdp_request(as_of)

    assert request["ticker"] == "MSFT"
    assert request["start_date"] == date(2024, 9, 23)  # 100 days before
    assert request["end_date"] == as_of
    assert "price" in request["fields"]

def test_invalid_ticker():
    """Test validation for empty ticker"""
    with pytest.raises(ValueError, match="Ticker cannot be empty"):
        query = EquityQuery(
            ticker="",
            sector="Technology",
            structure=EquityStructure.SINGLE,
            value=EquityValue.RETURN,
        )
        query.validate()

# ... 17 more tests covering all edge cases
```

**Success Criteria**:
- [ ] `EquityQuery`, `EquityStructure`, `EquityValue` implemented
- [ ] Inherits from `BaseQuery` correctly
- [ ] `build_mdp_request()` returns correct format
- [ ] Validation catches invalid inputs
- [ ] 20 tests passing
- [ ] Polars-ready (no pandas imports)
- [ ] Committed and pushed

---

#### AGENT-06: ETFQuery Implementation

**Objective**: Implement `ETFQuery` class for sector ETF queries.

**Starting Context**:
1. `Query/Equities/EquityQuery.py` (AGENT-05 output, similar pattern)
2. `Query/Base/BaseQuery.py` (base class)
3. `docs/research/SECTOR_ETF_MAPPING.md` (AGENT-02 output)
4. `docs/design/EQUITY_SECTOR_IMPLEMENTATION_PLAN.md` (Phase 1)

**Skills Required**:
- Python dataclasses
- Object-oriented design
- Test-driven development
- ETF-specific handling (no fundamentals)

**Deliverables**:
```
Query/Equities/ETFQuery.py

tests/unit/query/test_etf_query.py (15 tests)
```

**Implementation Guidance**:
```python
# Query/Equities/ETFQuery.py

# ABOUTME: Query structure for sector ETF instruments
# ABOUTME: Simplified vs EquityQuery (no fundamentals, pure sector exposure)

from dataclasses import dataclass, field
from datetime import date, timedelta
from Query.Base.BaseQuery import BaseQuery
from Query.Equities.EquityValue import EquityValue

@dataclass
class ETFQuery(BaseQuery):
    """
    Query for sector ETF data

    Example:
        query = ETFQuery(
            ticker="XLK",  # Technology Select Sector SPDR
            sector="Information Technology",
            value=EquityValue.RETURN,
            lookback_days=252,
        )
    """
    ticker: str  # ETF ticker (e.g., XLK, XLF, XLE)
    sector: str  # Corresponding GICS sector
    value: EquityValue  # Only PRICE, RETURN, LOG_RETURN (no fundamentals!)
    lookback_days: int = 252
    weight: float = 1.0
    metadata: Dict = field(default_factory=dict)

    def build_mdp_request(self, as_of_date: date) -> dict:
        """Convert to MDP request (simpler than EquityQuery)"""
        start_date = as_of_date - timedelta(days=self.lookback_days)

        return {
            "ticker": self.ticker,
            "start_date": start_date,
            "end_date": as_of_date,
            "fields": ["price", "volume"],  # ETFs don't have fundamentals
        }

    def validate(self) -> bool:
        """Validate ETF query"""
        if self.value not in [EquityValue.PRICE, EquityValue.RETURN, EquityValue.LOG_RETURN]:
            raise ValueError(f"ETFs only support price/return values, got {self.value}")
        return True
```

**Testing Strategy**:
```python
# tests/unit/query/test_etf_query.py

def test_etf_query_creation():
    """Test ETF query for sector ETF"""
    query = ETFQuery(
        ticker="XLK",
        sector="Information Technology",
        value=EquityValue.RETURN,
    )
    assert query.ticker == "XLK"
    assert query.sector == "Information Technology"

def test_etf_no_fundamentals():
    """ETFs should not support fundamental values"""
    with pytest.raises(ValueError, match="ETFs only support price/return"):
        query = ETFQuery(
            ticker="XLK",
            sector="Information Technology",
            value=EquityValue.EARNINGS_YIELD,  # Invalid for ETF!
        )
        query.validate()

# ... 13 more tests
```

**Success Criteria**:
- [ ] `ETFQuery` implemented (simpler than `EquityQuery`)
- [ ] Validation prevents fundamental value queries
- [ ] 15 tests passing
- [ ] Committed and pushed

---

#### AGENT-07: Yahoo Finance MDP Implementation

**Objective**: Implement Yahoo Finance market data provider with caching, rate limiting, and error handling.

**Starting Context**:
1. `MDP/IRSwaps/IRSwapsMDP.py` (existing MDP pattern)
2. `MDP/MarketDataProvider.py` (base class)
3. `docs/design/YAHOO_FINANCE_MDP_DESIGN.md` (AGENT-03 output)
4. `Query/Equities/EquityQuery.py` (AGENT-05 output)
5. `Query/Equities/ETFQuery.py` (AGENT-06 output)

**Skills Required**:
- API integration (yfinance library)
- Caching (ZODB)
- Error handling & retry logic
- Polars DataFrames
- Performance optimization

**Deliverables**:
```
MDP/YahooFinance/__init__.py
MDP/YahooFinance/YahooFinanceMDP.py
MDP/YahooFinance/cache.py

tests/unit/mdp/test_yahoo_finance_mdp.py (25 tests)
tests/integration/test_yahoo_finance_live.py (10 tests)
```

**Implementation Guidance**:
```python
# MDP/YahooFinance/YahooFinanceMDP.py

# ABOUTME: Yahoo Finance market data provider for equities and ETFs
# ABOUTME: Handles rate limiting, caching, error handling for Russell 3000 + sector ETFs

import yfinance as yf
import polars as pl
from datetime import date, timedelta
from typing import List, Optional
from MDP.MarketDataProvider import MarketDataProvider
from MDP.YahooFinance.cache import ZODBCache

class YahooFinanceMDP(MarketDataProvider):
    """
    Yahoo Finance data provider

    Features:
    - Batch requests (100 tickers max per call)
    - ZODB caching (1-day TTL for prices, 30-day for fundamentals)
    - Exponential backoff on rate limits
    - Polars-native returns (NO pandas!)
    """

    def __init__(self, cache_backend: str = "zodb", cache_ttl_days: int = 1):
        self.cache = ZODBCache(ttl_days=cache_ttl_days)
        self.batch_size = 100  # Yahoo Finance limit
        self.max_retries = 4

    def get_prices(
        self,
        tickers: List[str],
        start_date: date,
        end_date: date,
        adjusted: bool = True,
    ) -> pl.DataFrame:
        """
        Fetch price data for multiple tickers

        Returns Polars DataFrame:
            - ticker: str
            - date: date
            - open, high, low, close, volume: float
        """
        # Check cache first
        cache_key = self._cache_key(tickers, start_date, end_date, "prices")
        if cached := self.cache.get(cache_key):
            return cached

        # Batch requests
        all_data = []
        for batch in self._batch_tickers(tickers, self.batch_size):
            batch_data = self._fetch_prices_batch(batch, start_date, end_date, adjusted)
            all_data.append(batch_data)

        # Combine and convert to Polars
        result = pl.concat(all_data)

        # Cache
        self.cache.set(cache_key, result)

        return result

    def _fetch_prices_batch(
        self,
        tickers: List[str],
        start_date: date,
        end_date: date,
        adjusted: bool,
    ) -> pl.DataFrame:
        """Fetch single batch with retry logic"""
        for attempt in range(self.max_retries):
            try:
                # yfinance call
                data = yf.download(
                    tickers=tickers,
                    start=start_date,
                    end=end_date,
                    progress=False,
                    threads=True,
                    auto_adjust=adjusted,
                )

                # Convert pandas → Polars
                return self._pandas_to_polars(data, tickers)

            except Exception as e:
                if "429" in str(e):  # Rate limit
                    wait_time = 2 ** attempt  # Exponential backoff
                    time.sleep(wait_time)
                    continue
                else:
                    raise

        raise RuntimeError(f"Failed to fetch prices after {self.max_retries} attempts")

    def _pandas_to_polars(self, df_pandas, tickers: List[str]) -> pl.DataFrame:
        """Convert yfinance pandas DataFrame to Polars (CRITICAL!)"""
        # yfinance returns multi-index DataFrame
        # Convert to long format with ticker column

        df_reset = df_pandas.reset_index()
        df_long = df_reset.melt(id_vars=["Date"], var_name="ticker", value_name="value")

        # Convert to Polars
        df_polars = pl.from_pandas(df_long)

        # Pivot to get OHLCV columns
        df_wide = df_polars.pivot(
            values="value",
            index=["Date", "ticker"],
            columns="variable",
        )

        return df_wide.rename({"Date": "date"})

    def get_fundamentals(
        self,
        tickers: List[str],
        fields: List[str] = ["pe_ratio", "dividend_yield", "roe", "debt_to_equity"],
    ) -> pl.DataFrame:
        """
        Fetch fundamental data (slower, cache longer TTL)

        Returns Polars DataFrame:
            - ticker: str
            - pe_ratio, dividend_yield, roe, debt_to_equity: float
        """
        # Cache check (30-day TTL for fundamentals)
        cache_key = self._cache_key(tickers, None, None, "fundamentals")
        if cached := self.cache.get(cache_key, ttl_days=30):
            return cached

        # Fetch one-by-one (yfinance .info is per-ticker)
        rows = []
        for ticker in tickers:
            try:
                info = yf.Ticker(ticker).info
                row = {"ticker": ticker}

                # Map yfinance fields to our fields
                field_mapping = {
                    "pe_ratio": "trailingPE",
                    "dividend_yield": "dividendYield",
                    "roe": "returnOnEquity",
                    "debt_to_equity": "debtToEquity",
                }

                for our_field, yf_field in field_mapping.items():
                    row[our_field] = info.get(yf_field, None)

                rows.append(row)

            except Exception as e:
                # Log and continue (some tickers may not have fundamentals)
                print(f"Warning: Could not fetch fundamentals for {ticker}: {e}")
                continue

        result = pl.DataFrame(rows)
        self.cache.set(cache_key, result, ttl_days=30)

        return result

    def get_sector_info(self, tickers: List[str]) -> pl.DataFrame:
        """
        Fetch GICS sector classification

        Returns Polars DataFrame:
            - ticker: str
            - sector: str (GICS Level 1)
            - industry: str (GICS Level 2)
        """
        # Cache check (90-day TTL, sectors change rarely)
        cache_key = self._cache_key(tickers, None, None, "sectors")
        if cached := self.cache.get(cache_key, ttl_days=90):
            return cached

        rows = []
        for ticker in tickers:
            try:
                info = yf.Ticker(ticker).info
                rows.append({
                    "ticker": ticker,
                    "sector": info.get("sector", "Unknown"),
                    "industry": info.get("industry", "Unknown"),
                })
            except:
                rows.append({
                    "ticker": ticker,
                    "sector": "Unknown",
                    "industry": "Unknown",
                })

        result = pl.DataFrame(rows)
        self.cache.set(cache_key, result, ttl_days=90)

        return result

    def _batch_tickers(self, tickers: List[str], batch_size: int):
        """Split tickers into batches"""
        for i in range(0, len(tickers), batch_size):
            yield tickers[i:i+batch_size]

    def _cache_key(self, tickers, start_date, end_date, data_type):
        """Generate cache key"""
        ticker_str = "_".join(sorted(tickers))
        if start_date and end_date:
            return f"{data_type}_{ticker_str}_{start_date}_{end_date}"
        else:
            return f"{data_type}_{ticker_str}"
```

**Testing Strategy**:
```python
# tests/unit/mdp/test_yahoo_finance_mdp.py (mock yfinance)

def test_get_prices_single_ticker(mocker):
    """Test price fetching for single ticker"""
    # Mock yfinance response
    mock_data = pd.DataFrame(...)
    mocker.patch("yfinance.download", return_value=mock_data)

    mdp = YahooFinanceMDP()
    result = mdp.get_prices(["AAPL"], date(2024, 1, 1), date(2024, 12, 31))

    assert isinstance(result, pl.DataFrame)  # MUST be Polars!
    assert "ticker" in result.columns
    assert result["ticker"][0] == "AAPL"

# tests/integration/test_yahoo_finance_live.py (real API calls)

@pytest.mark.integration
def test_real_yahoo_finance_call():
    """Test actual Yahoo Finance API (may be slow, run separately)"""
    mdp = YahooFinanceMDP()
    result = mdp.get_prices(["AAPL", "MSFT"], date(2024, 11, 1), date(2024, 11, 10))

    assert len(result) > 0
    assert result["ticker"].unique().to_list() == ["AAPL", "MSFT"]
```

**Success Criteria**:
- [ ] `YahooFinanceMDP` implemented with all methods
- [ ] ZODB caching working (test cache hits)
- [ ] Rate limiting with exponential backoff
- [ ] Polars-native returns (NO pandas in output!)
- [ ] 35 tests passing (25 unit + 10 integration)
- [ ] Performance: <5 sec for 100 tickers, <1 sec cached
- [ ] Committed and pushed

---

#### AGENT-08: Sector Classification System

**Objective**: Implement GICS sector classification mapping and Russell 3000 constituent list loader.

**Starting Context**:
1. `docs/research/RUSSELL_3000_UNIVERSE.md` (AGENT-01 output)
2. `docs/research/SECTOR_ETF_MAPPING.md` (AGENT-02 output)
3. `MDP/YahooFinance/YahooFinanceMDP.py` (AGENT-07 output, uses sector info)

**Skills Required**:
- Data loading (CSV/JSON)
- Sector classification (GICS)
- Data validation

**Deliverables**:
```
MDP/YahooFinance/sector_mapping.py
MDP/YahooFinance/russell_3000_constituents.csv (downloaded)

tests/unit/mdp/test_sector_mapping.py (15 tests)
```

**Implementation Guidance**:
```python
# MDP/YahooFinance/sector_mapping.py

# ABOUTME: GICS sector classification and Russell 3000 constituent mapping
# ABOUTME: Provides ticker-to-sector mapping for 3000 stocks + 11 ETFs

import polars as pl
from pathlib import Path
from typing import List, Dict

# GICS Level 1 Sectors (11 sectors)
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

# Sector ETF mapping (SPDR Select Sector)
SECTOR_ETFS = {
    "XLE": "Energy",
    "XLB": "Materials",
    "XLI": "Industrials",
    "XLY": "Consumer Discretionary",
    "XLP": "Consumer Staples",
    "XLV": "Health Care",
    "XLF": "Financials",
    "XLK": "Information Technology",
    "XLC": "Communication Services",
    "XLU": "Utilities",
    "XLRE": "Real Estate",
}

def load_russell_3000_constituents() -> pl.DataFrame:
    """
    Load Russell 3000 constituent list

    Returns Polars DataFrame:
        - ticker: str
        - name: str
        - weight: float (index weight)
        - sector: str (GICS Level 1)
    """
    # Load from iShares IWV (Russell 3000 ETF) holdings CSV
    # Download URL: https://www.ishares.com/us/products/239714/ishares-russell-3000-etf

    csv_path = Path(__file__).parent / "russell_3000_constituents.csv"

    if not csv_path.exists():
        raise FileNotFoundError(
            f"Russell 3000 constituents file not found: {csv_path}\n"
            "Download from: https://www.ishares.com/us/products/239714/ishares-russell-3000-etf"
        )

    # Load CSV (iShares format)
    df = pl.read_csv(csv_path, skip_rows=10)  # iShares CSVs have header rows

    # Rename columns
    df = df.rename({
        "Ticker": "ticker",
        "Name": "name",
        "Weight (%)": "weight",
        "Sector": "sector",
    })

    # Clean
    df = df.select([
        pl.col("ticker"),
        pl.col("name"),
        pl.col("weight").cast(pl.Float64) / 100,  # Convert % to decimal
        pl.col("sector"),
    ])

    return df

def get_sector_tickers(sector_name: str) -> List[str]:
    """Get all tickers in a GICS sector"""
    df = load_russell_3000_constituents()
    return df.filter(pl.col("sector") == sector_name)["ticker"].to_list()

def get_sector_etf(sector_name: str) -> str:
    """Get ETF ticker for a sector"""
    # Reverse lookup
    for etf, sector in SECTOR_ETFS.items():
        if sector == sector_name:
            return etf
    raise ValueError(f"No ETF found for sector: {sector_name}")

def validate_universe_coverage(tickers: List[str], mdp) -> float:
    """
    Check what % of tickers are available in Yahoo Finance

    Args:
        tickers: List of tickers to check
        mdp: YahooFinanceMDP instance

    Returns:
        Coverage ratio (0.0 to 1.0)
    """
    # Try fetching sector info (lightweight check)
    result = mdp.get_sector_info(tickers)
    available = result.filter(pl.col("sector") != "Unknown")

    return len(available) / len(tickers)
```

**Testing Strategy**:
```python
# tests/unit/mdp/test_sector_mapping.py

def test_load_russell_3000_constituents():
    """Test loading Russell 3000 constituents"""
    df = load_russell_3000_constituents()

    assert len(df) >= 2900  # Expect ~3000, allow some missing
    assert "ticker" in df.columns
    assert "sector" in df.columns

    # Check GICS sectors present
    sectors = df["sector"].unique().to_list()
    assert len(sectors) == 11  # 11 GICS Level 1 sectors

def test_get_sector_tickers():
    """Test getting tickers by sector"""
    tech_tickers = get_sector_tickers("Information Technology")

    assert len(tech_tickers) > 0
    assert "AAPL" in tech_tickers
    assert "MSFT" in tech_tickers

def test_sector_etf_mapping():
    """Test sector ETF lookup"""
    etf = get_sector_etf("Information Technology")
    assert etf == "XLK"

    etf = get_sector_etf("Financials")
    assert etf == "XLF"

# ... 12 more tests
```

**Success Criteria**:
- [ ] Russell 3000 constituents CSV downloaded and loaded
- [ ] GICS sector mapping implemented (11 sectors)
- [ ] Sector ETF mapping implemented (11 ETFs)
- [ ] `get_sector_tickers()` returns correct tickers
- [ ] 15 tests passing
- [ ] Committed and pushed (including CSV file!)

---

#### AGENT-09: EquityAdapter Implementation

**Objective**: Implement adapter converting EquityQuery/ETFQuery to standardized Polars DataFrame.

**Starting Context**:
1. `Adapter/FuturesAdapter.py` (existing pattern)
2. `Adapter/Base/BaseAdapter.py` (base class)
3. `Query/Equities/EquityQuery.py` (AGENT-05 output)
4. `Query/Equities/ETFQuery.py` (AGENT-06 output)
5. `MDP/YahooFinance/YahooFinanceMDP.py` (AGENT-07 output)
6. `docs/design/EQUITY_SECTOR_IMPLEMENTATION_PLAN.md` (Phase 1, Section 1.3)

**Skills Required**:
- Adapter pattern
- Polars DataFrame manipulation
- Returns calculation
- Missing data handling

**Deliverables**:
```
Adapter/EquityAdapter.py

tests/unit/adapter/test_equity_adapter.py (20 tests)
tests/integration/test_equity_adapter_live.py (8 tests)
```

**Implementation Guidance**:
```python
# Adapter/EquityAdapter.py

# ABOUTME: Adapter converting EquityQuery/ETFQuery to standardized Polars DataFrame
# ABOUTME: Output format compatible with ReturnsCalculator and signal generation

import polars as pl
from datetime import date
from typing import List, Union
from Adapter.Base.BaseAdapter import BaseAdapter
from Query.Equities import EquityQuery, ETFQuery
from MDP.YahooFinance import YahooFinanceMDP

class EquityAdapter(BaseAdapter):
    """
    Converts equity/ETF queries to standardized format

    Output schema (Polars DataFrame):
        - ticker: str
        - sector: str (GICS Level 1)
        - returns: List[float] (historical returns array)
        - price: float (current price)
        - market_cap: float (optional, for weighting)
        - fundamentals: dict (optional, for signals)
        - avg_volume: float (for transaction costs)
    """

    def convert(
        self,
        queries: List[Union[EquityQuery, ETFQuery]],
        as_of_date: date,
        mdp: YahooFinanceMDP,
    ) -> pl.DataFrame:
        """
        Convert queries to standardized format

        Steps:
        1. Build MDP requests from queries
        2. Fetch price data
        3. Calculate returns
        4. Fetch fundamentals (stocks only, not ETFs)
        5. Combine into single DataFrame
        """
        # Extract tickers
        tickers = [q.ticker for q in queries]

        # Determine date range (max lookback across all queries)
        max_lookback = max(q.lookback_days for q in queries)
        start_date = as_of_date - timedelta(days=max_lookback)

        # Fetch price data
        prices_df = mdp.get_prices(tickers, start_date, as_of_date)

        # Calculate returns
        returns_df = self._calculate_returns(prices_df)

        # Fetch sector info
        sector_df = mdp.get_sector_info(tickers)

        # Fetch fundamentals (stocks only)
        stock_queries = [q for q in queries if isinstance(q, EquityQuery)]
        if stock_queries:
            fundamentals_df = mdp.get_fundamentals([q.ticker for q in stock_queries])
        else:
            fundamentals_df = pl.DataFrame({"ticker": []})  # Empty

        # Combine all data
        result = (
            returns_df
            .join(sector_df, on="ticker", how="left")
            .join(fundamentals_df, on="ticker", how="left")
        )

        # Add current price and avg volume
        current_prices = (
            prices_df
            .group_by("ticker")
            .agg([
                pl.col("close").last().alias("price"),
                pl.col("volume").mean().alias("avg_volume"),
            ])
        )
        result = result.join(current_prices, on="ticker", how="left")

        # Handle missing data
        result = self._handle_missing_data(result)

        return result

    def _calculate_returns(self, prices_df: pl.DataFrame) -> pl.DataFrame:
        """
        Calculate returns from prices

        Returns DataFrame with:
            - ticker: str
            - returns: List[float] (array of daily returns)
        """
        returns_df = (
            prices_df
            .sort(["ticker", "date"])
            .group_by("ticker")
            .agg([
                (pl.col("close").pct_change().drop_nulls()).alias("returns")
            ])
        )

        return returns_df

    def _handle_missing_data(self, df: pl.DataFrame) -> pl.DataFrame:
        """
        Handle missing data gracefully

        Strategies:
        - Sector: Use "Unknown" (will be filtered out later)
        - Fundamentals: Use sector median
        - Returns: Drop stocks with <80% data coverage
        """
        # Fill missing sectors
        df = df.with_columns(
            pl.col("sector").fill_null("Unknown")
        )

        # Fill missing fundamentals with sector median
        for col in ["pe_ratio", "dividend_yield", "roe", "debt_to_equity"]:
            if col in df.columns:
                sector_medians = df.group_by("sector").agg(
                    pl.col(col).median().alias(f"{col}_median")
                )
                df = df.join(sector_medians, on="sector", how="left")
                df = df.with_columns(
                    pl.col(col).fill_null(pl.col(f"{col}_median"))
                )

        # Drop stocks with insufficient returns data
        df = df.filter(
            pl.col("returns").list.lengths() >= 0.8 * 252  # At least 80% of year
        )

        return df
```

**Testing Strategy**:
```python
# tests/unit/adapter/test_equity_adapter.py

def test_convert_single_equity_query(mocker):
    """Test converting single EquityQuery"""
    # Mock MDP
    mock_mdp = mocker.Mock(spec=YahooFinanceMDP)
    mock_mdp.get_prices.return_value = pl.DataFrame(...)
    mock_mdp.get_sector_info.return_value = pl.DataFrame(...)
    mock_mdp.get_fundamentals.return_value = pl.DataFrame(...)

    query = EquityQuery(
        ticker="AAPL",
        sector="Information Technology",
        structure=EquityStructure.SINGLE,
        value=EquityValue.RETURN,
    )

    adapter = EquityAdapter()
    result = adapter.convert([query], date(2025, 1, 1), mock_mdp)

    assert isinstance(result, pl.DataFrame)  # Polars!
    assert "ticker" in result.columns
    assert "sector" in result.columns
    assert "returns" in result.columns
    assert result["ticker"][0] == "AAPL"

def test_convert_mixed_equity_and_etf(mocker):
    """Test converting mix of stocks and ETFs"""
    mock_mdp = mocker.Mock(spec=YahooFinanceMDP)
    mock_mdp.get_prices.return_value = pl.DataFrame(...)
    mock_mdp.get_sector_info.return_value = pl.DataFrame(...)
    mock_mdp.get_fundamentals.return_value = pl.DataFrame(...)  # Only called for stocks

    queries = [
        EquityQuery(ticker="AAPL", ...),
        ETFQuery(ticker="XLK", ...),
    ]

    adapter = EquityAdapter()
    result = adapter.convert(queries, date(2025, 1, 1), mock_mdp)

    assert len(result) == 2
    assert "AAPL" in result["ticker"]
    assert "XLK" in result["ticker"]

    # Check fundamentals only fetched for stocks
    assert mock_mdp.get_fundamentals.call_count == 1
    assert mock_mdp.get_fundamentals.call_args[0][0] == ["AAPL"]  # Not XLK!

# ... 18 more tests
```

**Success Criteria**:
- [ ] `EquityAdapter` implemented
- [ ] Handles both `EquityQuery` and `ETFQuery`
- [ ] Returns calculation working (daily returns)
- [ ] Missing data handled gracefully (sector median, 80% threshold)
- [ ] Polars-native output (no pandas!)
- [ ] 28 tests passing (20 unit + 8 integration)
- [ ] Committed and pushed

---

### WAVE 3: SIGNAL GENERATION

(Continue with AGENT-10 through AGENT-14...)

---

## Commit Strategy for Agents

**Each agent must commit and push their work**:

```bash
# When agent completes their task:

git add <files>
git commit -m "feat(agent-XX): <task description>

<Detailed commit message with:
- What was implemented
- Test coverage (N tests passing)
- Dependencies satisfied
- Success criteria met
>

<If any issues encountered, document here>"

git push -u origin claude/equity-sector-portfolio-planning-011CV2pP4NRAwS4k6wTNsm1u
```

**Example**:
```bash
git commit -m "feat(agent-05): Implement EquityQuery for Russell 3000 stocks

Implement EquityQuery dataclass with GICS sector support:
- EquityQuery, EquityStructure, EquityValue classes
- Inherits from BaseQuery
- build_mdp_request() method for Yahoo Finance integration
- Validation for invalid inputs

Test coverage: 20 tests passing
Dependencies: BaseQuery (existing), GICS sectors (AGENT-08 will provide)
Success criteria: All criteria met

Files created:
- Query/Equities/EquityQuery.py
- Query/Equities/EquityStructure.py
- Query/Equities/EquityValue.py
- tests/unit/query/test_equity_query.py"
```

---

## Agent Communication Protocol

**Agents do NOT communicate with each other directly.** Instead:

1. **Dependencies handled via file reads**: Each agent reads output files from prerequisite agents
2. **Synchronization via git**: Agents check branch for completed work
3. **Blocking dependencies**: Agent waits until prerequisite files exist
4. **Documentation updates**: Each agent updates relevant docs with their implementation notes

**Example**:
```python
# AGENT-09 (EquityAdapter) checks for prerequisites:

def check_prerequisites():
    """Ensure AGENT-05, AGENT-06, AGENT-07 have completed"""
    required_files = [
        "Query/Equities/EquityQuery.py",  # AGENT-05
        "Query/Equities/ETFQuery.py",  # AGENT-06
        "MDP/YahooFinance/YahooFinanceMDP.py",  # AGENT-07
    ]

    for file in required_files:
        if not Path(file).exists():
            raise RuntimeError(f"Prerequisite not met: {file} does not exist. "
                             f"Ensure AGENT-05, AGENT-06, AGENT-07 have completed.")

    print("✅ All prerequisites satisfied!")

check_prerequisites()
# ... proceed with implementation
```

---

## Next Steps

Peter, I'll now:

1. **Complete remaining agent specs** (AGENT-10 through AGENT-20)
2. **Commit this orchestration plan**
3. **Wait for your approval** to launch agents

**Critical decisions needed from you**:
- Start with Wave 1 (research agents) immediately?
- Or review this plan first before any agents launch?
- Any changes to timeline/scope?

**What I'm committing now**:
- This agent orchestration plan (AGENT-01 through AGENT-09 detailed)
- Will create Part 2 (AGENT-10 through AGENT-20) next

---

**End of Part 1 - Waves 1-2 Detailed**
