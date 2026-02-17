"""
Periodic UST RV ingestion into Postgres.

This script snapshots live UST RV points from MDPs and upserts them into
versioned tables for the dashboard to read quickly.
"""

from __future__ import annotations

import argparse
import datetime
import math
import os
import time
from typing import Any, Dict, Iterable, Optional, Tuple
from urllib.parse import quote_plus

import numpy as np
import pandas as pd
import QuantLib as ql
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from tqdm import tqdm


POINTS_TABLE = "arbs_ust_rv_points_v1"
RUNS_TABLE = "arbs_ust_rv_ingestion_runs_v1"

SCHEMA_SQL = f"""
CREATE TABLE IF NOT EXISTS {POINTS_TABLE} (
    as_of_date DATE NOT NULL,
    curve_name TEXT NOT NULL,
    cusip TEXT NOT NULL,
    oi TEXT,
    ust_label TEXT,
    rank INTEGER,
    ttm NUMERIC,
    mdur NUMERIC,
    ytm NUMERIC,
    mmss NUMERIC,
    clean_price NUMERIC,
    dirty_price NUMERIC,
    coupon NUMERIC,
    issue_date DATE,
    maturity_date DATE,
    market_timestamp TIMESTAMPTZ,
    snapshot_ts TIMESTAMPTZ NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (as_of_date, curve_name, cusip)
);

CREATE TABLE IF NOT EXISTS {RUNS_TABLE} (
    run_id BIGSERIAL PRIMARY KEY,
    ingestion_started_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    as_of_date DATE NOT NULL,
    curve_name TEXT NOT NULL,
    snapshot_ts TIMESTAMPTZ NOT NULL,
    points_written INTEGER,
    notes TEXT
);

CREATE INDEX IF NOT EXISTS idx_ust_rv_points_curve_date ON {POINTS_TABLE}(curve_name, as_of_date);
CREATE INDEX IF NOT EXISTS idx_ust_rv_points_snapshot ON {POINTS_TABLE}(snapshot_ts DESC);
CREATE INDEX IF NOT EXISTS idx_ust_rv_runs_date ON {RUNS_TABLE}(as_of_date, ingestion_started_at DESC);
"""

NUMERIC_COLUMNS: tuple[str, ...] = (
    "rank",
    "ttm",
    "mdur",
    "ytm",
    "mmss",
    "clean_price",
    "dirty_price",
    "coupon",
)


def _safe_float(x: Any) -> Optional[float]:
    try:
        y = float(x)
    except Exception:
        return None
    if np.isnan(y) or np.isinf(y):
        return None
    return y


def _to_iso(val: Any):
    if isinstance(val, (datetime.datetime, datetime.date)):
        return val.isoformat()
    return val


def _to_utc_timestamp(val: Any) -> Optional[pd.Timestamp]:
    if val is None:
        return None
    try:
        ts = pd.Timestamp(val)
    except Exception:
        return None
    if ts.tzinfo is None:
        return ts.tz_localize("UTC")
    return ts.tz_convert("UTC")


def _adjust_to_business_day(d: datetime.date) -> datetime.date:
    cal = ql.UnitedStates(ql.UnitedStates.GovernmentBond)
    probe = ql.Date(d.day, d.month, d.year)
    while not cal.isBusinessDay(probe):
        probe = cal.advance(probe, ql.Period(-1, ql.Days))
    return datetime.date(probe.year(), probe.month(), probe.dayOfMonth())


def _ensure_numeric_columns(df: pd.DataFrame, cols: Iterable[str]) -> pd.DataFrame:
    out = df.copy()
    for c in cols:
        if c in out.columns:
            out[c] = pd.to_numeric(out[c], errors="coerce")
    return out


def _extract_cusip_from_query_name(text: str) -> Optional[str]:
    import re

    match = re.search(r"\b[0-9A-Z]{9}\b", str(text or "").upper())
    return match.group(0) if match else None


def get_db_connection_string(override: Optional[str] = None) -> str:
    """
    Resolve Postgres connection string.

    Precedence:
      1) explicit override (CLI --database-url)
      2) SWAPPULSE_DATABASE_URL
      3) DATABASE_URL
      4) SWAPPULSE_DB_* component variables
      5) MVP hardcoded fallback defaults
    """
    if override and str(override).strip():
        conn_string = str(override).strip()
    else:
        conn_string = ""
        for key in ("SWAPPULSE_DATABASE_URL", "DATABASE_URL"):
            raw = os.getenv(key)
            if raw and raw.strip():
                conn_string = raw.strip()
                break

    if conn_string:
        if conn_string.startswith("postgres://"):
            conn_string = "postgresql://" + conn_string[len("postgres://") :]
        return conn_string

    host = os.getenv("SWAPPULSE_DB_HOST", "aws-0-us-east-1.pooler.supabase.com").strip()
    port = os.getenv("SWAPPULSE_DB_PORT", "6543").strip()
    dbname = os.getenv("SWAPPULSE_DB_NAME", "postgres").strip()
    user = os.getenv("SWAPPULSE_DB_USER", "postgres.rdobtpugtnmefxplgwyp").strip()
    password = os.getenv("SWAPPULSE_DB_PASSWORD", "0rbZUh8y0Fsvdlry").strip()
    sslmode = os.getenv("SWAPPULSE_DB_SSLMODE", "").strip()

    auth_user = quote_plus(user)
    auth_password = quote_plus(password)
    conn_string = f"postgresql://{auth_user}:{auth_password}@{host}:{port}/{dbname}"
    if sslmode:
        conn_string += f"?sslmode={sslmode}"
    return conn_string


def create_db_engine(connection_string: Optional[str] = None) -> Engine:
    conn_string = get_db_connection_string(connection_string)
    return create_engine(
        conn_string,
        pool_size=5,
        max_overflow=10,
        pool_timeout=30,
        pool_recycle=1800,
        pool_pre_ping=True,
    )


def ensure_schema(engine: Engine) -> None:
    with engine.begin() as conn:
        for statement in SCHEMA_SQL.split(";"):
            stmt = statement.strip()
            if stmt:
                conn.execute(text(stmt))


def _pythonify(val: Any) -> Any:
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
        pass
    if isinstance(val, pd.Timestamp):
        return val.isoformat()
    if hasattr(val, "item"):
        try:
            return val.item()
        except Exception:
            pass
    return val


def upsert_dataframe(
    df: pd.DataFrame,
    engine: Engine,
    table_name: str,
    conflict_cols: Iterable[str],
    update_cols: Iterable[str],
    batch_size: int = 1000,
    progress_desc: Optional[str] = None,
) -> int:
    if df.empty:
        return 0

    records = df.to_dict(orient="records")
    records = [{k: _pythonify(v) for k, v in rec.items()} for rec in records]
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
    as_of_date: datetime.date,
    curve_name: str,
    snapshot_ts: pd.Timestamp,
    points_written: int,
    notes: Optional[str] = None,
) -> None:
    with engine.begin() as conn:
        conn.execute(
            text(
                f"""
                INSERT INTO {RUNS_TABLE} (
                    as_of_date,
                    curve_name,
                    snapshot_ts,
                    points_written,
                    notes
                )
                VALUES (:as_of_date, :curve_name, :snapshot_ts, :points_written, :notes)
                """
            ),
            dict(
                as_of_date=as_of_date,
                curve_name=curve_name,
                snapshot_ts=snapshot_ts.to_pydatetime(),
                points_written=points_written,
                notes=notes,
            ),
        )


def delete_stale_points(
    engine: Engine,
    *,
    as_of_date: datetime.date,
    curve_name: str,
    active_cusips: list[str],
) -> int:
    if not active_cusips:
        with engine.begin() as conn:
            res = conn.execute(
                text(
                    f"""
                    DELETE FROM {POINTS_TABLE}
                    WHERE as_of_date = :as_of_date
                      AND curve_name = :curve_name
                    """
                ),
                dict(as_of_date=as_of_date, curve_name=curve_name),
            )
        return int(res.rowcount or 0)

    with engine.begin() as conn:
        res = conn.execute(
            text(
                f"""
                DELETE FROM {POINTS_TABLE}
                WHERE as_of_date = :as_of_date
                  AND curve_name = :curve_name
                  AND NOT (cusip = ANY(:active_cusips))
                """
            ),
            dict(as_of_date=as_of_date, curve_name=curve_name, active_cusips=active_cusips),
        )
    return int(res.rowcount or 0)


def build_points_dataframe(
    *,
    as_of_date: datetime.date,
    curve_name: str,
    min_ttm: float,
    include_mmss: bool,
) -> pd.DataFrame:
    from MDP.FixedRateBonds.FixedRateBondsMDP import FixedRateBondsMDP
    from MDP.IRSwaps.IRSwapsMDP import IRSwapsMDP
    from Query.IRSwaps.IRSwapQuery import IRSwapQuery
    from Query.IRSwaps.IRSwapValue import IRSwapValue
    from TB.FixedRateBondsTB import FixedRateBondsTB
    from TB.IRSwapsTB import IRSwapsTB
    from TB.TimeseriesBuilder import TimeseriesBuilder

    usts_mdp = FixedRateBondsMDP(source="USTS_FEDINVEST_WSJ_LIVE-QL")
    ref_df = usts_mdp.get_bond_reference_data(as_of_date=as_of_date).copy()
    ref_df = ref_df.drop(columns=["record_date"], errors="ignore").rename(columns={"label": "ust_label"})
    ref_df = _ensure_numeric_columns(ref_df, ["ttm", "rank", "cpn"])
    ref_df = ref_df[ref_df["ttm"] >= min_ttm].copy()
    ref_df["cusip"] = ref_df["cusip"].astype(str)
    ref_df = ref_df.drop_duplicates(subset=["cusip"], keep="last")

    if ref_df.empty:
        return pd.DataFrame()

    ts_for_pricing: datetime.date | str = "live" if as_of_date == datetime.date.today() else as_of_date
    pricers = usts_mdp.get_pricer(
        request={
            "cusips": ref_df["cusip"].tolist(),
            "timestamp": ts_for_pricing,
            "show_tqdm": False,
        }
    )

    metrics: list[Dict[str, Any]] = []
    for cusip, pricer in pricers.items():
        meta = {}
        try:
            meta = pricer.meta() or {}
        except Exception:
            meta = {}
        metrics.append(
            {
                "cusip": str(cusip),
                "ytm": _safe_float(pricer.ytm() if hasattr(pricer, "ytm") else None),
                "mdur": _safe_float(pricer.mod_duration() if hasattr(pricer, "mod_duration") else None),
                "clean_price": _safe_float(pricer.clean_price() if hasattr(pricer, "clean_price") else None),
                "dirty_price": _safe_float(pricer.dirty_price() if hasattr(pricer, "dirty_price") else None),
                "market_timestamp": _to_utc_timestamp(meta.get("timestamp")),
            }
        )
    metrics_df = pd.DataFrame(metrics)
    merged_df = ref_df.merge(metrics_df, on="cusip", how="left")

    if include_mmss and not merged_df.empty:
        swaps_mdp = IRSwapsMDP(source="ERIS_EOD_LIVE-RL_BASIC")
        tb = TimeseriesBuilder(
            irswaps_tb=IRSwapsTB(swaps_mdp),
            fixedratebonds_tb=FixedRateBondsTB(usts_mdp),
        )
        queries = [
            IRSwapQuery(curve=curve_name, tenor=c, value=IRSwapValue.MMSS)
            for c in merged_df["cusip"].tolist()
        ]
        ts_df = tb.get_timeseries(
            start=as_of_date,
            end=as_of_date,
            queries=queries,
            n_jobs=5,
        )
        mmss_map: Dict[str, float] = {}
        if ts_df is not None and not ts_df.empty:
            latest = ts_df.iloc[-1]
            for col_name, val in latest.items():
                cusip = _extract_cusip_from_query_name(col_name)
                fv = _safe_float(val)
                if cusip and fv is not None:
                    mmss_map[cusip] = fv
        merged_df["mmss"] = merged_df["cusip"].map(mmss_map)
    else:
        merged_df["mmss"] = np.nan

    merged_df["coupon"] = merged_df["cpn"] if "cpn" in merged_df.columns else np.nan
    merged_df = _ensure_numeric_columns(merged_df, NUMERIC_COLUMNS)
    merged_df = merged_df.sort_values(by=["ttm", "oi", "rank"], kind="mergesort")

    keep_cols = [
        "cusip",
        "oi",
        "ust_label",
        "rank",
        "ttm",
        "mdur",
        "ytm",
        "mmss",
        "clean_price",
        "dirty_price",
        "coupon",
        "issue_date",
        "maturity_date",
        "market_timestamp",
    ]
    for col in keep_cols:
        if col not in merged_df.columns:
            merged_df[col] = None

    out = merged_df[keep_cols].copy()
    out["as_of_date"] = as_of_date
    out["curve_name"] = curve_name
    return out


def ingest_snapshot(
    engine: Engine,
    *,
    as_of_date: datetime.date,
    curve_name: str,
    min_ttm: float,
    include_mmss: bool,
    dry_run: bool,
) -> Tuple[int, int]:
    points_df = build_points_dataframe(
        as_of_date=as_of_date,
        curve_name=curve_name,
        min_ttm=min_ttm,
        include_mmss=include_mmss,
    )

    if points_df.empty:
        print(f"No points returned for {as_of_date} ({curve_name}).")
        if not dry_run:
            record_ingestion_run(
                engine,
                as_of_date=as_of_date,
                curve_name=curve_name,
                snapshot_ts=pd.Timestamp.now(tz="UTC"),
                points_written=0,
                notes="No points returned from MDPs",
            )
        return 0, 0

    snapshot_ts = pd.Timestamp.now(tz="UTC")
    points_df["snapshot_ts"] = snapshot_ts

    print(
        f"Snapshot {as_of_date} ({curve_name}): "
        f"points={len(points_df)} "
        f"otrs={int((points_df['rank'] == 0).sum())} "
        f"mmss_non_null={int(points_df['mmss'].notna().sum())}"
    )

    if dry_run:
        print("Dry run enabled; skipping database writes.")
        return len(points_df), 0

    points_written = upsert_dataframe(
        points_df,
        engine=engine,
        table_name=POINTS_TABLE,
        conflict_cols=("as_of_date", "curve_name", "cusip"),
        update_cols=(
            "oi",
            "ust_label",
            "rank",
            "ttm",
            "mdur",
            "ytm",
            "mmss",
            "clean_price",
            "dirty_price",
            "coupon",
            "issue_date",
            "maturity_date",
            "market_timestamp",
            "snapshot_ts",
        ),
        progress_desc="Writing UST RV points",
    )
    deleted = delete_stale_points(
        engine,
        as_of_date=as_of_date,
        curve_name=curve_name,
        active_cusips=points_df["cusip"].astype(str).tolist(),
    )
    record_ingestion_run(
        engine,
        as_of_date=as_of_date,
        curve_name=curve_name,
        snapshot_ts=snapshot_ts,
        points_written=points_written,
    )
    return points_written, deleted


def _parse_date(raw: str, arg_name: str) -> datetime.date:
    txt = (raw or "").strip()
    if not txt:
        raise ValueError(f"--{arg_name} cannot be empty")
    if txt.lower() in {"today", "live"}:
        return datetime.date.today()
    try:
        return datetime.date.fromisoformat(txt)
    except Exception as exc:
        raise ValueError(f"Invalid --{arg_name}: {raw}. Expected YYYY-MM-DD.") from exc


def _date_range_business_days(start_date: datetime.date, end_date: datetime.date) -> list[datetime.date]:
    if start_date > end_date:
        raise ValueError(f"start_date must be <= end_date. Got {start_date} > {end_date}.")
    cal = ql.UnitedStates(ql.UnitedStates.GovernmentBond)
    out: list[datetime.date] = []
    current = start_date
    while current <= end_date:
        qd = ql.Date(current.day, current.month, current.year)
        if cal.isBusinessDay(qd):
            out.append(current)
        current += datetime.timedelta(days=1)
    return out


def run_range_mode(
    *,
    engine: Engine,
    start_date: datetime.date,
    end_date: datetime.date,
    curve_name: str,
    min_ttm: float,
    include_mmss: bool,
    dry_run: bool,
    stop_on_error: bool = False,
) -> None:
    days = _date_range_business_days(start_date, end_date)
    if not days:
        print(f"No business days between {start_date} and {end_date}.")
        return
    print(f"Ingesting {len(days)} business day snapshots...")
    total_written = 0
    total_deleted = 0
    failed_days: list[tuple[datetime.date, str]] = []
    for d in days:
        try:
            written, deleted = ingest_snapshot(
                engine,
                as_of_date=d,
                curve_name=curve_name,
                min_ttm=min_ttm,
                include_mmss=include_mmss,
                dry_run=dry_run,
            )
            total_written += int(written)
            total_deleted += int(deleted)
        except Exception as exc:
            err = f"{type(exc).__name__}: {exc}"
            failed_days.append((d, err))
            print(f"Range mode failed for {d}: {err}")
            if stop_on_error:
                raise

    print(
        f"Range mode complete. points_written={total_written}, "
        f"stale_deleted={total_deleted}, failed_days={len(failed_days)}"
    )
    if failed_days:
        print("Range mode failed dates:")
        for d, err in failed_days:
            print(f"  {d}: {err}")


def _coerce_db_date(val: Any) -> Optional[datetime.date]:
    if val is None:
        return None
    if isinstance(val, datetime.datetime):
        return val.date()
    if isinstance(val, datetime.date):
        return val
    try:
        return datetime.date.fromisoformat(str(val))
    except Exception:
        return None


def get_existing_snapshot_dates(
    engine: Engine,
    *,
    curve_name: str,
    start_date: datetime.date,
    end_date: datetime.date,
) -> set[datetime.date]:
    with engine.begin() as conn:
        rows = conn.execute(
            text(
                f"""
                SELECT DISTINCT as_of_date
                FROM {POINTS_TABLE}
                WHERE curve_name = :curve_name
                  AND as_of_date BETWEEN :start_date AND :end_date
                """
            ),
            dict(curve_name=curve_name, start_date=start_date, end_date=end_date),
        ).fetchall()

    out: set[datetime.date] = set()
    for row in rows:
        d = _coerce_db_date(row[0] if row else None)
        if d is not None:
            out.add(d)
    return out


def run_historical_backfill_mode(
    *,
    engine: Engine,
    start_date: datetime.date,
    end_date: datetime.date,
    curve_name: str,
    min_ttm: float,
    include_mmss: bool,
    dry_run: bool,
    skip_existing: bool,
    stop_on_error: bool = False,
) -> None:
    all_days = _date_range_business_days(start_date, end_date)
    if not all_days:
        print(f"No business days between {start_date} and {end_date}.")
        return

    if skip_existing and not dry_run:
        existing = get_existing_snapshot_dates(
            engine,
            curve_name=curve_name,
            start_date=start_date,
            end_date=end_date,
        )
        days = [d for d in all_days if d not in existing]
        print(
            f"Historical backfill business days={len(all_days)}, "
            f"existing={len(existing)}, remaining={len(days)}"
        )
    else:
        days = all_days
        print(f"Historical backfill business days={len(days)}")

    if not days:
        print("Historical backfill complete: nothing new to ingest.")
        return

    total_written = 0
    total_deleted = 0
    failed_days: list[tuple[datetime.date, str]] = []
    for d in days:
        try:
            written, deleted = ingest_snapshot(
                engine,
                as_of_date=d,
                curve_name=curve_name,
                min_ttm=min_ttm,
                include_mmss=include_mmss,
                dry_run=dry_run,
            )
            total_written += int(written)
            total_deleted += int(deleted)
        except Exception as exc:
            err = f"{type(exc).__name__}: {exc}"
            failed_days.append((d, err))
            print(f"Historical backfill failed for {d}: {err}")
            if stop_on_error:
                raise

    print(
        "Historical backfill complete. "
        f"days_processed={len(days)}, points_written={total_written}, "
        f"stale_deleted={total_deleted}, failed_days={len(failed_days)}"
    )
    if failed_days:
        print("Historical backfill failed dates:")
        for d, err in failed_days:
            print(f"  {d}: {err}")


def run_incremental_mode(
    *,
    engine: Engine,
    as_of_date: datetime.date,
    curve_name: str,
    min_ttm: float,
    include_mmss: bool,
    dry_run: bool,
) -> None:
    effective_date = _adjust_to_business_day(as_of_date)
    if effective_date != as_of_date:
        print(f"Adjusted as_of from {as_of_date} to prior business day {effective_date}.")
    written, deleted = ingest_snapshot(
        engine,
        as_of_date=effective_date,
        curve_name=curve_name,
        min_ttm=min_ttm,
        include_mmss=include_mmss,
        dry_run=dry_run,
    )
    print(f"Incremental mode complete. points_written={written}, stale_deleted={deleted}")


def run_service_mode(
    *,
    engine: Engine,
    interval_seconds: int,
    curve_name: str,
    min_ttm: float,
    include_mmss: bool,
    dry_run: bool,
    service_backfill_days: int,
    max_iterations: Optional[int],
    stop_on_error: bool,
) -> None:
    if interval_seconds <= 0:
        raise ValueError(f"interval_seconds must be > 0, got {interval_seconds}")
    if service_backfill_days < 0:
        raise ValueError(
            f"service_backfill_days must be >= 0, got {service_backfill_days}"
        )
    if max_iterations is not None and max_iterations <= 0:
        raise ValueError(f"max_iterations must be > 0 when provided, got {max_iterations}")

    print("Starting UST RV ingestion service")
    print(f"  Interval: {interval_seconds}s")
    print(f"  Curve: {curve_name}")
    print(f"  Min TTM: {min_ttm}")
    print(f"  Include MMSS: {include_mmss}")
    print(f"  Dry run: {dry_run}")
    if service_backfill_days > 0:
        print(f"  Startup backfill lookback: {service_backfill_days} calendar days")
    else:
        print("  Startup backfill lookback: disabled")
    if max_iterations is not None:
        print(f"  Max iterations: {max_iterations}")
    print()

    if service_backfill_days > 0:
        backfill_end = datetime.date.today()
        backfill_start = backfill_end - datetime.timedelta(days=service_backfill_days)
        print(
            "Running startup historical backfill before service loop: "
            f"{backfill_start} -> {backfill_end}"
        )
        run_historical_backfill_mode(
            engine=engine,
            start_date=backfill_start,
            end_date=backfill_end,
            curve_name=curve_name,
            min_ttm=min_ttm,
            include_mmss=include_mmss,
            dry_run=dry_run,
            skip_existing=False,
            stop_on_error=stop_on_error,
        )
        print("Startup historical backfill finished.\n")

    iteration = 0
    while True:
        iteration += 1
        cycle_start = time.monotonic()
        wall = pd.Timestamp.now(tz="UTC")
        as_of = _adjust_to_business_day(wall.date())
        print(f"[{wall.isoformat()}] UST RV cycle {iteration} (as_of={as_of})")
        try:
            written, deleted = ingest_snapshot(
                engine,
                as_of_date=as_of,
                curve_name=curve_name,
                min_ttm=min_ttm,
                include_mmss=include_mmss,
                dry_run=dry_run,
            )
            print(f"Cycle {iteration} complete. points_written={written}, stale_deleted={deleted}")
        except Exception as exc:
            print(f"Cycle {iteration} failed: {exc}")
            if stop_on_error:
                raise

        if max_iterations is not None and iteration >= max_iterations:
            print("Reached max iterations; exiting.")
            break

        elapsed = time.monotonic() - cycle_start
        sleep_seconds = max(0.0, interval_seconds - elapsed)
        print(f"Sleeping {sleep_seconds:.1f}s...\n")
        time.sleep(sleep_seconds)


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None or raw == "":
        return default
    return int(raw)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Ingest UST RV points into SwapPulse Postgres.")
    parser.add_argument(
        "--database-url",
        type=str,
        default=os.getenv("SWAPPULSE_DATABASE_URL", os.getenv("DATABASE_URL")),
        help=(
            "Postgres connection URL. If omitted, resolves from "
            "SWAPPULSE_DATABASE_URL, then DATABASE_URL, then SWAPPULSE_DB_* vars."
        ),
    )
    parser.add_argument(
        "--mode",
        choices=("range", "historical", "incremental", "service"),
        default=os.getenv("SWAPPULSE_USTRV_INGEST_MODE", "incremental"),
        help=(
            "range=custom date range backfill, historical=long-range backfill for "
            "timeseries history, incremental=single snapshot, service=continuous loop."
        ),
    )
    parser.add_argument(
        "--curve-name",
        type=str,
        default=os.getenv("SWAPPULSE_USTRV_CURVE_NAME", "USD-SOFR-1D"),
        help="Curve name used for MMSS queries.",
    )
    parser.add_argument(
        "--min-ttm",
        type=float,
        default=float(os.getenv("SWAPPULSE_USTRV_MIN_TTM", "1.0")),
        help="Minimum TTM filter applied at ingestion time.",
    )
    parser.add_argument(
        "--no-mmss",
        action="store_true",
        help="Skip MMSS computation.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Build snapshots but skip writes.",
    )

    parser.add_argument(
        "--as-of",
        type=str,
        help="Incremental mode as-of date (YYYY-MM-DD, today, live). Defaults to today.",
    )

    parser.add_argument(
        "--start-date",
        type=str,
        help="Range mode start date (YYYY-MM-DD).",
    )
    parser.add_argument(
        "--end-date",
        type=str,
        help="Range mode end date (YYYY-MM-DD).",
    )
    parser.add_argument(
        "--days",
        type=int,
        default=7,
        help="Range mode fallback lookback days when start/end are omitted.",
    )
    parser.add_argument(
        "--historical-start-date",
        type=str,
        default=os.getenv("SWAPPULSE_USTRV_HISTORICAL_START_DATE"),
        help="Historical mode start date (YYYY-MM-DD).",
    )
    parser.add_argument(
        "--historical-end-date",
        type=str,
        default=os.getenv("SWAPPULSE_USTRV_HISTORICAL_END_DATE"),
        help="Historical mode end date (YYYY-MM-DD). Defaults to today.",
    )
    parser.add_argument(
        "--historical-years",
        type=int,
        default=_env_int("SWAPPULSE_USTRV_HISTORICAL_YEARS", 10),
        help="Historical mode fallback lookback years when start date is omitted.",
    )
    parser.add_argument(
        "--include-existing",
        action="store_true",
        help="Historical mode: reprocess dates already present in DB.",
    )

    parser.add_argument(
        "--interval-seconds",
        type=int,
        default=_env_int("SWAPPULSE_USTRV_INTERVAL_SECONDS", 120),
        help="Service mode polling interval in seconds.",
    )
    parser.add_argument(
        "--service-backfill-days",
        type=int,
        default=_env_int("SWAPPULSE_USTRV_SERVICE_BACKFILL_DAYS", 7),
        help=(
            "Service mode only: on startup, reprocess this many calendar days "
            "of history (business-day filtered). Set to 0 to disable."
        ),
    )
    parser.add_argument(
        "--max-iterations",
        type=int,
        help="Service mode only: stop after this many cycles.",
    )
    parser.add_argument(
        "--stop-on-error",
        action="store_true",
        help=(
            "Exit immediately on first error. "
            "In range/historical modes this stops at first failed date; "
            "in service mode it stops at first failed cycle."
        ),
    )
    return parser.parse_args()


def _resolve_range_dates(
    start_raw: Optional[str],
    end_raw: Optional[str],
    days: int,
) -> tuple[datetime.date, datetime.date]:
    if days <= 0:
        raise ValueError(f"--days must be > 0, got {days}")

    today = datetime.date.today()
    if start_raw:
        start_date = _parse_date(start_raw, "start-date")
    else:
        start_date = today - datetime.timedelta(days=days)

    if end_raw:
        end_date = _parse_date(end_raw, "end-date")
    else:
        end_date = today
    return start_date, end_date


def _resolve_historical_dates(
    start_raw: Optional[str],
    end_raw: Optional[str],
    years: int,
) -> tuple[datetime.date, datetime.date]:
    if years <= 0:
        raise ValueError(f"--historical-years must be > 0, got {years}")

    today = datetime.date.today()
    if start_raw:
        start_date = _parse_date(start_raw, "historical-start-date")
    else:
        start_date = today - datetime.timedelta(days=365 * years)

    if end_raw:
        end_date = _parse_date(end_raw, "historical-end-date")
    else:
        end_date = today
    return start_date, end_date


if __name__ == "__main__":
    args = parse_args()
    include_mmss = not args.no_mmss
    engine = create_db_engine(args.database_url)
    ensure_schema(engine)

    if args.mode == "range":
        start_date, end_date = _resolve_range_dates(args.start_date, args.end_date, args.days)
        run_range_mode(
            engine=engine,
            start_date=start_date,
            end_date=end_date,
            curve_name=args.curve_name,
            min_ttm=args.min_ttm,
            include_mmss=include_mmss,
            dry_run=args.dry_run,
            stop_on_error=args.stop_on_error,
        )
    elif args.mode == "historical":
        start_date, end_date = _resolve_historical_dates(
            args.historical_start_date,
            args.historical_end_date,
            args.historical_years,
        )
        run_historical_backfill_mode(
            engine=engine,
            start_date=start_date,
            end_date=end_date,
            curve_name=args.curve_name,
            min_ttm=args.min_ttm,
            include_mmss=include_mmss,
            dry_run=args.dry_run,
            skip_existing=not args.include_existing,
            stop_on_error=args.stop_on_error,
        )
    elif args.mode == "incremental":
        as_of = _parse_date(args.as_of, "as-of") if args.as_of else datetime.date.today()
        run_incremental_mode(
            engine=engine,
            as_of_date=as_of,
            curve_name=args.curve_name,
            min_ttm=args.min_ttm,
            include_mmss=include_mmss,
            dry_run=args.dry_run,
        )
    else:
        run_service_mode(
            engine=engine,
            interval_seconds=args.interval_seconds,
            curve_name=args.curve_name,
            min_ttm=args.min_ttm,
            include_mmss=include_mmss,
            dry_run=args.dry_run,
            service_backfill_days=args.service_backfill_days,
            max_iterations=args.max_iterations,
            stop_on_error=args.stop_on_error,
        )
