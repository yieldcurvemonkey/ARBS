import datetime as dt
import itertools
import threading
from argparse import Namespace

import pandas as pd

import SDRUtils._swappulse_scripts.ingest_listed_option_oi_volume as ingest_module
from SDRUtils._swappulse_scripts.ingest_listed_option_oi_volume import (
    _fetch_history_in_batches,
    _get_barchart_fetcher,
    _resolve_once_ingest_window,
    build_contract_universe,
    build_option_symbol_universe,
    collect_history_rows,
    normalize_history_row,
    persist_rows,
)


def test_build_option_symbol_universe_dedupes_across_contract_days(monkeypatch):
    contract_universe = {
        dt.date(2026, 3, 3): {"UST": ["ZNM26"], "STIR": []},
        dt.date(2026, 3, 4): {"UST": ["ZNM26"], "STIR": []},
    }

    monkeypatch.setattr(
        "SDRUtils._swappulse_scripts.ingest_listed_option_oi_volume._extract_forward_price",
        lambda df, as_of_date: 112.625,
    )
    monkeypatch.setattr(
        "SDRUtils._swappulse_scripts.ingest_listed_option_oi_volume._ust_listed_strikes_for_contract",
        lambda **kwargs: [112.5, 112.5, 112.625],
    )
    monkeypatch.setattr(
        "SDRUtils._swappulse_scripts.ingest_listed_option_oi_volume._format_ust_barchart_strike",
        lambda contract, strike: "1125" if strike < 112.625 else "1126",
    )

    symbols = build_option_symbol_universe(
        contract_universe=contract_universe,
        underlying_data={"ZNM26": pd.DataFrame()},
    )

    assert symbols == [
        "ZNM26|1125C",
        "ZNM26|1125P",
        "ZNM26|1126C",
        "ZNM26|1126P",
    ]


def test_build_option_symbol_universe_skips_unencodable_ust_strikes(monkeypatch):
    contract_universe = {
        dt.date(2026, 3, 4): {"UST": ["ZNM26"], "STIR": []},
    }

    monkeypatch.setattr(
        "SDRUtils._swappulse_scripts.ingest_listed_option_oi_volume._extract_forward_price",
        lambda df, as_of_date: 112.625,
    )
    monkeypatch.setattr(
        "SDRUtils._swappulse_scripts.ingest_listed_option_oi_volume._ust_listed_strikes_for_contract",
        lambda **kwargs: [112.25, 112.5, 112.75],
    )
    monkeypatch.setattr(
        "SDRUtils._swappulse_scripts.ingest_listed_option_oi_volume._format_ust_barchart_strike",
        lambda contract, strike: (_ for _ in ()).throw(ValueError("bad strike"))
        if strike == 112.25
        else ("1125" if strike == 112.5 else "1127"),
    )

    symbols = build_option_symbol_universe(
        contract_universe=contract_universe,
        underlying_data={"ZNM26": pd.DataFrame()},
    )

    assert symbols == [
        "ZNM26|1125C",
        "ZNM26|1125P",
        "ZNM26|1127C",
        "ZNM26|1127P",
    ]


def test_normalize_history_row_computes_offsets_and_dte(monkeypatch):
    monkeypatch.setattr(
        "SDRUtils._swappulse_scripts.ingest_listed_option_oi_volume._extract_forward_price",
        lambda df, as_of_date: 112.625,
    )

    normalized = normalize_history_row(
        explicit_option_symbol="ZNM26|1125C",
        as_of_date=dt.date(2026, 3, 4),
        row={
            "open": 0.35,
            "high": 0.40,
            "low": 0.33,
            "close": 0.37,
            "volume": 5116,
            "openinterest": 27916,
            "delta": 0.58,
            "gamma": 0.44,
            "theta": -0.0002,
            "vega": 0.015,
            "impliedVolatility": 0.1929,
        },
        underlying_data={"ZNM26": pd.DataFrame()},
    )

    assert normalized is not None
    assert normalized["product_family"] == "UST"
    assert normalized["product_root"] == "TY"
    assert normalized["open_interest"] == 27916
    assert normalized["volume"] == 5116
    assert normalized["delta_abs"] == 0.58
    assert normalized["atm_strike"] == 112.5
    assert normalized["atm_offset_bps"] == 0.0
    assert normalized["dte_days"] >= 0


def test_build_contract_universe_filters_specific_stir_underlying_and_excludes_midcurves(monkeypatch):
    as_of = dt.date(2026, 3, 4)

    monkeypatch.setattr(
        ingest_module,
        "_business_dates",
        lambda start_date, end_date: [as_of],
    )
    monkeypatch.setattr(
        ingest_module,
        "_ust_contracts_for_day",
        lambda day: ["ZNM26"],
    )
    monkeypatch.setattr(
        ingest_module,
        "_stir_contracts_for_day",
        lambda day: ["SFRZ27", "0QZ26", "2QZ25", "SFRH28", "SERZ27"],
    )

    universe = build_contract_universe(
        as_of,
        as_of,
        underlying_contracts=["SFRZ27"],
    )

    assert universe == {
        as_of: {
            "UST": [],
            "STIR": ["SFRZ27"],
        }
    }


def test_build_contract_universe_includes_requested_stir_underlying_outside_default_horizon(monkeypatch):
    as_of = dt.date(2026, 3, 4)

    monkeypatch.setattr(
        ingest_module,
        "_business_dates",
        lambda start_date, end_date: [as_of],
    )
    monkeypatch.setattr(
        ingest_module,
        "_ust_contracts_for_day",
        lambda day: [],
    )
    monkeypatch.setattr(
        ingest_module,
        "_stir_contracts_for_day",
        lambda day: ["SFRU27"],
    )

    universe = build_contract_universe(
        as_of,
        as_of,
        underlying_contracts=["SFRZ27"],
    )

    assert universe[as_of]["STIR"] == ["SFRZ27"]


def test_collect_history_rows_skips_empty_option_frames(monkeypatch):
    class _FakeFetcher:
        calls = 0

        def __init__(self, *args, **kwargs):
            self.closed = False

        def _fetch_session_tokens(self, dummy_symbol="BTC"):  # noqa: ARG002
            return None

        def fetch_futures_options_timeseries(self, *, start, end, symbols, show_tqdm=False, max_concurrent_tasks=None, max_keepalive_connections=None):  # noqa: ARG002
            type(self).calls += 1
            if type(self).calls == 1:
                return {"ZNM26": pd.DataFrame({"close": [112.625]}, index=pd.to_datetime(["2026-03-04"]))}
            return {
                "ZNM26|1125C": pd.DataFrame(
                    {
                        "open": [0.35],
                        "high": [0.40],
                        "low": [0.33],
                        "close": [0.37],
                        "volume": [5116],
                        "openinterest": [27916],
                        "delta": [0.58],
                        "gamma": [0.44],
                        "theta": [-0.0002],
                        "vega": [0.015],
                        "impliedVolatility": [0.1929],
                    },
                    index=pd.to_datetime(["2026-03-04"]),
                ),
                "ZNM26|1125P": pd.DataFrame(),
            }

        def close(self):
            self.closed = True

    monkeypatch.setattr(
        "SDRUtils._swappulse_scripts.ingest_listed_option_oi_volume.build_contract_universe",
        lambda start_date, end_date, underlying_contracts=None: {  # noqa: ARG005
            dt.date(2026, 3, 4): {"UST": ["ZNM26"], "STIR": []}
        },
    )
    monkeypatch.setattr(
        "SDRUtils._swappulse_scripts.ingest_listed_option_oi_volume.build_underlying_symbol_universe",
        lambda contract_universe: ["ZNM26"],
    )
    monkeypatch.setattr(
        "SDRUtils._swappulse_scripts.ingest_listed_option_oi_volume.build_option_symbol_universe",
        lambda **kwargs: ["ZNM26|1125C", "ZNM26|1125P"],
    )
    monkeypatch.setattr(
        "SDRUtils._swappulse_scripts.ingest_listed_option_oi_volume.BarchartFetcher",
        _FakeFetcher,
    )

    rows = collect_history_rows(
        start_date=dt.date(2026, 3, 4),
        end_date=dt.date(2026, 3, 4),
        force_refresh=False,
        show_tqdm=False,
    )

    assert len(rows) == 1
    assert rows[0]["explicit_option_symbol"] == "ZNM26|1125C"


def test_fetch_history_in_batches_chunks_by_script_batch_size():
    class _FakeFetcher:
        def __init__(self):
            self.batch_sizes = []
            self.closed = False

        def fetch_futures_options_timeseries(self, *, start, end, symbols, show_tqdm=False, max_concurrent_tasks=None, max_keepalive_connections=None):  # noqa: ARG002
            self.batch_sizes.append(len(symbols))
            return {
                str(symbol): pd.DataFrame({"close": [1.0]}, index=pd.to_datetime(["2026-03-04"]))
                for symbol in symbols
            }

        def close(self):
            self.closed = True

    fetchers = []

    def _factory():
        fetcher = _FakeFetcher()
        fetchers.append(fetcher)
        return fetcher

    batch_size = ingest_module.MAX_BARCHART_SYMBOLS_PER_CALL
    symbols = [f"SYM{idx:03d}" for idx in range((batch_size * 2) + 3)]

    data = _fetch_history_in_batches(
        start=dt.date(2026, 3, 4),
        end=dt.date(2026, 3, 4),
        symbols=symbols,
        show_tqdm=False,
        fetcher_factory=_factory,
    )

    assert [fetcher.batch_sizes for fetcher in fetchers] == [[batch_size], [batch_size], [3]]
    assert len({id(fetcher) for fetcher in fetchers}) == 3
    assert all(fetcher.closed for fetcher in fetchers)
    assert list(data) == symbols


def test_fetch_history_in_batches_logs_batch_progress(monkeypatch):
    messages = []

    class _FakeFetcher:
        def __init__(self):
            self.closed = False

        def fetch_futures_options_timeseries(self, *, start, end, symbols, show_tqdm=False, max_concurrent_tasks=None, max_keepalive_connections=None):  # noqa: ARG002
            return {
                str(symbol): pd.DataFrame({"close": [1.0]}, index=pd.to_datetime(["2026-03-04"]))
                for symbol in symbols
            }

        def close(self):
            self.closed = True

    monkeypatch.setattr(ingest_module, "_log_status", lambda message, level="INFO": messages.append((level, message)))

    batch_size = ingest_module.MAX_BARCHART_SYMBOLS_PER_CALL

    _fetch_history_in_batches(
        start=dt.date(2026, 3, 4),
        end=dt.date(2026, 3, 4),
        symbols=[f"SYM{idx:03d}" for idx in range(batch_size + 1)],
        show_tqdm=False,
        fetcher_factory=_FakeFetcher,
        stage_name="option",
    )

    logged_text = "\n".join(message for _level, message in messages)
    assert f"Fetching {batch_size + 1} option symbols from Barchart in 2 batch(es)" in logged_text
    assert f"Fetching option batch 1/2 ({batch_size} symbols)" in logged_text
    assert "Completed option batch 2/2: requested=1 returned=1" in logged_text
    assert f"Fetched {batch_size + 1} option symbol payload(s) from Barchart" in logged_text


def test_fetch_history_in_batches_retries_batch_when_fetcher_reports_429(monkeypatch):
    sleeps = []
    created = []
    status_responses = iter(
        [
            {
                "SYM000": {"status_code": 429, "reason": "max_retries_exceeded", "saw_429": True},
                "SYM001": {"status_code": 200, "reason": "ok", "saw_429": False},
            },
            {
                "SYM000": {"status_code": 200, "reason": "ok", "saw_429": False},
                "SYM001": {"status_code": 200, "reason": "ok", "saw_429": False},
            },
        ]
    )

    class _FakeFetcher:
        def __init__(self):
            self.closed = False
            self.statuses = next(status_responses)
            self.calls = []
            self._swappulse_proxy_host = f"proxy-{len(created) + 1}"
            created.append(self)

        def fetch_futures_options_timeseries(
            self,
            *,
            start,
            end,
            symbols,
            show_tqdm=False,
            max_concurrent_tasks=None,
            max_keepalive_connections=None,
        ):  # noqa: ARG002
            self.calls.append((start, end, list(symbols), max_concurrent_tasks, max_keepalive_connections))
            return {
                str(symbol): pd.DataFrame({"close": [1.0]}, index=pd.to_datetime(["2026-03-04"]))
                for symbol in symbols
            }

        def get_history_statuses(self):
            return self.statuses

        def close(self):
            self.closed = True

    monkeypatch.setattr(ingest_module.time, "sleep", lambda seconds: sleeps.append(seconds))

    data = _fetch_history_in_batches(
        start=dt.date(2026, 3, 1),
        end=dt.date(2026, 3, 4),
        symbols=["SYM000", "SYM001"],
        show_tqdm=False,
        fetcher_factory=_FakeFetcher,
        stage_name="option",
    )

    assert len(created) == 2
    assert created[0].calls[0][0] == dt.date(2026, 3, 1)
    assert created[0].calls[0][1] == dt.date(2026, 3, 4)
    assert created[0].calls[0][3] == 2
    assert created[0].calls[0][4] == 2
    assert sleeps == [ingest_module.BARCHART_BATCH_RETRY_BASE_SLEEP_SECONDS]
    assert all(fetcher.closed for fetcher in created)
    assert list(data) == ["SYM000", "SYM001"]


def test_get_barchart_fetcher_rotates_proxy_after_token_failure(monkeypatch):
    state = {
        "lock": threading.RLock(),
        "initialized": True,
        "hosts": ["atlanta.us.socks.nordhold.net", "chicago.us.socks.nordhold.net"],
        "cycler": itertools.cycle(["atlanta.us.socks.nordhold.net", "chicago.us.socks.nordhold.net"]),
        "socksio_enabled": True,
        "ttl": 60,
        "proxies": None,
        "host": None,
        "chosen_at": 0.0,
    }
    created = []
    choices = iter(
        [
            (
                {"http": "socks5h://user:pass@atlanta.us.socks.nordhold.net:1080", "https": "socks5h://user:pass@atlanta.us.socks.nordhold.net:1080"},
                "atlanta.us.socks.nordhold.net",
            ),
            (
                {"http": "socks5h://user:pass@chicago.us.socks.nordhold.net:1080", "https": "socks5h://user:pass@chicago.us.socks.nordhold.net:1080"},
                "chicago.us.socks.nordhold.net",
            ),
        ]
    )

    class _FakeFetcher:
        def __init__(self, **kwargs):
            self.kwargs = kwargs
            self.closed = False
            self.seed_attempts = 0
            created.append(self)

        def _fetch_session_tokens(self, dummy_symbol="BTC"):  # noqa: ARG002
            self.seed_attempts += 1
            if len(created) == 1:
                raise RuntimeError("token failure")

        def close(self):
            self.closed = True

    monkeypatch.setattr(ingest_module, "_init_barchart_proxy_state", lambda: state)
    monkeypatch.setattr(ingest_module, "_get_cached_barchart_proxy", lambda: (None, None))
    monkeypatch.setattr(ingest_module, "_choose_barchart_proxy", lambda: next(choices))
    monkeypatch.setattr(ingest_module, "BarchartFetcher", _FakeFetcher)

    fetcher = _get_barchart_fetcher()

    assert fetcher is created[1]
    assert created[0].closed is True
    assert fetcher.kwargs["proxies"]["http"].endswith("@chicago.us.socks.nordhold.net:1080")
    assert state["host"] == "chicago.us.socks.nordhold.net"


def test_get_barchart_fetcher_uses_new_proxy_and_fresh_tokens_each_call(monkeypatch):
    state = {
        "lock": threading.RLock(),
        "initialized": True,
        "hosts": ["atlanta.us.socks.nordhold.net", "chicago.us.socks.nordhold.net"],
        "cycler": itertools.cycle(["atlanta.us.socks.nordhold.net", "chicago.us.socks.nordhold.net"]),
        "socksio_enabled": True,
        "ttl": 60,
        "proxies": None,
        "host": None,
        "chosen_at": 0.0,
    }
    created = []

    class _FakeFetcher:
        cleared = 0

        def __init__(self, **kwargs):
            self.kwargs = kwargs
            self.closed = False
            self.seed_attempts = 0
            created.append(self)

        @classmethod
        def clear_shared_session_token_cache(cls):
            cls.cleared += 1

        def _fetch_session_tokens(self, dummy_symbol="BTC"):  # noqa: ARG002
            self.seed_attempts += 1

        def close(self):
            self.closed = True

    monkeypatch.setattr(ingest_module, "_init_barchart_proxy_state", lambda: state)
    monkeypatch.setattr(
        ingest_module,
        "_build_socks5h",
        lambda host: {
            "http": f"socks5h://user:pass@{host}:1080",
            "https": f"socks5h://user:pass@{host}:1080",
        },
    )
    monkeypatch.setattr(ingest_module, "_preflight_proxy", lambda proxies: True)
    monkeypatch.setattr(ingest_module, "BarchartFetcher", _FakeFetcher)

    fetcher_a = _get_barchart_fetcher()
    fetcher_b = _get_barchart_fetcher()

    assert fetcher_a is created[0]
    assert fetcher_b is created[1]
    assert fetcher_a.kwargs["proxies"]["http"].endswith("@atlanta.us.socks.nordhold.net:1080")
    assert fetcher_b.kwargs["proxies"]["http"].endswith("@chicago.us.socks.nordhold.net:1080")
    assert fetcher_a.seed_attempts == 1
    assert fetcher_b.seed_attempts == 1
    assert _FakeFetcher.cleared == 2
    assert state["host"] == "chicago.us.socks.nordhold.net"


def test_main_service_respects_max_runs(monkeypatch):
    calls = []
    sleeps = []
    messages = []
    engine = object()

    monkeypatch.setattr(ingest_module, "create_db_engine", lambda: engine)
    monkeypatch.setattr(ingest_module, "ensure_schema", lambda passed_engine: calls.append(("ensure_schema", passed_engine)))
    monkeypatch.setattr(ingest_module, "_current_trade_date", lambda: dt.date(2026, 3, 4))
    monkeypatch.setattr(
        ingest_module,
        "run_ingest_window",
        lambda *args, **kwargs: (
            calls.append(("run_ingest_window", kwargs["start_date"], kwargs["end_date"])),
            {"start_date": "2026-03-04", "row_count": 12, "symbol_count": 8},
        )[1],
    )
    monkeypatch.setattr(ingest_module.time, "sleep", lambda seconds: sleeps.append(seconds))
    monkeypatch.setattr(ingest_module, "_log_status", lambda message, level="INFO": messages.append((level, message)))

    ingest_module.main_service(
        Namespace(
            interval_seconds=30,
            force_refresh=False,
            max_runs=1,
        )
    )

    assert calls == [
        ("ensure_schema", engine),
        ("run_ingest_window", dt.date(2026, 3, 4), dt.date(2026, 3, 4)),
    ]
    assert sleeps == []
    assert any("for 1 run(s)" in message for _level, message in messages)
    assert any("service loop complete after 1 run(s)" in message for _level, message in messages)


def test_persist_rows_uses_postgres_copy_path(monkeypatch):
    captured = {}

    class _Dialect:
        name = "postgresql"

    class _Engine:
        dialect = _Dialect()

    monkeypatch.setattr(
        ingest_module,
        "_persist_rows_postgres_copy",
        lambda engine, **kwargs: captured.update({"engine": engine, **kwargs}),
    )

    persist_rows(
        _Engine(),
        rows=[],
        start_date=dt.date(2026, 3, 12),
        end_date=dt.date(2026, 3, 12),
        underlying_contracts=["SFRZ27"],
    )

    assert captured["start_date"] == dt.date(2026, 3, 12)
    assert captured["end_date"] == dt.date(2026, 3, 12)
    assert captured["requested_underlyings"] == ["SFRZ27"]


def test_persist_rows_postgres_copy_uses_table_column_names_for_staging(monkeypatch):
    executed = []
    copied = []

    class _Cursor:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def execute(self, statement, params=None):
            executed.append((statement, params))

        def copy_expert(self, sql, buffer):
            copied.append((sql, buffer.getvalue()))

    class _RawConnection:
        def cursor(self):
            return _Cursor()

        def commit(self):
            return None

        def rollback(self):
            return None

        def close(self):
            return None

    class _Engine:
        def raw_connection(self):
            return _RawConnection()

    monkeypatch.setattr(ingest_module, "_log_status", lambda *args, **kwargs: None)

    ingest_module._persist_rows_postgres_copy(
        _Engine(),
        rows=[
            {
                "as_of_date": dt.date(2026, 3, 12),
                "explicit_option_symbol": "SQZ27|9500C",
                "right": "C",
                "raw_payload": "{}",
            }
        ],
        start_date=dt.date(2026, 3, 12),
        end_date=dt.date(2026, 3, 12),
        requested_underlyings=["SFRZ27"],
    )

    assert copied
    copy_sql, _payload = copied[0]
    assert '"option_right"' in copy_sql
    assert '"right"' not in copy_sql
    assert any("INSERT INTO" in str(statement) and '"option_right"' in str(statement) for statement, _ in executed)


def test_persist_rows_scopes_delete_to_requested_underlyings_in_fallback():
    executed = []

    class _Conn:
        def execute(self, statement, params=None):
            executed.append((statement, params))

    class _Begin:
        def __init__(self, conn):
            self._conn = conn

        def __enter__(self):
            return self._conn

        def __exit__(self, exc_type, exc, tb):
            return False

    class _Dialect:
        name = "sqlite"

    class _Engine:
        dialect = _Dialect()

        def __init__(self):
            self._conn = _Conn()

        def begin(self):
            return _Begin(self._conn)

    persist_rows(
        _Engine(),
        rows=[],
        start_date=dt.date(2026, 3, 12),
        end_date=dt.date(2026, 3, 12),
        underlying_contracts=["SFRZ27"],
    )

    assert len(executed) == 1
    statement, params = executed[0]
    assert "underlying_contract IN" in str(statement)
    assert params["underlying_contracts"] == ["SFRZ27"]


def test_run_ingest_window_passes_underlying_contracts_to_persist_rows(monkeypatch):
    captured = {}
    engine = object()

    monkeypatch.setattr(ingest_module, "collect_history_rows", lambda **kwargs: [])
    monkeypatch.setattr(
        ingest_module,
        "persist_rows",
        lambda *args, **kwargs: captured.update(kwargs),
    )

    summary = ingest_module.run_ingest_window(
        engine,
        start_date=dt.date(2026, 3, 12),
        end_date=dt.date(2026, 3, 12),
        force_refresh=False,
        show_tqdm=False,
        underlying_contracts=["SFRZ27"],
    )

    assert captured["underlying_contracts"] == ["SFRZ27"]
    assert summary["row_count"] == 0


def test_resolve_once_ingest_window_expands_for_underlying_prefetch():
    as_of = dt.date(2026, 3, 12)

    start_date, end_date = _resolve_once_ingest_window(
        as_of,
        underlying_contracts=["SFRZ27"],
    )

    # ONCE_UNDERLYING_PREFETCH_LOOKBACK_DAYS = 720 (≈2 yr), not 365; 2026-03-12 - 720d = 2024-03-22
    assert start_date == as_of - dt.timedelta(days=ingest_module.ONCE_UNDERLYING_PREFETCH_LOOKBACK_DAYS)
    assert end_date == as_of


def test_main_once_prefetches_one_year_for_underlying_filter(monkeypatch):
    calls = []
    messages = []
    engine = object()

    monkeypatch.setattr(ingest_module, "create_db_engine", lambda: engine)
    monkeypatch.setattr(ingest_module, "ensure_schema", lambda passed_engine: calls.append(("ensure_schema", passed_engine)))
    monkeypatch.setattr(
        ingest_module,
        "run_ingest_window",
        lambda *args, **kwargs: (
            calls.append(("run_ingest_window", kwargs["start_date"], kwargs["end_date"], kwargs["underlying_contracts"])),
            {
                "start_date": kwargs["start_date"].isoformat(),
                "end_date": kwargs["end_date"].isoformat(),
                "row_count": 120,
                "symbol_count": 82,
            },
        )[1],
    )
    monkeypatch.setattr(ingest_module, "_log_status", lambda message, level="INFO": messages.append((level, message)))

    ingest_module.main_once(
        Namespace(
            date="2026-03-12",
            force_refresh=False,
            show_tqdm=False,
            underlying_contract=["SFRZ27"],
        )
    )

    # ONCE_UNDERLYING_PREFETCH_LOOKBACK_DAYS = 720 (≈2 yr); 2026-03-12 - 720d = 2024-03-22
    expected_start = dt.date(2026, 3, 12) - dt.timedelta(days=ingest_module.ONCE_UNDERLYING_PREFETCH_LOOKBACK_DAYS)
    assert calls == [
        ("ensure_schema", engine),
        ("run_ingest_window", expected_start, dt.date(2026, 3, 12), ["SFRZ27"]),
    ]
    assert any(
        f"requested_as_of=2026-03-12 window={expected_start.isoformat()}..2026-03-12" in message
        for _level, message in messages
    )


def test_main_once_keeps_single_day_window_without_underlying_filter(monkeypatch):
    calls = []
    messages = []
    engine = object()

    monkeypatch.setattr(ingest_module, "create_db_engine", lambda: engine)
    monkeypatch.setattr(ingest_module, "ensure_schema", lambda passed_engine: calls.append(("ensure_schema", passed_engine)))
    monkeypatch.setattr(
        ingest_module,
        "run_ingest_window",
        lambda *args, **kwargs: (
            calls.append(("run_ingest_window", kwargs["start_date"], kwargs["end_date"], kwargs["underlying_contracts"])),
            {
                "start_date": kwargs["start_date"].isoformat(),
                "end_date": kwargs["end_date"].isoformat(),
                "row_count": 12,
                "symbol_count": 8,
            },
        )[1],
    )
    monkeypatch.setattr(ingest_module, "_log_status", lambda message, level="INFO": messages.append((level, message)))

    ingest_module.main_once(
        Namespace(
            date="2026-03-12",
            force_refresh=False,
            show_tqdm=False,
            underlying_contract=None,
        )
    )

    assert calls == [
        ("ensure_schema", engine),
        ("run_ingest_window", dt.date(2026, 3, 12), dt.date(2026, 3, 12), None),
    ]
    assert any(
        "daily ingest complete for 2026-03-12: rows=12 symbols=8" in message
        for _level, message in messages
    )


def test_build_parser_accepts_service_max_runs():
    parser = ingest_module.build_parser()

    args = parser.parse_args(["service", "--max-runs", "2"])

    assert args.mode == "service"
    assert args.max_runs == 2


def test_build_parser_accepts_underlying_contract_filter():
    parser = ingest_module.build_parser()

    args = parser.parse_args(["once", "--underlying-contract", "SFRZ27"])

    assert args.mode == "once"
    assert args.underlying_contract == ["SFRZ27"]
