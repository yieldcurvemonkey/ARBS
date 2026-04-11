from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

from SDRUtils.core.utils import _ensure_int64_epoch_seconds, _pv01_bucket
from SDRUtils.packages.base import PackageDetector


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
    require_same_currency: bool = True,
    currency_col: str = "notional_currency",
    require_same_effective_date: bool = True,
    effective_date_col: str = "effective_date",
    require_same_forward: bool = True,
    forward_label_col: str = "forward_label",
    forward_years_col: str = "forward_start_years",
    forward_years_tol: float = 0.05,  # used if forward_label_col missing
    allow_gap_flies: bool = True,
    require_same_underlier: bool = True,
    underlier_col: str = "UPI Underlier Name",
    require_same_platform: bool = True,
    platform_col: str = "Platform identifier",
    # Optional: if you want to prohibit mixing cleared/uncleared etc.
    require_same_cleared_flag: bool = True,
    cleared_col: str = "Cleared",
    # V2 rate-index and tenor-segment awareness
    rate_index_col: str = "rate_index",
    tenor_segment_col: str = "tenor_segment",
    time_window_short: int = 30,
    time_window_medium: int = 60,
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

    def _run_pass(
        *,
        ten_axis_col: str,
        require_same_forward_pass: bool,
        require_same_underlying_tenor: bool,
    ) -> pd.DataFrame:
        nonlocal out

        # Only candidates
        m = (out[product_col].values == "OIS_SWAP") & (out[pv01_col].fillna(0).values > 0)
        if package_col in out.columns:
            m &= out[package_col].fillna("OUTRIGHT").values == "OUTRIGHT"

        # columns needed
        cols = [trade_id_col, exec_col, pv01_col, tenor_years_col, ten_axis_col]
        if require_same_currency and currency_col in out.columns:
            cols.append(currency_col)
        if require_same_effective_date and effective_date_col in out.columns:
            cols.append(effective_date_col)
        if require_same_forward_pass:
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
        if rate_index_col in out.columns:
            cols.append(rate_index_col)
        if tenor_segment_col in out.columns:
            cols.append(tenor_segment_col)

        cols = list(dict.fromkeys(cols))

        if ten_axis_col not in out.columns:
            return out

        cand = out.loc[m, cols].copy()
        if cand.empty:
            return out

        cand["_t"] = _ensure_int64_epoch_seconds(cand[exec_col])
        cand.sort_values("_t", inplace=True, kind="mergesort")

        pv01 = cand[pv01_col].to_numpy(dtype=np.float64)
        tsec = cand["_t"].to_numpy(dtype=np.int64)
        ten_axis = pd.to_numeric(cand[ten_axis_col], errors="coerce").to_numpy(dtype=np.float64)
        tenor_years = pd.to_numeric(cand[tenor_years_col], errors="coerce").to_numpy(dtype=np.float64)
        trade_ids = cand[trade_id_col].to_numpy()

        # Precompute economic keys as fast arrays (or None)
        ccy = cand[currency_col].astype("string").to_numpy() if (require_same_currency and currency_col in cand.columns) else None
        eff = (
            pd.to_datetime(cand[effective_date_col], errors="coerce").dt.date.to_numpy()
            if (require_same_effective_date and effective_date_col in cand.columns)
            else None
        )

        fwd_label = cand[forward_label_col].astype("string").to_numpy() if (require_same_forward_pass and forward_label_col in cand.columns) else None
        fwd_years = (
            pd.to_numeric(cand[forward_years_col], errors="coerce").fillna(0.0).to_numpy(dtype=np.float64)
            if (require_same_forward_pass and fwd_label is None and forward_years_col in cand.columns)
            else None
        )

        und = cand[underlier_col].astype("string").to_numpy() if (require_same_underlier and underlier_col in cand.columns) else None
        plat = cand[platform_col].astype("string").to_numpy() if (require_same_platform and platform_col in cand.columns) else None
        clr = cand[cleared_col].astype("string").to_numpy() if (require_same_cleared_flag and cleared_col in cand.columns) else None

        # V2 rate-index and tenor-segment arrays (None when absent → backward compat)
        _has_ridx = rate_index_col in cand.columns
        ridx = cand[rate_index_col].fillna("_UNKNOWN_").astype(str).to_numpy() if _has_ridx else None
        _has_tseg = tenor_segment_col in cand.columns
        tseg = cand[tenor_segment_col].astype("string").to_numpy() if _has_tseg else None

        _evict_window = time_window_seconds if tseg is None else max(time_window_short, time_window_medium)

        def _effective_window(i: int, j: int) -> int:
            if tseg is None:
                return time_window_seconds
            si, sj = tseg[i], tseg[j]
            if si == "MEDIUM" or sj == "MEDIUM":
                return time_window_medium
            return time_window_short

        # Buckets
        pv_bucket = _pv01_bucket(pv01, belly_ratio_tolerance)
        ten_bucket = np.floor(ten_axis / 0.25).astype(np.int32)

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
            while left < len(cand) and (curr_t - tsec[left] > _evict_window):
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
            if ridx is not None and ridx[i] != ridx[j]:
                return False
            if ccy is not None and ccy[i] != ccy[j]:
                return False
            if eff is not None and eff[i] != eff[j]:
                return False
            if require_same_underlying_tenor and tenor_years[i] != tenor_years[j]:
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
                    if tsec[i] - tsec[j] > _effective_window(i, j):
                        continue
                    if not _econ_ok(i, j):
                        continue

                    w = pv01[j]
                    rel = abs(w - target_wing) / max(target_wing, 1e-12)
                    if rel > belly_ratio_tolerance:
                        continue

                    if ten_axis[j] < ten_axis[i]:
                        if rel < best_short[1]:
                            best_short = (j, rel)
                    elif ten_axis[j] > ten_axis[i]:
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
                            legs = [str(trade_ids[j]), str(trade_ids[i]), str(trade_ids[k])]

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

    out = _run_pass(
        ten_axis_col=tenor_years_col,
        require_same_forward_pass=require_same_forward,
        require_same_underlying_tenor=False,
    )

    if allow_gap_flies:
        out = _run_pass(
            ten_axis_col=forward_years_col,
            require_same_forward_pass=False,
            require_same_underlying_tenor=True,
        )

    return out


class FlyPackageDetector(PackageDetector):
    package_type = "FLY"

    def detect(self, df: pd.DataFrame, **kwargs: object) -> pd.DataFrame:
        return detect_fly_trades_df(df, **kwargs)
