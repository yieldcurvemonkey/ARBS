"""Tests for the vectorized EOD rate computation engine."""
import datetime

import numpy as np
import pytest

from Caching.eod_vectorized_engine import (
    parse_tenor,
    build_payment_schedule,
    PaymentSchedule,
    interpolate_discount_factors,
)


class TestParseTenor:
    """Test tenor string parsing into (fwd_period, swap_period) tuples."""

    def test_spot_outright_months(self):
        fwd, swap = parse_tenor("6M")
        assert fwd is None
        assert swap == "6M"

    def test_spot_outright_years(self):
        fwd, swap = parse_tenor("10Y")
        assert fwd is None
        assert swap == "10Y"

    def test_forward_starting(self):
        fwd, swap = parse_tenor("2Y3Y")
        assert fwd == "2Y"
        assert swap == "3Y"

    def test_forward_starting_months(self):
        fwd, swap = parse_tenor("6M1Y")
        assert fwd == "6M"
        assert swap == "1Y"

    def test_forward_starting_mixed(self):
        fwd, swap = parse_tenor("18M5Y")
        assert fwd == "18M"
        assert swap == "5Y"

    def test_granular_month_tenor(self):
        fwd, swap = parse_tenor("42M")
        assert fwd is None
        assert swap == "42M"


class TestBuildPaymentSchedule:
    """Test payment schedule generation."""

    def test_spot_2y_schedule(self):
        # 2Y annual swap from 2024-01-02 (T+2 from 2023-12-29)
        sched = build_payment_schedule(
            trading_date=datetime.date(2023, 12, 29),
            tenor="2Y",
            settlement_days=2,
        )
        assert isinstance(sched, PaymentSchedule)
        assert len(sched.payment_dates) == 2  # annual payments
        assert len(sched.accrual_fractions) == 2
        assert sched.effective_date < sched.maturity_date
        # ACT/360 accrual fractions should be close to 1.0139 (365/360)
        for tau in sched.accrual_fractions:
            assert 0.99 < tau < 1.03

    def test_forward_starting_schedule(self):
        sched = build_payment_schedule(
            trading_date=datetime.date(2024, 3, 15),
            tenor="1Y2Y",
            settlement_days=2,
        )
        # Forward 1Y then 2Y swap = 2 annual payments
        assert len(sched.payment_dates) == 2
        # Effective should be ~1Y after spot
        spot = datetime.date(2024, 3, 19)  # T+2
        assert (sched.effective_date - spot).days > 350

    def test_maturity_equals_last_payment(self):
        sched = build_payment_schedule(
            trading_date=datetime.date(2024, 6, 3),
            tenor="5Y",
            settlement_days=2,
        )
        assert sched.maturity_date == sched.payment_dates[-1]


class TestInterpolateDiscountFactors:
    """Test log-linear discount factor interpolation."""

    def test_on_node_returns_exact(self):
        base_date = datetime.date(2024, 1, 2)
        node_dates = [datetime.date(2024, 1, 2), datetime.date(2025, 1, 2), datetime.date(2026, 1, 2)]
        node_dfs = np.array([1.0, 0.96, 0.92])
        target_dates = [datetime.date(2025, 1, 2)]
        result = interpolate_discount_factors(base_date, node_dates, node_dfs, target_dates)
        np.testing.assert_allclose(result, [0.96], atol=1e-12)

    def test_midpoint_log_linear(self):
        base_date = datetime.date(2024, 1, 2)
        node_dates = [datetime.date(2024, 1, 2), datetime.date(2026, 1, 2)]
        node_dfs = np.array([1.0, 0.92])
        # Midpoint: log-linear interpolation at 1Y
        target_dates = [datetime.date(2025, 1, 2)]
        result = interpolate_discount_factors(base_date, node_dates, node_dfs, target_dates)
        # 2024 is leap year: 366 days to midpoint, 731 days to end
        frac = 366.0 / 731.0
        expected = np.exp(frac * np.log(0.92))
        np.testing.assert_allclose(result, [expected], atol=1e-10)

    def test_multiple_targets(self):
        base_date = datetime.date(2024, 1, 2)
        node_dates = [datetime.date(2024, 1, 2), datetime.date(2025, 1, 2), datetime.date(2029, 1, 2)]
        node_dfs = np.array([1.0, 0.95, 0.80])
        targets = [datetime.date(2025, 1, 2), datetime.date(2027, 1, 2)]
        result = interpolate_discount_factors(base_date, node_dates, node_dfs, targets)
        assert len(result) == 2
        np.testing.assert_allclose(result[0], 0.95, atol=1e-12)

    def test_beyond_last_node_returns_nan(self):
        base_date = datetime.date(2024, 1, 2)
        node_dates = [datetime.date(2024, 1, 2), datetime.date(2026, 1, 2)]
        node_dfs = np.array([1.0, 0.92])
        target_dates = [datetime.date(2030, 1, 2)]
        result = interpolate_discount_factors(base_date, node_dates, node_dfs, target_dates)
        assert np.isnan(result[0])
