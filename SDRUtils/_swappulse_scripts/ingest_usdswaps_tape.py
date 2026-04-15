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
import time
from datetime import datetime, timezone
from typing import Any, Iterable, Optional

import numpy as np
import pandas as pd
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

from SDRUtils.analytics.trade_tape import TradeTape

from ._tape_schema import (
    LEGS_TABLE,
    MANUAL_LINKS_TABLE,
    PACKAGES_TABLE,
    RUNS_TABLE,
    TAPE_SCHEMA_SQL,
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
    "risk",
    "fixed_rate",
    "trade_type",
    "rate_index_clean",
    "venue",
    "ccp",
    "platform_identifier",
    "tape_label",
    "leg_tape_label",
    "upi_reset_freq",
    "upi_notional_schedule",
    "upi_delivery_type",
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
    "lc_status",
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
    "manual_link_id",
    "enrichment_metrics",
)


PACKAGE_COLUMNS: tuple[str, ...] = (
    "package_id",
    "manual_link_id",
    "as_of_date",
    "execution_start",
    "execution_end",
    "package_structure",
    "package_type",
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
    "is_fomc_dated",
    "fomc_meeting_label",
    "cluster_id",
    "cluster_size",
    "tape_label",
    "package_metrics",
)


JSON_LEG_COLS = {"enrichment_metrics"}
JSON_PKG_COLS = {"lifecycle_mix", "package_metrics"}


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


def ensure_schema(engine: Engine) -> None:
    """Create tables / indexes / view if they don't already exist."""
    with engine.begin() as conn:
        buffer: list[str] = []
        for line in TAPE_SCHEMA_SQL.splitlines():
            buffer.append(line)
            stripped = line.strip()
            if stripped.endswith(";"):
                sql = "\n".join(buffer).strip()
                if sql:
                    conn.execute(text(sql))
                buffer = []
        tail = "\n".join(buffer).strip()
        if tail:
            conn.execute(text(tail))


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


def _leg_order_series(df: pd.DataFrame) -> pd.Series:
    """Assign stable 0-based leg_order within each package, ordered by (ts, trade_id)."""
    out = pd.Series(0, index=df.index, dtype="int64")
    for _, group in df.groupby("package_id", sort=False):
        ordered = group.sort_values(["execution_timestamp", "trade_id"]).index
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


def _consistent_str(group: pd.DataFrame, col: str) -> str | None:
    if col not in group.columns:
        return None
    vals = [v for v in (_str_or_none(x) for x in group[col]) if v]
    if not vals:
        return None
    if all(v == vals[0] for v in vals):
        return vals[0]
    return None


def build_leg_rows(tape: pd.DataFrame, *, as_of_date: str) -> list[dict]:
    if tape.empty:
        return []
    df = tape.copy()
    if "leg_order" not in df.columns:
        df["leg_order"] = _leg_order_series(df)
    df["execution_hour_et"] = _hour_et_series(df["execution_timestamp"])
    if "execution_session" not in df.columns:
        df["execution_session"] = None
    if "tenor_display" not in df.columns:
        df["tenor_display"] = df.get("tenor_label")
    if "quality_flags" not in df.columns:
        df["quality_flags"] = df.apply(_quality_flag_list, axis=1)

    rows: list[dict] = []
    for _, row in df.iterrows():
        rec: dict[str, Any] = {col: None for col in LEG_COLUMNS}
        for col in LEG_COLUMNS:
            if col in row.index:
                rec[col] = row[col]
        rec["as_of_date"] = as_of_date
        # Type coercions
        rec["leg_order"] = _int_or_none(rec.get("leg_order")) or 0
        rec["execution_hour_et"] = _int_or_none(rec.get("execution_hour_et"))
        rec["tenor_years"] = _num_or_none(rec.get("tenor_years"))
        rec["forward_start_years"] = _num_or_none(rec.get("forward_start_years"))
        rec["notional"] = _num_or_none(rec.get("notional"))
        rec["risk"] = _num_or_none(rec.get("risk"))
        rec["fixed_rate"] = _num_or_none(rec.get("fixed_rate"))
        rec["lc_n_events"] = _int_or_none(rec.get("lc_n_events"))
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
        ):
            rec[bool_col] = _bool_or_none(rec.get(bool_col))
        for text_col in (
            "trade_id", "package_id", "execution_session", "tenor_label",
            "tenor_display", "forward_label", "forward_bucket", "notional_currency",
            "trade_type", "rate_index_clean", "venue", "ccp", "platform_identifier",
            "tape_label", "leg_tape_label", "upi_reset_freq", "upi_notional_schedule",
            "upi_delivery_type", "lifecycle_type", "lc_status", "fomc_meeting_label",
            "fomc_proximity", "cluster_id", "xd_status",
        ):
            rec[text_col] = _str_or_none(rec.get(text_col))
        rec["execution_timestamp"] = _to_db_value(rec.get("execution_timestamp"))
        rec["effective_date"] = _to_db_value(rec.get("effective_date"))
        rec["expiration_date"] = _to_db_value(rec.get("expiration_date"))
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
        rows.append(rec)
    return rows


def _structural_risk(
    risk: pd.Series, tenor_years: pd.Series, trade_type: str
) -> Optional[float]:
    """Representative package DV01 for the front-of-tape DV01 cell.

    Curves and flies have offsetting leg risks, so summing them is misleading:
    a 5s10s curve with +41.5k / +41.6k legs would display +83.1k, which isn't
    meaningful. Convention here:
    - CURVE: back-leg DV01 (leg with the longest tenor).
    - FLY: belly-leg DV01 (middle tenor after sorting).
    - Anything else: sum of leg DV01s (unchanged behaviour).

    Returns None if no leg has a non-null risk.
    """
    if not risk.notna().any():
        return None
    tt = (trade_type or "").upper()
    if tt in ("CURVE", "FLY"):
        valid_mask = risk.notna() & tenor_years.notna()
        if valid_mask.any():
            ordered = tenor_years[valid_mask].sort_values(kind="stable")
            if tt == "CURVE":
                # Back leg = longest tenor.
                target_idx = ordered.index[-1]
            else:
                # Belly = middle tenor after sorting. For a conventional 3-leg
                # fly this lands on the middle leg; for 2-leg inputs we fall
                # back to the longer-tenor leg so the value is still well
                # defined. len // 2 gives the right answer in both cases.
                target_idx = ordered.index[len(ordered) // 2]
            return _num_or_none(risk.loc[target_idx])
    return _num_or_none(risk.sum(skipna=True))


def build_package_rows(tape: pd.DataFrame, *, as_of_date: str) -> list[dict]:
    """Aggregate the per-trade TradeTape output into one row per package_id."""
    if tape.empty:
        return []
    rows: list[dict] = []
    lifecycle_keys = [
        ("NEW_RISK", "is_new_risk"),
        ("UNWIND", "is_unwind"),
        ("COMPRESSION", "is_compression"),
        ("TERMINATION", None),  # count via lifecycle_type
        ("NOVATION", "is_novation"),
        ("RESET_OPT", "is_reset_optimization"),
        ("CORRECTION", None),
        ("CLEARING_TERM", "is_clearing_termination"),
        ("EXERCISE_BORN", "is_exercise_born"),
    ]
    for package_id, group in tape.groupby("package_id", sort=False):
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
            return bool(g[flag].fillna(False).astype(bool).any())

        package_type = _consistent_str(g, "package_type") or "OUTRIGHT"
        trade_type = _consistent_str(g, "trade_type") or package_type
        structural_risk = _structural_risk(risk, tenor_years_series, trade_type)

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
            "package_structure": _package_structure_label(g),
            "package_type": package_type,
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
            "is_fomc_dated": _any("is_fomc_dated"),
            "fomc_meeting_label": _consistent_str(g, "fomc_meeting_label"),
            "cluster_id": _consistent_str(g, "cluster_id"),
            "cluster_size": _int_or_none(
                g["cluster_size"].iloc[0] if "cluster_size" in g.columns else None
            ),
            "tape_label": _rep_tape_label(g),
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
) -> int:
    if not rows:
        return 0
    cols = list(columns)
    placeholders = ", ".join(f":{c}" for c in cols)
    col_list = ", ".join(cols)
    update_cols = [c for c in cols if c != conflict_col]
    updates = ", ".join(f"{c} = EXCLUDED.{c}" for c in update_cols)
    sql = text(
        f"""
        INSERT INTO {table} ({col_list})
        VALUES ({placeholders})
        ON CONFLICT ({conflict_col}) DO UPDATE
        SET {updates}, updated_at = NOW()
        """
    )
    payload = []
    for rec in rows:
        out = {c: _to_db_value(rec.get(c)) for c in cols}
        for c in json_cols:
            if c in cols:
                out[c] = json.dumps(_to_jsonable(rec.get(c)) if rec.get(c) is not None else {})
        payload.append(out)
    with engine.begin() as conn:
        conn.execute(sql, payload)
    return len(payload)


def write_tape_rows(engine: Engine, tape: pd.DataFrame, as_of_date: str) -> dict:
    """Upsert leg + package rows. Returns stats dict."""
    ensure_schema(engine)
    tape = _normalize_package_id(tape)
    package_rows = build_package_rows(tape, as_of_date=as_of_date)
    leg_rows = build_leg_rows(tape, as_of_date=as_of_date)
    # Packages must be written first (legs FK them).
    n_pkgs = _upsert(
        engine,
        PACKAGES_TABLE,
        PACKAGE_COLUMNS,
        package_rows,
        conflict_col="package_id",
        json_cols=JSON_PKG_COLS,
    )
    n_legs = _upsert(
        engine,
        LEGS_TABLE,
        LEG_COLUMNS,
        leg_rows,
        conflict_col="trade_id",
        json_cols=JSON_LEG_COLS,
    )
    return {"packages_written": n_pkgs, "legs_written": n_legs}


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
# End-to-end entrypoint
# ---------------------------------------------------------------------------


def run_ingest(
    pg_url: str,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    use_cache: bool = True,
) -> int:
    """Full pipeline: load classified df → TradeTape.compute() → write → record run.

    ``start_date`` / ``end_date`` name inclusive calendar days (YYYY-MM-DD).
    The underlying ``load_usd_swaps`` expects ``[start, end)`` timestamps, so
    ``end`` is bumped to ``end_date + 1 day`` at midnight UTC. Same-day runs
    (``start_date == end_date``) therefore cover a full 24-hour window. This
    matches the classification stage in ``run_usdswaps_pipeline._run_classification_range``.
    """
    from datetime import timedelta

    from notebooks.sdr._usd_swaps_common import load_usd_swaps

    start = (
        datetime.strptime(start_date, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        if start_date else datetime.now(tz=timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    )
    end_day = (
        datetime.strptime(end_date, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        if end_date else start
    )
    end = end_day + timedelta(days=1)

    engine = create_engine(pg_url)
    ensure_schema(engine)
    run_id = _start_run(engine, as_of_date=start.date().isoformat())
    try:
        # load_usd_swaps(return_raw=True) can fail inside grab_sdr_trades
        # when the upstream SDR builder returns an empty frame for the day.
        # raw_df is optional for TradeTape (only used for cross-day lifecycle),
        # so fall back to classified-only on raw-fetch failure.
        try:
            classified, raw_df = load_usd_swaps(
                start=start, end=end, return_raw=True
            )
        except Exception as raw_err:
            import warnings

            warnings.warn(
                f"load_usd_swaps raw fetch failed ({raw_err}); "
                "continuing with classified-only",
            )
            classified = load_usd_swaps(start=start, end=end, return_raw=False)
            raw_df = None
        cache_hit = False
        # Heuristic: if cache file is already on disk, TradeTape will hit it.
        tape = TradeTape(df=classified, raw_df=raw_df).compute(use_cache=use_cache)
        tape = attach_manual_links(engine, tape)
        stats = write_tape_rows(engine, tape, as_of_date=start.date().isoformat())
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
