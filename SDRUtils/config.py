"""
Central configuration for SDRUtils.

This module provides currency-specific conventions, calendar settings,
and default parameters used across the SDR analytics pipeline.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence, Tuple

import QuantLib as ql

TRADE_ID = "Dissemination Identifier"


@dataclass(frozen=True)
class CurrencyConventions:
    """Trading conventions for a specific currency."""

    currency: str
    calendar: ql.Calendar
    day_counter: ql.DayCounter
    business_day_convention: int
    spot_lag_days: int = 2  # T+2 is standard for most currencies

    # Standard tenors for this currency
    standard_tenors: Tuple[str, ...] = (
        "1D",
        "1W",
        "2W",
        "3W",
        "1M",
        "2M",
        "3M",
        "4M",
        "5M",
        "6M",
        "7M",
        "8M",
        "9M",
        "10M",
        "11M",
        "1Y",
        "15M",
        "18M",
        "21M",
        "22M",
        "2Y",
        "3Y",
        "4Y",
        "5Y",
        "6Y",
        "7Y",
        "8Y",
        "9Y",
        "10Y",
        "11Y",
        "12Y",
        "13Y",
        "14Y",
        "15Y",
        "16Y",
        "17Y",
        "18Y",
        "19Y",
        "20Y",
        "21Y",
        "22Y",
        "23Y",
        "24Y",
        "25Y",
        "26Y",
        "27Y",
        "28Y",
        "29Y",
        "30Y",
        "40Y",
        "50Y",
    )


# USD Conventions (SOFR OIS)
USD_CONVENTIONS = CurrencyConventions(
    currency="USD",
    calendar=ql.UnitedStates(ql.UnitedStates.GovernmentBond),
    day_counter=ql.Actual360(),
    business_day_convention=ql.ModifiedFollowing,
    spot_lag_days=2,
)

# EUR Conventions (ESTR)
EUR_CONVENTIONS = CurrencyConventions(
    currency="EUR",
    calendar=ql.TARGET(),
    day_counter=ql.Actual360(),
    business_day_convention=ql.ModifiedFollowing,
    spot_lag_days=2,
)

# GBP Conventions (SONIA)
GBP_CONVENTIONS = CurrencyConventions(
    currency="GBP",
    calendar=ql.UnitedKingdom(),
    day_counter=ql.Actual365Fixed(),
    business_day_convention=ql.ModifiedFollowing,
    spot_lag_days=0,  # SONIA is T+0
)

# JPY Conventions (TONA)
JPY_CONVENTIONS = CurrencyConventions(
    currency="JPY",
    calendar=ql.Japan(),
    day_counter=ql.Actual365Fixed(),
    business_day_convention=ql.ModifiedFollowing,
    spot_lag_days=2,
)

# CHF Conventions (SARON)
CHF_CONVENTIONS = CurrencyConventions(
    currency="CHF",
    calendar=ql.Switzerland(),
    day_counter=ql.Actual360(),
    business_day_convention=ql.ModifiedFollowing,
    spot_lag_days=2,
)


# Registry of all conventions
CURRENCY_CONVENTIONS: Dict[str, CurrencyConventions] = {
    "USD": USD_CONVENTIONS,
    "EUR": EUR_CONVENTIONS,
    "GBP": GBP_CONVENTIONS,
    "JPY": JPY_CONVENTIONS,
    "CHF": CHF_CONVENTIONS,
}


def get_conventions(currency: str) -> CurrencyConventions:
    """Get conventions for a currency, raising if not found."""
    conv = CURRENCY_CONVENTIONS.get(currency.upper())
    if conv is None:
        raise ValueError(f"No conventions defined for currency: {currency}")
    return conv


@dataclass
class PackageDetectionConfig:
    """Configuration for package detection algorithms."""

    # Time window for grouping trades into packages
    time_window_seconds: int = 60

    # PV01 tolerance for matching legs
    pv01_tolerance: float = 0.10

    # Fly-specific: belly to wing ratio tolerance
    belly_ratio_tolerance: float = 0.15

    # Forward start tolerance (in years)
    forward_years_tolerance: float = 0.05

    # Economic filters
    require_same_currency: bool = True
    require_same_effective_date: bool = True
    require_same_forward: bool = True
    require_same_underlier: bool = True
    require_same_platform: bool = True
    require_same_cleared_flag: bool = True


@dataclass
class SDRColumnConfig:
    """Column name mappings for SDR data."""

    # Core columns
    trade_id: str = "trade_id"
    execution_timestamp: str = "execution_timestamp"
    effective_date: str = "effective_date"
    expiration_date: str = "expiration_date"

    # Product columns
    product_type: str = "product_type"
    notional: str = "notional"
    notional_currency: str = "notional_currency"
    fixed_rate: str = "fixed_rate"
    strike: str = "strike"

    # Tenor columns
    tenor_years: str = "tenor_years"
    tenor_label: str = "tenor_label"
    forward_start_years: str = "forward_start_years"
    forward_label: str = "forward_label"
    trade_label: str = "trade_label"
    is_forward: str = "is_forward"

    # Risk columns
    estimated_pv01: str = "estimated_pv01"

    # Package columns
    package_type: str = "package_type"
    package_id: str = "package_id"
    package_legs: str = "package_legs"

    # Raw SDR columns
    raw_execution_timestamp: str = "Execution Timestamp"
    raw_effective_date: str = "Effective Date"
    raw_expiration_date: str = "Expiration Date"
    raw_notional: str = "Notional amount-Leg 1"
    raw_currency: str = "Notional currency-Leg 1"
    raw_fixed_rate: str = "Fixed rate-Leg 1"
    raw_strike: str = "Strike Price"
    raw_upi_fisn: str = "UPI FISN"
    raw_upi_underlier: str = "UPI Underlier Name"
    raw_dissemination_id: str = "Dissemination Identifier"
    raw_action_type: str = "Action type"
    raw_platform: str = "Platform identifier"
    raw_cleared: str = "Cleared"


# Default column config
DEFAULT_COLUMNS = SDRColumnConfig()

# Default package detection config
DEFAULT_PACKAGE_CONFIG = PackageDetectionConfig()


@dataclass
class ProductTypeMapping:
    """Mapping of SDR fields to product types."""

    # Product type literals
    OIS_SWAP: str = "OIS_SWAP"
    SWAPTION_CALL: str = "SWAPTION_CALL"
    SWAPTION_PUT: str = "SWAPTION_PUT"
    SWAPTION: str = "SWAPTION_PUT"
    CAP: str = "CAP"
    FLOOR: str = "FLOOR"
    XCCY_SWAP: str = "XCCY_SWAP"
    BASIS_SWAP: str = "BASIS_SWAP"
    FRA: str = "FRA"
    UNKNOWN: str = "UNKNOWN"


PRODUCT_TYPES = ProductTypeMapping()


@dataclass
class PackageTypeMapping:
    """Package type literals."""

    # Linear swap packages
    OUTRIGHT: str = "OUTRIGHT"
    CURVE: str = "CURVE"
    FLY: str = "FLY"
    MMS: str = "MATCHEDMATURITY"

    # Swaption packages - basic
    STRADDLE: str = "STRADDLE"
    STRANGLE: str = "STRANGLE"
    RISK_REVERSAL: str = "RISK_REVERSAL"

    # Swaption packages - vertical spreads
    VERTICAL_SPREAD_1x1: str = "VERTICAL_SPREAD_1x1"
    VERTICAL_SPREAD_1x1_5: str = "VERTICAL_SPREAD_1x1.5"
    VERTICAL_SPREAD_1x2: str = "VERTICAL_SPREAD_1x2"
    VERTICAL_SPREAD_1x3: str = "VERTICAL_SPREAD_1x3"

    # Swaption packages - conditional curve
    CONDITIONAL_STEEPENER: str = "CONDITIONAL_STEEPENER"
    CONDITIONAL_FLATTENER: str = "CONDITIONAL_FLATTENER"

    # Swaption packages - vega curve
    VEGA_EXPIRY_SPREAD: str = "VEGA_EXPIRY_SPREAD"
    VEGA_TAIL_SPREAD: str = "VEGA_TAIL_SPREAD"
    VEGA_DIAGONAL: str = "VEGA_DIAGONAL"

    # Vega-based packages
    VEGA_BUCKETED_PACKAGE: str = "VEGA_BUCKETED_PACKAGE"
    IMPLIED_PACKAGE_SAME_TIMESTAMP: str = "IMPLIED_PACKAGE_SAME_TIMESTAMP"
    DELTA_HEDGE: str = "DELTA_HEDGE"


PACKAGE_TYPES = PackageTypeMapping()
