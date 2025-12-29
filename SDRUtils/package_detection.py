from collections import defaultdict, deque
from typing import Dict, List, Optional, Tuple, Sequence

import numpy as np
import pandas as pd

from SDRUtils.utils import _ensure_int64_epoch_seconds, _pv01_bucket


def detect_curve_trades_df(
    df: pd.DataFrame,
    *,
    time_window_seconds: int = 60,
    pv01_tolerance: float = 0.10,
    require_different_tenor: bool = True,
    require_opposite_direction: bool = False,  # set True if you have/pay-receive direction info
    direction_col: Optional[str] = None,  # e.g. +1 receive fixed, -1 pay fixed
    product_col: str = "product_type",
    package_col: str = "package_type",
    exec_col: str = "execution_timestamp",
    pv01_col: str = "estimated_pv01",
    tenor_col: str = "tenor_label",
    trade_id_col: str = "trade_id",
    # ------------------ economic match filters (NEW) ------------------
    require_same_currency: bool = True,
    currency_col: str = "notional_currency",
    require_same_effective_date: bool = True,
    effective_date_col: str = "effective_date",
    require_same_forward: bool = True,
    forward_label_col: str = "forward_label",
    forward_years_col: str = "forward_start_years",
    forward_years_tol: float = 0.05,  # used if forward_label_col missing
    require_same_underlier: bool = True,
    underlier_col: str = "UPI Underlier Name",
    require_same_platform: bool = True,
    platform_col: str = "Platform identifier",
    require_same_cleared_flag: bool = True,
    cleared_col: str = "Cleared",
) -> pd.DataFrame:
    """
    Fast curve detection on the classifications dataframe.
    Mutates package_type/package_id/package_legs in returned df.

    Economic filters (recommended):
      - same currency (default True)
      - same effective date (default True)
      - same forward bucket (default True; via forward_label else forward_start_years tol)
      - optional same underlier / platform / cleared flag
    """
    if df.empty:
        return df

    out = df.copy()

    # Only candidates
    m = (out[product_col].values == "OIS_SWAP") & (out[pv01_col].fillna(0).values > 0)
    if package_col in out.columns:
        m &= out[package_col].fillna("OUTRIGHT").values == "OUTRIGHT"

    # Build candidate columns list (only include cols that exist)
    cols = [trade_id_col, exec_col, pv01_col, tenor_col]
    if require_opposite_direction and direction_col and direction_col in out.columns:
        cols.append(direction_col)

    if require_same_currency and currency_col in out.columns:
        cols.append(currency_col)
    if require_same_effective_date and effective_date_col in out.columns:
        cols.append(effective_date_col)

    # forward key (prefer label)
    _use_fwd_label = require_same_forward and (forward_label_col in out.columns)
    _use_fwd_years = require_same_forward and (not _use_fwd_label) and (forward_years_col in out.columns)
    if _use_fwd_label:
        cols.append(forward_label_col)
    elif _use_fwd_years:
        cols.append(forward_years_col)

    if require_same_underlier and underlier_col in out.columns:
        cols.append(underlier_col)
    if require_same_platform and platform_col in out.columns:
        cols.append(platform_col)
    if require_same_cleared_flag and cleared_col in out.columns:
        cols.append(cleared_col)

    cand = out.loc[m, cols].copy()
    if cand.empty:
        return out

    # Sort by exec time
    cand["_t"] = _ensure_int64_epoch_seconds(cand[exec_col])
    cand.sort_values("_t", inplace=True, kind="mergesort")  # stable & fast

    pv01 = cand[pv01_col].to_numpy(dtype=np.float64)
    tsec = cand["_t"].to_numpy(dtype=np.int64)
    tenor = cand[tenor_col].astype("string").to_numpy()
    trade_ids = cand[trade_id_col].to_numpy()

    # Precompute econ key arrays for O(1) comparisons
    ccy = cand[currency_col].astype("string").to_numpy() if (require_same_currency and currency_col in cand.columns) else None
    eff = (
        pd.to_datetime(cand[effective_date_col], errors="coerce").dt.date.to_numpy()
        if (require_same_effective_date and effective_date_col in cand.columns)
        else None
    )
    fwd_label = cand[forward_label_col].astype("string").to_numpy() if _use_fwd_label else None
    fwd_years = pd.to_numeric(cand[forward_years_col], errors="coerce").fillna(0.0).to_numpy(dtype=np.float64) if _use_fwd_years else None
    und = cand[underlier_col].astype("string").to_numpy() if (require_same_underlier and underlier_col in cand.columns) else None
    plat = cand[platform_col].astype("string").to_numpy() if (require_same_platform and platform_col in cand.columns) else None
    clr = cand[cleared_col].astype("string").to_numpy() if (require_same_cleared_flag and cleared_col in cand.columns) else None

    # direction as array (avoid cand.iloc in hot loop)
    if require_opposite_direction and direction_col and direction_col in cand.columns:
        dirv = pd.to_numeric(cand[direction_col], errors="coerce").fillna(0.0).to_numpy(dtype=np.float64)
    else:
        dirv = None

    def _econ_ok(i: int, j: int) -> bool:
        if ccy is not None and ccy[i] != ccy[j]:
            return False
        if eff is not None and eff[i] != eff[j]:
            return False
        if fwd_label is not None and fwd_label[i] != fwd_label[j]:
            return False
        if fwd_years is not None and abs(fwd_years[i] - fwd_years[j]) > forward_years_tol:
            return False
        if und is not None and und[i] != und[j]:
            return False
        if plat is not None and plat[i] != plat[j]:
            return False
        if clr is not None and clr[i] != clr[j]:
            return False
        return True

    # PV01 bucket index
    b = _pv01_bucket(pv01, pv01_tolerance)

    bucket_to_indices: Dict[int, List[int]] = {}
    bucket_head: Dict[int, int] = {}

    matched = np.zeros(len(cand), dtype=bool)

    pkg_ids = np.full(len(cand), "", dtype=object)
    pkg_type = np.full(len(cand), "OUTRIGHT", dtype=object)
    pkg_legs = np.full(len(cand), None, dtype=object)

    pkg_counter = 0
    left = 0

    def _evict_old(curr_t: int):
        nonlocal left
        while left < len(cand) and (curr_t - tsec[left] > time_window_seconds):
            left += 1

    for i in range(len(cand)):
        if matched[i]:
            continue

        _evict_old(tsec[i])
        bi = int(b[i])

        best_j = -1
        best_rel = 1e9

        for bb in (bi - 1, bi, bi + 1):
            lst = bucket_to_indices.get(bb)
            if not lst:
                continue

            h = bucket_head.get(bb, 0)
            while h < len(lst) and lst[h] < left:
                h += 1
            bucket_head[bb] = h

            for j in lst[h:]:
                if matched[j]:
                    continue
                if tsec[i] - tsec[j] > time_window_seconds:
                    continue

                # economic guards (fast array comparisons)
                if not _econ_ok(i, j):
                    continue

                if require_different_tenor and tenor[i] == tenor[j]:
                    continue

                if dirv is not None:
                    si = np.sign(dirv[i])
                    sj = np.sign(dirv[j])
                    if si == 0 or sj == 0 or si == sj:
                        continue

                avg = 0.5 * (pv01[i] + pv01[j])
                if avg <= 0:
                    continue
                rel = abs(pv01[i] - pv01[j]) / avg
                if rel <= pv01_tolerance and rel < best_rel:
                    best_rel = rel
                    best_j = j

        if best_j >= 0:
            pkg_counter += 1
            pid = f"CURVE_{pkg_counter}"
            legs = [int(trade_ids[best_j]), int(trade_ids[i])]

            matched[best_j] = True
            matched[i] = True
            pkg_type[best_j] = "CURVE"
            pkg_type[i] = "CURVE"
            pkg_ids[best_j] = pid
            pkg_ids[i] = pid
            pkg_legs[best_j] = legs
            pkg_legs[i] = legs

        bucket_to_indices.setdefault(bi, []).append(i)

    res = pd.DataFrame(
        {
            trade_id_col: trade_ids,
            "_pkg_type": pkg_type,
            "_pkg_id": pkg_ids,
            "_pkg_legs": pkg_legs,
        }
    )

    out = out.merge(res, on=trade_id_col, how="left")

    if package_col not in out.columns:
        out[package_col] = "OUTRIGHT"
    if "package_id" not in out.columns:
        out["package_id"] = None
    if "package_legs" not in out.columns:
        out["package_legs"] = None

    m2 = out["_pkg_type"].notna() & (out["_pkg_type"].values != "OUTRIGHT")
    out.loc[m2, package_col] = out.loc[m2, "_pkg_type"].values
    out.loc[m2, "package_id"] = out.loc[m2, "_pkg_id"].values
    out.loc[m2, "package_legs"] = out.loc[m2, "_pkg_legs"].values

    out.drop(columns=["_pkg_type", "_pkg_id", "_pkg_legs"], inplace=True)
    return out


def detect_fly_trades_df(
    df: pd.DataFrame,
    *,
    time_window_seconds: int = 60,
    belly_ratio_tolerance: float = 0.15,
    product_col: str = "product_type",
    package_col: str = "package_type",
    exec_col: str = "execution_timestamp",
    pv01_col: str = "estimated_pv01",
    tenor_years_col: str = "tenor_years",
    trade_id_col: str = "trade_id",
    # ------------------ economic match filters (NEW) ------------------
    require_same_currency: bool = True,
    currency_col: str = "notional_currency",
    require_same_effective_date: bool = True,
    effective_date_col: str = "effective_date",
    require_same_forward: bool = True,
    forward_label_col: str = "forward_label",
    forward_years_col: str = "forward_start_years",
    forward_years_tol: float = 0.05,  # used if forward_label_col missing
    require_same_underlier: bool = True,
    underlier_col: str = "UPI Underlier Name",
    require_same_platform: bool = True,
    platform_col: str = "Platform identifier",
    # Optional: if you want to prohibit mixing cleared/uncleared etc.
    require_same_cleared_flag: bool = True,
    cleared_col: str = "Cleared",
) -> pd.DataFrame:
    """
    Fast fly detection on the classifications dataframe.

    Strategy:
      - Operate only on OUTRIGHT OIS_SWAP with pv01>0
      - Sort by time
      - Sliding time window
      - Maintain a time-window multimap keyed by (tenor_bucket, pv_bucket)
      - For each new trade as potential belly, find candidate wings near half pv01 on both sides of tenor

    Economic filters (optional, but recommended for SDR):
      - same currency (default True)
      - same effective date (default True)
      - same forward bucket (default True, via forward_label; fallback to forward_start_years tol)
      - optionally same underlier / platform / cleared flag
    """
    if df.empty:
        return df

    out = df.copy()

    # Only candidates
    m = (out[product_col].values == "OIS_SWAP") & (out[pv01_col].fillna(0).values > 0)
    if package_col in out.columns:
        m &= out[package_col].fillna("OUTRIGHT").values == "OUTRIGHT"

    # columns needed
    cols = [trade_id_col, exec_col, pv01_col, tenor_years_col]
    if require_same_currency and currency_col in out.columns:
        cols.append(currency_col)
    if require_same_effective_date and effective_date_col in out.columns:
        cols.append(effective_date_col)
    if require_same_forward:
        if forward_label_col in out.columns:
            cols.append(forward_label_col)
        elif forward_years_col in out.columns:
            cols.append(forward_years_col)
    if require_same_underlier and underlier_col in out.columns:
        cols.append(underlier_col)
    if require_same_platform and platform_col in out.columns:
        cols.append(platform_col)
    if require_same_cleared_flag and cleared_col in out.columns:
        cols.append(cleared_col)

    cand = out.loc[m, cols].copy()
    if cand.empty:
        return out

    cand["_t"] = _ensure_int64_epoch_seconds(cand[exec_col])
    cand.sort_values("_t", inplace=True, kind="mergesort")

    pv01 = cand[pv01_col].to_numpy(dtype=np.float64)
    tsec = cand["_t"].to_numpy(dtype=np.int64)
    ten = cand[tenor_years_col].to_numpy(dtype=np.float64)
    trade_ids = cand[trade_id_col].to_numpy(dtype=np.int64)

    # Precompute economic keys as fast arrays (or None)
    ccy = cand[currency_col].astype("string").to_numpy() if (require_same_currency and currency_col in cand.columns) else None
    eff = (
        pd.to_datetime(cand[effective_date_col], errors="coerce").dt.date.to_numpy()
        if (require_same_effective_date and effective_date_col in cand.columns)
        else None
    )

    fwd_label = cand[forward_label_col].astype("string").to_numpy() if (require_same_forward and forward_label_col in cand.columns) else None
    fwd_years = (
        pd.to_numeric(cand[forward_years_col], errors="coerce").fillna(0.0).to_numpy(dtype=np.float64)
        if (require_same_forward and fwd_label is None and forward_years_col in cand.columns)
        else None
    )

    und = cand[underlier_col].astype("string").to_numpy() if (require_same_underlier and underlier_col in cand.columns) else None
    plat = cand[platform_col].astype("string").to_numpy() if (require_same_platform and platform_col in cand.columns) else None
    clr = cand[cleared_col].astype("string").to_numpy() if (require_same_cleared_flag and cleared_col in cand.columns) else None

    # Buckets
    pv_bucket = _pv01_bucket(pv01, belly_ratio_tolerance)
    ten_bucket = np.floor(ten / 0.25).astype(np.int32)

    store: Dict[Tuple[int, int], List[int]] = {}
    head: Dict[Tuple[int, int], int] = {}

    matched = np.zeros(len(cand), dtype=bool)
    pkg_ids = np.full(len(cand), "", dtype=object)
    pkg_type = np.full(len(cand), "OUTRIGHT", dtype=object)
    pkg_legs = np.full(len(cand), None, dtype=object)

    pkg_counter = 0
    left = 0

    def _evict(curr_t: int):
        nonlocal left
        while left < len(cand) and (curr_t - tsec[left] > time_window_seconds):
            left += 1

    def _active_list(key: Tuple[int, int]) -> List[int]:
        lst = store.get(key)
        if not lst:
            return []
        h = head.get(key, 0)
        while h < len(lst) and lst[h] < left:
            h += 1
        head[key] = h
        return lst[h:]

    # Fast econ guard between i and j
    def _econ_ok(i: int, j: int) -> bool:
        if ccy is not None and ccy[i] != ccy[j]:
            return False
        if eff is not None and eff[i] != eff[j]:
            return False
        if fwd_label is not None and fwd_label[i] != fwd_label[j]:
            return False
        if fwd_years is not None and abs(fwd_years[i] - fwd_years[j]) > forward_years_tol:
            return False
        if und is not None and und[i] != und[j]:
            return False
        if plat is not None and plat[i] != plat[j]:
            return False
        if clr is not None and clr[i] != clr[j]:
            return False
        return True

    for i in range(len(cand)):
        if matched[i]:
            continue

        _evict(tsec[i])

        belly_pv = pv01[i]
        if belly_pv <= 0:
            store.setdefault((int(ten_bucket[i]), int(pv_bucket[i])), []).append(i)
            continue

        target_wing = belly_pv / 2.0
        target_b = int(np.floor(np.log(max(target_wing, 1e-12)) / np.log(1.0 + belly_ratio_tolerance)))

        tb = int(ten_bucket[i])

        wing_candidates: List[int] = []
        for dt in range(-8, 9):
            if dt == 0:
                continue
            tkey = tb + dt
            for db in (-1, 0, 1):
                wing_candidates.extend(_active_list((tkey, target_b + db)))

        if wing_candidates:
            best_short = (-1, 1e9)
            best_long = (-1, 1e9)

            for j in wing_candidates:
                if matched[j] or j == i:
                    continue
                if tsec[i] - tsec[j] > time_window_seconds:
                    continue
                if not _econ_ok(i, j):
                    continue

                w = pv01[j]
                rel = abs(w - target_wing) / max(target_wing, 1e-12)
                if rel > belly_ratio_tolerance:
                    continue

                if ten[j] < ten[i]:
                    if rel < best_short[1]:
                        best_short = (j, rel)
                elif ten[j] > ten[i]:
                    if rel < best_long[1]:
                        best_long = (j, rel)

            j = best_short[0]
            k = best_long[0]

            if j >= 0 and k >= 0 and (not matched[j]) and (not matched[k]):
                # Also enforce econ consistency across the two wings
                if _econ_ok(j, k) and _econ_ok(i, k) and _econ_ok(i, j):
                    wing_avg = 0.5 * (pv01[j] + pv01[k])
                    expected_belly = 2.0 * wing_avg
                    belly_rel = abs(belly_pv - expected_belly) / max(expected_belly, 1e-12)
                    wings_rel = abs(pv01[j] - pv01[k]) / max(wing_avg, 1e-12)

                    if belly_rel <= belly_ratio_tolerance and wings_rel <= belly_ratio_tolerance:
                        pkg_counter += 1
                        pid = f"FLY_{pkg_counter}"
                        legs = [int(trade_ids[j]), int(trade_ids[i]), int(trade_ids[k])]

                        for idx in (j, i, k):
                            matched[idx] = True
                            pkg_type[idx] = "FLY"
                            pkg_ids[idx] = pid
                            pkg_legs[idx] = legs

        key_i = (int(ten_bucket[i]), int(pv_bucket[i]))
        store.setdefault(key_i, []).append(i)

    res = pd.DataFrame({trade_id_col: trade_ids, "_pkg_type": pkg_type, "_pkg_id": pkg_ids, "_pkg_legs": pkg_legs})
    out = out.merge(res, on=trade_id_col, how="left")

    if package_col not in out.columns:
        out[package_col] = "OUTRIGHT"
    if "package_id" not in out.columns:
        out["package_id"] = None
    if "package_legs" not in out.columns:
        out["package_legs"] = None

    m2 = out["_pkg_type"].notna() & (out["_pkg_type"].values != "OUTRIGHT")
    out.loc[m2, package_col] = out.loc[m2, "_pkg_type"].values
    out.loc[m2, "package_id"] = out.loc[m2, "_pkg_id"].values
    out.loc[m2, "package_legs"] = out.loc[m2, "_pkg_legs"].values

    out.drop(columns=["_pkg_type", "_pkg_id", "_pkg_legs"], inplace=True)
    return out


def _load_ust_reference_data(
    *,
    source: str = "fiscaldata",
    force_refresh: bool = False,
) -> pd.DataFrame:
    # Repo pattern: FixedRateBondQuery.resolve_query -> update_reference_data(...)
    from MDP.FixedRateBonds.reference_data_cache.ust_reference_data import update_reference_data

    ref = update_reference_data(source=source, force_refresh=force_refresh).copy()

    # normalize key fields
    if "maturity_date" in ref.columns:
        ref["maturity_date"] = pd.to_datetime(ref["maturity_date"], errors="coerce").dt.date
    if "issue_date" in ref.columns:
        ref["issue_date"] = pd.to_datetime(ref["issue_date"], errors="coerce").dt.date

    return ref


def _build_maturity_to_ust_map(
    ust_ref: pd.DataFrame,
    *,
    prefer_oi: Optional[Sequence[str]] = None,  # e.g. ("2-Year","3-Year","5-Year","7-Year","10-Year","20-Year","30-Year")
) -> pd.DataFrame:
    """
    Returns 1 row per maturity_date, choosing a "best" CUSIP:
      - prefer latest issue_date (reopenings share maturity)
      - deterministic tie-breaks
    """
    ref = ust_ref.copy()

    if prefer_oi is not None and "oi" in ref.columns:
        ref = ref[ref["oi"].isin(list(prefer_oi))].copy()

    if "maturity_date" not in ref.columns or "cusip" not in ref.columns:
        raise KeyError("UST reference data must include columns: 'maturity_date', 'cusip'")

    ref = ref.dropna(subset=["maturity_date", "cusip"]).copy()

    # Sort so "best" is last, then drop_duplicates(keep="last")
    sort_cols = []
    asc = []
    if "issue_date" in ref.columns:
        sort_cols.append("issue_date")
        asc.append(True)  # older -> newer
    # deterministic tie-breakers
    sort_cols.append("cusip")
    asc.append(True)

    ref = ref.sort_values(sort_cols, ascending=asc, kind="mergesort")

    keep_cols = [
        c
        for c in [
            "maturity_date",
            "cusip",
            "oi",
            "security_type",
            "security_term",
            "issue_date",
            "original_security_term",
            "interest_rate",
        ]
        if c in ref.columns
    ]

    best = ref[keep_cols].drop_duplicates(subset=["maturity_date"], keep="last").copy()
    best = best.rename(
        columns={
            "cusip": "ust_cusip",
            "oi": "ust_oi",
            "security_type": "ust_security_type",
            "security_term": "ust_security_term",
            "issue_date": "ust_issue_date",
            "original_security_term": "ust_original_security_term",
            "interest_rate": "ust_coupon",
        }
    )
    return best


def match_swaps_to_ust_by_maturity(
    df: pd.DataFrame,
    *,
    swap_maturity_col: str = "expiration_date",
    product_col: str = "product_type",
    product_values: Sequence[str] = ("OIS_SWAP",),
    currency_col: str = "notional_currency",
    require_usd: bool = True,
    usd_value: str = "USD",
    ust_ref_source: str = "fiscaldata",
    ust_force_refresh: bool = False,
) -> pd.DataFrame:
    """
    Adds UST reference fields to swaps whose maturity date exactly matches a UST maturity_date.

    Output columns (if matched):
      - ust_cusip, ust_oi, ust_security_type, ust_issue_date, ust_coupon, ...
      - matched_ust_maturity (bool)

    This is a *matched maturity* join. It does NOT attempt “nearest on-the-run” mapping.
    """
    if df.empty:
        return df

    out = df.copy()

    # candidate swaps
    m = out[product_col].isin(list(product_values)).values
    if require_usd and currency_col in out.columns:
        m &= out[currency_col].astype("string").values == usd_value

    if not m.any():
        # still ensure columns exist for downstream code
        out["matched_ust_maturity"] = False
        return out

    # load + build maturity map
    ust_ref = _load_ust_reference_data(source=ust_ref_source, force_refresh=ust_force_refresh)
    maturity_map = _build_maturity_to_ust_map(ust_ref)

    def _to_date_series(x: pd.Series) -> pd.Series:
        # Works for datetime64[ns], Timestamp w/ tz, python date, strings
        return pd.to_datetime(x, errors="coerce", utc=True).dt.date

    # normalize swap maturity date
    swap_mat = _to_date_series(out.loc[m, swap_maturity_col])
    tmp = out.loc[m, ["trade_id"]].copy() if "trade_id" in out.columns else out.loc[m, []].copy()
    tmp["_swap_maturity_date"] = swap_mat.values

    # merge
    tmp = tmp.merge(
        maturity_map,
        left_on="_swap_maturity_date",
        right_on="maturity_date",
        how="left",
    )

    # write back (vectorized)
    out["matched_ust_maturity"] = False
    matched = tmp["ust_cusip"].notna().values

    # align index positions of m==True rows
    idx = out.index[m]
    out.loc[idx, "matched_ust_maturity"] = matched

    # bring UST fields back
    for c in [c for c in tmp.columns if c.startswith("ust_")]:
        out.loc[idx, c] = tmp[c].values

    # optional: also record the swap maturity date used for join
    out.loc[idx, "swap_maturity_date"] = tmp["_swap_maturity_date"].values

    return out


def detect_spreadover_trades_df(
    df: pd.DataFrame,
    *,
    # swap columns
    product_col: str = "product_type",
    product_values: Sequence[str] = ("OIS_SWAP",),
    package_col: str = "package_type",
    trade_id_col: str = "trade_id",
    swap_maturity_col: str = "expiration_date",
    currency_col: str = "notional_currency",
    require_usd: bool = True,
    usd_value: str = "USD",
    # ust ref
    ust_ref_source: str = "fiscaldata",
    ust_force_refresh: bool = False,
    # tagging
    spreadover_package_type: str = "SPREADOVER",
    only_tag_outrights: bool = True,
) -> pd.DataFrame:
    """
    Practical “step back” detector:
      - identifies swaps whose *maturity date exactly matches* a UST maturity_date
      - tags those swaps as SPREADOVER (swap leg only) and attaches ust_* fields

    This is NOT the full Clarus “on-the-run vs spot-starting swap” logic.
    It’s the strict matched-maturity screen you asked for.
    """
    if df.empty:
        return df

    out = df.copy()

    # optional: only re-tag OUTRIGHT rows
    if only_tag_outrights and package_col in out.columns:
        outright_mask = out[package_col].fillna("OUTRIGHT").astype("string").values == "OUTRIGHT"
    else:
        outright_mask = np.ones(len(out), dtype=bool)

    # match to UST by maturity (adds matched_ust_maturity + ust_* fields)
    out = match_swaps_to_ust_by_maturity(
        out,
        swap_maturity_col=swap_maturity_col,
        product_col=product_col,
        product_values=product_values,
        currency_col=currency_col,
        require_usd=require_usd,
        usd_value=usd_value,
        ust_ref_source=ust_ref_source,
        ust_force_refresh=ust_force_refresh,
    )

    # tag
    can_tag = out["matched_ust_maturity"].fillna(False).values & outright_mask
    if can_tag.any():
        if package_col not in out.columns:
            out[package_col] = "OUTRIGHT"
        if "package_id" not in out.columns:
            out["package_id"] = None
        if "package_legs" not in out.columns:
            out["package_legs"] = None

        # package_id: deterministic, no loops
        # If trade_id missing, fall back to index
        if trade_id_col in out.columns:
            pid = out.loc[can_tag, trade_id_col].astype("string").radd("SPREADOVER_")
        else:
            pid = pd.Series(out.index[can_tag], index=out.index[can_tag]).astype("string").radd("SPREADOVER_")

        out.loc[can_tag, package_col] = spreadover_package_type
        out.loc[can_tag, "package_id"] = pid.values

        # package_legs: swap leg only (bond leg is not in SDR swaps df)
        if trade_id_col in out.columns:
            out.loc[can_tag, "package_legs"] = out.loc[can_tag, trade_id_col].apply(lambda x: [int(x)] if pd.notna(x) else None).values
        else:
            out.loc[can_tag, "package_legs"] = out.index[can_tag].to_series().apply(lambda x: [int(x)]).values

    return out
