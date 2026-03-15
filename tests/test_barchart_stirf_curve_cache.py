import datetime as dt
import pickle
from concurrent.futures import Future

import pandas as pd
import pytest
import pytz

pytest.importorskip("rateslib")
import rateslib as rl

from MDP.IRSwaps.BARCHART_STIRF import rl as barchart_rl_module


def _make_curve(timestamp: dt.datetime) -> rl.Curve:
    curve = rl.Curve(
        nodes={
            rl.dt(2026, 3, 5): 1.0,
            rl.dt(2026, 3, 6): 0.9999,
        },
        id="USD-SOFR-1D",
        convention="act360",
        calendar="nyc",
        modifier="mf",
    )
    curve.timestamp = timestamp
    curve.timestamp_utc = timestamp.astimezone(pytz.UTC)
    return curve


def _inline_executor_factory(recorder, label):
    class _InlineExecutor:
        def __init__(self, *args, **kwargs):
            recorder.append((label, dict(kwargs)))

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def submit(self, fn, *args, **kwargs):
            fut = Future()
            try:
                fut.set_result(fn(*args, **kwargs))
            except Exception as exc:
                fut.set_exception(exc)
            return fut

    return _InlineExecutor


def test_bulk_bundle_write_uses_cme_trading_date(monkeypatch):
    builder = object.__new__(barchart_rl_module.BARCHART_STIRF_CURVE)
    builder._STIRF_CURVE_CONFIGS = {
        "USD-SOFR-1D-Q12STIRT": {
            "instruments": ["SFRCM1"],
            "reference_key": "USD-SOFR-1D",
        }
    }

    ny_tz = pytz.timezone("America/New_York")
    session_timestamps = [
        ny_tz.localize(dt.datetime(2026, 3, 4, 18, minute))
        for minute in range(11)
    ]

    bulk_fetch_requests = []
    bundle_writes = []
    individual_puts = []

    def _resolve_fetchers_for_request(*, cfg, is_live_request):
        def _single_fetch(request):
            raise AssertionError("single fetch should not be used in bulk path")

        def _bulk_fetch(request):
            bulk_fetch_requests.append(dict(request))
            return {
                ts: {"SFRCM1": [object()]}
                for ts in request["timestamps"]
            }

        return _single_fetch, _bulk_fetch

    def _build_curve_from_pricers(*, curve_name, timestamp, cfg, pricers):
        return _make_curve(timestamp), object()

    def _attach_curve_context(curve, *, curve_name, timestamp, cfg):
        curve.timestamp = timestamp
        curve.timestamp_utc = timestamp.astimezone(pytz.UTC)
        return curve

    monkeypatch.setattr(builder, "_resolve_fetchers_for_request", _resolve_fetchers_for_request)
    monkeypatch.setattr(builder, "_build_curve_from_pricers", _build_curve_from_pricers)
    monkeypatch.setattr(builder, "_attach_curve_context", _attach_curve_context)
    monkeypatch.setattr(
        builder,
        "_curve_cache_bulk_get",
        lambda curve_name, timestamps, cfg: ({}, list(timestamps)),
    )
    monkeypatch.setattr(builder, "_curve_cache_put", lambda *args, **kwargs: individual_puts.append(args))
    monkeypatch.setattr(builder, "_curve_cache_daily_bundle_get", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        builder,
        "_curve_cache_daily_bundle_put",
        lambda curve_name, date, cfg, curves_by_ts: bundle_writes.append(
            (curve_name, date, dict(curves_by_ts))
        ),
    )

    curves = builder.build_curve(
        curve_name="USD-SOFR-1D-Q12STIRT",
        timestamp=session_timestamps,
        kwargs={
            "force_refresh": False,
            "cache_full_intraday_fetch": True,
            "show_tqdm": False,
            "auto_prime_bulk": False,
            "calibration_max_workers": 1,
        },
    )

    assert set(curves) == set(session_timestamps)
    assert len(bulk_fetch_requests) == 1
    assert bulk_fetch_requests[0]["timestamps"] == session_timestamps

    assert len(bundle_writes) == 1
    bundle_curve_name, bundle_date, curves_by_ts = bundle_writes[0]
    assert bundle_curve_name == "USD-SOFR-1D-Q12STIRT"
    assert bundle_date == dt.date(2026, 3, 5)
    assert set(curves_by_ts) == set(session_timestamps)
    assert individual_puts == []


def test_single_curve_cache_get_falls_back_to_daily_bundle(monkeypatch):
    builder = object.__new__(barchart_rl_module.BARCHART_STIRF_CURVE)
    cfg = {
        "reference_key": "USD-SOFR-1D",
    }

    ny_tz = pytz.timezone("America/New_York")
    timestamp = ny_tz.localize(dt.datetime(2026, 3, 4, 18, 5))
    node_values = {
        pd.Timestamp(dt.datetime(2026, 3, 5)).isoformat(): 1.0,
        pd.Timestamp(dt.datetime(2026, 3, 6)).isoformat(): 0.9999,
    }

    monkeypatch.setattr(builder, "_curve_cache_mapping", lambda: {})
    monkeypatch.setattr(
        builder,
        "_curve_cache_daily_bundle_get",
        lambda curve_name, date, cfg_arg: {timestamp.isoformat(): node_values},
    )

    curve = builder._curve_cache_get("USD-SOFR-1D-Q12STIRT", timestamp, cfg)

    assert curve is not None
    assert curve.timestamp == timestamp
    raw_nodes = curve.nodes._nodes if hasattr(curve.nodes, "_nodes") else dict(curve.nodes)
    assert len(raw_nodes) == 2


def test_reduced_calibration_cfg_is_pickleable_and_excludes_fetchers():
    reduced = barchart_rl_module._reduced_calibration_cfg(
        {
            "reference_key": "USD-SOFR-1D",
            "max_tenor_from_timestamp_months": 36,
            "rl_irs_spec": "usd_irs_lt_2y",
            "fetch_pricers_func": lambda: None,
            "fetch_pricers_bulk_func": lambda: None,
            "mixed_interpolation": True,
        }
    )

    assert "fetch_pricers_func" not in reduced
    assert "fetch_pricers_bulk_func" not in reduced
    assert reduced["reference_key"] == "USD-SOFR-1D"
    pickle.dumps(reduced)


def test_process_mode_rejects_curve_only_false():
    builder = object.__new__(barchart_rl_module.BARCHART_STIRF_CURVE)
    builder._STIRF_CURVE_CONFIGS = {
        "USD-SOFR-1D-Q12STIRT": {
            "instruments": ["SFRCM1"],
            "reference_key": "USD-SOFR-1D",
        }
    }

    ny_tz = pytz.timezone("America/New_York")
    timestamps = [ny_tz.localize(dt.datetime(2026, 3, 5, 11, 0))]

    with pytest.raises(ValueError, match="curve_only=True"):
        builder.build_curve(
            curve_name="USD-SOFR-1D-Q12STIRT",
            timestamp=timestamps,
            kwargs={"calibration_executor": "process"},
            curve_only=False,
        )


def test_process_mode_uses_process_executor_and_parent_bundle_write(monkeypatch):
    builder = object.__new__(barchart_rl_module.BARCHART_STIRF_CURVE)
    builder._STIRF_CURVE_CONFIGS = {
        "USD-SOFR-1D-Q12STIRT": {
            "instruments": ["SFRCM1"],
            "reference_key": "USD-SOFR-1D",
            "max_tenor_from_timestamp_months": 36,
            "rl_irs_spec": "usd_irs_lt_2y",
        }
    }

    ny_tz = pytz.timezone("America/New_York")
    session_timestamps = [
        ny_tz.localize(dt.datetime(2026, 3, 4, 18, minute))
        for minute in range(11)
    ]

    bulk_fetch_requests = []
    bundle_writes = []
    executor_uses = []
    individual_puts = []

    def _resolve_fetchers_for_request(*, cfg, is_live_request):
        def _single_fetch(request):
            raise AssertionError("single fetch should not be used in bulk path")

        def _bulk_fetch(request):
            bulk_fetch_requests.append(dict(request))
            return {
                ts: {"SFRCM1": [object()]}
                for ts in request["timestamps"]
            }

        return _single_fetch, _bulk_fetch

    def _attach_curve_context(curve, *, curve_name, timestamp, cfg):
        curve.timestamp = timestamp
        curve.timestamp_utc = timestamp.astimezone(pytz.UTC)
        return curve

    monkeypatch.setattr(builder, "_resolve_fetchers_for_request", _resolve_fetchers_for_request)
    monkeypatch.setattr(builder, "_attach_curve_context", _attach_curve_context)
    monkeypatch.setattr(
        builder,
        "_curve_cache_bulk_get",
        lambda curve_name, timestamps, cfg: ({}, list(timestamps)),
    )
    monkeypatch.setattr(builder, "_curve_cache_put", lambda *args, **kwargs: individual_puts.append(args))
    monkeypatch.setattr(builder, "_curve_cache_daily_bundle_get", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        builder,
        "_curve_cache_daily_bundle_put",
        lambda curve_name, date, cfg, curves_by_ts: bundle_writes.append(
            (curve_name, date, dict(curves_by_ts))
        ),
    )
    monkeypatch.setattr(
        barchart_rl_module,
        "_build_curve_from_pricers_core",
        lambda curve_name, timestamp, cfg, pricers: (_make_curve(timestamp), object()),
    )
    monkeypatch.setattr(barchart_rl_module, "_validate_spawn_process_pool_environment", lambda: None)
    monkeypatch.setattr(
        barchart_rl_module,
        "ProcessPoolExecutor",
        _inline_executor_factory(executor_uses, "process"),
    )
    monkeypatch.setattr(
        barchart_rl_module,
        "ThreadPoolExecutor",
        _inline_executor_factory(executor_uses, "thread"),
    )

    curves = builder.build_curve(
        curve_name="USD-SOFR-1D-Q12STIRT",
        timestamp=session_timestamps,
        kwargs={
            "force_refresh": False,
            "cache_full_intraday_fetch": True,
            "show_tqdm": False,
            "auto_prime_bulk": False,
            "calibration_max_workers": 3,
            "calibration_executor": "process",
        },
    )

    assert set(curves) == set(session_timestamps)
    assert len(bulk_fetch_requests) == 1
    assert bulk_fetch_requests[0]["timestamps"] == session_timestamps
    assert [label for label, _ in executor_uses] == ["process"]
    assert executor_uses[0][1]["max_workers"] == 3
    assert "mp_context" in executor_uses[0][1]

    assert len(bundle_writes) == 1
    bundle_curve_name, bundle_date, curves_by_ts = bundle_writes[0]
    assert bundle_curve_name == "USD-SOFR-1D-Q12STIRT"
    assert bundle_date == dt.date(2026, 3, 5)
    assert set(curves_by_ts) == set(session_timestamps)
    assert individual_puts == []


def test_process_and_thread_modes_return_equivalent_curves(monkeypatch):
    builder = object.__new__(barchart_rl_module.BARCHART_STIRF_CURVE)
    builder._STIRF_CURVE_CONFIGS = {
        "USD-SOFR-1D-Q12STIRT": {
            "instruments": ["SFRCM1"],
            "reference_key": "USD-SOFR-1D",
            "max_tenor_from_timestamp_months": 36,
            "rl_irs_spec": "usd_irs_lt_2y",
        }
    }

    ny_tz = pytz.timezone("America/New_York")
    timestamps = [
        ny_tz.localize(dt.datetime(2026, 3, 5, 11, minute))
        for minute in range(3)
    ]
    executor_uses = []

    def _resolve_fetchers_for_request(*, cfg, is_live_request):
        def _single_fetch(request):
            raise AssertionError("single fetch should not be used in bulk path")

        def _bulk_fetch(request):
            return {
                ts: {"SFRCM1": [object()]}
                for ts in request["timestamps"]
            }

        return _single_fetch, _bulk_fetch

    def _attach_curve_context(curve, *, curve_name, timestamp, cfg):
        curve.timestamp = timestamp
        curve.timestamp_utc = timestamp.astimezone(pytz.UTC)
        return curve

    monkeypatch.setattr(builder, "_resolve_fetchers_for_request", _resolve_fetchers_for_request)
    monkeypatch.setattr(builder, "_attach_curve_context", _attach_curve_context)
    monkeypatch.setattr(
        builder,
        "_curve_cache_bulk_get",
        lambda curve_name, timestamps, cfg: ({}, list(timestamps)),
    )
    monkeypatch.setattr(builder, "_curve_cache_put", lambda *args, **kwargs: None)
    monkeypatch.setattr(builder, "_curve_cache_daily_bundle_get", lambda *args, **kwargs: None)
    monkeypatch.setattr(builder, "_curve_cache_daily_bundle_put", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        barchart_rl_module,
        "_build_curve_from_pricers_core",
        lambda curve_name, timestamp, cfg, pricers: (_make_curve(timestamp), object()),
    )
    monkeypatch.setattr(barchart_rl_module, "_validate_spawn_process_pool_environment", lambda: None)
    monkeypatch.setattr(
        barchart_rl_module,
        "ProcessPoolExecutor",
        _inline_executor_factory(executor_uses, "process"),
    )
    monkeypatch.setattr(
        barchart_rl_module,
        "ThreadPoolExecutor",
        _inline_executor_factory(executor_uses, "thread"),
    )

    thread_curves = builder.build_curve(
        curve_name="USD-SOFR-1D-Q12STIRT",
        timestamp=timestamps,
        kwargs={
            "force_refresh": True,
            "cache_full_intraday_fetch": True,
            "show_tqdm": False,
            "auto_prime_bulk": False,
            "calibration_max_workers": 2,
            "calibration_executor": "thread",
        },
    )
    process_curves = builder.build_curve(
        curve_name="USD-SOFR-1D-Q12STIRT",
        timestamp=timestamps,
        kwargs={
            "force_refresh": True,
            "cache_full_intraday_fetch": True,
            "show_tqdm": False,
            "auto_prime_bulk": False,
            "calibration_max_workers": 2,
            "calibration_executor": "process",
        },
    )

    assert set(thread_curves) == set(process_curves) == set(timestamps)
    for ts in timestamps:
        thread_nodes = thread_curves[ts].nodes._nodes if hasattr(thread_curves[ts].nodes, "_nodes") else dict(thread_curves[ts].nodes)
        process_nodes = process_curves[ts].nodes._nodes if hasattr(process_curves[ts].nodes, "_nodes") else dict(process_curves[ts].nodes)
        assert thread_nodes == process_nodes
    assert [label for label, _ in executor_uses] == ["thread", "process"]
