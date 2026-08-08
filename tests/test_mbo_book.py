"""Known-answer tests for the MBO replay kernel and the SR3 symbol parser.

Every sequence here is hand-built and its resulting book worked out by hand, so
a failure points at the kernel rather than at the data.  The sequences encode
the rules that the real file actually exercises: the T/F/C match pattern, the
mid-packet transient, snapshot suppression, and negative spread prices.
"""
from __future__ import annotations

import datetime

import numpy as np
import pandas as pd
import pytest

from RVUtils.MBO.book import (
    F_LAST,
    F_SNAPSHOT,
    PRICE_SCALE,
    build_price_grid,
    replay_book,
)
from RVUtils.MBO.symbols import bp_per_price_unit, parse_symbol

MBO_DTYPE = np.dtype(
    [
        ("length", "u1"), ("rtype", "u1"), ("publisher_id", "u2"),
        ("instrument_id", "u4"), ("ts_event", "u8"), ("order_id", "u8"),
        ("price", "i8"), ("size", "u4"), ("flags", "u1"), ("channel_id", "u1"),
        ("action", "S1"), ("side", "S1"), ("ts_recv", "u8"),
        ("ts_in_delta", "i4"), ("sequence", "u4"),
    ]
)

T0 = 1_784_073_600_000_000_000


def make(rows, instrument_id=1):
    """rows: (ts_offset_ns, action, side, price_float, size, order_id, flags)."""
    arr = np.zeros(len(rows), dtype=MBO_DTYPE)
    for i, (dt, action, side, px, sz, oid, flags) in enumerate(rows):
        arr[i]["instrument_id"] = instrument_id
        arr[i]["ts_recv"] = T0 + dt
        arr[i]["ts_event"] = T0 + dt
        arr[i]["action"] = action.encode()
        arr[i]["side"] = side.encode()
        arr[i]["price"] = (
            np.iinfo(np.int64).max if px is None else int(round(px * PRICE_SCALE))
        )
        arr[i]["size"] = sz
        arr[i]["order_id"] = oid
        arr[i]["flags"] = flags
        arr[i]["sequence"] = i
    return arr


L = F_LAST


# --------------------------------------------------------------------------- #
# price grid
# --------------------------------------------------------------------------- #

def test_price_grid_infers_quarter_tick():
    px = np.array([96.0, 96.0025, 96.005, 96.0075], dtype=np.float64)
    g = build_price_grid((px * PRICE_SCALE).round().astype(np.int64))
    assert g.tick == 2_500_000
    assert g.n_slots == 4
    assert g.to_price(np.array([0, 3, -1]))[2] != g.to_price(np.array([0, 3, -1]))[2]  # NaN


def test_price_grid_handles_negative_spread_prices():
    px = np.array([-0.055, -0.05, 0.0, 0.05], dtype=np.float64)
    g = build_price_grid((px * PRICE_SCALE).round().astype(np.int64))
    assert g.px_min == -55_000_000
    assert g.tick == 5_000_000
    np.testing.assert_allclose(g.to_price(np.array([0, 1, 2])), [-0.055, -0.05, -0.045])


def test_price_grid_rejects_an_outlier_that_would_blow_the_ladder():
    px = np.array([96.0, 96.005, 1_000_000.0], dtype=np.float64)
    with pytest.raises(ValueError, match="outlier price"):
        build_price_grid((px * PRICE_SCALE).round().astype(np.int64))


# --------------------------------------------------------------------------- #
# core replay
# --------------------------------------------------------------------------- #

def test_adds_build_top_of_book():
    r = replay_book(make([
        (1, "A", "B", 96.00, 10, 1, 0),
        (1, "A", "A", 96.01, 7, 2, L),
        (2, "A", "B", 96.005, 4, 3, L),      # better bid
    ]))
    tob = r.tob
    assert len(tob) == 2
    assert tob.iloc[0][["bid_px", "bid_sz", "ask_px", "ask_sz"]].tolist() == [96.00, 10, 96.01, 7]
    assert tob.iloc[1][["bid_px", "bid_sz"]].tolist() == [96.005, 4]
    assert r.crossed_events == 0


def test_two_orders_at_one_level_aggregate_and_count():
    r = replay_book(make([
        (1, "A", "B", 96.00, 10, 1, 0),
        (1, "A", "B", 96.00, 5, 2, 0),
        (1, "A", "A", 96.01, 3, 3, L),
    ]))
    row = r.tob.iloc[-1]
    assert row["bid_sz"] == 15
    assert row["bid_ct"] == 2


def test_trade_fill_cancel_decrements_the_level_exactly_once():
    """The pattern the real file prints: T, then F on the resting order, then C.

    Honouring F *and* C would take the level to -2 and leave a phantom bid
    behind; honouring neither would leave the filled order resting.
    """
    r = replay_book(make([
        (1, "A", "A", 96.0075, 8, 100, 0),
        (1, "A", "B", 96.00, 12, 101, L),
        (2, "T", "B", 96.0075, 8, 200, 0),
        (2, "F", "A", 96.0075, 8, 100, 0),
        (3, "C", "A", 96.0075, 8, 100, L),
    ]))
    last = r.tob.iloc[-1]
    assert np.isnan(last["ask_px"])          # the ask is gone, not negative
    assert last["ask_sz"] == 0
    assert last["bid_sz"] == 12              # the bid is untouched
    assert len(r.trades) == 1
    assert r.trades.iloc[0]["size"] == 8
    assert r.trades.iloc[0]["aggressor"] == "B"


def test_mid_packet_transient_is_never_emitted():
    """Inside one packet the book crosses; only the F_LAST state may be seen."""
    r = replay_book(make([
        (1, "A", "B", 96.00, 10, 1, 0),
        (1, "A", "A", 96.01, 10, 2, L),
        (2, "A", "B", 96.02, 5, 3, 0),       # crosses, mid-packet
        (2, "C", "A", 96.01, 10, 2, 0),      # resolved inside the same packet
        (2, "A", "A", 96.03, 6, 4, L),
    ]))
    assert r.crossed_events == 0
    assert (r.tob["bid_px"] < r.tob["ask_px"]).all()
    assert r.tob.iloc[-1]["bid_px"] == 96.02
    assert r.tob.iloc[-1]["ask_px"] == 96.03


def test_modify_moves_price_and_size():
    r = replay_book(make([
        (1, "A", "B", 96.00, 10, 1, L),
        (2, "M", "B", 96.005, 3, 1, L),
    ]))
    last = r.tob.iloc[-1]
    assert last["bid_px"] == 96.005
    assert last["bid_sz"] == 3
    assert last["bid_ct"] == 1


def test_modify_that_worsens_price_leaves_no_ghost_level():
    r = replay_book(make([
        (1, "A", "B", 96.005, 10, 1, 0),
        (1, "A", "B", 96.00, 4, 2, L),
        (2, "M", "B", 95.99, 10, 1, L),      # order 1 drops below order 2
    ]))
    last = r.tob.iloc[-1]
    assert last["bid_px"] == 96.00
    assert last["bid_sz"] == 4


def test_partial_cancel_keeps_the_order_resting():
    r = replay_book(make([
        (1, "A", "B", 96.00, 10, 1, L),
        (2, "C", "B", 96.00, 4, 1, L),
    ]))
    last = r.tob.iloc[-1]
    assert last["bid_sz"] == 6
    assert last["bid_ct"] == 1


def test_clear_empties_the_book():
    r = replay_book(make([
        (1, "A", "B", 96.00, 10, 1, 0),
        (1, "A", "A", 96.01, 10, 2, L),
        (2, "R", "N", None, 0, 0, L),
        (3, "A", "B", 95.50, 2, 3, L),
    ]))
    assert np.isnan(r.tob.iloc[-1]["ask_px"])
    assert r.tob.iloc[-1]["bid_px"] == 95.50
    assert r.tob.iloc[-1]["bid_sz"] == 2


def test_snapshot_rows_seed_the_book_without_emitting():
    """Snapshot ts_recv is unusable, so no row may carry it."""
    snap = F_SNAPSHOT | 8
    r = replay_book(make([
        (0, "A", "B", 96.00, 10, 1, snap),
        (0, "A", "A", 96.01, 10, 2, snap | L),
        (5_000, "A", "B", 96.005, 4, 3, L),
    ]))
    assert r.n_snapshot == 2
    assert len(r.tob) == 1                                   # only the live packet
    assert r.tob.iloc[0]["ts_recv"] == pd.Timestamp(T0 + 5_000, unit="ns", tz="UTC")
    assert r.tob.iloc[0]["ask_px"] == 96.01                  # seeded by the snapshot
    assert r.tob.iloc[0]["bid_px"] == 96.005


def test_unchanged_top_of_book_is_not_re_emitted():
    r = replay_book(make([
        (1, "A", "B", 96.00, 10, 1, 0),
        (1, "A", "A", 96.01, 10, 2, L),
        (2, "A", "B", 95.90, 50, 3, L),      # deep bid: top of book unchanged
    ]))
    assert len(r.tob) == 1


def test_negative_prices_replay():
    """A butterfly book sits either side of zero; nothing may special-case it."""
    r = replay_book(make([
        (1, "A", "B", -0.055, 10, 1, 0),
        (1, "A", "A", -0.045, 8, 2, L),
        (2, "T", "A", -0.055, 3, 3, 0),
        (2, "F", "B", -0.055, 3, 1, 0),
        (3, "C", "B", -0.055, 3, 1, L),
    ]))
    assert r.tob.iloc[0]["bid_px"] == pytest.approx(-0.055)
    assert r.tob.iloc[0]["ask_px"] == pytest.approx(-0.045)
    assert r.tob.iloc[-1]["bid_sz"] == 7
    assert r.trades.iloc[0]["price"] == pytest.approx(-0.055)
    assert r.trades.iloc[0]["aggressor"] == "A"


def test_replay_rejects_mixed_instruments():
    a = make([(1, "A", "B", 96.0, 1, 1, L)], instrument_id=1)
    b = make([(1, "A", "B", 96.0, 1, 2, L)], instrument_id=2)
    with pytest.raises(ValueError, match="one instrument_id"):
        replay_book(np.concatenate([a, b]))


# --------------------------------------------------------------------------- #
# depth grid
# --------------------------------------------------------------------------- #

def test_depth_grid_has_no_look_ahead():
    """The 5,000 ns grid point must not see the packet stamped at 6,000 ns."""
    rows = make([
        (1_000, "A", "B", 96.00, 10, 1, 0),
        (1_000, "A", "A", 96.01, 7, 2, L),
        (6_000, "A", "B", 96.005, 4, 3, L),
    ])
    grid = np.array([T0 + 5_000, T0 + 9_000], dtype=np.int64)
    r = replay_book(rows, grid_ts=grid, n_levels=3)
    d = r.depth
    assert d["bid_px"][0, 0] == 96.00        # before the 6,000 ns improvement
    assert d["bid_px"][1, 0] == 96.005       # after it
    assert bool(d["filled"].all())


def test_depth_grid_reports_multiple_levels_outward_from_the_touch():
    rows = make([
        (1, "A", "B", 96.00, 10, 1, 0),
        (1, "A", "B", 95.995, 20, 2, 0),
        (1, "A", "B", 95.99, 30, 3, 0),
        (1, "A", "A", 96.01, 5, 4, 0),
        (1, "A", "A", 96.015, 15, 5, L),
    ])
    r = replay_book(rows, grid_ts=np.array([T0 + 100], dtype=np.int64), n_levels=3)
    d = r.depth
    np.testing.assert_allclose(d["bid_px"][0], [96.00, 95.995, 95.99])
    np.testing.assert_array_equal(d["bid_sz"][0], [10, 20, 30])
    np.testing.assert_allclose(d["ask_px"][0][:2], [96.01, 96.015])
    np.testing.assert_array_equal(d["ask_sz"][0][:2], [5, 15])
    assert d["ask_px"][0][2] != d["ask_px"][0][2]            # third level is NaN


# --------------------------------------------------------------------------- #
# symbology
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize(
    "symbol,kind,legs,weights",
    [
        ("SR3U6", "OUTRIGHT", ("SR3U6",), (1,)),
        ("SR3Z6-SR3H7", "CALENDAR", ("SR3Z6", "SR3H7"), (1, -1)),
        ("SR3:BF Z6-H7-M7", "BUTTERFLY", ("SR3Z6", "SR3H7", "SR3M7"), (1, -2, 1)),
        ("SR3:BF M7-M8-M9", "BUTTERFLY", ("SR3M7", "SR3M8", "SR3M9"), (1, -2, 1)),
        ("SR3:CF M6U6Z6H7", "CONDOR",
         ("SR3M6", "SR3U6", "SR3Z6", "SR3H7"), (1, -1, -1, 1)),
        ("SR3:DF Z7M8Z8M9", "DOUBLE_FLY",
         ("SR3Z7", "SR3M8", "SR3Z8", "SR3M9"), (1, -3, 3, -1)),
    ],
)
def test_symbol_parsing(symbol, kind, legs, weights):
    p = parse_symbol(symbol, ref_year=2026)
    assert p.kind == kind
    assert p.legs == legs
    assert p.weights == weights


def test_bundle_expands_to_quarterly_legs():
    p = parse_symbol("SR3:AB 01Y U6", ref_year=2026)
    assert p.kind == "BUNDLE"
    assert p.legs == ("SR3U6", "SR3Z6", "SR3H7", "SR3M7")
    assert p.weights == (1, 1, 1, 1)
    assert p.n_contracts == 4

    p3 = parse_symbol("SR3:AB 03Y U6", ref_year=2026)
    assert len(p3.legs) == 12
    assert p3.legs[-1] == "SR3M9"


def test_bundle_spread_and_bundle_fly():
    sb = parse_symbol("SR3:SB PK Z7-Z8", ref_year=2026)
    assert sb.kind == "BUNDLE_SPREAD"
    assert sb.legs == ("SR3Z7", "SR3H8", "SR3M8", "SR3U8",
                       "SR3Z8", "SR3H9", "SR3M9", "SR3U9")
    assert sb.weights == (1, 1, 1, 1, -1, -1, -1, -1)

    sb3 = parse_symbol("SR3:SB 3Y Z7-Z0", ref_year=2026)
    assert len(sb3.legs) == 24

    bb = parse_symbol("SR3:BB Z6-Z7-Z8", ref_year=2026)
    assert bb.kind == "BUNDLE_FLY"
    assert bb.weights[:4] == (1, 1, 1, 1)
    assert bb.weights[4:8] == (-2, -2, -2, -2)
    assert bb.n_contracts == 16


def test_contract_years_resolve_forward_never_backward():
    """SR3H5 in a 2026 file is Mar-2035; the strip never runs into the past."""
    assert parse_symbol("SR3U6", 2026).months[0] == datetime.date(2026, 9, 1)
    assert parse_symbol("SR3H7", 2026).months[0] == datetime.date(2027, 3, 1)
    assert parse_symbol("SR3H0", 2026).months[0] == datetime.date(2030, 3, 1)
    assert parse_symbol("SR3H5", 2026).months[0] == datetime.date(2035, 3, 1)


def test_n_contracts_is_the_cost_multiplier():
    """A butterfly fill delivers four contracts, not three."""
    assert parse_symbol("SR3:BF Z6-H7-M7", 2026).n_contracts == 4
    assert parse_symbol("SR3Z6-SR3H7", 2026).n_contracts == 2
    assert parse_symbol("SR3:DF Z7M8Z8M9", 2026).n_contracts == 8


def test_unmodelled_forms_are_visible_not_silently_dropped():
    p = parse_symbol("SR3U6-TBF3U6", ref_year=2026)
    assert p.kind == "INTERCOMMODITY"
    assert p.legs == ()


# --------------------------------------------------------------------------- #
# price units -- the 100x trap
# --------------------------------------------------------------------------- #

def test_outrights_and_bundles_quote_in_index_points():
    assert parse_symbol("SR3U6", 2026).bp_per_price_unit == 100.0
    assert parse_symbol("SR3:AB 01Y U6", 2026).bp_per_price_unit == 100.0


def test_differential_instruments_quote_in_basis_points():
    """A one-tick butterfly market is 0.5 bp wide, not 50."""
    for sym in ("SR3Z6-SR3H7", "SR3:BF Z6-H7-M7", "SR3:CF M6U6Z6H7",
                "SR3:DF Z7M8Z8M9", "SR3:SB PK Z7-Z8", "SR3:BB Z6-Z7-Z8"):
        assert parse_symbol(sym, 2026).bp_per_price_unit == 1.0, sym


def test_price_unit_agrees_with_the_observed_tick():
    assert bp_per_price_unit("OUTRIGHT", 0.005) == 100.0
    assert bp_per_price_unit("OUTRIGHT", 0.0025) == 100.0
    assert bp_per_price_unit("BUTTERFLY", 0.5) == 1.0
    assert bp_per_price_unit("CALENDAR", 1.0) == 1.0


def test_dollar_value_per_bp_is_25_except_for_bundles():
    """The leg ratios are inside a fly's price; they are not inside a bundle's."""
    assert parse_symbol("SR3U6", 2026).usd_per_bp_per_lot == 25.0
    assert parse_symbol("SR3Z6-SR3H7", 2026).usd_per_bp_per_lot == 25.0
    assert parse_symbol("SR3:BF Z6-H7-M7", 2026).usd_per_bp_per_lot == 25.0
    assert parse_symbol("SR3:DF Z7M8Z8M9", 2026).usd_per_bp_per_lot == 25.0
    # a 1-year bundle averages 4 contracts: 1 bp on the average is 1 bp on each
    assert parse_symbol("SR3:AB 01Y U6", 2026).usd_per_bp_per_lot == 100.0
    assert parse_symbol("SR3:AB 03Y U6", 2026).usd_per_bp_per_lot == 300.0
    # a pack spread is two 4-leg bundles; only one side moves per bp of spread
    assert parse_symbol("SR3:SB PK Z7-Z8", 2026).usd_per_bp_per_lot == 100.0
    assert parse_symbol("SR3:BB Z6-Z7-Z8", 2026).usd_per_bp_per_lot == 100.0


def test_price_unit_disagreement_raises_rather_than_guessing():
    with pytest.raises(ValueError, match="price unit disagreement"):
        bp_per_price_unit("OUTRIGHT", 0.5)
    with pytest.raises(ValueError, match="price unit disagreement"):
        bp_per_price_unit("BUTTERFLY", 0.005)


def test_replay_infers_the_price_scale_from_the_tick():
    outright = replay_book(make([
        (1, "A", "B", 96.000, 10, 1, 0),
        (1, "A", "A", 96.005, 10, 2, L),
    ]))
    assert outright.bp_per_unit == 100.0
    assert outright.tob.iloc[0]["spread"] * outright.bp_per_unit == pytest.approx(0.5)

    fly = replay_book(make([
        (1, "A", "B", 6.0, 10, 1, 0),
        (1, "A", "A", 6.5, 10, 2, L),
    ]))
    assert fly.bp_per_unit == 1.0
    assert fly.tob.iloc[0]["spread"] * fly.bp_per_unit == pytest.approx(0.5)


# --------------------------------------------------------------------------- #
# emit window
# --------------------------------------------------------------------------- #

def test_emit_window_bounds_output_but_not_the_replay():
    """The book still warms up before the window, so the first row is real."""
    rows = make([
        (1_000, "A", "B", 96.00, 10, 1, 0),
        (1_000, "A", "A", 96.01, 7, 2, L),      # before the window
        (9_000, "A", "B", 96.005, 4, 3, L),     # inside it
    ])
    r = replay_book(rows, emit_window=(pd.Timestamp(T0 + 5_000, unit="ns", tz="UTC"),
                                       pd.Timestamp(T0 + 20_000, unit="ns", tz="UTC")))
    assert len(r.tob) == 1
    row = r.tob.iloc[0]
    assert row["bid_px"] == 96.005
    assert row["ask_px"] == 96.01                # inherited from before the window
    assert row["ask_sz"] == 7
