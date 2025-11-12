# ABOUTME: Time series data caching infrastructure
# ABOUTME: Manages cached time series with metadata, versioning, and efficient retrieval
# Caching/timeseries_cache.py
from __future__ import annotations

import hashlib
import os
import tempfile
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple, Union

import polars as pl
import pyarrow as pa
import pyarrow.parquet as pq
import transaction
from BTrees.OOBTree import OOBTree  # type: ignore
from persistent import Persistent

# ------------------------------ Configuration --------------------------------

DEFAULT_COMPRESSION = "zstd"
DEFAULT_ROW_GROUP_SIZE = 256_000  # ~rows per row-group; tune for your data
DEFAULT_PARTITION_FMT = "date=%Y-%m-%d"  # directory partition format
SMALL_TXN_BATCH = 32  # commit every N partitions written


# ------------------------------ Catalog model ---------------------------------


class TSCatalog(Persistent):
    """
    ZODB catalog:
    root['ts_catalog'] -> TSCatalog
      .shards   : OOBTree[str, OOBTree[str, SymbolIndex]]
      .pointers : optional: lookup of arbitrary logical names -> (symbol, date_str, part_file)
    """

    def __init__(self):
        self.shards = OOBTree()  # 2-hex shard -> OOBTree[symbol:str, SymbolIndex]
        self.pointers = OOBTree()  # optional


class SymbolIndex(Persistent):
    """
    Per-symbol index:
      .by_date : OOBTree[date_str -> OOBTree[part_filename -> FileMetaDict]]
    """

    def __init__(self):
        self.by_date = OOBTree()


# Minimal dict schema to keep catalog objects tiny.
# { "path": str, "rows": int, "size": int, "min_ts": str, "max_ts": str, "sha256": str }
FileMetaDict = Dict[str, Union[str, int]]


# ------------------------------ Helpers ---------------------------------------


def _sanitize_symbol(symbol: str) -> str:
    # filesystem-safe-ish
    return "".join(ch if ch.isalnum() or ch in ("-", "_", ".") else "_" for ch in symbol)


def _sym_shard(symbol: str) -> str:
    return hashlib.sha256(symbol.encode("utf-8")).hexdigest()[:2]


def _ensure_catalog(root) -> TSCatalog:
    cat = root.get("ts_catalog")
    if cat is None:
        cat = TSCatalog()
        root["ts_catalog"] = cat
    return cat


def _symbol_index(cat: TSCatalog, symbol: str) -> SymbolIndex:
    shard = _sym_shard(symbol)
    shard_map = cat.shards.get(shard)
    if shard_map is None:
        shard_map = OOBTree()
        cat.shards[shard] = shard_map
    s_idx = shard_map.get(symbol)
    if s_idx is None:
        s_idx = SymbolIndex()
        shard_map[symbol] = s_idx
    return s_idx


def _to_datestr(d: Union[date, datetime]) -> str:
    if isinstance(d, datetime):
        d = d.date()
    return d.isoformat()


def _atomic_write_bytes(dst_path: Path, data: bytes) -> None:
    dst_path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=str(dst_path.parent), delete=False) as tmp:
        tmp.write(data)
        tmp.flush()
        os.fsync(tmp.fileno())
        tmp_path = Path(tmp.name)
    os.replace(tmp_path, dst_path)


def _hash_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _df_min_max_ts(df: pl.DataFrame) -> Tuple[str, str]:
    # Check for _index_ts column (from pandas-indexed data)
    if "_index_ts" in df.columns and df.schema["_index_ts"] in [pl.Datetime, pl.Date]:
        min_val = df["_index_ts"].min()
        max_val = df["_index_ts"].max()
        return (min_val.isoformat(), max_val.isoformat())
    # Check for timestamp column
    if "timestamp" in df.columns and df.schema["timestamp"] in [pl.Datetime, pl.Date]:
        min_val = df["timestamp"].min()
        max_val = df["timestamp"].max()
        return (min_val.isoformat(), max_val.isoformat())
    # Check for any datetime column
    for col_name in df.columns:
        if df.schema[col_name] in [pl.Datetime, pl.Date]:
            min_val = df[col_name].min()
            max_val = df[col_name].max()
            return (min_val.isoformat(), max_val.isoformat())
    # No datetime column: use row indices as strings
    return ("0", str(len(df) - 1))


def _df_to_table(df: pl.DataFrame) -> pa.Table:
    # Polars doesn't have an index, data is already in columns
    # Convert directly to Arrow table
    return df.to_arrow()


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


# ------------------------------ Public API ------------------------------------


@dataclass
class WriteOptions:
    base_dir: Union[str, Path]
    compression: str = DEFAULT_COMPRESSION
    row_group_size: int = DEFAULT_ROW_GROUP_SIZE
    partition_fmt: str = DEFAULT_PARTITION_FMT  # e.g., 'date=%Y-%m-%d'


def append_timeseries(
    root,
    symbol: str,
    df: Union[pl.DataFrame, "pd.DataFrame"],  # Accept both pandas and polars
    *,
    as_of_date: Optional[date] = None,  # if None, will use df datetime column
    opts: Optional[WriteOptions] = None,
) -> List[FileMetaDict]:
    """
    Append a DataFrame to partitioned Parquet storage and update the ZODB catalog.
    Partitions by calendar date (derived from datetime index or provided as_of_date).

    Returns a list of FileMetaDict entries created.
    """
    if df is None or len(df) == 0:
        return []

    # Convert pandas to polars if needed
    is_pandas = hasattr(df, 'index') and not isinstance(df, pl.DataFrame)
    if is_pandas:
        import pandas as pd
        # If pandas DataFrame has DatetimeIndex, convert it to a column
        if isinstance(df.index, pd.DatetimeIndex):
            df_copy = df.copy()
            df_copy.insert(0, "_index_ts", df_copy.index.tz_localize(None) if df_copy.index.tz else df_copy.index)
            df_copy.reset_index(drop=True, inplace=True)
            df = pl.from_pandas(df_copy)
        else:
            df = pl.from_pandas(df)

    opts = opts or WriteOptions(base_dir="./data/ts")
    base_dir = Path(opts.base_dir)
    symbol = _sanitize_symbol(symbol)
    cat = _ensure_catalog(root)
    s_idx = _symbol_index(cat, symbol)

    # Partition df by date
    # Find datetime column
    datetime_col = None
    for col_name in df.columns:
        if df.schema[col_name] in [pl.Datetime, pl.Date]:
            datetime_col = col_name
            break

    if datetime_col is not None:
        # Group by date extracted from datetime column
        df_with_date = df.with_columns(pl.col(datetime_col).cast(pl.Date).alias("_partition_date"))
        groups: Dict[date, pl.DataFrame] = {}
        for group_df in df_with_date.partition_by("_partition_date", as_dict=False):
            partition_date = group_df["_partition_date"][0]
            # Convert polars date to Python date
            if isinstance(partition_date, date):
                py_date = partition_date
            else:
                py_date = partition_date.date() if hasattr(partition_date, 'date') else date.fromisoformat(str(partition_date))
            # Remove the temporary partition column
            clean_df = group_df.drop("_partition_date")
            groups[py_date] = clean_df
    else:
        # No datetime column; use provided as_of_date
        if as_of_date is None:
            raise ValueError("DataFrame has no datetime column; provide as_of_date.")
        groups = {as_of_date: df}

    metas: List[FileMetaDict] = []
    batch_count = 0

    for d, g in sorted(groups.items()):
        # path: base_dir/asset=<SYMBOL>/date=YYYY-MM-DD/part-<N>.parquet
        datest = d.isoformat()
        part_dir = base_dir / f"asset={symbol}" / datetime.strftime(datetime(d.year, d.month, d.day), opts.partition_fmt)
        part_dir.mkdir(parents=True, exist_ok=True)

        # Arrow table + Parquet
        table = _df_to_table(g)
        pbytes = _write_parquet_bytes(table, opts.compression, opts.row_group_size)

        # Content addressing at file level: write to temp, hash, rename to sha.parquet
        tmp_path = part_dir / f"part.tmp"
        _atomic_write_bytes(tmp_path, pbytes)
        file_sha = _hash_file(tmp_path)
        final_name = f"{file_sha}.parquet"
        final_path = part_dir / final_name

        # If a file with identical content exists already, drop temp; else atomically publish
        if final_path.exists():
            try:
                os.remove(tmp_path)
            except FileNotFoundError:
                pass
        else:
            os.replace(tmp_path, final_path)

        rows = len(g)
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

        # Update catalog (per date, per filename)
        date_map = s_idx.by_date.get(datest)
        if date_map is None:
            date_map = OOBTree()
            s_idx.by_date[datest] = date_map
        if final_name not in date_map:
            date_map[final_name] = meta  # insert new
        # else already present -> de-dup noop

        metas.append(meta)
        batch_count += 1

        if batch_count % SMALL_TXN_BATCH == 0:
            transaction.commit()
    transaction.commit()
    return metas


def read_timeseries(
    root,
    symbol: str,
    *,
    start: Optional[Union[date, datetime]] = None,
    end: Optional[Union[date, datetime]] = None,
    columns: Optional[List[str]] = None,
    base_dir: Union[str, Path] = "./data/ts",
    return_pandas: bool = True,  # For backward compatibility with existing code
) -> Union[pl.DataFrame, "pd.DataFrame"]:
    """
    Read back timeseries for symbol over [start, end], concatenating Parquet partitions.

    Args:
        return_pandas: If True (default), returns pandas DataFrame for backward compatibility.
                      If False, returns polars DataFrame.
    """
    cat = _ensure_catalog(root)
    symbol = _sanitize_symbol(symbol)
    s_idx = _symbol_index(cat, symbol)

    if start is None and end is None:
        dates = list(s_idx.by_date.keys())
    else:
        s = _to_datestr(start) if start else min(s_idx.by_date.keys(), default=None)
        e = _to_datestr(end) if end else max(s_idx.by_date.keys(), default=None)
        if s is None or e is None:
            if return_pandas:
                import pandas as pd
                return pd.DataFrame()
            return pl.DataFrame()
        dates = [d for d in s_idx.by_date.keys() if s <= d <= e]

    parts: List[pl.DataFrame] = []
    for d in dates:
        date_map = s_idx.by_date.get(d)
        if not date_map:
            continue
        for _, meta in date_map.items():
            p = Path(meta["path"])
            if not p.exists():
                # stale entry – skip; optional: schedule cleanup
                continue
            tbl = pq.read_table(p, columns=columns)
            df = pl.from_arrow(tbl)
            # Note: _index_ts column is kept as a regular column in polars
            # (polars doesn't have an index concept)
            parts.append(df)

    if not parts:
        if return_pandas:
            import pandas as pd
            return pd.DataFrame()
        return pl.DataFrame()
    out = pl.concat(parts)

    # If user provided start/end as datetimes, trim exactly
    # Find the datetime column to filter on
    datetime_col = None
    if "_index_ts" in out.columns:
        datetime_col = "_index_ts"
    elif "timestamp" in out.columns:
        datetime_col = "timestamp"
    else:
        # Find first datetime column
        for col_name in out.columns:
            if out.schema[col_name] in [pl.Datetime, pl.Date]:
                datetime_col = col_name
                break

    if datetime_col and isinstance(start, datetime):
        out = out.filter(pl.col(datetime_col) >= start)
    if datetime_col and isinstance(end, datetime):
        out = out.filter(pl.col(datetime_col) <= end)

    # Sort by datetime column if it exists
    if datetime_col:
        out = out.sort(datetime_col)

    # Convert back to pandas if requested (for backward compatibility)
    if return_pandas:
        import pandas as pd
        pandas_df = out.to_pandas()
        # If _index_ts column exists, set it as the index (restoring pandas convention)
        if "_index_ts" in pandas_df.columns:
            pandas_df.set_index(pd.to_datetime(pandas_df["_index_ts"], utc=False), inplace=True)
            pandas_df.drop(columns=["_index_ts"], inplace=True)
        return pandas_df

    return out


def register_negative_cache(
    root,
    symbol: str,
    miss_date: Union[date, datetime],
    *,
    ttl_seconds: int = 3600,
) -> None:
    """
    Optional negative cache: mark (symbol, date) as a miss with TTL.
    Readers can check and avoid immediate re-fetch loops.
    """
    cat = _ensure_catalog(root)
    symbol = _sanitize_symbol(symbol)
    s_idx = _symbol_index(cat, symbol)
    d = _to_datestr(miss_date)
    date_map = s_idx.by_date.get(d)
    if date_map is None:
        date_map = OOBTree()
        s_idx.by_date[d] = date_map
    date_map["__MISS__"] = {
        "path": "",
        "rows": 0,
        "size": 0,
        "min_ts": "",
        "max_ts": "",
        "sha256": "",
        "miss": "true",
        "expires_at": (datetime.utcnow().timestamp() + ttl_seconds),
    }
    transaction.commit()


def vacuum_catalog(
    root,
    *,
    base_dir: Union[str, Path] = "./data/ts",
    delete_stale_files: bool = False,
) -> int:
    """
    Remove catalog entries pointing to missing files. Optionally delete stray files not indexed.
    Returns number of catalog entries removed.
    """
    cat = _ensure_catalog(root)
    removed = 0
    for shard, shard_map in list(cat.shards.items()):
        for symbol, s_idx in list(shard_map.items()):
            for d, date_map in list(s_idx.by_date.items()):
                to_del = []
                for fname, meta in date_map.items():
                    if fname == "__MISS__":
                        # expire?
                        exp = meta.get("expires_at")
                        if exp and datetime.utcnow().timestamp() > float(exp):
                            to_del.append(fname)
                        continue
                    p = Path(meta["path"])
                    if not p.exists():
                        to_del.append(fname)
                for fname in to_del:
                    del date_map[fname]
                    removed += 1
                if len(date_map) == 0:
                    del s_idx.by_date[d]
    transaction.commit()

    if delete_stale_files:
        # Sweep filesystem for files not referenced by catalog (optional)
        base = Path(base_dir)
        referenced = set()
        for shard_map in cat.shards.values():
            for s_idx in shard_map.values():
                for date_map in s_idx.by_date.values():
                    for meta in date_map.values():
                        if isinstance(meta, dict) and meta.get("path"):
                            referenced.add(Path(meta["path"]).resolve())
        for p in base.rglob("*.parquet"):
            if p.resolve() not in referenced:
                try:
                    p.unlink()
                except Exception:
                    pass
    return removed
