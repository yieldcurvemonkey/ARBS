import datetime as dt
import json
import logging
import threading
import time
from collections import OrderedDict
from types import SimpleNamespace
from zoneinfo import ZoneInfo

from scripts import stirf_curve_service as stirf_curve_calibration
from scripts.stirf_curve_service import BackfillProgress, _probe_completed_days


class TestBackfillProgress:
    def test_record_day_increments_counters(self):
        p = BackfillProgress(curve_name="TEST", total_days=10, skipped_days=2)
        p.record_calibration(status="ok")
        p.record_timeseries(status="ok", failed_tenors=[])
        assert p.processed_days == 1
        assert p.calibration_ok == 1
        assert p.timeseries_ok == 1

    def test_record_day_tracks_errors(self):
        p = BackfillProgress(curve_name="TEST", total_days=10, skipped_days=0)
        p.record_calibration(status="error")
        p.record_timeseries(status="partial", failed_tenors=["1M1Y"])
        assert p.calibration_error == 1
        assert p.timeseries_partial == 1
        assert p.failed_tenors == ["1M1Y"]

    def test_pct_complete_includes_skipped(self):
        p = BackfillProgress(curve_name="TEST", total_days=10, skipped_days=5)
        p.record_calibration(status="ok")
        p.record_timeseries(status="ok", failed_tenors=[])
        # 5 skipped + 1 processed = 6/10 = 60%
        assert p.pct_complete == 60.0

    def test_format_heartbeat_returns_string(self):
        p = BackfillProgress(curve_name="TEST", total_days=10, skipped_days=0)
        p.record_calibration(status="ok")
        p.record_timeseries(status="ok", failed_tenors=[])
        msg = p.format_heartbeat()
        assert "TEST" in msg
        assert "1/10" in msg

    def test_to_perf_event_returns_dict(self):
        p = BackfillProgress(curve_name="TEST", total_days=5, skipped_days=1)
        event = p.to_perf_event()
        assert event["event"] == "backfill_heartbeat"
        assert event["curve_name"] == "TEST"
        assert event["total_days"] == 5
        assert event["skipped_days"] == 1


class TestCheckpointProbe:
    def test_returns_intersection_of_raw_and_ts(self):
        raw_dates = {dt.date(2026, 1, 6), dt.date(2026, 1, 7), dt.date(2026, 1, 8)}
        ts_dates = {dt.date(2026, 1, 7), dt.date(2026, 1, 8), dt.date(2026, 1, 9)}
        result = _probe_completed_days(
            raw_complete_dates=raw_dates,
            ts_complete_dates=ts_dates,
            skip_timeseries_warm=False,
        )
        assert result == {dt.date(2026, 1, 7), dt.date(2026, 1, 8)}

    def test_returns_raw_only_when_ts_skipped(self):
        raw_dates = {dt.date(2026, 1, 6), dt.date(2026, 1, 7)}
        result = _probe_completed_days(
            raw_complete_dates=raw_dates,
            ts_complete_dates=set(),
            skip_timeseries_warm=True,
        )
        assert result == raw_dates

    def test_returns_empty_when_no_overlap(self):
        raw_dates = {dt.date(2026, 1, 6)}
        ts_dates = {dt.date(2026, 1, 7)}
        result = _probe_completed_days(
            raw_complete_dates=raw_dates,
            ts_complete_dates=ts_dates,
            skip_timeseries_warm=False,
        )
        assert result == set()


def test_build_daily_minute_buckets_skips_non_business_days():
    buckets = stirf_curve_calibration.build_daily_minute_buckets(
        start_date=dt.date(2026, 3, 13),
        end_date=dt.date(2026, 3, 16),
        session_start=dt.time(7, 0),
        session_end=dt.time(7, 2),
        freq="1min",
        timezone=ZoneInfo("America/New_York"),
    )

    assert list(buckets.keys()) == [
        dt.date(2026, 3, 13),
        dt.date(2026, 3, 16),
    ]
    assert len(buckets[dt.date(2026, 3, 13)]) == 3
    assert buckets[dt.date(2026, 3, 13)][0].isoformat() == "2026-03-13T07:00:00-04:00"
    assert buckets[dt.date(2026, 3, 16)][-1].isoformat() == "2026-03-16T07:02:00-04:00"


def test_build_daily_minute_buckets_cme_session_includes_sunday_open_for_monday():
    buckets = stirf_curve_calibration.build_daily_minute_buckets(
        start_date=dt.date(2026, 3, 9),
        end_date=dt.date(2026, 3, 10),
        session_start=dt.time(7, 0),
        session_end=dt.time(17, 0),
        freq="60min",
        timezone=ZoneInfo("America/Chicago"),
        cme_session=True,
    )

    assert list(buckets.keys()) == [
        dt.date(2026, 3, 9),
        dt.date(2026, 3, 10),
    ]
    assert len(buckets[dt.date(2026, 3, 9)]) == 24
    assert buckets[dt.date(2026, 3, 9)][0].isoformat() == "2026-03-08T17:00:00-05:00"
    assert buckets[dt.date(2026, 3, 9)][-1].isoformat() == "2026-03-09T16:00:00-05:00"
    assert len(buckets[dt.date(2026, 3, 10)]) == 24
    assert buckets[dt.date(2026, 3, 10)][0].isoformat() == "2026-03-09T17:00:00-05:00"
    assert buckets[dt.date(2026, 3, 10)][-1].isoformat() == "2026-03-10T16:00:00-05:00"


def test_iter_daily_minute_buckets_streams_trade_dates_in_order():
    buckets = list(
        stirf_curve_calibration.iter_daily_minute_buckets(
            start_date=dt.date(2026, 3, 13),
            end_date=dt.date(2026, 3, 16),
            session_start=dt.time(7, 0),
            session_end=dt.time(7, 2),
            freq="1min",
            timezone=ZoneInfo("America/New_York"),
        )
    )

    assert [trade_date for trade_date, _ in buckets] == [
        dt.date(2026, 3, 13),
        dt.date(2026, 3, 16),
    ]
    assert len(buckets[0][1]) == 3
    assert buckets[0][1][0].isoformat() == "2026-03-13T07:00:00-04:00"
    assert buckets[1][1][-1].isoformat() == "2026-03-16T07:02:00-04:00"


def test_run_bucketed_calibration_writes_perf_log(tmp_path):
    class FakeCurve:
        def __init__(self, curve_name):
            self._curve_name = curve_name

        def meta(self):
            return {"curve_name": self._curve_name}

    class FakeMDP:
        def __init__(self):
            self.calls = []

        def bulk_get_data(self, request):
            self.calls.append(dict(request))
            timestamps = list(request["timestamps"])
            if len(self.calls) == 1:
                return {timestamps[0]: FakeCurve(request["curve_name"])}
            return {ts: FakeCurve(request["curve_name"]) for ts in timestamps}

    daily_buckets = OrderedDict(
        [
            (
                dt.date(2026, 3, 10),
                [
                    dt.datetime(2026, 3, 10, 7, 0, tzinfo=ZoneInfo("America/New_York")),
                    dt.datetime(2026, 3, 10, 7, 1, tzinfo=ZoneInfo("America/New_York")),
                ],
            ),
            (
                dt.date(2026, 3, 11),
                [
                    dt.datetime(2026, 3, 11, 7, 0, tzinfo=ZoneInfo("America/New_York")),
                ],
            ),
        ]
    )
    request_options = {
        "n_jobs": 4,
        "show_tqdm": False,
        "ignore_cache": False,
        "calibration_executor": "process",
        "auto_prime_bulk": True,
        "stirf_fetch_max_workers": 2,
        "calibration_max_workers": 4,
    }
    perf_log_path = tmp_path / "perf.jsonl"
    logger = logging.getLogger("test_stirf_curve_calibration")

    fake_mdp = FakeMDP()
    all_curves, daily_results, summary = stirf_curve_calibration.run_bucketed_calibration(
        curve_mdp=fake_mdp,
        curve_name="USD-SOFR-1D-Q12STIRT",
        source="BARCHART_STIRF-RL",
        daily_buckets=daily_buckets,
        request_options=request_options,
        perf_log_path=perf_log_path,
        logger=logger,
        fail_fast=False,
    )

    assert len(fake_mdp.calls) == 2
    assert fake_mdp.calls[0]["calibration_executor"] == "process"
    assert fake_mdp.calls[0]["calibration_max_workers"] == 4
    assert fake_mdp.calls[0]["stirf_fetch_max_workers"] == 2

    assert all_curves == {}
    assert len(daily_results) == 2
    assert daily_results[0].requested_timestamps == 2
    assert daily_results[0].returned_curves == 1
    assert daily_results[0].missing_curves == 1
    assert daily_results[1].returned_curves == 1

    assert summary["business_days"] == 2
    assert summary["successful_days"] == 2
    assert summary["failed_days"] == 0
    assert summary["requested_timestamps"] == 3
    assert summary["returned_curves"] == 2
    assert summary["missing_curves"] == 1

    events = [json.loads(line) for line in perf_log_path.read_text(encoding="utf-8").splitlines()]
    assert [event["event"] for event in events] == [
        "run_start",
        "day_result",
        "day_result",
        "run_summary",
    ]
    assert events[1]["trade_date"] == "2026-03-10"
    assert events[1]["missing_curves"] == 1
    assert events[-1]["returned_curves"] == 2


def test_run_bucketed_calibration_accepts_streaming_bucket_iterable(tmp_path):
    class FakeCurve:
        def __init__(self, curve_name):
            self._curve_name = curve_name

        def meta(self):
            return {"curve_name": self._curve_name}

    class FakeMDP:
        def bulk_get_data(self, request):
            return {
                ts: FakeCurve(request["curve_name"])
                for ts in request["timestamps"]
            }

    daily_buckets = iter(
        [
            (
                dt.date(2026, 3, 10),
                [
                    dt.datetime(2026, 3, 10, 7, 0, tzinfo=ZoneInfo("America/New_York")),
                    dt.datetime(2026, 3, 10, 7, 1, tzinfo=ZoneInfo("America/New_York")),
                ],
            ),
            (
                dt.date(2026, 3, 11),
                [
                    dt.datetime(2026, 3, 11, 7, 0, tzinfo=ZoneInfo("America/New_York")),
                ],
            ),
        ]
    )
    request_options = {
        "n_jobs": 2,
        "show_tqdm": False,
        "ignore_cache": False,
        "calibration_executor": "process",
        "auto_prime_bulk": True,
        "stirf_fetch_max_workers": None,
        "calibration_max_workers": None,
    }

    _, daily_results, summary = stirf_curve_calibration.run_bucketed_calibration(
        curve_mdp=FakeMDP(),
        curve_name="USD-SOFR-1D-Q12STIRT",
        source="BARCHART_STIRF-RL",
        daily_buckets=daily_buckets,
        request_options=request_options,
        perf_log_path=tmp_path / "perf.jsonl",
        logger=logging.getLogger("test_stirf_curve_calibration"),
        fail_fast=False,
        business_days=2,
    )

    assert len(daily_results) == 2
    assert summary["business_days"] == 2
    assert summary["requested_timestamps"] == 3


def test_flush_computed_ts_pushes_waits_on_unique_stores():
    waits: list[tuple[str, float]] = []

    class _FakeStore:
        def __init__(self, label, waited):
            self.label = label
            self.waited = waited

        def wait_for_background_pushes(self, timeout=None):
            waits.append((self.label, timeout))
            return self.waited

    shared = _FakeStore("shared", 2)
    isolated = _FakeStore("isolated", 1)
    ts_builder = SimpleNamespace(
        _routers={"IRS": SimpleNamespace(_computed_ts_store=shared)},
        _specialized_router_cache={"IRS": SimpleNamespace(_computed_ts_store=shared)},
        _generic_router_cache={"FRB": SimpleNamespace()},
    )
    ts_builder._routers["ALT"] = SimpleNamespace(_computed_ts_store=isolated)

    stirf_curve_calibration._flush_computed_ts_pushes(
        ts_builder=ts_builder,
        logger=logging.getLogger("test_stirf_curve_calibration"),
        timeout_seconds=12.5,
    )

    assert waits == [("shared", 12.5), ("isolated", 12.5)]


def test_run_bucketed_calibration_can_retain_all_curves(tmp_path):
    class FakeCurve:
        def __init__(self, curve_name):
            self._curve_name = curve_name

        def meta(self):
            return {"curve_name": self._curve_name}

    class FakeMDP:
        def bulk_get_data(self, request):
            return {
                ts: FakeCurve(request["curve_name"])
                for ts in request["timestamps"]
            }

    daily_buckets = OrderedDict(
        [
            (
                dt.date(2026, 3, 10),
                [
                    dt.datetime(2026, 3, 10, 7, 0, tzinfo=ZoneInfo("America/New_York")),
                    dt.datetime(2026, 3, 10, 7, 1, tzinfo=ZoneInfo("America/New_York")),
                ],
            ),
        ]
    )
    request_options = {
        "n_jobs": 4,
        "show_tqdm": False,
        "ignore_cache": False,
        "calibration_executor": "process",
        "auto_prime_bulk": True,
        "stirf_fetch_max_workers": None,
        "calibration_max_workers": None,
    }

    all_curves, daily_results, summary = stirf_curve_calibration.run_bucketed_calibration(
        curve_mdp=FakeMDP(),
        curve_name="USD-SOFR-1D-Q12STIRT",
        source="BARCHART_STIRF-RL",
        daily_buckets=daily_buckets,
        request_options=request_options,
        perf_log_path=tmp_path / "perf.jsonl",
        logger=logging.getLogger("test_stirf_curve_calibration"),
        fail_fast=False,
        retain_all_curves=True,
    )

    assert len(all_curves) == 2
    assert len(daily_results) == 1
    assert summary["returned_curves"] == 2


def test_parse_args_backfill_defaults(monkeypatch):
    args = stirf_curve_calibration.parse_args(
        [
            "backfill",
            "--start-date",
            "2026-03-10",
            "--end-date",
            "2026-03-12",
        ]
    )

    assert args.mode == "backfill"
    assert args.backfill_local_cache is True
    assert args.rewrite_existing_supabase is True
    assert args.backfill_batch_size == stirf_curve_calibration.DEFAULT_BACKFILL_BATCH_SIZE


def test_backfill_local_curve_store_to_supabase_pushes_local_days_in_batches(tmp_path, monkeypatch):
    pushed = []

    class FakeSync:
        def __init__(self):
            self._engine = object()

        def push_day(self, curve_name, trading_date, *, event_calendar=None):
            pushed.append((curve_name, trading_date, dict(event_calendar or {})))
            return True

    monkeypatch.setattr(
        stirf_curve_calibration,
        "inspect_curve_store_sync_status",
        lambda **kwargs: {
            "curve_name": kwargs["curve_name"],
            "start_date": kwargs["start_date"].isoformat(),
            "end_date": kwargs["end_date"].isoformat(),
            "local_dates": [
                dt.date(2026, 3, 10),
                dt.date(2026, 3, 11),
                dt.date(2026, 3, 12),
            ],
            "remote_dates": [dt.date(2026, 3, 11)],
            "local_days": 3,
            "remote_days": 1,
            "local_only_days": 2,
            "local_only_dates": [dt.date(2026, 3, 10), dt.date(2026, 3, 12)],
        },
    )

    summary = stirf_curve_calibration.backfill_local_curve_store_to_supabase(
        curve_name="USD-SOFR-1D-Q12STIRT",
        start_date=dt.date(2026, 3, 10),
        end_date=dt.date(2026, 3, 12),
        batch_size=2,
        rewrite_existing=True,
        logger=logging.getLogger("test_stirf_curve_calibration"),
        perf_log_path=tmp_path / "perf.jsonl",
        sync=FakeSync(),
        event_calendar={dt.date(2026, 3, 11): {"tag": "FOMC_RATE_DECISION", "session_minute": 480}},
    )

    assert [item[1] for item in pushed] == [
        dt.date(2026, 3, 10),
        dt.date(2026, 3, 11),
        dt.date(2026, 3, 12),
    ]
    assert summary["queued_days"] == 3
    assert summary["pushed_days"] == 3
    assert summary["failed_days"] == 0

    events = [json.loads(line) for line in (tmp_path / "perf.jsonl").read_text(encoding="utf-8").splitlines()]
    assert [event["event"] for event in events] == [
        "supabase_backfill_day",
        "supabase_backfill_day",
        "supabase_backfill_batch",
        "supabase_backfill_day",
        "supabase_backfill_batch",
        "supabase_backfill_summary",
    ]
    assert [event["trading_date"] for event in events if event["event"] == "supabase_backfill_day"] == [
        "2026-03-10",
        "2026-03-11",
        "2026-03-12",
    ]


def test_backfill_local_curve_store_to_supabase_can_skip_existing_remote_days(tmp_path, monkeypatch):
    pushed = []

    class FakeSync:
        def __init__(self):
            self._engine = object()

        def push_day(self, curve_name, trading_date, *, event_calendar=None):
            _ = event_calendar
            pushed.append((curve_name, trading_date))
            return True

    monkeypatch.setattr(
        stirf_curve_calibration,
        "inspect_curve_store_sync_status",
        lambda **kwargs: {
            "curve_name": kwargs["curve_name"],
            "start_date": kwargs["start_date"].isoformat(),
            "end_date": kwargs["end_date"].isoformat(),
            "local_dates": [
                dt.date(2026, 3, 10),
                dt.date(2026, 3, 11),
                dt.date(2026, 3, 12),
            ],
            "remote_dates": [dt.date(2026, 3, 11)],
            "local_days": 3,
            "remote_days": 1,
            "local_only_days": 2,
            "local_only_dates": [dt.date(2026, 3, 10), dt.date(2026, 3, 12)],
        },
    )

    summary = stirf_curve_calibration.backfill_local_curve_store_to_supabase(
        curve_name="USD-SOFR-1D-Q12STIRT",
        start_date=dt.date(2026, 3, 10),
        end_date=dt.date(2026, 3, 12),
        batch_size=10,
        rewrite_existing=False,
        logger=logging.getLogger("test_stirf_curve_calibration"),
        perf_log_path=tmp_path / "perf.jsonl",
        sync=FakeSync(),
    )

    assert [item[1] for item in pushed] == [
        dt.date(2026, 3, 10),
        dt.date(2026, 3, 12),
    ]
    assert summary["queued_days"] == 2
    assert summary["pushed_days"] == 2
    assert summary["failed_days"] == 0


def test_main_backfill_only_skips_bucket_build(monkeypatch, tmp_path):
    monkeypatch.setattr(
        stirf_curve_calibration,
        "inspect_curve_store_sync_status",
        lambda **kwargs: {
            "curve_name": kwargs["curve_name"],
            "start_date": kwargs["start_date"].isoformat(),
            "end_date": kwargs["end_date"].isoformat(),
            "local_dates": [],
            "remote_dates": [],
            "local_days": 0,
            "remote_days": 0,
            "local_only_days": 0,
            "local_only_dates": [],
        },
    )
    monkeypatch.setattr(
        stirf_curve_calibration,
        "backfill_local_curve_store_to_supabase",
        lambda **kwargs: {
            "status": "ok",
            "pushed_days": 0,
            "failed_days": 0,
            "queued_days": 0,
        },
    )

    def _boom(*args, **kwargs):
        raise AssertionError("build_daily_minute_buckets should not be called in backfill-only mode")

    monkeypatch.setattr(stirf_curve_calibration, "iter_daily_minute_buckets", _boom)

    exit_code = stirf_curve_calibration.main(
        [
            "backfill",
            "--start-date",
            "2026-03-10",
            "--end-date",
            "2026-03-12",
            "--backfill-only",
            "--perf-log-path",
            str(tmp_path / "perf.jsonl"),
        ]
    )

    assert exit_code == 0


def test_release_barchart_runtime_state_clears_builder_cache(monkeypatch):
    class FakeChildMDP:
        def __init__(self):
            self.closed = False
            self._cache_ready = True

        def close_cache(self):
            self.closed = True

    class FakeBuilder:
        _CURVE_MEM_CACHE = {"curve-a": object(), "curve-b": object()}
        _CURVE_MEM_CACHE_LOCK = threading.Lock()

        def __init__(self):
            self.closed = False
            self.stirf_mdp = FakeChildMDP()
            self.stirf_mdp_schwab_app = FakeChildMDP()
            self.stirf_mdp_barchart = FakeChildMDP()

        def close_cache(self):
            self.closed = True

    fake_builder = FakeBuilder()
    fake_state = {
        "builder": fake_builder,
        "lock": threading.RLock(),
        "io_lock": threading.RLock(),
    }
    monkeypatch.setattr(stirf_curve_calibration.IRSwapsMDP, "_BARCHART_STIRF_STATE", fake_state)

    stirf_curve_calibration._release_barchart_runtime_state(
        source="BARCHART_STIRF-RL",
        logger=logging.getLogger("test_stirf_curve_calibration"),
    )

    assert fake_state["builder"] is None
    assert FakeBuilder._CURVE_MEM_CACHE == {}
    assert fake_builder.closed is True
    assert fake_builder.stirf_mdp.closed is True
    assert fake_builder.stirf_mdp._cache_ready is False
    assert fake_builder.stirf_mdp_schwab_app.closed is True
    assert fake_builder.stirf_mdp_barchart.closed is True
