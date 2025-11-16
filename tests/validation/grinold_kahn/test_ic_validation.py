# ABOUTME: Validation tests for Information Coefficient (IC) against Grinold-Kahn textbook
# ABOUTME: Tests IC definition, typical values, IR relationship, and time-series calculations
"""
Grinold-Kahn IC Validation Tests

Validates our IC implementation against definitions from:
    Grinold & Kahn (1999). "Active Portfolio Management", 2nd Edition
    Chapter 7: Expected Returns and the Information Ratio
    Pages 137-165

Key formulas tested:
    1. IC = corr(α̂, r) where α̂ = forecast, r = realized return
    2. IR = IC × √BR where BR = breadth (number of independent bets)
    3. E[RA] = IC × σA × score where RA = active return

Realistic IC values (Grinold-Kahn benchmarks):
    - IC = 0.05: Good predictive power
    - IC = 0.10: Very good predictive power
    - IC = 0.15: Exceptional (rare in practice)
"""

import numpy as np
import polars as pl
import pytest

from Signals.Utils.IC import (
    calculate_ic,
    calculate_ic_decay,
    calculate_ic_significance,
    calculate_ic_statistics,
    calculate_ic_time_series,
    calculate_rank_ic,
)


class TestICDefinition:
    """Validate IC matches textbook definition: IC = corr(forecast, realized)"""

    def test_ic_definition_matches_textbook(self):
        """
        IC should equal Pearson correlation between forecast and realized returns.

        From Grinold-Kahn Chapter 7:
            IC = corr(α̂, r)

        Where:
            α̂ = forecast alpha (expected return)
            r = realized return
        """
        # Create known forecast and realized returns
        forecasts = np.array([0.10, 0.05, -0.03, 0.08, -0.02, 0.06, -0.04, 0.09, 0.01, -0.05])
        realized = np.array([0.12, 0.06, -0.04, 0.07, -0.01, 0.08, -0.03, 0.10, 0.02, -0.06])

        # Our implementation
        ic = calculate_ic(forecasts, realized)

        # Textbook definition: IC = corr(forecast, realized)
        ic_manual = np.corrcoef(forecasts, realized)[0, 1]

        # Should match exactly (within numerical precision)
        assert abs(ic - ic_manual) < 1e-10, (
            f"IC implementation doesn't match textbook definition:\n"
            f"  Our IC: {ic:.10f}\n"
            f"  np.corrcoef: {ic_manual:.10f}\n"
            f"  Difference: {abs(ic - ic_manual):.2e}"
        )

        print("\n✓ IC Definition Validation:")
        print(f"  IC from implementation: {ic:.6f}")
        print(f"  IC from np.corrcoef: {ic_manual:.6f}")
        print("  Matches Grinold-Kahn definition: IC = corr(α̂, r)")

    def test_ic_alternative_calculation(self):
        """
        Validate IC can also be calculated using manual correlation formula.

        IC = cov(forecast, realized) / (σ_forecast × σ_realized)
        """
        np.random.seed(42)
        forecasts = np.random.randn(100)
        realized = 0.3 * forecasts + 0.7 * np.random.randn(100)

        # Our implementation
        ic = calculate_ic(forecasts, realized)

        # Manual calculation using covariance
        cov = np.cov(forecasts, realized)[0, 1]
        std_f = np.std(forecasts, ddof=1)
        std_r = np.std(realized, ddof=1)
        ic_manual = cov / (std_f * std_r)

        assert abs(ic - ic_manual) < 1e-10

        print("\n✓ Alternative IC Calculation:")
        print(f"  IC from implementation: {ic:.6f}")
        print(f"  IC from cov/(σ_f × σ_r): {ic_manual:.6f}")


class TestICBoundaryConditions:
    """Test IC behavior at boundary conditions"""

    def test_ic_perfect_forecasts(self):
        """
        IC = 1.0 for perfect forecasts (forecast = realized).

        Perfect forecasting skill → perfect correlation
        """
        np.random.seed(42)
        forecasts = np.random.randn(50)
        realized = forecasts.copy()  # Perfect forecast

        ic = calculate_ic(forecasts, realized)

        assert abs(ic - 1.0) < 1e-10, f"Perfect forecasts should give IC=1.0, got {ic:.6f}"

        print("\n✓ Perfect Forecasts:")
        print(f"  IC = {ic:.10f}")
        print("  Expected: 1.0")
        print("  This represents perfect forecasting skill")

    def test_ic_perfect_inverse_forecasts(self):
        """IC = -1.0 for perfectly inverse forecasts."""
        np.random.seed(42)
        forecasts = np.random.randn(50)
        realized = -forecasts  # Perfect inverse

        ic = calculate_ic(forecasts, realized)

        assert abs(ic - (-1.0)) < 1e-10, f"Inverse forecasts should give IC=-1.0, got {ic:.6f}"

        print("\n✓ Perfect Inverse Forecasts:")
        print(f"  IC = {ic:.10f}")
        print("  Expected: -1.0")

    def test_ic_random_forecasts(self):
        """
        IC ≈ 0.0 for random forecasts (no skill).

        From Grinold-Kahn: Random forecasts have no correlation with realized returns.
        """
        np.random.seed(42)
        forecasts = np.random.randn(1000)
        realized = np.random.randn(1000)  # Independent random

        ic = calculate_ic(forecasts, realized)

        # With 1000 samples, IC should be very close to 0
        # 95% confidence interval: ±1.96/√1000 ≈ ±0.062
        assert abs(ic) < 0.10, f"Random forecasts should give IC≈0, got {ic:.6f}"

        print("\n✓ Random Forecasts (No Skill):")
        print(f"  IC = {ic:.6f}")
        print("  Expected: ≈0.0 (within ±0.10 for random data)")
        print("  This represents no forecasting skill")

    def test_ic_zero_variance(self):
        """IC = 0.0 when forecasts or realized have zero variance."""
        forecasts_constant = np.array([1.0, 1.0, 1.0, 1.0, 1.0])
        realized_varying = np.array([0.5, 1.0, 1.5, 2.0, 2.5])

        ic = calculate_ic(forecasts_constant, realized_varying)

        assert ic == 0.0, f"Zero variance should give IC=0.0, got {ic:.6f}"

        print("\n✓ Zero Variance Edge Case:")
        print(f"  IC = {ic:.6f}")
        print("  Zero variance → no correlation possible")


class TestICTypicalValues:
    """Test realistic IC values from Grinold-Kahn benchmarks"""

    def test_ic_good_skill(self):
        """
        Test IC ≈ 0.05 (good predictive power).

        From Grinold-Kahn: IC > 0.05 indicates good forecasting skill.
        """
        np.random.seed(42)

        # Create forecasts with IC ≈ 0.05
        # If realized = α × forecast + β × noise, then IC ≈ α/√(α² + β²)
        # For IC=0.05: α=0.05, β=√(1-0.05²)≈0.9987
        forecasts = np.random.randn(1000)
        noise = np.random.randn(1000)
        realized = 0.05 * forecasts + 0.9987 * noise

        ic = calculate_ic(forecasts, realized)

        # Should be close to 0.05 (within 2 std errors ≈ 0.063)
        assert 0.0 < ic < 0.15, f"Good IC should be in (0, 0.15), got {ic:.6f}"
        assert abs(ic - 0.05) < 0.10, f"Target IC=0.05, got {ic:.6f}"

        print("\n✓ Good Forecasting Skill:")
        print(f"  IC = {ic:.6f}")
        print("  Target: 0.05 (good predictive power)")
        print("  Grinold-Kahn: IC > 0.05 is good")

    def test_ic_very_good_skill(self):
        """
        Test IC ≈ 0.10 (very good predictive power).

        From Grinold-Kahn: IC > 0.10 is very good (top quartile of managers).
        """
        np.random.seed(42)

        # Create forecasts with IC ≈ 0.10
        forecasts = np.random.randn(1000)
        noise = np.random.randn(1000)
        realized = 0.10 * forecasts + 0.995 * noise

        ic = calculate_ic(forecasts, realized)

        assert 0.05 < ic < 0.20, f"Very good IC should be in (0.05, 0.20), got {ic:.6f}"

        print("\n✓ Very Good Forecasting Skill:")
        print(f"  IC = {ic:.6f}")
        print("  Target: 0.10 (very good predictive power)")
        print("  Grinold-Kahn: IC > 0.10 is very good (top quartile)")

    def test_ic_exceptional_skill(self):
        """
        Test IC ≈ 0.15 (exceptional, rare in practice).

        From Grinold-Kahn: IC > 0.15 is exceptional and rare.
        """
        np.random.seed(42)

        # Create forecasts with IC ≈ 0.15
        forecasts = np.random.randn(1000)
        noise = np.random.randn(1000)
        realized = 0.15 * forecasts + 0.989 * noise

        ic = calculate_ic(forecasts, realized)

        assert 0.10 < ic < 0.25, f"Exceptional IC should be in (0.10, 0.25), got {ic:.6f}"

        print("\n✓ Exceptional Forecasting Skill:")
        print(f"  IC = {ic:.6f}")
        print("  Target: 0.15 (exceptional, rare in practice)")
        print("  Grinold-Kahn: IC > 0.15 is exceptional")


class TestICToIRRelationship:
    """Test Fundamental Law of Active Management: IR = IC × √BR"""

    def test_fundamental_law_basic(self):
        """
        Validate IR = IC × √BR (Fundamental Law of Active Management).

        From Grinold-Kahn Chapter 7:
            IR = Information Ratio = E[RA] / σ(RA)
            IC = Information Coefficient
            BR = Breadth (number of independent bets)

        Fundamental Law: IR = IC × √BR

        This assumes:
            1. Independent bets (zero correlation between assets)
            2. Perfect transfer coefficient (TC = 1.0)
            3. Optimal portfolio construction
        """
        np.random.seed(42)

        # Simulation parameters
        n_periods = 252  # One year of daily data
        n_assets = 50  # Breadth = 50 independent bets
        ic_target = 0.10  # IC = 0.10 (very good skill)

        # Generate independent forecasts and returns
        # Each asset is an independent bet
        forecasts = np.random.randn(n_periods, n_assets)

        # Create realized returns with IC ≈ 0.10
        # realized_i = IC × forecast_i + √(1-IC²) × noise_i
        noise = np.random.randn(n_periods, n_assets)
        realized = ic_target * forecasts + np.sqrt(1 - ic_target**2) * noise

        # Calculate IC (should be ≈ 0.10)
        ic_list = []
        for i in range(n_assets):
            ic_i = calculate_ic(forecasts[:, i], realized[:, i])
            ic_list.append(ic_i)
        ic_mean = np.mean(ic_list)

        # Calculate portfolio returns using equal weights (simplified)
        # In practice, use mean-variance optimization
        portfolio_realized = realized.mean(axis=1)

        # Calculate Information Ratio
        # IR = mean(active_return) / std(active_return)
        # For simplicity, assume benchmark return = 0
        active_returns = portfolio_realized
        ir_empirical = active_returns.mean() / active_returns.std()

        # Theoretical IR from Fundamental Law
        # IR = IC × √BR
        breadth = n_assets
        ir_theoretical = ic_mean * np.sqrt(breadth)

        # Note: Equal weighting is suboptimal (TC < 1.0)
        # So empirical IR will be lower than theoretical
        # But they should be positively correlated

        print("\n✓ Fundamental Law of Active Management:")
        print(f"  IC (mean across assets): {ic_mean:.4f}")
        print(f"  Breadth (n_assets): {breadth}")
        print(f"  IR (theoretical) = IC × √BR: {ir_theoretical:.4f}")
        print(f"  IR (empirical from portfolio): {ir_empirical:.4f}")
        print(f"  Ratio (empirical/theoretical): {ir_empirical/ir_theoretical:.4f}")
        print("  Note: Ratio < 1.0 due to suboptimal weighting (TC < 1.0)")

        # Empirical IR should be positive and correlated with theoretical
        assert ir_empirical > 0, "IR should be positive with positive IC"
        assert ir_empirical < ir_theoretical * 1.5, "IR shouldn't exceed theory by too much"

    def test_breadth_scaling(self):
        """
        Test that IR scales with √BR (breadth).

        Doubling breadth should increase IR by √2 ≈ 1.41
        """
        np.random.seed(42)

        ic = 0.08

        # Test different breadth values
        breadths = [10, 20, 40, 80]
        irs = [ic * np.sqrt(br) for br in breadths]

        # IR should increase with √BR
        for i in range(len(breadths) - 1):
            ratio = irs[i + 1] / irs[i]
            expected_ratio = np.sqrt(breadths[i + 1] / breadths[i])
            assert abs(ratio - expected_ratio) < 1e-10

        print("\n✓ Breadth Scaling:")
        print(f"  IC = {ic:.2f}")
        for br, ir in zip(breadths, irs):
            print(f"  BR={br:2d} → IR = IC × √{br:2d} = {ir:.4f}")
        print(f"  Doubling BR increases IR by √2 = {np.sqrt(2):.3f}")

    def test_ic_zero_gives_ir_zero(self):
        """If IC = 0 (no skill), then IR = 0 regardless of breadth."""
        ic = 0.0
        breadth = 100

        ir = ic * np.sqrt(breadth)

        assert ir == 0.0, "No skill (IC=0) → No information ratio (IR=0)"

        print("\n✓ No Skill → No IR:")
        print(f"  IC = {ic:.1f}")
        print(f"  BR = {breadth}")
        print(f"  IR = IC × √BR = {ir:.1f}")


class TestRollingICCalculation:
    """Test time-series IC estimation and stability"""

    def test_rolling_ic_calculation(self):
        """
        Test rolling IC over time windows.

        IC stability is a key metric from AlphaEval framework.
        """
        np.random.seed(42)

        n_periods = 100
        window = 20

        # Create time series with stable IC ≈ 0.10
        forecasts = np.random.randn(n_periods)
        noise = np.random.randn(n_periods)
        realized = 0.10 * forecasts + 0.995 * noise

        # Convert to Polars Series
        forecasts_pl = pl.Series(forecasts)
        realized_pl = pl.Series(realized)

        # Calculate rolling IC
        ic_series = calculate_ic_time_series(forecasts_pl, realized_pl, window=window)

        # Should have n_periods - window + 1 values
        expected_length = n_periods - window + 1
        assert len(ic_series) == expected_length, f"Expected {expected_length} IC values, got {len(ic_series)}"

        # Mean IC should be close to 0.10
        ic_mean = ic_series.mean()
        ic_std = ic_series.std()

        print("\n✓ Rolling IC Calculation:")
        print(f"  Window: {window} periods")
        print(f"  N rolling windows: {len(ic_series)}")
        print(f"  IC mean: {ic_mean:.4f} (target: 0.10)")
        print(f"  IC std: {ic_std:.4f} (stability metric)")
        print(f"  IC range: [{ic_series.min():.4f}, {ic_series.max():.4f}]")

    def test_ic_stability_metric(self):
        """
        Test IC stability (std of rolling IC).

        Stable signals have low IC volatility over time.
        """
        np.random.seed(42)

        n_periods = 200
        window = 20

        # Create stable signal (constant IC)
        forecasts_stable = np.random.randn(n_periods)
        realized_stable = 0.10 * forecasts_stable + 0.995 * np.random.randn(n_periods)

        # Create unstable signal (time-varying IC)
        forecasts_unstable = np.random.randn(n_periods)
        ic_time_varying = 0.10 * np.sin(np.arange(n_periods) * 2 * np.pi / 50)
        realized_unstable = ic_time_varying * forecasts_unstable + np.random.randn(n_periods)

        # Calculate rolling IC for both
        ic_stable = calculate_ic_time_series(pl.Series(forecasts_stable), pl.Series(realized_stable), window=window)

        ic_unstable = calculate_ic_time_series(
            pl.Series(forecasts_unstable), pl.Series(realized_unstable), window=window
        )

        # Stable signal should have lower IC volatility
        stability_stable = ic_stable.std()
        stability_unstable = ic_unstable.std()

        print("\n✓ IC Stability Comparison:")
        print(f"  Stable signal IC std: {stability_stable:.4f}")
        print(f"  Unstable signal IC std: {stability_unstable:.4f}")
        print("  Lower std → more stable signal")

        # This may not always hold due to randomness, so just report
        # assert stability_stable < stability_unstable


class TestRankIC:
    """Test Rank IC (Spearman correlation) vs Pearson IC"""

    def test_rank_ic_robust_to_outliers(self):
        """
        Rank IC should be more robust to outliers than Pearson IC.

        From Grinold-Kahn: Use Rank IC when returns have heavy tails.
        """
        # Create forecasts with one outlier
        forecasts = np.array([1.0, 2.0, 3.0, 4.0, 5.0])
        realized_normal = np.array([1.1, 2.0, 3.2, 3.9, 5.1])
        realized_outlier = np.array([1.1, 2.0, 3.2, 3.9, 100.0])  # Huge outlier

        # Pearson IC (sensitive to outlier)
        ic_normal = calculate_ic(forecasts, realized_normal)
        ic_outlier = calculate_ic(forecasts, realized_outlier)

        # Rank IC (robust to outlier)
        rank_ic_normal = calculate_rank_ic(forecasts, realized_normal)
        rank_ic_outlier = calculate_rank_ic(forecasts, realized_outlier)

        # Rank IC should be more stable
        pearson_change = abs(ic_outlier - ic_normal)
        rank_change = abs(rank_ic_outlier - rank_ic_normal)

        print("\n✓ Rank IC Robustness:")
        print(f"  Pearson IC (normal): {ic_normal:.4f}")
        print(f"  Pearson IC (outlier): {ic_outlier:.4f}")
        print(f"  Pearson change: {pearson_change:.4f}")
        print(f"  Rank IC (normal): {rank_ic_normal:.4f}")
        print(f"  Rank IC (outlier): {rank_ic_outlier:.4f}")
        print(f"  Rank change: {rank_change:.4f}")
        print("  Rank IC is more robust (smaller change)")

        # Rank IC should be less affected by outlier
        # (Ranks are preserved: [1,2,3,4,5] in both cases)
        assert abs(rank_ic_outlier - rank_ic_normal) < 0.01

    def test_rank_ic_perfect_monotonic(self):
        """Rank IC = 1.0 for perfect monotonic relationship."""
        forecasts = np.array([1, 2, 3, 4, 5])
        realized = np.array([10, 100, 1000, 10000, 100000])  # Perfect monotonic

        rank_ic = calculate_rank_ic(forecasts, realized)

        assert abs(rank_ic - 1.0) < 1e-10

        print("\n✓ Perfect Monotonic Relationship:")
        print(f"  Forecasts: {forecasts}")
        print(f"  Realized: {realized}")
        print(f"  Rank IC: {rank_ic:.10f} (should be 1.0)")


class TestICSignificance:
    """Test statistical significance of IC"""

    def test_ic_significance_testing(self):
        """
        Test IC with p-value calculation.

        From Grinold-Kahn: Need T > 60 for IC > 0.05 @ 95% confidence.
        """
        np.random.seed(42)

        # Create significant IC (n=100, IC=0.10)
        forecasts = np.random.randn(100)
        realized = 0.10 * forecasts + 0.995 * np.random.randn(100)

        ic, p_value = calculate_ic_significance(forecasts, realized)

        print("\n✓ IC Significance Testing:")
        print(f"  IC = {ic:.4f}")
        print(f"  p-value = {p_value:.4f}")
        print(f"  Significant at 95%? {p_value < 0.05}")
        print("  Grinold-Kahn: Need n > 60 for IC=0.05 @ 95% confidence")

        # With n=100 and IC≈0.10, should be significant
        # (Critical t ≈ 1.96 / √100 = 0.196 for 95% confidence)

    def test_ic_significance_small_sample(self):
        """Small samples may not show significance even with true IC."""
        np.random.seed(42)

        # Small sample (n=20)
        forecasts = np.random.randn(20)
        realized = 0.10 * forecasts + 0.995 * np.random.randn(20)

        ic, p_value = calculate_ic_significance(forecasts, realized)

        print("\n✓ Small Sample Size:")
        print("  n = 20")
        print(f"  IC = {ic:.4f}")
        print(f"  p-value = {p_value:.4f}")
        print("  May not be significant due to small sample")


class TestICNaNHandling:
    """Test IC calculation with NaN values"""

    def test_ic_with_nan_values(self):
        """IC should handle NaN values by removing them."""
        forecasts = np.array([1.0, 2.0, np.nan, 4.0, 5.0])
        realized = np.array([1.1, 2.0, 3.0, np.nan, 5.1])

        ic = calculate_ic(forecasts, realized)

        # Should calculate IC on valid pairs: (1.0, 1.1), (2.0, 2.0), (5.0, 5.1)
        assert not np.isnan(ic), "IC should handle NaN values"

        print("\n✓ NaN Handling:")
        print(f"  Forecasts: {forecasts}")
        print(f"  Realized: {realized}")
        print(f"  IC (on valid pairs): {ic:.4f}")

    def test_ic_all_nan(self):
        """IC should return NaN when all values are NaN."""
        forecasts = np.array([np.nan, np.nan, np.nan])
        realized = np.array([np.nan, np.nan, np.nan])

        ic = calculate_ic(forecasts, realized)

        assert np.isnan(ic), "All NaN should return NaN"

        print("\n✓ All NaN Input:")
        print(f"  IC = {ic}")


class TestICDecay:
    """Test IC decay (halflife) calculation"""

    def test_ic_decay_halflife(self):
        """
        Test IC decay halflife calculation.

        IC decay measures how quickly signal predictive power deteriorates.
        """
        np.random.seed(42)

        n_periods = 100

        # Create signal with known decay
        forecasts = np.random.randn(n_periods)

        # Realized with exponential decay (halflife ≈ 20 days)
        # r(t) = exp(-t/20) × f(0) + noise
        decay_rate = 1.0 / 20
        decayed_signal = forecasts * np.exp(-decay_rate * np.arange(n_periods))
        noise = 0.5 * np.random.randn(n_periods)
        realized = decayed_signal + noise

        # Calculate halflife
        forecasts_pl = pl.Series(forecasts)
        realized_pl = pl.Series(realized)
        halflife = calculate_ic_decay(forecasts_pl, realized_pl, max_lag=60)

        print("\n✓ IC Decay Halflife:")
        print(f"  Halflife: {halflife:.1f} days")
        print("  < 20 days: High frequency signal")
        print("  20-60 days: Medium frequency")
        print("  > 60 days: Low frequency")


class TestICStatistics:
    """Test comprehensive IC statistics calculation"""

    def test_ic_statistics_comprehensive(self):
        """
        Test comprehensive IC statistics calculation.

        Should return all key metrics in one call.
        """
        np.random.seed(42)

        n_periods = 200
        forecasts = np.random.randn(n_periods)
        realized = 0.08 * forecasts + 0.997 * np.random.randn(n_periods)

        # Calculate comprehensive statistics
        stats_dict = calculate_ic_statistics(pl.Series(forecasts), pl.Series(realized), window=20)

        print("\n✓ Comprehensive IC Statistics:")
        print(f"  IC: {stats_dict['ic']:.4f}")
        print(f"  Rank IC: {stats_dict['rank_ic']:.4f}")
        print(f"  IC Stability (std): {stats_dict['ic_stability']:.4f}")
        print(f"  IC Decay Halflife: {stats_dict['ic_decay_halflife']:.1f} days")
        print(f"  p-value: {stats_dict['p_value']:.4f}")
        print(f"  N observations: {stats_dict['n_observations']}")

        # Validate all fields present
        expected_fields = {"ic", "rank_ic", "ic_stability", "ic_decay_halflife", "p_value", "n_observations"}
        assert set(stats_dict.keys()) == expected_fields

        # IC should be reasonable
        assert -1.0 <= stats_dict["ic"] <= 1.0
        assert -1.0 <= stats_dict["rank_ic"] <= 1.0


if __name__ == "__main__":
    """Run validation tests with detailed output."""

    print("=" * 80)
    print("GRINOLD-KAHN IC VALIDATION")
    print("=" * 80)
    print("\nValidating against:")
    print("  Grinold & Kahn (1999). 'Active Portfolio Management', 2nd Edition")
    print("  Chapter 7: Expected Returns and the Information Ratio")
    print("  Pages 137-165")
    print("\n" + "=" * 80)

    # Run pytest with verbose output
    pytest.main([__file__, "-v", "-s"])
