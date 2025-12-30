"""
DEPRECATED: This module is maintained for backward compatibility.
Please import from SDRUtils.core.utils instead.

Example:
    # Old way (deprecated)
    from SDRUtils.utils import calculate_tenor_years

    # New way (recommended)
    from SDRUtils.core.utils import calculate_tenor_years
    # or
    from SDRUtils import calculate_tenor_years
"""

# Re-export everything from the new location
from SDRUtils.core.utils import (
    NY_tz,
    UTC_tz,
    USD_OIS_CAL,
    USD_OIS_DC,
    USD_OIS_BDC,
    ensure_int64_epoch_seconds,
    pv01_bucket,
    parse_notional,
    to_float,
    to_naive_timestamp,
    ts_to_ql_date,
    to_ql_date,
    adjust_ql_date,
    calculate_tenor_years,
    calculate_forward_start_years,
    get_imm_label,
    get_fomc_label,
    get_special_label,
    special_forward_label,
    tenor_to_label,
    forward_to_label,
    # Legacy aliases
    _ensure_int64_epoch_seconds,
    _pv01_bucket,
    _parse_notional,
    _to_float,
    _to_naive_timestamp,
    _ts_to_ql_date,
    _to_ql_date,
    _adjust_ql_date,
    _get_imm_label,
    _get_fomc_label,
    _get_special_label,
    _special_forward_label,
    _USD_OIS_CAL,
    _USD_OIS_DC,
    _USD_OIS_BDC,
)

__all__ = [
    "NY_tz",
    "UTC_tz",
    "USD_OIS_CAL",
    "USD_OIS_DC",
    "USD_OIS_BDC",
    "ensure_int64_epoch_seconds",
    "pv01_bucket",
    "parse_notional",
    "to_float",
    "to_naive_timestamp",
    "ts_to_ql_date",
    "to_ql_date",
    "adjust_ql_date",
    "calculate_tenor_years",
    "calculate_forward_start_years",
    "get_imm_label",
    "get_fomc_label",
    "get_special_label",
    "special_forward_label",
    "tenor_to_label",
    "forward_to_label",
    # Legacy aliases
    "_ensure_int64_epoch_seconds",
    "_pv01_bucket",
    "_parse_notional",
    "_to_float",
    "_to_naive_timestamp",
    "_ts_to_ql_date",
    "_to_ql_date",
    "_adjust_ql_date",
    "_get_imm_label",
    "_get_fomc_label",
    "_get_special_label",
    "_special_forward_label",
    "_USD_OIS_CAL",
    "_USD_OIS_DC",
    "_USD_OIS_BDC",
]
