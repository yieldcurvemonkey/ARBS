from __future__ import annotations

import datetime as dt
import logging
from collections import OrderedDict
from typing import Any, Sequence
from zoneinfo import ZoneInfo

import pandas as pd


_LOGGER = logging.getLogger(__name__)
_DEFAULT_CME_TIMEZONE = "America/Chicago"
_DEFAULT_CME_SESSION_OPEN_HOUR = 17


def build_bulk_request(
    *,
    curve_name: str,
    timestamps: Sequence[dt.datetime],
    n_jobs: int,
    show_tqdm: bool,
    ignore_cache: bool,
    calibration_executor: str,
    auto_prime_bulk: bool,
    stirf_fetch_max_workers: int | None = None,
    calibration_max_workers: int | None = None,
    max_tasks_per_child: int | None = None,
) -> dict[str, Any]:
    request: dict[str, Any] = {
        "curve_name": str(curve_name),
        "timestamps": list(timestamps),
        "n_jobs": int(n_jobs),
        "show_tqdm": bool(show_tqdm),
        "ignore_cache": bool(ignore_cache),
        "calibration_executor": str(calibration_executor),
        "auto_prime_bulk": bool(auto_prime_bulk),
    }
    if stirf_fetch_max_workers is not None:
        request["stirf_fetch_max_workers"] = int(stirf_fetch_max_workers)
    if calibration_max_workers is not None:
        request["calibration_max_workers"] = int(calibration_max_workers)
    if max_tasks_per_child is not None:
        request["max_tasks_per_child"] = int(max_tasks_per_child)
    return request


def normalize_timestamp_utc_minute(value: Any) -> dt.datetime | None:
    if hasattr(value, "to_pydatetime"):
        value = value.to_pydatetime()
    if not isinstance(value, dt.datetime):
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=dt.timezone.utc)
    else:
        value = value.astimezone(dt.timezone.utc)
    return value.replace(second=0, microsecond=0)


def curve_store_trading_date(value: dt.datetime) -> dt.date:
    value_chi = value.astimezone(ZoneInfo(_DEFAULT_CME_TIMEZONE))
    if value_chi.hour >= _DEFAULT_CME_SESSION_OPEN_HOUR:
        return value_chi.date() + dt.timedelta(days=1)
    return value_chi.date()


def bucket_timestamps_by_trading_date(
    timestamps: Sequence[dt.datetime],
) -> "OrderedDict[dt.date, list[dt.datetime]]":
    buckets: "OrderedDict[dt.date, list[dt.datetime]]" = OrderedDict()
    seen: set[dt.datetime] = set()
    for timestamp in timestamps:
        if hasattr(timestamp, "to_pydatetime"):
            timestamp = timestamp.to_pydatetime()
        if not isinstance(timestamp, dt.datetime):
            raise TypeError(f"Expected datetime-like bucket value, got {type(timestamp)!r}")
        normalized = normalize_timestamp_utc_minute(timestamp)
        if normalized is None or normalized in seen:
            continue
        seen.add(normalized)
        trading_date = curve_store_trading_date(normalized)
        buckets.setdefault(trading_date, []).append(timestamp)
    return buckets


def read_existing_curve_store_timestamps(
    store: Any,
    *,
    curve_name: str,
    timestamps: Sequence[dt.datetime],
) -> set[dt.datetime]:
    requested_keys = [
        ts_key
        for ts_key in (normalize_timestamp_utc_minute(timestamp) for timestamp in timestamps)
        if ts_key is not None
    ]
    if not requested_keys:
        return set()

    requested_key_set = set(requested_keys)
    ordered_trading_dates = sorted({curve_store_trading_date(ts_key) for ts_key in requested_keys})
    df = pd.DataFrame()

    if hasattr(store, "read_raw_nodes"):
        try:
            df = store.read_raw_nodes(curve_name, timestamps_utc=sorted(requested_key_set))
        except TypeError:
            df = store.read_raw_nodes(
                curve_name,
                start=ordered_trading_dates[0],
                end=ordered_trading_dates[-1],
            )
        except Exception:
            df = pd.DataFrame()

    if (df is None or df.empty or "timestamp_utc" not in df.columns) and hasattr(store, "read_raw_day"):
        day_frames = []
        for trading_date in ordered_trading_dates:
            try:
                day_df = store.read_raw_day(curve_name, trading_date)
            except Exception:
                continue
            if day_df is not None and not day_df.empty:
                day_frames.append(day_df)
        if day_frames:
            df = pd.concat(day_frames, ignore_index=True, sort=False)

    if df is None or df.empty or "timestamp_utc" not in df.columns:
        return set()

    present_keys = {
        ts_key
        for ts_key in (normalize_timestamp_utc_minute(value) for value in df["timestamp_utc"])
        if ts_key is not None
    }
    return present_keys & requested_key_set


def select_missing_curve_store_timestamps(
    store: Any,
    *,
    curve_name: str,
    timestamps: Sequence[dt.datetime],
) -> list[dt.datetime]:
    existing = read_existing_curve_store_timestamps(store, curve_name=curve_name, timestamps=timestamps)
    missing: list[dt.datetime] = []
    for timestamp in timestamps:
        ts_key = normalize_timestamp_utc_minute(timestamp)
        if ts_key is None or ts_key in existing:
            continue
        missing.append(timestamp)
    return missing


def safe_warm_raw_curves(
    mdp: Any,
    *,
    curve_name: str,
    timestamps: Sequence[dt.datetime],
    ignore_cache: bool,
    n_jobs: int,
    calibration_executor: str,
    show_tqdm: bool = False,
    auto_prime_bulk: bool = True,
    stirf_fetch_max_workers: int | None = None,
    calibration_max_workers: int | None = None,
    logger: logging.Logger | None = None,
) -> tuple[int, list[dt.datetime]]:
    timestamp_list = list(timestamps)
    if not timestamp_list:
        return 0, []

    def _run(batch: Sequence[dt.datetime], *, depth: int = 0) -> tuple[int, list[dt.datetime]]:
        batch_list = list(batch)
        request = build_bulk_request(
            curve_name=curve_name,
            timestamps=batch_list,
            n_jobs=n_jobs,
            show_tqdm=show_tqdm,
            ignore_cache=ignore_cache,
            calibration_executor=calibration_executor,
            auto_prime_bulk=auto_prime_bulk,
            stirf_fetch_max_workers=stirf_fetch_max_workers,
            calibration_max_workers=calibration_max_workers,
        )
        try:
            return len(mdp.bulk_get_data(request)), []
        except Exception as exc:
            if len(batch_list) == 1:
                if logger is not None:
                    logger.warning(
                        "RAW %s failed for timestamp=%s (%s)",
                        curve_name,
                        batch_list[0].isoformat(),
                        exc,
                    )
                return 0, batch_list
            if depth == 0 and logger is not None:
                logger.warning(
                    "RAW %s failed for %s timestamps (%s); retrying in smaller batches.",
                    curve_name,
                    len(batch_list),
                    exc,
                )
            midpoint = max(1, len(batch_list) // 2)
            left_count, left_failed = _run(batch_list[:midpoint], depth=depth + 1)
            right_count, right_failed = _run(batch_list[midpoint:], depth=depth + 1)
            return left_count + right_count, left_failed + right_failed

    return _run(timestamp_list)

