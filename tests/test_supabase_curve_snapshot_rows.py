import datetime
import pytest

from Caching.curve_store import CurveSnapshot
from Caching.supabase_curve_sync import _snapshot_insert_params


def _make_snap():
    utc = datetime.timezone.utc
    return CurveSnapshot(
        timestamp_utc=datetime.datetime(2026, 7, 23, 14, 31, tzinfo=utc),
        timestamp_local=datetime.datetime(2026, 7, 23, 9, 31, tzinfo=utc),
        trading_date=datetime.date(2026, 7, 23),
        session_minute=571,
        curve_name="USD-SOFR-1D-ERISLIVE",
        cfg_hash="",
        reference_key="USD-SOFR-1D",
        interpolation="log_linear",
        source_variant="ERIS_RL_BASIC_NOJUMPS",
        node_dates=[datetime.date(2026, 7, 24), datetime.date(2026, 7, 25)],
        discount_factors=[0.99989, 0.99978],
    )


def test_snapshot_insert_params_shape():
    params = _snapshot_insert_params(_make_snap(), "USD-SOFR-1D-ERISLIVE")
    assert params["curve_name"] == "USD-SOFR-1D-ERISLIVE"
    assert params["tags"] == []  # untagged is legal (TEXT[] DEFAULT '{}')
    assert params["reference_key"] == "USD-SOFR-1D"
    assert params["source_variant"] == "ERIS_RL_BASIC_NOJUMPS"
    assert params["session_minute"] == 571 and isinstance(params["session_minute"], int)
    assert params["node_dates"] == [datetime.date(2026, 7, 24), datetime.date(2026, 7, 25)]
    assert all(isinstance(d, datetime.date) for d in params["node_dates"])
    assert params["discount_factors"] == [0.99989, 0.99978]
    assert all(isinstance(v, float) for v in params["discount_factors"])


@pytest.mark.db
def test_upsert_snapshot_row_roundtrip():
    from sqlalchemy import text
    from Caching.supabase_curve_sync import SupabaseCurveSync

    TEST_ASSET = "USD-SOFR-1D-ERISLIVE-TEST"
    sync = SupabaseCurveSync.from_defaults()
    if sync._engine is None:
        pytest.skip("no Supabase engine configured")
    snap = _make_snap()
    try:
        assert sync.upsert_snapshot_row(snap, TEST_ASSET) is True
        # idempotent second write
        assert sync.upsert_snapshot_row(snap, TEST_ASSET) is True
        with sync._engine.begin() as conn:
            row = conn.execute(
                text("""
                    SELECT node_dates, discount_factors, reference_key, tags
                    FROM arbs_curve_snapshots_v1
                    WHERE curve_name = :cn AND timestamp_utc = :ts
                """),
                {"cn": TEST_ASSET, "ts": snap.timestamp_utc},
            ).fetchone()
        assert row is not None
        assert [d for d in row.node_dates] == snap.node_dates
        assert [float(v) for v in row.discount_factors] == snap.discount_factors
        assert row.reference_key == "USD-SOFR-1D"
        assert list(row.tags) == []
    finally:
        with sync._engine.begin() as conn:
            conn.execute(
                text("DELETE FROM arbs_curve_snapshots_v1 WHERE curve_name = :cn"),
                {"cn": TEST_ASSET},
            )


def test_pick_nearest():
    import datetime
    from Caching.supabase_curve_sync import _pick_nearest

    utc = datetime.timezone.utc
    rows = [
        {"timestamp_utc": datetime.datetime(2026, 7, 23, 14, 30, tzinfo=utc), "id": "a"},
        {"timestamp_utc": datetime.datetime(2026, 7, 23, 14, 33, tzinfo=utc), "id": "b"},
    ]
    target = datetime.datetime(2026, 7, 23, 14, 31, 10, tzinfo=utc)
    assert _pick_nearest(target, rows)["id"] == "a"
    assert _pick_nearest(target, [])  is None


@pytest.mark.db
def test_pull_snapshot_asof_roundtrip():
    import datetime
    from sqlalchemy import text
    from Caching.supabase_curve_sync import SupabaseCurveSync

    TEST_ASSET = "USD-SOFR-1D-ERISLIVE-TEST"
    utc = datetime.timezone.utc
    sync = SupabaseCurveSync.from_defaults()
    if sync._engine is None:
        pytest.skip("no Supabase engine configured")

    snaps = []
    for minute in (30, 31, 33):
        s = _make_snap()
        s.timestamp_utc = datetime.datetime(2026, 7, 23, 14, minute, tzinfo=utc)
        s.session_minute = 14 * 60 + minute
        snaps.append(s)
    try:
        for s in snaps:
            sync.upsert_snapshot_row(s, TEST_ASSET)

        # asof 14:32 -> the 14:31 row
        r = sync.pull_snapshot_asof(TEST_ASSET, datetime.datetime(2026, 7, 23, 14, 32, tzinfo=utc), "asof")
        assert r["timestamp_utc"] == datetime.datetime(2026, 7, 23, 14, 31, tzinfo=utc)
        # nearest 14:32:10 -> the 14:33 row is 50s away, 14:31 is 70s away -> 14:33
        r = sync.pull_snapshot_asof(TEST_ASSET, datetime.datetime(2026, 7, 23, 14, 32, 10, tzinfo=utc), "nearest")
        assert r["timestamp_utc"] == datetime.datetime(2026, 7, 23, 14, 33, tzinfo=utc)
        # exact miss
        assert sync.pull_snapshot_asof(TEST_ASSET, datetime.datetime(2026, 7, 23, 14, 32, tzinfo=utc), "exact") is None
        # latest
        assert sync.pull_latest_snapshot(TEST_ASSET)["timestamp_utc"] == datetime.datetime(2026, 7, 23, 14, 33, tzinfo=utc)
        # high-water-mark
        assert sync.latest_snapshot_ts(TEST_ASSET, datetime.date(2026, 7, 23)) == datetime.datetime(2026, 7, 23, 14, 33, tzinfo=utc)
    finally:
        with sync._engine.begin() as conn:
            conn.execute(text("DELETE FROM arbs_curve_snapshots_v1 WHERE curve_name = :cn"), {"cn": TEST_ASSET})


def test_pull_snapshot_asof_rejects_bad_method():
    import datetime, pytest as _pytest
    from Caching.supabase_curve_sync import SupabaseCurveSync
    sync = SupabaseCurveSync(base_dir=".", engine=None)
    with _pytest.raises(ValueError):
        sync.pull_snapshot_asof("X", datetime.datetime(2026, 7, 23, tzinfo=datetime.timezone.utc), "bogus")
    assert sync.pull_latest_snapshot("X") is None  # None-engine guard path
