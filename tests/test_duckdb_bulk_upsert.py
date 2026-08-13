r"""`upsert_many_rows` as ONE set-based statement, and what that must not change.

The old implementation issued one `INSERT OR REPLACE` per row. DuckDB is columnar
and row-at-a-time DML is its worst case: measured against a copy of the real
700k-row table, 2,000 rows took 16.22 s, 8,000 took 272.90 s and 17,000 took
751.19 s - 8.5x the rows for 46x the time, and worse as the table grows. py-spy
put a live ten-year UST warm inside this call, with 12.5 minutes of every chunk
spent here, and its rate had decayed from 28 to 72 minutes per chunk.

The set-based version does the same work in 0.07 s. These tests are about the two
things that change when you replace ordered row-by-row DML with one statement:

* **Last-wins on a repeated key.** `executemany` applied rows in order, so a key
  appearing twice ended at its final value. A single statement has no such
  ordering, and the de-duplication is what preserves it rather than picking
  arbitrarily.
* **The registered payload must not outlive the call.** A DuckDB registered name
  is connection-global; leaving `_upsert_payload` behind would shadow a real
  table of that name for every later query on the connection.
"""

from __future__ import annotations

import datetime

import pytest

from Caching.duckdb_timeseries_cache import DuckDBTimeseriesCache

D = datetime.date


@pytest.fixture()
def cache(tmp_path):
    return DuckDBTimeseriesCache(db_path=str(tmp_path / "t.duckdb"))


def _all(cache):
    with cache._lock:
        return cache._conn.execute(
            "select symbol, trading_date, column_name, value "
            "from computed_timeseries order by symbol, trading_date"
        ).fetchall()


def test_a_fresh_insert_lands(cache):
    cache.upsert_many_rows({"A": [(D(2024, 1, 2), "YTM", 1.0), (D(2024, 1, 3), "YTM", 2.0)]})
    assert _all(cache) == [
        ("A", D(2024, 1, 2), "YTM", 1.0),
        ("A", D(2024, 1, 3), "YTM", 2.0),
    ]


def test_an_existing_key_is_replaced_not_duplicated(cache):
    cache.upsert_many_rows({"A": [(D(2024, 1, 2), "YTM", 1.0)]})
    cache.upsert_many_rows({"A": [(D(2024, 1, 2), "YTM", 9.99)]})
    assert _all(cache) == [("A", D(2024, 1, 2), "YTM", 9.99)]


def test_the_same_key_twice_in_one_payload_keeps_the_last(cache):
    """`executemany` applied rows in order, so the second write won. One statement
    has no ordering, so this is exactly the semantic the de-duplication carries -
    and without it DuckDB raises on the duplicate key instead."""
    cache.upsert_many_rows({"B": [(D(2024, 1, 2), "YTM", 1.0), (D(2024, 1, 2), "YTM", 7.0)]})
    assert _all(cache) == [("B", D(2024, 1, 2), "YTM", 7.0)]


def test_a_replacement_may_carry_a_different_column_name(cache):
    """The primary key is (symbol, trading_date); column_name is a label that
    rides along and must be replaced with the row, not merged."""
    cache.upsert_many_rows({"A": [(D(2024, 1, 3), "YTM", 2.0)]})
    cache.upsert_many_rows({"A": [(D(2024, 1, 3), "DV01", 4.4)]})
    assert _all(cache) == [("A", D(2024, 1, 3), "DV01", 4.4)]


def test_many_symbols_in_one_call(cache):
    rows = {f"S{i}": [(D(2024, 1, 2), "YTM", float(i))] for i in range(50)}
    assert cache.upsert_many_rows(rows) == 50
    assert len(_all(cache)) == 50


def test_the_return_count_is_rows_offered_not_rows_written(cache):
    """Unchanged from the old behaviour: it counts the payload, and a payload with
    a repeated key still reports both. Callers use it for logging, and changing it
    quietly would move a number someone reads."""
    n = cache.upsert_many_rows({"B": [(D(2024, 1, 2), "YTM", 1.0), (D(2024, 1, 2), "YTM", 7.0)]})
    assert n == 2
    assert len(_all(cache)) == 1


def test_an_empty_payload_is_a_no_op(cache):
    assert cache.upsert_many_rows({}) == 0
    assert cache.upsert_many_rows({"A": []}) == 0
    assert _all(cache) == []


def test_the_payload_view_does_not_outlive_the_call(cache):
    """A registered name is connection-global. Left behind, `_upsert_payload`
    shadows any real table of that name for every later query."""
    cache.upsert_many_rows({"A": [(D(2024, 1, 2), "YTM", 1.0)]})
    with cache._lock:
        names = {r[0] for r in cache._conn.execute("show tables").fetchall()}
    assert "_upsert_payload" not in names


def test_a_failed_upsert_leaves_no_partial_write(cache):
    """The rollback path, and that it still cleans up the registration."""
    cache.upsert_many_rows({"A": [(D(2024, 1, 2), "YTM", 1.0)]})
    with pytest.raises(Exception):
        # value is NOT NULL, so this fails inside the statement
        cache.upsert_many_rows({"A": [(D(2024, 1, 3), "YTM", None)]})
    assert _all(cache) == [("A", D(2024, 1, 2), "YTM", 1.0)]
    with cache._lock:
        names = {r[0] for r in cache._conn.execute("show tables").fetchall()}
    assert "_upsert_payload" not in names


def test_a_read_only_cache_still_refuses(tmp_path):
    live = DuckDBTimeseriesCache(db_path=str(tmp_path / "t.duckdb"))
    live.upsert_many_rows({"A": [(D(2024, 1, 2), "YTM", 1.0)]})
    live.close()
    ro = DuckDBTimeseriesCache(db_path=str(tmp_path / "t.duckdb"), read_only=True)
    assert ro.upsert_many_rows({"A": [(D(2024, 1, 3), "YTM", 5.0)]}) == 0
    assert len(_all(ro)) == 1
