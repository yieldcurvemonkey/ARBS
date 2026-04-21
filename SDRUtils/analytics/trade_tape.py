"""
Trade Tape: single enriched DataFrame with all signals a market maker needs.

Composes existing analytics modules into a unified per-trade enrichment
pipeline.  Each row in the output is a classified SDR trade with ~35 new
columns spanning classification, lifecycle, quality, package structure,
market context, relative value, and an enriched trade label.
"""
from __future__ import annotations

import hashlib
import os
import pickle
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
    consecutive_meeting_pair,
    load_fomc_schedule,
    short_meeting_label,
)
from ..core.tenors import get_imm_label
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
# Result cache versioning
# ---------------------------------------------------------------------------

TRADE_TAPE_CACHE_VERSION = "v1"
DEFAULT_CACHE_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "notebooks", "sdr", "_cache", "trade_tape",
)


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


def _match_novation_pairs(df: pd.DataFrame) -> pd.DataFrame:
    """Conservative heuristic matching of TERM+NOVA <-> NEWT+NOVA pairs.

    Match criteria:
    - Same notional (exact)
    - Same tenor_years (within 0.1Y)
    - Timestamps within 60 seconds
    - Same upi_underlier_name

    Greedy 1:1 matching. Unmatched trades get NaN.
    """
    df["novation_match_id"] = pd.Series(dtype="object", index=df.index)
    df["novation_confidence"] = pd.Series(dtype="object", index=df.index)

    term_nova = df[df.get("is_novation_terminated", pd.Series(False, index=df.index)) == True]
    newt_nova = df[df.get("is_novation_born", pd.Series(False, index=df.index)) == True]

    if term_nova.empty or newt_nova.empty:
        return df

    matched_newt_indices = set()
    match_seq = 0

    for t_idx, t_row in term_nova.iterrows():
        t_ts = pd.to_datetime(t_row.get("execution_timestamp"))
        t_notional = t_row.get("notional", 0)
        t_tenor = t_row.get("tenor_years", 0)
        t_underlier = str(t_row.get("upi_underlier_name", ""))

        best_idx = None
        best_score = 0

        for n_idx, n_row in newt_nova.iterrows():
            if n_idx in matched_newt_indices:
                continue

            # Mandatory gates: notional must match exactly
            if t_notional != n_row.get("notional", -1):
                continue

            # Mandatory gate: timestamps within 60s
            n_ts = pd.to_datetime(n_row.get("execution_timestamp"))
            try:
                if abs((t_ts - n_ts).total_seconds()) > 60:
                    continue
            except (TypeError, AttributeError):
                continue

            score = 2  # notional + timestamp already matched

            # Criterion 3: tenor within 0.1Y
            n_tenor = n_row.get("tenor_years", -999)
            try:
                if abs(float(t_tenor) - float(n_tenor)) <= 0.1:
                    score += 1
            except (ValueError, TypeError):
                pass

            # Criterion 4: same underlier
            if t_underlier == str(n_row.get("upi_underlier_name", "")):
                score += 1

            if score >= 3 and score > best_score:
                best_score = score
                best_idx = n_idx

        if best_idx is not None:
            match_id = f"nova_{match_seq}"
            confidence = "HIGH" if best_score == 4 else "MEDIUM"
            df.at[t_idx, "novation_match_id"] = match_id
            df.at[t_idx, "novation_confidence"] = confidence
            df.at[best_idx, "novation_match_id"] = match_id
            df.at[best_idx, "novation_confidence"] = confidence
            matched_newt_indices.add(best_idx)
            match_seq += 1

    return df


class TradeTape(SDRAnalyzer):
    """Unified trade enrichment pipeline.

    Takes a classified DataFrame (from ``load_usd_swaps`` or
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
        raw_df: pd.DataFrame | None = None,
        cluster_gap_seconds: int = 120,
        off_market_threshold_bp: float = 10.0,
    ) -> None:
        super().__init__(df)
        self._raw_df = raw_df
        self._cluster_gap_seconds = cluster_gap_seconds
        self._off_market_threshold_bp = off_market_threshold_bp

    # -- result cache ------------------------------------------------------

    def _cache_key(self) -> str:
        """Deterministic hash of inputs that affect compute() output."""
        df = self._df
        parts: list[str] = [str(len(df))]
        if "execution_timestamp" in df.columns and not df.empty:
            parts.append(str(df["execution_timestamp"].min()))
            parts.append(str(df["execution_timestamp"].max()))
        if "trade_id" in df.columns and not df.empty:
            parts.append(
                hashlib.sha256(
                    "".join(sorted(df["trade_id"].astype(str))).encode()
                ).hexdigest()[:16]
            )
        parts.append(
            str(len(self._raw_df)) if self._raw_df is not None else "no_raw"
        )
        parts.append(str(self._cluster_gap_seconds))
        parts.append(str(self._off_market_threshold_bp))
        parts.append(TRADE_TAPE_CACHE_VERSION)
        return hashlib.sha256("|".join(parts).encode()).hexdigest()[:20]

    def _cache_path(self, cache_dir: str | None = None) -> str:
        directory = cache_dir or DEFAULT_CACHE_DIR
        return os.path.join(directory, f"{self._cache_key()}.pkl")

    def _try_load_cache(self, cache_dir: str | None = None) -> pd.DataFrame | None:
        """Return cached DataFrame for current inputs, or None on miss/corruption."""
        path = self._cache_path(cache_dir)
        if not os.path.exists(path):
            return None
        try:
            with open(path, "rb") as f:
                return pickle.load(f)
        except Exception as e:
            import warnings
            warnings.warn(f"TradeTape cache load failed ({path}): {e}")
            return None

    def _save_cache(self, df: pd.DataFrame, cache_dir: str | None = None) -> None:
        """Persist compute() output to the cache directory."""
        path = self._cache_path(cache_dir)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        try:
            with open(path, "wb") as f:
                pickle.dump(df, f, protocol=pickle.HIGHEST_PROTOCOL)
        except Exception as e:
            import warnings
            warnings.warn(f"TradeTape cache save failed ({path}): {e}")

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

        # Unwind/novation flag: effective_date before execution = backdated
        df["is_unwind"] = False
        fwd_yrs = pd.to_numeric(
            df.get("forward_start_years", pd.Series(0.0, index=df.index)),
            errors="coerce",
        ).fillna(0.0)
        df["is_unwind"] = fwd_yrs < -0.02  # more than ~7 days backdated

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
        """Layer 2: lifecycle type, new-risk, correction flags, compression, reset-opt."""
        if "lc_status" in df.columns:
            # Pre-resolved lifecycle from classification pipeline
            lc_status = df["lc_status"].fillna("ACTIVE")
            status_map = {
                "ACTIVE": "NEW_TRADE",
                "TERMINATED": "TERMINATION",
                "ERRORED": "OTHER",
            }
            df["lifecycle_type"] = lc_status.map(status_map).fillna("OTHER")
            df["is_new_risk"] = (df["lc_n_events"].fillna(1) <= 1) & (lc_status == "ACTIVE")
            df["is_corrected"] = df["lc_is_corrected"].fillna(False)
            df["correction_crossed_day"] = df["lc_correction_crossed_day"].fillna(False)
        else:
            # Fallback for old cached data without lc_* columns
            action = df["event_action"].astype(str).str.upper()
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
        # Always False: the prior tenor<0.5 "reset optimization" heuristic was a
        # misnomer (flagged any short-dated NEWT, not true reset-opt cycles) and
        # has been removed. Column retained as False so downstream schema /
        # dashboard SQL (``NOT d.is_reset_optimization_any``) keep working.
        df["is_reset_optimization"] = False

        return df

    def _enrich_cross_day_lifecycle(self, df: pd.DataFrame) -> pd.DataFrame:
        """Layer 2b: cross-day lifecycle resolution from full raw data."""
        if self._raw_df is None:
            return df

        from SDRUtils.core.lifecycle import resolve_lifecycle_cross_day

        classified_ids = set(df["trade_id"].astype(str).values)
        xd_df = resolve_lifecycle_cross_day(self._raw_df, classified_ids)

        if xd_df.empty:
            return df

        xd_df.index = xd_df.index.astype(str)
        df = df.merge(
            xd_df,
            left_on="trade_id",
            right_index=True,
            how="left",
        )

        # Fill defaults for trades without cross-day events
        defaults = {
            "xd_n_events": 1,
            "xd_status": "ACTIVE",
            "xd_notional_pct_remaining": 1.0,
            "xd_is_terminated": False,
            "xd_has_partial_unwind": False,
            "xd_was_corrected": False,
            "xd_was_amended": False,
            "xd_fields_changed": "",
            "xd_correction_lag_seconds": 0,
            "xd_n_days_spanned": 1,
        }
        for col, default in defaults.items():
            if col in df.columns:
                df[col] = df[col].fillna(default)

        # Fill notional defaults from trade notional
        if "xd_inception_notional" in df.columns and "notional" in df.columns:
            df["xd_inception_notional"] = df["xd_inception_notional"].fillna(df["notional"])
        if "xd_current_notional" in df.columns and "notional" in df.columns:
            df["xd_current_notional"] = df["xd_current_notional"].fillna(df["notional"])

        return df

    def _enrich_event_type(self, df: pd.DataFrame) -> pd.DataFrame:
        """Layer 2c: CFTC spec Event type flags (NOVA, COMP, EXER, CLRG)."""
        # Extract event_type — prefer dedicated column, fallback to event_action
        if "event_type" in df.columns:
            et = df["event_type"].astype(str).str.upper().str.strip()
        elif "event_action" in df.columns:
            parts = df["event_action"].astype(str).str.split("-", n=1)
            et = parts.str[1].fillna("").str.upper().str.strip()
        else:
            return df

        # Action type prefix for directional flags
        action = df.get("event_action", pd.Series("", index=df.index))
        action_prefix = action.astype(str).str.split("-", n=1).str[0].str.upper()

        # Boolean flags
        df["is_compression_spec"] = et == "COMP"
        df["is_exercise_born"] = et == "EXER"
        df["is_novation"] = et == "NOVA"
        df["is_novation_born"] = (et == "NOVA") & (action_prefix == "NEWT")
        df["is_novation_terminated"] = (et == "NOVA") & (action_prefix == "TERM")
        df["is_clearing_termination"] = (et == "CLRG")

        # Non-standardized term indicator passthrough
        nst_col = "non-standardized_term_indicator"
        if nst_col in df.columns:
            df["is_non_standard_term"] = df[nst_col].astype(str).str.upper().isin({"TRUE", "1"})
        else:
            df["is_non_standard_term"] = False

        # Novation chain matching
        if df["is_novation"].any():
            df = _match_novation_pairs(df)
        else:
            df["novation_match_id"] = pd.Series(dtype="object", index=df.index)
            df["novation_confidence"] = pd.Series(dtype="object", index=df.index)

        # Override heuristic compression with spec signal
        if "is_compression" in df.columns:
            df["is_compression"] = df["is_compression"] | df["is_compression_spec"]
        else:
            df["is_compression"] = df["is_compression_spec"]

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

        # Resolve package legs from package_legs array (batched assignment).
        # Uses positional numpy indexing throughout to avoid per-row .loc[]
        # DataFrame slices and sort_values, each of which allocates a new
        # frame. On 9K packages that overhead dominates.
        legs_col = "package_legs"
        if "trade_id" in df.columns and legs_col in df.columns and df["is_package"].any():
            import numpy as np

            # Positional lookup: trade_id -> integer position in df
            tid_arr = df["trade_id"].astype(str).to_numpy()
            tid_to_pos: dict[str, int] = {tid: i for i, tid in enumerate(tid_arr)}

            # Pre-materialize columns as numpy arrays for O(1) positional access
            tenor_years_arr = df["tenor_years"].to_numpy()
            tenor_src_arr = df[tenor_src].astype(str).to_numpy()
            legs_arr = df[legs_col].to_numpy()
            is_pkg_arr = df["is_package"].to_numpy()
            df_indices = df.index.to_numpy()

            pkg_positions = np.where(is_pkg_arr)[0]

            # --- UPI validator (safety net) -------------------------------
            # Catches SDR-native packages that bypass our detectors: if any
            # multi-leg group carries >1 distinct Unique Product Identifier,
            # the group is a false positive -> reset to OUTRIGHT.
            upi_col_raw = "Unique Product Identifier"
            upi_col_snake = "unique_product_identifier"
            upi_col = (
                upi_col_raw if upi_col_raw in df.columns else
                upi_col_snake if upi_col_snake in df.columns else None
            )
            if upi_col is not None and len(pkg_positions) > 0:
                upi_arr = df[upi_col].astype(str).to_numpy()
                to_unpackage: list = []
                for pos in pkg_positions:
                    legs = legs_arr[pos]
                    if legs is None or (isinstance(legs, float) and pd.isna(legs)):
                        continue
                    try:
                        leg_ids = [str(x) for x in legs]
                    except (TypeError, ValueError):
                        continue
                    leg_positions = [tid_to_pos[lid] for lid in leg_ids if lid in tid_to_pos]
                    if len(leg_positions) < 2:
                        continue
                    leg_upis = {
                        upi_arr[p] for p in leg_positions
                        if upi_arr[p] and upi_arr[p].lower() not in ("nan", "none", "")
                    }
                    if len(leg_upis) > 1:
                        to_unpackage.extend(df_indices[p] for p in leg_positions)

                if to_unpackage:
                    df.loc[to_unpackage, "package_type"] = "OUTRIGHT"
                    if "package_id" in df.columns:
                        df.loc[to_unpackage, "package_id"] = None
                    if "package_legs" in df.columns:
                        df.loc[to_unpackage, "package_legs"] = None
                    df.loc[to_unpackage, "is_package"] = False
                    if "trade_type" in df.columns:
                        df.loc[to_unpackage, "trade_type"] = "OUTRIGHT"
                    # Recompute is_package mask + cached arrays so the rest of
                    # this method (tenor join, structure label) respects the
                    # un-package.
                    pkg = df["package_type"].astype(str).fillna("").str.upper()
                    df["is_package"] = ~pkg.isin({"", "OUTRIGHT", "NAN", "NONE"})
                    is_pkg_arr = df["is_package"].to_numpy()
                    legs_arr = df[legs_col].to_numpy()
                    pkg_positions = np.where(is_pkg_arr)[0]

            valid_indices: list = []
            n_legs_arr: list[int] = []
            tenors_arr: list[str] = []

            for pos in pkg_positions:
                legs = legs_arr[pos]
                if legs is None or (isinstance(legs, float) and pd.isna(legs)):
                    continue
                try:
                    leg_ids = [str(x) for x in legs]
                except (TypeError, ValueError):
                    continue

                leg_positions = [tid_to_pos[lid] for lid in leg_ids if lid in tid_to_pos]
                if len(leg_positions) < 2:
                    continue

                # Sort leg positions by tenor_years using numpy (much cheaper
                # than df.loc[...].sort_values on a 100+-col frame)
                leg_pos_arr = np.asarray(leg_positions)
                sort_order = np.argsort(tenor_years_arr[leg_pos_arr], kind="stable")
                sorted_tenors = tenor_src_arr[leg_pos_arr[sort_order]]

                valid_indices.append(df_indices[pos])
                n_legs_arr.append(len(leg_positions))
                tenors_arr.append("/".join(sorted_tenors))

            if valid_indices:
                df.loc[valid_indices, "n_package_legs"] = n_legs_arr
                df.loc[valid_indices, "package_tenors"] = tenors_arr

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
                        """Return ``(label, append_tenor)`` for a single row.

                        * Tier 1 consecutive -> ``("APR26", False)``
                        * Tier 3a non-consecutive FOMC/FOMC -> ``("APR26 DEC26", False)``
                        * Tier 3b FOMC + constant tenor -> ``("APR26", True)``
                        * Tier 2 (quarterly IMM + constant-tenor mat) -> ``("", False)``
                          so the downstream forward+tenor branch prints
                          ``"IMM_Z2026 10Y"``.
                        """
                        eff = pd.to_datetime(row.get("effective_date"), errors="coerce")
                        mat = pd.to_datetime(row.get("expiration_date"), errors="coerce")
                        if pd.isna(eff) or pd.isna(mat):
                            return ("", False)
                        eff_date = eff.date()
                        mat_date = mat.date()
                        eff_lbl_raw = eff_to_label.get(eff_date)
                        # Prefer the meeting that STARTS at mat (eff_to_label)
                        # so endpoint-to-endpoint labels like "APR26 DEC26"
                        # resolve cleanly. Fall back to mat_to_label for
                        # completeness.
                        mat_lbl_raw = eff_to_label.get(mat_date) or mat_to_label.get(mat_date)

                        # Tier 1 — consecutive FOMC meetings.
                        if eff_lbl_raw and mat_lbl_raw and consecutive_meeting_pair(
                            eff, mat, schedule
                        ):
                            return (short_meeting_label(eff_lbl_raw), False)

                        # Tier 2 — quarterly IMM eff + constant-tenor mat.
                        if get_imm_label(eff) is not None and not mat_lbl_raw:
                            tenor_label = str(row.get("tenor_label", ""))
                            if not (
                                tenor_label.startswith("IMM_")
                                or tenor_label.startswith("FOMC_")
                            ):
                                return ("", False)

                        # Tier 3a — FOMC eff + FOMC mat but non-consecutive.
                        if eff_lbl_raw and mat_lbl_raw:
                            return (
                                short_meeting_label(eff_lbl_raw)
                                + " "
                                + short_meeting_label(mat_lbl_raw),
                                False,
                            )

                        # Tier 3b — FOMC eff + constant-tenor mat. Flag that
                        # the label builder should append the tenor display
                        # so the final tape_label reads "FOMC APR26 10Y".
                        if eff_lbl_raw:
                            return (short_meeting_label(eff_lbl_raw), True)

                        return ("", False)

                    # Broaden the mask — tier rules consume eff AND mat, so we
                    # can't rely on the upstream ``special_tenor_type == FOMC``
                    # gate alone.
                    def _eff_hits(d):
                        ts = pd.to_datetime(d, errors="coerce")
                        if pd.isna(ts):
                            return False
                        return eff_to_label.get(ts.date()) is not None

                    candidate_mask = df["effective_date"].map(_eff_hits) | fomc_mask

                    if "fomc_label_append_tenor" not in df.columns:
                        df["fomc_label_append_tenor"] = False
                    if candidate_mask.any():
                        assignments = df[candidate_mask].apply(
                            _assign_meeting, axis=1, result_type="expand"
                        )
                        assignments.columns = [
                            "_fomc_label", "_fomc_append_tenor"
                        ]
                        df.loc[candidate_mask, "fomc_meeting_label"] = (
                            assignments["_fomc_label"]
                        )
                        df.loc[candidate_mask, "fomc_label_append_tenor"] = (
                            assignments["_fomc_append_tenor"]
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
        """Layer 7: build professional ``tape_label`` (package scope) and
        ``leg_tape_label`` (per-leg scope).

        Package-scope format (tape_label on both legs and packages): uses the
        package tenor pair ("5Y/10Y") and structure ("CURVE"/"FLY"). Used for
        groupby/search across the tape.

        Leg-scope format (leg_tape_label, legs only): uses the leg's own tenor
        and "Outright" structure for CURVE/FLY legs, so each package leg shows
        its own outright description in the expanded sub-table. For all other
        trade types the two labels are identical.

        Format: [underlier] [reset] [forward] [tenors] [structure] [flags] [mac_coupons] [settlement]
        Example (package): USD-SOFR-COMPOUND 1D Constant Spot 5Y/10Y CURVE PHYS
        Example (leg): USD-SOFR-COMPOUND 1D Constant Spot 5Y Outright PHYS
        """
        # Build trade_id -> index lookup for MAC coupon resolution
        tid_to_idx: dict[str, int] = {}
        if "trade_id" in df.columns:
            for idx, tid in df["trade_id"].items():
                tid_to_idx[str(tid)] = idx

        def _label_for_row(row: pd.Series, *, leg_scope: bool = False) -> str:
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

            trade_type = str(row.get("trade_type", "OUTRIGHT")).upper()

            # Render a CURVE/FLY leg as a single-leg outright when leg_scope=True
            # so the expanded sub-table shows "5Y Outright" / "10Y Outright".
            leg_as_outright = leg_scope and trade_type in ("CURVE", "FLY")

            # 3+4. Forward + Tenor (FOMC-dated swaps get special handling)
            fomc_label = str(row.get("fomc_meeting_label", "")).strip()
            if fomc_label and fomc_label.lower() not in ("", "nan", "none"):
                # FOMC-dated swap: "FOMC APR26" replaces forward + tenor for outrights.
                parts.append(f"FOMC {fomc_label.upper()}")
                # For CURVE/FLY packages, still append the leg tenor pair
                # (e.g. "5Y/30Y") — the FOMC anchor describes the shared start
                # but the package's tenor structure is what identifies the trade.
                # In leg scope we fall through to the single-leg tenor below.
                if trade_type in ("CURVE", "FLY") and not leg_as_outright:
                    pkg_tenors = str(row.get("package_tenors", "")).strip()
                    if pkg_tenors and pkg_tenors.lower() not in ("nan", "none"):
                        parts.append(pkg_tenors)
                elif leg_as_outright:
                    leg_tenor = str(
                        row.get("tenor_display", row.get("tenor_label", ""))
                    ).strip()
                    if leg_tenor and leg_tenor.lower() not in ("nan", "none"):
                        parts.append(leg_tenor)
                elif row.get("fomc_label_append_tenor", False):
                    # Tier 3b — FOMC eff + constant-maturity tenor. Append
                    # the tenor so tape_label reads "FOMC APR26 10Y".
                    tenor_display = str(
                        row.get("tenor_display", row.get("tenor_label", ""))
                    ).strip()
                    if (
                        tenor_display
                        and tenor_display.lower() not in ("nan", "none")
                        and not tenor_display.startswith("IMM_")
                        and not tenor_display.startswith("FOMC_")
                    ):
                        parts.append(tenor_display)
            else:
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

                # 4. Tenors — leg scope uses the leg's own tenor; package scope
                # uses the combined package_tenors (e.g. "5Y/10Y").
                if leg_as_outright:
                    tenors = str(row.get("tenor_display", row.get("tenor_label", "")))
                else:
                    tenors = str(
                        row.get(
                            "package_tenors",
                            row.get("tenor_display", row.get("tenor_label", "")),
                        )
                    )
                if tenors and tenors.lower() not in ("nan", "none"):
                    parts.append(tenors)

            # 5. Structure
            if leg_as_outright:
                parts.append("Outright")
            elif trade_type in ("CURVE", "FLY"):
                parts.append(trade_type)
            elif trade_type == "SPREADOVER":
                parts.append("Spreadover")
            else:
                # Trade is a package leg per SDR reporting (Package indicator=True)
                # but no peer leg was paired by our detectors (curve/fly/MMS). Labelling
                # this as "Outright" misrepresents the execution structure — prefer
                # "Package" so downstream consumers can see it was part of a bundle.
                pkg_ind = row.get("package_indicator")
                is_sdr_package = (pkg_ind is True) or (
                    str(pkg_ind).strip().lower() in ("true", "1")
                )
                parts.append("Package" if is_sdr_package else "Outright")

            # 6. Flags
            flags: list[str] = []
            # Invoice swap ticker (TVA, TYB, UBI, …) — when present, surface
            # the CME product code inline so the desk doesn't need the side
            # panel. Takes precedence over generic MMS tagging.
            invoice_ticker = row.get("invoice_swap_ticker")
            if invoice_ticker is not None:
                invoice_ticker_str = str(invoice_ticker).strip().upper()
                if invoice_ticker_str and invoice_ticker_str.lower() not in ("nan", "none"):
                    flags.append(invoice_ticker_str)
            # Matched-maturity swap (CTD-aligned coupon / maturity, no invoice
            # ticker resolved) — surface as "MMS" so it's filterable in the tape.
            elif str(row.get("special_tenor_type", "")).upper() == "MATCHED_MATURITY":
                flags.append("MMS")
            if row.get("is_unwind", False):
                flags.append("UNWIND")
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
            # Cross-day lifecycle flags
            xd_status = str(row.get("xd_status", "")).upper()
            if xd_status == "TERMINATED" and ltype != "TERMINATION":
                flags.append("XD-TERM")
            if row.get("xd_has_partial_unwind", False):
                flags.append("PARTIAL-UNWIND")
            # Event type flags
            if row.get("is_novation_born", False):
                flags.append("NOVA-IN")
            if row.get("is_novation_terminated", False):
                flags.append("NOVA-OUT")
            if row.get("is_exercise_born", False):
                flags.append("EXER")
            if row.get("is_clearing_termination", False):
                flags.append("CLRG")
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
        df["leg_tape_label"] = df.apply(
            lambda r: _label_for_row(r, leg_scope=True), axis=1
        )
        # Clean double spaces
        df["tape_label"] = df["tape_label"].str.replace(r"\s+", " ", regex=True).str.strip()
        df["leg_tape_label"] = (
            df["leg_tape_label"].str.replace(r"\s+", " ", regex=True).str.strip()
        )

        return df

    # -- public interface --------------------------------------------------

    def compute(
        self,
        use_cache: bool = True,
        cache_dir: str | None = None,
    ) -> pd.DataFrame:
        """Run all enrichment layers and return the fully enriched tape.

        Args:
            use_cache: When True, check pickle cache before running the
                pipeline and persist output to cache on success.  False
                forces a full recompute and skips writing.
            cache_dir: Override the default cache directory
                (``notebooks/sdr/_cache/trade_tape``).  Mostly for tests.
        """
        from tqdm.auto import tqdm

        if self._result is not None:
            return self._result

        df = self._df.copy()
        if df.empty:
            self._result = df
            return df

        if use_cache:
            cached = self._try_load_cache(cache_dir)
            if cached is not None:
                self._result = cached
                return cached

        steps = [
            ("Prerequisites", self._ensure_prerequisites),
            ("Classification", self._enrich_classification),
            ("UPI reference", self._enrich_upi_reference),
            ("Off-date detection", self._detect_off_date),
            ("Lifecycle", self._enrich_lifecycle),
            ("Cross-day lifecycle", self._enrich_cross_day_lifecycle),
            ("Event type", self._enrich_event_type),
            ("Quality flags", self._enrich_quality),
            ("Packages", self._enrich_packages),
            ("Market context", self._enrich_context),
            ("Clustering", self._enrich_rv),
            ("Tape labels", self._build_enriched_label),
        ]

        pbar = tqdm(steps, desc="TradeTape", unit="layer")
        for name, fn in pbar:
            pbar.set_postfix_str(name)
            df = fn(df)
        pbar.close()

        self._result = df
        if use_cache and not df.empty:
            self._save_cache(df, cache_dir)
        return df

    @classmethod
    def clear_cache(cls, cache_dir: str | None = None) -> int:
        """Delete all cached tape files. Returns count of files removed."""
        directory = cache_dir or DEFAULT_CACHE_DIR
        if not os.path.isdir(directory):
            return 0
        n = 0
        for fn in os.listdir(directory):
            if fn.endswith(".pkl"):
                try:
                    os.remove(os.path.join(directory, fn))
                    n += 1
                except OSError:
                    pass
        return n

    def summary(self) -> Dict[str, Any]:
        """Key stats for the enriched tape."""
        if self._result is None:
            self.compute()
        df = self._result
        n = len(df)
        n_new = int(df["is_new_risk"].sum()) if "is_new_risk" in df.columns else 0
        n_comp = int(df["is_compression"].sum()) if "is_compression" in df.columns else 0
        n_xd_term = int(df["xd_is_terminated"].sum()) if "xd_is_terminated" in df.columns else 0
        n_xd_partial = int(df["xd_has_partial_unwind"].sum()) if "xd_has_partial_unwind" in df.columns else 0
        n_nova = int(df["is_novation"].sum()) if "is_novation" in df.columns else 0
        n_comp_spec = int(df["is_compression_spec"].sum()) if "is_compression_spec" in df.columns else 0
        n_exer = int(df["is_exercise_born"].sum()) if "is_exercise_born" in df.columns else 0
        n_clrg = int(df["is_clearing_termination"].sum()) if "is_clearing_termination" in df.columns else 0
        n_nst = int(df["is_non_standard_term"].sum()) if "is_non_standard_term" in df.columns else 0

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
            "n_xd_terminated": n_xd_term,
            "n_xd_partial_unwind": n_xd_partial,
            "n_novations": n_nova,
            "n_compressions_spec": n_comp_spec,
            "n_exercise_born": n_exer,
            "n_clearing_terminations": n_clrg,
            "n_non_standard_term": n_nst,
        }

    def clean_tape(self) -> pd.DataFrame:
        """Tape filtered to new-risk only, no UFRO/compression/unwind.

        Returns the 'real' organic flow: NEWT trades, excluding
        off-market-coupon (UFRO) and lifecycle events.
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
        if "is_unwind" in df.columns:
            mask &= ~df["is_unwind"]
        if "xd_is_terminated" in df.columns:
            mask &= ~df["xd_is_terminated"].fillna(False).astype(bool)
        if "is_novation_terminated" in df.columns:
            mask &= ~df["is_novation_terminated"].fillna(False).astype(bool)
        if "is_clearing_termination" in df.columns:
            mask &= ~df["is_clearing_termination"].fillna(False).astype(bool)

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
