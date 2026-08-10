"""Exact FIFO fill simulation over an order-resolved book.

The rule, and why it is exact rather than modelled:

    A hypothetical passive order joining a price level fills at the first trade
    at that level occurring after every order already resting there has left.

Under FIFO an order is matched only when nothing ahead of it remains, and "ahead
of it" is a set this data names individually.  Whether each of those left by being
executed or by being pulled does not matter to the arithmetic -- only that it
left -- which is exactly the distinction an aggregated-depth simulator has to
guess at, and the reason its queue models are calibration exercises.

**What is still assumed**, because no replay-based simulator escapes it:

* **No market impact.**  The hypothetical order does not change what anyone else
  did.  hftbacktest's documentation is blunt about this being the binding
  assumption, and it is why a simulated edge must be checked against live fills
  before it is believed.
* **No self-consumption.**  The order is treated as small enough that it does not
  exhaust the trade that fills it.  ``fill_size`` is capped at the volume of the
  filling trade so the result never claims more than actually traded.
* **Latency is a delay on arrival only.**  Adding latency moves the order's join
  time later, which can only put it behind more of the queue; it does not model a
  cancel that arrives too late.

Latency therefore weakly reduces fills, which is one of the invariants tested.
"""
from __future__ import annotations

import dataclasses
from typing import Iterable, Optional, Sequence

import numpy as np
import pandas as pd

__all__ = [
    "FillResult",
    "fill_probability_curve",
    "simulate_many",
    "simulate_resting_order",
]


@dataclasses.dataclass
class FillResult:
    """What happened to one hypothetical resting order."""

    filled: bool
    #: When every order ahead had gone.  NaT if some never left within the data.
    cleared_ts: Optional[pd.Timestamp]
    fill_ts: Optional[pd.Timestamp]
    fill_size: int
    #: Size resting ahead at the moment of joining -- the queue position.
    ahead_qty: int
    ahead_orders: int
    #: Volume that traded at this price after joining, whether or not it reached
    #: the order.  The denominator for "was there ever enough flow".
    traded_after: int
    wait_ns: Optional[int]
    reason: str

    def __repr__(self) -> str:
        if not self.filled:
            return f"<Fill NO ahead={self.ahead_qty} ({self.reason})>"
        return (f"<Fill YES {self.fill_size} lots after "
                f"{(self.wait_ns or 0) / 1e9:.3f}s, ahead={self.ahead_qty}>")


def _at_level(orders: pd.DataFrame, side: str, price: float,
              tol: float = 1e-12) -> pd.DataFrame:
    return orders[(orders["side"] == side)
                  & (np.abs(orders["price"] - price) <= tol)]


def simulate_resting_order(
    orders: pd.DataFrame,
    trades: pd.DataFrame,
    side: str,
    price: float,
    t_place: pd.Timestamp,
    size: int = 1,
    latency_ns: int = 0,
) -> FillResult:
    """Would a passive order joining ``price`` at ``t_place`` have been filled?

    ``orders`` is a lifecycle table (:func:`RVUtils.MBO.lifecycle.replay_lifecycle`)
    and ``trades`` a trade tape, both for the same instrument and session.

    ``side`` is the side the hypothetical order rests on: ``"B"`` to join the bid,
    which is filled by sell-initiated trades.
    """
    t0 = pd.Timestamp(t_place)
    if latency_ns:
        t0 = t0 + pd.Timedelta(latency_ns, unit="ns")

    level = _at_level(orders, side, price)
    # Resting at t0: joined the queue at or before it, and had not yet left.
    # An order that never left carries the session's last timestamp as its exit,
    # which would otherwise read as "already gone" for any placement after the
    # instrument's final message -- and it is the opposite: it is ahead forever.
    never_left = level["exit_reason"].astype(str).eq("OPEN_AT_END")
    ahead = level[(level["priority_ts"] <= t0)
                  & (never_left | (level["exit_ts"] > t0))]
    ahead_qty = int(ahead["size_initial"].sum())
    ahead_orders = int(len(ahead))

    # Trades at this price that could fill us.  A resting bid is filled by a
    # seller hitting it, so the aggressor sign is the opposite of our side.
    want_aggressor = -1 if side == "B" else 1
    tape = trades[(np.abs(trades["price"] - price) <= 1e-12)
                  & (trades["aggressor"] == want_aggressor)
                  & (trades["ts_recv"] >= t0)].sort_values("ts_recv")
    traded_after = int(tape["size"].sum()) if len(tape) else 0

    if ahead_orders == 0:
        cleared = t0
        must_trade = 0
    else:
        # An order still resting when the data ends never cleared, so nothing
        # behind it can be claimed to have filled.
        if bool(never_left.loc[ahead.index].any()):
            return FillResult(False, None, None, 0, ahead_qty, ahead_orders,
                              traded_after, None,
                              "an order ahead never left within the session")
        cleared = ahead["exit_ts"].max()
        # **Volume, not the clock, is what reaches us.**  Taking "the first trade
        # after the queue cleared" double-counts: the trade that cleared the last
        # order ahead is the one that consumed it, and only its residual can
        # reach us.  What must trade through before we are touched is the part of
        # the queue ahead that was *executed* -- an order ahead that was pulled
        # advances us for free, which is exactly the distinction L3 data lets us
        # make and aggregated depth does not.
        must_trade = int(np.minimum(
            ahead["filled_size"].to_numpy(dtype=np.int64),
            ahead["size_initial"].to_numpy(dtype=np.int64),
        ).sum())

    if tape.empty:
        return FillResult(False, cleared, None, 0, ahead_qty, ahead_orders,
                          traded_after, None, "no trade at this price after joining")

    cum = tape["size"].to_numpy(dtype=np.int64).cumsum()
    reached = np.flatnonzero(cum > must_trade)
    if reached.size == 0:
        return FillResult(False, cleared, None, 0, ahead_qty, ahead_orders,
                          traded_after, None,
                          f"only {int(cum[-1])} lots traded against {must_trade} "
                          f"that had to clear first")

    k = int(reached[0])
    row = tape.iloc[k]
    residual = int(cum[k] - must_trade)
    fill_size = int(min(int(size), residual))
    wait = int(pd.Timestamp(row["ts_recv"]).value - t0.value)
    return FillResult(True, cleared, row["ts_recv"], fill_size, ahead_qty,
                      ahead_orders, traded_after, wait, "filled")


def simulate_many(
    orders: pd.DataFrame,
    trades: pd.DataFrame,
    placements: pd.DataFrame,
    latency_ns: int = 0,
) -> pd.DataFrame:
    """Run a table of hypothetical placements.

    ``placements`` needs ``side``, ``price``, ``t_place`` and optionally ``size``.
    """
    rows = []
    for _, p in placements.iterrows():
        r = simulate_resting_order(
            orders, trades, str(p["side"]), float(p["price"]),
            pd.Timestamp(p["t_place"]), int(p.get("size", 1)), latency_ns,
        )
        rows.append({
            "side": p["side"], "price": p["price"], "t_place": p["t_place"],
            "filled": r.filled, "fill_ts": r.fill_ts, "fill_size": r.fill_size,
            "ahead_qty": r.ahead_qty, "ahead_orders": r.ahead_orders,
            "traded_after": r.traded_after, "wait_ns": r.wait_ns,
            "reason": r.reason,
        })
    return pd.DataFrame(rows)


def fill_probability_curve(
    orders: pd.DataFrame,
    bins: Sequence[float] = (0, 10, 50, 100, 500, 1000, 5000),
) -> pd.DataFrame:
    """Realised fill rate against queue position, from the orders that really rested.

    This is the empirical counterpart of the simulator and the thing to check it
    against: it uses no model at all, only what happened to actual orders. On ZNU6
    it runs from about 79% at the front of the queue to under 3% behind five
    thousand lots, monotonically -- which is what a correct queue reconstruction
    must produce and what a wrong one does not.
    """
    cols = ["ahead_lo", "ahead_hi", "n", "n_filled", "fill_rate",
            "median_rest_s", "median_fill_s"]
    if orders.empty:
        return pd.DataFrame(columns=cols)

    edges = list(bins) + [np.inf]
    rows = []
    a = orders["ahead_qty"].to_numpy(dtype=float)
    for lo, hi in zip(edges[:-1], edges[1:]):
        m = (a >= lo) & (a < hi)
        g = orders[m]
        if g.empty:
            continue
        filled = g["filled"].to_numpy(dtype=bool)
        rows.append({
            "ahead_lo": lo, "ahead_hi": hi, "n": int(len(g)),
            "n_filled": int(filled.sum()),
            "fill_rate": float(filled.mean()),
            "median_rest_s": float(g["rest_ns"].median()) / 1e9,
            "median_fill_s": (
                float(g.loc[filled, "time_to_fill_ns"].median()) / 1e9
                if filled.any() else np.nan
            ),
        })
    return pd.DataFrame(rows, columns=cols)
