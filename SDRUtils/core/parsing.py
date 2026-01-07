"""
Data parsing utilities for SDR analytics.

This module provides functions for parsing SDR data fields
like notional amounts, rates, and other numeric values.
"""

from __future__ import annotations

from typing import Union

import numpy as np
import pandas as pd


def parse_notional(notional_str: Union[str, float, int]) -> float:
    """
    Parse notional string like '31,000,000' to float.

    Handles various formats including:
    - Comma-separated numbers: "31,000,000"
    - Plain numbers: 31000000
    - Already float/int values

    Args:
        notional_str: Notional value in string or numeric format

    Returns:
        Parsed notional as float, or 0.0 if parsing fails
    """
    if pd.isna(notional_str) or notional_str == "":
        return 0.0
    if isinstance(notional_str, (int, float)):
        return float(notional_str)
    
    # capped notionals
    if "+" in notional_str:
        return float(str(notional_str).replace(",", "").replace("+", "").strip()), True
    
    # Remove commas and convert
    try:
        return float(str(notional_str).replace(",", "").strip())
    except Exception:
        return 0.0


def to_float(x) -> float:
    """
    Convert value to float, returning NaN for invalid values.

    Handles:
    - Numeric types (int, float, numpy numeric)
    - String representations with commas
    - Empty/null values

    Args:
        x: Value to convert

    Returns:
        Float value, or np.nan if conversion fails
    """
    if pd.isna(x) or x == "":
        return np.nan
    if isinstance(x, (int, float, np.integer, np.floating)):
        return float(x)
    s = str(x).strip().replace(",", "")
    try:
        return float(s)
    except Exception:
        return np.nan


def pv01_bucket(pv01: np.ndarray, tol: float) -> np.ndarray:
    """
    Bucket PV01 values by log scale for grouping similar-risk trades.

    Uses log scale so that "within % tolerance" becomes "nearby buckets".

    Args:
        pv01: Array of PV01 values
        tol: Tolerance as fraction (e.g., 0.10 for 10%)

    Returns:
        Array of bucket indices
    """
    pv01_pos = np.maximum(pv01, 1e-12)
    return np.floor(np.log(pv01_pos) / np.log(1.0 + tol)).astype(np.int32)


def tenor_bucket(tenor_years: np.ndarray, bucket_size: float = 0.25) -> np.ndarray:
    """
    Bucket tenor values for grouping similar tenors.

    Args:
        tenor_years: Array of tenor values in years
        bucket_size: Size of each bucket in years

    Returns:
        Array of bucket indices
    """
    return np.floor(tenor_years / bucket_size).astype(np.int32)


def extract_numeric_from_string(s: str, default: float = np.nan) -> float:
    """
    Extract first numeric value from a string.

    Args:
        s: String that may contain a number
        default: Default value if no number found

    Returns:
        Extracted float value or default
    """
    import re

    if pd.isna(s) or s == "":
        return default

    match = re.search(r"[-+]?\d*\.?\d+", str(s))
    if match:
        try:
            return float(match.group())
        except Exception:
            return default
    return default


def safe_get(row: pd.Series, key: str, default=None):
    """
    Safely get a value from a pandas Series.

    Args:
        row: pandas Series (typically a DataFrame row)
        key: Column name to retrieve
        default: Default value if key not found or value is null

    Returns:
        Value or default
    """
    val = row.get(key)
    if pd.isna(val):
        return default
    return val


def normalize_currency(currency: str) -> str:
    """
    Normalize currency code to uppercase 3-letter format.

    Args:
        currency: Currency string

    Returns:
        Normalized currency code
    """
    if pd.isna(currency) or currency == "":
        return ""
    return str(currency).strip().upper()[:3]


# Backward compatibility aliases
_parse_notional = parse_notional
_to_float = to_float
_pv01_bucket = pv01_bucket
