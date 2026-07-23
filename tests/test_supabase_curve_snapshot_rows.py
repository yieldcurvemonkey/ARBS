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
