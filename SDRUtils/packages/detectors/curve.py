"""
Curve Package Detector.

Detects 2-leg curve spreads (different tenors, similar PV01).
"""

from typing import Dict, List, Optional

import numpy as np
import pandas as pd

from SDRUtils.packages.base import PackageDetector, PackageDetectorConfig
from SDRUtils.packages.registry import PackageRegistry
from SDRUtils.core.utils import ensure_int64_epoch_seconds, pv01_bucket


class CurveDetector(PackageDetector):
    """
    Detector for 2-leg curve spreads.

    Matches pairs of OIS swaps with:
    - Different tenors
    - Similar PV01 (within tolerance)
    - Same economic attributes (currency, effective date, etc.)
    - Within time window
    """

    package_type = "CURVE"
    priority = 10  # Run early

    def __init__(
        self,
        require_different_tenor: bool = True,
        require_opposite_direction: bool = False,
        direction_col: Optional[str] = None,
        forward_years_tol: float = 0.05,
    ):
        self.require_different_tenor = require_different_tenor
        self.require_opposite_direction = require_opposite_direction
        self.direction_col = direction_col
        self.forward_years_tol = forward_years_tol

    def detect(
        self,
        df: pd.DataFrame,
        config: Optional[PackageDetectorConfig] = None,
    ) -> pd.DataFrame:
        """Detect curve packages in the DataFrame."""
        if config is None:
            config = PackageDetectorConfig()

        if df.empty:
            return df

        out = df.copy()

        # Only candidates: OIS_SWAP with PV01 > 0 and OUTRIGHT
        m = (out[config.product_col].isin(config.product_values)) & (out[config.pv01_col].fillna(0).values > 0)
        if config.package_col in out.columns:
            m &= out[config.package_col].fillna("OUTRIGHT").values == "OUTRIGHT"

        # Build candidate columns list
        cols = [config.trade_id_col, config.exec_col, config.pv01_col, config.tenor_col]
        if self.require_opposite_direction and self.direction_col and self.direction_col in out.columns:
            cols.append(self.direction_col)

        if config.require_same_currency and config.currency_col in out.columns:
            cols.append(config.currency_col)
        if config.require_same_effective_date and config.effective_date_col in out.columns:
            cols.append(config.effective_date_col)

        _use_fwd_label = config.require_same_forward and (config.forward_label_col in out.columns)
        _use_fwd_years = config.require_same_forward and (not _use_fwd_label) and (config.forward_years_col in out.columns)
        if _use_fwd_label:
            cols.append(config.forward_label_col)
        elif _use_fwd_years:
            cols.append(config.forward_years_col)

        if config.require_same_underlier and config.underlier_col in out.columns:
            cols.append(config.underlier_col)
        if config.require_same_platform and config.platform_col in out.columns:
            cols.append(config.platform_col)
        if config.require_same_cleared_flag and config.cleared_col in out.columns:
            cols.append(config.cleared_col)

        cand = out.loc[m, cols].copy()
        if cand.empty:
            return out

        # Sort by exec time
        cand["_t"] = ensure_int64_epoch_seconds(cand[config.exec_col])
        cand.sort_values("_t", inplace=True, kind="mergesort")

        pv01 = cand[config.pv01_col].to_numpy(dtype=np.float64)
        tsec = cand["_t"].to_numpy(dtype=np.int64)
        tenor = cand[config.tenor_col].astype("string").to_numpy()
        trade_ids = cand[config.trade_id_col].to_numpy()

        # Precompute econ key arrays
        ccy = (
            cand[config.currency_col].astype("string").to_numpy()
            if (config.require_same_currency and config.currency_col in cand.columns)
            else None
        )
        eff = (
            pd.to_datetime(cand[config.effective_date_col], errors="coerce").dt.date.to_numpy()
            if (config.require_same_effective_date and config.effective_date_col in cand.columns)
            else None
        )
        fwd_label = cand[config.forward_label_col].astype("string").to_numpy() if _use_fwd_label else None
        fwd_years = (
            pd.to_numeric(cand[config.forward_years_col], errors="coerce").fillna(0.0).to_numpy(dtype=np.float64)
            if _use_fwd_years
            else None
        )
        und = (
            cand[config.underlier_col].astype("string").to_numpy()
            if (config.require_same_underlier and config.underlier_col in cand.columns)
            else None
        )
        plat = (
            cand[config.platform_col].astype("string").to_numpy()
            if (config.require_same_platform and config.platform_col in cand.columns)
            else None
        )
        clr = (
            cand[config.cleared_col].astype("string").to_numpy()
            if (config.require_same_cleared_flag and config.cleared_col in cand.columns)
            else None
        )

        dirv = None
        if self.require_opposite_direction and self.direction_col and self.direction_col in cand.columns:
            dirv = pd.to_numeric(cand[self.direction_col], errors="coerce").fillna(0.0).to_numpy(dtype=np.float64)

        def _econ_ok(i: int, j: int) -> bool:
            if ccy is not None and ccy[i] != ccy[j]:
                return False
            if eff is not None and eff[i] != eff[j]:
                return False
            if fwd_label is not None and fwd_label[i] != fwd_label[j]:
                return False
            if fwd_years is not None and abs(fwd_years[i] - fwd_years[j]) > self.forward_years_tol:
                return False
            if und is not None and und[i] != und[j]:
                return False
            if plat is not None and plat[i] != plat[j]:
                return False
            if clr is not None and clr[i] != clr[j]:
                return False
            return True

        # PV01 bucket index
        b = pv01_bucket(pv01, config.pv01_tolerance)

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
            while left < len(cand) and (curr_t - tsec[left] > config.time_window_seconds):
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
                    if tsec[i] - tsec[j] > config.time_window_seconds:
                        continue

                    if not _econ_ok(i, j):
                        continue

                    if self.require_different_tenor and tenor[i] == tenor[j]:
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
                    if rel <= config.pv01_tolerance and rel < best_rel:
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
                config.trade_id_col: trade_ids,
                "_pkg_type": pkg_type,
                "_pkg_id": pkg_ids,
                "_pkg_legs": pkg_legs,
            }
        )

        out = out.merge(res, on=config.trade_id_col, how="left")

        if config.package_col not in out.columns:
            out[config.package_col] = "OUTRIGHT"
        if "package_id" not in out.columns:
            out["package_id"] = None
        if "package_legs" not in out.columns:
            out["package_legs"] = None

        m2 = out["_pkg_type"].notna() & (out["_pkg_type"].values != "OUTRIGHT")
        out.loc[m2, config.package_col] = out.loc[m2, "_pkg_type"].values
        out.loc[m2, "package_id"] = out.loc[m2, "_pkg_id"].values
        out.loc[m2, "package_legs"] = out.loc[m2, "_pkg_legs"].values

        out.drop(columns=["_pkg_type", "_pkg_id", "_pkg_legs"], inplace=True)
        return out


# Auto-register on import
PackageRegistry.register(CurveDetector())
