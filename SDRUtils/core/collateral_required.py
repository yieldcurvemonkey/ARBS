"""Collateralisation category required-fields validator.

Implements [#115] collateralisation category → required P45 Appendix E
fields mapping. A row whose collateralisation category declares PRC1
("partial") without populating the VM pre-haircut fields [#125]/[#127]
is non-compliant; we surface that via ``missing_required_fields``
rather than dropping or silently imputing (see design D4).
"""
from __future__ import annotations

from typing import Dict, List, Optional, Set

import pandas as pd


# Appendix E mappings — minimal authoritative subset used by the
# dashboard. Full mapping lives in the Tech Spec; we encode the fields
# required for each observed category.
COLLATERAL_REQUIRED_FIELDS: Dict[str, Set[str]] = {
    # Uncollateralised — no VM/IM required.
    "UNCL": set(),
    # Partially collateralised — requires VM pre-haircut for both sides.
    "PRC1": {
        "Initial margin posted by the reporting counterparty (pre-haircut)",
        "Variation margin posted by the reporting counterparty (pre-haircut)",
    },
    # One-way collateralised — requires VM from one side.
    "OWC1": {
        "Variation margin posted by the reporting counterparty (pre-haircut)",
    },
    # Fully collateralised.
    "FLCL": {
        "Initial margin posted by the reporting counterparty (pre-haircut)",
        "Variation margin posted by the reporting counterparty (pre-haircut)",
        "Initial margin collected by the reporting counterparty (pre-haircut)",
        "Variation margin collected by the reporting counterparty (pre-haircut)",
    },
    # Unknown / narrative — no validation.
    "NARR": set(),
}


def missing_required_fields(
    row: pd.Series,
    category_col: str = "Collateralisation category",
) -> List[str]:
    """Return list of field names that the row's category requires but
    leaves null / empty / NaN.

    Args:
        row: A single pandas Series (DataFrame row).
        category_col: Column holding [#115] Collateralisation category.
    """
    category = row.get(category_col)
    if category is None or (isinstance(category, float) and pd.isna(category)):
        return []
    key = str(category).strip().upper()
    required = COLLATERAL_REQUIRED_FIELDS.get(key)
    if not required:
        return []
    missing: List[str] = []
    for field in required:
        val = row.get(field)
        if val is None:
            missing.append(field)
            continue
        if isinstance(val, float) and pd.isna(val):
            missing.append(field)
            continue
        if isinstance(val, str) and val.strip() == "":
            missing.append(field)
    return missing


def enrich_collateral_columns(
    df: pd.DataFrame,
    category_col: str = "Collateralisation category",
) -> pd.DataFrame:
    """Materialize ``missing_required_fields`` (list[str]) column."""
    if category_col not in df.columns:
        df["missing_required_fields"] = [[] for _ in range(len(df))]
        return df
    df["missing_required_fields"] = [
        missing_required_fields(df.iloc[i], category_col) for i in range(len(df))
    ]
    return df
