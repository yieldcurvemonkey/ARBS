"""USD swap tape v2 ingestion.

Runs TradeTape.compute() against the output of the classification
pipeline and persists enriched per-trade + per-package rows to the
``arbs_usd_swap_tape_*`` tables for the Next.js dashboard.

The legacy ``ingest_usdswaps.py`` pipeline is left untouched; this
script is additive and sits in front of the new dashboard route tree.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import re
import time
from datetime import datetime, timezone
from typing import Any, Iterable, Optional

import numpy as np
import pandas as pd
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from tqdm.auto import tqdm

from SDRUtils.analytics.trade_tape import TradeTape

from ._tape_monitoring_v2 import MONITORING_SQL_V2
from ._tape_schema import TAPE_SCHEMA_SQL  # v1 DDL for back-compat migration
from ._tape_schema_v2 import (
    DISPLAY_VIEW_V2,
    LEGS_TABLE_V2 as LEGS_TABLE,
    MANUAL_LINKS_TABLE,
    PACKAGES_TABLE_V2 as PACKAGES_TABLE,
    RUNS_TABLE_V2 as RUNS_TABLE,
    SIGNAL_REALTIME_DDL,
    SIGNAL_TABLE_DDL,
    SIGNAL_TABLE_V2,
    TAPE_SCHEMA_SQL_V2,
)
from .ingest_usdswaps import get_db_connection_string as _legacy_conn_string


# ---------------------------------------------------------------------------
# Column plumbing: keep in sync with ``_tape_schema.py``
# ---------------------------------------------------------------------------

LEG_COLUMNS: tuple[str, ...] = (
    "trade_id",
    "package_id",
    "leg_order",
    "as_of_date",
    "execution_timestamp",
    "original_execution_timestamp",
    "clearing_accepted_timestamp",
    "execution_session",
    "execution_hour_et",
    "tenor_years",
    "tenor_label",
    "tenor_display",
    "forward_start_years",
    "forward_label",
    "forward_bucket",
    "effective_date",
    "expiration_date",
    "notional",
    "notional_currency",
    "notional_source",
    "is_notional_capped",
    "risk",
    "fixed_rate",
    "other_payment_amount",
    "other_payment_currency",
    "trade_type",
    "rate_index_clean",
    "venue",
    "ccp",
    "platform_identifier",
    "cleared",
    "tape_label",
    "leg_tape_label",
    "upi_reset_freq",
    "upi_notional_schedule",
    "upi_delivery_type",
    # Phase 4 canonical underlier key — collapses SDR-feed display
    # variations of the same economic underlier (e.g.
    # 'USD-SOFR-COMPOUND' vs 'USD-SOFR-OIS' vs 'USD-SOFR') into a
    # single comparable key. Read by the dashboard's rarity / extremes
    # / package-analytics queries (groupBy=canonical).
    "canonical_underlier_key",
    "is_new_risk",
    "is_unwind",
    "is_compression",
    "is_compression_spec",
    "is_reset_optimization",
    "is_novation",
    "is_novation_born",
    "is_novation_terminated",
    "is_exercise_born",
    "is_clearing_termination",
    "lifecycle_type",
    "lc_n_events",
    "lc_n_events_economic",
    "lc_n_valuation_events",
    "lc_status",
    "lc_was_amended",
    "lc_was_null_filled",
    "lc_was_scheduled_amortization",
    "lc_has_economics_change",
    "state_machine_violation",
    "violation_reason",
    "economic_class",
    "contributes_to_flow",
    "contributes_to_volume",
    "contributes_to_pnl",
    "contributes_to_pnl_as_delta",
    "on_p43",
    "economic_class_reason",
    "is_ufro",
    "is_off_market",
    "is_capped",
    "is_block",
    "is_off_date",
    "is_mac",
    "is_spreadover",
    "is_asset_swap",
    "is_non_standard_term",
    "quality_flags",
    "is_fomc_dated",
    "fomc_meeting_label",
    "fomc_proximity",
    "is_month_end",
    "is_quarter_end",
    "cluster_id",
    "cluster_size",
    "is_multi_meeting_cluster",
    "xd_status",
    "xd_n_events",
    "xd_notional_pct_remaining",
    "xd_is_terminated",
    "xd_has_partial_unwind",
    # Phase 5 structural
    "schedule_truncated",
    "schedule_row_count",
    "schedule_notional_series",
    "missing_required_fields",
    "cap_band_violation",
    "rc_timeline_json",
    "other_payment_ufro",
    "other_payment_uwin",
    "other_payment_pexh",
    "frequency_anomaly",
    "d2_missing",
    "manual_link_id",
    # Per-leg broker spread / price — populated from the raw SDR
    # ``Package transaction spread`` / ``Package transaction price``
    # fields. For composite CURVE / FLY packages the two legs' spreads
    # may differ; the front-end needs per-leg values to render them.
    "package_transaction_spread",
    "package_transaction_price",
    "package_transaction_price_currency",
    # Phase 7: frontend-to-backend logic port
    "off_market_reason",
    "normalized_tape_label",
    "tape_tags",
    "enrichment_metrics",
    # Basis swap fields — populated by classify_basis_swap_trade
    "basis_type",
    "basis_spread_bps",
    "leg1_rate_index",
    "leg2_rate_index",
    # PTP/OPA per-leg columns — package-detection enhancement
    "ptp_group_id",
    "opa_sign",
    "opa_signed_amount",
    # Matched-UST-maturity / special-tenor enrichment
    "matched_ust_maturity",
    "special_tenor_type",
    "ust_cusip",
    "tape_label_ust_alias",
    "leg_tape_label_ust_alias",
    "matched_ust_maturity_trade_confidence",
)


PACKAGE_COLUMNS: tuple[str, ...] = (
    "package_id",
    "manual_link_id",
    "as_of_date",
    "execution_start",
    "execution_end",
    "original_execution_start",
    "clearing_accepted_start",
    "package_structure",
    "package_type",
    "package_indicator",
    "package_tenors",
    "n_package_legs",
    "legs_count",
    "total_notional",
    "gross_notional",
    "total_risk",
    "gross_risk",
    "weighted_fixed_rate",
    "min_fixed_rate",
    "max_fixed_rate",
    "has_spread",
    "package_transaction_spread",
    "package_transaction_price",
    "package_transaction_price_currency",
    "rate_index_clean",
    "venue",
    "ccp",
    "execution_session",
    "is_new_risk",
    "is_unwind",
    "is_compression_any",
    "is_ufro_any",
    "is_block_any",
    "is_capped_any",
    "is_off_date_any",
    "is_termination_any",
    "is_novation_any",
    "is_reset_optimization_any",
    "is_clearing_termination_any",
    "is_correction_any",
    "lifecycle_mix",
    "economic_class_primary",
    "contributes_to_flow_any",
    "contributes_to_volume_any",
    "contributes_to_pnl_any",
    "on_p43_any",
    "state_machine_violation_any",
    "is_fomc_dated",
    "fomc_meeting_label",
    "cluster_id",
    "cluster_size",
    "tape_label",
    # Phase 7: frontend-to-backend logic port
    "is_off_market_any",
    "confidence_score",
    "confidence_total",
    "confidence_tone",
    "confidence_signals",
    "summary_rate",
    "summary_risk",
    "summary_opa",
    "is_ccp_switch",
    "ccp_switch_from",
    "ccp_switch_to",
    "package_adjusted_dv01",
    "normalized_tape_label",
    "tape_tags",
    # PTP/OPA package-level columns — package-detection enhancement
    "ptp_group_id",
    "ptp_group_size",
    "ptp_price_notation",
    "opa_signed_net",
    "opa_ptp_residual",
    "opa_sign_confidence",
    "opa_constrained_net",
    "opa_constrained_residual",
    "dealer_spread_est",
    "dealer_spread_bps",
    "ptp_sub_structures",
    "package_metrics",
    # Matched-UST-maturity / special-tenor enrichment (package)
    "special_tenor_type",
    "tape_label_ust_alias",
    "is_matched_maturity_all",
)


JSON_LEG_COLS = {"enrichment_metrics"}
JSON_PKG_COLS = {"lifecycle_mix", "package_metrics", "confidence_signals", "ptp_sub_structures"}


# ---------------------------------------------------------------------------
# Value normalization helpers (ported from ingest_usdswaps.py)
# ---------------------------------------------------------------------------


def _to_db_value(val: Any) -> Any:
    """Normalize pandas/numpy sentinels to DB-safe python scalars."""
    if val is None:
        return None
    if isinstance(val, (pd.Timestamp,)):
        if pd.isna(val):
            return None
        return val.to_pydatetime()
    if isinstance(val, (pd.Timedelta,)):
        if pd.isna(val):
            return None
        return val.to_pytimedelta()
    if isinstance(val, np.ndarray):
        if val.size == 0:
            return None
        return [_to_db_value(v) for v in val.tolist()]
    if isinstance(val, (list, tuple)):
        return [_to_db_value(v) for v in val]
    if isinstance(val, (pd.Series,)):
        return [_to_db_value(v) for v in val.tolist()]
    if hasattr(val, "item"):
        try:
            val = val.item()
        except Exception:
            pass
    if isinstance(val, float) and math.isnan(val):
        return None
    try:
        if pd.isna(val):
            return None
    except Exception:
        pass
    if isinstance(val, str) and val.strip() == "NaT":
        return None
    return val


def _to_jsonable(val: Any) -> Any:
    if val is None:
        return None
    if isinstance(val, (pd.Timestamp,)):
        if pd.isna(val):
            return None
        return val.isoformat()
    if isinstance(val, np.ndarray):
        if val.size == 0:
            return None
        return [_to_jsonable(v) for v in val.tolist()]
    if isinstance(val, (list, tuple, set)):
        return [_to_jsonable(v) for v in val]
    if isinstance(val, dict):
        return {k: _to_jsonable(v) for k, v in val.items()}
    if hasattr(val, "item"):
        try:
            val = val.item()
        except Exception:
            pass
    if isinstance(val, float) and math.isnan(val):
        return None
    try:
        if pd.isna(val):
            return None
    except Exception:
        pass
    return val


def _bool_or_none(val: Any) -> Optional[bool]:
    val = _to_db_value(val)
    if val is None:
        return None
    if isinstance(val, bool):
        return val
    if isinstance(val, (int, np.integer)):
        return bool(val)
    if isinstance(val, (float, np.floating)):
        if math.isnan(float(val)):
            return None
        return bool(val)
    if isinstance(val, str):
        normalized = val.strip().lower()
        if normalized in {"", "nan", "none", "null", "nat"}:
            return None
        if normalized in {"true", "t", "1", "yes", "y"}:
            return True
        if normalized in {"false", "f", "0", "no", "n"}:
            return False
    return bool(val)


def _num_or_none(val: Any) -> Optional[float]:
    val = _to_db_value(val)
    if val is None:
        return None
    try:
        f = float(val)
    except (TypeError, ValueError):
        return None
    if math.isnan(f):
        return None
    return f


def _int_or_none(val: Any) -> Optional[int]:
    n = _num_or_none(val)
    if n is None:
        return None
    return int(n)


def _str_or_none(val: Any) -> Optional[str]:
    val = _to_db_value(val)
    if val is None:
        return None
    s = str(val).strip()
    return s if s else None


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------


def _is_blank_sql(sql: str) -> bool:
    """True if the chunk has no executable SQL — only blank lines and ``--`` line
    comments. Such a chunk arises when a comment line itself ends in ``;`` (the
    v2 schema has one), and psycopg2 rejects it with 'can't execute an empty
    query', so it must be skipped rather than sent to the server."""
    for line in sql.splitlines():
        s = line.strip()
        if s and not s.startswith("--"):
            return False
    return True


def _split_ddl_statements(ddl: str) -> list[str]:
    """Split a DDL bundle into individual executable statements on
    ``;``-terminated lines (mirrors the original line-buffered splitter), dropping
    comment-only chunks."""
    stmts: list[str] = []
    buffer: list[str] = []
    for line in ddl.splitlines():
        buffer.append(line)
        if line.strip().endswith(";"):
            sql = "\n".join(buffer).strip()
            if sql and not _is_blank_sql(sql):
                stmts.append(sql)
            buffer = []
    tail = "\n".join(buffer).strip()
    if tail and not _is_blank_sql(tail):
        stmts.append(tail)
    return stmts


def _is_view_statement(sql: str) -> bool:
    head = sql.lstrip().upper()
    return (
        head.startswith("DROP VIEW")
        or head.startswith("CREATE VIEW")
        or head.startswith("CREATE OR REPLACE VIEW")
        or head.startswith("DROP MATERIALIZED VIEW")
        or head.startswith("CREATE MATERIALIZED VIEW")
    )


def _group_ddl_statements(stmts: list[str]) -> list[list[str]]:
    """Group consecutive view DROP/CREATE statements so a view rebuild runs in a
    single transaction — there must be no window where the view is dropped but
    not yet recreated (the frontend reads it). Every other statement runs on its
    own so each holds ACCESS EXCLUSIVE for the shortest possible time."""
    groups: list[list[str]] = []
    i, n = 0, len(stmts)
    while i < n:
        if _is_view_statement(stmts[i]):
            grp: list[str] = []
            while i < n and _is_view_statement(stmts[i]):
                grp.append(stmts[i])
                i += 1
            groups.append(grp)
        else:
            groups.append([stmts[i]])
            i += 1
    return groups


def _execute_ddl_bundle(
    engine: Engine, ddl: str, lock_timeout_ms: int = 5_000, _max_attempts: int = 10
) -> None:
    """Apply a DDL bundle statement-by-statement, each in its own short
    transaction with a bounded ``lock_timeout`` and retry-with-backoff.

    The tape tables are served by long-running (~50s) frontend analytical
    queries holding ``AccessShareLock``. Running the whole bundle in one
    transaction forced a single window in which every ``ACCESS EXCLUSIVE`` lock
    (tables + view) had to be free simultaneously, which deadlocked under live
    traffic. Executing each statement independently keeps every lock window tiny
    (fail fast on lock_timeout, then retry into a gap), while a view DROP/CREATE
    stays atomic within its group so the view is never observably missing."""
    for group in _group_ddl_statements(_split_ddl_statements(ddl)):
        for attempt in range(1, _max_attempts + 1):
            try:
                with engine.begin() as conn:
                    conn.execute(text(f"SET LOCAL lock_timeout = '{lock_timeout_ms}ms'"))
                    for sql in group:
                        conn.execute(text(sql))
                break
            except Exception as exc:
                msg = str(exc).lower()
                if ("deadlock" in msg or "lock timeout" in msg) and attempt < _max_attempts:
                    wait = min(1.5 ** attempt, 15.0)
                    print(
                        f"_execute_ddl_bundle: lock contention (attempt "
                        f"{attempt}/{_max_attempts}), retrying in {wait:.1f}s…"
                    )
                    time.sleep(wait)
                else:
                    raise


_schema_ensured: set[str] = set()

_LATEST_MIGRATION_COLS = [
    ("arbs_usd_swap_tape_packages_v2", "ptp_price_notation"),
    ("arbs_usd_swap_tape_legs_v2", "opa_signed_amount"),
    ("arbs_usd_swap_tape_overrides_v2", "override_id"),
    ("arbs_usd_swap_tape_display_v2", "override_map"),
    # Matched-maturity (MMS) migration markers — without these, ensure_schema's
    # _schema_already_current() short-circuit would skip the MMS ADD COLUMNs once
    # the #333 markers exist, leaving the MMS columns unmigrated.
    ("arbs_usd_swap_tape_packages_v2", "is_matched_maturity_all"),
    ("arbs_usd_swap_tape_legs_v2", "matched_ust_maturity"),
]


def _schema_already_current(engine: Engine) -> bool:
    """Check if the latest migration columns exist, avoiding ACCESS EXCLUSIVE DDL."""
    try:
        with engine.connect() as conn:
            for table, col in _LATEST_MIGRATION_COLS:
                row = conn.execute(text(
                    "SELECT 1 FROM information_schema.columns "
                    "WHERE table_name = :t AND column_name = :c"
                ), {"t": table, "c": col}).fetchone()
                if row is None:
                    return False
        return True
    except Exception:
        return False


def ensure_schema(engine: Engine, _max_retries: int = 5) -> None:
    """Create v2 tables / indexes / view if they don't already exist.

    Also runs the v1 DDL so the frozen rollback tables remain valid on
    fresh environments (§4.11). Writes after Phase 4 cutover target v2
    only; v1 is preserved for instant rollback via the dashboard's
    TAPE_DISPLAY_VIEW constant.

    Guarded per-engine-URL so DDL (which takes AccessExclusiveLock on
    views) runs at most once per process, avoiding deadlocks during
    multi-date backfills. Before attempting DDL, checks
    information_schema for the latest migration columns — if they exist,
    the schema is already current and we skip DDL entirely, avoiding
    ACCESS EXCLUSIVE lock contention with concurrent frontend readers.
    Retries on deadlock/lock-timeout up to ``_max_retries`` times with
    exponential backoff.
    """
    key = str(engine.url)
    if key in _schema_ensured:
        return
    if _schema_already_current(engine):
        _schema_ensured.add(key)
        return
    for attempt in range(1, _max_retries + 1):
        try:
            _execute_ddl_bundle(engine, TAPE_SCHEMA_SQL)
            _execute_ddl_bundle(engine, TAPE_SCHEMA_SQL_V2)
            _execute_ddl_bundle(engine, MONITORING_SQL_V2)
            _schema_ensured.add(key)
            return
        except Exception as exc:
            msg = str(exc).lower()
            if ("deadlock" in msg or "lock timeout" in msg) and attempt < _max_retries:
                wait = 3 ** attempt
                print(f"ensure_schema: deadlock on attempt {attempt}/{_max_retries}, retrying in {wait}s…")
                time.sleep(wait)
            else:
                raise


# ---------------------------------------------------------------------------
# DataFrame shaping
# ---------------------------------------------------------------------------


def _normalize_package_id(df: pd.DataFrame) -> pd.DataFrame:
    """Synthesize 'OUTRIGHT-{trade_id}' for any row missing a package_id.

    Mirrors the normalization in ``ingest_usdswaps.normalize_dataframe`` so
    that the FK from legs → packages never sees NULL. Trades classified as
    outrights by the upstream pipeline arrive with ``package_id`` None.
    """
    df = df.copy()
    if "package_id" not in df.columns:
        df["package_id"] = None
    mask = df["package_id"].isna() | (df["package_id"].astype(str).str.len() == 0)
    if mask.any():
        df.loc[mask, "package_id"] = df.loc[mask, "trade_id"].astype(str).map(
            lambda tid: f"OUTRIGHT-{tid}"
        )
        if "package_type" in df.columns:
            df.loc[mask & df["package_type"].isna(), "package_type"] = "OUTRIGHT"
        else:
            df["package_type"] = df.apply(
                lambda r: "OUTRIGHT" if r.name in df.index[mask] else r.get("package_type"),
                axis=1,
            )
    df["package_id"] = df["package_id"].astype(str)
    return df


def _gap_aware_sort_key(group: pd.DataFrame) -> list[str]:
    """Choose sort columns: tenor_years for normal packages, forward_start_years
    for gap structures (all legs within ~0.05y of each other in tenor)."""
    tenor_y = pd.to_numeric(
        group.get("tenor_years", pd.Series(index=group.index, dtype="float64")),
        errors="coerce",
    )
    if tenor_y.notna().any() and (tenor_y.max() - tenor_y.min()) > 0.05:
        return ["tenor_years", "trade_id"]
    fwd_y = pd.to_numeric(
        group.get("forward_start_years", pd.Series(index=group.index, dtype="float64")),
        errors="coerce",
    )
    if fwd_y.notna().any() and (fwd_y.max() - fwd_y.min()) > 0.05:
        return ["forward_start_years", "trade_id"]
    return ["execution_timestamp", "trade_id"]


def _leg_order_series(df: pd.DataFrame) -> pd.Series:
    """Assign stable 0-based leg_order within each package.

    Normal packages sort by tenor (5Y < 10Y < 30Y). Gap structures (same tail
    tenor, different forwards) sort by forward_start_years so M2027 < M2028 < M2029.
    """
    out = pd.Series(0, index=df.index, dtype="int64")
    for _, group in df.groupby("package_id", sort=False):
        sort_cols = _gap_aware_sort_key(group)
        ordered = group.sort_values(sort_cols).index
        for rank, idx in enumerate(ordered):
            out.at[idx] = rank
    return out


def _hour_et_series(ts: pd.Series) -> pd.Series:
    try:
        hours = pd.to_datetime(ts, errors="coerce", utc=True).dt.tz_convert("America/New_York").dt.hour
    except Exception:
        hours = pd.to_datetime(ts, errors="coerce", utc=True).dt.hour
    return hours.astype("Int64")


def _quality_flag_list(row: pd.Series) -> list[str]:
    flags: list[str] = []
    for col, flag in [
        ("is_ufro", "UFRO"),
        ("is_off_market", "OFF_MKT"),
        ("is_capped", "CAPPED"),
        ("is_block", "BLK"),
        ("is_off_date", "OFF_DATE"),
        ("is_non_standard_term", "NSTD"),
    ]:
        if bool(row.get(col, False)):
            flags.append(flag)
    return flags


def _package_structure_label(group: pd.DataFrame) -> str:
    """Produce a compact structure label like '2Y/5Y Curve' from legs."""
    tenors = [
        _str_or_none(t) for t in group.get("tenor_display", group.get("tenor_label"))
    ]
    tenors = [t for t in tenors if t]
    pkg_type = (
        _str_or_none(group["package_type"].iloc[0])
        if "package_type" in group.columns and not group.empty
        else "OUTRIGHT"
    ) or "OUTRIGHT"
    if not tenors:
        return pkg_type
    return f"{'/'.join(tenors)} {pkg_type.title()}"


def _package_tenors_str(group: pd.DataFrame) -> str:
    tenors = [
        _str_or_none(t) for t in group.get("tenor_display", group.get("tenor_label"))
    ]
    return ",".join([t for t in tenors if t])


def _rep_tape_label(group: pd.DataFrame) -> str | None:
    labels = group.get("tape_label")
    if labels is None:
        return None
    non_null = [l for l in (_str_or_none(x) for x in labels) if l]
    if not non_null:
        return None
    # Longest label tends to be the most descriptive
    return max(non_null, key=len)


def _rep_tape_label_ust_alias(group: pd.DataFrame) -> str | None:
    labels = group.get("tape_label_ust_alias")
    if labels is None:
        return None
    non_null = [l for l in (_str_or_none(x) for x in labels) if l]
    if not non_null:
        return None
    return max(non_null, key=len)


def _consistent_str(group: pd.DataFrame, col: str) -> str | None:
    if col not in group.columns:
        return None
    vals = [v for v in (_str_or_none(x) for x in group[col]) if v]
    if not vals:
        return None
    if all(v == vals[0] for v in vals):
        return vals[0]
    return None


def _consistent_num(group: pd.DataFrame, col: str) -> float | None:
    """Pick the single numeric value per group; fall back to first on disagreement."""
    if col not in group.columns:
        return None
    vals = pd.to_numeric(
        group[col].astype(str).str.replace(",", ""),
        errors="coerce",
    ).dropna().unique().tolist()
    if not vals:
        return None
    return float(vals[0])


_DISPLAY_OUTRIGHT_TYPES = {"", "OUTRIGHT", "NAN", "NONE"}


def _force_outright_label(label: Any) -> str | None:
    text = _str_or_none(label)
    if not text:
        return text
    return re.sub(r"\bPackage\b", "Outright", text, flags=re.IGNORECASE)


def _normalize_false_positive_package_labels(tape: pd.DataFrame) -> pd.DataFrame:
    """Rewrite raw-SDR package-flagged single legs back to display outrights.

    Some single-leg trades arrive with ``package_indicator=True`` even though
    the dashboard receives them as standalone legs rather than as a linked
    multi-leg structure. Keep the raw indicator for auditability, but normalize
    the display label from ``Package`` to ``Outright`` so the tape matches what
    traders actually see.
    """
    if tape.empty or "package_indicator" not in tape.columns:
        return tape.copy()

    df = tape.copy()
    package_indicator = df["package_indicator"].map(_bool_or_none).eq(True)
    trade_type = (
        df.get("trade_type", pd.Series("", index=df.index))
        .astype(str)
        .str.strip()
        .str.upper()
    )
    package_type = (
        df.get("package_type", pd.Series("", index=df.index))
        .astype(str)
        .str.strip()
        .str.upper()
    )
    n_package_legs = pd.to_numeric(
        df.get("n_package_legs", pd.Series(1, index=df.index)),
        errors="coerce",
    )

    mask = (
        package_indicator
        & trade_type.isin(_DISPLAY_OUTRIGHT_TYPES)
        & package_type.isin(_DISPLAY_OUTRIGHT_TYPES)
        & (n_package_legs.fillna(1) <= 1)
    )
    if not mask.any():
        return df

    for col in ("tape_label", "leg_tape_label"):
        if col in df.columns:
            df.loc[mask, col] = df.loc[mask, col].map(_force_outright_label)

    return df


_LEG_INT_COLS: tuple[str, ...] = (
    "execution_hour_et",
    "lc_n_events",
    "xd_n_events",
    "cluster_size",
)
_LEG_NUM_COLS: tuple[str, ...] = (
    "tenor_years",
    "forward_start_years",
    "notional",
    "risk",
    "fixed_rate",
    "other_payment_amount",
    "package_transaction_spread",
    "package_transaction_price",
    "xd_notional_pct_remaining",
)
_LEG_BOOL_COLS: tuple[str, ...] = (
    "is_new_risk", "is_unwind", "is_compression", "is_compression_spec",
    "is_reset_optimization", "is_novation", "is_novation_born",
    "is_novation_terminated", "is_exercise_born", "is_clearing_termination",
    "is_ufro", "is_off_market", "is_capped", "is_block", "is_off_date",
    "is_mac", "is_spreadover", "is_asset_swap", "is_non_standard_term",
    "is_fomc_dated", "is_month_end", "is_quarter_end",
    "is_multi_meeting_cluster", "xd_is_terminated", "xd_has_partial_unwind",
)
_LEG_TEXT_COLS: tuple[str, ...] = (
    "trade_id", "package_id", "execution_session", "tenor_label",
    "tenor_display", "forward_label", "forward_bucket", "notional_currency",
    "other_payment_currency",
    "package_transaction_price_currency",
    "trade_type", "rate_index_clean", "venue", "ccp", "platform_identifier",
    "tape_label", "upi_reset_freq", "upi_notional_schedule",
    "upi_delivery_type", "lifecycle_type", "lc_status", "fomc_meeting_label",
    "fomc_proximity", "cluster_id", "xd_status",
    # Phase 4 canonical underlier key — text column on the v2 leg
    # table; computed by SDRUtils.core.underlier_canonical and
    # materialized by analytics.trade_tape.compute().
    "canonical_underlier_key",
    # Phase 7
    "off_market_reason",
    "normalized_tape_label",
    "tape_tags",
)
_LEG_TS_COLS: tuple[str, ...] = (
    "execution_timestamp",
    "effective_date",
    "expiration_date",
)


def build_leg_rows(tape: pd.DataFrame, *, as_of_date: str) -> list[dict]:
    if tape.empty:
        return []
    df = _normalize_false_positive_package_labels(tape)
    if "leg_order" not in df.columns:
        df["leg_order"] = _leg_order_series(df)
    df["execution_hour_et"] = _hour_et_series(df["execution_timestamp"])
    if "execution_session" not in df.columns:
        df["execution_session"] = None
    if "tenor_display" not in df.columns:
        df["tenor_display"] = df.get("tenor_label")
    if "quality_flags" not in df.columns:
        df["quality_flags"] = df.apply(_quality_flag_list, axis=1)

    # Basis swap: rename spread_bps → basis_spread_bps for schema alignment;
    # coerce enum values to plain strings for DB storage.
    if "spread_bps" in df.columns and "basis_spread_bps" not in df.columns:
        df["basis_spread_bps"] = df["spread_bps"]
    if "basis_type" in df.columns:
        df["basis_type"] = df["basis_type"].apply(
            lambda v: v.value if hasattr(v, "value") else v
        )

    # OPA (feedback round 1): normalize from raw CFTC column names if the
    # classifier/TradeTape hasn't already produced snake_case equivalents.
    if "other_payment_amount" not in df.columns and "Other payment amount" in df.columns:
        df["other_payment_amount"] = pd.to_numeric(
            df["Other payment amount"].astype(str).str.replace(",", ""),
            errors="coerce",
        )
    if "other_payment_currency" not in df.columns and "Other payment currency" in df.columns:
        df["other_payment_currency"] = df["Other payment currency"].astype("string")

    # Extract a frame with exactly LEG_COLUMNS (missing filled with None) and
    # convert to records in one shot. to_dict(orient="records") is ~10x
    # cheaper than iterrows() on wide (60+ col) frames because it avoids
    # building a Series per row.
    extracted = pd.DataFrame({
        col: df[col] if col in df.columns else None
        for col in LEG_COLUMNS
    }, index=df.index)
    records: list[dict[str, Any]] = extracted.to_dict(orient="records")

    for rec in tqdm(
        records, desc="Building tape leg rows", unit="row", leave=False
    ):
        rec["as_of_date"] = as_of_date
        # Type coercions
        rec["leg_order"] = _int_or_none(rec.get("leg_order")) or 0
        rec["execution_hour_et"] = _int_or_none(rec.get("execution_hour_et"))
        rec["tenor_years"] = _num_or_none(rec.get("tenor_years"))
        rec["forward_start_years"] = _num_or_none(rec.get("forward_start_years"))
        rec["notional"] = _num_or_none(rec.get("notional"))
        rec["risk"] = _num_or_none(rec.get("risk"))
        rec["fixed_rate"] = _num_or_none(rec.get("fixed_rate"))
        rec["other_payment_amount"] = _num_or_none(rec.get("other_payment_amount"))
        # Per-leg package economics (composite SPREADOVER_CURVE etc.)
        rec["package_transaction_spread"] = _num_or_none(
            rec.get("package_transaction_spread")
        )
        rec["package_transaction_price"] = _num_or_none(
            rec.get("package_transaction_price")
        )
        rec["package_transaction_price_currency"] = _str_or_none(
            rec.get("package_transaction_price_currency")
        )
        rec["lc_n_events"] = _int_or_none(rec.get("lc_n_events"))
        rec["lc_n_events_economic"] = _int_or_none(rec.get("lc_n_events_economic"))
        rec["lc_n_valuation_events"] = _int_or_none(rec.get("lc_n_valuation_events"))
        rec["xd_n_events"] = _int_or_none(rec.get("xd_n_events"))
        rec["xd_notional_pct_remaining"] = _num_or_none(rec.get("xd_notional_pct_remaining"))
        rec["cluster_size"] = _int_or_none(rec.get("cluster_size"))
        for bool_col in (
            "is_new_risk", "is_unwind", "is_compression", "is_compression_spec",
            "is_reset_optimization", "is_novation", "is_novation_born",
            "is_novation_terminated", "is_exercise_born", "is_clearing_termination",
            "is_ufro", "is_off_market", "is_capped", "is_block", "is_off_date",
            "is_mac", "is_spreadover", "is_asset_swap", "is_non_standard_term",
            "is_fomc_dated", "is_month_end", "is_quarter_end",
            "is_multi_meeting_cluster", "xd_is_terminated", "xd_has_partial_unwind",
            # v2 additions
            "is_notional_capped",
            "lc_was_amended", "lc_was_null_filled",
            "lc_was_scheduled_amortization", "lc_has_economics_change",
            "state_machine_violation",
            "contributes_to_flow", "contributes_to_volume",
            "contributes_to_pnl", "contributes_to_pnl_as_delta", "on_p43",
            # Phase 5 bool columns
            "schedule_truncated", "cap_band_violation",
            "frequency_anomaly", "d2_missing",
            # matched-UST-maturity enrichment
            "matched_ust_maturity",
        ):
            rec[bool_col] = _bool_or_none(rec.get(bool_col))
        for text_col in (
            "trade_id", "package_id", "execution_session", "tenor_label",
            "tenor_display", "forward_label", "forward_bucket", "notional_currency",
            "notional_source",
            "other_payment_currency",
            "trade_type", "rate_index_clean", "venue", "ccp", "platform_identifier",
            "cleared",
            "tape_label", "leg_tape_label", "upi_reset_freq", "upi_notional_schedule",
            "upi_delivery_type", "lifecycle_type", "lc_status", "fomc_meeting_label",
            "fomc_proximity", "cluster_id", "xd_status",
            # v2 additions
            "violation_reason", "economic_class", "economic_class_reason",
            # Phase 7
            "off_market_reason", "normalized_tape_label", "tape_tags",
            # Basis swap fields
            "basis_type", "leg1_rate_index", "leg2_rate_index",
            # PTP/OPA
            "ptp_group_id",
            # matched-UST-maturity enrichment
            "special_tenor_type", "ust_cusip",
            "tape_label_ust_alias", "leg_tape_label_ust_alias",
            "matched_ust_maturity_trade_confidence",
        ):
            rec[text_col] = _str_or_none(rec.get(text_col))
        rec["basis_spread_bps"] = _num_or_none(rec.get("basis_spread_bps"))
        # PTP/OPA per-leg coercions
        rec["opa_sign"] = _int_or_none(rec.get("opa_sign"))
        rec["opa_signed_amount"] = _num_or_none(rec.get("opa_signed_amount"))
        rec["execution_timestamp"] = _to_db_value(rec.get("execution_timestamp"))
        rec["original_execution_timestamp"] = _to_db_value(
            rec.get("original_execution_timestamp")
        )
        rec["clearing_accepted_timestamp"] = _to_db_value(
            rec.get("clearing_accepted_timestamp")
        )
        rec["effective_date"] = _to_db_value(rec.get("effective_date"))
        rec["expiration_date"] = _to_db_value(rec.get("expiration_date"))
        # Phase 5 numeric / list / text normalization
        rec["schedule_row_count"] = _int_or_none(rec.get("schedule_row_count"))
        rec["other_payment_ufro"] = _num_or_none(rec.get("other_payment_ufro"))
        rec["other_payment_uwin"] = _num_or_none(rec.get("other_payment_uwin"))
        rec["other_payment_pexh"] = _num_or_none(rec.get("other_payment_pexh"))
        rec["rc_timeline_json"] = _str_or_none(rec.get("rc_timeline_json"))
        sched = rec.get("schedule_notional_series")
        if sched is None or (isinstance(sched, float) and math.isnan(sched)):
            rec["schedule_notional_series"] = None
        elif isinstance(sched, (list, tuple, np.ndarray)):
            rec["schedule_notional_series"] = [
                _num_or_none(v) for v in list(sched)
            ]
        mrf = rec.get("missing_required_fields")
        if mrf is None or (isinstance(mrf, float) and math.isnan(mrf)):
            rec["missing_required_fields"] = []
        elif isinstance(mrf, (list, tuple, np.ndarray)):
            rec["missing_required_fields"] = [str(v) for v in list(mrf) if v is not None]
        else:
            rec["missing_required_fields"] = [str(mrf)]
        flags = rec.get("quality_flags")
        if flags is None or (isinstance(flags, float) and math.isnan(flags)):
            flags = []
        if isinstance(flags, (list, tuple, np.ndarray)):
            rec["quality_flags"] = [str(f) for f in list(flags) if f is not None]
        elif isinstance(flags, str):
            rec["quality_flags"] = [flags]
        else:
            rec["quality_flags"] = []
        rec["enrichment_metrics"] = _to_jsonable(rec.get("enrichment_metrics")) or {}
    return records


def _structural_risk(
    risk: pd.Series,
    tenor_years: pd.Series,
    trade_type: str,
    forward_start_years: pd.Series | None = None,
) -> Optional[float]:
    """Street-convention package DV01 for the front-of-tape RISK cell.

    * CURVE — ``max(|leg_dv01|)`` (the larger-DV01 leg).
    * FLY — belly DV01 only (absolute value). Belly = middle leg after
      gap-aware sort (``tenor_years`` for normal flies, ``forward_start_years``
      for gap flies where all legs share the same tail tenor).
    * Anything else — signed sum.

    Returns None if no leg has a non-null risk.
    """
    if not risk.notna().any():
        return None
    tt = (trade_type or "").upper()
    if tt == "CURVE" or tt.endswith("_CURVE") or tt in ("INVOICE_SWITCH", "INVOICE_CALENDAR"):
        return _num_or_none(risk.abs().max(skipna=True))
    if tt == "FLY" or tt.endswith("_FLY"):
        valid_mask = risk.notna() & tenor_years.notna()
        if valid_mask.any():
            ty = tenor_years[valid_mask]
            # Gap fly: all same tail → sort by forward_start_years
            if (ty.max() - ty.min()) <= 0.05 and forward_start_years is not None:
                fwd = forward_start_years.reindex(ty.index)
                if fwd.notna().any():
                    ty = fwd[fwd.notna()]
            ordered = ty.sort_values(kind="stable")
            belly_idx = ordered.index[len(ordered) // 2]
            return _num_or_none(abs(risk.loc[belly_idx]))
        return _num_or_none(risk.abs().max(skipna=True))
    return _num_or_none(risk.sum(skipna=True))


# ---------------------------------------------------------------------------
# Phase 7: frontend-to-backend ported computations
# ---------------------------------------------------------------------------

_SUPPORTED_CCPS = {"LCH", "CME"}


def _compute_ccp_switch(g: pd.DataFrame) -> dict[str, Any]:
    """Detect CCP switch: 2-leg, opposite-sign, same tenor, different CCP."""
    result: dict[str, Any] = {
        "is_ccp_switch": False,
        "ccp_switch_from": None,
        "ccp_switch_to": None,
    }
    if len(g) != 2:
        return result
    ccp_vals = g.get("ccp", pd.Series(dtype="string"))
    if ccp_vals.isna().any():
        return result
    ccps = ccp_vals.astype(str).str.upper().str.strip().values
    if ccps[0] == ccps[1]:
        return result
    if ccps[0] not in _SUPPORTED_CCPS or ccps[1] not in _SUPPORTED_CCPS:
        return result
    tenor_y = pd.to_numeric(g.get("tenor_years"), errors="coerce")
    if tenor_y.isna().any():
        return result
    tv = tenor_y.values
    if abs(tv[0] - tv[1]) > 0.01:
        return result
    risk_vals = pd.to_numeric(g.get("risk"), errors="coerce")
    if risk_vals.isna().any():
        return result
    rv = risk_vals.values
    if (rv[0] > 0) == (rv[1] > 0):
        return result
    # Positive risk = closing position = "from" CCP
    from_idx = 0 if rv[0] > 0 else 1
    to_idx = 1 - from_idx
    result["is_ccp_switch"] = True
    result["ccp_switch_from"] = ccps[from_idx]
    result["ccp_switch_to"] = ccps[to_idx]
    return result


_SWAP_LEG_COUNT = {"OUTRIGHT": 1, "CURVE": 2, "FLY": 3}


def _base_type_of(package_type: str) -> str:
    """Extract base type from composite types (SPREADOVER_CURVE -> CURVE)."""
    pt = (package_type or "").upper()
    if pt.endswith("_FLY"):
        return "FLY"
    if pt.endswith("_CURVE"):
        return "CURVE"
    if pt in ("SPREADOVER", "MATCHED_MATURITY"):
        return "OUTRIGHT"
    return pt


def _is_composite_with_hedge(package_type: str) -> bool:
    pt = (package_type or "").upper()
    return (
        pt == "SPREADOVER" or pt == "MATCHED_MATURITY"
        or pt.startswith("SPREADOVER_") or pt.startswith("MATCHED_MATURITY_")
    )


def _compute_package_adjusted_dv01(
    risk: pd.Series, package_type: str, n_legs: int
) -> Optional[float]:
    """Clarus-convention package-adjusted DV01: sum|risk| / denominator."""
    abs_risks = risk.abs().dropna()
    if abs_risks.empty:
        return None
    total = float(abs_risks.sum())
    base = _base_type_of(package_type)
    if _is_composite_with_hedge(package_type):
        base_count = _SWAP_LEG_COUNT.get(base, 1)
        denom = max(base_count + 1, n_legs)
    elif base in _SWAP_LEG_COUNT:
        denom = _SWAP_LEG_COUNT[base]
    else:
        denom = max(1, n_legs)
    return _num_or_none(total / denom)


def _is_curvey(tt: str) -> bool:
    return tt == "CURVE" or tt.endswith("_CURVE")


def _is_flyey(tt: str) -> bool:
    return tt == "FLY" or tt.endswith("_FLY")


def _compute_leg_summary(
    g: pd.DataFrame, package_type: str, trade_type: str
) -> dict[str, Any]:
    """Desk-convention headline rate/risk/opa for the package."""
    result: dict[str, Any] = {
        "summary_rate": None,
        "summary_risk": None,
        "summary_opa": None,
    }
    tenor_y = pd.to_numeric(
        g.get("tenor_years", pd.Series(index=g.index, dtype="float64")),
        errors="coerce",
    )
    fixed = pd.to_numeric(
        g.get("fixed_rate", pd.Series(index=g.index, dtype="float64")),
        errors="coerce",
    )
    risk = pd.to_numeric(
        g.get("risk", pd.Series(index=g.index, dtype="float64")),
        errors="coerce",
    )
    opa = pd.to_numeric(
        g.get("other_payment_amount", pd.Series(index=g.index, dtype="float64")),
        errors="coerce",
    )

    kind = f"{package_type or ''} {trade_type or ''}".upper()
    _invoice_multi = {"INVOICE_SWITCH", "INVOICE_CALENDAR"}
    is_curve = bool(
        _is_curvey(package_type) or _is_curvey(trade_type)
        or package_type in _invoice_multi or trade_type in _invoice_multi
    )
    is_fly = bool(_is_flyey(package_type) or _is_flyey(trade_type))

    if not is_curve and not is_fly:
        if "CURVE" in kind:
            is_curve = True
        elif "FLY" in kind:
            is_fly = True

    # Gap-aware sort: tenor_years for normal packages, forward_start_years
    # for gap structures where all legs share the same tail tenor.
    fwd_y = pd.to_numeric(
        g.get("forward_start_years", pd.Series(index=g.index, dtype="float64")),
        errors="coerce",
    )
    valid = tenor_y.notna()
    if valid.any():
        ty_range = tenor_y[valid].max() - tenor_y[valid].min()
        if ty_range <= 0.05 and fwd_y.notna().any() and (fwd_y.max() - fwd_y.min()) > 0.05:
            sort_axis = fwd_y
        else:
            sort_axis = tenor_y
        order = sort_axis[sort_axis.notna()].sort_values(kind="stable").index
        idx_list = list(order) + [i for i in g.index if i not in order]
    else:
        idx_list = list(g.index)

    if is_curve and len(idx_list) >= 2:
        front, back = idx_list[0], idx_list[-1]
        fr, br = fixed.get(front), fixed.get(back)
        if pd.notna(fr) and pd.notna(br):
            result["summary_rate"] = _num_or_none(br - fr)
        result["summary_risk"] = _num_or_none(risk.get(back))
        fo, bo = opa.get(front), opa.get(back)
        if pd.notna(fo) and pd.notna(bo):
            result["summary_opa"] = _num_or_none(bo - fo)
    elif is_fly and len(idx_list) >= 3:
        front = idx_list[0]
        belly = idx_list[len(idx_list) // 2]
        back = idx_list[-1]
        fr, mr, br = fixed.get(front), fixed.get(belly), fixed.get(back)
        if pd.notna(fr) and pd.notna(mr) and pd.notna(br):
            result["summary_rate"] = _num_or_none(2 * mr - fr - br)
        result["summary_risk"] = _num_or_none(risk.get(belly))
        fo, mo, bo = opa.get(front), opa.get(belly), opa.get(back)
        if pd.notna(fo) and pd.notna(mo) and pd.notna(bo):
            result["summary_opa"] = _num_or_none(2 * mo - fo - bo)
    else:
        # OUTRIGHT or single-leg: pass-through first leg
        first = idx_list[0] if idx_list else None
        if first is not None:
            result["summary_rate"] = _num_or_none(fixed.get(first))
            result["summary_risk"] = _num_or_none(risk.get(first))
            result["summary_opa"] = _num_or_none(opa.get(first))
    return result


def _compute_confidence_columns(
    g: pd.DataFrame, package_type: str
) -> dict[str, Any]:
    """Compute package confidence score. Returns columns for the package row."""
    empty: dict[str, Any] = {
        "confidence_score": None,
        "confidence_total": None,
        "confidence_tone": None,
        "confidence_signals": None,
    }
    try:
        from SDRUtils.analytics.package_confidence import compute_confidence_for_group
        result = compute_confidence_for_group(g, package_type)
        return {
            "confidence_score": result.get("score"),
            "confidence_total": result.get("total"),
            "confidence_tone": result.get("tone"),
            "confidence_signals": result.get("signals"),
        }
    except (ImportError, Exception):
        return empty


def build_package_rows(tape: pd.DataFrame, *, as_of_date: str) -> list[dict]:
    """Aggregate the per-trade TradeTape output into one row per package_id."""
    if tape.empty:
        return []
    tape = _normalize_false_positive_package_labels(tape)
    rows: list[dict] = []
    lifecycle_keys = [
        ("NEW_RISK", "is_new_risk"),
        ("UNWIND", "is_unwind"),
        ("COMPRESSION", "is_compression"),
        ("TERMINATION", None),  # count via lifecycle_type
        ("NOVATION", "is_novation"),
        ("CORRECTION", None),
        ("CLEARING_TERM", "is_clearing_termination"),
        ("EXERCISE_BORN", "is_exercise_born"),
    ]
    groups = tape.groupby("package_id", sort=False)
    for package_id, group in tqdm(
        groups,
        total=groups.ngroups,
        desc="Aggregating tape packages",
        unit="pkg",
        leave=False,
    ):
        g = group.sort_values(["execution_timestamp", "trade_id"])
        notional = pd.to_numeric(g.get("notional", pd.Series(dtype=float)), errors="coerce")
        risk = pd.to_numeric(g.get("risk", pd.Series(dtype=float)), errors="coerce")
        tenor_years_series = pd.to_numeric(
            g.get("tenor_years", pd.Series(dtype=float)), errors="coerce"
        )
        fixed = pd.to_numeric(g.get("fixed_rate", pd.Series(dtype=float)), errors="coerce")
        abs_notional = notional.abs()

        execution_start = g["execution_timestamp"].min()
        execution_end = g["execution_timestamp"].max()

        weighted_fixed_rate = None
        denom = float(abs_notional.sum(skipna=True)) if abs_notional.notna().any() else 0.0
        if denom > 0:
            weighted_fixed_rate = float((abs_notional * fixed).sum(skipna=True) / denom)

        lifecycle_mix: dict[str, int] = {}
        for label, flag in lifecycle_keys:
            if flag and flag in g.columns:
                lifecycle_mix[label] = int(g[flag].fillna(False).astype(bool).sum())
            else:
                lifecycle_mix[label] = 0
        if "lifecycle_type" in g.columns:
            lc = g["lifecycle_type"].astype(str).str.upper()
            lifecycle_mix["TERMINATION"] = int((lc == "TERMINATION").sum())
            lifecycle_mix["CORRECTION"] = int((lc == "CORRECTION").sum())

        def _any(flag: str) -> bool | None:
            if flag not in g.columns:
                return None
            normalized = g[flag].map(_bool_or_none)
            return bool(normalized.eq(True).any())

        def _all(flag: str) -> bool | None:
            if flag not in g.columns:
                return None
            normalized = g[flag].map(_bool_or_none)
            non_null = normalized.dropna()
            if non_null.empty:
                return None
            return bool(non_null.eq(True).all())

        package_type = _consistent_str(g, "package_type") or "OUTRIGHT"
        trade_type = _consistent_str(g, "trade_type") or package_type
        fwd_years_series = pd.to_numeric(g.get("forward_start_years"), errors="coerce")
        structural_risk = _structural_risk(risk, tenor_years_series, trade_type, forward_start_years=fwd_years_series)

        rec: dict[str, Any] = {
            "package_id": str(package_id),
            "manual_link_id": (
                _str_or_none(g["manual_link_id"].iloc[0])
                if "manual_link_id" in g.columns
                else None
            ),
            "as_of_date": as_of_date,
            "execution_start": _to_db_value(execution_start),
            "execution_end": _to_db_value(execution_end),
            "original_execution_start": _to_db_value(
                g["original_execution_timestamp"].min()
                if "original_execution_timestamp" in g.columns else execution_start
            ),
            "clearing_accepted_start": _to_db_value(
                g["clearing_accepted_timestamp"].min(skipna=True)
                if "clearing_accepted_timestamp" in g.columns else None
            ),
            "package_structure": _package_structure_label(g),
            "package_type": package_type,
            "package_indicator": _any("package_indicator"),
            "package_tenors": _package_tenors_str(g) or None,
            "n_package_legs": int(len(g)),
            "legs_count": int(len(g)),
            "total_notional": _num_or_none(notional.sum(skipna=True)) if notional.notna().any() else None,
            "gross_notional": _num_or_none(abs_notional.sum(skipna=True)) if abs_notional.notna().any() else None,
            "total_risk": structural_risk,
            "gross_risk": _num_or_none(risk.abs().sum(skipna=True)) if risk.notna().any() else None,
            "weighted_fixed_rate": weighted_fixed_rate,
            "min_fixed_rate": _num_or_none(fixed.min(skipna=True)) if fixed.notna().any() else None,
            "max_fixed_rate": _num_or_none(fixed.max(skipna=True)) if fixed.notna().any() else None,
            "has_spread": (
                bool(g.get("has_spread", pd.Series(dtype=bool)).fillna(False).astype(bool).any())
                if "has_spread" in g.columns else None
            ),
            "package_transaction_spread": _num_or_none(
                g["package_transaction_spread"].iloc[0]
                if "package_transaction_spread" in g.columns else None
            ),
            "package_transaction_price": (
                _consistent_num(g, "package_transaction_price")
                if "package_transaction_price" in g.columns
                else _consistent_num(g, "Package transaction price")
            ),
            "package_transaction_price_currency": (
                _consistent_str(g, "package_transaction_price_currency")
                if "package_transaction_price_currency" in g.columns
                else _consistent_str(g, "Package transaction price currency")
            ),
            "rate_index_clean": _consistent_str(g, "rate_index_clean"),
            "venue": _consistent_str(g, "venue"),
            "ccp": _consistent_str(g, "ccp"),
            "execution_session": _consistent_str(g, "execution_session"),
            "is_new_risk": _any("is_new_risk"),
            "is_unwind": _any("is_unwind"),
            "is_compression_any": _any("is_compression"),
            "is_ufro_any": _any("is_ufro"),
            "is_block_any": _any("is_block"),
            "is_capped_any": _any("is_capped"),
            "is_off_date_any": _any("is_off_date"),
            "is_termination_any": bool(lifecycle_mix.get("TERMINATION", 0) > 0),
            "is_novation_any": _any("is_novation"),
            "is_reset_optimization_any": _any("is_reset_optimization"),
            "is_clearing_termination_any": _any("is_clearing_termination"),
            "is_correction_any": bool(lifecycle_mix.get("CORRECTION", 0) > 0),
            "lifecycle_mix": lifecycle_mix,
            # Phase 3/4 economic-class rollups
            "economic_class_primary": (
                _consistent_str(g, "economic_class")
                or (
                    g["economic_class"].value_counts().idxmax()
                    if "economic_class" in g.columns and g["economic_class"].notna().any()
                    else None
                )
            ),
            "contributes_to_flow_any": _any("contributes_to_flow"),
            "contributes_to_volume_any": _any("contributes_to_volume"),
            "contributes_to_pnl_any": _any("contributes_to_pnl"),
            "on_p43_any": _any("on_p43"),
            "state_machine_violation_any": _any("state_machine_violation"),
            "is_fomc_dated": _any("is_fomc_dated"),
            "fomc_meeting_label": _consistent_str(g, "fomc_meeting_label"),
            "cluster_id": _consistent_str(g, "cluster_id"),
            "cluster_size": _int_or_none(
                g["cluster_size"].iloc[0] if "cluster_size" in g.columns else None
            ),
            "tape_label": _rep_tape_label(g),
            "special_tenor_type": _consistent_str(g, "special_tenor_type"),
            "tape_label_ust_alias": _rep_tape_label_ust_alias(g),
            "is_matched_maturity_all": _all("matched_ust_maturity"),
            "tape_tags": _str_or_none(
                ",".join(sorted({
                    t
                    for raw in g["tape_tags"].dropna() if raw
                    for t in str(raw).split(",") if t
                })) if "tape_tags" in g.columns and g["tape_tags"].notna().any() else None
            ),
            # Phase 7: frontend-to-backend logic port
            "is_off_market_any": _any("is_off_market"),
            **_compute_ccp_switch(g),
            "package_adjusted_dv01": _compute_package_adjusted_dv01(
                risk, package_type, len(g)
            ),
            **_compute_leg_summary(g, package_type, trade_type),
            "normalized_tape_label": _str_or_none(
                g["normalized_tape_label"].iloc[0]
                if "normalized_tape_label" in g.columns
                else None
            ),
            **_compute_confidence_columns(g, package_type),
            # PTP/OPA package-level aggregations (identical across legs in a group)
            "ptp_group_id": _str_or_none(
                g["ptp_group_id"].iloc[0] if "ptp_group_id" in g.columns else None
            ),
            "ptp_group_size": _int_or_none(
                g["ptp_group_size"].iloc[0] if "ptp_group_size" in g.columns else None
            ),
            "ptp_price_notation": _int_or_none(
                g["ptp_price_notation"].iloc[0] if "ptp_price_notation" in g.columns else None
            ),
            "opa_signed_net": _num_or_none(
                g["opa_signed_net"].iloc[0] if "opa_signed_net" in g.columns else None
            ),
            "opa_ptp_residual": _num_or_none(
                g["opa_ptp_residual"].iloc[0] if "opa_ptp_residual" in g.columns else None
            ),
            "opa_sign_confidence": _str_or_none(
                g["opa_sign_confidence"].iloc[0] if "opa_sign_confidence" in g.columns else None
            ),
            "opa_constrained_net": _num_or_none(
                g["opa_constrained_net"].iloc[0] if "opa_constrained_net" in g.columns else None
            ),
            "opa_constrained_residual": _num_or_none(
                g["opa_constrained_residual"].iloc[0] if "opa_constrained_residual" in g.columns else None
            ),
            "dealer_spread_est": _num_or_none(
                g["dealer_spread_est"].iloc[0] if "dealer_spread_est" in g.columns else None
            ),
            "dealer_spread_bps": _num_or_none(
                g["dealer_spread_bps"].iloc[0] if "dealer_spread_bps" in g.columns else None
            ),
            "ptp_sub_structures": (
                _to_jsonable(g["ptp_sub_structures"].iloc[0])
                if "ptp_sub_structures" in g.columns else None
            ),
            "package_metrics": {
                "execution_span_seconds": float(
                    (execution_end - execution_start).total_seconds()
                ) if pd.notna(execution_start) and pd.notna(execution_end) else None,
            },
        }
        rows.append(rec)
    return rows


# ---------------------------------------------------------------------------
# Upsert helpers
# ---------------------------------------------------------------------------


def _upsert(
    engine: Engine,
    table: str,
    columns: Iterable[str],
    rows: list[dict],
    *,
    conflict_col: str,
    json_cols: set[str],
    batch_size: int = 10_000,
    progress_desc: Optional[str] = None,
    _raw_conn=None,
) -> int:
    """Batched INSERT .. ON CONFLICT DO UPDATE.

    Fast path uses psycopg2's ``execute_values`` which collapses N round-trips
    to a handful of multi-row statements; that is 10-100x faster than
    SQLAlchemy's generic executemany on wide upserts with JSONB + GIN
    indexes. Mirrors :func:`ingest_usdswaps.upsert_dataframe`.

    Falls back to SQLAlchemy ``text()`` + ``executemany``, still batched and
    progress-reported, when psycopg2 is unavailable (e.g. psycopg3-only envs).

    When ``_raw_conn`` is supplied the caller owns the transaction — this
    function will execute batches on that connection but will NOT commit,
    rollback, or close it.
    """
    if not rows:
        return 0
    cols = list(columns)
    col_list = ", ".join(cols)
    update_cols = [c for c in cols if c != conflict_col]
    updates = ", ".join(f"{c} = EXCLUDED.{c}" for c in update_cols)

    # Normalize payload once (same coercion for both paths).
    payload: list[dict] = []
    for rec in rows:
        out = {c: _to_db_value(rec.get(c)) for c in cols}
        for c in json_cols:
            if c in cols:
                out[c] = json.dumps(
                    _to_jsonable(rec.get(c)) if rec.get(c) is not None else {}
                )
        payload.append(out)

    total = len(payload)
    desc = progress_desc or f"Writing {table}"

    # Fast path: psycopg2 execute_values.
    try:
        from psycopg2.extras import execute_values
    except Exception:
        execute_values = None

    if execute_values is not None:
        upsert_sql = f"""
            INSERT INTO {table} ({col_list})
            VALUES %s
            ON CONFLICT ({conflict_col}) DO UPDATE
            SET {updates},
                updated_at = NOW()
        """
        owns_conn = _raw_conn is None
        raw_conn = engine.raw_connection() if owns_conn else _raw_conn
        try:
            with raw_conn.cursor() as cur:
                for start_idx in tqdm(
                    range(0, total, batch_size), desc=desc, unit="batch"
                ):
                    batch = payload[start_idx : start_idx + batch_size]
                    values = [tuple(rec[c] for c in cols) for rec in batch]
                    execute_values(
                        cur,
                        upsert_sql,
                        values,
                        page_size=min(len(values), 2_000),
                    )
            if owns_conn:
                raw_conn.commit()
        except Exception:
            if owns_conn:
                raw_conn.rollback()
            raise
        finally:
            if owns_conn:
                raw_conn.close()
        return total

    # Fallback path: SQLAlchemy executemany, but still batched + progress.
    placeholders = ", ".join(f":{c}" for c in cols)
    sql = text(
        f"""
        INSERT INTO {table} ({col_list})
        VALUES ({placeholders})
        ON CONFLICT ({conflict_col}) DO UPDATE
        SET {updates},
            updated_at = NOW()
        """
    )
    with engine.begin() as conn:
        for start_idx in tqdm(
            range(0, total, batch_size), desc=desc, unit="batch"
        ):
            batch = payload[start_idx : start_idx + batch_size]
            conn.execute(sql, batch)
    return total


def write_tape_rows(engine: Engine, tape: pd.DataFrame, as_of_date: str) -> dict:
    """Upsert leg + package rows in a single atomic transaction.

    All three write steps (packages, legs, orphan cleanup) share one
    psycopg2 connection so the COMMIT is a single point-in-time flip.
    Concurrent readers (the dashboard API) see either all-old or all-new
    data via MVCC — never the intermediate state that caused the frontend
    to blank during ingestion.
    """
    ensure_schema(engine)
    tape = _normalize_package_id(tape)
    package_rows = build_package_rows(tape, as_of_date=as_of_date)
    leg_rows = build_leg_rows(tape, as_of_date=as_of_date)

    raw_conn = engine.raw_connection()
    try:
        # Packages must be written first (legs FK them).
        n_pkgs = _upsert(
            engine,
            PACKAGES_TABLE,
            PACKAGE_COLUMNS,
            package_rows,
            conflict_col="package_id",
            json_cols=JSON_PKG_COLS,
            progress_desc="Writing tape packages",
            _raw_conn=raw_conn,
        )
        n_legs = _upsert(
            engine,
            LEGS_TABLE,
            LEG_COLUMNS,
            leg_rows,
            conflict_col="trade_id",
            json_cols=JSON_LEG_COLS,
            progress_desc="Writing tape legs",
            _raw_conn=raw_conn,
        )
        n_orphans = _delete_orphan_packages(
            engine, as_of_date=as_of_date, _raw_conn=raw_conn
        )
        raw_conn.commit()
    except Exception:
        raw_conn.rollback()
        raise
    finally:
        raw_conn.close()
    stats = {
        "packages_written": n_pkgs,
        "legs_written": n_legs,
        "orphan_packages_deleted": n_orphans,
    }
    _signal_tape_update(engine, as_of_date=as_of_date, stats=stats)
    return stats


_signal_ensured = False


def _ensure_signal_table(engine: Engine) -> None:
    """Create signal table if missing. Lightweight — no view locks."""
    global _signal_ensured
    if _signal_ensured:
        return
    try:
        with engine.connect() as conn:
            row = conn.execute(text(
                "SELECT 1 FROM information_schema.tables "
                "WHERE table_name = :t AND table_schema = 'public'"
            ), {"t": SIGNAL_TABLE_V2}).fetchone()
            if row is not None:
                _signal_ensured = True
                return
        _execute_ddl_bundle(engine, SIGNAL_TABLE_DDL)
        try:
            _execute_ddl_bundle(engine, SIGNAL_REALTIME_DDL)
        except Exception:
            pass
        _signal_ensured = True
    except Exception as e:
        print(f"  [SIGNAL] Signal table setup failed (non-fatal): {e}")


def _signal_tape_update(
    engine: Engine,
    *,
    as_of_date: str,
    stats: dict,
    cycle_ms: int = 0,
) -> None:
    """Update signal table + pg_notify for Supabase Realtime push.

    Non-critical — failures are logged and swallowed.
    """
    _ensure_signal_table(engine)
    try:
        payload = json.dumps({
            "d": as_of_date,
            "p": stats.get("packages_written", 0),
            "l": stats.get("legs_written", 0),
        })
        with engine.begin() as conn:
            conn.execute(
                text(f"""
                    UPDATE {SIGNAL_TABLE_V2}
                    SET updated_at = NOW(),
                        as_of_date = :d,
                        packages_written = :p,
                        legs_written = :l,
                        cycle_ms = :ms
                    WHERE id = 1
                """),
                {
                    "d": as_of_date,
                    "p": stats.get("packages_written", 0),
                    "l": stats.get("legs_written", 0),
                    "ms": cycle_ms,
                },
            )
            conn.execute(
                text("SELECT pg_notify('tape_updates', :payload)"),
                {"payload": payload},
            )
    except Exception as e:
        print(f"  [SIGNAL] Realtime notify failed (non-fatal): {e}")


def _delete_orphan_packages(
    engine: Engine, *, as_of_date: Optional[str] = None, _raw_conn=None
) -> int:
    """Delete package rows that have no legs pointing at them.

    Defensive maintenance step — runs after every ingest. Two ways a
    package can end up orphaned:

    1. **Leg FK re-parented to a new package_id.** The legs table upserts
       on ``trade_id``, so a trade that was part of CURVE_A yesterday and
       is now part of CURVE_B (detector produced a different package_id)
       has its leg row's ``package_id`` FK flipped to CURVE_B. Package row
       CURVE_A is left behind with zero legs pointing at it.

       The globally-unique ``CURVE_N_<min_leg>`` fix in
       ``SDRUtils/packages/curve.py`` et al. prevents most of these, but
       any detector change that shifts leg assignments still creates
       orphans on re-ingest.

    2. **Package-only write, leg write failed.** If a prior run wrote
       packages but crashed before legs, the package is stranded.

    Orphans don't render an expand chevron in the dashboard (the view's
    ``legs_json`` aggregates to empty), so they're visible noise. Cleaning
    them up post-write keeps the tape tidy.

    When ``as_of_date`` is supplied the scan is restricted to that date,
    avoiding a full-table anti-join on every cycle.

    When ``_raw_conn`` is supplied the caller owns the transaction.
    """
    date_clause = ""
    params: tuple = ()
    if as_of_date is not None:
        date_clause = f" AND p.as_of_date = %s"
        params = (as_of_date,)

    delete_sql = f"""
        DELETE FROM {PACKAGES_TABLE} p
        WHERE NOT EXISTS (
            SELECT 1 FROM {LEGS_TABLE} l
            WHERE l.package_id = p.package_id
        ){date_clause}
    """

    if _raw_conn is not None:
        with _raw_conn.cursor() as cur:
            cur.execute(delete_sql, params)
            return cur.rowcount or 0
    # Standalone path uses SQLAlchemy text() — swap %s for :d placeholder.
    sa_sql = delete_sql.replace("%s", ":d")
    sa_params = {"d": as_of_date} if as_of_date is not None else {}
    with engine.begin() as conn:
        result = conn.execute(text(sa_sql), sa_params)
        return int(result.rowcount or 0)


# ---------------------------------------------------------------------------
# Manual-link join
# ---------------------------------------------------------------------------


def attach_manual_links(engine: Engine, tape: pd.DataFrame) -> pd.DataFrame:
    """Join the manual-links table onto the enriched tape and populate
    ``manual_link_id`` per trade.
    """
    if tape.empty or "trade_id" not in tape.columns:
        tape["manual_link_id"] = None
        return tape
    with engine.connect() as conn:
        links = conn.execute(
            text(
                f"""
                SELECT link_id::text AS link_id, linked_trade_ids
                FROM {MANUAL_LINKS_TABLE}
                WHERE is_active = TRUE
                """
            )
        ).fetchall()
    trade_to_link: dict[str, str] = {}
    for row in links:
        link_id = str(row[0])
        for tid in row[1] or []:
            trade_to_link[str(tid)] = link_id
    tape = tape.copy()
    tape["manual_link_id"] = tape["trade_id"].astype(str).map(trade_to_link)
    return tape


# ---------------------------------------------------------------------------
# Ingestion runs observability
# ---------------------------------------------------------------------------


def _start_run(engine: Engine, *, as_of_date: str | None) -> int:
    with engine.begin() as conn:
        result = conn.execute(
            text(
                f"""
                INSERT INTO {RUNS_TABLE} (started_at, as_of_date, status)
                VALUES (NOW(), :as_of, 'running')
                RETURNING run_id
                """
            ),
            {"as_of": as_of_date},
        )
        return int(result.scalar_one())


def _finish_run(
    engine: Engine,
    run_id: int,
    *,
    status: str,
    rows_in: int,
    rows_out: int,
    cache_hit: bool,
    error_text: str | None = None,
    failed_rows: list | None = None,
) -> None:
    with engine.begin() as conn:
        conn.execute(
            text(
                f"""
                UPDATE {RUNS_TABLE}
                SET ended_at = NOW(),
                    status = :status,
                    rows_in = :rows_in,
                    rows_out = :rows_out,
                    cache_hit = :cache_hit,
                    error_text = :error_text,
                    failed_rows = :failed_rows
                WHERE run_id = :run_id
                """
            ),
            {
                "status": status,
                "rows_in": rows_in,
                "rows_out": rows_out,
                "cache_hit": cache_hit,
                "error_text": error_text,
                "failed_rows": json.dumps(failed_rows or []),
                "run_id": run_id,
            },
        )


# ---------------------------------------------------------------------------
# Phase 7: VWAP daily aggregate
# ---------------------------------------------------------------------------

_VWAP_TICKER_SPECS: list[dict[str, Any]] = [
    {"ticker": "USSFCT2", "package_type": "SPREADOVER", "tenor_years": 2, "canonical_key": "USD/SOFR-OIS/COMPOUND"},
    {"ticker": "USSFCT5", "package_type": "SPREADOVER", "tenor_years": 5, "canonical_key": "USD/SOFR-OIS/COMPOUND"},
    {"ticker": "USSFCT10", "package_type": "SPREADOVER", "tenor_years": 10, "canonical_key": "USD/SOFR-OIS/COMPOUND"},
    {"ticker": "USSFCT30", "package_type": "SPREADOVER", "tenor_years": 30, "canonical_key": "USD/SOFR-OIS/COMPOUND"},
    {"ticker": "USSO5", "package_type": "OUTRIGHT", "tenor_years": 5, "canonical_key": "USD/SOFR-OIS/COMPOUND"},
    {"ticker": "USSO10", "package_type": "OUTRIGHT", "tenor_years": 10, "canonical_key": "USD/SOFR-OIS/COMPOUND"},
    {"ticker": "USSO30", "package_type": "OUTRIGHT", "tenor_years": 30, "canonical_key": "USD/SOFR-OIS/COMPOUND"},
]


def _resolve_vwap_ticker(
    tenor_years: float,
    canonical_key: str | None,
    package_type: str | None,
) -> str | None:
    """Map a trade to its Bloomberg-style VWAP ticker."""
    if not canonical_key or not package_type:
        return None
    pt = (package_type or "").upper()
    ck = (canonical_key or "").upper()
    for spec in _VWAP_TICKER_SPECS:
        if (spec["canonical_key"].upper() == ck
                and spec["package_type"] == pt
                and abs(spec["tenor_years"] - tenor_years) <= 0.5):
            return spec["ticker"]
    return None


def compute_and_write_vwap(
    engine: Any,
    tape: pd.DataFrame,
    as_of_date: str,
) -> int:
    """Compute risk-weighted daily VWAP per ticker and upsert to DB.

    Returns number of ticker rows written.
    """
    from SDRUtils._swappulse_scripts._tape_schema_v2 import VWAP_TABLE_V2

    if tape.empty:
        return 0

    tenor_y = pd.to_numeric(tape.get("tenor_years"), errors="coerce")
    canonical = tape.get("canonical_underlier_key", pd.Series(dtype="string"))
    pkg_type = tape.get("package_type", pd.Series(dtype="string"))
    fixed_rate = pd.to_numeric(tape.get("fixed_rate"), errors="coerce")
    risk_abs = pd.to_numeric(tape.get("risk"), errors="coerce").abs()

    tape_work = tape.copy()
    tape_work["_ticker"] = [
        _resolve_vwap_ticker(
            float(t) if pd.notna(t) else 0.0,
            str(c) if pd.notna(c) else None,
            str(p) if pd.notna(p) else None,
        )
        for t, c, p in zip(tenor_y, canonical, pkg_type)
    ]
    tape_work["_rate"] = fixed_rate
    tape_work["_risk_abs"] = risk_abs

    has_ticker = tape_work["_ticker"].notna()
    has_rate = tape_work["_rate"].notna()
    subset = tape_work[has_ticker & has_rate]
    if subset.empty:
        return 0

    rows_written = 0
    with engine.begin() as conn:
        for ticker, grp in subset.groupby("_ticker"):
            rates = grp["_rate"]
            risks = grp["_risk_abs"].fillna(0)
            weight_sum = float(risks.sum())
            if weight_sum > 0:
                vwap = float((rates * risks).sum() / weight_sum)
            else:
                vwap = float(rates.mean())
            vwap_bps = round(vwap * 10_000, 2)

            conn.execute(
                text(f"""
                    INSERT INTO {VWAP_TABLE_V2}
                        (as_of_date, ticker, vwap_bps, total_risk, total_notional, trade_count)
                    VALUES (:d, :t, :v, :r, :n, :c)
                    ON CONFLICT (as_of_date, ticker) DO UPDATE SET
                        vwap_bps = EXCLUDED.vwap_bps,
                        total_risk = EXCLUDED.total_risk,
                        total_notional = EXCLUDED.total_notional,
                        trade_count = EXCLUDED.trade_count
                """),
                {
                    "d": as_of_date,
                    "t": ticker,
                    "v": vwap_bps,
                    "r": _num_or_none(risks.sum()),
                    "n": _num_or_none(
                        pd.to_numeric(grp.get("notional"), errors="coerce").abs().sum()
                    ),
                    "c": len(grp),
                },
            )
            rows_written += 1
    return rows_written


# ---------------------------------------------------------------------------
# End-to-end entrypoint
# ---------------------------------------------------------------------------


def run_ingest(
    pg_url: str,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    use_cache: bool = True,
    cache_path: Optional[str] = None,
    pre_classified: Optional[pd.DataFrame] = None,
    engine: Optional[Engine] = None,
) -> int:
    """Full pipeline: load classified df → TradeTape.compute() → write → record run.

    ``start_date`` / ``end_date`` name inclusive calendar days (YYYY-MM-DD).
    The underlying ``load_usd_swaps`` expects ``[start, end)`` timestamps, so
    ``end`` is bumped to ``end_date + 1 day`` at midnight UTC. Same-day runs
    (``start_date == end_date``) therefore cover a full 24-hour window. This
    matches the classification stage in ``run_usdswaps_pipeline._run_classification_range``.

    ``cache_path`` must point at the SAME SDR classification cache directory
    used by the classification stage (``ingest_usdswaps._resolve_cache_path``),
    otherwise the tape stage reads stale pre-fix classifications while the
    classification stage writes fresh parquet elsewhere. Defaults to the shared
    resolver so both stages land on the same directory by default.

    ``pre_classified``: when provided, skip re-classification entirely and use
    this DataFrame directly. Eliminates the double-classify race in service mode.

    ``engine``: when provided, reuse this SQLAlchemy engine instead of creating
    a new one. Avoids leaking connection pools in long-running service loops.
    """
    from datetime import timedelta

    from notebooks.sdr._usd_swaps_common import load_usd_swaps
    from SDRUtils._swappulse_scripts.ingest_usdswaps import _resolve_cache_path

    resolved_cache_path = _resolve_cache_path(cache_path)

    start = (
        datetime.strptime(start_date, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        if start_date else datetime.now(tz=timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    )
    end_day = (
        datetime.strptime(end_date, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        if end_date else start
    )
    end = end_day + timedelta(days=1)

    if engine is None:
        engine = create_engine(pg_url)
    ensure_schema(engine)
    run_id = _start_run(engine, as_of_date=start.date().isoformat())
    try:
        if pre_classified is not None:
            classified = pre_classified
            raw_df = None
        else:
            # load_usd_swaps(return_raw=True) can fail inside grab_sdr_trades
            # when the upstream SDR builder returns an empty frame for the day.
            # raw_df is optional for TradeTape (only used for cross-day lifecycle),
            # so fall back to classified-only on raw-fetch failure.
            try:
                classified, raw_df = load_usd_swaps(
                    start=start, end=end, cache_path=resolved_cache_path, return_raw=True
                )
            except Exception as raw_err:
                import warnings

                warnings.warn(
                    f"load_usd_swaps raw fetch failed ({raw_err}); "
                    "continuing with classified-only",
                )
                classified = load_usd_swaps(
                    start=start, end=end, cache_path=resolved_cache_path, return_raw=False
                )
                raw_df = None
        cache_hit = False
        tape = TradeTape(df=classified, raw_df=raw_df).compute(use_cache=use_cache)
        tape = attach_manual_links(engine, tape)
        stats = write_tape_rows(engine, tape, as_of_date=start.date().isoformat())
        orphans_cleaned = int(stats.get("orphan_packages_deleted") or 0)
        if orphans_cleaned:
            print(
                f"  Cleaned up {orphans_cleaned:,} orphan package row(s) left "
                f"behind by re-assigned legs."
            )
        vwap_count = compute_and_write_vwap(
            engine, tape, as_of_date=start.date().isoformat()
        )
        if vwap_count:
            print(f"  Wrote {vwap_count} VWAP ticker(s).")
        _finish_run(
            engine,
            run_id,
            status="success",
            rows_in=int(len(classified)),
            rows_out=int(stats["legs_written"]),
            cache_hit=cache_hit,
        )
        return 0
    except Exception as e:  # pragma: no cover - operational path
        _finish_run(
            engine,
            run_id,
            status="error",
            rows_in=0,
            rows_out=0,
            cache_hit=False,
            error_text=str(e),
        )
        raise


def run_ingest_incremental(
    engine: Engine,
    classified_df: pd.DataFrame,
    prev_enriched: pd.DataFrame,
    new_trade_ids: set[str],
    as_of_date: str,
    raw_df: pd.DataFrame | None = None,
) -> tuple[pd.DataFrame, dict]:
    """Incremental tape pipeline: enrich only new rows, merge, write, VWAP.

    Returns ``(enriched_tape, stats_dict)`` so the service loop can carry
    forward the enriched tape for the next cycle.

    When ``prev_enriched`` is provided and ``new_trade_ids`` is a small
    delta, only the packages that *contain* a new trade are built and
    upserted — skipping the expensive build_package_rows aggregation on
    the full tape.
    """
    import time as _time

    from SDRUtils.analytics.trade_tape import TradeTape

    ensure_schema(engine)
    run_id = _start_run(engine, as_of_date=as_of_date)
    t0 = _time.monotonic()
    try:
        tape_obj = TradeTape(df=classified_df, raw_df=raw_df)
        enriched = tape_obj.compute_incremental(prev_enriched, new_trade_ids)
        enriched = attach_manual_links(engine, enriched)

        t_write = _time.monotonic()

        # Delta write: only build + upsert packages/legs that contain
        # new trade_ids. Avoids the O(n) build_package_rows aggregation
        # on 3000+ packages when only a handful changed.
        _do_delta = (
            prev_enriched is not None
            and not prev_enriched.empty
            and new_trade_ids
            and len(new_trade_ids) < len(enriched)
        )
        if _do_delta and "trade_id" in enriched.columns:
            _new_mask = enriched["trade_id"].astype(str).isin(new_trade_ids)
            if "package_id" in enriched.columns:
                _affected_pkg_ids = set(
                    enriched.loc[_new_mask, "package_id"].dropna().astype(str)
                )
                _pkg_mask = enriched["package_id"].astype(str).isin(
                    _affected_pkg_ids
                )
                delta_tape = enriched[_new_mask | _pkg_mask].copy()
            else:
                delta_tape = enriched[_new_mask].copy()
            print(
                f"  Delta write: {len(delta_tape)} rows "
                f"({len(new_trade_ids)} new trades, "
                f"{len(_affected_pkg_ids) if 'package_id' in enriched.columns else '?'} packages) "
                f"/ {len(enriched)} total"
            )
            stats = write_tape_rows(
                engine, delta_tape, as_of_date=as_of_date
            )
        else:
            stats = write_tape_rows(
                engine, enriched, as_of_date=as_of_date
            )

        t_write_done = _time.monotonic()

        orphans_cleaned = int(stats.get("orphan_packages_deleted") or 0)
        if orphans_cleaned:
            print(
                f"  Cleaned up {orphans_cleaned:,} orphan package row(s)."
            )

        vwap_count = compute_and_write_vwap(
            engine, enriched, as_of_date=as_of_date
        )
        if vwap_count:
            print(f"  Wrote {vwap_count} VWAP ticker(s).")

        elapsed = _time.monotonic() - t0
        print(
            f"  [TIMING] Tape incremental total: {elapsed:.1f}s "
            f"(write: {t_write_done - t_write:.1f}s)"
        )

        _finish_run(
            engine,
            run_id,
            status="success",
            rows_in=int(len(classified_df)),
            rows_out=int(stats["legs_written"]),
            cache_hit=False,
        )
        return enriched, stats
    except Exception as e:
        _finish_run(
            engine,
            run_id,
            status="error",
            rows_in=0,
            rows_out=0,
            cache_hit=False,
            error_text=str(e),
        )
        raise


def resolve_pg_url(explicit: str | None = None) -> str:
    """Resolve a Postgres URL using the same lookup ladder as ingest_usdswaps.

    Precedence: explicit arg → DATABASE_URL env → PG_URL env → the shared
    SWAPPULSE_DB_* helper on ingest_usdswaps (which itself honours env
    overrides and falls back to the repo-default Supabase host).
    """
    return (
        explicit
        or os.environ.get("DATABASE_URL")
        or os.environ.get("PG_URL")
        or _legacy_conn_string()
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--pg-url",
        default=None,
        help="Postgres URL. Omit to fall back to DATABASE_URL / PG_URL env vars and then the shared SWAPPULSE_DB_* defaults.",
    )
    parser.add_argument("--start-date")
    parser.add_argument("--end-date")
    parser.add_argument("--no-cache", action="store_true")
    args = parser.parse_args()
    return run_ingest(
        pg_url=resolve_pg_url(args.pg_url),
        start_date=args.start_date,
        end_date=args.end_date,
        use_cache=not args.no_cache,
    )


if __name__ == "__main__":
    raise SystemExit(main())
