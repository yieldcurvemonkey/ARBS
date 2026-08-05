import numpy as np
import pandas as pd
import pytest

from RVUtils.StrikelessVol.conventions import VolQuote
from RVUtils.StrikelessVol.vol_metrics import (
    be_over_implied,
    be_over_realized,
    realized_quote,
    realized_vol_bp_day,
    spread_vol_bp_day,
)


def test_realized_vol_of_a_known_series():
    # daily changes of exactly 5bp, alternating sign -> std of |5bp| series
    idx = pd.date_range("2026-01-01", periods=101, freq="B")
    steps = np.where(np.arange(100) % 2 == 0, 5e-4, -5e-4)
    rates = pd.Series(np.concatenate([[0.04], 0.04 + np.cumsum(steps)]), index=idx)
    rv = realized_vol_bp_day(rates, window=100)
    assert rv.iloc[-1] == pytest.approx(5.0, rel=0.02)


def test_spread_vol_is_computed_on_bp_input_without_rescaling():
    idx = pd.date_range("2026-01-01", periods=101, freq="B")
    spread = pd.Series(np.arange(101, dtype=float) * 1.65, index=idx)
    sv = spread_vol_bp_day(spread, window=100)
    assert sv.iloc[-1] == pytest.approx(0.0, abs=1e-9)  # constant increments


def test_realized_quote_is_labelled():
    idx = pd.date_range("2026-01-01", periods=70, freq="B")
    rates = pd.Series(np.linspace(0.04, 0.045, 70), index=idx)
    q = realized_quote(rates, 63, underlying="USD 20Y10Y forward par rate")
    assert isinstance(q, VolQuote)
    assert q.measure == "realized"
    assert q.window == "63d"
    assert "20Y10Y" in q.underlying


def test_ratios_below_one_mean_embedded_vol_is_cheap():
    be = pd.Series([1.3, 4.0])
    rv = pd.Series([3.0, 4.0])
    r = be_over_realized(be, rv)
    assert r.iloc[0] == pytest.approx(0.4333, abs=1e-3)  # the May-2019 15y5y/20y10y case
    assert r.iloc[1] == pytest.approx(1.0)


def test_ratio_is_nan_when_the_denominator_is_zero():
    r = be_over_implied(pd.Series([2.0]), pd.Series([0.0]))
    assert np.isnan(r.iloc[0])
