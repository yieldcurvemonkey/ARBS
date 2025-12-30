"""
Core utilities for SDR analytics.

This module re-exports functions from the refactored submodules for
backward compatibility. New code should import directly from the
specific modules (dates, tenors, parsing).

Deprecated: Import from SDRUtils.core.dates, SDRUtils.core.tenors,
or SDRUtils.core.parsing instead.
"""

from __future__ import annotations

import pytz

# Re-export from dates module
from SDRUtils.core.dates import (
    NY_tz,
    UTC_tz,
    to_naive_timestamp,
    ts_to_ql_date,
    to_ql_date,
    adjust_ql_date,
    ensure_int64_epoch_seconds,
    calculate_tenor_years,
    calculate_forward_start_years,
    is_forward_starting,
    # Backward compatibility aliases
    _to_naive_timestamp,
    _ts_to_ql_date,
    _to_ql_date,
    _adjust_ql_date,
    _ensure_int64_epoch_seconds,
)

# Re-export from tenors module
from SDRUtils.core.tenors import (
    get_imm_label,
    get_fomc_label,
    get_special_label,
    tenor_to_label,
    forward_to_label,
    build_trade_label,
    # Backward compatibility aliases
    _get_imm_label,
    _get_fomc_label,
    _get_special_label,
    _special_forward_label,
)

# Re-export from parsing module
from SDRUtils.core.parsing import (
    parse_notional,
    to_float,
    pv01_bucket,
    tenor_bucket,
    extract_numeric_from_string,
    safe_get,
    normalize_currency,
    # Backward compatibility aliases
    _parse_notional,
    _to_float,
    _pv01_bucket,
)

# Re-export conventions for backward compatibility
from SDRUtils.config import (
    USD_CONVENTIONS,
    EUR_CONVENTIONS,
    GBP_CONVENTIONS,
    get_conventions,
)

# Legacy aliases for USD conventions
_USD_OIS_CAL = USD_CONVENTIONS.calendar
_USD_OIS_DC = USD_CONVENTIONS.day_counter
_USD_OIS_BDC = USD_CONVENTIONS.business_day_convention


__all__ = [
    # Timezones
    "NY_tz",
    "UTC_tz",
    # Date functions
    "to_naive_timestamp",
    "ts_to_ql_date",
    "to_ql_date",
    "adjust_ql_date",
    "ensure_int64_epoch_seconds",
    "calculate_tenor_years",
    "calculate_forward_start_years",
    "is_forward_starting",
    # Tenor functions
    "get_imm_label",
    "get_fomc_label",
    "get_special_label",
    "tenor_to_label",
    "forward_to_label",
    "build_trade_label",
    # Parsing functions
    "parse_notional",
    "to_float",
    "pv01_bucket",
    "tenor_bucket",
    "extract_numeric_from_string",
    "safe_get",
    "normalize_currency",
    # Conventions
    "USD_CONVENTIONS",
    "EUR_CONVENTIONS",
    "GBP_CONVENTIONS",
    "get_conventions",
    # Legacy aliases
    "_USD_OIS_CAL",
    "_USD_OIS_DC",
    "_USD_OIS_BDC",
    "_to_naive_timestamp",
    "_ts_to_ql_date",
    "_to_ql_date",
    "_adjust_ql_date",
    "_ensure_int64_epoch_seconds",
    "_get_imm_label",
    "_get_fomc_label",
    "_get_special_label",
    "_special_forward_label",
    "_parse_notional",
    "_to_float",
    "_pv01_bucket",
]
