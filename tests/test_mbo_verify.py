"""Tests for the verification helpers -- including the checker's own failure mode.

A checking tool that is itself wrong reports success and hides the thing it was
built to find.  The first version of ``implied_vs_listed`` thresholded on *grid*
points rather than events, so an instrument that quoted once and was
forward-filled across 84,834 one-second points sailed through and scored a
ten-tick disagreement that said nothing about the engine.  That case is pinned
here.
"""
from __future__ import annotations

import datetime

import numpy as np
import pandas as pd
import pytest

from RVUtils.MBO.book import build_price_grid, replay_book
from RVUtils.MBO.store.manifest import ENGINE_VERSION
from RVUtils.MBO.store.writer import StoreWriter
from RVUtils.MBO.symbols import parse_symbol
from RVUtils.MBO.verify import implied_vs_listed, invariants, session_bars
from tests.test_mbo_book import L, make

DATE = datetime.date(2026, 7, 14)


def _walk(base, n, step_ns=1_000_000_000, tick=0.005, start=0, mult=1):
    """A two-sided book stepping up ``mult`` ticks a second, spread fixed at two.

    ``mult`` is what makes the legs *diverge*.  Two legs walking at the same rate
    leave their difference constant, so a spread quoted once and never updated
    still matches them -- and a test built that way cannot tell a stale
    instrument from a live one, which is precisely the bug it is meant to catch.
    """
    rows = [(start, "A", "B", base, 10, 1, 0),
            (start, "A", "A", base + 2 * tick, 7, 2, L)]
    for i in range(1, n):
        t = start + i * step_ns
        rows.append((t, "M", "B", base + i * mult * tick, 10, 1, 0))
        rows.append((t, "M", "A", base + 2 * tick + i * mult * tick, 7, 2, L))
    return rows


def _one_quote(base, tick=0.005):
    """An instrument that quotes once and then never again."""
    return [(0, "A", "B", base, 5, 1, 0), (0, "A", "A", base + tick, 5, 2, L)]


def _store(tmp_path, specs, product="SR3"):
    w = StoreWriter(str(tmp_path), product, DATE, engine_version=ENGINE_VERSION)
    for i, (sym, rows) in enumerate(specs.items()):
        rec = make(rows)
        g = build_price_grid(rec["price"].astype(np.int64))
        w.add(sym, 100 + i, parse_symbol(sym, 2026), replay_book(rec, grid=g))
    w.close()
    return str(tmp_path)


# --------------------------------------------------------------------------- #
# invariants
# --------------------------------------------------------------------------- #

def test_invariants_reports_one_row_per_instrument_day(tmp_path):
    root = _store(tmp_path, {"SR3Z6": _walk(96.0, 40), "SR3H7": _walk(95.5, 40)})
    iv = invariants(root, "SR3", [DATE])
    assert len(iv) == 2
    assert set(iv["symbol"]) == {"SR3Z6", "SR3H7"}
    assert (iv["crossed_states"] == 0).all()


def test_invariants_expresses_crossings_as_a_fraction(tmp_path):
    root = _store(tmp_path, {"SR3Z6": _walk(96.0, 40)})
    iv = invariants(root, "SR3", [DATE])
    assert iv.iloc[0]["crossed_frac"] == 0.0


def test_invariants_on_an_empty_store_is_empty(tmp_path):
    assert invariants(str(tmp_path), "SR3", [DATE]).empty


# --------------------------------------------------------------------------- #
# leg-implied against listed
# --------------------------------------------------------------------------- #

def _diverging(n=400):
    """Front walks two ticks a second, back one, so the spread walks one.

    The legs must diverge for any of this to be a test: if they moved together
    the difference would be constant and a spread quoted once would match it.
    """
    return {
        "SR3Z6": _walk(96.00, n, mult=2),
        "SR3H7": _walk(95.50, n, mult=1),
        "SR3Z6-SR3H7": _walk(0.495, n, mult=1),
    }


def test_a_consistent_calendar_agrees_with_its_legs(tmp_path):
    """The identity no book knows about: listed mid == front mid - back mid."""
    root = _store(tmp_path, _diverging())
    r = implied_vs_listed(root, "SR3", [DATE], min_events=100)
    assert len(r) == 1
    assert r.iloc[0]["symbol"] == "SR3Z6-SR3H7"
    assert r.iloc[0]["median_abs_err_ticks"] <= 1.0


def test_a_structure_that_quoted_once_is_excluded_not_reported_as_broken(tmp_path):
    """The checker's own bug.

    A single quote forward-fills across the whole grid, so a threshold on grid
    points passes it.  Compared against legs that moved all day it scores a large
    error that is entirely about staleness -- exactly the false alarm that would
    send someone hunting a replay defect that does not exist.
    """
    spec = _diverging()
    spec["SR3Z6-SR3H7"] = _one_quote(0.495)
    root = _store(tmp_path, spec)
    r = implied_vs_listed(root, "SR3", [DATE], min_events=100)
    assert r.empty


def test_lowering_the_threshold_lets_the_stale_structure_back_in(tmp_path):
    """Proves the exclusion is the threshold doing its job, not an unrelated skip."""
    spec = _diverging()
    spec["SR3Z6-SR3H7"] = _one_quote(0.495)
    root = _store(tmp_path, spec)
    r = implied_vs_listed(root, "SR3", [DATE], min_events=1)
    assert len(r) == 1
    assert r.iloc[0]["n_events_listed"] == 1
    assert r.iloc[0]["median_abs_err_ticks"] > 1.0


def test_a_stale_leg_also_disqualifies_the_structure(tmp_path):
    spec = _diverging()
    spec["SR3H7"] = _one_quote(95.50)
    root = _store(tmp_path, spec)
    assert implied_vs_listed(root, "SR3", [DATE], min_events=100).empty


def test_event_counts_are_reported_so_staleness_is_visible(tmp_path):
    root = _store(tmp_path, _diverging())
    r = implied_vs_listed(root, "SR3", [DATE], min_events=10)
    assert r.iloc[0]["n_events_listed"] > 100
    assert r.iloc[0]["n_events_min_leg"] > 100


def test_an_outright_has_no_legs_to_compare_against(tmp_path):
    root = _store(tmp_path, {"SR3Z6": _walk(96.0, 400)})
    assert implied_vs_listed(root, "SR3", [DATE], min_events=10).empty


# --------------------------------------------------------------------------- #
# bars
# --------------------------------------------------------------------------- #

def test_session_bars_are_ohlcv_per_symbol(tmp_path):
    rows = [
        (0, "A", "B", 96.000, 10, 1, 0),
        (0, "A", "A", 96.010, 7, 2, L),
        (1_000_000_000, "T", "B", 96.010, 3, 9, L),
        (2_000_000_000, "T", "A", 96.000, 5, 10, L),
    ]
    root = _store(tmp_path, {"SR3Z6": rows})
    b = session_bars(root, "SR3", [DATE])
    assert len(b) == 1
    assert b.iloc[0]["open"] == pytest.approx(96.010)
    assert b.iloc[0]["close"] == pytest.approx(96.000)
    assert b.iloc[0]["volume"] == 8
    assert b.iloc[0]["n_trades"] == 2


def test_session_bars_on_a_store_with_no_trades_is_empty(tmp_path):
    root = _store(tmp_path, {"SR3Z6": _walk(96.0, 5)})
    assert session_bars(root, "SR3", [DATE]).empty
