"""Order-level replay: one row per order, with the queue position it joined at.

The top-of-book kernel in :mod:`RVUtils.MBO.book` answers "what was quoted".  This
one answers "what happened to an order" -- how long it rested, where in the queue
it started, whether it was filled or pulled, and how much traded at its price
while it waited.  That table is the substrate for queue analytics, fill
probability, cancel-to-trade ratios, iceberg detection and the fill simulator.

Three things make this tractable, and each of them was a research question:

**Queue rank is O(1), not O(depth).**  Under strict FIFO an order fills *because*
everything ahead of it has cleared, so "size ahead at the moment of the fill" is
approximately zero by construction and tells you nothing.  The informative
quantity is the size ahead **when the order joined the queue**, which is simply
the resting size at that level at that instant.  Fill probability by rank -- the
headline analytic -- needs only that, so no per-level prefix sums, Fenwick trees
or linked lists are required.

**Priority is reconstructed, because the feed does not carry it.**  CME's
MDOrderPriority (tag 37707, lower value = higher priority, meaningful only within
a side-and-price bucket) is deliberately omitted from Databento's normalized MBO
as venue-specific.  So rank comes from arrival order, and the rules for when a
modification forfeits it have to be applied by hand.  The generic CME
"Order Functionalities" table is venue-unqualified and wrong for futures; the
matching-algorithm page for futures and options under FIFO lists exactly three
priority-losing modifications: **an increase of working quantity, a change of
price, and a change of account number**.  Account is not in the feed, so what this
kernel implements is: *price change or size increase sends the order to the back;
a size decrease keeps its place.*

**The model is falsifiable on the data itself.**  Orders resting at the same side
and price should be filled in the order they joined.  Counting rank inversions
among filled orders tests the reconstruction without needing the vendor to supply
priority, and it is strongest exactly where the statistics are best: on the
busiest instruments.  :func:`rank_inversions` does that.

One caveat this cannot escape: Databento notes that ``ts_event`` substitutes for
MDOrderPriority "except for interest rate options and instruments where there's an
LMM".  A lead-market-maker allocation would break FIFO, and the inversion count is
how it would show up.
"""
from __future__ import annotations

import dataclasses
from typing import Optional, Tuple

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

__all__ = [
    "EXIT_REASONS",
    "LifecycleResult",
    "PRIORITY_LOST_PRICE",
    "PRIORITY_LOST_SIZE_UP",
    "rank_inversions",
    "replay_lifecycle",
]

UNDEF_PRICE = np.iinfo(np.int64).max

_A, _C, _M, _R, _T, _F, _N = (ord(x) for x in "ACMRTFN")
_BID, _ASK = ord("B"), ord("A")

#: Why an order left the book.
EXIT_REASONS = {
    0: "OPEN_AT_END",
    1: "CANCELLED",
    2: "FILLED",
    3: "PARTIAL_FILL_CANCELLED",
    4: "BOOK_RESET",
}

PRIORITY_LOST_PRICE = 1
PRIORITY_LOST_SIZE_UP = 2


@dataclasses.dataclass
class LifecycleResult:
    """One row per order that ever rested, plus the counters worth watching."""

    orders: pd.DataFrame
    grid: PriceGrid
    n_records: int = 0
    n_orders: int = 0
    n_snapshot_orders: int = 0
    #: Modifications that forfeited queue priority, by cause.
    n_priority_loss_price: int = 0
    n_priority_loss_size: int = 0
    #: Fill records that referenced an order this replay never saw resting.  Not
    #: necessarily an error -- an order that rested before the session snapshot
    #: can be filled inside it -- but a large count means the reconstruction is
    #: missing state and the queue numbers should not be trusted.
    n_orphan_fills: int = 0
    #: Orders detected as display-quantity (iceberg) orders, and the total number
    #: of refreshed tranches across them.
    n_icebergs: int = 0
    n_refreshes: int = 0


@njit(cache=True, nogil=True)
def _lifecycle(
    action, side, price_idx, size, ord_idx, n_orders, flags, ts_recv, ts_event,
    sequence, n_slots,
    o_side, o_pidx, o_size, o_size0, o_entry_ts, o_entry_tse, o_entry_seq,
    o_prio_ts, o_ahead_qty, o_ahead_ct, o_trd_at_prio, o_filled, o_first_fill,
    o_nmod, o_nprice, o_nup, o_ndown, o_exit_ts, o_reason, o_seen, o_snap,
    o_iceberg, o_refresh,
    bid_sz, ask_sz, bid_ct, ask_ct, bid_trd, ask_trd,
):
    n = action.shape[0]
    n_loss_price = 0
    n_loss_size = 0
    n_orphan = 0
    cur_gen = 1
    o_gen = np.zeros(n_orders, dtype=np.int64)

    for i in range(n):
        a = action[i]
        o = ord_idx[i]
        f = flags[i]
        is_snap = (f & F_SNAPSHOT) != 0

        if a == _R:
            # Close everything still resting; the book is gone.  Rare (once or
            # twice per instrument-day), so the O(orders) sweep is affordable and
            # buys an exact exit reason.
            for k in range(n_orders):
                if o_gen[k] == cur_gen and o_seen[k] == 1 and o_reason[k] == 0:
                    o_reason[k] = 4
                    o_exit_ts[k] = ts_recv[i]
            for k in range(n_slots):
                bid_sz[k] = 0
                ask_sz[k] = 0
                bid_ct[k] = 0
                ask_ct[k] = 0
            cur_gen += 1
            continue

        if a == _A:
            pidx = price_idx[i]
            sz = size[i]
            if pidx < 0 or sz <= 0:
                continue
            sd = side[i]
            if sd == _BID:
                ahead_q = bid_sz[pidx]
                ahead_c = bid_ct[pidx]
                trd = bid_trd[pidx]
                bid_sz[pidx] += sz
                bid_ct[pidx] += 1
                o_side[o] = 1
            elif sd == _ASK:
                ahead_q = ask_sz[pidx]
                ahead_c = ask_ct[pidx]
                trd = ask_trd[pidx]
                ask_sz[pidx] += sz
                ask_ct[pidx] += 1
                o_side[o] = 2
            else:
                continue
            # Rule (b): an order that was fully traded and then comes back
            # with volume is a refreshed tranche.  CME preserves the order id
            # across the whole life of a display-quantity order, so a slot that
            # has already been filled and closed cannot legitimately be a new
            # order under the same id.
            if o_seen[o] == 1 and o_filled[o] > 0:
                o_iceberg[o] = 1
                o_refresh[o] += 1
            o_gen[o] = cur_gen
            o_pidx[o] = pidx
            o_size[o] = sz
            o_size0[o] = sz
            o_entry_ts[o] = ts_recv[i]
            o_entry_tse[o] = ts_event[i]
            o_entry_seq[o] = sequence[i]
            o_prio_ts[o] = ts_recv[i]
            o_ahead_qty[o] = ahead_q
            o_ahead_ct[o] = ahead_c
            o_trd_at_prio[o] = trd
            o_seen[o] = 1
            o_reason[o] = 0
            if is_snap:
                o_snap[o] = 1

        elif a == _F:
            # A fill against a resting order.  This is where the order's own
            # execution is recorded; the C that follows in the same packet is the
            # removal, not a second event.
            if o_gen[o] != cur_gen or o_seen[o] != 1:
                n_orphan += 1
                continue
            sz = size[i]
            if sz <= 0:
                continue
            # Zotikov-Antonov rule (a): a trade whose volume exceeds the
            # order's resting volume can only have come from hidden quantity, so
            # the order is a display-quantity (iceberg) order.  Exact and
            # threshold-free -- the trade message carries the TOTAL matched
            # volume including the concealed part.
            if sz > o_size[o]:
                o_iceberg[o] = 1
            o_filled[o] += sz
            if o_first_fill[o] == 0:
                o_first_fill[o] = ts_recv[i]
            pidx = o_pidx[o]
            if o_side[o] == 1:
                bid_trd[pidx] += sz
            else:
                ask_trd[pidx] += sz

        elif a == _C:
            if o_gen[o] != cur_gen or o_seen[o] != 1:
                continue
            pidx = o_pidx[o]
            held = o_size[o]
            rm = size[i]
            if rm > held or rm <= 0:
                rm = held
            if o_side[o] == 1:
                bid_sz[pidx] -= rm
            else:
                ask_sz[pidx] -= rm
            if held - rm <= 0:
                if o_side[o] == 1:
                    bid_ct[pidx] -= 1
                else:
                    ask_ct[pidx] -= 1
                o_gen[o] = 0
                o_exit_ts[o] = ts_recv[i]
                if o_filled[o] <= 0:
                    o_reason[o] = 1
                elif o_filled[o] >= o_size0[o]:
                    o_reason[o] = 2
                else:
                    o_reason[o] = 3
                o_size[o] = 0
            else:
                o_size[o] = held - rm

        elif a == _M:
            pidx_new = price_idx[i]
            sz_new = size[i]
            known = o_gen[o] == cur_gen and o_seen[o] == 1
            if known:
                pidx_old = o_pidx[o]
                held = o_size[o]
                if o_side[o] == 1:
                    bid_sz[pidx_old] -= held
                    bid_ct[pidx_old] -= 1
                else:
                    ask_sz[pidx_old] -= held
                    ask_ct[pidx_old] -= 1
                o_nmod[o] += 1
                price_moved = pidx_new != pidx_old
                size_up = sz_new > held
                if price_moved:
                    o_nprice[o] += 1
                    n_loss_price += 1
                if size_up:
                    o_nup[o] += 1
                    n_loss_size += 1
                elif sz_new < held:
                    o_ndown[o] += 1
                lost = price_moved or size_up
                o_gen[o] = 0
            else:
                lost = True

            if pidx_new < 0 or sz_new <= 0:
                continue
            sd = side[i]
            if sd == _BID:
                ahead_q = bid_sz[pidx_new]
                ahead_c = bid_ct[pidx_new]
                trd = bid_trd[pidx_new]
                bid_sz[pidx_new] += sz_new
                bid_ct[pidx_new] += 1
                o_side[o] = 1
            elif sd == _ASK:
                ahead_q = ask_sz[pidx_new]
                ahead_c = ask_ct[pidx_new]
                trd = ask_trd[pidx_new]
                ask_sz[pidx_new] += sz_new
                ask_ct[pidx_new] += 1
                o_side[o] = 2
            else:
                continue
            if o_seen[o] == 1 and o_filled[o] > 0 and not known and sz_new > 0:
                o_iceberg[o] = 1
                o_refresh[o] += 1
            o_gen[o] = cur_gen
            o_pidx[o] = pidx_new
            o_size[o] = sz_new
            if o_seen[o] == 0:
                o_size0[o] = sz_new
                o_entry_ts[o] = ts_recv[i]
                o_entry_tse[o] = ts_event[i]
                o_entry_seq[o] = sequence[i]
                o_seen[o] = 1
                o_reason[o] = 0
            if lost:
                # Back of the queue: re-stamp the priority clock and the size
                # ahead, because that is the queue this order is now actually in.
                o_prio_ts[o] = ts_recv[i]
                o_ahead_qty[o] = ahead_q
                o_ahead_ct[o] = ahead_c
                o_trd_at_prio[o] = trd

    # anything still resting when the data ends
    for k in range(n_orders):
        if o_seen[k] == 1 and o_gen[k] == cur_gen and o_reason[k] == 0:
            o_reason[k] = 0
            o_exit_ts[k] = ts_recv[n - 1] if n > 0 else 0

    return n_loss_price, n_loss_size, n_orphan


def replay_lifecycle(
    records: np.ndarray,
    grid: Optional[PriceGrid] = None,
) -> LifecycleResult:
    """Replay one instrument's MBO records into a per-order table.

    ``records`` must be a single instrument's records **in file order**, the same
    input :func:`RVUtils.MBO.book.replay_book` takes.  Mixing instruments produces
    nonsense: order ids and price ladders are both per-instrument.

    The returned frame has one row per order that ever rested.  ``ahead_qty`` and
    ``ahead_orders`` are measured at the order's **last** queue join, not its
    first, because a modification that forfeits priority puts it in a different
    queue and the earlier number no longer describes anything.  ``rest_ns`` is
    measured from that same instant for the same reason.
    """
    if records.size == 0:
        raise ValueError("no records to replay")
    if np.unique(records["instrument_id"]).size != 1:
        raise ValueError("replay_lifecycle expects exactly one instrument_id")

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
    uniq, ord_idx = np.unique(order_id, return_inverse=True)
    ord_idx = ord_idx.astype(np.int64)
    n_orders = int(uniq.size)
    flags = records["flags"].astype(np.int64)
    ts_recv = records["ts_recv"].astype(np.int64)
    ts_event = records["ts_event"].astype(np.int64)
    sequence = records["sequence"].astype(np.int64)

    z = lambda: np.zeros(n_orders, dtype=np.int64)  # noqa: E731
    o = {k: z() for k in (
        "side", "pidx", "size", "size0", "entry_ts", "entry_tse", "entry_seq",
        "prio_ts", "ahead_qty", "ahead_ct", "trd_at_prio", "filled", "first_fill",
        "nmod", "nprice", "nup", "ndown", "exit_ts", "reason", "seen", "snap",
        "iceberg", "refresh",
    )}

    ns = g.n_slots
    n_loss_price, n_loss_size, n_orphan = _lifecycle(
        action, side, px_idx, size, ord_idx, n_orders, flags, ts_recv, ts_event,
        sequence, ns,
        o["side"], o["pidx"], o["size"], o["size0"], o["entry_ts"], o["entry_tse"],
        o["entry_seq"], o["prio_ts"], o["ahead_qty"], o["ahead_ct"],
        o["trd_at_prio"], o["filled"], o["first_fill"], o["nmod"], o["nprice"],
        o["nup"], o["ndown"], o["exit_ts"], o["reason"], o["seen"], o["snap"],
        o["iceberg"], o["refresh"],
        np.zeros(ns, dtype=np.int64), np.zeros(ns, dtype=np.int64),
        np.zeros(ns, dtype=np.int64), np.zeros(ns, dtype=np.int64),
        np.zeros(ns, dtype=np.int64), np.zeros(ns, dtype=np.int64),
    )

    keep = o["seen"] == 1
    df = pd.DataFrame({
        "order_id": uniq[keep],
        "side": np.where(o["side"][keep] == 1, "B", "A"),
        "price_idx": o["pidx"][keep].astype(np.int32),
        "price": g.to_price(o["pidx"][keep]),
        "size_initial": o["size0"][keep].astype(np.int32),
        "entry_ts": pd.to_datetime(o["entry_ts"][keep], utc=True),
        "entry_seq": o["entry_seq"][keep].astype(np.uint32),
        "priority_ts": pd.to_datetime(o["prio_ts"][keep], utc=True),
        "ahead_qty": o["ahead_qty"][keep].astype(np.int64),
        "ahead_orders": o["ahead_ct"][keep].astype(np.int32),
        "n_modify": o["nmod"][keep].astype(np.int32),
        "n_price_move": o["nprice"][keep].astype(np.int32),
        "n_size_up": o["nup"][keep].astype(np.int32),
        "n_size_down": o["ndown"][keep].astype(np.int32),
        "filled_size": o["filled"][keep].astype(np.int64),
        "first_fill_ts": pd.to_datetime(
            np.where(o["first_fill"][keep] > 0, o["first_fill"][keep], np.nan), utc=True
        ),
        #: Cumulative size traded at this price level at the moment the order
        #: joined the queue.  Differencing it against the level's total by the
        #: order's exit gives how much had to clear while it waited -- the
        #: denominator for "was there ever enough flow to reach me".
        "level_traded_at_join": o["trd_at_prio"][keep].astype(np.int64),
        "exit_ts": pd.to_datetime(o["exit_ts"][keep], utc=True),
        "exit_reason": pd.Categorical(
            [EXIT_REASONS[int(r)] for r in o["reason"][keep]],
            categories=list(EXIT_REASONS.values()),
        ),
        "from_snapshot": o["snap"][keep].astype(bool),
        #: A display-quantity (iceberg) order, by the exact structural rule of
        #: Zotikov & Antonov: a trade exceeding the resting volume, or a full
        #: fill followed by a return with volume.  No time window and no
        #: threshold -- the order id is preserved across an iceberg's whole life,
        #: which is what makes the rule unambiguous.
        "iceberg": o["iceberg"][keep].astype(bool),
        "n_refresh": o["refresh"][keep].astype(np.int32),
    })
    df["rest_ns"] = (
        df["exit_ts"].astype("int64") - df["priority_ts"].astype("int64")
    )
    df["time_to_fill_ns"] = (
        df["first_fill_ts"].astype("int64") - df["priority_ts"].astype("int64")
    ).where(df["first_fill_ts"].notna())
    df["filled"] = df["filled_size"] > 0

    return LifecycleResult(
        orders=df.sort_values("entry_ts", kind="stable").reset_index(drop=True),
        grid=g,
        n_records=int(records.size),
        n_orders=int(keep.sum()),
        n_snapshot_orders=int(o["snap"][keep].sum()),
        n_priority_loss_price=int(n_loss_price),
        n_priority_loss_size=int(n_loss_size),
        n_orphan_fills=int(n_orphan),
        n_icebergs=int(df["iceberg"].sum()) if len(df) else 0,
        n_refreshes=int(df["n_refresh"].sum()) if len(df) else 0,
    )


def rank_inversions(orders: pd.DataFrame) -> pd.DataFrame:
    """Does the reconstructed queue rank predict the order fills actually took?

    This is the falsification test for the priority model, and it needs nothing
    from the vendor.  Within one side and price, orders that joined the queue
    earlier hold a better position, so among those that were filled the fill times
    should follow the priority times.  A pair where they do not is an inversion.

    A model that gets the modify rules wrong -- treating a size increase as
    priority-preserving, say -- produces inversions immediately and on the busiest
    instruments, where the counts are largest.  A low rate is evidence the
    reconstruction is right; a high rate is evidence it is not, or that the
    instrument is not FIFO.

    Returns one row per (side, price) with the pair count and the inversion rate.
    Pairs are counted exactly, in O(n log n), by counting how many later-priority
    orders filled earlier.
    """
    if orders.empty:
        return pd.DataFrame(
            columns=["side", "price", "n_filled", "n_pairs", "n_inversions", "rate"]
        )
    f = orders[orders["filled"] & orders["first_fill_ts"].notna()]
    rows = []
    for (sd, px), g in f.groupby(["side", "price"], sort=False):
        if len(g) < 2:
            continue
        g = g.sort_values(["priority_ts", "entry_seq"], kind="stable")
        fill_order = g["first_fill_ts"].astype("int64").to_numpy()
        inv = _count_inversions(fill_order)
        n = len(g)
        rows.append({
            "side": sd, "price": px, "n_filled": n,
            "n_pairs": n * (n - 1) // 2, "n_inversions": int(inv),
            "rate": float(inv) / (n * (n - 1) / 2),
        })
    cols = ["side", "price", "n_filled", "n_pairs", "n_inversions", "rate"]
    if not rows:
        # A day where no price level saw two fills is perfectly ordinary; it just
        # yields no evidence either way.  Return the typed empty frame rather than
        # a column-less one, so a caller can concatenate sessions without care.
        return pd.DataFrame(columns=cols)
    out = pd.DataFrame(rows, columns=cols)
    return out.sort_values("n_pairs", ascending=False).reset_index(drop=True)


def _count_inversions(a: np.ndarray) -> int:
    """Inversions in ``a`` by merge sort -- O(n log n), exact."""
    a = np.asarray(a, dtype=np.int64)
    n = a.size
    if n < 2:
        return 0
    buf = np.empty(n, dtype=np.int64)
    return int(_merge_count(a.copy(), buf, 0, n - 1))


@njit(cache=True)
def _merge_count(a, buf, lo, hi):
    if lo >= hi:
        return 0
    mid = (lo + hi) // 2
    count = _merge_count(a, buf, lo, mid) + _merge_count(a, buf, mid + 1, hi)
    i, j, k = lo, mid + 1, lo
    while i <= mid and j <= hi:
        if a[i] <= a[j]:
            buf[k] = a[i]
            i += 1
        else:
            buf[k] = a[j]
            j += 1
            count += mid - i + 1
        k += 1
    while i <= mid:
        buf[k] = a[i]
        i += 1
        k += 1
    while j <= hi:
        buf[k] = a[j]
        j += 1
        k += 1
    for t in range(lo, hi + 1):
        a[t] = buf[t]
    return count
