from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd


MLFINLAB_ROOT = Path(__file__).resolve().parents[1] / "RVUtils" / "mlfinlab"
if str(MLFINLAB_ROOT) not in sys.path:
    sys.path.insert(0, str(MLFINLAB_ROOT))


def test_mlfinlab_imports_are_repo_friendly():
    import mlfinlab
    import mlfinlab.data_structures as data_structures
    import mlfinlab.networks as networks

    assert mlfinlab.__version__ == "0.4.1"
    assert "datasets" in dir(mlfinlab)
    assert "get_tick_bars" in dir(data_structures)
    assert "Graph" in dir(networks)


def test_mlfinlab_loaders_read_packaged_csv_data():
    from mlfinlab.datasets import (
        load_dollar_bar_sample,
        load_stock_prices,
        load_tick_sample,
    )

    stock_prices = load_stock_prices()
    tick_sample = load_tick_sample()
    dollar_bars = load_dollar_bar_sample()

    assert isinstance(stock_prices.index, pd.DatetimeIndex)
    assert list(stock_prices.columns[:3]) == ["EEM", "EWG", "TIP"]
    assert "SPY" in stock_prices.columns
    assert isinstance(tick_sample.index, pd.DatetimeIndex)
    assert list(tick_sample.columns) == ["Price", "Volume"]
    assert isinstance(dollar_bars.index, pd.DatetimeIndex)
    assert {"open", "high", "low", "close"}.issubset(dollar_bars.columns)


def test_mlfinlab_legacy_filters_emit_events():
    from mlfinlab.datasets import load_stock_prices
    from mlfinlab.filters import cusum_filter, z_score_filter

    close = load_stock_prices()["SPY"].dropna()
    cusum_events = cusum_filter(close, threshold=2.0)
    z_score_events = z_score_filter(close, mean_window=20, std_window=20, z_score=2.0)

    assert isinstance(cusum_events, pd.DatetimeIndex)
    assert isinstance(z_score_events, pd.DatetimeIndex)
    assert len(cusum_events) > 0
    assert len(z_score_events) > 0
    assert cusum_events.is_monotonic_increasing
    assert z_score_events.is_monotonic_increasing
