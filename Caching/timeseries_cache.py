# Caching/timeseries_cache.py
from __future__ import annotations

import hashlib
import os
import tempfile
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Union

import duckdb
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

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
    if df is None or len(df) == 0:
        return []

    opts = opts or WriteOptions(base_dir="./data/ts")
    base_dir = Path(opts.base_dir)
    symbol = _sanitize_symbol(symbol)

    # Partition df by date
    if isinstance(df.index, pd.DatetimeIndex):
        sdf = df.copy()
        sdf.index = sdf.index.tz_convert(None) if sdf.index.tz else sdf.index
        groups: Dict[date, pd.DataFrame] = {pd.Timestamp(d).date(): g for d, g in sdf.groupby(sdf.index.date)}
    else:
        # No datetime index; use provided as_of_date
        if as_of_date is None:
            raise ValueError("DataFrame has no DatetimeIndex; provide as_of_date.")
        groups = {as_of_date: df}

    metas: List[FileMetaDict] = []

    for d, g in sorted(groups.items()):
        # path: base_dir/asset=<SYMBOL>/date=YYYY-MM-DD/part-<N>.parquet
        part_dir = base_dir / f"asset={symbol}" / datetime.strftime(datetime(d.year, d.month, d.day), opts.partition_fmt)
        part_dir.mkdir(parents=True, exist_ok=True)

        existing = read_timeseries(
            None,
            symbol,
            start=d,
            end=d,
            base_dir=base_dir,
        )
        if not existing.empty:
            if isinstance(existing.index, pd.DatetimeIndex) and isinstance(g.index, pd.DatetimeIndex):
                combined = pd.concat([existing, g], axis=0).sort_index()
                combined = combined[~combined.index.duplicated(keep="last")]
            else:
                combined = pd.concat([existing, g], axis=0).drop_duplicates(keep="last")
            g = combined

        # Arrow table + Parquet
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

        rows = g.shape[0]
        size = final_path.stat().st_size
        ts_min, ts_max = _df_min_max_ts(g)
        meta: FileMetaDict = {
            "path": str(final_path),
            "rows": int(rows),
            "size": int(size),
            "min_ts": ts_min,
            "max_ts": ts_max,
            "sha256": file_sha,
        }

        metas.append(meta)

    return metas


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
    primary_symbol = _sanitize_symbol(symbol)
    legacy_symbol = _legacy_sanitize_symbol(symbol)
    base = Path(base_dir)
    symbol_dir = base / f"asset={primary_symbol}"
    if not symbol_dir.exists() and legacy_symbol != primary_symbol:
        legacy_dir = base / f"asset={legacy_symbol}"
        if legacy_dir.exists():
            symbol_dir = legacy_dir

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
        df = duckdb.sql(query).df()
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
            df = duckdb.sql(query).df()
        except Exception:
            return pd.DataFrame()

    if df.empty:
        return pd.DataFrame()

    # Restore DatetimeIndex from _index_ts if present
    if "_index_ts" in df.columns:
        df.set_index(pd.to_datetime(df["_index_ts"], utc=False), inplace=True)
        df.drop(columns=["_index_ts"], inplace=True)

    # Drop the hive partition column if it leaked through
    if "date" in df.columns:
        df.drop(columns=["date"], inplace=True)

    # If user provided start/end as datetimes, trim exactly
    if isinstance(start, datetime) and isinstance(df.index, pd.DatetimeIndex):
        df = df[df.index >= pd.Timestamp(start)]
    if isinstance(end, datetime) and isinstance(df.index, pd.DatetimeIndex):
        df = df[df.index <= pd.Timestamp(end)]

    return df.sort_index()
