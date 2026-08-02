"""Synthetic tests for the FOMC-swap meeting ladder (no network, no curves)."""
import datetime

import numpy as np
import pandas as pd
import pytest

from RVUtils.MeetingProb.ladder import MeetingLattice
from RVUtils.MeetingProb.swap_ladder import (
    fomc_period_rates,
    jumps_from_period_rates,
    swap_meeting_ladder,
)


def _schedule():
    """Four meetings mirroring the jul26-jan27 registry strip."""
    return pd.DataFrame({
        "meeting_label": ["jul26", "sep26", "oct26", "dec26"],
        "effective_date": pd.to_datetime(
            ["2026-07-29", "2026-09-16", "2026-10-28", "2026-12-09"]),
        "maturity_date": pd.to_datetime(
            ["2026-09-16", "2026-10-28", "2026-12-09", "2027-01-27"]),
    })


def _price_fn(rates_by_eff):
    def fn(eff, mat):
        return rates_by_eff[eff]
    return fn


class TestJumpsFromPeriodRates:
    def test_consecutive_differences_off_the_base(self):
        rates = pd.Series([0.0375, 0.0388, 0.0400])
        jumps = jumps_from_period_rates(rates, base_rate=0.0363)
        np.testing.assert_allclose(jumps.values, [12.0, 13.0, 12.0], atol=1e-9)

    def test_static_basis_cancels_beyond_the_first_jump(self):
        rates = pd.Series([0.0375, 0.0388, 0.0400])
        shifted = rates + 0.0003          # constant overnight basis
        j0 = jumps_from_period_rates(rates, base_rate=0.0363)
        j1 = jumps_from_period_rates(shifted, base_rate=0.0363)
        np.testing.assert_allclose(j0.values[1:], j1.values[1:], atol=1e-9)
        assert j1.iloc[0] == pytest.approx(j0.iloc[0] + 3.0)


class TestFomcPeriodRates:
    def test_prices_only_upcoming_meetings(self):
        rates = {
            datetime.date(2026, 9, 16): 0.0388,
            datetime.date(2026, 10, 28): 0.0399,
            datetime.date(2026, 12, 9): 0.0410,
        }
        frame = fomc_period_rates(
            datetime.date(2026, 7, 31), None, _schedule(),
            price_fn=_price_fn(rates),
        )
        # jul26 (effective 07-29 <= as_of) is the in-progress period: excluded.
        assert list(frame["meeting_label"]) == ["sep26", "oct26", "dec26"]
        np.testing.assert_allclose(frame["rate"], [0.0388, 0.0399, 0.0410])

    def test_pricing_failure_is_nan_not_dropped(self):
        def fn(eff, mat):
            if eff == datetime.date(2026, 10, 28):
                raise ValueError("calendar mismatch")
            return 0.039
        frame = fomc_period_rates(
            datetime.date(2026, 7, 31), None, _schedule(), price_fn=fn)
        assert list(frame["meeting_label"]) == ["sep26", "oct26", "dec26"]
        assert np.isnan(frame["rate"].iloc[1])


class TestSwapMeetingLadder:
    def test_lattice_reproduces_planted_jumps(self):
        rates = {
            datetime.date(2026, 7, 29): 0.0373,   # +10bp off the 3.63 base
            datetime.date(2026, 9, 16): 0.0389,   # +16
            datetime.date(2026, 10, 28): 0.0397,  # +8
            datetime.date(2026, 12, 9): 0.0409,   # +12
        }
        lad = swap_meeting_ladder(
            datetime.date(2026, 7, 27), None, _schedule(), base_rate=0.0363,
            price_fn=_price_fn(rates),
        )
        assert [m.contract for m in lad] == ["jul26", "sep26", "oct26", "dec26"]
        assert [round(m.jump_bp, 6) for m in lad] == [10.0, 16.0, 8.0, 12.0]
        for m in lad:
            # the two-point lattice must reproduce its own jump exactly
            assert m.e_moves * 25.0 == pytest.approx(m.jump_bp, abs=1e-9)
            assert m.support == (0, 1)
            assert not m.stale
        assert lad[0].effective == datetime.date(2026, 7, 29)
        assert lad[0].decision == datetime.date(2026, 7, 28)

    def test_negative_jump_lands_on_the_cut_lattice(self):
        rates = {datetime.date(2026, 7, 29): 0.0343,   # -20bp
                 datetime.date(2026, 9, 16): 0.0338}   # -5 more
        lad = swap_meeting_ladder(
            datetime.date(2026, 7, 1), None, _schedule().head(2),
            base_rate=0.0363, price_fn=_price_fn(rates),
        )
        assert lad[0].support == (-1, 0)
        assert lad[0].q == pytest.approx(0.2)          # P(no move) = 0.2
        assert lad[0].e_moves * 25.0 == pytest.approx(-20.0)

    def test_nan_period_truncates_all_later_meetings(self):
        def fn(eff, mat):
            if eff == datetime.date(2026, 9, 16):
                raise ValueError("boom")
            return 0.0373
        lad = swap_meeting_ladder(
            datetime.date(2026, 7, 1), None, _schedule(), base_rate=0.0363,
            price_fn=fn,
        )
        # sep26 failed -> sep26, oct26, dec26 all dropped; jul26 survives.
        assert [m.contract for m in lad] == ["jul26"]

    def test_first_period_nan_yields_empty_ladder(self):
        def fn(eff, mat):
            raise ValueError("boom")
        lad = swap_meeting_ladder(
            datetime.date(2026, 7, 1), None, _schedule(), base_rate=0.0363,
            price_fn=fn,
        )
        assert lad == []

    def test_same_dataclass_as_the_zq_ladder(self):
        rates = {datetime.date(2026, 7, 29): 0.0373,
                 datetime.date(2026, 9, 16): 0.0389}
        lad = swap_meeting_ladder(
            datetime.date(2026, 7, 1), None, _schedule().head(2),
            base_rate=0.0363, price_fn=_price_fn(rates),
        )
        # the swap path emits the ZQ-side dataclass field-for-field, so
        # everything downstream (atoms, pricer, refit) is source-blind
        m = lad[0]
        assert isinstance(m, MeetingLattice)
        assert (m.effective, m.decision, m.support, m.contract, m.stale) == (
            datetime.date(2026, 7, 29), datetime.date(2026, 7, 28), (0, 1),
            "jul26", False,
        )
        assert m.jump_bp == pytest.approx(10.0)
        assert m.q == pytest.approx(0.4)
        assert m.probs[1] == pytest.approx(0.4)
        assert m.variance_bp2() == pytest.approx(25.0 ** 2 * 0.4 * 0.6)
