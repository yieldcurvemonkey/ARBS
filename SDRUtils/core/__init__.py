"""
Core SDR utilities.

This module provides the fundamental building blocks for SDR analytics:
- Classification: Trade classification dataclass and functions
- Dates: Date/time conversion and year fraction calculations
- Tenors: Tenor labeling and special date detection (IMM/FOMC)
- Parsing: Data parsing utilities for SDR fields
"""

# Classification
from SDRUtils.core.classification import (
    TradeClassification,
    SwapTradeClassification,
    SwaptionTradeClassification,
    classify_product_type,
    classifications_to_dataframe,
)

# Dates
from SDRUtils.core.dates import (
    NY_tz,
    UTC_tz,
    to_ql_date,
    to_naive_timestamp,
    calculate_tenor_components,
    calculate_tenor_years,
    calculate_forward_start_years,
    is_forward_starting,
)

# Tenors
from SDRUtils.core.tenors import (
    tenor_to_label,
    tenor_from_dates,
    forward_to_label,
    build_trade_label,
    get_imm_label,
    get_fomc_label,
)

# Parsing
from SDRUtils.core.parsing import (
    parse_notional,
    to_float,
    pv01_bucket,
)

# Graph resolution
from SDRUtils.core.graph_resolver import (
    assign_synthetic_uti,
    build_synthetic_uti_mapping,
)

# Lifecycle state machine
from SDRUtils.core.lifecycle import (
    replay_lifecycle,
    replay_lifecycle_full,
    ResolvedTrade,
    LifecycleReplayResult,
    ECONOMICS_FIELDS,
)
# Backward compatibility - re-export legacy names
from SDRUtils.core.utils import (
    _USD_OIS_BDC,
    _USD_OIS_CAL,
    _USD_OIS_DC,
    _to_float,
    _parse_notional,
    _pv01_bucket,
    _ensure_int64_epoch_seconds,
)


__all__ = [
    # Classification
    "TradeClassification",
    "SwapTradeClassification",
    "SwaptionTradeClassification",
    "classify_product_type",
    "classifications_to_dataframe",
    # Dates
    "NY_tz",
    "UTC_tz",
    "to_ql_date",
    "to_naive_timestamp",
    "calculate_tenor_components",
    "calculate_tenor_years",
    "calculate_forward_start_years",
    "is_forward_starting",
    # Tenors
    "tenor_to_label",
    "tenor_from_dates",
    "forward_to_label",
    "build_trade_label",
    "get_imm_label",
    "get_fomc_label",
    # Parsing
    "parse_notional",
    "to_float",
    "pv01_bucket",
    # Graph resolution
    "assign_synthetic_uti",
    "build_synthetic_uti_mapping",
    # Lifecycle
    "replay_lifecycle",
    "replay_lifecycle_full",
    "ResolvedTrade",
    "LifecycleReplayResult",
    "ECONOMICS_FIELDS",
    # Legacy
    "_USD_OIS_BDC",
    "_USD_OIS_CAL",
    "_USD_OIS_DC",
    "_to_float",
    "_parse_notional",
    "_pv01_bucket",
    "_ensure_int64_epoch_seconds",
]
