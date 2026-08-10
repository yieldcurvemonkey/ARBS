"""Known-answer tests for the order-lifecycle kernel and the queue model.

Every sequence is hand-built and its resulting order table worked out by hand, so
a failure points at the kernel rather than at the data.  The priority rules under
test are the ones CME's futures matching-algorithm page states for FIFO -- a price
change or a working-quantity increase forfeits queue position, a decrease keeps it
-- and not the generic Order Functionalities table, which is venue-unqualified and
disagrees.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from RVUtils.MBO.book import F_SNAPSHOT
from RVUtils.MBO.lifecycle import rank_inversions, replay_lifecycle
from tests.test_mbo_book import L, make


def _orders(rows):
    return replay_lifecycle(make(rows)).orders.set_index("order_id")


# --------------------------------------------------------------------------- #
# entry and queue position
# --------------------------------------------------------------------------- #

def test_the_first_order_at_a_level_joins_an_empty_queue():
    o = _orders([(1, "A", "B", 96.00, 10, 1, L)])
    assert o.loc[1, "ahead_qty"] == 0
    assert o.loc[1, "ahead_orders"] == 0
    assert o.loc[1, "side"] == "B"
    assert o.loc[1, "size_initial"] == 10


def test_queue_ahead_is_the_resting_size_at_the_moment_of_joining():
    o = _orders([
        (1, "A", "B", 96.00, 10, 1, 0),
        (1, "A", "B", 96.00, 5, 2, 0),
        (1, "A", "B", 96.00, 7, 3, L),
    ])
    assert o.loc[1, "ahead_qty"] == 0
    assert o.loc[2, "ahead_qty"] == 10
    assert o.loc[3, "ahead_qty"] == 15
    assert o.loc[3, "ahead_orders"] == 2


def test_a_different_price_is_a_different_queue():
    o = _orders([
        (1, "A", "B", 96.00, 10, 1, 0),
        (1, "A", "B", 95.99, 4, 2, L),
    ])
    assert o.loc[2, "ahead_qty"] == 0


def test_the_two_sides_are_separate_queues():
    o = _orders([
        (1, "A", "B", 96.00, 10, 1, 0),
        (1, "A", "A", 96.00, 4, 2, L),
    ])
    assert o.loc[2, "ahead_qty"] == 0
    assert o.loc[2, "side"] == "A"


# --------------------------------------------------------------------------- #
# the priority rules
# --------------------------------------------------------------------------- #

def test_a_size_decrease_keeps_queue_position():
    """CME futures FIFO: a decrease of working quantity is priority-preserving."""
    o = _orders([
        (1, "A", "B", 96.00, 10, 1, 0),
        (1, "A", "B", 96.00, 20, 2, L),
        (2, "M", "B", 96.00, 5, 2, L),        # order 2 shrinks 20 -> 5
    ])
    assert o.loc[2, "ahead_qty"] == 10        # still behind order 1 only
    assert o.loc[2, "n_size_down"] == 1
    assert o.loc[2, "n_size_up"] == 0


def test_a_size_increase_forfeits_queue_position():
    o = _orders([
        (1, "A", "B", 96.00, 10, 1, 0),
        (1, "A", "B", 96.00, 5, 2, 0),
        (1, "A", "B", 96.00, 7, 3, L),
        (2, "M", "B", 96.00, 9, 2, L),        # order 2 grows 5 -> 9: back of queue
    ])
    # after removing its own 5, the level holds 10 + 7 = 17 ahead of it
    assert o.loc[2, "ahead_qty"] == 17
    assert o.loc[2, "n_size_up"] == 1


def test_a_price_change_forfeits_queue_position():
    o = _orders([
        (1, "A", "B", 95.99, 8, 1, 0),
        (1, "A", "B", 96.00, 10, 2, 0),
        (1, "A", "B", 96.00, 3, 3, L),
        (2, "M", "B", 95.99, 10, 2, L),       # order 2 moves down to join order 1
    ])
    assert o.loc[2, "ahead_qty"] == 8
    assert o.loc[2, "n_price_move"] == 1


def test_the_priority_clock_is_restamped_on_a_priority_loss():
    o = _orders([
        (1, "A", "B", 96.00, 10, 1, 0),
        (5_000_000_000, "M", "B", 96.00, 20, 1, L),
    ])
    assert o.loc[1, "priority_ts"] > o.loc[1, "entry_ts"]


def test_the_priority_clock_is_not_restamped_on_a_decrease():
    o = _orders([
        (1, "A", "B", 96.00, 20, 1, 0),
        (5_000_000_000, "M", "B", 96.00, 5, 1, L),
    ])
    assert o.loc[1, "priority_ts"] == o.loc[1, "entry_ts"]


def test_priority_losses_are_counted_by_cause():
    r = replay_lifecycle(make([
        (1, "A", "B", 96.00, 10, 1, 0),
        (2, "M", "B", 96.00, 20, 1, 0),       # size up
        (3, "M", "B", 95.99, 20, 1, L),       # price move
    ]))
    assert r.n_priority_loss_size == 1
    assert r.n_priority_loss_price == 1


# --------------------------------------------------------------------------- #
# fills and exits
# --------------------------------------------------------------------------- #

def test_a_full_fill_is_recorded_as_filled():
    o = _orders([
        (1, "A", "A", 96.01, 8, 100, 0),
        (1, "A", "B", 96.00, 12, 101, L),
        (2, "T", "B", 96.01, 8, 200, 0),
        (2, "F", "A", 96.01, 8, 100, 0),
        (3, "C", "A", 96.01, 8, 100, L),
    ])
    assert o.loc[100, "exit_reason"] == "FILLED"
    assert o.loc[100, "filled_size"] == 8
    assert bool(o.loc[100, "filled"])
    assert pd.notna(o.loc[100, "first_fill_ts"])


def test_a_partial_fill_then_a_cancel_is_distinguished_from_both():
    o = _orders([
        (1, "A", "A", 96.01, 10, 100, L),
        (2, "T", "B", 96.01, 4, 200, 0),
        (2, "F", "A", 96.01, 4, 100, 0),
        (2, "C", "A", 96.01, 4, 100, L),      # 4 removed, 6 still resting
        (3, "C", "A", 96.01, 6, 100, L),      # participant pulls the rest
    ])
    assert o.loc[100, "filled_size"] == 4
    assert o.loc[100, "exit_reason"] == "PARTIAL_FILL_CANCELLED"


def test_a_plain_cancel_is_not_a_fill():
    o = _orders([
        (1, "A", "B", 96.00, 10, 1, L),
        (2, "C", "B", 96.00, 10, 1, L),
    ])
    assert o.loc[1, "exit_reason"] == "CANCELLED"
    assert o.loc[1, "filled_size"] == 0
    assert not bool(o.loc[1, "filled"])


def test_an_order_still_resting_at_the_end_is_open_not_cancelled():
    o = _orders([(1, "A", "B", 96.00, 10, 1, L)])
    assert o.loc[1, "exit_reason"] == "OPEN_AT_END"


def test_a_book_reset_closes_everything_resting():
    o = _orders([
        (1, "A", "B", 96.00, 10, 1, 0),
        (1, "A", "A", 96.01, 5, 2, L),
        (2, "R", "N", None, 0, 0, L),
    ])
    assert o.loc[1, "exit_reason"] == "BOOK_RESET"
    assert o.loc[2, "exit_reason"] == "BOOK_RESET"


def test_rest_time_is_measured_from_the_last_priority_join():
    """An order that lost priority has been in its current queue only since then;
    measuring from first entry would overstate how long it actually waited."""
    o = _orders([
        (0, "A", "B", 96.00, 10, 1, 0),
        (10_000_000_000, "M", "B", 96.00, 20, 1, 0),     # priority lost
        (12_000_000_000, "C", "B", 96.00, 20, 1, L),
    ])
    assert o.loc[1, "rest_ns"] == 2_000_000_000


def test_time_to_fill_is_null_when_the_order_never_filled():
    o = _orders([
        (1, "A", "B", 96.00, 10, 1, L),
        (2, "C", "B", 96.00, 10, 1, L),
    ])
    assert pd.isna(o.loc[1, "time_to_fill_ns"])


# --------------------------------------------------------------------------- #
# snapshot orders
# --------------------------------------------------------------------------- #

def test_snapshot_orders_are_flagged():
    """CME's start-of-day snapshot carries orders submitted before the session,
    in priority order, so they seed the queue and must be distinguishable."""
    snap = F_SNAPSHOT | 8
    r = replay_lifecycle(make([
        (0, "A", "B", 96.00, 10, 1, snap),
        (0, "A", "B", 96.00, 5, 2, snap | L),
        (1_000_000_000, "A", "B", 96.00, 3, 3, L),
    ]))
    o = r.orders.set_index("order_id")
    assert bool(o.loc[1, "from_snapshot"])
    assert not bool(o.loc[3, "from_snapshot"])
    assert r.n_snapshot_orders == 2
    # the snapshot seeded the queue the live order joined behind
    assert o.loc[3, "ahead_qty"] == 15


# --------------------------------------------------------------------------- #
# the falsification test
# --------------------------------------------------------------------------- #

def test_fifo_fills_produce_no_rank_inversions():
    """Orders filled in the order they joined: the model's own prediction."""
    rows = [
        (1, "A", "A", 96.01, 5, 10, 0),
        (1, "A", "A", 96.01, 5, 11, 0),
        (1, "A", "A", 96.01, 5, 12, L),
    ]
    for k, oid in enumerate((10, 11, 12)):
        t = (2 + k) * 1_000_000_000
        rows += [
            (t, "T", "B", 96.01, 5, 900 + k, 0),
            (t, "F", "A", 96.01, 5, oid, 0),
            (t, "C", "A", 96.01, 5, oid, L),
        ]
    inv = rank_inversions(replay_lifecycle(make(rows)).orders)
    assert len(inv) == 1
    assert inv.iloc[0]["n_filled"] == 3
    assert inv.iloc[0]["n_inversions"] == 0
    assert inv.iloc[0]["rate"] == 0.0


def test_out_of_order_fills_are_counted_as_inversions():
    """If the queue model were wrong, this is the signature it would leave."""
    rows = [
        (1, "A", "A", 96.01, 5, 10, 0),
        (1, "A", "A", 96.01, 5, 11, 0),
        (1, "A", "A", 96.01, 5, 12, L),
    ]
    for k, oid in enumerate((12, 11, 10)):        # filled back to front
        t = (2 + k) * 1_000_000_000
        rows += [
            (t, "T", "B", 96.01, 5, 900 + k, 0),
            (t, "F", "A", 96.01, 5, oid, 0),
            (t, "C", "A", 96.01, 5, oid, L),
        ]
    inv = rank_inversions(replay_lifecycle(make(rows)).orders)
    assert inv.iloc[0]["n_inversions"] == 3       # every pair inverted
    assert inv.iloc[0]["rate"] == 1.0


def test_rank_inversions_on_an_empty_table_is_typed_and_empty():
    out = rank_inversions(pd.DataFrame())
    assert out.empty
    assert "n_inversions" in out.columns


def test_rank_inversions_ignores_a_level_with_a_single_fill():
    o = replay_lifecycle(make([
        (1, "A", "A", 96.01, 5, 10, L),
        (2, "T", "B", 96.01, 5, 900, 0),
        (2, "F", "A", 96.01, 5, 10, 0),
        (2, "C", "A", 96.01, 5, 10, L),
    ])).orders
    assert rank_inversions(o).empty


# --------------------------------------------------------------------------- #
# guards
# --------------------------------------------------------------------------- #

def test_replaying_two_instruments_at_once_raises():
    a = make([(1, "A", "B", 96.0, 1, 1, L)], instrument_id=1)
    b = make([(1, "A", "B", 96.0, 1, 2, L)], instrument_id=2)
    with pytest.raises(ValueError, match="exactly one instrument_id"):
        replay_lifecycle(np.concatenate([a, b]))


def test_replaying_nothing_raises():
    with pytest.raises(ValueError, match="no records"):
        replay_lifecycle(make([])[:0])


def test_a_fill_for_an_order_never_seen_is_counted_not_silently_dropped():
    r = replay_lifecycle(make([
        (1, "A", "B", 96.00, 10, 1, 0),
        (2, "F", "A", 96.01, 4, 999, L),      # order 999 never rested here
    ]))
    assert r.n_orphan_fills == 1
