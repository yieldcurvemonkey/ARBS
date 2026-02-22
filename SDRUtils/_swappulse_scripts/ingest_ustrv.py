"""
Periodic UST RV ingestion into Postgres.

This script snapshots live UST RV points from MDPs and upserts them into
versioned tables for the dashboard to read quickly.
"""

from __future__ import annotations

import argparse
import csv
import datetime
import io
import math
import os
import time
import uuid
from typing import Any, Callable, Dict, Iterable, Optional, Tuple
from urllib.parse import quote_plus

import numpy as np
import pandas as pd
import pytz
import QuantLib as ql
import requests
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from tqdm import tqdm

from RVUtils.Interpolation.GeneralCurveInterpolator import GeneralCurveInterpolator


POINTS_TABLE = "arbs_ust_rv_points_v1"
INTRADAY_POINTS_TABLE = "arbs_ust_rv_intraday_points_v1"
RUNS_TABLE = "arbs_ust_rv_ingestion_runs_v1"
INTRADAY_SOURCE = "USTS_WEBULL_WSJ_LIVE-RL"

_REQUESTS_TIMEOUT_SECONDS: Optional[float] = None
_REQUESTS_TIMEOUT_PATCHED = False
_REQUESTS_ORIGINAL_REQUEST: Optional[Callable[..., Any]] = None

SCHEMA_SQL = f"""
CREATE TABLE IF NOT EXISTS {POINTS_TABLE} (
    as_of_date DATE NOT NULL,
    curve_name TEXT NOT NULL,
    cusip TEXT NOT NULL,
    oi TEXT,
    ust_label TEXT,
    rank INTEGER,
    ttm NUMERIC,
    mdur NUMERIC,
    ytm NUMERIC,
    mmss NUMERIC,
    clean_price NUMERIC,
    dirty_price NUMERIC,
    coupon NUMERIC,
    carry_bps NUMERIC,
    roll_bps NUMERIC,
    carry_and_roll_bps NUMERIC,
    carry_1m_bps NUMERIC,
    roll_1m_bps NUMERIC,
    carry_and_roll_1m_bps NUMERIC,
    carry_2m_bps NUMERIC,
    roll_2m_bps NUMERIC,
    carry_and_roll_2m_bps NUMERIC,
    carry_3m_bps NUMERIC,
    roll_3m_bps NUMERIC,
    carry_and_roll_3m_bps NUMERIC,
    carry_6m_bps NUMERIC,
    roll_6m_bps NUMERIC,
    carry_and_roll_6m_bps NUMERIC,
    swap_carry_bps NUMERIC,
    swap_roll_bps NUMERIC,
    swap_carry_and_roll_bps NUMERIC,
    swap_carry_1m_bps NUMERIC,
    swap_roll_1m_bps NUMERIC,
    swap_carry_and_roll_1m_bps NUMERIC,
    swap_carry_2m_bps NUMERIC,
    swap_roll_2m_bps NUMERIC,
    swap_carry_and_roll_2m_bps NUMERIC,
    swap_carry_3m_bps NUMERIC,
    swap_roll_3m_bps NUMERIC,
    swap_carry_and_roll_3m_bps NUMERIC,
    swap_carry_6m_bps NUMERIC,
    swap_roll_6m_bps NUMERIC,
    swap_carry_and_roll_6m_bps NUMERIC,
    mmss_carry_bps NUMERIC,
    mmss_roll_bps NUMERIC,
    mmss_carry_and_roll_bps NUMERIC,
    mmss_carry_1m_bps NUMERIC,
    mmss_roll_1m_bps NUMERIC,
    mmss_carry_and_roll_1m_bps NUMERIC,
    mmss_carry_2m_bps NUMERIC,
    mmss_roll_2m_bps NUMERIC,
    mmss_carry_and_roll_2m_bps NUMERIC,
    mmss_carry_3m_bps NUMERIC,
    mmss_roll_3m_bps NUMERIC,
    mmss_carry_and_roll_3m_bps NUMERIC,
    mmss_carry_6m_bps NUMERIC,
    mmss_roll_6m_bps NUMERIC,
    mmss_carry_and_roll_6m_bps NUMERIC,
    issue_date DATE,
    maturity_date DATE,
    market_timestamp TIMESTAMPTZ,
    snapshot_ts TIMESTAMPTZ NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (as_of_date, curve_name, cusip)
);

CREATE TABLE IF NOT EXISTS {INTRADAY_POINTS_TABLE} (
    as_of_date DATE NOT NULL,
    curve_name TEXT NOT NULL,
    cusip TEXT NOT NULL,
    oi TEXT,
    ust_label TEXT,
    rank INTEGER,
    ttm NUMERIC,
    mdur NUMERIC,
    ytm NUMERIC,
    mmss NUMERIC,
    clean_price NUMERIC,
    dirty_price NUMERIC,
    coupon NUMERIC,
    carry_bps NUMERIC,
    roll_bps NUMERIC,
    carry_and_roll_bps NUMERIC,
    carry_1m_bps NUMERIC,
    roll_1m_bps NUMERIC,
    carry_and_roll_1m_bps NUMERIC,
    carry_2m_bps NUMERIC,
    roll_2m_bps NUMERIC,
    carry_and_roll_2m_bps NUMERIC,
    carry_3m_bps NUMERIC,
    roll_3m_bps NUMERIC,
    carry_and_roll_3m_bps NUMERIC,
    carry_6m_bps NUMERIC,
    roll_6m_bps NUMERIC,
    carry_and_roll_6m_bps NUMERIC,
    swap_carry_bps NUMERIC,
    swap_roll_bps NUMERIC,
    swap_carry_and_roll_bps NUMERIC,
    swap_carry_1m_bps NUMERIC,
    swap_roll_1m_bps NUMERIC,
    swap_carry_and_roll_1m_bps NUMERIC,
    swap_carry_2m_bps NUMERIC,
    swap_roll_2m_bps NUMERIC,
    swap_carry_and_roll_2m_bps NUMERIC,
    swap_carry_3m_bps NUMERIC,
    swap_roll_3m_bps NUMERIC,
    swap_carry_and_roll_3m_bps NUMERIC,
    swap_carry_6m_bps NUMERIC,
    swap_roll_6m_bps NUMERIC,
    swap_carry_and_roll_6m_bps NUMERIC,
    mmss_carry_bps NUMERIC,
    mmss_roll_bps NUMERIC,
    mmss_carry_and_roll_bps NUMERIC,
    mmss_carry_1m_bps NUMERIC,
    mmss_roll_1m_bps NUMERIC,
    mmss_carry_and_roll_1m_bps NUMERIC,
    mmss_carry_2m_bps NUMERIC,
    mmss_roll_2m_bps NUMERIC,
    mmss_carry_and_roll_2m_bps NUMERIC,
    mmss_carry_3m_bps NUMERIC,
    mmss_roll_3m_bps NUMERIC,
    mmss_carry_and_roll_3m_bps NUMERIC,
    mmss_carry_6m_bps NUMERIC,
    mmss_roll_6m_bps NUMERIC,
    mmss_carry_and_roll_6m_bps NUMERIC,
    issue_date DATE,
    maturity_date DATE,
    market_timestamp TIMESTAMPTZ NOT NULL,
    snapshot_ts TIMESTAMPTZ NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (curve_name, market_timestamp, cusip)
);

CREATE TABLE IF NOT EXISTS {RUNS_TABLE} (
    run_id BIGSERIAL PRIMARY KEY,
    ingestion_started_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    as_of_date DATE NOT NULL,
    curve_name TEXT NOT NULL,
    snapshot_ts TIMESTAMPTZ NOT NULL,
    points_written INTEGER,
    notes TEXT
);

CREATE INDEX IF NOT EXISTS idx_ust_rv_points_curve_date ON {POINTS_TABLE}(curve_name, as_of_date);
CREATE INDEX IF NOT EXISTS idx_ust_rv_points_snapshot ON {POINTS_TABLE}(snapshot_ts DESC);
CREATE INDEX IF NOT EXISTS idx_ust_rv_intraday_curve_date ON {INTRADAY_POINTS_TABLE}(curve_name, as_of_date);
CREATE INDEX IF NOT EXISTS idx_ust_rv_intraday_curve_ts ON {INTRADAY_POINTS_TABLE}(curve_name, market_timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_ust_rv_intraday_cusip_ts ON {INTRADAY_POINTS_TABLE}(cusip, market_timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_ust_rv_runs_date ON {RUNS_TABLE}(as_of_date, ingestion_started_at DESC);
"""

CARRY_ROLL_HORIZONS: tuple[tuple[str, str, float], ...] = (
    ("1m", "1M", 1.0 / 12.0),
    ("2m", "2M", 2.0 / 12.0),
    ("3m", "3M", 3.0 / 12.0),
    ("6m", "6M", 6.0 / 12.0),
)

CARRY_BPS_HORIZON_COLUMNS: tuple[str, ...] = tuple(
    f"carry_{label}_bps" for label, _, _ in CARRY_ROLL_HORIZONS
)
ROLL_BPS_HORIZON_COLUMNS: tuple[str, ...] = tuple(
    f"roll_{label}_bps" for label, _, _ in CARRY_ROLL_HORIZONS
)
CARRY_AND_ROLL_BPS_HORIZON_COLUMNS: tuple[str, ...] = tuple(
    f"carry_and_roll_{label}_bps" for label, _, _ in CARRY_ROLL_HORIZONS
)

SWAP_CARRY_BPS_HORIZON_COLUMNS: tuple[str, ...] = tuple(
    f"swap_carry_{label}_bps" for label, _, _ in CARRY_ROLL_HORIZONS
)
SWAP_ROLL_BPS_HORIZON_COLUMNS: tuple[str, ...] = tuple(
    f"swap_roll_{label}_bps" for label, _, _ in CARRY_ROLL_HORIZONS
)
SWAP_CARRY_AND_ROLL_BPS_HORIZON_COLUMNS: tuple[str, ...] = tuple(
    f"swap_carry_and_roll_{label}_bps" for label, _, _ in CARRY_ROLL_HORIZONS
)

MMSS_CARRY_BPS_HORIZON_COLUMNS: tuple[str, ...] = tuple(
    f"mmss_carry_{label}_bps" for label, _, _ in CARRY_ROLL_HORIZONS
)
MMSS_ROLL_BPS_HORIZON_COLUMNS: tuple[str, ...] = tuple(
    f"mmss_roll_{label}_bps" for label, _, _ in CARRY_ROLL_HORIZONS
)
MMSS_CARRY_AND_ROLL_BPS_HORIZON_COLUMNS: tuple[str, ...] = tuple(
    f"mmss_carry_and_roll_{label}_bps" for label, _, _ in CARRY_ROLL_HORIZONS
)

SWAP_CARRY_ROLL_ALIAS_COLUMNS: tuple[str, ...] = (
    "swap_carry_bps",
    "swap_roll_bps",
    "swap_carry_and_roll_bps",
)
MMSS_CARRY_ROLL_ALIAS_COLUMNS: tuple[str, ...] = (
    "mmss_carry_bps",
    "mmss_roll_bps",
    "mmss_carry_and_roll_bps",
)

NUMERIC_COLUMNS: tuple[str, ...] = (
    "rank",
    "ttm",
    "mdur",
    "ytm",
    "mmss",
    "clean_price",
    "dirty_price",
    "coupon",
    "carry_bps",
    "roll_bps",
    "carry_and_roll_bps",
    *CARRY_BPS_HORIZON_COLUMNS,
    *ROLL_BPS_HORIZON_COLUMNS,
    *CARRY_AND_ROLL_BPS_HORIZON_COLUMNS,
    *SWAP_CARRY_ROLL_ALIAS_COLUMNS,
    *SWAP_CARRY_BPS_HORIZON_COLUMNS,
    *SWAP_ROLL_BPS_HORIZON_COLUMNS,
    *SWAP_CARRY_AND_ROLL_BPS_HORIZON_COLUMNS,
    *MMSS_CARRY_ROLL_ALIAS_COLUMNS,
    *MMSS_CARRY_BPS_HORIZON_COLUMNS,
    *MMSS_ROLL_BPS_HORIZON_COLUMNS,
    *MMSS_CARRY_AND_ROLL_BPS_HORIZON_COLUMNS,
)

POINT_DATA_COLUMNS: tuple[str, ...] = (
    "oi",
    "ust_label",
    "rank",
    "ttm",
    "mdur",
    "ytm",
    "mmss",
    "clean_price",
    "dirty_price",
    "coupon",
    "carry_bps",
    "roll_bps",
    "carry_and_roll_bps",
    *CARRY_BPS_HORIZON_COLUMNS,
    *ROLL_BPS_HORIZON_COLUMNS,
    *CARRY_AND_ROLL_BPS_HORIZON_COLUMNS,
    *SWAP_CARRY_ROLL_ALIAS_COLUMNS,
    *SWAP_CARRY_BPS_HORIZON_COLUMNS,
    *SWAP_ROLL_BPS_HORIZON_COLUMNS,
    *SWAP_CARRY_AND_ROLL_BPS_HORIZON_COLUMNS,
    *MMSS_CARRY_ROLL_ALIAS_COLUMNS,
    *MMSS_CARRY_BPS_HORIZON_COLUMNS,
    *MMSS_ROLL_BPS_HORIZON_COLUMNS,
    *MMSS_CARRY_AND_ROLL_BPS_HORIZON_COLUMNS,
    "issue_date",
    "maturity_date",
    "market_timestamp",
)


def _load_sofr_fixing_pct(as_of_date: datetime.date) -> Optional[float]:
    from MDP.IRSwaps.fixings_cache.fixings_cache import _fetch_fixings

    try:
        fixings = _fetch_fixings(as_of_date=as_of_date, curve_name="USD-SOFR-1D")
    except Exception:
        return None
    if fixings is None:
        return None

    try:
        s = pd.Series(fixings).copy()
    except Exception:
        return None
    if s.empty:
        return None

    idx = pd.to_datetime(s.index, errors="coerce")
    val = pd.to_numeric(s, errors="coerce")
    tmp = pd.DataFrame({"fixing": val}, index=idx)
    tmp = tmp[~tmp.index.isna()]
    tmp = tmp.dropna(subset=["fixing"])
    tmp = tmp[tmp.index.date < as_of_date].sort_index()
    if tmp.empty:
        return None

    sofr_pct = float(tmp["fixing"].iloc[-1])
    if not np.isfinite(sofr_pct):
        return None

    # Fixings are usually decimals (e.g. 0.0435). Convert to percent if needed.
    if abs(sofr_pct) <= 1.0:
        sofr_pct *= 100.0
    return sofr_pct


def _fit_roll_spline(ttm: np.ndarray, ytm: np.ndarray) -> Optional[Callable[[np.ndarray], np.ndarray]]:
    if ttm.size == 0 or ytm.size == 0:
        return None

    df = pd.DataFrame({"ttm": ttm, "ytm": ytm})
    df = df.replace([np.inf, -np.inf], np.nan).dropna(subset=["ttm", "ytm"])
    if df.empty:
        return None

    dedup = df.groupby("ttm", as_index=False)["ytm"].mean().sort_values(by="ttm")
    if len(dedup) < 4:
        return None

    x = dedup["ttm"].to_numpy(dtype=float)
    y = dedup["ytm"].to_numpy(dtype=float)
    degree = max(1, min(3, len(x) - 1))
    try:
        interp = GeneralCurveInterpolator(x=x, y=y)
        return interp.b_spline1_interpolation(k=degree, return_func=True)
    except Exception:
        return None


def _coerce_date(val: Any) -> Optional[datetime.date]:
    if val is None:
        return None
    if isinstance(val, datetime.datetime):
        return val.date()
    if isinstance(val, datetime.date):
        return val
    if isinstance(val, ql.Date):
        return datetime.date(val.year(), val.month(), val.dayOfMonth())
    try:
        year = getattr(val, "year", None)
        month = getattr(val, "month", None)
        day = getattr(val, "day", None)
        if callable(year):
            year = year()
        if callable(month):
            month = month()
        if callable(day):
            day = day()
        if year is not None and month is not None and day is not None:
            return datetime.date(int(year), int(month), int(day))
    except Exception:
        pass
    try:
        return pd.Timestamp(val).date()
    except Exception:
        return None


def _advance_horizon_date(
    *,
    as_of_date: datetime.date,
    pricer: Any = None,
    horizon_tenor: str = "3M",
) -> datetime.date:
    if pricer is not None:
        try:
            adv = pricer.calendar_advance(as_of_date, horizon_tenor)
            d = _coerce_date(adv)
            if d is not None:
                return d
        except Exception:
            pass

    try:
        cal = ql.UnitedStates(ql.UnitedStates.GovernmentBond)
        qd = _to_ql_date(as_of_date)
        adv = cal.advance(qd, ql.Period(horizon_tenor), ql.ModifiedFollowing)
        return datetime.date(adv.year(), adv.month(), adv.dayOfMonth())
    except Exception:
        return as_of_date + datetime.timedelta(days=91)


def _to_ql_date(d: datetime.date) -> ql.Date:
    return ql.Date(d.day, d.month, d.year)


def _normalize_coupon_pct(cpn_raw: Optional[float]) -> Optional[float]:
    if cpn_raw is None or not np.isfinite(cpn_raw):
        return None
    cpn = float(cpn_raw)
    # Support either decimal (0.0475) or percent (4.75) coupon conventions.
    if abs(cpn) <= 1.0:
        cpn *= 100.0
    return cpn


def _coupon_accrual_price_per_100(
    *,
    issue_date: Optional[datetime.date],
    maturity_date: Optional[datetime.date],
    coupon_pct: Optional[float],
    start_date: datetime.date,
    end_date: datetime.date,
) -> Optional[float]:
    if end_date <= start_date:
        return 0.0

    cpn = _normalize_coupon_pct(coupon_pct)
    if issue_date is not None and maturity_date is not None and cpn is not None:
        try:
            cal = ql.UnitedStates(ql.UnitedStates.GovernmentBond)
            sched = ql.Schedule(
                _to_ql_date(issue_date),
                _to_ql_date(maturity_date),
                ql.Period(6, ql.Months),
                cal,
                ql.ModifiedFollowing,
                ql.ModifiedFollowing,
                ql.DateGeneration.Backward,
                False,
            )
            qs = _to_ql_date(start_date)
            qe = _to_ql_date(end_date)
            total = 0.0
            cpn_per_period = cpn / 2.0

            for i in range(len(sched) - 1):
                a0 = sched[i]
                a1 = sched[i + 1]
                if a1 <= qs or a0 >= qe:
                    continue
                ov_start = a0 if a0 > qs else qs
                ov_end = a1 if a1 < qe else qe
                ov_days = int(ov_end - ov_start)
                period_days = int(a1 - a0)
                if ov_days <= 0 or period_days <= 0:
                    continue
                total += cpn_per_period * (ov_days / period_days)

            if total > 0.0:
                return float(total)
        except Exception:
            pass

    # Fallback: annual coupon * Act/365 over horizon (price points per 100 face).
    if cpn is None:
        return None
    days = max((end_date - start_date).days, 0)
    return float(cpn) * (days / 365.0)


def _compute_carry_roll_columns(
    df: pd.DataFrame,
    *,
    as_of_date: datetime.date,
    pricers: Dict[str, Any],
) -> pd.DataFrame:
    out = df.copy()
    metric_cols = [
        "carry_bps",
        "roll_bps",
        "carry_and_roll_bps",
        *CARRY_BPS_HORIZON_COLUMNS,
        *ROLL_BPS_HORIZON_COLUMNS,
        *CARRY_AND_ROLL_BPS_HORIZON_COLUMNS,
    ]
    for col in metric_cols:
        out[col] = np.nan
    if out.empty:
        return out

    out = _ensure_numeric_columns(out, ["ttm", "ytm", "coupon", "dirty_price", "mdur"])

    sofr_pct = _load_sofr_fixing_pct(as_of_date=as_of_date)
    if sofr_pct is not None:
        # Carry in yield bps:
        # carry_price = coupon_accrual(Act/Act) - financing_cost(Act/360)
        # carry_bps = carry_price / DV01, with DV01 ~= ModDur * Dirty / 10000 (per 100 face)
        sofr_dec = float(sofr_pct) / 100.0
        horizon_defaults: dict[str, datetime.date] = {
            label: _advance_horizon_date(as_of_date=as_of_date, horizon_tenor=tenor)
            for label, tenor, _ in CARRY_ROLL_HORIZONS
        }
        carry_by_horizon: dict[str, list[float]] = {
            label: [] for label, _, _ in CARRY_ROLL_HORIZONS
        }

        for _, row in out.iterrows():
            cusip = str(row.get("cusip") or "")
            pricer = pricers.get(cusip)

            dirty0 = _safe_float(row.get("dirty_price"))
            if dirty0 is None and pricer is not None and hasattr(pricer, "dirty_price"):
                dirty0 = _safe_float(pricer.dirty_price())

            mdur = _safe_float(row.get("mdur"))
            if mdur is None and pricer is not None and hasattr(pricer, "mod_duration"):
                mdur = _safe_float(pricer.mod_duration())

            if dirty0 is None or mdur is None or dirty0 <= 0 or mdur <= 0:
                for label, _, _ in CARRY_ROLL_HORIZONS:
                    carry_by_horizon[label].append(np.nan)
                continue

            issue_date = _coerce_date(row.get("issue_date"))
            maturity_date = _coerce_date(row.get("maturity_date"))
            cpn = _safe_float(row.get("coupon"))

            if (issue_date is None or maturity_date is None or cpn is None) and pricer is not None:
                try:
                    if issue_date is None:
                        issue_date = _coerce_date(pricer.issue_date())
                    if maturity_date is None:
                        maturity_date = _coerce_date(pricer.maturity_date())
                    if cpn is None:
                        cpn = _safe_float(pricer.coupon())
                except Exception:
                    pass

            dv01 = mdur * dirty0 / 10000.0
            if dv01 <= 0 or not np.isfinite(dv01):
                for label, _, _ in CARRY_ROLL_HORIZONS:
                    carry_by_horizon[label].append(np.nan)
                continue

            for label, tenor, _ in CARRY_ROLL_HORIZONS:
                horizon_date = horizon_defaults[label]
                if pricer is not None:
                    horizon_date = _advance_horizon_date(
                        as_of_date=as_of_date,
                        pricer=pricer,
                        horizon_tenor=tenor,
                    )

                if horizon_date <= as_of_date:
                    carry_by_horizon[label].append(np.nan)
                    continue

                horizon_days = max((horizon_date - as_of_date).days, 1)
                coupon_accrual = _coupon_accrual_price_per_100(
                    issue_date=issue_date,
                    maturity_date=maturity_date,
                    coupon_pct=cpn,
                    start_date=as_of_date,
                    end_date=horizon_date,
                )

                if coupon_accrual is None:
                    carry_by_horizon[label].append(np.nan)
                    continue

                financing_cost = dirty0 * sofr_dec * (horizon_days / 360.0)
                carry_price = coupon_accrual - financing_cost
                carry_bps = carry_price / dv01
                if not np.isfinite(carry_bps):
                    carry_bps = np.nan
                carry_by_horizon[label].append(float(carry_bps))

        for label, _, _ in CARRY_ROLL_HORIZONS:
            out[f"carry_{label}_bps"] = pd.Series(carry_by_horizon[label], index=out.index)

    ttm_arr = out["ttm"].to_numpy(dtype=float)
    ytm_arr = out["ytm"].to_numpy(dtype=float)
    roll_func = _fit_roll_spline(ttm=ttm_arr, ytm=ytm_arr)
    if roll_func is not None:
        fit_df = (
            out[["ttm", "ytm"]]
            .replace([np.inf, -np.inf], np.nan)
            .dropna(subset=["ttm", "ytm"])
            .groupby("ttm", as_index=False)["ytm"]
            .mean()
            .sort_values(by="ttm")
        )
        if not fit_df.empty:
            fit_min = float(fit_df["ttm"].iloc[0])
            fit_max = float(fit_df["ttm"].iloc[-1])
            for label, _, horizon_years in CARRY_ROLL_HORIZONS:
                shifted_ttm = out["ttm"] - horizon_years
                valid = (
                    out["ttm"].notna()
                    & out["ytm"].notna()
                    & shifted_ttm.notna()
                    & (shifted_ttm >= fit_min)
                    & (shifted_ttm <= fit_max)
                )
                if not bool(valid.any()):
                    continue
                x_now = out.loc[valid, "ttm"].to_numpy(dtype=float)
                x_prev = shifted_ttm.loc[valid].to_numpy(dtype=float)
                try:
                    y_now = np.asarray(roll_func(x_now), dtype=float)
                    y_prev = np.asarray(roll_func(x_prev), dtype=float)
                    roll_bps = (y_now - y_prev) * 100.0
                    roll_bps[~np.isfinite(roll_bps)] = np.nan
                    out.loc[valid, f"roll_{label}_bps"] = roll_bps
                except Exception:
                    pass

    for label, _, _ in CARRY_ROLL_HORIZONS:
        carry_col = f"carry_{label}_bps"
        roll_col = f"roll_{label}_bps"
        carry_roll_col = f"carry_and_roll_{label}_bps"
        out[carry_roll_col] = out[carry_col] + out[roll_col]

    # Backward-compatible aliases for existing consumers (3m horizon).
    out["carry_bps"] = out["carry_3m_bps"]
    out["roll_bps"] = out["roll_3m_bps"]
    out["carry_and_roll_bps"] = out["carry_and_roll_3m_bps"]
    return out


def _safe_float(x: Any) -> Optional[float]:
    try:
        y = float(x)
    except Exception:
        return None
    if np.isnan(y) or np.isinf(y):
        return None
    return y


def _to_iso(val: Any):
    if isinstance(val, (datetime.datetime, datetime.date)):
        return val.isoformat()
    return val


def _to_utc_timestamp(val: Any) -> Optional[pd.Timestamp]:
    if val is None:
        return None
    try:
        ts = pd.Timestamp(val)
    except Exception:
        return None
    if ts.tzinfo is None:
        return ts.tz_localize("UTC")
    return ts.tz_convert("UTC")


def _adjust_to_business_day(d: datetime.date) -> datetime.date:
    cal = ql.UnitedStates(ql.UnitedStates.GovernmentBond)
    probe = ql.Date(d.day, d.month, d.year)
    while not cal.isBusinessDay(probe):
        probe = cal.advance(probe, ql.Period(-1, ql.Days))
    return datetime.date(probe.year(), probe.month(), probe.dayOfMonth())


def _ensure_numeric_columns(df: pd.DataFrame, cols: Iterable[str]) -> pd.DataFrame:
    out = df.copy()
    for c in cols:
        if c in out.columns:
            out[c] = pd.to_numeric(out[c], errors="coerce")
    return out


def _extract_cusip_from_query_name(text: str) -> Optional[str]:
    import re

    match = re.search(r"\b[0-9A-Z]{9}\b", str(text or "").upper())
    return match.group(0) if match else None


def get_db_connection_string(override: Optional[str] = None) -> str:
    """
    Resolve Postgres connection string.

    Precedence:
      1) explicit override (CLI --database-url)
      2) SWAPPULSE_DATABASE_URL
      3) DATABASE_URL
      4) SWAPPULSE_DB_* component variables
      5) MVP hardcoded fallback defaults
    """
    if override and str(override).strip():
        conn_string = str(override).strip()
    else:
        conn_string = ""
        for key in ("SWAPPULSE_DATABASE_URL", "DATABASE_URL"):
            raw = os.getenv(key)
            if raw and raw.strip():
                conn_string = raw.strip()
                break

    if conn_string:
        if conn_string.startswith("postgres://"):
            conn_string = "postgresql://" + conn_string[len("postgres://") :]
        return conn_string

    host = os.getenv("SWAPPULSE_DB_HOST", "aws-0-us-east-1.pooler.supabase.com").strip()
    port = os.getenv("SWAPPULSE_DB_PORT", "6543").strip()
    dbname = os.getenv("SWAPPULSE_DB_NAME", "postgres").strip()
    user = os.getenv("SWAPPULSE_DB_USER", "postgres.rdobtpugtnmefxplgwyp").strip()
    password = os.getenv("SWAPPULSE_DB_PASSWORD", "0rbZUh8y0Fsvdlry").strip()
    sslmode = os.getenv("SWAPPULSE_DB_SSLMODE", "").strip()

    auth_user = quote_plus(user)
    auth_password = quote_plus(password)
    conn_string = f"postgresql://{auth_user}:{auth_password}@{host}:{port}/{dbname}"
    if sslmode:
        conn_string += f"?sslmode={sslmode}"
    return conn_string


def create_db_engine(connection_string: Optional[str] = None) -> Engine:
    conn_string = get_db_connection_string(connection_string)
    return create_engine(
        conn_string,
        pool_size=5,
        max_overflow=10,
        pool_timeout=30,
        pool_recycle=1800,
        pool_pre_ping=True,
    )


def ensure_schema(engine: Engine) -> None:
    with engine.begin() as conn:
        if engine.dialect.name == "postgresql":
            conn.execute(text("SET LOCAL statement_timeout = 0"))
        for statement in SCHEMA_SQL.split(";"):
            stmt = statement.strip()
            if stmt:
                conn.execute(text(stmt))
        for table_name in (POINTS_TABLE, INTRADAY_POINTS_TABLE):
            for col in (
                "carry_bps",
                "roll_bps",
                "carry_and_roll_bps",
                *CARRY_BPS_HORIZON_COLUMNS,
                *ROLL_BPS_HORIZON_COLUMNS,
                *CARRY_AND_ROLL_BPS_HORIZON_COLUMNS,
                *SWAP_CARRY_ROLL_ALIAS_COLUMNS,
                *SWAP_CARRY_BPS_HORIZON_COLUMNS,
                *SWAP_ROLL_BPS_HORIZON_COLUMNS,
                *SWAP_CARRY_AND_ROLL_BPS_HORIZON_COLUMNS,
                *MMSS_CARRY_ROLL_ALIAS_COLUMNS,
                *MMSS_CARRY_BPS_HORIZON_COLUMNS,
                *MMSS_ROLL_BPS_HORIZON_COLUMNS,
                *MMSS_CARRY_AND_ROLL_BPS_HORIZON_COLUMNS,
            ):
                conn.execute(
                    text(
                        f"""
                        ALTER TABLE {table_name}
                        ADD COLUMN IF NOT EXISTS {col} NUMERIC
                        """
                    )
                )


def _pythonify(val: Any) -> Any:
    if val is None:
        return None
    if isinstance(val, (list, tuple, set)):
        return [_pythonify(v) for v in val]
    if isinstance(val, dict):
        return {k: _pythonify(v) for k, v in val.items()}
    if isinstance(val, np.ndarray):
        if val.size == 0:
            return None
        return [_pythonify(v) for v in val.tolist()]
    try:
        if pd.isna(val):
            return None
    except Exception:
        pass
    if isinstance(val, pd.Timestamp):
        return val.isoformat()
    if hasattr(val, "item"):
        try:
            return val.item()
        except Exception:
            pass
    return val


def _coerce_copy_cell(val: Any) -> Any:
    py = _pythonify(val)
    if py is None:
        return r"\N"
    if isinstance(py, (datetime.date, datetime.datetime)):
        return py.isoformat()
    return py


def _upsert_dataframe_postgres_copy(
    df: pd.DataFrame,
    engine: Engine,
    *,
    table_name: str,
    conflict_cols: Iterable[str],
    update_cols: Iterable[str],
    batch_size: int,
    progress_desc: Optional[str],
) -> int:
    total = int(len(df))
    if total == 0:
        return 0

    all_cols = list(df.columns)
    col_list = ", ".join(all_cols)
    conflict_clause = ", ".join(conflict_cols)
    updates = ", ".join([f"{c} = EXCLUDED.{c}" for c in update_cols])
    temp_table = f"{table_name}_tmp_{uuid.uuid4().hex[:12]}"
    desc = progress_desc or f"Writing {table_name} (COPY)"

    insert_sql = f"""
        INSERT INTO {table_name} ({col_list})
        SELECT {col_list}
        FROM {temp_table}
        ON CONFLICT ({conflict_clause}) DO UPDATE
        SET {updates},
            updated_at = NOW()
    """
    copy_sql = f"COPY {temp_table} ({col_list}) FROM STDIN WITH (FORMAT csv, NULL '\\N')"

    raw_conn = engine.raw_connection()
    try:
        cur = raw_conn.cursor()
        try:
            cur.execute("SET LOCAL statement_timeout = 0")
            cur.execute("SET LOCAL synchronous_commit = OFF")
            cur.execute(f"CREATE TEMP TABLE {temp_table} (LIKE {table_name} INCLUDING DEFAULTS) ON COMMIT DROP")

            for start_idx in tqdm(range(0, total, batch_size), desc=desc, unit="batch"):
                stop_idx = min(start_idx + batch_size, total)
                view = df.iloc[start_idx:stop_idx]

                buffer = io.StringIO()
                writer = csv.writer(buffer, lineterminator="\n")
                for row in view.itertuples(index=False, name=None):
                    writer.writerow([_coerce_copy_cell(v) for v in row])
                buffer.seek(0)
                cur.copy_expert(copy_sql, buffer)

            merge_start = time.monotonic()
            print(
                f"{desc}: staged_rows={total}. "
                f"Merging temp table into {table_name}..."
            )
            cur.execute(insert_sql)
            merge_elapsed = time.monotonic() - merge_start
            print(f"{desc}: merge complete in {merge_elapsed:.1f}s")
            raw_conn.commit()
        finally:
            cur.close()
    except Exception:
        raw_conn.rollback()
        raise
    finally:
        raw_conn.close()

    return total


def upsert_dataframe(
    df: pd.DataFrame,
    engine: Engine,
    table_name: str,
    conflict_cols: Iterable[str],
    update_cols: Iterable[str],
    batch_size: int = 5000,
    progress_desc: Optional[str] = None,
) -> int:
    if df.empty:
        return 0

    if batch_size <= 0:
        raise ValueError(f"batch_size must be > 0, got {batch_size}")

    if engine.dialect.name == "postgresql":
        try:
            return _upsert_dataframe_postgres_copy(
                df,
                engine,
                table_name=table_name,
                conflict_cols=conflict_cols,
                update_cols=update_cols,
                batch_size=batch_size,
                progress_desc=progress_desc,
            )
        except Exception as exc:
            print(
                "COPY upsert path failed; falling back to executemany path. "
                f"reason={type(exc).__name__}: {exc}"
            )

    records = df.to_dict(orient="records")
    records = [{k: _pythonify(v) for k, v in rec.items()} for rec in records]
    all_cols = list(records[0].keys())

    col_list = ", ".join(all_cols)
    placeholders = ", ".join([f":{c}" for c in all_cols])
    updates = ", ".join([f"{c} = EXCLUDED.{c}" for c in update_cols])
    conflict_clause = ", ".join(conflict_cols)

    sql = text(
        f"""
        INSERT INTO {table_name} ({col_list})
        VALUES ({placeholders})
        ON CONFLICT ({conflict_clause}) DO UPDATE
        SET {updates},
            updated_at = NOW()
        """
    )

    total = len(records)
    desc = progress_desc or f"Writing {table_name}"
    with engine.begin() as conn:
        for start_idx in tqdm(range(0, total, batch_size), desc=desc, unit="batch"):
            batch = records[start_idx : start_idx + batch_size]
            conn.execute(sql, batch)

    return total


def record_ingestion_run(
    engine: Engine,
    *,
    as_of_date: datetime.date,
    curve_name: str,
    snapshot_ts: pd.Timestamp,
    points_written: int,
    notes: Optional[str] = None,
) -> None:
    with engine.begin() as conn:
        conn.execute(
            text(
                f"""
                INSERT INTO {RUNS_TABLE} (
                    as_of_date,
                    curve_name,
                    snapshot_ts,
                    points_written,
                    notes
                )
                VALUES (:as_of_date, :curve_name, :snapshot_ts, :points_written, :notes)
                """
            ),
            dict(
                as_of_date=as_of_date,
                curve_name=curve_name,
                snapshot_ts=snapshot_ts.to_pydatetime(),
                points_written=points_written,
                notes=notes,
            ),
        )


def delete_stale_points(
    engine: Engine,
    *,
    as_of_date: datetime.date,
    curve_name: str,
    active_cusips: list[str],
) -> int:
    if not active_cusips:
        with engine.begin() as conn:
            res = conn.execute(
                text(
                    f"""
                    DELETE FROM {POINTS_TABLE}
                    WHERE as_of_date = :as_of_date
                      AND curve_name = :curve_name
                    """
                ),
                dict(as_of_date=as_of_date, curve_name=curve_name),
            )
        return int(res.rowcount or 0)

    with engine.begin() as conn:
        res = conn.execute(
            text(
                f"""
                DELETE FROM {POINTS_TABLE}
                WHERE as_of_date = :as_of_date
                  AND curve_name = :curve_name
                  AND NOT (cusip = ANY(:active_cusips))
                """
            ),
            dict(as_of_date=as_of_date, curve_name=curve_name, active_cusips=active_cusips),
        )
    return int(res.rowcount or 0)


def build_points_dataframe(
    *,
    as_of_date: datetime.date,
    curve_name: str,
    min_ttm: float,
    include_mmss: bool,
    usts_source: str = "USTS_FEDINVEST_WSJ_LIVE-QL",
    pricing_timestamp: Optional[datetime.date | datetime.datetime | str] = None,
) -> pd.DataFrame:
    from MDP.FixedRateBonds.FixedRateBondsMDP import FixedRateBondsMDP
    from MDP.IRSwaps.IRSwapsMDP import IRSwapsMDP
    from Query.IRSwaps.IRSwapQuery import IRSwapQuery
    from Query.IRSwaps.IRSwapValue import IRSwapValue
    from TB.FixedRateBondsTB import FixedRateBondsTB
    from TB.IRSwapsTB import IRSwapsTB
    from TB.TimeseriesBuilder import TimeseriesBuilder

    usts_mdp = FixedRateBondsMDP(source=usts_source)
    ref_df = usts_mdp.get_bond_reference_data(as_of_date=as_of_date).copy()
    ref_df = ref_df.drop(columns=["record_date"], errors="ignore").rename(columns={"label": "ust_label"})
    ref_df = _ensure_numeric_columns(ref_df, ["ttm", "rank", "cpn"])
    ref_df = ref_df[ref_df["ttm"] >= min_ttm].copy()
    ref_df["cusip"] = ref_df["cusip"].astype(str)
    ref_df = ref_df.drop_duplicates(subset=["cusip"], keep="last")

    if ref_df.empty:
        return pd.DataFrame()

    if pricing_timestamp is not None:
        ts_for_pricing: datetime.date | datetime.datetime | str = pricing_timestamp
    else:
        ts_for_pricing = "live" if as_of_date == datetime.date.today() else as_of_date

    source_upper = str(usts_source).upper()
    if (
        source_upper == "USTS_WEBULL_WSJ_LIVE-RL"
        and isinstance(ts_for_pricing, datetime.date)
        and not isinstance(ts_for_pricing, datetime.datetime)
        and ts_for_pricing != datetime.date.today()
    ):
        ny_tz = pytz.timezone("America/New_York")
        ts_for_pricing = ny_tz.localize(
            datetime.datetime(
                ts_for_pricing.year,
                ts_for_pricing.month,
                ts_for_pricing.day,
                15,
                0,
            )
        )

    pricers = usts_mdp.get_pricer(
        request={
            "cusips": ref_df["cusip"].tolist(),
            "timestamp": ts_for_pricing,
            "show_tqdm": False,
        }
    )

    metrics: list[Dict[str, Any]] = []
    for cusip, pricer in pricers.items():
        meta = {}
        try:
            meta = pricer.meta() or {}
        except Exception:
            meta = {}
        metrics.append(
            {
                "cusip": str(cusip),
                "ytm": _safe_float(pricer.ytm() if hasattr(pricer, "ytm") else None),
                "mdur": _safe_float(pricer.mod_duration() if hasattr(pricer, "mod_duration") else None),
                "clean_price": _safe_float(pricer.clean_price() if hasattr(pricer, "clean_price") else None),
                "dirty_price": _safe_float(pricer.dirty_price() if hasattr(pricer, "dirty_price") else None),
                "market_timestamp": _to_utc_timestamp(meta.get("timestamp")),
            }
        )
    metrics_df = pd.DataFrame(metrics)
    merged_df = ref_df.merge(metrics_df, on="cusip", how="left")

    if include_mmss and not merged_df.empty:
        swaps_mdp = IRSwapsMDP(source="ERIS_EOD_LIVE-RL_BASIC")
        tb = TimeseriesBuilder(
            irswaps_tb=IRSwapsTB(swaps_mdp),
            fixedratebonds_tb=FixedRateBondsTB(usts_mdp),
        )
        mmss_queries = [
            IRSwapQuery(curve=curve_name, tenor=c, value=IRSwapValue.MMSS)
            for c in merged_df["cusip"].tolist()
        ]

        metric_specs: list[tuple[str, IRSwapValue]] = [
            ("swap_carry", IRSwapValue.CARRY_BPS_RUNNING),
            ("swap_roll", IRSwapValue.ROLL_BPS_RUNNING),
        ]
        swap_metric_queries: list[IRSwapQuery] = []
        query_name_to_output_col: Dict[str, str] = {}
        metric_maps_by_col: Dict[str, Dict[str, float]] = {}
        for cusip in merged_df["cusip"].tolist():
            for label, tenor, _ in CARRY_ROLL_HORIZONS:
                for metric_prefix, metric_value in metric_specs:
                    output_col = f"{metric_prefix}_{label}_bps"
                    query_name = f"USTRV::{cusip}::{metric_prefix}::{label}"
                    swap_metric_queries.append(
                        IRSwapQuery(
                            curve=curve_name,
                            tenor=cusip,
                            value=metric_value,
                            value_kwargs={"horizon": tenor},
                            # Long MMSS spread is modeled as long bond + pay-fixed swap.
                            structure_kwargs={"bpv": -1},
                            name=query_name,
                        )
                    )
                    query_name_to_output_col[query_name] = output_col
                    metric_maps_by_col.setdefault(output_col, {})

        combined_queries = [*mmss_queries, *swap_metric_queries]
        combined_df = tb.get_timeseries(
            start=as_of_date,
            end=as_of_date,
            queries=combined_queries,
            n_jobs=1,
        )
        mmss_map: Dict[str, float] = {}
        if combined_df is not None and not combined_df.empty:
            latest_metrics = combined_df.iloc[-1]
            for query_name, val in latest_metrics.items():
                query_name = str(query_name)
                output_col = query_name_to_output_col.get(query_name)
                if output_col is None:
                    cusip = _extract_cusip_from_query_name(query_name)
                    fv = _safe_float(val)
                    if cusip and fv is not None:
                        mmss_map[cusip] = fv
                    continue
                cusip = _extract_cusip_from_query_name(query_name)
                fv = _safe_float(val)
                if cusip and fv is not None:
                    metric_maps_by_col[output_col][cusip] = fv

        merged_df["mmss"] = merged_df["cusip"].map(mmss_map)

        for label, _, _ in CARRY_ROLL_HORIZONS:
            swap_carry_col = f"swap_carry_{label}_bps"
            swap_roll_col = f"swap_roll_{label}_bps"
            swap_carry_roll_col = f"swap_carry_and_roll_{label}_bps"
            merged_df[swap_carry_col] = merged_df["cusip"].map(metric_maps_by_col.get(swap_carry_col, {}))
            merged_df[swap_roll_col] = merged_df["cusip"].map(metric_maps_by_col.get(swap_roll_col, {}))
            merged_df[swap_carry_roll_col] = merged_df[swap_carry_col] + merged_df[swap_roll_col]
    else:
        merged_df["mmss"] = np.nan
        for col in (
            *SWAP_CARRY_BPS_HORIZON_COLUMNS,
            *SWAP_ROLL_BPS_HORIZON_COLUMNS,
            *SWAP_CARRY_AND_ROLL_BPS_HORIZON_COLUMNS,
            *MMSS_CARRY_BPS_HORIZON_COLUMNS,
            *MMSS_ROLL_BPS_HORIZON_COLUMNS,
            *MMSS_CARRY_AND_ROLL_BPS_HORIZON_COLUMNS,
        ):
            merged_df[col] = np.nan

    merged_df["swap_carry_bps"] = merged_df.get("swap_carry_3m_bps")
    merged_df["swap_roll_bps"] = merged_df.get("swap_roll_3m_bps")
    merged_df["swap_carry_and_roll_bps"] = merged_df.get("swap_carry_and_roll_3m_bps")

    merged_df["coupon"] = merged_df["cpn"] if "cpn" in merged_df.columns else np.nan
    merged_df = _compute_carry_roll_columns(
        merged_df,
        as_of_date=as_of_date,
        pricers={str(k): v for k, v in pricers.items()},
    )
    for label, _, _ in CARRY_ROLL_HORIZONS:
        merged_df[f"mmss_carry_{label}_bps"] = (
            merged_df[f"carry_{label}_bps"] + merged_df[f"swap_carry_{label}_bps"]
        )
        merged_df[f"mmss_roll_{label}_bps"] = (
            merged_df[f"roll_{label}_bps"] + merged_df[f"swap_roll_{label}_bps"]
        )
        merged_df[f"mmss_carry_and_roll_{label}_bps"] = (
            merged_df[f"carry_and_roll_{label}_bps"] + merged_df[f"swap_carry_and_roll_{label}_bps"]
        )

    merged_df["mmss_carry_bps"] = merged_df.get("mmss_carry_3m_bps")
    merged_df["mmss_roll_bps"] = merged_df.get("mmss_roll_3m_bps")
    merged_df["mmss_carry_and_roll_bps"] = merged_df.get("mmss_carry_and_roll_3m_bps")

    merged_df = _ensure_numeric_columns(merged_df, NUMERIC_COLUMNS)
    merged_df = merged_df.sort_values(by=["ttm", "oi", "rank"], kind="mergesort")

    keep_cols = ["cusip", *POINT_DATA_COLUMNS]
    for col in keep_cols:
        if col not in merged_df.columns:
            merged_df[col] = None

    out = merged_df[keep_cols].copy()
    out["as_of_date"] = as_of_date
    out["curve_name"] = curve_name
    return out


def ingest_snapshot(
    engine: Engine,
    *,
    as_of_date: datetime.date,
    curve_name: str,
    min_ttm: float,
    include_mmss: bool,
    dry_run: bool,
) -> Tuple[int, int]:
    points_df = build_points_dataframe(
        as_of_date=as_of_date,
        curve_name=curve_name,
        min_ttm=min_ttm,
        include_mmss=include_mmss,
    )

    if points_df.empty:
        print(f"No points returned for {as_of_date} ({curve_name}).")
        if not dry_run:
            record_ingestion_run(
                engine,
                as_of_date=as_of_date,
                curve_name=curve_name,
                snapshot_ts=pd.Timestamp.now(tz="UTC"),
                points_written=0,
                notes="No points returned from MDPs",
            )
        return 0, 0

    snapshot_ts = pd.Timestamp.now(tz="UTC")
    points_df["snapshot_ts"] = snapshot_ts

    horizon_counts = " ".join(
        [
            f"{label}:"
            f"bond=({int(points_df[f'carry_{label}_bps'].notna().sum())},"
            f"{int(points_df[f'roll_{label}_bps'].notna().sum())},"
            f"{int(points_df[f'carry_and_roll_{label}_bps'].notna().sum())}) "
            f"swap=({int(points_df[f'swap_carry_{label}_bps'].notna().sum())},"
            f"{int(points_df[f'swap_roll_{label}_bps'].notna().sum())},"
            f"{int(points_df[f'swap_carry_and_roll_{label}_bps'].notna().sum())}) "
            f"mmss=({int(points_df[f'mmss_carry_{label}_bps'].notna().sum())},"
            f"{int(points_df[f'mmss_roll_{label}_bps'].notna().sum())},"
            f"{int(points_df[f'mmss_carry_and_roll_{label}_bps'].notna().sum())})"
            for label, _, _ in CARRY_ROLL_HORIZONS
        ]
    )
    print(
        f"Snapshot {as_of_date} ({curve_name}): "
        f"points={len(points_df)} "
        f"otrs={int((points_df['rank'] == 0).sum())} "
        f"mmss_non_null={int(points_df['mmss'].notna().sum())} "
        f"carry_non_null={int(points_df['carry_bps'].notna().sum())} "
        f"roll_non_null={int(points_df['roll_bps'].notna().sum())} "
        f"carry_roll_non_null={int(points_df['carry_and_roll_bps'].notna().sum())} "
        f"swap_carry_non_null={int(points_df['swap_carry_bps'].notna().sum())} "
        f"swap_roll_non_null={int(points_df['swap_roll_bps'].notna().sum())} "
        f"swap_carry_roll_non_null={int(points_df['swap_carry_and_roll_bps'].notna().sum())} "
        f"mmss_carry_non_null={int(points_df['mmss_carry_bps'].notna().sum())} "
        f"mmss_roll_non_null={int(points_df['mmss_roll_bps'].notna().sum())} "
        f"mmss_carry_roll_non_null={int(points_df['mmss_carry_and_roll_bps'].notna().sum())} "
        f"{horizon_counts}"
    )

    if dry_run:
        print("Dry run enabled; skipping database writes.")
        return len(points_df), 0

    points_written = upsert_dataframe(
        points_df,
        engine=engine,
        table_name=POINTS_TABLE,
        conflict_cols=("as_of_date", "curve_name", "cusip"),
        update_cols=(
            *POINT_DATA_COLUMNS,
            "snapshot_ts",
        ),
        progress_desc="Writing UST RV points",
    )
    deleted = delete_stale_points(
        engine,
        as_of_date=as_of_date,
        curve_name=curve_name,
        active_cusips=points_df["cusip"].astype(str).tolist(),
    )
    record_ingestion_run(
        engine,
        as_of_date=as_of_date,
        curve_name=curve_name,
        snapshot_ts=snapshot_ts,
        points_written=points_written,
    )
    return points_written, deleted


def _is_business_day(d: datetime.date) -> bool:
    cal = ql.UnitedStates(ql.UnitedStates.GovernmentBond)
    qd = ql.Date(d.day, d.month, d.year)
    return bool(cal.isBusinessDay(qd))


def build_intraday_points_dataframe(
    *,
    as_of_date: datetime.date,
    curve_name: str,
    min_ttm: float,
    interval_minutes: int,
    session_open: datetime.time,
    session_close: datetime.time,
    max_workers: int,
    show_tqdm: bool,
) -> pd.DataFrame:
    from BT.misc import ql_cal_date_range
    from MDP.FixedRateBonds.FixedRateBondsMDP import FixedRateBondsMDP
    from Query.FixedRateBonds.FixedRateBondQuery import FixedRateBondQuery
    from TB.FixedRateBondsTB import FixedRateBondsTB

    if interval_minutes <= 0:
        raise ValueError(f"interval_minutes must be > 0, got {interval_minutes}")
    if session_close <= session_open:
        raise ValueError(
            f"session_close must be after session_open. Got {session_open} -> {session_close}."
        )
    if not _is_business_day(as_of_date):
        return pd.DataFrame()

    usts_mdp = FixedRateBondsMDP(source=INTRADAY_SOURCE)
    ref_df = usts_mdp.get_bond_reference_data(as_of_date=as_of_date).copy()
    ref_df = ref_df.drop(columns=["record_date"], errors="ignore").rename(columns={"label": "ust_label"})
    ref_df = _ensure_numeric_columns(ref_df, ["ttm", "rank", "cpn"])
    ref_df = ref_df[ref_df["ttm"] >= min_ttm].copy()
    ref_df["cusip"] = ref_df["cusip"].astype(str)
    ref_df = ref_df.drop_duplicates(subset=["cusip"], keep="last")
    if ref_df.empty:
        return pd.DataFrame()

    ny_tz = pytz.timezone("America/New_York")
    start_dt = ny_tz.localize(datetime.datetime.combine(as_of_date, session_open))
    end_dt = ny_tz.localize(datetime.datetime.combine(as_of_date, session_close))
    timestamps = ql_cal_date_range(
        ql.UnitedStates(ql.UnitedStates.GovernmentBond),
        start=start_dt,
        end=end_dt,
        freq=f"{int(interval_minutes)}min",
        open_time=session_open,
        close_time=session_close,
    )
    if not timestamps:
        return pd.DataFrame()

    ts_points = sorted(pd.to_datetime(pd.Index(timestamps)).to_pydatetime().tolist())
    queries = [FixedRateBondQuery(cusip=cusip) for cusip in ref_df["cusip"].tolist()]
    if not queries:
        return pd.DataFrame()

    with FixedRateBondsTB(usts_mdp, show_tqdm=show_tqdm) as usts_tb:
        ytm_df = usts_tb.get_timeseries(
            start=None,
            end=None,
            timestamps=ts_points,
            queries=queries,
            n_jobs=max_workers,
        )
    if ytm_df is None or ytm_df.empty:
        return pd.DataFrame()

    ytm_df = ytm_df.copy()
    ytm_df.index = pd.to_datetime(ytm_df.index, errors="coerce", utc=True)
    ytm_df = ytm_df[~ytm_df.index.isna()]
    if ytm_df.empty:
        return pd.DataFrame()

    ytm_rows: list[pd.DataFrame] = []
    for col in ytm_df.columns:
        cusip = _extract_cusip_from_query_name(str(col))
        if not cusip:
            continue
        tmp = pd.DataFrame(
            {
                "market_timestamp": ytm_df.index,
                "cusip": cusip,
                "ytm": pd.to_numeric(ytm_df[col], errors="coerce"),
            }
        ).dropna(subset=["ytm"])
        if not tmp.empty:
            ytm_rows.append(tmp)

    if not ytm_rows:
        return pd.DataFrame()

    out = pd.concat(ytm_rows, ignore_index=True)
    ref_slim = ref_df[
        ["cusip", "oi", "ust_label", "rank", "ttm", "cpn", "issue_date", "maturity_date"]
    ].copy()
    ref_slim = ref_slim.rename(columns={"cpn": "coupon"}).drop_duplicates(subset=["cusip"], keep="last")
    out = out.merge(ref_slim, on="cusip", how="left")

    out["as_of_date"] = as_of_date
    out["curve_name"] = curve_name
    out["mdur"] = np.nan
    out["mmss"] = np.nan
    out["clean_price"] = np.nan
    out["dirty_price"] = np.nan
    out["carry_bps"] = np.nan
    out["roll_bps"] = np.nan
    out["carry_and_roll_bps"] = np.nan
    for col in (
        *CARRY_BPS_HORIZON_COLUMNS,
        *ROLL_BPS_HORIZON_COLUMNS,
        *CARRY_AND_ROLL_BPS_HORIZON_COLUMNS,
        *SWAP_CARRY_ROLL_ALIAS_COLUMNS,
        *SWAP_CARRY_BPS_HORIZON_COLUMNS,
        *SWAP_ROLL_BPS_HORIZON_COLUMNS,
        *SWAP_CARRY_AND_ROLL_BPS_HORIZON_COLUMNS,
        *MMSS_CARRY_ROLL_ALIAS_COLUMNS,
        *MMSS_CARRY_BPS_HORIZON_COLUMNS,
        *MMSS_ROLL_BPS_HORIZON_COLUMNS,
        *MMSS_CARRY_AND_ROLL_BPS_HORIZON_COLUMNS,
    ):
        out[col] = np.nan

    for col in ["as_of_date", "curve_name", "cusip", *POINT_DATA_COLUMNS]:
        if col not in out.columns:
            out[col] = None

    out = _ensure_numeric_columns(out, NUMERIC_COLUMNS)
    out["cusip"] = out["cusip"].astype(str)
    out["market_timestamp"] = pd.to_datetime(out["market_timestamp"], errors="coerce", utc=True)
    out = out.dropna(subset=["market_timestamp"])
    out = out.drop_duplicates(subset=["curve_name", "market_timestamp", "cusip"], keep="last")
    out = out.sort_values(by=["market_timestamp", "ttm", "oi", "rank", "cusip"], kind="mergesort")
    return out[["as_of_date", "curve_name", "cusip", *POINT_DATA_COLUMNS]]


def ingest_intraday_day(
    engine: Engine,
    *,
    as_of_date: datetime.date,
    curve_name: str,
    min_ttm: float,
    dry_run: bool,
    interval_minutes: int,
    session_open: datetime.time,
    session_close: datetime.time,
    max_workers: int,
    show_tqdm: bool,
) -> int:
    try:
        points_df = build_intraday_points_dataframe(
            as_of_date=as_of_date,
            curve_name=curve_name,
            min_ttm=min_ttm,
            interval_minutes=interval_minutes,
            session_open=session_open,
            session_close=session_close,
            max_workers=max_workers,
            show_tqdm=show_tqdm,
        )
    except Exception as exc:
        raise RuntimeError(
            "build_intraday_points_dataframe failed "
            f"for as_of={as_of_date}, curve={curve_name}, "
            f"session={session_open}-{session_close}, interval={interval_minutes}min, "
            f"max_workers={max_workers}: {type(exc).__name__}: {exc}"
        ) from exc

    if points_df.empty:
        print(f"No intraday points returned for {as_of_date} ({curve_name}).")
        return 0

    snapshot_ts = pd.Timestamp.now(tz="UTC")
    points_df["snapshot_ts"] = snapshot_ts

    print(
        f"Intraday snapshot {as_of_date} ({curve_name}): "
        f"rows={len(points_df)} "
        f"unique_cusips={points_df['cusip'].nunique()} "
        f"range=[{points_df['market_timestamp'].min()}, {points_df['market_timestamp'].max()}]"
    )

    if dry_run:
        print("Dry run enabled; skipping intraday database writes.")
        return int(len(points_df))

    points_written = upsert_dataframe(
        points_df,
        engine=engine,
        table_name=INTRADAY_POINTS_TABLE,
        conflict_cols=("curve_name", "market_timestamp", "cusip"),
        update_cols=(
            "as_of_date",
            *POINT_DATA_COLUMNS,
            "snapshot_ts",
        ),
        progress_desc="Writing UST RV intraday points",
    )
    record_ingestion_run(
        engine,
        as_of_date=as_of_date,
        curve_name=curve_name,
        snapshot_ts=snapshot_ts,
        points_written=points_written,
        notes=(
            f"intraday table={INTRADAY_POINTS_TABLE} interval={interval_minutes}min "
            f"session={session_open}-{session_close}"
        ),
    )
    return points_written


def get_existing_intraday_dates(
    engine: Engine,
    *,
    curve_name: str,
    start_date: datetime.date,
    end_date: datetime.date,
) -> set[datetime.date]:
    with engine.begin() as conn:
        rows = conn.execute(
            text(
                f"""
                SELECT DISTINCT as_of_date
                FROM {INTRADAY_POINTS_TABLE}
                WHERE curve_name = :curve_name
                  AND as_of_date BETWEEN :start_date AND :end_date
                """
            ),
            dict(curve_name=curve_name, start_date=start_date, end_date=end_date),
        ).fetchall()

    out: set[datetime.date] = set()
    for row in rows:
        d = _coerce_db_date(row[0] if row else None)
        if d is not None:
            out.add(d)
    return out


def run_intraday_backfill_mode(
    *,
    engine: Engine,
    start_date: datetime.date,
    end_date: datetime.date,
    curve_name: str,
    min_ttm: float,
    dry_run: bool,
    interval_minutes: int,
    session_open: datetime.time,
    session_close: datetime.time,
    max_workers: int,
    show_tqdm: bool,
    skip_existing: bool,
    network_timeout_seconds: Optional[float] = None,
    stop_on_error: bool = False,
) -> None:
    all_days = _date_range_business_days(start_date, end_date)
    if not all_days:
        print(f"No business days between {start_date} and {end_date}.")
        return

    if skip_existing and not dry_run:
        existing = get_existing_intraday_dates(
            engine,
            curve_name=curve_name,
            start_date=start_date,
            end_date=end_date,
        )
        days = [d for d in all_days if d not in existing]
        print(
            f"Intraday backfill business days={len(all_days)}, "
            f"existing={len(existing)}, remaining={len(days)}"
        )
    else:
        days = all_days
        print(f"Intraday backfill business days={len(days)}")

    if not days:
        print("Intraday backfill complete: nothing new to ingest.")
        return

    run_start_wall = pd.Timestamp.now(tz="UTC")
    run_start_monotonic = time.monotonic()
    print(
        f"[{run_start_wall.isoformat()}] Intraday backfill START "
        f"curve={curve_name} range={start_date}->{end_date} "
        f"days={len(days)} interval={interval_minutes}min "
        f"session={session_open}-{session_close} "
        f"max_workers={max_workers} dry_run={dry_run}"
    )

    total_written = 0
    failed_days: list[tuple[datetime.date, str]] = []
    for idx, d in enumerate(days, start=1):
        day_start_wall = pd.Timestamp.now(tz="UTC")
        day_start_monotonic = time.monotonic()
        print(
            f"[{day_start_wall.isoformat()}] Intraday day {idx}/{len(days)} START "
            f"as_of={d} curve={curve_name}"
        )
        try:
            written = ingest_intraday_day(
                engine,
                as_of_date=d,
                curve_name=curve_name,
                min_ttm=min_ttm,
                dry_run=dry_run,
                interval_minutes=interval_minutes,
                session_open=session_open,
                session_close=session_close,
                max_workers=max_workers,
                show_tqdm=show_tqdm,
            )
            total_written += int(written)
            day_elapsed = time.monotonic() - day_start_monotonic
            day_end_wall = pd.Timestamp.now(tz="UTC")
            print(
                f"[{day_end_wall.isoformat()}] Intraday day {idx}/{len(days)} END "
                f"as_of={d} status=ok rows_written={int(written)} "
                f"elapsed={day_elapsed:.1f}s"
            )
        except Exception as exc:
            day_elapsed = time.monotonic() - day_start_monotonic
            day_end_wall = pd.Timestamp.now(tz="UTC")
            err = _format_intraday_day_error(
                exc,
                network_timeout_seconds=network_timeout_seconds,
            )
            failed_days.append((d, err))
            print(
                f"[{day_end_wall.isoformat()}] Intraday day {idx}/{len(days)} END "
                f"as_of={d} status=failed elapsed={day_elapsed:.1f}s error={err}"
            )
            if stop_on_error:
                raise

    run_elapsed = time.monotonic() - run_start_monotonic
    run_end_wall = pd.Timestamp.now(tz="UTC")
    print(
        f"[{run_end_wall.isoformat()}] Intraday backfill END. "
        f"days_processed={len(days)}, rows_written={total_written}, "
        f"failed_days={len(failed_days)}, elapsed={run_elapsed:.1f}s"
    )
    if failed_days:
        print("Intraday backfill failed dates:")
        for d, err in failed_days:
            print(f"  {d}: {err}")


def _parse_date(raw: str, arg_name: str) -> datetime.date:
    txt = (raw or "").strip()
    if not txt:
        raise ValueError(f"--{arg_name} cannot be empty")
    if txt.lower() in {"today", "live"}:
        return datetime.date.today()
    try:
        return datetime.date.fromisoformat(txt)
    except Exception as exc:
        raise ValueError(f"Invalid --{arg_name}: {raw}. Expected YYYY-MM-DD.") from exc


def _date_range_business_days(start_date: datetime.date, end_date: datetime.date) -> list[datetime.date]:
    if start_date > end_date:
        raise ValueError(f"start_date must be <= end_date. Got {start_date} > {end_date}.")
    cal = ql.UnitedStates(ql.UnitedStates.GovernmentBond)
    out: list[datetime.date] = []
    current = start_date
    while current <= end_date:
        qd = ql.Date(current.day, current.month, current.year)
        if cal.isBusinessDay(qd):
            out.append(current)
        current += datetime.timedelta(days=1)
    return out


def run_range_mode(
    *,
    engine: Engine,
    start_date: datetime.date,
    end_date: datetime.date,
    curve_name: str,
    min_ttm: float,
    include_mmss: bool,
    dry_run: bool,
    stop_on_error: bool = False,
) -> None:
    days = _date_range_business_days(start_date, end_date)
    if not days:
        print(f"No business days between {start_date} and {end_date}.")
        return
    print(f"Ingesting {len(days)} business day snapshots...")
    total_written = 0
    total_deleted = 0
    failed_days: list[tuple[datetime.date, str]] = []
    for d in days:
        try:
            written, deleted = ingest_snapshot(
                engine,
                as_of_date=d,
                curve_name=curve_name,
                min_ttm=min_ttm,
                include_mmss=include_mmss,
                dry_run=dry_run,
            )
            total_written += int(written)
            total_deleted += int(deleted)
        except Exception as exc:
            err = f"{type(exc).__name__}: {exc}"
            failed_days.append((d, err))
            print(f"Range mode failed for {d}: {err}")
            if stop_on_error:
                raise

    print(
        f"Range mode complete. points_written={total_written}, "
        f"stale_deleted={total_deleted}, failed_days={len(failed_days)}"
    )
    if failed_days:
        print("Range mode failed dates:")
        for d, err in failed_days:
            print(f"  {d}: {err}")


def _coerce_db_date(val: Any) -> Optional[datetime.date]:
    if val is None:
        return None
    if isinstance(val, datetime.datetime):
        return val.date()
    if isinstance(val, datetime.date):
        return val
    try:
        return datetime.date.fromisoformat(str(val))
    except Exception:
        return None


def get_existing_snapshot_dates(
    engine: Engine,
    *,
    curve_name: str,
    start_date: datetime.date,
    end_date: datetime.date,
) -> set[datetime.date]:
    with engine.begin() as conn:
        rows = conn.execute(
            text(
                f"""
                SELECT DISTINCT as_of_date
                FROM {POINTS_TABLE}
                WHERE curve_name = :curve_name
                  AND as_of_date BETWEEN :start_date AND :end_date
                """
            ),
            dict(curve_name=curve_name, start_date=start_date, end_date=end_date),
        ).fetchall()

    out: set[datetime.date] = set()
    for row in rows:
        d = _coerce_db_date(row[0] if row else None)
        if d is not None:
            out.add(d)
    return out


def run_historical_backfill_mode(
    *,
    engine: Engine,
    start_date: datetime.date,
    end_date: datetime.date,
    curve_name: str,
    min_ttm: float,
    include_mmss: bool,
    dry_run: bool,
    skip_existing: bool,
    stop_on_error: bool = False,
) -> None:
    all_days = _date_range_business_days(start_date, end_date)
    if not all_days:
        print(f"No business days between {start_date} and {end_date}.")
        return

    if skip_existing and not dry_run:
        existing = get_existing_snapshot_dates(
            engine,
            curve_name=curve_name,
            start_date=start_date,
            end_date=end_date,
        )
        days = [d for d in all_days if d not in existing]
        print(
            f"Historical backfill business days={len(all_days)}, "
            f"existing={len(existing)}, remaining={len(days)}"
        )
    else:
        days = all_days
        print(f"Historical backfill business days={len(days)}")

    if not days:
        print("Historical backfill complete: nothing new to ingest.")
        return

    total_written = 0
    total_deleted = 0
    failed_days: list[tuple[datetime.date, str]] = []
    for d in days:
        try:
            written, deleted = ingest_snapshot(
                engine,
                as_of_date=d,
                curve_name=curve_name,
                min_ttm=min_ttm,
                include_mmss=include_mmss,
                dry_run=dry_run,
            )
            total_written += int(written)
            total_deleted += int(deleted)
        except Exception as exc:
            err = f"{type(exc).__name__}: {exc}"
            failed_days.append((d, err))
            print(f"Historical backfill failed for {d}: {err}")
            if stop_on_error:
                raise

    print(
        "Historical backfill complete. "
        f"days_processed={len(days)}, points_written={total_written}, "
        f"stale_deleted={total_deleted}, failed_days={len(failed_days)}"
    )
    if failed_days:
        print("Historical backfill failed dates:")
        for d, err in failed_days:
            print(f"  {d}: {err}")


def run_incremental_mode(
    *,
    engine: Engine,
    as_of_date: datetime.date,
    curve_name: str,
    min_ttm: float,
    include_mmss: bool,
    dry_run: bool,
) -> None:
    effective_date = _adjust_to_business_day(as_of_date)
    if effective_date != as_of_date:
        print(f"Adjusted as_of from {as_of_date} to prior business day {effective_date}.")
    written, deleted = ingest_snapshot(
        engine,
        as_of_date=effective_date,
        curve_name=curve_name,
        min_ttm=min_ttm,
        include_mmss=include_mmss,
        dry_run=dry_run,
    )
    print(f"Incremental mode complete. points_written={written}, stale_deleted={deleted}")


def run_service_mode(
    *,
    engine: Engine,
    interval_seconds: int,
    curve_name: str,
    min_ttm: float,
    include_mmss: bool,
    dry_run: bool,
    service_backfill_days: int,
    max_iterations: Optional[int],
    stop_on_error: bool,
) -> None:
    if interval_seconds <= 0:
        raise ValueError(f"interval_seconds must be > 0, got {interval_seconds}")
    if service_backfill_days < 0:
        raise ValueError(
            f"service_backfill_days must be >= 0, got {service_backfill_days}"
        )
    if max_iterations is not None and max_iterations <= 0:
        raise ValueError(f"max_iterations must be > 0 when provided, got {max_iterations}")

    print("Starting UST RV ingestion service")
    print(f"  Interval: {interval_seconds}s")
    print(f"  Curve: {curve_name}")
    print(f"  Min TTM: {min_ttm}")
    print(f"  Include MMSS: {include_mmss}")
    print(f"  Dry run: {dry_run}")
    if service_backfill_days > 0:
        print(f"  Startup backfill lookback: {service_backfill_days} calendar days")
    else:
        print("  Startup backfill lookback: disabled")
    if max_iterations is not None:
        print(f"  Max iterations: {max_iterations}")
    print()

    if service_backfill_days > 0:
        backfill_end = datetime.date.today()
        backfill_start = backfill_end - datetime.timedelta(days=service_backfill_days)
        print(
            "Running startup historical backfill before service loop: "
            f"{backfill_start} -> {backfill_end}"
        )
        run_historical_backfill_mode(
            engine=engine,
            start_date=backfill_start,
            end_date=backfill_end,
            curve_name=curve_name,
            min_ttm=min_ttm,
            include_mmss=include_mmss,
            dry_run=dry_run,
            skip_existing=False,
            stop_on_error=stop_on_error,
        )
        print("Startup historical backfill finished.\n")

    iteration = 0
    while True:
        iteration += 1
        cycle_start = time.monotonic()
        wall = pd.Timestamp.now(tz="UTC")
        as_of = _adjust_to_business_day(wall.date())
        print(f"[{wall.isoformat()}] UST RV cycle {iteration} (as_of={as_of})")
        try:
            written, deleted = ingest_snapshot(
                engine,
                as_of_date=as_of,
                curve_name=curve_name,
                min_ttm=min_ttm,
                include_mmss=include_mmss,
                dry_run=dry_run,
            )
            print(f"Cycle {iteration} complete. points_written={written}, stale_deleted={deleted}")
        except Exception as exc:
            print(f"Cycle {iteration} failed: {exc}")
            if stop_on_error:
                raise

        if max_iterations is not None and iteration >= max_iterations:
            print("Reached max iterations; exiting.")
            break

        elapsed = time.monotonic() - cycle_start
        sleep_seconds = max(0.0, interval_seconds - elapsed)
        print(f"Sleeping {sleep_seconds:.1f}s...\n")
        time.sleep(sleep_seconds)


def _configure_requests_timeout(timeout_seconds: Optional[float]) -> Optional[float]:
    """
    Configure a default timeout for requests made without an explicit timeout.
    This avoids indefinite hangs from upstream APIs.
    """
    global _REQUESTS_TIMEOUT_SECONDS, _REQUESTS_TIMEOUT_PATCHED, _REQUESTS_ORIGINAL_REQUEST

    if timeout_seconds is None:
        return None

    timeout_val = float(timeout_seconds)
    if not math.isfinite(timeout_val):
        raise ValueError(f"--network-timeout-seconds must be finite, got {timeout_seconds}")
    if timeout_val <= 0:
        print("Network timeout disabled (--network-timeout-seconds <= 0).")
        return None

    _REQUESTS_TIMEOUT_SECONDS = timeout_val
    if not _REQUESTS_TIMEOUT_PATCHED:
        _REQUESTS_ORIGINAL_REQUEST = requests.sessions.Session.request

        def _patched_request(self: requests.sessions.Session, method: str, url: str, **kwargs: Any):
            kwargs.setdefault("timeout", _REQUESTS_TIMEOUT_SECONDS)
            assert _REQUESTS_ORIGINAL_REQUEST is not None
            return _REQUESTS_ORIGINAL_REQUEST(self, method, url, **kwargs)

        requests.sessions.Session.request = _patched_request
        _REQUESTS_TIMEOUT_PATCHED = True

    print(
        "Configured default requests timeout "
        f"to {timeout_val:.1f}s for calls without an explicit timeout."
    )
    return timeout_val


def _is_timeout_error(exc: Exception) -> bool:
    txt = f"{type(exc).__name__}: {exc}".lower()
    return ("timeout" in txt) or ("timed out" in txt)


def _format_intraday_day_error(
    exc: Exception,
    *,
    network_timeout_seconds: Optional[float] = None,
) -> str:
    base = f"{type(exc).__name__}: {exc}"
    if not _is_timeout_error(exc):
        return base

    if network_timeout_seconds is not None and network_timeout_seconds > 0:
        timeout_txt = f"{network_timeout_seconds:.1f}s"
    else:
        timeout_txt = "disabled"

    return (
        f"{base}. Timeout while fetching intraday data "
        f"(default requests timeout={timeout_txt}). "
        "Try reducing --intraday-max-workers or increasing --network-timeout-seconds."
    )


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None or raw == "":
        return default
    return int(raw)


def _parse_time_arg(raw: str, arg_name: str) -> datetime.time:
    txt = (raw or "").strip()
    if not txt:
        raise ValueError(f"--{arg_name} cannot be empty")
    try:
        parsed = datetime.time.fromisoformat(txt)
    except Exception as exc:
        raise ValueError(f"Invalid --{arg_name}: {raw}. Expected HH:MM or HH:MM:SS.") from exc
    return parsed


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Ingest UST RV points into SwapPulse Postgres.")
    parser.add_argument(
        "--database-url",
        type=str,
        default=os.getenv("SWAPPULSE_DATABASE_URL", os.getenv("DATABASE_URL")),
        help=(
            "Postgres connection URL. If omitted, resolves from "
            "SWAPPULSE_DATABASE_URL, then DATABASE_URL, then SWAPPULSE_DB_* vars."
        ),
    )
    parser.add_argument(
        "--skip-schema",
        action="store_true",
        help="Skip schema/index ensure step (use when schema is already provisioned).",
    )
    parser.add_argument(
        "--mode",
        choices=("range", "historical", "incremental", "service", "intraday"),
        default=os.getenv("SWAPPULSE_USTRV_INGEST_MODE", "incremental"),
        help=(
            "range=custom date range backfill, historical=long-range backfill for "
            "timeseries history, incremental=single snapshot, service=continuous loop, "
            "intraday=minute-level intraday backfill."
        ),
    )
    parser.add_argument(
        "--curve-name",
        type=str,
        default=os.getenv("SWAPPULSE_USTRV_CURVE_NAME", "USD-SOFR-1D"),
        help="Curve name used for MMSS queries.",
    )
    parser.add_argument(
        "--min-ttm",
        type=float,
        default=float(os.getenv("SWAPPULSE_USTRV_MIN_TTM", "1.0")),
        help="Minimum TTM filter applied at ingestion time.",
    )
    parser.add_argument(
        "--no-mmss",
        action="store_true",
        help="Skip MMSS computation.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Build snapshots but skip writes.",
    )
    parser.add_argument(
        "--network-timeout-seconds",
        type=float,
        default=float(os.getenv("SWAPPULSE_USTRV_NETWORK_TIMEOUT_SECONDS", "20")),
        help=(
            "Default timeout (seconds) for requests calls that do not specify one. "
            "Set <= 0 to disable."
        ),
    )

    parser.add_argument(
        "--as-of",
        type=str,
        help="Incremental mode as-of date (YYYY-MM-DD, today, live). Defaults to today.",
    )

    parser.add_argument(
        "--start-date",
        type=str,
        help="Range mode start date (YYYY-MM-DD).",
    )
    parser.add_argument(
        "--end-date",
        type=str,
        help="Range mode end date (YYYY-MM-DD).",
    )
    parser.add_argument(
        "--days",
        type=int,
        default=7,
        help="Range mode fallback lookback days when start/end are omitted.",
    )
    parser.add_argument(
        "--historical-start-date",
        type=str,
        default=os.getenv("SWAPPULSE_USTRV_HISTORICAL_START_DATE"),
        help="Historical mode start date (YYYY-MM-DD).",
    )
    parser.add_argument(
        "--historical-end-date",
        type=str,
        default=os.getenv("SWAPPULSE_USTRV_HISTORICAL_END_DATE"),
        help="Historical mode end date (YYYY-MM-DD). Defaults to today.",
    )
    parser.add_argument(
        "--historical-years",
        type=int,
        default=_env_int("SWAPPULSE_USTRV_HISTORICAL_YEARS", 10),
        help="Historical mode fallback lookback years when start date is omitted.",
    )
    parser.add_argument(
        "--include-existing",
        action="store_true",
        help="Historical mode: reprocess dates already present in DB.",
    )
    parser.add_argument(
        "--intraday-include-existing",
        action="store_true",
        help="Intraday mode: reprocess dates already present in intraday table.",
    )
    parser.add_argument(
        "--intraday-open-time",
        type=str,
        default=os.getenv("SWAPPULSE_USTRV_INTRADAY_OPEN_TIME", "07:00"),
        help="Intraday mode session open time in America/New_York (HH:MM).",
    )
    parser.add_argument(
        "--intraday-close-time",
        type=str,
        default=os.getenv("SWAPPULSE_USTRV_INTRADAY_CLOSE_TIME", "15:00"),
        help="Intraday mode session close time in America/New_York (HH:MM).",
    )
    parser.add_argument(
        "--intraday-interval-minutes",
        type=int,
        default=_env_int("SWAPPULSE_USTRV_INTRADAY_INTERVAL_MINUTES", 1),
        help="Intraday mode minute interval for timestamps.",
    )
    parser.add_argument(
        "--intraday-max-workers",
        type=int,
        default=_env_int("SWAPPULSE_USTRV_INTRADAY_MAX_WORKERS", 8),
        help="Intraday mode max workers passed to FixedRateBondsMDP.bulk_get_data.",
    )
    parser.add_argument(
        "--intraday-show-tqdm",
        action="store_true",
        help="Intraday mode: show tqdm progress for MDP bulk fetch.",
    )

    parser.add_argument(
        "--interval-seconds",
        type=int,
        default=_env_int("SWAPPULSE_USTRV_INTERVAL_SECONDS", 120),
        help="Service mode polling interval in seconds.",
    )
    parser.add_argument(
        "--service-backfill-days",
        type=int,
        default=_env_int("SWAPPULSE_USTRV_SERVICE_BACKFILL_DAYS", 2),
        help=(
            "Service mode only: on startup, reprocess this many calendar days "
            "of history (business-day filtered). Set to 0 to disable."
        ),
    )
    parser.add_argument(
        "--max-iterations",
        type=int,
        help="Service mode only: stop after this many cycles.",
    )
    parser.add_argument(
        "--stop-on-error",
        action="store_true",
        help=(
            "Exit immediately on first error. "
            "In range/historical modes this stops at first failed date; "
            "in service mode it stops at first failed cycle."
        ),
    )
    return parser.parse_args()


def _resolve_range_dates(
    start_raw: Optional[str],
    end_raw: Optional[str],
    days: int,
) -> tuple[datetime.date, datetime.date]:
    if days <= 0:
        raise ValueError(f"--days must be > 0, got {days}")

    today = datetime.date.today()
    if start_raw:
        start_date = _parse_date(start_raw, "start-date")
    else:
        start_date = today - datetime.timedelta(days=days)

    if end_raw:
        end_date = _parse_date(end_raw, "end-date")
    else:
        end_date = today
    return start_date, end_date


def _resolve_historical_dates(
    start_raw: Optional[str],
    end_raw: Optional[str],
    years: int,
) -> tuple[datetime.date, datetime.date]:
    if years <= 0:
        raise ValueError(f"--historical-years must be > 0, got {years}")

    today = datetime.date.today()
    if start_raw:
        start_date = _parse_date(start_raw, "historical-start-date")
    else:
        start_date = today - datetime.timedelta(days=365 * years)

    if end_raw:
        end_date = _parse_date(end_raw, "historical-end-date")
    else:
        end_date = today
    return start_date, end_date


if __name__ == "__main__":
    args = parse_args()
    include_mmss = not args.no_mmss
    configured_network_timeout = _configure_requests_timeout(args.network_timeout_seconds)
    engine = create_db_engine(args.database_url)
    if args.skip_schema:
        print("Skipping schema ensure (--skip-schema).")
    else:
        ensure_schema(engine)

    if args.mode == "range":
        start_date, end_date = _resolve_range_dates(args.start_date, args.end_date, args.days)
        run_range_mode(
            engine=engine,
            start_date=start_date,
            end_date=end_date,
            curve_name=args.curve_name,
            min_ttm=args.min_ttm,
            include_mmss=include_mmss,
            dry_run=args.dry_run,
            stop_on_error=args.stop_on_error,
        )
    elif args.mode == "historical":
        start_date, end_date = _resolve_historical_dates(
            args.historical_start_date,
            args.historical_end_date,
            args.historical_years,
        )
        run_historical_backfill_mode(
            engine=engine,
            start_date=start_date,
            end_date=end_date,
            curve_name=args.curve_name,
            min_ttm=args.min_ttm,
            include_mmss=include_mmss,
            dry_run=args.dry_run,
            skip_existing=not args.include_existing,
            stop_on_error=args.stop_on_error,
        )
    elif args.mode == "incremental":
        as_of = _parse_date(args.as_of, "as-of") if args.as_of else datetime.date.today()
        run_incremental_mode(
            engine=engine,
            as_of_date=as_of,
            curve_name=args.curve_name,
            min_ttm=args.min_ttm,
            include_mmss=include_mmss,
            dry_run=args.dry_run,
        )
    elif args.mode == "intraday":
        start_date, end_date = _resolve_range_dates(args.start_date, args.end_date, args.days)
        session_open = _parse_time_arg(args.intraday_open_time, "intraday-open-time")
        session_close = _parse_time_arg(args.intraday_close_time, "intraday-close-time")
        run_intraday_backfill_mode(
            engine=engine,
            start_date=start_date,
            end_date=end_date,
            curve_name=args.curve_name,
            min_ttm=args.min_ttm,
            dry_run=args.dry_run,
            interval_minutes=args.intraday_interval_minutes,
            session_open=session_open,
            session_close=session_close,
            max_workers=args.intraday_max_workers,
            show_tqdm=args.intraday_show_tqdm,
            skip_existing=not args.intraday_include_existing,
            network_timeout_seconds=configured_network_timeout,
            stop_on_error=args.stop_on_error,
        )
    else:
        run_service_mode(
            engine=engine,
            interval_seconds=args.interval_seconds,
            curve_name=args.curve_name,
            min_ttm=args.min_ttm,
            include_mmss=include_mmss,
            dry_run=args.dry_run,
            service_backfill_days=args.service_backfill_days,
            max_iterations=args.max_iterations,
            stop_on_error=args.stop_on_error,
        )
