"""
Full Limit Order Book reconstruction from snapshots and deltas.

Implements the snapshot-anchored windowing algorithm from:
    Marriott (2026), "Reconstructing Full Limit Order Books for
    Kalshi from WebSocket Streams", Section 4.

Algorithm:
    RECONSTRUCT(m, snapshots, deltas):
        Sort snapshots by timestamp
        For each window [S_i, S_{i+1}):
            book <- PARSE_SNAPSHOT(S_i)
            EMIT(book, ts(S_i))
            For each group of deltas at the same timestamp:
                For each delta d in group:
                    new = max(0, book[d.side][d.price] + d.delta)
                    If new == 0: REMOVE book[d.side][d.price]
                    Else: book[d.side][d.price] = new
                EMIT(book, timestamp)

Output schema:
    market_ticker, ts, side, price, qty
"""
from __future__ import annotations

import datetime
import logging
from collections import defaultdict
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

from OBI.kalshi_lob.storage import LOBStorage

logger = logging.getLogger(__name__)

Book = Dict[str, Dict[float, float]]  # side -> {price: qty}


def parse_snapshot(snapshot_rows: pd.DataFrame) -> Book:
    """Parse snapshot rows into a book dict.

    snapshot_rows: DataFrame with columns [side, price, qty]
    """
    book: Book = {"yes": {}, "no": {}}
    for _, row in snapshot_rows.iterrows():
        side = row["side"]
        price = round(float(row["price"]), 3)
        qty = float(row["qty"])
        if qty > 0:
            book[side][price] = qty
    return book


def apply_delta(book: Book, side: str, price: float, delta: float) -> Book:
    """Apply a single delta to the book state.

    Formula (2) from the paper:
        B_{t+1}(s, p) = max(0, B_t(s, p) + delta_{t+1}(s, p))
    """
    price = round(price, 3)
    old = book[side].get(price, 0.0)
    new = max(0.0, old + delta)
    if new == 0.0:
        book[side].pop(price, None)
    else:
        book[side][price] = new
    return book


def emit_book(
    book: Book,
    market_ticker: str,
    ts: Any,
) -> List[dict]:
    """Emit the current book state as a list of (ticker, ts, side, price, qty) rows.

    One row per active price level — matches the paper's output schema.
    """
    rows = []
    for side in ("yes", "no"):
        for price, qty in sorted(book[side].items()):
            rows.append({
                "market_ticker": market_ticker,
                "ts": ts,
                "side": side,
                "price": price,
                "qty": qty,
            })
    return rows


def reconstruct_market(
    market_ticker: str,
    snapshots_df: pd.DataFrame,
    deltas_df: pd.DataFrame,
    emit_every_delta: bool = True,
) -> List[dict]:
    """Reconstruct full LOB history for one market using snapshot-anchored windowing.

    Parameters
    ----------
    market_ticker : str
    snapshots_df : DataFrame with [ts, side, price, qty] for this market
    deltas_df : DataFrame with [ts, side, price, delta] for this market
    emit_every_delta : if True, emit book state after every delta group (full LOB)
                       if False, emit only at snapshot boundaries (lighter output)

    Returns
    -------
    List of LOB rows: [{market_ticker, ts, side, price, qty}, ...]
    """
    if snapshots_df.empty:
        logger.warning(f"No snapshots for {market_ticker}, cannot reconstruct")
        return []

    snap_times = snapshots_df["ts"].drop_duplicates().sort_values().tolist()
    all_rows: List[dict] = []

    for i, snap_ts in enumerate(snap_times):
        snap_data = snapshots_df[snapshots_df["ts"] == snap_ts]
        book = parse_snapshot(snap_data)

        all_rows.extend(emit_book(book, market_ticker, snap_ts))

        if deltas_df.empty or "ts" not in deltas_df.columns:
            continue

        if i + 1 < len(snap_times):
            window_end = snap_times[i + 1]
        else:
            window_end = deltas_df["ts"].max()

        window_deltas = deltas_df[
            (deltas_df["ts"] > snap_ts) & (deltas_df["ts"] <= window_end)
        ].sort_values("ts")

        if window_deltas.empty:
            continue

        grouped = window_deltas.groupby("ts")
        for delta_ts, group in grouped:
            for _, d in group.iterrows():
                book = apply_delta(book, d["side"], d["price"], d["delta"])

            if emit_every_delta:
                all_rows.extend(emit_book(book, market_ticker, delta_ts))

    return all_rows


def reconstruct_date(
    storage: LOBStorage,
    date: datetime.date,
    market_tickers: Optional[List[str]] = None,
    emit_every_delta: bool = True,
    save: bool = True,
) -> pd.DataFrame:
    """Reconstruct LOB for all markets on a given date.

    Reads raw deltas and snapshots from storage, runs reconstruction,
    and optionally saves the result.
    """
    deltas = storage.read_deltas(date)
    snapshots = storage.read_snapshots(date)

    if deltas.empty and snapshots.empty:
        logger.warning(f"No data for {date}")
        return pd.DataFrame()

    if market_tickers is None:
        tickers_d = set(deltas["market_ticker"].unique()) if not deltas.empty else set()
        tickers_s = set(snapshots["market_ticker"].unique()) if not snapshots.empty else set()
        market_tickers = sorted(tickers_d | tickers_s)

    logger.info(f"Reconstructing {len(market_tickers)} markets for {date}")
    all_rows: List[dict] = []

    for ticker in market_tickers:
        snap = snapshots[snapshots["market_ticker"] == ticker] if not snapshots.empty else pd.DataFrame()
        delt = deltas[deltas["market_ticker"] == ticker] if not deltas.empty else pd.DataFrame()

        rows = reconstruct_market(ticker, snap, delt, emit_every_delta=emit_every_delta)
        all_rows.extend(rows)

    if not all_rows:
        return pd.DataFrame()

    result = pd.DataFrame(all_rows)

    if save:
        storage.flush_lob(all_rows, date)

    logger.info(f"Reconstruction complete: {len(result)} LOB rows for {date}")
    return result


def verify_reconstruction(
    book: Book,
    snapshot_df: pd.DataFrame,
) -> Dict[str, Any]:
    """Verify reconstructed book matches a snapshot (Section 3.2 of paper).

    Returns verification results: match counts, mismatches.
    """
    expected = parse_snapshot(snapshot_df)
    mismatches = []
    total_levels = 0

    for side in ("yes", "no"):
        all_prices = set(book[side].keys()) | set(expected[side].keys())
        total_levels += len(all_prices)
        for price in all_prices:
            actual = book[side].get(price, 0.0)
            exp = expected[side].get(price, 0.0)
            if abs(actual - exp) > 0.01:
                mismatches.append({
                    "side": side,
                    "price": price,
                    "reconstructed": actual,
                    "snapshot": exp,
                    "diff": actual - exp,
                })

    return {
        "total_levels": total_levels,
        "mismatches": len(mismatches),
        "match_rate": 1.0 - len(mismatches) / max(total_levels, 1),
        "details": mismatches[:20],
    }
