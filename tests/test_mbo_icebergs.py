"""Iceberg detection and size estimation.

Detection is an exact structural rule, so the tests are exact.  The estimator is
the part that needs care: a cancelled iceberg is a censored observation of its own
size, and treating it as complete biases the distribution downward exactly where a
hidden-liquidity estimate depends on it.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from RVUtils.MBO.analytics.icebergs import (
    hidden_volume_share,
    iceberg_summary,
    km_size_distribution,
)
from RVUtils.MBO.lifecycle import replay_lifecycle
from tests.test_mbo_book import L, make


def _orders(rows):
    return replay_lifecycle(make(rows)).orders.set_index("order_id")


# --------------------------------------------------------------------------- #
# detection
# --------------------------------------------------------------------------- #

def test_a_trade_larger_than_the_resting_size_marks_an_iceberg():
    """The trade message carries the total matched volume including the hidden
    part, so more traded than was showing can only be concealed quantity."""
    o = _orders([
        (1, "A", "A", 96.01, 5, 100, L),          # only 5 displayed
        (2, "T", "B", 96.01, 20, 200, 0),
        (2, "F", "A", 96.01, 20, 100, 0),         # but 20 traded
        (3, "C", "A", 96.01, 5, 100, L),
    ])
    assert bool(o.loc[100, "iceberg"])
    assert o.loc[100, "filled_size"] == 20


def test_an_ordinary_order_is_not_an_iceberg():
    o = _orders([
        (1, "A", "A", 96.01, 8, 100, L),
        (2, "T", "B", 96.01, 8, 200, 0),
        (2, "F", "A", 96.01, 8, 100, 0),
        (3, "C", "A", 96.01, 8, 100, L),
    ])
    assert not bool(o.loc[100, "iceberg"])


def test_a_partial_fill_is_not_an_iceberg():
    o = _orders([
        (1, "A", "A", 96.01, 10, 100, L),
        (2, "T", "B", 96.01, 4, 200, 0),
        (2, "F", "A", 96.01, 4, 100, 0),
        (2, "C", "A", 96.01, 4, 100, L),
    ])
    assert not bool(o.loc[100, "iceberg"])


def test_a_refresh_after_a_full_fill_marks_an_iceberg_and_is_counted():
    """The order id is preserved across an iceberg's whole life, so a slot that
    was filled out and returns with volume is a refreshed tranche."""
    rows = [(1, "A", "A", 96.01, 5, 100, L)]
    for k in range(3):
        t = (2 + k) * 1_000_000_000
        rows += [
            (t, "T", "B", 96.01, 5, 900 + k, 0),
            (t, "F", "A", 96.01, 5, 100, 0),
            (t, "C", "A", 96.01, 5, 100, 0),
            (t + 1, "A", "A", 96.01, 5, 100, L),     # next tranche, same id
        ]
    r = replay_lifecycle(make(rows))
    o = r.orders.set_index("order_id")
    assert bool(o.loc[100, "iceberg"])
    assert o.loc[100, "n_refresh"] == 3
    assert r.n_icebergs == 1
    assert r.n_refreshes == 3


def test_the_refreshed_tranche_goes_to_the_back_of_the_queue():
    """CME: the display-quantity order's priority is refreshed to the lowest at
    the level after every match event."""
    rows = [
        (1, "A", "A", 96.01, 5, 100, 0),
        (1, "A", "A", 96.01, 30, 101, L),        # a big order joins behind
        (2, "T", "B", 96.01, 5, 900, 0),
        (2, "F", "A", 96.01, 5, 100, 0),
        (2, "C", "A", 96.01, 5, 100, 0),
        (3, "A", "A", 96.01, 5, 100, L),         # tranche two
    ]
    o = _orders(rows)
    assert o.loc[100, "ahead_qty"] == 30          # now behind the resting 30


# --------------------------------------------------------------------------- #
# summaries
# --------------------------------------------------------------------------- #

def _frame(rows):
    return pd.DataFrame(rows)


def test_summary_counts_and_shares():
    df = _frame([
        {"iceberg": True, "n_refresh": 2, "filled_size": 40, "size_initial": 5,
         "exit_reason": "FILLED"},
        {"iceberg": False, "n_refresh": 0, "filled_size": 10, "size_initial": 10,
         "exit_reason": "FILLED"},
    ])
    s = iceberg_summary(df)
    assert s["n_icebergs"] == 1
    assert s["iceberg_share"] == pytest.approx(0.5)
    assert s["iceberg_volume"] == 40
    assert s["iceberg_volume_share"] == pytest.approx(40 / 50)


def test_summary_of_an_empty_frame_is_typed_not_an_error():
    s = iceberg_summary(pd.DataFrame())
    assert s["n_icebergs"] == 0


def test_hidden_volume_is_what_traded_beyond_what_was_shown():
    df = _frame([
        {"iceberg": True, "n_refresh": 1, "filled_size": 40, "size_initial": 5,
         "exit_reason": "FILLED"},
    ])
    h = hidden_volume_share(df)
    assert h["hidden_at_least"] == 40 - 5 * 2      # two tranches of five shown
    assert h["share"] == pytest.approx(30 / 40)


def test_hidden_volume_never_goes_negative():
    df = _frame([
        {"iceberg": True, "n_refresh": 5, "filled_size": 3, "size_initial": 10,
         "exit_reason": "CANCELLED"},
    ])
    assert hidden_volume_share(df)["hidden_at_least"] == 0


# --------------------------------------------------------------------------- #
# Kaplan-Meier
# --------------------------------------------------------------------------- #

def test_survival_is_the_empirical_tail_when_nothing_is_censored():
    """The known answer the old tests could not see.

    With no censoring, Kaplan-Meier must reduce to the empirical survival
    P(V > v). Three icebergs of 10, 20 and 30 give 2/3, 1/3, 0. The previous
    version accumulated the product downward from the largest volume, so the
    terminal (1 - 1/1) = 0 factor entered every row and the whole column was
    zero -- and the test that was supposed to catch it asserted only that the
    result was monotone non-increasing, which a column of zeros satisfies.
    """
    df = _frame([
        {"iceberg": True, "filled_size": v, "exit_reason": "FILLED",
         "n_refresh": 1, "size_initial": 1}
        for v in (10, 20, 30)
    ])
    km = km_size_distribution(df)
    assert list(km["volume"]) == [10, 20, 30]
    assert km["survival"].tolist() == pytest.approx([2 / 3, 1 / 3, 0.0])
    assert km["n_at_risk"].tolist() == [3, 2, 1]


def test_survival_starts_below_one_and_is_not_all_zero():
    """Two properties a column of zeros fails and monotonicity does not."""
    df = _frame([
        {"iceberg": True, "filled_size": v, "exit_reason": "FILLED",
         "n_refresh": 1, "size_initial": 1}
        for v in (5, 15, 25, 35)
    ])
    km = km_size_distribution(df)
    assert 0.0 < km["survival"].iloc[0] < 1.0
    assert (km["survival"] > 0).sum() >= 3


def test_a_cancelled_iceberg_is_censored_and_lifts_the_tail():
    """A censored observation contributes to the risk set but not to the events,
    so survival past it stays above what the uncensored sample would give."""
    uncensored = _frame([
        {"iceberg": True, "filled_size": v, "exit_reason": "FILLED",
         "n_refresh": 1, "size_initial": 1} for v in (10, 20, 30)
    ])
    censored = _frame([
        {"iceberg": True, "filled_size": 10, "exit_reason": "FILLED",
         "n_refresh": 1, "size_initial": 1},
        {"iceberg": True, "filled_size": 20, "exit_reason": "CANCELLED",
         "n_refresh": 1, "size_initial": 1},
        {"iceberg": True, "filled_size": 30, "exit_reason": "FILLED",
         "n_refresh": 1, "size_initial": 1},
    ])
    a = km_size_distribution(uncensored).set_index("volume")["survival"]
    b = km_size_distribution(censored).set_index("volume")["survival"]
    assert b.loc[20] > a.loc[20]
    assert km_size_distribution(censored).set_index("volume").loc[20, "n_events"] == 0


def test_an_explicit_completion_mask_overrides_the_exit_reason():
    """Native detection cannot tell a completed iceberg from a pulled one --
    rule (a) guarantees filled_size exceeds the displayed size, so the lifecycle
    kernel calls every one of them FILLED. A caller with a better signal must be
    able to supply it."""
    df = _frame([
        {"iceberg": True, "filled_size": v, "exit_reason": "FILLED",
         "n_refresh": 1, "size_initial": 1} for v in (10, 20, 30)
    ])
    all_censored = km_size_distribution(df, complete=pd.Series([False] * 3))
    assert (all_censored["n_events"] == 0).all()
    assert (all_censored["survival"] == 1.0).all()


def test_survival_is_monotone_non_increasing_in_volume():
    rng = np.random.default_rng(0)
    df = _frame([
        {"iceberg": True, "filled_size": int(v), "n_refresh": 1, "size_initial": 1,
         "exit_reason": "FILLED" if k % 3 else "CANCELLED"}
        for k, v in enumerate(rng.integers(5, 200, 60))
    ])
    km = km_size_distribution(df)
    s = km.sort_values("volume")["survival"].to_numpy()
    assert np.all(np.diff(s) <= 1e-12)
    assert s[0] < 1.0                      # not the vacuous all-zeros case
    assert (s > 0).any()


def test_km_of_no_icebergs_is_typed_and_empty():
    df = _frame([{"iceberg": False, "filled_size": 10, "exit_reason": "FILLED",
                  "n_refresh": 0, "size_initial": 10}])
    out = km_size_distribution(df)
    assert out.empty
    assert "survival" in out.columns
