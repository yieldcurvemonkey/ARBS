from __future__ import annotations

import argparse
import csv
import datetime as dt
import importlib.util
import io
import itertools
import json
import math
import os
import random
import threading
import time
import uuid
from collections import OrderedDict
from typing import Any, Callable, Dict, Iterable, List, Optional, Sequence
from urllib.parse import quote
from zoneinfo import ZoneInfo

import pandas as pd
import requests
from sqlalchemy import bindparam, create_engine, text
from sqlalchemy.engine import Engine

from MDP.IRSwaps.SDR_INTRADAY.rl_curve_utils.tos import _imm_cutoff, _next_contracts
from MDP.STIRFutures.BARCHART.BarchartFetcher import BarchartFetcher
from MDP.STIRFutures.STIRFutureOptionMDP import (
    _ROOT_TO_BARCHART as _STIR_ROOT_TO_BARCHART,
    _contract_expiry_date as _stir_contract_expiry_date,
    _contract_to_barchart_contract as _stir_contract_to_barchart_contract,
    _cme_listed_strikes_for_contract_forward as _stir_listed_strikes_for_contract_forward,
    _option_contract_to_underlying_contract as _stir_underlying_contract_for_option,
    _parse_option_request_symbol as _parse_stir_option_request_symbol,
    _strike_from_symbol as _stir_strike_from_symbol,
)
from MDP.USTFutures.USTFutureOptionMDP import (
    _cme_listed_strikes_for_contract_forward as _ust_listed_strikes_for_contract_forward,
    _format_strike4 as _format_ust_strike4,
    _parse_option_request_symbol as _parse_ust_option_request_symbol,
    _strike_from_symbol as _ust_strike_from_symbol,
)
from definitions.USTFutureOptions import (
    MONTHLY_CANON_ROOTS as _UST_MONTHLY_ROOTS,
    NUM_TO_MONTH_CODE as _UST_NUM_TO_MONTH_CODE,
    iter_all_weekly_roots,
    option_expiry_date,
    option_root_base_root,
    parse_option_contract,
    strike_step_for_contract,
    underlying_contract_for_option,
)


TABLE_NAME = "arbs_listed_option_oi_volume_v1"
DEFAULT_INTERVAL_SECONDS = 300
DEFAULT_RANGE_LOOKAHEAD_MONTHS = 12
DEFAULT_WEEKLY_LOOKAHEAD_MONTHS = 4
DEFAULT_STIR_QUARTERLY_CONTRACT_COUNT = 8
DEFAULT_STIR_MONTHLY_CONTRACT_COUNT = 12
MAX_BARCHART_SYMBOLS_PER_CALL = 10
BARCHART_PROXY_TTL_SECONDS = 60
ONCE_UNDERLYING_PREFETCH_LOOKBACK_DAYS = 720
DB_WRITE_BATCH_SIZE = 5_000
BARCHART_BATCH_MAX_RETRIES = 2
BARCHART_INTER_BATCH_PAUSE_SECONDS = 1.0
BARCHART_BATCH_RETRY_BASE_SLEEP_SECONDS = 4.0
BARCHART_OPTION_MAX_CONCURRENT_TASKS = 3
BARCHART_UNDERLYING_MAX_CONCURRENT_TASKS = 2
SOURCE_NAME = "BARCHART_EOD"

ET_ZONE = ZoneInfo("America/New_York")

UST_BASE_ROOT_TO_GLOBEX: Dict[str, str] = {
    "ZT": "TU",
    "ZF": "FV",
    "ZN": "TY",
    "ZB": "US",
}

UST_SUPPORTED_GLOBEX_ROOTS = tuple(UST_BASE_ROOT_TO_GLOBEX.values())
UST_WEEKLY_HALF_WIDTHS: Dict[str, int] = {
    "ZT": 20,
    "ZF": 24,
    "ZN": 50,
    "ZB": 40,
}

STIR_SUPPORTED_ROOTS: tuple[str, ...] = ("SFR", "SER", "FF", "0Q", "2Q", "3Q", "4Q", "5Q")
STIR_QUARTERLY_ROOTS = {"SFR", "0Q", "2Q", "3Q", "4Q", "5Q"}
STIR_DIRECT_UNDERLYING_PREFIXES: tuple[str, ...] = ("SFR", "SER", "FF", "SR3", "SQ", "SR1", "SL", "ZQ", "QZ")
_BARCHART_PROXY_STATE: Dict[str, Any] = {"lock": threading.RLock(), "initialized": False}

SCHEMA_SQL = f"""
CREATE TABLE IF NOT EXISTS {TABLE_NAME} (
    as_of_date                DATE NOT NULL,
    product_family            TEXT NOT NULL,
    product_root              TEXT NOT NULL,
    root_bbg                  TEXT NOT NULL,
    root_globex               TEXT NOT NULL,
    root_barchart             TEXT NOT NULL,
    option_contract           TEXT NOT NULL,
    option_contract_barchart  TEXT NOT NULL,
    explicit_option_symbol    TEXT NOT NULL,
    underlying_contract       TEXT NOT NULL,
    underlying_barchart       TEXT NOT NULL,
    expiry_date               DATE NOT NULL,
    dte_days                  INTEGER NOT NULL,
    option_root               TEXT NOT NULL,
    option_right              TEXT NOT NULL,
    strike                    DOUBLE PRECISION NOT NULL,
    forward_price             DOUBLE PRECISION,
    atm_strike                DOUBLE PRECISION,
    atm_offset_bps            DOUBLE PRECISION,
    vendor_delta              DOUBLE PRECISION,
    delta_abs                 DOUBLE PRECISION,
    open_interest             BIGINT,
    volume                    BIGINT,
    open_price                DOUBLE PRECISION,
    high_price                DOUBLE PRECISION,
    low_price                 DOUBLE PRECISION,
    close_price               DOUBLE PRECISION,
    source                    TEXT NOT NULL,
    raw_payload               JSONB NOT NULL DEFAULT '{{}}'::jsonb,
    created_at                TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at                TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (as_of_date, explicit_option_symbol)
);

CREATE INDEX IF NOT EXISTS idx_listed_option_oi_volume_snapshot
    ON {TABLE_NAME}(as_of_date DESC, product_family, product_root);
CREATE INDEX IF NOT EXISTS idx_listed_option_oi_volume_symbol
    ON {TABLE_NAME}(explicit_option_symbol, as_of_date DESC);
CREATE INDEX IF NOT EXISTS idx_listed_option_oi_volume_alias
    ON {TABLE_NAME}(as_of_date DESC, product_root, expiry_date, option_right, atm_offset_bps, delta_abs);
"""

UPSERT_SQL = f"""
INSERT INTO {TABLE_NAME} (
    as_of_date,
    product_family,
    product_root,
    root_bbg,
    root_globex,
    root_barchart,
    option_contract,
    option_contract_barchart,
    explicit_option_symbol,
    underlying_contract,
    underlying_barchart,
    expiry_date,
    dte_days,
    option_root,
    option_right,
    strike,
    forward_price,
    atm_strike,
    atm_offset_bps,
    vendor_delta,
    delta_abs,
    open_interest,
    volume,
    open_price,
    high_price,
    low_price,
    close_price,
    source,
    raw_payload
) VALUES (
    :as_of_date,
    :product_family,
    :product_root,
    :root_bbg,
    :root_globex,
    :root_barchart,
    :option_contract,
    :option_contract_barchart,
    :explicit_option_symbol,
    :underlying_contract,
    :underlying_barchart,
    :expiry_date,
    :dte_days,
    :option_root,
    :right,
    :strike,
    :forward_price,
    :atm_strike,
    :atm_offset_bps,
    :vendor_delta,
    :delta_abs,
    :open_interest,
    :volume,
    :open_price,
    :high_price,
    :low_price,
    :close_price,
    :source,
    CAST(:raw_payload AS JSONB)
)
ON CONFLICT (as_of_date, explicit_option_symbol) DO UPDATE SET
    product_family = EXCLUDED.product_family,
    product_root = EXCLUDED.product_root,
    root_bbg = EXCLUDED.root_bbg,
    root_globex = EXCLUDED.root_globex,
    root_barchart = EXCLUDED.root_barchart,
    option_contract = EXCLUDED.option_contract,
    option_contract_barchart = EXCLUDED.option_contract_barchart,
    underlying_contract = EXCLUDED.underlying_contract,
    underlying_barchart = EXCLUDED.underlying_barchart,
    expiry_date = EXCLUDED.expiry_date,
    dte_days = EXCLUDED.dte_days,
    option_root = EXCLUDED.option_root,
    option_right = EXCLUDED.option_right,
    strike = EXCLUDED.strike,
    forward_price = EXCLUDED.forward_price,
    atm_strike = EXCLUDED.atm_strike,
    atm_offset_bps = EXCLUDED.atm_offset_bps,
    vendor_delta = EXCLUDED.vendor_delta,
    delta_abs = EXCLUDED.delta_abs,
    open_interest = EXCLUDED.open_interest,
    volume = EXCLUDED.volume,
    open_price = EXCLUDED.open_price,
    high_price = EXCLUDED.high_price,
    low_price = EXCLUDED.low_price,
    close_price = EXCLUDED.close_price,
    source = EXCLUDED.source,
    raw_payload = EXCLUDED.raw_payload,
    updated_at = NOW()
"""

DB_WRITE_COLUMN_SPECS: tuple[tuple[str, str], ...] = (
    ("as_of_date", "as_of_date"),
    ("product_family", "product_family"),
    ("product_root", "product_root"),
    ("root_bbg", "root_bbg"),
    ("root_globex", "root_globex"),
    ("root_barchart", "root_barchart"),
    ("option_contract", "option_contract"),
    ("option_contract_barchart", "option_contract_barchart"),
    ("explicit_option_symbol", "explicit_option_symbol"),
    ("underlying_contract", "underlying_contract"),
    ("underlying_barchart", "underlying_barchart"),
    ("expiry_date", "expiry_date"),
    ("dte_days", "dte_days"),
    ("option_root", "option_root"),
    ("option_right", "right"),
    ("strike", "strike"),
    ("forward_price", "forward_price"),
    ("atm_strike", "atm_strike"),
    ("atm_offset_bps", "atm_offset_bps"),
    ("vendor_delta", "vendor_delta"),
    ("delta_abs", "delta_abs"),
    ("open_interest", "open_interest"),
    ("volume", "volume"),
    ("open_price", "open_price"),
    ("high_price", "high_price"),
    ("low_price", "low_price"),
    ("close_price", "close_price"),
    ("source", "source"),
    ("raw_payload", "raw_payload"),
)


def _log_status(message: str, *, level: str = "INFO") -> None:
    timestamp = dt.datetime.now(tz=ET_ZONE).strftime("%Y-%m-%d %H:%M:%S %Z")
    print(f"[{timestamp}] [{level}] {message}", flush=True)


def _current_trade_date(now: Optional[dt.datetime] = None) -> dt.date:
    ts = now.astimezone(ET_ZONE) if now else dt.datetime.now(tz=ET_ZONE)
    trade_date = ts.date()
    while trade_date.weekday() >= 5:
        trade_date -= dt.timedelta(days=1)
    return trade_date


def _business_dates(start: dt.date, end: dt.date) -> list[dt.date]:
    if start > end:
        return []
    return [timestamp.date() for timestamp in pd.bdate_range(start, end)]


def _resolve_once_ingest_window(
    as_of_date: dt.date,
    *,
    underlying_contracts: Optional[Sequence[str]] = None,
) -> tuple[dt.date, dt.date]:
    if underlying_contracts:
        return as_of_date - dt.timedelta(days=ONCE_UNDERLYING_PREFETCH_LOOKBACK_DAYS), as_of_date
    return as_of_date, as_of_date


def _resolved_requested_underlying_contracts(
    underlying_contracts: Optional[Sequence[str]],
) -> List[str]:
    requested_by_family = _normalize_requested_underlying_contracts(underlying_contracts)
    return [
        contract
        for family in ("UST", "STIR")
        for contract in requested_by_family.get(family, [])
    ]


def get_db_connection_string() -> str:
    host = os.getenv("SWAPPULSE_DB_HOST", "aws-0-us-east-1.pooler.supabase.com")
    port = os.getenv("SWAPPULSE_DB_PORT", "6543")
    dbname = os.getenv("SWAPPULSE_DB_NAME", "postgres")
    user = os.getenv("SWAPPULSE_DB_USER", "postgres.rdobtpugtnmefxplgwyp")
    password = os.getenv("SWAPPULSE_DB_PASSWORD", "0rbZUh8y0Fsvdlry")
    return f"postgresql://{user}:{password}@{host}:{port}/{dbname}"


def create_db_engine() -> Engine:
    return create_engine(
        get_db_connection_string(),
        pool_size=5,
        max_overflow=10,
        pool_timeout=30,
        pool_recycle=1800,
    )


def ensure_schema(engine: Engine) -> None:
    with engine.begin() as conn:
        for statement in SCHEMA_SQL.split(";"):
            stmt = statement.strip()
            if stmt:
                conn.execute(text(stmt))


def _safe_float(value: Any) -> Optional[float]:
    if value is None:
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if math.isfinite(parsed) else None


def _safe_int(value: Any) -> Optional[int]:
    parsed = _safe_float(value)
    if parsed is None:
        return None
    return int(round(parsed))


def _json_dumps(value: Any) -> str:
    return json.dumps(value, separators=(",", ":"), sort_keys=True, default=str)


def _iter_month_codes_from(as_of: dt.date, months_ahead: int) -> List[str]:
    out: List[str] = []
    for offset in range(max(1, int(months_ahead))):
        month_idx = (as_of.month - 1) + offset
        year = as_of.year + (month_idx // 12)
        month = (month_idx % 12) + 1
        out.append(f"{_UST_NUM_TO_MONTH_CODE[month]}{year % 100:02d}")
    return out


def _dedupe_preserve_order(items: Iterable[str]) -> List[str]:
    out: List[str] = []
    seen: set[str] = set()
    for item in items:
        token = str(item or "").strip().upper()
        if not token or token in seen:
            continue
        seen.add(token)
        out.append(token)
    return out


def _normalize_contract_token(contract: str) -> str:
    return str(contract or "").strip().upper().replace("/", "")


def _looks_like_month_code(token: str) -> bool:
    cleaned = _normalize_contract_token(token)
    return len(cleaned) == 3 and cleaned[0] in _UST_NUM_TO_MONTH_CODE.values() and cleaned[1:].isdigit()


def _is_direct_stir_underlying_contract(contract: str) -> bool:
    token = _normalize_contract_token(contract)
    return any(
        token.startswith(prefix) and _looks_like_month_code(token[len(prefix) :])
        for prefix in STIR_DIRECT_UNDERLYING_PREFIXES
    )


def _normalize_requested_underlying_contracts(
    underlying_contracts: Optional[Sequence[str]],
) -> Dict[str, List[str]]:
    by_family: Dict[str, List[str]] = {"UST": [], "STIR": []}
    for raw_value in underlying_contracts or []:
        for token_raw in str(raw_value or "").split(","):
            token = _normalize_contract_token(token_raw)
            if not token:
                continue
            if _is_direct_stir_underlying_contract(token):
                canonical = _normalize_contract_token(_stir_underlying_contract_for_option(token))
                by_family["STIR"].append(canonical)
                continue
            try:
                canonical = _normalize_contract_token(underlying_contract_for_option(token))
            except Exception as exc:
                raise ValueError(f"Unsupported underlying contract filter: {token_raw!r}") from exc
            by_family["UST"].append(canonical)
    return {
        family: _dedupe_preserve_order(contracts)
        for family, contracts in by_family.items()
        if contracts
    }


def _filter_contracts_for_requested_underlyings(
    *,
    contracts: Sequence[str],
    family: str,
    requested_underlyings: Optional[Sequence[str]],
    as_of: dt.date,
) -> List[str]:
    if requested_underlyings is None:
        return _dedupe_preserve_order(contracts)
    requested = _dedupe_preserve_order(requested_underlyings or [])
    if not requested:
        return []

    if family == "STIR":
        requested_set = set(requested)
        filtered = [contract for contract in contracts if _normalize_contract_token(contract) in requested_set]
        for requested_contract in requested:
            try:
                if _stir_contract_expiry_date(requested_contract[-3:]) >= as_of:
                    filtered.append(requested_contract)
            except Exception:
                continue
        return _dedupe_preserve_order(filtered)

    requested_set = set(requested)
    filtered = [
        contract
        for contract in contracts
        if _normalize_contract_token(underlying_contract_for_option(contract)) in requested_set
    ]
    for requested_contract in requested:
        try:
            if option_expiry_date(requested_contract) >= as_of:
                filtered.append(requested_contract)
        except Exception:
            continue
    return _dedupe_preserve_order(filtered)


def _socksio_available() -> bool:
    return importlib.util.find_spec("socksio") is not None


def _build_socks5h(host: str) -> dict:
    user = os.getenv("NORDVPN_USER", "3G5mmfKXWfCGFGT4yDL34Tzn")
    pwd = os.getenv("NORDVPN_PASS", "VN33uViQZp6pXVzdgsGskhNg")
    if not user or not pwd:
        raise ValueError("Missing NORDVPN_USER/NORDVPN_PASS in environment.")
    url = f"socks5h://{quote(user, safe='')}:{quote(pwd, safe='')}@{host}:1080"
    return {"http": url, "https": url}


def _preflight_proxy(proxies: dict | None, timeout: int = 6) -> bool:
    try:
        response = requests.get(
            "https://api.ipify.org?format=json",
            proxies=proxies,
            timeout=timeout,
            headers={"Connection": "close"},
        )
        response.raise_for_status()
        return True
    except Exception:
        return False


def _init_barchart_proxy_state() -> Dict[str, Any]:
    state = _BARCHART_PROXY_STATE
    with state["lock"]:
        if state.get("initialized"):
            return state
        default_hosts: List[Optional[str]] = [
            "atlanta.us.socks.nordhold.net",
            "chicago.us.socks.nordhold.net",
            "dallas.us.socks.nordhold.net",
            "los-angeles.us.socks.nordhold.net",
            "new-york.us.socks.nordhold.net",
            "phoenix.us.socks.nordhold.net",
            "san-francisco.us.socks.nordhold.net",
            "us.socks.nordhold.net",
            None,
        ]
        hosts = list(default_hosts)
        socksio_enabled = _socksio_available()
        if not socksio_enabled:
            hosts = [None]
        random.shuffle(hosts)
        state.update(
            {
                "initialized": True,
                "hosts": hosts,
                "cycler": itertools.cycle(hosts),
                "socksio_enabled": socksio_enabled,
                "ttl": BARCHART_PROXY_TTL_SECONDS,
                "proxies": None,
                "host": None,
                "chosen_at": 0.0,
            }
        )
    return state


def _get_cached_barchart_proxy() -> tuple[dict | None, str | None]:
    state = _init_barchart_proxy_state()
    if time.time() - float(state["chosen_at"]) < float(state["ttl"]):
        return state["proxies"], state["host"]
    return None, None


def _choose_barchart_proxy() -> tuple[dict | None, str | None]:
    state = _init_barchart_proxy_state()
    cycler = state["cycler"]
    hosts: List[Optional[str]] = list(state["hosts"])
    if not hosts:
        return None, None

    last_host = state.get("host")
    saw_direct = False
    fallback_proxy: tuple[dict | None, str | None] | None = None
    for _ in range(len(hosts)):
        host = next(cycler)
        is_reuse = len(hosts) > 1 and host == last_host
        if host is None:
            saw_direct = True
            continue
        if not state["socksio_enabled"]:
            continue
        try:
            proxies = _build_socks5h(host)
        except Exception:
            continue
        if _preflight_proxy(proxies):
            if is_reuse:
                fallback_proxy = (proxies, host)
                continue
            return proxies, host
    if saw_direct and len(hosts) > 1 and last_host is not None:
        return None, None
    if fallback_proxy is not None:
        return fallback_proxy
    if saw_direct:
        return None, None
    return None, None


def _safe_close_barchart_fetcher(fetcher: Optional[BarchartFetcher]) -> None:
    if fetcher is None:
        return
    try:
        fetcher.close()
    except Exception:
        pass


def _clear_barchart_session_token_cache() -> None:
    clear_cache = getattr(BarchartFetcher, "clear_shared_session_token_cache", None)
    if not callable(clear_cache):
        return
    try:
        clear_cache()
    except Exception:
        pass


def _get_barchart_fetcher() -> BarchartFetcher:
    state = _init_barchart_proxy_state()
    with state["lock"]:
        proxies, host = _choose_barchart_proxy()
        state["proxies"], state["host"], state["chosen_at"] = proxies, host, time.time()

        def _build_fetcher(fetcher_proxies: Optional[dict], fetcher_host: Optional[str]) -> BarchartFetcher:
            scope_host = fetcher_host if fetcher_host is not None else "direct"
            fetcher = BarchartFetcher(
                proxies=fetcher_proxies,
                debug_verbose=False,
                info_verbose=True,
                error_verbose=True,
                session_token_ttl_seconds=max(1, int(state["ttl"])),
                session_token_scope=f"{TABLE_NAME}:{scope_host}",
            )
            setattr(fetcher, "_swappulse_proxy_host", scope_host)
            return fetcher

        _clear_barchart_session_token_cache()
        bcf = _build_fetcher(proxies, host)
        try:
            bcf._fetch_session_tokens(dummy_symbol="BTC")
        except Exception:
            _safe_close_barchart_fetcher(bcf)
            proxies, host = _choose_barchart_proxy()
            state["proxies"], state["host"], state["chosen_at"] = proxies, host, time.time()
            _clear_barchart_session_token_cache()
            bcf = _build_fetcher(proxies, host)
            bcf._fetch_session_tokens(dummy_symbol="BTC")
        return bcf


def _chunk_symbols(symbols: Sequence[str], *, chunk_size: int = MAX_BARCHART_SYMBOLS_PER_CALL) -> List[List[str]]:
    size = max(1, int(chunk_size))
    cleaned = [str(symbol) for symbol in symbols if str(symbol or "").strip()]
    return [cleaned[idx : idx + size] for idx in range(0, len(cleaned), size)]


def _batch_max_concurrent_tasks(stage_name: str, batch_size: int) -> int:
    default_limit = BARCHART_OPTION_MAX_CONCURRENT_TASKS
    if stage_name == "underlying":
        default_limit = BARCHART_UNDERLYING_MAX_CONCURRENT_TASKS
    return max(1, min(batch_size, default_limit))


def _batch_retry_sleep_seconds(attempt: int) -> float:
    return max(0.0, float(BARCHART_BATCH_RETRY_BASE_SLEEP_SECONDS) * float(max(1, attempt)))


def _fetcher_proxy_host(fetcher: BarchartFetcher) -> str:
    return str(getattr(fetcher, "_swappulse_proxy_host", "direct") or "direct")


def _fetcher_history_statuses(fetcher: BarchartFetcher) -> Dict[str, Dict[str, Any]]:
    getter = getattr(fetcher, "get_history_statuses", None)
    if callable(getter):
        try:
            statuses = getter()
            if isinstance(statuses, dict):
                return statuses
        except Exception:
            return {}
    return {}


def _count_batch_429s(batch: Sequence[str], fetcher: BarchartFetcher) -> int:
    statuses = _fetcher_history_statuses(fetcher)
    count = 0
    for symbol in batch:
        status = statuses.get(str(symbol), {})
        if bool(status.get("saw_429")) and status.get("status_code") != 200:
            count += 1
    return count


def _fetch_history_in_batches(
    *,
    start: dt.date,
    end: dt.date,
    symbols: Sequence[str],
    show_tqdm: bool = False,
    chunk_size: int = MAX_BARCHART_SYMBOLS_PER_CALL,
    fetcher_factory: Callable[[], BarchartFetcher] = _get_barchart_fetcher,
    stage_name: str = "history",
) -> Dict[str, pd.DataFrame]:
    out: "OrderedDict[str, pd.DataFrame]" = OrderedDict()
    batches = _chunk_symbols(symbols, chunk_size=chunk_size)
    if not batches:
        _log_status(
            f"No {stage_name} symbols to fetch from Barchart for {start.isoformat()}..{end.isoformat()}"
        )
        return {}
    _log_status(
        f"Fetching {sum(len(batch) for batch in batches)} {stage_name} symbols from Barchart in "
        f"{len(batches)} batch(es) for {start.isoformat()}..{end.isoformat()}"
    )
    for batch_idx, batch in enumerate(batches, start=1):
        max_attempts = max(1, int(BARCHART_BATCH_MAX_RETRIES) + 1)
        concurrency = _batch_max_concurrent_tasks(stage_name, len(batch))
        keepalive = max(1, concurrency)
        for attempt in range(1, max_attempts + 1):
            bcf = fetcher_factory()
            proxy_host = _fetcher_proxy_host(bcf)
            _log_status(
                f"Fetching {stage_name} batch {batch_idx}/{len(batches)} ({len(batch)} symbols) "
                f"via proxy {proxy_host} attempt {attempt}/{max_attempts}"
            )
            started_at = time.monotonic()
            try:
                batch_data = bcf.fetch_futures_options_timeseries(
                    start=start,
                    end=end,
                    symbols=batch,
                    show_tqdm=show_tqdm,
                    max_concurrent_tasks=concurrency,
                    max_keepalive_connections=keepalive,
                )
                throttle_hits = _count_batch_429s(batch, bcf)
                elapsed_seconds = time.monotonic() - started_at
                if throttle_hits > 0 and attempt < max_attempts:
                    sleep_seconds = _batch_retry_sleep_seconds(attempt)
                    _log_status(
                        f"{stage_name.capitalize()} batch {batch_idx}/{len(batches)} saw 429s for "
                        f"{throttle_hits}/{len(batch)} symbol(s) via proxy {proxy_host}; "
                        f"retrying with a new proxy in {sleep_seconds:.1f}s",
                        level="WARNING",
                    )
                    time.sleep(sleep_seconds)
                    continue

                out.update(batch_data)
                completion_level = "WARNING" if throttle_hits > 0 else "INFO"
                _log_status(
                    f"Completed {stage_name} batch {batch_idx}/{len(batches)}: "
                    f"requested={len(batch)} returned={len(batch_data)} elapsed={elapsed_seconds:.1f}s "
                    f"proxy={proxy_host} concurrency={concurrency} 429_symbols={throttle_hits}",
                    level=completion_level,
                )
                break
            except Exception as exc:
                elapsed_seconds = time.monotonic() - started_at
                if attempt < max_attempts:
                    sleep_seconds = _batch_retry_sleep_seconds(attempt)
                    _log_status(
                        f"{stage_name.capitalize()} batch {batch_idx}/{len(batches)} failed after "
                        f"{elapsed_seconds:.1f}s via proxy {proxy_host}: {exc}. "
                        f"Retrying with a new proxy in {sleep_seconds:.1f}s",
                        level="WARNING",
                    )
                    time.sleep(sleep_seconds)
                    continue
                _log_status(
                    f"{stage_name.capitalize()} batch {batch_idx}/{len(batches)} failed after "
                    f"{elapsed_seconds:.1f}s via proxy {proxy_host}: {exc}",
                    level="ERROR",
                )
                raise
            finally:
                _safe_close_barchart_fetcher(bcf)
        if batch_idx < len(batches) and BARCHART_INTER_BATCH_PAUSE_SECONDS > 0:
            time.sleep(BARCHART_INTER_BATCH_PAUSE_SECONDS)
    _log_status(
        f"Fetched {len(out)} {stage_name} symbol payload(s) from Barchart for {start.isoformat()}..{end.isoformat()}"
    )
    return dict(out)


def _resolve_index_row(df: Optional[pd.DataFrame], as_of_date: dt.date) -> Optional[pd.Series]:
    if df is None or df.empty:
        return None
    if isinstance(df.index, pd.DatetimeIndex):
        mask = df.index.date <= as_of_date
        if not mask.any():
            return None
        return df.loc[mask].iloc[-1]
    return None


def _extract_forward_price(df: Optional[pd.DataFrame], as_of_date: dt.date) -> Optional[float]:
    row = _resolve_index_row(df, as_of_date)
    if row is None:
        return None
    for key in ("close", "open", "high", "low"):
        value = _safe_float(row.get(key))
        if value is not None and value > 0.0:
            return value
    return None


def _ust_weekly_listed_strikes_for_contract_forward(
    *,
    contract: str,
    forward: float,
    as_of: dt.date,
) -> Optional[List[float]]:
    try:
        root, _ = parse_option_contract(contract, as_of=as_of)
    except Exception:
        return None
    base_root = option_root_base_root(root)
    half_width = UST_WEEKLY_HALF_WIDTHS.get(base_root)
    if half_width is None:
        return None
    step = float(strike_step_for_contract(contract))
    atm = round(float(forward) / step) * step
    return [atm + (idx * step) for idx in range(-half_width, half_width + 1)]


def _ust_listed_strikes_for_contract(
    *,
    contract: str,
    forward: float,
    as_of: dt.date,
) -> Optional[List[float]]:
    strikes = _ust_listed_strikes_for_contract_forward(
        contract=contract,
        forward=forward,
        as_of=as_of,
    )
    if strikes:
        return strikes
    return _ust_weekly_listed_strikes_for_contract_forward(contract=contract, forward=forward, as_of=as_of)


def _stir_contracts_for_day(
    as_of: dt.date,
    *,
    quarterly_count: int = DEFAULT_STIR_QUARTERLY_CONTRACT_COUNT,
    monthly_count: int = DEFAULT_STIR_MONTHLY_CONTRACT_COUNT,
) -> List[str]:
    out: List[str] = []
    for root in STIR_SUPPORTED_ROOTS:
        if root in STIR_QUARTERLY_ROOTS:
            out.extend(
                _next_contracts(
                    start_date=as_of,
                    prefix=root,
                    count=max(1, quarterly_count),
                    valid_months=[3, 6, 9, 12],
                    cutoff_fn=_imm_cutoff,
                )
            )
        else:
            out.extend(
                _next_contracts(
                    start_date=as_of,
                    prefix=root,
                    count=max(1, monthly_count),
                    valid_months=list(range(1, 13)),
                    cutoff_fn=None,
                )
            )
    return _dedupe_preserve_order(out)


def _ust_contracts_for_day(
    as_of: dt.date,
    *,
    monthly_lookahead_months: int = DEFAULT_RANGE_LOOKAHEAD_MONTHS,
    weekly_lookahead_months: int = DEFAULT_WEEKLY_LOOKAHEAD_MONTHS,
) -> List[str]:
    contracts: List[str] = []
    for root in _UST_MONTHLY_ROOTS:
        for code in _iter_month_codes_from(as_of, monthly_lookahead_months):
            contract = f"{root}{code}"
            try:
                if option_expiry_date(contract) >= as_of:
                    contracts.append(contract)
            except Exception:
                continue
    weekly_codes = _iter_month_codes_from(as_of, weekly_lookahead_months)
    for root in iter_all_weekly_roots():
        for code in weekly_codes:
            contract = f"{root}{code}"
            try:
                if option_expiry_date(contract) >= as_of:
                    contracts.append(contract)
            except Exception:
                continue
    return _dedupe_preserve_order(contracts)


def build_contract_universe(
    start_date: dt.date,
    end_date: dt.date,
    *,
    underlying_contracts: Optional[Sequence[str]] = None,
) -> Dict[dt.date, Dict[str, List[str]]]:
    requested_by_family = _normalize_requested_underlying_contracts(underlying_contracts)
    restrict_to_requested = bool(requested_by_family)
    by_day: Dict[dt.date, Dict[str, List[str]]] = {}
    for day in _business_dates(start_date, end_date):
        ust_contracts = _filter_contracts_for_requested_underlyings(
            contracts=_ust_contracts_for_day(day),
            family="UST",
            requested_underlyings=requested_by_family.get("UST") if not restrict_to_requested or "UST" in requested_by_family else [],
            as_of=day,
        )
        stir_contracts = _filter_contracts_for_requested_underlyings(
            contracts=_stir_contracts_for_day(day),
            family="STIR",
            requested_underlyings=requested_by_family.get("STIR") if not restrict_to_requested or "STIR" in requested_by_family else [],
            as_of=day,
        )
        by_day[day] = {
            "UST": ust_contracts,
            "STIR": stir_contracts,
        }
    return by_day


def _contract_underlying_barchart(contract: str, family: str) -> str:
    if family == "UST":
        return underlying_contract_for_option(contract)
    return _stir_contract_to_barchart_contract(_stir_underlying_contract_for_option(contract))


def _contract_barchart(contract: str, family: str) -> str:
    if family == "UST":
        return contract
    return _stir_contract_to_barchart_contract(contract)


def build_underlying_symbol_universe(contract_universe: Dict[dt.date, Dict[str, List[str]]]) -> List[str]:
    symbols: List[str] = []
    for families in contract_universe.values():
        for family, contracts in families.items():
            for contract in contracts:
                symbols.append(_contract_underlying_barchart(contract, family))
    return _dedupe_preserve_order(symbols)


def build_option_symbol_universe(
    *,
    contract_universe: Dict[dt.date, Dict[str, List[str]]],
    underlying_data: Dict[str, pd.DataFrame],
) -> List[str]:
    symbols: List[str] = []
    for as_of_date, families in contract_universe.items():
        for family, contracts in families.items():
            for contract in contracts:
                underlying_barchart = _contract_underlying_barchart(contract, family)
                forward = _extract_forward_price(underlying_data.get(underlying_barchart), as_of_date)
                if forward is None or forward <= 0.0:
                    continue
                if family == "UST":
                    strikes = _ust_listed_strikes_for_contract(
                        contract=contract,
                        forward=float(forward),
                        as_of=as_of_date,
                    )
                else:
                    strikes = _stir_listed_strikes_for_contract_forward(
                        contract=contract,
                        forward=float(forward),
                        as_of=as_of_date,
                    )
                if not strikes:
                    continue
                option_contract_barchart = _contract_barchart(contract, family)
                for strike in strikes:
                    try:
                        if family == "UST":
                            token = _format_ust_barchart_strike(contract, strike)
                        else:
                            token = _format_stir_barchart_strike(contract, strike)
                    except Exception:
                        # Some generated UST strike ladders contain values that the vendor
                        # symbology cannot encode for a given monthly contract. Skip those
                        # impossible symbols instead of failing the full backfill window.
                        continue
                    symbols.append(f"{option_contract_barchart}|{token}C")
                    symbols.append(f"{option_contract_barchart}|{token}P")
    return _dedupe_preserve_order(symbols)


def _format_stir_barchart_strike(contract: str, strike: float) -> str:
    canonical = f"{contract}|{int(round(float(strike) * 100.0)):04d}C"
    parsed = _parse_stir_option_request_symbol(canonical)
    return str(parsed["strike4"])


def _format_ust_barchart_strike(contract: str, strike: float) -> str:
    return _format_ust_strike4(float(strike), contract=contract)


def _infer_ust_row_metadata(option_symbol: str) -> Dict[str, Any]:
    parsed = _parse_ust_option_request_symbol(option_symbol)
    canonical = str(parsed["canonical"])
    contract = str(parsed["contract"])
    right = str(parsed["right"])
    strike = float(_ust_strike_from_symbol(canonical))
    option_root, _ = parse_option_contract(contract)
    base_root = option_root_base_root(option_root)
    product_root = UST_BASE_ROOT_TO_GLOBEX.get(base_root, base_root)
    expiry = option_expiry_date(contract)
    underlying_contract = underlying_contract_for_option(contract)
    return {
        "product_family": "UST",
        "product_root": product_root,
        "root_bbg": product_root,
        "root_globex": product_root,
        "root_barchart": base_root,
        "option_contract": contract,
        "option_contract_barchart": contract,
        "underlying_contract": underlying_contract,
        "underlying_barchart": underlying_contract,
        "option_root": option_root,
        "right": right,
        "strike": strike,
        "expiry_date": expiry,
    }


def _infer_stir_row_metadata(option_symbol: str) -> Dict[str, Any]:
    parsed = _parse_stir_option_request_symbol(option_symbol)
    canonical = str(parsed["canonical"])
    contract = str(parsed["contract"])
    right = str(parsed["right"])
    strike = float(_stir_strike_from_symbol(canonical))
    option_root = contract[:-3]
    expiry = _stir_contract_expiry_date(contract[-3:])
    underlying_contract = _stir_underlying_contract_for_option(contract)
    return {
        "product_family": "STIR",
        "product_root": option_root,
        "root_bbg": option_root,
        "root_globex": option_root,
        "root_barchart": _STIR_ROOT_TO_BARCHART.get(option_root, option_root),
        "option_contract": contract,
        "option_contract_barchart": _stir_contract_to_barchart_contract(contract),
        "underlying_contract": underlying_contract,
        "underlying_barchart": _stir_contract_to_barchart_contract(underlying_contract),
        "option_root": option_root,
        "right": right,
        "strike": strike,
        "expiry_date": expiry,
    }


def infer_row_metadata(option_symbol: str) -> Dict[str, Any]:
    last_error: Optional[Exception] = None
    for builder in (_infer_ust_row_metadata, _infer_stir_row_metadata):
        try:
            return builder(option_symbol)
        except Exception as exc:
            last_error = exc
    raise ValueError(f"Could not infer listed option metadata for {option_symbol!r}") from last_error


def _atm_strike_from_forward(
    *,
    family: str,
    contract: str,
    forward: float,
    as_of_date: dt.date,
) -> Optional[float]:
    if family == "UST":
        strikes = _ust_listed_strikes_for_contract(contract=contract, forward=forward, as_of=as_of_date)
    else:
        strikes = _stir_listed_strikes_for_contract_forward(contract=contract, forward=forward, as_of=as_of_date)
    if not strikes:
        return None
    return min((float(strike) for strike in strikes), key=lambda strike: abs(strike - float(forward)))


def normalize_history_row(
    *,
    explicit_option_symbol: str,
    as_of_date: dt.date,
    row: Dict[str, Any],
    underlying_data: Dict[str, pd.DataFrame],
) -> Optional[Dict[str, Any]]:
    metadata = infer_row_metadata(explicit_option_symbol)
    forward = _extract_forward_price(underlying_data.get(str(metadata["underlying_barchart"])), as_of_date)
    atm_strike = (
        _atm_strike_from_forward(
            family=str(metadata["product_family"]),
            contract=str(metadata["option_contract"]),
            forward=float(forward),
            as_of_date=as_of_date,
        )
        if forward is not None and forward > 0.0
        else None
    )
    vendor_delta = _safe_float(row.get("delta"))
    delta_abs = abs(vendor_delta) if vendor_delta is not None else None
    open_interest = _safe_int(row.get("openinterest"))
    volume = _safe_int(row.get("volume"))
    if open_interest is None and volume is None:
        return None

    expiry_date = metadata["expiry_date"]
    dte_days = max((expiry_date - as_of_date).days, 0)
    atm_offset_bps = (
        round((float(atm_strike) - float(metadata["strike"])) * 100.0, 8)
        if atm_strike is not None
        else None
    )

    payload = {
        "symbol": explicit_option_symbol,
        "open": _safe_float(row.get("open")),
        "high": _safe_float(row.get("high")),
        "low": _safe_float(row.get("low")),
        "close": _safe_float(row.get("close")),
        "volume": volume,
        "openinterest": open_interest,
        "delta": vendor_delta,
        "gamma": _safe_float(row.get("gamma")),
        "theta": _safe_float(row.get("theta")),
        "vega": _safe_float(row.get("vega")),
        "impliedVolatility": _safe_float(row.get("impliedVolatility")),
    }

    return {
        "as_of_date": as_of_date,
        "product_family": metadata["product_family"],
        "product_root": metadata["product_root"],
        "root_bbg": metadata["root_bbg"],
        "root_globex": metadata["root_globex"],
        "root_barchart": metadata["root_barchart"],
        "option_contract": metadata["option_contract"],
        "option_contract_barchart": metadata["option_contract_barchart"],
        "explicit_option_symbol": explicit_option_symbol,
        "underlying_contract": metadata["underlying_contract"],
        "underlying_barchart": metadata["underlying_barchart"],
        "expiry_date": expiry_date,
        "dte_days": dte_days,
        "option_root": metadata["option_root"],
        "right": metadata["right"],
        "strike": metadata["strike"],
        "forward_price": forward,
        "atm_strike": atm_strike,
        "atm_offset_bps": atm_offset_bps,
        "vendor_delta": vendor_delta,
        "delta_abs": delta_abs,
        "open_interest": open_interest,
        "volume": volume,
        "open_price": payload["open"],
        "high_price": payload["high"],
        "low_price": payload["low"],
        "close_price": payload["close"],
        "source": SOURCE_NAME,
        "raw_payload": _json_dumps(payload),
    }


def collect_history_rows(
    *,
    start_date: dt.date,
    end_date: dt.date,
    force_refresh: bool,
    show_tqdm: bool = False,
    underlying_contracts: Optional[Sequence[str]] = None,
) -> List[Dict[str, Any]]:
    contract_universe = build_contract_universe(
        start_date,
        end_date,
        underlying_contracts=underlying_contracts,
    )
    requested_underlyings = _normalize_requested_underlying_contracts(underlying_contracts)
    if requested_underlyings:
        selected = [
            contract
            for family in ("UST", "STIR")
            for contract in requested_underlyings.get(family, [])
        ]
        _log_status(f"Filtering listed option universe to underlying contract(s): {', '.join(selected)}")
    ust_contract_count = sum(len(families.get("UST", [])) for families in contract_universe.values())
    stir_contract_count = sum(len(families.get("STIR", [])) for families in contract_universe.values())
    _log_status(
        f"Built listed option contract universe for {len(contract_universe)} business day(s): "
        f"UST={ust_contract_count} STIR={stir_contract_count}"
    )
    underlying_symbols = build_underlying_symbol_universe(contract_universe)
    _log_status(f"Resolved {len(underlying_symbols)} unique underlying symbols")
    underlying_data = _fetch_history_in_batches(
        start=start_date,
        end=end_date,
        symbols=underlying_symbols,
        show_tqdm=show_tqdm,
        stage_name="underlying",
    )
    option_symbols = build_option_symbol_universe(contract_universe=contract_universe, underlying_data=underlying_data)
    _log_status(f"Resolved {len(option_symbols)} unique option symbols")
    option_data = _fetch_history_in_batches(
        start=start_date,
        end=end_date,
        symbols=option_symbols,
        show_tqdm=show_tqdm,
        stage_name="option",
    )

    rows: List[Dict[str, Any]] = []
    for symbol, df in option_data.items():
        if df is None or df.empty:
            continue
        for row_dt, row in df.iterrows():
            as_of_date = pd.Timestamp(row_dt).date()
            if as_of_date < start_date or as_of_date > end_date:
                continue
            normalized = normalize_history_row(
                explicit_option_symbol=str(symbol),
                as_of_date=as_of_date,
                row=row.to_dict(),
                underlying_data=underlying_data,
            )
            if normalized is not None:
                rows.append(normalized)
    return rows


def _coerce_copy_cell(value: Any) -> Any:
    if value is None:
        return r"\N"
    if isinstance(value, (dt.date, dt.datetime)):
        return value.isoformat()
    if hasattr(value, "item"):
        try:
            return value.item()
        except Exception:
            return value
    return value


def _quote_ident(identifier: str) -> str:
    return f'"{str(identifier).replace(chr(34), chr(34) * 2)}"'


def _build_delete_statement(
    *,
    start_date: dt.date,
    end_date: dt.date,
    requested_underlyings: Sequence[str],
):
    sql = f"DELETE FROM {TABLE_NAME} WHERE as_of_date >= :start_date AND as_of_date <= :end_date"
    params: Dict[str, Any] = {
        "start_date": start_date,
        "end_date": end_date,
    }
    if requested_underlyings:
        statement = text(f"{sql} AND underlying_contract IN :underlying_contracts").bindparams(
            bindparam("underlying_contracts", expanding=True)
        )
        params["underlying_contracts"] = list(requested_underlyings)
        return statement, params
    return text(sql), params


def _persist_rows_postgres_copy(
    engine: Engine,
    *,
    rows: Sequence[Dict[str, Any]],
    start_date: dt.date,
    end_date: dt.date,
    requested_underlyings: Sequence[str],
) -> None:
    total_rows = len(rows)
    db_cols = [db_col for db_col, _row_key in DB_WRITE_COLUMN_SPECS]
    quoted_db_cols = ", ".join(_quote_ident(col) for col in db_cols)
    update_cols = [col for col in db_cols if col not in {"as_of_date", "explicit_option_symbol"}]
    updates = ", ".join([f'{_quote_ident(col)} = EXCLUDED.{_quote_ident(col)}' for col in update_cols])
    temp_table = f"{TABLE_NAME}_tmp_{uuid.uuid4().hex[:12]}"
    copy_sql = f"COPY {temp_table} ({quoted_db_cols}) FROM STDIN WITH (FORMAT csv, NULL '\\N')"
    merge_sql = f"""
        INSERT INTO {TABLE_NAME} ({quoted_db_cols})
        SELECT {quoted_db_cols}
        FROM {temp_table}
        ON CONFLICT (as_of_date, explicit_option_symbol) DO UPDATE
        SET {updates},
            updated_at = NOW()
    """
    delete_sql = f"DELETE FROM {TABLE_NAME} WHERE as_of_date >= %s AND as_of_date <= %s"
    delete_params: List[Any] = [start_date, end_date]
    if requested_underlyings:
        delete_sql += " AND underlying_contract = ANY(%s)"
        delete_params.append(list(requested_underlyings))

    raw_conn = engine.raw_connection()
    try:
        with raw_conn.cursor() as cur:
            cur.execute("SET LOCAL statement_timeout = 0")
            cur.execute("SET LOCAL synchronous_commit = OFF")

            if total_rows:
                _log_status(f"Persisting {total_rows} listed option rows via PostgreSQL COPY staging")
                cur.execute(f"CREATE TEMP TABLE {temp_table} (LIKE {TABLE_NAME} INCLUDING DEFAULTS) ON COMMIT DROP")
                for start_idx in range(0, total_rows, DB_WRITE_BATCH_SIZE):
                    batch = rows[start_idx : start_idx + DB_WRITE_BATCH_SIZE]
                    buffer = io.StringIO()
                    writer = csv.writer(buffer, lineterminator="\n")
                    for row in batch:
                        writer.writerow(
                            [_coerce_copy_cell(row.get(row_key)) for _db_col, row_key in DB_WRITE_COLUMN_SPECS]
                        )
                    buffer.seek(0)
                    cur.copy_expert(copy_sql, buffer)

            _log_status(
                f"Replacing DB slice for {start_date.isoformat()}..{end_date.isoformat()} "
                f"(underlyings={len(requested_underlyings) if requested_underlyings else 'ALL'})"
            )
            cur.execute(delete_sql, delete_params)
            if total_rows:
                merge_started = time.monotonic()
                cur.execute(merge_sql)
                _log_status(
                    f"Merged {total_rows} staged listed option rows in {time.monotonic() - merge_started:.1f}s"
                )
        raw_conn.commit()
    except Exception:
        raw_conn.rollback()
        raise
    finally:
        raw_conn.close()


def persist_rows(
    engine: Engine,
    *,
    rows: Sequence[Dict[str, Any]],
    start_date: dt.date,
    end_date: dt.date,
    underlying_contracts: Optional[Sequence[str]] = None,
) -> None:
    requested_underlyings = _resolved_requested_underlying_contracts(underlying_contracts)
    if engine.dialect.name == "postgresql":
        try:
            _persist_rows_postgres_copy(
                engine,
                rows=rows,
                start_date=start_date,
                end_date=end_date,
                requested_underlyings=requested_underlyings,
            )
            return
        except Exception as exc:
            _log_status(
                f"PostgreSQL COPY persist path failed; falling back to batched upserts: {type(exc).__name__}: {exc}",
                level="ERROR",
            )

    delete_stmt, delete_params = _build_delete_statement(
        start_date=start_date,
        end_date=end_date,
        requested_underlyings=requested_underlyings,
    )
    with engine.begin() as conn:
        conn.execute(delete_stmt, delete_params)
        if not rows:
            return
        for start_idx in range(0, len(rows), DB_WRITE_BATCH_SIZE):
            batch = list(rows[start_idx : start_idx + DB_WRITE_BATCH_SIZE])
            conn.execute(text(UPSERT_SQL), batch)


def run_ingest_window(
    engine: Engine,
    *,
    start_date: dt.date,
    end_date: dt.date,
    force_refresh: bool,
    show_tqdm: bool = False,
    underlying_contracts: Optional[Sequence[str]] = None,
) -> Dict[str, Any]:
    rows = collect_history_rows(
        start_date=start_date,
        end_date=end_date,
        force_refresh=force_refresh,
        show_tqdm=show_tqdm,
        underlying_contracts=underlying_contracts,
    )
    persist_rows(
        engine,
        rows=rows,
        start_date=start_date,
        end_date=end_date,
        underlying_contracts=underlying_contracts,
    )
    return {
        "start_date": start_date.isoformat(),
        "end_date": end_date.isoformat(),
        "row_count": len(rows),
        "symbol_count": len({str(row["explicit_option_symbol"]) for row in rows}),
    }


def main_range(args: argparse.Namespace) -> None:
    start_date = dt.date.fromisoformat(str(args.start_date))
    end_date = dt.date.fromisoformat(str(args.end_date))
    engine = create_db_engine()
    ensure_schema(engine)
    try:
        summary = run_ingest_window(
            engine,
            start_date=start_date,
            end_date=end_date,
            force_refresh=bool(args.force_refresh),
            show_tqdm=bool(getattr(args, "show_tqdm", False)),
            underlying_contracts=getattr(args, "underlying_contract", None),
        )
    except Exception as exc:
        _log_status(f"Listed option OI/volume backfill failed: {exc}", level="ERROR")
        raise
    _log_status(
        "Listed option OI/volume backfill complete: "
        f"{summary['start_date']}..{summary['end_date']} rows={summary['row_count']} symbols={summary['symbol_count']}"
    )


def main_once(args: argparse.Namespace) -> None:
    as_of_date = dt.date.fromisoformat(str(args.date)) if getattr(args, "date", None) else _current_trade_date()
    underlying_contracts = getattr(args, "underlying_contract", None)
    start_date, end_date = _resolve_once_ingest_window(
        as_of_date,
        underlying_contracts=underlying_contracts,
    )
    engine = create_db_engine()
    ensure_schema(engine)
    summary = run_ingest_window(
        engine,
        start_date=start_date,
        end_date=end_date,
        force_refresh=bool(args.force_refresh),
        show_tqdm=bool(getattr(args, "show_tqdm", False)),
        underlying_contracts=underlying_contracts,
    )
    if start_date != end_date:
        _log_status(
            "Listed option OI/volume prefetch complete: "
            f"requested_as_of={as_of_date.isoformat()} window={summary['start_date']}..{summary['end_date']} "
            f"rows={summary['row_count']} symbols={summary['symbol_count']}"
        )
        return
    _log_status(
        f"Listed option OI/volume daily ingest complete for {summary['start_date']}: "
        f"rows={summary['row_count']} symbols={summary['symbol_count']}"
    )


def main_service(args: argparse.Namespace) -> None:
    interval_seconds = max(30, int(getattr(args, "interval_seconds", DEFAULT_INTERVAL_SECONDS)))
    max_runs_raw = getattr(args, "max_runs", None)
    max_runs = None if max_runs_raw is None else max(1, int(max_runs_raw))
    engine = create_db_engine()
    ensure_schema(engine)
    if max_runs is None:
        _log_status(f"Starting listed option OI/volume service loop with {interval_seconds}s interval")
    else:
        _log_status(
            f"Starting listed option OI/volume service loop with {interval_seconds}s interval "
            f"for {max_runs} run(s)"
        )
    run_count = 0
    while max_runs is None or run_count < max_runs:
        as_of_date = _current_trade_date()
        try:
            summary = run_ingest_window(
                engine,
                start_date=as_of_date,
                end_date=as_of_date,
                force_refresh=bool(args.force_refresh),
                show_tqdm=False,
                underlying_contracts=getattr(args, "underlying_contract", None),
            )
            _log_status(
                f"Listed option OI/volume refresh complete for {summary['start_date']}: "
                f"rows={summary['row_count']} symbols={summary['symbol_count']}"
            )
        except Exception as exc:
            _log_status(f"Listed option OI/volume refresh failed: {exc}", level="ERROR")
        run_count += 1
        if max_runs is not None and run_count >= max_runs:
            _log_status(f"Listed option OI/volume service loop complete after {run_count} run(s)")
            break
        time.sleep(interval_seconds)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Ingest listed option open interest and volume history from Barchart.")
    subparsers = parser.add_subparsers(dest="mode", required=True)

    range_parser = subparsers.add_parser("range")
    range_parser.add_argument("--start-date", required=True)
    range_parser.add_argument("--end-date", required=True)
    range_parser.add_argument("--force-refresh", action="store_true")
    range_parser.add_argument("--show-tqdm", action="store_true")
    range_parser.add_argument("--underlying-contract", action="append")

    once_parser = subparsers.add_parser("once")
    once_parser.add_argument("--date")
    once_parser.add_argument("--force-refresh", action="store_true")
    once_parser.add_argument("--show-tqdm", action="store_true")
    once_parser.add_argument("--underlying-contract", action="append")

    service_parser = subparsers.add_parser("service")
    service_parser.add_argument("--interval-seconds", type=int, default=DEFAULT_INTERVAL_SECONDS)
    service_parser.add_argument("--force-refresh", action="store_true")
    service_parser.add_argument("--max-runs", type=int)
    service_parser.add_argument("--underlying-contract", action="append")
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    if args.mode == "range":
        main_range(args)
        return
    if args.mode == "once":
        main_once(args)
        return
    if args.mode == "service":
        main_service(args)
        return
    raise ValueError(f"Unsupported mode: {args.mode}")


if __name__ == "__main__":
    main()
