"""Tests for the vectorized EOD rate computation engine."""
import datetime

import numpy as np
import pytest

from Caching.eod_vectorized_engine import (
    parse_tenor,
    build_payment_schedule,
    PaymentSchedule,
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
