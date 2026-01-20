"""
Swaption data ingestion for SwapPulse.

Goal: persist USD swaption classification output so that packages render as
single rows (with leg drill-down) and outrights remain one row per trade.
The schema uses normalized package/leg tables plus JSONB metrics for
package-type-specific analytics to stay extensible as new detections ship.
"""

from __future__ import annotations

import argparse
import json
import os
import math
from datetime import date, datetime, timedelta
from typing import Any, Dict, Iterable, Optional

import numpy as np
import pandas as pd
from tqdm import tqdm
import pytz
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

NY_tz = pytz.timezone("America/New_York")


# Table/view names (versioned so we can cut over safely)
PACKAGES_TABLE = "arbs_swaption_packages_v1"
LEGS_TABLE = "arbs_swaption_legs_v1"
RUNS_TABLE = "arbs_swaption_ingestion_runs_v1"
DISPLAY_VIEW = "arbs_swaption_display_items_v1"

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
)

TIMESTAMP_COLUMNS: tuple[str, ...] = ("execution_timestamp",)
DATE_COLUMNS: tuple[str, ...] = (
    "effective_date",
    "expiration_date",
    "underlying_expiration_date",
)

# Schema (packages + legs + ingestion runs + display view)
SCHEMA_SQL = f"""
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

CREATE INDEX IF NOT EXISTS idx_swaption_packages_type_date ON {PACKAGES_TABLE}(package_type, as_of_date);
CREATE INDEX IF NOT EXISTS idx_swaption_packages_exec ON {PACKAGES_TABLE}(execution_start);
CREATE INDEX IF NOT EXISTS idx_swaption_packages_vega ON {PACKAGES_TABLE}(vega_curve_id) WHERE vega_curve_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_swaption_legs_package ON {LEGS_TABLE}(package_id);
CREATE INDEX IF NOT EXISTS idx_swaption_legs_exec ON {LEGS_TABLE}(execution_timestamp);

CREATE OR REPLACE VIEW {DISPLAY_VIEW} AS
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
  l.legs_json
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
            'premium', l.premium,
            'exercise_style', l.exercise_style,
            'package_type', l.package_type,
            'leg_metrics', l.leg_metrics
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
            "total_notional": pd.to_numeric(g.get("notional", pd.Series(dtype=float)), errors="coerce").sum(skipna=True),
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


def ingest_to_postgres(
    df: pd.DataFrame,
    engine: Engine,
    start: pd.Timestamp,
    end: pd.Timestamp,
) -> tuple[pd.DataFrame, pd.DataFrame, int, int]:
    cleaned = normalize_dataframe(df)
    packages_df = build_packages_dataframe(cleaned)
    legs_df = build_legs_dataframe(cleaned)

    packages_written = upsert_dataframe(
        packages_df,
        engine,
        PACKAGES_TABLE,
        conflict_cols=["package_id"],
        update_cols=[
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
        ],
        json_cols=["package_metrics"],
        progress_desc="Writing packages",
    )

    legs_written = upsert_dataframe(
        legs_df,
        engine,
        LEGS_TABLE,
        conflict_cols=["trade_id"],
        update_cols=[
            "package_id",
            "leg_order",
            "event_action",
            "execution_timestamp",
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
            "leg_metrics",
        ],
        json_cols=["leg_metrics"],
        progress_desc="Writing legs",
    )

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


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Ingest USD swaption classifications into SwapPulse Postgres.")
    parser.add_argument("--days", type=int, default=7, help="Days to look back when start not provided.")
    parser.add_argument("--start", type=str, help="Start date (YYYY-MM-DD).")
    parser.add_argument("--end", type=str, help="End date (YYYY-MM-DD).")
    parser.add_argument("--cache-path", type=str, help="Path to SDR cache directory.")
    parser.add_argument("--ignore-cache", action="store_true", help="Ignore cached classifications.")
    parser.add_argument("--no-only-newt", action="store_true", help="Include non-NEWT/TRAD events.")
    parser.add_argument("--dry-run", action="store_true", help="Build dataframes but skip database writes.")
    return parser.parse_args()


def main(
    start: Optional[pd.Timestamp] = None,
    end: Optional[pd.Timestamp] = None,
    days: int = 7,
    cache_path: Optional[str] = None,
    ignore_cache: bool = False,
    only_newt: bool = False,
    dry_run: bool = False,
) -> None:
    # Resolve dates
    if end is None:
        end = pd.Timestamp.now(tz="UTC")
    if start is None:
        start = end - timedelta(days=days)
    if cache_path is None:
        cache_path = os.getenv("SDR_CACHE_PATH", "./sdr_cache")

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

    engine = create_db_engine()
    ensure_schema(engine)

    packages_df, legs_df, packages_written, legs_written = ingest_to_postgres(
        raw_df,
        engine,
        start=start,
        end=end,
    )

    print_summary(raw_df, packages_df, legs_df, packages_written, legs_written)


if __name__ == "__main__":
    args = parse_args()

    # parsed_start = pd.Timestamp(args.start, tz="UTC") if args.start else None
    # parsed_end = pd.Timestamp(args.end, tz="UTC") if args.end else None

    import QuantLib as ql
    from BT.misc import ql_cal_date_range

    date_range = ql_cal_date_range(ql.UnitedStates(ql.UnitedStates.GovernmentBond), date(2025, 1, 1), date(2025, 7, 1))
    errors = []
    for d in date_range:
        try:
            as_of = d.date()
            start = NY_tz.localize(datetime(as_of.year, as_of.month, as_of.day, 0, 0))
            end = NY_tz.localize(datetime(as_of.year, as_of.month, as_of.day, 23, 59))

            cache_path = r"C:\Users\chris\clee\project-oasis\private\sdranalytics\.cache"

            main(
                # start=parsed_start,
                # end=parsed_end,
                start=start,
                end=end,
                cache_path=cache_path,
                ignore_cache=True,
                only_newt=False,
                dry_run=False,
            )
        except Exception as e:
            print(e)
            errors.append({"d": str(d), "err": str(e)})

    print(pd.DataFrame(errors))
    pd.DataFrame(errors).to_excel("swappulse_usdswaptions_ingest.xlsx")
