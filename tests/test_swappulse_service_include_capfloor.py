import sys
import types
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path


MODULE_PATH = (
    Path(__file__).resolve().parents[1]
    / "SDRUtils"
    / "_swappulse_scripts"
    / "ingest_usdswaptions.py"
)
SPEC = spec_from_file_location("ingest_usdswaptions_test", MODULE_PATH)
assert SPEC and SPEC.loader
ingest_module = module_from_spec(SPEC)
SPEC.loader.exec_module(ingest_module)


def test_main_incremental_include_capfloor_runs_both_ingesters(monkeypatch):
    calls: list[tuple[str, object, dict | None]] = []
    engine = object()

    monkeypatch.setattr(ingest_module, "_resolve_cache_path", lambda path: path or "cache")
    monkeypatch.setattr(ingest_module, "create_db_engine", lambda: engine)
    monkeypatch.setattr(
        ingest_module,
        "ensure_schema",
        lambda passed_engine: calls.append(("ensure_schema", passed_engine, None)),
    )
    monkeypatch.setattr(
        ingest_module,
        "ingest_incremental_once",
        lambda passed_engine, **kwargs: calls.append(("swaption", passed_engine, kwargs)),
    )
    monkeypatch.setattr(
        ingest_module,
        "_ingest_capfloor_incremental_once",
        lambda passed_engine, **kwargs: calls.append(("capfloor", passed_engine, kwargs)),
    )

    ingest_module.main_incremental(
        cache_path="C:/tmp/cache",
        only_newt=True,
        dry_run=True,
        cleanup_orphans=False,
        initial_lookback_minutes=90,
        overlap_seconds=15,
        include_capfloor=True,
        market_timezone="America/Chicago",
    )

    assert calls[0] == ("ensure_schema", engine, None)
    assert calls[1][0] == "swaption"
    assert calls[1][1] is engine
    assert calls[1][2] == {
        "cache_path": "C:/tmp/cache",
        "ignore_cache": False,
        "only_newt": True,
        "dry_run": True,
        "cleanup_orphans": False,
        "initial_lookback_minutes": 90,
        "overlap_seconds": 15,
    }
    assert calls[2][0] == "capfloor"
    assert calls[2][1] is engine
    assert calls[2][2] == {
        "cache_path": "C:/tmp/cache",
        "ignore_cache": False,
        "only_newt": True,
        "dry_run": True,
        "cleanup_orphans": False,
        "initial_lookback_minutes": 90,
        "overlap_seconds": 15,
        "market_timezone": "America/Chicago",
    }


def test_main_service_include_capfloor_runs_both_in_same_cycle(monkeypatch):
    calls: list[tuple[str, object, dict | None]] = []
    engine = object()

    monkeypatch.setattr(ingest_module, "_resolve_cache_path", lambda path: path or "cache")
    monkeypatch.setattr(ingest_module, "create_db_engine", lambda: engine)
    monkeypatch.setattr(
        ingest_module,
        "ensure_schema",
        lambda passed_engine: calls.append(("ensure_schema", passed_engine, None)),
    )
    monkeypatch.setattr(
        ingest_module,
        "ingest_incremental_once",
        lambda passed_engine, **kwargs: calls.append(("swaption", passed_engine, kwargs)),
    )
    monkeypatch.setattr(
        ingest_module,
        "_ingest_capfloor_incremental_once",
        lambda passed_engine, **kwargs: calls.append(("capfloor", passed_engine, kwargs)),
    )

    ingest_module.main_service(
        interval_seconds=30,
        cache_path="C:/tmp/cache",
        only_newt=False,
        dry_run=True,
        cleanup_orphans=True,
        initial_lookback_minutes=120,
        overlap_seconds=25,
        smart_intervals=False,
        max_iterations=1,
        include_capfloor=True,
        market_timezone="America/New_York",
    )

    assert calls[0] == ("ensure_schema", engine, None)
    assert calls[1][0] == "swaption"
    assert calls[1][1] is engine
    assert calls[1][2]["force_fetch_end_of_day"] is True
    assert calls[1][2]["force_fetch_full_market_day"] is True
    assert calls[1][2]["ignore_cache"] is False
    assert calls[1][2]["market_timezone"] == "America/New_York"
    assert calls[2][0] == "capfloor"
    assert calls[2][1] is engine
    assert calls[2][2] == {
        "cache_path": "C:/tmp/cache",
        "ignore_cache": False,
        "only_newt": False,
        "dry_run": True,
        "cleanup_orphans": True,
        "initial_lookback_minutes": 120,
        "overlap_seconds": 25,
        "market_timezone": "America/New_York",
    }


def test_parse_args_accepts_include_capfloor(monkeypatch):
    monkeypatch.setattr(
        sys,
        "argv",
        ["ingest_usdswaptions.py", "--mode", "service", "--include-capfloor"],
    )

    args = ingest_module.parse_args()

    assert args.mode == "service"
    assert args.include_capfloor is True


def test_parse_args_accepts_daily_range(monkeypatch):
    monkeypatch.setattr(
        sys,
        "argv",
        ["ingest_usdswaptions.py", "--mode", "daily-range", "--continue-on-error"],
    )

    args = ingest_module.parse_args()

    assert args.mode == "daily-range"
    assert args.continue_on_error is True


def test_capfloor_helper_uses_exact_swaption_cache_path(monkeypatch):
    captured: list[tuple[object, dict]] = []
    fake_module = types.SimpleNamespace(
        ensure_schema=lambda engine: None,
        ingest_incremental_once=lambda engine, **kwargs: captured.append((engine, kwargs)),
    )

    monkeypatch.setattr(ingest_module, "_load_capfloor_ingest_module", lambda: fake_module)

    engine = object()
    shared_cache_path = r"C:\Users\chris\clee\project-oasis\private\sdranalytics\.cache"
    ingest_module._ingest_capfloor_incremental_once(
        engine,
        cache_path=shared_cache_path,
        ignore_cache=False,
        only_newt=False,
        dry_run=False,
        cleanup_orphans=True,
        initial_lookback_minutes=1440,
        overlap_seconds=0,
        market_timezone="America/New_York",
    )

    assert captured == [
        (
            engine,
            {
                "cache_path": shared_cache_path,
                "ignore_cache": False,
                "only_newt": False,
                "dry_run": False,
                "cleanup_orphans": True,
                "initial_lookback_minutes": 1440,
                "overlap_seconds": 0,
                "force_fetch_end_of_day": True,
                "force_fetch_full_market_day": True,
                "market_timezone": "America/New_York",
            },
        )
    ]


def test_main_daily_range_splits_utc_days_and_runs_both_paths(monkeypatch):
    swaption_calls: list[dict] = []
    capfloor_calls: list[dict] = []
    ensured: list[tuple[str, object]] = []
    engine = object()
    fake_capfloor_module = types.SimpleNamespace(
        ensure_schema=lambda passed_engine: ensured.append(("capfloor", passed_engine)),
    )

    monkeypatch.setattr(ingest_module, "_resolve_cache_path", lambda path: path or "cache")
    monkeypatch.setattr(ingest_module, "create_db_engine", lambda: engine)
    monkeypatch.setattr(
        ingest_module,
        "ensure_schema",
        lambda passed_engine: ensured.append(("swaption", passed_engine)),
    )
    monkeypatch.setattr(
        ingest_module,
        "_load_capfloor_ingest_module",
        lambda: fake_capfloor_module,
    )
    monkeypatch.setattr(
        ingest_module,
        "_run_swaption_range_window",
        lambda **kwargs: swaption_calls.append(kwargs),
    )
    monkeypatch.setattr(
        ingest_module,
        "_run_capfloor_range_window",
        lambda **kwargs: capfloor_calls.append(kwargs),
    )

    ingest_module.main_daily_range(
        start="2025-06-20T10:15:00Z",
        end="2025-06-22T01:00:00Z",
        cache_path="C:/tmp/cache",
        ignore_cache=False,
        only_newt=True,
        dry_run=False,
        include_capfloor=True,
    )

    assert ensured == [("swaption", engine), ("capfloor", engine)]
    assert len(swaption_calls) == 3
    assert len(capfloor_calls) == 3

    expected_windows = [
        (
            "2025-06-20 10:15:00+00:00",
            "2025-06-20 23:59:59.999999999+00:00",
        ),
        (
            "2025-06-21 00:00:00+00:00",
            "2025-06-21 23:59:59.999999999+00:00",
        ),
        (
            "2025-06-22 00:00:00+00:00",
            "2025-06-22 01:00:00+00:00",
        ),
    ]

    for idx, (expected_start, expected_end) in enumerate(expected_windows):
        swaption_call = swaption_calls[idx]
        capfloor_call = capfloor_calls[idx]
        assert str(swaption_call["start"]) == expected_start
        assert str(swaption_call["end"]) == expected_end
        assert swaption_call["cache_path"] == "C:/tmp/cache"
        assert swaption_call["ignore_cache"] is False
        assert swaption_call["only_newt"] is True
        assert swaption_call["dry_run"] is False
        assert swaption_call["engine"] is engine

        assert str(capfloor_call["start"]) == expected_start
        assert str(capfloor_call["end"]) == expected_end
        assert capfloor_call["cache_path"] == "C:/tmp/cache"
        assert capfloor_call["ignore_cache"] is False
        assert capfloor_call["only_newt"] is True
        assert capfloor_call["dry_run"] is False
        assert capfloor_call["engine"] is engine
        assert capfloor_call["capfloor_ingest"] is fake_capfloor_module


def test_main_daily_range_continue_on_error_logs_failed_day_and_continues(monkeypatch, capsys):
    attempted_dates: list[str] = []
    completed_dates: list[str] = []
    engine = object()

    monkeypatch.setattr(ingest_module, "_resolve_cache_path", lambda path: path or "cache")
    monkeypatch.setattr(ingest_module, "create_db_engine", lambda: engine)
    monkeypatch.setattr(ingest_module, "ensure_schema", lambda passed_engine: None)

    def fake_run_swaption_range_window(**kwargs):
        window_date = kwargs["start"].date().isoformat()
        attempted_dates.append(window_date)
        if window_date == "2025-06-21":
            raise RuntimeError("boom")
        completed_dates.append(window_date)

    monkeypatch.setattr(
        ingest_module,
        "_run_swaption_range_window",
        fake_run_swaption_range_window,
    )

    ingest_module.main_daily_range(
        start="2025-06-20T00:00:00Z",
        end="2025-06-22T23:59:59Z",
        cache_path="C:/tmp/cache",
        ignore_cache=False,
        only_newt=False,
        dry_run=False,
        continue_on_error=True,
    )

    assert attempted_dates == ["2025-06-20", "2025-06-21", "2025-06-22"]
    assert completed_dates == ["2025-06-20", "2025-06-22"]

    stdout = capsys.readouterr().out
    assert "DAILY-RANGE ERROR SUMMARY" in stdout
    assert "2025-06-21 [SWAPTION]: boom" in stdout
