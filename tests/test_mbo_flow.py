"""Known-answer tests for order-flow imbalance and signed trade flow.

Every expected number here was worked out by hand from the Cont-Kukanov-Stoikov
definition before the code was run, so a failure points at the module rather
than at the data.  The sequences are built to hit the branches that are easy to
get wrong rather than the ones that are easy to write: the equality case in the
OFI indicators, the one-sided book, the session boundary, the empty bar, and the
difference between a within-bar mid change and the bar-to-bar one.

One test goes the whole way through the store, because the layers disagree about
what an aggressor is: a raw replay frame carries ``'B'``/``'A'`` and the reader
serves ``+1``/``-1``.  A change to that contract must break this suite rather
than silently zero every signed volume.
"""
from __future__ import annotations

import datetime
import math

import numpy as np
import pandas as pd
import pytest

from RVUtils.MBO.analytics.flow import (
    flow_summary,
    ofi_bars,
    ofi_events,
    trade_flow,
    trade_sign_autocorrelation,
)

T0 = pd.Timestamp("2026-07-14 12:00:00", tz="UTC")
DATE = datetime.date(2026, 7, 14)
DATE2 = datetime.date(2026, 7, 15)
T0_D2 = T0 + pd.Timedelta(days=1)


# --------------------------------------------------------------------------- #
# fixture builders -- hand-built frames shaped like what the reader serves
# --------------------------------------------------------------------------- #

def _ts(offsets, base):
    if len(offsets) == 0:
        return pd.Series(pd.DatetimeIndex([], tz="UTC"))
    return pd.Series([base + pd.Timedelta(seconds=float(o)) for o in offsets])


def tob_frame(rows, symbol="SR3Z6", date=DATE, base=T0):
    """rows: ``(t_seconds, bid_px, bid_sz, ask_px, ask_sz)``; ``None`` px = empty."""
    n = len(rows)

    def col(i, dtype):
        return np.array([r[i] for r in rows], dtype=dtype) if n else np.zeros(0, dtype)

    df = pd.DataFrame({
        "symbol": np.array([symbol] * n, dtype=object),
        "ts_recv": _ts([r[0] for r in rows], base),
        "sequence": np.arange(n, dtype=np.uint32),
        "date": np.array([date] * n, dtype=object),
        "bid_px": col(1, float),
        "bid_sz": col(2, np.int64),
        "ask_px": col(3, float),
        "ask_sz": col(4, np.int64),
    })
    df["mid"] = (df["bid_px"] + df["ask_px"]) / 2.0
    df["spread"] = df["ask_px"] - df["bid_px"]
    return df


def trade_frame(rows, symbol="SR3Z6", date=DATE, base=T0):
    """rows: ``(t_seconds, price, size, aggressor)`` with aggressor in -1/0/+1."""
    n = len(rows)

    def col(i, dtype):
        return np.array([r[i] for r in rows], dtype=dtype) if n else np.zeros(0, dtype)

    return pd.DataFrame({
        "symbol": np.array([symbol] * n, dtype=object),
        "ts_recv": _ts([r[0] for r in rows], base),
        "sequence": np.arange(n, dtype=np.uint32),
        "date": np.array([date] * n, dtype=object),
        "price": col(1, float),
        "size": col(2, np.int64),
        "aggressor": col(3, np.int8),
    })


def signs_frame(signs, date=DATE, base=T0):
    """One unit trade per sign, one second apart -- trade time is all that matters."""
    return trade_frame([(i, 96.0, 1, s) for i, s in enumerate(signs)],
                       date=date, base=base)


#: Every branch of the CKS indicator pair, in order, with the answer per event:
#:   1  bid price flat, size 10 -> 12          +2   (equality: q_n - q_{n-1})
#:   2  ask price flat, size 7 -> 4            +3   (equality on the ask)
#:   3  bid improves to 96.005 with 5 lots     +5   (+q_n, and NOT -q_{n-1})
#:   4  bid falls back to 96.000               -5   (-q_{n-1}, the queue it left)
#:   5  ask worsens to 96.015                  +4   (+q_{n-1})
#:   6  ask improves back to 96.010 with 2     -2   (-q_n)
_ALL_BRANCHES = [
    (0, 96.000, 10, 96.010, 7),
    (1, 96.000, 12, 96.010, 7),
    (2, 96.000, 12, 96.010, 4),
    (12, 96.005, 5, 96.010, 4),
    (13, 96.000, 8, 96.010, 4),
    (35, 96.000, 8, 96.015, 9),
    (36, 96.000, 8, 96.010, 2),
]
_ALL_BRANCHES_OFI = [0.0, 2.0, 3.0, 5.0, -5.0, 4.0, -2.0]


# --------------------------------------------------------------------------- #
# ofi_events
# --------------------------------------------------------------------------- #

def test_ofi_events_reproduces_every_branch_of_the_cks_definition():
    e = ofi_events(tob_frame(_ALL_BRANCHES))
    assert e.tolist() == _ALL_BRANCHES_OFI


def test_an_unchanged_price_with_a_size_change_is_the_size_difference():
    """The classic error: both indicators fire on equality, so this is not zero.

    A bid that grows from 10 to 12 lots at a standing price contributes exactly
    +2.  Coding the indicators with ``>`` and ``<`` gives 0 and deletes every
    queue build and pull on a tick-bound contract.
    """
    e = ofi_events(tob_frame([
        (0, 96.000, 10, 96.010, 7),
        (1, 96.000, 12, 96.010, 7),
        (2, 96.000, 12, 96.010, 3),
    ]))
    assert e.tolist() == [0.0, 2.0, 4.0]


def test_the_first_event_has_no_predecessor_and_scores_zero():
    e = ofi_events(tob_frame([(0, 96.000, 10, 96.010, 7)]))
    assert e.tolist() == [0.0]


def test_one_sided_states_are_dropped_and_the_gap_is_accounted_across():
    """The ask is pulled entirely and comes back four lots thinner.

    Comparing the two two-sided states gives ``-(3 - 7) = +4``.  Keeping the
    empty state would score 0 for the pull and 0 for the return -- every
    comparison against NaN is false -- and the episode would vanish.
    """
    e = ofi_events(tob_frame([
        (0, 96.000, 10, 96.010, 7),
        (1, 96.000, 10, None, 0),
        (2, 96.000, 10, 96.010, 3),
    ]))
    assert len(e) == 2
    assert e.tolist() == [0.0, 4.0]


def test_ofi_is_indexed_by_ts_recv():
    e = ofi_events(tob_frame(_ALL_BRANCHES))
    assert e.index.name == "ts_recv"
    assert str(e.index.tz) == "UTC"
    assert e.index[1] == T0 + pd.Timedelta(seconds=1)
    assert e.name == "ofi"


def test_the_first_event_of_a_new_session_scores_zero_not_an_overnight_gap():
    """Pairing 95.00 on Wednesday with 96.00 on Tuesday would book -17 lots of
    flow for a night in which the book was closed."""
    day1 = tob_frame([(0, 96.000, 10, 96.010, 7),
                      (1, 96.000, 12, 96.010, 7)])
    day2 = tob_frame([(0, 95.000, 20, 95.010, 5),
                      (1, 95.000, 25, 95.010, 5)], date=DATE2, base=T0_D2)
    e = ofi_events(pd.concat([day1, day2], ignore_index=True))
    assert e.tolist() == [0.0, 2.0, 0.0, 5.0]


def test_ofi_events_sorts_a_frame_handed_over_out_of_order():
    rows = tob_frame(_ALL_BRANCHES)
    e = ofi_events(rows.iloc[::-1].reset_index(drop=True))
    assert e.tolist() == _ALL_BRANCHES_OFI


def test_ofi_events_on_an_empty_frame_is_an_empty_typed_series():
    e = ofi_events(tob_frame([]))
    assert len(e) == 0
    assert e.dtype == np.float64
    assert e.index.name == "ts_recv"


def test_a_book_that_is_never_two_sided_yields_nothing_rather_than_zeros():
    e = ofi_events(tob_frame([(0, 96.0, 10, None, 0), (1, 96.0, 12, None, 0)]))
    assert len(e) == 0


def test_ofi_events_refuses_two_instruments():
    a = tob_frame(_ALL_BRANCHES, symbol="SR3Z6")
    b = tob_frame(_ALL_BRANCHES, symbol="SR3H7")
    with pytest.raises(ValueError, match="order flow is a property of one book"):
        ofi_events(pd.concat([a, b], ignore_index=True))


def test_ofi_events_names_the_column_it_is_missing():
    t = tob_frame(_ALL_BRANCHES).drop(columns=["mid"])
    with pytest.raises(ValueError, match=r"missing \['mid'\]"):
        ofi_events(t)


# --------------------------------------------------------------------------- #
# ofi_bars
# --------------------------------------------------------------------------- #

def test_ofi_bars_sum_the_events_inside_each_bar():
    """Events at 0,1,2 | 12,13 | -- | 35,36 seconds against a ten-second grid."""
    b = ofi_bars(tob_frame(_ALL_BRANCHES), freq="10s")
    assert b["ofi"].tolist() == [5.0, 0.0, 0.0, 2.0]
    assert b["n_events"].tolist() == [3, 2, 0, 2]
    assert b.index[0] == T0
    assert b.index[-1] == T0 + pd.Timedelta(seconds=30)
    assert b["ofi"].sum() == ofi_events(tob_frame(_ALL_BRANCHES)).sum()


#: One event per bar, the mid walking up half a tick a bar, and one empty bar.
_WALK = [
    (0, 96.000, 10, 96.010, 10),     # mid 96.005
    (12, 96.005, 10, 96.015, 10),    # mid 96.010
    (31, 96.010, 10, 96.020, 10),    # mid 96.015
]


def test_d_mid_is_the_bar_to_bar_change_not_the_within_bar_one():
    """Each bar holds one event, so ``mid_last - mid_first`` is identically zero.

    That is the trap: the within-bar reading throws away exactly the move the
    bar's own flow caused, and it does so hardest where bars are sparse.  CKS
    pair the flow in a bar with the mid at the end of it against the mid at the
    end of the previous one, which is what these numbers are.
    """
    b = ofi_bars(tob_frame(_WALK), freq="10s")
    assert b["mid_first"].tolist() == pytest.approx([96.005, 96.010, np.nan, 96.015],
                                                    nan_ok=True)
    assert b["mid_last"].tolist() == pytest.approx([96.005, 96.010, np.nan, 96.015],
                                                   nan_ok=True)
    assert np.isnan(b["d_mid"].iloc[0])
    assert b["d_mid"].iloc[1] == pytest.approx(0.005)
    assert b["d_mid"].iloc[2] == 0.0
    assert b["d_mid"].iloc[3] == pytest.approx(0.005)


def test_an_empty_bar_reports_no_events_and_no_price_change():
    """``mid_first``/``mid_last`` are NaN because there were no events; ``d_mid``
    is 0 because the prevailing mid stood still.  Both are true at once."""
    b = ofi_bars(tob_frame(_WALK), freq="10s")
    quiet = b.iloc[2]
    assert quiet["n_events"] == 0
    assert quiet["ofi"] == 0.0
    assert np.isnan(quiet["mid_first"]) and np.isnan(quiet["mid_last"])
    assert quiet["d_mid"] == 0.0


def test_the_first_bar_of_each_session_has_no_previous_bar_to_difference():
    day1 = tob_frame(_WALK)
    day2 = tob_frame(_WALK, date=DATE2, base=T0_D2)
    b = ofi_bars(pd.concat([day1, day2], ignore_index=True), freq="10s")
    assert len(b) == 8
    assert np.isnan(b["d_mid"].iloc[0])
    assert np.isnan(b["d_mid"].iloc[4])


def test_no_bars_are_manufactured_for_the_overnight_gap():
    """A naive resample across two sessions would put 8,640 empty ten-second bars
    between them."""
    both = pd.concat([tob_frame(_WALK), tob_frame(_WALK, date=DATE2, base=T0_D2)],
                     ignore_index=True)
    assert len(ofi_bars(both, freq="10s")) == 2 * len(ofi_bars(tob_frame(_WALK), "10s"))


def test_ofi_bars_default_bar_is_the_ten_seconds_cks_use():
    assert ofi_bars(tob_frame(_ALL_BRANCHES)).equals(
        ofi_bars(tob_frame(_ALL_BRANCHES), freq="10s")
    )


def test_ofi_bars_rejects_a_frequency_that_is_not_a_fixed_span():
    with pytest.raises(ValueError, match="non-fixed frequency"):
        ofi_bars(tob_frame(_ALL_BRANCHES), freq="ME")


def test_ofi_bars_on_an_empty_frame_is_an_empty_typed_frame():
    b = ofi_bars(tob_frame([]))
    assert b.empty
    assert list(b.columns) == ["ofi", "n_events", "mid_first", "mid_last", "d_mid"]
    assert b["n_events"].dtype == np.int64


# --------------------------------------------------------------------------- #
# trade_flow
# --------------------------------------------------------------------------- #

_TAPE = [
    (0, 96.010, 5, 1),     # buy-initiated
    (3, 96.000, 2, -1),    # sell-initiated
    (4, 96.000, 7, 0),     # aggressor unknown
    (12, 96.010, 4, 1),
    (31, 96.000, 9, -1),
]


def test_trade_flow_signs_volume_by_the_true_aggressor():
    f = trade_flow(trade_frame(_TAPE), freq="10s")
    assert f["signed_volume"].tolist() == [3, 4, 0, -9]
    assert f["buy_volume"].tolist() == [5, 4, 0, 0]
    assert f["sell_volume"].tolist() == [2, 0, 0, 9]


def test_an_unknown_aggressor_counts_as_a_trade_and_as_neither_side():
    """Seven lots printed in the first bar with no side, and they must not be
    silently split, dropped, or shovelled into ``buy_volume``."""
    f = trade_flow(trade_frame(_TAPE), freq="10s")
    first = f.iloc[0]
    assert first["n_trades"] == 3
    assert first["buy_trades"] == 1
    assert first["sell_trades"] == 1
    assert first["buy_volume"] + first["sell_volume"] == 7      # not 14
    assert first["signed_volume"] == 3


def test_trade_imbalance_is_the_same_number_as_signed_volume():
    """CKS call it TI; both names are served, and they cannot diverge unless the
    aggressor column carries something other than +1/-1/0."""
    f = trade_flow(trade_frame(_TAPE), freq="10s")
    assert f["signed_trade_imbalance"].tolist() == f["signed_volume"].tolist()


def test_a_bar_with_no_prints_is_zero_rather_than_missing():
    f = trade_flow(trade_frame(_TAPE), freq="10s")
    quiet = f.iloc[2]
    assert quiet["n_trades"] == 0
    assert quiet["signed_volume"] == 0
    assert quiet["buy_volume"] == 0 and quiet["sell_volume"] == 0


def test_trade_flow_bars_start_and_end_on_the_tape():
    f = trade_flow(trade_frame(_TAPE), freq="10s")
    assert f.index[0] == T0
    assert f.index[-1] == T0 + pd.Timedelta(seconds=30)
    assert f.index.name == "ts_recv"


def test_trade_flow_counts_are_integers_not_floats():
    f = trade_flow(trade_frame(_TAPE), freq="10s")
    for col in f.columns:
        assert f[col].dtype == np.int64, col


def test_trade_flow_on_an_empty_tape_is_an_empty_typed_frame():
    f = trade_flow(trade_frame([]))
    assert f.empty
    assert list(f.columns) == ["signed_volume", "buy_volume", "sell_volume",
                               "n_trades", "buy_trades", "sell_trades",
                               "signed_trade_imbalance"]


def test_trade_flow_refuses_a_replay_frame_whose_aggressor_is_a_letter():
    t = trade_frame(_TAPE)
    t["aggressor"] = np.array(["B", "A", "N", "B", "A"], dtype=object)
    with pytest.raises(ValueError, match="not integral"):
        trade_flow(t)


def test_trade_flow_refuses_a_side_encoded_some_other_way():
    t = trade_frame(_TAPE)
    t["aggressor"] = np.array([1, 2, 0, 1, -1], dtype=np.int8)
    with pytest.raises(ValueError, match=r"holds \[2\]"):
        trade_flow(t)


def test_trade_flow_refuses_two_instruments():
    a = trade_frame(_TAPE, symbol="SR3Z6")
    b = trade_frame(_TAPE, symbol="SR3H7")
    with pytest.raises(ValueError, match="order flow is a property of one book"):
        trade_flow(pd.concat([a, b], ignore_index=True))


# --------------------------------------------------------------------------- #
# trade_sign_autocorrelation
# --------------------------------------------------------------------------- #

def test_sign_autocorrelation_of_a_period_four_sequence():
    """``[+1,+1,-1,-1]`` twice.  The mean is zero and the denominator is 8, so
    the lag sums 1, -6, -1, 4 divide straight down to these."""
    a = trade_sign_autocorrelation(signs_frame([1, 1, -1, -1, 1, 1, -1, -1]),
                                   max_lag=4)
    assert a["lag"].tolist() == [1, 2, 3, 4]
    assert a["autocorr"].tolist() == pytest.approx([0.125, -0.75, -0.125, 0.5])
    assert a["n"].tolist() == [7, 6, 5, 4]


def test_sign_autocorrelation_subtracts_the_mean():
    """``[+1,+1,+1,-1]`` has mean 0.5 and denominator 3, so the answers are
    -1/12, -1/6 and -1/4.  Leaving the mean in gives 1/3, -1/3 and -1/3."""
    a = trade_sign_autocorrelation(signs_frame([1, 1, 1, -1]), max_lag=3)
    assert a["autocorr"].tolist() == pytest.approx([-1 / 12, -1 / 6, -1 / 4])
    assert a["n"].tolist() == [3, 2, 1]


def test_an_unknown_aggressor_leaves_the_sequence_rather_than_shifting_it():
    """``[+1, 0, -1, +1]`` becomes ``[+1, -1, +1]``: mean 1/3, denominator 8/3,
    so lag 1 is -2/3 over two pairs.  Keeping the zero as a third element would
    give -0.295 over three pairs and would push every later lag along by one."""
    a = trade_sign_autocorrelation(signs_frame([1, 0, -1, 1]), max_lag=2)
    assert a["autocorr"].tolist() == pytest.approx([-2 / 3, 1 / 6])
    assert a["n"].tolist() == [2, 1]


def test_pairs_that_straddle_a_session_boundary_are_not_counted():
    """Two buys on Tuesday and two sells on Wednesday.  Within a session lag 1
    is perfectly persistent (+0.5 over two pairs); reaching across the night
    would report 0.25 over three, and lag 2 would report -0.5 for a pair of
    trades a day apart."""
    both = pd.concat([signs_frame([1, 1]),
                      signs_frame([-1, -1], date=DATE2, base=T0_D2)],
                     ignore_index=True)
    a = trade_sign_autocorrelation(both, max_lag=2)
    assert a["autocorr"].iloc[0] == pytest.approx(0.5)
    assert a["n"].tolist() == [2, 0]
    assert np.isnan(a["autocorr"].iloc[1])


def test_a_lag_longer_than_the_tape_is_nan_on_no_pairs_not_zero():
    a = trade_sign_autocorrelation(signs_frame([1, -1, 1]), max_lag=5)
    assert a["n"].tolist() == [2, 1, 0, 0, 0]
    assert bool(a["autocorr"].iloc[2:].isna().all())


def test_a_one_sided_tape_has_no_variance_to_correlate():
    a = trade_sign_autocorrelation(signs_frame([1, 1, 1, 1]), max_lag=2)
    assert bool(a["autocorr"].isna().all())
    assert a["n"].tolist() == [3, 2]


def test_sign_autocorrelation_default_reaches_twenty_lags():
    a = trade_sign_autocorrelation(signs_frame([1, -1] * 30))
    assert a["lag"].tolist() == list(range(1, 21))


def test_sign_autocorrelation_rejects_a_lag_below_one():
    with pytest.raises(ValueError, match="max_lag must be at least 1"):
        trade_sign_autocorrelation(signs_frame([1, -1]), max_lag=0)


def test_sign_autocorrelation_on_an_empty_tape_is_an_empty_typed_frame():
    a = trade_sign_autocorrelation(trade_frame([]))
    assert a.empty
    assert list(a.columns) == ["lag", "autocorr", "n"]


# --------------------------------------------------------------------------- #
# flow_summary
# --------------------------------------------------------------------------- #

#: One buy and one sell landing in the walking-mid frame's bars 1 and 3.
_WALK_TAPE = [(12, 96.010, 4, 1), (31, 96.020, 2, -1)]


def test_flow_summary_correlates_each_flow_with_the_same_bars_mid_change():
    """Four bars; the first has no ``d_mid`` and drops out pairwise.

    Over the remaining three, ``ofi`` is (20, 0, 20) against ``d_mid``
    (0.005, 0, 0.005) -- perfectly proportional, so 1.  ``TI`` is (4, 0, -2)
    against the same, which works out at 1/(2*sqrt(7)).
    """
    s = flow_summary(tob_frame(_WALK), trade_frame(_WALK_TAPE), freq="10s")
    assert s["n_bars"] == 4
    assert s["corr_ofi_dmid"] == pytest.approx(1.0)
    assert s["corr_ti_dmid"] == pytest.approx(0.5 / math.sqrt(7.0))
    assert s["ofi_total"] == pytest.approx(40.0)
    assert s["signed_volume_total"] == pytest.approx(2.0)


def test_flow_summary_returns_exactly_the_five_keys():
    s = flow_summary(tob_frame(_WALK), trade_frame(_WALK_TAPE))
    assert set(s) == {"n_bars", "corr_ofi_dmid", "corr_ti_dmid", "ofi_total",
                      "signed_volume_total"}


def test_flow_summary_spans_the_union_of_the_two_grids():
    """A print after the last quote change still gets a bar."""
    late = trade_frame(_WALK_TAPE + [(55, 96.020, 1, 1)])
    s = flow_summary(tob_frame(_WALK), late, freq="10s")
    assert s["n_bars"] == 6                     # bars at 0,10,20,30,40,50 s
    assert s["signed_volume_total"] == pytest.approx(3.0)


def test_flow_summary_refuses_to_pair_one_instruments_book_with_anothers_tape():
    with pytest.raises(ValueError, match="not a measure of anything"):
        flow_summary(tob_frame(_WALK, symbol="SR3Z6"),
                     trade_frame(_WALK_TAPE, symbol="SR3H7"))


def test_flow_summary_on_empty_inputs_reports_nothing_rather_than_zero():
    s = flow_summary(tob_frame([]), trade_frame([]))
    assert s["n_bars"] == 0
    assert math.isnan(s["corr_ofi_dmid"])
    assert math.isnan(s["corr_ti_dmid"])
    assert s["ofi_total"] == 0.0


def test_flow_summary_with_no_trades_still_measures_the_book():
    s = flow_summary(tob_frame(_WALK), trade_frame([]), freq="10s")
    assert s["n_bars"] == 4
    assert s["corr_ofi_dmid"] == pytest.approx(1.0)
    assert s["signed_volume_total"] == 0.0
    assert math.isnan(s["corr_ti_dmid"])         # a constant zero has no variance


# --------------------------------------------------------------------------- #
# the real store -- the layer where 'B' becomes +1
# --------------------------------------------------------------------------- #

def _store(tmp_path, rows, symbol="SR3Z6", date=DATE):
    from RVUtils.MBO.book import build_price_grid, replay_book
    from RVUtils.MBO.store.manifest import ENGINE_VERSION
    from RVUtils.MBO.store.writer import StoreWriter
    from RVUtils.MBO.symbols import parse_symbol
    from tests.test_mbo_book import make

    w = StoreWriter(str(tmp_path), "SR3", date, engine_version=ENGINE_VERSION)
    rec = make(rows)
    grid = build_price_grid(rec["price"].astype(np.int64))
    w.add(symbol, 100, parse_symbol(symbol, 2026), replay_book(rec, grid=grid))
    w.close()
    return str(tmp_path)


def test_flow_reads_the_store_the_reader_writes(tmp_path):
    """The T/F/C pattern the real file prints, replayed and read back.

    Three top-of-book states: 7 lots on the ask, then 4 after the cancel, then 9
    when a new order joins.  The bid never moves, so OFI is the ask queue's
    change with the sign flipped: 0, +3, -5.  One trade prints, three lots,
    buy-initiated -- and it arrives here as ``+1`` because the store writer maps
    the replay's ``'B'``.  Nothing else in this suite exercises that mapping.
    """
    from RVUtils.MBO.store.reader import read_tob, read_trades
    from tests.test_mbo_book import L

    root = _store(tmp_path, [
        (0, "A", "B", 96.000, 10, 1, 0),
        (0, "A", "A", 96.010, 7, 2, L),
        (1_000_000_000, "T", "B", 96.010, 3, 9, 0),
        (1_000_000_000, "F", "A", 96.010, 3, 2, 0),
        (2_000_000_000, "C", "A", 96.010, 3, 2, L),
        (3_000_000_000, "A", "A", 96.010, 5, 3, L),
    ])

    tob = read_tob(root, "SR3", [DATE])
    assert ofi_events(tob).tolist() == [0.0, 3.0, -5.0]

    trades = read_trades(root, "SR3", [DATE])
    f = trade_flow(trades, freq="10s")
    assert len(f) == 1
    assert f.iloc[0]["signed_volume"] == 3
    assert f.iloc[0]["buy_volume"] == 3
    assert f.iloc[0]["n_trades"] == 1
    assert f.iloc[0]["buy_trades"] == 1
    assert f.iloc[0]["sell_trades"] == 0

    s = flow_summary(tob, trades, freq="10s")
    assert s["n_bars"] == 1
    assert s["ofi_total"] == pytest.approx(-2.0)
    assert s["signed_volume_total"] == pytest.approx(3.0)
