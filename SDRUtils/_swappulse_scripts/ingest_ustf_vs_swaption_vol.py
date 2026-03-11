"""
Ingest UST Futures option ATM normal vol snapshots (SABR) and
MONKEYCUBE swaption SABR snapshots, plus pre-computed comparison rows.

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
from collections import OrderedDict
from typing import Any
from zoneinfo import ZoneInfo

import pandas as pd
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

from MDP.IRSwaptions.IRSwaptionMDP import IRSwaptionMDP
from MDP.IRSwaptions.MONKEYCUBE import get_cached_cube
from MDP.USTFutures.USTFutureOptionMDP import USTFutureOptionMDP


USTF_SNAPSHOTS_TABLE = "arbs_ustf_vol_snapshots_v2"
SWAPTION_SNAPSHOTS_TABLE = "arbs_swaption_vol_snapshots_v2"
COMPARISON_TABLE = "arbs_ustf_vs_swaption_comparison_v2"

DEFAULT_CURVE_NAME = "USD-SOFR-1D"
DEFAULT_LOOKBACK_BUSINESS_DAYS = 126
DEFAULT_INTERVAL_SECONDS = 300
MAX_BULK_SABR_SYMBOLS_PER_REQUEST = 3

MONKEYCUBE_DATA_DIR = (
    r"C:\Users\chris\clee\ARBS\MDP\IRSwaptions\MONKEYCUBE\YCMONKEY_USD_VOL_CUBE_GAMMA_MIX"
)

ET_ZONE = ZoneInfo("America/New_York")

USTF_PRODUCTS = ["TU", "FV", "TY", "TN", "US", "UL"]

USTF_SWAP_TAIL: dict[str, str] = {
    "TU": "2Y",
    "FV": "5Y",
    "TY": "7Y",
    "TN": "10Y",
    "US": "20Y",
    "UL": "30Y",
}

USTF_GLOBEX_ROOT: dict[str, str] = {
    "TU": "TU",
    "FV": "FV",
    "TY": "TY",
    "TN": "TN",
    "US": "US",
    "UL": "UL",
}

ROLLING_EXPIRIES: OrderedDict[str, int] = OrderedDict(
    [
        ("1W", 7),
        ("2W", 14),
        ("1M", 30),
        ("2M", 60),
        ("3M", 90),
        ("6M", 180),
    ]
)

USTF_TO_SWAPTION_EXPIRY: dict[str, str] = {
    "1W": "1M",
    "2W": "1M",
    "1M": "1M",
    "2M": "3M",
    "3M": "3M",
    "6M": "6M",
}

SWAPTION_EXPIRY_LABELS = ["1M", "3M", "6M", "1Y"]
SWAPTION_TAIL_LABELS = ["2Y", "5Y", "7Y", "10Y", "20Y", "30Y"]

SCHEMA_SQL = f"""
CREATE TABLE IF NOT EXISTS {USTF_SNAPSHOTS_TABLE} (
    as_of_date          DATE NOT NULL,
    product             TEXT NOT NULL,
    expiry_label        TEXT NOT NULL,
    expiry_days         INTEGER NOT NULL,
    atm_nvol_bps        DOUBLE PRECISION,
    atm_nvol_price      DOUBLE PRECISION,
    forward_price       DOUBLE PRECISION,
    forward_yield       DOUBLE PRECISION,
    fv01                DOUBLE PRECISION,
    sabr_alpha          DOUBLE PRECISION,
    sabr_beta           DOUBLE PRECISION,
    sabr_rho            DOUBLE PRECISION,
    sabr_nu             DOUBLE PRECISION,
    time_to_expiry      DOUBLE PRECISION,
    underlying_contract TEXT,
    source              TEXT NOT NULL,
    smile_points        JSONB NOT NULL DEFAULT '[]'::jsonb,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (as_of_date, product, expiry_label)
);

CREATE TABLE IF NOT EXISTS {SWAPTION_SNAPSHOTS_TABLE} (
    as_of_date          DATE NOT NULL,
    expiry_label        TEXT NOT NULL,
    tail_label          TEXT NOT NULL,
    atm_nvol_bps        DOUBLE PRECISION,
    atmf_rate           DOUBLE PRECISION,
    sabr_alpha          DOUBLE PRECISION,
    sabr_beta           DOUBLE PRECISION,
    sabr_rho            DOUBLE PRECISION,
    sabr_nu             DOUBLE PRECISION,
    expiry_time         DOUBLE PRECISION,
    source              TEXT NOT NULL,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (as_of_date, expiry_label, tail_label)
);

CREATE TABLE IF NOT EXISTS {COMPARISON_TABLE} (
    as_of_date              DATE NOT NULL,
    product                 TEXT NOT NULL,
    expiry_label            TEXT NOT NULL,
    ustf_atm_nvol_bps       DOUBLE PRECISION,
    swaption_atm_nvol_bps   DOUBLE PRECISION,
    vol_diff_bps            DOUBLE PRECISION,
    vol_ratio               DOUBLE PRECISION,
    swaption_expiry_label   TEXT,
    swaption_tail_label     TEXT,
    created_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (as_of_date, product, expiry_label)
);

CREATE INDEX IF NOT EXISTS idx_ustf_vol_snapshots_v2_lookup
    ON {USTF_SNAPSHOTS_TABLE}(as_of_date DESC, product, expiry_label);
CREATE INDEX IF NOT EXISTS idx_swaption_vol_snapshots_v2_lookup
    ON {SWAPTION_SNAPSHOTS_TABLE}(as_of_date DESC, expiry_label, tail_label);
CREATE INDEX IF NOT EXISTS idx_ustf_vs_swaption_v2_lookup
    ON {COMPARISON_TABLE}(as_of_date DESC, product, expiry_label);
"""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# DB
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# USTF Option Snapshot Fetching
# ---------------------------------------------------------------------------

def _ust_request_symbol(product: str, expiry_days: int) -> str:
    root = USTF_GLOBEX_ROOT[product]
    return f"{root}_{int(expiry_days):02d}"


def _build_ustf_request_map() -> dict[str, tuple[str, str]]:
    mapping: dict[str, tuple[str, str]] = {}
    for product in USTF_PRODUCTS:
        for expiry_label, expiry_days in ROLLING_EXPIRIES.items():
            symbol = _ust_request_symbol(product, expiry_days)
            mapping[symbol] = (product, expiry_label)
    return mapping


def _fetch_bulk_sabr_smiles_batched(
    *,
    mdp: USTFutureOptionMDP,
    globex_symbols: list[str],
    as_of_date: dt.date,
    force_refresh: bool,
    batch_size: int = MAX_BULK_SABR_SYMBOLS_PER_REQUEST,
) -> dict[str, dict[dt.date, Any]]:
    if not globex_symbols:
        return {}
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


def _build_ustf_snapshot_row(
    *,
    as_of_date: dt.date,
    product: str,
    expiry_label: str,
    expiry_days_requested: int,
    smile: Any,
) -> dict[str, Any]:
    atm_nvol_price = _safe_float(smile.normal_vol(smile.params.forward_price))
    fv01 = _safe_float(smile.fv01)
    atm_nvol_bps = (
        _safe_ratio(atm_nvol_price, fv01)
        if atm_nvol_price is not None and fv01 is not None
        else None
    )
    actual_expiry_days = max((smile.params.expiry_date - as_of_date).days, 0)
    smile_points_list = [pt.to_dict() for pt in smile.points] if smile.points else []
    return {
        "as_of_date": as_of_date,
        "product": product,
        "expiry_label": expiry_label,
        "expiry_days": actual_expiry_days or int(expiry_days_requested),
        "atm_nvol_bps": atm_nvol_bps,
        "atm_nvol_price": atm_nvol_price,
        "forward_price": _safe_float(smile.params.forward_price),
        "forward_yield": _safe_float(smile.params.forward_futures_ytm),
        "fv01": fv01,
        "sabr_alpha": _safe_float(smile.params.alpha),
        "sabr_beta": _safe_float(smile.params.beta),
        "sabr_rho": _safe_float(smile.params.rho),
        "sabr_nu": _safe_float(smile.params.nu),
        "time_to_expiry": _safe_float(smile.params.time_to_expiry),
        "underlying_contract": str(smile.underlying_contract),
        "source": str(smile.source),
        "smile_points": _json_dumps(smile_points_list),
    }


def _fetch_ustf_snapshot_rows(
    *,
    as_of_date: dt.date,
    force_refresh: bool,
) -> list[dict[str, Any]]:
    request_map = _build_ustf_request_map()
    all_symbols = list(request_map.keys())

    mdp = USTFutureOptionMDP(source="USTFO_DUAL-QL", force_refresh=force_refresh)
    smiles = _fetch_bulk_sabr_smiles_batched(
        mdp=mdp,
        globex_symbols=all_symbols,
        as_of_date=as_of_date,
        force_refresh=force_refresh,
    )

    rows: list[dict[str, Any]] = []
    for request_symbol, by_date in smiles.items():
        key = request_map.get(str(request_symbol))
        if key is None:
            continue
        product, expiry_label = key
        smile = by_date.get(as_of_date)
        if smile is None:
            continue
        rows.append(
            _build_ustf_snapshot_row(
                as_of_date=as_of_date,
                product=product,
                expiry_label=expiry_label,
                expiry_days_requested=ROLLING_EXPIRIES[expiry_label],
                smile=smile,
            )
        )
    return sorted(rows, key=lambda r: (r["product"], r["expiry_label"]))


# ---------------------------------------------------------------------------
# Swaption Snapshot Fetching (MONKEYCUBE)
# ---------------------------------------------------------------------------

def _fetch_swaption_snapshot_rows(
    *,
    as_of_date: dt.date,
    curve_name: str,
    force_refresh: bool,
) -> list[dict[str, Any]]:
    mdp = IRSwaptionMDP(
        source="MONKEYCUBE-QL",
        curve_source="ERIS_EOD_LIVE-QL_BASIC",
        data_dir=MONKEYCUBE_DATA_DIR,
        force_refresh=force_refresh,
    )
    mdp.get_data(
        {
            "curve_name": curve_name,
            "timestamp": as_of_date,
            "ignore_cache": force_refresh,
        }
    )
    cube = get_cached_cube(curve_name, as_of_date)
    if cube is None:
        _log_status(
            f"No MONKEYCUBE cube found for {as_of_date.isoformat()}",
            level="WARN",
        )
        return []

    rows: list[dict[str, Any]] = []
    for expiry_label in SWAPTION_EXPIRY_LABELS:
        for tail_label in SWAPTION_TAIL_LABELS:
            try:
                params = cube.sabr_params_at(expiry_label, tail_label)
                atm_vol_raw = cube.atm_vol(expiry_label, tail_label)
                atm_nvol_bps = _safe_float(atm_vol_raw * 10_000.0) if atm_vol_raw is not None else None
            except Exception as exc:
                _log_status(
                    f"Failed to fetch swaption {expiry_label}x{tail_label} on "
                    f"{as_of_date.isoformat()}: {exc}",
                    level="WARN",
                )
                continue
            rows.append(
                {
                    "as_of_date": as_of_date,
                    "expiry_label": expiry_label,
                    "tail_label": tail_label,
                    "atm_nvol_bps": atm_nvol_bps,
                    "atmf_rate": _safe_float(params.get("atmf_rate")),
                    "sabr_alpha": _safe_float(params.get("alpha")),
                    "sabr_beta": _safe_float(params.get("beta")),
                    "sabr_rho": _safe_float(params.get("rho")),
                    "sabr_nu": _safe_float(params.get("nu")),
                    "expiry_time": _safe_float(params.get("expiry_time")),
                    "source": "MONKEYCUBE-QL",
                }
            )
    return rows


# ---------------------------------------------------------------------------
# Comparison Rows
# ---------------------------------------------------------------------------

def _build_comparison_rows(
    ustf_rows: list[dict[str, Any]],
    swaption_rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    swaption_lookup: dict[tuple[str, str], float | None] = {}
    for row in swaption_rows:
        swaption_lookup[(row["expiry_label"], row["tail_label"])] = _safe_float(row["atm_nvol_bps"])

    rows: list[dict[str, Any]] = []
    for ustf_row in ustf_rows:
        product = str(ustf_row["product"])
        expiry_label = str(ustf_row["expiry_label"])
        swaption_expiry = USTF_TO_SWAPTION_EXPIRY.get(expiry_label)
        swaption_tail = USTF_SWAP_TAIL.get(product)
        if swaption_expiry is None or swaption_tail is None:
            continue

        ustf_bps = _safe_float(ustf_row.get("atm_nvol_bps"))
        swaption_bps = swaption_lookup.get((swaption_expiry, swaption_tail))
        vol_diff = (
            swaption_bps - ustf_bps
            if swaption_bps is not None and ustf_bps is not None
            else None
        )
        vol_ratio = _safe_ratio(swaption_bps, ustf_bps)

        rows.append(
            {
                "as_of_date": ustf_row["as_of_date"],
                "product": product,
                "expiry_label": expiry_label,
                "ustf_atm_nvol_bps": ustf_bps,
                "swaption_atm_nvol_bps": swaption_bps,
                "vol_diff_bps": vol_diff,
                "vol_ratio": vol_ratio,
                "swaption_expiry_label": swaption_expiry,
                "swaption_tail_label": swaption_tail,
            }
        )
    return rows


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------

def _persist_daily_rows(
    engine: Engine,
    *,
    as_of_date: dt.date,
    ustf_rows: list[dict[str, Any]],
    swaption_rows: list[dict[str, Any]],
    comparison_rows: list[dict[str, Any]],
) -> None:
    delete_ustf_sql = text(f"DELETE FROM {USTF_SNAPSHOTS_TABLE} WHERE as_of_date = :as_of_date")
    delete_swaption_sql = text(f"DELETE FROM {SWAPTION_SNAPSHOTS_TABLE} WHERE as_of_date = :as_of_date")
    delete_comparison_sql = text(f"DELETE FROM {COMPARISON_TABLE} WHERE as_of_date = :as_of_date")

    ustf_upsert_sql = text(
        f"""
        INSERT INTO {USTF_SNAPSHOTS_TABLE} (
            as_of_date, product, expiry_label, expiry_days,
            atm_nvol_bps, atm_nvol_price, forward_price, forward_yield, fv01,
            sabr_alpha, sabr_beta, sabr_rho, sabr_nu, time_to_expiry,
            underlying_contract, source, smile_points
        ) VALUES (
            :as_of_date, :product, :expiry_label, :expiry_days,
            :atm_nvol_bps, :atm_nvol_price, :forward_price, :forward_yield, :fv01,
            :sabr_alpha, :sabr_beta, :sabr_rho, :sabr_nu, :time_to_expiry,
            :underlying_contract, :source, CAST(:smile_points AS JSONB)
        )
        ON CONFLICT (as_of_date, product, expiry_label) DO UPDATE SET
            expiry_days = EXCLUDED.expiry_days,
            atm_nvol_bps = EXCLUDED.atm_nvol_bps,
            atm_nvol_price = EXCLUDED.atm_nvol_price,
            forward_price = EXCLUDED.forward_price,
            forward_yield = EXCLUDED.forward_yield,
            fv01 = EXCLUDED.fv01,
            sabr_alpha = EXCLUDED.sabr_alpha,
            sabr_beta = EXCLUDED.sabr_beta,
            sabr_rho = EXCLUDED.sabr_rho,
            sabr_nu = EXCLUDED.sabr_nu,
            time_to_expiry = EXCLUDED.time_to_expiry,
            underlying_contract = EXCLUDED.underlying_contract,
            source = EXCLUDED.source,
            smile_points = EXCLUDED.smile_points,
            updated_at = NOW()
        """
    )

    swaption_upsert_sql = text(
        f"""
        INSERT INTO {SWAPTION_SNAPSHOTS_TABLE} (
            as_of_date, expiry_label, tail_label,
            atm_nvol_bps, atmf_rate,
            sabr_alpha, sabr_beta, sabr_rho, sabr_nu, expiry_time,
            source
        ) VALUES (
            :as_of_date, :expiry_label, :tail_label,
            :atm_nvol_bps, :atmf_rate,
            :sabr_alpha, :sabr_beta, :sabr_rho, :sabr_nu, :expiry_time,
            :source
        )
        ON CONFLICT (as_of_date, expiry_label, tail_label) DO UPDATE SET
            atm_nvol_bps = EXCLUDED.atm_nvol_bps,
            atmf_rate = EXCLUDED.atmf_rate,
            sabr_alpha = EXCLUDED.sabr_alpha,
            sabr_beta = EXCLUDED.sabr_beta,
            sabr_rho = EXCLUDED.sabr_rho,
            sabr_nu = EXCLUDED.sabr_nu,
            expiry_time = EXCLUDED.expiry_time,
            source = EXCLUDED.source,
            updated_at = NOW()
        """
    )

    comparison_upsert_sql = text(
        f"""
        INSERT INTO {COMPARISON_TABLE} (
            as_of_date, product, expiry_label,
            ustf_atm_nvol_bps, swaption_atm_nvol_bps,
            vol_diff_bps, vol_ratio,
            swaption_expiry_label, swaption_tail_label
        ) VALUES (
            :as_of_date, :product, :expiry_label,
            :ustf_atm_nvol_bps, :swaption_atm_nvol_bps,
            :vol_diff_bps, :vol_ratio,
            :swaption_expiry_label, :swaption_tail_label
        )
        ON CONFLICT (as_of_date, product, expiry_label) DO UPDATE SET
            ustf_atm_nvol_bps = EXCLUDED.ustf_atm_nvol_bps,
            swaption_atm_nvol_bps = EXCLUDED.swaption_atm_nvol_bps,
            vol_diff_bps = EXCLUDED.vol_diff_bps,
            vol_ratio = EXCLUDED.vol_ratio,
            swaption_expiry_label = EXCLUDED.swaption_expiry_label,
            swaption_tail_label = EXCLUDED.swaption_tail_label,
            updated_at = NOW()
        """
    )

    with engine.begin() as conn:
        conn.execute(delete_ustf_sql, {"as_of_date": as_of_date})
        conn.execute(delete_swaption_sql, {"as_of_date": as_of_date})
        conn.execute(delete_comparison_sql, {"as_of_date": as_of_date})
        if ustf_rows:
            conn.execute(ustf_upsert_sql, ustf_rows)
        if swaption_rows:
            conn.execute(swaption_upsert_sql, swaption_rows)
        if comparison_rows:
            conn.execute(comparison_upsert_sql, comparison_rows)


# ---------------------------------------------------------------------------
# Daily Ingest
# ---------------------------------------------------------------------------

def run_daily_ingest(
    engine: Engine,
    *,
    as_of_date: dt.date,
    curve_name: str,
    force_refresh: bool = False,
) -> dict[str, Any]:
    ustf_rows = _fetch_ustf_snapshot_rows(
        as_of_date=as_of_date,
        force_refresh=force_refresh,
    )
    swaption_rows = _fetch_swaption_snapshot_rows(
        as_of_date=as_of_date,
        curve_name=curve_name,
        force_refresh=force_refresh,
    )
    comparison_rows = _build_comparison_rows(ustf_rows, swaption_rows)
    _persist_daily_rows(
        engine,
        as_of_date=as_of_date,
        ustf_rows=ustf_rows,
        swaption_rows=swaption_rows,
        comparison_rows=comparison_rows,
    )
    return {
        "as_of_date": as_of_date.isoformat(),
        "ustf_rows": len(ustf_rows),
        "swaption_rows": len(swaption_rows),
        "comparison_rows": len(comparison_rows),
    }


# ---------------------------------------------------------------------------
# CLI Modes
# ---------------------------------------------------------------------------

def main_range(args: argparse.Namespace) -> None:
    engine = create_db_engine()
    ensure_schema(engine)

    if args.start_date:
        start_date = dt.date.fromisoformat(args.start_date)
    else:
        anchor = (
            dt.date.fromisoformat(args.end_date)
            if args.end_date
            else _previous_business_day(_current_trade_date())
        )
        start_date = (pd.Timestamp(anchor) - pd.tseries.offsets.BDay(args.lookback_business_days)).date()

    end_date = (
        dt.date.fromisoformat(args.end_date)
        if args.end_date
        else _previous_business_day(_current_trade_date())
    )
    dates = _business_dates(start_date, end_date)
    _log_status(
        f"Starting USTF-vs-swaption backfill: {start_date.isoformat()} -> {end_date.isoformat()} "
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
                force_refresh=args.force_refresh,
            )
            elapsed = time.time() - started
            success_count += 1
            _log_status(
                f"{result['as_of_date']}: ustf={result['ustf_rows']} "
                f"swaption={result['swaption_rows']} comparison={result['comparison_rows']} "
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
        f"USTF-vs-swaption backfill complete: success={success_count} failure={failure_count}"
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
        force_refresh=args.force_refresh,
    )
    _log_status(
        f"{result['as_of_date']}: ustf={result['ustf_rows']} "
        f"swaption={result['swaption_rows']} comparison={result['comparison_rows']}"
    )


def main_service(args: argparse.Namespace) -> None:
    engine = create_db_engine()
    ensure_schema(engine)
    interval_seconds = max(int(args.interval_seconds), 30)
    cycle_number = 0
    _log_status(
        f"Starting USTF-vs-swaption service: "
        f"curve={args.curve_name} interval={interval_seconds}s"
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
                force_refresh=args.force_refresh,
            )
            _log_status(
                f"Cycle {cycle_number} [{result['as_of_date']}]: "
                f"ustf={result['ustf_rows']} swaption={result['swaption_rows']} "
                f"comparison={result['comparison_rows']}"
            )
        except Exception as exc:
            _log_status(f"Cycle {cycle_number} failed: {exc}", level="ERROR")

        elapsed = time.time() - started
        sleep_seconds = max(interval_seconds - elapsed, 5)
        _log_status(f"Cycle {cycle_number} finished in {elapsed:.1f}s; sleeping {sleep_seconds:.1f}s")
        time.sleep(sleep_seconds)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Ingest USTF option ATM vol and MONKEYCUBE swaption SABR snapshots.",
    )
    parser.add_argument(
        "--mode",
        choices=("range", "once", "service"),
        required=True,
    )
    parser.add_argument("--curve-name", default=DEFAULT_CURVE_NAME)
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
