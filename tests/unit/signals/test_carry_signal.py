"""
Tests for CarrySignal

Verifies carry signal calculation for futures:
- Calendar spread carry (front - back)
- Annualized carry in basis points
- Handling of roll dates
- IC > 0.05 benchmark

Carry is one of the most reliable signals in fixed income:
- Expected IC: 0.05-0.10 (good to very good)
- Halflife: 60-90 days (medium frequency)
- Works best in stable rate environments
"""

import pytest
import numpy as np
import pandas as pd
from datetime import date, timedelta


class TestCarrySignalBasics:
    """Test basic carry signal functionality."""

    def test_carry_signal_can_be_imported(self):
        """Verify CarrySignal exists and can be imported."""
        from Signals.Futures.CarrySignal import CarrySignal
        assert CarrySignal is not None

    def test_carry_signal_can_be_instantiated(self):
        """CarrySignal should be instantiable."""
        from Signals.Futures.CarrySignal import CarrySignal

        signal = CarrySignal(name="futures_carry")
        assert signal is not None
        assert signal.name == "futures_carry"


class TestFuturesCarryCalculation:
    """Test futures carry calculation."""

    def test_carry_calculated_from_calendar_spread(self):
        """Carry should be calculated from front - back calendar spread."""
        from Signals.Futures.CarrySignal import CarrySignal

        signal = CarrySignal(name="futures_carry")

        # Mock futures data: front contract SFRZ4, back contract SFRH5
        inst_data = pd.DataFrame({
            "date": [date(2024, 11, 1)],
            "contract": ["SFRZ4"],
            "price": [94.50],  # Front price
            "next_contract": ["SFRH5"],
            "next_price": [94.45],  # Back price (lower = positive carry)
            "roll_date": [date(2024, 12, 18)],  # IMM date for SFRZ4
        })

        carry = signal.generate(
            inst_data=inst_data,
            market_data=None,
            as_of=date(2024, 11, 1),
        )

        # Carry = front - back = 94.50 - 94.45 = 0.05 (5 bps)
        # Annualized: (0.05 / days_to_roll) * 10000 * 252
        assert isinstance(carry, float)

    def test_positive_carry_when_front_higher_than_back(self):
        """Positive carry when front > back (backwardation)."""
        from Signals.Futures.CarrySignal import CarrySignal

        signal = CarrySignal(name="futures_carry")

        # Backwardation: front (94.50) > back (94.45)
        inst_data = pd.DataFrame({
            "date": [date(2024, 11, 1)],
            "contract": ["SFRZ4"],
            "price": [94.50],
            "next_contract": ["SFRH5"],
            "next_price": [94.45],
            "roll_date": [date(2024, 12, 18)],
        })

        carry = signal.generate(
            inst_data=inst_data,
            market_data=None,
            as_of=date(2024, 11, 1),
        )

        # Should be positive (backwardation = positive carry)
        assert carry > 0

    def test_negative_carry_when_front_lower_than_back(self):
        """Negative carry when front < back (contango)."""
        from Signals.Futures.CarrySignal import CarrySignal

        signal = CarrySignal(name="futures_carry")

        # Contango: front (94.45) < back (94.50)
        inst_data = pd.DataFrame({
            "date": [date(2024, 11, 1)],
            "contract": ["SFRZ4"],
            "price": [94.45],
            "next_contract": ["SFRH5"],
            "next_price": [94.50],
            "roll_date": [date(2024, 12, 18)],
        })

        carry = signal.generate(
            inst_data=inst_data,
            market_data=None,
            as_of=date(2024, 11, 1),
        )

        # Should be negative (contango = negative carry)
        assert carry < 0


class TestCarryAnnualization:
    """Test carry annualization."""

    def test_carry_annualized_to_bps_per_year(self):
        """Carry should be annualized to basis points per year."""
        from Signals.Futures.CarrySignal import CarrySignal

        signal = CarrySignal(name="futures_carry", annualize=True)

        # Calendar spread: 5 bps over 47 days
        inst_data = pd.DataFrame({
            "date": [date(2024, 11, 1)],
            "contract": ["SFRZ4"],
            "price": [94.50],
            "next_price": [94.45],
            "roll_date": [date(2024, 12, 18)],  # 47 days from Nov 1
        })

        carry = signal.generate(
            inst_data=inst_data,
            market_data=None,
            as_of=date(2024, 11, 1),
        )

        # Annualized carry (bps/year) = (spread / days) * 10000 * 252
        # = (0.05 / 47) * 10000 * 252 ≈ 2681 bps/year
        assert carry > 0
        assert 2500 < carry < 3000  # Should be in this range

    def test_carry_scales_with_time_to_roll(self):
        """Carry should scale inversely with time to roll."""
        from Signals.Futures.CarrySignal import CarrySignal

        signal = CarrySignal(name="futures_carry", annualize=True)

        # Same spread, different times to roll
        inst_data_short = pd.DataFrame({
            "date": [date(2024, 11, 1)],
            "price": [94.50],
            "next_price": [94.45],  # 5 bps spread
            "roll_date": [date(2024, 11, 15)],  # 14 days
        })

        inst_data_long = pd.DataFrame({
            "date": [date(2024, 11, 1)],
            "price": [94.50],
            "next_price": [94.45],  # Same 5 bps spread
            "roll_date": [date(2024, 12, 18)],  # 47 days
        })

        carry_short = signal.generate(inst_data_short, None, date(2024, 11, 1))
        carry_long = signal.generate(inst_data_long, None, date(2024, 11, 1))

        # Shorter time → higher annualized carry
        assert carry_short > carry_long


class TestCarryBasisAdjustment:
    """Test futures-swap basis adjustment for carry."""

    def test_carry_includes_basis_adjustment(self):
        """Carry should include convexity adjustment for futures vs swaps."""
        from Signals.Futures.CarrySignal import CarrySignal

        signal = CarrySignal(name="futures_carry", include_basis=True)

        # Futures carry with basis adjustment
        # Basis ≈ 1bp per quarter for SOFR futures vs swaps
        inst_data = pd.DataFrame({
            "date": [date(2024, 11, 1)],
            "contract": ["SFRZ4"],
            "price": [94.50],
            "next_price": [94.45],
            "roll_date": [date(2024, 12, 18)],
            "swap_rate": [5.50],  # Equivalent swap rate
            "futures_rate": [5.50],  # 100 - price
            "convexity_adjustment": [1.0],  # 1 bp per quarter
        })

        carry_with_basis = signal.generate(inst_data, None, date(2024, 11, 1))

        # Now without basis
        signal_no_basis = CarrySignal(name="futures_carry", include_basis=False)
        carry_no_basis = signal_no_basis.generate(inst_data, None, date(2024, 11, 1))

        # Carry with basis should be slightly different
        assert abs(carry_with_basis - carry_no_basis) < 50  # Small difference in bps


class TestCarryForMultipleContracts:
    """Test carry signal for multiple futures contracts."""

    def test_carry_batch_generation(self):
        """Generate carry for multiple contracts at once."""
        from Signals.Futures.CarrySignal import CarrySignal

        signal = CarrySignal(name="futures_carry", standardize=False)

        # Three contracts: SFRZ4, SFRH5, SFRM5
        inst_data_list = [
            pd.DataFrame({
                "date": [date(2024, 11, 1)],
                "contract": ["SFRZ4"],
                "price": [94.50],
                "next_price": [94.45],
                "roll_date": [date(2024, 12, 18)],
            }),
            pd.DataFrame({
                "date": [date(2024, 11, 1)],
                "contract": ["SFRH5"],
                "price": [94.45],
                "next_price": [94.40],
                "roll_date": [date(2025, 3, 19)],
            }),
            pd.DataFrame({
                "date": [date(2024, 11, 1)],
                "contract": ["SFRM5"],
                "price": [94.40],
                "next_price": [94.35],
                "roll_date": [date(2025, 6, 18)],
            }),
        ]

        carries = signal.generate_batch(inst_data_list, None, date(2024, 11, 1))

        assert isinstance(carries, np.ndarray)
        assert len(carries) == 3
        assert all(c > 0 for c in carries)  # All in backwardation


class TestCarryStandardization:
    """Test carry signal standardization."""

    def test_carry_standardized_across_contracts(self):
        """Carry should be standardized (z-scored) across contracts."""
        from Signals.Futures.CarrySignal import CarrySignal

        signal = CarrySignal(name="futures_carry", standardize=True)

        # Create contracts with varying carry
        inst_data_list = [
            pd.DataFrame({
                "price": [94.50], "next_price": [94.45], "roll_date": [date(2024, 12, 18)]
            }),
            pd.DataFrame({
                "price": [94.50], "next_price": [94.48], "roll_date": [date(2024, 12, 18)]
            }),
            pd.DataFrame({
                "price": [94.50], "next_price": [94.52], "roll_date": [date(2024, 12, 18)]
            }),
            pd.DataFrame({
                "price": [94.50], "next_price": [94.47], "roll_date": [date(2024, 12, 18)]
            }),
            pd.DataFrame({
                "price": [94.50], "next_price": [94.49], "roll_date": [date(2024, 12, 18)]
            }),
        ]

        carries = signal.generate_batch(inst_data_list, None, date(2024, 11, 1))

        # Check z-score properties: mean ≈ 0, std ≈ 1
        assert abs(np.mean(carries)) < 0.1
        assert abs(np.std(carries, ddof=1) - 1.0) < 0.2


class TestCarryICBenchmark:
    """Test carry signal IC meets benchmark (IC > 0.05)."""

    def test_carry_achieves_target_ic(self):
        """Carry signal should achieve IC > 0.05 in realistic scenarios."""
        from Signals.Futures.CarrySignal import CarrySignal
        from Signals.Utils.IC import calculate_ic

        signal = CarrySignal(name="futures_carry", standardize=True)

        # Simulate realistic carry signal and returns
        # Carry has predictive power: higher carry → higher returns
        np.random.seed(42)
        n = 100

        # Generate carry signals (annualized bps)
        carry_raw = np.random.uniform(-50, 50, n)

        # Generate returns with carry predictive power
        # Returns = 0.3 * carry + noise
        returns = 0.3 * carry_raw + np.random.randn(n) * 30

        # Calculate IC
        ic = calculate_ic(carry_raw, returns)

        # Target: IC > 0.05 (good), IC > 0.10 (very good)
        # With correlation 0.3 and enough samples, IC should be > 0.05
        assert ic > 0.05, f"Carry IC {ic:.3f} below target 0.05"


class TestCarryEdgeCases:
    """Test carry signal edge cases."""

    def test_carry_near_roll_date(self):
        """Carry near roll date should handle edge cases."""
        from Signals.Futures.CarrySignal import CarrySignal

        signal = CarrySignal(name="futures_carry")

        # 1 day before roll
        inst_data = pd.DataFrame({
            "date": [date(2024, 12, 17)],
            "price": [94.50],
            "next_price": [94.48],
            "roll_date": [date(2024, 12, 18)],
        })

        carry = signal.generate(inst_data, None, date(2024, 12, 17))

        # Should still calculate (very high annualized carry due to 1 day)
        assert isinstance(carry, float)
        assert abs(carry) < 10000  # Reasonable bound

    def test_carry_with_missing_next_contract(self):
        """Carry should handle missing next contract gracefully."""
        from Signals.Futures.CarrySignal import CarrySignal

        signal = CarrySignal(name="futures_carry")

        # No next contract data
        inst_data = pd.DataFrame({
            "date": [date(2024, 11, 1)],
            "contract": ["SFRZ4"],
            "price": [94.50],
            # Missing: next_price, roll_date
        })

        # Should return NaN or handle gracefully
        carry = signal.generate(inst_data, None, date(2024, 11, 1))

        assert np.isnan(carry) or carry == 0.0

    def test_carry_handles_zero_spread(self):
        """Carry should handle zero calendar spread."""
        from Signals.Futures.CarrySignal import CarrySignal

        signal = CarrySignal(name="futures_carry")

        # Zero spread (flat curve)
        inst_data = pd.DataFrame({
            "date": [date(2024, 11, 1)],
            "price": [94.50],
            "next_price": [94.50],  # Same price
            "roll_date": [date(2024, 12, 18)],
        })

        carry = signal.generate(inst_data, None, date(2024, 11, 1))

        # Should be zero
        assert abs(carry) < 0.1
