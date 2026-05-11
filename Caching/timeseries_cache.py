# Caching/timeseries_cache.py
from __future__ import annotations

import hashlib
import os
import tempfile
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple, Union

import duckdb
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


# ------------------------------ Configuration --------------------------------

DEFAULT_COMPRESSION = "zstd"
DEFAULT_ROW_GROUP_SIZE = 256_000  # ~rows per row-group; tune for your data
DEFAULT_PARTITION_FMT = "date=%Y-%m-%d"  # directory partition format


# ------------------------------ Helpers ---------------------------------------


def _sanitize_symbol(symbol: str) -> str:
    safe = _legacy_sanitize_symbol(symbol)
    if len(safe) <= 48:
        return safe
    digest = hashlib.sha1(symbol.encode("utf-8")).hexdigest()[:16]
    return f"{safe[:24]}__{digest}"


def _legacy_sanitize_symbol(symbol: str) -> str:
    # filesystem-safe-ish
    return "".join(ch if ch.isalnum() or ch in ("-", "_", ".") else "_" for ch in symbol)


def _to_datestr(d: Union[date, datetime]) -> str:
    if isinstance(d, datetime):
        d = d.date()
    return d.isoformat()


def _atomic_write_bytes(dst_path: Path, data: bytes) -> None:
    def _path_str(path: Path) -> str:
        resolved = str(path.resolve())
        if os.name == "nt" and not resolved.startswith("\\\\?\\"):
            return "\\\\?\\" + resolved
        return resolved

    dst_path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=str(dst_path.parent), delete=False) as tmp:
        tmp.write(data)
        tmp.flush()
        os.fsync(tmp.fileno())
        tmp_path = Path(tmp.name)
    os.replace(_path_str(tmp_path), _path_str(dst_path))


def _df_min_max_ts(df: pd.DataFrame) -> Tuple[str, str]:
    idx = df.index
    if isinstance(idx, pd.DatetimeIndex):
        return (idx.min().isoformat(), idx.max().isoformat())
    # fallback to a column called 'timestamp' if present
    if "timestamp" in df.columns and pd.api.types.is_datetime64_any_dtype(df["timestamp"]):
        return (df["timestamp"].min().isoformat(), df["timestamp"].max().isoformat())
    # not datetime: store row indices as strings
    return (str(df.index.min()), str(df.index.max()))


def _df_to_table(df: pd.DataFrame) -> pa.Table:
    if isinstance(df.index, pd.DatetimeIndex):
        df = df.copy()
        df.insert(0, "_index_ts", df.index.tz_localize(None) if df.index.tz else df.index)
        df.reset_index(drop=True, inplace=True)
    return pa.Table.from_pandas(df, preserve_index=False)


def _restore_datetime_index(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df

    restored_index = None
    if "_index_ts" in df.columns:
        restored_index = pd.to_datetime(df["_index_ts"], utc=False, errors="coerce")
        if "date" in df.columns:
            partition_dates = pd.to_datetime(df["date"], utc=False, errors="coerce")
            restored_index = restored_index.where(restored_index.notna(), partition_dates)
        df = df.drop(columns=["_index_ts"])

    if restored_index is None or restored_index.isna().all():
        for candidate in ("timestamp", "Timestamp", "Date", "date"):
            if candidate not in df.columns:
                continue
            candidate_index = pd.to_datetime(df[candidate], utc=False, errors="coerce")
            if candidate_index.notna().any():
                restored_index = candidate_index
                break

    if restored_index is not None and restored_index.notna().any():
        df = df.copy()
        df.index = pd.DatetimeIndex(restored_index)
        df = df.loc[~df.index.isna()].copy()

    for partition_col in ("date", "asset"):
        if partition_col in df.columns:
            df = df.drop(columns=[partition_col])

    return df


def _write_parquet_bytes(table: pa.Table, compression: str = DEFAULT_COMPRESSION, row_group_size: int = DEFAULT_ROW_GROUP_SIZE) -> bytes:
    sink = pa.BufferOutputStream()
    pq.write_table(
        table,
        sink,
        compression=compression,
        use_dictionary=True,
        write_statistics=True,
        data_page_size=None,  # let parquet choose
        row_group_size=row_group_size,
    )
    return sink.getvalue().to_pybytes()


# Minimal dict schema to keep return values compatible.
# { "path": str, "rows": int, "size": int, "min_ts": str, "max_ts": str, "sha256": str }
FileMetaDict = Dict[str, Union[str, int]]


def _resolve_symbol_dir(base_dir: Path, symbol: str) -> Path:
    primary_symbol = _sanitize_symbol(symbol)
    legacy_symbol = _legacy_sanitize_symbol(symbol)
    symbol_dir = base_dir / f"asset={primary_symbol}"
    if not symbol_dir.exists() and legacy_symbol != primary_symbol:
        legacy_dir = base_dir / f"asset={legacy_symbol}"
        if legacy_dir.exists():
            return legacy_dir
    return symbol_dir


def _partition_frames_by_date(
    df: pd.DataFrame,
    *,
    as_of_date: Optional[date],
) -> Dict[date, pd.DataFrame]:
    if isinstance(df.index, pd.DatetimeIndex):
        sdf = df.copy()
        sdf.index = sdf.index.tz_convert(None) if sdf.index.tz else sdf.index
        return {pd.Timestamp(d).date(): g for d, g in sdf.groupby(sdf.index.date)}

    if as_of_date is None:
        raise ValueError("DataFrame has no DatetimeIndex; provide as_of_date.")
    return {as_of_date: df}


def _read_partition_df(part_dir: Path) -> pd.DataFrame:
    parquet_files = sorted(part_dir.glob("*.parquet"))
    if not parquet_files:
        return pd.DataFrame()

    # Use ParquetFile to avoid PyArrow's Hive-partition auto-discovery which
    # conflicts with legacy files that already have an ``asset`` column.
    tables = [pq.ParquetFile(path).read() for path in parquet_files]

    # Drop stale partition-artifact columns that some legacy files carry.
    _ARTIFACT_COLS = {"asset", "date"}
    cleaned: list[pa.Table] = []
    for t in tables:
        drop = [c for c in t.column_names if c in _ARTIFACT_COLS]
        if drop:
            t = t.drop_columns(drop)
        cleaned.append(t)
    tables = cleaned

    table = tables[0] if len(tables) == 1 else pa.concat_tables(tables, promote_options="default")
    df = table.to_pandas()
    if df.empty:
        return pd.DataFrame()
    if "_index_ts" in df.columns:
        restored_index = pd.to_datetime(df["_index_ts"], utc=False, errors="coerce")
        if restored_index.isna().all() and "date" not in df.columns:
            partition_label = str(part_dir.name)
            if partition_label.startswith("date="):
                df = df.copy()
                df["date"] = partition_label.split("=", 1)[1]
    return _restore_datetime_index(df).sort_index()


# ------------------------------ Public API ------------------------------------


@dataclass
class WriteOptions:
    base_dir: Union[str, Path]
    compression: str = DEFAULT_COMPRESSION
    row_group_size: int = DEFAULT_ROW_GROUP_SIZE
    partition_fmt: str = DEFAULT_PARTITION_FMT  # e.g., 'date=%Y-%m-%d'


def append_timeseries(
    root,  # ignored (kept for API compat, was ZODB root)
    symbol: str,
    df: pd.DataFrame,
    *,
    as_of_date: Optional[date] = None,
    opts: Optional[WriteOptions] = None,
) -> List[FileMetaDict]:
    """
    Append a DataFrame to partitioned Parquet storage.
    Returns a list of FileMetaDict entries created.

    The ``root`` parameter is ignored (kept for backward compatibility with
    callers that previously passed a ZODB connection root).
    """
    metas_by_symbol = append_timeseries_many(
        root,
        [(symbol, df, as_of_date)],
        opts=opts,
    )
    return metas_by_symbol.get(symbol, [])


def append_timeseries_many(
    root,  # ignored (kept for API compat, was ZODB root)
    items: Iterable[Tuple[str, pd.DataFrame, Optional[date]]],
    *,
    opts: Optional[WriteOptions] = None,
) -> Dict[str, List[FileMetaDict]]:
    """
    Append multiple symbol DataFrames to partitioned Parquet storage.
    Returns a mapping from input symbol to FileMetaDict entries created.
    """
    _ = root

    item_list = [(symbol, df, as_of_date) for symbol, df, as_of_date in items if df is not None and len(df) > 0]
    if not item_list:
        return {}

    opts = opts or WriteOptions(base_dir="./data/ts")
    base_dir = Path(opts.base_dir)

    tasks: List[Tuple[str, Path, date, pd.DataFrame]] = []
    for symbol, df, as_of_date in item_list:
        symbol_dir = _resolve_symbol_dir(base_dir, symbol)
        groups = _partition_frames_by_date(df, as_of_date=as_of_date)
        for d, g in groups.items():
            tasks.append((symbol, symbol_dir, d, g))

    def _process_partition(symbol: str, symbol_dir: Path, d: date, g: pd.DataFrame) -> Tuple[str, FileMetaDict]:
        part_dir = symbol_dir / datetime.strftime(datetime(d.year, d.month, d.day), opts.partition_fmt)
        part_dir.mkdir(parents=True, exist_ok=True)

        existing = _read_partition_df(part_dir)
        if not existing.empty:
            if isinstance(existing.index, pd.DatetimeIndex) and isinstance(g.index, pd.DatetimeIndex):
                # Preserve append order for duplicate timestamps so the incoming
                # frame deterministically overwrites older values.
                combined = pd.concat([existing, g], axis=0)
                combined = combined[~combined.index.duplicated(keep="last")]
                combined = combined.sort_index()
            else:
                combined = pd.concat([existing, g], axis=0).drop_duplicates(keep="last")
            g = combined

        table = _df_to_table(g)
        pbytes = _write_parquet_bytes(table, opts.compression, opts.row_group_size)

        file_sha = hashlib.sha256(pbytes).hexdigest()
        final_name = f"{file_sha}.parquet"
        final_path = part_dir / final_name

        if not final_path.exists():
            _atomic_write_bytes(final_path, pbytes)

        for old_path in part_dir.glob("*.parquet"):
            if old_path == final_path:
                continue
            try:
                os.remove(old_path)
            except FileNotFoundError:
                pass

        rows_count = g.shape[0]
        size = final_path.stat().st_size
        ts_min, ts_max = _df_min_max_ts(g)
        return symbol, {
            "path": str(final_path),
            "rows": int(rows_count),
            "size": int(size),
            "min_ts": ts_min,
            "max_ts": ts_max,
            "sha256": file_sha,
        }

    if len(tasks) <= 4:
        results = [_process_partition(symbol, symbol_dir, d, g) for symbol, symbol_dir, d, g in tasks]
    else:
        workers = min(len(tasks), os.cpu_count() or 4, 8)
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = {
                pool.submit(_process_partition, symbol, symbol_dir, d, g): symbol
                for symbol, symbol_dir, d, g in tasks
            }
            results = [future.result() for future in as_completed(futures)]

    metas_by_symbol: Dict[str, List[FileMetaDict]] = {}
    for symbol, meta in results:
        metas_by_symbol.setdefault(symbol, []).append(meta)
    return metas_by_symbol


def read_timeseries(
    root,  # ignored (kept for API compat)
    symbol: str,
    *,
    start: Optional[Union[date, datetime]] = None,
    end: Optional[Union[date, datetime]] = None,
    columns: Optional[List[str]] = None,
    base_dir: Union[str, Path] = "./data/ts",
) -> pd.DataFrame:
    """
    Read timeseries for *symbol* over [start, end] using DuckDB to scan
    Hive-partitioned Parquet files directly (no catalog needed).
    """
    base = Path(base_dir)
    symbol_dir = _resolve_symbol_dir(base, symbol)

    if not symbol_dir.exists():
        return pd.DataFrame()

    # Build glob pattern for DuckDB
    glob_pattern = str(symbol_dir / "date=*" / "*.parquet").replace("\\", "/")

    # Build column expression
    if columns:
        # Always include _index_ts if it exists so we can restore the index
        select_cols = list(columns)
        if "_index_ts" not in select_cols:
            select_cols.append("_index_ts")
        col_expr = ", ".join(f'"{c}"' for c in select_cols)
    else:
        col_expr = "*"

    # Build WHERE clause for date partition pruning
    where_parts = []
    if start is not None:
        s = start.date() if isinstance(start, datetime) else start
        where_parts.append(f"date >= '{s.isoformat()}'")
    if end is not None:
        e = end.date() if isinstance(end, datetime) else end
        where_parts.append(f"date <= '{e.isoformat()}'")

    where_clause = f"WHERE {' AND '.join(where_parts)}" if where_parts else ""

    try:
        query = f"""
            SELECT {col_expr}
            FROM read_parquet('{glob_pattern}', hive_partitioning=true)
            {where_clause}
            ORDER BY _index_ts
        """
        df = _thread_local_conn().sql(query).df()
    except duckdb.IOException:
        return pd.DataFrame()
    except duckdb.CatalogException:
        # No _index_ts column; try without ORDER BY
        query = f"""
            SELECT {col_expr}
            FROM read_parquet('{glob_pattern}', hive_partitioning=true)
            {where_clause}
        """
        try:
            df = _thread_local_conn().sql(query).df()
        except Exception:
            return pd.DataFrame()

    if df.empty:
        return pd.DataFrame()

    df = _restore_datetime_index(df)

    # If user provided start/end as datetimes, trim exactly
    if isinstance(start, datetime) and isinstance(df.index, pd.DatetimeIndex):
        df = df[df.index >= pd.Timestamp(start)]
    if isinstance(end, datetime) and isinstance(df.index, pd.DatetimeIndex):
        df = df[df.index <= pd.Timestamp(end)]

    return df.sort_index()
