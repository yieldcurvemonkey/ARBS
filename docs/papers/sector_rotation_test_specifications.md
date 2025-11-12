# Sector Rotation Model - Test Specifications
## Unit Test Design for TDD Implementation

**Purpose**: Define comprehensive test suite BEFORE implementation begins (TDD)
**Source**: Yang & Shi (2023) sector rotation paper
**Date**: 2025-11-11

---

## Test Philosophy

Following ARBS TDD principles:
1. **Write tests FIRST** - Define expected behavior before implementation
2. **Business perspective** - Tests validate investment logic, not just code correctness
3. **Comprehensive coverage** - Every component independently tested
4. **Integration validation** - End-to-end pipeline tests

---

## Test Organization

```
tests/unit/signals/sector_rotation/
├── test_momentum_factor.py          # MOM_7M construction and returns
├── test_reversion_factor.py         # REV_30D construction and returns
├── test_fundamental_factors.py      # Fundamental data processing
├── test_cross_sectional_neutral.py  # Factor neutralization
├── test_sector_signals.py           # Signal generation from factors
└── test_sector_portfolio.py         # Portfolio construction rules

tests/integration/
└── test_sector_rotation_pipeline.py # End-to-end backtest
```

---

## 1. Momentum Factor Tests

### File: `tests/unit/signals/sector_rotation/test_momentum_factor.py`

```python
"""
Test MOM_7M momentum factor construction and validation.
"""

class TestMomentumFactorConstruction:
    """Test mathematical correctness of momentum factor."""

    def test_mom_7m_calculation_formula(self):
        """
        Test MOM_7M = sum(7M returns) - sum(recent 10% returns).

        Setup:
            - 7 months = 147 trading days (21 days/month)
            - Exclude recent 10% = 14.7 ≈ 15 trading days
            - Mock daily returns: [0.01] * 132 + [0.02] * 15

        Expected:
            MOM_7M = (132 * 0.01) - (15 * 0.02) = 1.32 - 0.30 = 1.02

        Assert:
            abs(calculated_mom - 1.02) < 1e-6
        """
        pass

    def test_mom_lookback_periods(self):
        """
        Test all momentum lookback periods (1M-12M) calculate correctly.

        Setup:
            - Generate 12 months of mock daily returns
            - Calculate MOM_1M through MOM_12M

        Assert:
            - Each factor uses correct lookback window
            - Each factor excludes correct recent period (10%)
            - Longer lookbacks include more history
        """
        pass

    def test_mom_handles_missing_data(self):
        """
        Test momentum factor handles missing/NaN returns gracefully.

        Setup:
            - Daily returns with NaN values scattered

        Assert:
            - Factor calculation skips NaN days
            - Or raises clear error with helpful message
        """
        pass

    def test_mom_cross_sectional_calculation(self):
        """
        Test momentum calculated for all 11 sectors simultaneously.

        Setup:
            - 11 sector price series (different trends)

        Assert:
            - Returns 11 momentum values
            - Sectors with stronger trends have higher MOM values
            - Independent calculation per sector
        """
        pass


class TestMomentumSignalGeneration:
    """Test signal generation from momentum factors."""

    def test_mom_ranking_order(self):
        """
        Test sectors ranked correctly by momentum.

        Setup:
            - MOM values: [0.15, -0.05, 0.30, ..., -0.20]

        Assert:
            - Highest MOM gets rank 1
            - Lowest MOM gets rank 11
            - Ranking is monotonic
        """
        pass

    def test_mom_long_short_signals(self):
        """
        Test long/short signals generated from momentum ranks.

        Setup:
            - 11 ranked sectors

        Assert:
            - Top 2 sectors get positive signals
            - Bottom 2 sectors get negative signals
            - Middle 7 sectors get zero signals
        """
        pass


class TestMomentumFactorReturns:
    """Test momentum factor achieves paper's performance benchmarks."""

    def test_mom_7m_historical_performance(self):
        """
        Test MOM_7M achieves reasonable returns (2017-2022 period).

        Setup:
            - Real S&P GICS sector index data (2017-2022)
            - Construct MOM_7M signals
            - Backtest: long top 2, short bottom 2, monthly rebal

        Expected (from paper):
            - Annual return: ~21% (target: >15%)
            - Sharpe ratio: ~0.62 (target: >0.4)

        Assert:
            - annual_return > 0.15  # 15% threshold
            - sharpe_ratio > 0.40   # 0.4 threshold

        Note: Exact replication may differ due to data source,
              but should be in same ballpark.
        """
        pass

    def test_mom_vs_benchmark(self):
        """
        Test momentum strategy outperforms equal-weighted sectors.

        Setup:
            - Momentum strategy returns
            - Equal-weighted sector index returns

        Assert:
            - mom_cumulative_return > ew_cumulative_return
            - mom_sharpe > ew_sharpe
        """
        pass


class TestMomentumEdgeCases:
    """Test momentum factor edge cases and robustness."""

    def test_mom_all_sectors_positive(self):
        """Test momentum when all sectors have positive returns."""
        pass

    def test_mom_all_sectors_negative(self):
        """Test momentum during market crash (all negative)."""
        pass

    def test_mom_single_outlier_sector(self):
        """Test momentum with one extreme outlier doesn't break ranking."""
        pass

    def test_mom_flat_market(self):
        """Test momentum when all sectors have ~zero returns."""
        pass
```

---

## 2. Reversion Factor Tests

### File: `tests/unit/signals/sector_rotation/test_reversion_factor.py`

```python
"""
Test REV_30D short-term reversion factor construction and validation.
"""

class TestReversionFactorConstruction:
    """Test mathematical correctness of reversion factor."""

    def test_rev_30d_calculation_formula(self):
        """
        Test REV_30D = -sum(past 30 days returns).

        Setup:
            - 30 days of returns: [0.01] * 15 + [-0.01] * 15
            - Sum = 15*0.01 + 15*(-0.01) = 0

        Expected:
            REV_30D = -0.0 = 0.0

        Assert:
            abs(calculated_rev - 0.0) < 1e-6
        """
        pass

    def test_rev_negative_cumulative_return(self):
        """
        Test reversion factor negates cumulative return correctly.

        Setup:
            - Strong uptrend: [0.02] * 30
            - Cumulative = 0.60

        Expected:
            REV_30D = -0.60 (reversion signal: bet against momentum)

        Assert:
            calculated_rev == -0.60
        """
        pass

    def test_rev_lookback_periods(self):
        """
        Test all reversion lookback periods (5D-55D) calculate correctly.

        Setup:
            - 60 days of mock returns
            - Calculate REV_5D, REV_10D, ..., REV_55D

        Assert:
            - Each uses correct lookback window
            - No exclusion period (unlike momentum)
            - Factors are nested (REV_10D includes REV_5D period)
        """
        pass


class TestReversionSignalGeneration:
    """Test signal generation from reversion factors."""

    def test_rev_contrarian_logic(self):
        """
        Test reversion produces contrarian signals.

        Setup:
            - Sector A: strong recent gains (+10%)
            - Sector B: strong recent losses (-10%)

        Expected:
            - REV_30D(A) = -0.10 (low, bearish signal)
            - REV_30D(B) = +0.10 (high, bullish signal)

        Assert:
            - Losers get positive reversion scores
            - Winners get negative reversion scores
        """
        pass

    def test_rev_long_short_signals(self):
        """
        Test long/short signals from reversion ranks.

        Setup:
            - REV factors for 11 sectors

        Assert:
            - Top 2 REV (recent losers) get long signals
            - Bottom 2 REV (recent winners) get short signals
        """
        pass


class TestReversionFactorReturns:
    """Test reversion factor achieves paper's performance benchmarks."""

    def test_rev_30d_historical_performance(self):
        """
        Test REV_30D achieves reasonable returns (2002-2022 period).

        Setup:
            - Real S&P GICS sector index data (2002-2022)
            - Construct REV_30D signals
            - Backtest: long top 2, short bottom 2, monthly rebal

        Expected (from paper):
            - Annual return: ~8.77% (target: >5%)
            - Sharpe ratio: ~0.87 (target: >0.6)

        Assert:
            - annual_return > 0.05  # 5% threshold
            - sharpe_ratio > 0.60   # 0.6 threshold
        """
        pass

    def test_rev_complements_momentum(self):
        """
        Test reversion and momentum are complementary (low correlation).

        Setup:
            - Calculate MOM_7M and REV_30D simultaneously

        Assert:
            - correlation(MOM_7M, REV_30D) < 0.3
            - Combining both improves Sharpe vs either alone
        """
        pass


class TestReversionEdgeCases:
    """Test reversion factor edge cases."""

    def test_rev_extreme_drawdown(self):
        """Test reversion during extreme drawdown (>20% decline)."""
        pass

    def test_rev_extreme_rally(self):
        """Test reversion during extreme rally (>20% gain)."""
        pass

    def test_rev_choppy_market(self):
        """Test reversion in high-volatility, range-bound market."""
        pass
```

---

## 3. Fundamental Factor Tests

### File: `tests/unit/signals/sector_rotation/test_fundamental_factors.py`

```python
"""
Test fundamental factor data processing and validation.
"""

class TestFundamentalDataIngestion:
    """Test fundamental data loading and validation."""

    def test_fundamental_data_schema(self):
        """
        Test fundamental data has correct schema.

        Expected Columns:
            - sector (str): GICS sector name
            - date (datetime): Quarter end date
            - PE, PB, EV_Sales, EV_EBIT, EV_EBITDA (float)
            - Dividend_Yield (float)
            - Gross_Margin, Operating_Margin, Profit_Margin (float)
            - ROA, ROE (float)

        Assert:
            - All columns present
            - Correct dtypes
            - No missing values in key fields
        """
        pass

    def test_fundamental_quarterly_frequency(self):
        """
        Test fundamental data is quarterly frequency.

        Assert:
            - Each sector has one row per quarter
            - Dates are quarter-end aligned
            - No duplicate sector-date combinations
        """
        pass

    def test_fundamental_sector_coverage(self):
        """
        Test all 11 GICS sectors have fundamental data.

        Assert:
            - 11 unique sectors in data
            - Sectors match GICS Level 1 standard
        """
        pass


class TestFundamentalFactorCalculations:
    """Test fundamental ratio calculations (if computed from raw data)."""

    def test_pe_ratio_calculation(self):
        """
        Test PE = Price / EPS.

        Setup:
            - Price = 100
            - EPS = 5

        Expected:
            PE = 20
        """
        pass

    def test_profit_margin_calculation(self):
        """
        Test Profit Margin = (Revenue - Expenses) / Revenue.

        Setup:
            - Revenue = 1000
            - Expenses = 800

        Expected:
            Profit Margin = 0.20 (20%)
        """
        pass

    def test_roe_calculation(self):
        """
        Test ROE = Net Income / Equity.

        Setup:
            - Net Income = 50
            - Equity = 500

        Expected:
            ROE = 0.10 (10%)
        """
        pass


class TestFundamentalEdgeCases:
    """Test fundamental factor edge cases."""

    def test_negative_earnings_pe(self):
        """Test PE ratio handling when earnings are negative."""
        pass

    def test_zero_denominator_ratios(self):
        """Test ratio handling when denominator is zero."""
        pass

    def test_extreme_outliers(self):
        """Test handling of extreme outlier values (e.g., PE > 100)."""
        pass
```

---

## 4. Cross-Sectional Neutralization Tests

### File: `tests/unit/signals/sector_rotation/test_cross_sectional_neutral.py`

```python
"""
Test cross-sectional factor neutralization (z-score normalization).
"""

class TestCrossSectionalNeutralization:
    """Test factor neutralization produces correct statistics."""

    def test_neutralization_formula(self):
        """
        Test X_neutral = (X - mean(X)) / std(X).

        Setup:
            - 11 sectors with factor values: [10, 12, 8, 15, 9, 11, 13, 7, 14, 10, 11]

        Expected:
            - Mean of neutralized = 0.0
            - Std of neutralized = 1.0

        Assert:
            abs(mean(X_neutral)) < 1e-6
            abs(std(X_neutral) - 1.0) < 1e-6
        """
        pass

    def test_neutralization_preserves_ranking(self):
        """
        Test neutralization preserves relative ranking.

        Setup:
            - Original: [5, 10, 15, 20]
            - Neutralized: [-1.34, -0.45, 0.45, 1.34]

        Assert:
            - rank(original) == rank(neutralized)
            - Highest value stays highest after neutralization
        """
        pass

    def test_neutralization_per_time_period(self):
        """
        Test neutralization applied separately per time period.

        Setup:
            - Q1: 11 sectors with factor values
            - Q2: Same 11 sectors with different values

        Assert:
            - Q1 neutralized has mean=0, std=1
            - Q2 neutralized has mean=0, std=1
            - Q1 and Q2 treated independently
        """
        pass

    def test_neutralization_all_fundamental_factors(self):
        """
        Test all 10 fundamental factors get neutralized.

        Setup:
            - DataFrame with 11 sectors × 10 factors

        Assert:
            - Each factor column has mean ≈ 0, std ≈ 1
        """
        pass


class TestNeutralizationEdgeCases:
    """Test neutralization edge cases."""

    def test_constant_factor_values(self):
        """
        Test neutralization when all sectors have same value.

        Setup:
            - All sectors: PE = 15.0

        Expected:
            - std = 0, can't divide by zero

        Assert:
            - Raises ValueError or returns NaN with warning
        """
        pass

    def test_single_outlier(self):
        """
        Test neutralization with one extreme outlier.

        Setup:
            - Values: [10, 11, 12, 11, 10, 11, 12, 11, 10, 11, 100]

        Assert:
            - Outlier gets extreme z-score (>3)
            - Other values get reasonable z-scores
        """
        pass

    def test_two_sector_minimum(self):
        """
        Test neutralization requires at least 2 sectors.

        Setup:
            - Only 1 sector value

        Assert:
            - Raises error (can't compute std from n=1)
        """
        pass
```

---

## 5. Sector Signal Tests

### File: `tests/unit/signals/sector_rotation/test_sector_signals.py`

```python
"""
Test sector rotation signal classes (BaseSignal subclasses).
"""

class TestSectorMomentumSignal:
    """Test SectorMomentumSignal class."""

    def test_signal_inheritance(self):
        """
        Test SectorMomentumSignal inherits from BaseSignal.

        Assert:
            - isinstance(signal, BaseSignal)
            - Has required methods: calculate(), get_positions()
        """
        pass

    def test_signal_calculate_returns_dataframe(self):
        """
        Test calculate() returns proper DataFrame.

        Expected Columns:
            - ticker (str): Sector ticker/name
            - date (datetime)
            - signal (float): Raw momentum score

        Assert:
            - Returns pl.DataFrame (Polars)
            - Correct columns and dtypes
        """
        pass

    def test_signal_uses_correct_lookback(self):
        """
        Test signal uses MOM_7M lookback by default.

        Assert:
            - signal.lookback_months == 7
            - signal.exclusion_pct == 0.10
        """
        pass

    def test_signal_configurable_parameters(self):
        """
        Test signal parameters are configurable.

        Setup:
            - Create signal with lookback_months=6, exclusion_pct=0.15

        Assert:
            - Signal uses custom parameters
            - Different config produces different signals
        """
        pass


class TestSectorReversionSignal:
    """Test SectorReversionSignal class."""

    def test_signal_inheritance(self):
        """Test SectorReversionSignal inherits from BaseSignal."""
        pass

    def test_signal_uses_correct_lookback(self):
        """
        Test signal uses REV_30D lookback by default.

        Assert:
            - signal.lookback_days == 30
        """
        pass

    def test_signal_negative_cumulative(self):
        """
        Test signal negates cumulative return correctly.

        Setup:
            - Sector with +10% 30-day return

        Expected:
            - Signal = -0.10
        """
        pass


class TestFundamentalSignal:
    """Test FundamentalSignal class (neural network predictor)."""

    def test_signal_requires_trained_model(self):
        """
        Test signal requires pre-trained model to initialize.

        Assert:
            - Raises error if model_path not provided
            - Loads model successfully if path valid
        """
        pass

    def test_signal_outputs_probabilities(self):
        """
        Test signal outputs probabilities in [0, 1].

        Setup:
            - 11 sectors with fundamental factors

        Assert:
            - All signal values in [0, 1]
            - Sum across sectors not necessarily 1 (not softmax)
        """
        pass

    def test_signal_uses_all_fundamental_factors(self):
        """
        Test signal requires all 10 fundamental factors as input.

        Setup:
            - Input with only 9 factors

        Assert:
            - Raises error about missing factors
        """
        pass


class TestSignalCombination:
    """Test combining multiple signals (momentum + reversion + fundamental)."""

    def test_signal_combiner_with_weights(self):
        """
        Test SignalCombiner with custom weights.

        Setup:
            - MOM signal, REV signal, FUND signal
            - Weights: [0.4, 0.3, 0.3]

        Assert:
            - Combined = 0.4*MOM + 0.3*REV + 0.3*FUND
        """
        pass

    def test_signal_combiner_equal_weighted(self):
        """
        Test SignalCombiner with equal weights (default).

        Assert:
            - Combined = mean(MOM, REV, FUND)
        """
        pass
```

---

## 6. Portfolio Construction Tests

### File: `tests/unit/signals/sector_rotation/test_sector_portfolio.py`

```python
"""
Test sector rotation portfolio construction rules.
"""

class TestLongShortPortfolioConstruction:
    """Test long/short portfolio from sector signals."""

    def test_long_top_3_short_bottom_3(self):
        """
        Test portfolio goes long top 3, short bottom 3 sectors.

        Setup:
            - 11 sectors ranked by signal

        Expected:
            - Ranks 1-3: positive weights
            - Ranks 4-8: zero weights
            - Ranks 9-11: negative weights

        Assert:
            sum(weights[0:3]) > 0
            all(weights[3:8] == 0)
            sum(weights[8:11]) < 0
        """
        pass

    def test_equal_weighting_within_buckets(self):
        """
        Test equal weighting within long and short buckets.

        Setup:
            - Long bucket: 3 sectors
            - Short bucket: 3 sectors

        Expected:
            - Each long position: +1/3
            - Each short position: -1/3

        Assert:
            weights[0] == weights[1] == weights[2] == 1/3
            weights[8] == weights[9] == weights[10] == -1/3
        """
        pass

    def test_dollar_neutrality(self):
        """
        Test portfolio is dollar-neutral (longs = shorts).

        Setup:
            - Any signal configuration

        Assert:
            abs(sum(weights)) < 1e-6
            sum(abs(weights)) == 2.0  # 1.0 long + 1.0 short
        """
        pass

    def test_portfolio_rebalancing(self):
        """
        Test portfolio rebalances monthly.

        Setup:
            - Signals at t=0, t=1 month, t=2 months

        Assert:
            - Weights updated at each month
            - Old positions closed, new positions opened
        """
        pass


class TestPortfolioConstraints:
    """Test portfolio constraints and limits."""

    def test_no_leverage_constraint(self):
        """
        Test portfolio doesn't exceed 100% long, 100% short.

        Assert:
            sum(positive_weights) <= 1.0
            sum(abs(negative_weights)) <= 1.0
        """
        pass

    def test_sector_concentration_limit(self):
        """
        Test optional sector concentration limit.

        Setup:
            - max_sector_weight = 0.5

        Assert:
            max(abs(weights)) <= 0.5
        """
        pass

    def test_minimum_position_size(self):
        """
        Test optional minimum position size filter.

        Setup:
            - min_position = 0.05

        Assert:
            - Positions either == 0 or abs(weight) >= 0.05
        """
        pass


class TestPortfolioEdgeCases:
    """Test portfolio construction edge cases."""

    def test_tied_signal_values(self):
        """
        Test portfolio handling when signals are tied.

        Setup:
            - 4 sectors with identical top signals

        Assert:
            - Clear tiebreaker rule (alphabetical, random, etc.)
            - Deterministic output
        """
        pass

    def test_all_positive_signals(self):
        """
        Test portfolio when all signals are positive.

        Assert:
            - Still goes short bottom 3 (relative ranking)
        """
        pass

    def test_signal_outliers(self):
        """
        Test portfolio with one extreme signal outlier.

        Assert:
            - Outlier gets position, but constrained by equal-weighting
        """
        pass
```

---

## 7. Integration Tests

### File: `tests/integration/test_sector_rotation_pipeline.py`

```python
"""
End-to-end integration tests for sector rotation strategy.
"""

class TestSectorRotationPipeline:
    """Test complete pipeline from data to portfolio returns."""

    def test_end_to_end_momentum_strategy(self):
        """
        Test complete momentum strategy (MOM_7M) pipeline.

        Steps:
            1. Load sector price data (2017-2022)
            2. Calculate MOM_7M factors
            3. Generate momentum signals
            4. Construct long/short portfolio
            5. Calculate returns
            6. Compute performance metrics

        Assert:
            - Pipeline runs without errors
            - Returns are calculated
            - Sharpe ratio > 0.4
        """
        pass

    def test_end_to_end_reversion_strategy(self):
        """
        Test complete reversion strategy (REV_30D) pipeline.

        Similar to momentum test, but with REV_30D.

        Assert:
            - Pipeline runs without errors
            - Sharpe ratio > 0.6
        """
        pass

    def test_end_to_end_fundamental_strategy(self):
        """
        Test complete fundamental strategy (neural network) pipeline.

        Steps:
            1. Load fundamental data (quarterly)
            2. Neutralize factors cross-sectionally
            3. Train/load neural network model
            4. Generate probability signals
            5. Construct long/short portfolio
            6. Calculate returns

        Assert:
            - Pipeline runs without errors
            - Model predictions in [0, 1]
            - Sharpe ratio > 1.0
        """
        pass

    def test_end_to_end_combined_strategy(self):
        """
        Test combined strategy (momentum + reversion + fundamental).

        Steps:
            1. Calculate all three signal types
            2. Combine signals with equal weights
            3. Construct portfolio
            4. Backtest

        Assert:
            - Combined Sharpe > individual Sharpes
            - Diversification benefit visible
        """
        pass


class TestBacktestValidation:
    """Test backtest produces valid results."""

    def test_backtest_returns_match_holdings(self):
        """
        Test portfolio returns match underlying holdings.

        Setup:
            - Portfolio with known holdings
            - Known sector returns

        Assert:
            portfolio_return == sum(weights * sector_returns)
        """
        pass

    def test_backtest_handles_rebalancing_costs(self):
        """
        Test backtest accounts for rebalancing (if implemented).

        Setup:
            - Portfolio with turnover
            - Transaction cost = 10 bps

        Assert:
            - Realized return < frictionless return
        """
        pass

    def test_backtest_handles_missing_data(self):
        """
        Test backtest handles missing sector data gracefully.

        Setup:
            - One sector has missing returns for a period

        Assert:
            - Skips that sector or uses last available data
            - Doesn't crash
        """
        pass


class TestPerformanceMetrics:
    """Test performance metric calculations."""

    def test_sharpe_ratio_calculation(self):
        """
        Test Sharpe = mean(returns) / std(returns) * sqrt(252).

        Setup:
            - Known daily returns series

        Expected:
            - Manual calculation matches computed Sharpe
        """
        pass

    def test_information_ratio_calculation(self):
        """
        Test IR = mean(active_returns) / std(active_returns).

        Setup:
            - Strategy returns
            - Benchmark returns

        Expected:
            - IR measures risk-adjusted outperformance
        """
        pass

    def test_maximum_drawdown(self):
        """
        Test max drawdown = max(peak - trough) / peak.

        Setup:
            - Returns with known drawdown period

        Expected:
            - Correctly identifies largest peak-to-trough decline
        """
        pass


class TestARBSArchitectureCompliance:
    """Test integration with existing ARBS components."""

    def test_uses_equity_query(self):
        """
        Test sector data loaded via EquityQuery/ETFQuery.

        Assert:
            - Queries are EquityQuery or ETFQuery instances
            - Inherit from BaseQuery
        """
        pass

    def test_uses_equity_adapter(self):
        """
        Test sector data converted via EquityAdapter.

        Assert:
            - EquityAdapter transforms Query -> DataFrame
            - Output has required columns (ticker, date, return, sector)
        """
        pass

    def test_uses_returns_calculator(self):
        """
        Test returns calculated via ReturnsCalculator.

        Assert:
            - ReturnsCalculator computes period returns
            - Returns-first design (not prices)
        """
        pass

    def test_signals_inherit_base_signal(self):
        """
        Test all sector signals inherit from BaseSignal.

        Assert:
            - SectorMomentumSignal(BaseSignal)
            - SectorReversionSignal(BaseSignal)
            - FundamentalSignal(BaseSignal)
        """
        pass

    def test_uses_alpha_generator(self):
        """
        Test signals scaled via AlphaGenerator.

        Assert:
            - Alphas = IC × Vol × Z (Grinold-Kahn)
        """
        pass

    def test_uses_covariance_estimator(self):
        """
        Test risk model uses CovarianceEstimator.

        Assert:
            - Covariance matrix estimated
            - Sector-aware structure (block diagonal)
        """
        pass

    def test_uses_mean_variance_optimizer(self):
        """
        Test portfolio optimized via MeanVarianceOptimizer.

        Assert:
            - Optimizer takes alphas + covariance
            - Produces optimal weights
        """
        pass

    def test_uses_portfolio_class(self):
        """
        Test portfolio constructed via Portfolio class.

        Assert:
            - Portfolio is composite asset
            - Tracks nested positions
        """
        pass

    def test_produces_tear_sheet(self):
        """
        Test backtest produces TearSheet analysis.

        Assert:
            - TearSheet shows IC, Sharpe, returns
            - Comprehensive performance analysis
        """
        pass
```

---

## 8. Performance Benchmark Tests

### File: `tests/integration/test_performance_benchmarks.py`

```python
"""
Test strategy performance meets paper's reported benchmarks.
"""

class TestPaperReplicationBenchmarks:
    """Test strategies replicate paper's performance (within tolerance)."""

    def test_mom_7m_benchmark(self):
        """
        Test MOM_7M replication (2017-2022).

        Paper Results:
            - Annual Return: 21.19%
            - Sharpe Ratio: 0.62

        Tolerance:
            - Annual Return: ±5% (16-26%)
            - Sharpe Ratio: ±0.15 (0.47-0.77)

        Assert:
            0.16 < annual_return < 0.26
            0.47 < sharpe_ratio < 0.77
        """
        pass

    def test_rev_30d_benchmark(self):
        """
        Test REV_30D replication (2002-2022).

        Paper Results:
            - Annual Return: 8.77%
            - Sharpe Ratio: 0.8735

        Tolerance:
            - Annual Return: ±3% (5.77-11.77%)
            - Sharpe Ratio: ±0.2 (0.67-1.07)

        Assert:
            0.0577 < annual_return < 0.1177
            0.67 < sharpe_ratio < 1.07
        """
        pass

    def test_fundamental_nn_benchmark(self):
        """
        Test neural network strategy replication (Sept 2020 - Sept 2021).

        Paper Results:
            - Sharpe Ratio: 2.21 (test set)

        Tolerance:
            - Sharpe Ratio: ±0.5 (1.71-2.71)

        Assert:
            1.71 < sharpe_ratio < 2.71

        Note: This is a short test period (1 year), so high variance expected.
        """
        pass


class TestLongTermRobustness:
    """Test strategy robustness over extended periods."""

    def test_strategy_survives_2008_crisis(self):
        """
        Test strategy during 2008 financial crisis.

        Setup:
            - Run strategy on 2007-2009 data

        Assert:
            - Strategy doesn't blow up (max DD < 50%)
            - Recovers within reasonable time
        """
        pass

    def test_strategy_survives_2020_covid(self):
        """
        Test strategy during COVID-19 crash (March 2020).

        Setup:
            - Run strategy on Q1 2020 data

        Assert:
            - Strategy handles extreme volatility
            - No catastrophic losses
        """
        pass

    def test_strategy_rolling_sharpe_stability(self):
        """
        Test rolling 12-month Sharpe ratio stability.

        Assert:
            - Rolling Sharpe mostly positive
            - Occasional negative periods expected, but not sustained
        """
        pass
```

---

## 9. Test Execution Order (TDD Workflow)

### Phase 1: Factor Construction
1. `test_momentum_factor.py` - Test MOM_7M construction
2. `test_reversion_factor.py` - Test REV_30D construction
3. `test_fundamental_factors.py` - Test fundamental data processing
4. `test_cross_sectional_neutral.py` - Test neutralization

### Phase 2: Signal Generation
5. `test_sector_signals.py` - Test signal classes (BaseSignal subclasses)

### Phase 3: Portfolio Construction
6. `test_sector_portfolio.py` - Test portfolio rules and constraints

### Phase 4: Integration
7. `test_sector_rotation_pipeline.py` - Test end-to-end pipeline
8. `test_performance_benchmarks.py` - Test replication of paper results

### Phase 5: Production Readiness
9. Edge case tests (all edge case methods)
10. Stress tests (crisis periods, extreme scenarios)
11. Performance tests (speed, memory usage)

---

## 10. Test Data Requirements

### Mock Data Generators

Create fixture generators for testing:

```python
# conftest.py

@pytest.fixture
def mock_sector_prices():
    """Generate 11 sectors × 252 days of mock price data."""
    pass

@pytest.fixture
def mock_fundamental_data():
    """Generate 11 sectors × 20 quarters of mock fundamental ratios."""
    pass

@pytest.fixture
def mock_trained_nn_model():
    """Generate pre-trained neural network model for testing."""
    pass
```

### Real Data Requirements

For integration tests requiring real data:
- S&P 500 GICS Sector Index daily prices (2002-2022)
- Sector fundamental data quarterly (2017-2022 minimum)
- Source: Yahoo Finance (via YahooFinanceMDP) or Bloomberg

---

## 11. Success Criteria Summary

### Unit Test Success Criteria
- ✅ All factor construction formulas match paper
- ✅ Cross-sectional neutralization produces mean=0, std=1
- ✅ Signals produce correct rankings
- ✅ Portfolio construction follows long/short rules
- ✅ Dollar-neutrality maintained

### Integration Test Success Criteria
- ✅ End-to-end pipeline runs without errors
- ✅ MOM_7M achieves Sharpe > 0.4 (target: 0.62)
- ✅ REV_30D achieves Sharpe > 0.6 (target: 0.87)
- ✅ Fundamental NN achieves Sharpe > 1.5 (target: 2.21)
- ✅ Combined strategy outperforms individual components

### Architecture Compliance Success Criteria
- ✅ All components inherit from ARBS base classes
- ✅ Uses existing Query/Adapter/Returns/Signals/Alpha/Risk/Optimizer/Portfolio
- ✅ Extends architecture without modifying core abstractions
- ✅ 100% test coverage on new components

---

**END OF TEST SPECIFICATIONS**

These tests define the success criteria BEFORE implementation begins. Following TDD:
1. Write these tests first (they will fail)
2. Implement components to make tests pass
3. Refactor while keeping tests green
4. Achieve 100% coverage

The tests validate both correctness (formulas match paper) and performance (Sharpe ratios meet benchmarks).
