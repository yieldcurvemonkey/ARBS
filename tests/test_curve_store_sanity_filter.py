"""The CurveStore read path quarantines snapshots it cannot believe.

History already on disk cannot be trusted wholesale -- 2026-07-01 is 1,381
stored identity curves -- and a rebuild takes hours, so the filter runs on the
way out of the store. Two things it must never do: take a read down when it
raises, and filter the merge base the writer reads back.
"""

import datetime

import pandas as pd
import pytest

pytest.importorskip("pyarrow")

from Caching.curve_sanity import sanity_filter_enabled
from Caching.curve_store import CurveSnapshot, CurveStore

CHI = "America/Chicago"
TRADING_DATE = datetime.date(2026, 3, 10)
NODE_DATES = [
    datetime.date(2026, 3, 10),
    datetime.date(2026, 4, 29),
    datetime.date(2026, 6, 17),
    datetime.date(2027, 3, 10),
]
HEALTHY_DFS = [1.0, 0.9945, 0.9890, 0.9615]
IDENTITY_DFS = [1.0, 1.0, 1.0, 1.0]


def _snapshot(minute: int, dfs) -> CurveSnapshot:
    ts_utc = datetime.datetime(2026, 3, 10, 14, 0, tzinfo=datetime.timezone.utc) + datetime.timedelta(
        minutes=minute
    )
    ts_local = pd.Timestamp(ts_utc).tz_convert(CHI).to_pydatetime()
    return CurveSnapshot(
        timestamp_utc=ts_utc,
        timestamp_local=ts_local,
        trading_date=TRADING_DATE,
        session_minute=480 + minute,
        curve_name="TEST-CURVE",
        cfg_hash="cfg",
        reference_key="USD-SOFR-1D",
        interpolation="log_linear",
        source_variant="TEST",
        node_dates=list(NODE_DATES),
        discount_factors=list(dfs),
    )


@pytest.fixture()
def store(tmp_path) -> CurveStore:
    return CurveStore(base_dir=tmp_path)


def _write(store: CurveStore, n_good: int, n_dead: int) -> None:
    snapshots = [_snapshot(i, HEALTHY_DFS) for i in range(n_good)]
    snapshots += [_snapshot(100 + i, IDENTITY_DFS) for i in range(n_dead)]
    store.write_day("TEST-CURVE", TRADING_DATE, snapshots, overwrite=True)


def test_read_raw_day_quarantines_identity_curves(store):
    _write(store, n_good=10, n_dead=3)
    df = store.read_raw_day("TEST-CURVE", TRADING_DATE)
    assert len(df) == 10
    assert all(dfs[1] != 1.0 for dfs in df["discount_factors"])


def test_read_raw_day_can_serve_the_unfiltered_truth(store):
    """The writer's merge base must see the rows the filter hides."""
    _write(store, n_good=10, n_dead=3)
    df = store.read_raw_day("TEST-CURVE", TRADING_DATE, apply_sanity_filter=False)
    assert len(df) == 13


def test_read_raw_nodes_single_day_path_is_filtered(store):
    _write(store, n_good=10, n_dead=3)
    df = store.read_raw_nodes("TEST-CURVE", start=TRADING_DATE, end=TRADING_DATE)
    assert len(df) == 10


def test_filter_is_disabled_by_env(store, monkeypatch):
    monkeypatch.setenv("ARBS_CURVE_STORE_SANITY_FILTER", "0")
    assert sanity_filter_enabled() is False
    _write(store, n_good=10, n_dead=3)
    assert len(store.read_raw_day("TEST-CURVE", TRADING_DATE)) == 13


def test_a_clean_day_is_returned_untouched(store):
    _write(store, n_good=12, n_dead=0)
    assert len(store.read_raw_day("TEST-CURVE", TRADING_DATE)) == 12


def test_a_raising_filter_never_takes_the_read_down(store, monkeypatch):
    import Caching.curve_sanity as sanity

    def _boom(*args, **kwargs):
        raise RuntimeError("predicate exploded")

    monkeypatch.setattr(sanity, "filter_raw_frame", _boom)
    _write(store, n_good=10, n_dead=3)
    assert len(store.read_raw_day("TEST-CURVE", TRADING_DATE)) == 13
