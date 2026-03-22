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


def _ordered_unique(tokens: Sequence[str]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(str(token) for token in tokens if str(token)))


_USD_SOFR_EOD_FORWARD_START_TENORS: tuple[str, ...] = (
    "1M3M", "1M6M", "1M1Y", "1M2Y", "1M3Y", "1M5Y", "1M7Y", "1M10Y",
    "1M15Y", "1M20Y", "1M30Y",
    "2M3M", "2M6M", "2M1Y", "2M2Y", "2M3Y", "2M5Y", "2M7Y", "2M10Y",
    "2M15Y", "2M20Y", "2M30Y",
    "3M3M", "3M6M", "3M9M", "3M1Y", "3M18M", "3M2Y", "3M3Y", "3M5Y", "3M7Y", "3M10Y",
    "3M15Y", "3M20Y", "3M30Y",
    "6M3M", "6M6M", "6M1Y", "6M18M", "6M2Y", "6M3Y", "6M5Y", "6M7Y", "6M10Y",
    "6M15Y", "6M20Y", "6M30Y",
    "9M3M", "9M6M", "9M1Y", "9M18M", "9M2Y", "9M3Y", "9M5Y", "9M7Y", "9M10Y",
    "9M15Y", "9M20Y", "9M30Y",
    "1Y1Y", "1Y18M", "1Y2Y", "1Y3Y", "1Y4Y", "1Y5Y", "1Y7Y", "1Y10Y",
    "1Y15Y", "1Y20Y", "1Y30Y",
    "18M6M", "18M1Y", "18M18M", "18M2Y", "18M3Y", "18M5Y", "18M7Y", "18M10Y",
    "18M15Y", "18M20Y", "18M30Y",
    "2Y1Y", "2Y2Y", "2Y3Y", "2Y5Y", "2Y7Y", "2Y8Y", "2Y10Y",
    "2Y15Y", "2Y20Y", "2Y30Y",
    "3Y1Y", "3Y2Y", "3Y3Y", "3Y5Y", "3Y7Y", "3Y10Y",
    "3Y15Y", "3Y20Y", "3Y30Y",
    "4Y1Y", "4Y2Y", "4Y3Y", "4Y5Y", "4Y6Y", "4Y7Y", "4Y10Y",
    "4Y15Y", "4Y20Y", "4Y30Y",
    "5Y1Y", "5Y2Y", "5Y3Y", "5Y5Y", "5Y7Y", "5Y10Y",
    "5Y15Y", "5Y20Y", "5Y30Y",
    "7Y1Y", "7Y2Y", "7Y3Y", "7Y5Y", "7Y10Y",
    "7Y15Y", "7Y20Y", "7Y30Y",
    "10Y1Y", "10Y2Y", "10Y3Y", "10Y5Y", "10Y10Y",
    "10Y15Y", "10Y20Y", "10Y30Y",
    "15Y1Y", "15Y5Y", "15Y10Y", "15Y15Y", "15Y30Y",
    "20Y1Y", "20Y5Y", "20Y10Y", "20Y30Y",
    "30Y1Y", "30Y5Y", "30Y10Y", "30Y20Y", "30Y30Y",
)

_USD_SOFR_EOD_ANALYTICS_TENORS: tuple[str, ...] = _ordered_unique(
    tuple(f"{month}M" for month in range(1, 24))
    + tuple(f"{year}Y" for year in range(1, 51))
    + _USD_SOFR_EOD_FORWARD_START_TENORS
)

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
    if curve_upper == "USD-SOFR-1D":
        return _USD_SOFR_EOD_ANALYTICS_TENORS
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
