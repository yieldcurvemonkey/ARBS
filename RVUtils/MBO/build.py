"""Build the event store from the archives, resumably, one session per unit.

Invoke with the environment's interpreter **directly**::

    C:/Users/chris/anaconda3/envs/stir/python.exe -m RVUtils.MBO.build \\
        --products SR3,ZT,ZF,ZN,TN,ZB,UB --dates 2026-05-07:2026-08-06 \\
        --workers auto --disk-budget-gb 250

Never through ``conda run``.  Parallel ``conda run`` invocations collide on a
temporary file and return empty output with exit status 0, which reads as a pass.

**Memory is the binding constraint, not CPU.**  One SR3 session is 72.9 M records
and about 4 GB held whole; the host has 32 cores and could not run 32 of those.
``--workers auto`` therefore derives concurrency from measured session size rather
than from core count.  Within a session, records are accumulated per instrument
and concatenated one instrument at a time, so peak memory is the session plus its
largest single instrument rather than twice the session.

**The disk budget is enforced before the build starts**, from measured bytes per
record, and again as it runs.  Running out of disk nine hours into a build is the
failure this exists to prevent.

A session that raises is recorded as FAILED and the build continues.  One bad
session must not cost the other five hundred and fifty-two.
"""
from __future__ import annotations

import argparse
import datetime
import os
import shutil
import sys
import time
import traceback
from concurrent.futures import ProcessPoolExecutor, as_completed
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

import numpy as np
import pandas as pd

from RVUtils.MBO.archive import MboArchive, session_key
from RVUtils.MBO.book import build_price_grid, replay_book
from RVUtils.MBO.products import root_of
from RVUtils.MBO.store import manifest as mf
from RVUtils.MBO.store.schema import store_root
from RVUtils.MBO.store.writer import StoreWriter
from RVUtils.MBO.symbols import parse_symbol

__all__ = [
    "build_session",
    "estimate_bytes",
    "main",
    "plan",
    "workers_for",
]

#: Fraction of free memory a build may commit to in-flight sessions.
_RAM_FRACTION = 0.6
#: Records decoded per chunk.  Smaller chunks trade a little throughput for a
#: lower peak, and peak is what fails a build: four consecutive SR3 sessions died
#: of MemoryError at five million.
DEFAULT_CHUNK = 2_000_000
#: Bytes of store written per source record.  **Measured on the pilot**, not
#: estimated: 7.8 to 9.1 across the six Treasury roots on 2026-07-14, and 13.0
#: for SR3, whose messages are far more likely to change the touch (75.5 M
#: top-of-book states from 81.0 M records, against ZN's 4.0 M from 7.1 M).
#:
#: The default is the SR3 figure rather than the mean, because this number feeds
#: a *guard*: over-estimating costs a needlessly cautious refusal, and
#: under-estimating fills the drive nine hours in.  The first guess here was 0.9,
#: which is fourteen times optimistic and would have waved through a build that
#: could not fit.  The manifest carries what each session actually cost.
DEFAULT_BYTES_PER_RECORD = 13.0


def workers_for(session_gb: float, free_ram_gb: float,
                cap: Optional[int] = None) -> int:
    """How many sessions may be in flight at once.

    Derived from session size, not core count: one SR3 session held whole is
    about 4 GB, so a 32-core host can run six of them and not thirty-two.
    """
    if cap is None:
        cap = max(1, (os.cpu_count() or 4) - 2)
    if session_gb <= 0:
        return int(cap)
    by_ram = int((_RAM_FRACTION * free_ram_gb) // session_gb)
    return int(max(1, min(cap, by_ram)))


def plan(root: str, archive: MboArchive, products: Optional[Sequence[str]] = None,
         dates: Optional[Tuple[datetime.date, datetime.date]] = None,
         kinds: Sequence[str] = ("tob", "trades", "catalog"),
         engine_version: str = mf.ENGINE_VERSION,
         tier: str = "wide") -> pd.DataFrame:
    """Sessions still to build, after archive filtering and manifest resume."""
    s = archive.sessions()
    if s.empty:
        return s
    if products:
        s = s[s["product"].isin(list(products))]
    if dates:
        lo, hi = dates
        s = s[(s["date"] >= lo) & (s["date"] <= hi)]
    return mf.pending(root, s.reset_index(drop=True), kinds=kinds,
                      engine_version=engine_version, tier=tier)


def estimate_bytes(pending: pd.DataFrame,
                   bytes_per_record: float = DEFAULT_BYTES_PER_RECORD,
                   records_per_byte_of_source: float = 0.065) -> float:
    """Projected store bytes for a plan.

    ``records_per_byte_of_source`` converts compressed source bytes into records:
    measured at about 0.065 (7.08 M records from a 108 MB member).  Crude, and
    that is the point -- it is a pre-flight guard, not an accounting.
    """
    if pending.empty:
        return 0.0
    est_records = pending["member_bytes"].to_numpy(dtype=float) * records_per_byte_of_source
    return float(est_records.sum() * bytes_per_record)


def build_session(root: str, archive_roots: Sequence[str], product: str,
                  date: datetime.date, engine_version: str = mf.ENGINE_VERSION,
                  tier: str = "wide", min_records: int = 1,
                  keep_scratch: bool = False,
                  chunk: int = DEFAULT_CHUNK) -> Dict[str, object]:
    """Replay one session into the store and return its manifest rows.

    Runs in a worker process, so it takes only picklable arguments and builds its
    own archive index.
    """
    import databento as db

    t0 = time.perf_counter()
    archive = MboArchive(list(archive_roots))
    s = archive.sessions()
    hit = s[(s["product"] == product) & (s["date"] == date)]
    src = hit.iloc[0] if not hit.empty else None

    row = {
        "product": product, "date": date, "tier": tier,
        "engine_version": engine_version,
        "source_zip": None if src is None else str(src["zip_path"]),
        "source_member": None if src is None else str(src["member"]),
        "source_bytes": None if src is None else int(src["member_bytes"]),
        "status": "OK", "error": "",
    }

    writer: Optional[StoreWriter] = None
    try:
        with archive.open_session(product, date, keep=keep_scratch) as path:
            store = db.DBNStore.from_file(path)
            md = store.metadata
            dbn_version = int(getattr(md, "version", 0) or 0)
            ref_year = int(pd.to_datetime(md.start, utc=True).year)
            id_to_symbol = {}
            for sym, entries in md.mappings.items():
                for e in entries:
                    if e["symbol"]:
                        id_to_symbol[int(e["symbol"])] = sym

            parts: Dict[int, List[np.ndarray]] = {}
            n_records = 0
            for arr in store.to_ndarray(count=chunk):
                n_records += arr.shape[0]
                # Sort once and slice, rather than masking per instrument.  The
                # obvious ``arr[iid == u]`` in a loop allocates a full-length
                # boolean per unique instrument per chunk: on SR3, 443 active
                # instruments times a five-million-row chunk is about 2 GB of
                # transient masks on top of the session itself, and it is what
                # put four consecutive SR3 sessions into MemoryError.  One
                # stable argsort plus searchsorted gives the same partition with
                # a single index array.
                iid = arr["instrument_id"].astype(np.int64)
                order_ix = np.argsort(iid, kind="stable")
                sid = iid[order_ix]
                sub = arr[order_ix]
                del order_ix
                uniq = np.unique(sid)
                lo = np.searchsorted(sid, uniq, side="left")
                hi = np.searchsorted(sid, uniq, side="right")
                for k, u in enumerate(uniq.tolist()):
                    parts.setdefault(int(u), []).append(sub[lo[k]:hi[k]].copy())
                del sub, sid, iid

            writer = StoreWriter(root, product, date, engine_version)
            # Busiest first: the largest instrument dominates peak memory, and
            # releasing it early leaves the most headroom for the rest.
            order = sorted(parts, key=lambda k: -sum(c.size for c in parts[k]))
            for iid in order:
                chunks = parts.pop(iid)
                rec = np.concatenate(chunks)
                del chunks
                if rec.size < min_records:
                    continue
                symbol = id_to_symbol.get(iid, f"?{iid}")
                parsed = parse_symbol(symbol, ref_year)
                grid = build_price_grid(rec["price"].astype(np.int64))
                result = replay_book(rec, grid=grid)
                writer.add(symbol, iid, parsed, result, dbn_version=dbn_version)
                del rec, result

            stats = writer.close()
            writer = None

        wall = time.perf_counter() - t0
        row.update({
            "n_records": int(n_records),
            "n_symbols": int(stats["n_symbols"]),
            "n_rows": int(stats["n_tob"]),
            "bytes_written": int(stats["bytes_written"]),
            "wall_s": float(wall),
            "locked_states": int(stats["locked_states"]),
            "crossed_states": int(stats["crossed_states"]),
            "trades_outside_book": int(stats["trades_outside_book"]),
        })
    except BaseException as exc:  # noqa: BLE001 - one bad session must not stop 552
        if writer is not None:
            writer.abort()
        row.update({
            "status": "FAILED",
            "error": f"{type(exc).__name__}: {exc}\n{traceback.format_exc(limit=3)}",
            "wall_s": float(time.perf_counter() - t0),
        })

    for kind in ("tob", "trades", "catalog"):
        mf.append(root, {**row, "kind": kind})
    return row


def _free_gb(path: str) -> float:
    os.makedirs(path, exist_ok=True)
    return shutil.disk_usage(path).free / 1e9


def main(argv: Optional[Sequence[str]] = None) -> int:
    p = argparse.ArgumentParser(prog="RVUtils.MBO.build", description=__doc__)
    p.add_argument("--root", default=None, help="store root (else ARBS_MBO_STORE)")
    p.add_argument("--archive-roots", default=None,
                   help="comma-separated archive directories")
    p.add_argument("--products", default=None, help="comma-separated product roots")
    p.add_argument("--dates", default=None, help="YYYY-MM-DD:YYYY-MM-DD, inclusive")
    p.add_argument("--tier", default="wide", choices=("wide", "deep"))
    p.add_argument("--workers", default="auto")
    p.add_argument("--disk-budget-gb", type=float, default=250.0)
    p.add_argument("--bytes-per-record", type=float, default=DEFAULT_BYTES_PER_RECORD)
    p.add_argument("--chunk", type=int, default=DEFAULT_CHUNK,
                   help="records decoded per chunk; lower it if memory is tight")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--force", action="store_true",
                   help="rebuild sessions the manifest already calls complete")
    a = p.parse_args(list(argv) if argv is not None else None)

    root = store_root(a.root)
    archive_roots = a.archive_roots.split(",") if a.archive_roots else None
    archive = MboArchive(archive_roots)
    products = a.products.split(",") if a.products else None
    dates = None
    if a.dates:
        lo, hi = a.dates.split(":")
        dates = (pd.Timestamp(lo).date(), pd.Timestamp(hi).date())

    todo = (archive.sessions() if a.force else
            plan(root, archive, products, dates, tier=a.tier))
    if a.force:
        if products:
            todo = todo[todo["product"].isin(products)]
        if dates:
            todo = todo[(todo["date"] >= dates[0]) & (todo["date"] <= dates[1])]
        todo = todo.reset_index(drop=True)

    if todo.empty:
        print("nothing to build")
        return 0

    projected = estimate_bytes(todo, a.bytes_per_record)
    free = _free_gb(root)
    print(f"{len(todo)} session(s); projected {projected / 1e9:,.1f} GB, "
          f"budget {a.disk_budget_gb:,.1f} GB, free {free:,.1f} GB")
    if projected / 1e9 > a.disk_budget_gb:
        raise RuntimeError(
            f"disk budget exceeded before starting: projected "
            f"{projected / 1e9:,.1f} GB against a budget of {a.disk_budget_gb:,.1f} GB. "
            f"Narrow --products/--dates or raise --disk-budget-gb deliberately."
        )
    if projected / 1e9 > free * 0.9:
        raise RuntimeError(
            f"projected {projected / 1e9:,.1f} GB against {free:,.1f} GB free on "
            f"{root}; refusing to start a build that would fill the drive"
        )
    if a.dry_run:
        print(todo.to_string(index=False))
        return 0

    biggest_gb = float(todo["member_bytes"].max()) * 4.0 / 1e9    # ~4x decoded
    workers = (workers_for(biggest_gb, free_ram_gb=_ram_gb())
               if a.workers == "auto" else int(a.workers))
    print(f"workers={workers} (largest session ~{biggest_gb:.1f} GB decoded)")

    ok = failed = 0
    t0 = time.perf_counter()
    with ProcessPoolExecutor(max_workers=workers) as ex:
        futs = {
            ex.submit(build_session, root, archive.roots, r["product"], r["date"],
                      mf.ENGINE_VERSION, a.tier, 1, False, a.chunk):
                (r["product"], r["date"])
            for _, r in todo.iterrows()
        }
        for i, fut in enumerate(as_completed(futs), 1):
            product, date = futs[fut]
            try:
                row = fut.result()
            except BaseException as exc:  # noqa: BLE001
                failed += 1
                print(f"[{i}/{len(futs)}] {session_key(product, date)} POOL-FAILED {exc}")
                continue
            if row["status"] == "OK":
                ok += 1
                print(f"[{i}/{len(futs)}] {session_key(product, date)} "
                      f"{row['n_records']:,} rec -> {row['n_rows']:,} tob, "
                      f"{row['bytes_written'] / 1e6:,.0f} MB, {row['wall_s']:.1f}s")
            else:
                failed += 1
                print(f"[{i}/{len(futs)}] {session_key(product, date)} FAILED: "
                      f"{str(row['error'])[:200]}")

    print(f"\n{ok} built, {failed} failed, {time.perf_counter() - t0:,.0f}s total")
    return 1 if failed else 0


def _ram_gb() -> float:
    try:
        import psutil

        return psutil.virtual_memory().available / 1e9
    except Exception:  # noqa: BLE001 - psutil is optional
        return 32.0


if __name__ == "__main__":
    sys.exit(main())
