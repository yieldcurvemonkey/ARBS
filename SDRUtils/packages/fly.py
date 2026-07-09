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
    require_same_upi: bool = True,
    upi_col: str = "Unique Product Identifier",
    require_same_platform: bool = True,
    platform_col: str = "Platform identifier",
    # Optional: if you want to prohibit mixing cleared/uncleared etc.
    require_same_cleared_flag: bool = True,
    cleared_col: str = "Cleared",
    special_tenor_col: str = "special_tenor_type",
    # V2 rate-index and tenor-segment awareness
    rate_index_col: str = "rate_index",
    tenor_segment_col: str = "tenor_segment",
    time_window_short: int = 30,
    time_window_medium: int = 60,
    # PTS constraint: legs of the same fly must share the same reported spread
    require_same_pts: bool = True,
    pts_col: str = "package_transaction_spread",
    reject_non_standard_term: bool = True,
    non_standard_term_col: str = "is_non_standard_term",
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
        require_same_effective_date_pass: bool = True,
    ) -> pd.DataFrame:
        nonlocal out

        # Only candidates — outrights and spreadovers (spreadover triples → SPREADOVER_FLY)
        _FLY_ELIGIBLE = {"OUTRIGHT", "SPREADOVER"}
        _FLY_PRODUCT_TYPES = {"OIS_SWAP", "BASIS_SWAP"}
        m = np.array([v in _FLY_PRODUCT_TYPES for v in out[product_col].fillna("").values]) & (out[pv01_col].fillna(0).values > 0)
        if package_col in out.columns:
            m &= np.array([v in _FLY_ELIGIBLE for v in out[package_col].fillna("OUTRIGHT").values])

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
        if require_same_upi and upi_col in out.columns:
            cols.append(upi_col)
        if require_same_platform and platform_col in out.columns:
            cols.append(platform_col)
        if require_same_cleared_flag and cleared_col in out.columns:
            cols.append(cleared_col)
        if special_tenor_col in out.columns:
            cols.append(special_tenor_col)
        if rate_index_col in out.columns:
            cols.append(rate_index_col)
        if tenor_segment_col in out.columns:
            cols.append(tenor_segment_col)
        if require_same_pts and pts_col in out.columns:
            cols.append(pts_col)

        cols = list(dict.fromkeys(cols))

        if ten_axis_col not in out.columns:
            return out

        cand = out.loc[m, cols].copy()
        if cand.empty:
            return out

        # Track original package_type for spreadover → SPREADOVER_FLY
        orig_pkg = out.loc[cand.index, package_col].fillna("OUTRIGHT").values if package_col in out.columns else None

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
            if (require_same_effective_date and require_same_effective_date_pass and effective_date_col in cand.columns)
            else None
        )

        fwd_label = cand[forward_label_col].astype("string").to_numpy() if (require_same_forward_pass and forward_label_col in cand.columns) else None
        fwd_years = (
            pd.to_numeric(cand[forward_years_col], errors="coerce").fillna(0.0).to_numpy(dtype=np.float64)
            if (require_same_forward_pass and fwd_label is None and forward_years_col in cand.columns)
            else None
        )

        und = cand[underlier_col].astype("string").to_numpy() if (require_same_underlier and underlier_col in cand.columns) else None
        upi = cand[upi_col].astype("string").to_numpy() if (require_same_upi and upi_col in cand.columns) else None
        plat = cand[platform_col].astype("string").to_numpy() if (require_same_platform and platform_col in cand.columns) else None
        clr = cand[cleared_col].astype("string").to_numpy() if (require_same_cleared_flag and cleared_col in cand.columns) else None
        stt = cand[special_tenor_col].fillna("STANDARD").astype(str).to_numpy() if special_tenor_col in cand.columns else None
        nst: np.ndarray | None = None
        if reject_non_standard_term:
            if non_standard_term_col in cand.columns:
                nst = cand[non_standard_term_col].fillna(False).astype(bool).to_numpy()
            elif "tenor_label" in cand.columns:
                _tl = cand["tenor_label"].fillna("").astype(str).to_numpy()
                nst = np.array([t.startswith("~") for t in _tl], dtype=bool)

        # V2 rate-index and tenor-segment arrays (None when absent → backward compat)
        _has_ridx = rate_index_col in cand.columns
        ridx = cand[rate_index_col].fillna("_UNKNOWN_").astype(str).to_numpy() if _has_ridx else None
        _has_tseg = tenor_segment_col in cand.columns
        tseg = cand[tenor_segment_col].fillna("_UNKNOWN_").astype(str).to_numpy() if _has_tseg else None

        _has_pts = require_same_pts and pts_col in cand.columns
        pts = pd.to_numeric(cand[pts_col], errors="coerce").to_numpy(dtype=np.float64) if _has_pts else None

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
            if nst is not None and (nst[i] or nst[j]):
                return False
            both_fomc = stt is not None and stt[i] == "FOMC" and stt[j] == "FOMC"
            if ridx is not None and ridx[i] != ridx[j]:
                return False
            if ccy is not None and ccy[i] != ccy[j]:
                return False
            if not both_fomc:
                if eff is not None and eff[i] != eff[j]:
                    return False
                if fwd_label is not None and fwd_label[i] != fwd_label[j]:
                    return False
                if fwd_years is not None and abs(fwd_years[i] - fwd_years[j]) > forward_years_tol:
                    return False
            # "Same underlying tenor" with day-count/leap-year tolerance
            # (~7 days): a 1Y tail spanning Feb 29 is 1.0027y, not 1.0, so exact
            # equality would split forward gap flies (same tail, different
            # forward) into outrights. Genuinely different tails differ by >> tol.
            if require_same_underlying_tenor:
                _ti, _tj = tenor_years[i], tenor_years[j]
                if np.isnan(_ti) or np.isnan(_tj) or abs(_ti - _tj) > 0.02:
                    return False
            if und is not None and und[i] != und[j]:
                return False
            if upi is not None and upi[i] != upi[j]:
                return False
            if plat is not None and plat[i] != plat[j]:
                return False
            if clr is not None and clr[i] != clr[j]:
                return False
            if pts is not None:
                pi, pj = pts[i], pts[j]
                if not (np.isnan(pi) or np.isnan(pj)) and pi != pj:
                    return False
            return True

        _FOMC_BELLY_TOL = 0.50

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

            _is_fomc_i = stt is not None and stt[i] == "FOMC"
            _db_range = range(-4, 5) if _is_fomc_i else (-1, 0, 1)

            wing_candidates: List[int] = []
            for dt in range(-8, 9):
                if dt == 0:
                    continue
                tkey = tb + dt
                for db in _db_range:
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

                    _fomc_pair = _is_fomc_i and stt is not None and stt[j] == "FOMC"
                    _tol = _FOMC_BELLY_TOL if _fomc_pair else belly_ratio_tolerance

                    w = pv01[j]
                    rel = abs(w - target_wing) / max(target_wing, 1e-12)
                    if rel > _tol:
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
                        _all_fomc = stt is not None and stt[j] == "FOMC" and stt[i] == "FOMC" and stt[k] == "FOMC"
                        _final_tol = _FOMC_BELLY_TOL if _all_fomc else belly_ratio_tolerance

                        wing_avg = 0.5 * (pv01[j] + pv01[k])
                        expected_belly = 2.0 * wing_avg
                        belly_rel = abs(belly_pv - expected_belly) / max(expected_belly, 1e-12)
                        wings_rel = abs(pv01[j] - pv01[k]) / max(wing_avg, 1e-12)

                        if belly_rel <= _final_tol and wings_rel <= _final_tol:
                            pkg_counter += 1
                            legs = [str(trade_ids[j]), str(trade_ids[i]), str(trade_ids[k])]
                            # Globally-unique suffix: smallest leg trade_id.
                            # Prevents FLY_N collisions across daily detector runs.
                            ft = "FLY"
                            if orig_pkg is not None and all(orig_pkg[idx] == "SPREADOVER" for idx in (j, i, k)):
                                ft = "SPREADOVER_FLY"
                            pid = f"{ft}_{pkg_counter}_{min(legs)}"

                            for idx in (j, i, k):
                                matched[idx] = True
                                pkg_type[idx] = ft
                                pkg_ids[idx] = pid
                                pkg_legs[idx] = legs

            key_i = (int(ten_bucket[i]), int(pv_bucket[i]))
            store.setdefault(key_i, []).append(i)

        # --- Second pass: order-independent fly detection ---------------
        # The streaming loop above only matches flys where the belly arrives
        # AFTER both wings, because it can only see wings that are already
        # in the store. Belly-first or belly-middle arrivals leak through
        # undetected and then get mis-paired by the curve detector as a
        # 2-leg package with the belly dangling as an outright.
        #
        # Re-scan the remaining unmatched rows and do a simple O(n^2)
        # combinatorial search per candidate belly, since all other
        # trades are now visible. All economic guards from the streaming
        # pass (_econ_ok, belly/wing DV01 tolerance, time window) are
        # re-applied here.
        for i in range(len(cand)):
            if matched[i]:
                continue
            belly_pv = pv01[i]
            if belly_pv <= 0:
                continue
            target_wing = belly_pv / 2.0

            _is_fomc_i2 = stt is not None and stt[i] == "FOMC"

            best_short = (-1, 1e9)
            best_long = (-1, 1e9)
            for j in range(len(cand)):
                if matched[j] or j == i:
                    continue
                if abs(int(tsec[i]) - int(tsec[j])) > _effective_window(i, j):
                    continue
                if not _econ_ok(i, j):
                    continue
                w = pv01[j]
                if w <= 0:
                    continue
                _fomc_pair2 = _is_fomc_i2 and stt is not None and stt[j] == "FOMC"
                _tol2 = _FOMC_BELLY_TOL if _fomc_pair2 else belly_ratio_tolerance
                rel = abs(w - target_wing) / max(target_wing, 1e-12)
                if rel > _tol2:
                    continue
                if ten_axis[j] < ten_axis[i]:
                    if rel < best_short[1]:
                        best_short = (j, rel)
                elif ten_axis[j] > ten_axis[i]:
                    if rel < best_long[1]:
                        best_long = (j, rel)

            j_idx, k_idx = best_short[0], best_long[0]
            if j_idx < 0 or k_idx < 0:
                continue
            if matched[j_idx] or matched[k_idx]:
                continue
            if not (_econ_ok(j_idx, k_idx) and _econ_ok(i, k_idx) and _econ_ok(i, j_idx)):
                continue

            _all_fomc2 = stt is not None and stt[j_idx] == "FOMC" and stt[i] == "FOMC" and stt[k_idx] == "FOMC"
            _final_tol2 = _FOMC_BELLY_TOL if _all_fomc2 else belly_ratio_tolerance

            wing_avg = 0.5 * (pv01[j_idx] + pv01[k_idx])
            expected_belly = 2.0 * wing_avg
            belly_rel = abs(belly_pv - expected_belly) / max(expected_belly, 1e-12)
            wings_rel = abs(pv01[j_idx] - pv01[k_idx]) / max(wing_avg, 1e-12)
            if belly_rel > _final_tol2 or wings_rel > _final_tol2:
                continue

            pkg_counter += 1
            legs = [str(trade_ids[j_idx]), str(trade_ids[i]), str(trade_ids[k_idx])]
            ft = "FLY"
            if orig_pkg is not None and all(orig_pkg[idx] == "SPREADOVER" for idx in (j_idx, i, k_idx)):
                ft = "SPREADOVER_FLY"
            pid = f"{ft}_{pkg_counter}_{min(legs)}"
            for idx in (j_idx, i, k_idx):
                matched[idx] = True
                pkg_type[idx] = ft
                pkg_ids[idx] = pid
                pkg_legs[idx] = legs

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
            require_same_effective_date_pass=False,
        )

    return out


class FlyPackageDetector(PackageDetector):
    package_type = "FLY"

    def detect(self, df: pd.DataFrame, **kwargs: object) -> pd.DataFrame:
        return detect_fly_trades_df(df, **kwargs)
