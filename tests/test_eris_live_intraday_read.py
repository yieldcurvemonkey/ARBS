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


@pytest.mark.db
def test_eris_live_intraday_bulk_asof_between_snapshots():
    # Batch as-of path: a target strictly BETWEEN two snapshots must resolve to
    # the EARLIER one (merge_asof backward == single-point as-of). Seed two
    # snapshots with DISTINCT discount factors so the resolved snapshot is
    # identifiable by the reconstructed DFs.
    from sqlalchemy import text
    from Caching.curve_store import CurveSnapshot
    from Caching.supabase_curve_sync import SupabaseCurveSync
    from MDP.IRSwaps.IRSwapsMDP import IRSwapsMDP

    ASSET = IRSwapsMDP._ERIS_LIVE_STORE_ASSET
    utc = datetime.timezone.utc
    ts1 = datetime.datetime(2000, 1, 3, 20, 0, tzinfo=utc)
    ts2 = datetime.datetime(2000, 1, 3, 20, 10, tzinfo=utc)
    between = datetime.datetime(2000, 1, 3, 20, 5, tzinfo=utc)  # -> ts1 (earlier)

    def _snap(ts, dfs):
        return CurveSnapshot(
            timestamp_utc=ts, timestamp_local=ts,
            trading_date=datetime.date(2000, 1, 3),
            session_minute=ts.hour * 60 + ts.minute,
            curve_name=ASSET, cfg_hash="", reference_key="USD-SOFR-1D",
            interpolation="log_linear", source_variant="ERIS_RL_BASIC_NOJUMPS",
            node_dates=[datetime.date(2000, 1, 4), datetime.date(2001, 1, 4)],
            discount_factors=dfs,
        )

    sync = SupabaseCurveSync.from_defaults()
    if sync._engine is None:
        pytest.skip("no Supabase engine configured")

    # This synthetic trading_date is settled, so the read path materializes it into
    # the local Parquet L1. That partition is test-owned state: leaving it behind
    # makes the NEXT run assert against a previous run's discount factors. Start
    # clean and tear it down again below.
    from Caching.curve_store import CurveStore, _sanitize
    from MDP.IRSwaps.IRSwapsMDP import IRSwapsMDP as _MDP

    _store = CurveStore.default()
    _part = _store._raw_dir / f"asset={_sanitize(ASSET)}" / f"date={ts1.date().isoformat()}"

    def _drop_local_partition():
        import shutil
        shutil.rmtree(_part, ignore_errors=True)
        _MDP._ERIS_L1_DAY_STATE.pop((str(ASSET), ts1.date()), None)

    _drop_local_partition()
    try:
        sync.upsert_snapshot_row(_snap(ts1, [0.9999, 0.95]), ASSET)     # earlier
        sync.upsert_snapshot_row(_snap(ts2, [0.9990, 0.90]), ASSET)     # later (distinct DFs)

        mdp = IRSwapsMDP(source="eris_live_intraday")
        out = mdp.bulk_get_data(
            {"curve_name": "USD-SOFR-1D", "timestamps": [between, ts2], "method": "asof"}
        )
        assert set(out.keys()) == {between, ts2}

        def _dfs(curve):
            h = curve.handle()
            raw = h.nodes._nodes if hasattr(h.nodes, "_nodes") else dict(h.nodes)
            return sorted(round(float(v), 6) for v in raw.values())

        # between -> ts1's DFs (earlier snapshot); ts2 exact -> ts2's DFs
        assert _dfs(out[between]) == sorted([0.9999, 0.95])
        assert _dfs(out[ts2]) == sorted([0.9990, 0.90])

        # batch == single-point on the between target
        single = mdp.get_pricer({"curve_name": "USD-SOFR-1D", "timestamp": between, "method": "asof"})
        assert _dfs(single) == _dfs(out[between])
    finally:
        with sync._engine.begin() as conn:
            conn.execute(
                text("DELETE FROM arbs_curve_snapshots_v1 WHERE curve_name = :cn AND timestamp_utc IN (:t1, :t2)"),
                {"cn": ASSET, "t1": ts1, "t2": ts2},
            )
        _drop_local_partition()


def test_eris_local_l1_enabled_env(monkeypatch):
    from MDP.IRSwaps.IRSwapsMDP import IRSwapsMDP
    monkeypatch.delenv("ARBS_ERIS_LOCAL_CURVE_L1", raising=False)
    assert IRSwapsMDP._eris_local_l1_enabled() is True   # default on
    monkeypatch.setenv("ARBS_ERIS_LOCAL_CURVE_L1", "0")
    assert IRSwapsMDP._eris_local_l1_enabled() is False
    monkeypatch.setenv("ARBS_ERIS_LOCAL_CURVE_L1", "1")
    assert IRSwapsMDP._eris_local_l1_enabled() is True


@pytest.mark.db
def test_eris_live_intraday_bulk_l1_settled_day(monkeypatch):
    # Read-only local Parquet L1 for a SETTLED day: first read materializes the
    # local partition (local-only, no L2 blob), a second read serves from local
    # with ZERO remote day-pulls, and both are value-identical to the remote path.
    import shutil
    from sqlalchemy import text
    from Caching.curve_store import CurveSnapshot
    from Caching.supabase_curve_sync import SupabaseCurveSync, CURVE_INTRADAY_BLOCKS_TABLE
    from MDP.IRSwaps.IRSwapsMDP import IRSwapsMDP

    ASSET = IRSwapsMDP._ERIS_LIVE_STORE_ASSET
    utc = datetime.timezone.utc
    SETTLED = datetime.date(2000, 1, 4)  # far-past -> settled (< today)
    t1 = datetime.datetime(2000, 1, 4, 20, 0, tzinfo=utc)
    t2 = datetime.datetime(2000, 1, 4, 20, 5, tzinfo=utc)
    between = datetime.datetime(2000, 1, 4, 20, 3, tzinfo=utc)  # -> t1 (earlier)

    def _snap(ts, dfs):
        return CurveSnapshot(
            timestamp_utc=ts, timestamp_local=ts, trading_date=SETTLED,
            session_minute=ts.hour * 60 + ts.minute, curve_name=ASSET, cfg_hash="",
            reference_key="USD-SOFR-1D", interpolation="log_linear",
            source_variant="ERIS_RL_BASIC_NOJUMPS",
            node_dates=[datetime.date(2000, 1, 5), datetime.date(2001, 1, 4)],
            discount_factors=dfs,
        )

    sync = SupabaseCurveSync.from_defaults()
    if sync._engine is None:
        pytest.skip("no Supabase engine configured")
    store = IRSwapsMDP._get_curve_store()
    part = store._raw_dir / f"asset={ASSET}" / f"date={SETTLED.isoformat()}"
    if part.exists():
        shutil.rmtree(part)
    mdp = IRSwapsMDP(source="eris_live_intraday")

    def _dfs(cv):
        h = cv.handle()
        raw = h.nodes._nodes if hasattr(h.nodes, "_nodes") else dict(h.nodes)
        return sorted(round(float(v), 6) for v in raw.values())

    orig_day = SupabaseCurveSync.pull_snapshots_day
    try:
        sync.upsert_snapshot_row(_snap(t1, [0.9999, 0.95]), ASSET)
        sync.upsert_snapshot_row(_snap(t2, [0.9990, 0.90]), ASSET)
        req = {"curve_name": "USD-SOFR-1D", "timestamps": [t1, between, t2], "method": "asof"}

        monkeypatch.setenv("ARBS_ERIS_LOCAL_CURVE_L1", "0")
        ref = mdp.bulk_get_data(dict(req))

        monkeypatch.setenv("ARBS_ERIS_LOCAL_CURVE_L1", "1")
        l1a = mdp.bulk_get_data(dict(req))
        assert part.exists()  # first L1 read materialized the local partition

        def _boom(self, cn, td):
            raise AssertionError("remote pull_snapshots_day called on an L1 hit")

        SupabaseCurveSync.pull_snapshots_day = _boom
        l1b = mdp.bulk_get_data(dict(req))  # must serve from local; no remote day-pull
        SupabaseCurveSync.pull_snapshots_day = orig_day

        assert set(ref) == set(l1a) == set(l1b) == {t1, between, t2}
        for k in (t1, between, t2):
            assert _dfs(ref[k]) == _dfs(l1a[k]) == _dfs(l1b[k])
        assert _dfs(l1a[between]) == sorted([0.9999, 0.95])  # between -> earlier snapshot

        with sync._engine.begin() as conn:
            n_blob = conn.execute(
                text(f"SELECT count(*) FROM {CURVE_INTRADAY_BLOCKS_TABLE} WHERE curve_name=:cn AND trading_date=:td"),
                {"cn": ASSET, "td": SETTLED},
            ).scalar()
        assert n_blob == 0  # push_l2=False -> no whole-day blob written
    finally:
        SupabaseCurveSync.pull_snapshots_day = orig_day
        if part.exists():
            shutil.rmtree(part)
        with sync._engine.begin() as conn:
            conn.execute(
                text("DELETE FROM arbs_curve_snapshots_v1 WHERE curve_name=:cn AND timestamp_utc IN (:t1, :t2)"),
                {"cn": ASSET, "t1": t1, "t2": t2},
            )
