"""Reader and panel tests.

Two panels are provided and the tests pin the property that separates them: the
grid forward-fills and the event frame resamples nothing.  Imposing a grid on
asynchronous series biases measured comovement toward zero as the interval
shrinks, so a lead-lag study must be able to avoid one.
"""
from __future__ import annotations

import datetime

import numpy as np
import pandas as pd
import pytest

from RVUtils.MBO.book import build_price_grid, replay_book
from RVUtils.MBO.store.manifest import ENGINE_VERSION
from RVUtils.MBO.store.panel import panel, panel_events, scale_to
from RVUtils.MBO.store.reader import (
    available_dates,
    read_catalog,
    read_tob,
    read_trades,
    symbols_by_product,
)
from RVUtils.MBO.store.writer import StoreWriter
from RVUtils.MBO.symbols import parse_symbol
from tests.test_mbo_book import L, make

DATE = datetime.date(2026, 7, 14)
T0_S = 1_784_073_600           # T0 in whole seconds


def _rows(base_px, n=6, step_ns=1_000_000_000, start=0):
    """A two-sided book that walks up one tick a second, both sides together.

    Both sides move in the same packet, so the spread stays two ticks and the mid
    moves a whole tick per step.  Moving only the bid would walk it into the ask
    and would shift the mid by half a tick, which is arithmetically right and
    makes for a confusing fixture.
    """
    out = [(start, "A", "B", base_px, 10, 1, 0),
           (start, "A", "A", base_px + 0.01, 7, 2, L)]
    for i in range(1, n):
        t = start + i * step_ns
        out.append((t, "M", "B", base_px + i * 0.005, 10, 1, 0))
        out.append((t, "M", "A", base_px + 0.01 + i * 0.005, 7, 2, L))
    return out


def _store(tmp_path, specs, product="SR3", date=DATE):
    """specs: {symbol: rows}"""
    w = StoreWriter(str(tmp_path), product, date, engine_version=ENGINE_VERSION)
    for i, (sym, rows) in enumerate(specs.items()):
        rec = make(rows)
        g = build_price_grid(rec["price"].astype(np.int64))
        w.add(sym, 100 + i, parse_symbol(sym, 2026), replay_book(rec, grid=g))
    w.close()
    return str(tmp_path)


@pytest.fixture
def two_symbols(tmp_path):
    return _store(tmp_path, {"SR3Z6": _rows(96.00), "SR3H7": _rows(95.50)})


@pytest.fixture
def late_start(tmp_path):
    return _store(tmp_path, {
        "SR3Z6": _rows(96.00, start=0),
        "SR3H7": _rows(95.50, start=10_000_000_000),      # ten seconds later
    })


# --------------------------------------------------------------------------- #
# reader
# --------------------------------------------------------------------------- #

def test_read_tob_decodes_tick_indices_to_prices(two_symbols):
    t = read_tob(two_symbols, "SR3", [DATE])
    assert set(t["symbol"]) == {"SR3Z6", "SR3H7"}
    assert t["bid_px"].min() == pytest.approx(95.50)
    assert (t["spread"] > 0).all()


def test_read_tob_can_return_raw_indices(two_symbols):
    t = read_tob(two_symbols, "SR3", [DATE], decode=False)
    assert "bid_idx" in t.columns
    assert "bid_px" not in t.columns


def test_read_tob_pushes_the_symbol_filter_down(two_symbols):
    t = read_tob(two_symbols, "SR3", [DATE], symbols=["SR3Z6"])
    assert set(t["symbol"]) == {"SR3Z6"}


def test_read_tob_on_a_missing_session_is_empty_not_an_error(two_symbols):
    assert read_tob(two_symbols, "SR3", [datetime.date(2026, 1, 1)]).empty


def test_read_catalog_adds_the_session_date(two_symbols):
    c = read_catalog(two_symbols, "SR3", [DATE])
    assert (c["date"] == DATE).all()
    assert set(c["symbol"]) == {"SR3Z6", "SR3H7"}


def test_available_dates_lists_what_was_built(two_symbols):
    assert available_dates(two_symbols, "tob", "SR3") == [DATE]
    assert available_dates(two_symbols, "tob", "ZN") == []


def test_symbols_by_product_groups_across_roots():
    got = symbols_by_product(["SR3Z6", "ZNU6", "SR3H7"])
    assert got == {"SR3": ["SR3Z6", "SR3H7"], "ZN": ["ZNU6"]}


def test_symbols_by_product_refuses_an_unknown_symbol():
    with pytest.raises(KeyError, match="cannot tell which product"):
        symbols_by_product(["WOBBLE9"])


def test_read_trades_carries_the_prevailing_mid(tmp_path):
    rows = [
        (0, "A", "B", 96.000, 10, 1, 0),
        (0, "A", "A", 96.010, 7, 2, L),
        (1_000_000_000, "T", "B", 96.010, 3, 9, 0),
        (1_000_000_000, "F", "A", 96.010, 3, 2, 0),
        (2_000_000_000, "C", "A", 96.010, 3, 2, L),
    ]
    root = _store(tmp_path, {"SR3Z6": rows})
    t = read_trades(root, "SR3", [DATE])
    assert len(t) == 1
    assert t.iloc[0]["price"] == pytest.approx(96.010)
    assert t.iloc[0]["prev_mid"] == pytest.approx(96.005)


def test_decoding_without_a_catalogue_row_raises_rather_than_guessing(two_symbols,
                                                                     monkeypatch):
    monkeypatch.setattr("RVUtils.MBO.store.reader.read_catalog",
                        lambda *a, **k: pd.DataFrame())
    with pytest.raises(KeyError, match="no catalogue row"):
        read_tob(two_symbols, "SR3", [DATE])


# --------------------------------------------------------------------------- #
# units
# --------------------------------------------------------------------------- #

def test_scale_to_points_is_the_identity():
    assert scale_to("points", "SR3", "OUTRIGHT") == 1.0


def test_scale_to_ticks_counts_ticks():
    assert scale_to("ticks", "ZN", "OUTRIGHT") == pytest.approx(64.0)


def test_scale_to_usd_is_dollars_per_point():
    assert scale_to("usd", "ZN", "OUTRIGHT") == pytest.approx(1000.0)


def test_sr3_bp_scaling_is_exactly_a_hundred():
    """A rate contract's price is 100 - rate, so one point is a hundred bp."""
    assert scale_to("bp", "SR3", "OUTRIGHT") == pytest.approx(100.0)


def test_treasury_bp_scaling_needs_a_dv01():
    with pytest.raises(ValueError, match="no DV01"):
        scale_to("bp", "ZN", "OUTRIGHT")


def test_treasury_bp_scaling_uses_the_dv01_when_supplied():
    """$1,000 per point over $65 per bp: a point of price is about 15.4 bp."""
    got = scale_to("bp", "ZN", "OUTRIGHT", dv01_per_contract=65.0)
    assert got == pytest.approx(1000.0 / 65.0)


def test_a_bp_difference_is_a_yield_move(two_symbols):
    """The level in bp is not a yield; its differences are.  One SR3 tick is
    half a basis point, and that must come out of the panel arithmetic."""
    p = panel(two_symbols, ["SR3Z6"], [DATE], freq="1s", fields=("mid",), units="bp")
    d = p[("mid", "SR3Z6")].diff().dropna()
    moved = d[d != 0]
    assert np.allclose(np.abs(moved), 0.5, atol=1e-9)


# --------------------------------------------------------------------------- #
# grid panel
# --------------------------------------------------------------------------- #

def test_grid_panel_has_a_field_symbol_column_index(two_symbols):
    p = panel(two_symbols, ["SR3Z6", "SR3H7"], [DATE], freq="1s",
              fields=("mid", "spread"))
    assert list(p.columns.names) == ["field", "symbol"]
    assert ("mid", "SR3Z6") in p.columns
    assert ("spread", "SR3H7") in p.columns


def test_grid_panel_forward_fills_between_events(two_symbols):
    p = panel(two_symbols, ["SR3Z6"], [DATE], freq="500ms", fields=("mid",))
    assert p[("mid", "SR3Z6")].isna().sum() == 0
    assert len(p) > 6


def test_grid_panel_is_nan_before_a_symbols_first_quote(late_start):
    p = panel(late_start, ["SR3Z6", "SR3H7"], [DATE], freq="1s", fields=("mid",))
    late = p[("mid", "SR3H7")]
    assert late.iloc[0] != late.iloc[0]           # NaN, not back-filled
    assert late.iloc[-1] == late.iloc[-1]


def test_grid_panel_respects_a_session_window(two_symbols):
    lo = pd.Timestamp(T0_S + 2, unit="s", tz="UTC")
    hi = pd.Timestamp(T0_S + 4, unit="s", tz="UTC")
    p = panel(two_symbols, ["SR3Z6"], [DATE], freq="1s", fields=("mid",),
              session=(lo, hi))
    assert p.index.min() >= lo
    assert p.index.max() < hi


def test_grid_panel_rejects_an_unknown_field(two_symbols):
    with pytest.raises(KeyError, match="unknown fields"):
        panel(two_symbols, ["SR3Z6"], [DATE], fields=("wobble",))


def test_grid_panel_can_use_the_exchange_clock(two_symbols):
    p = panel(two_symbols, ["SR3Z6"], [DATE], freq="1s", fields=("mid",),
              clock="ts_event")
    assert p.index.name == "ts_event"


def test_grid_panel_rejects_an_unknown_clock(two_symbols):
    with pytest.raises(ValueError, match="clock must be"):
        panel(two_symbols, ["SR3Z6"], [DATE], clock="wall")


# --------------------------------------------------------------------------- #
# event panel
# --------------------------------------------------------------------------- #

def test_event_panel_keeps_every_original_observation(two_symbols):
    e = panel_events(two_symbols, ["SR3Z6", "SR3H7"], [DATE])
    t = read_tob(two_symbols, "SR3", [DATE])
    assert len(e) == len(t)


def test_event_panel_invents_nothing(two_symbols):
    """No resampling, so no row exists that was not an event."""
    e = panel_events(two_symbols, ["SR3Z6"], [DATE])
    t = read_tob(two_symbols, "SR3", [DATE], symbols=["SR3Z6"])
    assert sorted(e["ts_recv"].astype("int64")) == sorted(
        t["ts_recv"].astype("int64")
    )


def test_event_panel_is_ordered_by_time_then_sequence(two_symbols):
    e = panel_events(two_symbols, ["SR3Z6", "SR3H7"], [DATE])
    assert e["ts_recv"].is_monotonic_increasing


def test_event_panel_interleaves_the_symbols(two_symbols):
    e = panel_events(two_symbols, ["SR3Z6", "SR3H7"], [DATE])
    assert e["symbol"].nunique() == 2
    assert e["symbol"].iloc[:4].nunique() == 2      # not one symbol then the other


def test_event_panel_scales_units_the_same_way_as_the_grid(two_symbols):
    e = panel_events(two_symbols, ["SR3Z6"], [DATE], units="bp")
    g = panel(two_symbols, ["SR3Z6"], [DATE], freq="1s", fields=("mid",), units="bp")
    assert e["mid"].max() == pytest.approx(g[("mid", "SR3Z6")].max())
