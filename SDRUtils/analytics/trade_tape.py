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
from ..products._swaptions.upi import _load_swaps_df, _norm_upi, build_upi_path
from .filters import (
    add_execution_date,
    add_volume_buckets,
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
# ANNA DSB UPI reference helpers
# ---------------------------------------------------------------------------

_UNIT_SUFFIX = {
    "DAY": "D", "WEEK": "W", "MNTH": "M", "MONTH": "M", "YEAR": "Y",
}


def _term_label(value: object, unit: object) -> str:
    """Convert ANNA DSB term value+unit to compact label (e.g. '1D', '3M')."""
    if value is None or unit is None or pd.isna(value) or pd.isna(unit):
        return ""
    try:
        v = int(float(str(value).strip()))
    except (ValueError, TypeError):
        return ""
    u = str(unit).strip().upper()
    for prefix, suf in _UNIT_SUFFIX.items():
        if u.startswith(prefix):
            return f"{v}{suf}"
    return ""


def _load_swap_upi_lookup() -> pd.DataFrame:
    """Load ANNA DSB swap reference data and return a lookup DataFrame.

    Returns DataFrame indexed by normalized UPI with columns:
    upi_reset_freq, upi_notional_schedule, upi_delivery_type
    """
    try:
        swaps = _load_swaps_df(None)
    except Exception:
        return pd.DataFrame()
    if swaps.empty:
        return pd.DataFrame()

    # Build compact columns from ANNA DSB attributes
    out = pd.DataFrame(index=swaps.index)
    out["upi"] = swaps["swap_Identifier_UPI"]

    # Reset frequency: e.g. "1" + "DAYS" -> "1D"
    out["upi_reset_freq"] = swaps.apply(
        lambda r: _term_label(
            r.get("swap_Attributes_ReferenceRateTermValue"),
            r.get("swap_Attributes_ReferenceRateTermUnit"),
        ),
        axis=1,
    )

    # Notional schedule: CONSTANT, AMORTIZING, ACCRETING, CUSTOM
    out["upi_notional_schedule"] = (
        swaps.get("swap_Attributes_NotionalSchedule", pd.Series("", index=swaps.index))
        .fillna("")
        .astype(str)
        .str.strip()
        .str.title()
    )

    # Delivery type: PHYS, CASH
    out["upi_delivery_type"] = (
        swaps.get("swap_Attributes_DeliveryType", pd.Series("", index=swaps.index))
        .fillna("")
        .astype(str)
        .str.strip()
        .str.upper()
    )

    # Deduplicate on UPI (keep first)
    out = out.drop_duplicates(subset="upi", keep="first")
    return out.set_index("upi")


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
        """Add execution_date, risk, and tenor_bucket if missing."""
        if "execution_date" not in df.columns:
            df = add_execution_date(df)
        if "risk" not in df.columns:
            pv01 = pd.to_numeric(df.get("estimated_pv01", 0), errors="coerce")
            df["risk"] = pv01.abs().round(-2)
        if "tenor_bucket" not in df.columns:
            df = add_volume_buckets(df)
        # Drop garbage dv01 column if present (from legacy add_dv01_columns)
        if "dv01" in df.columns:
            df = df.drop(columns=["dv01"])
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

    def _enrich_upi_reference(self, df: pd.DataFrame) -> pd.DataFrame:
        """Layer 1b: merge ANNA DSB UPI reference data for reset/schedule/delivery."""
        # Defaults (fallback when UPI lookup misses)
        df["upi_reset_freq"] = ""
        df["upi_notional_schedule"] = ""
        df["upi_delivery_type"] = ""

        upi_col = "unique_product_identifier"
        if upi_col not in df.columns:
            return df

        try:
            lookup = _load_swap_upi_lookup()
        except Exception:
            return df
        if lookup.empty:
            return df

        # Normalize trade UPIs and merge
        norm_upis = df[upi_col].astype(str).map(_norm_upi)
        for col in ["upi_reset_freq", "upi_notional_schedule", "upi_delivery_type"]:
            mapped = norm_upis.map(lookup[col])
            df[col] = mapped.fillna("").values

        return df

    @staticmethod
    def _detect_off_date(df: pd.DataFrame, tolerance_days: int = 5) -> pd.DataFrame:
        """Flag broken-date swaps whose expiry doesn't match the standard anniversary.

        Uses QuantLib USD calendar to compute the business-day-adjusted
        standard maturity. A 7Y swap from 2026-04-14 should expire on
        the modified-following-adjusted 2033-04-14. If the actual expiry
        differs by more than ``tolerance_days`` business days, the trade
        is flagged as off-date.

        Adds columns: ``is_off_date`` (bool), ``tenor_display`` (str).
        ``tenor_display`` is ``~7Y`` for off-date or ``7Y`` for standard.
        """
        import re

        import QuantLib as ql

        from SDRUtils.config import USD_CONVENTIONS
        from SDRUtils.core.dates import to_ql_date

        cal = USD_CONVENTIONS.calendar
        bdc = USD_CONVENTIONS.business_day_convention

        df["is_off_date"] = False
        df["tenor_display"] = df["tenor_label"].astype(str)

        eff = pd.to_datetime(df.get("effective_date"), errors="coerce")
        exp = pd.to_datetime(df.get("expiration_date"), errors="coerce")
        tlabel = df["tenor_label"].astype(str)

        year_pattern = re.compile(r"^(\d+)Y$")

        for idx in df.index:
            m = year_pattern.match(str(tlabel.at[idx]))
            if not m:
                continue
            n_years = int(m.group(1))
            e, x = eff.at[idx], exp.at[idx]
            if pd.isna(e) or pd.isna(x):
                continue

            ql_eff = to_ql_date(e)
            ql_exp = to_ql_date(x)
            if ql_eff is None or ql_exp is None:
                continue

            # Standard maturity: effective + N years, adjusted to business day
            ql_standard = cal.adjust(
                cal.advance(ql_eff, ql.Period(n_years, ql.Years)),
                bdc,
            )

            # Count business days between actual expiry and standard
            bd_diff = abs(cal.businessDaysBetween(ql_exp, ql_standard))
            if bd_diff > tolerance_days:
                df.at[idx, "is_off_date"] = True
                df.at[idx, "tenor_display"] = f"~{n_years}Y"

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
        """Layer 4: package detection, structure derivation, leg count.

        Uses ``package_legs`` array (trade IDs) to resolve actual legs
        rather than grouping by ``package_id`` which can collide.
        """
        pkg = df["package_type"].astype(str).fillna("").str.upper()
        df["is_package"] = ~pkg.isin({"", "OUTRIGHT", "NAN", "NONE"})

        # Package transaction spread
        spread_col = "package_transaction_spread"
        if spread_col in df.columns:
            spread_val = pd.to_numeric(df[spread_col], errors="coerce")
            df["has_spread"] = spread_val.notna() & (spread_val != 0)
        else:
            df["has_spread"] = False

        # Defaults — use tenor_display (with ~7Y off-date notation) if available
        df["n_package_legs"] = 1
        tenor_src = "tenor_display" if "tenor_display" in df.columns else "tenor_label"
        df["package_tenors"] = df[tenor_src].astype(str)
        df["package_structure"] = ""

        # Build trade_id -> index lookup (string keys for type safety)
        tid_to_idx: dict[str, int] = {}
        if "trade_id" in df.columns:
            for idx, tid in df["trade_id"].items():
                tid_to_idx[str(tid)] = idx

        # Resolve package legs from package_legs array
        legs_col = "package_legs"
        if legs_col in df.columns and df["is_package"].any() and tid_to_idx:
            for idx in df.index[df["is_package"]]:
                legs = df.at[idx, legs_col]
                if legs is None or (isinstance(legs, float) and pd.isna(legs)):
                    continue
                try:
                    leg_ids = [str(x) for x in legs]
                except (TypeError, ValueError):
                    continue

                # Resolve leg indices
                leg_indices = [tid_to_idx[lid] for lid in leg_ids if lid in tid_to_idx]
                if len(leg_indices) < 2:
                    continue

                leg_rows = df.loc[leg_indices].sort_values("tenor_years")
                tenors = "/".join(leg_rows[tenor_src].astype(str).values)
                df.at[idx, "n_package_legs"] = len(leg_indices)
                df.at[idx, "package_tenors"] = tenors

        # Build package_structure from tenors + trade_type
        pkg_mask = df["is_package"]
        if pkg_mask.any():
            df.loc[pkg_mask, "package_structure"] = (
                df.loc[pkg_mask, "package_tenors"]
                + " "
                + df.loc[pkg_mask, "trade_type"].str.title()
            ).str.strip()

        # Non-package outrights
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

        return df

    def _build_enriched_label(self, df: pd.DataFrame) -> pd.DataFrame:
        """Layer 7: build professional ``tape_label``.

        Format: [underlier] [reset] [forward] [tenors] [structure] [flags] [mac_coupons] [settlement]
        Example: USD-SOFR-COMPOUND 1D Constant Spot 5Y Outright PHYS
        """
        # Build trade_id -> index lookup for MAC coupon resolution
        tid_to_idx: dict[str, int] = {}
        if "trade_id" in df.columns:
            for idx, tid in df["trade_id"].items():
                tid_to_idx[str(tid)] = idx

        def _label_for_row(row: pd.Series) -> str:
            parts: list[str] = []

            # 1. Underlier name
            underlier = str(row.get("upi_underlier_name", "")).strip()
            if underlier and underlier.lower() not in ("nan", "none", ""):
                parts.append(underlier)

            # 2. Reset frequency + notional schedule (from ANNA DSB UPI)
            reset = str(row.get("upi_reset_freq", "")).strip()
            schedule = str(row.get("upi_notional_schedule", "")).strip()
            if reset or schedule:
                parts.append(f"{reset} {schedule}".strip())
            else:
                # Fallback for trades without UPI match
                pt = str(row.get("product_type", "")).upper()
                if pt == "OIS_SWAP":
                    parts.append("1D Constant")

            # 3. Forward (normalize T+2 settlement labels to Spot)
            fwd = row.get("forward_label", "spot")
            fwd_years = row.get("forward_start_years", 0.0)
            try:
                fwd_years = float(fwd_years) if pd.notna(fwd_years) else 0.0
            except (ValueError, TypeError):
                fwd_years = 0.0
            if pd.isna(fwd) or str(fwd).lower() == "spot" or fwd_years <= 0.02:
                parts.append("Spot")
            else:
                parts.append(str(fwd))

            # 4. Tenors (package_tenors uses tenor_display with ~7Y off-date notation)
            tenors = str(row.get("package_tenors", row.get("tenor_display", row.get("tenor_label", ""))))
            if tenors and tenors.lower() not in ("nan", "none"):
                parts.append(tenors)

            # 5. Structure
            trade_type = str(row.get("trade_type", "OUTRIGHT")).upper()
            if trade_type in ("CURVE", "FLY"):
                parts.append(trade_type)
            elif trade_type == "SPREADOVER":
                parts.append("Spreadover")
            else:
                parts.append("Outright")

            # 6. Flags
            flags: list[str] = []
            if row.get("is_mac", False):
                flags.append("MAC")
            if row.get("is_ufro", False):
                flags.append("UFRO")
            if row.get("is_block", False):
                flags.append("BLOCK")
            # Lifecycle flags for non-NEWT
            ltype = str(row.get("lifecycle_type", "")).upper()
            if ltype in ("TERMINATION", "CORRECTION", "MODIFICATION"):
                flags.append(ltype[:4])
            if flags:
                parts.append(" ".join(flags))

            # 7. MAC coupons — show fixed rates of legs
            if row.get("is_mac", False):
                legs = row.get("package_legs")
                if legs is not None and not (isinstance(legs, float) and pd.isna(legs)):
                    try:
                        leg_ids = [str(x) for x in legs]
                        leg_indices = [tid_to_idx[lid] for lid in leg_ids if lid in tid_to_idx]
                        if leg_indices:
                            rates = df.loc[leg_indices, "fixed_rate"].dropna()
                            if not rates.empty:
                                rate_strs = [f"{r*100:.2f}" for r in rates.values]
                                parts.append(f"({'/'.join(rate_strs)})")
                    except (TypeError, ValueError, KeyError):
                        pass

            # 8. Settlement / delivery type (from ANNA DSB, fallback to cleared)
            delivery = str(row.get("upi_delivery_type", "")).strip().upper()
            if delivery and delivery.lower() not in ("nan", "none", ""):
                parts.append(delivery)
            else:
                cleared = str(row.get("cleared", "")).upper()
                if cleared in ("Y", "TRUE", "I"):
                    parts.append("PHYS")

            return " ".join(parts)

        df["tape_label"] = df.apply(_label_for_row, axis=1)
        # Clean double spaces
        df["tape_label"] = df["tape_label"].str.replace(r"\s+", " ", regex=True).str.strip()

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
        df = self._enrich_upi_reference(df)
        df = self._detect_off_date(df)
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
            n_legs, trade_type, total_risk, total_notional, has_spread,
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
                total_risk=("risk", "sum"),
                total_notional=("notional", "sum"),
                has_spread=("has_spread", "first"),
                rate_index_clean=("rate_index_clean", "first"),
            )
            .sort_values("total_risk", ascending=False)
            .reset_index()
        )
