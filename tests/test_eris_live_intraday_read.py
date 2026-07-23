def test_eris_live_intraday_skips_eod_validation():
    from MDP.IRSwaps.IRSwapsMDP import IRSwapsMDP
    mdp = IRSwapsMDP(source="eris_live_intraday")
    # source contains INTRADAY and not EOD -> strict EOD calendar validation off
    assert mdp._requires_strict_eod_calendar_validation() is False


def test_eris_live_intraday_store_asset_constant():
    from MDP.IRSwaps.IRSwapsMDP import IRSwapsMDP
    assert IRSwapsMDP._ERIS_LIVE_STORE_ASSET == "USD-SOFR-1D-ERISLIVE"


import datetime
import pytest


@pytest.mark.db
def test_eris_live_intraday_reads_seeded_row():
    from sqlalchemy import text
    from Caching.curve_store import CurveSnapshot
    from Caching.supabase_curve_sync import SupabaseCurveSync
    from MDP.IRSwaps.IRSwapsMDP import IRSwapsMDP

    ASSET = IRSwapsMDP._ERIS_LIVE_STORE_ASSET  # real asset; unique timestamp keeps it isolated
    utc = datetime.timezone.utc
    ts = datetime.datetime(2000, 1, 3, 20, 0, tzinfo=utc)  # far-past sentinel minute
    snap = CurveSnapshot(
        timestamp_utc=ts,
        timestamp_local=ts,
        trading_date=datetime.date(2000, 1, 3),
        session_minute=900,
        curve_name=ASSET,
        cfg_hash="",
        reference_key="USD-SOFR-1D",
        interpolation="log_linear",
        source_variant="ERIS_RL_BASIC_NOJUMPS",
        node_dates=[datetime.date(2000, 1, 4), datetime.date(2000, 1, 5), datetime.date(2001, 1, 4)],
        discount_factors=[0.9999, 0.9998, 0.95],
    )
    sync = SupabaseCurveSync.from_defaults()
    if sync._engine is None:
        pytest.skip("no Supabase engine configured")
    try:
        sync.upsert_snapshot_row(snap, ASSET)
        mdp = IRSwapsMDP(source="eris_live_intraday")
        curve = mdp.get_pricer({"curve_name": "USD-SOFR-1D", "timestamp": ts, "method": "asof"})
        handle = curve.handle()
        raw = handle.nodes._nodes if hasattr(handle.nodes, "_nodes") else dict(handle.nodes)
        assert len(raw) == 3
        assert curve.meta()["timestamp"].date() == datetime.date(2000, 1, 3)
    finally:
        with sync._engine.begin() as conn:
            conn.execute(
                text("DELETE FROM arbs_curve_snapshots_v1 WHERE curve_name = :cn AND timestamp_utc = :ts"),
                {"cn": ASSET, "ts": ts},
            )


@pytest.mark.db
def test_eris_live_intraday_bulk_reads_seeded_rows():
    from sqlalchemy import text
    from Caching.curve_store import CurveSnapshot
    from Caching.supabase_curve_sync import SupabaseCurveSync
    from MDP.IRSwaps.IRSwapsMDP import IRSwapsMDP

    ASSET = IRSwapsMDP._ERIS_LIVE_STORE_ASSET
    utc = datetime.timezone.utc
    ts_missing = datetime.datetime(2000, 1, 3, 19, 0, tzinfo=utc)  # before any seeded row
    ts1 = datetime.datetime(2000, 1, 3, 20, 0, tzinfo=utc)
    ts2 = datetime.datetime(2000, 1, 3, 20, 5, tzinfo=utc)

    def _snap(ts, session_minute):
        return CurveSnapshot(
            timestamp_utc=ts,
            timestamp_local=ts,
            trading_date=datetime.date(2000, 1, 3),
            session_minute=session_minute,
            curve_name=ASSET,
            cfg_hash="",
            reference_key="USD-SOFR-1D",
            interpolation="log_linear",
            source_variant="ERIS_RL_BASIC_NOJUMPS",
            node_dates=[datetime.date(2000, 1, 4), datetime.date(2000, 1, 5), datetime.date(2001, 1, 4)],
            discount_factors=[0.9999, 0.9998, 0.95],
        )

    sync = SupabaseCurveSync.from_defaults()
    if sync._engine is None:
        pytest.skip("no Supabase engine configured")
    try:
        sync.upsert_snapshot_row(_snap(ts1, 1200), ASSET)
        sync.upsert_snapshot_row(_snap(ts2, 1205), ASSET)

        mdp = IRSwapsMDP(source="eris_live_intraday")
        out = mdp.bulk_get_data(
            {
                "curve_name": "USD-SOFR-1D",
                "timestamps": [ts_missing, ts1, ts2],
                "method": "asof",
            }
        )

        # partial results: ts_missing has no row <= it (asof) -> omitted
        assert set(out.keys()) == {ts1, ts2}
        assert ts_missing not in out
        for k in (ts1, ts2):
            handle = out[k].handle()
            raw = handle.nodes._nodes if hasattr(handle.nodes, "_nodes") else dict(handle.nodes)
            assert len(raw) == 3
            assert out[k].meta()["timestamp"].date() == datetime.date(2000, 1, 3)

        # bulk[ts1] reconstructs the same curve as the single-point read
        single = mdp.get_pricer({"curve_name": "USD-SOFR-1D", "timestamp": ts1, "method": "asof"})
        sh = single.handle()
        s_raw = sh.nodes._nodes if hasattr(sh.nodes, "_nodes") else dict(sh.nodes)
        bh = out[ts1].handle()
        b_raw = bh.nodes._nodes if hasattr(bh.nodes, "_nodes") else dict(bh.nodes)
        # compare node keys AND values (not just sorted values) so a date-mapping
        # bug can't slip through
        assert {str(k): float(v) for k, v in s_raw.items()} == {str(k): float(v) for k, v in b_raw.items()}
    finally:
        with sync._engine.begin() as conn:
            conn.execute(
                text(
                    "DELETE FROM arbs_curve_snapshots_v1 "
                    "WHERE curve_name = :cn AND timestamp_utc IN (:t1, :t2)"
                ),
                {"cn": ASSET, "t1": ts1, "t2": ts2},
            )
