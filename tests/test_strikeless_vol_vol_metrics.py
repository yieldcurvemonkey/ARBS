import numpy as np
import pandas as pd
import pytest

from RVUtils.StrikelessVol.conventions import VolQuote
from RVUtils.StrikelessVol.vol_metrics import (
    UNDERLYING_RATE,
    UNDERLYING_SPREAD,
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


def test_spread_vol_detects_rescaling():
    # alternating +2bp/-2bp increments -> known std of 2bp
    idx = pd.date_range("2026-01-01", periods=101, freq="B")
    steps = np.where(np.arange(100) % 2 == 0, 2.0, -2.0)
    spread = pd.Series(np.concatenate([[0.0], np.cumsum(steps)]), index=idx)
    sv = spread_vol_bp_day(spread, window=100)
    # mean of diffs is 0, std of ±2 values is 2.0
    assert sv.iloc[-1] == pytest.approx(2.0, rel=0.02)


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
    # the denominator must be a LABELLED rate vol -- see be_over_realized
    rv = pd.Series([3.0, 4.0])
    rv.attrs["underlying"] = UNDERLYING_RATE
    r = be_over_realized(be, rv)
    assert r.iloc[0] == pytest.approx(0.4333, abs=1e-3)  # the May-2019 15y5y/20y10y case
    assert r.iloc[1] == pytest.approx(1.0)


def test_the_two_builders_label_what_they_were_computed_on():
    rng = np.random.default_rng(3)
    rates = pd.Series(np.cumsum(rng.normal(0, 1e-4, 200)) + 0.04)
    spread = pd.Series(np.cumsum(rng.normal(0, 1.0, 200)) - 50.0)
    assert realized_vol_bp_day(rates, window=63).attrs["underlying"] == UNDERLYING_RATE
    assert spread_vol_bp_day(spread, window=63).attrs["underlying"] == UNDERLYING_SPREAD
    assert realized_vol_bp_day(rates, window=63).attrs["window"] == "63d"


def test_an_unlabelled_denominator_is_refused():
    """The failure mode that actually happened: a hand-rolled rolling std.

    No prose on the builders can intervene when the builders are never called,
    which is why the label is required rather than merely stamped.
    """
    spread = pd.Series(np.cumsum(np.random.default_rng(5).normal(0, 1.0, 200)))
    hand_rolled = spread.diff().rolling(63, min_periods=63).std(ddof=1)
    with pytest.raises(ValueError, match="carries no `underlying` label"):
        be_over_realized(pd.Series(4.0, index=spread.index), hand_rolled)


def test_a_spread_vol_denominator_is_refused_unless_it_is_declared():
    spread = pd.Series(np.cumsum(np.random.default_rng(7).normal(0, 1.0, 200)))
    slope_vol = spread_vol_bp_day(spread, window=63)
    be = pd.Series(4.0, index=spread.index)
    with pytest.raises(ValueError, match="category error|is a 'spread' vol"):
        be_over_realized(be, slope_vol)
    # ... and the deliberate slope diagnostic stays available, spelled out
    out = be_over_realized(be, slope_vol, denominator=UNDERLYING_SPREAD)
    assert out.notna().sum() > 0


def test_a_declared_denominator_that_contradicts_the_label_is_refused():
    rng = np.random.default_rng(11)
    rates = pd.Series(np.cumsum(rng.normal(0, 1e-4, 200)) + 0.04)
    rate_vol = realized_vol_bp_day(rates, window=63)
    be = pd.Series(4.0, index=rates.index)
    with pytest.raises(ValueError, match="will not guess which"):
        be_over_realized(be, rate_vol, denominator=UNDERLYING_SPREAD)
    assert be_over_realized(be, rate_vol, denominator=UNDERLYING_RATE).notna().sum() > 0


def test_the_slope_denominator_systematically_overstates_richness():
    """Not an opinion: on the same panel the slope vol is the smaller number,
    so the ratio built on it is uniformly larger and reads richer."""
    rng = np.random.default_rng(13)
    level = np.cumsum(rng.normal(0, 4e-4, 400))
    rates = pd.Series(level + 0.04)
    spread = pd.Series(np.cumsum(rng.normal(0, 0.8, 400)) - 50.0)
    be = pd.Series(4.0, index=rates.index)
    rate_ratio = be_over_realized(be, realized_vol_bp_day(rates, window=63))
    slope_ratio = be_over_realized(be, spread_vol_bp_day(spread, window=63),
                                   denominator=UNDERLYING_SPREAD)
    both = pd.concat([rate_ratio.rename("r"), slope_ratio.rename("s")],
                     axis=1).dropna()
    assert len(both) > 100
    assert (both["s"] > both["r"]).mean() > 0.95


def test_ratio_is_nan_for_non_positive_denominator():
    r = be_over_implied(pd.Series([2.0, 2.0]), pd.Series([0.0, -1.5]))
    assert np.isnan(r.iloc[0])  # zero denominator
    assert np.isnan(r.iloc[1])  # negative denominator


def test_realized_quote_raises_on_insufficient_history():
    idx = pd.date_range("2026-01-01", periods=5, freq="B")
    rates = pd.Series(np.linspace(0.04, 0.041, 5), index=idx)
    with pytest.raises(ValueError, match="not enough observations"):
        realized_quote(rates, 63, underlying="test")
