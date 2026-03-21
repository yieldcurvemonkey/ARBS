from __future__ import annotations

import datetime
from functools import lru_cache
from typing import Any, Iterable, Sequence

import pandas as pd
import pytz

DEFAULT_ANALYTICS_TENORS: tuple[str, ...] = (
    "1M",
    "3M",
    "6M",
    "1Y",
    "2Y",
    "3Y",
    "5Y",
    "7Y",
    "10Y",
    "20Y",
    "30Y",
)

DEFAULT_ANALYTICS_METRICS: tuple[str, ...] = ("par_rate", "rate")

_USD_SOFR_Q12STIRT_ANALYTICS_TENORS: tuple[str, ...] = (
    tuple(f"{month}M" for month in range(1, 12))
    + (
        "1Y",
        "18M",
        "22M",
        "2Y",
        "30M",
        "3Y",
        "3M1Y",
        "3M2Y",
        "6M1Y",
        "6M2Y",
        "1Y1Y",
        "2Y1Y",
        "1Y2Y",
    )
    + tuple(f"FOMC_{rank}" for rank in range(1, 8))
    + tuple(f"IMM_{rank}xIMM_{rank + 1}" for rank in range(1, 13))
)

_CHI = pytz.timezone("America/Chicago")
_UTC = pytz.UTC


@lru_cache(maxsize=64)
def analytics_tenors_for_curve(curve_name: str | None) -> tuple[str, ...]:
    curve_upper = str(curve_name or "").upper()
    if curve_upper == "USD-SOFR-1D-Q12STIRT":
        return _USD_SOFR_Q12STIRT_ANALYTICS_TENORS
    return DEFAULT_ANALYTICS_TENORS


def compute_session_minute(timestamp_local: datetime.datetime) -> int:
    session_open = timestamp_local.replace(hour=6, minute=0, second=0, microsecond=0)
    return int((timestamp_local - session_open).total_seconds() // 60)


def compute_analytics_row(
    curve: Any,
    *,
    timestamp_utc: datetime.datetime,
    trading_date: datetime.date,
    session_minute: int | None = None,
    tenors: Sequence[str] | None = None,
    curve_name: str | None = None,
) -> dict[str, Any]:
    ts_utc = pd.Timestamp(timestamp_utc).to_pydatetime()
    if ts_utc.tzinfo is None:
        ts_utc = _UTC.localize(ts_utc)
    else:
        ts_utc = ts_utc.astimezone(_UTC)

    if session_minute is None:
        session_minute = compute_session_minute(ts_utc.astimezone(_CHI))

    resolved_curve_name = str(curve_name or "")
    if not resolved_curve_name:
        meta_fn = getattr(curve, "meta", None)
        if callable(meta_fn):
            meta = meta_fn() or {}
            resolved_curve_name = str(
                meta.get("requested_curve_name")
                or meta.get("curve_name")
                or meta.get("reference_curve_name")
                or ""
            )
    if not resolved_curve_name:
        resolved_curve_name = str(getattr(curve, "curve_name", "") or getattr(curve, "name", "") or "")

    resolved_tenors = tuple(tenors or analytics_tenors_for_curve(resolved_curve_name))

    row: dict[str, Any] = {
        "timestamp_utc": ts_utc,
        "trading_date": trading_date,
        "session_minute": int(session_minute),
    }

    for tenor in resolved_tenors:
        value = float("nan")
        try:
            irs = curve.build_irswap(tenor=str(tenor))
            value = float(curve.fair_rate(irs)) * 100.0
        except Exception:
            value = float("nan")
        row[f"par_rate_{tenor}"] = value
        row[f"rate_{tenor}"] = value

    return row


def build_analytics_frame(
    rows: Iterable[dict[str, Any]],
) -> pd.DataFrame:
    data = list(rows)
    if not data:
        return pd.DataFrame()
    df = pd.DataFrame(data)
    if "timestamp_utc" in df.columns:
        df["timestamp_utc"] = pd.to_datetime(df["timestamp_utc"], utc=True)
        df = df.sort_values("timestamp_utc")
    return df.reset_index(drop=True)
