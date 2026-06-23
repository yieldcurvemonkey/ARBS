"""Tests for plt_timeseries new indicator kinds (Task 9)."""
import matplotlib
matplotlib.use("Agg")

import numpy as np
import pandas as pd

from RVUtils.plt_timeseries import make_secondary_axis_plot


def _s(n=300, seed=0):
    rng = np.random.default_rng(seed)
    idx = pd.date_range("2023-01-02", periods=n, freq="B")
    return pd.Series(np.cumsum(rng.standard_normal(n)) * 0.1 + 3.0, index=idx, name="x")


def test_percentile_helper_matches_rolling_rank():
    s = _s()
    plot, fig, ax, ax2, legend = make_secondary_axis_plot()
    pf = plot.add_indicator_defs["percentile"]
    got = pf(s, 60)
    exp = s.rolling(60).rank(pct=True)
    pd.testing.assert_series_equal(got.dropna(), exp.dropna())


def test_new_indicators_build_without_error_matplotlib():
    s = _s()
    fitted = s.rolling(20).mean()
    plot, fig, ax, ax2, legend = make_secondary_axis_plot(engine="matplotlib")
    plot(
        s,
        indicators=[
            {"kind": "percentile", "window": 60, "hide": True},
            {"kind": "zbands", "entry": 2, "stop": 3, "hide": True},
            {"kind": "fair_value", "series": fitted},
        ],
    )
    legend(show_date=True)
    assert len(plot.state["hidden_meta"]) >= 1  # percentile + zbands captured


def test_fair_value_overlay_plotly_adds_trace():
    s = _s()
    fitted = s.rolling(20).mean()
    plot, fig, ax, ax2, legend = make_secondary_axis_plot(engine="plotly")
    plot(s, which="left", indicators=[{"kind": "fair_value", "series": fitted, "label": "FV"}])
    names = [tr.name for tr in fig.data]
    assert "FV" in names
