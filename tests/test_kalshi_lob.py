"""Tests for Kalshi LOB reconstruction pipeline."""
import datetime
import pandas as pd
import pytest

from OBI.kalshi_lob.storage import LOBStorage
from OBI.kalshi_lob.reconstructor import (
    parse_snapshot, apply_delta, emit_book, reconstruct_market, verify_reconstruction,
)


class TestReconstruction:
    """Test the reconstruction algorithm from the paper (Section 4)."""

    def test_parse_snapshot(self):
        df = pd.DataFrame({
            "side": ["yes", "yes", "no"],
            "price": [0.40, 0.41, 0.60],
            "qty": [10, 5, 8],
        })
        book = parse_snapshot(df)
        assert book["yes"][0.40] == 10
        assert book["yes"][0.41] == 5
        assert book["no"][0.60] == 8

    def test_apply_delta_add(self):
        book = {"yes": {0.42: 8}, "no": {}}
        book = apply_delta(book, "yes", 0.42, 1)
        assert book["yes"][0.42] == 9

    def test_apply_delta_add_new_level(self):
        book = {"yes": {0.42: 8}, "no": {}}
        book = apply_delta(book, "yes", 0.40, 3)
        assert book["yes"][0.40] == 3

    def test_apply_delta_remove(self):
        book = {"yes": {0.40: 10, 0.42: 8}, "no": {}}
        book = apply_delta(book, "yes", 0.40, -5)
        assert book["yes"][0.40] == 5

    def test_apply_delta_remove_to_zero(self):
        """When depth goes to 0, the level is removed (paper Section 4)."""
        book = {"yes": {0.40: 5}, "no": {}}
        book = apply_delta(book, "yes", 0.40, -5)
        assert 0.40 not in book["yes"]

    def test_apply_delta_clamp_negative(self):
        """Depth cannot go below 0: max(0, old + delta) per formula (2)."""
        book = {"yes": {0.40: 3}, "no": {}}
        book = apply_delta(book, "yes", 0.40, -10)
        assert 0.40 not in book["yes"]

    def test_paper_example(self):
        """Reproduce the exact example from the paper's Table (Section 3.1).

        Tick 1: Snapshot — YES side at 40c:10, 41c:5, 42c:8, 43c:0, 44c:3
        Tick 2: Delta 42c: +1  → 42c becomes 9
        Tick 3: Delta 40c: +3  → 40c becomes 13
        Tick 4: Delta 40c: -5  → 40c becomes 8
        """
        snap = pd.DataFrame({
            "side": ["yes"] * 5,
            "price": [0.40, 0.41, 0.42, 0.43, 0.44],
            "qty": [10, 5, 8, 0, 3],
        })
        book = parse_snapshot(snap)
        assert book["yes"][0.40] == 10
        assert book["yes"][0.42] == 8
        assert 0.43 not in book["yes"]

        book = apply_delta(book, "yes", 0.42, 1)
        assert book["yes"][0.42] == 9

        book = apply_delta(book, "yes", 0.40, 3)
        assert book["yes"][0.40] == 13

        book = apply_delta(book, "yes", 0.40, -5)
        assert book["yes"][0.40] == 8

    def test_reconstruct_market(self):
        """Full reconstruction with one snapshot and several deltas."""
        snap_ts = pd.Timestamp("2026-06-04 10:00:00", tz="UTC")
        snapshots = pd.DataFrame({
            "ts": [snap_ts] * 3,
            "side": ["yes", "yes", "no"],
            "price": [0.50, 0.51, 0.50],
            "qty": [100, 50, 80],
        })

        deltas = pd.DataFrame({
            "ts": [
                pd.Timestamp("2026-06-04 10:00:01", tz="UTC"),
                pd.Timestamp("2026-06-04 10:00:01", tz="UTC"),
                pd.Timestamp("2026-06-04 10:00:02", tz="UTC"),
            ],
            "side": ["yes", "no", "yes"],
            "price": [0.50, 0.50, 0.50],
            "delta": [10, -20, -110],
        })

        rows = reconstruct_market("TEST-MKT", snapshots, deltas)
        assert len(rows) > 0

        df = pd.DataFrame(rows)
        assert set(df["side"].unique()).issubset({"yes", "no"})

        last_ts = df["ts"].max()
        last_book = df[df["ts"] == last_ts]
        yes_at_50 = last_book[(last_book["side"] == "yes") & (last_book["price"] == 0.50)]
        assert yes_at_50.empty  # 100 + 10 - 110 = 0, should be removed

    def test_emit_book(self):
        book = {"yes": {0.50: 100, 0.51: 50}, "no": {0.50: 80}}
        rows = emit_book(book, "TEST", pd.Timestamp.now(tz="UTC"))
        assert len(rows) == 3
        sides = [r["side"] for r in rows]
        assert sides.count("yes") == 2
        assert sides.count("no") == 1

    def test_verify_reconstruction_perfect(self):
        book = {"yes": {0.50: 100, 0.51: 50}, "no": {0.50: 80}}
        snap = pd.DataFrame({
            "side": ["yes", "yes", "no"],
            "price": [0.50, 0.51, 0.50],
            "qty": [100, 50, 80],
        })
        result = verify_reconstruction(book, snap)
        assert result["mismatches"] == 0
        assert result["match_rate"] == 1.0

    def test_verify_reconstruction_with_drift(self):
        book = {"yes": {0.50: 105, 0.51: 50}, "no": {0.50: 80}}
        snap = pd.DataFrame({
            "side": ["yes", "yes", "no"],
            "price": [0.50, 0.51, 0.50],
            "qty": [100, 50, 80],
        })
        result = verify_reconstruction(book, snap)
        assert result["mismatches"] == 1


class TestStorage:
    def test_roundtrip(self, tmp_path):
        storage = LOBStorage(tmp_path)
        today = datetime.date.today()

        storage.buffer_delta({
            "market_ticker": "TEST-MKT",
            "ts": datetime.datetime.now(datetime.timezone.utc),
            "side": "yes",
            "price": 0.50,
            "delta": 5.0,
            "seq": 1,
        })
        storage.flush(today)

        df = storage.read_deltas(today)
        assert len(df) == 1
        assert df.iloc[0]["market_ticker"] == "TEST-MKT"

    def test_lob_write_read(self, tmp_path):
        storage = LOBStorage(tmp_path)
        today = datetime.date.today()

        rows = [
            {"market_ticker": "T", "ts": datetime.datetime.now(datetime.timezone.utc),
             "side": "yes", "price": 0.50, "qty": 100},
        ]
        storage.flush_lob(rows, today)

        df = storage.read_lob(today, market_ticker="T")
        assert len(df) == 1
        assert df.iloc[0]["qty"] == 100.0

    def test_list_dates(self, tmp_path):
        storage = LOBStorage(tmp_path)
        today = datetime.date.today()
        storage.buffer_delta({
            "market_ticker": "X", "ts": datetime.datetime.now(datetime.timezone.utc),
            "side": "yes", "price": 0.5, "delta": 1.0, "seq": 0,
        })
        storage.flush(today)
        dates = storage.list_dates("deltas")
        assert today in dates
