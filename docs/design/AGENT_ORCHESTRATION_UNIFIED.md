# Agent Orchestration Plan: Equity Sector Portfolio Implementation

**Date**: 2025-11-11
**Universe**: Russell 3000 + Sector ETFs
**Strategy**: Long/Short (Market-Neutral)
**Timeline**: 17 weeks
**Status**: 40% Complete (Waves 1-2)

---

## Implementation Status (2025-11-14)

**Completed (40%)**:
- Wave 1: Foundation (AGENT-01 to AGENT-05) - Research and design completed
- Wave 2: Infrastructure (AGENT-06 to AGENT-09) - Data infrastructure implemented

**Not Started (60%)**:
- Wave 3: Signal Generation (AGENT-10 to AGENT-13) - Cross-sectional equity signals
- Wave 4: Risk Models (AGENT-14 to AGENT-17) - Multi-factor covariance estimation
- Wave 5: Optimization (AGENT-18 to AGENT-19) - Long/short market-neutral optimization
- Wave 6: Integration (AGENT-20) - End-to-end integration and validation

**Conflicts**: This plan conflicts with BACKTEST_UNIFICATION_PLAN.md. Both propose different architectures for equity integration.

**Recommendation**: Resolve architectural approach before proceeding with either plan. The agent orchestration plan proposes a separate equity infrastructure, while the backtest unification plan proposes extending the existing generic backtest framework.

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

| Agent ID | Task | Estimated Time | Status |
|----------|------|----------------|--------|
| AGENT-01 | Russell 3000 Universe Research | 2 days | ✓ Complete |
| AGENT-02 | Sector ETF Research & Mapping | 2 days | ✓ Complete |
| AGENT-03 | Yahoo Finance API Design | 2 days | ✓ Complete |
| AGENT-04 | Long/Short Strategy Design | 2 days | ✓ Complete |

### Wave 2: Data Infrastructure (Weeks 2-3)
**5 agents in parallel** - Query layer and data providers

| Agent ID | Task | Estimated Time | Status |
|----------|------|----------------|--------|
| AGENT-05 | EquityQuery Implementation | 3 days | ✓ Complete |
| AGENT-06 | ETFQuery Implementation | 3 days | ✓ Complete |
| AGENT-07 | Yahoo Finance MDP Implementation | 5 days | ✓ Complete |
| AGENT-08 | Sector Classification System | 3 days | ✓ Complete |
| AGENT-09 | EquityAdapter Implementation | 4 days | ✓ Complete |

### Wave 3: Signal Generation (Weeks 4-7)
**5 agents in parallel** - Cross-sectional equity signals

| Agent ID | Task | Estimated Time | Status |
|----------|------|----------------|--------|
| AGENT-10 | ValueSignal Implementation | 5 days | Pending |
| AGENT-11 | MomentumSignal Implementation | 5 days | Pending |
| AGENT-12 | QualitySignal Implementation | 5 days | Pending |
| AGENT-13 | BaseSignal Cross-Sectional Extension | 3 days | Pending |
| AGENT-14 | Signal IC Validation Framework | 4 days | Pending |

### Wave 4: Risk Models (Weeks 8-11)
**3 agents in parallel** - Multi-factor covariance

| Agent ID | Task | Estimated Time | Status |
|----------|------|----------------|--------|
| AGENT-15 | EquityFactorModel Implementation | 7 days | Pending |
| AGENT-16 | FactorCovariance Implementation | 7 days | Pending |
| AGENT-17 | PPFMCovariance Implementation | 10 days | Pending |

### Wave 5: Long/Short Optimization (Weeks 12-14)
**2 agents in parallel** - Market-neutral optimization

| Agent ID | Task | Estimated Time | Status |
|----------|------|----------------|--------|
| AGENT-18 | Long/Short Optimizer with Constraints | 10 days | Pending |
| AGENT-19 | Transaction Cost Integration | 7 days | Pending |

### Wave 6: Analysis & Integration (Weeks 15-17)
**1 agent** - End-to-end integration and validation

| Agent ID | Task | Estimated Time | Status |
|----------|------|----------------|--------|
| AGENT-20 | End-to-End Integration & Validation | 15 days | Pending |

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

(Detailed specifications for AGENT-10 through AGENT-14 covering ValueSignal, MomentumSignal, QualitySignal, BaseSignal extensions, and IC validation framework)

[Content from Part 2, lines 1-1024]

---

### WAVE 4: RISK MODELS

(Detailed specifications for AGENT-15 through AGENT-17 covering EquityFactorModel, FactorCovariance, and PPFMCovariance)

[Content from Part 2, lines 1025-1838]

---

### WAVE 5: LONG/SHORT OPTIMIZATION

(Detailed specifications for AGENT-18 and AGENT-19 covering long/short optimizer with constraints and transaction cost integration)

[Content from Part 3, lines 1-819]

---

### WAVE 6: END-TO-END INTEGRATION

(Detailed specifications for AGENT-20 covering end-to-end integration and validation)

[Content from Part 3, lines 820-1250]

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
- [ ] AGENT-10: ValueSignal implementation
- [ ] AGENT-11: MomentumSignal implementation
- [ ] AGENT-12: QualitySignal implementation
- [ ] AGENT-13: BaseSignal cross-sectional extension
- [ ] AGENT-14: Signal IC validation framework

**Wave 4: Risk Models (Weeks 8-11)** - 3 agents
- [ ] AGENT-15: EquityFactorModel implementation
- [ ] AGENT-16: FactorCovariance implementation
- [ ] AGENT-17: PPFMCovariance implementation

**Wave 5: Optimization (Weeks 12-14)** - 2 agents
- [ ] AGENT-18: Long/Short optimizer with constraints
- [ ] AGENT-19: Transaction cost integration

**Wave 6: Integration (Weeks 15-17)** - 1 agent
- [ ] AGENT-20: End-to-end integration & validation

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

---

**End of Agent Orchestration Plan (Unified)**
