"""Notional/effective-date schedule parsing for SDR analytics.

Depends on ``SDRUtils.core.parsing.parse_schedule`` (Phase 1) to split
the semicolon-delimited schedule cells ([#33]-[#40]) into typed lists.
Part 43 truncates public schedules to the first 10 entries per §43.4(d);
trades with > 10 steps surface via ``schedule_truncated``.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, List, Optional

import pandas as pd

from SDRUtils.core.parsing import parse_schedule

P43_SCHEDULE_MAX_ROWS = 10


@dataclass(frozen=True)
class ScheduleInfo:
    """Parsed schedule metrics for a single row."""

    notional_series: List[float]
    date_series: List[str]
    row_count: int
    truncated: bool


def extract_schedule(
    notional_cell: Any,
    date_cell: Any,
) -> ScheduleInfo:
    """Parse a ``;``-delimited schedule pair into a ScheduleInfo record.

    Args:
        notional_cell: Value from [#34] / [#38] Notional amount in effect
            on associated effective date-Leg 1/2.
        date_cell: Value from [#33] / [#37] associated effective dates.

    Returns:
        ScheduleInfo with parsed series, row count, and truncation flag.
    """
    notionals_raw = parse_schedule(notional_cell)
    dates_raw = parse_schedule(date_cell)

    notional_series: List[float] = []
    for v in notionals_raw:
        try:
            notional_series.append(float(v))
        except (TypeError, ValueError):
            continue

    date_series: List[str] = [str(d) for d in dates_raw]

    row_count = max(len(notional_series), len(date_series))
    truncated = row_count >= P43_SCHEDULE_MAX_ROWS

    return ScheduleInfo(
        notional_series=notional_series,
        date_series=date_series,
        row_count=row_count,
        truncated=truncated,
    )


def enrich_schedule_columns(df: pd.DataFrame) -> pd.DataFrame:
    """Materialize schedule_notional_series / schedule_row_count / truncated.

    Reads [#34] Notional amount in effect on associated effective date-
    Leg 1 and [#33] associated effective dates if present; otherwise
    emits empty lists / row_count=0.
    """
    notional_col = (
        "Notional amount in effect on associated effective date-Leg 1"
        if "Notional amount in effect on associated effective date-Leg 1" in df.columns
        else "notional_amount_in_effect_on_associated_effective_date-leg_1"
        if "notional_amount_in_effect_on_associated_effective_date-leg_1" in df.columns
        else None
    )
    date_col = (
        "Effective date of the notional amount-Leg 1"
        if "Effective date of the notional amount-Leg 1" in df.columns
        else "effective_date_of_the_notional_amount-leg_1"
        if "effective_date_of_the_notional_amount-leg_1" in df.columns
        else None
    )

    if notional_col is None and date_col is None:
        df["schedule_notional_series"] = [[] for _ in range(len(df))]
        df["schedule_row_count"] = 0
        df["schedule_truncated"] = False
        return df

    schedules: List[ScheduleInfo] = []
    for i in range(len(df)):
        n_cell = df[notional_col].iat[i] if notional_col else None
        d_cell = df[date_col].iat[i] if date_col else None
        schedules.append(extract_schedule(n_cell, d_cell))

    df["schedule_notional_series"] = [s.notional_series for s in schedules]
    df["schedule_row_count"] = [s.row_count for s in schedules]
    df["schedule_truncated"] = [s.truncated for s in schedules]
    return df
