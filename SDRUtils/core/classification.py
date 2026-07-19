from dataclasses import asdict, dataclass, field, is_dataclass
from typing import Any, List, Literal, Optional

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

ProductType = Literal[
    "OIS_SWAP",
    "SWAPTION_CALL",
    "SWAPTION_PUT",
    "SWAPTION_PAYER",
    "SWAPTION_RECEIVER",
    "SWAPTION",
    "CAP",
    "FLOOR",
    "OTHER_FXD_FLT_SWAP",
    "UNKNOWN",
]

SpecialTenorType = Literal[
    "STANDARD",
    "IMM",
    "FOMC",
    "MATCHED_MATURITY",
    "INVOICE_SWAP",
    "MAC",
]

SpecialTenorConfidence = Literal["high", "medium", "low"]

OptionType = Literal["CALL", "PUT"]
ExerciseStyle = Literal["EUROPEAN", "AMERICAN", "BERMUDAN"]


@dataclass
class TradeClassification:
    """Classification of an SDR trade."""

    event_action: str
    trade_id: int
    execution_timestamp: pd.Timestamp
    effective_date: pd.Timestamp
    expiration_date: pd.Timestamp

    # Product type
    product_type: ProductType

    # Full trade label e.g., "spot 10Y", "5Y10Y", "1Y1Y"
    trade_label: str

    # Notional and risk
    notional: float
    notional_currency: str
    is_notional_capped: bool

    # Estimated PV01 (per 1bp)
    estimated_pv01: Optional[float] = field(default=None, kw_only=True)

    # --- Execution-vs-Event timestamp integration (2026-07-17 spec) ---
    # CFTC Part 43/45 Event timestamp (#30): when the reported event occurred;
    # invariant event_timestamp >= execution_timestamp. Read at classify time.
    event_timestamp: Optional[pd.Timestamp] = field(default=None, kw_only=True)
    # Alpha's original execution (lineage-resolved in enrichment); <= execution.
    original_execution_timestamp: Optional[pd.Timestamp] = field(default=None, kw_only=True)
    # Precomputed deltas (seconds); populated in enrichment (trade_tape).
    report_lag_seconds: Optional[float] = field(default=None, kw_only=True)
    alpha_lag_seconds: Optional[float] = field(default=None, kw_only=True)
    # Provenance of original_execution_timestamp: 'newt' | 'lineage' | 'fallback'.
    # Also set to 'fallback' at classify time when a product falls back from a
    # missing Execution Timestamp to the Event timestamp (swaptions/capfloors).
    original_execution_source: Optional[str] = field(default=None, kw_only=True)

    # TODO support more packages
    # Package info
    package_type: Optional[Literal["CURVE", "FLY", "STRADDLE", "STRANGLE", "OUTRIGHT"]] = field(default=None, kw_only=True)
    package_id: Optional[str] = field(default=None, kw_only=True)
    package_legs: Optional[List[int]] = field(default=None, kw_only=True)
    underlying_expiration_date: Optional[pd.Timestamp] = field(default=None, kw_only=True)


@dataclass
class SwapTradeClassification(TradeClassification):
    """Swap-specific classification details."""

    # Tenor information
    tenor_years: float
    tenor_label: str  # e.g., "2Y", "5Y", "10Y"

    # Forward start info (for forward swaps)
    is_forward: bool
    forward_start_years: float
    forward_label: str  # e.g., "spot", "1Y", "5Y"

    # Rates
    fixed_rate: Optional[float]

    # Unified special tenor classification
    special_tenor_type: SpecialTenorType = field(default="STANDARD", kw_only=True)
    special_tenor_confidence: SpecialTenorConfidence = field(default="high", kw_only=True)
    special_tenor_tags: List[str] = field(default_factory=list, kw_only=True)

    # Reference data enrichment (populated by Phase 2 detectors)
    matched_ust_cusip: Optional[str] = field(default=None, kw_only=True)
    invoice_swap_ticker: Optional[str] = field(default=None, kw_only=True)
    is_mac: bool = field(default=False, kw_only=True)


@dataclass
class SwaptionTradeClassification(TradeClassification):
    """Swaption-specific classification details."""

    # Underlying swap characteristics
    tenor_years: float
    tenor_label: str
    forward_start_years: float
    forward_label: str

    # Option characteristics
    premium: Optional[float]
    exercise_style: Optional[ExerciseStyle]
    strike: Optional[float]

    # misc
    # is_midcurve: Optional[bool]
    # option_start_years


@dataclass
class CapFloorTradeClassification(SwaptionTradeClassification):
    """Cap/Floor-specific classification details."""

    cap_floor_type: str = ""
    reset_frequency: str = ""
    num_caplets: Optional[int] = None
    implied_vol_bps: Optional[float] = None
    moneyness_bps: Optional[float] = None


def classify_product_type(row: pd.Series) -> ProductType:
    upi_fisn = str(row.get("UPI FISN", "")).upper()
    upi_underlier = str(row.get("UPI Underlier Name", "")).upper()

    # Explicit option labeling from FISN first
    if "NA/O Call" in upi_fisn or "CALL" in upi_fisn:
        return "SWAPTION_PAYER"
    if "NA/O P Epn" in upi_fisn or "PUT" in upi_fisn or "O P" in upi_fisn:
        return "SWAPTION_RECEIVER"
    if "NA/O Opt Epn" in upi_fisn or "OPT" in upi_fisn or "Opt" in upi_fisn:
        return "SWAPTION_CHOOSER"
    if "CAP" in upi_fisn:
        return "CAP"
    if "FLOOR" in upi_fisn:
        return "FLOOR"

    # N5 (deferred): strike-based option inference is disabled until the
    # strike is notation-normalised. If re-enabled, the strike MUST be
    # routed through SDRUtils.core.parsing.parse_notation_scalar paired
    # with [#64] Strike price notation (1=monetary, 3=decimal, 4=bps),
    # otherwise package-spread-style B4/B5 bugs will recur.
    # strike = _to_float(row.get("Strike Price"))
    # first_exercise = row.get("First exercise date")
    # if pd.notna(strike) and strike > 0 and pd.notna(first_exercise):
    #     return "SWAPTION_CALL"

    # OIS swap inference
    if "SWAP" in upi_fisn and "OIS" in upi_fisn:
        return "OIS_SWAP"
    if "SOFR" in upi_underlier and ("COMPOUND" in upi_underlier or "OIS" in upi_underlier):
        return "OIS_SWAP"

    if "Swap Fxd Flt" in upi_fisn:
        return "OTHER_FXD_FLT_SWAP"

    # Fixed rate inference (now safe)
    fixed_rate = _to_float(row.get("Fixed rate-Leg 1"))
    if pd.notna(fixed_rate) and fixed_rate > 0:
        return "OIS_SWAP"

    return "UNKNOWN"


def classifications_to_dataframe(classifications: List["TradeClassification"]) -> pd.DataFrame:
    """
    Convert list of classifications to DataFrame dynamically.

    This function detects attributes automatically, allowing for polymorphic
    inputs (e.g., specific Swap vs Swaption fields) without manual mapping.
    It creates a union of all attributes found across the list.
    """
    if not classifications:
        return pd.DataFrame()

    records = []

    for c in classifications:
        # 1. Extract base attributes dynamically
        record = _object_to_dict(c)

        # 2. Apply specific overrides/mappings required by your pipeline
        # (The original code mapped 'trade_id' to 'Dissemination Identifier')
        if "trade_id" in record:
            record["Dissemination Identifier"] = record["trade_id"]

        records.append(record)

    # Pandas handles the alignment of different schemas (keys) automatically,
    # filling missing fields with NaN (None).
    return pd.DataFrame(records)


def _object_to_dict(obj: Any) -> dict:
    """Helper to safely convert various object types to a dictionary."""
    # 1. Handle Python DataClasses
    if is_dataclass(obj):
        return asdict(obj)

    # 2. Handle Pydantic Models (v1 and v2 compat)
    if hasattr(obj, "model_dump"):  # Pydantic v2
        return obj.model_dump()
    if hasattr(obj, "dict") and callable(obj.dict):  # Pydantic v1
        return obj.dict()

    # 3. Handle standard classes with __dict__
    if hasattr(obj, "__dict__"):
        return vars(obj).copy()

    # 4. Handle classes using __slots__ (memory optimized classes)
    if hasattr(obj, "__slots__"):
        return {s: getattr(obj, s) for s in obj.__slots__ if hasattr(obj, s)}

    # 5. Fallback: try casting directly if it mimics a dict
    try:
        return dict(obj)
    except (ValueError, TypeError):
        return {}
