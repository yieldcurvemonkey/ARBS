"""pandas-ta-backed technical indicator signal builders."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd
import pandas_ta as ta


@dataclass(frozen=True)
class TechnicalIndicatorSignalResult:
    raw_series: pd.Series | pd.DataFrame
    indicator_frame: pd.DataFrame
    desired_position: pd.Series | pd.DataFrame
    execution_position: pd.Series | pd.DataFrame


def moving_average_crossover_signal(
    raw_series: pd.Series | pd.DataFrame,
    *,
    fast_window: int,
    slow_window: int,
) -> TechnicalIndicatorSignalResult:
    """Return discrete crossover positions from fast and slow simple moving averages."""
    if fast_window <= 0 or slow_window <= 0:
        raise ValueError("Moving-average windows must be positive.")
    if fast_window >= slow_window:
        raise ValueError("fast_window must be smaller than slow_window.")

    raw, was_series = _coerce_numeric_input(raw_series)
    fast_ma = _apply_series_indicator(raw, lambda series: ta.sma(series, length=fast_window))
    slow_ma = _apply_series_indicator(raw, lambda series: ta.sma(series, length=slow_window))
    spread = fast_ma - slow_ma

    desired = _empty_positions_like(raw)
    valid = fast_ma.notna() & slow_ma.notna()
    desired = desired.mask(valid & (spread > 0.0), 1.0)
    desired = desired.mask(valid & (spread < 0.0), -1.0)
    desired = desired.mask(valid & (spread == 0.0), 0.0)

    indicator_frame = _build_indicator_frame(
        was_series=was_series,
        components={
            "fast_ma": fast_ma,
            "slow_ma": slow_ma,
            "spread": spread,
        },
    )
    return _finalize_signal_result(
        raw_input=raw_series,
        raw_frame=raw,
        indicator_frame=indicator_frame,
        desired_frame=desired,
        was_series=was_series,
    )


def rsi_signal(
    raw_series: pd.Series | pd.DataFrame,
    *,
    window: int = 14,
    lower: float = 30.0,
    upper: float = 70.0,
) -> TechnicalIndicatorSignalResult:
    """Return discrete positions from the relative-strength index."""
    if window <= 0:
        raise ValueError("window must be positive.")
    if lower >= upper:
        raise ValueError("lower threshold must be below upper threshold.")

    raw, was_series = _coerce_numeric_input(raw_series)
    delta = raw.diff()
    gains = delta.clip(lower=0.0)
    losses = -delta.clip(upper=0.0)
    avg_gain = _apply_series_indicator(gains, lambda series: ta.rma(series, length=window))
    avg_loss = _apply_series_indicator(losses, lambda series: ta.rma(series, length=window))
    rsi = _apply_series_indicator(raw, lambda series: ta.rsi(series, length=window))
    warmup_mask = _valid_observation_counts(raw) < int(window)
    avg_gain = avg_gain.mask(warmup_mask)
    avg_loss = avg_loss.mask(warmup_mask)
    rsi = rsi.mask(warmup_mask)

    desired = _empty_positions_like(raw)
    valid = rsi.notna()
    desired = desired.mask(valid & (rsi < lower), 1.0)
    desired = desired.mask(valid & (rsi > upper), -1.0)
    desired = desired.mask(valid & (rsi >= lower) & (rsi <= upper), 0.0)

    indicator_frame = _build_indicator_frame(
        was_series=was_series,
        components={
            "rsi": rsi,
            "avg_gain": avg_gain,
            "avg_loss": avg_loss,
        },
    )
    return _finalize_signal_result(
        raw_input=raw_series,
        raw_frame=raw,
        indicator_frame=indicator_frame,
        desired_frame=desired,
        was_series=was_series,
    )


def bollinger_signal(
    raw_series: pd.Series | pd.DataFrame,
    *,
    window: int = 20,
    num_std: float = 2.0,
) -> TechnicalIndicatorSignalResult:
    """Return discrete positions from Bollinger band breaks."""
    if window <= 0:
        raise ValueError("window must be positive.")
    if num_std <= 0.0:
        raise ValueError("num_std must be positive.")

    raw, was_series = _coerce_numeric_input(raw_series)
    lower_band = _empty_indicator_like(raw)
    basis = _empty_indicator_like(raw)
    upper_band = _empty_indicator_like(raw)
    for column in raw.columns:
        bands = ta.bbands(raw[column], length=window, std=float(num_std))
        if bands is None or bands.empty:
            continue
        bands = bands.reindex(raw.index)
        lower_band[column] = pd.to_numeric(bands.iloc[:, 0], errors="coerce")
        basis[column] = pd.to_numeric(bands.iloc[:, 1], errors="coerce")
        upper_band[column] = pd.to_numeric(bands.iloc[:, 2], errors="coerce")

    desired = _empty_positions_like(raw)
    prior_lower = lower_band.shift(1)
    prior_upper = upper_band.shift(1)
    valid = prior_lower.notna() & prior_upper.notna()
    desired = desired.mask(valid & (raw < prior_lower), 1.0)
    desired = desired.mask(valid & (raw > prior_upper), -1.0)
    desired = desired.mask(valid & (raw >= prior_lower) & (raw <= prior_upper), 0.0)

    indicator_frame = _build_indicator_frame(
        was_series=was_series,
        components={
            "basis": basis,
            "upper_band": upper_band,
            "lower_band": lower_band,
            "band_width": upper_band - lower_band,
        },
    )
    return _finalize_signal_result(
        raw_input=raw_series,
        raw_frame=raw,
        indicator_frame=indicator_frame,
        desired_frame=desired,
        was_series=was_series,
    )


def macd_signal(
    raw_series: pd.Series | pd.DataFrame,
    *,
    fast_span: int = 12,
    slow_span: int = 26,
    signal_span: int = 9,
) -> TechnicalIndicatorSignalResult:
    """Return discrete positions from MACD line versus signal line."""
    if fast_span <= 0 or slow_span <= 0 or signal_span <= 0:
        raise ValueError("MACD spans must be positive.")
    if fast_span >= slow_span:
        raise ValueError("fast_span must be smaller than slow_span.")

    raw, was_series = _coerce_numeric_input(raw_series)
    ema_fast = _apply_series_indicator(raw, lambda series: ta.ema(series, length=fast_span))
    ema_slow = _apply_series_indicator(raw, lambda series: ta.ema(series, length=slow_span))
    macd_line = _empty_indicator_like(raw)
    signal_line = _empty_indicator_like(raw)
    histogram = _empty_indicator_like(raw)
    for column in raw.columns:
        macd_frame = ta.macd(raw[column], fast=fast_span, slow=slow_span, signal=signal_span)
        if macd_frame is None or macd_frame.empty:
            continue
        macd_frame = macd_frame.reindex(raw.index)
        macd_line[column] = pd.to_numeric(macd_frame.iloc[:, 0], errors="coerce")
        histogram[column] = pd.to_numeric(macd_frame.iloc[:, 1], errors="coerce")
        signal_line[column] = pd.to_numeric(macd_frame.iloc[:, 2], errors="coerce")

    desired = _empty_positions_like(raw)
    valid = signal_line.notna()
    desired = desired.mask(valid & (macd_line > signal_line), 1.0)
    desired = desired.mask(valid & (macd_line < signal_line), -1.0)
    desired = desired.mask(valid & (macd_line == signal_line), 0.0)

    indicator_frame = _build_indicator_frame(
        was_series=was_series,
        components={
            "ema_fast": ema_fast,
            "ema_slow": ema_slow,
            "macd_line": macd_line,
            "signal_line": signal_line,
            "histogram": histogram,
        },
    )
    return _finalize_signal_result(
        raw_input=raw_series,
        raw_frame=raw,
        indicator_frame=indicator_frame,
        desired_frame=desired,
        was_series=was_series,
    )


def _coerce_numeric_input(raw_series: pd.Series | pd.DataFrame) -> tuple[pd.DataFrame, bool]:
    if isinstance(raw_series, pd.Series):
        column_name = str(raw_series.name or "value")
        series = pd.to_numeric(raw_series.sort_index(), errors="coerce")
        return series.to_frame(name=column_name), True
    if isinstance(raw_series, pd.DataFrame):
        frame = raw_series.sort_index().copy()
        for column in frame.columns:
            frame[column] = pd.to_numeric(frame[column], errors="coerce")
        return frame, False
    raise TypeError(f"Expected Series or DataFrame, got {type(raw_series)!r}")


def _empty_positions_like(frame: pd.DataFrame) -> pd.DataFrame:
    return pd.DataFrame(np.nan, index=frame.index, columns=frame.columns, dtype=float)


def _empty_indicator_like(frame: pd.DataFrame) -> pd.DataFrame:
    return pd.DataFrame(np.nan, index=frame.index, columns=frame.columns, dtype=float)


def _apply_series_indicator(
    frame: pd.DataFrame,
    indicator_fn: Any,
) -> pd.DataFrame:
    output = _empty_indicator_like(frame)
    for column in frame.columns:
        values = indicator_fn(frame[column])
        if values is None:
            continue
        output[column] = pd.to_numeric(pd.Series(values).reindex(frame.index), errors="coerce")
    return output


def _valid_observation_counts(frame: pd.DataFrame) -> pd.DataFrame:
    counts = frame.notna().astype(int)
    return counts.cumsum()


def _build_indicator_frame(
    *,
    was_series: bool,
    components: dict[str, pd.DataFrame],
) -> pd.DataFrame:
    if was_series:
        return pd.DataFrame(
            {
                name: component.iloc[:, 0]
                for name, component in components.items()
            },
            index=next(iter(components.values())).index,
        )
    return pd.concat(components, axis=1)


def _restore_shape(frame: pd.DataFrame, *, was_series: bool, original: pd.Series | pd.DataFrame) -> pd.Series | pd.DataFrame:
    if not was_series:
        return frame
    column_name = str(original.name or frame.columns[0])
    restored = frame.iloc[:, 0].copy()
    restored.name = column_name
    return restored


def _finalize_signal_result(
    *,
    raw_input: pd.Series | pd.DataFrame,
    raw_frame: pd.DataFrame,
    indicator_frame: pd.DataFrame,
    desired_frame: pd.DataFrame,
    was_series: bool,
) -> TechnicalIndicatorSignalResult:
    execution_frame = desired_frame.shift(1)
    return TechnicalIndicatorSignalResult(
        raw_series=_restore_shape(raw_frame, was_series=was_series, original=raw_input),
        indicator_frame=indicator_frame,
        desired_position=_restore_shape(desired_frame, was_series=was_series, original=raw_input),
        execution_position=_restore_shape(execution_frame, was_series=was_series, original=raw_input),
    )
