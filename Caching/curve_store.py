# Caching/curve_store.py
"""High-performance Parquet-backed curve snapshot store.

Two persisted products:
  A) Raw Snapshot Store — node_dates + discount_factors per timestamp,
     sufficient for exact rl.Curve reconstruction.
  B) Analytics Panel — pre-computed rates at canonical stable tenors
     for fast research queries (wide-format, no reconstruction needed).

Read path uses DuckDB for Hive-partitioned Parquet scans with predicate
pushdown.  Write path uses atomic rename + content-addressing (SHA256)
for safe concurrent / incremental writes.
"""
from __future__ import annotations

import datetime
import hashlib
import json
import os
import queue
import re
import tempfile
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple, Union

import logging as _logging

import duckdb
import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

# --------------- Thread-safe DuckDB connection for read-only queries ----------
_duckdb_local = threading.local()


def _thread_local_conn() -> duckdb.DuckDBPyConnection:
    """Return a per-thread DuckDB connection (read-only, no shared state)."""
    conn = getattr(_duckdb_local, "conn", None)
    if conn is None:
        conn = duckdb.connect()
        _duckdb_local.conn = conn
    return conn
import pytz

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

logger = _logging.getLogger(__name__)

DEFAULT_COMPRESSION = "zstd"
_CHI = pytz.timezone("America/Chicago")
_NYC = pytz.timezone("America/New_York")
_UTC = pytz.UTC

# reference_keys already reported as unknown, so the warning fires once per key
# rather than once per reconstructed curve.
_WARNED_REFERENCE_KEYS: set[str] = set()

# Session reference: CME STIR futures regular hours 06:00-17:00 CT
_SESSION_OPEN_HOUR = 6
_SESSION_OPEN_MINUTE = 0


def _normalize_timestamp_utc_values(
    timestamps_utc: Optional[Sequence[Union[datetime.datetime, pd.Timestamp]]],
) -> list[datetime.datetime]:
    if not timestamps_utc:
        return []

    normalized: list[datetime.datetime] = []
    seen: set[datetime.datetime] = set()
    for value in timestamps_utc:
        if isinstance(value, pd.Timestamp):
            value = value.to_pydatetime()
        if not isinstance(value, datetime.datetime):
            continue
        if value.tzinfo is None:
            value = _UTC.localize(value)
        else:
            value = value.astimezone(_UTC)
        value = value.replace(microsecond=0)
        if value not in seen:
            seen.add(value)
            normalized.append(value)
    return sorted(normalized)


def _trading_dates_for_timestamps_utc(timestamps_utc: Sequence[datetime.datetime]) -> list[datetime.date]:
    """Candidate partition dates for a set of instants.

    Assets do not agree on what `trading_date` means: the CME-derived feeds use
    a 17:00-CT roll (_compute_trading_date), while the ERIS live daemon and
    citivelo partition on the plain ET calendar date. Keying only on the CME rule
    silently returned ZERO rows for data that was physically on disk -- every
    evening snapshot of an ET-partitioned asset sits in the PREVIOUS day's
    partition under that rule.
    Return both candidates. Partitions are cheap to skip and the caller filters
    to the exact timestamps afterwards (_filter_df_to_timestamps_utc), so a
    superset costs a little IO and is correct under either convention.
    """
    dates: set[datetime.date] = set()
    for ts in timestamps_utc:
        dates.add(_compute_trading_date(ts.astimezone(_CHI)))  # CME 17:00-CT roll
        dates.add(ts.astimezone(_NYC).date())                  # ET calendar date
    return sorted(dates)


def _filter_df_to_timestamps_utc(df: pd.DataFrame, timestamps_utc: Sequence[datetime.datetime]) -> pd.DataFrame:
    if df.empty or "timestamp_utc" not in df.columns or not timestamps_utc:
        return df
    requested = set(timestamps_utc)
    ts_keys = df["timestamp_utc"].map(_normalize_timestamp_utc_scalar)
    return df.loc[ts_keys.isin(requested)].reset_index(drop=True)


def _normalize_timestamp_utc_scalar(value: Any) -> Optional[datetime.datetime]:
    if value is None:
        return None
    if isinstance(value, pd.Timestamp):
        value = value.to_pydatetime()
    if not isinstance(value, datetime.datetime):
        return None
    if value.tzinfo is None:
        value = _UTC.localize(value)
    else:
        value = value.astimezone(_UTC)
    return value.replace(microsecond=0)


def _timestamps_cte_sql(
    timestamps_utc: Sequence[datetime.datetime],
) -> str:
    values = ", ".join(
        f"(TIMESTAMPTZ '{ts.isoformat(sep=' ')}')"
        for ts in timestamps_utc
    )
    return f"WITH requested(ts) AS (VALUES {values})"


def _quote_identifier(identifier: str) -> str:
    return f"\"{str(identifier).replace('\"', '\"\"')}\""


# ---------------------------------------------------------------------------
# CurveSnapshot dataclass
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class CurveSnapshot:
    """Lightweight container for one curve snapshot's raw state."""

    timestamp_utc: datetime.datetime  # tz-aware UTC
    timestamp_local: datetime.datetime  # tz-aware US/Chicago
    trading_date: datetime.date
    session_minute: int  # minutes since 07:00 CT
    curve_name: str
    cfg_hash: str
    reference_key: str
    interpolation: str
    source_variant: str = field(default="", kw_only=True)
    node_dates: list[datetime.date]  # sorted
    discount_factors: list[float]  # parallel to node_dates
    # Log-cubic spline knot sequence (rl.Curve's `t`) and endpoint conditions.
    # Without these a spline-calibrated curve reconstructs as plain log-linear:
    # the stored node DFs are the SPLINE's solution and are not a valid
    # log-linear curve for the same market, so the reconstruction reprices its
    # own calibration instruments wrong. None for non-spline curves.
    spline_knots: Optional[list[datetime.date]] = field(default=None, kw_only=True)
    spline_endpoints: Optional[str] = field(default=None, kw_only=True)  # "left,right"

    @staticmethod
    def _extract_spline(curve: Any) -> tuple[Optional[list], Optional[str]]:
        """Recover (knots, endpoints) from a live rl.Curve, or (None, None)."""
        spline = getattr(getattr(curve, "_interpolator", None), "spline", None)
        if spline is None:
            return None, None
        knots = getattr(spline, "t", None)
        if not knots:
            return None, None
        endpoints = getattr(spline, "endpoints", None)
        if isinstance(endpoints, (tuple, list)):
            endpoints = ",".join(str(e) for e in endpoints)
        elif endpoints is not None:
            endpoints = str(endpoints)
        return [_to_date(k) for k in knots], endpoints

    # ── Factories ──

    @classmethod
    def from_diskcache_payload(
        cls,
        *,
        cache_key: str,
        payload: dict,
    ) -> "CurveSnapshot":
        """Build a snapshot by parsing the diskcache payload's curve_json
        WITHOUT calling rl.from_json() (avoids the 1.6ms bottleneck)."""
        curve_json_str: str = (
            payload.get("curve_json", "") if isinstance(payload, dict) else payload
        )
        curve_name_stored = payload.get("curve_name", "") if isinstance(payload, dict) else ""
        ts_utc_str = payload.get("timestamp_utc", "") if isinstance(payload, dict) else ""

        # Parse the key to extract curve_name, timestamp, cfg_hash
        key_curve_name, key_ts_utc, key_cfg_hash = _parse_cache_key(cache_key)
        curve_name = curve_name_stored or key_curve_name

        # Parse timestamp
        if ts_utc_str:
            ts_utc = datetime.datetime.fromisoformat(ts_utc_str)
            if ts_utc.tzinfo is None:
                ts_utc = _UTC.localize(ts_utc)
        else:
            ts_utc = _parse_key_timestamp(key_ts_utc)

        ts_local = ts_utc.astimezone(_CHI)

        # Extract nodes directly from JSON without rl.from_json()
        node_dates, discount_factors, interpolation, reference_key = (
            _extract_nodes_from_curve_json(curve_json_str)
        )

        trading_date = _compute_trading_date(ts_local)
        session_minute = _compute_session_minute(ts_local)

        return cls(
            timestamp_utc=ts_utc,
            timestamp_local=ts_local,
            trading_date=trading_date,
            session_minute=session_minute,
            curve_name=curve_name,
            cfg_hash=key_cfg_hash,
            reference_key=reference_key,
            interpolation=interpolation,
            source_variant="BARCHART_STIRF",
            node_dates=node_dates,
            discount_factors=discount_factors,
        )

    @classmethod
    def from_rl_curve(
        cls,
        curve: Any,  # rl.Curve
        *,
        curve_name: str,
        cfg: dict,
        cfg_hash: str = "",
    ) -> "CurveSnapshot":
        """Build a snapshot from a live rl.Curve object."""
        ts = getattr(curve, "timestamp", None) or getattr(curve, "timestamp_utc", None)
        if ts is None:
            raise ValueError("Curve has no timestamp attribute")
        if ts.tzinfo is None:
            ts = _UTC.localize(ts)
        ts_utc = ts.astimezone(_UTC)
        ts_local = ts_utc.astimezone(_CHI)

        # Extract nodes from the rl.Curve (_CurveNodes wraps a dict in ._nodes)
        raw_nodes: dict = curve.nodes._nodes if hasattr(curve.nodes, "_nodes") else dict(curve.nodes)
        node_dates_sorted = sorted(raw_nodes.keys())
        node_dates = [_to_date(d) for d in node_dates_sorted]
        discount_factors = [float(raw_nodes[d]) for d in node_dates_sorted]

        if not cfg_hash:
            from MDP.IRSwaps.BARCHART_STIRF.rl import BARCHART_STIRF_CURVE

            cfg_hash = BARCHART_STIRF_CURVE._curve_cfg_hash(cfg)

        reference_key = cfg.get("reference_key", "")
        interpolation = cfg.get("interpolation", "log_linear")
        spline_knots, spline_endpoints = cls._extract_spline(curve)

        return cls(
            timestamp_utc=ts_utc,
            timestamp_local=ts_local,
            trading_date=_compute_trading_date(ts_local),
            session_minute=_compute_session_minute(ts_local),
            curve_name=curve_name,
            cfg_hash=cfg_hash,
            reference_key=reference_key,
            interpolation=interpolation,
            source_variant="BARCHART_STIRF",
            node_dates=node_dates,
            discount_factors=discount_factors,
            spline_knots=spline_knots,
            spline_endpoints=spline_endpoints,
        )

    @classmethod
    def from_eris_df(
        cls,
        df: "pd.DataFrame",
        *,
        trading_date: datetime.date,
        curve_name: str = "USD-SOFR-1D",
        source_variant: str = "ERIS_RL_BASIC",
        interpolation: str = "log_linear",
        timestamp_utc: Optional[datetime.datetime] = None,
    ) -> "CurveSnapshot":
        """Build a snapshot from an Eris discount factor DataFrame."""
        import pandas as pd_local

        df = df.copy()
        df["Date"] = pd_local.to_datetime(df["Date"], errors="coerce")
        df["DiscountFactor"] = pd_local.to_numeric(
            df["DiscountFactor"], errors="coerce"
        )
        df = df.dropna(subset=["Date", "DiscountFactor"]).sort_values("Date")

        node_dates = [d.date() for d in df["Date"]]
        discount_factors = df["DiscountFactor"].tolist()

        if timestamp_utc is None:
            et = pytz.timezone("America/New_York")
            ts_local_et = et.localize(
                datetime.datetime(
                    trading_date.year,
                    trading_date.month,
                    trading_date.day,
                    15,
                    0,
                )
            )
            timestamp_utc = ts_local_et.astimezone(_UTC)
        elif timestamp_utc.tzinfo is None:
            timestamp_utc = _UTC.localize(timestamp_utc)
        else:
            timestamp_utc = timestamp_utc.astimezone(_UTC)

        ts_local = timestamp_utc.astimezone(_CHI)

        return cls(
            timestamp_utc=timestamp_utc,
            timestamp_local=ts_local,
            trading_date=trading_date,
            session_minute=_compute_session_minute(ts_local),
            curve_name=curve_name,
            cfg_hash="",
            reference_key=curve_name,
            interpolation=interpolation,
            source_variant=source_variant,
            node_dates=node_dates,
            discount_factors=discount_factors,
        )


# ---------------------------------------------------------------------------
# L2 Supabase sync (lazy-loaded)
# ---------------------------------------------------------------------------


def _get_curve_sync(base_dir: Optional[Union[str, Path]] = None):
    """Lazy-load SupabaseCurveSync for the active CurveStore base directory."""
    from Caching.supabase_engine import SUPABASE_ENABLED

    if not SUPABASE_ENABLED:
        return None

    from Caching.supabase_curve_sync import SupabaseCurveSync

    if base_dir is None:
        return SupabaseCurveSync.from_defaults()
    from Caching.supabase_engine import get_engine

    return SupabaseCurveSync(base_dir=Path(base_dir), engine=get_engine())


# ---------------------------------------------------------------------------
# CurveStore
# ---------------------------------------------------------------------------


class CurveStore:
    """Parquet-backed store for bulk curve retrieval.

    Layout (Hive-partitioned)::

        {base_dir}/raw/asset={curve_name}/date={YYYY-MM-DD}/{sha256}.parquet
        {base_dir}/analytics/asset={curve_name}/date={YYYY-MM-DD}/{sha256}.parquet
    """

    # Singleton instance for reuse across modules (see CurveStore.default()).
    _default_instance: Optional["CurveStore"] = None
    _default_lock = threading.Lock()

    @classmethod
    def default(cls) -> "CurveStore":
        """Return a module-wide singleton CurveStore instance."""
        if cls._default_instance is None:
            with cls._default_lock:
                if cls._default_instance is None:
                    cls._default_instance = cls()
        return cls._default_instance

    def __init__(
        self,
        base_dir: Optional[Union[str, Path]] = None,
        compression: str = DEFAULT_COMPRESSION,
        bg_push_workers: Optional[int] = None,
    ) -> None:
        if base_dir is None:
            base_dir = self._default_base_dir()
        self._base_dir = Path(base_dir)
        self._compression = compression
        self._raw_dir = self._base_dir / "raw"
        self._analytics_dir = self._base_dir / "analytics"
        self._bg_push_threads: list[threading.Thread] = []
        self._bg_push_lock = threading.Lock()
        self._bg_push_condition = threading.Condition(self._bg_push_lock)
        self._bg_push_queue: queue.Queue[tuple[Any, str, str, datetime.date]] = queue.Queue()
        self._bg_push_pending = 0
        self._bg_push_worker_count = self._resolve_bg_push_workers(bg_push_workers)

    @staticmethod
    def _resolve_bg_push_workers(bg_push_workers: Optional[int]) -> int:
        if bg_push_workers is None:
            raw_value = os.getenv("ARBS_CURVE_STORE_BG_PUSH_WORKERS")
            if raw_value is None or raw_value == "":
                return 2
            try:
                bg_push_workers = int(raw_value)
            except ValueError:
                logger.warning(
                    "Invalid ARBS_CURVE_STORE_BG_PUSH_WORKERS=%r; defaulting to 2",
                    raw_value,
                )
                return 2
        return max(1, int(bg_push_workers))

    def _ensure_bg_push_workers(self) -> None:
        threads_to_start: list[threading.Thread] = []
        with self._bg_push_lock:
            self._bg_push_threads = [t for t in self._bg_push_threads if t.is_alive()]
            while len(self._bg_push_threads) < self._bg_push_worker_count:
                worker_idx = len(self._bg_push_threads) + 1
                thread = threading.Thread(
                    target=self._bg_push_worker,
                    name=f"curve-store-bg-push-{worker_idx}",
                    daemon=True,
                )
                self._bg_push_threads.append(thread)
                threads_to_start.append(thread)
        for thread in threads_to_start:
            thread.start()

    def _bg_push_worker(self) -> None:
        while True:
            sync, kind, curve_name, trading_date = self._bg_push_queue.get()
            try:
                if kind == "raw":
                    sync.push_day(curve_name, trading_date)
                else:
                    sync.push_analytics_day(curve_name, trading_date)
            except Exception:
                if kind == "raw":
                    logger.warning(
                        "L2 push failed for %s/%s",
                        curve_name,
                        trading_date,
                        exc_info=True,
                    )
                else:
                    logger.warning(
                        "L2 analytics push failed for %s/%s",
                        curve_name,
                        trading_date,
                        exc_info=True,
                    )
            finally:
                with self._bg_push_condition:
                    self._bg_push_pending = max(0, self._bg_push_pending - 1)
                    if self._bg_push_pending == 0:
                        self._bg_push_condition.notify_all()
                self._bg_push_queue.task_done()

    def _enqueue_bg_push(
        self,
        sync: Any,
        *,
        kind: str,
        curve_name: str,
        trading_date: datetime.date,
    ) -> None:
        self._ensure_bg_push_workers()
        with self._bg_push_condition:
            self._bg_push_pending += 1
        self._bg_push_queue.put((sync, kind, curve_name, trading_date))

    def wait_for_background_pushes(self, timeout: Optional[float] = None) -> int:
        """Wait for outstanding background Supabase pushes to finish.

        Returns the number of queued or in-flight pushes that were awaited.
        """
        deadline = None if timeout is None else (time.monotonic() + float(timeout))
        with self._bg_push_condition:
            waited = self._bg_push_pending
            while self._bg_push_pending > 0:
                remaining = None if deadline is None else max(0.0, deadline - time.monotonic())
                if remaining is not None and remaining <= 0.0:
                    return waited
                self._bg_push_condition.wait(timeout=remaining)
                if deadline is not None and time.monotonic() >= deadline and self._bg_push_pending > 0:
                    return waited
            return waited

    @staticmethod
    def _default_base_dir() -> Path:
        arbs_cache = os.getenv("ARBS_CACHE_DIR")
        if arbs_cache:
            return Path(arbs_cache) / "curve_store"
        try:
            from platformdirs import user_cache_dir

            return Path(user_cache_dir(appname="ARBS", appauthor=False)) / "curve_store"
        except Exception:
            if os.name == "nt":
                return (
                    Path(os.getenv("LOCALAPPDATA", str(Path.home())))
                    / "ARBS"
                    / "Cache"
                    / "curve_store"
                )
            return Path.home() / ".cache" / "arbs" / "curve_store"

    # ── Write Path ──

    def write_day(
        self,
        curve_name: str,
        trading_date: datetime.date,
        snapshots: Sequence[CurveSnapshot],
        *,
        overwrite: bool = False,
        push_l2: bool = True,
    ) -> Optional[dict]:
        """Atomic write of all snapshots for one (curve_name, trading_date).

        Content-addressed: skips write if SHA256 matches existing file.
        Returns file metadata dict, or None if skipped. Set ``push_l2=False`` for
        a purely-local write (e.g. materializing a read-only L1 cache from rows
        that already live in Supabase, without re-pushing a whole-day blob).
        """
        if not snapshots:
            return None

        table = _snapshots_to_arrow_table(snapshots)
        pbytes = _write_parquet_bytes(table, self._compression)

        part_dir = (
            self._raw_dir
            / f"asset={_sanitize(curve_name)}"
            / f"date={trading_date.isoformat()}"
        )
        meta = _atomic_content_write(part_dir, pbytes, overwrite=overwrite)

        # L2: background push to Supabase
        sync = _get_curve_sync(self._base_dir) if push_l2 else None
        if sync is not None:
            self._enqueue_bg_push(
                sync,
                kind="raw",
                curve_name=curve_name,
                trading_date=trading_date,
            )

        return meta

    def write_analytics_day(
        self,
        curve_name: str,
        trading_date: datetime.date,
        df: pd.DataFrame,
        *,
        overwrite: bool = False,
    ) -> Optional[dict]:
        """Write pre-computed analytics panel for one (curve_name, trading_date)."""
        if df is None or df.empty:
            return None
        table = pa.Table.from_pandas(df, preserve_index=False)
        pbytes = _write_parquet_bytes(table, self._compression)
        part_dir = (
            self._analytics_dir
            / f"asset={_sanitize(curve_name)}"
            / f"date={trading_date.isoformat()}"
        )
        meta = _atomic_content_write(part_dir, pbytes, overwrite=overwrite)

        sync = _get_curve_sync(self._base_dir)
        if sync is not None:
            self._enqueue_bg_push(
                sync,
                kind="analytics",
                curve_name=curve_name,
                trading_date=trading_date,
            )

        return meta

    # ── Read Path (Bulk) ──

    def read_raw_day(
        self,
        curve_name: str,
        trading_date: datetime.date,
    ) -> pd.DataFrame:
        """Fast single-day read via direct PyArrow (no DuckDB overhead).

        ~5ms vs ~200ms for DuckDB Hive scan on a single partition.
        """
        part_dir = (
            self._raw_dir
            / f"asset={_sanitize(curve_name)}"
            / f"date={trading_date.isoformat()}"
        )
        if not part_dir.exists() or not any(part_dir.glob("*.parquet")):
            # L2 fallback: try pulling from Supabase before returning empty
            sync = _get_curve_sync(self._base_dir)
            if sync is not None and sync.pull_day(curve_name, trading_date):
                return self.read_raw_day(curve_name, trading_date)
            return pd.DataFrame()

        pq_files = list(part_dir.glob("*.parquet"))
        if not pq_files:
            return pd.DataFrame()

        tables = [pq.read_table(f) for f in pq_files]
        tables = [_ensure_raw_table_columns(t) for t in tables]
        if len(tables) == 1:
            table = tables[0]
        else:
            table = pa.concat_tables(tables, promote_options="default")

        df = _ensure_raw_df_columns(table.to_pandas())
        return df.sort_values("timestamp_utc").reset_index(drop=True)

    def read_raw_nodes(
        self,
        curve_name: str,
        *,
        start: Optional[Union[datetime.date, datetime.datetime]] = None,
        end: Optional[Union[datetime.date, datetime.datetime]] = None,
        session_minute_min: Optional[int] = None,
        session_minute_max: Optional[int] = None,
        timestamps_utc: Optional[Sequence[Union[datetime.datetime, pd.Timestamp]]] = None,
    ) -> pd.DataFrame:
        """Bulk read raw node data via DuckDB Hive-partitioned scan.

        Returns a DataFrame with columns matching the raw schema.
        node_dates and discount_factors are Python list columns.

        For single-day reads, prefer read_raw_day() which bypasses DuckDB
        overhead (~5ms vs ~200ms).
        """
        requested_timestamps_utc = _normalize_timestamp_utc_values(timestamps_utc)
        start_date = start.date() if isinstance(start, datetime.datetime) else start
        end_date = end.date() if isinstance(end, datetime.datetime) else end
        if requested_timestamps_utc:
            requested_dates = _trading_dates_for_timestamps_utc(requested_timestamps_utc)
            if requested_dates:
                if start_date is None:
                    start_date = requested_dates[0]
                if end_date is None:
                    end_date = requested_dates[-1]

        asset_dir = self._raw_dir / f"asset={_sanitize(curve_name)}"
        if not asset_dir.exists():
            sync = _get_curve_sync(self._base_dir)
            if sync is not None and start_date is not None and end_date is not None:
                try:
                    sync.prefetch_range(curve_name, start_date, end_date)
                except Exception:
                    logger.debug(
                        "Raw CurveStore prefetch failed for %s %s->%s",
                        curve_name,
                        start_date,
                        end_date,
                        exc_info=True,
                    )
            if not asset_dir.exists():
                return pd.DataFrame()

        if requested_timestamps_utc:
            trading_dates = _trading_dates_for_timestamps_utc(requested_timestamps_utc)
            if len(trading_dates) == 1 and session_minute_min is None and session_minute_max is None:
                day_df = self.read_raw_day(curve_name, trading_dates[0])
                return _ensure_raw_df_columns(_filter_df_to_timestamps_utc(day_df, requested_timestamps_utc))

        # Fast path: if start == end (single day), use direct PyArrow
        if (
            start is not None
            and end is not None
            and session_minute_min is None
            and session_minute_max is None
        ):
            s = start.date() if isinstance(start, datetime.datetime) else start
            e = end.date() if isinstance(end, datetime.datetime) else end
            if s == e:
                return self.read_raw_day(curve_name, s)

        glob_pattern = str(asset_dir / "date=*" / "*.parquet").replace("\\", "/")

        where_parts: list[str] = []
        cte_prefix = ""
        join_clause = ""
        if requested_timestamps_utc:
            trading_dates = _trading_dates_for_timestamps_utc(requested_timestamps_utc)
            where_parts.append(f"date >= '{trading_dates[0].isoformat()}'")
            where_parts.append(f"date <= '{trading_dates[-1].isoformat()}'")
            cte_prefix = _timestamps_cte_sql(requested_timestamps_utc)
            join_clause = "INNER JOIN requested ON raw.timestamp_utc = requested.ts"
        if start is not None:
            s = start.date() if isinstance(start, datetime.datetime) else start
            where_parts.append(f"date >= '{s.isoformat()}'")
        if end is not None:
            e = end.date() if isinstance(end, datetime.datetime) else end
            where_parts.append(f"date <= '{e.isoformat()}'")
        if session_minute_min is not None:
            where_parts.append(f"session_minute >= {int(session_minute_min)}")
        if session_minute_max is not None:
            where_parts.append(f"session_minute <= {int(session_minute_max)}")

        where_clause = f"WHERE {' AND '.join(where_parts)}" if where_parts else ""

        query = f"""
            {cte_prefix}
            SELECT raw.*
            FROM read_parquet('{glob_pattern}', hive_partitioning=true, union_by_name=true) raw
            {join_clause}
            {where_clause}
            ORDER BY timestamp_utc
        """
        try:
            df = _thread_local_conn().sql(query).df()
        except (duckdb.IOException, duckdb.CatalogException):
            sync = _get_curve_sync(self._base_dir)
            if sync is not None and start_date is not None and end_date is not None:
                try:
                    sync.prefetch_range(curve_name, start_date, end_date)
                    df = _thread_local_conn().sql(query).df()
                except (duckdb.IOException, duckdb.CatalogException):
                    return pd.DataFrame()
            else:
                return pd.DataFrame()

        if "date" in df.columns:
            df.drop(columns=["date"], inplace=True)

        return _ensure_raw_df_columns(df)

    def read_analytics(
        self,
        curve_name: str,
        *,
        start: Optional[Union[datetime.date, datetime.datetime]] = None,
        end: Optional[Union[datetime.date, datetime.datetime]] = None,
        tenors: Optional[list[str]] = None,
        metrics: Optional[list[str]] = None,
        timestamps_utc: Optional[Sequence[Union[datetime.datetime, pd.Timestamp]]] = None,
        columns: Optional[Sequence[str]] = None,
    ) -> pd.DataFrame:
        """Read analytics panel (wide-format)."""
        asset_dir = self._analytics_dir / f"asset={_sanitize(curve_name)}"
        glob_pattern = str(asset_dir / "date=*" / "*.parquet").replace("\\", "/")
        requested_timestamps_utc = _normalize_timestamp_utc_values(timestamps_utc)
        start_date = start.date() if isinstance(start, datetime.datetime) else start
        end_date = end.date() if isinstance(end, datetime.datetime) else end
        if requested_timestamps_utc:
            trading_dates = _trading_dates_for_timestamps_utc(requested_timestamps_utc)
            if trading_dates:
                if start_date is None:
                    start_date = trading_dates[0]
                if end_date is None:
                    end_date = trading_dates[-1]

        if not asset_dir.exists():
            sync = _get_curve_sync(self._base_dir)
            if sync is not None and start_date is not None and end_date is not None:
                sync.prefetch_analytics_range(curve_name, start_date, end_date)
            if not asset_dir.exists():
                return pd.DataFrame()

        # Build column selection
        cols: list[str] = ["timestamp_utc", "trading_date", "session_minute"]
        if tenors and metrics:
            for m in metrics:
                for t in tenors:
                    cols.append(f"{m}_{t}")
        if columns:
            for column in columns:
                column_name = str(column)
                if column_name not in cols:
                    cols.append(column_name)

        projected_cols: Optional[list[str]] = None
        if columns or (tenors and metrics):
            schema_query = f"SELECT * FROM read_parquet('{glob_pattern}', hive_partitioning=true, union_by_name=true) LIMIT 0"
            try:
                available_cols = set(_thread_local_conn().sql(schema_query).df().columns)
            except (duckdb.IOException, duckdb.CatalogException):
                available_cols = set()
            if available_cols:
                projected_cols = [col for col in cols if col in available_cols]

        col_expr = "*"
        if projected_cols:
            col_expr = ", ".join(f"analytics.{_quote_identifier(col)}" for col in projected_cols)

        where_parts: list[str] = []
        cte_prefix = ""
        join_clause = ""
        if requested_timestamps_utc:
            trading_dates = _trading_dates_for_timestamps_utc(requested_timestamps_utc)
            where_parts.append(f"date >= '{trading_dates[0].isoformat()}'")
            where_parts.append(f"date <= '{trading_dates[-1].isoformat()}'")
            cte_prefix = _timestamps_cte_sql(requested_timestamps_utc)
            join_clause = "INNER JOIN requested ON analytics.timestamp_utc = requested.ts"
        if start_date is not None:
            where_parts.append(f"date >= '{start_date.isoformat()}'")
        if end_date is not None:
            where_parts.append(f"date <= '{end_date.isoformat()}'")

        where_clause = f"WHERE {' AND '.join(where_parts)}" if where_parts else ""

        query = f"""
            {cte_prefix}
            SELECT {col_expr}
            FROM read_parquet('{glob_pattern}', hive_partitioning=true, union_by_name=true) analytics
            {join_clause}
            {where_clause}
            ORDER BY timestamp_utc
        """
        try:
            df = _thread_local_conn().sql(query).df()
        except (duckdb.IOException, duckdb.CatalogException):
            sync = _get_curve_sync(self._base_dir)
            if sync is not None and start_date is not None and end_date is not None:
                try:
                    sync.prefetch_analytics_range(curve_name, start_date, end_date)
                    df = _thread_local_conn().sql(query).df()
                except (duckdb.IOException, duckdb.CatalogException):
                    return pd.DataFrame()
            else:
                return pd.DataFrame()

        if "date" in df.columns:
            df.drop(columns=["date"], inplace=True)

        df = _ensure_analytics_df_columns(df)
        if tenors and metrics:
            available_cols = [col for col in cols if col in df.columns]
            return df.loc[:, available_cols]
        return df

    # ── Lazy Reconstruction ──

    @staticmethod
    def reconstruct_curve(
        row: dict,
        *,
        cfg: Optional[dict] = None,
    ) -> Any:
        """Reconstruct a single rl.Curve from a raw store row.

        ~1.6ms per curve — only call when pricing is needed.
        """
        import rateslib as rl

        from Query.IRSwaps.backends.rateslib.rl_curve_definitions_map import (
            RATESLIB_CURVE_DEFINITIONS,
        )

        node_dates_raw = row["node_dates"]
        dfs_raw = row["discount_factors"]
        reference_key = row.get("reference_key", "")
        interpolation = row.get("interpolation", "log_linear")

        # Build node dict: {rl datetime → discount factor}
        nodes = {}
        for d, v in zip(node_dates_raw, dfs_raw):
            d = _to_date(d)
            nodes[rl.dt(d.year, d.month, d.day)] = float(v)

        # Curve construction kwargs.
        # An unknown reference_key silently produced an act360/nyc/mf curve,
        # which is right for USD but quietly wrong for anything else (act365f/tro
        # conventions differ by 3-4 bp). Warn once per key so a bad writer is
        # visible instead of being absorbed.
        curve_def = RATESLIB_CURVE_DEFINITIONS.get(reference_key, {})
        if not curve_def and reference_key not in _WARNED_REFERENCE_KEYS:
            _WARNED_REFERENCE_KEYS.add(reference_key)
            logger.warning(
                "Stored reference_key %r is not in RATESLIB_CURVE_DEFINITIONS; "
                "falling back to act360/nyc/mf. Conventions for this curve may be wrong.",
                reference_key,
            )
        kwargs: Dict[str, Any] = {
            "nodes": nodes,
            "id": reference_key,
            "convention": curve_def.get("DayCounter", "act360"),
            "calendar": curve_def.get("Calendar", "nyc"),
            "modifier": curve_def.get("BusinessConvention", "mf"),
            "interpolation": interpolation,
        }

        # Log-cubic spline: restore the knot sequence the curve was calibrated
        # under. The stored node DFs are the SPLINE's solution, so rebuilding
        # them as plain log-linear does not reprice the curve's own calibration
        # instruments (measured -0.18 bp at 30Y, +4.9 bp at 40Y on GSQUANT
        # USD-OIS, and up to +7.4 bp on ERIS EOD).
        spline_knots = row.get("spline_knots")
        try:
            has_spline = spline_knots is not None and len(spline_knots) > 0
        except TypeError:  # NaN / scalar null from a column-padded frame
            has_spline = False
        if has_spline:
            kwargs["t"] = [
                rl.dt(d.year, d.month, d.day)
                for d in (_to_date(k) for k in spline_knots)
            ]
            endpoints = row.get("spline_endpoints")
            if endpoints:
                parts = [p.strip() for p in str(endpoints).split(",") if p.strip()]
                if len(parts) == 2:
                    kwargs["endpoints"] = tuple(parts)
                elif len(parts) == 1:
                    kwargs["endpoints"] = parts[0]

        # Handle mixed interpolation if cfg provided
        if cfg and cfg.get("mixed_interpolation"):
            from MDP.IRSwaps.BARCHART_STIRF.rl import BARCHART_STIRF_CURVE

            base_date = min(d.date() if hasattr(d, "date") else d for d in node_dates_raw)
            interp_kwargs = BARCHART_STIRF_CURVE._curve_interp_kwargs(
                nodes=nodes,
                cfg=cfg,
                base_date=base_date,
                interpolation=interpolation,
            )
            kwargs.update(interp_kwargs)

        curve = rl.Curve(**kwargs)

        # Attach metadata
        ts_utc = row.get("timestamp_utc")
        if ts_utc is not None:
            if isinstance(ts_utc, str):
                ts_utc = pd.Timestamp(ts_utc)
            curve.timestamp = ts_utc
            curve.timestamp_utc = ts_utc
            curve.curve_name = row.get("curve_name", reference_key)
            curve.name = curve.curve_name
            curve.reference_key = reference_key

        return curve

    @staticmethod
    def reconstruct_ql_curve(
        row: dict,
        *,
        ql_dc: Any = None,
        ql_cal: Any = None,
        interpolation_algo: str = "df_log_linear",
        enable_extrapolation: bool = True,
    ) -> Any:
        """Reconstruct a QuantLib DiscountCurve from a raw store row."""
        import pandas as pd_local

        from Query.IRSwaps.backends.quantlib.ql_curve_building_utils import (
            build_ql_discount_curve,
        )

        if ql_dc is None or ql_cal is None:
            import QuantLib as ql

            if ql_dc is None:
                ql_dc = ql.Actual360()
            if ql_cal is None:
                ql_cal = ql.UnitedStates(ql.UnitedStates.GovernmentBond)

        node_dates_raw = row["node_dates"]
        dfs_raw = row["discount_factors"]

        dates = [_to_date(d) for d in node_dates_raw]
        datetime_series = pd_local.Series(
            [datetime.datetime(d.year, d.month, d.day) for d in dates]
        )
        df_series = pd_local.Series([float(v) for v in dfs_raw])

        ql_curve = build_ql_discount_curve(
            datetime_series=datetime_series,
            discount_factor_series=df_series,
            ql_dc=ql_dc,
            ql_cal=ql_cal,
            interpolation_algo=interpolation_algo,
        )
        if enable_extrapolation:
            ql_curve.enableExtrapolation()
        elif hasattr(ql_curve, "disableExtrapolation"):
            ql_curve.disableExtrapolation()

        return ql_curve

    @classmethod
    def reconstruct_curves_batch(
        cls,
        df: pd.DataFrame,
        *,
        cfg: Optional[dict] = None,
        max_workers: int = 4,
        progress_callback: Optional[Callable[[int], None]] = None,
    ) -> Dict[datetime.datetime, Any]:
        """Parallel rl.Curve reconstruction from a raw-store DataFrame.

        Returns {timestamp_utc: rl.Curve}.
        """
        if df.empty:
            return {}

        rows = df.to_dict("records")

        def _build_one(row: dict) -> Tuple[Any, Any]:
            ts = row.get("timestamp_utc")
            curve = cls.reconstruct_curve(row, cfg=cfg)
            return ts, curve

        def _emit_progress() -> None:
            if progress_callback is None:
                return
            try:
                progress_callback(1)
            except Exception:
                logger.debug("Curve reconstruction progress callback failed.", exc_info=True)

        n_workers = min(max_workers, max(1, len(rows)))
        result: Dict[datetime.datetime, Any] = {}

        if n_workers <= 1 or len(rows) <= 4:
            for r in rows:
                ts, curve = _build_one(r)
                result[ts] = curve
                _emit_progress()
        else:
            with ThreadPoolExecutor(
                max_workers=n_workers, thread_name_prefix="curve-reconstruct"
            ) as pool:
                futures = {pool.submit(_build_one, r): r for r in rows}
                for fut in as_completed(futures):
                    ts, curve = fut.result()
                    result[ts] = curve
                    _emit_progress()

        return result

    @classmethod
    def reconstruct_ql_curves_batch(
        cls,
        df: pd.DataFrame,
        *,
        ql_dc: Any = None,
        ql_cal: Any = None,
        interpolation_algo: str = "df_log_linear",
        enable_extrapolation: bool = True,
    ) -> Dict[datetime.date, Any]:
        """Batch reconstruct QL DiscountCurves keyed by trading_date."""
        if df.empty:
            return {}

        rows = df.to_dict("records")
        result: Dict[datetime.date, Any] = {}

        for row in rows:
            trading_date = row.get("trading_date")
            if trading_date is None:
                continue
            result[_to_date(trading_date)] = cls.reconstruct_ql_curve(
                row,
                ql_dc=ql_dc,
                ql_cal=ql_cal,
                interpolation_algo=interpolation_algo,
                enable_extrapolation=enable_extrapolation,
            )

        return result

    # ── Metadata ──

    def available_dates(self, curve_name: str) -> list[datetime.date]:
        """List trading dates that have raw data for a curve."""
        asset_dir = self._raw_dir / f"asset={_sanitize(curve_name)}"
        if not asset_dir.exists():
            return []
        dates: list[datetime.date] = []
        for d in sorted(asset_dir.iterdir()):
            if d.is_dir() and d.name.startswith("date="):
                try:
                    dates.append(datetime.date.fromisoformat(d.name[5:]))
                except ValueError:
                    continue
        return dates

    def invalidate_day(
        self,
        curve_name: str,
        trading_date: datetime.date,
    ) -> bool:
        """Delete Parquet file(s) for a specific (curve_name, trading_date).

        Returns True if anything was deleted.
        """
        deleted = False
        for base in (self._raw_dir, self._analytics_dir):
            part_dir = base / f"asset={_sanitize(curve_name)}" / f"date={trading_date.isoformat()}"
            if part_dir.exists():
                for f in part_dir.glob("*.parquet"):
                    f.unlink()
                    deleted = True
                # Remove empty directory
                try:
                    part_dir.rmdir()
                except OSError:
                    pass
        return deleted

    def has_day(self, curve_name: str, trading_date: datetime.date) -> bool:
        """Check if raw data exists for a (curve_name, trading_date)."""
        part_dir = (
            self._raw_dir
            / f"asset={_sanitize(curve_name)}"
            / f"date={trading_date.isoformat()}"
        )
        if not part_dir.exists():
            return False
        return any(part_dir.glob("*.parquet"))

    def has_analytics_day(self, curve_name: str, trading_date: datetime.date) -> bool:
        """Check if analytics data exists for a (curve_name, trading_date)."""
        part_dir = (
            self._analytics_dir
            / f"asset={_sanitize(curve_name)}"
            / f"date={trading_date.isoformat()}"
        )
        if not part_dir.exists():
            return False
        return any(part_dir.glob("*.parquet"))

    @property
    def base_dir(self) -> Path:
        return self._base_dir


# ---------------------------------------------------------------------------
# Arrow / Parquet helpers
# ---------------------------------------------------------------------------

# Raw store Arrow schema
_RAW_SCHEMA = pa.schema(
    [
        pa.field("timestamp_utc", pa.timestamp("us", tz="UTC")),
        pa.field("timestamp_local", pa.timestamp("us")),
        pa.field("trading_date", pa.date32()),
        pa.field("session_minute", pa.int16()),
        pa.field("curve_name", pa.dictionary(pa.int8(), pa.utf8())),
        pa.field("cfg_hash", pa.dictionary(pa.int8(), pa.utf8())),
        pa.field("reference_key", pa.dictionary(pa.int8(), pa.utf8())),
        pa.field("interpolation", pa.dictionary(pa.int8(), pa.utf8())),
        pa.field("source_variant", pa.dictionary(pa.int8(), pa.utf8())),
        pa.field("node_dates", pa.list_(pa.date32())),
        pa.field("discount_factors", pa.list_(pa.float64())),
        # Nullable; absent in partitions written before spline support, which
        # _ensure_raw_table_columns backfills as null -> reconstructs log-linear
        # exactly as those rows always did.
        pa.field("spline_knots", pa.list_(pa.date32())),
        pa.field("spline_endpoints", pa.utf8()),
    ]
)


def _ensure_raw_table_columns(table: pa.Table) -> pa.Table:
    arrays = []
    for field_ in _RAW_SCHEMA:
        if field_.name in table.column_names:
            arrays.append(table[field_.name])
        else:
            arrays.append(pa.array([None] * table.num_rows, type=field_.type))
    return pa.table({name: arr for name, arr in zip(_RAW_SCHEMA.names, arrays)})


def _ensure_raw_df_columns(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    for name in _RAW_SCHEMA.names:
        if name not in df.columns:
            df[name] = None
    return df.loc[:, _RAW_SCHEMA.names]


def _analytics_trading_date_from_timestamp(value: Any) -> Optional[datetime.date]:
    ts_utc = _normalize_timestamp_utc_scalar(value)
    if ts_utc is None:
        return None
    return _compute_trading_date(ts_utc.astimezone(_CHI))


def _analytics_session_minute_from_timestamp(value: Any) -> Optional[int]:
    ts_utc = _normalize_timestamp_utc_scalar(value)
    if ts_utc is None:
        return None
    return _compute_session_minute(ts_utc.astimezone(_CHI))


def _ensure_analytics_df_columns(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    if "timestamp_utc" not in df.columns:
        df["timestamp_utc"] = pd.NaT

    derived_trading_dates = df["timestamp_utc"].map(_analytics_trading_date_from_timestamp)
    if "trading_date" not in df.columns:
        df["trading_date"] = derived_trading_dates
    else:
        missing_trading_dates = df["trading_date"].isna()
        if missing_trading_dates.any():
            df.loc[missing_trading_dates, "trading_date"] = derived_trading_dates.loc[missing_trading_dates]

    derived_session_minutes = df["timestamp_utc"].map(_analytics_session_minute_from_timestamp)
    if "session_minute" not in df.columns:
        df["session_minute"] = pd.array(derived_session_minutes.tolist(), dtype="Int16")
    else:
        session_minute = pd.to_numeric(df["session_minute"], errors="coerce")
        missing_session_minutes = session_minute.isna()
        if missing_session_minutes.any():
            fill_values = pd.Series(derived_session_minutes, index=df.index, dtype="float64")
            session_minute = session_minute.where(~missing_session_minutes, fill_values)
        try:
            df["session_minute"] = session_minute.astype("Int16")
        except (TypeError, ValueError):
            df["session_minute"] = session_minute

    return df


def _snapshots_to_arrow_table(snapshots: Sequence[CurveSnapshot]) -> pa.Table:
    """Convert a list of CurveSnapshot to a PyArrow Table."""
    ts_utc = []
    ts_local = []
    tdate = []
    smin = []
    cname = []
    chash = []
    rkey = []
    interp = []
    svar = []
    ndates = []
    dfs = []
    sknots = []
    sends = []

    for s in snapshots:
        ts_utc.append(s.timestamp_utc)
        # Strip tzinfo for the local column (Arrow timestamp without tz)
        ts_local.append(s.timestamp_local.replace(tzinfo=None))
        tdate.append(s.trading_date)
        smin.append(s.session_minute)
        cname.append(s.curve_name)
        chash.append(s.cfg_hash)
        rkey.append(s.reference_key)
        interp.append(s.interpolation)
        svar.append(s.source_variant)
        ndates.append(s.node_dates)
        dfs.append(s.discount_factors)
        sknots.append(getattr(s, "spline_knots", None))
        sends.append(getattr(s, "spline_endpoints", None))

    arrays = [
        pa.array(ts_utc, type=pa.timestamp("us", tz="UTC")),
        pa.array(ts_local, type=pa.timestamp("us")),
        pa.array(tdate, type=pa.date32()),
        pa.array(smin, type=pa.int16()),
        pa.array(cname).dictionary_encode(),
        pa.array(chash).dictionary_encode(),
        pa.array(rkey).dictionary_encode(),
        pa.array(interp).dictionary_encode(),
        pa.array(svar).dictionary_encode(),
        pa.array(ndates, type=pa.list_(pa.date32())),
        pa.array(dfs, type=pa.list_(pa.float64())),
        pa.array(sknots, type=pa.list_(pa.date32())),
        pa.array(sends, type=pa.utf8()),
    ]

    return pa.table(
        {name: arr for name, arr in zip(_RAW_SCHEMA.names, arrays)}
    )


def _write_parquet_bytes(
    table: pa.Table,
    compression: str = DEFAULT_COMPRESSION,
) -> bytes:
    """Serialize an Arrow Table to Parquet bytes in memory."""
    sink = pa.BufferOutputStream()
    pq.write_table(
        table,
        sink,
        compression=compression,
        use_dictionary=True,
        write_statistics=True,
    )
    return sink.getvalue().to_pybytes()


def _atomic_content_write(
    part_dir: Path,
    data: bytes,
    *,
    overwrite: bool = False,
) -> Optional[dict]:
    """Content-addressed atomic write. Returns metadata or None if skipped."""
    part_dir.mkdir(parents=True, exist_ok=True)
    sha = hashlib.sha256(data).hexdigest()
    final_path = part_dir / f"{sha}.parquet"

    if final_path.exists() and not overwrite:
        return None  # identical content already exists

    # Remove old files in this partition if overwriting
    if overwrite:
        for old in part_dir.glob("*.parquet"):
            old.unlink()

    # Atomic: write to temp, then rename
    with tempfile.NamedTemporaryFile(
        dir=str(part_dir), delete=False, suffix=".tmp"
    ) as tmp:
        tmp.write(data)
        tmp.flush()
        os.fsync(tmp.fileno())
        tmp_path = Path(tmp.name)

    os.replace(tmp_path, final_path)

    return {
        "path": str(final_path),
        "size": len(data),
        "sha256": sha,
    }


# ---------------------------------------------------------------------------
# Parsing helpers
# ---------------------------------------------------------------------------

_KEY_RX = re.compile(r"^v(\d+)_(.+?)_(\d{8}T\d{6}Z)_([a-f0-9]{16})$")


def _parse_cache_key(key: str) -> Tuple[str, str, str]:
    """Parse a diskcache key like 'v1_USD-SOFR-1D-Q12STIRT_20260313T120000Z_b1da569...'

    Returns (curve_name, ts_str, cfg_hash).
    """
    m = _KEY_RX.match(key)
    if m:
        return m.group(2), m.group(3), m.group(4)

    # Fallback: split from the right (cfg_hash is always last 16 hex chars)
    parts = key.split("_")
    if len(parts) >= 4:
        cfg_hash = parts[-1]
        ts_str = parts[-2]
        curve_name = "_".join(parts[1:-2])
        return curve_name, ts_str, cfg_hash

    return "", "", ""


def _parse_key_timestamp(ts_str: str) -> datetime.datetime:
    """Parse '20260313T120000Z' → tz-aware UTC datetime."""
    try:
        dt = datetime.datetime.strptime(ts_str, "%Y%m%dT%H%M%SZ")
        return _UTC.localize(dt)
    except ValueError:
        return _UTC.localize(datetime.datetime(2000, 1, 1))


def _extract_nodes_from_curve_json(
    curve_json_str: str,
) -> Tuple[list[datetime.date], list[float], str, str]:
    """Extract node dates + DFs from rateslib curve JSON without rl.from_json().

    Returns (node_dates, discount_factors, interpolation, reference_key).
    ~0.02ms per call vs 1.6ms for rl.from_json().
    """
    parsed = json.loads(curve_json_str)

    # Navigate: {"PyNative": {"Curve": {"nodes": ..., "interpolator": ..., "id": ...}}}
    curve_data = parsed.get("PyNative", {}).get("Curve", {})

    # Extract nodes
    nodes_raw = curve_data.get("nodes", "{}")
    if isinstance(nodes_raw, str):
        nodes_parsed = json.loads(nodes_raw)
    else:
        nodes_parsed = nodes_raw

    node_dict: dict = {}
    if "PyNative" in nodes_parsed:
        node_dict = (
            nodes_parsed.get("PyNative", {})
            .get("_CurveNodes", {})
            .get("_nodes", {})
        )
    elif isinstance(nodes_parsed, dict):
        node_dict = nodes_parsed

    # Sort by date
    sorted_dates = sorted(node_dict.keys())
    node_dates = [datetime.date.fromisoformat(d) for d in sorted_dates]
    discount_factors = [float(node_dict[d]) for d in sorted_dates]

    # Extract interpolation
    interpolation = "log_linear"
    interp_raw = curve_data.get("interpolator", "{}")
    if isinstance(interp_raw, str):
        try:
            interp_parsed = json.loads(interp_raw)
            interpolation = (
                interp_parsed.get("PyNative", {})
                .get("_CurveInterpolator", {})
                .get("local", "log_linear")
            )
        except (json.JSONDecodeError, KeyError):
            pass

    # Extract reference key (curve id)
    reference_key = str(curve_data.get("id", ""))

    return node_dates, discount_factors, interpolation, reference_key


def _sanitize(name: str) -> str:
    """Filesystem-safe name."""
    return re.sub(r"[^\w.\-]", "_", name)


def _to_date(d: Any) -> datetime.date:
    """Convert various date types to datetime.date."""
    if isinstance(d, datetime.date) and not isinstance(d, datetime.datetime):
        return d
    if isinstance(d, datetime.datetime):
        return d.date()
    if isinstance(d, pd.Timestamp):
        return d.date()
    if isinstance(d, np.datetime64):
        return pd.Timestamp(d).date()
    if hasattr(d, "year") and hasattr(d, "month") and hasattr(d, "day"):
        return datetime.date(d.year, d.month, d.day)
    if isinstance(d, str):
        return datetime.date.fromisoformat(d)
    raise TypeError(f"Cannot convert {type(d)} to date")


def _compute_trading_date(ts_local: datetime.datetime) -> datetime.date:
    """Compute the CME trading date from a Chicago-localized timestamp.

    CME session boundary is 17:00 CT — timestamps before 17:00 belong to
    that calendar date's session; timestamps at/after 17:00 belong to the
    next session.
    """
    if ts_local.hour >= 17:
        return (ts_local + datetime.timedelta(days=1)).date()
    return ts_local.date()


def _compute_session_minute(ts_local: datetime.datetime) -> int:
    """Minutes since 07:00 CT.  Negative for pre-open, >480 for post-close."""
    ref = ts_local.replace(hour=_SESSION_OPEN_HOUR, minute=_SESSION_OPEN_MINUTE, second=0, microsecond=0)
    delta = ts_local - ref
    return int(delta.total_seconds() // 60)
