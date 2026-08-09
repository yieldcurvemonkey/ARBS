"""Known-answer tests for the trade-cost measures.

Every book and tape here is hand-built and every expected number was worked out
on paper before the code ran.  The prices are those of a listed SR3 butterfly,
which quotes directly in basis points on a half-basis-point grid, so the whole
fixture set lives on quarters and is exact in binary floating point -- an
assertion that fails here fails on arithmetic, not on representation.

The traps these pin, rather than the mechanics:

* the prevailing mid comes off the trade row, so a book state stamped inside the
  trade's own packet cannot be picked up by an as-of join;
* the mid at the horizon is the state at the horizon, including no state at all
  when the book was one-sided or when the data had ended;
* Kyle's lambda differences the mid within a session and counts only the bars in
  which something happened.
"""
from __future__ import annotations

import datetime

import numpy as np
import pandas as pd
import pytest

from RVUtils.MBO.analytics.impact import (
    effective_spread,
    impact_by_size,
    kyle_lambda,
    permanent_temporary,
)
from RVUtils.MBO.book import build_price_grid, replay_book
from RVUtils.MBO.store.manifest import ENGINE_VERSION
from RVUtils.MBO.store.reader import read_tob, read_trades
from RVUtils.MBO.store.writer import StoreWriter
from RVUtils.MBO.symbols import parse_symbol
from tests.test_mbo_book import L, make

DATE = datetime.date(2026, 7, 14)
#: A whole minute boundary, so a 60s bar grid anchored on the epoch starts here.
T0 = pd.Timestamp(1_784_073_600, unit="s", tz="UTC")
FLY = "SR3:BF Z6-H7-M7"


def _ts(offsets):
    return [T0 + pd.Timedelta(seconds=float(s)) for s in offsets]


def _tob(rows, symbol=FLY, date=DATE):
    """rows: ``(offset_s, bid_px, ask_px)``.  NaN on a side means it was empty."""
    df = pd.DataFrame({
        "symbol": symbol,
        "ts_recv": _ts([r[0] for r in rows]),
        "sequence": np.arange(len(rows), dtype=np.uint32),
        "date": date,
        "bid_px": [float(r[1]) for r in rows],
        "ask_px": [float(r[2]) for r in rows],
    })
    df["ts_event"] = df["ts_recv"]
    df["mid"] = (df["bid_px"] + df["ask_px"]) / 2.0
    df["spread"] = df["ask_px"] - df["bid_px"]
    return df


def _trades(rows, symbol=FLY, date=DATE):
    """rows: ``(offset_s, price, size, aggressor, prev_bid, prev_ask)``."""
    df = pd.DataFrame({
        "symbol": symbol,
        "ts_recv": _ts([r[0] for r in rows]),
        "sequence": np.arange(len(rows), dtype=np.uint32),
        "date": date,
        "price": [float(r[1]) for r in rows],
        "size": np.array([r[2] for r in rows], dtype=np.int32),
        "aggressor": np.array([r[3] for r in rows], dtype=np.int8),
        "prev_bid_px": [float(r[4]) for r in rows],
        "prev_ask_px": [float(r[5]) for r in rows],
    })
    df["ts_event"] = df["ts_recv"]
    df["prev_mid"] = (df["prev_bid_px"] + df["prev_ask_px"]) / 2.0
    return df


#: mids 6.00, 6.25, 7.00 at 0 s, 10 s and 30 s.
BOOK = _tob([(0, 5.5, 6.5), (10, 5.75, 6.75), (30, 6.5, 7.5)])

#: One trade lifting the offer and one hitting the bid, both against a market
#: quoted 5.5 / 6.5 -- so both pay the whole one-basis-point spread.
TAPE = _trades([
    (1, 6.5, 5, +1, 5.5, 6.5),
    (2, 5.5, 20, -1, 5.5, 6.5),
])


# --------------------------------------------------------------------------- #
# effective_spread
# --------------------------------------------------------------------------- #

def test_effective_spread_is_twice_the_signed_distance_from_the_prevailing_mid():
    """A trade at the touch of a 1.0 wide market pays 1.0, whichever side it is."""
    out = effective_spread(TAPE, horizons_s=(10.0,))
    assert out["eff"].tolist() == [1.0, 1.0]


def test_effective_spread_signs_the_two_sides_the_same_way():
    """Selling below the mid and buying above it are both a cost, not a gain."""
    out = effective_spread(
        _trades([(1, 6.25, 1, +1, 5.5, 6.5), (2, 5.75, 1, -1, 5.5, 6.5)])
    )
    assert out["eff"].tolist() == [0.5, 0.5]


def test_realised_spread_and_impact_use_the_mid_at_the_horizon():
    """Mid 6.00 at the trade, 6.25 ten seconds later.

    Buy at 6.5:  eff 1.0, real 2*(6.5-6.25) = 0.5, impact 0.5.
    Sell at 5.5: eff 1.0, real 2*(6.25-5.5) = 1.5, impact -0.5 -- the mid rose
    after a sale, so the seller was, briefly, right to be paid.
    """
    out = effective_spread(TAPE, BOOK, horizons_s=(10.0,))
    assert out["real_10s"].tolist() == [0.5, 1.5]
    assert out["impact_10s"].tolist() == [0.5, -0.5]


def test_impact_is_effective_minus_realised_trade_by_trade():
    out = effective_spread(TAPE, BOOK, horizons_s=(10.0, 20.0))
    for h in ("10s", "20s"):
        np.testing.assert_allclose(
            out["eff"] - out[f"real_{h}"], out[f"impact_{h}"], rtol=0, atol=1e-12
        )


def test_the_prevailing_mid_is_not_re_joined_from_the_book():
    """The packet trap, and the reason ``prev_mid`` is stored on the trade.

    The book row at 1 s is the state the trade itself created (the offer it took
    is gone, so the market is 5.5 / 7.0 and the mid is 6.25).  An as-of join on
    time would match it and report this trade at the touch as costing 0.5 rather
    than the 1.0 it actually paid.
    """
    book = _tob([(0, 5.5, 6.5), (1, 5.5, 7.0), (30, 6.5, 7.5)])
    out = effective_spread(TAPE, book, horizons_s=(10.0,))
    assert out["eff"].iloc[0] == 1.0


def test_a_one_sided_book_at_the_horizon_is_nan_not_the_last_two_sided_mid():
    book = _tob([(0, 5.5, 6.5), (10, np.nan, 6.75), (60, 6.0, 7.0)])
    out = effective_spread(TAPE, book, horizons_s=(10.0,))
    assert np.isnan(out["mid_fwd_10s"].iloc[0])
    assert np.isnan(out["real_10s"].iloc[0])
    assert np.isnan(out["impact_10s"].iloc[0])


def test_a_horizon_past_the_end_of_the_data_is_nan_not_the_last_quote():
    """The book ends at 30 s.  A 60 s horizon on a trade at 2 s has no answer."""
    out = effective_spread(TAPE, BOOK, horizons_s=(10.0, 60.0))
    assert out["real_10s"].notna().all()
    assert out["real_60s"].isna().all()


def test_the_forward_mid_takes_a_quote_stamped_exactly_at_the_horizon():
    """``t + h`` is a state of the book, so a quote at that instant counts."""
    book = _tob([(0, 5.5, 6.5), (11, 6.0, 7.0), (60, 6.0, 7.0)])
    out = effective_spread(TAPE, book, horizons_s=(10.0,))
    assert out["mid_fwd_10s"].iloc[0] == 6.5


def test_the_forward_mid_holds_the_last_state_between_quotes():
    """Nothing happened between 10 s and 30 s, so the mid at 20 s is the 10 s one."""
    out = effective_spread(TAPE, BOOK, horizons_s=(20.0,))
    assert out["mid_fwd_20s"].iloc[0] == 6.25


def test_without_a_book_only_the_effective_spread_is_added():
    out = effective_spread(TAPE, None)
    assert "eff" in out.columns
    assert not [c for c in out.columns if c.startswith(("real_", "impact_", "mid_fwd_"))]


def test_an_unknown_aggressor_is_nan_and_the_trade_is_still_returned():
    """Zero would read as a trade at the mid and pull every median toward it."""
    out = effective_spread(_trades([(1, 6.5, 5, 0, 5.5, 6.5)]), BOOK, horizons_s=(10.0,))
    assert len(out) == 1
    assert np.isnan(out["eff"].iloc[0])
    assert np.isnan(out["impact_10s"].iloc[0])


def test_row_order_and_index_survive_the_forward_join():
    """The as-of join needs sorted input; the caller's frame must come back intact."""
    t = _trades([(2, 5.5, 20, -1, 5.5, 6.5), (1, 6.5, 5, +1, 5.5, 6.5)])
    t.index = [17, 4]
    out = effective_spread(t, BOOK, horizons_s=(10.0,))
    assert list(out.index) == [17, 4]
    assert out.loc[17, "real_10s"] == 1.5
    assert out.loc[4, "real_10s"] == 0.5


def test_every_original_column_is_kept():
    out = effective_spread(TAPE, BOOK, horizons_s=(10.0,))
    assert set(TAPE.columns) <= set(out.columns)
    assert len(out) == len(TAPE)


def test_two_instruments_in_the_two_frames_raise():
    other = BOOK.assign(symbol="SR3:BF H7-M7-U7")
    with pytest.raises(ValueError, match="more than one instrument"):
        effective_spread(TAPE, other)


def test_an_empty_tape_returns_an_empty_typed_frame():
    out = effective_spread(pd.DataFrame(), BOOK, horizons_s=(10.0,))
    assert len(out) == 0
    assert out["eff"].dtype == np.float64
    assert out["impact_10s"].dtype == np.float64


def test_an_empty_book_raises_rather_than_returning_nan_columns():
    with pytest.raises(ValueError, match="tob is empty"):
        effective_spread(TAPE, pd.DataFrame())


def test_the_replay_frames_aggressor_convention_is_refused():
    """``ReplayResult.trades`` carries 'B'/'A'; only the store frame is accepted."""
    t = TAPE.copy()
    t["aggressor"] = ["B", "A"]
    with pytest.raises(ValueError, match="read the tape through"):
        effective_spread(t)


def test_a_tape_without_the_prevailing_book_raises():
    with pytest.raises(KeyError, match="prev_mid"):
        effective_spread(TAPE.drop(columns=["prev_mid"]))


def test_a_non_positive_horizon_raises():
    with pytest.raises(ValueError, match="finite and positive"):
        effective_spread(TAPE, BOOK, horizons_s=(0.0,))


# --------------------------------------------------------------------------- #
# impact_by_size
# --------------------------------------------------------------------------- #

#: Sizes 1, 2, 4, 5, 100, 250 against the default edges land in buckets
#: 0, 1, 1, 2, 5, 5 -- two buckets stay empty and the last is open-ended.
SIZED = _trades([
    (1, 6.5, 1, +1, 5.5, 6.5),      # eff 1.0
    (2, 6.5, 2, +1, 5.5, 6.5),      # eff 1.0
    (3, 7.5, 4, +1, 5.5, 7.5),      # eff 2.0
    (4, 6.5, 5, +1, 5.5, 6.5),      # eff 1.0
    (5, 7.5, 100, +1, 5.5, 7.5),    # eff 2.0
    (6, 6.5, 250, +1, 5.5, 6.5),    # eff 1.0
])
SIZED_BOOK = _tob([(0, 5.5, 6.5), (10, 5.75, 6.75), (60, 6.0, 7.0)])


def test_size_buckets_are_left_closed_with_an_open_ended_last():
    out = impact_by_size(SIZED)
    assert out["size_lo"].tolist() == [1, 2, 5, 10, 25, 100]
    assert out["size_hi"].tolist() == [2, 5, 10, 25, 100, np.inf]
    assert out["n"].tolist() == [1, 2, 1, 0, 0, 2]
    assert out["volume"].tolist() == [1, 6, 5, 0, 0, 350]


def test_empty_buckets_are_reported_rather_than_omitted():
    """The frame's shape must not depend on the day, or a sweep goes ragged."""
    out = impact_by_size(SIZED)
    assert len(out) == 6
    assert np.isnan(out["eff_median"].iloc[3])
    assert out["n"].iloc[3] == 0


def test_bucket_medians_are_the_medians_of_the_bucket():
    """Bucket [2, 5) holds eff 1.0 and 2.0, so its median is 1.5.

    Ten seconds on, the mid is 6.25: the two buys at 6.5 realise 0.5 and the two
    at 7.5 realise 2.5, so that bucket's realised median is 1.5 and its impact
    median is 0.0.
    """
    out = impact_by_size(SIZED, SIZED_BOOK, horizon_s=10.0)
    assert out["eff_median"].tolist()[:3] == [1.0, 1.5, 1.0]
    assert out["real_median"].iloc[1] == 1.5
    assert out["impact_median"].iloc[1] == 0.0
    assert out["eff_median"].iloc[5] == 1.5


def test_without_a_book_the_realised_columns_are_present_and_nan():
    out = impact_by_size(SIZED)
    assert list(out.columns) == ["size_lo", "size_hi", "n", "volume",
                                 "eff_median", "real_median", "impact_median"]
    assert out["real_median"].isna().all()
    assert out["eff_median"].notna().sum() == 4


def test_a_size_below_the_first_edge_raises_rather_than_losing_the_volume():
    with pytest.raises(ValueError, match="below the first bin edge"):
        impact_by_size(SIZED, bins=(2, 5, 10))


def test_bins_that_do_not_increase_raise():
    with pytest.raises(ValueError, match="strictly increasing"):
        impact_by_size(SIZED, bins=(1, 5, 5))


def test_an_empty_tape_gives_an_empty_typed_bucket_frame():
    out = impact_by_size(pd.DataFrame())
    assert len(out) == 0
    assert out["n"].dtype == np.int64
    assert out["eff_median"].dtype == np.float64


# --------------------------------------------------------------------------- #
# kyle_lambda
# --------------------------------------------------------------------------- #

def _kyle_book(offsets=(10, 70, 130, 190), date=DATE, level=0.0):
    """Mids 6.0, 5.0, 5.0, 8.0 in four separate 60 s bars.

    The third bar quotes without moving the mid, which is the case a
    trade-conditioned sample would silently drop.
    """
    quotes = [(5.5, 6.5), (4.5, 5.5), (4.5, 5.5), (7.5, 8.5)]
    return _tob([(o, b + level, a + level) for o, (b, a) in zip(offsets, quotes)],
                date=date)


def _kyle_tape(offsets=(80, 200), date=DATE, level=0.0):
    """A 2-lot sale in the second bar and a 2-lot purchase in the fourth."""
    return _trades([
        (offsets[0], 4.5 + level, 2, -1, 4.5 + level, 5.5 + level),
        (offsets[1], 8.5 + level, 2, +1, 7.5 + level, 8.5 + level),
    ], date=date)


def test_kyle_lambda_is_the_hand_computed_regression():
    """Three usable bars: signed volume (-2, 0, +2) against mid moves (-1, 0, +3).

    Sxy = 8, Sxx = 8, so lam = 1 and alpha = 2/3.  The residuals are
    (1/3, -2/3, 1/3), giving SS_res = 2/3 against SS_tot = 26/3, so r2 = 12/13,
    and with one degree of freedom the standard error is sqrt(1/12).
    """
    got = kyle_lambda(_kyle_book(), _kyle_tape(), freq="60s")
    assert got["n_bars"] == 3
    assert got["lam"] == pytest.approx(1.0)
    assert got["alpha"] == pytest.approx(2.0 / 3.0)
    assert got["r2"] == pytest.approx(12.0 / 13.0)
    assert got["t_stat"] == pytest.approx(np.sqrt(12.0))


def test_a_bar_that_quotes_without_trading_is_kept():
    """Dropping it conditions the sample on trading.  Its (0 volume, 0 move) point
    is what argues lambda is smaller than the traded bars alone suggest."""
    with_quiet = kyle_lambda(_kyle_book(), _kyle_tape(), freq="60s")
    without = kyle_lambda(_kyle_book(offsets=(10, 70, 190)),
                          _kyle_tape(offsets=(80, 200)), freq="60s")
    assert with_quiet["n_bars"] == 3
    assert without["n_bars"] == 2
    assert np.isnan(without["lam"])


def test_a_silent_stretch_manufactures_no_bars():
    """Ten minutes of nothing must not become ten (0, 0) observations: they would
    leave lambda where it is and shrink its standard error tenfold."""
    compact = kyle_lambda(_kyle_book(), _kyle_tape(), freq="60s")
    spaced = kyle_lambda(_kyle_book(offsets=(10, 70, 130, 790)),
                         _kyle_tape(offsets=(80, 800)), freq="60s")
    assert spaced["n_bars"] == compact["n_bars"] == 3
    assert spaced["lam"] == pytest.approx(compact["lam"])
    assert spaced["t_stat"] == pytest.approx(compact["t_stat"])


def test_the_mid_is_not_differenced_across_a_session_break():
    """The second session opens a hundred basis points away on no volume at all.

    Differenced globally that gap becomes a fourth observation per session and
    lambda collapses; differenced within the date it is simply not an
    observation, and the pooled fit is the single-session one at twice the size.
    """
    day2 = DATE + datetime.timedelta(days=1)
    off = [o + 86_400 for o in (10, 70, 130, 190)]
    book = pd.concat([_kyle_book(), _kyle_book(offsets=off, date=day2, level=100.0)],
                     ignore_index=True)
    tape = pd.concat([_kyle_tape(),
                      _kyle_tape(offsets=(80 + 86_400, 200 + 86_400), date=day2,
                                 level=100.0)], ignore_index=True)
    got = kyle_lambda(book, tape, freq="60s")
    assert got["n_bars"] == 6
    assert got["lam"] == pytest.approx(1.0)
    assert got["r2"] == pytest.approx(12.0 / 13.0)
    assert got["t_stat"] == pytest.approx(np.sqrt(48.0))


def test_fewer_than_three_bars_is_nan_rather_than_an_exception():
    got = kyle_lambda(_kyle_book(offsets=(10, 70)), _kyle_tape(offsets=(80, 90)),
                      freq="60s")
    assert got["n_bars"] == 1
    assert np.isnan(got["lam"]) and np.isnan(got["t_stat"]) and np.isnan(got["r2"])


def test_a_session_with_no_signed_volume_is_nan_rather_than_an_exception():
    got = kyle_lambda(_kyle_book(), pd.DataFrame(), freq="60s")
    assert got["n_bars"] == 3
    assert np.isnan(got["lam"])


def test_a_missing_session_is_nan_with_no_bars():
    """``read_tob`` returns a column-less frame for a session that is not in the
    store, and a sweep over five hundred instrument-days will hit one."""
    got = kyle_lambda(pd.DataFrame(), pd.DataFrame())
    assert got == {"lam": pytest.approx(np.nan, nan_ok=True), "t_stat":
                   pytest.approx(np.nan, nan_ok=True),
                   "r2": pytest.approx(np.nan, nan_ok=True), "n_bars": 0,
                   "alpha": pytest.approx(np.nan, nan_ok=True)}


def test_kyle_lambda_recovers_a_planted_slope_exactly():
    """Four bars whose mid moves exactly 0.5 per signed lot."""
    book = _tob([(10, 5.5, 6.5), (70, 6.5, 7.5), (130, 8.0, 9.0), (190, 8.5, 9.5)])
    tape = _trades([
        (80, 7.5, 2, +1, 6.5, 7.5),      # bar 1: +2 lots, mid 6.0 -> 7.0
        (140, 9.0, 3, +1, 8.0, 9.0),     # bar 2: +3 lots, mid 7.0 -> 8.5
        (200, 9.5, 1, +1, 8.5, 9.5),     # bar 3: +1 lot,  mid 8.5 -> 9.0
    ])
    got = kyle_lambda(book, tape, freq="60s")
    assert got["n_bars"] == 3
    assert got["lam"] == pytest.approx(0.5)
    assert got["alpha"] == pytest.approx(0.0, abs=1e-12)
    assert got["r2"] == pytest.approx(1.0)


def test_kyle_lambda_refuses_a_book_and_a_tape_from_different_instruments():
    with pytest.raises(ValueError, match="more than one instrument"):
        kyle_lambda(_kyle_book(), _kyle_tape().assign(symbol="SR3:BF H7-M7-U7"))


# --------------------------------------------------------------------------- #
# permanent_temporary
# --------------------------------------------------------------------------- #

#: mids 6.00, 6.25, 7.00, 6.50 at 0 s, 10 s, 30 s and 100 s.
PT_BOOK = _tob([(0, 5.5, 6.5), (10, 5.75, 6.75), (30, 6.5, 7.5), (100, 6.0, 7.0)])

#: Four trades, each paying an effective 1.0, whose permanent components at ten
#: seconds are 0.5, 0.5, 1.0 and 1.0 -- so the permanent and temporary medians
#: are 0.75 and 0.25 and cannot be swapped without the arithmetic showing it.
PT_TAPE = _trades([
    (1, 6.5, 5, +1, 5.5, 6.5),
    (15, 6.0, 5, -1, 6.0, 7.0),
    (25, 7.0, 5, +1, 6.0, 7.0),
    (90, 6.5, 5, -1, 6.5, 7.5),
])


def test_the_decomposition_adds_up_trade_by_trade():
    e = effective_spread(PT_TAPE, PT_BOOK, horizons_s=(10.0,))
    np.testing.assert_allclose(
        e["impact_10s"] + e["real_10s"], e["eff"], rtol=0, atol=1e-12
    )


def test_permanent_and_temporary_are_the_hand_computed_medians():
    """Effective 1.0 four times; permanent 0.5, 0.5, 1.0, 1.0; temporary the rest.

    Three quarters of what these trades paid was the market revising its view and
    a quarter was compensation that came back.
    """
    got = permanent_temporary(PT_TAPE, PT_BOOK, horizon_s=10.0)
    assert got["n"] == 4
    assert got["eff_median"] == pytest.approx(1.0)
    assert got["permanent_median"] == pytest.approx(0.75)
    assert got["temporary_median"] == pytest.approx(0.25)
    assert got["permanent_share"] == pytest.approx(0.75)


def test_a_trade_whose_horizon_runs_off_the_data_leaves_every_median():
    """Not just the permanent one: measuring the three on different subsets would
    make the decomposition stop adding up for a reason nothing in the output shows."""
    tape = pd.concat([PT_TAPE, _trades([(95, 8.5, 5, +1, 5.5, 6.5)])],
                     ignore_index=True)
    got = permanent_temporary(tape, PT_BOOK, horizon_s=10.0)
    assert got["n"] == 4
    assert got["permanent_median"] == pytest.approx(0.75)


def test_permanent_share_is_nan_when_every_trade_printed_at_the_mid():
    """A zero effective spread makes the share a division by zero, not a zero."""
    tape = _trades([(1, 6.0, 5, +1, 5.5, 6.5), (2, 6.0, 5, -1, 5.5, 6.5)])
    got = permanent_temporary(tape, PT_BOOK, horizon_s=10.0)
    assert got["eff_median"] == 0.0
    assert np.isnan(got["permanent_share"])


def test_an_empty_tape_decomposes_to_nothing_rather_than_raising():
    got = permanent_temporary(pd.DataFrame(), PT_BOOK)
    assert got["n"] == 0
    assert np.isnan(got["eff_median"])


def test_the_decomposition_needs_the_book():
    with pytest.raises(ValueError, match="needs the book"):
        permanent_temporary(PT_TAPE, None)


# --------------------------------------------------------------------------- #
# the frames the store actually hands over
# --------------------------------------------------------------------------- #

@pytest.fixture
def store(tmp_path):
    """One instrument-day written and read back through the real store.

    The hand-built frames above pin the arithmetic; this pins the column
    contract, which is the other half of being right.
    """
    rows = [
        (0, "A", "B", 96.000, 10, 1, 0),
        (0, "A", "A", 96.010, 7, 2, L),
        (1_000_000_000, "T", "B", 96.010, 3, 9, 0),      # a buy at the offer
        (1_000_000_000, "F", "A", 96.010, 3, 2, 0),
        (2_000_000_000, "C", "A", 96.010, 3, 2, L),
        (12_000_000_000, "M", "B", 96.005, 10, 1, L),    # mid 96.0075
        (30_000_000_000, "M", "B", 96.0075, 10, 1, L),
    ]
    w = StoreWriter(str(tmp_path), "SR3", DATE, engine_version=ENGINE_VERSION)
    rec = make(rows)
    w.add("SR3Z6", 100, parse_symbol("SR3Z6", 2026),
          replay_book(rec, grid=build_price_grid(rec["price"].astype(np.int64))))
    w.close()
    return str(tmp_path)


def test_it_runs_on_the_frames_the_reader_returns(store):
    tob = read_tob(store, "SR3", [DATE])
    trades = read_trades(store, "SR3", [DATE])
    out = effective_spread(trades, tob, horizons_s=(20.0,))

    assert len(out) == 1
    assert out["eff"].iloc[0] == pytest.approx(0.010)          # 2 * (96.010 - 96.005)
    assert out["mid_fwd_20s"].iloc[0] == pytest.approx(96.0075)
    assert out["real_20s"].iloc[0] == pytest.approx(0.005)
    assert out["impact_20s"].iloc[0] == pytest.approx(0.005)


def test_the_store_frames_carry_the_numeric_aggressor(store):
    trades = read_trades(store, "SR3", [DATE])
    assert trades["aggressor"].iloc[0] == 1
    buckets = impact_by_size(trades, read_tob(store, "SR3", [DATE]), horizon_s=20.0)
    assert buckets["n"].sum() == 1
    assert buckets["volume"].sum() == 3
