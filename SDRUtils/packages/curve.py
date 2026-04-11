from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

from SDRUtils.core.utils import _ensure_int64_epoch_seconds, _pv01_bucket
from SDRUtils.packages.base import PackageDetector


def detect_curve_trades_df(
    df: pd.DataFrame,
    *,
    time_window_seconds: int = 60,
    pv01_tolerance: float = 0.10,
    require_different_tenor: bool = True,
    require_opposite_direction: bool = False,
    direction_col: Optional[str] = None,
    product_col: str = "product_type",
    package_col: str = "package_type",
    exec_col: str = "execution_timestamp",
    pv01_col: str = "estimated_pv01",
    tenor_col: str = "tenor_label",
    trade_id_col: str = "trade_id",
    require_same_currency: bool = True,
    currency_col: str = "notional_currency",
    require_same_effective_date: bool = True,
    effective_date_col: str = "effective_date",
    require_same_forward: bool = True,
    forward_label_col: str = "forward_label",
    forward_years_col: str = "forward_start_years",
    forward_years_tol: float = 0.05,  # used if forward_label_col missing
    allow_gap_curves: bool = True,
    require_same_underlier: bool = True,
    underlier_col: str = "UPI Underlier Name",
    require_same_platform: bool = True,
    platform_col: str = "Platform identifier",
    require_same_cleared_flag: bool = True,
    cleared_col: str = "Cleared",
    # V2 rate-index and tenor-segment awareness
    rate_index_col: str = "rate_index",
    tenor_segment_col: str = "tenor_segment",
    time_window_short: int = 30,
    time_window_medium: int = 60,
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
    _use_fwd_label = (require_same_forward or allow_gap_curves) and (forward_label_col in out.columns)
    _use_fwd_years = (require_same_forward or allow_gap_curves) and (not _use_fwd_label) and (forward_years_col in out.columns)
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
    if rate_index_col in out.columns:
        cols.append(rate_index_col)
    if tenor_segment_col in out.columns:
        cols.append(tenor_segment_col)

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

    # V2 rate-index and tenor-segment arrays (None when columns absent → backward compat)
    _has_ridx = rate_index_col in cand.columns
    ridx = cand[rate_index_col].fillna("_UNKNOWN_").astype(str).to_numpy() if _has_ridx else None
    _has_tseg = tenor_segment_col in cand.columns
    tseg = cand[tenor_segment_col].astype("string").to_numpy() if _has_tseg else None

    # Eviction uses conservative (widest) window when V2 present
    _evict_window = time_window_seconds if tseg is None else max(time_window_short, time_window_medium)

    def _effective_window(i: int, j: int) -> int:
        if tseg is None:
            return time_window_seconds
        si, sj = tseg[i], tseg[j]
        if si == "MEDIUM" or sj == "MEDIUM":
            return time_window_medium
        return time_window_short

    # direction as array (avoid cand.iloc in hot loop)
    if require_opposite_direction and direction_col and direction_col in cand.columns:
        dirv = pd.to_numeric(cand[direction_col], errors="coerce").fillna(0.0).to_numpy(dtype=np.float64)
    else:
        dirv = None

    def _econ_ok(i: int, j: int) -> bool:
        if ridx is not None and ridx[i] != ridx[j]:
            return False
        if ccy is not None and ccy[i] != ccy[j]:
            return False
        if eff is not None and eff[i] != eff[j]:
            return False
        if fwd_label is not None and fwd_label[i] != fwd_label[j]:
            if not (allow_gap_curves and tenor[i] == tenor[j]):
                return False
        if fwd_years is not None and abs(fwd_years[i] - fwd_years[j]) > forward_years_tol:
            if not (allow_gap_curves and tenor[i] == tenor[j]):
                return False
        if und is not None and und[i] != und[j]:
            return False
        if plat is not None and plat[i] != plat[j]:
            return False
        if clr is not None and clr[i] != clr[j]:
            return False
        return True

    def _forward_diff(i: int, j: int) -> bool:
        if fwd_label is not None:
            return fwd_label[i] != fwd_label[j]
        if fwd_years is not None:
            return abs(fwd_years[i] - fwd_years[j]) > forward_years_tol
        return False

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
        while left < len(cand) and (curr_t - tsec[left] > _evict_window):
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
                if tsec[i] - tsec[j] > _effective_window(i, j):
                    continue

                # economic guards (fast array comparisons)
                if not _econ_ok(i, j):
                    continue

                if require_different_tenor and tenor[i] == tenor[j]:
                    if not (allow_gap_curves and _forward_diff(i, j)):
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
            legs = [str(trade_ids[best_j]), str(trade_ids[i])]

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


class CurvePackageDetector(PackageDetector):
    package_type = "CURVE"

    def detect(self, df: pd.DataFrame, **kwargs: object) -> pd.DataFrame:
        return detect_curve_trades_df(df, **kwargs)
