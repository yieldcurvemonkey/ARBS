"""Tests for the linear strip-peak-fade backtests."""
import datetime
import pandas as pd
import numpy as np
import pytest

from RVUtils.StripPeak.peak_tracker import identify_peak
from RVUtils.StripPeak.linear_backtest import (
    backtest_spread,
    backtest_butterfly,
    summary_stats,
)


def _make_strip_with_decay() -> pd.DataFrame:
    """10-day strip where the peak decays: M27 starts at 4.20 and falls to 4.10."""
    contracts = ["SR3U26", "SR3Z26", "SR3H27", "SR3M27", "SR3U27", "SR3Z27"]
    n = 10
    dates = pd.date_range("2026-01-05", periods=n, freq="B").date
    base = np.array([3.80, 3.90, 4.00, 4.20, 4.05, 3.95])
    # decay: M27 falls by 1bp/day, neighbors stay flat
    data = {}
    for j, c in enumerate(contracts):
        if c == "SR3M27":
            data[c] = [base[j] - 0.01 * i for i in range(n)]
        else:
            data[c] = [base[j]] * n
    return pd.DataFrame(data, index=dates)


def test_backtest_spread_positive_pnl_on_decay():
    """When the peak decays, the spread (sell peak / buy peak+1) should profit."""
    strip = _make_strip_with_decay()
    peak = identify_peak(strip)
    bt = backtest_spread(strip, peak, hold_days=5, cost_bp=0.0)
    assert len(bt) > 0
    # peak decays 5bp over 5 days — spread should profit
    assert bt["pnl_bp"].mean() > 0


def test_backtest_butterfly_positive_pnl_on_decay():
    """When the peak decays, the butterfly should profit."""
    strip = _make_strip_with_decay()
    peak = identify_peak(strip)
    bt = backtest_butterfly(strip, peak, hold_days=5, cost_bp=0.0)
    assert len(bt) > 0
    assert bt["pnl_bp"].mean() > 0


def test_backtest_spread_cost_reduces_pnl():
    strip = _make_strip_with_decay()
    peak = identify_peak(strip)
    bt_free = backtest_spread(strip, peak, hold_days=5, cost_bp=0.0)
    bt_cost = backtest_spread(strip, peak, hold_days=5, cost_bp=2.0)
    assert bt_cost["pnl_bp"].mean() < bt_free["pnl_bp"].mean()


def test_summary_stats_has_required_keys():
    strip = _make_strip_with_decay()
    peak = identify_peak(strip)
    bt = backtest_spread(strip, peak, hold_days=5, cost_bp=0.0)
    stats = summary_stats(bt)
    for key in ["n_trades", "hit_rate", "avg_pnl_bp", "sharpe", "total_pnl_bp"]:
        assert key in stats
