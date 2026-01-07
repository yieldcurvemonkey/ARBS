from dataclasses import dataclass
from typing import List, Literal, Optional, Union, Callable

import numpy as np
import pandas as pd
import QuantLib as ql

from SDRUtils.core.utils import _to_float

"""
TODO

additional fields to TradeClassification

'Cleared': 'I',
'Platform identifier': 'BGCD',
'Prime brokerage transaction indicator': False,
'Block trade election indicator': False,
'Large notional off-facility swap election indicator': None,

'Package indicator': False,
'Package transaction price': '',

'Unique Product Identifier': 'QZF08M5TR8H3',
'UPI Underlier Name': 'JPY-TONA-OIS Compound'

"""

@dataclass
class TradeClassification:
    """Classification of an SDR trade"""

    trade_id: int
    execution_timestamp: pd.Timestamp
    effective_date: pd.Timestamp
    expiration_date: pd.Timestamp

    # TODO support more products
    # Product type
    product_type: Literal["OIS_SWAP", "SWAPTION_CALL", "SWAPTION_PUT", "CAP", "FLOOR", "UNKNOWN"]

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

    # TODO support more packages
    # Package info
    package_type: Optional[Literal["CURVE", "FLY", "STRADDLE", "STRANGLE", "OUTRIGHT"]] = None
    package_id: Optional[str] = None
    package_legs: Optional[List[int]] = None


def classify_product_type(row: pd.Series) -> Literal["OIS_SWAP", "SWAPTION_CALL", "SWAPTION_PUT", "CAP", "FLOOR", "UNKNOWN"]:
    upi_fisn = str(row.get("UPI FISN", "")).upper()
    upi_underlier = str(row.get("UPI Underlier Name", "")).upper()

    strike = _to_float(row.get("Strike Price"))
    fixed_rate = _to_float(row.get("Fixed rate-Leg 1"))

    first_exercise = row.get("First exercise date")
    # normalize if you want:
    first_exercise = pd.to_datetime(first_exercise, errors="coerce") if not isinstance(first_exercise, pd.Timestamp) else first_exercise

    # Explicit option labeling from FISN first
    if "NA/O Call" in upi_fisn or "CALL" in upi_fisn:
        return "SWAPTION_CALL"
    if "NA/O P Epn" in upi_fisn or "PUT" in upi_fisn or "O P" in upi_fisn:
        return "SWAPTION_PUT"
    if "CAP" in upi_fisn:
        return "CAP"
    if "FLOOR" in upi_fisn:
        return "FLOOR"

    # Strike-based option inference (now safe)
    if pd.notna(strike) and strike > 0:
        if pd.notna(first_exercise):
            return "SWAPTION_CALL"  # default if unclear

    # OIS swap inference
    if "SWAP" in upi_fisn and "OIS" in upi_fisn:
        return "OIS_SWAP"
    if "SOFR" in upi_underlier and ("COMPOUND" in upi_underlier or "OIS" in upi_underlier):
        return "OIS_SWAP"

    if "Swap Fxd Flt" in upi_fisn:
        return "OTHER_FXD_FLT_SWAP" 

    # Fixed rate inference (now safe)
    if pd.notna(fixed_rate) and fixed_rate > 0:
        return "OIS_SWAP"

    return "UNKNOWN"


def classifications_to_dataframe(classifications: List[TradeClassification]) -> pd.DataFrame:
    """Convert list of classifications to DataFrame"""
    records = []
    for c in classifications:
        records.append(
            {
                "Dissemination Identifier": c.trade_id,
                "trade_id": c.trade_id,
                "execution_timestamp": c.execution_timestamp,
                "effective_date": c.effective_date,
                "expiration_date": c.expiration_date,
                "product_type": c.product_type,
                "tenor_years": c.tenor_years,
                "tenor_label": c.tenor_label,
                "is_forward": c.is_forward,
                "forward_start_years": c.forward_start_years,
                "forward_label": c.forward_label,
                "trade_label": c.trade_label,
                "notional": c.notional,
                "notional_currency": c.notional_currency,
                "fixed_rate": c.fixed_rate,
                "strike": c.strike,
                "estimated_pv01": c.estimated_pv01,
                "package_type": c.package_type,
                "package_id": c.package_id,
            }
        )

    return pd.DataFrame(records)
