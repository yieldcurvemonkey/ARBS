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
import re
import tempfile
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple, Union

import logging as _logging

import duckdb
import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
import pytz

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

logger = _logging.getLogger(__name__)

DEFAULT_COMPRESSION = "zstd"
_CHI = pytz.timezone("America/Chicago")
_UTC = pytz.UTC

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
    return sorted({_compute_trading_date(ts.astimezone(_CHI)) for ts in timestamps_utc})


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
    ) -> None:
        if base_dir is None:
            base_dir = self._default_base_dir()
        self._base_dir = Path(base_dir)
        self._compression = compression
        self._raw_dir = self._base_dir / "raw"
        self._analytics_dir = self._base_dir / "analytics"
        self._bg_push_threads: list[threading.Thread] = []
        self._bg_push_lock = threading.Lock()

    def _track_bg_push_thread(self, thread: threading.Thread) -> None:
        with self._bg_push_lock:
            self._bg_push_threads = [t for t in self._bg_push_threads if t.is_alive()]
            self._bg_push_threads.append(thread)

    def _release_bg_push_thread(self, thread: threading.Thread) -> None:
        with self._bg_push_lock:
            self._bg_push_threads = [t for t in self._bg_push_threads if t.is_alive() and t is not thread]

    def wait_for_background_pushes(self, timeout: Optional[float] = None) -> int:
        """Join outstanding background Supabase push threads.

        Returns the number of tracked push threads that were awaited.
        """
        deadline = None if timeout is None else (time.monotonic() + float(timeout))
        waited = 0

        while True:
            with self._bg_push_lock:
                threads = [t for t in self._bg_push_threads if t.is_alive()]
                self._bg_push_threads = threads

            if not threads:
                return waited

            waited = max(waited, len(threads))
            for thread in threads:
                remaining = None if deadline is None else max(0.0, deadline - time.monotonic())
                thread.join(remaining)

            if deadline is not None and time.monotonic() >= deadline:
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
    ) -> Optional[dict]:
        """Atomic write of all snapshots for one (curve_name, trading_date).

        Content-addressed: skips write if SHA256 matches existing file.
        Returns file metadata dict, or None if skipped.
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
        sync = _get_curve_sync(self._base_dir)
        if sync is not None:
            def _bg_push():
                try:
                    sync.push_day(curve_name, trading_date)
                except Exception:
                    logger.warning("L2 push failed for %s/%s", curve_name, trading_date, exc_info=True)
                finally:
                    self._release_bg_push_thread(threading.current_thread())

            thread = threading.Thread(target=_bg_push, daemon=True)
            self._track_bg_push_thread(thread)
            thread.start()

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
            def _bg_push():
                try:
                    sync.push_analytics_day(curve_name, trading_date)
                except Exception:
                    logger.warning(
                        "L2 analytics push failed for %s/%s",
                        curve_name,
                        trading_date,
                        exc_info=True,
                    )
                finally:
                    self._release_bg_push_thread(threading.current_thread())

            thread = threading.Thread(target=_bg_push, daemon=True)
            self._track_bg_push_thread(thread)
            thread.start()

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
        asset_dir = self._raw_dir / f"asset={_sanitize(curve_name)}"
        if not asset_dir.exists():
            return pd.DataFrame()

        requested_timestamps_utc = _normalize_timestamp_utc_values(timestamps_utc)
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
            df = duckdb.sql(query).df()
        except (duckdb.IOException, duckdb.CatalogException):
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
        col_expr = ", ".join(f'"{c}"' for c in cols) if (tenors and metrics) else "*"

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
            FROM read_parquet('{glob_pattern}', hive_partitioning=true) analytics
            {join_clause}
            {where_clause}
            ORDER BY timestamp_utc
        """
        try:
            df = duckdb.sql(query).df()
        except (duckdb.IOException, duckdb.CatalogException):
            sync = _get_curve_sync(self._base_dir)
            if sync is not None and start_date is not None and end_date is not None:
                try:
                    sync.prefetch_analytics_range(curve_name, start_date, end_date)
                    df = duckdb.sql(query).df()
                except (duckdb.IOException, duckdb.CatalogException):
                    return pd.DataFrame()
            else:
                return pd.DataFrame()

        if "date" in df.columns:
            df.drop(columns=["date"], inplace=True)

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

        # Curve construction kwargs
        curve_def = RATESLIB_CURVE_DEFINITIONS.get(reference_key, {})
        kwargs: Dict[str, Any] = {
            "nodes": nodes,
            "id": reference_key,
            "convention": curve_def.get("DayCounter", "act360"),
            "calendar": curve_def.get("Calendar", "nyc"),
            "modifier": curve_def.get("BusinessConvention", "mf"),
            "interpolation": interpolation,
        }

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

        n_workers = min(max_workers, max(1, len(rows)))
        result: Dict[datetime.datetime, Any] = {}

        if n_workers <= 1 or len(rows) <= 4:
            for r in rows:
                ts, curve = _build_one(r)
                result[ts] = curve
        else:
            with ThreadPoolExecutor(
                max_workers=n_workers, thread_name_prefix="curve-reconstruct"
            ) as pool:
                futures = {pool.submit(_build_one, r): r for r in rows}
                for fut in as_completed(futures):
                    ts, curve = fut.result()
                    result[ts] = curve

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
