"""
Trade Tape: single enriched DataFrame with all signals a market maker needs.

Composes existing analytics modules into a unified per-trade enrichment
pipeline.  Each row in the output is a classified SDR trade with ~35 new
columns spanning classification, lifecycle, quality, package structure,
market context, relative value, and an enriched trade label.
"""
from __future__ import annotations

from typing import Any, Dict, List

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
            .astype(str)
            .fillna("")
            .map(classify_rate_index)
        )
        df["venue"] = df["platform_identifier"].map(
            lambda x: classify_venue(x)
        )
        df["ccp"] = df.apply(infer_ccp, axis=1)
        return df

    def _enrich_lifecycle(self, df: pd.DataFrame) -> pd.DataFrame:
        """Layer 2: lifecycle type, new-risk, compression, reset-opt flags."""
        action = df["event_action"].astype(str).str.upper()

        # Extract first token (e.g. "NEWT-TRAD" -> "NEWT", "NEWT" -> "NEWT")
        action_prefix = action.str.split(r"[-\s]", n=1).str[0]

        lifecycle_map = {
            "NEWT": "NEW_TRADE",
            "TERM": "TERMINATION",
            "CORR": "CORRECTION",
            "MODI": "MODIFICATION",
        }
        df["lifecycle_type"] = action_prefix.map(lifecycle_map).fillna("OTHER")
        df["is_new_risk"] = action_prefix == "NEWT"

        # Reuse compression signals for consistency
        signals = detect_compression_signals(df)
        df["is_compression"] = signals["is_lifecycle"].values
        df["is_reset_optimization"] = signals["is_reset_opt"].values

        return df

    def _enrich_quality(self, df: pd.DataFrame) -> pd.DataFrame:
        """Layer 3: UFRO, off-market, capped, block, quality flags."""
        df = flag_outliers(df, threshold_bp=self._off_market_threshold_bp)

        # Block trade flag
        col = "block_trade_election_indicator"
        if col in df.columns:
            df["is_block"] = df[col].astype(str).str.upper().isin({"TRUE", "1"})
        else:
            df["is_block"] = False

        # Add COMPRESSION to quality_flags for lifecycle events
        if "is_compression" in df.columns and "quality_flags" in df.columns:
            comp_mask = df["is_compression"]
            df.loc[comp_mask, "quality_flags"] = df.loc[comp_mask, "quality_flags"].apply(
                lambda flags: flags + [TradeQualityFlag.COMPRESSION.value]
                if TradeQualityFlag.COMPRESSION.value not in flags
                else flags
            )

        return df

    def _enrich_packages(self, df: pd.DataFrame) -> pd.DataFrame:
        """Layer 4: package detection, structure derivation, leg count."""
        pkg = df["package_type"].astype(str).fillna("").str.upper()
        df["is_package"] = ~pkg.isin({"", "OUTRIGHT", "NAN", "NONE"})

        # Package transaction spread
        spread_col = "package_transaction_spread"
        if spread_col in df.columns:
            spread_val = pd.to_numeric(df[spread_col], errors="coerce")
            df["has_spread"] = spread_val.notna() & (spread_val != 0)
        else:
            df["has_spread"] = False

        # Package leg count and structure
        df["n_package_legs"] = 1
        df["package_structure"] = ""

        pkg_id_col = "package_id"
        if pkg_id_col in df.columns and df["is_package"].any():
            pkg_groups = (
                df[df["is_package"]]
                .groupby(pkg_id_col)
                .agg(
                    n_legs=("tenor_label", "size"),
                    tenors=("tenor_label", lambda x: "/".join(
                        x.dropna().astype(str).tolist()
                    )),
                    pkg_type=("trade_type", "first"),
                )
            )
            # Map back to df
            for pkg_id, row in pkg_groups.iterrows():
                mask = df[pkg_id_col] == pkg_id
                df.loc[mask, "n_package_legs"] = row["n_legs"]
                structure = f"{row['tenors']} {row['pkg_type'].title()}"
                df.loc[mask, "package_structure"] = structure.strip()

        # Non-package outrights get a simple structure
        outright_mask = ~df["is_package"]
        if outright_mask.any():
            df.loc[outright_mask, "package_structure"] = (
                df.loc[outright_mask, "tenor_label"].astype(str) + " Outright"
            )

        return df

    def _enrich_context(self, df: pd.DataFrame) -> pd.DataFrame:
        """Layer 5: event windows, FOMC meeting label/proximity, session."""
        # Event classifications (FOMC, month-end, quarter-end)
        df = add_event_classifications(
            df,
            date_col="execution_timestamp",
            include_me=True,
            include_qe=True,
            include_fomc=True,
        )

        # FOMC meeting label and proximity for FOMC-dated trades
        df["fomc_meeting_label"] = ""
        df["fomc_proximity"] = ""

        fomc_mask = df.get("special_tenor_type", pd.Series("", index=df.index)).astype(str).str.upper() == "FOMC"
        if fomc_mask.any():
            try:
                schedule = load_fomc_schedule()
                if not schedule.empty:
                    mat_to_label = dict(
                        zip(
                            schedule["maturity_date"].dt.date,
                            schedule["meeting_label"],
                        )
                    )
                    eff_to_label = dict(
                        zip(
                            schedule["effective_date"].dt.date,
                            schedule["meeting_label"],
                        )
                    )

                    def _assign_meeting(row):
                        exp = pd.to_datetime(row.get("expiration_date"))
                        eff = pd.to_datetime(row.get("effective_date"))
                        if pd.notna(exp):
                            d = exp.date() if hasattr(exp, "date") else exp
                            lbl = mat_to_label.get(d)
                            if lbl:
                                return lbl
                        if pd.notna(eff):
                            d = eff.date() if hasattr(eff, "date") else eff
                            lbl = eff_to_label.get(d)
                            if lbl:
                                return lbl
                        return ""

                    df.loc[fomc_mask, "fomc_meeting_label"] = (
                        df[fomc_mask].apply(_assign_meeting, axis=1)
                    )

                    # Proximity requires meeting_eff column
                    meeting_eff_map = dict(
                        zip(
                            schedule["meeting_label"],
                            schedule["effective_date"],
                        )
                    )
                    labelled = df["fomc_meeting_label"] != ""
                    if labelled.any():
                        df.loc[labelled, "fomc_proximity"] = df[labelled].apply(
                            lambda r: classify_meeting_proximity(
                                pd.Series({
                                    "execution_timestamp": r["execution_timestamp"],
                                    "meeting_eff": meeting_eff_map.get(
                                        r["fomc_meeting_label"]
                                    ),
                                }),
                                schedule,
                            ),
                            axis=1,
                        )
            except Exception:
                pass  # schedule not available

        # Execution session (Eastern Time)
        ts = pd.to_datetime(df["execution_timestamp"], errors="coerce")
        try:
            ts_et = ts.dt.tz_convert("America/New_York")
        except TypeError:
            try:
                ts_et = ts.dt.tz_localize("UTC").dt.tz_convert("America/New_York")
            except Exception:
                ts_et = ts

        df["execution_hour_et"] = ts_et.dt.hour
        df["execution_session"] = df["execution_hour_et"].map(_hour_to_session)

        return df

    def _enrich_rv(self, df: pd.DataFrame) -> pd.DataFrame:
        """Layer 6: temporal clusters, daily VWAP, rate vs VWAP."""
        # Trade clustering
        clustered = trade_clustering(
            df,
            ts_col="execution_timestamp",
            gap_seconds=self._cluster_gap_seconds,
        )
        df["cluster_id"] = clustered["cluster_id"].values
        df["cluster_size"] = df.groupby("cluster_id")["cluster_id"].transform("size")

        # Multi-meeting cluster detection (FOMC trades spanning multiple meetings)
        df["is_multi_meeting_cluster"] = False
        if "fomc_meeting_label" in df.columns:
            fomc_in_cluster = (
                df[df["fomc_meeting_label"] != ""]
                .groupby("cluster_id")["fomc_meeting_label"]
                .nunique()
            )
            multi_ids = fomc_in_cluster[fomc_in_cluster > 1].index
            df.loc[df["cluster_id"].isin(multi_ids), "is_multi_meeting_cluster"] = True

        # Daily tenor VWAP
        df["daily_tenor_vwap"] = np.nan
        df["rate_vs_vwap_bp"] = np.nan

        rate = pd.to_numeric(df.get("fixed_rate", pd.Series(np.nan, index=df.index)), errors="coerce")
        has_rate = rate.notna()
        if has_rate.any() and "tenor_label" in df.columns and "execution_date" in df.columns:
            vwap_df = daily_vwap(
                df[has_rate],
                group_col="tenor_label",
                rate_col="fixed_rate",
                weight_col="dv01",
                date_col="execution_date",
            )
            if not vwap_df.empty:
                vwap_map = vwap_df.set_index(["execution_date", "tenor_label"])["vwap"]
                keys = list(zip(df["execution_date"], df["tenor_label"]))
                df["daily_tenor_vwap"] = [vwap_map.get(k, np.nan) for k in keys]
                df["rate_vs_vwap_bp"] = (rate - df["daily_tenor_vwap"]) * 10_000

        return df

    def _build_enriched_label(self, df: pd.DataFrame) -> pd.DataFrame:
        """Layer 7: enrich trade_label with prefix tags.

        Mirrors the swaption ``_backfill_swaption_fields`` pattern:
        prefix tokens are prepended to the base label.

        Token order: [INDEX] [LIFECYCLE] [QUALITY] [STRUCTURE] base_label
        Examples: SOFR spot 10Y, SOFR UFRO spot 5Y, FF CURVE 2Y/5Y
        """
        from SDRUtils.core.tenors import build_trade_label

        # Stage 1: ensure base label exists
        missing_label = (
            df["trade_label"].isna()
            | (df["trade_label"].astype(str).str.strip() == "")
        )
        if missing_label.any():
            df.loc[missing_label, "trade_label"] = df[missing_label].apply(
                lambda r: build_trade_label(
                    str(r.get("forward_label", "spot")),
                    str(r.get("tenor_label", "UNK")),
                    bool(r.get("is_forward", False)),
                ),
                axis=1,
            )

        # Stage 2: for packages, replace base label with slash-joined tenors
        if "package_structure" in df.columns:
            pkg_mask = df["is_package"] & df["package_structure"].astype(str).str.contains("/")
            if pkg_mask.any():
                # Extract tenor part from package_structure ("10Y/5Y Curve" -> "10Y/5Y")
                df.loc[pkg_mask, "trade_label"] = (
                    df.loc[pkg_mask, "package_structure"]
                    .str.rsplit(" ", n=1)
                    .str[0]
                )

        # Stage 3: build prefix tokens
        # (a) Rate index prefix
        tokens = df["rate_index_clean"].map(_INDEX_PREFIX).fillna("")

        # (b) Lifecycle prefix (non-NEWT only)
        lifecycle_prefix = df["lifecycle_type"].map({
            "TERMINATION": "TERM",
            "CORRECTION": "CORR",
            "MODIFICATION": "MODI",
        }).fillna("")
        has_lifecycle = lifecycle_prefix != ""
        tokens = tokens.where(~has_lifecycle, tokens + " " + lifecycle_prefix)

        # (c) Quality prefix: UFRO or BLOCK (pick the most important one)
        quality_prefix = pd.Series("", index=df.index, dtype=str)
        if "is_ufro" in df.columns:
            quality_prefix = quality_prefix.where(~df["is_ufro"], "UFRO")
        if "is_block" in df.columns:
            # BLOCK only if not already UFRO
            block_only = df.get("is_block", False) & (quality_prefix == "")
            quality_prefix = quality_prefix.where(~block_only, "BLOCK")
        has_quality = quality_prefix != ""
        tokens = tokens.where(~has_quality, tokens + " " + quality_prefix)

        # (d) Structure prefix (CURVE/FLY for packages)
        structure_prefix = pd.Series("", index=df.index, dtype=str)
        if "trade_type" in df.columns:
            pkg_type = df["trade_type"].where(
                df["trade_type"].isin({"CURVE", "FLY"}), ""
            )
            structure_prefix = pkg_type
        has_structure = structure_prefix != ""
        tokens = tokens.where(~has_structure, tokens + " " + structure_prefix)

        # Stage 4: prepend tokens to trade_label
        tokens = tokens.str.strip()
        has_prefix = tokens != ""
        df.loc[has_prefix, "trade_label"] = (
            tokens[has_prefix] + " " + df.loc[has_prefix, "trade_label"].astype(str)
        ).str.strip()

        # Clean up any double spaces
        df["trade_label"] = df["trade_label"].str.replace(r"\s+", " ", regex=True).str.strip()

        return df

    # -- public interface --------------------------------------------------

    def compute(self) -> pd.DataFrame:
        """Run all enrichment layers and return the fully enriched tape."""
        if self._result is not None:
            return self._result

        df = self._df.copy()
        if df.empty:
            self._result = df
            return df
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
        n_new = int(df["is_new_risk"].sum()) if "is_new_risk" in df.columns else 0
        n_comp = int(df["is_compression"].sum()) if "is_compression" in df.columns else 0

        return {
            "n_trades": n,
            "n_new_risk": n_new,
            "pct_new_risk": round(n_new / max(n, 1) * 100, 1),
            "pct_compression": round(n_comp / max(n, 1) * 100, 1),
            "pct_ufro": round(
                df["is_ufro"].sum() / max(n, 1) * 100, 1
            ) if "is_ufro" in df.columns else 0,
            "pct_block": round(
                df["is_block"].sum() / max(n, 1) * 100, 1
            ) if "is_block" in df.columns else 0,
            "pct_capped": round(
                df["is_capped"].sum() / max(n, 1) * 100, 1
            ) if "is_capped" in df.columns else 0,
            "top_trade_types": (
                df["trade_type"].value_counts().head(5).to_dict()
                if "trade_type" in df.columns else {}
            ),
            "venue_split": (
                df["venue"].value_counts().to_dict()
                if "venue" in df.columns else {}
            ),
            "ccp_split": (
                df["ccp"].value_counts().to_dict()
                if "ccp" in df.columns else {}
            ),
        }

    def clean_tape(self) -> pd.DataFrame:
        """Tape filtered to new-risk only, no UFRO/compression/reset-opt.

        Returns the 'real' organic flow: NEWT trades with tenor >= 0.5Y,
        excluding off-market-coupon (UFRO) trades.
        """
        if self._result is None:
            self.compute()
        df = self._result

        mask = pd.Series(True, index=df.index)
        if "is_new_risk" in df.columns:
            mask &= df["is_new_risk"]
        if "is_ufro" in df.columns:
            mask &= ~df["is_ufro"]
        if "is_compression" in df.columns:
            mask &= ~df["is_compression"]
        if "is_reset_optimization" in df.columns:
            mask &= ~df["is_reset_optimization"]

        return df[mask].copy()

    def package_summary(self) -> pd.DataFrame:
        """One row per package_id with structure description.

        Returns:
            DataFrame with columns: package_id, package_structure,
            n_legs, trade_type, total_dv01, total_notional, has_spread,
            rate_index_clean.
        """
        if self._result is None:
            self.compute()
        df = self._result

        if "is_package" not in df.columns or "package_id" not in df.columns:
            return pd.DataFrame()
        pkg = df[df["is_package"]].copy()
        if pkg.empty:
            return pd.DataFrame()

        return (
            pkg.groupby("package_id")
            .agg(
                package_structure=("package_structure", "first"),
                n_legs=("package_id", "size"),
                trade_type=("trade_type", "first"),
                total_dv01=("dv01", "sum"),
                total_notional=("notional", "sum"),
                has_spread=("has_spread", "first"),
                rate_index_clean=("rate_index_clean", "first"),
            )
            .sort_values("total_dv01", ascending=False)
            .reset_index()
        )
