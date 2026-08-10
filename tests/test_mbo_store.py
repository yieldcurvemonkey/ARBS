"""Store round-trip tests.

The load-bearing property is that reading the store back gives exactly what the
replay produced.  A store that is 99.99% right produces plausible research, which
is a worse failure than one that is obviously broken.
"""
from __future__ import annotations

import datetime
import os

import numpy as np
import pandas as pd
import pyarrow.parquet as pq
import pytest

from RVUtils.MBO.book import PRICE_SCALE, PriceGrid, build_price_grid, replay_book
from RVUtils.MBO.store.schema import store_path
from RVUtils.MBO.store.writer import StoreWriter, to_tick_index
from RVUtils.MBO.symbols import parse_symbol
from tests.test_mbo_book import L, make

DATE = datetime.date(2026, 7, 14)
VER = "test-1"

SEQ = [
    (1, "A", "B", 96.000, 10, 1, 0),
    (1, "A", "A", 96.010, 7, 2, L),
    (2, "A", "B", 96.005, 4, 3, L),
    (3, "T", "B", 96.010, 3, 9, 0),
    (3, "F", "A", 96.010, 3, 2, 0),
    (4, "C", "A", 96.010, 3, 2, L),
]


def _write(tmp_path, symbol="SR3Z6", rows=SEQ, iid=101):
    rec = make(rows)
    g = build_price_grid(rec["price"].astype(np.int64))
    r = replay_book(rec, grid=g)
    w = StoreWriter(str(tmp_path), "SR3", DATE, engine_version=VER)
    w.add(symbol, iid, parse_symbol(symbol, 2026), r)
    stats = w.close()
    return g, r, stats


def _read(tmp_path, kind, product="SR3"):
    return pq.read_table(store_path(str(tmp_path), kind, product, DATE)).to_pandas()


# --------------------------------------------------------------------------- #
# tick-index conversion
# --------------------------------------------------------------------------- #

def test_tick_index_round_trips_exactly():
    g = PriceGrid(px_min=95_000_000_000, tick=5_000_000, n_slots=1000)
    idx = np.arange(0, 1000, 7, dtype=np.int64)
    px = g.to_price(idx)
    np.testing.assert_array_equal(to_tick_index(px, g), idx.astype(np.int32))


def test_tick_index_maps_an_empty_side_to_minus_one():
    g = PriceGrid(px_min=0, tick=5_000_000, n_slots=10)
    out = to_tick_index(np.array([np.nan, 0.005]), g)
    assert out[0] == -1
    assert out[1] == 1


def test_tick_index_refuses_a_price_off_the_ladder():
    """Silently rounding would put a quote on the wrong rung and look fine."""
    g = PriceGrid(px_min=0, tick=5_000_000, n_slots=10)
    with pytest.raises(ValueError, match="does not sit on the ladder"):
        to_tick_index(np.array([0.0031]), g)


def test_tick_index_round_trips_a_negative_spread_price():
    g = build_price_grid(
        (np.array([-0.055, -0.05, 0.0, 0.05]) * PRICE_SCALE).round().astype(np.int64)
    )
    px = np.array([-0.055, -0.05, 0.0, 0.05])
    np.testing.assert_allclose(g.to_price(to_tick_index(px, g).astype(np.int64)), px)


# --------------------------------------------------------------------------- #
# what lands on disk
# --------------------------------------------------------------------------- #

def test_writer_creates_all_three_tables(tmp_path):
    _write(tmp_path)
    for kind in ("tob", "trades", "catalog"):
        assert os.path.exists(store_path(str(tmp_path), kind, "SR3", DATE))


def test_tob_round_trips_to_the_same_prices(tmp_path):
    g, r, _ = _write(tmp_path)
    t = _read(tmp_path, "tob")
    assert len(t) == len(r.tob)
    for side in ("bid", "ask"):
        got = g.to_price(t[f"{side}_idx"].to_numpy().astype(np.int64))
        np.testing.assert_allclose(got, r.tob[f"{side}_px"].to_numpy(), equal_nan=True)
        np.testing.assert_array_equal(
            t[f"{side}_sz"].to_numpy(), r.tob[f"{side}_sz"].to_numpy()
        )


def test_tob_timestamps_survive_as_nanoseconds(tmp_path):
    _, r, _ = _write(tmp_path)
    t = _read(tmp_path, "tob")
    np.testing.assert_array_equal(
        t["ts_recv"].to_numpy(), r.tob["ts_recv"].astype("int64").to_numpy()
    )


def test_trades_carry_the_book_that_prevailed_before_them(tmp_path):
    g, r, _ = _write(tmp_path)
    t = _read(tmp_path, "trades")
    assert len(t) == 1
    row = t.iloc[0]
    assert row["size"] == 3
    assert row["aggressor"] == 1                      # buy-initiated
    assert g.to_price(np.array([row["prev_bid_idx"]]))[0] == pytest.approx(96.005)
    assert g.to_price(np.array([row["prev_ask_idx"]]))[0] == pytest.approx(96.010)


def test_the_prevailing_book_is_strictly_before_the_trades_own_packet(tmp_path):
    """The trade's own packet removes the ask; the book stored must be the one
    before it, not the one the trade created."""
    g, r, _ = _write(tmp_path)
    t = _read(tmp_path, "trades")
    assert t.iloc[0]["prev_ask_sz"] == 7              # not 4, and not empty


def test_catalog_carries_the_grid_so_tick_indices_can_be_decoded(tmp_path):
    g, r, _ = _write(tmp_path)
    c = _read(tmp_path, "catalog")
    row = c.iloc[0]
    assert row["px_min"] == g.px_min
    assert row["tick"] == g.tick
    assert row["n_slots"] == g.n_slots
    assert row["symbol"] == "SR3Z6"
    assert row["root"] == "SR3"
    assert row["kind"] == "OUTRIGHT"
    assert row["n_trades"] == 1
    assert row["trade_volume"] == 3


def test_catalog_records_the_invariants_rather_than_only_asserting_them(tmp_path):
    _write(tmp_path)
    c = _read(tmp_path, "catalog")
    for col in ("locked_states", "crossed_states", "n_unindexed", "n_out_of_band",
                "trades_outside_book"):
        assert col in c.columns
        assert c.iloc[0][col] == 0


def test_one_row_group_per_symbol(tmp_path):
    w = StoreWriter(str(tmp_path), "SR3", DATE, engine_version=VER)
    for i, sym in enumerate(("SR3Z6", "SR3H7", "SR3M7")):
        rec = make(SEQ)
        g = build_price_grid(rec["price"].astype(np.int64))
        w.add(sym, 100 + i, parse_symbol(sym, 2026), replay_book(rec, grid=g))
    w.close()
    md = pq.read_metadata(store_path(str(tmp_path), "tob", "SR3", DATE))
    assert md.num_row_groups == 3


def test_symbols_with_colons_and_spaces_survive_the_store(tmp_path):
    """SR3 spread symbols are not filesystem-safe, which is one reason the store
    keys on row groups rather than on one file per instrument."""
    sym = "SR3:BF Z6-H7-M7"
    _write(tmp_path, symbol=sym)
    assert _read(tmp_path, "catalog").iloc[0]["symbol"] == sym
    assert _read(tmp_path, "tob")["symbol"].iloc[0] == sym


def test_close_returns_the_stats_the_manifest_needs(tmp_path):
    _, _, stats = _write(tmp_path)
    assert stats["n_symbols"] == 1
    assert stats["n_trades"] == 1
    assert stats["bytes_written"] > 0


# --------------------------------------------------------------------------- #
# atomicity
# --------------------------------------------------------------------------- #

def test_an_aborted_session_leaves_nothing_behind(tmp_path):
    """A build killed halfway must not leave a file resume would call complete."""
    w = StoreWriter(str(tmp_path), "SR3", DATE, engine_version=VER)
    rec = make(SEQ)
    g = build_price_grid(rec["price"].astype(np.int64))
    w.add("SR3Z6", 1, parse_symbol("SR3Z6", 2026), replay_book(rec, grid=g))
    w.abort()
    for kind in ("tob", "trades", "catalog"):
        assert not os.path.exists(store_path(str(tmp_path), kind, "SR3", DATE))
    leftovers = []
    for dirpath, _, files in os.walk(tmp_path):
        leftovers += [f for f in files if f.endswith(".part")]
    assert leftovers == []


def test_the_context_manager_aborts_on_an_exception(tmp_path):
    with pytest.raises(RuntimeError, match="boom"):
        with StoreWriter(str(tmp_path), "SR3", DATE, engine_version=VER) as w:
            rec = make(SEQ)
            g = build_price_grid(rec["price"].astype(np.int64))
            w.add("SR3Z6", 1, parse_symbol("SR3Z6", 2026), replay_book(rec, grid=g))
            raise RuntimeError("boom")
    assert not os.path.exists(store_path(str(tmp_path), "tob", "SR3", DATE))


def test_rewriting_a_session_replaces_it_rather_than_appending(tmp_path):
    _write(tmp_path)
    first = pq.read_metadata(store_path(str(tmp_path), "tob", "SR3", DATE)).num_rows
    _write(tmp_path)
    assert pq.read_metadata(
        store_path(str(tmp_path), "tob", "SR3", DATE)
    ).num_rows == first


def test_a_session_with_no_instruments_still_writes_readable_empty_tables(tmp_path):
    StoreWriter(str(tmp_path), "ZN", DATE, engine_version=VER).close()
    for kind in ("tob", "trades", "catalog"):
        assert len(_read(tmp_path, kind, product="ZN")) == 0
