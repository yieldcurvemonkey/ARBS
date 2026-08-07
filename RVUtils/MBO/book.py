"""L3 order-book replay for DBN MBO, JIT-compiled.

The replay contract, which is where every MBO reconstruction goes wrong:

**Book state mutates on A / C / M / R only.**  ``T`` (trade) and ``F`` (fill)
are trade *information*.  In this file a match prints as ``T`` then ``F`` then
an explicit ``C`` on the resting order, all inside one packet::

    T B 96.0075 8 order=...792 seq=141868133 flags=0
    F A 96.0075 8 order=...160 seq=141868133 flags=0
    C A 96.0075 8 order=...160 seq=141868134 flags=128

Applying the ``F`` *and* the ``C`` decrements the level twice.

**Top of book is only meaningful at ``F_LAST`` (128) packet boundaries.**  The
three records above are one exchange event; between them the book is
momentarily inconsistent.  Sampling mid-packet manufactures crossed books, and
any mid taken from one poisons every effective-spread number computed off it.

**Snapshot rows** (``F_SNAPSHOT``, 32) replay as adds but carry an unusable
``ts_recv`` -- in this file all 51,658 of them are stamped exactly 00:00:00.
Emission is suppressed until the snapshot ends, so the first emitted book is
the real opening state rather than 393 instruments' worth of fake midnight
activity.

Prices stay on the integer 1e-9 DBN scale throughout.  Levels live in a dense
array indexed by tick offset from the instrument's own minimum price, which is
what makes best-bid/best-ask maintenance O(1) amortised: an add can only
improve the best (checked when it happens), a removal can only degrade it
(walked back at the next emission).  Spread and butterfly prices are routinely
negative and the offset indexing handles that without a special case.
"""
from __future__ import annotations

import dataclasses
from typing import Optional, Tuple

import numpy as np
import pandas as pd
from numba import njit

__all__ = [
    "F_BAD_TS_RECV",
    "F_LAST",
    "F_SNAPSHOT",
    "MAX_PRICE_SLOTS",
    "PRICE_SCALE",
    "PriceGrid",
    "ReplayResult",
    "build_price_grid",
    "replay_book",
]

PRICE_SCALE = 1_000_000_000
UNDEF_PRICE = np.iinfo(np.int64).max

F_LAST = 128
F_TOB = 64
F_SNAPSHOT = 32
F_MBP = 16
F_BAD_TS_RECV = 8

_A, _C, _M, _R, _T, _F = (ord(x) for x in "ACMRTF")
_BID, _ASK = ord("B"), ord("A")

#: A dense price ladder is only sane while it stays small.  A fat-finger print
#: far from the market would otherwise allocate gigabytes silently.
MAX_PRICE_SLOTS = 4_000_000


@dataclasses.dataclass(frozen=True)
class PriceGrid:
    """The instrument's own tick lattice: ``price = px_min + idx * tick``."""

    px_min: int
    tick: int
    n_slots: int

    def to_price(self, idx: np.ndarray) -> np.ndarray:
        """Tick indices (-1 = empty side) to float prices, empty -> NaN."""
        out = np.full(np.shape(idx), np.nan, dtype=np.float64)
        live = (idx >= 0) & (idx < self.n_slots)
        out[live] = (self.px_min + idx[live].astype(np.int64) * self.tick) / PRICE_SCALE
        return out

    @property
    def tick_float(self) -> float:
        return self.tick / PRICE_SCALE


def build_price_grid(price: np.ndarray) -> PriceGrid:
    """Infer the tick lattice from the prices the instrument actually printed.

    The tick is the gcd of every price offset from the minimum, so it adapts to
    the quarter-tick front outright, the half-tick back of the strip and the
    finer grids the spread instruments quote on, without any of them being
    hard-coded.
    """
    px = price[price != UNDEF_PRICE].astype(np.int64)
    if px.size == 0:
        return PriceGrid(px_min=0, tick=1, n_slots=1)
    px_min = int(px.min())
    offs = np.unique(px - px_min)
    tick = int(np.gcd.reduce(offs)) if offs.size > 1 else 0
    if tick <= 0:
        tick = 1
    n_slots = int(offs.max() // tick) + 1
    if n_slots > MAX_PRICE_SLOTS:
        raise ValueError(
            f"price ladder would need {n_slots:,} slots (tick={tick / PRICE_SCALE:g}, "
            f"range={(offs.max()) / PRICE_SCALE:g}); the instrument printed an outlier price"
        )
    return PriceGrid(px_min=px_min, tick=tick, n_slots=n_slots)


@dataclasses.dataclass
class ReplayResult:
    """Everything one instrument's replay produces.

    ``tob`` has one row per packet boundary at which the top of book *changed*.
    ``rec_idx`` is the position of that boundary in the instrument's own record
    array -- joining trades to the prevailing book on ``rec_idx`` is exact,
    where an as-of join on timestamps is not (records inside a packet share a
    timestamp).
    """

    tob: pd.DataFrame
    trades: pd.DataFrame
    grid: PriceGrid
    depth: Optional[dict] = None
    n_records: int = 0
    n_snapshot: int = 0
    crossed_events: int = 0
    #: Basis points per unit of this instrument's price.  100 for an outright or
    #: a bundle (index points), 1 for every differential instrument, which CME
    #: quotes directly in bp.  Prices in ``tob``/``trades`` stay in the
    #: exchange's own units; this is what converts them.
    bp_per_unit: float = 100.0


@njit(cache=True, nogil=True)
def _replay(
    action, side, price_idx, size, ord_idx, n_orders, flags, ts_recv, ts_event,
    n_slots, grid_ts, n_levels, emit_from, emit_to,
    out_rec, out_ts, out_tse, out_bidx, out_bsz, out_bct, out_aidx, out_asz, out_act,
    d_bidx, d_bsz, d_aidx, d_asz, d_filled,
):
    # Orders live in dense slots, not a hash map: the caller factorises order_id
    # into 0..n_orders-1 with one numpy pass, which is both faster than a typed
    # dict and sidesteps numba's lack of tuple-valued dicts.  ``ord_gen`` makes
    # a Clear O(1) -- bumping the generation orphans every slot at once.
    ord_gen = np.zeros(n_orders, dtype=np.int64)
    ord_side = np.zeros(n_orders, dtype=np.int64)
    ord_pidx = np.zeros(n_orders, dtype=np.int64)
    ord_size = np.zeros(n_orders, dtype=np.int64)
    cur_gen = 1

    bid_sz = np.zeros(n_slots, dtype=np.int64)
    ask_sz = np.zeros(n_slots, dtype=np.int64)
    bid_ct = np.zeros(n_slots, dtype=np.int64)
    ask_ct = np.zeros(n_slots, dtype=np.int64)

    best_b = -1
    best_a = n_slots
    n = action.shape[0]
    n_grid = grid_ts.shape[0]

    out_n = 0
    g = 0
    crossed = 0
    n_snap = 0
    at_packet_start = True
    in_snapshot = True

    last_bidx = -2
    last_bsz = -1
    last_aidx = -2
    last_asz = -1

    for i in range(n):
        f = flags[i]
        is_snap = (f & F_SNAPSHOT) != 0
        if is_snap:
            n_snap += 1
        elif in_snapshot:
            in_snapshot = False

        # --- grid capture: state strictly before this packet -----------------
        if at_packet_start and not in_snapshot and n_grid > 0:
            t = ts_recv[i]
            while g < n_grid and grid_ts[g] < t:
                bb = best_b
                while bb >= 0 and bid_sz[bb] == 0:
                    bb -= 1
                aa = best_a
                while aa < n_slots and ask_sz[aa] == 0:
                    aa += 1
                best_b = bb
                best_a = aa
                k = bb
                for lv in range(n_levels):
                    while k >= 0 and bid_sz[k] == 0:
                        k -= 1
                    if k < 0:
                        break
                    d_bidx[g, lv] = k
                    d_bsz[g, lv] = bid_sz[k]
                    k -= 1
                k = aa
                for lv in range(n_levels):
                    while k < n_slots and ask_sz[k] == 0:
                        k += 1
                    if k >= n_slots:
                        break
                    d_aidx[g, lv] = k
                    d_asz[g, lv] = ask_sz[k]
                    k += 1
                d_filled[g] = 1
                g += 1

        a = action[i]
        o = ord_idx[i]

        if a == _R:
            for k in range(n_slots):
                bid_sz[k] = 0
                ask_sz[k] = 0
                bid_ct[k] = 0
                ask_ct[k] = 0
            cur_gen += 1
            best_b = -1
            best_a = n_slots

        elif a == _A:
            pidx = price_idx[i]
            sz = size[i]
            if pidx >= 0 and sz > 0:
                sd = side[i]
                if sd == _BID:
                    bid_sz[pidx] += sz
                    bid_ct[pidx] += 1
                    if pidx > best_b:
                        best_b = pidx
                    ord_gen[o] = cur_gen
                    ord_side[o] = 1
                    ord_pidx[o] = pidx
                    ord_size[o] = sz
                elif sd == _ASK:
                    ask_sz[pidx] += sz
                    ask_ct[pidx] += 1
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
                    if sd == 1:
                        bid_ct[pidx] -= 1
                    else:
                        ask_ct[pidx] -= 1
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
                    bid_ct[pidx0] -= 1
                else:
                    ask_sz[pidx0] -= held0
                    ask_ct[pidx0] -= 1
                ord_gen[o] = 0
            pidx = price_idx[i]
            sz = size[i]
            if pidx >= 0 and sz > 0:
                sd = side[i]
                if sd == _BID:
                    bid_sz[pidx] += sz
                    bid_ct[pidx] += 1
                    if pidx > best_b:
                        best_b = pidx
                    ord_gen[o] = cur_gen
                    ord_side[o] = 1
                    ord_pidx[o] = pidx
                    ord_size[o] = sz
                elif sd == _ASK:
                    ask_sz[pidx] += sz
                    ask_ct[pidx] += 1
                    if pidx < best_a:
                        best_a = pidx
                    ord_gen[o] = cur_gen
                    ord_side[o] = 2
                    ord_pidx[o] = pidx
                    ord_size[o] = sz

        at_packet_start = (f & F_LAST) != 0
        if not at_packet_start or is_snap:
            continue

        while best_b >= 0 and bid_sz[best_b] == 0:
            best_b -= 1
        while best_a < n_slots and ask_sz[best_a] == 0:
            best_a += 1

        bidx = best_b
        aidx = best_a if best_a < n_slots else -1
        bsz = bid_sz[bidx] if bidx >= 0 else 0
        asz = ask_sz[aidx] if aidx >= 0 else 0
        if bidx >= 0 and aidx >= 0 and bidx >= aidx:
            crossed += 1

        changed = (bidx != last_bidx or bsz != last_bsz
                   or aidx != last_aidx or asz != last_asz)
        if changed:
            last_bidx = bidx
            last_bsz = bsz
            last_aidx = aidx
            last_asz = asz

        t_i = ts_recv[i]
        if changed and t_i >= emit_from and t_i < emit_to:
            out_rec[out_n] = i
            out_ts[out_n] = ts_recv[i]
            out_tse[out_n] = ts_event[i]
            out_bidx[out_n] = bidx
            out_bsz[out_n] = bsz
            out_bct[out_n] = bid_ct[bidx] if bidx >= 0 else 0
            out_aidx[out_n] = aidx
            out_asz[out_n] = asz
            out_act[out_n] = ask_ct[aidx] if aidx >= 0 else 0
            out_n += 1
            last_bidx = bidx
            last_bsz = bsz
            last_aidx = aidx
            last_asz = asz

    # any grid points past the last message hold the closing book
    while g < n_grid:
        bb = best_b
        while bb >= 0 and bid_sz[bb] == 0:
            bb -= 1
        aa = best_a
        while aa < n_slots and ask_sz[aa] == 0:
            aa += 1
        best_b = bb
        best_a = aa
        k = bb
        for lv in range(n_levels):
            while k >= 0 and bid_sz[k] == 0:
                k -= 1
            if k < 0:
                break
            d_bidx[g, lv] = k
            d_bsz[g, lv] = bid_sz[k]
            k -= 1
        k = aa
        for lv in range(n_levels):
            while k < n_slots and ask_sz[k] == 0:
                k += 1
            if k >= n_slots:
                break
            d_aidx[g, lv] = k
            d_asz[g, lv] = ask_sz[k]
            k += 1
        d_filled[g] = 1
        g += 1

    return out_n, crossed, n_snap


def replay_book(
    records: np.ndarray,
    grid_ts: Optional[np.ndarray] = None,
    n_levels: int = 10,
    grid: Optional[PriceGrid] = None,
    emit_window: Optional[Tuple[pd.Timestamp, pd.Timestamp]] = None,
    bp_per_unit: Optional[float] = None,
) -> ReplayResult:
    """Replay one instrument's MBO records into a top-of-book stream.

    ``records`` must be a single instrument's records **in file order** -- the
    structured array databento's ``to_ndarray`` yields, filtered by
    ``instrument_id``.  Mixing instruments silently produces nonsense, because
    order ids and price ladders are per-instrument.

    ``grid_ts`` (sorted int64 UTC nanoseconds) additionally captures an
    ``n_levels``-deep ladder as of each grid time, using the book state from
    strictly before the packet that crosses it -- no look-ahead.

    ``emit_window`` replays the whole file but only *emits* top-of-book rows
    inside it.  The book still warms up from the opening snapshot, so the first
    emitted row is a real state and not an empty book; this only bounds output
    size, which matters because the busiest outright changes its touch fifteen
    million times in a day.

    ``bp_per_unit`` defaults to the tick-implied scale: an instrument ticking in
    0.5 quotes in basis points, one ticking in 0.005 quotes in index points.
    Pass it explicitly (from ``ParsedSymbol.bp_per_price_unit``) when the symbol
    is known -- see :func:`RVUtils.MBO.symbols.bp_per_price_unit`.
    """
    if records.size == 0:
        raise ValueError("no records to replay")
    if np.unique(records["instrument_id"]).size != 1:
        raise ValueError("replay_book expects exactly one instrument_id")

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
    ts_event = records["ts_event"].astype(np.int64)

    if emit_window is None:
        emit_from, emit_to = np.iinfo(np.int64).min, np.iinfo(np.int64).max
        in_window = (flags & F_LAST) != 0
    else:
        emit_from = int(pd.Timestamp(emit_window[0]).value)
        emit_to = int(pd.Timestamp(emit_window[1]).value)
        in_window = ((flags & F_LAST) != 0) & (ts_recv >= emit_from) & (ts_recv < emit_to)

    cap = int(in_window.sum()) + 1
    out_rec = np.zeros(cap, dtype=np.int64)
    out_ts = np.zeros(cap, dtype=np.int64)
    out_tse = np.zeros(cap, dtype=np.int64)
    out_bidx = np.zeros(cap, dtype=np.int64)
    out_bsz = np.zeros(cap, dtype=np.int64)
    out_bct = np.zeros(cap, dtype=np.int64)
    out_aidx = np.zeros(cap, dtype=np.int64)
    out_asz = np.zeros(cap, dtype=np.int64)
    out_act = np.zeros(cap, dtype=np.int64)

    gts = np.asarray([], dtype=np.int64) if grid_ts is None else np.asarray(grid_ts, dtype=np.int64)
    ng = gts.shape[0]
    nl = max(1, int(n_levels))
    d_bidx = np.full((max(ng, 1), nl), -1, dtype=np.int64)
    d_bsz = np.zeros((max(ng, 1), nl), dtype=np.int64)
    d_aidx = np.full((max(ng, 1), nl), -1, dtype=np.int64)
    d_asz = np.zeros((max(ng, 1), nl), dtype=np.int64)
    d_filled = np.zeros(max(ng, 1), dtype=np.int64)

    n_out, crossed, n_snap = _replay(
        action, side, px_idx, size, ord_idx, n_orders, flags, ts_recv, ts_event,
        g.n_slots, gts, nl, np.int64(emit_from), np.int64(emit_to),
        out_rec, out_ts, out_tse, out_bidx, out_bsz, out_bct, out_aidx, out_asz, out_act,
        d_bidx, d_bsz, d_aidx, d_asz, d_filled,
    )

    s = slice(0, n_out)
    tob = pd.DataFrame(
        {
            "rec_idx": out_rec[s],
            "ts_recv": pd.to_datetime(out_ts[s], utc=True),
            "ts_event": pd.to_datetime(out_tse[s], utc=True),
            "bid_px": g.to_price(out_bidx[s]),
            "bid_sz": out_bsz[s].astype(np.int32),
            "bid_ct": out_bct[s].astype(np.int32),
            "ask_px": g.to_price(out_aidx[s]),
            "ask_sz": out_asz[s].astype(np.int32),
            "ask_ct": out_act[s].astype(np.int32),
        }
    )
    tob["mid"] = (tob["bid_px"] + tob["ask_px"]) / 2.0
    tob["spread"] = tob["ask_px"] - tob["bid_px"]

    is_trade = action == _T
    trades = pd.DataFrame(
        {
            "rec_idx": np.flatnonzero(is_trade),
            "ts_recv": pd.to_datetime(ts_recv[is_trade], utc=True),
            "ts_event": pd.to_datetime(ts_event[is_trade], utc=True),
            "price": price[is_trade] / PRICE_SCALE,
            "size": size[is_trade],
            "aggressor": np.where(side[is_trade] == _BID, "B",
                                  np.where(side[is_trade] == _ASK, "A", "N")),
            "sequence": records["sequence"][is_trade],
        }
    )

    depth = None
    if ng > 0:
        depth = {
            "ts": gts,
            "bid_px": g.to_price(d_bidx),
            "bid_sz": d_bsz,
            "ask_px": g.to_price(d_aidx),
            "ask_sz": d_asz,
            "filled": d_filled.astype(bool),
        }

    scale = bp_per_unit if bp_per_unit is not None else (
        1.0 if g.tick_float >= 0.1 else 100.0
    )
    return ReplayResult(
        tob=tob, trades=trades, grid=g, depth=depth,
        n_records=int(records.size), n_snapshot=int(n_snap),
        crossed_events=int(crossed), bp_per_unit=float(scale),
    )
