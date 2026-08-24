r"""What the short-mirror repair must not COST, and the read it must not raise on.

Companion to ``tests/test_computed_ts_short_mirror.py``, which covers the repair
itself: a mirror holding less than Parquet no longer shortens the answer. This
file covers three things that fix does not.

1. IT MUST NOT MAKE EVERY EOD READ PARSE PARQUET.
   ``pd.bdate_range`` is what nearly every caller builds reference points from,
   and it drops only WEEKENDS - it hands you the ~9 market holidays a year that
   no tier will ever hold. So ``covered >= requested`` fails on a perfectly
   complete mirror, every EOD read takes the short-mirror branch, and each one
   parses Parquet across its whole span to be told nothing. It never converges,
   because the missing date does not exist to be filled. Measured on a
   three-year window with a complete mirror and six holidays among the reference
   points:

       without the guard   1 Parquet trip and 0.62-0.76 s on EVERY read
       with the guard      0 trips, 0.002 s

2. IT MUST NOT RAISE ON A TZ-AWARE EOD READ.
   ``TB.utils.build_reference_points`` returns tz-aware 17:00 America/New_York
   datetimes for freq in {eod, nyc_eod, chi_eod, ldn_eod}, and the Parquet tier
   indexes EOD rows naive. The resulting ``TypeError`` is pre-existing - a cold
   mirror raises with the repair both on and off - but the repair routes the
   SHORT case down the same path, so leaving it would trade a truncation for a
   raise. Nobody would have seen the raise: every production caller swallows it
   into an empty result, so the whole batch is discarded and repriced.

3. THE CAUSE MUST STOP BEING SILENT.
   A read-only DuckDB handle returns 0 from every upsert and raises nothing, so
   the caller's ``try/except`` never fires. That is how the short mirrors were
   created in the first place.
"""

from __future__ import annotations

import datetime
import logging

import pytest

from Caching.computed_timeseries_store import ComputedTimeseriesStore

SYMBOL = "IRS::GSQUANT-RL::USD-OIS::partialmirror"

# A working week, so no weekend/holiday accident decides a test.
D = [datetime.date(2012, 1, 2) + datetime.timedelta(days=i) for i in range(5)]


@pytest.fixture()
def tiers(tmp_path):
    """Parquet holding all five days; the mirror holding only the last three.

    Built by writing everything, then deleting the two early days FROM THE
    MIRROR ONLY - which is exactly the shape a locked-mirror run leaves behind.
    """
    base = tmp_path / "ts"
    db = tmp_path / "mirror.duckdb"
    store = ComputedTimeseriesStore(base_dir=str(base), duckdb_path=str(db))
    store.append_many_rows(rows_by_symbol={
        SYMBOL: [(d, "rate", 4.0 + i) for i, d in enumerate(D)],
    })
    con = store._duckdb_cache._conn
    con.execute("delete from computed_timeseries where trading_date < ?", [D[2]])
    assert con.execute(
        "select count(*) from computed_timeseries where symbol = ?", [SYMBOL],
    ).fetchone()[0] == 3, "the fixture must leave the mirror SHORT, not empty"
    return base, db


def _store(base, db):
    return ComputedTimeseriesStore(base_dir=str(base), duckdb_path=str(db))


def _spy(store):
    """Count trips to the Parquet + L2 tier."""
    calls = {"n": 0}
    real = store._read_with_l2_prefetch

    def counted(**kwargs):
        calls["n"] += 1
        return real(**kwargs)

    store._read_with_l2_prefetch = counted
    return calls


# ------------------------------------------------------------------ #
#         1. the repair must stay free on a healthy read             #
# ------------------------------------------------------------------ #


def test_a_fully_covered_read_costs_no_parquet_trip(tmp_path):
    """The fast path is the common path and must be untouched."""
    base, db = tmp_path / "ts", tmp_path / "m.duckdb"
    store = ComputedTimeseriesStore(base_dir=str(base), duckdb_path=str(db))
    store.append_many_rows(rows_by_symbol={SYMBOL: [(d, "rate", 4.0) for d in D]})

    fresh = _store(base, db)
    calls = _spy(fresh)
    rows = fresh.read_rows(symbol=SYMBOL, reference_points=D,
                           intraday=False, allow_partial=True)
    assert len(rows) == 5
    assert calls["n"] == 0


def test_a_MARKET_HOLIDAY_in_the_window_costs_no_parquet_trip(tmp_path):
    """THE regression this guard exists for, and it is the common case.

    Every ``bdate_range`` contains market holidays and no tier holds them, so
    without the guard a complete mirror is "short" on every read and pays a
    full-span Parquet parse to be told nothing - for ever, because the missing
    date does not exist to be filled.
    """
    base, db = tmp_path / "ts", tmp_path / "m.duckdb"
    store = ComputedTimeseriesStore(base_dir=str(base), duckdb_path=str(db))
    store.append_many_rows(rows_by_symbol={SYMBOL: [(d, "rate", 4.0) for d in D]})

    holiday = datetime.date(2012, 1, 16)          # a Monday nobody traded
    fresh = _store(base, db)
    calls = _spy(fresh)
    rows = fresh.read_rows(symbol=SYMBOL, reference_points=D + [holiday],
                           intraday=False, allow_partial=True)

    assert len(rows) == 5, "the holiday has no row anywhere, which is correct"
    assert calls["n"] == 0, (
        "a date with no Parquet partition must be settled by a stat, not by "
        "parsing the whole window"
    )


def test_the_batch_reader_gets_the_same_guard(tmp_path):
    """``read_many_symbols`` is the path every EOD IRS read actually takes."""
    base, db = tmp_path / "ts", tmp_path / "m.duckdb"
    store = ComputedTimeseriesStore(base_dir=str(base), duckdb_path=str(db))
    store.append_many_rows(rows_by_symbol={SYMBOL: [(d, "rate", 4.0) for d in D]})

    holiday = datetime.date(2012, 1, 16)
    fresh = _store(base, db)
    calls = _spy(fresh)
    out = fresh.read_many_symbols(symbols=[SYMBOL], reference_points=D + [holiday],
                                  intraday=False, allow_partial=True)
    assert len(out[SYMBOL]) == 5
    assert calls["n"] == 0


def test_a_date_missing_everywhere_is_asked_for_at_most_once(tmp_path):
    """Otherwise a permanently absent date costs a trip on every read, for ever."""
    base, db = tmp_path / "ts", tmp_path / "m.duckdb"
    store = ComputedTimeseriesStore(base_dir=str(base), duckdb_path=str(db))
    store.append_many_rows(rows_by_symbol={SYMBOL: [(d, "rate", 4.0) for d in D]})
    store._duckdb_cache._conn.execute(
        "delete from computed_timeseries where trading_date < ?", [D[2]])
    nowhere = datetime.date(2012, 1, 16)

    fresh = _store(base, db)
    calls = _spy(fresh)
    for _ in range(3):
        fresh.read_rows(symbol=SYMBOL, reference_points=D + [nowhere],
                        intraday=False, allow_partial=True)
    assert calls["n"] <= 1, (
        f"Parquet was consulted {calls['n']} times for a date it does not hold"
    )


def test_an_EMPTY_partition_directory_is_asked_for_at_most_once(tmp_path):
    """The other way a date is permanently absent: the directory exists, empty.

    An interrupted write leaves ``date=YYYY-MM-DD`` behind with no parquet in it,
    so the cheap stat says "Parquet might have this" and the expensive read says
    "no". Without remembering that answer, the date costs a full parse on every
    read for the life of the process.
    """
    base, db = tmp_path / "ts", tmp_path / "m.duckdb"
    store = ComputedTimeseriesStore(base_dir=str(base), duckdb_path=str(db))
    store.append_many_rows(rows_by_symbol={SYMBOL: [(d, "rate", 4.0) for d in D]})
    store._duckdb_cache._conn.execute(
        "delete from computed_timeseries where trading_date < ?", [D[2]])

    from Caching.timeseries_cache import _resolve_symbol_dir
    hollow = datetime.date(2012, 1, 16)
    (_resolve_symbol_dir(base, SYMBOL) / f"date={hollow:%Y-%m-%d}").mkdir(parents=True)

    fresh = _store(base, db)
    calls = _spy(fresh)
    for _ in range(3):
        rows = fresh.read_rows(symbol=SYMBOL, reference_points=D + [hollow],
                               intraday=False, allow_partial=True)
    assert [r[0] for r in rows] == D, "the real days must still be recovered"
    assert calls["n"] <= 1, (
        f"Parquet was parsed {calls['n']} times for a partition holding nothing"
    )


# ------------------------------------------------------------------ #
#      ...and the repair itself must still work with the guard       #
# ------------------------------------------------------------------ #


def test_an_INTERIOR_hole_is_still_recovered(tmp_path):
    """The guard must not shortcut a gap Parquet CAN fill.

    An interior hole is the case first/last coverage reasoning cannot see, and
    it does not raise: the as-of search serves the previous print, so a whole
    session silently inherits the day before.
    """
    base, db = tmp_path / "ts", tmp_path / "m.duckdb"
    store = ComputedTimeseriesStore(base_dir=str(base), duckdb_path=str(db))
    store.append_many_rows(rows_by_symbol={
        SYMBOL: [(d, "rate", 4.0 + i) for i, d in enumerate(D)],
    })
    store._duckdb_cache._conn.execute(
        "delete from computed_timeseries where trading_date in (?, ?)", [D[1], D[2]],
    )

    rows = _store(base, db).read_rows(symbol=SYMBOL, reference_points=D,
                                      intraday=False, allow_partial=True)
    assert [r[0] for r in rows] == D
    assert [r[2] for r in rows] == [4.0, 5.0, 6.0, 7.0, 8.0]


def test_the_recovered_series_is_in_reference_point_order(tiers):
    """Callers frame these rows straight onto an index.

    The merge appends the mirror's extras after Parquet's rows, so order is a
    property worth pinning rather than assuming.
    """
    rows = _store(*tiers).read_rows(symbol=SYMBOL, reference_points=D,
                                    intraday=False, allow_partial=True)
    dates = [r[0] for r in rows]
    assert sorted(dates) == D
    assert len(dates) == len(set(dates)), f"duplicated dates in {dates}"


# ------------------------------------------------------------------ #
#            2. a tz-aware EOD read must be served, not raise        #
# ------------------------------------------------------------------ #


def test_a_TZ_AWARE_eod_reference_point_is_served_not_dropped(tiers):
    """The repair would otherwise have traded a truncation for an empty batch."""
    from TB.utils import build_reference_points

    rps = build_reference_points(start=D[0], end=D[-1], freq="nyc_eod", timestamps=None)
    assert rps and rps[0].tzinfo is not None, "the premise: these are tz-aware"

    rows = _store(*tiers).read_rows(symbol=SYMBOL, reference_points=rps,
                                    intraday=False, allow_partial=True)
    assert [r[2] for r in rows] == [4.0, 5.0, 6.0, 7.0, 8.0], (
        f"expected all five days from a tz-aware EOD read, got {rows}"
    )


def test_a_TZ_AWARE_read_of_a_COLD_symbol_is_served_too(tmp_path):
    """The pre-existing half, fixed by the same normalisation.

    A symbol with no mirror rows already took this path before the repair and
    already raised there - the likely cause of the note recorded at
    ``RVUtils/ConvexityRV/citi_fig89.py:96`` that ``freq="nyc_eod"`` returns an
    EMPTY frame on this source.
    """
    from TB.utils import build_reference_points

    base, db = tmp_path / "ts", tmp_path / "m.duckdb"
    store = ComputedTimeseriesStore(base_dir=str(base), duckdb_path=str(db))
    store.append_many_rows(rows_by_symbol={
        SYMBOL: [(d, "rate", 4.0 + i) for i, d in enumerate(D)]})
    store._duckdb_cache._conn.execute("delete from computed_timeseries")

    rps = build_reference_points(start=D[0], end=D[-1], freq="nyc_eod", timestamps=None)
    rows = _store(base, db).read_rows(symbol=SYMBOL, reference_points=rps,
                                      intraday=False, allow_partial=True)
    assert [r[2] for r in rows] == [4.0, 5.0, 6.0, 7.0, 8.0]


def test_a_TZ_AWARE_read_agrees_with_the_plain_date_read(tiers):
    """The control: normalising the bound must not change WHICH rows come back.

    A comparison, so it is blind to any fault that breaks BOTH sides identically
    - collapsing the end bound onto the start, for instance, loses the same row
    from each and this still passes. The tests above assert exact values and are
    what catch that; this one only pins that the tz-aware and plain-date routes
    do not DIVERGE.
    """
    from TB.utils import build_reference_points

    rps = build_reference_points(start=D[0], end=D[-1], freq="nyc_eod", timestamps=None)
    aware = _store(*tiers).read_rows(symbol=SYMBOL, reference_points=rps,
                                     intraday=False, allow_partial=True)
    naive = _store(*tiers).read_rows(symbol=SYMBOL, reference_points=D,
                                     intraday=False, allow_partial=True)
    assert [r[2] for r in aware] == [r[2] for r in naive]


# ------------------------------------------------------------------ #
#                  3. the cause must stop being silent               #
# ------------------------------------------------------------------ #


def test_a_read_only_mirror_says_it_is_dropping_every_write(tmp_path, caplog):
    """The silence that created the short mirrors in the first place.

    A read-only handle returns 0 from both upserts and raises nothing, so the
    caller's try/except never fires. Fourteen committed notebooks carry the
    matching "DuckDB unavailable (file locked)" line in their saved output.
    """
    import duckdb

    from Caching.duckdb_timeseries_cache import DuckDBTimeseriesCache

    db = tmp_path / "ro.duckdb"
    duckdb.connect(str(db)).close()
    ComputedTimeseriesStore(base_dir=str(tmp_path / "ts"), duckdb_path=str(db))

    cache = DuckDBTimeseriesCache(db_path=str(db), read_only=True)
    with caplog.at_level(logging.WARNING, logger="Caching.duckdb_timeseries_cache"):
        assert cache.upsert_rows(SYMBOL, [(D[0], "rate", 4.0)]) == 0
        assert cache.upsert_rows(SYMBOL, [(D[1], "rate", 4.0)]) == 0

    said = [r for r in caplog.records if "READ-ONLY" in r.getMessage()]
    assert len(said) == 1, (
        f"expected exactly one warning per handle, got {len(said)} - a warm "
        f"upserts thousands of times and a per-write warning is a log nobody reads"
    )
