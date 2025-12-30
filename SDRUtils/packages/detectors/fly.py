"""
Butterfly (Fly) Package Detector.

Detects 3-leg butterfly spreads (short, belly, long tenors).
"""

from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

from SDRUtils.packages.base import PackageDetector, PackageDetectorConfig
from SDRUtils.packages.registry import PackageRegistry
from SDRUtils.core.utils import ensure_int64_epoch_seconds, pv01_bucket


class FlyDetector(PackageDetector):
    """
    Detector for 3-leg butterfly spreads.

    Matches triplets of OIS swaps with:
    - Three different tenors (short < belly < long)
    - Belly PV01 ≈ 2x wing PV01
    - Same economic attributes (currency, effective date, etc.)
    - Within time window
    """

    package_type = "FLY"
    priority = 20  # Run after curve detector

    def __init__(
        self,
        belly_ratio_tolerance: float = 0.15,
        forward_years_tol: float = 0.05,
    ):
        self.belly_ratio_tolerance = belly_ratio_tolerance
        self.forward_years_tol = forward_years_tol

    def detect(
        self,
        df: pd.DataFrame,
        config: Optional[PackageDetectorConfig] = None,
    ) -> pd.DataFrame:
        """Detect fly packages in the DataFrame."""
        if config is None:
            config = PackageDetectorConfig()

        if df.empty:
            return df

        out = df.copy()

        # Only candidates: OIS_SWAP with PV01 > 0 and OUTRIGHT
        m = (out[config.product_col].isin(config.product_values)) & (out[config.pv01_col].fillna(0).values > 0)
        if config.package_col in out.columns:
            m &= out[config.package_col].fillna("OUTRIGHT").values == "OUTRIGHT"

        # Columns needed
        cols = [config.trade_id_col, config.exec_col, config.pv01_col, config.tenor_years_col]
        if config.require_same_currency and config.currency_col in out.columns:
            cols.append(config.currency_col)
        if config.require_same_effective_date and config.effective_date_col in out.columns:
            cols.append(config.effective_date_col)
        if config.require_same_forward:
            if config.forward_label_col in out.columns:
                cols.append(config.forward_label_col)
            elif config.forward_years_col in out.columns:
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

        cand["_t"] = ensure_int64_epoch_seconds(cand[config.exec_col])
        cand.sort_values("_t", inplace=True, kind="mergesort")

        pv01 = cand[config.pv01_col].to_numpy(dtype=np.float64)
        tsec = cand["_t"].to_numpy(dtype=np.int64)
        ten = cand[config.tenor_years_col].to_numpy(dtype=np.float64)
        trade_ids = cand[config.trade_id_col].to_numpy(dtype=np.int64)

        # Precompute economic keys
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

        fwd_label = (
            cand[config.forward_label_col].astype("string").to_numpy()
            if (config.require_same_forward and config.forward_label_col in cand.columns)
            else None
        )
        fwd_years = (
            pd.to_numeric(cand[config.forward_years_col], errors="coerce").fillna(0.0).to_numpy(dtype=np.float64)
            if (config.require_same_forward and fwd_label is None and config.forward_years_col in cand.columns)
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

        # Buckets
        pv_bucket = pv01_bucket(pv01, self.belly_ratio_tolerance)
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
            while left < len(cand) and (curr_t - tsec[left] > config.time_window_seconds):
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

        for i in range(len(cand)):
            if matched[i]:
                continue

            _evict(tsec[i])

            belly_pv = pv01[i]
            if belly_pv <= 0:
                store.setdefault((int(ten_bucket[i]), int(pv_bucket[i])), []).append(i)
                continue

            target_wing = belly_pv / 2.0
            target_b = int(np.floor(np.log(max(target_wing, 1e-12)) / np.log(1.0 + self.belly_ratio_tolerance)))

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
                    if tsec[i] - tsec[j] > config.time_window_seconds:
                        continue
                    if not _econ_ok(i, j):
                        continue

                    w = pv01[j]
                    rel = abs(w - target_wing) / max(target_wing, 1e-12)
                    if rel > self.belly_ratio_tolerance:
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
                    if _econ_ok(j, k) and _econ_ok(i, k) and _econ_ok(i, j):
                        wing_avg = 0.5 * (pv01[j] + pv01[k])
                        expected_belly = 2.0 * wing_avg
                        belly_rel = abs(belly_pv - expected_belly) / max(expected_belly, 1e-12)
                        wings_rel = abs(pv01[j] - pv01[k]) / max(wing_avg, 1e-12)

                        if belly_rel <= self.belly_ratio_tolerance and wings_rel <= self.belly_ratio_tolerance:
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

        res = pd.DataFrame(
            {config.trade_id_col: trade_ids, "_pkg_type": pkg_type, "_pkg_id": pkg_ids, "_pkg_legs": pkg_legs}
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
PackageRegistry.register(FlyDetector())
