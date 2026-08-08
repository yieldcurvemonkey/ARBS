"""Reading a GLBX MBO file: one cheap catalogue pass, then targeted extraction.

A day of SR3 MBO is ~73 M records but decodes at ~3 M/s vectorised, so a full
pass is seconds, not minutes.  That shapes the design: **scan everything once**
to find out where the activity is, then **extract only the instruments you
care about** to a parquet cache and replay those.

Extraction is deliberately batched.  Pulling one instrument costs a full pass,
so pulling forty costs one full pass too -- ``extract`` takes a *set* of ids and
writes them all in a single sweep.  Asking for them one at a time would be
forty passes.

The cache lives wherever the caller says.  Point it outside the worktree: a
``git worktree remove`` should not be able to destroy half an hour of extracts.
"""
from __future__ import annotations

import dataclasses
import datetime
import os
from typing import Dict, Iterable, Iterator, List, Optional, Sequence

import numpy as np
import pandas as pd

from RVUtils.MBO.symbols import ParsedSymbol, parse_symbol

__all__ = [
    "CHUNK",
    "MboSource",
    "activity_catalogue",
    "instrument_records",
    "scan_activity",
]

CHUNK = 5_000_000

_ACTIONS = ("A", "C", "M", "R", "T", "F")
_UNDEF_PRICE = np.iinfo(np.int64).max
_F_SNAPSHOT = 32
_NS_PER_MIN = 60_000_000_000

#: Columns kept in the per-instrument cache -- everything ``replay_book`` reads.
_KEEP = (
    "instrument_id", "ts_event", "ts_recv", "order_id", "price", "size",
    "flags", "action", "side", "sequence",
)


@dataclasses.dataclass
class MboSource:
    """A DBN MBO file plus its symbology and a parquet cache directory."""

    path: str
    cache_dir: str
    ref_year: Optional[int] = None

    def __post_init__(self) -> None:
        import databento as db

        self._db = db
        self._store = db.DBNStore.from_file(self.path)
        md = self._store.metadata
        self.dataset: str = str(md.dataset)
        self.schema: str = str(md.schema)
        self.session_start: pd.Timestamp = pd.to_datetime(md.start, utc=True)
        self.session_end: pd.Timestamp = pd.to_datetime(md.end, utc=True)
        if self.ref_year is None:
            self.ref_year = int(self.session_start.year)

        self.id_to_symbol: Dict[int, str] = {}
        for sym, entries in md.mappings.items():
            for e in entries:
                if e["symbol"]:
                    self.id_to_symbol[int(e["symbol"])] = sym
        self.symbol_to_id: Dict[str, int] = {v: k for k, v in self.id_to_symbol.items()}
        self.parsed: Dict[str, ParsedSymbol] = {
            s: parse_symbol(s, self.ref_year) for s in self.id_to_symbol.values()
        }
        os.makedirs(self.cache_dir, exist_ok=True)

    # -- plumbing ---------------------------------------------------------- #

    def chunks(self, count: int = CHUNK) -> Iterator[np.ndarray]:
        """Stream the whole file as structured-array chunks (fresh decoder each call)."""
        store = self._db.DBNStore.from_file(self.path)
        return iter(store.to_ndarray(count=count))

    def _cache_path(self, name: str) -> str:
        return os.path.join(self.cache_dir, name)

    def _instrument_path(self, instrument_id: int) -> str:
        return self._cache_path(f"inst_{int(instrument_id)}.parquet")

    # -- catalogue --------------------------------------------------------- #

    def scan(self, force: bool = False) -> "ActivityScan":
        return scan_activity(self, force=force)

    def catalogue(self, force: bool = False) -> pd.DataFrame:
        return activity_catalogue(self, force=force)

    # -- extraction -------------------------------------------------------- #

    def extract(self, instrument_ids: Iterable[int], force: bool = False) -> List[int]:
        """Write one parquet per instrument, in a single pass over the file.

        Rows are appended as row groups per chunk rather than accumulated, so
        peak memory is one chunk regardless of how many instruments are asked
        for: the busiest outright alone is 15 M records.

        Returns the ids that were actually written.  Already-cached ids are
        skipped, so calling this repeatedly from a notebook is free.
        """
        import pyarrow.parquet as pq

        want = sorted({int(i) for i in instrument_ids})
        todo = [i for i in want if force or not os.path.exists(self._instrument_path(i))]
        if not todo:
            return []

        wanted = np.array(todo, dtype=np.int64)
        tmp = {i: self._instrument_path(i) + ".part" for i in todo}
        writers: Dict[int, "pq.ParquetWriter"] = {}
        try:
            for arr in self.chunks():
                iid = arr["instrument_id"].astype(np.int64)
                hit = np.isin(iid, wanted)
                if not hit.any():
                    continue
                sub = arr[hit]
                sid = sub["instrument_id"].astype(np.int64)
                order = np.argsort(sid, kind="stable")
                sub, sid = sub[order], sid[order]
                lo = np.searchsorted(sid, wanted, side="left")
                hi = np.searchsorted(sid, wanted, side="right")
                for k, i in enumerate(todo):
                    if hi[k] <= lo[k]:
                        continue
                    tbl = _records_table(sub[lo[k]:hi[k]])
                    w = writers.get(i)
                    if w is None:
                        w = pq.ParquetWriter(tmp[i], tbl.schema, compression="zstd")
                        writers[i] = w
                    w.write_table(tbl)
            for i in todo:
                w = writers.get(i)
                if w is None:                       # instrument never printed
                    _records_table(np.empty(0, dtype=_EMPTY_DTYPE))
                    writers[i] = pq.ParquetWriter(
                        tmp[i], _records_table(np.empty(0, dtype=_EMPTY_DTYPE)).schema,
                        compression="zstd",
                    )
        finally:
            for w in writers.values():
                w.close()

        for i in todo:
            os.replace(tmp[i], self._instrument_path(i))
        return todo

    def records(self, instrument: int | str, force: bool = False) -> np.ndarray:
        """Records for one instrument, extracting on demand."""
        iid = self.symbol_to_id[instrument] if isinstance(instrument, str) else int(instrument)
        self.extract([iid], force=force)
        return instrument_records(self._instrument_path(iid))

    def symbol(self, instrument_id: int) -> str:
        return self.id_to_symbol.get(int(instrument_id), f"?{instrument_id}")


@dataclasses.dataclass
class ActivityScan:
    """One full pass, cached: per-instrument counts plus a minute-of-day grid."""

    per_instrument: pd.DataFrame
    minute_msgs: np.ndarray          # (n_instruments, 1440)
    minute_trades: np.ndarray
    minute_volume: np.ndarray
    instrument_ids: np.ndarray       # row order of the minute grids
    total_records: int

    def minute_frame(self, which: str = "msgs") -> pd.DataFrame:
        grid = {"msgs": self.minute_msgs, "trades": self.minute_trades,
                "volume": self.minute_volume}[which]
        return pd.DataFrame(grid.T, columns=self.instrument_ids,
                            index=pd.RangeIndex(1440, name="minute_utc"))


#: The structured dtype ``replay_book`` reads -- and what a cached instrument
#: round-trips back into.  Deliberately a subset of the DBN record: dropping
#: length/rtype/publisher/channel/ts_in_delta costs nothing and the parquet is
#: what sits on disk for a working day of extracts.
_EMPTY_DTYPE = np.dtype(
    [
        ("instrument_id", "u4"), ("ts_event", "u8"), ("ts_recv", "u8"),
        ("order_id", "u8"), ("price", "i8"), ("size", "u4"), ("flags", "u1"),
        ("action", "S1"), ("side", "S1"), ("sequence", "u4"),
    ]
)


def _records_table(rec: np.ndarray):
    import pyarrow as pa

    cols = {}
    for name in _KEEP:
        v = rec[name]
        cols[name] = pa.array(np.char.decode(v, "ascii")) if v.dtype.kind == "S" else pa.array(v)
    return pa.table(cols)


def instrument_records(path: str) -> np.ndarray:
    """Read a cached instrument back into the structured array ``replay_book`` wants."""
    df = pd.read_parquet(path)
    out = np.zeros(len(df), dtype=_EMPTY_DTYPE)
    for name in _EMPTY_DTYPE.names:
        v = df[name].to_numpy()
        out[name] = np.char.encode(v.astype("U1"), "ascii") if _EMPTY_DTYPE[name].kind == "S" else v
    return out


def scan_activity(src: MboSource, force: bool = False) -> ActivityScan:
    """Single vectorised pass: what is on this file and when was it busy.

    Snapshot records are excluded from the timestamp and minute-grid statistics.
    Their ``ts_recv`` is stamped at the session boundary for every instrument at
    once, which would otherwise put a spike in the first minute of the day and
    make every instrument look like it started trading at midnight.
    """
    inst_path = src._cache_path("activity_instruments.parquet")
    grid_path = src._cache_path("activity_minutes.npz")
    if not force and os.path.exists(inst_path) and os.path.exists(grid_path):
        per = pd.read_parquet(inst_path)
        z = np.load(grid_path)
        return ActivityScan(
            per_instrument=per, minute_msgs=z["msgs"], minute_trades=z["trades"],
            minute_volume=z["volume"], instrument_ids=z["ids"],
            total_records=int(z["total"][0]),
        )

    day0 = int(src.session_start.value)
    acc: Dict[str, Dict[int, int]] = {}
    grids: Dict[int, np.ndarray] = {}
    total = 0

    def _add(field: str, ids: np.ndarray, vals: np.ndarray) -> None:
        d = acc.setdefault(field, {})
        for u, v in zip(ids.tolist(), vals.tolist()):
            d[u] = d.get(u, 0) + v

    for arr in src.chunks():
        total += arr.shape[0]
        iid = arr["instrument_id"].astype(np.int64)
        act = np.ascontiguousarray(arr["action"]).view(np.uint8)
        ts = arr["ts_recv"].astype(np.int64)
        sz = arr["size"].astype(np.int64)
        px = arr["price"].astype(np.int64)
        snap = (arr["flags"].astype(np.int64) & _F_SNAPSHOT) != 0
        live_px = px != _UNDEF_PRICE
        minute = np.clip((ts - day0) // _NS_PER_MIN, 0, 1439)
        is_trade = act == ord("T")

        # One factorisation, then bincounts.  Masking per instrument instead
        # would be O(instruments x chunk) -- 443 x 5 M, which does not finish.
        uniq, inv = np.unique(iid, return_inverse=True)
        n_u = uniq.size
        _add("n_msgs", uniq, np.bincount(inv, minlength=n_u))
        _add("n_snapshot", uniq, np.bincount(inv[snap], minlength=n_u))
        for a in _ACTIONS:
            _add(f"n_{a}", uniq, np.bincount(inv[act == ord(a)], minlength=n_u))
        _add("n_trades", uniq, np.bincount(inv[is_trade], minlength=n_u))
        _add("trade_volume", uniq,
             np.bincount(inv[is_trade], weights=sz[is_trade], minlength=n_u).astype(np.int64))

        big = np.iinfo(np.int64).max
        lo = np.full(n_u, big, dtype=np.int64)
        hi = np.zeros(n_u, dtype=np.int64)
        pmin = np.full(n_u, big, dtype=np.int64)
        pmax = np.full(n_u, -big, dtype=np.int64)
        live = ~snap
        np.minimum.at(lo, inv[live], ts[live])
        np.maximum.at(hi, inv[live], ts[live])
        np.minimum.at(pmin, inv[live_px], px[live_px])
        np.maximum.at(pmax, inv[live_px], px[live_px])
        d_lo = acc.setdefault("first_ts", {})
        d_hi = acc.setdefault("last_ts", {})
        d_pl = acc.setdefault("px_min", {})
        d_ph = acc.setdefault("px_max", {})
        for k, u in enumerate(uniq.tolist()):
            if lo[k] != big:
                d_lo[u] = min(d_lo.get(u, big), int(lo[k]))
                d_hi[u] = max(d_hi.get(u, 0), int(hi[k]))
            if pmin[k] != big:
                d_pl[u] = min(d_pl.get(u, big), int(pmin[k]))
                d_ph[u] = max(d_ph.get(u, -big), int(pmax[k]))

        # (instrument, minute) histograms via a flattened bincount
        for row, mask, wts in ((0, live, None), (1, is_trade, None), (2, is_trade, sz)):
            if not mask.any():
                continue
            flat = inv[mask] * 1440 + minute[mask]
            w = None if wts is None else wts[mask].astype(np.float64)
            h = np.bincount(flat, weights=w, minlength=n_u * 1440).astype(np.int64)
            h = h.reshape(n_u, 1440)
            nz = np.flatnonzero(h.any(axis=1))
            for k in nz.tolist():
                g = grids.setdefault(int(uniq[k]), np.zeros((3, 1440), dtype=np.int64))
                g[row] += h[k]

    counts = (["n_msgs", "n_snapshot", "n_trades", "trade_volume"]
              + [f"n_{a}" for a in _ACTIONS] + ["first_ts", "last_ts"])
    rows = []
    for u in sorted(acc["n_msgs"]):
        row = {"instrument_id": u, "symbol": src.symbol(u)}
        for f in counts:
            row[f] = acc.get(f, {}).get(u, 0)
        # Missing must be None, not 0: a calendar spread legitimately prints at
        # 0.000, and a zero sentinel would erase its real price range.
        row["px_min"] = acc.get("px_min", {}).get(u)
        row["px_max"] = acc.get("px_max", {}).get(u)
        rows.append(row)
    per = pd.DataFrame(rows).sort_values("n_msgs", ascending=False).reset_index(drop=True)
    per["px_min"] = per["px_min"].astype("float64") / 1e9
    per["px_max"] = per["px_max"].astype("float64") / 1e9

    ids = per["instrument_id"].to_numpy()
    zero = np.zeros((3, 1440), dtype=np.int64)
    msgs = np.stack([grids.get(int(i), zero)[0] for i in ids])
    trades = np.stack([grids.get(int(i), zero)[1] for i in ids])
    volume = np.stack([grids.get(int(i), zero)[2] for i in ids])

    per.to_parquet(inst_path, index=False)
    np.savez_compressed(grid_path, msgs=msgs, trades=trades, volume=volume,
                        ids=ids, total=np.array([total]))
    return ActivityScan(per, msgs, trades, volume, ids, total)


def activity_catalogue(src: MboSource, force: bool = False) -> pd.DataFrame:
    """The scan joined to parsed symbology -- the notebook's instrument index."""
    scan = scan_activity(src, force=force)
    per = scan.per_instrument.copy()

    p = per["symbol"].map(lambda s: src.parsed.get(s) or parse_symbol(s, src.ref_year))
    per["kind"] = [x.kind for x in p]
    per["label"] = [x.label for x in p]
    per["n_legs"] = [x.n_legs for x in p]
    per["n_contracts"] = [x.n_contracts for x in p]
    per["legs"] = [",".join(x.legs) for x in p]
    per["weights"] = [",".join(str(w) for w in x.weights) for x in p]
    per["front_month"] = [x.front_month for x in p]
    per["span_months"] = [x.span_months() for x in p]

    per["first_ts"] = pd.to_datetime(per["first_ts"], utc=True)
    per["last_ts"] = pd.to_datetime(per["last_ts"], utc=True)
    per["msgs_per_trade"] = per["n_msgs"] / per["n_trades"].replace(0, np.nan)
    per["avg_trade_size"] = per["trade_volume"] / per["n_trades"].replace(0, np.nan)
    return per
