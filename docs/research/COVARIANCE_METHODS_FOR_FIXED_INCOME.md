# Research Plan: Covariance Estimation for Fixed Income/Futures Portfolios

**Question**: What covariance methods do practitioners say actually work for highly correlated instruments (futures, swaps, STIR)?

**Context**: ARBS backtests futures/swaps strategies with:
- High correlation between instruments (90%+)
- Mean-reversion and carry signals
- DV01-based risk models
- Need empirically validated methods, not theoretical curiosities

---

## Research Tasks (Orthogonal)

### Task 1: Grinold-Kahn Fixed Income Guidance
**Agent**: Explore
**Goal**: Extract specific fixed income covariance recommendations from Active Portfolio Management

**Deliverable**:
- What does Ch 3 (Risk) say about fixed income specifically?
- Do they recommend factor models? Shrinkage? Sample covariance?
- Any empirical results comparing methods?
- File: `docs/research/grinold_kahn_fixed_income_covariance.md`

### Task 2: Practitioner Surveys & Industry Papers
**Agent**: Explore
**Goal**: Find surveys/whitepapers from practitioners on what they actually use

**Search for**:
- "covariance estimation fixed income" site:ssrn.com
- "risk model interest rate swaps" practitioner guides
- CFA Institute / GARP papers on fixed income risk
- Industry surveys (MSCI, Bloomberg, etc.)

**Deliverable**:
- What methods are mentioned most?
- Any head-to-head empirical comparisons?
- File: `docs/research/practitioner_covariance_methods.md`

### Task 3: Factor Model Evidence
**Agent**: Explore
**Goal**: Find empirical evidence for factor models in fixed income

**Research**:
- Do practitioners use PCA for yield curves?
- Factor models (level/slope/curvature) vs full covariance?
- Papers comparing factor vs shrinkage for bonds/swaps

**Deliverable**:
- When do factor models work better?
- How many factors for futures portfolios?
- File: `docs/research/factor_models_fixed_income.md`

### Task 4: High-Correlation Specific Methods
**Agent**: Explore
**Goal**: Methods designed for highly correlated assets

**Research**:
- Constant correlation models
- Diagonal + correlation structure
- Total Positivity (MTP2) methods
- Papers on "covariance estimation positively correlated assets"

**Deliverable**:
- Which methods handle 90%+ correlation?
- Empirical results vs Ledoit-Wolf?
- File: `docs/research/high_correlation_covariance.md`

### Task 5: Current ARBS Covariance Analysis
**Agent**: Explore
**Goal**: Understand what we're using now and how it performs

**Analyze**:
- Read current implementations (SampleCovariance, LedoitWolf, etc.)
- Check if any tests compare methods
- Look at example backtests - which risk model is used?

**Deliverable**:
- What's implemented vs what's actually used?
- Any performance comparisons in tests?
- File: `docs/research/current_arbs_covariance_usage.md`

---

## Success Criteria

**Good outcomes**:
- Clear recommendation: "For futures portfolios, use X because Y"
- Empirical evidence (not just theory)
- Implementation path identified
- Knows what NOT to use

**Bad outcomes**:
- List of 20 methods with no guidance
- Theoretical papers with no empirical tests
- "It depends" with no decision framework

---

## Expected Findings

**Hypothesis** (to be validated):
1. **Ledoit-Wolf shrinkage** is industry standard baseline (5000+ citations)
2. **Factor models** (PCA) work well for yield curves but maybe not individual futures
3. **Constant correlation** might work for STIR futures (all driven by same factors)
4. **Sample covariance fails** when N ≈ T or high correlation

**Next Step After Research**:
- Pick top 2-3 methods
- Implement if not already in ARBS
- Backtest comparison on actual futures data
- Document "use this for futures portfolios"
