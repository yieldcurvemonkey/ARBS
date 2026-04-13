"""
Volume regime analysis: spike detection, event context, and seasonality.

Identifies abnormal trading days via rolling z-scores and maps them
to calendar events (FOMC, quarter-end, IMM roll).
"""

from __future__ import annotations

import datetime
from typing import List, Sequence

import pandas as pd

from .filters import rolling_zscore


# ---------------------------------------------------------------------------
# Volume spike detection
# ---------------------------------------------------------------------------


def detect_volume_spikes(
    daily_series: pd.Series,
    window: int = 20,
    threshold: float = 2.0,
) -> pd.DataFrame:
    """Flag days whose DV01 deviates significantly from a rolling baseline.

    Computes a rolling z-score over *daily_series* and marks any date
    whose absolute z-score exceeds *threshold* as a spike.

    Args:
        daily_series: Daily DV01 series indexed by date.
        window: Rolling window size for mean/std calculation.
        threshold: Absolute z-score cutoff for spike detection.

    Returns:
        DataFrame with columns ``[dv01, z_score, is_spike]``, indexed by
        date.  Rows with insufficient history for the rolling window are
        dropped.
    """
    z = rolling_zscore(daily_series, window=window)
    result = pd.DataFrame({
        "dv01": daily_series,
        "z_score": z,
    })
    result = result.dropna(subset=["z_score"])
    result["is_spike"] = result["z_score"].abs() > threshold
    return result


# ---------------------------------------------------------------------------
# Spike event-context classification
# ---------------------------------------------------------------------------


def classify_spike_context(
    date: object,
    fomc_dates: Sequence[datetime.date],
    qe_dates: Sequence[datetime.date],
    imm_dates: Sequence[datetime.date],
    days_proximity: int = 1,
) -> str:
    """Return comma-separated event tags for a given date.

    Checks whether *date* falls on (or within *days_proximity* of) an
    FOMC meeting, quarter-end, or IMM roll date.

    Args:
        date: The date to classify (``datetime.date`` or Timestamp).
        fomc_dates: List of FOMC meeting dates.
        qe_dates: List of quarter-end dates.
        imm_dates: List of IMM roll dates.
        days_proximity: Number of calendar days around an event to flag
            as "near" (e.g. ``FOMC+-1``).

    Returns:
        Comma-separated string of event tags (e.g. ``"FOMC, Quarter-End"``),
        or ``"None"`` if no events match.
    """
    d = date.date() if hasattr(date, "date") else date
    tags: List[str] = []

    if d in fomc_dates:
        tags.append("FOMC")
    if d in qe_dates:
        tags.append("Quarter-End")
    if d in imm_dates:
        tags.append("IMM Roll")

    # Check +/- days_proximity
    for event_dates, label in [(fomc_dates, "FOMC\u00b11"), (qe_dates, "QE\u00b11")]:
        for ed in event_dates:
            if 0 < abs((d - ed).days) <= days_proximity:
                tags.append(label)
                break

    return ", ".join(tags) if tags else "None"


# ---------------------------------------------------------------------------
# Seasonality heatmap pivot
# ---------------------------------------------------------------------------

_WEEKDAY_ORDER: List[str] = [
    "Monday", "Tuesday", "Wednesday", "Thursday", "Friday",
]
_MONTH_ORDER: List[str] = [
    "January", "February", "March", "April", "May", "June",
    "July", "August", "September", "October", "November", "December",
]


def seasonality_heatmap_data(
    df: pd.DataFrame,
    date_col: str = "execution_date",
    value_col: str = "dv01",
) -> pd.DataFrame:
    """Build a weekday-by-month pivot of mean daily values.

    Useful as input for a ``seaborn.heatmap`` showing intra-week and
    seasonal volume patterns.

    Args:
        df: DataFrame with at least a date column and a numeric value
            column.
        date_col: Column containing execution dates (coerced to
            ``datetime``).
        value_col: Column to aggregate (typically ``"dv01"``).

    Returns:
        Pivot table with weekdays as rows (Mon--Fri) and months as
        columns (Jan--Dec), values being the mean daily total.
    """
    tmp = df.copy()
    tmp["_dt"] = pd.to_datetime(tmp[date_col])
    tmp["_weekday"] = tmp["_dt"].dt.day_name()
    tmp["_month"] = tmp["_dt"].dt.month_name()

    daily = (
        tmp
        .groupby([date_col, "_weekday", "_month"])[value_col]
        .sum()
        .reset_index()
    )

    pivot = daily.pivot_table(
        index="_weekday",
        columns="_month",
        values=value_col,
        aggfunc="mean",
    )

    # Re-order rows/columns to calendar order
    pivot = pivot.reindex(
        index=[d for d in _WEEKDAY_ORDER if d in pivot.index],
        columns=[m for m in _MONTH_ORDER if m in pivot.columns],
    )
    return pivot
