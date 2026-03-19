import datetime as dt
import importlib.util
import json
import logging
import sys
import threading
from collections import OrderedDict
from pathlib import Path
from zoneinfo import ZoneInfo


MODULE_PATH = Path(__file__).resolve().parents[1] / "notebooks" / "stirf_curve_calibration.py"
SPEC = importlib.util.spec_from_file_location("stirf_curve_calibration_module", MODULE_PATH)
stirf_curve_calibration = importlib.util.module_from_spec(SPEC)
assert SPEC is not None and SPEC.loader is not None
sys.modules[SPEC.name] = stirf_curve_calibration
SPEC.loader.exec_module(stirf_curve_calibration)


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
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "stirf_curve_calibration.py",
            "--start-date",
            "2026-03-10",
            "--end-date",
            "2026-03-12",
        ],
    )

    args = stirf_curve_calibration.parse_args()

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
        "parse_args",
        lambda: type(
            "Args",
            (),
            {
                "source": "BARCHART_STIRF-RL",
                "curve_name": "USD-SOFR-1D-Q12STIRT",
                "start_date": "2026-03-10",
                "end_date": "2026-03-12",
                "session_start": "07:00",
                "session_end": "17:00",
                "cme_session": False,
                "freq": "1min",
                "timezone": "America/New_York",
                "n_jobs": 8,
                "calibration_executor": "process",
                "stirf_fetch_max_workers": None,
                "calibration_max_workers": None,
                "ignore_cache": False,
                "fail_fast": False,
                "backfill_only": True,
                "backfill_batch_size": 25,
                "verbose": False,
                "show_tqdm": True,
                "auto_prime_bulk": True,
                "backfill_local_cache": True,
                "rewrite_existing_supabase": True,
                "perf_log_path": str(tmp_path / "perf.jsonl"),
            },
        )()
    )
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

    monkeypatch.setattr(stirf_curve_calibration, "build_daily_minute_buckets", _boom)

    exit_code = stirf_curve_calibration.main()

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
