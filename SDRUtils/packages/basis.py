"""
Basis-aware package detection for USD linear products.

Detects packages of basis swaps traded together:
- BASIS_CURVE: Basis swaps across different tenors (e.g. 2Y FF/SOFR + 10Y FF/SOFR)
- BASIS_FLY: 3 basis swaps in butterfly structure
- BASIS_HEDGE: Basis swap + outright = basis-adjusted position
"""

from __future__ import annotations

from enum import Enum
from typing import Dict, List, Optional

import numpy as np
import pandas as pd

from SDRUtils.core.dates import ensure_int64_epoch_seconds
from SDRUtils.packages.base import PackageDetector


class BasisPackageType(str, Enum):
    BASIS_CURVE = "BASIS_CURVE"
    BASIS_FLY = "BASIS_FLY"
    BASIS_HEDGE = "BASIS_HEDGE"


def detect_basis_packages_df(
    df: pd.DataFrame,
    *,
    time_window_seconds: int = 60,
    basis_type_col: str = "basis_type",
    tenor_col: str = "tenor_label",
    effective_date_col: str = "effective_date",
    forward_label_col: str = "forward_label",
    exec_col: str = "execution_timestamp",
    trade_id_col: str = "trade_id",
    package_col: str = "package_type",
    package_id_col: str = "package_id",
    package_legs_col: str = "package_legs",
    platform_col: str = "Platform identifier",
    cleared_col: str = "Cleared",
    require_same_platform: bool = True,
    require_same_cleared: bool = True,
    require_same_upi: bool = True,
    upi_col: str = "Unique Product Identifier",
) -> pd.DataFrame:
    """
    Detect basis swap packages (curves and flies) from classified trades.

    Matching criteria:
    - Same basis_type (e.g. all SOFR_FF)
    - Same effective_date and forward_label
    - Same platform and cleared flag (optional)
    - Different tenor_label (for curve/fly)
    - Within time window

    Returns DataFrame with package annotations applied.
    """
    if df.empty:
        return df

    out = df.copy()

    # Only basis swap candidates without existing package assignment
    has_basis = basis_type_col in out.columns and out[basis_type_col].notna().any()
    if not has_basis:
        return out

    m = out[basis_type_col].notna()
    if package_col in out.columns:
        m &= out[package_col].fillna("OUTRIGHT").values == "OUTRIGHT"

    cand = out.loc[m].copy()
    if len(cand) < 2:
        return out

    # Sort by exec time
    cand["_t"] = ensure_int64_epoch_seconds(cand[exec_col])
    cand.sort_values("_t", inplace=True, kind="mergesort")

    tsec = cand["_t"].to_numpy(dtype=np.int64)
    tenor = cand[tenor_col].astype("string").to_numpy()
    trade_ids = cand[trade_id_col].to_numpy()
    bt = cand[basis_type_col].astype("string").to_numpy()

    eff = (
        pd.to_datetime(cand[effective_date_col], errors="coerce").dt.date.to_numpy()
        if effective_date_col in cand.columns else None
    )
    fwd = cand[forward_label_col].astype("string").to_numpy() if forward_label_col in cand.columns else None
    plat = cand[platform_col].astype("string").to_numpy() if (require_same_platform and platform_col in cand.columns) else None
    clr = cand[cleared_col].astype("string").to_numpy() if (require_same_cleared and cleared_col in cand.columns) else None
    upi = cand[upi_col].astype("string").to_numpy() if (require_same_upi and upi_col in cand.columns) else None

    n = len(cand)
    matched = np.zeros(n, dtype=bool)
    pkg_type_arr = np.full(n, "", dtype=object)
    pkg_id_arr = np.full(n, "", dtype=object)
    pkg_legs_arr = np.full(n, None, dtype=object)
    pkg_counter = 0

    def _match_ok(i: int, j: int) -> bool:
        if bt[i] != bt[j]:
            return False
        if tenor[i] == tenor[j]:
            return False  # Must have different tenors
        if eff is not None and eff[i] != eff[j]:
            return False
        if fwd is not None and fwd[i] != fwd[j]:
            return False
        if plat is not None and plat[i] != plat[j]:
            return False
        if clr is not None and clr[i] != clr[j]:
            return False
        if upi is not None and upi[i] != upi[j]:
            return False
        return True

    # Sliding window cursor approach
    left = 0

    for i in range(n):
        if matched[i]:
            continue

        # Evict old entries
        while left < n and (tsec[i] - tsec[left] > time_window_seconds):
            left += 1

        # Find matching legs in window
        legs = [i]
        for j in range(max(left, i + 1), n):
            if tsec[j] - tsec[i] > time_window_seconds:
                break
            if matched[j]:
                continue
            if _match_ok(i, j):
                legs.append(j)

        if len(legs) < 2:
            continue

        # Classify package type
        if len(legs) == 3:
            pkg_name = BasisPackageType.BASIS_FLY.value
        else:
            # Take first 2 for curve
            legs = legs[:2]
            pkg_name = BasisPackageType.BASIS_CURVE.value

        pkg_counter += 1
        pid = f"BPKG_{pkg_counter}"
        leg_ids = [trade_ids[k] for k in legs]

        for k in legs:
            matched[k] = True
            pkg_type_arr[k] = pkg_name
            pkg_id_arr[k] = pid
            pkg_legs_arr[k] = leg_ids

    # Write back to output
    idx = cand.index
    if package_col not in out.columns:
        out[package_col] = "OUTRIGHT"
    if package_id_col not in out.columns:
        out[package_id_col] = ""
    if package_legs_col not in out.columns:
        out[package_legs_col] = None

    for k, orig_idx in enumerate(idx):
        if matched[k]:
            out.at[orig_idx, package_col] = pkg_type_arr[k]
            out.at[orig_idx, package_id_col] = pkg_id_arr[k]
            out.at[orig_idx, package_legs_col] = pkg_legs_arr[k]

    return out


class BasisPackageDetector(PackageDetector):
    """PackageDetector for basis swap packages."""

    package_type = "BASIS"

    def detect(self, df: pd.DataFrame, **kwargs) -> pd.DataFrame:
        return detect_basis_packages_df(df, **kwargs)
