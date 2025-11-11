# Pandas → Polars Migration Progress

**Total Files**: 135 Python files
**Strategy**: Migrate in batches of ~10 files, commit after each batch
**Started**: 2025-11-11

---

## Progress Summary

- ✅ **BATCH 1**: Base classes + tests (9 files) - **COMPLETED**
- ⏳ **BATCH 2**: Core adapters + signals + tests (10 files) - IN PROGRESS
- ⬜ **BATCH 3**: AlphaGenerator + risk models + tests (10 files)
- ⬜ **BATCH 4**: More risk + volatility + tests (10 files)
- ⬜ **BATCH 5**: Portfolio + backtest + analysis + tests (10 files)
- ⬜ **BATCH 6**: Signal components + examples (10 files)
- ⬜ **BATCH 7**: Utilities + caching (10 files)
- ⬜ **BATCH 8**: RVUtils (10 files)
- ⬜ **BATCH 9**: Query backends (10 files)
- ⬜ **BATCH 10**: MDP Fixed Rate Bonds (10 files)
- ⬜ **BATCH 11**: MDP IRSwaps RL Basic (10 files)
- ⬜ **BATCH 12**: MDP IRSwaps SDR INTRADAY (10 files)
- ⬜ **BATCH 13**: MDP IRSwaps SDR INTRADAY Final (2 files)

**Files Migrated**: 9 / 135 (6.7%)

---

## Batch Details

### ✅ BATCH 1: Base Classes + Tests (COMPLETED)

**Commit**: `2943fd4` - "refactor: Migrate BATCH 1 base classes from pandas to polars"

**Files Migrated (9)**:
1. Adapter/Base/BaseAdapter.py
2. Risk/Base/BaseCovarianceEstimator.py
3. Signals/Base/BaseSignal.py
4. Backtest/Base/BaseBacktest.py
5. Optimizer/Base/BaseOptimizer.py
6. tests/unit/signals/test_base_signal.py
7. tests/unit/backtest/test_minimal_backtest.py
8. tests/unit/optimizer/test_mean_variance_optimizer.py
9. tests/unit/asset/test_grinold_kahn_portfolio.py

**Key Changes**:
- `import pandas as pd` → `import polars as pl`
- `pd.DataFrame` → `pl.DataFrame`
- `pd.Series([1,2], index=['a','b'])` → `pl.Series('name', [1,2])`
- `.dropna()` → `.drop_nulls()`
- `.values` → `.to_numpy()`
- `pd.date_range()` → manual date generation or `pl.datetime_range()`

**Note**: Asset/Base/Asset.py had no pandas dependencies, skipped

---

## Next Steps

1. Migrate BATCH 2: Core adapters + signals (10 files)
2. Run tests after each batch to catch issues early
3. Continue through all 13 batches
4. Update documentation
5. Run full test suite
6. Delete this file when 100% complete
