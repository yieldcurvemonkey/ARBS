"""The build log: what was built, from what, and whether it can be trusted.

Append-only, one small parquet per append.  That is deliberately lock-free: a
process pool writes these concurrently and a single shared file would need
coordination that buys nothing, since the reader reduces the fragments anyway.

**Resume respects the engine version, and that is the point of the version
existing.**  A one-line robustness fix applied part-way through a long backfill
has previously left this repo with two vintages of derived data in one store and
no way to tell them apart afterwards.  Here the vintage is a column, resume only
skips a unit built by the *current* engine, and a bump is therefore a visible,
deliberate re-build rather than an invisible mixture.

Invariant counters are stored, not merely asserted.  A day where the book crossed
inside the session, or where trades printed outside the quote at ten times the
usual rate, is then findable with a query rather than only in a log that has
scrolled away.
"""
from __future__ import annotations

import datetime
import os
import uuid
from typing import Iterable, Optional, Sequence

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

from RVUtils.MBO.store.schema import store_root

__all__ = [
    "ENGINE_VERSION",
    "MANIFEST_SCHEMA",
    "append",
    "is_complete",
    "manifest_dir",
    "pending",
    "read",
]

#: Bump in the same commit as any change to replay or store semantics.  Resume
#: treats a differing version as "not built", so a bump re-builds -- visibly.
ENGINE_VERSION = "1.0.0"

MANIFEST_SCHEMA = pa.schema([
    pa.field("product", pa.string(), nullable=False),
    pa.field("date", pa.date32(), nullable=False),
    pa.field("tier", pa.string(), nullable=False),
    pa.field("kind", pa.string(), nullable=False),
    pa.field("engine_version", pa.string(), nullable=False),
    pa.field("source_zip", pa.string(), nullable=True),
    pa.field("source_member", pa.string(), nullable=True),
    pa.field("source_bytes", pa.int64(), nullable=True),
    pa.field("n_records", pa.int64(), nullable=True),
    pa.field("n_symbols", pa.int64(), nullable=True),
    pa.field("n_rows", pa.int64(), nullable=True),
    pa.field("bytes_written", pa.int64(), nullable=True),
    pa.field("wall_s", pa.float64(), nullable=True),
    pa.field("locked_states", pa.int64(), nullable=True),
    pa.field("crossed_states", pa.int64(), nullable=True),
    pa.field("trades_outside_book", pa.int64(), nullable=True),
    pa.field("status", pa.string(), nullable=False),
    pa.field("error", pa.string(), nullable=True),
    pa.field("ts_built", pa.int64(), nullable=False),
])

_COLS = [f.name for f in MANIFEST_SCHEMA]


def manifest_dir(root: Optional[str] = None) -> str:
    return os.path.join(store_root(root), "_manifest")


def append(root: str, row: dict) -> str:
    """Write one build-log row.  Returns the fragment path."""
    d = manifest_dir(root)
    os.makedirs(d, exist_ok=True)
    full = {c: row.get(c) for c in _COLS}
    if full.get("ts_built") is None:
        full["ts_built"] = int(pd.Timestamp.utcnow().value)
    if isinstance(full.get("date"), pd.Timestamp):
        full["date"] = full["date"].date()
    tbl = pa.Table.from_pylist([full], schema=MANIFEST_SCHEMA)
    # ts_built first so a directory listing sorts chronologically; uuid so two
    # workers finishing in the same nanosecond cannot collide.
    path = os.path.join(d, f"{full['ts_built']:020d}-{uuid.uuid4().hex[:8]}.parquet")
    pq.write_table(tbl, path, compression="zstd")
    return path


def read(root: Optional[str] = None) -> pd.DataFrame:
    """Every build-log row, oldest first.  Empty (typed) frame if none."""
    d = manifest_dir(root)
    if not os.path.isdir(d):
        return pd.DataFrame(columns=_COLS)
    files = sorted(f for f in os.listdir(d) if f.endswith(".parquet"))
    if not files:
        return pd.DataFrame(columns=_COLS)
    frames = [pq.read_table(os.path.join(d, f)).to_pandas() for f in files]
    df = pd.concat(frames, ignore_index=True)
    return df.sort_values("ts_built", kind="stable").reset_index(drop=True)


def latest(root: Optional[str] = None) -> pd.DataFrame:
    """The most recent row for each ``(product, date, tier, kind)``."""
    df = read(root)
    if df.empty:
        return df
    return (
        df.groupby(["product", "date", "tier", "kind"], as_index=False, sort=False)
        .tail(1)
        .reset_index(drop=True)
    )


def is_complete(root: str, product: str, date: datetime.date, kind: str,
                engine_version: str = ENGINE_VERSION, tier: str = "wide") -> bool:
    """Was this unit built successfully, by this engine?"""
    df = latest(root)
    if df.empty:
        return False
    hit = df[
        (df["product"] == product)
        & (df["date"] == date)
        & (df["kind"] == kind)
        & (df["tier"] == tier)
    ]
    if hit.empty:
        return False
    row = hit.iloc[-1]
    return bool(row["status"] == "OK" and row["engine_version"] == engine_version)


def pending(root: str, sessions: pd.DataFrame, kinds: Sequence[str] = ("tob",),
            engine_version: str = ENGINE_VERSION, tier: str = "wide") -> pd.DataFrame:
    """The sessions still to build, for any of ``kinds``."""
    if sessions.empty:
        return sessions
    done = latest(root)
    if done.empty:
        return sessions.reset_index(drop=True)

    ok = done[(done["status"] == "OK")
              & (done["engine_version"] == engine_version)
              & (done["tier"] == tier)]
    complete = None
    for kind in kinds:
        s = set(zip(ok.loc[ok["kind"] == kind, "product"],
                    ok.loc[ok["kind"] == kind, "date"]))
        complete = s if complete is None else (complete & s)
    complete = complete or set()

    mask = [
        (p, d) not in complete
        for p, d in zip(sessions["product"], sessions["date"])
    ]
    return sessions[mask].reset_index(drop=True)
