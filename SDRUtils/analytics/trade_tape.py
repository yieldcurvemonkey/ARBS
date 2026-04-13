"""
Trade Tape: single enriched DataFrame with all signals a market maker needs.

Composes existing analytics modules into a unified per-trade enrichment
pipeline.  Each row in the output is a classified SDR trade with ~35 new
columns spanning classification, lifecycle, quality, package structure,
market context, relative value, and an enriched trade label.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd

from ._base import SDRAnalyzer
from .compression import detect_compression_signals
from .filters import (
    add_dv01_columns,
    add_execution_date,
    add_volume_buckets,
    daily_vwap,
)
from .flow import assign_trade_type, bucket_forward_start, classify_venue, infer_ccp
from .fomc import (
    assign_fomc_meeting,
    classify_meeting_proximity,
    classify_rate_index,
    load_fomc_schedule,
)
from .intraday import trade_clustering
from .seasonality import add_event_classifications
from .trade_quality import TradeQualityFlag, flag_outliers

# ---------------------------------------------------------------------------
# Execution session boundaries (Eastern Time hours)
# ---------------------------------------------------------------------------

_SESSION_BREAKS: List[tuple[int, int, str]] = [
    (2, 8, "London"),
    (8, 12, "NY_AM"),
    (12, 16, "NY_PM"),
    (16, 18, "Late"),
    # 18-02 wraps midnight -> handled as default
]


def _hour_to_session(hour: int) -> str:
    """Map an Eastern-Time hour (0-23) to a trading session label."""
    for lo, hi, label in _SESSION_BREAKS:
        if lo <= hour < hi:
            return label
    return "Asia"  # 18-23 and 0-1


# ---------------------------------------------------------------------------
# Rate-index abbreviation for trade labels
# ---------------------------------------------------------------------------

_INDEX_PREFIX = {
    "SOFR": "SOFR",
    "FED_FUNDS": "FF",
}


class TradeTape(SDRAnalyzer):
    """Unified trade enrichment pipeline.

    Takes a classified DataFrame (from ``load_classified_trades`` or
    ``build_classification_dataframe``) and produces a fully enriched
    tape with ~35 new columns across 7 layers.

    Args:
        df: Classified SDR trade DataFrame.
        cluster_gap_seconds: Max seconds between trades in the same
            temporal cluster (default 120).
        off_market_threshold_bp: Basis-point threshold for flagging
            off-market rates (default 10.0).
    """

    def __init__(
        self,
        df: pd.DataFrame,
        *,
        cluster_gap_seconds: int = 120,
        off_market_threshold_bp: float = 10.0,
    ) -> None:
        super().__init__(df)
        self._cluster_gap_seconds = cluster_gap_seconds
        self._off_market_threshold_bp = off_market_threshold_bp

    # -- prerequisites -----------------------------------------------------

    def _ensure_prerequisites(self, df: pd.DataFrame) -> pd.DataFrame:
        """Add execution_date, dv01, and tenor_bucket if missing."""
        if "execution_date" not in df.columns:
            df = add_execution_date(df)
        if "dv01" not in df.columns:
            df = add_dv01_columns(df)
        if "tenor_bucket" not in df.columns:
            df = add_volume_buckets(df)
        return df

    # -- placeholder layers (Tasks 2-8 fill these in) ----------------------

    def _enrich_classification(self, df: pd.DataFrame) -> pd.DataFrame:
        """Layer 1: trade type, forward bucket, rate index, venue, CCP."""
        df["trade_type"] = df.apply(assign_trade_type, axis=1)
        df["forward_bucket"] = df["forward_label"].map(bucket_forward_start)
        df["rate_index_clean"] = (
            df["upi_underlier_name"]
            .fillna("")
            .map(classify_rate_index)
        )
        df["venue"] = df["platform_identifier"].map(
            lambda x: classify_venue(x)
        )
        df["ccp"] = df.apply(infer_ccp, axis=1)
        return df

    def _enrich_lifecycle(self, df: pd.DataFrame) -> pd.DataFrame:
        return df

    def _enrich_quality(self, df: pd.DataFrame) -> pd.DataFrame:
        return df

    def _enrich_packages(self, df: pd.DataFrame) -> pd.DataFrame:
        return df

    def _enrich_context(self, df: pd.DataFrame) -> pd.DataFrame:
        return df

    def _enrich_rv(self, df: pd.DataFrame) -> pd.DataFrame:
        return df

    def _build_enriched_label(self, df: pd.DataFrame) -> pd.DataFrame:
        return df

    # -- public interface --------------------------------------------------

    def compute(self) -> pd.DataFrame:
        """Run all enrichment layers and return the fully enriched tape."""
        if self._result is not None:
            return self._result

        df = self._df.copy()
        df = self._ensure_prerequisites(df)
        df = self._enrich_classification(df)
        df = self._enrich_lifecycle(df)
        df = self._enrich_quality(df)
        df = self._enrich_packages(df)
        df = self._enrich_context(df)
        df = self._enrich_rv(df)
        df = self._build_enriched_label(df)

        self._result = df
        return df

    def summary(self) -> Dict[str, Any]:
        """Key stats for the enriched tape."""
        if self._result is None:
            self.compute()
        df = self._result
        n = len(df)
        return {}  # placeholder -- Task 9

    def clean_tape(self) -> pd.DataFrame:
        """Tape filtered to new-risk only, no UFRO/compression/reset-opt."""
        if self._result is None:
            self.compute()
        df = self._result
        return pd.DataFrame(columns=df.columns)  # placeholder -- Task 9

    def package_summary(self) -> pd.DataFrame:
        """One row per package_id with structure description."""
        if self._result is None:
            self.compute()
        return pd.DataFrame()  # placeholder -- Task 9
