"""Cap/floor ingestion for SwapPulse."""

from __future__ import annotations

import argparse
import datetime as dt
import os
from datetime import timedelta
from typing import Any, Optional

import pandas as pd
from sqlalchemy import text
from sqlalchemy.engine import Engine

from SDRUtils._swappulse_scripts.ingest_usdswaptions import (
    BOOL_COLUMNS,
    DATE_COLUMNS,
    LEG_UPSERT_UPDATE_COLUMNS,
    NUMERIC_COLUMNS,
    PACKAGE_UPSERT_UPDATE_COLUMNS,
    TIMESTAMP_COLUMNS,
    _boolify,
    _pythonify,
    _resolve_cache_path,
    _resolve_end_of_day_fetch_timestamp,
    _resolve_start_of_day_fetch_timestamp,
    _to_jsonable,
    _to_utc_timestamp,
    build_packages_dataframe,
    create_db_engine,
    print_summary,
    upsert_dataframe,
)


PACKAGES_TABLE = "arbs_capfloor_packages_v1"
LEGS_TABLE = "arbs_capfloor_legs_v1"
RUNS_TABLE = "arbs_capfloor_ingestion_runs_v1"
DISPLAY_VIEW = "arbs_capfloor_display_items_v1"

CAPFLOOR_LEG_METRIC_COLUMNS: tuple[str, ...] = (
    "bpvol",
    "implied_vol_bps",
    "num_caplets",
    "reset_frequency",
    "moneyness_bps",
    "cap_floor_type",
    "caplet_details",
    "model_premium",
    "market_premium",
    "pricing_error",
    "warnings",
    "outright_bpvol_yr",
)

CAPFLOOR_NUMERIC_COLUMNS: tuple[str, ...] = (
    *NUMERIC_COLUMNS,
    "bpvol",
    "implied_vol_bps",
    "num_caplets",
    "moneyness_bps",
    "model_premium",
    "market_premium",
)

CAPFLOOR_SCHEMA_SQL = f"""
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

-- Execution-vs-Event timestamp integration (2026-07-17): additively persist
-- the CFTC Event timestamp (#30) at leg grain, alongside the real Execution
-- timestamp (#96). Idempotent + nullable / no default so the ADD COLUMN is a
-- fast metadata-only change and re-runs stay safe.
ALTER TABLE {LEGS_TABLE} ADD COLUMN IF NOT EXISTS event_timestamp TIMESTAMPTZ;

CREATE INDEX IF NOT EXISTS idx_capfloor_packages_type_date ON {PACKAGES_TABLE}(package_type, as_of_date);
CREATE INDEX IF NOT EXISTS idx_capfloor_packages_exec ON {PACKAGES_TABLE}(execution_start);
CREATE INDEX IF NOT EXISTS idx_capfloor_legs_package ON {LEGS_TABLE}(package_id);
CREATE INDEX IF NOT EXISTS idx_capfloor_legs_exec ON {LEGS_TABLE}(execution_timestamp);

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
) l ON TRUE
"""


def ensure_schema(engine: Engine) -> None:
    with engine.begin() as conn:
        for statement in CAPFLOOR_SCHEMA_SQL.split(";"):
            stmt = statement.strip()
            if stmt:
                conn.execute(text(stmt))


def normalize_dataframe(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()

    for col in CAPFLOOR_NUMERIC_COLUMNS:
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

    if "trade_label" in out.columns:
        out["trade_label"] = out["trade_label"].astype("string").str.strip()

    if "package_id" not in out.columns:
        out["package_id"] = out["trade_id"].astype("string").map(lambda x: f"OUTRIGHT-{x}")
    mask_no_pkg = out["package_id"].isna() | out["package_id"].astype("string").str.strip().eq("")
    if mask_no_pkg.any():
        out.loc[mask_no_pkg, "package_id"] = out.loc[mask_no_pkg, "trade_id"].astype("string").map(lambda x: f"OUTRIGHT-{x}")
    out["package_type"] = "OUTRIGHT"
    out["package_id"] = out["package_id"].astype(str)
    return out


def _has_metric_value(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return value.strip() != ""
    if isinstance(value, (list, tuple, set, dict)):
        return len(value) > 0
    try:
        return bool(pd.notna(value))
    except Exception:
        return True


def _capfloor_pythonify(value: Any) -> Any:
    if isinstance(value, dt.datetime):
        return value.isoformat()
    if isinstance(value, dt.date):
        return value.isoformat()
    if isinstance(value, (list, tuple, set)):
        return [_capfloor_pythonify(item) for item in value]
    if isinstance(value, dict):
        return {key: _capfloor_pythonify(item) for key, item in value.items()}
    return _pythonify(value)


def build_leg_metrics(row: pd.Series) -> dict[str, Any]:
    metrics: dict[str, Any] = {}
    for col in CAPFLOOR_LEG_METRIC_COLUMNS:
        if col in row and _has_metric_value(row[col]):
            metrics[col] = _capfloor_pythonify(row[col])
    return metrics


def build_legs_dataframe(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame()

    legs: list[dict[str, Any]] = []
    for _, group in df.groupby("package_id", sort=False):
        ordered = group.sort_values(["execution_timestamp", "strike", "trade_id"])
        for idx, (_, row) in enumerate(ordered.iterrows()):
            legs.append(
                {
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
                    "leg_metrics": build_leg_metrics(row),
                }
            )
    return pd.DataFrame(legs)


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
    from SDRUtils.products.usd.usd_capfloors import USD_CapFloors

    capfloors = USD_CapFloors()
    return capfloors.build_classification_dataframe(
        start=start,
        end=end,
        cache_path=cache_path,
        ignore_cache=ignore_cache,
        merge_package_legs=False,
        only_newt=only_newt,
    )


def delete_date_range(engine: Engine, start: pd.Timestamp, end: pd.Timestamp) -> tuple[int, int]:
    with engine.begin() as conn:
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
        packages_result = conn.execute(
            text(
                f"""
                DELETE FROM {PACKAGES_TABLE}
                WHERE execution_start >= :start AND execution_start < :end
                """
            ),
            {"start": start, "end": end},
        )
    return packages_result.rowcount, legs_result.rowcount


def get_last_ingested_timestamp(engine: Engine) -> Optional[pd.Timestamp]:
    with engine.connect() as conn:
        result = conn.execute(text(f"SELECT MAX(execution_timestamp) FROM {LEGS_TABLE}")).scalar()
    return _to_utc_timestamp(result) if result is not None else None


def get_last_run_timestamp(engine: Engine) -> Optional[pd.Timestamp]:
    with engine.connect() as conn:
        result = conn.execute(text(f"SELECT MAX(end_ts) FROM {RUNS_TABLE}")).scalar()
    return _to_utc_timestamp(result) if result is not None else None


def get_ingestion_cursor_timestamp(engine: Engine) -> Optional[pd.Timestamp]:
    last_trade_ts = get_last_ingested_timestamp(engine)
    last_run_ts = get_last_run_timestamp(engine)
    if last_trade_ts is None:
        return last_run_ts
    if last_run_ts is None:
        return last_trade_ts
    return max(last_trade_ts, last_run_ts)


def cleanup_orphaned_packages(engine: Engine) -> int:
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
        progress_desc="Writing cap/floor packages",
    )
    legs_written = upsert_dataframe(
        legs_df,
        engine,
        LEGS_TABLE,
        conflict_cols=["trade_id"],
        update_cols=LEG_UPSERT_UPDATE_COLUMNS,
        json_cols=["leg_metrics"],
        progress_desc="Writing cap/floor legs",
    )
    return packages_df, legs_df, packages_written, legs_written


def ingest_to_postgres(
    df: pd.DataFrame,
    engine: Engine,
    start: pd.Timestamp,
    end: pd.Timestamp,
) -> tuple[pd.DataFrame, pd.DataFrame, int, int]:
    packages_deleted, legs_deleted = delete_date_range(engine, start, end)
    if packages_deleted or legs_deleted:
        print(f"Deleted {packages_deleted} packages, {legs_deleted} legs in range")

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

    print("Cap/floor ingestion")
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
        print("No cap/floor trades found in date range.")
        return

    cleaned = normalize_dataframe(raw_df)
    packages_df = build_packages_dataframe(cleaned)
    legs_df = build_legs_dataframe(cleaned)
    if dry_run:
        print("Dry run enabled; skipping database writes.")
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
    cursor_ts = get_ingestion_cursor_timestamp(engine)
    end = pd.Timestamp.now(tz="UTC")
    start = end - timedelta(minutes=initial_lookback_minutes) if cursor_ts is None else cursor_ts - timedelta(seconds=overlap_seconds)
    if start > end:
        start = end

    fetch_start = start
    fetch_end = end
    if force_fetch_end_of_day or force_fetch_full_market_day:
        if force_fetch_full_market_day:
            fetch_start = _resolve_start_of_day_fetch_timestamp(end, market_timezone)
        fetch_end = _resolve_end_of_day_fetch_timestamp(end, market_timezone)

    print("Incremental cap/floor ingestion")
    print(f"  Last cursor: {cursor_ts}")
    print(f"  Range: {start} -> {end}")
    if force_fetch_full_market_day:
        print(f"  Classifier fetch range (full market day {market_timezone}): {fetch_start} -> {fetch_end}")
    elif force_fetch_end_of_day:
        print(f"  Classifier fetch end (forced EOD {market_timezone}): {fetch_end}")
    print(f"  Cache: {cache_path}")
    print(f"  Ignore cache: {ignore_cache}")
    print(f"  Only NEWT/TRAD: {only_newt}")
    print(f"  Dry run: {dry_run}")
    print()

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

    cleaned = normalize_dataframe(raw_df)
    packages_df = build_packages_dataframe(cleaned)
    legs_df = build_legs_dataframe(cleaned)
    if dry_run:
        print("Dry run enabled; skipping database writes.")
        print_summary(raw_df, packages_df, legs_df, 0, 0)
        return

    packages_df, legs_df, packages_written, legs_written = ingest_to_postgres(
        raw_df,
        engine,
        start=start,
        end=end,
    )
    if cleanup_orphans:
        orphaned = cleanup_orphaned_packages(engine)
        if orphaned:
            print(f"Removed {orphaned} orphaned packages.")
    print_summary(raw_df, packages_df, legs_df, packages_written, legs_written)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Ingest USD cap/floor classifications into SwapPulse Postgres.")
    parser.add_argument("--mode", choices=("range", "incremental"), default=os.getenv("SWAPPULSE_INGEST_MODE", "incremental"))
    parser.add_argument("--days", type=int, default=7)
    parser.add_argument("--start", type=str)
    parser.add_argument("--end", type=str)
    parser.add_argument("--cache-path", type=str)
    parser.add_argument("--ignore-cache", action="store_true")
    parser.add_argument("--only-newt", dest="only_newt", action="store_true")
    parser.add_argument("--no-only-newt", dest="only_newt", action="store_false")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--initial-lookback-minutes", type=int, default=24 * 60)
    parser.add_argument("--overlap-seconds", type=int, default=0)
    parser.add_argument("--no-cleanup-orphans", action="store_true")
    parser.set_defaults(only_newt=False)
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
    cache_path = _resolve_cache_path(args.cache_path)
    if args.mode == "range":
        main(
            start=_parse_timestamp_arg(args.start, "start"),
            end=_parse_timestamp_arg(args.end, "end"),
            days=args.days,
            cache_path=cache_path,
            ignore_cache=args.ignore_cache,
            only_newt=args.only_newt,
            dry_run=args.dry_run,
        )
    else:
        engine = create_db_engine()
        ensure_schema(engine)
        ingest_incremental_once(
            engine,
            cache_path=cache_path,
            only_newt=args.only_newt,
            dry_run=args.dry_run,
            cleanup_orphans=not args.no_cleanup_orphans,
            initial_lookback_minutes=args.initial_lookback_minutes,
            overlap_seconds=args.overlap_seconds,
            force_fetch_end_of_day=True,
            force_fetch_full_market_day=True,
        )
