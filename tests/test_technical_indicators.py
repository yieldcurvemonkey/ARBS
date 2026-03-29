import numpy as np
import pandas as pd

from BT.signals.technical_indicators import (
    bollinger_signal,
    macd_signal,
    moving_average_crossover_signal,
    rsi_signal,
)


def test_moving_average_crossover_signal_uses_next_bar_execution():
    index = pd.date_range("2026-01-01", periods=6, freq="D")
    series = pd.Series([1.0, 2.0, 3.0, 4.0, 3.0, 2.0], index=index, name="rate")

    result = moving_average_crossover_signal(series, fast_window=2, slow_window=3)

    assert list(result.indicator_frame.columns) == ["fast_ma", "slow_ma", "spread"]
    assert result.desired_position.iloc[:2].isna().all()
    assert result.desired_position.iloc[2] == 1.0
    assert result.desired_position.iloc[-1] == -1.0
    assert result.execution_position.iloc[:3].isna().all()
    assert result.execution_position.iloc[3] == 1.0
    assert result.execution_position.iloc[-1] == 1.0


def test_rsi_signal_supports_panel_inputs_and_thresholds():
    index = pd.date_range("2026-01-01", periods=7, freq="D")
    panel = pd.DataFrame(
        {
            "up": [1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0],
            "down": [7.0, 6.0, 5.0, 4.0, 3.0, 2.0, 1.0],
        },
        index=index,
    )

    result = rsi_signal(panel, window=3, lower=30.0, upper=70.0)

    assert isinstance(result.desired_position, pd.DataFrame)
    assert list(result.desired_position.columns) == ["up", "down"]
    assert result.desired_position.iloc[:2].isna().all().all()
    assert result.desired_position.iloc[-1]["up"] == -1.0
    assert result.desired_position.iloc[-1]["down"] == 1.0
    assert ("rsi", "up") in result.indicator_frame.columns


def test_bollinger_signal_flags_band_breaks_and_reverts_to_neutral():
    index = pd.date_range("2026-01-01", periods=7, freq="D")
    series = pd.Series([10.0, 10.0, 10.0, 10.0, 10.0, 20.0, 10.0], index=index, name="spread")

    result = bollinger_signal(series, window=5, num_std=1.0)

    assert result.desired_position.iloc[:4].isna().all()
    assert result.desired_position.iloc[5] == -1.0
    assert result.desired_position.iloc[6] == 0.0
    assert result.execution_position.iloc[6] == -1.0
    assert list(result.indicator_frame.columns) == ["basis", "upper_band", "lower_band", "band_width"]


def test_macd_signal_produces_discrete_cross_signals():
    index = pd.date_range("2026-01-01", periods=12, freq="D")
    series = pd.Series([1.0, 1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 5.0, 4.0, 3.0, 2.0, 1.0], index=index, name="curve")

    result = macd_signal(series, fast_span=2, slow_span=4, signal_span=2)

    desired = result.desired_position.dropna()
    assert set(desired.unique()).issubset({-1.0, 0.0, 1.0})
    assert 1.0 in set(desired.tolist())
    assert -1.0 in set(desired.tolist())
    assert np.isnan(result.execution_position.iloc[0])
    assert list(result.indicator_frame.columns) == [
        "ema_fast",
        "ema_slow",
        "macd_line",
        "signal_line",
        "histogram",
    ]
