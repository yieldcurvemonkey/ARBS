# SDRUtils/packages/ptp_grouper.py
"""PTP-based package pre-grouper and structure classifier.

Groups SDR legs sharing the same (exec_ts, PTP, UPI, platform,
package_indicator=True) into PTP super-packages before DV01-based
detectors run. Prevents split-package and mis-classification errors.
"""
from __future__ import annotations

from typing import Optional

import numpy as np
import pandas as pd


def group_by_ptp(
    df: pd.DataFrame,
    *,
    time_tolerance_seconds: int = 5,
    exec_col: str = "execution_timestamp",
    ptp_col: str = "package_transaction_price",
    pkg_ind_col: str = "package_indicator",
    upi_col: str = "unique_product_identifier",
    platform_col: str = "platform_identifier",
    trade_id_col: str = "trade_id",
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Partition legs into PTP groups and non-PTP remainder.

    Returns (ptp_groups_df, non_ptp_df).  PTP groups have
    ``ptp_group_id`` and ``ptp_group_size`` columns added.
    """
    if df.empty:
        empty = df.copy()
        empty["ptp_group_id"] = None
        empty["ptp_group_size"] = 0
        return empty.iloc[:0], empty.iloc[:0]

    ptp_vals = pd.to_numeric(df.get(ptp_col), errors="coerce")
    pkg_ind = df.get(pkg_ind_col)
    if pkg_ind is None:
        pkg_ind = pd.Series(False, index=df.index)
    pkg_ind_bool = pkg_ind.astype(str).str.lower().isin({"true", "t", "1", "yes"})

    candidate_mask = pkg_ind_bool & ptp_vals.notna() & (ptp_vals > 0)
    if not candidate_mask.any():
        out = df.copy()
        out["ptp_group_id"] = None
        out["ptp_group_size"] = 0
        return out.iloc[:0], out

    candidates = df.loc[candidate_mask].copy()
    remainder = df.loc[~candidate_mask].copy()

    ts = pd.to_datetime(candidates[exec_col], errors="coerce", utc=True)
    candidates["_ts_epoch"] = ts.astype("int64") // 10**9
    candidates = candidates.sort_values("_ts_epoch", kind="mergesort")

    epoch = candidates["_ts_epoch"].values
    cluster_ids = np.zeros(len(candidates), dtype=np.int64)
    cid = 0
    for i in range(1, len(candidates)):
        if epoch[i] - epoch[i - 1] > time_tolerance_seconds:
            cid += 1
        cluster_ids[i] = cid
    candidates["_time_cluster"] = cluster_ids

    ptp_rounded = pd.to_numeric(candidates[ptp_col], errors="coerce")
    upi = candidates[upi_col].fillna("_NONE_").astype(str) if upi_col in candidates.columns else "_NONE_"
    plat = candidates[platform_col].fillna("_NONE_").astype(str) if platform_col in candidates.columns else "_NONE_"

    candidates["_group_key"] = (
        candidates["_time_cluster"].astype(str) + "|"
        + ptp_rounded.astype(str) + "|"
        + upi + "|"
        + plat
    )

    group_sizes = candidates.groupby("_group_key")[trade_id_col].transform("count")
    in_group = group_sizes >= 2
    grouped = candidates.loc[in_group].copy()
    ungrouped = candidates.loc[~in_group].copy()

    if grouped.empty:
        remainder = pd.concat([remainder, ungrouped], ignore_index=True)
        remainder["ptp_group_id"] = None
        remainder["ptp_group_size"] = 0
        grouped["ptp_group_id"] = None
        grouped["ptp_group_size"] = 0
        return grouped, remainder

    min_tid = grouped.groupby("_group_key")[trade_id_col].transform("min")
    grouped["ptp_group_id"] = "PTP_" + min_tid.astype(str)
    grouped["ptp_group_size"] = grouped.groupby("ptp_group_id")[trade_id_col].transform("count").astype(int)

    grouped.drop(columns=["_ts_epoch", "_time_cluster", "_group_key"], inplace=True)
    ungrouped.drop(columns=["_ts_epoch", "_time_cluster", "_group_key"], inplace=True, errors="ignore")
    remainder = pd.concat([remainder, ungrouped], ignore_index=True)
    remainder["ptp_group_id"] = None
    remainder["ptp_group_size"] = 0

    return grouped, remainder
