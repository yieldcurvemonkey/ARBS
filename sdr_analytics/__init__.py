"""
SDR Analytics Suite

Comprehensive analytics for US Interest Rate Swaps trading desk.
"""

from .sdr_utils import (
    BENCHMARK_TENORS,
    TENOR_BUCKET_ORDER,
    TENOR_BUCKET_ORDER_SIMPLE,
    assign_tenor_bucket_detailed,
    assign_tenor_bucket_simple,
    assign_tenor_bucket_trading,
    calculate_curve_spreads,
    calculate_intraday_profile,
    calculate_rate_stats,
    calculate_volume_stats,
    classify_product,
    classify_venue,
    export_summary_to_excel,
    get_benchmark_tenor_label,
    get_trading_session_range,
    identify_large_trades,
    is_benchmark_tenor,
    minutes_since_session_start,
    preprocess_sdr_data,
    tenor_label,
)

__all__ = [
    "preprocess_sdr_data",
    "assign_tenor_bucket_simple",
    "assign_tenor_bucket_detailed",
    "assign_tenor_bucket_trading",
    "classify_venue",
    "classify_product",
    "calculate_volume_stats",
    "calculate_rate_stats",
    "calculate_intraday_profile",
    "identify_large_trades",
    "calculate_curve_spreads",
    "export_summary_to_excel",
    "is_benchmark_tenor",
    "get_benchmark_tenor_label",
    "tenor_label",
    "get_trading_session_range",
    "minutes_since_session_start",
    "TENOR_BUCKET_ORDER",
    "TENOR_BUCKET_ORDER_SIMPLE",
    "BENCHMARK_TENORS",
]
