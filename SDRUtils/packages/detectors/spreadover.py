"""
Spreadover (Swap-UST) Package Detector.

Detects swaps whose maturity matches a UST maturity date.
"""

from typing import Optional, Sequence

import numpy as np
import pandas as pd

from SDRUtils.packages.base import PackageDetector, PackageDetectorConfig
from SDRUtils.packages.registry import PackageRegistry


class SpreadoverDetector(PackageDetector):
    """
    Detector for Spread-over-UST packages.

    Matches swaps whose maturity date exactly matches a UST maturity date.
    This is a "matched maturity" join, not "nearest on-the-run" mapping.
    """

    package_type = "SPREADOVER"
    priority = 30  # Run after curve and fly detectors

    def __init__(
        self,
        swap_maturity_col: str = "expiration_date",
        require_usd: bool = True,
        usd_value: str = "USD",
        ust_ref_source: str = "fiscaldata",
        ust_force_refresh: bool = False,
        only_tag_outrights: bool = True,
    ):
        self.swap_maturity_col = swap_maturity_col
        self.require_usd = require_usd
        self.usd_value = usd_value
        self.ust_ref_source = ust_ref_source
        self.ust_force_refresh = ust_force_refresh
        self.only_tag_outrights = only_tag_outrights

    def _load_ust_reference_data(self) -> pd.DataFrame:
        """Load UST reference data from cache."""
        from MDP.FixedRateBonds.reference_data_cache.ust_reference_data import update_reference_data

        ref = update_reference_data(source=self.ust_ref_source, force_refresh=self.ust_force_refresh).copy()

        if "maturity_date" in ref.columns:
            ref["maturity_date"] = pd.to_datetime(ref["maturity_date"], errors="coerce").dt.date
        if "issue_date" in ref.columns:
            ref["issue_date"] = pd.to_datetime(ref["issue_date"], errors="coerce").dt.date

        return ref

    def _build_maturity_to_ust_map(
        self,
        ust_ref: pd.DataFrame,
        prefer_oi: Optional[Sequence[str]] = None,
    ) -> pd.DataFrame:
        """
        Build 1 row per maturity_date, choosing best CUSIP.

        Prefers latest issue_date (reopenings share maturity).
        """
        ref = ust_ref.copy()

        if prefer_oi is not None and "oi" in ref.columns:
            ref = ref[ref["oi"].isin(list(prefer_oi))].copy()

        if "maturity_date" not in ref.columns or "cusip" not in ref.columns:
            raise KeyError("UST reference data must include columns: 'maturity_date', 'cusip'")

        ref = ref.dropna(subset=["maturity_date", "cusip"]).copy()

        # Sort so "best" is last
        sort_cols = []
        asc = []
        if "issue_date" in ref.columns:
            sort_cols.append("issue_date")
            asc.append(True)
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

    def detect(
        self,
        df: pd.DataFrame,
        config: Optional[PackageDetectorConfig] = None,
    ) -> pd.DataFrame:
        """Detect spreadover packages in the DataFrame."""
        if config is None:
            config = PackageDetectorConfig()

        if df.empty:
            return df

        out = df.copy()

        # Optional: only re-tag OUTRIGHT rows
        if self.only_tag_outrights and config.package_col in out.columns:
            outright_mask = out[config.package_col].fillna("OUTRIGHT").astype("string").values == "OUTRIGHT"
        else:
            outright_mask = np.ones(len(out), dtype=bool)

        # Candidate swaps
        m = out[config.product_col].isin(config.product_values).values
        if self.require_usd and config.currency_col in out.columns:
            m &= out[config.currency_col].astype("string").values == self.usd_value

        if not m.any():
            out["matched_ust_maturity"] = False
            return out

        # Load and build maturity map
        try:
            ust_ref = self._load_ust_reference_data()
            maturity_map = self._build_maturity_to_ust_map(ust_ref)
        except Exception:
            out["matched_ust_maturity"] = False
            return out

        def _to_date_series(x: pd.Series) -> pd.Series:
            return pd.to_datetime(x, errors="coerce", utc=True).dt.date

        # Normalize swap maturity date
        swap_mat = _to_date_series(out.loc[m, self.swap_maturity_col])
        tmp = out.loc[m, [config.trade_id_col]].copy() if config.trade_id_col in out.columns else out.loc[m, []].copy()
        tmp["_swap_maturity_date"] = swap_mat.values

        # Merge
        tmp = tmp.merge(
            maturity_map,
            left_on="_swap_maturity_date",
            right_on="maturity_date",
            how="left",
        )

        # Write back
        out["matched_ust_maturity"] = False
        matched = tmp["ust_cusip"].notna().values

        idx = out.index[m]
        out.loc[idx, "matched_ust_maturity"] = matched

        for c in [c for c in tmp.columns if c.startswith("ust_")]:
            out.loc[idx, c] = tmp[c].values

        out.loc[idx, "swap_maturity_date"] = tmp["_swap_maturity_date"].values

        # Tag as SPREADOVER
        can_tag = out["matched_ust_maturity"].fillna(False).values & outright_mask
        if can_tag.any():
            if config.package_col not in out.columns:
                out[config.package_col] = "OUTRIGHT"
            if "package_id" not in out.columns:
                out["package_id"] = None
            if "package_legs" not in out.columns:
                out["package_legs"] = None

            if config.trade_id_col in out.columns:
                pid = out.loc[can_tag, config.trade_id_col].astype("string").radd("SPREADOVER_")
            else:
                pid = pd.Series(out.index[can_tag], index=out.index[can_tag]).astype("string").radd("SPREADOVER_")

            out.loc[can_tag, config.package_col] = self.package_type
            out.loc[can_tag, "package_id"] = pid.values

            if config.trade_id_col in out.columns:
                out.loc[can_tag, "package_legs"] = (
                    out.loc[can_tag, config.trade_id_col].apply(lambda x: [int(x)] if pd.notna(x) else None).values
                )
            else:
                out.loc[can_tag, "package_legs"] = out.index[can_tag].to_series().apply(lambda x: [int(x)]).values

        return out


# Auto-register on import
PackageRegistry.register(SpreadoverDetector())
