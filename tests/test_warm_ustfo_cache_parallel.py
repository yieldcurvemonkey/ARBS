import datetime as dt

import pytest

import MDP.USTFutures.USTFutureOptionMDP as ustfo_module
import MDP.USTFutures.warm_ustfo_cache_parallel as warm_mod
from MDP.USTFutures.warm_ustfo_cache_parallel import (
    DateRange,
    WorkerProgress,
    _format_worker_heartbeat,
    _warm_range,
    _snapshot_worker_progress,
    ensure_non_overlapping,
    parse_range_token,
    split_contiguous_date_ranges,
)


def test_parse_range_token_round_trips_dates():
    parsed = parse_range_token("2025-09-08:2025-10-03")
    assert parsed == DateRange(dt.date(2025, 9, 8), dt.date(2025, 10, 3))
    assert parsed.label == "2025-09-08:2025-10-03"


def test_split_contiguous_date_ranges_preserves_order_and_balance():
    dates = [dt.date(2025, 9, day) for day in range(8, 18)]
    ranges = split_contiguous_date_ranges(dates, 3)
    assert ranges == [
        DateRange(dt.date(2025, 9, 8), dt.date(2025, 9, 11)),
        DateRange(dt.date(2025, 9, 12), dt.date(2025, 9, 14)),
        DateRange(dt.date(2025, 9, 15), dt.date(2025, 9, 17)),
    ]


def test_split_contiguous_date_ranges_caps_chunks_at_available_dates():
    dates = [dt.date(2025, 9, 8), dt.date(2025, 9, 9)]
    ranges = split_contiguous_date_ranges(dates, 5)
    assert ranges == [
        DateRange(dt.date(2025, 9, 8), dt.date(2025, 9, 8)),
        DateRange(dt.date(2025, 9, 9), dt.date(2025, 9, 9)),
    ]


def test_ensure_non_overlapping_sorts_and_rejects_overlap():
    ranges = ensure_non_overlapping(
        [
            DateRange(dt.date(2025, 10, 1), dt.date(2025, 10, 31)),
            DateRange(dt.date(2025, 9, 1), dt.date(2025, 9, 30)),
        ]
    )
    assert ranges[0].label == "2025-09-01:2025-09-30"
    assert ranges[1].label == "2025-10-01:2025-10-31"

    with pytest.raises(ValueError, match="overlap"):
        ensure_non_overlapping(
            [
                DateRange(dt.date(2025, 9, 1), dt.date(2025, 9, 30)),
                DateRange(dt.date(2025, 9, 30), dt.date(2025, 10, 15)),
            ]
        )


def test_format_worker_heartbeat_includes_progress_and_idle_time():
    progress = WorkerProgress(
        range_label="2025-09-08:2025-10-03",
        pid=12345,
        total_dates=20,
        total_pairs=60,
        completed_dates=7,
        completed_pairs=21,
        snapshot_requests=21,
        smile_requests=19,
        failure_count=2,
        current_date="2025-09-17",
        current_cmt="60",
        started_monotonic=100.0,
        last_update_monotonic=125.0,
    )
    snapshot = _snapshot_worker_progress(progress, now_monotonic=130.0)
    rendered = _format_worker_heartbeat(snapshot, tag="[worker-start]")

    assert "pid=12345" in rendered
    assert "range=2025-09-08:2025-10-03" in rendered
    assert "dates=7/20" in rendered
    assert "pairs=21/60" in rendered
    assert "current_date=2025-09-17" in rendered
    assert "current_cmt=60" in rendered
    assert "snapshot_calls=21" in rendered
    assert "smile_calls=19" in rendered
    assert "failures=2" in rendered
    assert "elapsed_s=30.0" in rendered
    assert "idle_s=5.0" in rendered


def test_warm_range_uses_bulk_smile_seed_for_dual_source(monkeypatch):
    d1 = dt.date(2025, 9, 8)
    d2 = dt.date(2025, 9, 9)
    seen = {"bulk_requests": []}

    class _DummyUSTFutureOptionMDP:
        def __init__(self, source):
            assert source == "USTFO_DUAL-QL"

        def fetch_bulk_sabr_smile(self, request):
            seen["bulk_requests"].append(request)
            return {symbol: {d1: object(), d2: object()} for symbol in request["globex_symbols"]}

        def get_pricer(self, request):
            raise AssertionError("dual-source warming should seed snapshot cache via bulk SABR fetch")

    monkeypatch.setattr(warm_mod, "ql_cal_date_range", lambda **kwargs: [d1, d2])
    monkeypatch.setattr(ustfo_module, "USTFutureOptionMDP", _DummyUSTFutureOptionMDP)

    out = _warm_range(
        DateRange(d1, d2),
        source="USTFO_DUAL-QL",
        roots=("TY",),
        cmts=("30",),
        warm_snapshot=True,
        warm_smile=True,
        use_ql_calculator=True,
        startup_delay_seconds=0.0,
        heartbeat_seconds=0.0,
    )

    assert len(seen["bulk_requests"]) == 1
    assert seen["bulk_requests"][0]["globex_symbols"] == ["TY_30"]
    assert seen["bulk_requests"][0]["timestamps"] == [d1, d2]
    assert out.snapshot_requests == 2
    assert out.smile_requests == 2
    assert out.failure_count == 0


def test_warm_range_retries_retryable_bulk_dual_source_errors(monkeypatch):
    d1 = dt.date(2025, 9, 8)
    d2 = dt.date(2025, 9, 9)
    seen = {"bulk_calls": 0, "sleep_calls": []}

    class _DummyUSTFutureOptionMDP:
        def __init__(self, source):
            assert source == "USTFO_DUAL-QL"

        def fetch_bulk_sabr_smile(self, request):
            _ = request
            seen["bulk_calls"] += 1
            if seen["bulk_calls"] == 1:
                raise RuntimeError("SOCKS5 authentication failed")
            return {"TY_30": {d1: object(), d2: object()}}

        def get_pricer(self, request):
            raise AssertionError("retryable bulk seed failure should not fall back after a successful retry")

    monkeypatch.setattr(warm_mod, "ql_cal_date_range", lambda **kwargs: [d1, d2])
    monkeypatch.setattr(warm_mod.time, "sleep", lambda seconds: seen["sleep_calls"].append(seconds))
    monkeypatch.setattr(ustfo_module, "USTFutureOptionMDP", _DummyUSTFutureOptionMDP)

    out = _warm_range(
        DateRange(d1, d2),
        source="USTFO_DUAL-QL",
        roots=("TY",),
        cmts=("30",),
        warm_snapshot=True,
        warm_smile=True,
        use_ql_calculator=True,
        startup_delay_seconds=0.0,
        heartbeat_seconds=0.0,
    )

    assert seen["bulk_calls"] == 2
    assert seen["sleep_calls"] == [1.0]
    assert out.failure_count == 0


def test_warm_range_dual_source_skips_bad_symbol_during_per_date_smile_warm(monkeypatch):
    d1 = dt.date(2025, 9, 8)
    d2 = dt.date(2025, 9, 9)
    seen = {"bulk_requests": [], "snapshot_requests": []}

    class _DummyUSTFutureOptionMDP:
        def __init__(self, source):
            assert source == "USTFO_DUAL-QL"

        def fetch_bulk_sabr_smile(self, request):
            payload = {
                "globex_symbols": list(request["globex_symbols"]),
                "timestamps": list(request["timestamps"]),
                "show_tqdm": request["show_tqdm"],
                "use_ql_calculator": request.get("use_ql_calculator"),
            }
            seen["bulk_requests"].append(payload)

            symbols = payload["globex_symbols"]
            timestamps = payload["timestamps"]
            if symbols == ["TU_30", "FV_30"] and timestamps == [d1, d2]:
                raise ValueError("range batch failed")
            if symbols == ["TU_30", "FV_30"]:
                raise ValueError("day batch failed")
            if symbols == ["TU_30"]:
                raise ValueError("Not enough valid SABR smile legs")
            return {symbol: {timestamp: object() for timestamp in timestamps} for symbol in symbols}

        def get_pricer(self, request):
            seen["snapshot_requests"].append(
                {
                    "symbols": list(request["symbols"]),
                    "timestamp": request["timestamp"],
                    "use_ql_calculator": request["use_ql_calculator"],
                }
            )
            return {}

    monkeypatch.setattr(warm_mod, "ql_cal_date_range", lambda **kwargs: [d1, d2])
    monkeypatch.setattr(ustfo_module, "USTFutureOptionMDP", _DummyUSTFutureOptionMDP)

    out = _warm_range(
        DateRange(d1, d2),
        source="USTFO_DUAL-QL",
        roots=("TU", "FV"),
        cmts=("30",),
        warm_snapshot=True,
        warm_smile=True,
        use_ql_calculator=True,
        startup_delay_seconds=0.0,
        heartbeat_seconds=0.0,
    )

    assert seen["snapshot_requests"] == [
        {
            "symbols": ["TU_30|ATMS", "FV_30|ATMS"],
            "timestamp": d1,
            "use_ql_calculator": True,
        },
        {
            "symbols": ["TU_30|ATMS", "FV_30|ATMS"],
            "timestamp": d2,
            "use_ql_calculator": True,
        },
    ]
    assert seen["bulk_requests"] == [
        {
            "globex_symbols": ["TU_30", "FV_30"],
            "timestamps": [d1, d2],
            "show_tqdm": False,
            "use_ql_calculator": True,
        },
        {
            "globex_symbols": ["TU_30", "FV_30"],
            "timestamps": [d1],
            "show_tqdm": False,
            "use_ql_calculator": True,
        },
        {
            "globex_symbols": ["TU_30"],
            "timestamps": [d1],
            "show_tqdm": False,
            "use_ql_calculator": True,
        },
        {
            "globex_symbols": ["FV_30"],
            "timestamps": [d1],
            "show_tqdm": False,
            "use_ql_calculator": True,
        },
        {
            "globex_symbols": ["TU_30", "FV_30"],
            "timestamps": [d2],
            "show_tqdm": False,
            "use_ql_calculator": True,
        },
        {
            "globex_symbols": ["TU_30"],
            "timestamps": [d2],
            "show_tqdm": False,
            "use_ql_calculator": True,
        },
        {
            "globex_symbols": ["FV_30"],
            "timestamps": [d2],
            "show_tqdm": False,
            "use_ql_calculator": True,
        },
    ]
    assert out.snapshot_requests == 2
    assert out.smile_requests == 2
    assert out.failure_count == 2
    assert out.failures == [
        {
            **out.failures[0],
            "date": "2025-09-08",
            "cmt": "30",
            "symbol": "TU_30",
            "error": "Not enough valid SABR smile legs",
        },
        {
            **out.failures[1],
            "date": "2025-09-09",
            "cmt": "30",
            "symbol": "TU_30",
            "error": "Not enough valid SABR smile legs",
        },
    ]


def test_warm_range_dual_source_skips_bad_symbol_during_per_date_snapshot_warm(monkeypatch):
    d1 = dt.date(2025, 9, 8)
    seen = {"bulk_requests": [], "snapshot_requests": []}

    class _DummyUSTFutureOptionMDP:
        def __init__(self, source):
            assert source == "USTFO_DUAL-QL"

        def fetch_bulk_sabr_smile(self, request):
            payload = {
                "globex_symbols": list(request["globex_symbols"]),
                "timestamps": list(request["timestamps"]),
                "show_tqdm": request["show_tqdm"],
                "use_ql_calculator": request.get("use_ql_calculator"),
            }
            seen["bulk_requests"].append(payload)
            raise ValueError("range batch failed")

        def get_pricer(self, request):
            payload = {
                "symbols": list(request["symbols"]),
                "timestamp": request["timestamp"],
                "use_ql_calculator": request["use_ql_calculator"],
            }
            seen["snapshot_requests"].append(payload)
            if payload["symbols"] == ["TU_30|ATMS", "FV_30|ATMS"]:
                raise ValueError("snapshot day batch failed")
            if payload["symbols"] == ["TU_30|ATMS"]:
                raise ValueError("Could not resolve dual-source constant-maturity option aliases: TU_30|ATMS")
            return {}

    monkeypatch.setattr(warm_mod, "ql_cal_date_range", lambda **kwargs: [d1])
    monkeypatch.setattr(ustfo_module, "USTFutureOptionMDP", _DummyUSTFutureOptionMDP)

    out = _warm_range(
        DateRange(d1, d1),
        source="USTFO_DUAL-QL",
        roots=("TU", "FV"),
        cmts=("30",),
        warm_snapshot=True,
        warm_smile=False,
        use_ql_calculator=True,
        startup_delay_seconds=0.0,
        heartbeat_seconds=0.0,
    )

    assert seen["bulk_requests"] == [
        {
            "globex_symbols": ["TU_30", "FV_30"],
            "timestamps": [d1],
            "show_tqdm": False,
            "use_ql_calculator": True,
        }
    ]
    assert seen["snapshot_requests"] == [
        {
            "symbols": ["TU_30|ATMS", "FV_30|ATMS"],
            "timestamp": d1,
            "use_ql_calculator": True,
        },
        {
            "symbols": ["TU_30|ATMS"],
            "timestamp": d1,
            "use_ql_calculator": True,
        },
        {
            "symbols": ["FV_30|ATMS"],
            "timestamp": d1,
            "use_ql_calculator": True,
        },
    ]
    assert out.snapshot_requests == 1
    assert out.smile_requests == 0
    assert out.failure_count == 1
    assert out.failures == [
        {
            **out.failures[0],
            "date": "2025-09-08",
            "cmt": "30",
            "symbol": "TU_30|ATMS",
            "error": "Could not resolve dual-source constant-maturity option aliases: TU_30|ATMS",
        }
    ]
