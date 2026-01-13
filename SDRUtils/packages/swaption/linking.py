"""
Package linking for swaption packages.

Second-pass linking of separate packages based on time proximity and vega overlap.
"""

from __future__ import annotations

from typing import Dict, List, Optional, Set

import numpy as np
import pandas as pd


def link_packages(
    df: pd.DataFrame,
    *,
    # Time window for linking
    time_window_link_seconds: int = 600,
    # Vega parameters
    vega_tolerance_pct: float = 0.00,
    # Column names
    package_col: str = "package_type",
    exec_col: str = "execution_timestamp",
    platform_col: str = "platform_identifier",
    currency_col: str = "notional_currency",
    # Economic filters
    require_same_platform: bool = True,
    require_same_currency: bool = True,
) -> pd.DataFrame:
    """
    Second-pass linking of separate swaption packages.

    Links packages that:
    - Are on the same platform
    - Have time gap <= time_window_link_seconds
    - Have vega overlap / similarity within tolerance

    This handles the 9m1y vs 1y1y example where two separate packages
    are economically linked.

    Args:
        df: DataFrame with package annotations from detection
        time_window_link_seconds: Max time gap for linking packages
        vega_tolerance_pct: Vega tolerance for linking (slightly relaxed)
        package_col: Column name for package type
        exec_col: Column name for execution timestamp
        platform_col: Column name for platform identifier
        currency_col: Column name for currency
        require_same_platform: Require same platform for linking
        require_same_currency: Require same currency for linking

    Returns:
        DataFrame with additional columns:
        - linked_package_id: ID linking related packages
        - linked_package_relation: Relation type (e.g., LINKED_BY_TIME_VEGA)
    """
    if df.empty:
        return df

    out = df.copy()

    # Initialize output columns
    if "linked_package_id" not in out.columns:
        out["linked_package_id"] = None
    if "linked_package_relation" not in out.columns:
        out["linked_package_relation"] = None

    # Find detected packages (non-null package_id with SWAPTION-related types)
    swaption_package_types = ["VEGA_BUCKETED_PACKAGE", "IMPLIED_PACKAGE_SAME_TIMESTAMP"]
    has_package = out["package_id"].notna() & out[package_col].isin(swaption_package_types)

    if not has_package.any():
        return out

    # Get unique packages with their characteristics
    packaged_df = out.loc[has_package].copy()

    # Aggregate package info
    package_info = packaged_df.groupby("package_id").agg(
        {
            exec_col: ["min", "max"],
            platform_col: "first",
            currency_col: "first",
            "package_confidence": "first",
        }
    )
    package_info.columns = ["time_min", "time_max", "platform", "currency", "confidence"]
    package_info["time_mid"] = (
        pd.to_datetime(package_info["time_min"]).astype(np.int64) // 10**9 +
        pd.to_datetime(package_info["time_max"]).astype(np.int64) // 10**9
    ) // 2

    # Compute package-level vega (sum of leg vegas)
    if "effective_premium" in packaged_df.columns:
        package_vega = packaged_df.groupby("package_id")["effective_premium"].sum()
    else:
        package_vega = pd.Series(dtype=float)

    package_info["total_vega"] = package_vega
    package_info = package_info.reset_index()

    if len(package_info) < 2:
        return out

    # Find linkable packages
    link_groups: Dict[str, str] = {}
    linked: Set[str] = set()
    link_counter = 0

    pkg_ids = package_info["package_id"].tolist()
    n_pkgs = len(pkg_ids)

    for i in range(n_pkgs):
        if pkg_ids[i] in linked:
            continue

        pid_i = pkg_ids[i]
        time_i = package_info.iloc[i]["time_mid"]
        plat_i = package_info.iloc[i]["platform"]
        ccy_i = package_info.iloc[i]["currency"]
        vega_i = package_info.iloc[i].get("total_vega", np.nan)

        group = [pid_i]

        for j in range(i + 1, n_pkgs):
            if pkg_ids[j] in linked:
                continue

            pid_j = pkg_ids[j]
            time_j = package_info.iloc[j]["time_mid"]
            plat_j = package_info.iloc[j]["platform"]
            ccy_j = package_info.iloc[j]["currency"]
            vega_j = package_info.iloc[j].get("total_vega", np.nan)

            # Check time proximity
            if abs(time_i - time_j) > time_window_link_seconds:
                continue

            # Check same platform and currency
            if require_same_platform and plat_i != plat_j:
                continue
            if require_same_currency and ccy_i != ccy_j:
                continue

            # Check vega similarity
            if pd.notna(vega_i) and pd.notna(vega_j) and vega_i > 0 and vega_j > 0:
                avg_vega = 0.5 * (vega_i + vega_j)
                vega_rel = abs(vega_i - vega_j) / max(avg_vega, 1e-12)
                if vega_rel <= vega_tolerance_pct * 2:  # Slightly relaxed for linking
                    group.append(pid_j)

        if len(group) > 1:
            link_counter += 1
            link_id = f"LINKED_{link_counter}"
            for pid in group:
                linked.add(pid)
                link_groups[pid] = link_id

    # Apply link annotations
    if link_groups:
        for pid, link_id in link_groups.items():
            mask = out["package_id"] == pid
            out.loc[mask, "linked_package_id"] = link_id
            out.loc[mask, "linked_package_relation"] = "LINKED_BY_TIME_VEGA"

    return out
