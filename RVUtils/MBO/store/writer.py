"""Replay results -> parquet, one row group per symbol, atomically per session.

The writer is the only place that turns a :class:`~RVUtils.MBO.book.ReplayResult`
into stored columns, so it is also the place that enforces two properties the
whole store depends on:

* **Tick indices decode back to exactly the price that was replayed.**  The
  conversion is checked, not trusted -- a float round-trip that is off by one
  unit in the last place would put a quote on the wrong rung of the ladder and
  nothing downstream would notice.
* **A session appears complete only when it is complete.**  All three files are
  written to ``.part`` names and moved into place together at the end, so a build
  killed halfway leaves nothing that resume would mistake for a finished session.
"""
from __future__ import annotations

import contextlib
import datetime
import os
from typing import Dict, List, Optional

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

from RVUtils.MBO.book import PRICE_SCALE, PriceGrid, ReplayResult
from RVUtils.MBO.products import PRODUCTS
from RVUtils.MBO.store.schema import (
    CATALOG_SCHEMA,
    TOB_SCHEMA,
    TRADES_SCHEMA,
    store_path,
)
from RVUtils.MBO.symbols import ParsedSymbol

__all__ = ["StoreWriter", "store_path", "to_tick_index"]

_EMPTY = -1


def to_tick_index(price: np.ndarray, grid: PriceGrid) -> np.ndarray:
    """Float prices -> tick indices, with the round-trip checked rather than assumed.

    ``PriceGrid.to_price`` produces ``(px_min + idx * tick) / 1e9`` in float64.
    At these magnitudes the inverse is exact, but "is exact" is a property of the
    magnitudes involved, and a store built on a silently-off-by-one index would
    misprice every spread by a tick.  So the reconstruction is verified.
    """
    px = np.asarray(price, dtype=np.float64)
    out = np.full(px.shape, _EMPTY, dtype=np.int64)
    live = np.isfinite(px)
    if not live.any():
        return out.astype(np.int32)

    scaled = np.rint(px[live] * PRICE_SCALE).astype(np.int64)
    off = scaled - grid.px_min
    idx = off // grid.tick
    bad = (off % grid.tick != 0) | (idx < 0) | (idx >= grid.n_slots)
    if bad.any():
        j = int(np.flatnonzero(bad)[0])
        raise ValueError(
            f"price {px[live][j]:.12g} does not sit on the ladder "
            f"(px_min={grid.px_min}, tick={grid.tick}, n_slots={grid.n_slots}); "
            f"the tick-index round-trip is not exact for this instrument"
        )
    out[live] = idx
    return out.astype(np.int32)


def _prevailing_book(trades: pd.DataFrame, tob: pd.DataFrame,
                     grid: PriceGrid) -> Dict[str, np.ndarray]:
    """The book strictly before each trade's packet, joined on record index.

    Record index, not timestamp: every record inside a packet shares a timestamp,
    so an as-of join on time would sometimes pick up the book the trade itself
    created.  ``allow_exact_matches=False`` is what makes it *strictly* before.
    """
    n = len(trades)
    empty = np.full(n, _EMPTY, dtype=np.int32)
    zero = np.zeros(n, dtype=np.int32)
    if n == 0 or tob.empty:
        return {"prev_bid_idx": empty, "prev_bid_sz": zero,
                "prev_ask_idx": empty, "prev_ask_sz": zero}

    left = trades[["rec_idx"]].reset_index(drop=True)
    right = tob[["rec_idx", "bid_px", "bid_sz", "ask_px", "ask_sz"]]
    m = pd.merge_asof(
        left.sort_values("rec_idx"),
        right.sort_values("rec_idx"),
        on="rec_idx", direction="backward", allow_exact_matches=False,
    )
    return {
        "prev_bid_idx": to_tick_index(m["bid_px"].to_numpy(), grid),
        "prev_bid_sz": np.nan_to_num(m["bid_sz"].to_numpy(), nan=0).astype(np.int32),
        "prev_ask_idx": to_tick_index(m["ask_px"].to_numpy(), grid),
        "prev_ask_sz": np.nan_to_num(m["ask_sz"].to_numpy(), nan=0).astype(np.int32),
    }


def _trades_outside_book(trades: pd.DataFrame, prev: Dict[str, np.ndarray],
                         grid: PriceGrid) -> int:
    """Trades printed beyond the prevailing quote.

    Not a defect on its own: a spread order executing against the outright book
    via implied matching prints at a price that book never displayed, and the
    previous work measured 0.041% of trades doing exactly that, only on outrights
    and bundles.  Recorded so the rate can be watched rather than assumed.
    """
    if trades.empty:
        return 0
    px = to_tick_index(trades["price"].to_numpy(), grid).astype(np.int64)
    b, a = prev["prev_bid_idx"].astype(np.int64), prev["prev_ask_idx"].astype(np.int64)
    below = (b >= 0) & (px < b)
    above = (a >= 0) & (px > a)
    return int(np.count_nonzero(below | above))


class StoreWriter:
    """Accumulates one session's instruments and lands them atomically."""

    def __init__(self, root: str, product: str, date: datetime.date,
                 engine_version: str) -> None:
        self.root = root
        self.product = product
        self.date = date
        self.engine_version = engine_version
        self._paths = {
            k: store_path(root, k, product, date) for k in ("tob", "trades", "catalog")
        }
        for p in self._paths.values():
            os.makedirs(os.path.dirname(p), exist_ok=True)
        self._tmp = {k: f"{v}.{os.getpid()}.part" for k, v in self._paths.items()}
        self._w: Dict[str, pq.ParquetWriter] = {}
        self._catalog: List[dict] = []
        self.n_symbols = 0
        self.n_tob = 0
        self.n_trades = 0
        self._closed = False

    # -- writing ----------------------------------------------------------- #

    def _writer(self, kind: str, schema: pa.Schema) -> pq.ParquetWriter:
        w = self._w.get(kind)
        if w is None:
            w = pq.ParquetWriter(
                self._tmp[kind], schema, compression="zstd", compression_level=9,
                version="2.6", write_statistics=True,
            )
            self._w[kind] = w
        return w

    def add(self, symbol: str, instrument_id: int, parsed: ParsedSymbol,
            result: ReplayResult, dbn_version: Optional[int] = None) -> None:
        """Append one instrument as a row group in each table."""
        if self._closed:
            raise RuntimeError("writer is closed")
        g = result.grid
        tob, trades = result.tob, result.trades

        sym_arr = pa.DictionaryArray.from_arrays(
            pa.array(np.zeros(len(tob), dtype=np.int32)), pa.array([symbol])
        )
        self._writer("tob", TOB_SCHEMA).write_table(pa.table({
            "symbol": sym_arr,
            "ts_recv": pa.array(tob["ts_recv"].astype("int64").to_numpy()),
            "ts_event": pa.array(tob["ts_event"].astype("int64").to_numpy()),
            "sequence": pa.array(tob["sequence"].to_numpy().astype(np.uint32)),
            "bid_idx": pa.array(to_tick_index(tob["bid_px"].to_numpy(), g)),
            "bid_sz": pa.array(tob["bid_sz"].to_numpy().astype(np.int32)),
            "bid_ct": pa.array(tob["bid_ct"].to_numpy().astype(np.int32)),
            "ask_idx": pa.array(to_tick_index(tob["ask_px"].to_numpy(), g)),
            "ask_sz": pa.array(tob["ask_sz"].to_numpy().astype(np.int32)),
            "ask_ct": pa.array(tob["ask_ct"].to_numpy().astype(np.int32)),
        }, schema=TOB_SCHEMA))

        prev = _prevailing_book(trades, tob, g)
        agg = trades["aggressor"].to_numpy() if len(trades) else np.array([], dtype=object)
        aggressor = np.where(agg == "B", 1, np.where(agg == "A", -1, 0)).astype(np.int8)
        tsym = pa.DictionaryArray.from_arrays(
            pa.array(np.zeros(len(trades), dtype=np.int32)), pa.array([symbol])
        )
        self._writer("trades", TRADES_SCHEMA).write_table(pa.table({
            "symbol": tsym,
            "ts_recv": pa.array(trades["ts_recv"].astype("int64").to_numpy()),
            "ts_event": pa.array(trades["ts_event"].astype("int64").to_numpy()),
            "sequence": pa.array(trades["sequence"].to_numpy().astype(np.uint32)),
            "order_id": pa.array(trades["order_id"].to_numpy().astype(np.uint64)),
            "price_idx": pa.array(to_tick_index(trades["price"].to_numpy(), g)),
            "size": pa.array(trades["size"].to_numpy().astype(np.int32)),
            "aggressor": pa.array(aggressor),
            **{k: pa.array(v) for k, v in prev.items()},
        }, schema=TRADES_SCHEMA))

        spec = PRODUCTS.get(parsed.root)
        first_ts = int(tob["ts_recv"].iloc[0].value) if len(tob) else None
        last_ts = int(tob["ts_recv"].iloc[-1].value) if len(tob) else None
        self._catalog.append({
            "symbol": symbol,
            "instrument_id": int(instrument_id),
            "root": parsed.root,
            "kind": parsed.kind,
            "label": parsed.label,
            "legs": list(parsed.legs),
            "weights": [int(w) for w in parsed.weights],
            "n_legs": int(parsed.n_legs),
            "n_contracts": int(parsed.n_contracts),
            "front_month": parsed.front_month,
            "span_months": parsed.span_months(),
            "px_min": int(g.px_min),
            "tick": int(g.tick),
            "n_slots": int(g.n_slots),
            "band_lo": float(result.band[0]),
            "band_hi": float(result.band[1]),
            "spec_tick": float(spec.tick_for(parsed.kind)) if spec else None,
            "usd_per_tick": float(spec.usd_per_tick) if spec else None,
            "bp_per_unit": float(result.bp_per_unit),
            "n_records": int(result.n_records),
            "n_snapshot": int(result.n_snapshot),
            "n_tob": int(len(tob)),
            "n_trades": int(len(trades)),
            "trade_volume": int(trades["size"].sum()) if len(trades) else 0,
            "n_unindexed": int(result.n_unindexed),
            "n_out_of_band": int(result.n_out_of_band),
            "locked_states": int(result.locked_states),
            "crossed_states": int(result.crossed_states),
            "crossed_events": int(result.crossed_events),
            "trades_outside_book": _trades_outside_book(trades, prev, g),
            "first_ts": first_ts,
            "last_ts": last_ts,
            "dbn_version": None if dbn_version is None else int(dbn_version),
            "n_action_none": int(result.n_action_none),
            # A session with no 'N' records is only *old* normalization if it had
            # events at all; a silent instrument proves nothing either way, so it
            # is labelled unknown rather than guessed.
            "normalization": (
                "new" if result.n_action_none > 0
                else ("old" if result.n_records > 1000 else "unknown")
            ),
        })
        self.n_symbols += 1
        self.n_tob += len(tob)
        self.n_trades += len(trades)

    # -- landing ----------------------------------------------------------- #

    def close(self) -> dict:
        """Close the writers and move all three files into place together."""
        if self._closed:
            raise RuntimeError("writer is closed")
        self._closed = True

        cat = pd.DataFrame(self._catalog)
        if cat.empty:
            cat = pd.DataFrame({f.name: pd.Series(dtype="object")
                                for f in CATALOG_SCHEMA})
        self._writer("catalog", CATALOG_SCHEMA).write_table(
            pa.Table.from_pandas(cat, schema=CATALOG_SCHEMA, preserve_index=False)
        )
        for kind in ("tob", "trades"):
            if kind not in self._w:
                schema = TOB_SCHEMA if kind == "tob" else TRADES_SCHEMA
                self._writer(kind, schema).write_table(schema.empty_table())

        bytes_written = 0
        for w in self._w.values():
            w.close()
        for kind, tmp in self._tmp.items():
            if os.path.exists(tmp):
                bytes_written += os.path.getsize(tmp)
                os.replace(tmp, self._paths[kind])

        return {
            "n_symbols": self.n_symbols,
            "n_tob": self.n_tob,
            "n_trades": self.n_trades,
            "bytes_written": bytes_written,
            "crossed_states": int(cat["crossed_states"].sum()) if len(cat) else 0,
            "locked_states": int(cat["locked_states"].sum()) if len(cat) else 0,
            "trades_outside_book": (
                int(cat["trades_outside_book"].sum()) if len(cat) else 0
            ),
        }

    def abort(self) -> None:
        """Drop the partial files, leaving nothing resume could mistake for done."""
        self._closed = True
        for w in self._w.values():
            with contextlib.suppress(Exception):
                w.close()
        for tmp in self._tmp.values():
            with contextlib.suppress(OSError):
                os.remove(tmp)

    def __enter__(self) -> "StoreWriter":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        if exc_type is not None:
            self.abort()
        elif not self._closed:
            self.close()
