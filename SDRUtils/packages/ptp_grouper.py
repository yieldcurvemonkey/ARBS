# SDRUtils/packages/ptp_grouper.py
"""PTP-based package pre-grouper and structure classifier.

Groups SDR legs sharing the same (exec_ts, PTP, platform,
package_indicator=True) into PTP super-packages before DV01-based
detectors run.  UPI is intentionally excluded from the grouping key
because multi-tenor / multi-forward packages have different UPIs per
leg yet belong to the same package.

Large groups (>3 legs) are decomposed into balanced fly/curve
sub-packages when possible, preventing over-grouping when multiple
distinct packages share the same PTP at the same execution time.
"""
from __future__ import annotations

import numpy as np
import pandas as pd


def numeric_like(series: pd.Series) -> pd.Series:
    """Tolerant numeric coercion for raw SDR string columns.

    At detection time ``Package transaction price`` / ``Other payment
    amount`` arrive as raw DTCC strings — thousands separators
    (``'88,100'``), dollar signs, parenthesised negatives, blanks.
    Plain ``pd.to_numeric(errors="coerce")`` turns every comma-formatted
    value into NaN, which silently disqualified all USD-amount packages
    >= $1,000 from PTP grouping. Mirrors ``_coerce_numeric_like`` in
    ``usd_swaps.py``.
    """
    if pd.api.types.is_numeric_dtype(series):
        return pd.to_numeric(series, errors="coerce")
    normalized = (
        series.astype("string")
        .str.strip()
        .str.replace(",", "", regex=False)
        .str.replace("$", "", regex=False)
        .str.replace(r"^\((.*)\)$", r"-\1", regex=True)
    )
    normalized = normalized.where(
        ~normalized.isin(["", "None", "none", "nan", "NaN"]), other=pd.NA
    )
    return pd.to_numeric(normalized, errors="coerce")


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
        empty["ptp_group_size"] = None
        return empty.iloc[:0], empty.iloc[:0]

    ptp_vals = numeric_like(df.get(ptp_col, pd.Series(index=df.index, dtype=object)))
    pkg_ind = df.get(pkg_ind_col)
    if pkg_ind is None:
        pkg_ind = pd.Series(False, index=df.index)
    # "1.0" covers boolean columns that arrive as float dtype (NaN-padded).
    pkg_ind_bool = pkg_ind.astype(str).str.lower().isin({"true", "t", "1", "1.0", "yes"})

    if exec_col in df.columns:
        ts_all = pd.to_datetime(df[exec_col], errors="coerce", utc=True)
    else:
        ts_all = pd.Series(pd.NaT, index=df.index)

    # NaT timestamps can't satisfy a time-window constraint — their int64
    # epoch is the NaT sentinel, which would cluster all NaT rows together.
    candidate_mask = (
        pkg_ind_bool & ptp_vals.notna() & (ptp_vals != 0) & ts_all.notna()
    )
    if not candidate_mask.any():
        out = df.copy()
        out["ptp_group_id"] = None
        out["ptp_group_size"] = None
        return out.iloc[:0], out

    candidates = df.loc[candidate_mask].copy()
    remainder = df.loc[~candidate_mask].copy()

    candidates["_ts_epoch"] = ts_all.loc[candidate_mask].astype("int64") // 10**9

    ptp_key = ptp_vals.loc[candidate_mask].astype(str)
    plat = candidates[platform_col].fillna("_NONE_").astype(str) if platform_col in candidates.columns else "_NONE_"
    candidates["_match_key"] = ptp_key + "|" + plat

    # Time-cluster within each (PTP, platform) partition.  Clustering
    # globally would let an unrelated trade sitting between two legs of the
    # same key bridge them into one group even when they are further than
    # the tolerance apart.
    candidates = candidates.sort_values(["_match_key", "_ts_epoch"], kind="mergesort")

    key_arr = candidates["_match_key"].values
    epoch = candidates["_ts_epoch"].values
    cluster_ids = np.zeros(len(candidates), dtype=np.int64)
    cid = 0
    for i in range(1, len(candidates)):
        if key_arr[i] != key_arr[i - 1] or epoch[i] - epoch[i - 1] > time_tolerance_seconds:
            cid += 1
        cluster_ids[i] = cid
    candidates["_group_key"] = cluster_ids

    group_sizes = candidates.groupby("_group_key")[trade_id_col].transform("count")
    in_group = group_sizes >= 2
    grouped = candidates.loc[in_group].copy()
    ungrouped = candidates.loc[~in_group].copy()

    if grouped.empty:
        remainder = pd.concat([remainder, ungrouped], ignore_index=True)
        remainder["ptp_group_id"] = None
        remainder["ptp_group_size"] = None
        grouped["ptp_group_id"] = None
        grouped["ptp_group_size"] = None
        return grouped, remainder

    min_tid = grouped.groupby("_group_key")[trade_id_col].transform("min")
    grouped["ptp_group_id"] = "PTP_" + min_tid.astype(str)
    grouped["ptp_group_size"] = grouped.groupby("ptp_group_id")[trade_id_col].transform("count").astype(int)

    grouped.drop(columns=["_ts_epoch", "_match_key", "_group_key"], inplace=True)
    ungrouped.drop(columns=["_ts_epoch", "_match_key", "_group_key"], inplace=True, errors="ignore")
    remainder = pd.concat([remainder, ungrouped], ignore_index=True)
    remainder["ptp_group_id"] = None
    remainder["ptp_group_size"] = None

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
    rate_col: str = "fixed_rate",
) -> list[dict]:
    """Detect DV01-balanced fly triplets within a large group.

    Returns list of sub-structure annotations. Non-greedy: only
    reports sub-flies if ALL legs are consumed by complete triplets.
    """
    tenors = numeric_like(group_df[tenor_years_col])
    pv01 = numeric_like(group_df[pv01_col]).fillna(0)
    tids = group_df[trade_id_col].astype(str)
    rates = numeric_like(group_df[rate_col]) if rate_col in group_df.columns else pd.Series(0.0, index=group_df.index)

    distinct_tenors = sorted(tenors.round(1).dropna().unique())
    if len(distinct_tenors) != 3:
        return []

    by_tenor = {}
    for idx, (t, p, tid, r) in enumerate(zip(tenors, pv01, tids, rates)):
        bucket = round(t, 1)
        by_tenor.setdefault(bucket, []).append({"pv01": p, "tid": tid, "rate": r})

    tenor_keys = sorted(by_tenor.keys())
    if len(tenor_keys) != 3:
        return []

    short_legs = by_tenor[tenor_keys[0]]
    belly_legs = by_tenor[tenor_keys[1]]
    long_legs = by_tenor[tenor_keys[2]]

    if not (len(short_legs) == len(belly_legs) == len(long_legs)):
        return []

    short_sorted = sorted(short_legs, key=lambda x: (x["pv01"], x["rate"]))
    belly_sorted = sorted(belly_legs, key=lambda x: (x["pv01"], x["rate"]))
    long_sorted = sorted(long_legs, key=lambda x: (x["pv01"], x["rate"]))

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


def _try_decompose(
    group_df: pd.DataFrame,
    pv01_col: str = "estimated_pv01",
    tenor_years_col: str = "tenor_years",
    trade_id_col: str = "trade_id",
    belly_tol: float = 0.15,
) -> list[dict] | None:
    """Decompose a large PTP group into balanced fly/curve sub-packages.

    Returns a list of sub-package dicts if ALL legs are consumed,
    else ``None``.  Each dict: ``{"type", "indices", "trade_ids"}``.

    This prevents over-grouping when multiple distinct packages
    (e.g. two separate flies) share the same PTP at the same timestamp.
    """
    pv01_s = numeric_like(group_df[pv01_col]).fillna(0)
    tenor_s = numeric_like(group_df[tenor_years_col])
    tid_s = group_df[trade_id_col].astype(str)

    legs = []
    for pos, (idx, pv, tn, tid) in enumerate(
        zip(group_df.index, pv01_s, tenor_s, tid_s)
    ):
        legs.append({
            "pos": pos,
            "idx": idx,
            "pv01": float(pv) if pd.notna(pv) else 0.0,
            "tenor": round(float(tn), 1) if pd.notna(tn) else float("nan"),
            "tid": tid,
        })

    used: set[int] = set()
    sub_pkgs: list[dict] = []

    # Phase 1: greedy fly detection (belly-first by descending PV01)
    for belly in sorted(legs, key=lambda x: -x["pv01"]):
        if belly["pos"] in used or belly["pv01"] <= 0:
            continue
        target_wing = belly["pv01"] / 2.0

        best_short: dict | None = None
        best_short_rel = float("inf")
        best_long: dict | None = None
        best_long_rel = float("inf")

        for wing in legs:
            if wing["pos"] in used or wing["pos"] == belly["pos"]:
                continue
            if np.isnan(wing["tenor"]) or np.isnan(belly["tenor"]):
                continue
            if wing["tenor"] == belly["tenor"]:
                continue
            rel = abs(wing["pv01"] - target_wing) / max(target_wing, 1e-12)
            if rel > belly_tol:
                continue
            if wing["tenor"] < belly["tenor"] and rel < best_short_rel:
                best_short, best_short_rel = wing, rel
            elif wing["tenor"] > belly["tenor"] and rel < best_long_rel:
                best_long, best_long_rel = wing, rel

        if best_short is not None and best_long is not None:
            wing_avg = (best_short["pv01"] + best_long["pv01"]) / 2.0
            expected_belly = 2.0 * wing_avg
            if wing_avg > 0:
                b_rel = abs(belly["pv01"] - expected_belly) / max(expected_belly, 1e-12)
                w_rel = abs(best_short["pv01"] - best_long["pv01"]) / max(wing_avg, 1e-12)
                if b_rel <= belly_tol and w_rel <= belly_tol:
                    used.update({best_short["pos"], belly["pos"], best_long["pos"]})
                    sub_pkgs.append({
                        "type": "FLY",
                        "indices": [best_short["idx"], belly["idx"], best_long["idx"]],
                        "trade_ids": [best_short["tid"], belly["tid"], best_long["tid"]],
                    })

    # Phase 2: greedy curve detection from remaining legs
    remaining = sorted(
        [l for l in legs if l["pos"] not in used],
        key=lambda x: x["tenor"],
    )
    paired: set[int] = set()
    for i, a in enumerate(remaining):
        if i in paired:
            continue
        best_j: int | None = None
        best_rel = float("inf")
        for j in range(i + 1, len(remaining)):
            if j in paired:
                continue
            b = remaining[j]
            if np.isnan(a["tenor"]) or np.isnan(b["tenor"]):
                continue
            if a["tenor"] == b["tenor"]:
                continue
            avg = (a["pv01"] + b["pv01"]) / 2.0
            if avg <= 0:
                continue
            rel = abs(a["pv01"] - b["pv01"]) / avg
            if rel <= belly_tol and rel < best_rel:
                best_j, best_rel = j, rel
        if best_j is not None:
            b = remaining[best_j]
            paired.update({i, best_j})
            used.update({a["pos"], b["pos"]})
            sub_pkgs.append({
                "type": "CURVE",
                "indices": [a["idx"], b["idx"]],
                "trade_ids": [a["tid"], b["tid"]],
            })

    if len(used) == len(legs) and len(sub_pkgs) >= 2:
        return sub_pkgs
    return None


def _classify_single_group(
    group_df: pd.DataFrame,
    pv01_col: str = "estimated_pv01",
    tenor_years_col: str = "tenor_years",
    trade_id_col: str = "trade_id",
    belly_tol: float = 0.15,
    rate_col: str = "fixed_rate",
) -> tuple[str, list[dict]]:
    """Classify one PTP group. Returns (package_type, sub_structures)."""
    n = len(group_df)
    pv01 = numeric_like(group_df[pv01_col]).fillna(0).values
    tenor_num = numeric_like(group_df[tenor_years_col])
    n_distinct_tenors = tenor_num.round(1).dropna().nunique()

    if n == 2:
        if n_distinct_tenors == 2 and _is_dv01_balanced(list(pv01), tolerance=belly_tol):
            return "CURVE", []
        return "PKG-2", []

    if n == 3:
        if n_distinct_tenors == 3:
            sorted_idx = tenor_num.fillna(0).argsort()
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
        trade_id_col=trade_id_col, belly_tol=belly_tol, rate_col=rate_col,
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

        # For large groups that aren't already FLY/CURVE, detect
        # balanced sub-structures (flies/curves) and record them in
        # ptp_sub_structures for display, but keep the group unified
        # as a single PKG-N. Previous behaviour decomposed them into
        # separate package_ids — that split the SDR-reported package
        # into fragments and lost the single-execution context.
        if len(grp) > 3 and pkg_type.startswith("PKG-"):
            decomposed = _try_decompose(
                grp, pv01_col=pv01_col, tenor_years_col=tenor_years_col,
                trade_id_col=trade_id_col, belly_tol=belly_ratio_tolerance,
            )
            if decomposed is not None:
                sub_structs = [
                    {"type": sub["type"], "legs": sub["trade_ids"]}
                    for sub in decomposed
                ]

        mask = out["ptp_group_id"] == gid
        out.loc[mask, "package_type"] = pkg_type
        out.loc[mask, "package_id"] = gid
        for idx in out.index[mask]:
            out.at[idx, "package_legs"] = all_tids
            out.at[idx, "ptp_sub_structures"] = sub_structs

    return out
