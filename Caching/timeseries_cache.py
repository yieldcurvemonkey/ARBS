# Caching/timeseries_cache.py
from __future__ import annotations

import hashlib
import os
import tempfile
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple, Union

import pandas as pd
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
    df: pd.DataFrame,
    *,
    as_of_date: Optional[date] = None,  # if None, will use df index/column
    opts: Optional[WriteOptions] = None,
) -> List[FileMetaDict]:
    """
    Append a DataFrame to partitioned Parquet storage and update the ZODB catalog.
    Partitions by calendar date (derived from datetime index or provided as_of_date).

    Returns a list of FileMetaDict entries created.
    """
    if df is None or len(df) == 0:
        return []

    opts = opts or WriteOptions(base_dir="./data/ts")
    base_dir = Path(opts.base_dir)
    symbol = _sanitize_symbol(symbol)
    cat = _ensure_catalog(root)
    s_idx = _symbol_index(cat, symbol)

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
) -> pd.DataFrame:
    """
    Read back timeseries for symbol over [start, end], concatenating Parquet partitions.
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
            return pd.DataFrame()
        dates = [d for d in s_idx.by_date.keys() if s <= d <= e]

    parts: List[pd.DataFrame] = []
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
            df = tbl.to_pandas()
            if "_index_ts" in df.columns:
                df.set_index(pd.to_datetime(df["_index_ts"], utc=False), inplace=True)
                df.drop(columns=["_index_ts"], inplace=True)
            parts.append(df)

    if not parts:
        return pd.DataFrame()
    out = pd.concat(parts, axis=0)
    # If user provided start/end as datetimes, trim exactly
    if isinstance(start, datetime):
        out = out[out.index >= pd.Timestamp(start)]
    if isinstance(end, datetime):
        out = out[out.index <= pd.Timestamp(end)]
    return out.sort_index()


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
