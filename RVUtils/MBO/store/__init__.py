"""The event store: replayed books on disk, in a shape analytics can read cheaply.

Layout, one file per ``(product, date, kind)`` with one row group per symbol::

    <root>/_manifest/            append-only build log
    <root>/catalog/product=P/date=D.parquet
    <root>/tob/product=P/date=D.parquet
    <root>/trades/product=P/date=D.parquet
    <root>/risk/product=P/date=D.parquet

One file per session rather than one per instrument: SR3 alone would otherwise
produce about 190,000 small files.  Row groups come out in symbol order because
the replay loop produces them that way, so a single-symbol read across a quarter
is one file open per session with row-group pruning, and no global sort is ever
needed.

Nothing under ``analytics/`` opens a DBN file.  That separation is what makes a
study cheap to re-run and what lets the later phases be built independently.
"""
from __future__ import annotations

from RVUtils.MBO.store.schema import (
    CATALOG_SCHEMA,
    RISK_SCHEMA,
    TOB_SCHEMA,
    TRADES_SCHEMA,
    store_path,
)

__all__ = [
    "CATALOG_SCHEMA",
    "RISK_SCHEMA",
    "TOB_SCHEMA",
    "TRADES_SCHEMA",
    "store_path",
]
