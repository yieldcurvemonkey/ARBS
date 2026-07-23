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
