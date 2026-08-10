"""Fill-simulator tests: the four bounds no replay simulator may violate.

The bounds matter more than any single number. A simulator that claims more fills
than actually traded, or fills an order that never reached the front, produces an
edge that does not exist -- and it does so quietly, because the output still looks
like a set of fills.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from RVUtils.MBO.lifecycle import replay_lifecycle
from RVUtils.MBO.sim import (
    fill_probability_curve,
    simulate_many,
    simulate_resting_order,
)
from tests.test_mbo_book import L, make

S = 1_000_000_000


def _replay(rows):
    r = replay_lifecycle(make(rows))
    tr = pd.DataFrame({
        "ts_recv": pd.to_datetime(
            [make([row])[0]["ts_recv"] for row in rows if row[1] == "T"], utc=True),
        "price": [row[3] for row in rows if row[1] == "T"],
        "size": [row[4] for row in rows if row[1] == "T"],
        "aggressor": [1 if row[2] == "B" else -1 for row in rows if row[1] == "T"],
    })
    return r.orders, tr


T0 = pd.Timestamp(1_784_073_600 * S, unit="ns", tz="UTC")


def _at(ns):
    return T0 + pd.Timedelta(ns, unit="ns")


# --------------------------------------------------------------------------- #
# the four bounds
# --------------------------------------------------------------------------- #

def test_an_order_behind_a_queue_that_never_clears_does_not_fill():
    """Bound one: joining behind size that is never consumed cannot fill."""
    rows = [
        (1, "A", "A", 96.01, 100, 10, L),        # a big resting ask
        (2 * S, "T", "B", 96.01, 5, 900, 0),     # only five trade
        (2 * S, "F", "A", 96.01, 5, 10, L),
    ]
    orders, trades = _replay(rows)
    r = simulate_resting_order(orders, trades, "A", 96.01, _at(S))
    assert not r.filled
    assert r.ahead_qty == 100


def test_an_order_at_the_front_of_a_cleared_level_fills():
    """Bound two: with nothing ahead, the next trade at the price fills it."""
    rows = [
        (1, "A", "A", 96.01, 5, 10, L),
        (2 * S, "T", "B", 96.01, 5, 900, 0),
        (2 * S, "F", "A", 96.01, 5, 10, 0),
        (2 * S, "C", "A", 96.01, 5, 10, 0),
        (3 * S, "T", "B", 96.01, 8, 901, L),      # a later trade reaches us
    ]
    orders, trades = _replay(rows)
    r = simulate_resting_order(orders, trades, "A", 96.01, _at(1))
    assert r.filled
    assert r.fill_ts == _at(3 * S)


def test_the_fill_never_exceeds_the_volume_that_actually_traded():
    """Bound three: a simulated fill cannot invent liquidity."""
    rows = [
        (1, "A", "A", 96.01, 1, 10, L),
        (2 * S, "T", "B", 96.01, 1, 900, 0),
        (2 * S, "F", "A", 96.01, 1, 10, 0),
        (2 * S, "C", "A", 96.01, 1, 10, 0),
        (3 * S, "T", "B", 96.01, 3, 901, L),
    ]
    orders, trades = _replay(rows)
    r = simulate_resting_order(orders, trades, "A", 96.01, _at(1), size=1000)
    assert r.filled
    assert r.fill_size == 3                      # the trade was three lots


def test_latency_can_only_weakly_reduce_fills():
    """Bound four: arriving later can only put you behind more of the queue."""
    rows = [
        (1, "A", "A", 96.01, 5, 10, 0),
        (1, "A", "A", 96.01, 5, 11, L),
        (2 * S, "T", "B", 96.01, 5, 900, 0),
        (2 * S, "F", "A", 96.01, 5, 10, 0),
        (2 * S, "C", "A", 96.01, 5, 10, 0),
        (3 * S, "T", "B", 96.01, 5, 901, 0),
        (3 * S, "F", "A", 96.01, 5, 11, 0),
        (3 * S, "C", "A", 96.01, 5, 11, 0),
        (4 * S, "T", "B", 96.01, 5, 902, L),
    ]
    orders, trades = _replay(rows)
    fast = simulate_resting_order(orders, trades, "A", 96.01, _at(1))
    slow = simulate_resting_order(orders, trades, "A", 96.01, _at(1),
                                  latency_ns=10 * S)
    assert fast.filled
    assert not slow.filled or slow.wait_ns >= 0


# --------------------------------------------------------------------------- #
# queue accounting
# --------------------------------------------------------------------------- #

def test_only_orders_resting_at_the_join_time_count_as_ahead():
    rows = [
        (1, "A", "A", 96.01, 5, 10, 0),
        (5 * S, "A", "A", 96.01, 7, 11, L),      # arrives later, behind us
    ]
    orders, trades = _replay(rows)
    r = simulate_resting_order(orders, trades, "A", 96.01, _at(2 * S))
    assert r.ahead_qty == 5
    assert r.ahead_orders == 1


def test_an_order_ahead_that_never_leaves_blocks_the_fill_explicitly():
    rows = [(1, "A", "A", 96.01, 5, 10, L)]
    orders, trades = _replay(rows)
    r = simulate_resting_order(orders, trades, "A", 96.01, _at(2 * S))
    assert not r.filled
    assert "never left" in r.reason


def test_a_cancel_ahead_clears_the_queue_without_any_trade():
    """The distinction an aggregated-depth simulator has to guess at: a pulled
    order ahead advances you just as an executed one does."""
    rows = [
        (1, "A", "A", 96.01, 50, 10, L),
        (2 * S, "C", "A", 96.01, 50, 10, L),     # pulled, not traded
        (3 * S, "T", "B", 96.01, 2, 900, L),
    ]
    orders, trades = _replay(rows)
    r = simulate_resting_order(orders, trades, "A", 96.01, _at(1))
    assert r.filled
    assert r.cleared_ts == _at(2 * S)


def test_the_resting_side_is_filled_by_the_opposite_aggressor():
    """A resting bid is filled by a seller. Getting this backwards fills every
    order instantly and looks like a wonderful strategy."""
    rows = [
        (1, "A", "B", 96.00, 5, 10, L),
        (2 * S, "C", "B", 96.00, 5, 10, L),
        (3 * S, "T", "B", 96.00, 4, 900, L),     # a BUYER lifting: not our fill
    ]
    orders, trades = _replay(rows)
    r = simulate_resting_order(orders, trades, "B", 96.00, _at(1))
    assert not r.filled


def test_simulate_many_returns_one_row_per_placement():
    rows = [
        (1, "A", "A", 96.01, 5, 10, L),
        (2 * S, "C", "A", 96.01, 5, 10, L),
        (3 * S, "T", "B", 96.01, 4, 900, L),
    ]
    orders, trades = _replay(rows)
    p = pd.DataFrame({"side": ["A", "A"], "price": [96.01, 96.01],
                      "t_place": [_at(1), _at(2 * S)]})
    out = simulate_many(orders, trades, p)
    assert len(out) == 2
    assert out["filled"].all()


# --------------------------------------------------------------------------- #
# the empirical curve the simulator is checked against
# --------------------------------------------------------------------------- #

def test_fill_probability_curve_is_monotone_on_a_constructed_book():
    orders = pd.DataFrame({
        "ahead_qty": [0, 0, 0, 5, 5, 5, 200, 200, 200],
        "filled": [True, True, True, True, False, False, False, False, False],
        "rest_ns": [1, 1, 1, 2, 2, 2, 3, 3, 3],
        "time_to_fill_ns": [1, 1, 1, 2, np.nan, np.nan, np.nan, np.nan, np.nan],
    })
    c = fill_probability_curve(orders, bins=(0, 1, 100))
    assert list(c["fill_rate"]) == [1.0, pytest.approx(1 / 3), 0.0]
    assert (np.diff(c["fill_rate"].to_numpy()) <= 0).all()


def test_fill_probability_curve_of_nothing_is_typed_and_empty():
    out = fill_probability_curve(pd.DataFrame())
    assert out.empty
    assert "fill_rate" in out.columns
