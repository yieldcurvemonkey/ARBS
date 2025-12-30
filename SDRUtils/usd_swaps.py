"""
DEPRECATED: This module is maintained for backward compatibility.
Please import from SDRUtils.currencies.usd instead.

Example:
    # Old way (deprecated)
    from SDRUtils.usd_swaps import classify_sofr_swap_trade, detect_ust_mms_trades_df

    # New way (recommended)
    from SDRUtils.currencies.usd import classify_sofr_swap_trade, match_swaps_to_ust
    # or
    from SDRUtils import classify_sofr_swap_trade, match_swaps_to_ust
"""

from typing import Optional, Sequence

import pandas as pd

from SDRUtils.currencies.usd.sofr_swap import classify_sofr_swap_trade
from SDRUtils.currencies.usd.ust_matching import match_swaps_to_ust
from SDRUtils.packages.detectors.spreadover import SpreadoverDetector
from SDRUtils.packages.base import PackageDetectorConfig

# Re-export for backward compatibility
from SDRUtils.models.trade_classification import TradeClassification
from SDRUtils.products.registry import classify_product_type
from SDRUtils.core.utils import (
    ensure_int64_epoch_seconds as _ensure_int64_epoch_seconds,
    parse_notional as _parse_notional,
    pv01_bucket as _pv01_bucket,
    to_ql_date as _to_ql_date,
    calculate_forward_start_years,
    calculate_tenor_years,
    forward_to_label,
    tenor_to_label,
    USD_OIS_CAL as _USD_OIS_CAL,
)


def detect_ust_mms_trades_df(
    df: pd.DataFrame,
    *,
    product_col: str = "product_type",
    product_values: Sequence[str] = ("OIS_SWAP",),
    package_col: str = "package_type",
    trade_id_col: str = "trade_id",
    swap_maturity_col: str = "expiration_date",
    currency_col: str = "notional_currency",
    require_usd: bool = True,
    usd_value: str = "USD",
    ust_ref_source: str = "fiscaldata",
    ust_force_refresh: bool = False,
    spreadover_package_type: str = "SPREADOVER",
    only_tag_outrights: bool = True,
) -> pd.DataFrame:
    """
    Detect UST matched-maturity trades.

    This is a compatibility wrapper around SpreadoverDetector.
    """
    config = PackageDetectorConfig(
        product_col=product_col,
        package_col=package_col,
        trade_id_col=trade_id_col,
        currency_col=currency_col,
        product_values=list(product_values),
    )

    detector = SpreadoverDetector(
        swap_maturity_col=swap_maturity_col,
        require_usd=require_usd,
        usd_value=usd_value,
        ust_ref_source=ust_ref_source,
        ust_force_refresh=ust_force_refresh,
        only_tag_outrights=only_tag_outrights,
    )

    return detector.detect(df, config)


__all__ = [
    "classify_sofr_swap_trade",
    "detect_ust_mms_trades_df",
    "match_swaps_to_ust",
    "TradeClassification",
    "classify_product_type",
    "calculate_forward_start_years",
    "calculate_tenor_years",
    "forward_to_label",
    "tenor_to_label",
    "_ensure_int64_epoch_seconds",
    "_parse_notional",
    "_pv01_bucket",
    "_to_ql_date",
    "_USD_OIS_CAL",
]
