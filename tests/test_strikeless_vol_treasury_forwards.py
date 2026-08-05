import datetime as dt

import numpy as np
import pandas as pd
import pytest

from RVUtils.StrikelessVol.treasury_forwards import (
    forward_par_rate,
    par_to_discount,
    treasury_forward_panel,
)
from RVUtils.StrikelessVol.universe import ForwardLeg


def _analytic_curve(rate, ttms, freq=2):
    """Discount factors and par yields of a flat continuously-quoted curve."""
    dfs = 1.0 / (1.0 + rate / freq) ** (ttms * freq)
    return dfs


def test_bootstrap_round_trips_a_flat_par_curve():
    ttms = np.arange(0.5, 40.5, 0.5)
    par = np.full_like(ttms, 0.04)
    dfs = par_to_discount(ttms, par, freq=2)
    expected = _analytic_curve(0.04, ttms)
    assert np.allclose(dfs, expected, atol=1e-10)


def test_forward_par_rate_of_a_flat_curve_is_the_flat_rate():
    ttms = np.arange(0.5, 40.5, 0.5)
    dfs = par_to_discount(ttms, np.full_like(ttms, 0.04), freq=2)
    fwd = forward_par_rate(ttms, dfs, fwd_years=10, tail_years=10)
    assert fwd == pytest.approx(0.04, abs=1e-8)


def test_forward_of_an_upward_sloping_curve_exceeds_the_spot_rate():
    ttms = np.arange(0.5, 40.5, 0.5)
    par = 0.03 + 0.0005 * ttms
    dfs = par_to_discount(ttms, par, freq=2)
    fwd = forward_par_rate(ttms, dfs, fwd_years=10, tail_years=10)
    spot20 = float(np.interp(20.0, ttms, par))
    assert fwd > spot20


def test_discount_factors_are_monotone_decreasing():
    ttms = np.arange(0.5, 40.5, 0.5)
    dfs = par_to_discount(ttms, 0.03 + 0.0005 * ttms, freq=2)
    assert np.all(np.diff(dfs) < 0)


def test_bootstrap_rejects_an_unsorted_grid():
    with pytest.raises(ValueError):
        par_to_discount(np.array([2.0, 1.0]), np.array([0.04, 0.04]))


class _FakeSpline:
    """Minimal stand-in for CashSpline: a flat curve plus an rmse attribute."""

    def __init__(self, rate: float, rmse: float):
        self.rate = rate
        self.rmse = rmse

    def yield_at(self, ttm):
        return self.rate


class _RaisingSpline:
    """A spline whose yield_at always raises -- simulates a compute failure
    distinct from a bad-RMSE fit (I2)."""

    rmse = 2.0  # a fine RMSE reading -- the guard must NOT be what excludes this

    def yield_at(self, ttm):
        raise ValueError("simulated forward-computation failure")


def test_treasury_forward_panel_excludes_bad_fit_days_and_reports_the_count_and_dates():
    """A spline whose own fit RMSE is anomalously high (see the module
    docstring's "RMSE guard" -- found on real 2021-2026 data: 13 dates with
    RMSE 22.5bp-80,000+bp against a normal ~2bp) does not represent its
    input bonds and must not silently corrupt the forward panel. I1: the
    exact excluded (date, rmse) pairs must be recoverable, not just a count.
    """
    legs = [ForwardLeg("10Y", "10Y"), ForwardLeg("20Y", "10Y")]
    good_date = dt.date(2024, 1, 2)
    bad_date = dt.date(2024, 1, 3)
    spline_by_date = {
        good_date: _FakeSpline(rate=4.0, rmse=2.5),   # normal fit quality
        bad_date: _FakeSpline(rate=4.0, rmse=43.6),   # matches a real corrupted date's RMSE
    }
    panel = treasury_forward_panel(spline_by_date, legs)
    assert list(panel.index.date) == [good_date]
    assert panel.attrs["treasury_excluded_bad_fit_days"] == 1
    assert panel.attrs["treasury_excluded_bad_fit_dates"] == [(bad_date, 43.6)]


def test_treasury_forward_panel_counts_compute_errors_separately_from_bad_fits():
    """I2: a date whose forward computation itself fails (yield_at raising)
    must be excluded, logged, AND counted on its own attrs key -- not
    silently dropped through the bare except with no counter moved.
    """
    legs = [ForwardLeg("10Y", "10Y"), ForwardLeg("20Y", "10Y")]
    good_date = dt.date(2024, 1, 2)
    error_date = dt.date(2024, 1, 3)
    spline_by_date = {
        good_date: _FakeSpline(rate=4.0, rmse=2.5),
        error_date: _RaisingSpline(),
    }
    panel = treasury_forward_panel(spline_by_date, legs)
    assert list(panel.index.date) == [good_date]
    assert panel.attrs["treasury_excluded_compute_errors"] == 1
    # the compute-error date must NOT also show up as an RMSE-guard exclusion
    assert panel.attrs["treasury_excluded_bad_fit_days"] == 0
    assert panel.attrs["treasury_excluded_bad_fit_dates"] == []


def test_treasury_forward_panel_keeps_a_spline_with_no_rmse_reading():
    """I3: rmse=None (or NaN) fails OPEN -- the guard treats a missing
    fit-quality reading as "unknown", not "assume the worst", so it cannot
    silently exclude an entire panel if some future spline stops populating
    rmse. Pinned by this test, not merely documented.
    """
    legs = [ForwardLeg("10Y", "10Y"), ForwardLeg("20Y", "10Y")]
    none_date = dt.date(2024, 1, 2)
    nan_date = dt.date(2024, 1, 3)
    spline_by_date = {
        none_date: _FakeSpline(rate=4.0, rmse=None),
        nan_date: _FakeSpline(rate=4.0, rmse=float("nan")),
    }
    panel = treasury_forward_panel(spline_by_date, legs)
    assert sorted(panel.index.date) == [none_date, nan_date]
    assert panel.attrs["treasury_excluded_bad_fit_days"] == 0


def test_treasury_forward_panel_keeps_a_borderline_good_fit():
    """rmse_guard_bp=10.0 sits between the normal group's 99th percentile
    (3.62bp) and the corrupted group's minimum (22.5bp) -- a fit at 5bp,
    inside that gap but still far below any corrupted date, must be kept.
    """
    legs = [ForwardLeg("10Y", "10Y"), ForwardLeg("20Y", "10Y")]
    d = dt.date(2024, 1, 2)
    spline_by_date = {d: _FakeSpline(rate=4.0, rmse=5.0)}
    panel = treasury_forward_panel(spline_by_date, legs)
    assert list(panel.index.date) == [d]
    assert panel.attrs["treasury_excluded_bad_fit_days"] == 0


def test_treasury_forward_panel_reports_zero_excluded_on_the_empty_path():
    legs = [ForwardLeg("10Y", "10Y"), ForwardLeg("20Y", "10Y")]
    panel = treasury_forward_panel({}, legs)
    assert panel.empty
    assert panel.attrs["treasury_excluded_bad_fit_days"] == 0
