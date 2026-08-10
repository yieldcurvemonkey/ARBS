"""Reading the store back, with tick indices decoded to prices.

Every read goes through the catalogue, because the catalogue holds the grid and
the grid is what turns a tick index into a price.  That indirection is the cost
of storing indices; it buys exactness, and it is paid once per session rather
than once per row.

Reads are pushed down: ``symbol`` is a dictionary column with statistics per row
group, and the store writes one row group per symbol, so asking for one
instrument across a quarter decompresses one instrument's worth of data.
"""
from __future__ import annotations

import datetime
import os
from typing import Dict, Iterable, List, Optional, Sequence, Union

import numpy as np
import pandas as pd
import pyarrow.dataset as ds
import pyarrow.parquet as pq

from RVUtils.MBO.book import PRICE_SCALE
from RVUtils.MBO.products import root_of
from RVUtils.MBO.store.schema import store_path, store_root

__all__ = [
    "available_dates",
    "grids_for",
    "read_catalog",
    "read_tob",
    "read_trades",
    "symbols_by_product",
]

DateLike = Union[datetime.date, str, pd.Timestamp]


def _as_date(d: DateLike) -> datetime.date:
    if isinstance(d, datetime.date) and not isinstance(d, datetime.datetime):
        return d
    return pd.Timestamp(d).date()


def available_dates(root: Optional[str], kind: str, product: str) -> List[datetime.date]:
    """Sessions of ``product`` present in the store for ``kind``."""
    d = os.path.join(store_root(root), kind, f"product={product}")
    if not os.path.isdir(d):
        return []
    out = []
    for fn in sorted(os.listdir(d)):
        if fn.startswith("date=") and fn.endswith(".parquet"):
            out.append(_as_date(fn[len("date="):-len(".parquet")]))
    return out


def symbols_by_product(symbols: Sequence[str]) -> Dict[str, List[str]]:
    """Group symbols by the product whose files hold them."""
    out: Dict[str, List[str]] = {}
    for s in symbols:
        r = root_of(s)
        if r is None:
            raise KeyError(f"cannot tell which product {s!r} belongs to")
        out.setdefault(r, []).append(s)
    return out


def _read_one(root: Optional[str], kind: str, product: str, date: datetime.date,
              symbols: Optional[Sequence[str]]) -> pd.DataFrame:
    path = store_path(store_root(root), kind, product, date)
    if not os.path.exists(path):
        return pd.DataFrame()
    dataset = ds.dataset(path, format="parquet")
    flt = None
    if symbols is not None:
        flt = ds.field("symbol").isin(list(symbols))
    tbl = dataset.to_table(filter=flt)
    df = tbl.to_pandas()
    if not df.empty:
        df["symbol"] = df["symbol"].astype(str)
    return df


def read_catalog(root: Optional[str], product: str, dates: Iterable[DateLike],
                 symbols: Optional[Sequence[str]] = None) -> pd.DataFrame:
    """Catalogue rows for a product over some sessions, with a ``date`` column."""
    frames = []
    for d in dates:
        dd = _as_date(d)
        df = _read_one(root, "catalog", product, dd, None)
        if df.empty:
            continue
        if symbols is not None:
            df = df[df["symbol"].isin(list(symbols))]
        df = df.copy()
        df["date"] = dd
        frames.append(df)
    if not frames:
        return pd.DataFrame()
    return pd.concat(frames, ignore_index=True)


def grids_for(root: Optional[str], product: str, dates: Iterable[DateLike],
              symbols: Optional[Sequence[str]] = None) -> pd.DataFrame:
    """``(date, symbol) -> px_min, tick`` -- what decodes a tick index."""
    cat = read_catalog(root, product, dates, symbols)
    if cat.empty:
        return pd.DataFrame(columns=["date", "symbol", "px_min", "tick", "kind"])
    return cat[["date", "symbol", "px_min", "tick", "n_slots", "kind"]].copy()


def _decode(df: pd.DataFrame, grids: pd.DataFrame, cols: Sequence[str]) -> pd.DataFrame:
    """Turn ``*_idx`` columns into prices using each session's own grid."""
    if df.empty:
        return df
    m = df.merge(grids[["date", "symbol", "px_min", "tick"]], on=["date", "symbol"],
                 how="left", validate="many_to_one")
    missing = m["tick"].isna()
    if missing.any():
        bad = m.loc[missing, ["date", "symbol"]].drop_duplicates()
        raise KeyError(
            "no catalogue row for "
            f"{bad.to_dict('records')[:5]}; the grid is required to decode tick "
            "indices and guessing one would silently shift every price"
        )
    px_min = m["px_min"].to_numpy(dtype=np.int64)
    tick = m["tick"].to_numpy(dtype=np.int64)
    for c in cols:
        idx = m[c].to_numpy(dtype=np.int64)
        px = np.where(idx >= 0, (px_min + idx * tick) / PRICE_SCALE, np.nan)
        m[c.replace("_idx", "_px")] = px
    return m


def read_tob(root: Optional[str], product: str, dates: Iterable[DateLike],
             symbols: Optional[Sequence[str]] = None,
             decode: bool = True) -> pd.DataFrame:
    """Top-of-book events, one row per touch change.

    With ``decode`` the frame carries ``bid_px``/``ask_px``/``mid``/``spread`` in
    the instrument's own price units; without it, raw tick indices.
    """
    frames = []
    for d in dates:
        dd = _as_date(d)
        df = _read_one(root, "tob", product, dd, symbols)
        if df.empty:
            continue
        df["date"] = dd
        frames.append(df)
    if not frames:
        return pd.DataFrame()
    out = pd.concat(frames, ignore_index=True)
    out["ts_recv"] = pd.to_datetime(out["ts_recv"], utc=True)
    out["ts_event"] = pd.to_datetime(out["ts_event"], utc=True)
    if not decode:
        return out

    grids = grids_for(root, product, dates, symbols)
    out = _decode(out, grids, ["bid_idx", "ask_idx"])
    out["mid"] = (out["bid_px"] + out["ask_px"]) / 2.0
    out["spread"] = out["ask_px"] - out["bid_px"]
    return out


def read_trades(root: Optional[str], product: str, dates: Iterable[DateLike],
                symbols: Optional[Sequence[str]] = None,
                decode: bool = True) -> pd.DataFrame:
    """The trade tape, each print carrying the book that prevailed before it."""
    frames = []
    for d in dates:
        dd = _as_date(d)
        df = _read_one(root, "trades", product, dd, symbols)
        if df.empty:
            continue
        df["date"] = dd
        frames.append(df)
    if not frames:
        return pd.DataFrame()
    out = pd.concat(frames, ignore_index=True)
    out["ts_recv"] = pd.to_datetime(out["ts_recv"], utc=True)
    out["ts_event"] = pd.to_datetime(out["ts_event"], utc=True)
    if not decode:
        return out

    grids = grids_for(root, product, dates, symbols)
    out = _decode(out, grids,
                  ["price_idx", "prev_bid_idx", "prev_ask_idx"])
    out = out.rename(columns={"price_px": "price"})
    out["prev_mid"] = (out["prev_bid_px"] + out["prev_ask_px"]) / 2.0
    return out
