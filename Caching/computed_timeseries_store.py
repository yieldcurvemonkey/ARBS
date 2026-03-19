from __future__ import annotations

import datetime
import logging
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, List, Sequence, Tuple, Union

import pandas as pd

from Caching.timeseries_cache import WriteOptions, append_timeseries, read_timeseries

DateLike = Union[datetime.date, datetime.datetime]

logger = logging.getLogger(__name__)


def _normalize_intraday_key(value: DateLike) -> pd.Timestamp:
    ts = pd.Timestamp(value)
    if ts.tzinfo is not None:
        ts = ts.tz_convert("UTC").tz_localize(None)
    return ts


def _normalize_eod_key(value: DateLike) -> datetime.date:
    if isinstance(value, datetime.datetime):
        return value.date()
    return value


@dataclass(frozen=True)
class CachedTimeseriesRow:
    ref_point: DateLike
    column_name: str
    value: float


def _get_computed_ts_sync(base_dir: Union[str, Path]):
    from Caching.supabase_engine import SUPABASE_ENABLED

    if not SUPABASE_ENABLED:
        return None

    from Caching.supabase_computed_timeseries_sync import SupabaseComputedTimeseriesSync
    from Caching.supabase_engine import get_engine

    return SupabaseComputedTimeseriesSync(base_dir=Path(base_dir), engine=get_engine())


class ComputedTimeseriesStore:
    def __init__(
        self,
        *,
        base_dir: Union[str, Path] = "./data/ts",
        compression: str = "zstd",
        row_group_size: int = 256_000,
    ) -> None:
        self._opts = WriteOptions(
            base_dir=str(base_dir),
            compression=compression,
            row_group_size=int(row_group_size),
        )

    @property
    def write_options(self) -> WriteOptions:
        return self._opts

    def _read_df(
        self,
        *,
        symbol: str,
        start: DateLike,
        end: DateLike,
    ) -> pd.DataFrame:
        return read_timeseries(
            None,
            symbol,
            start=start,
            end=end,
            columns=None,
            base_dir=self._opts.base_dir,
        )

    def _rows_from_df(
        self,
        *,
        df: pd.DataFrame,
        reference_points: Sequence[DateLike],
        intraday: bool,
        skip_current_eod: bool,
        fallback_column_name: str | None,
    ) -> List[Tuple[DateLike, str, float]]:
        if df.empty:
            return []

        if not isinstance(df.index, pd.DatetimeIndex):
            for candidate in ("Date", "date", "timestamp", "_index_ts"):
                if candidate not in df.columns:
                    continue
                candidate_index = pd.to_datetime(df[candidate], errors="coerce")
                if candidate_index.notna().any():
                    df = df.copy()
                    df.index = candidate_index
                    break

        if not isinstance(df.index, pd.DatetimeIndex):
            return []

        if df.index.hasnans:
            df = df.loc[~df.index.isna()].copy()
        if df.empty:
            return []

        numeric_cols = [c for c in df.columns if pd.api.types.is_numeric_dtype(df[c])]
        if not numeric_cols:
            return []

        value_col = "value" if "value" in numeric_cols else numeric_cols[0]
        has_column_name = "_column_name" in df.columns

        if intraday:
            by_key = {
                _normalize_intraday_key(ts): (
                    str(row["_column_name"]) if has_column_name and pd.notna(row["_column_name"]) else str(fallback_column_name or value_col),
                    float(row[value_col]),
                )
                for ts, row in df.iterrows()
                if pd.notna(row[value_col])
            }
        else:
            by_key = {
                _normalize_eod_key(ts.to_pydatetime() if hasattr(ts, "to_pydatetime") else ts): (
                    str(row["_column_name"]) if has_column_name and pd.notna(row["_column_name"]) else str(fallback_column_name or value_col),
                    float(row[value_col]),
                )
                for ts, row in df.iterrows()
                if pd.notna(row[value_col])
            }

        today = datetime.date.today()
        rows: List[Tuple[DateLike, str, float]] = []
        for ref_point in reference_points:
            if (not intraday) and skip_current_eod and (_normalize_eod_key(ref_point) == today):
                continue
            key = _normalize_intraday_key(ref_point) if intraday else _normalize_eod_key(ref_point)
            hit = by_key.get(key)
            if hit is None:
                continue
            col_name, value = hit
            rows.append((ref_point, col_name, value))
        return rows

    def _prefetch_remote_range(
        self,
        *,
        symbol: str,
        start_date: datetime.date,
        end_date: datetime.date,
    ) -> Any:
        sync = _get_computed_ts_sync(self._opts.base_dir)
        if sync is None:
            return None
        try:
            sync.prefetch_range(symbol, start_date, end_date)
        except Exception:
            logger.warning("Computed TS L2 prefetch failed for %s", symbol, exc_info=True)
        return sync

    def read_rows(
        self,
        *,
        symbol: str,
        reference_points: Sequence[DateLike],
        intraday: bool,
        skip_current_eod: bool = True,
        fallback_column_name: str | None = None,
    ) -> List[Tuple[DateLike, str, float]]:
        if not reference_points:
            return []

        start = min(reference_points)
        end = max(reference_points)
        read_start: DateLike = _normalize_intraday_key(start).to_pydatetime() if intraday else start
        read_end: DateLike = _normalize_intraday_key(end).to_pydatetime() if intraday else end
        start_date = _normalize_intraday_key(start).date() if intraday else _normalize_eod_key(start)
        end_date = _normalize_intraday_key(end).date() if intraday else _normalize_eod_key(end)

        sync = self._prefetch_remote_range(symbol=symbol, start_date=start_date, end_date=end_date)
        df = self._read_df(symbol=symbol, start=read_start, end=read_end)
        rows = self._rows_from_df(
            df=df,
            reference_points=reference_points,
            intraday=intraday,
            skip_current_eod=skip_current_eod,
            fallback_column_name=fallback_column_name,
        )
        local_present_dates = {
            _normalize_eod_key(ts.to_pydatetime() if hasattr(ts, "to_pydatetime") else ts)
            for ts in (df.index if isinstance(df.index, pd.DatetimeIndex) else [])
        }

        if sync is None:
            return rows

        skipped_keys = {
            (_normalize_intraday_key(ref_point) if intraday else _normalize_eod_key(ref_point))
            for ref_point in reference_points
            if (not intraday) and skip_current_eod and (_normalize_eod_key(ref_point) == datetime.date.today())
        }
        requested_keys = {
            (_normalize_intraday_key(ref_point) if intraday else _normalize_eod_key(ref_point))
            for ref_point in reference_points
            if (_normalize_intraday_key(ref_point) if intraday else _normalize_eod_key(ref_point)) not in skipped_keys
        }
        covered_keys = {
            (_normalize_intraday_key(ref_point) if intraday else _normalize_eod_key(ref_point))
            for ref_point, _col, _value in rows
        }
        missing_dates = sorted({
            key.date() if isinstance(key, pd.Timestamp) else key
            for key in (requested_keys - covered_keys)
        })
        if not missing_dates:
            return rows

        candidate_pull_dates = [trading_date for trading_date in missing_dates if trading_date in local_present_dates]
        if not candidate_pull_dates:
            return rows

        pulled_any = False
        for trading_date in candidate_pull_dates:
            try:
                pulled_any = sync.pull_day(symbol, trading_date) or pulled_any
            except Exception:
                logger.warning(
                    "Computed TS L2 pull failed for %s/%s",
                    symbol,
                    trading_date,
                    exc_info=True,
                )
        if not pulled_any:
            return rows

        df = self._read_df(symbol=symbol, start=read_start, end=read_end)
        return self._rows_from_df(
            df=df,
            reference_points=reference_points,
            intraday=intraday,
            skip_current_eod=skip_current_eod,
            fallback_column_name=fallback_column_name,
        )

    def _push_days_to_l2(
        self,
        *,
        symbol: str,
        trading_dates: Sequence[datetime.date],
    ) -> None:
        sync = _get_computed_ts_sync(self._opts.base_dir)
        if sync is None or not trading_dates:
            return

        unique_dates = sorted(set(trading_dates))

        def _bg_push() -> None:
            for trading_date in unique_dates:
                try:
                    sync.push_day(symbol, trading_date)
                except Exception:
                    logger.warning(
                        "Computed TS L2 push failed for %s/%s",
                        symbol,
                        trading_date,
                        exc_info=True,
                    )

        threading.Thread(target=_bg_push, daemon=True).start()

    def append_rows(
        self,
        *,
        symbol: str,
        rows: Iterable[Tuple[DateLike, str, float]],
    ) -> None:
        normalized_rows = list(rows)
        if not normalized_rows:
            return

        ordered: dict[pd.Timestamp, Tuple[str, float]] = {}
        for ref_point, column_name, value in normalized_rows:
            ordered[_normalize_intraday_key(ref_point)] = (str(column_name), float(value))

        index = pd.DatetimeIndex(list(ordered.keys()))
        df = pd.DataFrame(
            {
                "value": [item[1] for item in ordered.values()],
                "_column_name": [item[0] for item in ordered.values()],
            },
            index=index,
        ).sort_index()

        append_timeseries(
            None,
            symbol,
            df,
            opts=self._opts,
        )
        self._push_days_to_l2(
            symbol=symbol,
            trading_dates=[ts.date() for ts in ordered.keys()],
        )
