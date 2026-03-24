#!/usr/bin/env python
"""Repair local and Supabase STIR Q12STIRT intraday timeseries state.

This wrapper is intentionally opinionated for the known repair target:
    curve  = USD-SOFR-1D-Q12STIRT
    source = BARCHART_STIRF-RL
    tenors = IMM_1xIMM_2 .. IMM_12xIMM_13
    range  = 2025-01-01 .. 2026-03-20

Workflow:
1. Rebuild the local computed intraday timeseries cache via stirf_curve_service.py
   in local-only chunks, with L2 disabled.
2. Compare local artifacts against Supabase.
3. Push only missing or stale curve blocks, computed day blocks, and row-table
   rows until verification passes.

The script is resumable. If interrupted, rerun it and it will continue from the
saved local chunk state and re-diff Supabase from the repaired local cache.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import logging
import math
import os
import re
import subprocess
import sys
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterable, Sequence

import pandas as pd
import QuantLib as ql
from sqlalchemy import text

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from BT.misc import ql_cal_date_range
from Caching.curve_store import CurveStore
from Caching.supabase_computed_timeseries_sync import (
    COMPUTED_TIMESERIES_BLOCKS_TABLE,
    SupabaseComputedTimeseriesSync,
)
from Caching.supabase_curve_sync import (
    CURVE_INTRADAY_BLOCKS_TABLE,
    SupabaseCurveSync,
)
from Caching.supabase_engine import get_engine
from Caching.timeseries_cache import read_timeseries
from Query.Unified.UnifiedQuery import UnifiedQuery
from Query.Unified.registry import UnifiedValue
from TB.IRSwapsTB import _query_fingerprint

DEFAULT_SOURCE = "BARCHART_STIRF-RL"
DEFAULT_CURVE_NAME = "USD-SOFR-1D-Q12STIRT"
DEFAULT_START_DATE = dt.date(2025, 1, 1)
DEFAULT_END_DATE = dt.date(2026, 3, 20)
DEFAULT_N_JOBS = 12
DEFAULT_LOCAL_CHUNK_BUSINESS_DAYS = 5
DEFAULT_ROW_BATCH_DAYS = 25
DEFAULT_MAX_RETRIES = 3
DEFAULT_RETRY_SLEEP_SECONDS = 5.0
DEFAULT_VERIFICATION_ROUNDS = 3
DEFAULT_STATE_DIR = REPO_ROOT / "tmp" / "stirf_q12stirt_repair"
DEFAULT_STATE_PATH = DEFAULT_STATE_DIR / "state.json"
DEFAULT_REPORT_PATH = DEFAULT_STATE_DIR / "final_report.json"
DEFAULT_LOG_PATH = DEFAULT_STATE_DIR / "run.log"
IMM_TENORS = tuple(f"IMM_{idx}xIMM_{idx + 1}" for idx in range(1, 13))
_CURVE_SANITIZE_RX = re.compile(r"[^\w.\-]")


@dataclass(frozen=True)
class LocalChunk:
    start_date: dt.date
    end_date: dt.date

    @property
    def key(self) -> str:
        return f"{self.start_date.isoformat()}::{self.end_date.isoformat()}"


@dataclass(frozen=True)
class RepairConfig:
    curve_name: str
    source: str
    start_date: dt.date
    end_date: dt.date
    tenors: tuple[str, ...]
    n_jobs: int
    local_chunk_business_days: int
    row_batch_days: int
    max_retries: int
    retry_sleep_seconds: float
    verification_rounds: int
    state_path: Path
    report_path: Path
    log_path: Path
    ts_base_dir: Path
    sync_curve_blocks: bool
    skip_local: bool
    skip_supabase: bool
    reset_state: bool


def _parse_date(value: str) -> dt.date:
    return dt.date.fromisoformat(str(value).strip())


def _chunked[T](values: Sequence[T], chunk_size: int) -> list[list[T]]:
    if chunk_size <= 0:
        raise ValueError("chunk_size must be positive")
    return [list(values[idx : idx + chunk_size]) for idx in range(0, len(values), chunk_size)]


def _configure_logging(log_path: Path) -> logging.Logger:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger("stirf_q12stirt_repair")
    logger.setLevel(logging.INFO)
    logger.handlers.clear()
    formatter = logging.Formatter("%(asctime)s %(levelname)s %(message)s")

    file_handler = logging.FileHandler(log_path, encoding="utf-8")
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)

    stream_handler = logging.StreamHandler(sys.stdout)
    stream_handler.setFormatter(formatter)
    logger.addHandler(stream_handler)

    return logger


def _warn_if_not_stir_env(logger: logging.Logger) -> None:
    active = os.environ.get("CONDA_DEFAULT_ENV", "")
    python_path = str(sys.executable).replace("/", "\\").lower()
    using_stir_python = "\\envs\\stir\\" in python_path
    if active.strip().lower() != "stir" and not using_stir_python:
        logger.warning(
            "Expected to run from the 'stir' conda env. Active env=%r, python=%s",
            active,
            sys.executable,
        )


def _sanitize_curve_name(curve_name: str) -> str:
    return _CURVE_SANITIZE_RX.sub("_", curve_name)


def _symbol_for_tenor(*, curve_name: str, source: str, tenor: str) -> str:
    query = UnifiedQuery(curve=curve_name, tenor=tenor, value=UnifiedValue.IRS_RATE)
    legacy = query.return_query()[0].to_legacy()
    return f"IRS::{source}::{curve_name}::{_query_fingerprint(legacy)}"


def _business_days(start_date: dt.date, end_date: dt.date) -> list[dt.date]:
    calendar = ql.UnitedStates(ql.UnitedStates.GovernmentBond)
    start = dt.datetime.combine(start_date, dt.time())
    end = dt.datetime.combine(end_date, dt.time())
    return list(
        ql_cal_date_range(
            calendar,
            start=start,
            end=end,
            freq="1b",
            to_date=True,
        )
    )


def _build_local_chunks(config: RepairConfig) -> list[LocalChunk]:
    business_days = _business_days(config.start_date, config.end_date)
    return [
        LocalChunk(start_date=chunk[0], end_date=chunk[-1])
        for chunk in _chunked(business_days, config.local_chunk_business_days)
        if chunk
    ]


def _build_local_backfill_command(
    *,
    python_executable: str,
    config: RepairConfig,
    chunk: LocalChunk,
    perf_log_path: Path,
) -> list[str]:
    cmd = [
        python_executable,
        str(REPO_ROOT / "scripts" / "stirf_curve_service.py"),
        "backfill",
        "--curve",
        config.curve_name,
        "--source",
        config.source,
        "--start-date",
        chunk.start_date.isoformat(),
        "--end-date",
        chunk.end_date.isoformat(),
        "--cme-session",
        "--skip-curve-warm",
        "--no-backfill-local-cache",
        "--disable-l2",
        "--hide-tqdm",
        "--n-jobs",
        str(config.n_jobs),
        "--perf-log-path",
        str(perf_log_path),
    ]
    for tenor in config.tenors:
        cmd.extend(["--tenor", tenor])
    return cmd


def _default_state(config: RepairConfig) -> dict[str, Any]:
    return {
        "version": 1,
        "config": {
            "curve_name": config.curve_name,
            "source": config.source,
            "start_date": config.start_date.isoformat(),
            "end_date": config.end_date.isoformat(),
            "tenors": list(config.tenors),
            "n_jobs": config.n_jobs,
            "local_chunk_business_days": config.local_chunk_business_days,
            "row_batch_days": config.row_batch_days,
        },
        "completed_local_chunks": [],
        "local_complete": False,
        "supabase_complete": False,
        "updated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
    }


def _load_state(config: RepairConfig, *, reset: bool) -> dict[str, Any]:
    if reset or not config.state_path.exists():
        return _default_state(config)
    with config.state_path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def _save_state(config: RepairConfig, state: dict[str, Any]) -> None:
    config.state_path.parent.mkdir(parents=True, exist_ok=True)
    state["updated_at"] = dt.datetime.now(dt.timezone.utc).isoformat()
    tmp_path = config.state_path.with_suffix(".tmp")
    tmp_path.write_text(json.dumps(state, indent=2, sort_keys=True), encoding="utf-8")
    tmp_path.replace(config.state_path)


def _run_with_retries(
    *,
    logger: logging.Logger,
    description: str,
    max_retries: int,
    retry_sleep_seconds: float,
    fn,
) -> Any:
    last_exc: BaseException | None = None
    for attempt in range(1, max_retries + 1):
        try:
            return fn()
        except BaseException as exc:  # pragma: no cover - exercised via integration usage
            last_exc = exc
            logger.warning("%s failed on attempt %s/%s: %s", description, attempt, max_retries, exc)
            if attempt >= max_retries:
                break
            time.sleep(retry_sleep_seconds)
    assert last_exc is not None
    raise last_exc


def _run_local_phase(config: RepairConfig, state: dict[str, Any], logger: logging.Logger) -> None:
    if config.skip_local or state.get("local_complete"):
        logger.info("Skipping local rebuild phase.")
        return

    completed = set(state.get("completed_local_chunks", []))
    chunks = _build_local_chunks(config)
    perf_dir = config.state_path.parent / "perf_logs"
    perf_dir.mkdir(parents=True, exist_ok=True)

    logger.info("Starting local rebuild across %s chunk(s).", len(chunks))
    for idx, chunk in enumerate(chunks, start=1):
        if chunk.key in completed:
            logger.info(
                "Local chunk %s/%s already complete: %s -> %s",
                idx,
                len(chunks),
                chunk.start_date.isoformat(),
                chunk.end_date.isoformat(),
            )
            continue

        perf_log_path = perf_dir / f"local_{chunk.start_date.isoformat()}_{chunk.end_date.isoformat()}.jsonl"
        cmd = _build_local_backfill_command(
            python_executable=sys.executable,
            config=config,
            chunk=chunk,
            perf_log_path=perf_log_path,
        )

        logger.info(
            "Running local chunk %s/%s: %s -> %s",
            idx,
            len(chunks),
            chunk.start_date.isoformat(),
            chunk.end_date.isoformat(),
        )
        _run_with_retries(
            logger=logger,
            description=f"local chunk {chunk.start_date.isoformat()}->{chunk.end_date.isoformat()}",
            max_retries=config.max_retries,
            retry_sleep_seconds=config.retry_sleep_seconds,
            fn=lambda cmd=cmd: subprocess.run(cmd, cwd=REPO_ROOT, check=True),
        )

        completed.add(chunk.key)
        state["completed_local_chunks"] = sorted(completed)
        _save_state(config, state)

    state["local_complete"] = True
    _save_state(config, state)
    logger.info("Local rebuild phase complete.")


def _partition_sha(part_dir: Path) -> str | None:
    files = sorted(part_dir.glob("*.parquet"))
    if not files:
        return None
    return files[-1].stem


def _iter_partition_days(asset_root: Path, *, start_date: dt.date, end_date: dt.date) -> list[dt.date]:
    out: list[dt.date] = []
    if not asset_root.exists():
        return out
    for child in sorted(asset_root.iterdir()):
        if not child.is_dir() or not child.name.startswith("date="):
            continue
        try:
            trading_date = dt.date.fromisoformat(child.name[5:])
        except ValueError:
            continue
        if start_date <= trading_date <= end_date and _partition_sha(child):
            out.append(trading_date)
    return out


def _curve_asset_root(curve_store: CurveStore, curve_name: str) -> Path:
    return curve_store.base_dir / "raw" / f"asset={_sanitize_curve_name(curve_name)}"


def _ts_asset_root(base_dir: Path, symbol: str) -> Path:
    from Caching.timeseries_cache import _sanitize_symbol

    return base_dir / f"asset={_sanitize_symbol(symbol)}"


def _local_curve_shas(config: RepairConfig) -> dict[dt.date, str]:
    curve_store = CurveStore.default()
    asset_root = _curve_asset_root(curve_store, config.curve_name)
    out: dict[dt.date, str] = {}
    for trading_date in _iter_partition_days(asset_root, start_date=config.start_date, end_date=config.end_date):
        sha = _partition_sha(asset_root / f"date={trading_date.isoformat()}")
        if sha:
            out[trading_date] = sha
    return out


def _local_ts_block_shas(config: RepairConfig, symbols: Sequence[str]) -> dict[str, dict[dt.date, str]]:
    out: dict[str, dict[dt.date, str]] = {}
    for symbol in symbols:
        asset_root = _ts_asset_root(config.ts_base_dir, symbol)
        per_day: dict[dt.date, str] = {}
        for trading_date in _iter_partition_days(asset_root, start_date=config.start_date, end_date=config.end_date):
            sha = _partition_sha(asset_root / f"date={trading_date.isoformat()}")
            if sha:
                per_day[trading_date] = sha
        out[symbol] = per_day
    return out


def _extract_last_row_from_day_frame(day_df: pd.DataFrame, trading_date: dt.date) -> tuple[dt.date, str, float] | None:
    if day_df.empty:
        return None

    df = day_df.sort_index()
    numeric_cols = [col for col in df.columns if pd.api.types.is_numeric_dtype(df[col])]
    if not numeric_cols:
        return None

    value_col = "value" if "value" in numeric_cols else numeric_cols[0]
    valid = df.loc[pd.notna(df[value_col])]
    if valid.empty:
        return None

    last = valid.iloc[-1]
    column_name = str(last["_column_name"]) if "_column_name" in valid.columns and pd.notna(last["_column_name"]) else str(value_col)
    return trading_date, column_name, float(last[value_col])


def _local_row_targets(config: RepairConfig, symbols: Sequence[str]) -> dict[str, dict[dt.date, tuple[str, float]]]:
    out: dict[str, dict[dt.date, tuple[str, float]]] = {}
    for symbol in symbols:
        per_day: dict[dt.date, tuple[str, float]] = {}
        asset_root = _ts_asset_root(config.ts_base_dir, symbol)
        for trading_date in _iter_partition_days(asset_root, start_date=config.start_date, end_date=config.end_date):
            day_df = read_timeseries(
                None,
                symbol,
                start=trading_date,
                end=trading_date,
                base_dir=config.ts_base_dir,
            )
            extracted = _extract_last_row_from_day_frame(day_df, trading_date)
            if extracted is None:
                continue
            _day, column_name, value = extracted
            per_day[trading_date] = (column_name, value)
        out[symbol] = per_day
    return out


def _fetch_remote_curve_shas(config: RepairConfig) -> dict[dt.date, str]:
    engine = get_engine()
    if engine is None:
        raise RuntimeError("Supabase engine unavailable")
    with engine.begin() as conn:
        rows = conn.execute(
            text(
                f"""
                SELECT trading_date, sha256
                FROM {CURVE_INTRADAY_BLOCKS_TABLE}
                WHERE curve_name = :curve_name
                  AND trading_date BETWEEN :start_date AND :end_date
                """
            ),
            {
                "curve_name": config.curve_name,
                "start_date": config.start_date,
                "end_date": config.end_date,
            },
        ).fetchall()
    return {row.trading_date: str(row.sha256) for row in rows}


def _fetch_remote_ts_block_shas(config: RepairConfig, symbols: Sequence[str]) -> dict[str, dict[dt.date, str]]:
    if not symbols:
        return {}
    engine = get_engine()
    if engine is None:
        raise RuntimeError("Supabase engine unavailable")
    params = {f"s{idx}": symbol for idx, symbol in enumerate(symbols)}
    params["start_date"] = config.start_date
    params["end_date"] = config.end_date
    in_clause = ", ".join(f":s{idx}" for idx in range(len(symbols)))
    with engine.begin() as conn:
        rows = conn.execute(
            text(
                f"""
                SELECT symbol, trading_date, sha256
                FROM {COMPUTED_TIMESERIES_BLOCKS_TABLE}
                WHERE symbol IN ({in_clause})
                  AND trading_date BETWEEN :start_date AND :end_date
                """
            ),
            params,
        ).fetchall()
    out = {symbol: {} for symbol in symbols}
    for row in rows:
        out[str(row.symbol)][row.trading_date] = str(row.sha256)
    return out


def _fetch_remote_row_targets(config: RepairConfig, symbols: Sequence[str]) -> dict[str, dict[dt.date, tuple[str, float]]]:
    if not symbols:
        return {}
    engine = get_engine()
    if engine is None:
        raise RuntimeError("Supabase engine unavailable")
    params = {f"s{idx}": symbol for idx, symbol in enumerate(symbols)}
    params["start_date"] = config.start_date
    params["end_date"] = config.end_date
    in_clause = ", ".join(f":s{idx}" for idx in range(len(symbols)))
    with engine.begin() as conn:
        rows = conn.execute(
            text(
                f"""
                SELECT symbol, trading_date, column_name, value
                FROM arbs_computed_timeseries_rows_v1
                WHERE symbol IN ({in_clause})
                  AND trading_date BETWEEN :start_date AND :end_date
                """
            ),
            params,
        ).fetchall()
    out = {symbol: {} for symbol in symbols}
    for row in rows:
        out[str(row.symbol)][row.trading_date] = (str(row.column_name), float(row.value))
    return out


@dataclass
class SupabaseMismatchSummary:
    curve_block_days: list[dt.date]
    ts_block_days_by_symbol: dict[str, list[dt.date]]
    row_days_by_symbol: dict[str, list[dt.date]]

    @property
    def is_clean(self) -> bool:
        return (
            not self.curve_block_days
            and not any(self.ts_block_days_by_symbol.values())
            and not any(self.row_days_by_symbol.values())
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "curve_block_days": [day.isoformat() for day in self.curve_block_days],
            "ts_block_days_by_symbol": {
                symbol: [day.isoformat() for day in days]
                for symbol, days in self.ts_block_days_by_symbol.items()
                if days
            },
            "row_days_by_symbol": {
                symbol: [day.isoformat() for day in days]
                for symbol, days in self.row_days_by_symbol.items()
                if days
            },
        }


def _is_close_value(lhs: float, rhs: float) -> bool:
    return math.isclose(float(lhs), float(rhs), rel_tol=0.0, abs_tol=1e-12)


def _compute_supabase_mismatches(
    *,
    local_curve_shas: dict[dt.date, str],
    remote_curve_shas: dict[dt.date, str],
    local_ts_shas: dict[str, dict[dt.date, str]],
    remote_ts_shas: dict[str, dict[dt.date, str]],
    local_row_targets: dict[str, dict[dt.date, tuple[str, float]]],
    remote_row_targets: dict[str, dict[dt.date, tuple[str, float]]],
) -> SupabaseMismatchSummary:
    curve_block_days = sorted(
        day for day, sha in local_curve_shas.items()
        if remote_curve_shas.get(day) != sha
    )

    ts_block_days_by_symbol: dict[str, list[dt.date]] = {}
    for symbol, per_day in local_ts_shas.items():
        remote_per_day = remote_ts_shas.get(symbol, {})
        mismatches = sorted(day for day, sha in per_day.items() if remote_per_day.get(day) != sha)
        if mismatches:
            ts_block_days_by_symbol[symbol] = mismatches

    row_days_by_symbol: dict[str, list[dt.date]] = {}
    for symbol, per_day in local_row_targets.items():
        remote_per_day = remote_row_targets.get(symbol, {})
        mismatches: list[dt.date] = []
        for day, (column_name, value) in per_day.items():
            remote_value = remote_per_day.get(day)
            if remote_value is None:
                mismatches.append(day)
                continue
            remote_column, remote_number = remote_value
            if remote_column != column_name or not _is_close_value(remote_number, value):
                mismatches.append(day)
        if mismatches:
            row_days_by_symbol[symbol] = sorted(mismatches)

    return SupabaseMismatchSummary(
        curve_block_days=curve_block_days,
        ts_block_days_by_symbol=ts_block_days_by_symbol,
        row_days_by_symbol=row_days_by_symbol,
    )


def _push_curve_day(curve_sync: SupabaseCurveSync, curve_name: str, trading_date: dt.date) -> None:
    pushed = curve_sync.push_day(curve_name, trading_date)
    if not pushed:
        raise RuntimeError(f"Curve push returned False for {curve_name}/{trading_date.isoformat()}")


def _push_ts_block_day(ts_sync: SupabaseComputedTimeseriesSync, symbol: str, trading_date: dt.date) -> None:
    pushed = ts_sync.push_day(symbol, trading_date)
    if not pushed:
        raise RuntimeError(f"Computed TS block push returned False for {symbol}/{trading_date.isoformat()}")


def _push_ts_row_batches(
    *,
    ts_sync: SupabaseComputedTimeseriesSync,
    symbol: str,
    days: Sequence[dt.date],
    local_row_targets: dict[str, dict[dt.date, tuple[str, float]]],
    batch_size: int,
) -> None:
    for batch in _chunked(list(days), batch_size):
        row_batch = []
        for trading_date in batch:
            column_name, value = local_row_targets[symbol][trading_date]
            row_batch.append((trading_date, column_name, value))
        pushed = ts_sync.push_rows(symbol, row_batch)
        if not pushed:
            raise RuntimeError(
                f"Computed TS row push returned False for {symbol}/{batch[0].isoformat()}->{batch[-1].isoformat()}"
            )


def _verify_supabase(
    config: RepairConfig,
    symbols: Sequence[str],
    *,
    local_curve_shas: dict[dt.date, str],
    local_ts_shas: dict[str, dict[dt.date, str]],
    local_row_targets: dict[str, dict[dt.date, tuple[str, float]]],
) -> SupabaseMismatchSummary:
    remote_curve_shas = _fetch_remote_curve_shas(config)
    remote_ts_shas = _fetch_remote_ts_block_shas(config, symbols)
    remote_row_targets = _fetch_remote_row_targets(config, symbols)
    return _compute_supabase_mismatches(
        local_curve_shas=local_curve_shas,
        remote_curve_shas=remote_curve_shas,
        local_ts_shas=local_ts_shas,
        remote_ts_shas=remote_ts_shas,
        local_row_targets=local_row_targets,
        remote_row_targets=remote_row_targets,
    )


def _run_supabase_phase(config: RepairConfig, state: dict[str, Any], logger: logging.Logger) -> dict[str, Any]:
    if config.skip_supabase:
        logger.info("Skipping Supabase sync phase.")
        return {"skipped": True}

    symbols = [_symbol_for_tenor(curve_name=config.curve_name, source=config.source, tenor=tenor) for tenor in config.tenors]
    local_curve_shas = _local_curve_shas(config) if config.sync_curve_blocks else {}
    local_ts_shas = _local_ts_block_shas(config, symbols)
    local_row_targets = _local_row_targets(config, symbols)

    curve_sync = SupabaseCurveSync.from_defaults()
    ts_sync = SupabaseComputedTimeseriesSync.from_defaults(base_dir=config.ts_base_dir)

    mismatch = _verify_supabase(
        config,
        symbols,
        local_curve_shas=local_curve_shas,
        local_ts_shas=local_ts_shas,
        local_row_targets=local_row_targets,
    )
    logger.info(
        "Initial Supabase diff: curve_days=%s ts_block_days=%s row_days=%s",
        len(mismatch.curve_block_days),
        sum(len(days) for days in mismatch.ts_block_days_by_symbol.values()),
        sum(len(days) for days in mismatch.row_days_by_symbol.values()),
    )

    for round_idx in range(1, config.verification_rounds + 1):
        if mismatch.is_clean:
            break
        logger.info("Supabase repair round %s/%s starting.", round_idx, config.verification_rounds)

        if config.sync_curve_blocks:
            for trading_date in mismatch.curve_block_days:
                _run_with_retries(
                    logger=logger,
                    description=f"curve block push {trading_date.isoformat()}",
                    max_retries=config.max_retries,
                    retry_sleep_seconds=config.retry_sleep_seconds,
                    fn=lambda trading_date=trading_date: _push_curve_day(curve_sync, config.curve_name, trading_date),
                )

        for symbol, days in mismatch.ts_block_days_by_symbol.items():
            for trading_date in days:
                _run_with_retries(
                    logger=logger,
                    description=f"ts block push {symbol} {trading_date.isoformat()}",
                    max_retries=config.max_retries,
                    retry_sleep_seconds=config.retry_sleep_seconds,
                    fn=lambda symbol=symbol, trading_date=trading_date: _push_ts_block_day(ts_sync, symbol, trading_date),
                )

        for symbol, days in mismatch.row_days_by_symbol.items():
            _run_with_retries(
                logger=logger,
                description=f"ts row push {symbol} ({len(days)} day(s))",
                max_retries=config.max_retries,
                retry_sleep_seconds=config.retry_sleep_seconds,
                fn=lambda symbol=symbol, days=days: _push_ts_row_batches(
                    ts_sync=ts_sync,
                    symbol=symbol,
                    days=days,
                    local_row_targets=local_row_targets,
                    batch_size=config.row_batch_days,
                ),
            )

        mismatch = _verify_supabase(
            config,
            symbols,
            local_curve_shas=local_curve_shas,
            local_ts_shas=local_ts_shas,
            local_row_targets=local_row_targets,
        )
        logger.info(
            "Supabase repair round %s complete: curve_days=%s ts_block_days=%s row_days=%s",
            round_idx,
            len(mismatch.curve_block_days),
            sum(len(days) for days in mismatch.ts_block_days_by_symbol.values()),
            sum(len(days) for days in mismatch.row_days_by_symbol.values()),
        )

    if not mismatch.is_clean:
        raise RuntimeError(f"Supabase verification still failing: {json.dumps(mismatch.as_dict(), indent=2)}")

    state["supabase_complete"] = True
    _save_state(config, state)
    return {
        "curve_local_days": len(local_curve_shas),
        "ts_block_local_days": sum(len(per_day) for per_day in local_ts_shas.values()),
        "row_local_days": sum(len(per_day) for per_day in local_row_targets.values()),
        "symbols": list(symbols),
        "verification": mismatch.as_dict(),
    }


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Repair local and Supabase STIR Q12STIRT intraday timeseries state.",
    )
    parser.add_argument("--curve", default=DEFAULT_CURVE_NAME)
    parser.add_argument("--source", default=DEFAULT_SOURCE)
    parser.add_argument("--start-date", type=_parse_date, default=DEFAULT_START_DATE)
    parser.add_argument("--end-date", type=_parse_date, default=DEFAULT_END_DATE)
    parser.add_argument("--n-jobs", type=int, default=DEFAULT_N_JOBS)
    parser.add_argument("--local-business-days-per-chunk", type=int, default=DEFAULT_LOCAL_CHUNK_BUSINESS_DAYS)
    parser.add_argument("--row-batch-days", type=int, default=DEFAULT_ROW_BATCH_DAYS)
    parser.add_argument("--max-retries", type=int, default=DEFAULT_MAX_RETRIES)
    parser.add_argument("--retry-sleep-seconds", type=float, default=DEFAULT_RETRY_SLEEP_SECONDS)
    parser.add_argument("--verification-rounds", type=int, default=DEFAULT_VERIFICATION_ROUNDS)
    parser.add_argument("--state-path", type=Path, default=DEFAULT_STATE_PATH)
    parser.add_argument("--report-path", type=Path, default=DEFAULT_REPORT_PATH)
    parser.add_argument("--log-path", type=Path, default=DEFAULT_LOG_PATH)
    parser.add_argument("--ts-base-dir", type=Path, default=REPO_ROOT / "data" / "ts")
    parser.add_argument("--skip-local", action="store_true")
    parser.add_argument("--skip-supabase", action="store_true")
    parser.add_argument("--no-sync-curve-blocks", dest="sync_curve_blocks", action="store_false")
    parser.add_argument("--reset-state", action="store_true")
    parser.set_defaults(sync_curve_blocks=True)
    return parser


def parse_args(argv: Sequence[str] | None = None) -> RepairConfig:
    args = _build_parser().parse_args(argv)
    return RepairConfig(
        curve_name=str(args.curve),
        source=str(args.source),
        start_date=args.start_date,
        end_date=args.end_date,
        tenors=tuple(IMM_TENORS),
        n_jobs=int(args.n_jobs),
        local_chunk_business_days=int(args.local_business_days_per_chunk),
        row_batch_days=int(args.row_batch_days),
        max_retries=int(args.max_retries),
        retry_sleep_seconds=float(args.retry_sleep_seconds),
        verification_rounds=int(args.verification_rounds),
        state_path=Path(args.state_path),
        report_path=Path(args.report_path),
        log_path=Path(args.log_path),
        ts_base_dir=Path(args.ts_base_dir),
        sync_curve_blocks=bool(args.sync_curve_blocks),
        skip_local=bool(args.skip_local),
        skip_supabase=bool(args.skip_supabase),
        reset_state=bool(args.reset_state),
    )


def main(argv: Sequence[str] | None = None) -> int:
    config = parse_args(argv)
    logger = _configure_logging(config.log_path)
    _warn_if_not_stir_env(logger)
    state = _load_state(config, reset=bool(config.reset_state))
    if state.get("config") != _default_state(config).get("config"):
        logger.info("State config differs from current config; continuing with current settings.")

    started_at = time.perf_counter()
    try:
        _run_local_phase(config, state, logger)
        supabase_summary = _run_supabase_phase(config, state, logger)
    except Exception:
        logger.exception("Repair run failed.")
        return 1

    report = {
        "curve_name": config.curve_name,
        "source": config.source,
        "start_date": config.start_date.isoformat(),
        "end_date": config.end_date.isoformat(),
        "tenors": list(config.tenors),
        "elapsed_seconds": round(time.perf_counter() - started_at, 2),
        "state_path": str(config.state_path),
        "log_path": str(config.log_path),
        "supabase_summary": supabase_summary,
    }
    config.report_path.parent.mkdir(parents=True, exist_ok=True)
    config.report_path.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    logger.info("Repair run complete. Report written to %s", config.report_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
