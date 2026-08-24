"""A short DuckDB mirror must not shorten a read.

`ComputedTimeseriesStore` keeps two EOD tiers: Parquet, which is the source of
truth, and a DuckDB mirror in front of it. Under `allow_partial=True` the reader
computed coverage, found the mirror short, and returned the mirror's rows
anyway -- never consulting Parquet.

`allow_partial=True` is not an edge case. Every production caller passes it:
both timeseries routers, USTFutures, IRSwaptions, and five call sites in
TimeseriesBuilder. `allow_partial=False` survived only as the signature default.

Measured on the live store before the fix, same symbol, same reference points:

    IRS::GSQUANT-RL::USD-OIS::c6739ceb...
      parquet              5,078 rows   2006-01-03 .. 2026-03-27
      allow_partial=True   3,573 rows   2012-01-03 .. 2026-03-27
      allow_partial=False  5,078 rows

and it SELF-ARMS: a symbol the mirror has never seen reads correctly, because
`_read_from_duckdb` returns None rather than a short list -- but the backfill on
that path writes back exactly the window read, so the next wider read is short.
One 2015-2016 subrange read of a zero-mirror symbol banked 504 rows; the next
full-history read returned 504 instead of 4,077. A census at the time put ~2,900
symbols already short, roughly half the EOD estate.

These tests are hermetic: a temp store, a mirror deliberately truncated, no
production data touched.
"""

import datetime
import types

import pytest

from Caching.computed_timeseries_store import ComputedTimeseriesStore, _merge_preferring

SYMBOL = "IRS::TEST::USD-OIS::deadbeef"
COLUMN = "USD-OIS 10Y OUTRIGHT RATE"


def _days(n, start=datetime.date(2020, 1, 1)):
    return [start + datetime.timedelta(days=i) for i in range(n)]


def _rows(days, base=4.0):
    return [(d, COLUMN, base + i * 0.001) for i, d in enumerate(days)]


@pytest.fixture
def store(tmp_path):
    return ComputedTimeseriesStore(base_dir=tmp_path)


def _truncate_mirror(store, symbol, keep_from):
    """Delete the mirror's rows before ``keep_from`` -- Parquet keeps everything.

    This is the shape the live store was in: a mirror that postdates the data.
    """
    cache = store._duckdb_cache
    assert cache is not None, "this test needs the DuckDB tier"
    con = getattr(cache, "_conn", None)
    assert con is not None, "could not reach the DuckDB connection"
    con.execute(
        "delete from computed_timeseries where symbol = ? and trading_date < ?",
        [symbol, keep_from],
    )


def _clear_mirror(store, symbol):
    """Empty the mirror for one symbol -- Parquet keeps everything.

    Not expressible with ``_truncate_mirror``: its filter is ``< keep_from``,
    so passing the first day deletes nothing at all. A test that meant "the
    mirror has never seen this symbol" and reached for ``days[0]`` got a FULL
    mirror and passed without exercising anything.
    """
    cache = store._duckdb_cache
    assert cache is not None, "this test needs the DuckDB tier"
    con = getattr(cache, "_conn", None)
    assert con is not None, "could not reach the DuckDB connection"
    con.execute("delete from computed_timeseries where symbol = ?", [symbol])


# ── the defect ───────────────────────────────────────────────────────

def test_a_short_mirror_no_longer_shortens_the_read(store):
    days = _days(40)
    store.append_many_rows(rows_by_symbol={SYMBOL: _rows(days)})
    _truncate_mirror(store, SYMBOL, days[25])          # mirror keeps the last 15

    got = store.read_rows(symbol=SYMBOL, reference_points=days, intraday=False,
                          skip_current_eod=False, allow_partial=True)
    assert len(got) == len(days), (
        f"allow_partial=True returned {len(got)} of {len(days)} -- the mirror was "
        "served instead of Parquet"
    )
    assert min(r[0] for r in got) == days[0]


def test_the_two_flags_now_agree(store):
    """The discriminator. Before the fix these differed by 1,505 rows in prod."""
    days = _days(40)
    store.append_many_rows(rows_by_symbol={SYMBOL: _rows(days)})
    _truncate_mirror(store, SYMBOL, days[25])

    partial = store.read_rows(symbol=SYMBOL, reference_points=days, intraday=False,
                              skip_current_eod=False, allow_partial=True)
    strict = store.read_rows(symbol=SYMBOL, reference_points=days, intraday=False,
                             skip_current_eod=False, allow_partial=False)
    assert len(partial) == len(strict)


def test_the_batch_reader_too(store):
    """read_many_symbols had the same arm, spelled `elif allow_partial`."""
    days = _days(40)
    store.append_many_rows(rows_by_symbol={SYMBOL: _rows(days)})
    _truncate_mirror(store, SYMBOL, days[25])

    got = store.read_many_symbols(symbols=[SYMBOL], reference_points=days,
                                  intraday=False, skip_current_eod=False,
                                  allow_partial=True)
    assert len(got[SYMBOL]) == len(days)


def test_the_self_arm_is_defused(store):
    """A narrow read must not make a later wide read short.

    This is the measured escalation: one subrange read banked 504 rows and the
    next full-history read returned 504 instead of 4,077.
    """
    days = _days(40)
    store.append_many_rows(rows_by_symbol={SYMBOL: _rows(days)})
    _clear_mirror(store, SYMBOL)                       # mirror has never seen it

    narrow = store.read_rows(symbol=SYMBOL, reference_points=days[10:20],
                             intraday=False, skip_current_eod=False, allow_partial=True)
    assert len(narrow) == 10, "the narrow read itself must be correct"

    wide = store.read_rows(symbol=SYMBOL, reference_points=days, intraday=False,
                           skip_current_eod=False, allow_partial=True)
    assert len(wide) == len(days), (
        f"the narrow read armed the mirror: {len(wide)} of {len(days)}"
    )


def test_a_fully_mirrored_symbol_is_unchanged(store):
    """The control: nothing should change when the mirror is complete."""
    days = _days(40)
    store.append_many_rows(rows_by_symbol={SYMBOL: _rows(days)})
    got = store.read_rows(symbol=SYMBOL, reference_points=days, intraday=False,
                          skip_current_eod=False, allow_partial=True)
    assert len(got) == len(days)


def test_it_says_so(store, caplog):
    """Silence is why this ran unnoticed for five months."""
    days = _days(40)
    store.append_many_rows(rows_by_symbol={SYMBOL: _rows(days)})
    _truncate_mirror(store, SYMBOL, days[25])

    import Caching.computed_timeseries_store as mod
    mod._SHORT_MIRROR_WARNED.clear()
    with caplog.at_level("WARNING"):
        store.read_rows(symbol=SYMBOL, reference_points=days, intraday=False,
                        skip_current_eod=False, allow_partial=True)
    assert any("mirror held" in r.getMessage() for r in caplog.records), \
        [r.getMessage()[:80] for r in caplog.records]
    mod._SHORT_MIRROR_WARNED.clear()


# ── the merge rule ───────────────────────────────────────────────────

def test_parquet_wins_every_shared_key():
    """The mirror is the tier observed to be short; it must never displace."""
    parquet = [(datetime.date(2020, 1, 1), COLUMN, 1.0)]
    mirror = [(datetime.date(2020, 1, 1), COLUMN, 9.9),
              (datetime.date(2020, 1, 2), COLUMN, 2.0)]
    out = _merge_preferring(parquet, mirror, intraday=False)
    assert (datetime.date(2020, 1, 1), COLUMN, 1.0) in out
    assert (datetime.date(2020, 1, 1), COLUMN, 9.9) not in out
    assert len(out) == 2


def test_the_merge_keys_on_column_too():
    """A symbol may carry several columns; keying on the date alone drops them."""
    day = datetime.date(2020, 1, 1)
    out = _merge_preferring([(day, "a", 1.0)], [(day, "b", 2.0)], intraday=False)
    assert len(out) == 2, out


def test_the_merge_survives_an_empty_side():
    assert _merge_preferring([], [(1, "a", 1.0)], intraday=False) == [(1, "a", 1.0)]
    assert _merge_preferring([(1, "a", 1.0)], [], intraday=False) == [(1, "a", 1.0)]
    assert _merge_preferring([], None, intraday=False) == []


# -- the repair must not cost a network round trip ---------------------

def test_the_repair_reads_parquet_but_not_supabase(store, monkeypatch):
    """Correctness from local disk, not from production.

    The fall-through fires on roughly half the EOD estate. Routing it through
    the full L2 path would fix the read and quietly put a Supabase range
    prefetch on every one of those reads, so the fall-through passes
    ``remote=False``. Parquet is the source of truth; consulting it is a glob.
    """
    import Caching.computed_timeseries_store as mod

    calls = []
    fake = types.SimpleNamespace(
        prefetch_range=lambda *a, **k: calls.append(a),
        pull_days_batch=lambda *a, **k: [],
        pull_day=lambda *a, **k: False,
    )
    monkeypatch.setattr(mod, "_get_computed_ts_sync", lambda *a, **k: fake)

    days = _days(40)
    # Parquet is deliberately short by one day as well. With Parquet complete
    # there is nothing for L2 to be asked about, the reader returns before the
    # remote step by design, and this test passes even with the guard removed --
    # it went green under exactly that mutation before this line was added.
    store.append_many_rows(rows_by_symbol={SYMBOL: _rows(days[:-1])})
    _truncate_mirror(store, SYMBOL, days[25])

    got = store.read_rows(symbol=SYMBOL, reference_points=days, intraday=False,
                          skip_current_eod=False, allow_partial=True)
    assert len(got) == len(days) - 1, "the short mirror was not repaired from Parquet"
    assert calls == [], f"the repair called Supabase prefetch_range {len(calls)}x"


def test_the_batch_repair_does_not_either(store, monkeypatch):
    import Caching.computed_timeseries_store as mod

    calls = []
    fake = types.SimpleNamespace(
        prefetch_range=lambda *a, **k: calls.append(a),
        pull_days_batch=lambda *a, **k: [],
        pull_day=lambda *a, **k: False,
    )
    monkeypatch.setattr(mod, "_get_computed_ts_sync", lambda *a, **k: fake)

    days = _days(40)
    # Parquet is deliberately short by one day as well. With Parquet complete
    # there is nothing for L2 to be asked about, the reader returns before the
    # remote step by design, and this test passes even with the guard removed --
    # it went green under exactly that mutation before this line was added.
    store.append_many_rows(rows_by_symbol={SYMBOL: _rows(days[:-1])})
    _truncate_mirror(store, SYMBOL, days[25])

    got = store.read_many_symbols(symbols=[SYMBOL], reference_points=days,
                                  intraday=False, skip_current_eod=False,
                                  allow_partial=True)
    assert len(got[SYMBOL]) == len(days) - 1
    assert calls == [], f"the batch repair called prefetch_range {len(calls)}x"


def test_an_empty_mirror_keeps_its_l2_fetch(store, monkeypatch):
    """The guard adds a Parquet read; it must not remove an L2 fetch.

    When the mirror holds nothing for a symbol this is the pre-existing
    fallback path, and it went to L2 before the repair. Suppressing that too
    would be a silent loss of the only mechanism that imports rows this machine
    has never held.
    """
    import Caching.computed_timeseries_store as mod

    calls = []
    fake = types.SimpleNamespace(
        prefetch_range=lambda *a, **k: calls.append(a),
        pull_days_batch=lambda *a, **k: [],
        pull_day=lambda *a, **k: False,
    )
    monkeypatch.setattr(mod, "_get_computed_ts_sync", lambda *a, **k: fake)

    days = _days(40)
    # Parquet is short by one day too, so there is something for L2 to be asked
    # about. With Parquet complete the reader returns before the remote step by
    # design ("if everything is locally available, skip remote entirely"), and
    # the test would pass or fail for the wrong reason.
    store.append_many_rows(rows_by_symbol={SYMBOL: _rows(days[:-1])})
    _clear_mirror(store, SYMBOL)                       # mirror empty for it

    store.read_rows(symbol=SYMBOL, reference_points=days, intraday=False,
                    skip_current_eod=False, allow_partial=True)
    assert calls, "the empty-mirror path lost its L2 prefetch"
