# SDRUtils/packages/ptp_grouper.py
"""PTP-based package pre-grouper and structure classifier.

Groups SDR legs sharing the same (exec_ts, PTP, UPI, platform,
package_indicator=True) into PTP super-packages before DV01-based
detectors run. Prevents split-package and mis-classification errors.
"""
from __future__ import annotations

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


def _is_dv01_balanced(values: list[float], tolerance: float = 0.15) -> bool:
    if len(values) < 2:
        return False
    avg = sum(values) / len(values)
    if avg <= 0:
        return False
    return all(abs(v - avg) / avg <= tolerance for v in values)


def _detect_sub_flies(
    group_df: pd.DataFrame,
    pv01_col: str = "estimated_pv01",
    tenor_years_col: str = "tenor_years",
    trade_id_col: str = "trade_id",
    belly_tol: float = 0.15,
) -> list[dict]:
    """Detect DV01-balanced fly triplets within a large group.

    Returns list of sub-structure annotations. Non-greedy: only
    reports sub-flies if ALL legs are consumed by complete triplets.
    """
    tenors = pd.to_numeric(group_df[tenor_years_col], errors="coerce")
    pv01 = pd.to_numeric(group_df[pv01_col], errors="coerce").fillna(0)
    tids = group_df[trade_id_col].astype(str)

    distinct_tenors = sorted(tenors.dropna().unique())
    if len(distinct_tenors) != 3:
        return []

    by_tenor = {}
    for idx, (t, p, tid) in enumerate(zip(tenors, pv01, tids)):
        bucket = round(t, 1)
        by_tenor.setdefault(bucket, []).append({"pv01": p, "tid": tid})

    tenor_keys = sorted(by_tenor.keys())
    if len(tenor_keys) != 3:
        return []

    short_legs = by_tenor[tenor_keys[0]]
    belly_legs = by_tenor[tenor_keys[1]]
    long_legs = by_tenor[tenor_keys[2]]

    if not (len(short_legs) == len(belly_legs) == len(long_legs)):
        return []

    short_sorted = sorted(short_legs, key=lambda x: x["pv01"])
    belly_sorted = sorted(belly_legs, key=lambda x: x["pv01"])
    long_sorted = sorted(long_legs, key=lambda x: x["pv01"])

    subs = []
    for s, b, l in zip(short_sorted, belly_sorted, long_sorted):
        wing_avg = (s["pv01"] + l["pv01"]) / 2.0
        expected_belly = 2.0 * wing_avg
        if wing_avg <= 0:
            return []
        belly_rel = abs(b["pv01"] - expected_belly) / max(expected_belly, 1e-12)
        wings_rel = abs(s["pv01"] - l["pv01"]) / max(wing_avg, 1e-12)
        if belly_rel > belly_tol or wings_rel > belly_tol:
            return []
        subs.append({
            "type": "FLY",
            "legs": [s["tid"], b["tid"], l["tid"]],
            "belly_dv01": round(b["pv01"], 2),
        })
    return subs


def _classify_single_group(
    group_df: pd.DataFrame,
    pv01_col: str = "estimated_pv01",
    tenor_years_col: str = "tenor_years",
    trade_id_col: str = "trade_id",
    belly_tol: float = 0.15,
) -> tuple[str, list[dict]]:
    """Classify one PTP group. Returns (package_type, sub_structures)."""
    n = len(group_df)
    pv01 = pd.to_numeric(group_df[pv01_col], errors="coerce").fillna(0).values

    if n == 2:
        if _is_dv01_balanced(list(pv01), tolerance=belly_tol):
            return "CURVE", []
        return "PKG-2", []

    if n == 3:
        sorted_idx = pd.to_numeric(
            group_df[tenor_years_col], errors="coerce"
        ).fillna(0).argsort()
        sorted_pv01 = pv01[sorted_idx]
        wing_avg = (sorted_pv01[0] + sorted_pv01[2]) / 2.0
        expected_belly = 2.0 * wing_avg
        if wing_avg > 0:
            belly_rel = abs(sorted_pv01[1] - expected_belly) / max(expected_belly, 1e-12)
            wings_rel = abs(sorted_pv01[0] - sorted_pv01[2]) / max(wing_avg, 1e-12)
            if belly_rel <= belly_tol and wings_rel <= belly_tol:
                return "FLY", []
        return "PKG-3", []

    sub_flies = _detect_sub_flies(
        group_df, pv01_col=pv01_col, tenor_years_col=tenor_years_col,
        trade_id_col=trade_id_col, belly_tol=belly_tol,
    )
    return f"PKG-{n}", sub_flies


def classify_ptp_groups(
    df: pd.DataFrame,
    *,
    pv01_col: str = "estimated_pv01",
    tenor_years_col: str = "tenor_years",
    trade_id_col: str = "trade_id",
    belly_ratio_tolerance: float = 0.15,
) -> pd.DataFrame:
    """Classify each PTP group holistically. Sets package_type,
    package_id, package_legs, and ptp_sub_structures."""
    if df.empty or "ptp_group_id" not in df.columns:
        return df

    out = df.copy()
    if "package_type" not in out.columns:
        out["package_type"] = "OUTRIGHT"
    if "package_id" not in out.columns:
        out["package_id"] = None
    if "package_legs" not in out.columns:
        out["package_legs"] = None
    out["ptp_sub_structures"] = None

    for gid, grp in out.groupby("ptp_group_id"):
        if pd.isna(gid):
            continue
        all_tids = sorted(grp[trade_id_col].astype(str).tolist())
        pkg_type, sub_structs = _classify_single_group(
            grp, pv01_col=pv01_col, tenor_years_col=tenor_years_col,
            trade_id_col=trade_id_col, belly_tol=belly_ratio_tolerance,
        )
        mask = out["ptp_group_id"] == gid
        out.loc[mask, "package_type"] = pkg_type
        out.loc[mask, "package_id"] = gid
        for idx in out.index[mask]:
            out.at[idx, "package_legs"] = all_tids
            out.at[idx, "ptp_sub_structures"] = sub_structs

    return out
