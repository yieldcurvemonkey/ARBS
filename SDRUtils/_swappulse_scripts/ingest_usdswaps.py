"""
USD swaps ingestion for SwapPulse.

Persists USD swap classifications to normalized package/leg tables and
creates versioned display views consumed by the dashboard.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import time
from datetime import timedelta
from typing import Any, Dict, Iterable, Optional

import numpy as np
import pandas as pd
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from tqdm import tqdm


PACKAGES_TABLE = "arbs_usd_swap_packages_v2"
LEGS_TABLE = "arbs_usd_swap_legs_v2"
RUNS_TABLE = "arbs_usd_swap_ingestion_runs_v2"
MANUAL_LINKS_TABLE = "arbs_usd_swap_manual_links_v2"
LINK_HISTORY_TABLE = "arbs_usd_swap_link_history_v2"
DISPLAY_VIEW_V1 = "arbs_usd_swap_display_items_v3"
DISPLAY_VIEW_V2 = "arbs_usd_swap_display_items_v4"
DISPLAY_VIEW = DISPLAY_VIEW_V1

PACKAGE_METRIC_COLUMNS: dict[str, tuple[str, ...]] = {}

LEG_METRIC_COLUMNS: tuple[str, ...] = (
    "upi_underlier_name",
    "unique_product_identifier",
    "matched_ust_maturity",
    "matched_ust_maturity_trade_confidence",
    "invoice_swap_ticker",
    "is_mac",
    "is_spreadover",
    "is_asset_swap",
    "other_payment_type",
    "other_payment_amount",
)

NUMERIC_COLUMNS: tuple[str, ...] = (
    "notional",
    "estimated_pv01",
    "risk",
    "tenor_years",
    "forward_start_years",
    "fixed_rate",
    "package_transaction_spread",
    "other_payment_amount",
)

BOOL_COLUMNS: tuple[str, ...] = (
    "package_indicator",
    "is_notional_capped",
    "is_forward",
    "matched_ust_maturity",
    "is_mac",
    "is_spreadover",
    "is_asset_swap",
)

TIMESTAMP_COLUMNS: tuple[str, ...] = ("execution_timestamp",)
DATE_COLUMNS: tuple[str, ...] = (
    "effective_date",
    "expiration_date",
    "swap_maturity_date",
)

PACKAGE_UPSERT_UPDATE_COLUMNS: tuple[str, ...] = (
    "package_type",
    "package_source",
    "manual_link_id",
    "as_of_date",
    "execution_start",
    "execution_end",
    "effective_date",
    "expiration_date",
    "tenor_years",
    "tenor_label",
    "forward_start_years",
    "forward_label",
    "is_forward",
    "legs_count",
    "total_notional",
    "gross_notional",
    "total_risk",
    "gross_risk",
    "weighted_fixed_rate",
    "min_fixed_rate",
    "max_fixed_rate",
    "package_indicator",
    "package_transaction_spread",
    "package_metrics",
)

LEG_UPSERT_UPDATE_COLUMNS: tuple[str, ...] = (
    "package_id",
    "leg_order",
    "event_action",
    "execution_timestamp",
    "effective_date",
    "expiration_date",
    "product_type",
    "trade_label",
    "tenor_years",
    "tenor_label",
    "forward_start_years",
    "forward_label",
    "is_forward",
    "notional",
    "notional_currency",
    "is_notional_capped",
    "estimated_pv01",
    "risk",
    "fixed_rate",
    "cleared",
    "platform_identifier",
    "package_type",
    "package_indicator",
    "package_transaction_spread",
    "matched_ust_maturity",
    "ust_cusip",
    "swap_maturity_date",
    "matched_ust_maturity_trade_confidence",
    "invoice_swap_ticker",
    "is_mac",
    "is_spreadover",
    "is_asset_swap",
    "manual_link_id",
    "is_manually_linked",
    "leg_metrics",
)

# Schema (packages + legs + ingestion runs + display view)
SCHEMA_SQL = f"""
CREATE EXTENSION IF NOT EXISTS pgcrypto;

CREATE TABLE IF NOT EXISTS {PACKAGES_TABLE} (
    package_id TEXT PRIMARY KEY,
    package_type TEXT NOT NULL,
    package_source TEXT NOT NULL DEFAULT 'AUTO',
    manual_link_id UUID,
    as_of_date DATE NOT NULL,
    execution_start TIMESTAMPTZ NOT NULL,
    execution_end TIMESTAMPTZ NOT NULL,
    effective_date DATE,
    expiration_date DATE,
    tenor_years NUMERIC,
    tenor_label TEXT,
    forward_start_years NUMERIC,
    forward_label TEXT,
    is_forward BOOLEAN,
    legs_count INTEGER NOT NULL,
    total_notional NUMERIC,
    gross_notional NUMERIC,
    total_risk NUMERIC,
    gross_risk NUMERIC,
    weighted_fixed_rate NUMERIC,
    min_fixed_rate NUMERIC,
    max_fixed_rate NUMERIC,
    package_indicator BOOLEAN,
    package_transaction_spread NUMERIC,
    package_metrics JSONB NOT NULL DEFAULT '{{}}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS {LEGS_TABLE} (
    trade_id TEXT PRIMARY KEY,
    package_id TEXT NOT NULL REFERENCES {PACKAGES_TABLE}(package_id),
    leg_order INTEGER NOT NULL,
    event_action TEXT,
    execution_timestamp TIMESTAMPTZ NOT NULL,
    effective_date DATE,
    expiration_date DATE,
    product_type TEXT,
    trade_label TEXT,
    tenor_years NUMERIC,
    tenor_label TEXT,
    forward_start_years NUMERIC,
    forward_label TEXT,
    is_forward BOOLEAN,
    notional NUMERIC,
    notional_currency TEXT,
    is_notional_capped BOOLEAN,
    estimated_pv01 NUMERIC,
    risk NUMERIC,
    fixed_rate NUMERIC,
    cleared TEXT,
    platform_identifier TEXT,
    package_type TEXT,
    package_indicator BOOLEAN,
    package_transaction_spread NUMERIC,
    matched_ust_maturity BOOLEAN,
    ust_cusip TEXT,
    swap_maturity_date DATE,
    matched_ust_maturity_trade_confidence TEXT,
    invoice_swap_ticker TEXT,
    is_mac BOOLEAN,
    is_spreadover BOOLEAN,
    is_asset_swap BOOLEAN,
    manual_link_id UUID,
    is_manually_linked BOOLEAN NOT NULL DEFAULT FALSE,
    leg_metrics JSONB NOT NULL DEFAULT '{{}}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS {RUNS_TABLE} (
    run_id BIGSERIAL PRIMARY KEY,
    ingestion_started_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    start_ts TIMESTAMPTZ,
    end_ts TIMESTAMPTZ,
    rows_raw INTEGER,
    packages_written INTEGER,
    legs_written INTEGER,
    notes TEXT
);

CREATE TABLE IF NOT EXISTS {MANUAL_LINKS_TABLE} (
    link_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    manual_package_id TEXT NOT NULL UNIQUE,
    package_type TEXT,
    linked_trade_ids TEXT[] NOT NULL,
    created_by TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_by TEXT,
    updated_at TIMESTAMPTZ,
    user_comment TEXT,
    link_reason TEXT,
    tags TEXT[],
    link_metrics JSONB NOT NULL DEFAULT '{{}}'::jsonb,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    superseded_by UUID REFERENCES {MANUAL_LINKS_TABLE}(link_id),
    CONSTRAINT valid_link_size CHECK (array_length(linked_trade_ids, 1) >= 2)
);

CREATE TABLE IF NOT EXISTS {LINK_HISTORY_TABLE} (
    history_id BIGSERIAL PRIMARY KEY,
    link_id UUID NOT NULL REFERENCES {MANUAL_LINKS_TABLE}(link_id),
    action TEXT NOT NULL,
    changed_by TEXT NOT NULL,
    changed_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    change_details JSONB,
    previous_state JSONB
);

ALTER TABLE {PACKAGES_TABLE}
    ADD COLUMN IF NOT EXISTS package_source TEXT NOT NULL DEFAULT 'AUTO';
ALTER TABLE {PACKAGES_TABLE}
    ADD COLUMN IF NOT EXISTS manual_link_id UUID REFERENCES {MANUAL_LINKS_TABLE}(link_id);

ALTER TABLE {LEGS_TABLE}
    ADD COLUMN IF NOT EXISTS manual_link_id UUID REFERENCES {MANUAL_LINKS_TABLE}(link_id);
ALTER TABLE {LEGS_TABLE}
    ADD COLUMN IF NOT EXISTS is_manually_linked BOOLEAN NOT NULL DEFAULT FALSE;

CREATE INDEX IF NOT EXISTS idx_usd_swap_v2_packages_type_date ON {PACKAGES_TABLE}(package_type, as_of_date);
CREATE INDEX IF NOT EXISTS idx_usd_swap_v2_packages_exec ON {PACKAGES_TABLE}(execution_start);
CREATE INDEX IF NOT EXISTS idx_usd_swap_v2_packages_source ON {PACKAGES_TABLE}(package_source);
CREATE INDEX IF NOT EXISTS idx_usd_swap_v2_legs_package ON {LEGS_TABLE}(package_id);
CREATE INDEX IF NOT EXISTS idx_usd_swap_v2_legs_exec ON {LEGS_TABLE}(execution_timestamp);
CREATE INDEX IF NOT EXISTS idx_usd_swap_v2_legs_manual_link ON {LEGS_TABLE}(manual_link_id);
CREATE INDEX IF NOT EXISTS idx_usd_swap_v2_manual_links_trades ON {MANUAL_LINKS_TABLE} USING GIN (linked_trade_ids);
CREATE INDEX IF NOT EXISTS idx_usd_swap_v2_manual_links_active ON {MANUAL_LINKS_TABLE}(is_active) WHERE is_active = TRUE;
CREATE INDEX IF NOT EXISTS idx_usd_swap_v2_manual_links_created ON {MANUAL_LINKS_TABLE}(created_at);
CREATE INDEX IF NOT EXISTS idx_usd_swap_v2_manual_links_manual_pkg ON {MANUAL_LINKS_TABLE}(manual_package_id);
CREATE INDEX IF NOT EXISTS idx_usd_swap_v2_link_history_link ON {LINK_HISTORY_TABLE}(link_id);

CREATE OR REPLACE VIEW {DISPLAY_VIEW_V1} AS
-- NOTE: Append new columns at the end to avoid CREATE OR REPLACE VIEW rename errors.
SELECT
  p.package_id,
  p.package_type,
  p.as_of_date,
  p.execution_start,
  p.execution_end,
  p.effective_date,
  p.expiration_date,
  p.tenor_years,
  p.tenor_label,
  p.forward_start_years,
  p.forward_label,
  p.is_forward,
  p.legs_count,
  p.total_notional,
  p.gross_notional,
  p.total_risk,
  p.gross_risk,
  p.weighted_fixed_rate,
  p.min_fixed_rate,
  p.max_fixed_rate,
  p.package_indicator,
  p.package_transaction_spread,
  p.package_metrics,
  l.legs_json
FROM {PACKAGES_TABLE} p
LEFT JOIN LATERAL (
    SELECT jsonb_agg(
        jsonb_build_object(
            'trade_id', l.trade_id,
            'leg_order', l.leg_order,
            'event_action', l.event_action,
            'execution_timestamp', l.execution_timestamp,
            'effective_date', l.effective_date,
            'expiration_date', l.expiration_date,
            'product_type', l.product_type,
            'trade_label', l.trade_label,
            'tenor_years', l.tenor_years,
            'tenor_label', l.tenor_label,
            'forward_start_years', l.forward_start_years,
            'forward_label', l.forward_label,
            'is_forward', l.is_forward,
            'notional', l.notional,
            'notional_currency', l.notional_currency,
            'is_notional_capped', l.is_notional_capped,
            'estimated_pv01', l.estimated_pv01,
            'risk', l.risk,
            'fixed_rate', l.fixed_rate,
            'cleared', l.cleared,
            'platform_identifier', l.platform_identifier,
            'package_type', l.package_type,
            'package_indicator', l.package_indicator,
            'package_transaction_spread', l.package_transaction_spread,
            'matched_ust_maturity', l.matched_ust_maturity,
            'ust_cusip', l.ust_cusip,
            'swap_maturity_date', l.swap_maturity_date,
            'matched_ust_maturity_trade_confidence', l.matched_ust_maturity_trade_confidence,
            'invoice_swap_ticker', l.invoice_swap_ticker,
            'is_mac', l.is_mac,
            'is_spreadover', l.is_spreadover,
            'is_asset_swap', l.is_asset_swap,
            'leg_metrics', l.leg_metrics
        ) ORDER BY l.leg_order
    ) AS legs_json
    FROM {LEGS_TABLE} l
    WHERE l.package_id = p.package_id
) l ON TRUE;

CREATE OR REPLACE VIEW {DISPLAY_VIEW_V2} AS
-- NOTE: Append new columns at the end to avoid CREATE OR REPLACE VIEW rename errors.
SELECT
  p.package_id,
  p.package_type,
  p.package_source,
  ml.link_id,
  ml.manual_package_id,
  ml.user_comment,
  ml.link_reason,
  ml.tags,
  ml.created_by AS link_created_by,
  ml.created_at AS link_created_at,
  ml.link_metrics,
  p.as_of_date,
  p.execution_start,
  p.execution_end,
  p.effective_date,
  p.expiration_date,
  p.tenor_years,
  p.tenor_label,
  p.forward_start_years,
  p.forward_label,
  p.is_forward,
  p.legs_count,
  p.total_notional,
  p.gross_notional,
  p.total_risk,
  p.gross_risk,
  p.weighted_fixed_rate,
  p.min_fixed_rate,
  p.max_fixed_rate,
  p.package_indicator,
  p.package_transaction_spread,
  p.package_metrics,
  l.legs_json
FROM {PACKAGES_TABLE} p
LEFT JOIN {MANUAL_LINKS_TABLE} ml
  ON p.manual_link_id = ml.link_id AND ml.is_active = TRUE
LEFT JOIN LATERAL (
    SELECT jsonb_agg(
        jsonb_build_object(
            'trade_id', l.trade_id,
            'leg_order', l.leg_order,
            'event_action', l.event_action,
            'execution_timestamp', l.execution_timestamp,
            'effective_date', l.effective_date,
            'expiration_date', l.expiration_date,
            'product_type', l.product_type,
            'trade_label', l.trade_label,
            'tenor_years', l.tenor_years,
            'tenor_label', l.tenor_label,
            'forward_start_years', l.forward_start_years,
            'forward_label', l.forward_label,
            'is_forward', l.is_forward,
            'notional', l.notional,
            'notional_currency', l.notional_currency,
            'is_notional_capped', l.is_notional_capped,
            'estimated_pv01', l.estimated_pv01,
            'risk', l.risk,
            'fixed_rate', l.fixed_rate,
            'cleared', l.cleared,
            'platform_identifier', l.platform_identifier,
            'package_type', l.package_type,
            'package_indicator', l.package_indicator,
            'package_transaction_spread', l.package_transaction_spread,
            'matched_ust_maturity', l.matched_ust_maturity,
            'ust_cusip', l.ust_cusip,
            'swap_maturity_date', l.swap_maturity_date,
            'matched_ust_maturity_trade_confidence', l.matched_ust_maturity_trade_confidence,
            'invoice_swap_ticker', l.invoice_swap_ticker,
            'is_mac', l.is_mac,
            'is_spreadover', l.is_spreadover,
            'is_asset_swap', l.is_asset_swap,
            'leg_metrics', l.leg_metrics,
            'is_manually_linked', l.is_manually_linked,
            'manual_link_id', l.manual_link_id
        ) ORDER BY l.leg_order
    ) AS legs_json
    FROM {LEGS_TABLE} l
    WHERE l.package_id = p.package_id
) l ON TRUE;
"""


def get_db_connection_string() -> str:
    """Build database connection string from environment variables."""
    host = os.getenv("SWAPPULSE_DB_HOST", "aws-0-us-east-1.pooler.supabase.com")
    port = os.getenv("SWAPPULSE_DB_PORT", "6543")
    dbname = os.getenv("SWAPPULSE_DB_NAME", "postgres")
    user = os.getenv("SWAPPULSE_DB_USER", "postgres.rdobtpugtnmefxplgwyp")
    password = os.getenv("SWAPPULSE_DB_PASSWORD", "0rbZUh8y0Fsvdlry")

    return f"postgresql://{user}:{password}@{host}:{port}/{dbname}"


def create_db_engine() -> Engine:
    """Create SQLAlchemy engine with connection pooling."""
    conn_string = get_db_connection_string()
    return create_engine(
        conn_string,
        pool_size=5,
        max_overflow=10,
        pool_timeout=30,
        pool_recycle=1800,
    )


def ensure_schema(engine: Engine) -> None:
    """Create tables, indexes, and view if they do not exist."""
    with engine.begin() as conn:
        for statement in SCHEMA_SQL.split(";"):
            stmt = statement.strip()
            if stmt:
                conn.execute(text(stmt))


def _boolify(val: Any) -> Optional[bool]:
    """Normalize bool-like values from SDR into real booleans."""
    if isinstance(val, bool):
        return val
    if val is None:
        return None
    if isinstance(val, (int, float)) and not pd.isna(val):
        return bool(val)
    try:
        s = str(val).strip().lower()
    except Exception:
        return None
    if s in {"true", "t", "yes", "y", "1"}:
        return True
    if s in {"false", "f", "no", "n", "0"}:
        return False
    return None


def _pythonify(val: Any) -> Any:
    """Convert numpy/pandas scalars to plain python types for JSONB."""
    if val is None:
        return None
    if isinstance(val, (list, tuple, set)):
        return [_pythonify(v) for v in val]
    if isinstance(val, dict):
        return {k: _pythonify(v) for k, v in val.items()}
    if isinstance(val, np.ndarray):
        if val.size == 0:
            return None
        return [_pythonify(v) for v in val.tolist()]
    try:
        if pd.isna(val):
            return None
    except Exception:
        # pd.isna may not like arbitrary containers
        pass
    if isinstance(val, (pd.Timestamp,)):
        return val.isoformat()
    if isinstance(val, (pd.Timedelta,)):
        return val.total_seconds()
    if hasattr(val, "item"):
        try:
            return val.item()
        except Exception:
            pass
    return val


def _to_jsonable(val: Any) -> Any:
    """Recursively make a value JSON-serializable and strip NaNs."""
    if val is None:
        return None
    if isinstance(val, (pd.Timestamp,)):
        if pd.isna(val):
            return None
        return val.isoformat()
    if isinstance(val, (pd.Timedelta,)):
        if pd.isna(val):
            return None
        return val.total_seconds()
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
    if isinstance(val, (list, tuple, set)):
        return [_to_jsonable(v) for v in val]
    if isinstance(val, dict):
        return {k: _to_jsonable(v) for k, v in val.items()}
    if isinstance(val, np.ndarray):
        if val.size == 0:
            return None
        return [_to_jsonable(v) for v in val.tolist()]
    return val


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
    if isinstance(val, str) and val.strip() == "NaT":
        return None
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


def normalize_dataframe(df: pd.DataFrame) -> pd.DataFrame:
    """Clean basic types so downstream inserts are predictable."""
    out = df.copy()

    for col in NUMERIC_COLUMNS:
        if col in out.columns:
            out[col] = pd.to_numeric(out[col], errors="coerce")

    for col in BOOL_COLUMNS:
        if col in out.columns:
            out[col] = out[col].apply(_boolify)

    for col in TIMESTAMP_COLUMNS:
        if col in out.columns:
            out[col] = pd.to_datetime(out[col], errors="coerce", utc=True)

    for col in DATE_COLUMNS:
        if col in out.columns:
            out[col] = pd.to_datetime(out[col], errors="coerce").dt.date

    # Ensure package_id exists even for outrights
    if "package_id" not in out.columns:
        out["package_id"] = None

    mask_no_pkg = out["package_id"].isna() | (out["package_id"] == "")
    if mask_no_pkg.any():
        out.loc[mask_no_pkg, "package_id"] = out.loc[mask_no_pkg, "trade_id"].apply(lambda x: f"OUTRIGHT-{x}")
        if "package_type" in out.columns:
            out.loc[mask_no_pkg, "package_type"] = "OUTRIGHT"
        else:
            out["package_type"] = "OUTRIGHT"

    out["package_id"] = out["package_id"].astype(str)
    return out


def _consistent_value(series: pd.Series) -> Any:
    """Return a single value if all non-null entries are identical."""

    def _non_null_values(s: pd.Series) -> list[Any]:
        vals: list[Any] = []
        for v in s.tolist():
            if v is None:
                continue
            if isinstance(v, (list, tuple, dict, set)):
                vals.append(v)
                continue
            if isinstance(v, np.ndarray):
                if v.size == 0:
                    continue
                vals.append(v)
                continue
            try:
                if pd.isna(v):
                    continue
            except Exception:
                # pd.isna can choke on some object dtypes; treat as non-null
                pass
            vals.append(v)
        return vals

    def _safe_equal(a: Any, b: Any) -> bool:
        if isinstance(a, list) and isinstance(b, list):
            return len(a) == len(b) and all(_safe_equal(x, y) for x, y in zip(a, b))
        if isinstance(a, tuple) and isinstance(b, tuple):
            return len(a) == len(b) and all(_safe_equal(x, y) for x, y in zip(a, b))
        if isinstance(a, dict) and isinstance(b, dict):
            return a == b
        return a == b

    vals = _non_null_values(series)
    if not vals:
        return None
    first = vals[0]
    if all(_safe_equal(first, v) for v in vals[1:]):
        return _pythonify(first)
    return None


def _mean_numeric(series: pd.Series) -> Optional[float]:
    vals = pd.to_numeric(series, errors="coerce")
    if not vals.notna().any():
        return None
    return float(vals.mean(skipna=True))


def _median_numeric(series: pd.Series) -> Optional[float]:
    vals = pd.to_numeric(series, errors="coerce")
    if not vals.notna().any():
        return None
    return float(vals.median(skipna=True))


def build_package_metrics(package_type: str, group: pd.DataFrame) -> Dict[str, Any]:
    metrics: Dict[str, Any] = {}

    metrics["package_trade_ids"] = [
        str(v)
        for v in group.get("trade_id", pd.Series(dtype=object)).dropna().astype("string").tolist()
    ]
    metrics["package_types"] = sorted(
        {
            str(v)
            for v in group.get("package_type", pd.Series(dtype=object))
            .dropna()
            .astype("string")
            .tolist()
            if str(v)
        }
    )
    metrics["platform_set"] = sorted(
        {
            str(v)
            for v in group.get("platform_identifier", pd.Series(dtype=object))
            .dropna()
            .astype("string")
            .tolist()
            if str(v)
        }
    )

    metrics["is_mac_any"] = bool(
        group.get("is_mac", pd.Series(dtype=bool)).fillna(False).astype(bool).any()
    )
    metrics["is_spreadover_any"] = bool(
        group.get("is_spreadover", pd.Series(dtype=bool)).fillna(False).astype(bool).any()
    )
    metrics["is_asset_swap_any"] = bool(
        group.get("is_asset_swap", pd.Series(dtype=bool)).fillna(False).astype(bool).any()
    )
    metrics["matched_ust_any"] = bool(
        group.get("matched_ust_maturity", pd.Series(dtype=bool)).fillna(False).astype(bool).any()
    )

    metrics["invoice_swap_tickers"] = sorted(
        {
            str(v)
            for v in group.get("invoice_swap_ticker", pd.Series(dtype=object))
            .dropna()
            .astype("string")
            .tolist()
            if str(v)
        }
    )

    metrics["risk_mean"] = _mean_numeric(group.get("risk", pd.Series(dtype=float)))
    metrics["risk_median"] = _median_numeric(group.get("risk", pd.Series(dtype=float)))
    metrics["fixed_rate_mean"] = _mean_numeric(group.get("fixed_rate", pd.Series(dtype=float)))

    ts = pd.to_datetime(group.get("execution_timestamp"), errors="coerce", utc=True)
    if ts.notna().any():
        metrics["execution_span_seconds"] = float((ts.max() - ts.min()).total_seconds())
    else:
        metrics["execution_span_seconds"] = None

    return metrics


def build_leg_metrics(row: pd.Series) -> Dict[str, Any]:
    metrics: Dict[str, Any] = {}
    for col in LEG_METRIC_COLUMNS:
        if col in row and pd.notna(row[col]):
            metrics[col] = _pythonify(row[col])
    return metrics


def _sum_numeric(series: pd.Series) -> Optional[float]:
    vals = pd.to_numeric(series, errors="coerce")
    if not vals.notna().any():
        return None
    return float(vals.sum(skipna=True))


def build_packages_dataframe(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame()

    records: list[Dict[str, Any]] = []
    for package_id, group in df.groupby("package_id", sort=False):
        g = group.sort_values(["execution_timestamp", "trade_id"])
        notional = pd.to_numeric(g.get("notional", pd.Series(dtype=float)), errors="coerce")
        risk = pd.to_numeric(g.get("risk", pd.Series(dtype=float)), errors="coerce")
        fixed = pd.to_numeric(g.get("fixed_rate", pd.Series(dtype=float)), errors="coerce")
        abs_notional = notional.abs()

        pkg_type_series = g["package_type"].dropna()
        pkg_type = _consistent_value(g["package_type"]) or (
            pkg_type_series.iloc[0] if not pkg_type_series.empty else "OUTRIGHT"
        )
        execution_start = g["execution_timestamp"].min()
        execution_end = g["execution_timestamp"].max()
        as_of_date = execution_start.date() if pd.notna(execution_start) else None

        weighted_fixed_rate = None
        denom = abs_notional.sum(skipna=True)
        if denom and not pd.isna(denom) and denom > 0:
            weighted_fixed_rate = float((abs_notional * fixed).sum(skipna=True) / denom)

        record = {
            "package_id": package_id,
            "package_type": pkg_type,
            "package_source": "AUTO",
            "manual_link_id": None,
            "as_of_date": as_of_date,
            "execution_start": execution_start,
            "execution_end": execution_end,
            "expiration_date": _consistent_value(g["expiration_date"]),
            "effective_date": _consistent_value(g["effective_date"]),
            "tenor_years": _consistent_value(g["tenor_years"]),
            "tenor_label": _consistent_value(g["tenor_label"]),
            "forward_start_years": _consistent_value(g["forward_start_years"]),
            "forward_label": _consistent_value(g["forward_label"]),
            "is_forward": _consistent_value(g["is_forward"]) if "is_forward" in g else None,
            "legs_count": len(g),
            "total_notional": _sum_numeric(notional),
            "gross_notional": _sum_numeric(abs_notional),
            "total_risk": _sum_numeric(risk),
            "gross_risk": _sum_numeric(risk.abs()),
            "weighted_fixed_rate": weighted_fixed_rate,
            "min_fixed_rate": _pythonify(fixed.min(skipna=True) if fixed.notna().any() else None),
            "max_fixed_rate": _pythonify(fixed.max(skipna=True) if fixed.notna().any() else None),
            "package_indicator": _consistent_value(g["package_indicator"]) if "package_indicator" in g else None,
            "package_transaction_spread": _consistent_value(g["package_transaction_spread"]) if "package_transaction_spread" in g else None,
        }

        record["package_metrics"] = build_package_metrics(pkg_type, g)
        records.append(record)

    return pd.DataFrame(records)


def build_legs_dataframe(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame()

    legs: list[Dict[str, Any]] = []
    for _, group in df.groupby("package_id", sort=False):
        g = group.sort_values(["execution_timestamp", "trade_id"])
        for idx, (_, row) in enumerate(g.iterrows()):
            rec: Dict[str, Any] = {
                "trade_id": str(row.get("trade_id")),
                "package_id": row.get("package_id"),
                "leg_order": idx,
                "event_action": row.get("event_action"),
                "execution_timestamp": row.get("execution_timestamp"),
                "effective_date": row.get("effective_date"),
                "expiration_date": row.get("expiration_date"),
                "product_type": row.get("product_type"),
                "trade_label": row.get("trade_label"),
                "tenor_years": row.get("tenor_years"),
                "tenor_label": row.get("tenor_label"),
                "forward_start_years": row.get("forward_start_years"),
                "forward_label": row.get("forward_label"),
                "is_forward": row.get("is_forward"),
                "notional": row.get("notional"),
                "notional_currency": row.get("notional_currency"),
                "is_notional_capped": row.get("is_notional_capped"),
                "estimated_pv01": row.get("estimated_pv01"),
                "risk": row.get("risk"),
                "fixed_rate": row.get("fixed_rate"),
                "cleared": row.get("cleared"),
                "platform_identifier": row.get("platform_identifier"),
                "package_type": row.get("package_type"),
                "package_indicator": row.get("package_indicator"),
                "package_transaction_spread": row.get("package_transaction_spread"),
                "matched_ust_maturity": row.get("matched_ust_maturity"),
                "ust_cusip": row.get("ust_cusip"),
                "swap_maturity_date": row.get("swap_maturity_date"),
                "matched_ust_maturity_trade_confidence": row.get("matched_ust_maturity_trade_confidence"),
                "invoice_swap_ticker": row.get("invoice_swap_ticker"),
                "is_mac": row.get("is_mac"),
                "is_spreadover": row.get("is_spreadover"),
                "is_asset_swap": row.get("is_asset_swap"),
                "manual_link_id": None,
                "is_manually_linked": False,
            }
            rec["leg_metrics"] = build_leg_metrics(row)
            legs.append(rec)

    return pd.DataFrame(legs)


def upsert_dataframe(
    df: pd.DataFrame,
    engine: Engine,
    table_name: str,
    conflict_cols: Iterable[str],
    update_cols: Iterable[str],
    json_cols: Optional[Iterable[str]] = None,
    batch_size: int = 10_000,
    progress_desc: Optional[str] = None,
) -> int:
    """Generic upsert helper using INSERT .. ON CONFLICT .. DO UPDATE."""
    if df.empty:
        return 0

    json_cols_set = set(json_cols or [])

    records = df.to_dict(orient="records")
    # Normalize values for psycopg and serialize JSON columns to strings.
    for rec in records:
        for col, val in list(rec.items()):
            if col in json_cols_set:
                rec[col] = json.dumps(_to_jsonable(val), default=str)
            else:
                rec[col] = _to_db_value(val)
    all_cols = list(records[0].keys())

    col_list = ", ".join(all_cols)
    placeholders = ", ".join([f":{c}" for c in all_cols])
    updates = ", ".join([f"{c} = EXCLUDED.{c}" for c in update_cols])
    conflict_clause = ", ".join(conflict_cols)

    total = len(records)
    desc = progress_desc or f"Writing {table_name}"

    # Fast path for Postgres: execute_values batches are much faster than generic executemany.
    try:
        from psycopg2.extras import execute_values
    except Exception:
        execute_values = None

    if execute_values is not None:
        upsert_sql = f"""
            INSERT INTO {table_name} ({col_list})
            VALUES %s
            ON CONFLICT ({conflict_clause}) DO UPDATE
            SET {updates},
                updated_at = NOW()
        """
        raw_conn = engine.raw_connection()
        try:
            with raw_conn.cursor() as cur:
                for start_idx in tqdm(range(0, total, batch_size), desc=desc, unit="batch"):
                    batch = records[start_idx : start_idx + batch_size]
                    values = [tuple(rec[c] for c in all_cols) for rec in batch]
                    execute_values(cur, upsert_sql, values, page_size=min(len(values), 2_000))
            raw_conn.commit()
        except Exception:
            raw_conn.rollback()
            raise
        finally:
            raw_conn.close()
        return total

    # Fallback path if psycopg2 fast helpers are unavailable.
    sql = text(
        f"""
        INSERT INTO {table_name} ({col_list})
        VALUES ({placeholders})
        ON CONFLICT ({conflict_clause}) DO UPDATE
        SET {updates},
            updated_at = NOW()
        """
    )
    with engine.begin() as conn:
        for start_idx in tqdm(range(0, total, batch_size), desc=desc, unit="batch"):
            batch = records[start_idx : start_idx + batch_size]
            conn.execute(sql, batch)
    return total


def record_ingestion_run(
    engine: Engine,
    *,
    start: pd.Timestamp,
    end: pd.Timestamp,
    rows_raw: int,
    packages_written: int,
    legs_written: int,
) -> None:
    with engine.begin() as conn:
        conn.execute(
            text(
                f"""
                INSERT INTO {RUNS_TABLE} (start_ts, end_ts, rows_raw, packages_written, legs_written)
                VALUES (:start_ts, :end_ts, :rows_raw, :packages_written, :legs_written)
                """
            ),
            {
                "start_ts": start,
                "end_ts": end,
                "rows_raw": rows_raw,
                "packages_written": packages_written,
                "legs_written": legs_written,
            },
        )


def build_classification_dataframe(
    start: pd.Timestamp,
    end: pd.Timestamp,
    cache_path: str,
    ignore_cache: bool = False,
    only_newt: bool = True,
) -> pd.DataFrame:
    """
    Build the USD swap classification DataFrame at leg grain.

    We deliberately use merge_package_legs=False so packages retain one row per leg.
    """
    from SDRUtils.products.usd.usd_swaps import USD_SwapProduct

    swaps = USD_SwapProduct()
    df = swaps.build_classification_dataframe(
        start=start,
        end=end,
        cache_path=cache_path,
        ignore_cache=ignore_cache,
        merge_package_legs=False,
        detect_curve=True,
        detect_fly=True,
        detect_mms=True,
        detect_invoice=True,
        detect_mac=True,
        detect_spreadover=True,
        only_newt=only_newt,
    )
    return df


def delete_date_range(
    engine: Engine,
    start: pd.Timestamp,
    end: pd.Timestamp,
) -> tuple[int, int]:
    """
    Delete all packages and legs within a date range before re-ingestion.

    Returns (packages_deleted, legs_deleted).
    """
    with engine.begin() as conn:
        # Delete legs first (FK constraint)
        legs_result = conn.execute(
            text(
                f"""
                DELETE FROM {LEGS_TABLE}
                WHERE package_id IN (
                    SELECT package_id FROM {PACKAGES_TABLE}
                    WHERE execution_start >= :start AND execution_start < :end
                )
            """
            ),
            {"start": start, "end": end},
        )
        legs_deleted = legs_result.rowcount

        # Then delete packages
        packages_result = conn.execute(
            text(
                f"""
                DELETE FROM {PACKAGES_TABLE}
                WHERE execution_start >= :start AND execution_start < :end
            """
            ),
            {"start": start, "end": end},
        )
        packages_deleted = packages_result.rowcount

    return packages_deleted, legs_deleted


def _to_utc_timestamp(value: Any) -> pd.Timestamp:
    ts = pd.Timestamp(value)
    if ts.tzinfo is None:
        return ts.tz_localize("UTC")
    return ts.tz_convert("UTC")


def _resolve_end_of_day_fetch_timestamp(value: Any, market_timezone: str) -> pd.Timestamp:
    """Resolve timestamp to market-local end-of-day, returned in UTC."""
    end_utc = _to_utc_timestamp(value)
    end_local = end_utc.tz_convert(market_timezone)
    end_of_day_local = end_local.normalize() + pd.Timedelta(days=1) - pd.Timedelta(microseconds=1)
    return end_of_day_local.tz_convert("UTC")


def _resolve_start_of_day_fetch_timestamp(value: Any, market_timezone: str) -> pd.Timestamp:
    """Resolve timestamp to market-local start-of-day, returned in UTC."""
    start_utc = _to_utc_timestamp(value)
    start_local = start_utc.tz_convert(market_timezone)
    start_of_day_local = start_local.normalize()
    return start_of_day_local.tz_convert("UTC")


def _resolve_cache_path(cache_path: Optional[str]) -> str:
    return cache_path or os.getenv("SDR_CACHE_PATH", "./sdr_cache")


def get_last_ingested_timestamp(engine: Engine) -> Optional[pd.Timestamp]:
    """Get the most recent execution timestamp written to legs."""
    with engine.connect() as conn:
        result = conn.execute(text(f"SELECT MAX(execution_timestamp) FROM {LEGS_TABLE}")).scalar()
    return _to_utc_timestamp(result) if result is not None else None


def get_last_run_timestamp(engine: Engine) -> Optional[pd.Timestamp]:
    """Get the most recent end_ts written to ingestion runs."""
    with engine.connect() as conn:
        result = conn.execute(text(f"SELECT MAX(end_ts) FROM {RUNS_TABLE}")).scalar()
    return _to_utc_timestamp(result) if result is not None else None


def get_ingestion_cursor_timestamp(engine: Engine) -> Optional[pd.Timestamp]:
    """
    Cursor for incremental runs.

    Uses the latest timestamp between legs.execution_timestamp and runs.end_ts so
    the service can advance even when a window has zero trades.
    """
    last_trade_ts = get_last_ingested_timestamp(engine)
    last_run_ts = get_last_run_timestamp(engine)
    if last_trade_ts is None:
        return last_run_ts
    if last_run_ts is None:
        return last_trade_ts
    return max(last_trade_ts, last_run_ts)


def cleanup_orphaned_packages(engine: Engine) -> int:
    """Delete packages that have no legs (orphaned by reclassification)."""
    with engine.begin() as conn:
        result = conn.execute(
            text(
                f"""
                DELETE FROM {PACKAGES_TABLE} p
                WHERE NOT EXISTS (
                    SELECT 1 FROM {LEGS_TABLE} l
                    WHERE l.package_id = p.package_id
                )
            """
            )
        )
    return result.rowcount


def upsert_transformed_frames(df: pd.DataFrame, engine: Engine) -> tuple[pd.DataFrame, pd.DataFrame, int, int]:
    cleaned = normalize_dataframe(df)
    packages_df = build_packages_dataframe(cleaned)
    legs_df = build_legs_dataframe(cleaned)

    packages_written = upsert_dataframe(
        packages_df,
        engine,
        PACKAGES_TABLE,
        conflict_cols=["package_id"],
        update_cols=PACKAGE_UPSERT_UPDATE_COLUMNS,
        json_cols=["package_metrics"],
        progress_desc="Writing packages",
    )

    legs_written = upsert_dataframe(
        legs_df,
        engine,
        LEGS_TABLE,
        conflict_cols=["trade_id"],
        update_cols=LEG_UPSERT_UPDATE_COLUMNS,
        json_cols=["leg_metrics"],
        progress_desc="Writing legs",
    )

    return packages_df, legs_df, packages_written, legs_written


def ingest_to_postgres(
    df: pd.DataFrame,
    engine: Engine,
    start: pd.Timestamp,
    end: pd.Timestamp,
) -> tuple[pd.DataFrame, pd.DataFrame, int, int]:
    pkgs_del, legs_del = delete_date_range(engine, start, end)
    if pkgs_del or legs_del:
        print(f"Deleted {pkgs_del} packages, {legs_del} legs in range")

    packages_df, legs_df, packages_written, legs_written = upsert_transformed_frames(df, engine)

    record_ingestion_run(
        engine,
        start=start,
        end=end,
        rows_raw=len(df),
        packages_written=packages_written,
        legs_written=legs_written,
    )

    return packages_df, legs_df, packages_written, legs_written


def print_summary(
    raw_df: pd.DataFrame,
    packages_df: pd.DataFrame,
    legs_df: pd.DataFrame,
    packages_written: int,
    legs_written: int,
) -> None:
    print("\n" + "=" * 60)
    print("INGESTION SUMMARY")
    print("=" * 60)

    print(f"Classification rows: {len(raw_df)}")
    if not raw_df.empty and "package_type" in raw_df.columns:
        print("By package_type:")
        for ptype, count in raw_df["package_type"].value_counts().items():
            print(f"  {ptype}: {count}")

    print("\nTransformed:")
    print(f"  Packages dataframe: {len(packages_df)}")
    print(f"  Legs dataframe: {len(legs_df)}")

    print("\nDatabase (upsert):")
    print(f"  Packages written: {packages_written}")
    print(f"  Legs written: {legs_written}")

    if not packages_df.empty:
        total_notional_series = (
            pd.to_numeric(packages_df["total_notional"], errors="coerce")
            if "total_notional" in packages_df.columns
            else pd.Series(dtype=float)
        )
        total_risk_series = (
            pd.to_numeric(packages_df["total_risk"], errors="coerce")
            if "total_risk" in packages_df.columns
            else pd.Series(dtype=float)
        )
        total_notional = float(total_notional_series.sum(skipna=True))
        total_risk = float(total_risk_series.sum(skipna=True))
        print("\nNotional / risk:")
        print(f"  Total notional: {total_notional:,.0f}")
        print(f"  Total risk: {total_risk:,.0f}")
        print(f"  Avg legs per package: {packages_df['legs_count'].mean():.2f}")


def main(
    start: Optional[pd.Timestamp] = None,
    end: Optional[pd.Timestamp] = None,
    days: int = 7,
    cache_path: Optional[str] = None,
    ignore_cache: bool = False,
    only_newt: bool = False,
    dry_run: bool = False,
) -> None:
    if end is None:
        end = pd.Timestamp.now(tz="UTC")
    else:
        end = _to_utc_timestamp(end)
    if start is None:
        start = end - timedelta(days=days)
    else:
        start = _to_utc_timestamp(start)
    if start > end:
        raise ValueError(f"Start timestamp must be <= end timestamp. Got start={start}, end={end}")

    cache_path = _resolve_cache_path(cache_path)

    print("USD swap ingestion")
    print(f"  Range: {start} -> {end}")
    print(f"  Cache: {cache_path}")
    print(f"  Ignore cache: {ignore_cache}")
    print(f"  Only NEWT/TRAD: {only_newt}")
    print(f"  Dry run: {dry_run}")
    print()

    print("Building classification dataframe...")
    raw_df = build_classification_dataframe(
        start=start,
        end=end,
        cache_path=cache_path,
        ignore_cache=ignore_cache,
        only_newt=only_newt,
    )

    if raw_df.empty:
        print("No USD swap trades found in date range.")
        return

    if dry_run:
        print("Dry run enabled; skipping database writes.")
        cleaned = normalize_dataframe(raw_df)
        packages_df = build_packages_dataframe(cleaned)
        legs_df = build_legs_dataframe(cleaned)
        print_summary(raw_df, packages_df, legs_df, 0, 0)
        return

    engine = create_db_engine()
    ensure_schema(engine)

    packages_df, legs_df, packages_written, legs_written = ingest_to_postgres(
        raw_df,
        engine,
        start=start,
        end=end,
    )

    print_summary(raw_df, packages_df, legs_df, packages_written, legs_written)


def ingest_incremental_once(
    engine: Engine,
    *,
    cache_path: str,
    ignore_cache: bool = False,
    only_newt: bool = False,
    dry_run: bool = False,
    cleanup_orphans: bool = True,
    initial_lookback_minutes: int = 24 * 60,
    overlap_seconds: int = 0,
    force_fetch_end_of_day: bool = False,
    force_fetch_full_market_day: bool = False,
    market_timezone: str = "America/New_York",
) -> None:
    if initial_lookback_minutes < 0:
        raise ValueError(f"initial_lookback_minutes must be >= 0, got {initial_lookback_minutes}")
    if overlap_seconds < 0:
        raise ValueError(f"overlap_seconds must be >= 0, got {overlap_seconds}")

    cursor_ts = get_ingestion_cursor_timestamp(engine)
    end = pd.Timestamp.now(tz="UTC")

    if cursor_ts is None:
        start = end - timedelta(minutes=initial_lookback_minutes)
        print(f"No ingestion cursor found; bootstrapping with {initial_lookback_minutes} minutes")
    else:
        start = cursor_ts - timedelta(seconds=overlap_seconds)

    if start > end:
        start = end

    fetch_start = start
    fetch_end = end
    if force_fetch_end_of_day or force_fetch_full_market_day:
        try:
            if force_fetch_full_market_day:
                fetch_start = _resolve_start_of_day_fetch_timestamp(end, market_timezone)
            fetch_end = _resolve_end_of_day_fetch_timestamp(end, market_timezone)
        except Exception as exc:
            raise ValueError(f"Invalid market timezone: {market_timezone}") from exc

    print("Incremental USD swap ingestion")
    print(f"  Last cursor: {cursor_ts}")
    print(f"  Range: {start} -> {end}")
    if force_fetch_full_market_day:
        print(f"  Classifier fetch range (full market day {market_timezone}): {fetch_start} -> {fetch_end}")
    elif force_fetch_end_of_day:
        print(f"  Classifier fetch end (forced EOD {market_timezone}): {fetch_end}")
    print(f"  Overlap: {overlap_seconds} seconds")
    print(f"  Cache: {cache_path}")
    print(f"  Ignore cache: {ignore_cache}")
    print(f"  Only NEWT/TRAD: {only_newt}")
    print(f"  Dry run: {dry_run}")
    print()

    print("Building classification dataframe...")
    raw_df = build_classification_dataframe(
        start=fetch_start,
        end=fetch_end,
        cache_path=cache_path,
        ignore_cache=ignore_cache,
        only_newt=only_newt,
    )

    if raw_df.empty:
        print("No trades found in range.")
        if not dry_run:
            record_ingestion_run(
                engine,
                start=start,
                end=end,
                rows_raw=0,
                packages_written=0,
                legs_written=0,
            )
        return

    print(f"Found {len(raw_df)} trades in range")

    if dry_run:
        print("Dry run enabled; skipping database writes.")
        cleaned = normalize_dataframe(raw_df)
        packages_df = build_packages_dataframe(cleaned)
        legs_df = build_legs_dataframe(cleaned)
        print_summary(raw_df, packages_df, legs_df, 0, 0)
        return

    packages_df, legs_df, packages_written, legs_written = upsert_transformed_frames(raw_df, engine)
    record_ingestion_run(
        engine,
        start=start,
        end=end,
        rows_raw=len(raw_df),
        packages_written=packages_written,
        legs_written=legs_written,
    )

    if cleanup_orphans:
        orphans_deleted = cleanup_orphaned_packages(engine)
        if orphans_deleted:
            print(f"Cleaned up {orphans_deleted} orphaned packages")

    print_summary(raw_df, packages_df, legs_df, packages_written, legs_written)


def main_incremental(
    cache_path: Optional[str] = None,
    ignore_cache: bool = False,
    only_newt: bool = False,
    dry_run: bool = False,
    cleanup_orphans: bool = True,
    initial_lookback_minutes: int = 24 * 60,
    overlap_seconds: int = 0,
) -> None:
    cache_path = _resolve_cache_path(cache_path)
    engine = create_db_engine()
    ensure_schema(engine)
    ingest_incremental_once(
        engine,
        cache_path=cache_path,
        ignore_cache=ignore_cache,
        only_newt=only_newt,
        dry_run=dry_run,
        cleanup_orphans=cleanup_orphans,
        initial_lookback_minutes=initial_lookback_minutes,
        overlap_seconds=overlap_seconds,
    )


def main_service(
    interval_seconds: int = 120,
    cache_path: Optional[str] = None,
    ignore_cache: bool = False,
    only_newt: bool = False,
    dry_run: bool = False,
    cleanup_orphans: bool = True,
    initial_lookback_minutes: int = 24 * 60,
    overlap_seconds: int = 0,
    smart_intervals: bool = True,
    active_interval_seconds: int = 120,
    inactive_interval_seconds: int = 10 * 60,
    active_window_start: str = "07:00",
    active_window_end: str = "18:00",
    market_timezone: str = "America/New_York",
    weekdays_only: bool = True,
    max_iterations: Optional[int] = None,
    stop_on_error: bool = False,
) -> None:
    if interval_seconds <= 0:
        raise ValueError(f"interval_seconds must be > 0, got {interval_seconds}")
    if active_interval_seconds <= 0:
        raise ValueError(f"active_interval_seconds must be > 0, got {active_interval_seconds}")
    if inactive_interval_seconds <= 0:
        raise ValueError(f"inactive_interval_seconds must be > 0, got {inactive_interval_seconds}")
    if max_iterations is not None and max_iterations <= 0:
        raise ValueError(f"max_iterations must be > 0 when provided, got {max_iterations}")

    active_start_minutes = _parse_hhmm_to_minutes(active_window_start, "active-window-start")
    active_end_minutes = _parse_hhmm_to_minutes(active_window_end, "active-window-end")
    try:
        pd.Timestamp.now(tz="UTC").tz_convert(market_timezone)
    except Exception as exc:
        raise ValueError(f"Invalid market timezone: {market_timezone}") from exc

    cache_path = _resolve_cache_path(cache_path)
    engine = create_db_engine()
    ensure_schema(engine)

    print("Starting USD swap ingestion service")
    print(f"  Base interval: {interval_seconds} seconds")
    print(f"  Cache: {cache_path}")
    print(f"  Ignore cache: {ignore_cache}")
    print(f"  Only NEWT/TRAD: {only_newt}")
    print(f"  Dry run: {dry_run}")
    print(f"  Initial lookback: {initial_lookback_minutes} minutes")
    print(f"  Overlap: {overlap_seconds} seconds")
    if smart_intervals:
        print("  Smart intervals: enabled")
        print(f"  Active interval: {active_interval_seconds} seconds")
        print(f"  Inactive interval: {inactive_interval_seconds} seconds")
        print(f"  Active window: {active_window_start} - {active_window_end} ({market_timezone})")
        print(f"  Weekdays only: {weekdays_only}")
    else:
        print("  Smart intervals: disabled")
    if max_iterations:
        print(f"  Max iterations: {max_iterations}")
    print()

    iteration = 0
    while True:
        iteration += 1
        cycle_start_wall = pd.Timestamp.now(tz="UTC")
        cycle_start_monotonic = time.monotonic()
        print(f"[{cycle_start_wall.isoformat()}] Service cycle {iteration}")

        try:
            ingest_incremental_once(
                engine,
                cache_path=cache_path,
                ignore_cache=ignore_cache,
                only_newt=only_newt,
                dry_run=dry_run,
                cleanup_orphans=cleanup_orphans,
                initial_lookback_minutes=initial_lookback_minutes,
                overlap_seconds=overlap_seconds,
                force_fetch_end_of_day=True,
                force_fetch_full_market_day=True,
                market_timezone=market_timezone,
            )
        except Exception as exc:
            print(f"Service cycle {iteration} failed: {exc}")
            if stop_on_error:
                raise

        if max_iterations is not None and iteration >= max_iterations:
            print("Reached max iterations; exiting service loop.")
            break

        now_utc = pd.Timestamp.now(tz="UTC")
        interval_in_effect = interval_seconds
        interval_label = "fixed interval"
        if smart_intervals:
            local_now = now_utc.tz_convert(market_timezone)
            is_active = _is_in_active_window(
                local_now=local_now,
                active_start_minutes=active_start_minutes,
                active_end_minutes=active_end_minutes,
                weekdays_only=weekdays_only,
            )
            interval_in_effect = active_interval_seconds if is_active else inactive_interval_seconds
            interval_label = "active market hours" if is_active else "off-hours"

        elapsed = time.monotonic() - cycle_start_monotonic
        sleep_seconds = max(0.0, interval_in_effect - elapsed)
        print(f"Sleeping {sleep_seconds:.1f} seconds ({interval_label}, interval={interval_in_effect}s)...\n")
        time.sleep(sleep_seconds)


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None or raw == "":
        return default
    return int(raw)


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None or raw == "":
        return default
    return raw.strip().lower() in {"1", "true", "t", "yes", "y", "on"}


def _parse_hhmm_to_minutes(value: str, arg_name: str) -> int:
    try:
        hour_str, minute_str = value.split(":", maxsplit=1)
        hour = int(hour_str)
        minute = int(minute_str)
    except Exception as exc:
        raise ValueError(f"Invalid --{arg_name}: {value}. Expected HH:MM.") from exc
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        raise ValueError(f"Invalid --{arg_name}: {value}. Expected HH:MM in 24h format.")
    return hour * 60 + minute


def _is_in_active_window(
    *,
    local_now: pd.Timestamp,
    active_start_minutes: int,
    active_end_minutes: int,
    weekdays_only: bool,
) -> bool:
    if weekdays_only and local_now.weekday() >= 5:
        return False

    now_minutes = local_now.hour * 60 + local_now.minute
    if active_start_minutes <= active_end_minutes:
        return active_start_minutes <= now_minutes < active_end_minutes
    return now_minutes >= active_start_minutes or now_minutes < active_end_minutes


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Ingest USD swap classifications into SwapPulse Postgres.")
    parser.add_argument(
        "--mode",
        choices=("range", "incremental", "service"),
        default=os.getenv("SWAPPULSE_INGEST_MODE", "incremental"),
        help="range=explicit date range, incremental=single catch-up run, service=continuous loop.",
    )
    parser.add_argument("--days", type=int, default=7, help="Days to look back when --start is not provided in range mode.")
    parser.add_argument("--start", type=str, help="Start timestamp (e.g. 2026-02-04 or 2026-02-04T12:00:00Z).")
    parser.add_argument("--end", type=str, help="End timestamp (e.g. 2026-02-04 or 2026-02-04T12:00:00Z).")
    parser.add_argument("--cache-path", type=str, help="Path to SDR cache directory.")
    parser.add_argument(
        "--ignore-cache",
        action="store_true",
        help="Ignore cached classifications (all modes). Default uses cache when available.",
    )
    parser.add_argument("--only-newt", dest="only_newt", action="store_true", help="Only include NEWT/TRAD events.")
    parser.add_argument("--no-only-newt", dest="only_newt", action="store_false", help=argparse.SUPPRESS)
    parser.add_argument(
        "--smart-intervals",
        dest="smart_intervals",
        action="store_true",
        help="Service mode: use active/off-hours intervals by market time window.",
    )
    parser.add_argument(
        "--no-smart-intervals",
        dest="smart_intervals",
        action="store_false",
        help="Service mode: always use --interval-seconds.",
    )
    parser.add_argument(
        "--weekdays-only",
        dest="weekdays_only",
        action="store_true",
        help="Service mode: active window applies only Monday-Friday.",
    )
    parser.add_argument(
        "--include-weekends",
        dest="weekdays_only",
        action="store_false",
        help="Service mode: active window also applies on weekends.",
    )
    parser.set_defaults(
        only_newt=False,
        smart_intervals=_env_bool("SWAPPULSE_INGEST_SMART_INTERVALS", True),
        weekdays_only=_env_bool("SWAPPULSE_INGEST_WEEKDAYS_ONLY", True),
    )
    parser.add_argument("--dry-run", action="store_true", help="Build dataframes but skip database writes.")
    parser.add_argument(
        "--interval-seconds",
        type=int,
        default=_env_int("SWAPPULSE_INGEST_INTERVAL_SECONDS", 120),
        help="Service mode fallback polling interval when smart intervals are disabled.",
    )
    parser.add_argument(
        "--active-interval-seconds",
        type=int,
        default=_env_int("SWAPPULSE_INGEST_ACTIVE_INTERVAL_SECONDS", 120),
        help="Service mode interval during active market window.",
    )
    parser.add_argument(
        "--inactive-interval-seconds",
        type=int,
        default=_env_int("SWAPPULSE_INGEST_INACTIVE_INTERVAL_SECONDS", 10 * 60),
        help="Service mode interval outside active market window.",
    )
    parser.add_argument(
        "--active-window-start",
        type=str,
        default=os.getenv("SWAPPULSE_INGEST_ACTIVE_WINDOW_START", "07:00"),
        help="Service mode active window start in HH:MM, market timezone.",
    )
    parser.add_argument(
        "--active-window-end",
        type=str,
        default=os.getenv("SWAPPULSE_INGEST_ACTIVE_WINDOW_END", "18:00"),
        help="Service mode active window end in HH:MM, market timezone.",
    )
    parser.add_argument(
        "--market-timezone",
        type=str,
        default=os.getenv("SWAPPULSE_INGEST_MARKET_TIMEZONE", "America/New_York"),
        help="Service mode market timezone used for active window.",
    )
    parser.add_argument(
        "--initial-lookback-minutes",
        type=int,
        default=_env_int("SWAPPULSE_INGEST_INITIAL_LOOKBACK_MINUTES", 24 * 60),
        help="When cursor is empty, start incremental/service from now minus this many minutes.",
    )
    parser.add_argument(
        "--overlap-seconds",
        type=int,
        default=_env_int("SWAPPULSE_INGEST_OVERLAP_SECONDS", 0),
        help="Subtract this overlap from last cursor before incremental/service fetch.",
    )
    parser.add_argument(
        "--no-cleanup-orphans",
        action="store_true",
        help="Skip orphan package cleanup after incremental writes.",
    )
    parser.add_argument(
        "--max-iterations",
        type=int,
        help="Service mode only: stop after this many cycles.",
    )
    parser.add_argument(
        "--stop-on-error",
        action="store_true",
        help="Service mode only: exit after the first failed cycle.",
    )
    return parser.parse_args()


def _parse_timestamp_arg(raw: Optional[str], arg_name: str) -> Optional[pd.Timestamp]:
    if raw is None:
        return None
    try:
        return _to_utc_timestamp(raw)
    except Exception as exc:
        raise ValueError(f"Invalid --{arg_name} value: {raw}") from exc


if __name__ == "__main__":
    args = parse_args()
    parsed_start = _parse_timestamp_arg(args.start, "start")
    parsed_end = _parse_timestamp_arg(args.end, "end")
    cleanup_orphans = not args.no_cleanup_orphans

    if args.mode == "range":
        main(
            start=parsed_start,
            end=parsed_end,
            days=args.days,
            cache_path=args.cache_path,
            ignore_cache=args.ignore_cache,
            only_newt=args.only_newt,
            dry_run=args.dry_run,
        )
    elif args.mode == "incremental":
        main_incremental(
            cache_path=args.cache_path,
            ignore_cache=args.ignore_cache,
            only_newt=args.only_newt,
            dry_run=args.dry_run,
            cleanup_orphans=cleanup_orphans,
            initial_lookback_minutes=args.initial_lookback_minutes,
            overlap_seconds=args.overlap_seconds,
        )
    else:
        main_service(
            interval_seconds=args.interval_seconds,
            cache_path=args.cache_path,
            ignore_cache=args.ignore_cache,
            only_newt=args.only_newt,
            dry_run=args.dry_run,
            cleanup_orphans=cleanup_orphans,
            initial_lookback_minutes=args.initial_lookback_minutes,
            overlap_seconds=args.overlap_seconds,
            smart_intervals=args.smart_intervals,
            active_interval_seconds=args.active_interval_seconds,
            inactive_interval_seconds=args.inactive_interval_seconds,
            active_window_start=args.active_window_start,
            active_window_end=args.active_window_end,
            market_timezone=args.market_timezone,
            weekdays_only=args.weekdays_only,
            max_iterations=args.max_iterations,
            stop_on_error=args.stop_on_error,
        )


