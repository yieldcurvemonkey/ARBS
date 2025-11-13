# ABOUTME: Unit tests for CurrencyCarrySignal class
# ABOUTME: Tests carry calculation, z-score normalization, and cross-currency neutralization

import numpy as np
import polars as pl
from datetime import date, timedelta


class TestCurrencyCarrySignal:
    """Test CurrencyCarrySignal integration with BaseSignal."""

    def test_signal_initialization(self):
        """Test signal can be initialized with proper defaults."""
        from Signals.CurrencyCarrySignal import CurrencyCarrySignal

        signal = CurrencyCarrySignal()

        # Check BaseSignal attributes
        assert signal.name == "currency_carry"
        assert signal.standardize is True  # Default standardization
        assert signal.track_history is True  # Default history tracking

        # Check carry-specific attributes
        assert signal.long_tenor == "10Y"  # Default long tenor
        assert signal.short_tenor == "2Y"  # Default short tenor

    def test_signal_custom_parameters(self):
        """Test signal initialization with custom parameters."""
        from Signals.CurrencyCarrySignal import CurrencyCarrySignal

        signal = CurrencyCarrySignal(
            long_tenor="30Y",
            short_tenor="5Y",
            standardize=False
        )

        assert signal.name == "currency_carry"
        assert signal.standardize is False
        assert signal.long_tenor == "30Y"
        assert signal.short_tenor == "5Y"

    def test_calculate_raw_signal_single_currency(self):
        """Test _calculate_raw_signal returns carry for single currency."""
        from Signals.CurrencyCarrySignal import CurrencyCarrySignal

        # Create signal (10Y - 2Y carry)
        signal = CurrencyCarrySignal(long_tenor="10Y", short_tenor="2Y")

        # Create yield curve data
        dates = [date(2023, 1, 1) + timedelta(days=i) for i in range(10)]
        inst_data = pl.DataFrame({
            "currency": ["USD"] * 20,
            "tenor": ["2Y"] * 10 + ["10Y"] * 10,
            "date": dates + dates,
            "yield": [0.02] * 10 + [0.04] * 10  # 2Y: 2%, 10Y: 4%
        })

        # Calculate raw signal
        raw_signal = signal._calculate_raw_signal(
            inst_data=inst_data,
            market_data=None,
            as_of=dates[-1]
        )

        # Expected carry: 0.04 - 0.02 = 0.02 (200 bps)
        expected_carry = 0.02
        assert abs(raw_signal - expected_carry) < 1e-6

    def test_calculate_raw_signal_negative_carry(self):
        """Test _calculate_raw_signal with negative carry (inverted curve)."""
        from Signals.CurrencyCarrySignal import CurrencyCarrySignal

        signal = CurrencyCarrySignal(long_tenor="10Y", short_tenor="2Y")

        # Create inverted yield curve
        dates = [date(2023, 1, 1) + timedelta(days=i) for i in range(10)]
        inst_data = pl.DataFrame({
            "currency": ["USD"] * 20,
            "tenor": ["2Y"] * 10 + ["10Y"] * 10,
            "date": dates + dates,
            "yield": [0.05] * 10 + [0.03] * 10  # 2Y: 5%, 10Y: 3% (inverted)
        })

        raw_signal = signal._calculate_raw_signal(
            inst_data=inst_data,
            market_data=None,
            as_of=dates[-1]
        )

        # Expected carry: 0.03 - 0.05 = -0.02 (negative 200 bps)
        expected_carry = -0.02
        assert abs(raw_signal - expected_carry) < 1e-6

    def test_generate_batch_multiple_currencies(self):
        """Test generate_batch returns signals for multiple currencies."""
        from Signals.CurrencyCarrySignal import CurrencyCarrySignal

        signal = CurrencyCarrySignal(long_tenor="10Y", short_tenor="2Y")

        # Create data for 3 currencies with different carry
        dates = [date(2023, 1, 1) + timedelta(days=i) for i in range(10)]

        # USD: High carry (steep curve)
        usd_data = pl.DataFrame({
            "currency": ["USD"] * 20,
            "tenor": ["2Y"] * 10 + ["10Y"] * 10,
            "date": dates + dates,
            "yield": [0.02] * 10 + [0.05] * 10  # Carry: 300 bps
        })

        # EUR: Medium carry
        eur_data = pl.DataFrame({
            "currency": ["EUR"] * 20,
            "tenor": ["2Y"] * 10 + ["10Y"] * 10,
            "date": dates + dates,
            "yield": [0.01] * 10 + [0.025] * 10  # Carry: 150 bps
        })

        # CHF: Low carry (flat curve)
        chf_data = pl.DataFrame({
            "currency": ["CHF"] * 20,
            "tenor": ["2Y"] * 10 + ["10Y"] * 10,
            "date": dates + dates,
            "yield": [0.005] * 10 + [0.010] * 10  # Carry: 50 bps
        })

        # Generate batch signals WITHOUT standardization first
        signal_raw = CurrencyCarrySignal(
            long_tenor="10Y",
            short_tenor="2Y",
            standardize=False
        )

        raw_signals = signal_raw.generate_batch(
            inst_data_list=[usd_data, eur_data, chf_data],
            market_data=None,
            as_of=dates[-1]
        )

        # Check raw values
        assert len(raw_signals) == 3
        assert raw_signals[0] > raw_signals[1] > raw_signals[2]  # USD > EUR > CHF

        # USD: 0.05 - 0.02 = 0.03
        # EUR: 0.025 - 0.01 = 0.015
        # CHF: 0.010 - 0.005 = 0.005
        assert abs(raw_signals[0] - 0.03) < 1e-6
        assert abs(raw_signals[1] - 0.015) < 1e-6
        assert abs(raw_signals[2] - 0.005) < 1e-6

    def test_generate_batch_with_standardization(self):
        """Test generate_batch applies z-score standardization (cross-currency neutral)."""
        from Signals.CurrencyCarrySignal import CurrencyCarrySignal

        signal = CurrencyCarrySignal(
            long_tenor="10Y",
            short_tenor="2Y",
            standardize=True  # Enable standardization
        )

        # Create data for 3 currencies
        dates = [date(2023, 1, 1) + timedelta(days=i) for i in range(10)]

        usd_data = pl.DataFrame({
            "currency": ["USD"] * 20,
            "tenor": ["2Y"] * 10 + ["10Y"] * 10,
            "date": dates + dates,
            "yield": [0.02] * 10 + [0.05] * 10
        })

        eur_data = pl.DataFrame({
            "currency": ["EUR"] * 20,
            "tenor": ["2Y"] * 10 + ["10Y"] * 10,
            "date": dates + dates,
            "yield": [0.01] * 10 + [0.025] * 10
        })

        chf_data = pl.DataFrame({
            "currency": ["CHF"] * 20,
            "tenor": ["2Y"] * 10 + ["10Y"] * 10,
            "date": dates + dates,
            "yield": [0.005] * 10 + [0.010] * 10
        })

        # Generate batch with standardization
        z_scores = signal.generate_batch(
            inst_data_list=[usd_data, eur_data, chf_data],
            market_data=None,
            as_of=dates[-1]
        )

        # Check z-score properties (cross-currency neutralization)
        assert len(z_scores) == 3
        assert abs(np.mean(z_scores)) < 1e-6  # Mean ≈ 0
        assert abs(np.std(z_scores, ddof=1) - 1.0) < 1e-6  # Std ≈ 1

        # Check ranking preserved
        assert z_scores[0] > z_scores[1] > z_scores[2]  # USD > EUR > CHF

    def test_history_tracking(self):
        """Test signal history is tracked correctly."""
        from Signals.CurrencyCarrySignal import CurrencyCarrySignal

        signal = CurrencyCarrySignal(track_history=True)

        # Generate signals for 2 dates
        dates1 = [date(2023, 1, 1) + timedelta(days=i) for i in range(10)]
        dates2 = [date(2023, 1, 15) + timedelta(days=i) for i in range(10)]

        usd_data_t1 = pl.DataFrame({
            "currency": ["USD"] * 20,
            "tenor": ["2Y"] * 10 + ["10Y"] * 10,
            "date": dates1 + dates1,
            "yield": [0.02] * 10 + [0.04] * 10
        })

        usd_data_t2 = pl.DataFrame({
            "currency": ["USD"] * 20,
            "tenor": ["2Y"] * 10 + ["10Y"] * 10,
            "date": dates2 + dates2,
            "yield": [0.025] * 10 + [0.045] * 10
        })

        # Generate at two different dates
        signal.generate_batch(
            inst_data_list=[usd_data_t1],
            market_data=None,
            as_of=dates1[-1]
        )

        signal.generate_batch(
            inst_data_list=[usd_data_t2],
            market_data=None,
            as_of=dates2[-1]
        )

        # Check history
        history_df = signal.get_history()
        assert len(history_df) == 2
        assert dates1[-1] in history_df["date"].to_list()
        assert dates2[-1] in history_df["date"].to_list()

    def test_ic_calculation(self):
        """Test Information Coefficient calculation."""
        from Signals.CurrencyCarrySignal import CurrencyCarrySignal

        signal = CurrencyCarrySignal()

        # Create forecasts and actuals with positive correlation
        forecasts = pl.Series([1.5, 0.5, -0.5, -1.5])  # Z-scores (carry signals)
        actuals = pl.Series([0.10, 0.03, -0.02, -0.08])  # Next period returns

        ic = signal.calculate_ic(forecasts, actuals)

        # Should be positive (carry has predictive power)
        assert ic > 0.8  # Strong positive correlation

    def test_different_tenor_combinations(self):
        """Test different tenor spread combinations (5Y-2Y, 30Y-10Y)."""
        from Signals.CurrencyCarrySignal import CurrencyCarrySignal

        # Test 5Y-2Y carry
        signal_5y2y = CurrencyCarrySignal(long_tenor="5Y", short_tenor="2Y")
        assert signal_5y2y.long_tenor == "5Y"
        assert signal_5y2y.short_tenor == "2Y"

        # Test 30Y-10Y carry
        signal_30y10y = CurrencyCarrySignal(long_tenor="30Y", short_tenor="10Y")
        assert signal_30y10y.long_tenor == "30Y"
        assert signal_30y10y.short_tenor == "10Y"

    def test_butterfly_carry_signal(self):
        """Test butterfly carry (2s5s10s) calculation."""
        from Signals.CurrencyCarrySignal import CurrencyCarrySignal

        # Butterfly carry: (5Y-2Y) - (10Y-5Y) = 2*5Y - 2Y - 10Y
        signal = CurrencyCarrySignal(
            long_tenor="5Y",
            short_tenor="2Y",
            butterfly=True  # Enable butterfly mode
        )

        dates = [date(2023, 1, 1) + timedelta(days=i) for i in range(10)]
        inst_data = pl.DataFrame({
            "currency": ["USD"] * 30,
            "tenor": ["2Y"] * 10 + ["5Y"] * 10 + ["10Y"] * 10,
            "date": dates + dates + dates,
            "yield": [0.02] * 10 + [0.035] * 10 + [0.045] * 10
        })

        raw_signal = signal._calculate_raw_signal(
            inst_data=inst_data,
            market_data=None,
            as_of=dates[-1]
        )

        # Butterfly: 2*0.035 - 0.02 - 0.045 = 0.07 - 0.065 = 0.005
        expected_butterfly = 0.005
        assert abs(raw_signal - expected_butterfly) < 1e-6

    def test_signal_with_missing_tenor_data(self):
        """Test signal raises error when tenor data is missing."""
        from Signals.CurrencyCarrySignal import CurrencyCarrySignal

        signal = CurrencyCarrySignal(long_tenor="10Y", short_tenor="2Y")

        # Only 2Y data, missing 10Y
        dates = [date(2023, 1, 1) + timedelta(days=i) for i in range(10)]
        inst_data = pl.DataFrame({
            "currency": ["USD"] * 10,
            "tenor": ["2Y"] * 10,
            "date": dates,
            "yield": [0.02] * 10
        })

        # Should raise ValueError
        try:
            signal._calculate_raw_signal(
                inst_data=inst_data,
                market_data=None,
                as_of=dates[-1]
            )
            raise AssertionError("Expected ValueError for missing tenor data")
        except ValueError as e:
            assert "Missing tenor" in str(e) or "No data" in str(e)

    def test_signal_output_schema(self):
        """Test generate_batch returns NumPy array with correct shape."""
        from Signals.CurrencyCarrySignal import CurrencyCarrySignal

        signal = CurrencyCarrySignal()

        # Create data for 5 currencies
        dates = [date(2023, 1, 1) + timedelta(days=i) for i in range(10)]
        inst_data_list = []

        for currency in ["USD", "EUR", "GBP", "CHF", "JPY"]:
            inst_data_list.append(pl.DataFrame({
                "currency": [currency] * 20,
                "tenor": ["2Y"] * 10 + ["10Y"] * 10,
                "date": dates + dates,
                "yield": [0.02] * 10 + [0.04] * 10
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

    def test_cross_currency_neutralization(self):
        """Test that z-scores are cross-currency neutral (mean=0, std=1)."""
        from Signals.CurrencyCarrySignal import CurrencyCarrySignal

        signal = CurrencyCarrySignal(standardize=True)

        # Create data with various carry levels
        dates = [date(2023, 1, 1) + timedelta(days=i) for i in range(10)]
        carry_levels = [0.01, 0.02, 0.03, 0.04, 0.05]  # Different carry for each currency

        inst_data_list = []
        for i, currency in enumerate(["USD", "EUR", "GBP", "CHF", "JPY"]):
            long_yield = 0.03 + carry_levels[i]
            short_yield = 0.03

            inst_data_list.append(pl.DataFrame({
                "currency": [currency] * 20,
                "tenor": ["2Y"] * 10 + ["10Y"] * 10,
                "date": dates + dates,
                "yield": [short_yield] * 10 + [long_yield] * 10
            }))

        z_scores = signal.generate_batch(
            inst_data_list=inst_data_list,
            market_data=None,
            as_of=dates[-1]
        )

        # Verify cross-currency neutralization
        assert abs(np.mean(z_scores)) < 1e-10  # Mean exactly 0
        assert abs(np.std(z_scores, ddof=1) - 1.0) < 1e-10  # Std exactly 1

    def test_repr_string(self):
        """Test string representation."""
        from Signals.CurrencyCarrySignal import CurrencyCarrySignal

        signal = CurrencyCarrySignal()
        repr_str = repr(signal)

        assert "CurrencyCarrySignal" in repr_str
        assert "currency_carry" in repr_str


if __name__ == "__main__":
    # Run tests
    test = TestCurrencyCarrySignal()

    print("Running CurrencyCarrySignal tests...")

    test.test_signal_initialization()
    print("✓ test_signal_initialization")

    test.test_signal_custom_parameters()
    print("✓ test_signal_custom_parameters")

    test.test_calculate_raw_signal_single_currency()
    print("✓ test_calculate_raw_signal_single_currency")

    test.test_calculate_raw_signal_negative_carry()
    print("✓ test_calculate_raw_signal_negative_carry")

    test.test_generate_batch_multiple_currencies()
    print("✓ test_generate_batch_multiple_currencies")

    test.test_generate_batch_with_standardization()
    print("✓ test_generate_batch_with_standardization")

    test.test_history_tracking()
    print("✓ test_history_tracking")

    test.test_ic_calculation()
    print("✓ test_ic_calculation")

    test.test_different_tenor_combinations()
    print("✓ test_different_tenor_combinations")

    test.test_butterfly_carry_signal()
    print("✓ test_butterfly_carry_signal")

    test.test_signal_with_missing_tenor_data()
    print("✓ test_signal_with_missing_tenor_data")

    test.test_signal_output_schema()
    print("✓ test_signal_output_schema")

    test.test_cross_currency_neutralization()
    print("✓ test_cross_currency_neutralization")

    test.test_repr_string()
    print("✓ test_repr_string")

    print("\n✅ All CurrencyCarrySignal tests passed!")
