"""Multi-level order-flow imbalance, computed inside a book replay.

Touch order-flow imbalance answers "what happened at the best quote".  On these
contracts that turns out to be the wrong question at short horizons.  Measured on
the store: ZT's touch OFI correlates **negatively** with the same-second mid change
(-0.107), and only becomes informative at a minute (0.410) and five minutes
(0.581).  ZT has the finest tick of the complex and the deepest touch, 3,086 lots,
so its front queue churns enormously without the price moving and the touch tells
you almost nothing about where it is going.

Xu, Gould and Howison's multi-level OFI keeps the per-level contributions as a
**vector** rather than summing them, and their headline is that deeper levels buy
a 65 to 75 per cent out-of-sample error reduction for **large-tick** instruments
against 15 to 30 per cent for small-tick ones.  Every contract here is large-tick
-- the spread is one tick almost always -- and both of the degeneracies that cap
the small-tick case require a spread wider than one tick, so they cannot occur.
This is the regime where the deeper book should help most.

The per-level definitions, reproduced from arXiv:1907.06230v2 rather than
re-derived, with ``b^m``/``a^m`` the level-m bid/ask price and ``r^m``/``q^m`` the
size resting there, measured immediately after each book change::

    dW^m = r^m(n)                if b^m(n) > b^m(n-1)
         = r^m(n) - r^m(n-1)     if b^m(n) = b^m(n-1)
         = -r^m(n-1)             if b^m(n) < b^m(n-1)

    dV^m = -q^m(n-1)             if a^m(n) > a^m(n-1)
         = q^m(n) - q^m(n-1)     if a^m(n) = a^m(n-1)
         = q^m(n)                if a^m(n) < a^m(n-1)

    e^m  = dW^m - dV^m

Two things about this that are easy to get wrong and are the reason the code
follows the paper literally:

* **Only populated levels count.**  Level 2 is the next price at which something
  actually rests, not the next tick.  Counting empty ticks as levels would make
  ``e^m`` respond to the tick grid rather than to the book.
* **One event can move several components at once.**  The paper is explicit: if an
  arrival changes the level-1 bid price, then ``b^2``, ``b^3`` and the rest all
  change too, because the levels are defined by rank and the whole ladder shifts.
  The components are therefore strongly correlated by construction, which is why
  the regression that consumes them needs Ridge and not OLS.

At ``M = 1`` this is identical to Cont-Kukanov-Stoikov, and a test asserts it.
"""
from __future__ import annotations

import dataclasses
from typing import Optional

import numpy as np
import pandas as pd
from numba import njit

from RVUtils.MBO.book import (
    F_LAST,
    F_SNAPSHOT,
    PRICE_SCALE,
    PriceGrid,
    build_price_grid,
)

__all__ = ["MlofiResult", "replay_mlofi"]

UNDEF_PRICE = np.iinfo(np.int64).max
_A, _C, _M, _R = (ord(x) for x in "ACMR")
_BID, _ASK = ord("B"), ord("A")


@dataclasses.dataclass
class MlofiResult:
    """Per-event multi-level order-flow imbalance, with the mid beside it."""

    frame: pd.DataFrame
    grid: PriceGrid
    levels: int
    n_records: int = 0

    @property
    def e_columns(self):
        return [c for c in self.frame.columns if c.startswith("e_")]


@njit(cache=True, nogil=True)
def _mlofi(action, side, price_idx, size, ord_idx, n_orders, flags,
           ts_recv, n_slots, levels,
           out_ts, out_bidx, out_aidx, out_e):
    """Replay the ladder and emit the level vector at each packet boundary.

    The book maintenance is the same contract the top-of-book kernel uses: state
    mutates on A/C/M/R only, and a state is only meaningful at an F_LAST boundary,
    because between the records of one packet the book is momentarily torn.
    """
    ord_gen = np.zeros(n_orders, dtype=np.int64)
    ord_side = np.zeros(n_orders, dtype=np.int64)
    ord_pidx = np.zeros(n_orders, dtype=np.int64)
    ord_size = np.zeros(n_orders, dtype=np.int64)
    cur_gen = 1

    bid_sz = np.zeros(n_slots, dtype=np.int64)
    ask_sz = np.zeros(n_slots, dtype=np.int64)

    # Previous populated levels: price index and size, per side.
    pb_idx = np.full(levels, -1, dtype=np.int64)
    pb_sz = np.zeros(levels, dtype=np.int64)
    pa_idx = np.full(levels, -1, dtype=np.int64)
    pa_sz = np.zeros(levels, dtype=np.int64)
    cb_idx = np.full(levels, -1, dtype=np.int64)
    cb_sz = np.zeros(levels, dtype=np.int64)
    ca_idx = np.full(levels, -1, dtype=np.int64)
    ca_sz = np.zeros(levels, dtype=np.int64)

    best_b = -1
    best_a = n_slots
    n = action.shape[0]
    out_n = 0
    have_prev = False
    in_snapshot = True

    for i in range(n):
        f = flags[i]
        is_snap = (f & F_SNAPSHOT) != 0
        if not is_snap and in_snapshot:
            in_snapshot = False

        a = action[i]
        o = ord_idx[i]

        if a == _R:
            for k in range(n_slots):
                bid_sz[k] = 0
                ask_sz[k] = 0
            cur_gen += 1
            best_b = -1
            best_a = n_slots
            have_prev = False

        elif a == _A:
            pidx = price_idx[i]
            sz = size[i]
            if pidx >= 0 and sz > 0:
                sd = side[i]
                if sd == _BID:
                    bid_sz[pidx] += sz
                    if pidx > best_b:
                        best_b = pidx
                    ord_gen[o] = cur_gen
                    ord_side[o] = 1
                    ord_pidx[o] = pidx
                    ord_size[o] = sz
                elif sd == _ASK:
                    ask_sz[pidx] += sz
                    if pidx < best_a:
                        best_a = pidx
                    ord_gen[o] = cur_gen
                    ord_side[o] = 2
                    ord_pidx[o] = pidx
                    ord_size[o] = sz

        elif a == _C:
            if ord_gen[o] == cur_gen:
                sd = ord_side[o]
                pidx = ord_pidx[o]
                held = ord_size[o]
                rm = size[i]
                if rm > held or rm <= 0:
                    rm = held
                if sd == 1:
                    bid_sz[pidx] -= rm
                else:
                    ask_sz[pidx] -= rm
                if held - rm <= 0:
                    ord_gen[o] = 0
                else:
                    ord_size[o] = held - rm

        elif a == _M:
            if ord_gen[o] == cur_gen:
                sd0 = ord_side[o]
                pidx0 = ord_pidx[o]
                held0 = ord_size[o]
                if sd0 == 1:
                    bid_sz[pidx0] -= held0
                else:
                    ask_sz[pidx0] -= held0
                ord_gen[o] = 0
            pidx = price_idx[i]
            sz = size[i]
            if pidx >= 0 and sz > 0:
                sd = side[i]
                if sd == _BID:
                    bid_sz[pidx] += sz
                    if pidx > best_b:
                        best_b = pidx
                    ord_gen[o] = cur_gen
                    ord_side[o] = 1
                    ord_pidx[o] = pidx
                    ord_size[o] = sz
                elif sd == _ASK:
                    ask_sz[pidx] += sz
                    if pidx < best_a:
                        best_a = pidx
                    ord_gen[o] = cur_gen
                    ord_side[o] = 2
                    ord_pidx[o] = pidx
                    ord_size[o] = sz

        if (f & F_LAST) == 0 or is_snap:
            continue

        while best_b >= 0 and bid_sz[best_b] == 0:
            best_b -= 1
        while best_a < n_slots and ask_sz[best_a] == 0:
            best_a += 1

        # Walk down the POPULATED levels: level m is the m-th price at which
        # something rests, not the m-th tick.
        k = best_b
        for lv in range(levels):
            while k >= 0 and bid_sz[k] == 0:
                k -= 1
            if k < 0:
                cb_idx[lv] = -1
                cb_sz[lv] = 0
            else:
                cb_idx[lv] = k
                cb_sz[lv] = bid_sz[k]
                k -= 1
        k = best_a
        for lv in range(levels):
            while k < n_slots and ask_sz[k] == 0:
                k += 1
            if k >= n_slots:
                ca_idx[lv] = -1
                ca_sz[lv] = 0
            else:
                ca_idx[lv] = k
                ca_sz[lv] = ask_sz[k]
                k += 1

        if have_prev:
            for lv in range(levels):
                # dW on the bid: a higher price index is a better bid.
                bi, bp = cb_idx[lv], pb_idx[lv]
                if bi < 0 and bp < 0:
                    dW = 0
                elif bp < 0:
                    dW = cb_sz[lv]
                elif bi < 0:
                    dW = -pb_sz[lv]
                elif bi > bp:
                    dW = cb_sz[lv]
                elif bi == bp:
                    dW = cb_sz[lv] - pb_sz[lv]
                else:
                    dW = -pb_sz[lv]

                # dV on the ask: a LOWER price index is a better ask, so the
                # inequalities invert relative to the bid.
                ai, ap = ca_idx[lv], pa_idx[lv]
                if ai < 0 and ap < 0:
                    dV = 0
                elif ap < 0:
                    dV = ca_sz[lv]
                elif ai < 0:
                    dV = -pa_sz[lv]
                elif ai > ap:
                    dV = -pa_sz[lv]
                elif ai == ap:
                    dV = ca_sz[lv] - pa_sz[lv]
                else:
                    dV = ca_sz[lv]

                out_e[out_n, lv] = dW - dV

            out_ts[out_n] = ts_recv[i]
            out_bidx[out_n] = cb_idx[0]
            out_aidx[out_n] = ca_idx[0]
            out_n += 1

        for lv in range(levels):
            pb_idx[lv] = cb_idx[lv]
            pb_sz[lv] = cb_sz[lv]
            pa_idx[lv] = ca_idx[lv]
            pa_sz[lv] = ca_sz[lv]
        have_prev = True

    return out_n


def replay_mlofi(records: np.ndarray, grid: Optional[PriceGrid] = None,
                 levels: int = 10) -> MlofiResult:
    """Replay one instrument's records into a per-event multi-level OFI vector.

    ``records`` must be one instrument's records in file order, the same input
    :func:`RVUtils.MBO.book.replay_book` takes.

    Returns a frame with ``ts_recv``, ``bid_px``, ``ask_px``, ``mid`` and
    ``e_1 .. e_M``.  ``e_1`` is the Cont-Kukanov-Stoikov touch imbalance.
    """
    if records.size == 0:
        raise ValueError("no records to replay")
    if np.unique(records["instrument_id"]).size != 1:
        raise ValueError("replay_mlofi expects exactly one instrument_id")
    levels = max(1, int(levels))

    price = records["price"].astype(np.int64)
    g = grid if grid is not None else build_price_grid(price)

    px_idx = np.full(price.shape, -1, dtype=np.int64)
    live = price != UNDEF_PRICE
    off = price[live] - g.px_min
    ok = (off >= 0) & (off % g.tick == 0) & (off // g.tick < g.n_slots)
    tmp = np.full(off.shape, -1, dtype=np.int64)
    tmp[ok] = off[ok] // g.tick
    px_idx[live] = tmp

    action = np.ascontiguousarray(records["action"]).view(np.uint8).astype(np.int64)
    side = np.ascontiguousarray(records["side"]).view(np.uint8).astype(np.int64)
    size = records["size"].astype(np.int64)
    order_id = records["order_id"].astype(np.uint64)
    _, ord_idx = np.unique(order_id, return_inverse=True)
    ord_idx = ord_idx.astype(np.int64)
    n_orders = int(ord_idx.max()) + 1 if ord_idx.size else 1
    flags = records["flags"].astype(np.int64)
    ts_recv = records["ts_recv"].astype(np.int64)

    cap = int(((flags & F_LAST) != 0).sum()) + 1
    out_ts = np.zeros(cap, dtype=np.int64)
    out_bidx = np.full(cap, -1, dtype=np.int64)
    out_aidx = np.full(cap, -1, dtype=np.int64)
    out_e = np.zeros((cap, levels), dtype=np.int64)

    n_out = _mlofi(action, side, px_idx, size, ord_idx, n_orders, flags,
                   ts_recv, g.n_slots, levels, out_ts, out_bidx, out_aidx, out_e)

    s = slice(0, n_out)
    cols = {
        "ts_recv": pd.to_datetime(out_ts[s], utc=True),
        "bid_px": g.to_price(out_bidx[s]),
        "ask_px": g.to_price(out_aidx[s]),
    }
    for lv in range(levels):
        cols[f"e_{lv + 1}"] = out_e[s, lv].astype(np.int64)
    df = pd.DataFrame(cols)
    df["mid"] = (df["bid_px"] + df["ask_px"]) / 2.0
    return MlofiResult(frame=df, grid=g, levels=levels, n_records=int(records.size))
