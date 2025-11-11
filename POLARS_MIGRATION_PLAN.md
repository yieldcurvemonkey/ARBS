# Pandas to Polars Migration Plan

**Generated**: 2025-11-11
**Total Files**: 84 files to migrate
**Strategy**: Orthogonal batches of 5, parallel execution, commit after each batch

## Batch Execution Strategy

Each batch contains 5 orthogonal files (no dependencies between them within the batch).
Execute batches in parallel using subagents, then commit and push after each batch completes.

---

## WAVE 1: Core Library (Critical Path)

### Batch 1A - Core Components
- [ ] Analysis/TearSheet.py
- [ ] Asset/GrinoldKahnPortfolio.py
- [ ] BT/misc.py
- [ ] Caching/timeseries_cache.py
- [ ] Signals/AlphaGenerator.py

**Orthogonality**: Different modules, no cross-dependencies

---

## WAVE 2: Signal & Risk Infrastructure

### Batch 2A - Signal Components
- [ ] Signals/decomposable_signal.py
- [ ] Signals/signal_component.py
- [ ] Risk/Base/BaseCovarianceEstimator.py
- [ ] Risk/Covariance/CovarianceComparison.py
- [ ] Risk/Covariance/DiagonalCovariance.py

**Orthogonality**: Parallel signal and risk modules

### Batch 2B - Risk Estimators
- [ ] Risk/Covariance/IdentityCovariance.py
- [ ] Risk/Covariance/SampleCovariance.py
- [ ] Risk/Volatility/EWMAVolatility.py
- [ ] Risk/Volatility/VolatilityEstimator.py
- [ ] Risk/templates/external_risk_model_template.py

**Orthogonality**: Different covariance/volatility estimators

---

## WAVE 3: Tests

### Batch 3A - Risk Tests
- [ ] tests/Risk/test_risk_model_integration.py
- [ ] tests/risk/templates/test_risk_model_template.py
- [ ] tests/unit/risk/test_diagonal_covariance.py
- [ ] tests/Signals/test_decomposable_signal.py
- [ ] tests/Signals/test_signal_component.py

**Orthogonality**: Independent test files

### Batch 3B - Signal Tests
- [ ] tests/unit/signals/test_signal_combiner.py
- [ ] examples/custom_components_example.py
- [ ] examples/run_minimal_backtest.py
- [ ] examples/signal_decomposition_example.py
- [ ] examples/validate_dynamic_ic.py

**Orthogonality**: Tests and examples don't interfere

---

## WAVE 4: Utilities

### Batch 4A - RVUtils Part 1
- [ ] RVUtils/Interpolation/calibrate.py
- [ ] RVUtils/Interpolation/nss.py
- [ ] RVUtils/arbl_hedge_ratios.py
- [ ] RVUtils/general.py
- [ ] RVUtils/mean_reversion.py

**Orthogonality**: Independent utility functions

### Batch 4B - RVUtils Part 2
- [ ] RVUtils/plt_timeseries.py
- [ ] RVUtils/regression.py
- [ ] RVUtils/seasonality_utils.py
- [ ] RVUtils/ust_viz.py
- [ ] utils/misc.py

**Orthogonality**: Independent utility functions

### Batch 4C - Utils & Examples
- [ ] utils/ql_utils.py
- [ ] examples/yaml_strategy_example.py
- [ ] scripts/analyze_correlation_structure.py
- [ ] fomc_fly_backtest.py
- [ ] Query/IRSwaps/backends/rateslib/RLIRSwapCurve.py

**Orthogonality**: Separate scripts and query backends

---

## WAVE 5: Query Backends

### Batch 5A - Query Utils
- [ ] Query/IRSwaps/backends/quantlib/ql_curve_building_utils.py
- [ ] Query/IRSwaps/backends/quantlib/utils.py
- [ ] TB/FixedRateBondsTB.py
- [ ] TB/IRSwapsTB.py
- [ ] TB/TimeseriesBuilder.py

**Orthogonality**: Query and TB modules are independent

---

## WAVE 6: Data Providers (MDP) - Part 1

### Batch 6A - Fixed Rate Bonds MDP
- [ ] MDP/FixedRateBonds/FEDINVEST/FedInvestFetcher.py
- [ ] MDP/FixedRateBonds/PUBLICDOTCOM/PublicDotcomDataFetcher.py
- [ ] MDP/FixedRateBonds/WEBULL/WebullFintechFetcher.py
- [ ] MDP/FixedRateBonds/WSJ/WSJFetcher.py
- [ ] MDP/FixedRateBonds/reference_data_cache/cme_tcf.py

**Orthogonality**: Different data fetchers

### Batch 6B - Fixed Rate Bonds Continued
- [ ] MDP/FixedRateBonds/reference_data_cache/ust_reference_data.py
- [ ] MDP/FixedRateBonds/FixedRateBondsMDP.py
- [ ] TB/utils.py
- [ ] MDP/IRSwaps/fixings_cache/fixings_cache.py
- [ ] MDP/IRSwaps/GSQUANT/rl_basic/build.py

**Orthogonality**: Different subsystems

---

## WAVE 7: Data Providers (MDP) - Part 2 (CME)

### Batch 7A - CME QL Basic
- [ ] MDP/IRSwaps/CME_NY_EOD_LIVE/ql_basic/CMEFetcher.py
- [ ] MDP/IRSwaps/CME_NY_EOD_LIVE/ql_basic/CMEFetcherV2.py
- [ ] MDP/IRSwaps/CME_NY_EOD_LIVE/ql_basic/ErisFuturesFetcher.py
- [ ] MDP/IRSwaps/CME_NY_EOD_LIVE/ql_basic/FixingsFetcher.py
- [ ] MDP/IRSwaps/CME_NY_EOD_LIVE/ql_basic/FredFetcher.py

**Orthogonality**: Different fetcher implementations

### Batch 7B - CME RL Basic
- [ ] MDP/IRSwaps/CME_NY_EOD_LIVE/rl_basic/CMEFetcher.py
- [ ] MDP/IRSwaps/CME_NY_EOD_LIVE/rl_basic/CMEFetcherV2.py
- [ ] MDP/IRSwaps/CME_NY_EOD_LIVE/rl_basic/ErisFuturesFetcher.py
- [ ] MDP/IRSwaps/IRSwapsMDP.py
- [ ] MDP/IRSwaps/SDR_INTRADAY/rl_curve_utils/BarchartFetcher.py

**Orthogonality**: Different backend implementations

---

## WAVE 8: Data Providers (MDP) - Part 3 (SDR Curve Utils)

### Batch 8A - SDR Curve Utils Part 1
- [ ] MDP/IRSwaps/SDR_INTRADAY/rl_curve_utils/ErisFuturesFetcher.py
- [ ] MDP/IRSwaps/SDR_INTRADAY/rl_curve_utils/SDRDataBuilder.py
- [ ] MDP/IRSwaps/SDR_INTRADAY/rl_curve_utils/_RLCurveCache.py
- [ ] MDP/IRSwaps/SDR_INTRADAY/rl_curve_utils/rl_usd_curve_stir_builder.py
- [ ] MDP/IRSwaps/SDR_INTRADAY/rl_curve_utils/rl_usd_sofr_mt_builder.py

**Orthogonality**: Different builder utilities

### Batch 8B - SDR Curve Utils Part 2
- [ ] MDP/IRSwaps/SDR_INTRADAY/rl_curve_utils/rl_usd_sofr_mt_builder_parallel.py
- [ ] MDP/IRSwaps/SDR_INTRADAY/rl_curve_utils/stir_curve_building_utils.py
- [ ] MDP/IRSwaps/SDR_INTRADAY/rl_curve_utils/tos.py
- [ ] MDP/IRSwaps/SDR_INTRADAY/rl_usd_ois_stir_misc/rl_usd_ois_stir_misc.py
- [ ] MDP/IRSwaps/SDR_INTRADAY/rl_usd_ois_stir_q12x12/rl_usd_ois_stir_q12x12.py

**Orthogonality**: Different curve builders

---

## WAVE 9: Data Providers (MDP) - Part 4 (SDR Products)

### Batch 9A - OIS STIR Products
- [ ] MDP/IRSwaps/SDR_INTRADAY/rl_usd_ois_stir_q12x9/rl_usd_ois_stir_q12x9.py
- [ ] MDP/IRSwaps/SDR_INTRADAY/rl_usd_sofr_mt_misc/rl_usd_sofr_mt_misc.py
- [ ] MDP/IRSwaps/SDR_INTRADAY/rl_usd_sofr_mt_q12/rl_usd_sofr_mt_q12.py
- [ ] MDP/IRSwaps/SDR_INTRADAY/rl_usd_sofr_mt_q16/rl_usd_sofr_mt_q16.py
- [ ] MDP/IRSwaps/SDR_INTRADAY/rl_usd_sofr_mtv2_q12x11/rl_usd_sofr_mtv2_q12x11.py

**Orthogonality**: Different product configurations

### Batch 9B - SOFR STIR Products
- [ ] MDP/IRSwaps/SDR_INTRADAY/rl_usd_sofr_stir_misc/rl_usd_sofr_stir_misc.py
- [ ] MDP/IRSwaps/SDR_INTRADAY/rl_usd_sofr_stir_q12x12/rl_usd_sofr_stir_q12x12.py
- [ ] MDP/IRSwaps/SDR_INTRADAY/rl_usd_sofr_stir_q12x8/rl_usd_sofr_stir_q12x8.py
- [ ] MDP/IRSwaps/SDR_INTRADAY/rl_usd_sofr_stir_q13x10/rl_usd_sofr_stir_q13x10.py

**Orthogonality**: Different product configurations (only 4 files in final batch)

---

## Execution Plan

1. **Execute each batch in parallel** using 5 subagents
2. **After each batch completes**: Run tests, commit, and push
3. **Verify**: Run full test suite after each wave
4. **Total batches**: 17 batches across 9 waves

## Progress Tracking

- Wave 1: 0/1 batches complete
- Wave 2: 0/2 batches complete
- Wave 3: 0/2 batches complete
- Wave 4: 0/3 batches complete
- Wave 5: 0/1 batches complete
- Wave 6: 0/2 batches complete
- Wave 7: 0/2 batches complete
- Wave 8: 0/2 batches complete
- Wave 9: 0/2 batches complete

**Total Progress**: 0/17 batches (0%)

## Notes

- Each batch is orthogonal - files don't depend on each other within the batch
- Batches within a wave should be executed sequentially (2A before 2B)
- Waves should be executed sequentially to maintain dependency order
- Commit message format: `refactor: Migrate [batch name] from pandas to polars`
