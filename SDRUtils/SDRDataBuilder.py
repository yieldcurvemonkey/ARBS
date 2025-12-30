"""
DEPRECATED: This module is maintained for backward compatibility.
Please import from SDRUtils.core.data_builder instead.

Example:
    # Old way (deprecated)
    from SDRUtils.SDRDataBuilder import SDRDataBuilder

    # New way (recommended)
    from SDRUtils.core import SDRDataBuilder
    # or
    from SDRUtils import SDRDataBuilder
"""

import warnings

# Re-export everything from the new location
from SDRUtils.core.data_builder import (
    BaseFetcher,
    DTCCFetcher,
    SDRDataBuilder,
    datetime_today_utc,
    _df_to_parquet,
    _save_daily_dict,
    _load_daily_dict,
    _read_intraday_cache,
    _write_intraday_cache,
    _clear_file,
    _batch_convert_to_polars,
    _concat_dfs,
)

__all__ = [
    "BaseFetcher",
    "DTCCFetcher",
    "SDRDataBuilder",
    "datetime_today_utc",
    "_df_to_parquet",
    "_save_daily_dict",
    "_load_daily_dict",
    "_read_intraday_cache",
    "_write_intraday_cache",
    "_clear_file",
    "_batch_convert_to_polars",
    "_concat_dfs",
]
