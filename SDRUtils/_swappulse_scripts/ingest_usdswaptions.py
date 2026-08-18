"""
Swaption data ingestion for SwapPulse.

Goal: persist USD swaption classification output so that packages render as
single rows (with leg drill-down) and outrights remain one row per trade.
The schema uses normalized package/leg tables plus JSONB metrics for
package-type-specific analytics to stay extensible as new detections ship.
"""

from __future__ import annotations

import argparse
import importlib
import json
import math
import os
import sys
import time
from datetime import timedelta
from typing import Any, Dict, Iterable, Optional

import numpy as np
import pandas as pd
from sqlalchemy import create_engine, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.engine import Engine
from tqdm import tqdm

from utils.storage_paths import repo_store


# Table/view names (versioned so we can cut over safely)
PACKAGES_TABLE = "arbs_swaption_packages_v1"
LEGS_TABLE = "arbs_swaption_legs_v1"
RUNS_TABLE = "arbs_swaption_ingestion_runs_v1"
MANUAL_LINKS_TABLE = "arbs_swaption_manual_links_v1"
LINK_HISTORY_TABLE = "arbs_swaption_link_history_v1"
DISPLAY_VIEW_V1 = "arbs_swaption_display_items_v1"
DISPLAY_VIEW_V2 = "arbs_swaption_display_items_v2"
DISPLAY_VIEW = DISPLAY_VIEW_V1

# Package-type-specific metrics to lift into JSONB (avoids wide sparse tables)
PACKAGE_METRIC_COLUMNS: dict[str, tuple[str, ...]] = {
    "STRADDLE": (
        "straddle_bpvol_yr",
        "straddle_fwd_premium",
        "straddle_dv01",
        "straddle_vega01",
        "straddle_gamma01",
        "straddle_theta1d",
        "vega_curve_type",
        "vega_curve_id",
        "vega_curve_legs",
        "vega_curve_vega01",
        "vega_curve_weight",
        "vega_curve_vega_ratio",
        "vega_curve_pricing_method",
    ),
    "RISK_REVERSAL": (
        "rr_atmf",
        "rr_out_strike",
        "rr_skew_bpvol",
        "rr_atm_bpvol",
        "rr_payer_skew",
        "rr_receiver_skew",
        "rr_dv01",
        "rr_wing_dv01",
        "rr_gamma01",
        "rr_vega01",
        "rr_theta1d",
    ),
    "VERTICAL_SPREAD_1x1": (
        "vs_spread_type",
        "vs_atm_strike",
        "vs_otm_strike",
        "vs_strike_width_bps",
        "vs_atm_bpvol_yr",
        "vs_otm_bpvol_yr",
        "vs_vol_spread_bpvol_yr",
        "vs_atm_notional",
        "vs_otm_notional",
        "vs_notional_ratio",
        "vs_net_premium",
        "vs_atm_premium",
        "vs_otm_premium",
        "vs_atm_dv01",
        "vs_atm_gamma01",
        "vs_atm_vega01",
        "vs_atm_theta1d",
        "vs_otm_dv01",
        "vs_otm_gamma01",
        "vs_otm_vega01",
        "vs_otm_theta1d",
        "vs_dv01",
        "vs_gamma01",
        "vs_vega01",
        "vs_theta1d",
        "vs_atm_strike_offset",
        "vs_otm_strike_offset",
    ),
    "VERTICAL_SPREAD_1x2": (
        "vs_spread_type",
        "vs_atm_strike",
        "vs_otm_strike",
        "vs_strike_width_bps",
        "vs_atm_bpvol_yr",
        "vs_otm_bpvol_yr",
        "vs_vol_spread_bpvol_yr",
        "vs_atm_notional",
        "vs_otm_notional",
        "vs_notional_ratio",
        "vs_net_premium",
        "vs_atm_premium",
        "vs_otm_premium",
        "vs_atm_dv01",
        "vs_atm_gamma01",
        "vs_atm_vega01",
        "vs_atm_theta1d",
        "vs_otm_dv01",
        "vs_otm_gamma01",
        "vs_otm_vega01",
        "vs_otm_theta1d",
        "vs_dv01",
        "vs_gamma01",
        "vs_vega01",
        "vs_theta1d",
        "vs_atm_strike_offset",
        "vs_otm_strike_offset",
    ),
    "RECEIVER_LADDER": (
        "ladder_structure",
        "ladder_direction",
        "ladder_strikes",
        "ladder_notionals",
    ),
    "CUSTY_RR_STRANGLE": ("custy_rr_width_bps",),
    "DELTA_HEDGE": (
        "delta_hedge_implied_delta",
        "delta_hedge_swap_trade_id",
        "delta_hedge_swap_fixed_rate",
        "delta_hedge_swap_tenor_years",
        "delta_hedge_swap_notional",
        "delta_hedge_match_window_seconds",
        "delta_hedge_dv01_ratio",
        "delta_hedge_time_diff_seconds",
        "delta_hedge_swap_dv01",
        "delta_hedge_swaption_dv01",
        "delta_hedge_dv01_check",
        # Barbell decomposition columns
        "delta_hedge_match_type",
        "delta_hedge_curve_build",
        "delta_hedge_long_leg_trade_id",
        "delta_hedge_long_leg_tenor",
        "delta_hedge_long_leg_notional",
        "delta_hedge_long_leg_dv01",
        "delta_hedge_short_leg_trade_id",
        "delta_hedge_short_leg_tenor",
        "delta_hedge_short_leg_notional",
        "delta_hedge_short_leg_dv01",
        "delta_hedge_expected_ratio",
        "delta_hedge_observed_ratio",
    ),
}

# Leg-level analytics that are only meaningful for outrights
LEG_METRIC_COLUMNS: tuple[str, ...] = (
    "outright_atmf",
    "outright_strike_offset_bps",
    "outright_strike_offset_rounded_bps",
    "outright_moneyness",
    "outright_bpvol_yr",
    "outright_fwd_premium",
    "outright_dv01",
    "outright_vega01",
    "outright_gamma01",
    "outright_theta1d",
)

NUMERIC_COLUMNS: tuple[str, ...] = (
    "notional",
    "premium",
    "strike",
    "tenor_years",
    "forward_start_years",
    "package_confidence",
    "package_legs_count",
    "package_transaction_price",
    "vega_curve_vega01",
    "vega_curve_weight",
    "vega_curve_vega_ratio",
    "economic_notional",
    "straddle_bpvol_yr",
    "straddle_fwd_premium",
    "straddle_dv01",
    "straddle_vega01",
    "straddle_gamma01",
    "straddle_theta1d",
    "rr_atmf",
    "rr_out_strike",
    "rr_skew_bpvol",
    "rr_atm_bpvol",
    "rr_payer_skew",
    "rr_receiver_skew",
    "rr_dv01",
    "rr_wing_dv01",
    "rr_gamma01",
    "rr_vega01",
    "rr_theta1d",
    "custy_rr_width_bps",
    "delta_hedge_implied_delta",
    "delta_hedge_swap_fixed_rate",
    "delta_hedge_swap_tenor_years",
    "delta_hedge_swap_notional",
    "delta_hedge_match_window_seconds",
    "delta_hedge_dv01_ratio",
    "delta_hedge_time_diff_seconds",
    "delta_hedge_swap_dv01",
    "delta_hedge_swaption_dv01",
    "vs_atm_strike",
    "vs_otm_strike",
    "vs_strike_width_bps",
    "vs_atm_bpvol_yr",
    "vs_otm_bpvol_yr",
    "vs_vol_spread_bpvol_yr",
    "vs_atm_notional",
    "vs_otm_notional",
    "vs_notional_ratio",
    "vs_net_premium",
    "vs_atm_premium",
    "vs_otm_premium",
    "vs_atm_dv01",
    "vs_atm_gamma01",
    "vs_atm_vega01",
    "vs_atm_theta1d",
    "vs_otm_dv01",
    "vs_otm_gamma01",
    "vs_otm_vega01",
    "vs_otm_theta1d",
    "vs_dv01",
    "vs_gamma01",
    "vs_vega01",
    "vs_theta1d",
    "vs_atm_strike_offset",
    "vs_otm_strike_offset",
    "outright_atmf",
    "outright_strike_offset_bps",
    "outright_strike_offset_rounded_bps",
    "outright_bpvol_yr",
    "outright_fwd_premium",
    "outright_dv01",
    "outright_vega01",
    "outright_gamma01",
    "outright_theta1d",
)

BOOL_COLUMNS: tuple[str, ...] = (
    "cleared",
    "package_indicator",
    "is_notional_capped",
    "matched_ust_maturity",
)

TIMESTAMP_COLUMNS: tuple[str, ...] = ("execution_timestamp", "event_timestamp")
DATE_COLUMNS: tuple[str, ...] = (
    "effective_date",
    "expiration_date",
    "underlying_expiration_date",
)

PACKAGE_UPSERT_UPDATE_COLUMNS: tuple[str, ...] = (
    "package_type",
    "as_of_date",
    "execution_start",
    "execution_end",
    "expiration_date",
    "underlying_expiration_date",
    "effective_date",
    "tenor_years",
    "tenor_label",
    "forward_start_years",
    "forward_label",
    "legs_count",
    "total_notional",
    "economic_notional",
    "total_premium",
    "package_indicator",
    "package_transaction_price",
    "package_confidence",
    "package_reason",
    "vega_curve_id",
    "vega_curve_type",
    "vega_curve_vega01",
    "vega_curve_weight",
    "vega_curve_vega_ratio",
    "vega_curve_pricing_method",
    "package_metrics",
)

LEG_UPSERT_UPDATE_COLUMNS: tuple[str, ...] = (
    "package_id",
    "leg_order",
    "event_action",
    "execution_timestamp",
    "event_timestamp",
    "effective_date",
    "expiration_date",
    "underlying_expiration_date",
    "product_type",
    "trade_label",
    "tenor_years",
    "tenor_label",
    "forward_start_years",
    "forward_label",
    "notional",
    "notional_currency",
    "is_notional_capped",
    "strike",
    "premium",
    "exercise_style",
    "cleared",
    "platform_identifier",
    "package_type",
    "package_indicator",
    "package_transaction_price",
    "matched_ust_maturity",
    "invoice_swap_ticker",
    "leg_metrics",
)

# Schema (packages + legs + ingestion runs + display view)
SCHEMA_SQL = f"""
CREATE EXTENSION IF NOT EXISTS pgcrypto;

CREATE TABLE IF NOT EXISTS {PACKAGES_TABLE} (
    package_id TEXT PRIMARY KEY,
    package_type TEXT NOT NULL,
    as_of_date DATE NOT NULL,
    execution_start TIMESTAMPTZ NOT NULL,
    execution_end TIMESTAMPTZ NOT NULL,
    expiration_date DATE,
    underlying_expiration_date DATE,
    effective_date DATE,
    tenor_years NUMERIC,
    tenor_label TEXT,
    forward_start_years NUMERIC,
    forward_label TEXT,
    legs_count INTEGER NOT NULL,
    total_notional NUMERIC,
    economic_notional NUMERIC,
    total_premium NUMERIC,
    package_indicator BOOLEAN,
    package_transaction_price NUMERIC,
    package_confidence NUMERIC,
    package_reason TEXT,
    vega_curve_id TEXT,
    vega_curve_type TEXT,
    vega_curve_vega01 NUMERIC,
    vega_curve_weight NUMERIC,
    vega_curve_vega_ratio NUMERIC,
    vega_curve_pricing_method TEXT,
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
    underlying_expiration_date DATE,
    product_type TEXT,
    trade_label TEXT,
    tenor_years NUMERIC,
    tenor_label TEXT,
    forward_start_years NUMERIC,
    forward_label TEXT,
    notional NUMERIC,
    notional_currency TEXT,
    is_notional_capped BOOLEAN,
    strike NUMERIC,
    premium NUMERIC,
    exercise_style TEXT,
    cleared BOOLEAN,
    platform_identifier TEXT,
    package_type TEXT,
    package_indicator BOOLEAN,
    package_transaction_price NUMERIC,
    matched_ust_maturity BOOLEAN,
    invoice_swap_ticker TEXT,
    leg_metrics JSONB NOT NULL DEFAULT '{{}}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE(package_id, leg_order)
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
    ADD COLUMN IF NOT EXISTS package_source TEXT DEFAULT 'AUTO';
ALTER TABLE {PACKAGES_TABLE}
    ADD COLUMN IF NOT EXISTS economic_notional NUMERIC;
ALTER TABLE {PACKAGES_TABLE}
    ADD COLUMN IF NOT EXISTS manual_link_id UUID REFERENCES {MANUAL_LINKS_TABLE}(link_id);

ALTER TABLE {LEGS_TABLE}
    ADD COLUMN IF NOT EXISTS manual_link_id UUID REFERENCES {MANUAL_LINKS_TABLE}(link_id);
ALTER TABLE {LEGS_TABLE}
    ADD COLUMN IF NOT EXISTS is_manually_linked BOOLEAN DEFAULT FALSE;
ALTER TABLE {LEGS_TABLE}
    ADD COLUMN IF NOT EXISTS matched_ust_maturity BOOLEAN;
ALTER TABLE {LEGS_TABLE}
    ADD COLUMN IF NOT EXISTS invoice_swap_ticker TEXT;
-- Execution-vs-Event timestamp integration (2026-07-17): additively persist
-- the CFTC Event timestamp (#30) at leg grain, alongside the real Execution
-- timestamp (#96). Nullable / no default so the ADD COLUMN is a fast
-- metadata-only change and re-runs stay idempotent.
ALTER TABLE {LEGS_TABLE}
    ADD COLUMN IF NOT EXISTS event_timestamp TIMESTAMPTZ;

CREATE INDEX IF NOT EXISTS idx_swaption_packages_type_date ON {PACKAGES_TABLE}(package_type, as_of_date);
CREATE INDEX IF NOT EXISTS idx_swaption_packages_exec ON {PACKAGES_TABLE}(execution_start);
CREATE INDEX IF NOT EXISTS idx_swaption_packages_vega ON {PACKAGES_TABLE}(vega_curve_id) WHERE vega_curve_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_swaption_packages_source ON {PACKAGES_TABLE}(package_source);
CREATE INDEX IF NOT EXISTS idx_swaption_legs_package ON {LEGS_TABLE}(package_id);
CREATE INDEX IF NOT EXISTS idx_swaption_legs_exec ON {LEGS_TABLE}(execution_timestamp);
CREATE INDEX IF NOT EXISTS idx_swaption_legs_manual_link ON {LEGS_TABLE}(manual_link_id);
CREATE INDEX IF NOT EXISTS idx_manual_links_trades ON {MANUAL_LINKS_TABLE} USING GIN (linked_trade_ids);
CREATE INDEX IF NOT EXISTS idx_manual_links_active ON {MANUAL_LINKS_TABLE}(is_active) WHERE is_active = TRUE;
CREATE INDEX IF NOT EXISTS idx_manual_links_created ON {MANUAL_LINKS_TABLE}(created_at);
CREATE INDEX IF NOT EXISTS idx_manual_links_manual_pkg ON {MANUAL_LINKS_TABLE}(manual_package_id);
CREATE INDEX IF NOT EXISTS idx_link_history_link ON {LINK_HISTORY_TABLE}(link_id);

CREATE OR REPLACE VIEW {DISPLAY_VIEW_V1} AS
-- NOTE: Append new columns at the end to avoid CREATE OR REPLACE VIEW rename errors.
SELECT
  p.package_id,
  p.package_type,
  p.as_of_date,
  p.execution_start,
  p.execution_end,
  p.expiration_date,
  p.underlying_expiration_date,
  p.tenor_label,
  p.forward_label,
  p.legs_count,
  p.total_notional,
  p.total_premium,
  p.package_indicator,
  p.package_transaction_price,
  p.package_confidence,
  p.package_reason,
  p.vega_curve_id,
  p.vega_curve_type,
  p.package_metrics,
  l.legs_json,
  p.economic_notional
FROM {PACKAGES_TABLE} p
LEFT JOIN LATERAL (
    SELECT jsonb_agg(
        jsonb_build_object(
            'trade_id', l.trade_id,
            'leg_order', l.leg_order,
            'product_type', l.product_type,
            'trade_label', l.trade_label,
            'strike', l.strike,
            'notional', l.notional,
            'notional_currency', l.notional_currency,
            'is_notional_capped', l.is_notional_capped,
            'premium', l.premium,
            'exercise_style', l.exercise_style,
            'cleared', l.cleared,
            'package_type', l.package_type,
            'matched_ust_maturity', l.matched_ust_maturity,
            'invoice_swap_ticker', l.invoice_swap_ticker,
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
  p.expiration_date,
  p.underlying_expiration_date,
  p.tenor_label,
  p.forward_label,
  p.legs_count,
  p.total_notional,
  p.total_premium,
  p.package_indicator,
  p.package_transaction_price,
  p.package_confidence,
  p.package_reason,
  p.vega_curve_id,
  p.vega_curve_type,
  p.package_metrics,
  l.legs_json,
  p.economic_notional
FROM {PACKAGES_TABLE} p
LEFT JOIN {MANUAL_LINKS_TABLE} ml
  ON p.manual_link_id = ml.link_id AND ml.is_active = TRUE
LEFT JOIN LATERAL (
    SELECT jsonb_agg(
        jsonb_build_object(
            'trade_id', l.trade_id,
            'leg_order', l.leg_order,
            'product_type', l.product_type,
            'trade_label', l.trade_label,
            'strike', l.strike,
            'notional', l.notional,
            'notional_currency', l.notional_currency,
            'is_notional_capped', l.is_notional_capped,
            'premium', l.premium,
            'exercise_style', l.exercise_style,
            'cleared', l.cleared,
            'package_type', l.package_type,
            'matched_ust_maturity', l.matched_ust_maturity,
            'invoice_swap_ticker', l.invoice_swap_ticker,
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


def ensure_schema(engine: Engine, _max_retries: int = 3) -> None:
    """Create tables, indexes, and view if they do not exist.

    Uses a pg_advisory_xact_lock to serialize DDL across concurrent
    service instances and retries on transient deadlocks.
    """
    for attempt in range(1, _max_retries + 1):
        try:
            with engine.begin() as conn:
                conn.execute(text("SELECT pg_advisory_xact_lock(8675309)"))
                for statement in SCHEMA_SQL.split(";"):
                    stmt = statement.strip()
                    if stmt:
                        conn.execute(text(stmt))
            return
        except OperationalError as exc:
            if "deadlock" in str(exc).lower() and attempt < _max_retries:
                import time as _time
                _time.sleep(1.0 * attempt)
                continue
            raise


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


def _is_blank_like_series(series: pd.Series) -> pd.Series:
    text = series.astype("string").str.strip().str.lower()
    return series.isna() | text.isin({"", "nan", "none", "null", "nat"})


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
    if isinstance(val, float) and math.isnan(val):
        return None
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

    # Keep matched-maturity metadata in explicit columns, not in trade_label text.
    if "trade_label" in out.columns:
        out["trade_label"] = (
            out["trade_label"]
            .astype("string")
            .str.replace(r"\s*\[USTMAT[^\]]*\]\s*$", "", regex=True, case=False)
            .str.strip()
        )

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

    # Defensive guard: drop sparse outright artifacts (typically MODI/TRAD duplicates)
    # that have economics but no action/product/label metadata.
    required_cols = {"package_type", "event_action", "product_type", "trade_label"}
    if required_cols.issubset(set(out.columns)):
        is_outright = out["package_type"].astype("string").str.upper().eq("OUTRIGHT")
        blank_action = _is_blank_like_series(out["event_action"])
        blank_product = _is_blank_like_series(out["product_type"])
        blank_label = _is_blank_like_series(out["trade_label"])
        sparse_outright_mask = is_outright & blank_action & blank_product & blank_label
        sparse_outright_count = int(sparse_outright_mask.sum())
        if sparse_outright_count > 0:
            print(
                f"Dropping {sparse_outright_count} sparse OUTRIGHT rows "
                "(missing event_action/product_type/trade_label)."
            )
            out = out.loc[~sparse_outright_mask].copy()

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


def build_package_metrics(package_type: str, group: pd.DataFrame) -> Dict[str, Any]:
    cols = PACKAGE_METRIC_COLUMNS.get(package_type, ())
    metrics: Dict[str, Any] = {}
    for col in cols:
        if col not in group.columns:
            continue
        candidate = _consistent_value(group[col])
        if candidate is None:
            # Preserve a list if values legitimately differ across legs
            non_null: list[Any] = []
            for v in group[col].tolist():
                if v is None:
                    continue
                if isinstance(v, (list, tuple, dict, set)):
                    non_null.append(v)
                    continue
                if isinstance(v, np.ndarray):
                    if v.size == 0:
                        continue
                    non_null.append(v)
                    continue
                try:
                    if pd.isna(v):
                        continue
                except Exception:
                    # pd.isna can choke on some object dtypes; treat as non-null
                    pass
                non_null.append(v)
            if non_null:
                metrics[col] = [_pythonify(v) for v in non_null]
        else:
            metrics[col] = candidate
    return metrics


def build_leg_metrics(row: pd.Series) -> Dict[str, Any]:
    metrics: Dict[str, Any] = {}
    for col in LEG_METRIC_COLUMNS:
        if col in row and pd.notna(row[col]):
            metrics[col] = _pythonify(row[col])
    return metrics


def compute_economic_notional(group: pd.DataFrame, pkg_type: str) -> Optional[float]:
    """Compute economic notional (structure-adjusted) for a package."""
    if group.empty:
        return None

    notionals = pd.to_numeric(
        group.get("notional", pd.Series(dtype=float)), errors="coerce"
    )
    if notionals.empty:
        return None

    total_raw = notionals.sum(skipna=True)
    if pd.isna(total_raw):
        return None
    total = abs(float(total_raw))
    if total == 0:
        return 0.0

    max_leg = notionals.abs().max(skipna=True)
    normalized = (pkg_type or "").replace("-", "_").upper()

    if normalized == "STRADDLE":
        return total / 2

    if normalized in {"RISK_REVERSAL", "VERTICAL_SPREAD_1X1", "CUSTY_RR_STRANGLE"}:
        if pd.notna(max_leg):
            return abs(float(max_leg))
        return total / 2

    if normalized == "VERTICAL_SPREAD_1X2":
        atm_notional = None
        if "vs_atm_notional" in group.columns:
            candidate = _consistent_value(group["vs_atm_notional"])
            if candidate is None:
                series = group["vs_atm_notional"].dropna()
                if not series.empty:
                    candidate = series.iloc[0]
            if candidate is not None and not pd.isna(candidate):
                atm_notional = float(candidate)
        if atm_notional is not None:
            return abs(atm_notional)
        return total / 3

    if normalized in {"RECEIVER_LADDER", "PAYER_LADDER"}:
        if pd.notna(max_leg):
            return abs(float(max_leg))
        return total

    return total


def build_packages_dataframe(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame()

    records: list[Dict[str, Any]] = []
    for package_id, group in df.groupby("package_id", sort=False):
        g = group.sort_values(["execution_timestamp", "trade_id"])

        pkg_type_series = g["package_type"].dropna()
        pkg_type = _consistent_value(g["package_type"]) or (pkg_type_series.iloc[0] if not pkg_type_series.empty else "OUTRIGHT")
        execution_start = g["execution_timestamp"].min()
        execution_end = g["execution_timestamp"].max()
        as_of_date = execution_start.date() if pd.notna(execution_start) else None
        total_notional = pd.to_numeric(
            g.get("notional", pd.Series(dtype=float)), errors="coerce"
        ).sum(skipna=True)
        economic_notional = compute_economic_notional(g, pkg_type)

        record = {
            "package_id": package_id,
            "package_type": pkg_type,
            "as_of_date": as_of_date,
            "execution_start": execution_start,
            "execution_end": execution_end,
            "expiration_date": _consistent_value(g["expiration_date"]),
            "underlying_expiration_date": _consistent_value(g["underlying_expiration_date"]),
            "effective_date": _consistent_value(g["effective_date"]),
            "tenor_years": _consistent_value(g["tenor_years"]),
            "tenor_label": _consistent_value(g["tenor_label"]),
            "forward_start_years": _consistent_value(g["forward_start_years"]),
            "forward_label": _consistent_value(g["forward_label"]),
            "legs_count": len(g),
            "total_notional": total_notional,
            "economic_notional": economic_notional,
            "total_premium": pd.to_numeric(g.get("premium", pd.Series(dtype=float)), errors="coerce").sum(skipna=True),
            "package_indicator": _consistent_value(g["package_indicator"]) if "package_indicator" in g else None,
            "package_transaction_price": _consistent_value(g["package_transaction_price"]) if "package_transaction_price" in g else None,
            "package_confidence": _consistent_value(g["package_confidence"]) if "package_confidence" in g else None,
            "package_reason": _consistent_value(g["package_reason"]) if "package_reason" in g else None,
            "vega_curve_id": _consistent_value(g["vega_curve_id"]) if "vega_curve_id" in g else None,
            "vega_curve_type": _consistent_value(g["vega_curve_type"]) if "vega_curve_type" in g else None,
            "vega_curve_vega01": _consistent_value(g["vega_curve_vega01"]) if "vega_curve_vega01" in g else None,
            "vega_curve_weight": _consistent_value(g["vega_curve_weight"]) if "vega_curve_weight" in g else None,
            "vega_curve_vega_ratio": _consistent_value(g["vega_curve_vega_ratio"]) if "vega_curve_vega_ratio" in g else None,
            "vega_curve_pricing_method": _consistent_value(g["vega_curve_pricing_method"]) if "vega_curve_pricing_method" in g else None,
        }

        record["package_metrics"] = build_package_metrics(pkg_type, g)
        records.append(record)

    return pd.DataFrame(records)


def build_legs_dataframe(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame()

    legs: list[Dict[str, Any]] = []
    for _, group in df.groupby("package_id", sort=False):
        g = group.sort_values(["execution_timestamp", "strike", "trade_id"])
        for idx, (_, row) in enumerate(g.iterrows()):
            rec: Dict[str, Any] = {
                "trade_id": str(row.get("trade_id")),
                "package_id": row.get("package_id"),
                "leg_order": idx,
                "event_action": row.get("event_action"),
                "execution_timestamp": row.get("execution_timestamp"),
                "event_timestamp": row.get("event_timestamp"),
                "effective_date": row.get("effective_date"),
                "expiration_date": row.get("expiration_date"),
                "underlying_expiration_date": row.get("underlying_expiration_date"),
                "product_type": row.get("product_type"),
                "trade_label": row.get("trade_label"),
                "tenor_years": row.get("tenor_years"),
                "tenor_label": row.get("tenor_label"),
                "forward_start_years": row.get("forward_start_years"),
                "forward_label": row.get("forward_label"),
                "notional": row.get("notional"),
                "notional_currency": row.get("notional_currency"),
                "is_notional_capped": row.get("is_notional_capped"),
                "strike": row.get("strike"),
                "premium": row.get("premium"),
                "exercise_style": row.get("exercise_style"),
                "cleared": row.get("cleared"),
                "platform_identifier": row.get("platform_identifier"),
                "package_type": row.get("package_type"),
                "package_indicator": row.get("package_indicator"),
                "package_transaction_price": row.get("package_transaction_price"),
                "matched_ust_maturity": row.get("matched_ust_maturity"),
                "invoice_swap_ticker": row.get("invoice_swap_ticker"),
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
    batch_size: int = 1000,
    progress_desc: Optional[str] = None,
) -> int:
    """Generic upsert helper using INSERT .. ON CONFLICT .. DO UPDATE."""
    if df.empty:
        return 0

    json_cols_set = set(json_cols or [])

    records = df.to_dict(orient="records")
    for rec in records:
        for col, value in list(rec.items()):
            if col in json_cols_set:
                continue
            rec[col] = _to_db_value(value)
    # Ensure JSON columns are serialized to JSON strings (avoid hstore inference)
    for rec in records:
        for col in json_cols_set:
            if col in rec:
                rec[col] = json.dumps(_to_jsonable(rec[col]), default=str)
    all_cols = list(records[0].keys())

    col_list = ", ".join(all_cols)
    placeholders = ", ".join([f":{c}" for c in all_cols])
    updates = ", ".join([f"{c} = EXCLUDED.{c}" for c in update_cols])
    conflict_clause = ", ".join(conflict_cols)

    sql = text(
        f"""
        INSERT INTO {table_name} ({col_list})
        VALUES ({placeholders})
        ON CONFLICT ({conflict_clause}) DO UPDATE
        SET {updates},
            updated_at = NOW()
        """
    )

    total = len(records)
    desc = progress_desc or f"Writing {table_name}"
    with engine.begin() as conn:
        for start_idx in tqdm(range(0, total, batch_size), desc=desc, unit="rows"):
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
    Build the swaption classification DataFrame at leg grain.

    We deliberately use merge_package_legs=False so packages retain one row per leg.
    """
    from SDRUtils.products.usd.usd_swaptions import USD_Swaptions

    swaptions = USD_Swaptions()
    df = swaptions.build_classification_dataframe(
        start=start,
        end=end,
        cache_path=cache_path,
        ignore_cache=ignore_cache,
        detect_swaption_packages=True,
        merge_package_legs=False,
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
    """Explicit argument, then ``SDR_CACHE_PATH``, then the resolved store.

    Same reasoning as ``ingest_usdswaps._resolve_cache_path``: the old
    ``"./sdr_cache"`` fallback was relative to the process working directory, so
    running from anywhere but the repo root read an empty cache without saying
    so. ``SDR_CACHE_PATH=NONE`` in ``.env`` is treated as unset.
    """
    if cache_path:
        return cache_path
    from_env = os.getenv("SDR_CACHE_PATH")
    if from_env and from_env.strip() and from_env.strip().upper() != "NONE":
        return from_env
    return str(repo_store("sdr_cache", env_var="ARBS_SDR_CACHE_DIR"))


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
        print("\nNotional / premium:")
        print(f"  Total notional: {packages_df['total_notional'].sum():,.0f}")
        print(f"  Total premium: {packages_df['total_premium'].sum():,.0f}")
        print(f"  Avg legs per package: {packages_df['legs_count'].mean():.2f}")


def _normalize_range_inputs(
    start: Optional[pd.Timestamp],
    end: Optional[pd.Timestamp],
    days: int,
) -> tuple[pd.Timestamp, pd.Timestamp]:
    if end is None:
        end_ts = pd.Timestamp.now(tz="UTC")
    else:
        end_ts = _to_utc_timestamp(end)
    if start is None:
        start_ts = end_ts - timedelta(days=days)
    else:
        start_ts = _to_utc_timestamp(start)
    if start_ts > end_ts:
        raise ValueError(f"Start timestamp must be <= end timestamp. Got start={start_ts}, end={end_ts}")
    return start_ts, end_ts


def _iter_daily_windows(
    start: pd.Timestamp,
    end: pd.Timestamp,
) -> list[tuple[pd.Timestamp, pd.Timestamp]]:
    windows: list[tuple[pd.Timestamp, pd.Timestamp]] = []
    current_start = _to_utc_timestamp(start)
    end_ts = _to_utc_timestamp(end)
    while current_start <= end_ts:
        next_midnight = current_start.normalize() + pd.Timedelta(days=1)
        current_end = min(end_ts, next_midnight - pd.Timedelta(nanoseconds=1))
        windows.append((current_start, current_end))
        current_start = next_midnight
    return windows


def _print_daily_range_error_summary(errors: list[dict[str, str]]) -> None:
    if not errors:
        return
    print("=" * 60)
    print("DAILY-RANGE ERROR SUMMARY")
    print("=" * 60)
    for error in errors:
        print(
            f"{error['date']} [{error['component']}]: {error['message']}"
        )
    print()


def _run_swaption_range_window(
    *,
    start: pd.Timestamp,
    end: pd.Timestamp,
    cache_path: str,
    ignore_cache: bool,
    only_newt: bool,
    dry_run: bool,
    engine: Optional[Engine] = None,
) -> None:
    print("Swaption ingestion")
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
        print("No swaption trades found in date range.")
        return

    if dry_run:
        print("Dry run enabled; skipping database writes.")
        cleaned = normalize_dataframe(raw_df)
        packages_df = build_packages_dataframe(cleaned)
        legs_df = build_legs_dataframe(cleaned)
        print_summary(raw_df, packages_df, legs_df, 0, 0)
        return

    active_engine = engine
    if active_engine is None:
        active_engine = create_db_engine()
        ensure_schema(active_engine)

    packages_df, legs_df, packages_written, legs_written = ingest_to_postgres(
        raw_df,
        active_engine,
        start=start,
        end=end,
    )

    print_summary(raw_df, packages_df, legs_df, packages_written, legs_written)


def main(
    start: Optional[pd.Timestamp] = None,
    end: Optional[pd.Timestamp] = None,
    days: int = 7,
    cache_path: Optional[str] = None,
    ignore_cache: bool = False,
    only_newt: bool = False,
    dry_run: bool = False,
) -> None:
    start, end = _normalize_range_inputs(start, end, days)
    cache_path = _resolve_cache_path(cache_path)
    engine = None
    if not dry_run:
        engine = create_db_engine()
        ensure_schema(engine)
    _run_swaption_range_window(
        start=start,
        end=end,
        cache_path=cache_path,
        ignore_cache=ignore_cache,
        only_newt=only_newt,
        dry_run=dry_run,
        engine=engine,
    )


def ingest_incremental_once(
    engine: Engine,
    *,
    cache_path: str,
    ignore_cache: bool = True,
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

    print("Incremental swaption ingestion")
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


def _load_capfloor_ingest_module() -> Any:
    """Import the cap/floor ingester without duplicating this module when run as a script."""
    current_module = sys.modules.get(__name__)
    if current_module is not None:
        sys.modules.setdefault(
            "SDRUtils._swappulse_scripts.ingest_usdswaptions",
            current_module,
        )
    return importlib.import_module("SDRUtils._swappulse_scripts.ingest_usdcapfloors")


def _ingest_capfloor_incremental_once(
    engine: Engine,
    *,
    cache_path: str,
    ignore_cache: bool,
    only_newt: bool,
    dry_run: bool,
    cleanup_orphans: bool,
    initial_lookback_minutes: int,
    overlap_seconds: int,
    market_timezone: str,
) -> None:
    capfloor_ingest = _load_capfloor_ingest_module()
    capfloor_ingest.ensure_schema(engine)
    capfloor_ingest.ingest_incremental_once(
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


def _run_capfloor_range_window(
    *,
    start: pd.Timestamp,
    end: pd.Timestamp,
    cache_path: str,
    ignore_cache: bool,
    only_newt: bool,
    dry_run: bool,
    engine: Optional[Engine] = None,
    capfloor_ingest: Optional[Any] = None,
) -> None:
    capfloor_module = capfloor_ingest or _load_capfloor_ingest_module()

    print("Cap/floor ingestion")
    print(f"  Range: {start} -> {end}")
    print(f"  Cache: {cache_path}")
    print(f"  Ignore cache: {ignore_cache}")
    print(f"  Only NEWT/TRAD: {only_newt}")
    print(f"  Dry run: {dry_run}")
    print()

    print("Building classification dataframe...")
    raw_df = capfloor_module.build_classification_dataframe(
        start=start,
        end=end,
        cache_path=cache_path,
        ignore_cache=ignore_cache,
        only_newt=only_newt,
    )

    if raw_df.empty:
        print("No cap/floor trades found in date range.")
        return

    cleaned = capfloor_module.normalize_dataframe(raw_df)
    packages_df = capfloor_module.build_packages_dataframe(cleaned)
    legs_df = capfloor_module.build_legs_dataframe(cleaned)
    if dry_run:
        print("Dry run enabled; skipping database writes.")
        capfloor_module.print_summary(raw_df, packages_df, legs_df, 0, 0)
        return

    active_engine = engine
    if active_engine is None:
        active_engine = capfloor_module.create_db_engine()
        capfloor_module.ensure_schema(active_engine)
    else:
        capfloor_module.ensure_schema(active_engine)

    packages_df, legs_df, packages_written, legs_written = capfloor_module.ingest_to_postgres(
        raw_df,
        active_engine,
        start=start,
        end=end,
    )
    capfloor_module.print_summary(
        raw_df,
        packages_df,
        legs_df,
        packages_written,
        legs_written,
    )


def main_daily_range(
    start: Optional[pd.Timestamp] = None,
    end: Optional[pd.Timestamp] = None,
    days: int = 7,
    cache_path: Optional[str] = None,
    ignore_cache: bool = False,
    only_newt: bool = False,
    dry_run: bool = False,
    include_capfloor: bool = False,
    continue_on_error: bool = False,
) -> None:
    start, end = _normalize_range_inputs(start, end, days)
    cache_path = _resolve_cache_path(cache_path)
    windows = _iter_daily_windows(start, end)

    print("Starting daily-range swaption ingestion")
    print(f"  Full range: {start} -> {end}")
    print(f"  Cache: {cache_path}")
    print(f"  Ignore cache: {ignore_cache}")
    print(f"  Only NEWT/TRAD: {only_newt}")
    print(f"  Dry run: {dry_run}")
    print(f"  Include cap/floor: {include_capfloor}")
    print(f"  Continue on error: {continue_on_error}")
    print(f"  Daily windows: {len(windows)}")
    print()

    engine: Optional[Engine] = None
    capfloor_ingest: Optional[Any] = None
    errors: list[dict[str, str]] = []
    if not dry_run:
        engine = create_db_engine()
        ensure_schema(engine)
    if include_capfloor:
        capfloor_ingest = _load_capfloor_ingest_module()
        if not dry_run and engine is not None:
            capfloor_ingest.ensure_schema(engine)

    for index, (window_start, window_end) in enumerate(windows, start=1):
        print("=" * 60)
        print(f"Daily window {index}/{len(windows)}")
        print(f"  {window_start} -> {window_end}")
        print("=" * 60)
        window_date = window_start.date().isoformat()
        try:
            _run_swaption_range_window(
                start=window_start,
                end=window_end,
                cache_path=cache_path,
                ignore_cache=ignore_cache,
                only_newt=only_newt,
                dry_run=dry_run,
                engine=engine,
            )
        except Exception as exc:
            error_entry = {
                "date": window_date,
                "component": "SWAPTION",
                "message": str(exc),
            }
            errors.append(error_entry)
            print(
                f"Daily window failed for {window_date} [SWAPTION]: {exc}"
            )
            print()
            if not continue_on_error:
                _print_daily_range_error_summary(errors)
                raise
            continue
        if include_capfloor:
            try:
                print("Running cap/floor daily-range ingestion alongside swaptions")
                _run_capfloor_range_window(
                    start=window_start,
                    end=window_end,
                    cache_path=cache_path,
                    ignore_cache=ignore_cache,
                    only_newt=only_newt,
                    dry_run=dry_run,
                    engine=engine,
                    capfloor_ingest=capfloor_ingest,
                )
            except Exception as exc:
                error_entry = {
                    "date": window_date,
                    "component": "CAPFLOOR",
                    "message": str(exc),
                }
                errors.append(error_entry)
                print(
                    f"Daily window failed for {window_date} [CAPFLOOR]: {exc}"
                )
                print()
                if not continue_on_error:
                    _print_daily_range_error_summary(errors)
                    raise
                continue
        print()

    _print_daily_range_error_summary(errors)


def main_incremental(
    cache_path: Optional[str] = None,
    only_newt: bool = False,
    dry_run: bool = False,
    cleanup_orphans: bool = True,
    initial_lookback_minutes: int = 24 * 60,
    overlap_seconds: int = 0,
    include_capfloor: bool = False,
    market_timezone: str = "America/New_York",
) -> None:
    cache_path = _resolve_cache_path(cache_path)
    shared_cache_mode = include_capfloor
    engine = create_db_engine()
    ensure_schema(engine)
    ingest_incremental_once(
        engine,
        cache_path=cache_path,
        ignore_cache=not shared_cache_mode,
        only_newt=only_newt,
        dry_run=dry_run,
        cleanup_orphans=cleanup_orphans,
        initial_lookback_minutes=initial_lookback_minutes,
        overlap_seconds=overlap_seconds,
    )
    if include_capfloor:
        print("Running cap/floor incremental ingestion alongside swaptions")
        _ingest_capfloor_incremental_once(
            engine,
            cache_path=cache_path,
            ignore_cache=False,
            only_newt=only_newt,
            dry_run=dry_run,
            cleanup_orphans=cleanup_orphans,
            initial_lookback_minutes=initial_lookback_minutes,
            overlap_seconds=overlap_seconds,
            market_timezone=market_timezone,
        )


def main_service(
    interval_seconds: int = 120,
    cache_path: Optional[str] = None,
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
    include_capfloor: bool = False,
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

    print("Starting swaption ingestion service")
    print(f"  Base interval: {interval_seconds} seconds")
    print(f"  Cache: {cache_path}")
    print(f"  Only NEWT/TRAD: {only_newt}")
    print(f"  Dry run: {dry_run}")
    print(f"  Initial lookback: {initial_lookback_minutes} minutes")
    print(f"  Overlap: {overlap_seconds} seconds")
    print(f"  Include cap/floor: {include_capfloor}")
    if include_capfloor:
        print("  Shared raw SDR cache mode: enabled")
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
                ignore_cache=not include_capfloor,
                only_newt=only_newt,
                dry_run=dry_run,
                cleanup_orphans=cleanup_orphans,
                initial_lookback_minutes=initial_lookback_minutes,
                overlap_seconds=overlap_seconds,
                force_fetch_end_of_day=True,
                force_fetch_full_market_day=True,
                market_timezone=market_timezone,
            )
            if include_capfloor:
                print("Running cap/floor incremental ingestion alongside swaptions")
                _ingest_capfloor_incremental_once(
                    engine,
                    cache_path=cache_path,
                    ignore_cache=False,
                    only_newt=only_newt,
                    dry_run=dry_run,
                    cleanup_orphans=cleanup_orphans,
                    initial_lookback_minutes=initial_lookback_minutes,
                    overlap_seconds=overlap_seconds,
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
    parser = argparse.ArgumentParser(description="Ingest USD swaption classifications into SwapPulse Postgres.")
    parser.add_argument(
        "--mode",
        choices=("range", "daily-range", "incremental", "service"),
        default=os.getenv("SWAPPULSE_INGEST_MODE", "incremental"),
        help="range=single explicit date range, daily-range=write one UTC day at a time, incremental=single catch-up run, service=continuous loop.",
    )
    parser.add_argument("--days", type=int, default=7, help="Days to look back when --start is not provided in range mode.")
    parser.add_argument("--start", type=str, help="Start timestamp (e.g. 2026-02-04 or 2026-02-04T12:00:00Z).")
    parser.add_argument("--end", type=str, help="End timestamp (e.g. 2026-02-04 or 2026-02-04T12:00:00Z).")
    parser.add_argument("--cache-path", type=str, help="Path to SDR cache directory.")
    parser.add_argument("--ignore-cache", action="store_true", help="Ignore cached classifications (range mode only).")
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
    parser.add_argument(
        "--include-capfloor",
        action="store_true",
        help="Daily-range/incremental/service: also run cap/floor ingestion for the same windows.",
    )
    parser.add_argument(
        "--continue-on-error",
        action="store_true",
        help="Daily-range only: log failed days, skip them, and continue with later windows.",
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
    elif args.mode == "daily-range":
        main_daily_range(
            start=parsed_start,
            end=parsed_end,
            days=args.days,
            cache_path=args.cache_path,
            ignore_cache=args.ignore_cache,
            only_newt=args.only_newt,
            dry_run=args.dry_run,
            include_capfloor=args.include_capfloor,
            continue_on_error=args.continue_on_error,
        )
    elif args.mode == "incremental":
        main_incremental(
            cache_path=args.cache_path,
            only_newt=args.only_newt,
            dry_run=args.dry_run,
            cleanup_orphans=cleanup_orphans,
            initial_lookback_minutes=args.initial_lookback_minutes,
            overlap_seconds=args.overlap_seconds,
            include_capfloor=args.include_capfloor,
            market_timezone=args.market_timezone,
        )
    else:
        main_service(
            interval_seconds=args.interval_seconds,
            cache_path=args.cache_path,
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
            include_capfloor=args.include_capfloor,
        )
