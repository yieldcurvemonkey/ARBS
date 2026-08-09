"""Column definitions for the event store, in one place.

Two decisions are encoded here and both are worth stating, because neither is the
obvious choice.

**Prices are integer tick indices, and the reason is exactness rather than size.**
Measured on real ZN instrument-days, tick indices cost 12.9 bytes per row against
13.9 for float64 -- a 7% saving that would not justify the indirection on its own.
What justifies it is that SR3's 0.005 tick is not representable in binary floating
point, so on floats the question "is this market one tick wide" has to be asked
with a tolerance (``isclose(spread, tick, atol=tick*0.01)``, which is what the
first pass over this data had to do) and on tick indices it is an integer
comparison that is either true or false.  The grid needed to decode an index lives
in the catalogue, one row per symbol per session.

**A trade carries the book that prevailed before it.**  The alternative is to keep
a record index on the top-of-book table and join at read time.  Storing the book
on the trade drops eight bytes per row from the largest table in the store, turns
effective spread into a column subtraction, and -- the real reason -- removes the
join entirely.  Every record inside a packet shares a timestamp, so an as-of join
on time can pick up the book the trade itself created, and that mistake is silent.
"""
from __future__ import annotations

import datetime
import os
from typing import Union

import pyarrow as pa

__all__ = [
    "CATALOG_SCHEMA",
    "KINDS",
    "RISK_SCHEMA",
    "TOB_SCHEMA",
    "TRADES_SCHEMA",
    "store_path",
    "store_root",
]

#: ``symbol`` is dictionary-encoded: one row group holds one symbol, so the
#: column costs a few bytes per group rather than per row.
_SYMBOL = pa.dictionary(pa.int32(), pa.string())

TOB_SCHEMA = pa.schema([
    pa.field("symbol", _SYMBOL, nullable=False),
    pa.field("ts_recv", pa.int64(), nullable=False),
    pa.field("ts_event", pa.int64(), nullable=False),
    pa.field("sequence", pa.uint32(), nullable=False),
    # -1 means that side of the book was empty.
    pa.field("bid_idx", pa.int32(), nullable=False),
    pa.field("bid_sz", pa.int32(), nullable=False),
    # int32 rather than int16: an order count at the touch is small in every
    # instrument seen so far, but a silent overflow would be indistinguishable
    # from a thin book, and two bytes that compress away is a cheap insurance.
    pa.field("bid_ct", pa.int32(), nullable=False),
    pa.field("ask_idx", pa.int32(), nullable=False),
    pa.field("ask_sz", pa.int32(), nullable=False),
    pa.field("ask_ct", pa.int32(), nullable=False),
])

TRADES_SCHEMA = pa.schema([
    pa.field("symbol", _SYMBOL, nullable=False),
    pa.field("ts_recv", pa.int64(), nullable=False),
    pa.field("ts_event", pa.int64(), nullable=False),
    pa.field("sequence", pa.uint32(), nullable=False),
    pa.field("order_id", pa.uint64(), nullable=False),
    pa.field("price_idx", pa.int32(), nullable=False),
    pa.field("size", pa.int32(), nullable=False),
    #: +1 buy-initiated, -1 sell-initiated, 0 unknown.  MBO carries the true
    #: aggressor side, so no Lee-Ready or tick-rule proxy is needed and their
    #: misclassification error is simply absent.
    pa.field("aggressor", pa.int8(), nullable=False),
    # The book strictly before this trade's packet.  -1 = that side was empty.
    pa.field("prev_bid_idx", pa.int32(), nullable=False),
    pa.field("prev_bid_sz", pa.int32(), nullable=False),
    pa.field("prev_ask_idx", pa.int32(), nullable=False),
    pa.field("prev_ask_sz", pa.int32(), nullable=False),
])

CATALOG_SCHEMA = pa.schema([
    pa.field("symbol", pa.string(), nullable=False),
    pa.field("instrument_id", pa.uint32(), nullable=False),
    pa.field("root", pa.string(), nullable=False),
    pa.field("kind", pa.string(), nullable=False),
    pa.field("label", pa.string(), nullable=False),
    pa.field("legs", pa.list_(pa.string()), nullable=False),
    pa.field("weights", pa.list_(pa.int16()), nullable=False),
    pa.field("n_legs", pa.int16(), nullable=False),
    pa.field("n_contracts", pa.int16(), nullable=False),
    pa.field("front_month", pa.date32(), nullable=True),
    pa.field("span_months", pa.int32(), nullable=True),
    # The grid: this is what decodes a tick index back to a price.
    pa.field("px_min", pa.int64(), nullable=False),
    pa.field("tick", pa.int64(), nullable=False),
    pa.field("n_slots", pa.int32(), nullable=False),
    pa.field("band_lo", pa.float64(), nullable=False),
    pa.field("band_hi", pa.float64(), nullable=False),
    pa.field("spec_tick", pa.float64(), nullable=True),
    pa.field("usd_per_tick", pa.float64(), nullable=True),
    pa.field("bp_per_unit", pa.float64(), nullable=True),
    # Counts and invariants, recorded rather than only asserted, so that a bad
    # instrument-day is findable with a query instead of only in a lost log.
    pa.field("n_records", pa.int64(), nullable=False),
    pa.field("n_snapshot", pa.int64(), nullable=False),
    pa.field("n_tob", pa.int64(), nullable=False),
    pa.field("n_trades", pa.int64(), nullable=False),
    pa.field("trade_volume", pa.int64(), nullable=False),
    pa.field("n_unindexed", pa.int64(), nullable=False),
    pa.field("n_out_of_band", pa.int64(), nullable=False),
    pa.field("locked_states", pa.int64(), nullable=False),
    pa.field("crossed_states", pa.int64(), nullable=False),
    pa.field("crossed_events", pa.int64(), nullable=False),
    pa.field("trades_outside_book", pa.int64(), nullable=False),
    pa.field("first_ts", pa.int64(), nullable=True),
    pa.field("last_ts", pa.int64(), nullable=True),
])

RISK_SCHEMA = pa.schema([
    pa.field("symbol", pa.string(), nullable=False),
    pa.field("ctd", pa.string(), nullable=True),
    pa.field("conversion_factor", pa.float64(), nullable=True),
    pa.field("dv01_per_contract", pa.float64(), nullable=True),
    pa.field("ctd_dv01", pa.float64(), nullable=True),
    #: "intrinsic" for SR3, a pricer name for a Treasury root, "FAILED" when the
    #: curve build did not succeed.  A failure writes null with this set, never a
    #: zero -- a published all-null risk set that read as a successful run has
    #: cost this repo a day before.
    pa.field("source", pa.string(), nullable=False),
    pa.field("ts_built", pa.int64(), nullable=False),
])

KINDS = ("catalog", "tob", "trades", "risk")

_DEFAULT_ROOT = "D:/mbo_store"


def store_root(root: Union[str, None] = None) -> str:
    """The store root: explicit, else ``ARBS_MBO_STORE``, else ``D:/mbo_store``.

    Never inside a worktree -- a ``git worktree remove`` must not be able to
    destroy a build measured in hours.
    """
    return root or os.environ.get("ARBS_MBO_STORE", _DEFAULT_ROOT)


def store_path(root: str, kind: str, product: str, date: datetime.date) -> str:
    """Path of one ``(kind, product, date)`` file."""
    if kind not in KINDS:
        raise KeyError(f"unknown store kind {kind!r}; expected one of {KINDS}")
    return os.path.join(
        store_root(root), kind, f"product={product}", f"date={date.isoformat()}.parquet"
    )
