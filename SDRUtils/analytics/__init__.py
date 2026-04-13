"""
Analytics module for SDR trade analysis.

This package provides analytical tools for SDR trade data:
- Seasonality: Event-based analysis (FOMC, month-end, quarter-end)
- Flow: Trade type classification and venue/CCP inference
- Volume: Spike detection, event context, and seasonality heatmaps
- Intraday: Cumulative DV01, hourly distributions, trade clustering
- Trade Quality: Off-market flagging, UFRO detection, outlier identification
- Compression: Detection, decomposition, and measurement
- Liquidity: Price dispersion, tick size, venue analysis, composite scoring
- FOMC: Meeting schedules, implied rates, cut probabilities, calendar spreads
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

from SDRUtils.analytics.flow import (
    assign_trade_type,
    bucket_forward_start,
    classify_venue,
    infer_ccp,
)

from SDRUtils.analytics.volume import (
    detect_volume_spikes,
    classify_spike_context,
    seasonality_heatmap_data,
)

from SDRUtils.analytics.intraday import (
    intraday_cumulative_dv01,
    hourly_distribution,
    trade_clustering,
    execution_timing_stats,
)

from SDRUtils.analytics.trade_quality import (
    TradeQualityFlag,
    flag_upfront_payments,
    flag_off_market_trades,
    flag_capped_notional,
    flag_outliers,
)

from SDRUtils.analytics.compression import (
    detect_compression_signals,
    clean_volume_decomposition,
    monthly_compression_ratio,
)

from SDRUtils.analytics.liquidity import (
    price_dispersion,
    tick_size_stats,
    venue_analysis,
    LiquidityScorer,
)

from SDRUtils.analytics.fomc import (
    load_fomc_schedule,
    classify_rate_index,
    assign_fomc_meeting,
    classify_meeting_proximity,
    compute_calendar_spreads,
    compute_cut_probabilities,
    get_current_fixing,
    build_fomc_curves,
    price_fomc_meetings,
    FOMCAnalyzer,
)
from SDRUtils.analytics.trade_tape import TradeTape

__all__ = [
    # Seasonality
    "get_fomc_dates",
    "get_month_end_dates",
    "get_quarter_end_dates",
    "classify_date",
    "add_event_classifications",
    "aggregate_flows_by_label",
    "analyze_seasonality_by_event",
    # Flow
    "assign_trade_type",
    "bucket_forward_start",
    "classify_venue",
    "infer_ccp",
    # Volume
    "detect_volume_spikes",
    "classify_spike_context",
    "seasonality_heatmap_data",
    # Intraday
    "intraday_cumulative_dv01",
    "hourly_distribution",
    "trade_clustering",
    "execution_timing_stats",
    # Trade Quality
    "TradeQualityFlag",
    "flag_upfront_payments",
    "flag_off_market_trades",
    "flag_capped_notional",
    "flag_outliers",
    # Compression
    "detect_compression_signals",
    "clean_volume_decomposition",
    "monthly_compression_ratio",
    # Liquidity
    "price_dispersion",
    "tick_size_stats",
    "venue_analysis",
    "LiquidityScorer",
    # FOMC
    "load_fomc_schedule",
    "classify_rate_index",
    "assign_fomc_meeting",
    "classify_meeting_proximity",
    "compute_calendar_spreads",
    "compute_cut_probabilities",
    "get_current_fixing",
    "build_fomc_curves",
    "price_fomc_meetings",
    "FOMCAnalyzer",
    # Trade Tape
    "TradeTape",
]
