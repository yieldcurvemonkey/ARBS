"""
Analytics module for SDR trade analysis.

This package provides analytical tools for SDR trade data:
- Seasonality: Event-based analysis (FOMC, month-end, quarter-end)
- Flow Analysis: Trade flow aggregation and pattern detection
"""

from SDRUtils.analytics.seasonality import (
    get_fomc_dates,
    get_month_end_dates,
    get_quarter_end_dates,
    classify_date,
    add_event_classifications,
    aggregate_flows_by_label,
    analyze_seasonality_by_event,
)

__all__ = [
    # Seasonality
    "get_fomc_dates",
    "get_month_end_dates",
    "get_quarter_end_dates",
    "classify_date",
    "add_event_classifications",
    "aggregate_flows_by_label",
    "analyze_seasonality_by_event",
]
