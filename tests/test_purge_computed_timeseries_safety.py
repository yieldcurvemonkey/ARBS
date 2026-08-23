"""The purge must never destroy the good tier and keep the bad one.

`scripts/purge_computed_timeseries.py` deletes rows from both computed-TS tiers.
It used to delete the Parquet partitions FIRST and then run a DuckDB statement
filtered on a column called `ts`. The schema's column is `trading_date`
(Caching/duckdb_timeseries_cache.py:45), so any run carrying --start or --end
raised a Binder Error on the SELECT -- after Parquet was already gone.

Parquet is the source of truth; the DuckDB mirror is a cache in front of it. So
the failure destroyed the authoritative tier and left the stale one serving
reads, which is the exact outcome the script's own comment says it exists to
prevent. Without --start/--end the clause was just `symbol LIKE ?`, which is why
it survived.
"""

import datetime
import importlib.util
import os
import sys

import pytest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SYMBOL = "IRS::TEST::PURGE::cafebabe"
COLUMN = "USD-OIS 10Y OUTRIGHT RATE"


@pytest.fixture(scope="module")
def purge():
    spec = importlib.util.spec_from_file_location(
        "purge_computed_timeseries_under_test",
        os.path.join(REPO_ROOT, "scripts", "purge_computed_timeseries.py"),
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def populated(tmp_path):
    from Caching.computed_timeseries_store import ComputedTimeseriesStore

    days = [datetime.date(2020, 1, 1) + datetime.timedelta(days=i) for i in range(20)]
    store = ComputedTimeseriesStore(base_dir=tmp_path)
    store.append_many_rows(
        rows_by_symbol={SYMBOL: [(d, COLUMN, 4.0 + i) for i, d in enumerate(days)]}
    )
    if store._duckdb_cache is not None:
        store._duckdb_cache.close()
    return tmp_path, days


def _parquet_partitions(base):
    return sorted(p.name for a in base.glob("asset=*") for p in a.glob("date=*"))


def test_a_dated_purge_no_longer_uses_a_column_that_does_not_exist(purge, populated):
    """The regression. `ts` is not in the schema; `trading_date` is."""
    base, days = populated
    rc = purge.main([
        "--base-dir", str(base), "--dir-contains", "PURGE",
        "--start", days[0].isoformat(), "--end", days[4].isoformat(), "--apply",
    ])
    assert rc == 0, "a dated purge raised instead of completing"
    left = _parquet_partitions(base)
    assert len(left) == len(days) - 5, left


def test_the_mirror_is_purged_before_parquet(purge, populated, monkeypatch):
    """If the DuckDB half fails, Parquet must still be intact.

    Simulated by making the mirror statement raise. Before the reorder this test
    would find the partitions already gone -- the unrecoverable direction.
    """
    base, days = populated
    import duckdb

    real_connect = duckdb.connect

    class _Exploding:
        def __init__(self, inner):
            self._inner = inner

        def execute(self, *a, **k):
            raise RuntimeError("Binder Error: column \"ts\" not found")

        def close(self):
            self._inner.close()

    monkeypatch.setattr(duckdb, "connect", lambda *a, **k: _Exploding(real_connect(*a, **k)))

    before = _parquet_partitions(base)
    rc = purge.main([
        "--base-dir", str(base), "--dir-contains", "PURGE",
        "--start", days[0].isoformat(), "--end", days[4].isoformat(), "--apply",
    ])
    assert rc == 1, "a failing mirror purge must report failure"
    assert _parquet_partitions(base) == before, (
        "Parquet was deleted even though the mirror purge failed -- this is the "
        "unrecoverable direction: the source of truth gone, the stale cache kept"
    )


def test_a_locked_mirror_deletes_nothing(purge, populated, monkeypatch):
    base, days = populated
    import duckdb

    monkeypatch.setattr(duckdb, "connect",
                        lambda *a, **k: (_ for _ in ()).throw(IOError("locked")))
    before = _parquet_partitions(base)
    rc = purge.main([
        "--base-dir", str(base), "--dir-contains", "PURGE", "--apply",
    ])
    assert rc == 1
    assert _parquet_partitions(base) == before, "a locked mirror must not cost Parquet"


def test_dry_run_still_deletes_nothing(purge, populated):
    base, days = populated
    before = _parquet_partitions(base)
    rc = purge.main(["--base-dir", str(base), "--dir-contains", "PURGE"])
    assert rc == 0
    assert _parquet_partitions(base) == before
