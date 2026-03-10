"""
Ingest exchange-listed USD rates option ATM normal vol snapshots and
pre-compute comparisons versus OTC swaption ATMF normal vol.

Modes:
  - range: backfill business dates in a window
  - once: ingest a single trade date
  - service: refresh today's trade date on a polling loop
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import math
import os
import time
from collections import OrderedDict, defaultdict
from typing import Any
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
import QuantLib as ql
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

from MDP.IRSwaptions.IRSwaptionMDP import IRSwaptionMDP, IRSwaptionMarketContext
from MDP.STIRFutures.STIRFutureMDP import STIRFutureMDP
from MDP.STIRFutures.STIRFutureOptionMDP import STIRFutureOptionMDP
from MDP.USTFutures.USTFutureOptionMDP import USTFutureOptionMDP
from MDP.USTFutures.USTFuturesMDP import USTFuturesMDP


LISTED_SNAPSHOTS_TABLE = "arbs_listed_option_vol_snapshots_v1"
LISTED_COMPARISON_TABLE = "arbs_listed_vs_swaption_vol_v1"
REALIZED_SNAPSHOTS_TABLE = "arbs_realized_vol_snapshots_v1"

DEFAULT_CURVE_NAME = "USD-SOFR-1D"
DEFAULT_SURFACE_TYPE = "atmf_normal"
DEFAULT_LOOKBACK_BUSINESS_DAYS = 126
DEFAULT_INTERVAL_SECONDS = 300
DEFAULT_REALIZED_FETCH_BUSINESS_DAYS = 160
MAX_BULK_SABR_SYMBOLS_PER_REQUEST = 3
MAX_CONSTANT_MATURITY_REQUEST_DAYS = 90

UST_OPTION_SOURCE = "USTFO_DUAL-QL"
STIR_OPTION_SOURCE = "STIRFO_DUAL-QL"
SWAPTION_SOURCE = "GSQUANT-QL"
UST_FUTURE_SOURCE = "BARCHART_USTF-RL"
STIR_FUTURE_SOURCE = "BARCHART_STIRF-RL"

ET_ZONE = ZoneInfo("America/New_York")

ROLLING_EXPIRIES: "OrderedDict[str, int]" = OrderedDict(
    [
        ("1W", 7),
        ("2W", 14),
        ("1M", 30),
        ("2M", 60),
        ("3M", 90),
        ("6M", 180),
    ]
)

REALIZED_WINDOWS: "OrderedDict[str, int]" = OrderedDict(
    [
        ("1W", 5),
        ("2W", 10),
        ("1M", 21),
        ("2M", 42),
        ("3M", 63),
        ("6M", 126),
    ]
)

PRODUCT_CLASS_BY_PRODUCT = {
    "TU": "UST",
    "FV": "UST",
    "TY": "UST",
    "US": "UST",
    "WN": "UST",
    "UXY": "UST",
    "SFR": "STIR",
}

PRODUCT_SWAP_TENOR = {
    "TU": "2Y",
    "FV": "5Y",
    "TY": "10Y",
    "US": "20Y",
    "WN": "30Y",
    "UXY": "10Y",
    "SFR": "1Y",
}

LISTED_TO_SWAPTION_EXPIRY = {
    "1W": "1m",
    "2W": "1m",
    "1M": "1m",
    "2M": "3m",
    "3M": "3m",
    "6M": "6m",
}

STIR_GLOBEX_ROOT_BY_PRODUCT = {
    "SFR": "SR3",
}

UST_OPTION_GLOBEX_ROOT_BY_PRODUCT = {
    "TU": "TU",
    "FV": "FV",
    "TY": "TY",
    "US": "US",
    "WN": "UL",
    "UXY": "TN",
}

SCHEMA_SQL = f"""
CREATE TABLE IF NOT EXISTS {LISTED_SNAPSHOTS_TABLE} (
    as_of_date DATE NOT NULL,
    product TEXT NOT NULL,
    product_class TEXT NOT NULL,
    expiry_label TEXT NOT NULL,
    expiry_days INTEGER NOT NULL,
    atm_nvol_price DOUBLE PRECISION,
    atm_nvol_bps DOUBLE PRECISION,
    forward_price DOUBLE PRECISION,
    forward_yield DOUBLE PRECISION,
    fv01 DOUBLE PRECISION,
    sabr_alpha DOUBLE PRECISION,
    sabr_rho DOUBLE PRECISION,
    sabr_nu DOUBLE PRECISION,
    sabr_beta DOUBLE PRECISION,
    underlying_contract TEXT,
    source TEXT NOT NULL,
    snapshot_data JSONB NOT NULL DEFAULT '{{}}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (as_of_date, product, expiry_label)
);

CREATE TABLE IF NOT EXISTS {LISTED_COMPARISON_TABLE} (
    as_of_date DATE NOT NULL,
    product TEXT NOT NULL,
    expiry_label TEXT NOT NULL,
    listed_atm_nvol_bps DOUBLE PRECISION,
    swaption_atmf_nvol_bps DOUBLE PRECISION,
    vol_ratio DOUBLE PRECISION,
    vol_diff_bps DOUBLE PRECISION,
    swaption_expiry_label TEXT,
    swaption_tenor_label TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (as_of_date, product, expiry_label)
);

CREATE TABLE IF NOT EXISTS {REALIZED_SNAPSHOTS_TABLE} (
    as_of_date DATE NOT NULL,
    product TEXT NOT NULL,
    window_label TEXT NOT NULL,
    realized_nvol_bps DOUBLE PRECISION,
    implied_realized_ratio DOUBLE PRECISION,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (as_of_date, product, window_label)
);

CREATE INDEX IF NOT EXISTS idx_listed_vol_snapshots_lookup
    ON {LISTED_SNAPSHOTS_TABLE}(product_class, as_of_date DESC, product, expiry_label);
CREATE INDEX IF NOT EXISTS idx_listed_vs_swaption_lookup
    ON {LISTED_COMPARISON_TABLE}(as_of_date DESC, product, expiry_label);
CREATE INDEX IF NOT EXISTS idx_realized_vol_lookup
    ON {REALIZED_SNAPSHOTS_TABLE}(as_of_date DESC, product, window_label);
"""

SCHEMA_PATCH_SQL = [
    (
        f"ALTER TABLE {LISTED_SNAPSHOTS_TABLE} "
        "ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()"
    ),
    (
        f"ALTER TABLE {LISTED_COMPARISON_TABLE} "
        "ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()"
    ),
    (
        f"ALTER TABLE {REALIZED_SNAPSHOTS_TABLE} "
        "ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()"
    ),
]


def _log_status(message: str, *, level: str = "INFO") -> None:
    timestamp = dt.datetime.now(tz=ET_ZONE).strftime("%Y-%m-%d %H:%M:%S %Z")
    print(f"[{timestamp}] [{level}] {message}", flush=True)


def _current_trade_date(now: dt.datetime | None = None) -> dt.date:
    ts = now.astimezone(ET_ZONE) if now else dt.datetime.now(tz=ET_ZONE)
    trade_date = ts.date()
    while trade_date.weekday() >= 5:
        trade_date -= dt.timedelta(days=1)
    return trade_date


def _previous_business_day(value: dt.date) -> dt.date:
    current = value - dt.timedelta(days=1)
    while current.weekday() >= 5:
        current -= dt.timedelta(days=1)
    return current


def _business_dates(start: dt.date, end: dt.date) -> list[dt.date]:
    if start > end:
        return []
    return [timestamp.date() for timestamp in pd.bdate_range(start, end)]


def _label_to_period(label: str) -> ql.Period:
    token = str(label).strip().upper()
    if token.endswith("W"):
        return ql.Period(int(token[:-1]), ql.Weeks)
    if token.endswith("M"):
        return ql.Period(int(token[:-1]), ql.Months)
    if token.endswith("Y"):
        return ql.Period(int(token[:-1]), ql.Years)
    if token.endswith("D"):
        return ql.Period(int(token[:-1]), ql.Days)
    raise ValueError(f"Unsupported tenor label: {label!r}")


def _safe_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(parsed):
        return None
    return parsed


def _safe_ratio(numerator: float | None, denominator: float | None) -> float | None:
    if numerator is None or denominator is None:
        return None
    if not math.isfinite(numerator) or not math.isfinite(denominator) or abs(denominator) < 1e-12:
        return None
    return numerator / denominator


def _json_dumps(value: Any) -> str:
    return json.dumps(value, separators=(",", ":"), sort_keys=True)


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
        for statement in SCHEMA_PATCH_SQL:
            stmt = statement.strip()
            if stmt:
                conn.execute(text(stmt))


def _ust_request_symbol(product: str, expiry_days: int) -> str:
    root = UST_OPTION_GLOBEX_ROOT_BY_PRODUCT[product]
    return f"{root}_{int(expiry_days):02d}"


def _stir_request_symbol(product: str, expiry_days: int) -> str:
    root = STIR_GLOBEX_ROOT_BY_PRODUCT[product]
    return f"{root}_{int(expiry_days)}"


def _supported_smile_request_expiries() -> "OrderedDict[str, int]":
    return OrderedDict(
        (label, days)
        for label, days in ROLLING_EXPIRIES.items()
        if int(days) <= MAX_CONSTANT_MATURITY_REQUEST_DAYS
    )


def build_smile_request_maps() -> dict[str, tuple[str, str]]:
    mapping: dict[str, tuple[str, str]] = {}
    for product, product_class in PRODUCT_CLASS_BY_PRODUCT.items():
        for expiry_label, expiry_days in _supported_smile_request_expiries().items():
            if product_class == "UST":
                mapping[_ust_request_symbol(product, expiry_days)] = (product, expiry_label)
            else:
                mapping[_stir_request_symbol(product, expiry_days)] = (product, expiry_label)
    return mapping


def _fetch_bulk_sabr_smiles_batched(
    *,
    mdp: Any,
    globex_symbols: list[str],
    as_of_date: dt.date,
    force_refresh: bool,
    batch_size: int = MAX_BULK_SABR_SYMBOLS_PER_REQUEST,
) -> dict[str, dict[dt.date, Any]]:
    if not globex_symbols:
        return {}
    if batch_size <= 0:
        raise ValueError("batch_size must be positive")

    merged: dict[str, dict[dt.date, Any]] = {}
    for start in range(0, len(globex_symbols), batch_size):
        symbol_batch = globex_symbols[start : start + batch_size]
        batch_smiles = mdp.fetch_bulk_sabr_smile(
            {
                "globex_symbols": symbol_batch,
                "timestamps": [as_of_date],
                "force_refresh": force_refresh,
                "show_tqdm": False,
            }
        )
        for request_symbol, by_date in (batch_smiles or {}).items():
            merged.setdefault(str(request_symbol), {}).update(by_date or {})
    return merged


def _build_snapshot_row_from_ust_smile(
    *,
    as_of_date: dt.date,
    product: str,
    expiry_label: str,
    expiry_days_requested: int,
    smile: Any,
) -> dict[str, Any]:
    atm_nvol_price = _safe_float(smile.normal_vol(smile.params.forward_price))
    fv01 = _safe_float(smile.fv01)
    atm_nvol_bps = _safe_ratio(atm_nvol_price, fv01) if atm_nvol_price is not None and fv01 is not None else None
    actual_expiry_days = max((smile.params.expiry_date - as_of_date).days, 0)
    return {
        "as_of_date": as_of_date,
        "product": product,
        "product_class": "UST",
        "expiry_label": expiry_label,
        "expiry_days": actual_expiry_days or int(expiry_days_requested),
        "atm_nvol_price": atm_nvol_price,
        "atm_nvol_bps": atm_nvol_bps,
        "forward_price": _safe_float(smile.params.forward_price),
        "forward_yield": _safe_float(smile.params.forward_futures_ytm),
        "fv01": fv01,
        "sabr_alpha": _safe_float(smile.params.alpha),
        "sabr_rho": _safe_float(smile.params.rho),
        "sabr_nu": _safe_float(smile.params.nu),
        "sabr_beta": _safe_float(smile.params.beta),
        "underlying_contract": str(smile.underlying_contract),
        "source": str(smile.source),
        "snapshot_data": _json_dumps(smile.to_dict()),
    }


def _build_snapshot_row_from_stir_smile(
    *,
    as_of_date: dt.date,
    product: str,
    expiry_label: str,
    expiry_days_requested: int,
    smile: Any,
) -> dict[str, Any]:
    atm_nvol_price = _safe_float(smile.normal_vol(smile.params.forward_price))
    atm_nvol_bps = _safe_float(smile.normal_vol(smile.params.forward_price, vol_units="bps"))
    actual_expiry_days = max((smile.params.expiry_date - as_of_date).days, 0)
    return {
        "as_of_date": as_of_date,
        "product": product,
        "product_class": "STIR",
        "expiry_label": expiry_label,
        "expiry_days": actual_expiry_days or int(expiry_days_requested),
        "atm_nvol_price": atm_nvol_price,
        "atm_nvol_bps": atm_nvol_bps,
        "forward_price": _safe_float(smile.params.forward_price),
        "forward_yield": _safe_float(smile.params.forward_rate),
        "fv01": None,
        "sabr_alpha": _safe_float(smile.params.alpha),
        "sabr_rho": _safe_float(smile.params.rho),
        "sabr_nu": _safe_float(smile.params.nu),
        "sabr_beta": _safe_float(smile.params.beta),
        "underlying_contract": str(smile.underlying_contract),
        "source": str(smile.source),
        "snapshot_data": _json_dumps(smile.to_dict()),
    }


def _extract_swaption_normal_vol_bps(
    context: IRSwaptionMarketContext,
    *,
    expiry_label: str,
    tenor_label: str,
) -> float | None:
    as_of_date = context.as_of_date
    ql_eval = ql.Date(as_of_date.day, as_of_date.month, as_of_date.year)
    ql.Settings.instance().evaluationDate = ql_eval
    calendar = ql.UnitedStates(ql.UnitedStates.GovernmentBond)
    option_date = calendar.advance(
        ql_eval,
        _label_to_period(expiry_label.upper()),
        ql.ModifiedFollowing,
    )
    try:
        value = context.vol_handle.volatility(option_date, _label_to_period(tenor_label.upper()), 0.0)
    except Exception:
        return None
    return _safe_float(value * 10_000.0)


def _build_comparison_row(
    listed_row: dict[str, Any],
    *,
    swaption_atmf_nvol_bps: float | None,
) -> dict[str, Any]:
    listed_bps = _safe_float(listed_row.get("atm_nvol_bps"))
    expiry_label = str(listed_row["expiry_label"])
    product = str(listed_row["product"])
    swaption_expiry_label = LISTED_TO_SWAPTION_EXPIRY[expiry_label]
    swaption_tenor_label = PRODUCT_SWAP_TENOR[product]
    vol_ratio = _safe_ratio(swaption_atmf_nvol_bps, listed_bps)
    vol_diff_bps = (
        swaption_atmf_nvol_bps - listed_bps
        if swaption_atmf_nvol_bps is not None and listed_bps is not None
        else None
    )
    return {
        "as_of_date": listed_row["as_of_date"],
        "product": product,
        "expiry_label": expiry_label,
        "listed_atm_nvol_bps": listed_bps,
        "swaption_atmf_nvol_bps": swaption_atmf_nvol_bps,
        "vol_ratio": vol_ratio,
        "vol_diff_bps": vol_diff_bps,
        "swaption_expiry_label": swaption_expiry_label,
        "swaption_tenor_label": swaption_tenor_label,
    }


def compute_annualized_realized_normal_vol_bps(
    levels_bps: pd.Series,
    *,
    window_sessions: int,
) -> float | None:
    if levels_bps.empty:
        return None
    clean = pd.Series(levels_bps).dropna().sort_index()
    if clean.empty:
        return None
    daily_changes = clean.diff().dropna()
    if window_sessions > 0:
        daily_changes = daily_changes.tail(int(window_sessions))
    if len(daily_changes) < 2:
        return None
    volatility = float(np.std(daily_changes.to_numpy(dtype=float), ddof=1) * math.sqrt(252.0))
    if not math.isfinite(volatility):
        return None
    return volatility


def _load_ust_yield_series_by_symbol(
    *,
    symbols: list[str],
    dates: list[dt.date],
    force_refresh: bool,
) -> dict[str, pd.Series]:
    if not symbols or not dates:
        return {}
    mdp = USTFuturesMDP(source=UST_FUTURE_SOURCE, force_refresh=force_refresh)
    raw = mdp.get_bulk_data(
        {
            "symbols": symbols,
            "timestamps": dates,
            "show_tqdm": False,
            "force_refresh": force_refresh,
        }
    )
    buckets: dict[str, dict[dt.date, float]] = defaultdict(dict)
    for ts, by_symbol in (raw or {}).items():
        as_of_date = ts.date() if isinstance(ts, dt.datetime) else ts
        if not isinstance(as_of_date, dt.date):
            continue
        for symbol, pricers in (by_symbol or {}).items():
            if not pricers:
                continue
            pricer = pricers[0]
            try:
                price = float(pricer.price(None))
                yield_level = float(pricer.yield_to_maturity_from_price(price)) * 10_000.0
            except Exception:
                continue
            if math.isfinite(yield_level):
                buckets[str(symbol)][as_of_date] = yield_level
    return {
        symbol: pd.Series(dict(sorted(levels.items())))
        for symbol, levels in buckets.items()
        if levels
    }


def _load_stir_rate_series_by_symbol(
    *,
    symbols: list[str],
    dates: list[dt.date],
    force_refresh: bool,
) -> dict[str, pd.Series]:
    if not symbols or not dates:
        return {}
    mdp = STIRFutureMDP(source=STIR_FUTURE_SOURCE, force_refresh=force_refresh)
    raw = mdp.get_bulk_data(
        {
            "symbols": symbols,
            "timestamps": dates,
            "show_tqdm": False,
            "force_refresh": force_refresh,
        }
    )
    buckets: dict[str, dict[dt.date, float]] = defaultdict(dict)
    for ts, by_symbol in (raw or {}).items():
        as_of_date = ts.date() if isinstance(ts, dt.datetime) else ts
        if not isinstance(as_of_date, dt.date):
            continue
        for symbol, pricers in (by_symbol or {}).items():
            if not pricers:
                continue
            pricer = pricers[0]
            try:
                price = float(pricer.price())
                rate_bps = (100.0 - price) * 100.0
            except Exception:
                continue
            if math.isfinite(rate_bps):
                buckets[str(symbol)][as_of_date] = rate_bps
    return {
        symbol: pd.Series(dict(sorted(levels.items())))
        for symbol, levels in buckets.items()
        if levels
    }


def _build_realized_rows(
    listed_rows: list[dict[str, Any]],
    *,
    as_of_date: dt.date,
    force_refresh: bool,
) -> list[dict[str, Any]]:
    product_to_contract: dict[str, str] = {}
    product_to_class: dict[str, str] = {}
    implied_by_product_window: dict[tuple[str, str], float | None] = {}
    for row in listed_rows:
        product = str(row["product"])
        product_to_class[product] = str(row["product_class"])
        contract = str(row.get("underlying_contract") or "").strip()
        if contract and product not in product_to_contract:
            product_to_contract[product] = contract
        implied_by_product_window[(product, str(row["expiry_label"]))] = _safe_float(row.get("atm_nvol_bps"))

    if not product_to_contract:
        return []

    start_date = (pd.Timestamp(as_of_date) - pd.tseries.offsets.BDay(DEFAULT_REALIZED_FETCH_BUSINESS_DAYS)).date()
    fetch_dates = _business_dates(start_date, as_of_date)

    ust_symbols = sorted(
        contract
        for product, contract in product_to_contract.items()
        if product_to_class.get(product) == "UST"
    )
    stir_symbols = sorted(
        contract
        for product, contract in product_to_contract.items()
        if product_to_class.get(product) == "STIR"
    )

    ust_series = _load_ust_yield_series_by_symbol(
        symbols=ust_symbols,
        dates=fetch_dates,
        force_refresh=force_refresh,
    )
    stir_series = _load_stir_rate_series_by_symbol(
        symbols=stir_symbols,
        dates=fetch_dates,
        force_refresh=force_refresh,
    )

    realized_rows: list[dict[str, Any]] = []
    for product, contract in product_to_contract.items():
        levels = ust_series.get(contract) if product_to_class.get(product) == "UST" else stir_series.get(contract)
        if levels is None or levels.empty:
            continue
        for window_label, window_sessions in REALIZED_WINDOWS.items():
            realized_nvol_bps = compute_annualized_realized_normal_vol_bps(
                levels,
                window_sessions=window_sessions,
            )
            implied_nvol_bps = implied_by_product_window.get((product, window_label))
            implied_realized_ratio = _safe_ratio(implied_nvol_bps, realized_nvol_bps)
            realized_rows.append(
                {
                    "as_of_date": as_of_date,
                    "product": product,
                    "window_label": window_label,
                    "realized_nvol_bps": realized_nvol_bps,
                    "implied_realized_ratio": implied_realized_ratio,
                }
            )
    return realized_rows


def _fetch_daily_listed_snapshot_rows(
    *,
    as_of_date: dt.date,
    force_refresh: bool,
) -> list[dict[str, Any]]:
    request_map = build_smile_request_maps()

    ust_symbols = [symbol for symbol, (product, _) in request_map.items() if PRODUCT_CLASS_BY_PRODUCT[product] == "UST"]
    stir_symbols = [symbol for symbol, (product, _) in request_map.items() if PRODUCT_CLASS_BY_PRODUCT[product] == "STIR"]

    ust_mdp = USTFutureOptionMDP(source=UST_OPTION_SOURCE, force_refresh=force_refresh)
    stir_mdp = STIRFutureOptionMDP(source=STIR_OPTION_SOURCE, force_refresh=force_refresh)

    ust_smiles = _fetch_bulk_sabr_smiles_batched(
        mdp=ust_mdp,
        globex_symbols=ust_symbols,
        as_of_date=as_of_date,
        force_refresh=force_refresh,
    )
    stir_smiles = _fetch_bulk_sabr_smiles_batched(
        mdp=stir_mdp,
        globex_symbols=stir_symbols,
        as_of_date=as_of_date,
        force_refresh=force_refresh,
    )

    rows: list[dict[str, Any]] = []
    for request_symbol, by_date in ust_smiles.items():
        key = request_map.get(str(request_symbol))
        if key is None:
            continue
        product, expiry_label = key
        smile = by_date.get(as_of_date)
        if smile is None:
            continue
        rows.append(
            _build_snapshot_row_from_ust_smile(
                as_of_date=as_of_date,
                product=product,
                expiry_label=expiry_label,
                expiry_days_requested=ROLLING_EXPIRIES[expiry_label],
                smile=smile,
            )
        )

    for request_symbol, by_date in stir_smiles.items():
        key = request_map.get(str(request_symbol))
        if key is None:
            continue
        product, expiry_label = key
        smile = by_date.get(as_of_date)
        if smile is None:
            continue
        rows.append(
            _build_snapshot_row_from_stir_smile(
                as_of_date=as_of_date,
                product=product,
                expiry_label=expiry_label,
                expiry_days_requested=ROLLING_EXPIRIES[expiry_label],
                smile=smile,
            )
        )
    return sorted(rows, key=lambda row: (str(row["product"]), str(row["expiry_label"])))


def _build_daily_comparison_rows(
    listed_rows: list[dict[str, Any]],
    *,
    as_of_date: dt.date,
    curve_name: str,
    surface_type: str,
    force_refresh: bool,
) -> list[dict[str, Any]]:
    if not listed_rows:
        return []
    mdp = IRSwaptionMDP(source=SWAPTION_SOURCE, force_refresh=force_refresh)
    context = mdp.get_data(
        {
            "curve_name": curve_name,
            "timestamp": as_of_date,
            "surface_type": surface_type,
            "ignore_cache": force_refresh,
        }
    )

    rows: list[dict[str, Any]] = []
    for listed_row in listed_rows:
        product = str(listed_row["product"])
        swaption_expiry = LISTED_TO_SWAPTION_EXPIRY[str(listed_row["expiry_label"])]
        swaption_tenor = PRODUCT_SWAP_TENOR[product]
        swaption_nvol_bps = _extract_swaption_normal_vol_bps(
            context,
            expiry_label=swaption_expiry,
            tenor_label=swaption_tenor,
        )
        rows.append(
            _build_comparison_row(
                listed_row,
                swaption_atmf_nvol_bps=swaption_nvol_bps,
            )
        )
    return rows


def _persist_daily_rows(
    engine: Engine,
    *,
    as_of_date: dt.date,
    listed_rows: list[dict[str, Any]],
    comparison_rows: list[dict[str, Any]],
    realized_rows: list[dict[str, Any]],
) -> None:
    delete_snapshot_sql = text(f"DELETE FROM {LISTED_SNAPSHOTS_TABLE} WHERE as_of_date = :as_of_date")
    delete_comparison_sql = text(f"DELETE FROM {LISTED_COMPARISON_TABLE} WHERE as_of_date = :as_of_date")
    delete_realized_sql = text(f"DELETE FROM {REALIZED_SNAPSHOTS_TABLE} WHERE as_of_date = :as_of_date")

    snapshot_upsert_sql = text(
        f"""
        INSERT INTO {LISTED_SNAPSHOTS_TABLE} (
            as_of_date, product, product_class, expiry_label, expiry_days,
            atm_nvol_price, atm_nvol_bps, forward_price, forward_yield, fv01,
            sabr_alpha, sabr_rho, sabr_nu, sabr_beta, underlying_contract, source, snapshot_data
        ) VALUES (
            :as_of_date, :product, :product_class, :expiry_label, :expiry_days,
            :atm_nvol_price, :atm_nvol_bps, :forward_price, :forward_yield, :fv01,
            :sabr_alpha, :sabr_rho, :sabr_nu, :sabr_beta, :underlying_contract, :source, CAST(:snapshot_data AS JSONB)
        )
        ON CONFLICT (as_of_date, product, expiry_label) DO UPDATE SET
            product_class = EXCLUDED.product_class,
            expiry_days = EXCLUDED.expiry_days,
            atm_nvol_price = EXCLUDED.atm_nvol_price,
            atm_nvol_bps = EXCLUDED.atm_nvol_bps,
            forward_price = EXCLUDED.forward_price,
            forward_yield = EXCLUDED.forward_yield,
            fv01 = EXCLUDED.fv01,
            sabr_alpha = EXCLUDED.sabr_alpha,
            sabr_rho = EXCLUDED.sabr_rho,
            sabr_nu = EXCLUDED.sabr_nu,
            sabr_beta = EXCLUDED.sabr_beta,
            underlying_contract = EXCLUDED.underlying_contract,
            source = EXCLUDED.source,
            snapshot_data = EXCLUDED.snapshot_data,
            updated_at = NOW()
        """
    )
    comparison_upsert_sql = text(
        f"""
        INSERT INTO {LISTED_COMPARISON_TABLE} (
            as_of_date, product, expiry_label, listed_atm_nvol_bps,
            swaption_atmf_nvol_bps, vol_ratio, vol_diff_bps, swaption_expiry_label, swaption_tenor_label
        ) VALUES (
            :as_of_date, :product, :expiry_label, :listed_atm_nvol_bps,
            :swaption_atmf_nvol_bps, :vol_ratio, :vol_diff_bps, :swaption_expiry_label, :swaption_tenor_label
        )
        ON CONFLICT (as_of_date, product, expiry_label) DO UPDATE SET
            listed_atm_nvol_bps = EXCLUDED.listed_atm_nvol_bps,
            swaption_atmf_nvol_bps = EXCLUDED.swaption_atmf_nvol_bps,
            vol_ratio = EXCLUDED.vol_ratio,
            vol_diff_bps = EXCLUDED.vol_diff_bps,
            swaption_expiry_label = EXCLUDED.swaption_expiry_label,
            swaption_tenor_label = EXCLUDED.swaption_tenor_label,
            updated_at = NOW()
        """
    )
    realized_upsert_sql = text(
        f"""
        INSERT INTO {REALIZED_SNAPSHOTS_TABLE} (
            as_of_date, product, window_label, realized_nvol_bps, implied_realized_ratio
        ) VALUES (
            :as_of_date, :product, :window_label, :realized_nvol_bps, :implied_realized_ratio
        )
        ON CONFLICT (as_of_date, product, window_label) DO UPDATE SET
            realized_nvol_bps = EXCLUDED.realized_nvol_bps,
            implied_realized_ratio = EXCLUDED.implied_realized_ratio,
            updated_at = NOW()
        """
    )

    with engine.begin() as conn:
        conn.execute(delete_snapshot_sql, {"as_of_date": as_of_date})
        conn.execute(delete_comparison_sql, {"as_of_date": as_of_date})
        conn.execute(delete_realized_sql, {"as_of_date": as_of_date})
        if listed_rows:
            conn.execute(snapshot_upsert_sql, listed_rows)
        if comparison_rows:
            conn.execute(comparison_upsert_sql, comparison_rows)
        if realized_rows:
            conn.execute(realized_upsert_sql, realized_rows)


def run_daily_ingest(
    engine: Engine,
    *,
    as_of_date: dt.date,
    curve_name: str,
    surface_type: str,
    force_refresh: bool = False,
) -> dict[str, Any]:
    listed_rows = _fetch_daily_listed_snapshot_rows(
        as_of_date=as_of_date,
        force_refresh=force_refresh,
    )
    comparison_rows = _build_daily_comparison_rows(
        listed_rows,
        as_of_date=as_of_date,
        curve_name=curve_name,
        surface_type=surface_type,
        force_refresh=force_refresh,
    )
    realized_rows = _build_realized_rows(
        listed_rows,
        as_of_date=as_of_date,
        force_refresh=force_refresh,
    )
    _persist_daily_rows(
        engine,
        as_of_date=as_of_date,
        listed_rows=listed_rows,
        comparison_rows=comparison_rows,
        realized_rows=realized_rows,
    )
    return {
        "as_of_date": as_of_date.isoformat(),
        "listed_rows": len(listed_rows),
        "comparison_rows": len(comparison_rows),
        "realized_rows": len(realized_rows),
    }


def main_range(args: argparse.Namespace) -> None:
    engine = create_db_engine()
    ensure_schema(engine)

    if args.start_date:
        start_date = dt.date.fromisoformat(args.start_date)
    else:
        anchor = dt.date.fromisoformat(args.end_date) if args.end_date else _previous_business_day(_current_trade_date())
        start_date = (pd.Timestamp(anchor) - pd.tseries.offsets.BDay(args.lookback_business_days)).date()

    end_date = dt.date.fromisoformat(args.end_date) if args.end_date else _previous_business_day(_current_trade_date())
    dates = _business_dates(start_date, end_date)
    _log_status(
        f"Starting listed-vol backfill: {start_date.isoformat()} -> {end_date.isoformat()} "
        f"({len(dates)} business dates)"
    )
    success_count = 0
    failure_count = 0
    for as_of_date in dates:
        started = time.time()
        try:
            result = run_daily_ingest(
                engine,
                as_of_date=as_of_date,
                curve_name=args.curve_name,
                surface_type=args.surface_type,
                force_refresh=args.force_refresh,
            )
            elapsed = time.time() - started
            success_count += 1
            _log_status(
                f"{result['as_of_date']}: listed={result['listed_rows']} "
                f"comparison={result['comparison_rows']} realized={result['realized_rows']} "
                f"in {elapsed:.1f}s"
            )
        except Exception as exc:
            elapsed = time.time() - started
            failure_count += 1
            _log_status(
                f"{as_of_date.isoformat()}: failed after {elapsed:.1f}s with error: {exc}",
                level="ERROR",
            )
    _log_status(
        f"Listed-vol backfill complete: success={success_count} failure={failure_count}"
    )


def main_once(args: argparse.Namespace) -> None:
    engine = create_db_engine()
    ensure_schema(engine)
    as_of_date = (
        dt.date.fromisoformat(args.date)
        if args.date
        else (dt.date.fromisoformat(args.end_date) if args.end_date else _current_trade_date())
    )
    result = run_daily_ingest(
        engine,
        as_of_date=as_of_date,
        curve_name=args.curve_name,
        surface_type=args.surface_type,
        force_refresh=args.force_refresh,
    )
    _log_status(
        f"{result['as_of_date']}: listed={result['listed_rows']} "
        f"comparison={result['comparison_rows']} realized={result['realized_rows']}"
    )


def main_service(args: argparse.Namespace) -> None:
    engine = create_db_engine()
    ensure_schema(engine)
    interval_seconds = max(int(args.interval_seconds), 30)
    cycle_number = 0
    _log_status(
        "Starting listed-vol service: "
        f"curve={args.curve_name} surface={args.surface_type} interval={interval_seconds}s"
    )
    while True:
        cycle_number += 1
        started = time.time()
        as_of_date = _current_trade_date()
        try:
            result = run_daily_ingest(
                engine,
                as_of_date=as_of_date,
                curve_name=args.curve_name,
                surface_type=args.surface_type,
                force_refresh=args.force_refresh,
            )
            _log_status(
                f"Cycle {cycle_number} [{result['as_of_date']}]: "
                f"listed={result['listed_rows']} comparison={result['comparison_rows']} "
                f"realized={result['realized_rows']}"
            )
        except Exception as exc:
            _log_status(f"Cycle {cycle_number} failed: {exc}", level="ERROR")

        elapsed = time.time() - started
        sleep_seconds = max(interval_seconds - elapsed, 5)
        _log_status(f"Cycle {cycle_number} finished in {elapsed:.1f}s; sleeping {sleep_seconds:.1f}s")
        time.sleep(sleep_seconds)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Ingest listed USD rates option ATM vol and swaption comparisons.",
    )
    parser.add_argument(
        "--mode",
        choices=("range", "once", "service"),
        required=True,
    )
    parser.add_argument("--curve-name", default=DEFAULT_CURVE_NAME)
    parser.add_argument("--surface-type", default=DEFAULT_SURFACE_TYPE)
    parser.add_argument("--date")
    parser.add_argument("--start-date")
    parser.add_argument("--end-date")
    parser.add_argument(
        "--lookback-business-days",
        type=int,
        default=DEFAULT_LOOKBACK_BUSINESS_DAYS,
    )
    parser.add_argument(
        "--interval-seconds",
        type=int,
        default=DEFAULT_INTERVAL_SECONDS,
    )
    parser.add_argument("--force-refresh", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.mode == "range":
        main_range(args)
        return
    if args.mode == "once":
        main_once(args)
        return
    main_service(args)


if __name__ == "__main__":
    main()
