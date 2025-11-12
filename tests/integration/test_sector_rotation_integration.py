"""
Integration tests for sector rotation strategy.

Tests the complete pipeline from returns → signals → portfolio → performance.
Validates that all components work together correctly.
"""

from datetime import date, timedelta
import numpy as np
import polars as pl


class TestSectorRotationIntegration:
    """Integration tests for complete sector rotation pipeline."""

    def test_momentum_signal_end_to_end(self):
        """Test momentum signal from returns data to z-scores."""
        from Signals.SectorRotation.SectorMomentumSignal import SectorMomentumSignal

        # Create returns data for 3 sectors (150 days to cover MOM_7M)
        dates = [date(2023, 1, 1) + timedelta(days=i) for i in range(150)]

        sectors_data = []
        for ticker, daily_return in [("XLK", 0.002), ("XLF", 0.0), ("XLE", -0.001)]:
            sectors_data.append(pl.DataFrame({
                "ticker": [ticker] * 150,
                "date": dates,
                "return": [daily_return] * 150
            }))

        # Create signal
        signal = SectorMomentumSignal(lookback_months=1, exclusion_pct=0.10)

        # Generate signals
        z_scores = signal.generate_batch(
            inst_data_list=sectors_data,
            market_data=None,
            as_of=dates[-1]
        )

        # Verify z-scores
        assert len(z_scores) == 3
        assert abs(np.mean(z_scores)) < 1e-6  # Mean = 0
        assert abs(np.std(z_scores, ddof=1) - 1.0) < 1e-6  # Std = 1
        assert z_scores[0] > z_scores[1] > z_scores[2]  # XLK > XLF > XLE

    def test_reversion_signal_end_to_end(self):
        """Test reversion signal from returns data to z-scores."""
        from Signals.SectorRotation.SectorReversionSignal import SectorReversionSignal

        # Create returns data for 3 sectors (30 days for REV_30D)
        dates = [date(2023, 1, 1) + timedelta(days=i) for i in range(30)]

        sectors_data = []
        # Winner, neutral, loser
        for ticker, daily_return in [("XLK", 0.02), ("XLF", 0.0), ("XLE", -0.01)]:
            sectors_data.append(pl.DataFrame({
                "ticker": [ticker] * 30,
                "date": dates,
                "return": [daily_return] * 30
            }))

        # Create signal
        signal = SectorReversionSignal(lookback_days=30)

        # Generate signals
        z_scores = signal.generate_batch(
            inst_data_list=sectors_data,
            market_data=None,
            as_of=dates[-1]
        )

        # Verify contrarian logic (loser gets highest z-score)
        assert len(z_scores) == 3
        assert z_scores[2] > z_scores[1] > z_scores[0]  # XLE > XLF > XLK

    def test_fundamental_pipeline(self):
        """Test fundamental data processing → neural network → signals."""
        from Signals.SectorRotation.FundamentalProcessor import FundamentalProcessor
        from Signals.SectorRotation.CrossSectionalNeutralizer import CrossSectionalNeutralizer
        from Signals.SectorRotation.FundamentalSignal import FundamentalSignal

        # 1. Create raw fundamental data
        target_date = date(2023, 3, 31)
        raw_fundamentals = pl.DataFrame({
            "ticker": ["XLK", "XLE", "XLF"],
            "date": [target_date] * 3,
            "pe_ratio": [25.0, 15.0, 12.0],
            "pb_ratio": [3.5, 1.2, 1.0],
            "ev_sales": [4.0, 2.0, 2.5],
            "ev_ebit": [18.0, 8.0, 10.0],
            "ev_ebitda": [15.0, 6.0, 8.0],
            "dividend_yield": [0.01, 0.04, 0.03],
            "gross_margin": [0.45, 0.20, 0.35],
            "operating_margin": [0.25, 0.10, 0.20],
            "profit_margin": [0.18, 0.08, 0.15],
            "roa": [0.12, 0.05, 0.08],
            "roe": [0.25, 0.10, 0.15],
        })

        # 2. Process fundamentals
        processor = FundamentalProcessor()
        processed_fundamentals = processor.process(raw_fundamentals)

        # 3. Neutralize (cross-sectional z-scores)
        neutralizer = CrossSectionalNeutralizer()
        neutralized_fundamentals = neutralizer.neutralize(
            processed_fundamentals,
            factor_columns=processor.factor_columns
        )

        # 4. Train neural network
        signal = FundamentalSignal(hidden_layers=(5, 5))

        # Create training data (simplified)
        X_train = np.array([[0.5] * 11, [-0.5] * 11] * 20)
        y_train = np.array([1, 0] * 20)
        signal.train(X_train, y_train)

        # 5. Generate signals
        sectors_data = []
        for ticker in ["XLK", "XLE", "XLF"]:
            sector_fundamentals = neutralized_fundamentals.filter(pl.col("ticker") == ticker)
            sectors_data.append(sector_fundamentals)

        probabilities = signal.generate_batch(
            inst_data_list=sectors_data,
            market_data=None,
            as_of=target_date
        )

        # Verify probabilities
        assert len(probabilities) == 3
        assert all(0 <= p <= 1 for p in probabilities)

    def test_portfolio_construction_from_signals(self):
        """Test portfolio construction from sector signals."""
        from Signals.SectorRotation.SectorLongShortPortfolio import SectorLongShortPortfolio

        # Create signals for 11 GICS sectors
        tickers = ["XLE", "XLB", "XLI", "XLY", "XLP", "XLV", "XLF", "XLK", "XLC", "XLU", "XLRE"]
        z_scores = np.array([-1.5, -1.0, -0.5, 0.0, 0.2, 0.4, 0.6, 0.8, 1.0, 1.2, 1.5])

        # Construct portfolio
        portfolio = SectorLongShortPortfolio(n_long=3, n_short=3)
        weights = portfolio.construct_weights(tickers, z_scores)

        # Verify portfolio properties
        assert len(weights) == 11
        assert abs(sum(weights.values())) < 1e-10  # Dollar-neutral

        # Long positions (top 3)
        assert weights["XLRE"] > 0
        assert weights["XLU"] > 0
        assert weights["XLC"] > 0

        # Short positions (bottom 3)
        assert weights["XLE"] < 0
        assert weights["XLB"] < 0
        assert weights["XLI"] < 0

    def test_complete_pipeline_momentum_only(self):
        """Test complete pipeline: returns → momentum → portfolio."""
        from Signals.SectorRotation.SectorMomentumSignal import SectorMomentumSignal
        from Signals.SectorRotation.SectorLongShortPortfolio import SectorLongShortPortfolio

        # 1. Create sector returns (5 sectors, 25 days for 1-month momentum)
        dates = [date(2023, 1, 1) + timedelta(days=i) for i in range(25)]
        tickers = ["A", "B", "C", "D", "E"]
        daily_returns = [0.02, 0.01, 0.0, -0.01, -0.02]  # Strong to weak

        sectors_data = []
        for ticker, ret in zip(tickers, daily_returns):
            sectors_data.append(pl.DataFrame({
                "ticker": [ticker] * 25,
                "date": dates,
                "return": [ret] * 25
            }))

        # 2. Generate momentum signals
        signal = SectorMomentumSignal(lookback_months=1, exclusion_pct=0.10)
        z_scores = signal.generate_batch(sectors_data, None, dates[-1])

        # 3. Construct portfolio
        portfolio = SectorLongShortPortfolio(n_long=2, n_short=2)
        weights = portfolio.construct_weights(tickers, z_scores)

        # 4. Verify complete pipeline
        assert weights["A"] > 0  # Best momentum → long
        assert weights["B"] > 0  # Second best → long
        assert weights["C"] == 0  # Middle → zero
        assert weights["D"] < 0  # Second worst → short
        assert weights["E"] < 0  # Worst momentum → short

        # Dollar-neutral
        assert abs(sum(weights.values())) < 1e-10

    def test_signal_combination(self):
        """Test combining multiple signals (momentum + reversion)."""
        from Signals.SectorRotation.SectorMomentumSignal import SectorMomentumSignal
        from Signals.SectorRotation.SectorReversionSignal import SectorReversionSignal
        from Signals.SectorRotation.SectorLongShortPortfolio import SectorLongShortPortfolio

        # Create returns data (150 days to cover both signals)
        dates = [date(2023, 1, 1) + timedelta(days=i) for i in range(150)]
        tickers = ["A", "B", "C"]

        sectors_data = []
        for ticker, ret in [("A", 0.001), ("B", 0.0), ("C", -0.001)]:
            sectors_data.append(pl.DataFrame({
                "ticker": [ticker] * 150,
                "date": dates,
                "return": [ret] * 150
            }))

        # Generate momentum signals
        mom_signal = SectorMomentumSignal(lookback_months=1)
        mom_z_scores = mom_signal.generate_batch(sectors_data, None, dates[-1])

        # Generate reversion signals
        rev_signal = SectorReversionSignal(lookback_days=30)
        rev_z_scores = rev_signal.generate_batch(sectors_data, None, dates[-1])

        # Combine signals (simple average)
        combined_z_scores = (mom_z_scores + rev_z_scores) / 2

        # Construct portfolio from combined signals
        portfolio = SectorLongShortPortfolio(n_long=1, n_short=1)
        weights = portfolio.construct_weights(tickers, combined_z_scores)

        # Verify combination
        assert len(weights) == 3
        assert abs(sum(weights.values())) < 1e-10

    def test_ic_tracking_across_signals(self):
        """Test IC tracking works for all signal types."""
        from Signals.SectorRotation.SectorMomentumSignal import SectorMomentumSignal
        from Signals.SectorRotation.SectorReversionSignal import SectorReversionSignal

        # Create sample data
        dates = [date(2023, 1, 1) + timedelta(days=i) for i in range(25)]
        sectors_data = []
        for ticker in ["A", "B"]:
            sectors_data.append(pl.DataFrame({
                "ticker": [ticker] * 25,
                "date": dates,
                "return": [0.01, -0.01][ord(ticker) - ord("A")] * np.ones(25)
            }))

        # Generate momentum signals
        mom_signal = SectorMomentumSignal(lookback_months=1)
        mom_z_scores = mom_signal.generate_batch(sectors_data, None, dates[-1])

        # Test IC calculation
        forecasts = pl.Series(mom_z_scores)
        actuals = pl.Series([0.05, -0.03])
        ic = mom_signal.calculate_ic(forecasts, actuals)

        # IC should be positive (momentum predicts returns)
        assert ic > 0

    def test_cross_sectional_neutralization_consistency(self):
        """Test that neutralization is consistent across different data."""
        from Signals.SectorRotation.CrossSectionalNeutralizer import CrossSectionalNeutralizer

        neutralizer = CrossSectionalNeutralizer()

        # Test data 1
        df1 = pl.DataFrame({
            "ticker": ["A", "B", "C"],
            "date": [date(2023, 1, 1)] * 3,
            "factor1": [10.0, 20.0, 30.0],
        })

        neutral1 = neutralizer.neutralize(df1, ["factor1"])
        z_scores1 = neutral1["factor1_neutral"].to_numpy()

        # Verify z-score properties
        assert abs(np.mean(z_scores1)) < 1e-6
        assert abs(np.std(z_scores1, ddof=1) - 1.0) < 1e-6

        # Test that ranking is preserved
        assert z_scores1[0] < z_scores1[1] < z_scores1[2]

    def test_portfolio_statistics(self):
        """Test portfolio statistics calculation."""
        from Signals.SectorRotation.SectorLongShortPortfolio import SectorLongShortPortfolio

        portfolio = SectorLongShortPortfolio(n_long=3, n_short=3, leverage=1.0)

        tickers = ["A", "B", "C", "D", "E", "F"]
        z_scores = np.array([2.0, 1.0, 0.5, -0.5, -1.0, -2.0])

        weights = portfolio.construct_weights(tickers, z_scores)
        stats = portfolio.get_portfolio_statistics(weights)

        # Verify statistics
        assert abs(stats["total_long"] - 1.0) < 1e-10  # 100% long
        assert abs(stats["total_short"] - 1.0) < 1e-10  # 100% short
        assert abs(stats["net_exposure"]) < 1e-10  # Dollar-neutral
        assert abs(stats["gross_exposure"] - 2.0) < 1e-10  # 200% gross
        assert stats["n_long"] == 3
        assert stats["n_short"] == 3


if __name__ == "__main__":
    # Run integration tests
    test = TestSectorRotationIntegration()

    print("Running Sector Rotation Integration Tests...")
    print("=" * 60)

    test.test_momentum_signal_end_to_end()
    print("✓ test_momentum_signal_end_to_end")

    test.test_reversion_signal_end_to_end()
    print("✓ test_reversion_signal_end_to_end")

    test.test_fundamental_pipeline()
    print("✓ test_fundamental_pipeline")

    test.test_portfolio_construction_from_signals()
    print("✓ test_portfolio_construction_from_signals")

    test.test_complete_pipeline_momentum_only()
    print("✓ test_complete_pipeline_momentum_only")

    test.test_signal_combination()
    print("✓ test_signal_combination")

    test.test_ic_tracking_across_signals()
    print("✓ test_ic_tracking_across_signals")

    test.test_cross_sectional_neutralization_consistency()
    print("✓ test_cross_sectional_neutralization_consistency")

    test.test_portfolio_statistics()
    print("✓ test_portfolio_statistics")

    print("=" * 60)
    print("✅ All integration tests passed!")
