"""
Test suite for SectorMomentumSignal.

Tests the signal wrapper that integrates MomentumFactor with BaseSignal.
TDD approach: tests written BEFORE implementation.
"""

from datetime import date, timedelta
import numpy as np
import polars as pl


class TestSectorMomentumSignal:
    """Test SectorMomentumSignal integration with BaseSignal."""

    def test_signal_initialization(self):
        """Test signal can be initialized with proper defaults."""
        from Signals.SectorRotation.SectorMomentumSignal import SectorMomentumSignal

        signal = SectorMomentumSignal()

        # Check BaseSignal attributes
        assert signal.name == "sector_momentum"
        assert signal.standardize is True  # Default standardization
        assert signal.track_history is True  # Default history tracking

        # Check MomentumFactor attributes
        assert signal.lookback_months == 7  # Default MOM_7M
        assert signal.exclusion_pct == 0.10  # Default 10% exclusion

    def test_signal_custom_parameters(self):
        """Test signal initialization with custom parameters."""
        from Signals.SectorRotation.SectorMomentumSignal import SectorMomentumSignal

        signal = SectorMomentumSignal(
            lookback_months=5,
            exclusion_pct=0.15,
            standardize=False
        )

        assert signal.name == "sector_momentum"
        assert signal.standardize is False
        assert signal.lookback_months == 5
        assert signal.exclusion_pct == 0.15

    def test_calculate_raw_signal_single_sector(self):
        """Test _calculate_raw_signal returns momentum for single sector."""
        from Signals.SectorRotation.SectorMomentumSignal import SectorMomentumSignal

        # Create signal
        signal = SectorMomentumSignal(lookback_months=1, exclusion_pct=0.10)

        # Create sector returns data (21 days for 1 month)
        dates = [date(2023, 1, 1) + timedelta(days=i) for i in range(21)]
        inst_data = pl.DataFrame({
            "ticker": ["XLK"] * 21,
            "date": dates,
            "return": [0.01] * 21  # 1% daily return
        })

        # Calculate raw signal
        raw_signal = signal._calculate_raw_signal(
            inst_data=inst_data,
            market_data=None,
            as_of=dates[-1]
        )

        # Expected: 21 * 0.01 (total) - 2 * 0.01 (exclusion) = 0.21 - 0.02 = 0.19
        # (10% of 21 days = 2 days exclusion)
        expected_momentum = 0.19
        assert abs(raw_signal - expected_momentum) < 1e-6

    def test_calculate_raw_signal_negative_momentum(self):
        """Test _calculate_raw_signal with negative momentum (losing sector)."""
        from Signals.SectorRotation.SectorMomentumSignal import SectorMomentumSignal

        signal = SectorMomentumSignal(lookback_months=1, exclusion_pct=0.10)

        # Create sector with negative returns
        dates = [date(2023, 1, 1) + timedelta(days=i) for i in range(21)]
        inst_data = pl.DataFrame({
            "ticker": ["XLE"] * 21,
            "date": dates,
            "return": [-0.02] * 21  # -2% daily return (declining sector)
        })

        raw_signal = signal._calculate_raw_signal(
            inst_data=inst_data,
            market_data=None,
            as_of=dates[-1]
        )

        # Expected: 21 * (-0.02) - 2 * (-0.02) = -0.42 + 0.04 = -0.38
        expected_momentum = -0.38
        assert abs(raw_signal - expected_momentum) < 1e-6

    def test_generate_batch_multiple_sectors(self):
        """Test generate_batch returns signals for multiple sectors."""
        from Signals.SectorRotation.SectorMomentumSignal import SectorMomentumSignal

        signal = SectorMomentumSignal(lookback_months=1, exclusion_pct=0.10)

        # Create data for 3 sectors with different momentum
        dates = [date(2023, 1, 1) + timedelta(days=i) for i in range(21)]

        # Strong winner (XLK): +2% daily
        xlk_data = pl.DataFrame({
            "ticker": ["XLK"] * 21,
            "date": dates,
            "return": [0.02] * 21
        })

        # Weak winner (XLF): +0.5% daily
        xlf_data = pl.DataFrame({
            "ticker": ["XLF"] * 21,
            "date": dates,
            "return": [0.005] * 21
        })

        # Loser (XLE): -1% daily
        xle_data = pl.DataFrame({
            "ticker": ["XLE"] * 21,
            "date": dates,
            "return": [-0.01] * 21
        })

        # Generate batch signals (WITHOUT standardization first)
        signal_raw = SectorMomentumSignal(
            lookback_months=1,
            exclusion_pct=0.10,
            standardize=False  # Disable to check raw values
        )

        raw_signals = signal_raw.generate_batch(
            inst_data_list=[xlk_data, xlf_data, xle_data],
            market_data=None,
            as_of=dates[-1]
        )

        # Check raw values
        assert len(raw_signals) == 3
        assert raw_signals[0] > raw_signals[1] > raw_signals[2]  # XLK > XLF > XLE

        # XLK: 21*0.02 - 2*0.02 = 0.38
        # XLF: 21*0.005 - 2*0.005 = 0.095
        # XLE: 21*(-0.01) - 2*(-0.01) = -0.19
        assert abs(raw_signals[0] - 0.38) < 1e-6
        assert abs(raw_signals[1] - 0.095) < 1e-6
        assert abs(raw_signals[2] - (-0.19)) < 1e-6

    def test_generate_batch_with_standardization(self):
        """Test generate_batch applies z-score standardization."""
        from Signals.SectorRotation.SectorMomentumSignal import SectorMomentumSignal

        signal = SectorMomentumSignal(
            lookback_months=1,
            exclusion_pct=0.10,
            standardize=True  # Enable standardization
        )

        # Create data for 3 sectors
        dates = [date(2023, 1, 1) + timedelta(days=i) for i in range(21)]

        xlk_data = pl.DataFrame({
            "ticker": ["XLK"] * 21,
            "date": dates,
            "return": [0.02] * 21
        })

        xlf_data = pl.DataFrame({
            "ticker": ["XLF"] * 21,
            "date": dates,
            "return": [0.005] * 21
        })

        xle_data = pl.DataFrame({
            "ticker": ["XLE"] * 21,
            "date": dates,
            "return": [-0.01] * 21
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

        # Check ranking preserved
        assert z_scores[0] > z_scores[1] > z_scores[2]  # XLK > XLF > XLE

    def test_history_tracking(self):
        """Test signal history is tracked correctly."""
        from Signals.SectorRotation.SectorMomentumSignal import SectorMomentumSignal

        signal = SectorMomentumSignal(
            lookback_months=1,
            track_history=True
        )

        # Generate signals for 2 dates
        dates = [date(2023, 1, 1) + timedelta(days=i) for i in range(25)]

        xlk_data_t1 = pl.DataFrame({
            "ticker": ["XLK"] * 21,
            "date": dates[:21],
            "return": [0.01] * 21
        })

        xlk_data_t2 = pl.DataFrame({
            "ticker": ["XLK"] * 21,
            "date": dates[4:25],
            "return": [0.02] * 21
        })

        # Generate at two different dates
        signal.generate_batch(
            inst_data_list=[xlk_data_t1],
            market_data=None,
            as_of=dates[20]
        )

        signal.generate_batch(
            inst_data_list=[xlk_data_t2],
            market_data=None,
            as_of=dates[24]
        )

        # Check history
        history_df = signal.get_history()
        assert len(history_df) == 2
        assert dates[20] in history_df["date"].to_list()
        assert dates[24] in history_df["date"].to_list()

    def test_ic_calculation(self):
        """Test Information Coefficient calculation."""
        from Signals.SectorRotation.SectorMomentumSignal import SectorMomentumSignal

        signal = SectorMomentumSignal()

        # Create forecasts and actuals with positive correlation
        forecasts = pl.Series([1.5, 0.5, -0.5, -1.5])  # Z-scores
        actuals = pl.Series([0.12, 0.05, -0.03, -0.10])  # Next period returns

        ic = signal.calculate_ic(forecasts, actuals)

        # Should be positive (momentum has predictive power)
        assert ic > 0.8  # Strong positive correlation

    def test_default_mom_7m_configuration(self):
        """Test default configuration matches paper's MOM_7M."""
        from Signals.SectorRotation.SectorMomentumSignal import SectorMomentumSignal

        signal = SectorMomentumSignal()

        # Check default is MOM_7M from paper
        assert signal.lookback_months == 7
        assert signal.exclusion_pct == 0.10

        # Check computed windows
        total_days = 7 * 21  # 147 days
        exclusion_days = int(147 * 0.10)  # 14 days (rounded)

        assert signal.momentum_factor.total_lookback_days == 147
        assert signal.momentum_factor.exclusion_days == exclusion_days

    def test_signal_with_insufficient_data(self):
        """Test signal raises error when insufficient data provided."""
        from Signals.SectorRotation.SectorMomentumSignal import SectorMomentumSignal

        signal = SectorMomentumSignal(lookback_months=7)

        # Only 50 days of data (need 147 for MOM_7M)
        dates = [date(2023, 1, 1) + timedelta(days=i) for i in range(50)]
        inst_data = pl.DataFrame({
            "ticker": ["XLK"] * 50,
            "date": dates,
            "return": [0.01] * 50
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
        from Signals.SectorRotation.SectorMomentumSignal import SectorMomentumSignal

        signal = SectorMomentumSignal(lookback_months=1)

        # Create data for 5 sectors
        dates = [date(2023, 1, 1) + timedelta(days=i) for i in range(21)]
        inst_data_list = []

        for ticker in ["XLK", "XLE", "XLF", "XLI", "XLV"]:
            inst_data_list.append(pl.DataFrame({
                "ticker": [ticker] * 21,
                "date": dates,
                "return": [0.01] * 21
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

    def test_repr_string(self):
        """Test string representation."""
        from Signals.SectorRotation.SectorMomentumSignal import SectorMomentumSignal

        signal = SectorMomentumSignal()
        repr_str = repr(signal)

        assert "SectorMomentumSignal" in repr_str
        assert "sector_momentum" in repr_str


if __name__ == "__main__":
    # Run tests
    test = TestSectorMomentumSignal()

    print("Running SectorMomentumSignal tests...")

    test.test_signal_initialization()
    print("✓ test_signal_initialization")

    test.test_signal_custom_parameters()
    print("✓ test_signal_custom_parameters")

    test.test_calculate_raw_signal_single_sector()
    print("✓ test_calculate_raw_signal_single_sector")

    test.test_calculate_raw_signal_negative_momentum()
    print("✓ test_calculate_raw_signal_negative_momentum")

    test.test_generate_batch_multiple_sectors()
    print("✓ test_generate_batch_multiple_sectors")

    test.test_generate_batch_with_standardization()
    print("✓ test_generate_batch_with_standardization")

    test.test_history_tracking()
    print("✓ test_history_tracking")

    test.test_ic_calculation()
    print("✓ test_ic_calculation")

    test.test_default_mom_7m_configuration()
    print("✓ test_default_mom_7m_configuration")

    test.test_signal_with_insufficient_data()
    print("✓ test_signal_with_insufficient_data")

    test.test_signal_output_schema()
    print("✓ test_signal_output_schema")

    test.test_repr_string()
    print("✓ test_repr_string")

    print("\n✅ All SectorMomentumSignal tests passed!")
