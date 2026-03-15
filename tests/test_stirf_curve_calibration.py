import datetime as dt
import importlib.util
import json
import logging
import sys
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

    assert len(all_curves) == 2
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
