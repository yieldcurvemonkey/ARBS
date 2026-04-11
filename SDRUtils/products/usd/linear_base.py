from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

from SDRUtils.core.classification import SwapTradeClassification
from SDRUtils.core.lifecycle_v2 import LifecycleSummary


class TenorSegment(str, Enum):
    SHORT = "SHORT"    # <= 3Y
    MEDIUM = "MEDIUM"  # > 3Y

    @classmethod
    def from_years(cls, tenor_years: float) -> TenorSegment:
        return cls.SHORT if tenor_years <= 3.0 else cls.MEDIUM


class LinearProductType(str, Enum):
    OIS = "OIS"
    BASIS = "BASIS"
    SINGLE_PERIOD = "SINGLE_PERIOD"
    SPREADOVER = "SPREADOVER"


class RateIndex(str, Enum):
    SOFR = "SOFR"
    SOFR_COMPOUND = "SOFR_COMPOUND"
    FED_FUNDS = "FED_FUNDS"
    FED_FUNDS_COMPOUND = "FED_FUNDS_COMPOUND"
    OBFR = "OBFR"
    CMS = "CMS"
    SIFMA = "SIFMA"


class BasisType(str, Enum):
    SOFR_FF = "SOFR_FF"
    SOFR_TENOR = "SOFR_TENOR"
    FF_TENOR = "FF_TENOR"
    CMS = "CMS"
    SIFMA = "SIFMA"
    OBFR_SOFR = "OBFR_SOFR"
    XCCY = "XCCY"


@dataclass
class USDLinearClassification(SwapTradeClassification):
    rate_index: Optional[RateIndex] = None
    linear_product_type: Optional[LinearProductType] = None
    tenor_segment: Optional[TenorSegment] = None
    lifecycle_summary: Optional[LifecycleSummary] = None


@dataclass
class BasisSwapClassification(USDLinearClassification):
    basis_type: Optional[BasisType] = None
    leg1_rate_index: Optional[str] = None
    leg2_rate_index: Optional[str] = None
    leg1_reset_tenor: Optional[str] = None
    leg2_reset_tenor: Optional[str] = None
    spread_bps: Optional[float] = None
