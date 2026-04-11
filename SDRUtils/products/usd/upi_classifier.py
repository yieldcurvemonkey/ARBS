from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional

import pandas as pd

from SDRUtils.products.usd.linear_base import (
    BasisType,
    LinearProductType,
    RateIndex,
)


@dataclass
class UPIClassification:
    rate_index: Optional[RateIndex] = None
    product_type: Optional[LinearProductType] = None
    basis_type: Optional[BasisType] = None
    leg1_index: Optional[str] = None
    leg2_index: Optional[str] = None


_SOFR_PATTERNS = re.compile(r"USD-SOFR", re.IGNORECASE)
_FF_PATTERNS = re.compile(r"USD-Federal Funds", re.IGNORECASE)
_OBFR_PATTERN = re.compile(r"USD-Overnight Bank Funding", re.IGNORECASE)
_CMS_PATTERN = re.compile(r"USD-ISDA-Swap Rate|USD-CMS", re.IGNORECASE)
_SIFMA_PATTERN = re.compile(r"USD-SIFMA|USD-BMA", re.IGNORECASE)
_BASIS_SEPARATOR = re.compile(r"\s+vs\s+", re.IGNORECASE)


def classify_rate_index(
    upi_underlier: Optional[str],
    upi_fisn: Optional[str],
) -> UPIClassification:
    if upi_underlier is None or (isinstance(upi_underlier, float) and pd.isna(upi_underlier)):
        return UPIClassification()

    underlier = str(upi_underlier).strip()

    # Check for basis (float-float) — contains " vs "
    parts = _BASIS_SEPARATOR.split(underlier)
    if len(parts) == 2:
        return _classify_basis(parts[0].strip(), parts[1].strip(), underlier)

    # Single-index products
    return _classify_single(underlier)


def _classify_basis(leg1: str, leg2: str, full: str) -> UPIClassification:
    has_sofr_1 = bool(_SOFR_PATTERNS.search(leg1))
    has_sofr_2 = bool(_SOFR_PATTERNS.search(leg2))
    has_ff_1 = bool(_FF_PATTERNS.search(leg1))
    has_ff_2 = bool(_FF_PATTERNS.search(leg2))
    has_obfr_1 = bool(_OBFR_PATTERN.search(leg1))
    has_cms_1 = bool(_CMS_PATTERN.search(leg1))
    has_cms_2 = bool(_CMS_PATTERN.search(leg2))
    has_sifma_1 = bool(_SIFMA_PATTERN.search(leg1))
    has_sifma_2 = bool(_SIFMA_PATTERN.search(leg2))

    basis_type = None

    if (has_ff_1 and has_sofr_2) or (has_sofr_1 and has_ff_2):
        basis_type = BasisType.SOFR_FF
    elif has_obfr_1 and has_sofr_2:
        basis_type = BasisType.OBFR_SOFR
    elif has_sofr_1 and has_sofr_2:
        basis_type = BasisType.SOFR_TENOR
    elif has_ff_1 and has_ff_2:
        basis_type = BasisType.FF_TENOR
    elif has_cms_1 and has_cms_2:
        basis_type = BasisType.CMS
    elif has_sifma_1 or has_sifma_2:
        basis_type = BasisType.SIFMA
    elif (has_sofr_1 or has_sofr_2) and not (has_sofr_1 and has_sofr_2):
        basis_type = BasisType.XCCY
    elif (has_ff_1 or has_ff_2) and not (has_ff_1 and has_ff_2):
        basis_type = BasisType.XCCY

    if basis_type is None:
        return UPIClassification()

    return UPIClassification(
        product_type=LinearProductType.BASIS,
        basis_type=basis_type,
        leg1_index=leg1,
        leg2_index=leg2,
    )


def _is_compound_index(underlier: str) -> bool:
    """Detect explicit COMPOUND index (e.g. USD-SOFR-COMPOUND, not USD-SOFR-OIS Compound)."""
    upper = underlier.upper()
    return bool(re.search(r"-COMPOUND\b", upper))


def _classify_single(underlier: str) -> UPIClassification:
    if _SOFR_PATTERNS.search(underlier):
        idx = RateIndex.SOFR_COMPOUND if _is_compound_index(underlier) else RateIndex.SOFR
        return UPIClassification(rate_index=idx, product_type=LinearProductType.OIS)

    if _FF_PATTERNS.search(underlier):
        idx = RateIndex.FED_FUNDS_COMPOUND if _is_compound_index(underlier) else RateIndex.FED_FUNDS
        return UPIClassification(rate_index=idx, product_type=LinearProductType.OIS)

    if _OBFR_PATTERN.search(underlier):
        return UPIClassification(rate_index=RateIndex.OBFR, product_type=LinearProductType.OIS)

    if _CMS_PATTERN.search(underlier):
        return UPIClassification(rate_index=RateIndex.CMS, product_type=LinearProductType.OIS)

    if _SIFMA_PATTERN.search(underlier):
        return UPIClassification(rate_index=RateIndex.SIFMA, product_type=LinearProductType.OIS)

    return UPIClassification()
