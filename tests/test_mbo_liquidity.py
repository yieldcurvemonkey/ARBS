"""Known-answer tests for the liquidity measures.

Every fixture here is hand-built and every expected number was worked out by
hand, so a failure points at the measure rather than at the data.  The numbers
are chosen to *discriminate*: the book in ``BOOK`` has a tight state that lasted
one second and a wide one that lasted seven, so an event-weighted mean or median
lands on a different number than a time-weighted one and the test says which was
computed.  Two tests at the end run the same measures over a real parquet store
built in ``tmp_path``, so the frames the reader actually produces are exercised
end to end and not only the shapes this file invents.
"""
from __future__ import annotations

import datetime

import numpy as np
import pandas as pd
import pytest

from RVUtils.MBO.analytics.liquidity import (
    depth_profile,
    liquidity_summary,
    quoted_spread,
    resilience,
)
from RVUtils.MBO.book import build_price_grid, replay_book
from RVUtils.MBO.store.manifest import ENGINE_VERSION
from RVUtils.MBO.store.reader import read_tob, read_trades
from RVUtils.MBO.store.writer import StoreWriter
from RVUtils.MBO.symbols import parse_symbol
from tests.test_mbo_book import L, make

DATE = datetime.date(2026, 7, 14)
T0 = pd.Timestamp(1_784_073_600, unit="s", tz="UTC")


def _at(seconds: float) -> pd.Timestamp:
    return T0 + pd.Timedelta(seconds=seconds)


def _window(lo: float, hi: float):
    return (_at(lo), _at(hi))


def _tob(rows, symbol="SR3Z6") -> pd.DataFrame:
    """rows: ``(t_s, bid_px, bid_sz, bid_ct, ask_px, ask_sz, ask_ct)``.

    ``None`` for a price means that side was empty, which the reader spells as a
    NaN price with zero size -- and a NaN spread, which is what makes the state
    one-sided for every measure in the module.
    """
    out = []
    for i, (t, bpx, bsz, bct, apx, asz, act) in enumerate(rows):
        bid = np.nan if bpx is None else float(bpx)
        ask = np.nan if apx is None else float(apx)
        out.append({
            "symbol": symbol, "ts_recv": _at(t), "ts_event": _at(t), "sequence": i,
            "bid_px": bid, "bid_sz": int(bsz), "bid_ct": int(bct),
            "ask_px": ask, "ask_sz": int(asz), "ask_ct": int(act),
            "mid": (bid + ask) / 2.0, "spread": ask - bid,
        })
    return pd.DataFrame(out)


def _trades(rows, symbol="SR3Z6") -> pd.DataFrame:
    """rows: ``(t_s, price, size, aggressor, prev_bid_sz, prev_ask_sz)``."""
    out = []
    for i, (t, px, sz, agg, pbsz, pasz) in enumerate(rows):
        out.append({
            "symbol": symbol, "ts_recv": _at(t), "ts_event": _at(t), "sequence": i,
            "order_id": 1000 + i, "price": float(px), "size": int(sz),
            "aggressor": np.int8(agg),
            "prev_bid_sz": int(pbsz), "prev_ask_sz": int(pasz),
        })
    return pd.DataFrame(out)


#: One tight state that stood a second, a one-sided stretch of two, a wide state
#: that stood seven, and a two-tick state that stood the last two.
#:
#:   t=0   0.005 wide, bid 10 (1 order), ask 20 (2)      1 s
#:   t=1   ask empty                                      2 s
#:   t=3   0.015 wide, bid 30 (3),       ask 10 (1)       7 s
#:   t=10  0.010 wide, bid 40 (4),       ask 60 (6)       2 s  (to the session end)
BOOK = _tob([
    (0, 96.000, 10, 1, 96.005, 20, 2),
    (1, 96.000, 10, 1, None, 0, 0),
    (3, 96.000, 30, 3, 96.015, 10, 1),
    (10, 95.995, 40, 4, 96.005, 60, 6),
])
SESSION = _window(0, 12)
TICK = 0.005


# --------------------------------------------------------------------------- #
# quoted spread
# --------------------------------------------------------------------------- #

def test_quoted_spread_is_time_weighted_not_event_weighted():
    """(0.005*1 + 0.015*7 + 0.010*2) / 10 = 0.013.

    The event-weighted mean of the same three states is 0.010, so this number
    also says which weighting was used.
    """
    got = quoted_spread(BOOK, session=SESSION)
    assert got["spread_mean"] == pytest.approx(0.013)


def test_spread_median_is_the_state_that_stood_half_the_session():
    """Two-sided time is 10 s and 7 of them were 0.015 wide, so the median state
    is the wide one.  The middle *row* of the three is 0.010."""
    got = quoted_spread(BOOK, session=SESSION)
    assert got["spread_median"] == pytest.approx(0.015)


def test_two_sided_frac_and_seconds_expose_the_one_sided_stretch():
    got = quoted_spread(BOOK, session=SESSION)
    assert got["seconds"] == pytest.approx(12.0)
    assert got["two_sided_frac"] == pytest.approx(10.0 / 12.0)
    assert got["n_states"] == 4


def test_without_a_session_the_last_state_weighs_nothing():
    """It stood until something this frame does not contain, so 1 + 2 + 7 + 0 = 10
    seconds live and (0.005*1 + 0.015*7) / 8 = 0.01375 two-sided."""
    got = quoted_spread(BOOK)
    assert got["seconds"] == pytest.approx(10.0)
    assert got["two_sided_frac"] == pytest.approx(0.8)
    assert got["spread_mean"] == pytest.approx(0.01375)


def test_touch_depth_is_weighted_over_the_two_sided_seconds():
    """bid (10*1 + 30*7 + 40*2)/10 = 30, ask (20*1 + 10*7 + 60*2)/10 = 21,
    orders (3*1 + 4*7 + 10*2)/10 = 5.1."""
    got = quoted_spread(BOOK, session=SESSION)
    assert got["bid_sz_at_touch"] == pytest.approx(30.0)
    assert got["ask_sz_at_touch"] == pytest.approx(21.0)
    assert got["orders_at_touch"] == pytest.approx(5.1)


def test_tick_statistics_are_in_ticks_and_over_two_sided_time():
    """0.013 / 0.005 = 2.6 ticks, and the one-tick state held 1 of the 10
    two-sided seconds."""
    got = quoted_spread(BOOK, session=SESSION, tick=TICK)
    assert got["spread_ticks"] == pytest.approx(2.6)
    assert got["frac_time_one_tick"] == pytest.approx(0.1)


def test_tick_statistics_are_none_rather_than_guessed():
    got = quoted_spread(BOOK, session=SESSION)
    assert got["spread_ticks"] is None
    assert got["frac_time_one_tick"] is None


def test_one_tick_survives_a_price_that_is_not_binary_exact():
    """SR3's 0.005 has no exact float64 form, so the one-tick test cannot be an
    equality -- and a book that is one tick wide throughout must still score 1."""
    b = _tob([(0, 96.005, 5, 1, 96.010, 5, 1), (2, 96.010, 5, 1, 96.015, 5, 1)])
    got = quoted_spread(b, session=_window(0, 4), tick=TICK)
    assert got["frac_time_one_tick"] == pytest.approx(1.0)


def test_an_empty_frame_returns_every_key_rather_than_a_shorter_dict():
    got = quoted_spread(BOOK.iloc[:0], session=SESSION, tick=TICK)
    assert set(got) == set(quoted_spread(BOOK, session=SESSION, tick=TICK))
    assert got["n_states"] == 0
    assert got["seconds"] == 0.0
    assert np.isnan(got["spread_mean"])


def test_a_window_with_no_states_is_empty_not_an_average_of_none():
    got = quoted_spread(BOOK, session=_window(100, 200))
    assert got["n_states"] == 0
    assert np.isnan(got["spread_mean"])


def test_a_book_that_is_never_two_sided_reports_no_spread_at_all():
    b = _tob([(0, 96.000, 10, 1, None, 0, 0), (2, 96.000, 12, 1, None, 0, 0)])
    got = quoted_spread(b, session=_window(0, 4))
    assert got["seconds"] == pytest.approx(4.0)
    assert got["two_sided_frac"] == 0.0
    assert np.isnan(got["spread_mean"])
    assert np.isnan(got["bid_sz_at_touch"])


def test_mixing_two_instruments_raises_and_names_them():
    mixed = pd.concat([BOOK, BOOK.assign(symbol="SR3H7")], ignore_index=True)
    with pytest.raises(ValueError, match="SR3H7"):
        quoted_spread(mixed, session=SESSION)


def test_an_undecoded_frame_raises_naming_the_call_that_fixes_it():
    with pytest.raises(ValueError, match="decode=True"):
        quoted_spread(BOOK.drop(columns=["spread"]), session=SESSION)


def test_a_backwards_session_raises():
    with pytest.raises(ValueError, match="not after its start"):
        quoted_spread(BOOK, session=_window(12, 0))


def test_a_non_positive_tick_raises():
    with pytest.raises(ValueError, match="tick must be positive"):
        quoted_spread(BOOK, session=SESSION, tick=0.0)


def test_out_of_order_rows_cannot_produce_negative_time():
    """A shuffled frame is the same book, and every weight must stay positive."""
    shuffled = BOOK.iloc[[2, 0, 3, 1]].reset_index(drop=True)
    assert quoted_spread(shuffled, session=SESSION) == quoted_spread(
        BOOK, session=SESSION)


# --------------------------------------------------------------------------- #
# depth profile
# --------------------------------------------------------------------------- #

def test_depth_profile_has_one_row_per_side():
    d = depth_profile(BOOK, session=SESSION)
    assert list(d["side"]) == ["bid", "ask"]
    assert list(d.columns) == ["side", "mean", "median", "p25", "p75", "p95",
                               "seconds"]
    assert list(d["seconds"]) == pytest.approx([10.0, 10.0])


def test_depth_quantiles_are_time_weighted():
    """Bid sizes 10 (1 s), 30 (7 s), 40 (2 s): the 30 owns everything from the
    tenth percentile to the eightieth, and only p95 reaches the 40."""
    d = depth_profile(BOOK, session=SESSION).set_index("side")
    assert d.loc["bid", "mean"] == pytest.approx(30.0)
    assert d.loc["bid", "p25"] == pytest.approx(30.0)
    assert d.loc["bid", "median"] == pytest.approx(30.0)
    assert d.loc["bid", "p75"] == pytest.approx(30.0)
    assert d.loc["bid", "p95"] == pytest.approx(40.0)


def test_the_two_sides_are_measured_separately():
    """Ask sizes 20 (1 s), 10 (7 s), 60 (2 s): the mean is 21 but the book showed
    10 for most of the session, and only the pair says so."""
    d = depth_profile(BOOK, session=SESSION).set_index("side")
    assert d.loc["ask", "mean"] == pytest.approx(21.0)
    assert d.loc["ask", "median"] == pytest.approx(10.0)
    assert d.loc["ask", "p95"] == pytest.approx(60.0)


def test_a_quantile_is_a_size_that_was_really_displayed():
    """Sizes 10 for three seconds then 20 for one.  The weighted median is 10;
    an unweighted interpolating quantile over the two rows returns 15, which is a
    depth this book never showed."""
    b = _tob([(0, 96.000, 10, 1, 96.005, 10, 1),
              (3, 96.000, 20, 1, 96.005, 20, 1)])
    d = depth_profile(b, session=_window(0, 4)).set_index("side")
    assert d.loc["bid", "median"] == pytest.approx(10.0)


def test_depth_profile_on_an_empty_frame_is_an_empty_typed_frame():
    d = depth_profile(BOOK.iloc[:0])
    assert d.empty
    assert list(d.columns) == ["side", "mean", "median", "p25", "p75", "p95",
                               "seconds"]
    assert d["mean"].dtype == np.float64


def test_depth_profile_refuses_two_instruments():
    mixed = pd.concat([BOOK, BOOK.assign(symbol="SR3H7")], ignore_index=True)
    with pytest.raises(ValueError, match="SR3H7"):
        depth_profile(mixed)


# --------------------------------------------------------------------------- #
# resilience
# --------------------------------------------------------------------------- #

#: The ask is taken down from 40 to 10, refills to 20 four seconds in and to 60
#: at ten.  The bid never moves, so a trade that hit it looks fully recovered.
BOOK_R = _tob([
    (0, 96.000, 100, 1, 96.005, 40, 2),
    (2, 96.000, 100, 1, 96.005, 10, 1),
    (4, 96.000, 100, 1, 96.005, 20, 2),
    (10, 96.000, 100, 1, 96.005, 60, 3),
])
TRADES_R = _trades([
    (1, 96.005, 30, +1, 100, 40),      # buy-initiated: the ask was hit, 40 showing
    (3, 96.000, 5, -1, 100, 10),       # sell-initiated: the bid was hit, 100 showing
])


def test_resilience_ratios_are_the_hit_side_before_and_after():
    """At t+1 the buy's ask shows 10 of the 40 it took (0.25) and the sell's bid
    still shows all 100 (1.0); at t+5 the ask has refilled to 20 (0.5)."""
    r = resilience(BOOK_R, TRADES_R, horizons_s=(1.0, 5.0),
                   session=_window(0, 12)).set_index("horizon_s")
    assert list(r["n"]) == [2, 2]
    assert r.loc[1.0, "mean_ratio"] == pytest.approx(0.625)
    assert r.loc[1.0, "median_ratio"] == pytest.approx(0.625)
    assert r.loc[5.0, "mean_ratio"] == pytest.approx(0.75)
    assert r.loc[5.0, "frac_recovered"] == pytest.approx(0.5)


def test_a_buy_is_measured_against_the_ask():
    """Only the buy, whose ask went 40 -> 20 over five seconds.  Reading the bid
    instead would score this book as fully recovered, because its bid never
    moved."""
    r = resilience(BOOK_R, TRADES_R.iloc[:1], horizons_s=(5.0,),
                   session=_window(0, 12))
    assert r["n"].iloc[0] == 1
    assert r["mean_ratio"].iloc[0] == pytest.approx(0.5)
    assert r["frac_recovered"].iloc[0] == pytest.approx(0.0)


def test_a_sell_is_measured_against_the_bid():
    r = resilience(BOOK_R, TRADES_R.iloc[1:], horizons_s=(5.0,),
                   session=_window(0, 12))
    assert r["n"].iloc[0] == 1
    assert r["mean_ratio"].iloc[0] == pytest.approx(1.0)


def test_a_horizon_past_the_window_drops_the_trade_from_that_row_only():
    """The late trade's one-second point is inside the window and its five-second
    point is not.  Counting it at five seconds would read the closing state as a
    recovery that was never observed."""
    trades = _trades([
        (1, 96.005, 30, +1, 100, 40),
        (9, 96.005, 10, +1, 100, 40),
    ])
    r = resilience(BOOK_R, trades, horizons_s=(1.0, 5.0),
                   session=_window(0, 12)).set_index("horizon_s")
    assert r.loc[1.0, "n"] == 2
    assert r.loc[5.0, "n"] == 1
    # 60 / 40 at t=10 for the late one, 10 / 40 at t=2 for the early one.
    assert r.loc[1.0, "mean_ratio"] == pytest.approx(0.875)


def test_trades_with_nothing_to_recover_are_excluded():
    """An unknown aggressor has no side, and a hit side that showed nothing has
    no denominator.  Either one kept in would arrive as NaN or infinity."""
    trades = _trades([
        (1, 96.005, 30, +1, 100, 40),
        (1, 96.005, 30, 0, 100, 40),      # aggressor unknown
        (1, 96.005, 30, +1, 100, 0),      # the ask showed nothing before it
    ])
    r = resilience(BOOK_R, trades, horizons_s=(1.0,), session=_window(0, 12))
    assert r["n"].iloc[0] == 1
    assert r["mean_ratio"].iloc[0] == pytest.approx(0.25)


def test_resilience_reads_the_state_stamped_exactly_at_the_horizon():
    """A top-of-book row is the book from its own timestamp onward, so t+1 = 2
    must see the state written at 2 (ask 10), not the one before it (ask 40)."""
    r = resilience(BOOK_R, TRADES_R.iloc[:1], horizons_s=(1.0,),
                   session=_window(0, 12))
    assert r["mean_ratio"].iloc[0] == pytest.approx(0.25)


def test_resilience_without_trades_is_an_empty_typed_frame():
    r = resilience(BOOK_R, TRADES_R.iloc[:0], horizons_s=(1.0, 5.0))
    assert r.empty
    assert list(r.columns) == ["horizon_s", "n", "median_ratio", "mean_ratio",
                               "frac_recovered"]


def test_resilience_keeps_a_row_per_horizon_when_nothing_qualifies():
    trades = _trades([(1, 96.005, 30, 0, 100, 40)])       # aggressor unknown
    r = resilience(BOOK_R, trades, horizons_s=(1.0, 5.0), session=_window(0, 12))
    assert list(r["horizon_s"]) == [1.0, 5.0]
    assert list(r["n"]) == [0, 0]
    assert r["mean_ratio"].isna().all()


def test_resilience_refuses_a_tape_from_another_instrument():
    with pytest.raises(ValueError, match="SR3H7"):
        resilience(BOOK_R, TRADES_R.assign(symbol="SR3H7"),
                   horizons_s=(1.0,), session=_window(0, 12))


# --------------------------------------------------------------------------- #
# summary
# --------------------------------------------------------------------------- #

def test_liquidity_summary_carries_the_spread_keys_unchanged():
    s = liquidity_summary(BOOK, TRADES_R, session=SESSION, tick=TICK)
    q = quoted_spread(BOOK, session=SESSION, tick=TICK)
    assert all(s[k] == pytest.approx(q[k]) for k in q if q[k] is not None)
    assert s["spread_ticks"] == pytest.approx(2.6)


def test_liquidity_summary_splits_volume_by_the_true_aggressor():
    """30 lots bought and 5 sold: MBO carries the aggressing side, so neither
    number is a tick-rule guess."""
    s = liquidity_summary(BOOK, TRADES_R, session=SESSION)
    assert s["n_trades"] == 2
    assert s["volume"] == 35
    assert s["buy_volume"] == 30
    assert s["sell_volume"] == 5
    assert s["mean_trade_size"] == pytest.approx(17.5)


def test_an_unknown_aggressor_counts_in_the_total_and_neither_side():
    trades = _trades([
        (1, 96.005, 30, +1, 100, 40),
        (2, 96.005, 8, 0, 100, 40),
    ])
    s = liquidity_summary(BOOK, trades, session=SESSION)
    assert s["volume"] == 38
    assert s["buy_volume"] == 30
    assert s["sell_volume"] == 0


def test_a_session_bounds_the_tape_as_well_as_the_book():
    s = liquidity_summary(BOOK, TRADES_R, session=_window(0, 2))
    assert s["n_trades"] == 1
    assert s["volume"] == 30


def test_summary_without_trades_still_returns_the_spread():
    s = liquidity_summary(BOOK, TRADES_R.iloc[:0], session=SESSION)
    assert s["n_trades"] == 0
    assert s["volume"] == 0
    assert s["spread_mean"] == pytest.approx(0.013)


# --------------------------------------------------------------------------- #
# through the real store
# --------------------------------------------------------------------------- #

@pytest.fixture
def store(tmp_path):
    """One instrument whose ask is hit and then refills, written to parquet.

    ``t=0``  bid 100 @ 96.000, ask 40 @ 96.005
    ``t=1``  a buy takes 30 of the ask, leaving 10
    ``t=2``  the ask refills to 20
    ``t=6``  and to 60
    """
    rows = [
        (0, "A", "B", 96.000, 100, 1, 0),
        (0, "A", "A", 96.005, 40, 2, L),
        (1_000_000_000, "T", "B", 96.005, 30, 9, 0),
        (1_000_000_000, "C", "A", 96.005, 30, 2, L),
        (2_000_000_000, "A", "A", 96.005, 10, 3, L),
        (6_000_000_000, "A", "A", 96.005, 40, 4, L),
    ]
    rec = make(rows)
    w = StoreWriter(str(tmp_path), "SR3", DATE, engine_version=ENGINE_VERSION)
    w.add("SR3Z6", 100, parse_symbol("SR3Z6", 2026),
          replay_book(rec, grid=build_price_grid(rec["price"].astype(np.int64))))
    w.close()
    return str(tmp_path)


def test_the_measures_consume_what_the_reader_produces(store):
    """Ask depth (40*1 + 10*1 + 20*4 + 60*4) / 10 = 37 lots, one tick throughout,
    and one buy of 30."""
    tob = read_tob(store, "SR3", [DATE])
    trades = read_trades(store, "SR3", [DATE])
    s = liquidity_summary(tob, trades, session=_window(0, 10), tick=TICK)
    assert s["n_states"] == 4
    assert s["two_sided_frac"] == pytest.approx(1.0)
    assert s["spread_mean"] == pytest.approx(0.005)
    assert s["frac_time_one_tick"] == pytest.approx(1.0)
    assert s["bid_sz_at_touch"] == pytest.approx(100.0)
    assert s["ask_sz_at_touch"] == pytest.approx(37.0)
    assert s["orders_at_touch"] == pytest.approx(3.2)
    assert s["n_trades"] == 1
    assert s["buy_volume"] == 30


def test_resilience_reads_the_stored_previous_book(store):
    """The store already carries the book before each print, so the 40 lots the
    buy hit need no join: at t+1 the ask shows 20 of them and at t+5 it shows 60."""
    tob = read_tob(store, "SR3", [DATE])
    trades = read_trades(store, "SR3", [DATE])
    assert int(trades["prev_ask_sz"].iloc[0]) == 40
    r = resilience(tob, trades, horizons_s=(1.0, 5.0),
                   session=_window(0, 10)).set_index("horizon_s")
    assert list(r["n"]) == [1, 1]
    assert r.loc[1.0, "median_ratio"] == pytest.approx(0.5)
    assert r.loc[5.0, "median_ratio"] == pytest.approx(1.5)
    assert r.loc[5.0, "frac_recovered"] == pytest.approx(1.0)
