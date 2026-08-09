import datetime
import importlib
import types

import pandas as pd
import pytest

pytest.importorskip("rateslib")
pytest.importorskip("QuantLib")

from Caching.DiskCacheMixin import DiskCacheMixin
from Caching.layered_cache_mixin import LayeredDictProxy
import Caching.supabase_engine as supabase_engine_module
import MDP.IRSwaps.BARCHART_STIRF.rl as barchart_rl_module
from MDP.IRSwaps.BARCHART_STIRF.rl import BARCHART_STIRF_CURVE


class _RawOnlyMapping:
    def __init__(self):
        self.raw = {}

    def __setitem__(self, key, value):
        raise AssertionError("bulk bundle writes should bypass layered __setitem__")


# A believable node set. _curve_store_write_day now runs every candidate
# snapshot through the sanity gate before persisting, so a stub snapshot has to
# carry node data or it is (correctly) rejected as empty.
_HEALTHY_NODE_DATES = [
    datetime.date(2026, 3, 10),
    datetime.date(2026, 4, 29),
    datetime.date(2026, 6, 17),
    datetime.date(2027, 3, 10),
]
_HEALTHY_DFS = [1.0, 0.9945, 0.9890, 0.9615]


def test_daily_bundle_put_uses_local_mapping_only():
    builder = BARCHART_STIRF_CURVE.__new__(BARCHART_STIRF_CURVE)
    mapping = _RawOnlyMapping()
    builder._curve_cache_daily_bundle_key = lambda curve_name, date, cfg: "bundle-key"
    builder._curve_cache_daily_bundle_mapping = lambda: mapping

    ts = datetime.datetime(2026, 3, 10, 16, 0, tzinfo=datetime.timezone.utc)
    curve = types.SimpleNamespace(nodes=types.SimpleNamespace(nodes={pd.Timestamp("2026-03-11"): 0.99}))

    builder._curve_cache_daily_bundle_put(
        "USD-SOFR-1D-Q12STIRT",
        datetime.date(2026, 3, 10),
        {},
        {ts: curve},
    )

    assert "bundle-key" in mapping.raw
    assert mapping.raw["bundle-key"]["nodes_by_ts"][ts.isoformat()] == {"2026-03-11T00:00:00": 0.99}


def test_curve_cache_put_local_uses_local_mapping_only():
    builder = BARCHART_STIRF_CURVE.__new__(BARCHART_STIRF_CURVE)
    mapping = _RawOnlyMapping()
    builder._curve_cache_key = lambda curve_name, timestamp, cfg: "curve-key"
    builder._curve_cache_mapping = lambda: mapping
    builder._mem_cache_put = lambda key, curve: None

    ts = datetime.datetime(2026, 3, 10, 16, 0, tzinfo=datetime.timezone.utc)
    curve = types.SimpleNamespace(to_json=lambda: "{\"curve\":1}")

    builder._curve_cache_put_local("USD-SOFR-1D-Q12STIRT", ts, {}, curve)

    assert mapping.raw["curve-key"]["curve_json"] == "{\"curve\":1}"


def test_barchart_curve_cache_stays_local_when_supabase_enabled(tmp_path, monkeypatch):
    saved_root = DiskCacheMixin.CACHE_ROOT
    try:
        with monkeypatch.context() as env_patch:
            env_patch.delenv("ARBS_SUPABASE_ENABLED", raising=False)
            env_patch.setenv("ARBS_DATABASE_URL", "postgresql://user:pass@localhost:6543/testdb")
            importlib.reload(supabase_engine_module)

            DiskCacheMixin.CACHE_ROOT = tmp_path
            DiskCacheMixin._CACHE_REGISTRY.clear()

            builder = BARCHART_STIRF_CURVE()
            cache = getattr(builder, builder._CURVE_CACHE_ATTR)

            assert isinstance(cache, LayeredDictProxy)
            assert cache._l2_read is False
            assert cache._l2_write is False
            builder.close_cache()
            for child_attr in ("stirf_mdp", "stirf_mdp_schwab_app", "stirf_mdp_barchart"):
                getattr(builder, child_attr).close_cache()
    finally:
        DiskCacheMixin.CACHE_ROOT = saved_root
        DiskCacheMixin._CACHE_REGISTRY.clear()
        importlib.reload(supabase_engine_module)


def test_curve_store_write_day_persists_one_bulk_day(monkeypatch):
    builder = BARCHART_STIRF_CURVE.__new__(BARCHART_STIRF_CURVE)
    builder._curve_cfg_hash = lambda cfg: "cfg123"

    import Caching.curve_store as curve_store_module
    import Caching.curve_analytics as curve_analytics_module

    captured = {}
    ts1 = datetime.datetime(2026, 3, 10, 14, 0, tzinfo=datetime.timezone.utc)
    ts2 = datetime.datetime(2026, 3, 10, 15, 0, tzinfo=datetime.timezone.utc)

    class _Snapshot:
        def __init__(self, timestamp_utc, curve):
            self.timestamp_utc = timestamp_utc
            self.curve = curve
            self.node_dates = _HEALTHY_NODE_DATES
            self.discount_factors = _HEALTHY_DFS
            self.trading_date = datetime.date(2026, 3, 10)

    class _DummyStore:
        def read_raw_day(self, curve_name, trading_date, **kwargs):
            return pd.DataFrame()

        def reconstruct_curves_batch(self, raw_df, cfg, max_workers=4):
            return {}

        def write_day(self, curve_name, trading_date, snapshots, overwrite=False):
            captured["curve_name"] = curve_name
            captured["trading_date"] = trading_date
            captured["snapshots"] = list(snapshots)
            captured["overwrite"] = overwrite

        def write_analytics_day(self, curve_name, trading_date, df, overwrite=False):
            captured["analytics_curve_name"] = curve_name
            captured["analytics_trading_date"] = trading_date
            captured["analytics_df"] = df.copy()
            captured["analytics_overwrite"] = overwrite

    monkeypatch.setattr(
        curve_store_module.CurveSnapshot,
        "from_rl_curve",
        classmethod(
            lambda cls, curve, *, curve_name, cfg, cfg_hash="": _Snapshot(
                ts1 if curve == "curve-a" else ts2,
                (curve_name, cfg_hash, curve),
            )
        ),
    )
    monkeypatch.setattr(
        curve_store_module.CurveStore,
        "default",
        staticmethod(lambda: _DummyStore()),
    )
    monkeypatch.setattr(
        curve_analytics_module,
        "compute_analytics_row",
        lambda curve, *, timestamp_utc, trading_date, session_minute=None, tenors=None, curve_name=None: {
            "timestamp_utc": pd.Timestamp(timestamp_utc),
            "trading_date": trading_date,
            "session_minute": 480 if session_minute is None else session_minute,
            "par_rate_1Y1Y": float(tenors is not None and "1Y1Y" in tenors),
        },
    )

    curves_by_ts = {
        ts1: "curve-a",
        ts2: "curve-b",
    }

    builder._curve_store_write_day(
        "USD-SOFR-1D-Q12STIRT",
        datetime.date(2026, 3, 10),
        {"reference_key": "USD-SOFR-1D"},
        curves_by_ts,
    )

    assert captured["curve_name"] == "USD-SOFR-1D-Q12STIRT"
    assert captured["trading_date"] == datetime.date(2026, 3, 10)
    assert captured["overwrite"] is True
    assert [snapshot.curve for snapshot in captured["snapshots"]] == [
        ("USD-SOFR-1D-Q12STIRT", "cfg123", "curve-a"),
        ("USD-SOFR-1D-Q12STIRT", "cfg123", "curve-b"),
    ]
    assert captured["analytics_curve_name"] == "USD-SOFR-1D-Q12STIRT"
    assert captured["analytics_trading_date"] == datetime.date(2026, 3, 10)
    assert captured["analytics_overwrite"] is True
    assert "par_rate_1Y1Y" in captured["analytics_df"].columns


def test_curve_store_write_day_merges_existing_partial_day(monkeypatch):
    builder = BARCHART_STIRF_CURVE.__new__(BARCHART_STIRF_CURVE)
    builder._curve_cfg_hash = lambda cfg: "cfg123"

    import Caching.curve_store as curve_store_module
    import Caching.curve_analytics as curve_analytics_module

    existing_ts = datetime.datetime(2026, 3, 10, 14, 0, tzinfo=datetime.timezone.utc)
    new_ts = datetime.datetime(2026, 3, 10, 15, 0, tzinfo=datetime.timezone.utc)

    class _Snapshot:
        def __init__(self, timestamp_utc, label):
            self.timestamp_utc = timestamp_utc
            self.label = label
            self.node_dates = _HEALTHY_NODE_DATES
            self.discount_factors = _HEALTHY_DFS
            self.trading_date = datetime.date(2026, 3, 10)

    captured = {}

    class _DummyStore:
        def read_raw_day(self, curve_name, trading_date, **kwargs):
            return pd.DataFrame([{"timestamp_utc": existing_ts}])

        def reconstruct_curves_batch(self, raw_df, cfg, max_workers=4):
            assert list(raw_df["timestamp_utc"]) == [existing_ts]
            return {existing_ts: "curve-existing"}

        def write_day(self, curve_name, trading_date, snapshots, overwrite=False):
            captured["snapshots"] = list(snapshots)
            captured["overwrite"] = overwrite

        def write_analytics_day(self, curve_name, trading_date, df, overwrite=False):
            captured["analytics_df"] = df.copy()
            captured["analytics_overwrite"] = overwrite

    monkeypatch.setattr(
        curve_store_module.CurveSnapshot,
        "from_rl_curve",
        classmethod(lambda cls, curve, *, curve_name, cfg, cfg_hash="": _Snapshot(new_ts, "new")),
    )
    monkeypatch.setattr(
        builder,
        "_curve_store_snapshot_from_raw_row",
        lambda row, *, default_curve_name: _Snapshot(existing_ts, "existing"),
    )
    monkeypatch.setattr(
        curve_store_module.CurveStore,
        "default",
        staticmethod(lambda: _DummyStore()),
    )
    monkeypatch.setattr(
        curve_analytics_module,
        "compute_analytics_row",
        lambda curve, *, timestamp_utc, trading_date, session_minute=None, tenors=None, curve_name=None: {
            "timestamp_utc": pd.Timestamp(timestamp_utc),
            "trading_date": trading_date,
            "curve": curve,
        },
    )

    builder._curve_store_write_day(
        "USD-SOFR-1D-Q12STIRT",
        datetime.date(2026, 3, 10),
        {"reference_key": "USD-SOFR-1D"},
        {new_ts: "curve-new"},
    )

    assert captured["overwrite"] is True
    assert [(snap.timestamp_utc, snap.label) for snap in captured["snapshots"]] == [
        (existing_ts, "existing"),
        (new_ts, "new"),
    ]
    assert captured["analytics_overwrite"] is True
    assert list(captured["analytics_df"]["curve"]) == ["curve-existing", "curve-new"]


def test_curve_store_write_day_attaches_timestamp_context_from_bulk_key(monkeypatch):
    builder = BARCHART_STIRF_CURVE.__new__(BARCHART_STIRF_CURVE)
    builder._curve_cfg_hash = lambda cfg: "cfg123"

    import Caching.curve_store as curve_store_module
    import Caching.curve_analytics as curve_analytics_module

    ts = datetime.datetime(2026, 3, 10, 15, 0, tzinfo=datetime.timezone.utc)
    captured = {}

    class _Snapshot:
        def __init__(self, timestamp_utc):
            self.timestamp_utc = timestamp_utc
            self.node_dates = _HEALTHY_NODE_DATES
            self.discount_factors = _HEALTHY_DFS
            self.trading_date = datetime.date(2026, 3, 10)

    class _DummyStore:
        def read_raw_day(self, curve_name, trading_date, **kwargs):
            return pd.DataFrame()

        def reconstruct_curves_batch(self, raw_df, cfg, max_workers=4):
            return {}

        def write_day(self, curve_name, trading_date, snapshots, overwrite=False):
            captured["snapshots"] = list(snapshots)

        def write_analytics_day(self, curve_name, trading_date, df, overwrite=False):
            captured["analytics_df"] = df.copy()

    def _from_rl_curve(cls, curve, *, curve_name, cfg, cfg_hash=""):
        assert getattr(curve, "timestamp_utc", None) == ts
        assert getattr(curve, "curve_name", None) == "USD-SOFR-1D-Q12STIRT"
        return _Snapshot(ts)

    monkeypatch.setattr(
        curve_store_module.CurveSnapshot,
        "from_rl_curve",
        classmethod(_from_rl_curve),
    )
    monkeypatch.setattr(
        curve_store_module.CurveStore,
        "default",
        staticmethod(lambda: _DummyStore()),
    )
    monkeypatch.setattr(
        curve_analytics_module,
        "compute_analytics_row",
        lambda curve, *, timestamp_utc, trading_date, session_minute=None, tenors=None, curve_name=None: {
            "timestamp_utc": pd.Timestamp(timestamp_utc),
            "trading_date": trading_date,
            "curve_name": getattr(curve, "curve_name", None),
        },
    )

    curve_without_context = types.SimpleNamespace()

    builder._curve_store_write_day(
        "USD-SOFR-1D-Q12STIRT",
        datetime.date(2026, 3, 10),
        {"reference_key": "USD-SOFR-1D"},
        {ts: curve_without_context},
    )

    assert [snapshot.timestamp_utc for snapshot in captured["snapshots"]] == [ts]
    assert list(captured["analytics_df"]["curve_name"]) == ["USD-SOFR-1D-Q12STIRT"]


def test_curve_store_snapshot_from_raw_row_accepts_array_payloads():
    builder = BARCHART_STIRF_CURVE.__new__(BARCHART_STIRF_CURVE)
    ts = datetime.datetime(2026, 3, 10, 15, 0, tzinfo=datetime.timezone.utc)
    node_date = datetime.date(2026, 3, 11)

    snapshot = builder._curve_store_snapshot_from_raw_row(
        {
            "timestamp_utc": ts,
            "timestamp_local": pd.Timestamp(ts).tz_convert("America/Chicago"),
            "trading_date": datetime.date(2026, 3, 10),
            "session_minute": 480,
            "curve_name": "USD-SOFR-1D-Q12STIRT",
            "cfg_hash": "cfg123",
            "reference_key": "USD-SOFR-1D",
            "interpolation": "log_linear",
            "source_variant": "BARCHART_STIRF",
            "node_dates": pd.Series([node_date]).to_numpy(),
            "discount_factors": pd.Series([0.99]).to_numpy(),
        },
        default_curve_name="USD-SOFR-1D-Q12STIRT",
    )

    assert snapshot.timestamp_utc == ts
    assert snapshot.node_dates == [node_date]
    assert snapshot.discount_factors == [0.99]


def test_persist_bulk_curves_uses_curve_store_for_shallow_days_only_once(monkeypatch):
    builder = BARCHART_STIRF_CURVE.__new__(BARCHART_STIRF_CURVE)

    hit_ts = datetime.datetime(2026, 3, 10, 14, 0, tzinfo=datetime.timezone.utc)
    fresh_ts = datetime.datetime(2026, 3, 10, 15, 0, tzinfo=datetime.timezone.utc)
    trading_date = datetime.date(2026, 3, 10)

    class _CurveMarker:
        pass

    monkeypatch.setattr(barchart_rl_module.rl, "Curve", _CurveMarker)

    curve_hit = _CurveMarker()
    curve_fresh = _CurveMarker()

    store_calls = []
    local_cache_calls = []
    bundle_calls = []

    builder._trading_date_for_timestamp = lambda ts: trading_date
    builder._curve_store_write_day = lambda curve_name, date, cfg, curves_by_ts: store_calls.append(
        (curve_name, date, dict(curves_by_ts))
    )
    builder._curve_cache_put_local = lambda curve_name, timestamp, cfg, curve: local_cache_calls.append(
        (curve_name, timestamp, curve)
    )
    builder._curve_cache_daily_bundle_put = lambda curve_name, date, cfg, curves_by_ts: bundle_calls.append(
        (curve_name, date, dict(curves_by_ts))
    )

    builder._persist_bulk_curves(
        curve_name="USD-SOFR-1D-Q12STIRT",
        cfg={},
        out={hit_ts: curve_hit, fresh_ts: curve_fresh},
        fresh_curves={fresh_ts: curve_fresh},
        curve_only=True,
    )

    assert store_calls == [
        (
            "USD-SOFR-1D-Q12STIRT",
            trading_date,
            {hit_ts: curve_hit, fresh_ts: curve_fresh},
        )
    ]
    assert bundle_calls == []
    assert local_cache_calls == [("USD-SOFR-1D-Q12STIRT", fresh_ts, curve_fresh)]


def _write_day_harness(monkeypatch, snapshots_by_curve, captured):
    """Wire _curve_store_write_day to stubs, returning a bare builder.

    ``snapshots_by_curve`` maps the placeholder curve object to the snapshot the
    stubbed CurveSnapshot factory should return for it.
    """
    import Caching.curve_store as curve_store_module
    import Caching.curve_analytics as curve_analytics_module

    class _DummyStore:
        def read_raw_day(self, curve_name, trading_date, **kwargs):
            captured["merge_base_kwargs"] = kwargs
            return pd.DataFrame()

        def reconstruct_curves_batch(self, raw_df, cfg, max_workers=4):
            return {}

        def write_day(self, curve_name, trading_date, snapshots, overwrite=False):
            captured["snapshots"] = list(snapshots)

        def write_analytics_day(self, curve_name, trading_date, df, overwrite=False):
            captured["analytics_df"] = df.copy()

    monkeypatch.setattr(
        curve_store_module.CurveSnapshot,
        "from_rl_curve",
        classmethod(lambda cls, curve, *, curve_name, cfg, cfg_hash="": snapshots_by_curve[curve]),
    )
    monkeypatch.setattr(curve_store_module.CurveStore, "default", staticmethod(lambda: _DummyStore()))
    monkeypatch.setattr(
        curve_analytics_module,
        "compute_analytics_row",
        lambda curve, *, timestamp_utc, trading_date, session_minute=None, tenors=None, curve_name=None: {
            "timestamp_utc": pd.Timestamp(timestamp_utc),
            "trading_date": trading_date,
        },
    )

    builder = BARCHART_STIRF_CURVE.__new__(BARCHART_STIRF_CURVE)
    builder._curve_cfg_hash = lambda cfg: "cfg123"
    return builder


class _GateSnapshot:
    def __init__(self, timestamp_utc, discount_factors, label):
        self.timestamp_utc = timestamp_utc
        self.discount_factors = discount_factors
        self.label = label
        self.node_dates = _HEALTHY_NODE_DATES
        self.trading_date = datetime.date(2026, 3, 10)


def test_write_day_rejects_a_degenerate_snapshot_and_keeps_the_rest(monkeypatch):
    """2026-07-01 stored 1,381 identity curves and reported success.

    A snapshot whose discount factors are all exactly 1.0 is rateslib's
    pre-solve state, never a market, and must not reach the partition.
    """
    ts_good = datetime.datetime(2026, 3, 10, 14, 0, tzinfo=datetime.timezone.utc)
    ts_dead = datetime.datetime(2026, 3, 10, 15, 0, tzinfo=datetime.timezone.utc)
    good = _GateSnapshot(ts_good, _HEALTHY_DFS, "good")
    dead = _GateSnapshot(ts_dead, [1.0] * len(_HEALTHY_NODE_DATES), "dead")

    captured = {}
    builder = _write_day_harness(monkeypatch, {"c-good": good, "c-dead": dead}, captured)
    builder._curve_store_write_day(
        "USD-SOFR-1D-Q12STIRT",
        datetime.date(2026, 3, 10),
        {"reference_key": "USD-SOFR-1D"},
        {ts_good: "c-good", ts_dead: "c-dead"},
    )

    assert [s.label for s in captured["snapshots"]] == ["good"]
    # The merge base must be read unfiltered, or quarantined rows would be
    # silently deleted from the partition by the next write.
    assert captured["merge_base_kwargs"] == {"apply_sanity_filter": False}


def test_write_day_raises_when_every_snapshot_fails_the_gate(monkeypatch):
    """A day that produced nothing believable is a failure, not a no-op."""
    ts = datetime.datetime(2026, 3, 10, 14, 0, tzinfo=datetime.timezone.utc)
    dead = _GateSnapshot(ts, [1.0] * len(_HEALTHY_NODE_DATES), "dead")

    captured = {}
    builder = _write_day_harness(monkeypatch, {"c-dead": dead}, captured)
    with pytest.raises(ValueError, match="curve sanity gate"):
        builder._curve_store_write_day(
            "USD-SOFR-1D-Q12STIRT",
            datetime.date(2026, 3, 10),
            {"reference_key": "USD-SOFR-1D"},
            {ts: "c-dead"},
        )
    assert "snapshots" not in captured
