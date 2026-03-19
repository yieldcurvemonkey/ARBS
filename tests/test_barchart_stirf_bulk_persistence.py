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

    captured = {}

    class _DummyStore:
        def write_day(self, curve_name, trading_date, snapshots, overwrite=False):
            captured["curve_name"] = curve_name
            captured["trading_date"] = trading_date
            captured["snapshots"] = list(snapshots)
            captured["overwrite"] = overwrite

    monkeypatch.setattr(
        curve_store_module.CurveSnapshot,
        "from_rl_curve",
        classmethod(lambda cls, curve, *, curve_name, cfg, cfg_hash="": (curve_name, cfg_hash, curve)),
    )
    monkeypatch.setattr(
        curve_store_module.CurveStore,
        "default",
        staticmethod(lambda: _DummyStore()),
    )

    curves_by_ts = {
        datetime.datetime(2026, 3, 10, 14, 0, tzinfo=datetime.timezone.utc): "curve-a",
        datetime.datetime(2026, 3, 10, 15, 0, tzinfo=datetime.timezone.utc): "curve-b",
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
    assert captured["snapshots"] == [
        ("USD-SOFR-1D-Q12STIRT", "cfg123", "curve-a"),
        ("USD-SOFR-1D-Q12STIRT", "cfg123", "curve-b"),
    ]


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
