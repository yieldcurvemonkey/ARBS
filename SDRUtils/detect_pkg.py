"""
DEPRECATED: This module is maintained for backward compatibility.
Please import from SDRUtils.packages instead.

Example:
    # Old way (deprecated)
    from SDRUtils.detect_pkg import detect_curve_trades_df, detect_fly_trades_df

    # New way (recommended)
    from SDRUtils.packages import detect_packages
    from SDRUtils.packages.detectors import CurveDetector, FlyDetector
    # or
    from SDRUtils import detect_packages
"""

from typing import Optional

import pandas as pd

from SDRUtils.packages.base import PackageDetectorConfig
from SDRUtils.packages.detectors.curve import CurveDetector
from SDRUtils.packages.detectors.fly import FlyDetector
from SDRUtils.core.utils import (
    ensure_int64_epoch_seconds as _ensure_int64_epoch_seconds,
    pv01_bucket as _pv01_bucket,
)


def detect_curve_trades_df(
    df: pd.DataFrame,
    *,
    time_window_seconds: int = 60,
    pv01_tolerance: float = 0.10,
    require_different_tenor: bool = True,
    require_opposite_direction: bool = False,
    direction_col: Optional[str] = None,
    product_col: str = "product_type",
    package_col: str = "package_type",
    exec_col: str = "execution_timestamp",
    pv01_col: str = "estimated_pv01",
    tenor_col: str = "tenor_label",
    trade_id_col: str = "trade_id",
    require_same_currency: bool = True,
    currency_col: str = "notional_currency",
    require_same_effective_date: bool = True,
    effective_date_col: str = "effective_date",
    require_same_forward: bool = True,
    forward_label_col: str = "forward_label",
    forward_years_col: str = "forward_start_years",
    forward_years_tol: float = 0.05,
    require_same_underlier: bool = True,
    underlier_col: str = "UPI Underlier Name",
    require_same_platform: bool = True,
    platform_col: str = "Platform identifier",
    require_same_cleared_flag: bool = True,
    cleared_col: str = "Cleared",
) -> pd.DataFrame:
    """
    Fast curve detection on the classifications dataframe.
    Mutates package_type/package_id/package_legs in returned df.

    This is a compatibility wrapper around CurveDetector.
    """
    config = PackageDetectorConfig(
        time_window_seconds=time_window_seconds,
        pv01_tolerance=pv01_tolerance,
        product_col=product_col,
        package_col=package_col,
        exec_col=exec_col,
        pv01_col=pv01_col,
        tenor_col=tenor_col,
        trade_id_col=trade_id_col,
        currency_col=currency_col,
        effective_date_col=effective_date_col,
        forward_label_col=forward_label_col,
        forward_years_col=forward_years_col,
        underlier_col=underlier_col,
        platform_col=platform_col,
        cleared_col=cleared_col,
        require_same_currency=require_same_currency,
        require_same_effective_date=require_same_effective_date,
        require_same_forward=require_same_forward,
        require_same_underlier=require_same_underlier,
        require_same_platform=require_same_platform,
        require_same_cleared_flag=require_same_cleared_flag,
    )

    detector = CurveDetector(
        require_different_tenor=require_different_tenor,
        require_opposite_direction=require_opposite_direction,
        direction_col=direction_col,
        forward_years_tol=forward_years_tol,
    )

    return detector.detect(df, config)


def detect_fly_trades_df(
    df: pd.DataFrame,
    *,
    time_window_seconds: int = 60,
    belly_ratio_tolerance: float = 0.15,
    product_col: str = "product_type",
    package_col: str = "package_type",
    exec_col: str = "execution_timestamp",
    pv01_col: str = "estimated_pv01",
    tenor_years_col: str = "tenor_years",
    trade_id_col: str = "trade_id",
    require_same_currency: bool = True,
    currency_col: str = "notional_currency",
    require_same_effective_date: bool = True,
    effective_date_col: str = "effective_date",
    require_same_forward: bool = True,
    forward_label_col: str = "forward_label",
    forward_years_col: str = "forward_start_years",
    forward_years_tol: float = 0.05,
    require_same_underlier: bool = True,
    underlier_col: str = "UPI Underlier Name",
    require_same_platform: bool = True,
    platform_col: str = "Platform identifier",
    require_same_cleared_flag: bool = True,
    cleared_col: str = "Cleared",
) -> pd.DataFrame:
    """
    Fast fly detection on the classifications dataframe.

    This is a compatibility wrapper around FlyDetector.
    """
    config = PackageDetectorConfig(
        time_window_seconds=time_window_seconds,
        product_col=product_col,
        package_col=package_col,
        exec_col=exec_col,
        pv01_col=pv01_col,
        tenor_years_col=tenor_years_col,
        trade_id_col=trade_id_col,
        currency_col=currency_col,
        effective_date_col=effective_date_col,
        forward_label_col=forward_label_col,
        forward_years_col=forward_years_col,
        underlier_col=underlier_col,
        platform_col=platform_col,
        cleared_col=cleared_col,
        require_same_currency=require_same_currency,
        require_same_effective_date=require_same_effective_date,
        require_same_forward=require_same_forward,
        require_same_underlier=require_same_underlier,
        require_same_platform=require_same_platform,
        require_same_cleared_flag=require_same_cleared_flag,
    )

    detector = FlyDetector(
        belly_ratio_tolerance=belly_ratio_tolerance,
        forward_years_tol=forward_years_tol,
    )

    return detector.detect(df, config)


__all__ = [
    "detect_curve_trades_df",
    "detect_fly_trades_df",
    "_ensure_int64_epoch_seconds",
    "_pv01_bucket",
]
