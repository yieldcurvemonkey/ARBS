# Agent Orchestration Plan: Equity Sector Portfolio Implementation (Unified)

**Date**: 2025-11-11 (Created), 2025-11-14 (Unified)
**Universe**: Russell 3000 + Sector ETFs
**Strategy**: Long/Short (Market-Neutral)
**Timeline**: 17 weeks
**Agents**: 20 total

---

## Implementation Status (2025-11-14)

**Completed (40%)**:
- **Wave 1: Foundation (AGENT-01 to AGENT-05)** - Research and design completed
  - Russell 3000 universe research
  - Sector ETF research & mapping
  - Yahoo Finance API design
  - Long/short strategy design

- **Wave 2: Infrastructure (AGENT-06 to AGENT-09)** - Data infrastructure implemented
  - EquityQuery implementation
  - ETFQuery implementation
  - Yahoo Finance MDP implementation
  - Sector classification system
  - EquityAdapter implementation

**Not Started (60%)**:
- **Wave 3: Signal Generation (AGENT-10 to AGENT-13)** - Cross-sectional equity signals
  - ValueSignal (DDM + E/P ratio)
  - MomentumSignal (12-month, skip last month)
  - QualitySignal (ROE, debt, stability composite)
  - BaseSignal cross-sectional extension
  - Signal IC validation framework

- **Wave 4: Risk Models (AGENT-14 to AGENT-17)** - Multi-factor covariance estimation
  - EquityFactorModel (17 factors: 11 sectors + 6 styles)
  - FactorCovariance (V = X·F·X^T + Δ)
  - PPFMCovariance (Projection-Penalized Factor Model from paper)

- **Wave 5: Optimization (AGENT-18 to AGENT-19)** - Long/short market-neutral optimization
  - Long/Short Optimizer with constraints (market-neutral, sector-neutral, position limits)
  - Transaction cost integration (square-root law)

- **Wave 6: Integration (AGENT-20)** - End-to-end integration and validation
  - End-to-end backtest integration
  - IC validation against Grinold-Kahn targets
  - PPFM paper replication
  - Documentation and user guide

**Conflicts**: This plan conflicts with BACKTEST_UNIFICATION_PLAN.md. Both propose different architectures for equity integration.

**Recommendation**: Resolve architectural approach before proceeding with either plan.
- **Agent Orchestration Plan**: Proposes separate equity infrastructure with specialized components
- **Backtest Unification Plan**: Proposes extending the existing generic backtest framework

**Decision Needed**: Choose between:
1. Proceeding with agent orchestration (separate equity infrastructure)
2. Proceeding with backtest unification (extend generic framework)
3. Hybrid approach (unify where possible, specialize where necessary)

---

## Executive Summary

This plan orchestrates **20 AI agents** to implement equity sector portfolios in ARBS. Each agent:
- **Starts from zero** (no assumed context beyond specified files)
- Works **independently** on orthogonal tasks
- Has **clear success criteria**
- **Commits and pushes** their work when complete
- Can execute in **parallel waves** where dependencies allow

**Key Decisions**:
- **Universe**: Russell 3000 (3,000 stocks) + 11 sector ETFs
- **Strategy**: Long/short market-neutral (no long-only constraint)
- **Data Source**: Yahoo Finance (free, sufficient for MVP)
- **Framework**: Polars-native (no pandas)
- **Expected IR**: 1.5-2.0 (vs 0.5 for long-only)
- **Transfer Coefficient**: 0.85 (vs 0.5 for long-only)

---

## Wave-Based Execution Strategy

### Wave 1: Foundational Research & Design (Week 1) ✅ COMPLETE
**4 agents in parallel** - Pure research, no code

| Agent | Task | Time | Tests | Status |
|-------|------|------|-------|--------|
| AGENT-01 | Russell 3000 Universe Research | 2d | 0 | ✅ Complete |
| AGENT-02 | Sector ETF Research & Mapping | 2d | 0 | ✅ Complete |
| AGENT-03 | Yahoo Finance API Design | 2d | 0 | ✅ Complete |
| AGENT-04 | Long/Short Strategy Design | 2d | 0 | ✅ Complete |

**Deliverables**: 4 research documents defining universe, data sources, and strategy

---

### Wave 2: Data Infrastructure (Weeks 2-3) ✅ COMPLETE
**5 agents in parallel** - Query layer and data providers

| Agent | Task | Time | Tests | Status |
|-------|------|------|-------|--------|
| AGENT-05 | EquityQuery Implementation | 3d | 20 | ✅ Complete |
| AGENT-06 | ETFQuery Implementation | 3d | 15 | ✅ Complete |
| AGENT-07 | Yahoo Finance MDP Implementation | 5d | 35 | ✅ Complete |
| AGENT-08 | Sector Classification System | 3d | 15 | ✅ Complete |
| AGENT-09 | EquityAdapter Implementation | 4d | 28 | ✅ Complete |

**Deliverables**: Query classes, Yahoo Finance MDP, sector mapping, equity adapter (113 tests)

---

### Wave 3: Signal Generation (Weeks 4-7) ⏸️ PENDING
**5 agents in parallel** - Cross-sectional equity signals

| Agent | Task | Time | Tests | Status |
|-------|------|------|-------|--------|
| AGENT-10 | ValueSignal Implementation | 5d | 30 | ⏸️ Pending |
| AGENT-11 | MomentumSignal Implementation | 5d | 25 | ⏸️ Pending |
| AGENT-12 | QualitySignal Implementation | 5d | 25 | ⏸️ Pending |
| AGENT-13 | BaseSignal Cross-Sectional Extension | 3d | 15 | ⏸️ Pending |
| AGENT-14 | Signal IC Validation Framework | 4d | 15 | ⏸️ Pending |

**Expected Deliverables**:
- ValueSignal: DDM + E/P ratio (IC target: 0.03-0.04)
- MomentumSignal: 12-month return, skip last month (IC target: 0.04-0.06)
- QualitySignal: ROE, debt, stability composite (IC target: 0.02-0.03)
- BaseSignal extensions: Sector-neutralization utilities
- IC validation framework: Historical backtesting on Russell 3000 (2018-2023)

**Total**: 110 tests

---

### Wave 4: Risk Models (Weeks 8-11) ⏸️ PENDING
**3 agents in parallel** - Multi-factor covariance

| Agent | Task | Time | Tests | Status |
|-------|------|------|-------|--------|
| AGENT-15 | EquityFactorModel Implementation | 7d | 25 | ⏸️ Pending |
| AGENT-16 | FactorCovariance Implementation | 7d | 30 | ⏸️ Pending |
| AGENT-17 | PPFMCovariance Implementation | 10d | 45 | ⏸️ Pending |

**Expected Deliverables**:
- EquityFactorModel: 17 factors (11 GICS sectors + 6 style factors)
  - Style factors: Size, Value, Momentum, Quality, Low Volatility, Dividend Yield
  - Reduces parameters from N² (9M) to N·K + K² + N (54K) = 99.4% reduction

- FactorCovariance: V = X·F·X^T + Δ
  - Factor returns via regression
  - Specific risk decomposition
  - Lower condition number vs sample covariance

- PPFMCovariance: Projection-Penalized Factor Model (arXiv:2507.16433)
  - Multi-sector joint estimation
  - Projection penalty for sector relatedness
  - Cross-validated λ selection
  - Expected: 10-15% risk reduction vs FactorCovariance

**Total**: 100 tests

---

### Wave 5: Long/Short Optimization (Weeks 12-14) ⏸️ PENDING
**2 agents in parallel** - Market-neutral portfolio optimization

| Agent | Task | Time | Tests | Status |
|-------|------|------|-------|--------|
| AGENT-18 | Long/Short Optimizer with Constraints | 10d | 40 | ⏸️ Pending |
| AGENT-19 | Transaction Cost Integration | 7d | 30 | ⏸️ Pending |

**Expected Deliverables**:
- LongShortOptimizer:
  - Market-neutral constraint: Σ w_i = 0
  - Sector-neutral constraint: Σ w_i per sector = 0
  - Position limits: |w_i| ≤ 5%
  - Gross leverage: Σ |w_i| ≤ 2.0 (100% long, 100% short)
  - Expected TC ≈ 0.85 (vs 0.5 for long-only)

- Transaction Costs:
  - Square-root law (Loeb 1983): TC ∝ √(trade size)
  - Market impact + commission
  - Turnover/value-added frontier analysis
  - Expected costs: <50 bps per rebalance

**Total**: 70 tests

---

### Wave 6: Integration & Validation (Weeks 15-17) ⏸️ PENDING
**1 agent** - End-to-end integration and validation

| Agent | Task | Time | Tests | Status |
|-------|------|------|-------|--------|
| AGENT-20 | End-to-End Integration & Validation | 15d | 35 | ⏸️ Pending |

**Expected Deliverables**:
- End-to-end backtest pipeline
- IC validation report (vs Grinold-Kahn targets)
- PPFM paper replication report (vs Table 2 results)
- User guide (README_EQUITY_SECTOR.md)
- Example configurations (YAML)
- Performance validation:
  - IR > 1.0 (target: 1.5-2.0)
  - IC > 0.06 (combined signals)
  - Transfer coefficient > 0.8
  - Sector neutrality validated (<1e-6 per sector)

**Total**: 35 tests

---

## Total Project Metrics

**Agents**: 20 total (9 complete, 11 pending)
**Tests**: 583 total (113 complete, 470 pending)
**Duration**: 17 weeks (3 complete, 14 pending)
**Completion**: 40% (by agent count), ~19% (by tests)

**Test Breakdown by Wave**:
- Wave 1: 0 tests (research only)
- Wave 2: 113 tests ✅
- Wave 3: 110 tests ⏸️
- Wave 4: 100 tests ⏸️
- Wave 5: 70 tests ⏸️
- Wave 6: 35 tests ⏸️

---

## Success Criteria

### Technical Targets
- [ ] All 583 tests passing
- [ ] Information Ratio (IR) > 1.0 (target: 1.5-2.0)
- [ ] Information Coefficient (IC) > 0.06 (combined signals)
- [ ] Transfer Coefficient (TC) > 0.8 (long/short advantage vs 0.5 for long-only)
- [ ] PPFM risk reduction: 10-15% vs baseline FactorCovariance
- [ ] Transaction costs: <50 bps per monthly rebalance
- [ ] Sector neutrality: |mean| < 1e-6 for all 11 sectors

### Signal IC Validation Targets (vs Grinold-Kahn book)
- [ ] ValueSignal IC: 0.03-0.04 (historical backtest 2018-2023)
- [ ] MomentumSignal IC: 0.04-0.06 (historical backtest 2018-2023)
- [ ] QualitySignal IC: 0.02-0.03 (historical backtest 2018-2023)
- [ ] Combined IC: 0.06-0.07 (√(0.035² + 0.05² + 0.025²) ≈ 0.063)
- [ ] All ICs statistically significant (t-statistic > 2.0)

### Paper Replication Targets
- [ ] PPFM Sharpe ratio within 10% of paper Table 2
- [ ] PPFM turnover within 10% of paper
- [ ] PPFM risk reduction within 10% of paper (vs baseline)

### Documentation Completeness
- [ ] User guide (README_EQUITY_SECTOR.md)
- [ ] API documentation (all 20 agents)
- [ ] IC validation report with charts
- [ ] PPFM replication report with comparison tables
- [ ] Example configurations (at least 3 scenarios)

---

## Commit Strategy

Each agent commits with:
```bash
git commit -m "feat(agent-XX): <task description>

<Implementation details>
- What was implemented
- Test coverage: N tests passing
- Dependencies satisfied
- Success criteria met

<Any issues or deviations documented here>"

git push -u origin claude/equity-sector-portfolio-planning-011CV2pP4NRAwS4k6wTNsm1u
```

---

## Agent Communication Protocol

**Agents do NOT communicate directly.** Instead:
1. **File-based dependencies**: Agents read output files from prerequisite agents
2. **Git synchronization**: Check branch for completed work
3. **Blocking on missing files**: Wait for prerequisite files to exist
4. **No assumptions**: Each agent validates prerequisites before starting

Example prerequisite check:
```python
required_files = [
    "Query/Equities/EquityQuery.py",  # AGENT-05
    "MDP/YahooFinance/YahooFinanceMDP.py",  # AGENT-07
]

for file in required_files:
    if not Path(file).exists():
        raise RuntimeError(f"Prerequisite {file} not found")
```

---

## Detailed Specifications

**For complete implementation details for each agent, see:**

1. **Waves 1-2 (AGENT-01 to AGENT-09)**:
   - Originally in `AGENT_ORCHESTRATION_PLAN.md`
   - Now archived at `docs/archive/abandoned-plans/AGENT_ORCHESTRATION_PLAN.md`
   - Coverage: Research, design, data infrastructure
   - Status: ✅ COMPLETE

2. **Waves 3-4 (AGENT-10 to AGENT-17)**:
   - Originally in `AGENT_ORCHESTRATION_PLAN_PART2.md`
   - Now archived at `docs/archive/abandoned-plans/AGENT_ORCHESTRATION_PLAN_PART2.md`
   - Coverage: Signal generation, risk models
   - Status: ⏸️ PENDING

3. **Waves 5-6 (AGENT-18 to AGENT-20)**:
   - Originally in `AGENT_ORCHESTRATION_PLAN_PART3.md`
   - Now archived at `docs/archive/abandoned-plans/AGENT_ORCHESTRATION_PLAN_PART3.md`
   - Coverage: Optimization, transaction costs, integration
   - Status: ⏸️ PENDING

Each archived file contains:
- Detailed starting context (files to read)
- External research required
- Skills required
- Complete implementation guidance with code examples
- Testing strategy with example tests
- Success criteria

---

## Next Steps

### Immediate Actions Required
1. **Resolve architectural conflict** between this plan and BACKTEST_UNIFICATION_PLAN.md
   - Decision: Separate equity infrastructure OR extend generic backtest
   - Timeline: Before launching Wave 3 agents

2. **Review completion status**
   - Verify Waves 1-2 actually completed (test counts, file existence)
   - Document any gaps or issues

3. **Plan Wave 3 launch** (if proceeding with agent orchestration)
   - 5 agents in parallel
   - 110 tests to implement
   - ~3-4 weeks estimated duration

### For Peter
- **Review** this unified plan and status assessment
- **Decide** on architectural approach (agent orchestration vs backtest unification)
- **Approve** or modify before proceeding to Wave 3
- **Identify** any blockers or concerns

---

## Appendix: Agent Dependency Graph

```
Wave 1 (Research, no dependencies):
  AGENT-01 ─┐
  AGENT-02 ─┼─┐
  AGENT-03 ─┤ │
  AGENT-04 ─┘ │
              │
Wave 2 (Data Infrastructure):
              ├→ AGENT-05 ─┐
              ├→ AGENT-06 ─┼─┐
              ├→ AGENT-07 ─┤ │
              ├→ AGENT-08 ─┤ │
              └→ AGENT-09 ←─┘ │
                              │
Wave 3 (Signals):                │
                              ├→ AGENT-10 ─┐
                              ├→ AGENT-11 ─┼─┐
                              ├→ AGENT-12 ─┤ │
                              ├→ AGENT-13 ←─┘ │
                              └→ AGENT-14 ─────┤
                                               │
Wave 4 (Risk):                                 │
                              ├→ AGENT-15 ─┐   │
                              ├→ AGENT-16 ─┼─┐ │
                              └→ AGENT-17 ←─┘ │ │
                                               │ │
Wave 5 (Optimization):                         │ │
                              ├→ AGENT-18 ←────┘ │
                              └→ AGENT-19 ────────┤
                                                  │
Wave 6 (Integration):                             │
                              └→ AGENT-20 ←────────┘
```

**Critical Path**: AGENT-01 → AGENT-09 → AGENT-10 → AGENT-15 → AGENT-18 → AGENT-20

**Parallelization Opportunities**:
- Wave 1: All 4 agents in parallel
- Wave 2: AGENT-05 to AGENT-08 in parallel (AGENT-09 depends on 05, 06, 07)
- Wave 3: AGENT-10 to AGENT-12 in parallel (AGENT-13 refactors them, AGENT-14 validates)
- Wave 4: AGENT-15 to AGENT-17 in parallel (AGENT-16 and 17 depend on AGENT-15)
- Wave 5: AGENT-18 and AGENT-19 can partially overlap
- Wave 6: AGENT-20 is serial (depends on all previous)

---

**End of Unified Agent Orchestration Plan**

**Created**: 2025-11-11 (original)
**Unified**: 2025-11-14
**Last Updated**: 2025-11-14
