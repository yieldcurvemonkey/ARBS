"""
Trade Classification Data Model.

Defines the core data structures for representing classified SDR trades.
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import List, Literal, Optional

import pandas as pd


class ProductType(str, Enum):
    """Enumeration of supported product types."""

    OIS_SWAP = "OIS_SWAP"
    SWAPTION_CALL = "SWAPTION_CALL"
    SWAPTION_PUT = "SWAPTION_PUT"
    CAP = "CAP"
    FLOOR = "FLOOR"
    BASIS_SWAP = "BASIS_SWAP"
    FRA = "FRA"
    UNKNOWN = "UNKNOWN"

    @classmethod
    def from_string(cls, value: str) -> "ProductType":
        """Convert string to ProductType, defaulting to UNKNOWN."""
        try:
            return cls(value.upper())
        except (ValueError, AttributeError):
            return cls.UNKNOWN


class PackageType(str, Enum):
    """Enumeration of supported package types."""

    OUTRIGHT = "OUTRIGHT"
    CURVE = "CURVE"
    FLY = "FLY"
    STRADDLE = "STRADDLE"
    STRANGLE = "STRANGLE"
    SPREADOVER = "SPREADOVER"
    CALENDAR = "CALENDAR"

    @classmethod
    def from_string(cls, value: str) -> "PackageType":
        """Convert string to PackageType, defaulting to OUTRIGHT."""
        try:
            return cls(value.upper())
        except (ValueError, AttributeError):
            return cls.OUTRIGHT


@dataclass
class TradeClassification:
    """
    Classification of an SDR trade.

    This dataclass holds all the classification information for a single trade,
    including product type, tenor information, forward start details, and
    package membership.
    """

    trade_id: int
    execution_timestamp: pd.Timestamp
    effective_date: pd.Timestamp
    expiration_date: pd.Timestamp

    # Product type
    product_type: Literal["OIS_SWAP", "SWAPTION_CALL", "SWAPTION_PUT", "CAP", "FLOOR", "BASIS_SWAP", "FRA", "UNKNOWN"]

    # Tenor information
    tenor_years: float
    tenor_label: str  # e.g., "2Y", "5Y", "10Y"

    # Forward start info (for forward swaps/swaptions)
    is_forward: bool
    forward_start_years: float
    forward_label: str  # e.g., "spot", "1Y", "5Y"

    # Full trade label e.g., "spot 10Y", "5Y10Y", "1Y1Y"
    trade_label: str

    # Notional and risk
    notional: float
    notional_currency: str
    fixed_rate: Optional[float]
    strike: Optional[float]

    # Estimated PV01 (per 1bp)
    estimated_pv01: float

    # Package info
    package_type: Optional[Literal["CURVE", "FLY", "STRADDLE", "STRANGLE", "SPREADOVER", "OUTRIGHT"]] = None
    package_id: Optional[str] = None
    package_legs: Optional[List[int]] = None

    def to_dict(self) -> dict:
        """Convert to dictionary representation."""
        return {
            "trade_id": self.trade_id,
            "execution_timestamp": self.execution_timestamp,
            "effective_date": self.effective_date,
            "expiration_date": self.expiration_date,
            "product_type": self.product_type,
            "tenor_years": self.tenor_years,
            "tenor_label": self.tenor_label,
            "is_forward": self.is_forward,
            "forward_start_years": self.forward_start_years,
            "forward_label": self.forward_label,
            "trade_label": self.trade_label,
            "notional": self.notional,
            "notional_currency": self.notional_currency,
            "fixed_rate": self.fixed_rate,
            "strike": self.strike,
            "estimated_pv01": self.estimated_pv01,
            "package_type": self.package_type,
            "package_id": self.package_id,
            "package_legs": self.package_legs,
        }


def classifications_to_dataframe(classifications: List[TradeClassification]) -> pd.DataFrame:
    """Convert list of TradeClassification objects to DataFrame."""
    if not classifications:
        return pd.DataFrame()

    records = [c.to_dict() for c in classifications]
    return pd.DataFrame(records)
