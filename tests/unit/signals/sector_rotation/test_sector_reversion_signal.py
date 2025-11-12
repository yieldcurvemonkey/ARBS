"""
Test suite for SectorReversionSignal.

Tests the signal wrapper that integrates ReversionFactor with BaseSignal.
TDD approach: tests written BEFORE implementation.
"""

from datetime import date, timedelta
import numpy as np
import polars as pl


class TestSectorReversionSignal:
    """Test SectorReversionSignal integration with BaseSignal."""

    def test_signal_initialization(self):
        """Test signal can be initialized with proper defaults."""
        from Signals.SectorRotation.SectorReversionSignal import SectorReversionSignal

        signal = SectorReversionSignal()

        # Check BaseSignal attributes
        assert signal.name == "sector_reversion"
        assert signal.standardize is True  # Default standardization
        assert signal.track_history is True  # Default history tracking

        # Check ReversionFactor attributes
        assert signal.lookback_days == 30  # Default REV_30D

    def test_signal_custom_parameters(self):
        """Test signal initialization with custom parameters."""
        from Signals.SectorRotation.SectorReversionSignal import SectorReversionSignal

        signal = SectorReversionSignal(
            lookback_days=20,
            standardize=False
        )

        assert signal.name == "sector_reversion"
        assert signal.standardize is False
        assert signal.lookback_days == 20

    def test_calculate_raw_signal_single_sector_winner(self):
        """Test _calculate_raw_signal for winning sector (negative reversion signal)."""
        from Signals.SectorRotation.SectorReversionSignal import SectorReversionSignal

        signal = SectorReversionSignal(lookback_days=30)

        # Create sector with positive returns (recent winner)
        dates = [date(2023, 1, 1) + timedelta(days=i) for i in range(30)]
        inst_data = pl.DataFrame({
            "ticker": ["XLK"] * 30,
            "date": dates,
            "return": [0.02] * 30  # 2% daily return (strong uptrend)
        })

        # Calculate raw signal
        raw_signal = signal._calculate_raw_signal(
            inst_data=inst_data,
            market_data=None,
            as_of=dates[-1]
        )

        # Expected: -Σ(30 * 0.02) = -0.60
        # Contrarian: Winning sector gets NEGATIVE signal (bet on pullback)
        expected_reversion = -0.60
        assert abs(raw_signal - expected_reversion) < 1e-6

    def test_calculate_raw_signal_single_sector_loser(self):
        """Test _calculate_raw_signal for losing sector (positive reversion signal)."""
        from Signals.SectorRotation.SectorReversionSignal import SectorReversionSignal

        signal = SectorReversionSignal(lookback_days=30)

        # Create sector with negative returns (recent loser)
        dates = [date(2023, 1, 1) + timedelta(days=i) for i in range(30)]
        inst_data = pl.DataFrame({
            "ticker": ["XLE"] * 30,
            "date": dates,
            "return": [-0.01] * 30  # -1% daily return (downtrend)
        })

        raw_signal = signal._calculate_raw_signal(
            inst_data=inst_data,
            market_data=None,
            as_of=dates[-1]
        )

        # Expected: -Σ(30 * (-0.01)) = -(-0.30) = +0.30
        # Contrarian: Losing sector gets POSITIVE signal (bet on recovery)
        expected_reversion = 0.30
        assert abs(raw_signal - expected_reversion) < 1e-6

    def test_contrarian_logic_verification(self):
        """Test that contrarian logic is correct (winners negative, losers positive)."""
        from Signals.SectorRotation.SectorReversionSignal import SectorReversionSignal

        signal = SectorReversionSignal(lookback_days=10)

        # Winner sector (+10% cumulative)
        dates = [date(2023, 1, 1) + timedelta(days=i) for i in range(10)]
        winner_data = pl.DataFrame({
            "ticker": ["XLK"] * 10,
            "date": dates,
            "return": [0.01] * 10  # +10% cumulative
        })

        winner_signal = signal._calculate_raw_signal(
            winner_data, None, dates[-1]
        )

        # Loser sector (-5% cumulative)
        loser_data = pl.DataFrame({
            "ticker": ["XLE"] * 10,
            "date": dates,
            "return": [-0.005] * 10  # -5% cumulative
        })

        loser_signal = signal._calculate_raw_signal(
            loser_data, None, dates[-1]
        )

        # Contrarian: Winner should have NEGATIVE signal, loser should have POSITIVE
        assert winner_signal < 0  # Bet against winner
        assert loser_signal > 0   # Bet on loser recovery

        # Winner signal should be MORE negative than loser is positive
        assert abs(winner_signal) > abs(loser_signal)

    def test_generate_batch_multiple_sectors(self):
        """Test generate_batch returns signals for multiple sectors."""
        from Signals.SectorRotation.SectorReversionSignal import SectorReversionSignal

        signal = SectorReversionSignal(
            lookback_days=30,
            standardize=False  # Check raw values first
        )

        # Create data for 3 sectors with different behaviors
        dates = [date(2023, 1, 1) + timedelta(days=i) for i in range(30)]

        # Strong winner (XLK): +2% daily
        xlk_data = pl.DataFrame({
            "ticker": ["XLK"] * 30,
            "date": dates,
            "return": [0.02] * 30
        })

        # Flat (XLF): 0% daily
        xlf_data = pl.DataFrame({
            "ticker": ["XLF"] * 30,
            "date": dates,
            "return": [0.0] * 30
        })

        # Loser (XLE): -1% daily
        xle_data = pl.DataFrame({
            "ticker": ["XLE"] * 30,
            "date": dates,
            "return": [-0.01] * 30
        })

        # Generate batch signals
        raw_signals = signal.generate_batch(
            inst_data_list=[xlk_data, xlf_data, xle_data],
            market_data=None,
            as_of=dates[-1]
        )

        # Check raw values
        assert len(raw_signals) == 3

        # Contrarian ranking: Loser should have HIGHEST signal, winner should have LOWEST
        assert raw_signals[2] > raw_signals[1] > raw_signals[0]  # XLE > XLF > XLK

        # XLK (winner): -0.60
        # XLF (flat): 0.0
        # XLE (loser): +0.30
        assert abs(raw_signals[0] - (-0.60)) < 1e-6
        assert abs(raw_signals[1] - 0.0) < 1e-6
        assert abs(raw_signals[2] - 0.30) < 1e-6

    def test_generate_batch_with_standardization(self):
        """Test generate_batch applies z-score standardization."""
        from Signals.SectorRotation.SectorReversionSignal import SectorReversionSignal

        signal = SectorReversionSignal(
            lookback_days=30,
            standardize=True  # Enable standardization
        )

        # Create data for 3 sectors
        dates = [date(2023, 1, 1) + timedelta(days=i) for i in range(30)]

        xlk_data = pl.DataFrame({
            "ticker": ["XLK"] * 30,
            "date": dates,
            "return": [0.02] * 30
        })

        xlf_data = pl.DataFrame({
            "ticker": ["XLF"] * 30,
            "date": dates,
            "return": [0.0] * 30
        })

        xle_data = pl.DataFrame({
            "ticker": ["XLE"] * 30,
            "date": dates,
            "return": [-0.01] * 30
        })

        # Generate batch with standardization
        z_scores = signal.generate_batch(
            inst_data_list=[xlk_data, xlf_data, xle_data],
            market_data=None,
            as_of=dates[-1]
        )

        # Check z-score properties
        assert len(z_scores) == 3
        assert abs(np.mean(z_scores)) < 1e-6  # Mean ≈ 0
        assert abs(np.std(z_scores, ddof=1) - 1.0) < 1e-6  # Std ≈ 1

        # Check contrarian ranking preserved (loser > flat > winner)
        assert z_scores[2] > z_scores[1] > z_scores[0]  # XLE > XLF > XLK

    def test_history_tracking(self):
        """Test signal history is tracked correctly."""
        from Signals.SectorRotation.SectorReversionSignal import SectorReversionSignal

        signal = SectorReversionSignal(
            lookback_days=30,
            track_history=True
        )

        # Generate signals for 2 dates
        dates = [date(2023, 1, 1) + timedelta(days=i) for i in range(35)]

        xlk_data_t1 = pl.DataFrame({
            "ticker": ["XLK"] * 30,
            "date": dates[:30],
            "return": [0.01] * 30
        })

        xlk_data_t2 = pl.DataFrame({
            "ticker": ["XLK"] * 30,
            "date": dates[5:35],
            "return": [0.02] * 30
        })

        # Generate at two different dates
        signal.generate_batch(
            inst_data_list=[xlk_data_t1],
            market_data=None,
            as_of=dates[29]
        )

        signal.generate_batch(
            inst_data_list=[xlk_data_t2],
            market_data=None,
            as_of=dates[34]
        )

        # Check history
        history_df = signal.get_history()
        assert len(history_df) == 2
        assert dates[29] in history_df["date"].to_list()
        assert dates[34] in history_df["date"].to_list()

    def test_ic_calculation(self):
        """Test Information Coefficient calculation for contrarian strategy."""
        from Signals.SectorRotation.SectorReversionSignal import SectorReversionSignal

        signal = SectorReversionSignal()

        # Reversion strategy: Negative correlation expected
        # Recent winners (negative signal) → future underperformance
        # Recent losers (positive signal) → future outperformance
        forecasts = pl.Series([-1.5, -0.5, 0.5, 1.5])  # Z-scores (contrarian)
        actuals = pl.Series([-0.05, -0.02, 0.02, 0.05])  # Next period returns

        ic = signal.calculate_ic(forecasts, actuals)

        # Should be positive (contrarian strategy has predictive power)
        assert ic > 0.8  # Strong positive correlation for contrarian

    def test_default_rev_30d_configuration(self):
        """Test default configuration matches paper's REV_30D."""
        from Signals.SectorRotation.SectorReversionSignal import SectorReversionSignal

        signal = SectorReversionSignal()

        # Check default is REV_30D from paper
        assert signal.lookback_days == 30

        # Check computed windows
        assert signal.reversion_factor.lookback_days == 30

    def test_signal_with_insufficient_data(self):
        """Test signal raises error when insufficient data provided."""
        from Signals.SectorRotation.SectorReversionSignal import SectorReversionSignal

        signal = SectorReversionSignal(lookback_days=30)

        # Only 15 days of data (need 30 for REV_30D)
        dates = [date(2023, 1, 1) + timedelta(days=i) for i in range(15)]
        inst_data = pl.DataFrame({
            "ticker": ["XLK"] * 15,
            "date": dates,
            "return": [0.01] * 15
        })

        # Should raise ValueError
        try:
            signal._calculate_raw_signal(
                inst_data=inst_data,
                market_data=None,
                as_of=dates[-1]
            )
            raise AssertionError("Expected ValueError for insufficient data")
        except ValueError as e:
            assert "Insufficient history" in str(e)

    def test_signal_output_schema(self):
        """Test generate_batch returns NumPy array with correct shape."""
        from Signals.SectorRotation.SectorReversionSignal import SectorReversionSignal

        signal = SectorReversionSignal(lookback_days=30)

        # Create data for 5 sectors
        dates = [date(2023, 1, 1) + timedelta(days=i) for i in range(30)]
        inst_data_list = []

        for ticker in ["XLK", "XLE", "XLF", "XLI", "XLV"]:
            inst_data_list.append(pl.DataFrame({
                "ticker": [ticker] * 30,
                "date": dates,
                "return": [0.01] * 30
            }))

        signals = signal.generate_batch(
            inst_data_list=inst_data_list,
            market_data=None,
            as_of=dates[-1]
        )

        # Check output is NumPy array with correct shape
        assert isinstance(signals, np.ndarray)
        assert signals.shape == (5,)
        assert signals.dtype == np.float64

    def test_short_term_reversion_behavior(self):
        """Test that short-term reversion (30D) captures recent behavior."""
        from Signals.SectorRotation.SectorReversionSignal import SectorReversionSignal

        signal = SectorReversionSignal(lookback_days=5)

        # Sector with recent surge (last 5 days)
        dates = [date(2023, 1, 1) + timedelta(days=i) for i in range(5)]
        recent_surge = pl.DataFrame({
            "ticker": ["XLK"] * 5,
            "date": dates,
            "return": [0.03] * 5  # 3% daily = 15% in 5 days
        })

        surge_signal = signal._calculate_raw_signal(
            recent_surge, None, dates[-1]
        )

        # Should be strongly negative (bet against recent surge)
        assert surge_signal < -0.10  # Strong negative signal

    def test_repr_string(self):
        """Test string representation."""
        from Signals.SectorRotation.SectorReversionSignal import SectorReversionSignal

        signal = SectorReversionSignal()
        repr_str = repr(signal)

        assert "SectorReversionSignal" in repr_str
        assert "sector_reversion" in repr_str


if __name__ == "__main__":
    # Run tests
    test = TestSectorReversionSignal()

    print("Running SectorReversionSignal tests...")

    test.test_signal_initialization()
    print("✓ test_signal_initialization")

    test.test_signal_custom_parameters()
    print("✓ test_signal_custom_parameters")

    test.test_calculate_raw_signal_single_sector_winner()
    print("✓ test_calculate_raw_signal_single_sector_winner")

    test.test_calculate_raw_signal_single_sector_loser()
    print("✓ test_calculate_raw_signal_single_sector_loser")

    test.test_contrarian_logic_verification()
    print("✓ test_contrarian_logic_verification")

    test.test_generate_batch_multiple_sectors()
    print("✓ test_generate_batch_multiple_sectors")

    test.test_generate_batch_with_standardization()
    print("✓ test_generate_batch_with_standardization")

    test.test_history_tracking()
    print("✓ test_history_tracking")

    test.test_ic_calculation()
    print("✓ test_ic_calculation")

    test.test_default_rev_30d_configuration()
    print("✓ test_default_rev_30d_configuration")

    test.test_signal_with_insufficient_data()
    print("✓ test_signal_with_insufficient_data")

    test.test_signal_output_schema()
    print("✓ test_signal_output_schema")

    test.test_short_term_reversion_behavior()
    print("✓ test_short_term_reversion_behavior")

    test.test_repr_string()
    print("✓ test_repr_string")

    print("\n✅ All SectorReversionSignal tests passed!")
