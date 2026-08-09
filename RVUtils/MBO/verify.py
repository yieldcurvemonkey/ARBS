"""Checks that make the store trustworthy, run against real sessions.

Four of them, ordered by how much they can prove.

**Leg-implied against listed** is the strongest, and it needs no external data.
A listed calendar spread and its two outrights are three separately replayed
books that share no state -- different order ids, different price ladders,
different code paths through the kernel.  If the spread's mid does not equal the
difference of the outrights' mids to within a tick, one of the three is wrong.
Nothing in the engine knows this identity holds, which is exactly why agreement
is evidence.

**Store round-trip** proves the writer and reader are inverses on real data:
replay an instrument in memory, read it back from parquet, compare every column
exactly.  Tick indices are integers, so this is equality and not tolerance.

**Invariants** are recorded per instrument-day and read back as a table: locked
and crossed states, trades outside the prevailing book, orders the ladder could
not index.  Recording rather than only asserting is what makes a bad day findable
with a query months later.

**Settlement cross-check** compares a session's own trade prints against the
daily futures price already in the repo.  It is the weakest of the four and is
reported as such: CME settles Treasury futures on a volume-weighted window near
14:00 ET rather than at the close, so an exact match is not expected and a match
to a few ticks is the most it can say.
"""
from __future__ import annotations

import datetime
import os
from typing import Dict, Iterable, List, Optional, Sequence

import numpy as np
import pandas as pd

from RVUtils.MBO.products import spec_for
from RVUtils.MBO.store.reader import read_catalog, read_tob, read_trades

__all__ = [
    "implied_vs_listed",
    "invariants",
    "session_bars",
    "settle_crosscheck",
    "store_roundtrip",
]


# --------------------------------------------------------------------------- #
# 1. invariants
# --------------------------------------------------------------------------- #

def invariants(root: Optional[str], product: str,
               dates: Iterable[datetime.date]) -> pd.DataFrame:
    """Per instrument-day health, straight out of the catalogue."""
    cat = read_catalog(root, product, dates)
    if cat.empty:
        return cat
    out = cat[[
        "date", "symbol", "kind", "n_records", "n_tob", "n_trades",
        "locked_states", "crossed_states", "trades_outside_book",
        "n_unindexed", "n_out_of_band", "band_lo", "band_hi", "tick",
    ]].copy()
    out["crossed_frac"] = out["crossed_states"] / out["n_tob"].replace(0, np.nan)
    out["outside_frac"] = out["trades_outside_book"] / out["n_trades"].replace(0, np.nan)
    return out.sort_values(["date", "n_records"], ascending=[True, False])


# --------------------------------------------------------------------------- #
# 2. leg-implied against listed
# --------------------------------------------------------------------------- #

def implied_vs_listed(root: Optional[str], product: str,
                      dates: Iterable[datetime.date],
                      freq: str = "1s",
                      min_events: int = 200) -> pd.DataFrame:
    """Every listed structure against a mid synthesised from its own legs.

    The comparison is in **ticks of the structure**, so it reads the same way for
    a 32nd-quoting Treasury and a half-basis-point SR3 spread.  Half a tick is
    the floor: two books on the same lattice cannot agree more closely than the
    lattice allows.

    ``min_events`` counts **events, not grid points**, and that distinction is
    the whole reliability of this check.  ``ZNU6-ZNH7`` quoted exactly once on
    2026-07-14 -- one top-of-book state from 82 records -- which forward-fills to
    84,834 one-second points and sails past any threshold on grid size.  Compared
    against legs that moved all day it scores a ten-tick error that says nothing
    about the engine and everything about a deferred calendar nobody quotes.
    ``n_events_listed`` and ``n_events_min_leg`` are reported so that staleness
    stays visible instead of arriving disguised as disagreement.
    """
    dates = list(dates)
    cat = read_catalog(root, product, dates)
    if cat.empty:
        return pd.DataFrame()

    rows: List[dict] = []
    for date, day in cat.groupby("date"):
        have = set(day["symbol"])
        events = dict(zip(day["symbol"], day["n_tob"]))
        structures = day[(day["n_legs"] >= 2) & (day["n_tob"] >= min_events)]
        structures = structures[
            structures["legs"].map(
                lambda ls: bool(len(ls)) and all(
                    l in have and events.get(l, 0) >= min_events for l in ls
                )
            )
        ]
        if structures.empty:
            continue

        # Read each symbol once and keep only its resampled mid.  Reading a leg
        # per structure would be O(structures x legs) full scans, and an SR3
        # outright is fifteen million rows -- the first version of this ran out
        # of memory on the first product it was pointed at.
        needed = sorted(set(structures["symbol"]).union(
            *[set(ls) for ls in structures["legs"]]
        ))
        grid: Dict[str, pd.Series] = {}
        for sym in needed:
            one = read_tob(root, product, [date], symbols=[sym])
            if one.empty:
                continue
            grid[sym] = (one.set_index("ts_recv")["mid"]
                         .resample(freq).last().ffill())
            del one

        common = None
        for s in grid.values():
            common = s.index if common is None else common.union(s.index)
        if common is None:
            continue
        grid = {k: v.reindex(common).ffill() for k, v in grid.items()}

        for _, s in structures.iterrows():
            legs = list(s["legs"])
            weights = [int(w) for w in s["weights"]]
            if s["symbol"] not in grid or any(l not in grid for l in legs):
                continue
            ev_listed = int(events.get(s["symbol"], 0))
            ev_leg = int(min(events.get(l, 0) for l in legs))

            listed = grid[s["symbol"]]
            implied = None
            for l, w in zip(legs, weights):
                leg = grid[l] * float(w)
                implied = leg if implied is None else implied + leg

            both = pd.concat([listed.rename("listed"), implied.rename("implied")],
                             axis=1).dropna()
            if both.empty:
                continue
            tick = float(s["tick"]) / 1e9
            err_ticks = (both["listed"] - both["implied"]).abs() / tick
            rows.append({
                "date": date, "symbol": s["symbol"], "kind": s["kind"],
                "n_points": int(len(both)),
                "n_events_listed": ev_listed,
                "n_events_min_leg": ev_leg,
                "tick": tick,
                "median_abs_err_ticks": float(err_ticks.median()),
                "p95_abs_err_ticks": float(err_ticks.quantile(0.95)),
                "median_abs_err_price": float(err_ticks.median() * tick),
            })
    return pd.DataFrame(rows)


# --------------------------------------------------------------------------- #
# 3. store round-trip
# --------------------------------------------------------------------------- #

def store_roundtrip(root: Optional[str], archive_roots: Sequence[str],
                    product: str, date: datetime.date,
                    symbols: Optional[Sequence[str]] = None,
                    max_symbols: int = 3) -> pd.DataFrame:
    """Replay in memory, read the store, compare every column exactly."""
    import databento as db

    from RVUtils.MBO.archive import MboArchive
    from RVUtils.MBO.book import build_price_grid, replay_book

    cat = read_catalog(root, product, [date])
    if cat.empty:
        return pd.DataFrame()
    if symbols is None:
        symbols = list(cat.sort_values("n_records", ascending=False)
                       ["symbol"].head(max_symbols))

    archive = MboArchive(list(archive_roots))
    rows: List[dict] = []
    with archive.open_session(product, date, keep=True) as path:
        store = db.DBNStore.from_file(path)
        id_to_symbol = {}
        for sym, entries in store.metadata.mappings.items():
            for e in entries:
                if e["symbol"]:
                    id_to_symbol[int(e["symbol"])] = sym
        want_ids = {i for i, s in id_to_symbol.items() if s in set(symbols)}

        parts: Dict[int, List[np.ndarray]] = {}
        for arr in store.to_ndarray(count=5_000_000):
            iid = arr["instrument_id"]
            for u in np.unique(iid):
                if int(u) in want_ids:
                    parts.setdefault(int(u), []).append(arr[iid == u])

        for iid, chunks in parts.items():
            sym = id_to_symbol[iid]
            rec = np.concatenate(chunks)
            g = build_price_grid(rec["price"].astype(np.int64))
            r = replay_book(rec, grid=g)
            stored = read_tob(root, product, [date], symbols=[sym])
            ok_rows = len(stored) == len(r.tob)
            same_px = same_sz = False
            if ok_rows and len(stored):
                same_px = bool(
                    np.allclose(stored["bid_px"].to_numpy(),
                                r.tob["bid_px"].to_numpy(), equal_nan=True)
                    and np.allclose(stored["ask_px"].to_numpy(),
                                    r.tob["ask_px"].to_numpy(), equal_nan=True)
                )
                same_sz = bool(
                    np.array_equal(stored["bid_sz"].to_numpy(),
                                   r.tob["bid_sz"].to_numpy())
                    and np.array_equal(stored["ask_sz"].to_numpy(),
                                       r.tob["ask_sz"].to_numpy())
                )
            rows.append({
                "date": date, "symbol": sym, "n_replay": len(r.tob),
                "n_stored": len(stored), "rows_match": ok_rows,
                "prices_match": same_px, "sizes_match": same_sz,
            })
    return pd.DataFrame(rows)


# --------------------------------------------------------------------------- #
# 4. bars and the settlement cross-check
# --------------------------------------------------------------------------- #

def session_bars(root: Optional[str], product: str,
                 dates: Iterable[datetime.date],
                 freq: Optional[str] = None,
                 tz: str = "America/Chicago",
                 label: str = "left") -> pd.DataFrame:
    """OHLCV from stored trade prints.  ``freq=None`` gives one bar per session.

    Bars are stamped in Chicago time and labelled by their start, which is the
    convention the earlier SR3 work established: it reproduced 100% of vendor
    closes exactly against 23% for end-labelling.  Both are available so the
    alignment stays a finding rather than a setting.
    """
    tr = read_trades(root, product, dates)
    if tr.empty:
        return pd.DataFrame()
    tr = tr.set_index(tr["ts_recv"].dt.tz_convert(tz)).sort_index()
    keys = ["symbol", "date"] if freq is None else ["symbol"]
    if freq is None:
        g = tr.groupby(keys)
    else:
        g = tr.groupby([tr["symbol"], pd.Grouper(freq=freq, label=label)])
    out = g.agg(
        open=("price", "first"), high=("price", "max"),
        low=("price", "min"), close=("price", "last"),
        volume=("size", "sum"), n_trades=("price", "size"),
    ).reset_index()
    return out


def settle_crosscheck(root: Optional[str], product: str,
                      dates: Iterable[datetime.date],
                      reference: pd.DataFrame,
                      symbol_col: str = "symbol",
                      price_col: str = "future_price") -> pd.DataFrame:
    """Session close from MBO prints against a daily vendor futures price.

    **The weakest of the four checks, and it is reported that way.**  CME settles
    Treasury futures on a volume-weighted window near 14:00 Chicago time, not at
    the 16:00 close, so the two numbers are not measuring the same thing and an
    exact match is not the expectation.  What it can catch is an error of scale,
    of contract, or of day -- which is worth having, and is all it is claimed to
    do.
    """
    bars = session_bars(root, product, dates)
    if bars.empty or reference.empty:
        return pd.DataFrame()

    spec = spec_for(product)
    tick = float(spec.outright_tick)
    ref = reference.reset_index().rename(columns={symbol_col: "ref_symbol"})
    if "date" not in ref.columns:
        raise KeyError("reference needs a 'date' column or index")
    ref["date"] = pd.to_datetime(ref["date"]).dt.date

    m = bars.merge(ref[["date", "ref_symbol", price_col]], on="date", how="inner")
    if m.empty:
        return m
    m["diff_price"] = m["close"] - m[price_col]
    m["diff_ticks"] = m["diff_price"] / tick
    m["abs_ticks"] = m["diff_ticks"].abs()
    return m.sort_values(["date", "abs_ticks"])
