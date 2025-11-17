# Phase 4: Real Data Validation & Strategy Integration

**Branch:** `claude/phase-4-validation-[SESSION_ID]` (to be created)
**Prerequisites:** Phase 3 complete and merged
**Estimated Duration:** 3-4 hours
**Goal:** Validate sector-based covariance models on real market data and integrate into strategy factory

---

## Phase 3 Recap - What We Built

### Summary
Phase 3 created a unified architecture for sector-based covariance estimation:

1. **Abstract Base Class** (`SectorBasedCovarianceEstimator`)
   - Common interface for all sector-based models
   - Shared utilities (validation, format conversion, sector assignment)
   - 15 tests covering all functionality

2. **Refactored Implementations**
   - `BlockDiagonalCovariance` - Factor model with block-diagonal residuals
   - `TwoStepCovariance` - Hierarchical clustering + RMT filtering
   - `StochasticBlockCovariance` - Allows cross-sector correlations
   - **137 lines of duplicate code eliminated**
   - **All 107 tests passing**

3. **Comprehensive Documentation**
   - `SECTOR_COVARIANCE_GUIDE.md` (440 lines) - Usage guide and benchmarks
   - `sector_covariance_comparison.py` - Performance comparison script
   - `phase3_common_patterns_analysis.md` - Architecture analysis

### Key Achievement
✅ **Production-ready architecture** with consistent interface, comprehensive tests, and clear documentation

### What's Missing
❌ **Validation on real market data** - Currently only tested on synthetic data
❌ **Integration with strategy factory** - Not yet available in YAML configs
❌ **Performance benchmarks on actual portfolios** - Need empirical validation

---

## Phase 4 Objectives

### Primary Goal
**Validate sector-based covariance models on real market data and integrate them into the existing strategy factory system.**

### Success Criteria
1. ✅ All 3 models run successfully on real S&P 500 data (or similar)
2. ✅ Performance metrics match or improve upon paper claims
3. ✅ Models integrated into `StrategyFactory` with YAML support
4. ✅ End-to-end backtest demonstrating practical usage
5. ✅ Performance comparison on real data (not synthetic)
6. ✅ All tests passing (107+ new tests for integration)

---

## Phase 4 Tasks - Detailed Breakdown

### Task 1: Data Acquisition & Preparation (30 minutes)

**Objective:** Acquire real market data for validation

#### 1.1 Identify Data Source
- **Option A:** Use existing data in `Query/` if available
- **Option B:** Download S&P 500 data via yfinance
- **Option C:** Use smaller universe (e.g., Dow 30) for faster testing

**Deliverable:** Function to load real market data
```python
# File: tests/integration/test_sector_covariance_real_data.py
def load_real_market_data(
    universe: str = "sp500",  # or "dow30", "nasdaq100"
    start_date: str = "2020-01-01",
    end_date: str = "2024-01-01",
) -> pl.DataFrame:
    """
    Load real market data for validation.

    Returns:
        DataFrame with columns [ticker, date, return, sector]
    """
```

#### 1.2 Sector Classification
- Map tickers to GICS sectors (if not already available)
- Validate sector completeness (all tickers have sectors)
- Handle missing data appropriately

**Deliverable:** Sector mapping function
```python
def get_sector_mapping(tickers: list[str]) -> dict[str, str]:
    """Map tickers to GICS sectors."""
```

#### 1.3 Data Quality Checks
- Check for missing dates
- Verify return calculations
- Remove tickers with insufficient history
- Handle corporate actions (splits, dividends)

**Test:** `test_real_data_quality()`

---

### Task 2: Model Validation on Real Data (45 minutes)

**Objective:** Validate all 3 models produce reasonable results on real data

#### 2.1 BlockDiagonalCovariance Validation

**Tests to Run:**
```python
def test_block_diagonal_on_sp500():
    """Validate BlockDiagonalCovariance on S&P 500 data."""
    # 1. Load data
    data = load_real_market_data("sp500", "2020-01-01", "2024-01-01")

    # 2. Fit model
    estimator = BlockDiagonalCovariance(
        n_factors=10,  # More factors for large universe
        clustering_method="predefined",
        shrinkage_method="ledoit_wolf",
    )
    cov = estimator.fit(data, sector_col="sector")

    # 3. Validate outputs
    assert cov.shape[0] == data["ticker"].n_unique()
    assert np.allclose(cov, cov.T)  # Symmetry
    assert np.all(np.linalg.eigvalsh(cov) > 0)  # Positive definite
    assert estimator.condition_number() < 100  # Well-conditioned

    # 4. Check block structure
    sector_groups = estimator.get_sector_groups()
    assert len(sector_groups) == 11  # 11 GICS sectors
```

**Success Criteria:**
- ✅ Model fits without errors
- ✅ Covariance matrix is positive definite
- ✅ Condition number < 100 (well-conditioned)
- ✅ Block structure matches GICS sectors

#### 2.2 TwoStepCovariance Validation

**Tests to Run:**
```python
def test_two_step_on_sp500():
    """Validate TwoStepCovariance on S&P 500 data."""
    estimator = TwoStepCovariance(
        n_clusters=11,  # Match GICS sector count
        linkage_method="ward",
        rmt_filter=True,
    )
    cov = estimator.fit(data)

    # Validate discovered clusters align with sectors
    clustering = estimator.get_clustering_result()
    # Compute cluster purity vs GICS sectors
    purity = compute_cluster_purity(clustering, true_sectors)
    assert purity > 0.7  # At least 70% match
```

**Success Criteria:**
- ✅ Discovered clusters align with GICS sectors (>70% purity)
- ✅ RMT filtering removes noise eigenvalues
- ✅ Improved condition number vs sample covariance

#### 2.3 StochasticBlockCovariance Validation

**Tests to Run:**
```python
def test_stochastic_block_on_sp500():
    """Validate StochasticBlockCovariance on S&P 500 data."""
    estimator = StochasticBlockCovariance(
        allow_inter_block=True,
        alpha=0.7,
        shrinkage_per_block=True,
    )
    cov = estimator.fit(data, sector_col="sector")

    # Validate cross-sector correlations
    cross_corr = estimator.get_cross_sector_correlations()
    assert len(cross_corr) > 0  # Non-zero off-diagonal blocks

    # Compare alpha=1.0 (pure block) vs alpha=0.7
    estimator_block = StochasticBlockCovariance(alpha=1.0)
    cov_block = estimator_block.fit(data, sector_col="sector")

    # Verify interpolation: alpha=0.7 between alpha=1.0 and alpha=0.0
    assert np.linalg.norm(cov - cov_block, 'fro') > 0
```

**Success Criteria:**
- ✅ Cross-sector correlations captured
- ✅ Alpha parameter works as expected
- ✅ Interpolation between block-diagonal and full covariance

---

### Task 3: Performance Comparison on Real Data (45 minutes)

**Objective:** Compare all 3 models on real data metrics

#### 3.1 Out-of-Sample Validation

**Method:**
- Train period: 2020-2022 (3 years)
- Test period: 2023-2024 (1 year)
- Rolling window: 252-day estimation, 63-day test

**Metrics to Track:**
```python
@dataclass
class BacktestMetrics:
    sharpe_ratio: float
    total_return: float
    max_drawdown: float
    turnover: float
    hhi: float  # Herfindahl-Hirschman Index (diversification)
    leverage: float  # Sum of absolute weights
    condition_number: float
```

**Implementation:**
```python
def compare_models_out_of_sample(
    train_data: pl.DataFrame,
    test_data: pl.DataFrame,
    models: list[BaseCovarianceEstimator],
) -> pl.DataFrame:
    """
    Compare models on out-of-sample performance.

    Returns:
        DataFrame with columns [model, sharpe, return, drawdown, ...]
    """
    results = []

    for model in models:
        # 1. Fit on train data
        cov_train = model.fit(train_data)

        # 2. Compute mean-variance portfolio
        mu_train = compute_expected_returns(train_data)
        weights = solve_markowitz(mu_train, cov_train)

        # 3. Test on out-of-sample data
        returns_test = compute_portfolio_returns(test_data, weights)
        metrics = compute_metrics(returns_test)

        results.append({
            "model": model.__class__.__name__,
            **asdict(metrics),
        })

    return pl.DataFrame(results)
```

#### 3.2 Replicate Paper Results

**Target Metrics from García-Medina et al. (2024):**

| Metric | Sample Cov | TwoStep | Target |
|--------|-----------|---------|--------|
| Sharpe Ratio | 0.45 | 0.61 | > 0.55 |
| HHI | 0.55 | 0.38 | < 0.45 |
| Leverage | 2.10 | 1.72 | < 1.90 |

**Success Criteria:**
- ✅ TwoStep achieves Sharpe > 0.55 (vs 0.61 in paper)
- ✅ TwoStep achieves HHI < 0.45 (diversification)
- ✅ TwoStep achieves Leverage < 1.90

#### 3.3 Create Real Data Comparison Report

**File:** `docs/REAL_DATA_VALIDATION_REPORT.md`

**Contents:**
1. Dataset description (universe, period, sectors)
2. Performance metrics table (all 3 models + sample cov baseline)
3. Statistical significance tests (Sharpe ratio differences)
4. Visualization: Cumulative returns, drawdowns, turnover
5. Comparison to paper results
6. Recommendations for practitioners

**Deliverable:** Comprehensive markdown report with tables and analysis

---

### Task 4: Strategy Factory Integration (60 minutes)

**Objective:** Integrate sector-based covariance into YAML strategy configs

#### 4.1 Create CovarianceFactory Extension

**File:** `Risk/Factory/CovarianceFactory.py` (extend existing)

**Add Methods:**
```python
class CovarianceFactory:
    # ... existing methods ...

    @staticmethod
    def create_block_diagonal(config: dict) -> BlockDiagonalCovariance:
        """Create BlockDiagonalCovariance from config."""
        return BlockDiagonalCovariance(
            n_factors=config.get("n_factors"),
            clustering_method=config.get("clustering_method", "predefined"),
            shrinkage_method=config.get("shrinkage_method", "ledoit_wolf"),
            bias_correction=config.get("bias_correction", True),
        )

    @staticmethod
    def create_two_step(config: dict) -> TwoStepCovariance:
        """Create TwoStepCovariance from config."""
        return TwoStepCovariance(
            n_clusters=config.get("n_clusters"),
            linkage_method=config.get("linkage_method", "ward"),
            rmt_filter=config.get("rmt_filter", True),
        )

    @staticmethod
    def create_stochastic_block(config: dict) -> StochasticBlockCovariance:
        """Create StochasticBlockCovariance from config."""
        return StochasticBlockCovariance(
            allow_inter_block=config.get("allow_inter_block", True),
            alpha=config.get("alpha"),
            discover_blocks=config.get("discover_blocks", False),
            shrinkage_per_block=config.get("shrinkage_per_block", True),
        )
```

#### 4.2 Update StrategyFactory

**File:** `Strategy/Factory/StrategyFactory.py` (modify)

**Add Covariance Type Mapping:**
```python
COVARIANCE_REGISTRY = {
    "sample": CovarianceFactory.create_sample,
    "ledoit_wolf": CovarianceFactory.create_ledoit_wolf,
    "block_diagonal": CovarianceFactory.create_block_diagonal,  # NEW
    "two_step": CovarianceFactory.create_two_step,              # NEW
    "stochastic_block": CovarianceFactory.create_stochastic_block,  # NEW
}
```

#### 4.3 Create YAML Templates

**File:** `config/strategies/sector_rotation_block_diagonal.yaml`

```yaml
name: "Sector Rotation - Block Diagonal"
description: "Mean reversion strategy with block-diagonal covariance"

signals:
  - type: "mean_reversion"
    lookback: 20
    z_score_threshold: 2.0

risk:
  covariance:
    type: "block_diagonal"
    n_factors: 5
    clustering_method: "predefined"
    shrinkage_method: "ledoit_wolf"
    bias_correction: true

optimizer:
  type: "mean_variance"
  risk_aversion: 1.0

constraints:
  max_weight: 0.10
  min_weight: -0.10
```

**File:** `config/strategies/sector_rotation_two_step.yaml`

```yaml
name: "Sector Rotation - Two Step"
description: "Carry strategy with hierarchical clustering + RMT"

signals:
  - type: "carry"
    lookback: 60

risk:
  covariance:
    type: "two_step"
    n_clusters: 10
    linkage_method: "ward"
    rmt_filter: true

optimizer:
  type: "mean_variance"
  risk_aversion: 1.0
```

**File:** `config/strategies/macro_stochastic_block.yaml`

```yaml
name: "Global Macro - Stochastic Block"
description: "Multi-currency strategy with cross-sector correlations"

signals:
  - type: "momentum"
    lookback: 60
  - type: "carry"
    lookback: 20

signal_combiner:
  method: "weighted"
  weights: [0.6, 0.4]

risk:
  covariance:
    type: "stochastic_block"
    allow_inter_block: true
    alpha: 0.7  # 70% block, 30% full cov
    shrinkage_per_block: true

optimizer:
  type: "mean_variance"
  risk_aversion: 2.0

constraints:
  sector_max: 0.30  # Max 30% per currency
```

#### 4.4 Create Integration Tests

**File:** `tests/integration/test_sector_covariance_factory.py`

```python
def test_create_block_diagonal_from_yaml():
    """Test creating BlockDiagonalCovariance from YAML."""
    strategy = StrategyFactory.from_yaml("sector_rotation_block_diagonal.yaml")
    assert isinstance(strategy.risk_model, BlockDiagonalCovariance)

def test_create_two_step_from_yaml():
    """Test creating TwoStepCovariance from YAML."""
    strategy = StrategyFactory.from_yaml("sector_rotation_two_step.yaml")
    assert isinstance(strategy.risk_model, TwoStepCovariance)

def test_create_stochastic_block_from_yaml():
    """Test creating StochasticBlockCovariance from YAML."""
    strategy = StrategyFactory.from_yaml("macro_stochastic_block.yaml")
    assert isinstance(strategy.risk_model, StochasticBlockCovariance)
```

**Success Criteria:**
- ✅ All 3 models creatable via YAML
- ✅ Parameters correctly parsed
- ✅ Integration tests passing

---

### Task 5: End-to-End Backtest (30 minutes)

**Objective:** Demonstrate practical usage with complete backtest

#### 5.1 Create Example Backtest Script

**File:** `examples/sector_rotation_backtest.py`

```python
#!/usr/bin/env python3
"""
End-to-end sector rotation backtest using sector-based covariance.

Demonstrates:
1. Loading real market data
2. Creating strategy from YAML
3. Running backtest
4. Analyzing results
"""

from Strategy.Factory.StrategyFactory import StrategyFactory
from Backtest.Backtest import Backtest

def run_sector_rotation_backtest():
    # 1. Load strategy from YAML
    strategy = StrategyFactory.from_yaml(
        "config/strategies/sector_rotation_two_step.yaml"
    )

    # 2. Load data
    data = load_real_market_data("sp500", "2020-01-01", "2024-01-01")

    # 3. Run backtest
    backtest = Backtest(
        strategy=strategy,
        data=data,
        initial_capital=1000000,
    )
    results = backtest.run()

    # 4. Analyze results
    print(f"Sharpe Ratio: {results.sharpe_ratio:.2f}")
    print(f"Total Return: {results.total_return:.2%}")
    print(f"Max Drawdown: {results.max_drawdown:.2%}")

    # 5. Generate tear sheet
    tear_sheet = results.generate_tear_sheet()
    tear_sheet.save("results/sector_rotation_tear_sheet.pdf")

if __name__ == "__main__":
    run_sector_rotation_backtest()
```

#### 5.2 Compare Against Baseline

**Baseline:** Sample covariance (no sector structure)

**Comparison Metrics:**
- Sharpe ratio improvement
- Drawdown reduction
- Turnover reduction
- Computational speedup

**Target:** Show at least one sector-based model outperforms baseline

---

### Task 6: Documentation Updates (30 minutes)

**Objective:** Update all documentation to reflect Phase 4 additions

#### 6.1 Update Main README

**File:** `README.md` (if exists) or `docs/README.md`

**Add Section:**
```markdown
## Sector-Based Covariance Estimation

Three state-of-the-art sector-based covariance models:

- **BlockDiagonalCovariance** - Factor model with block-diagonal residuals
- **TwoStepCovariance** - Best empirical performance (García-Medina 2024)
- **StochasticBlockCovariance** - Critical for macro (cross-currency effects)

See [SECTOR_COVARIANCE_GUIDE.md](docs/SECTOR_COVARIANCE_GUIDE.md) for details.

### Quick Start

```yaml
# config/strategy.yaml
risk:
  covariance:
    type: "two_step"
    n_clusters: 10
    rmt_filter: true
```

See [examples/sector_rotation_backtest.py](examples/sector_rotation_backtest.py) for complete example.
```

#### 6.2 Update SECTOR_COVARIANCE_GUIDE.md

**Add Section:** "Real Data Validation Results"

**Contents:**
- Performance on S&P 500 (2020-2024)
- Comparison to sample covariance baseline
- Comparison to paper results
- Recommendations for practitioners

#### 6.3 Create Phase 4 Completion Summary

**File:** `docs/PHASE_4_COMPLETION_SUMMARY.md`

**Contents:**
- What was accomplished
- Test results (all passing)
- Performance metrics on real data
- Integration with strategy factory
- Examples created
- Next steps (if any)

---

## Success Criteria - Phase 4

### Validation ✅
- [ ] All 3 models run on real S&P 500 (or equivalent) data
- [ ] Covariance matrices positive definite and well-conditioned
- [ ] Performance metrics reasonable (Sharpe > 0.5)

### Comparison ✅
- [ ] Out-of-sample backtest completed (train/test split)
- [ ] All 3 models compared on same data
- [ ] At least one model outperforms sample covariance baseline
- [ ] Results documented in markdown report

### Integration ✅
- [ ] CovarianceFactory extended with 3 new methods
- [ ] StrategyFactory recognizes new covariance types
- [ ] 3 YAML templates created and tested
- [ ] Integration tests passing (10+ new tests)

### Documentation ✅
- [ ] REAL_DATA_VALIDATION_REPORT.md created
- [ ] SECTOR_COVARIANCE_GUIDE.md updated
- [ ] End-to-end example script working
- [ ] Phase 4 completion summary written

### Code Quality ✅
- [ ] All tests passing (117+ total)
- [ ] No regressions introduced
- [ ] Code follows existing patterns
- [ ] Git history clean (logical commits)

---

## Deliverables Summary

### New Files
1. `tests/integration/test_sector_covariance_real_data.py` - Real data loading and quality checks
2. `tests/integration/test_sector_covariance_validation.py` - Model validation tests
3. `tests/integration/test_sector_covariance_factory.py` - Factory integration tests
4. `config/strategies/sector_rotation_block_diagonal.yaml` - BlockDiagonal template
5. `config/strategies/sector_rotation_two_step.yaml` - TwoStep template
6. `config/strategies/macro_stochastic_block.yaml` - StochasticBlock template
7. `examples/sector_rotation_backtest.py` - End-to-end backtest example
8. `docs/REAL_DATA_VALIDATION_REPORT.md` - Validation results
9. `docs/PHASE_4_COMPLETION_SUMMARY.md` - Phase 4 summary

### Modified Files
1. `Risk/Factory/CovarianceFactory.py` - Add 3 creation methods
2. `Strategy/Factory/StrategyFactory.py` - Register new covariance types
3. `docs/SECTOR_COVARIANCE_GUIDE.md` - Add real data validation section
4. `docs/CLAUDE.md` - Update with Phase 4 completion (if needed)

### Documentation Files
- Total: ~600 lines of new documentation
- Comprehensive validation report
- Updated usage guide
- Phase 4 completion summary

---

## Estimated Timeline

| Task | Duration | Dependencies |
|------|----------|-------------|
| 1. Data Acquisition | 30 min | None |
| 2. Model Validation | 45 min | Task 1 |
| 3. Performance Comparison | 45 min | Task 2 |
| 4. Factory Integration | 60 min | Task 2 |
| 5. End-to-End Backtest | 30 min | Task 4 |
| 6. Documentation | 30 min | Tasks 3, 5 |
| **Total** | **3.5 hours** | |

**Buffer:** Add 30 minutes for debugging/unexpected issues
**Final Estimate:** 4 hours total

---

## Testing Strategy

### Unit Tests
- Real data loading functions (5 tests)
- Sector mapping utilities (3 tests)
- Factory creation methods (9 tests)

### Integration Tests
- Model validation on real data (9 tests)
- Strategy creation from YAML (9 tests)
- End-to-end backtest (3 tests)

### Total New Tests: ~30 tests

**Target:** All 137 tests passing (107 existing + 30 new)

---

## Risk Mitigation

### Potential Issues

1. **Data Availability**
   - **Risk:** Real market data not available
   - **Mitigation:** Use yfinance as fallback, or smaller universe (Dow 30)

2. **Performance Below Papers**
   - **Risk:** Cannot replicate paper results
   - **Mitigation:** Document differences (data period, universe, implementation details)

3. **Integration Complexity**
   - **Risk:** Strategy factory integration breaks existing functionality
   - **Mitigation:** Extensive integration tests, maintain backward compatibility

4. **Computation Time**
   - **Risk:** Real data backtests too slow
   - **Mitigation:** Use smaller universe initially, profile and optimize

---

## Agent Initialization Prompt

```
You are continuing the ARBS project development. Phase 3 (abstract base class and documentation) is complete and merged.

Your task is to complete Phase 4: Real Data Validation & Strategy Integration.

**Phase 4 Document:** /home/user/ARBS/docs/PHASE_4_PLAN.md

**What Phase 3 Accomplished:**
- Created SectorBasedCovarianceEstimator abstract base class
- Refactored BlockDiagonalCovariance, TwoStepCovariance, StochasticBlockCovariance
- Eliminated 137 lines of duplicate code
- All 107 tests passing
- Comprehensive documentation and examples

**Your Phase 4 Objectives:**
1. Validate all 3 sector-based covariance models on real S&P 500 data
2. Compare performance metrics (Sharpe, HHI, leverage) on real data
3. Integrate models into StrategyFactory with YAML support
4. Create 3 YAML strategy templates
5. Build end-to-end backtest example
6. Document validation results

**Start by:**
1. Reading /home/user/ARBS/docs/PHASE_4_PLAN.md completely
2. Following Task 1: Data Acquisition & Preparation
3. Use TDD approach: write tests first, then implement
4. Commit frequently with descriptive messages
5. Push to remote after each major milestone

**Success Criteria:**
- All 137+ tests passing (107 existing + 30 new)
- Real data validation report completed
- 3 YAML templates working
- End-to-end backtest script functional

**Estimated Duration:** 3-4 hours

**Branch:** Create new branch: claude/phase-4-validation-[YOUR_SESSION_ID]

**Key Documents:**
- Phase 4 Plan: /home/user/ARBS/docs/PHASE_4_PLAN.md
- Phase 3 Summary: /home/user/ARBS/docs/PHASE_3_COMPLETION_SUMMARY.md
- Usage Guide: /home/user/ARBS/docs/SECTOR_COVARIANCE_GUIDE.md

Begin by reading PHASE_4_PLAN.md and confirming you understand all 6 tasks before starting implementation.
```

---

## References

### Phase 3 Documents
- [Phase 3 Completion Summary](/home/user/ARBS/docs/PHASE_3_COMPLETION_SUMMARY.md)
- [Sector Covariance Guide](/home/user/ARBS/docs/SECTOR_COVARIANCE_GUIDE.md)
- [Common Patterns Analysis](/home/user/ARBS/docs/phase3_common_patterns_analysis.md)

### Papers
1. Žignić et al. (2024) - BlockDiagonalCovariance
2. García-Medina et al. (2024) - TwoStepCovariance
3. Chen et al. (2025) - StochasticBlockCovariance

### Existing Code
- `Risk/Covariance/SectorBased/` - All sector-based models
- `Strategy/Factory/StrategyFactory.py` - Strategy creation system
- `Risk/Factory/CovarianceFactory.py` - Covariance creation system
- `examples/sector_covariance_comparison.py` - Synthetic data comparison

---

## Notes for Future Agent

**Important Context:**
- All 3 models use long format data: `[ticker, date, return, sector]`
- TwoStep doesn't require `sector` column (discovers via clustering)
- StochasticBlock can use predefined sectors OR discover them
- BlockDiagonal can cluster on residuals (unique feature)

**Common Pitfalls:**
- Don't forget to handle missing data
- Ensure dates align across all tickers
- Watch out for survivorship bias in real data
- Test on small universe first before scaling to S&P 500

**Testing Philosophy:**
- Write tests FIRST (TDD approach)
- Test on real data, not just synthetic
- Compare against baseline (sample covariance)
- Validate against paper results where possible

**Git Workflow:**
- Create new branch: `claude/phase-4-validation-[SESSION_ID]`
- Commit after each task completion
- Push to remote immediately after commit
- Create PR when all tasks complete

Good luck! 🚀
