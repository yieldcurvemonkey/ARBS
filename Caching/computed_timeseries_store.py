from __future__ import annotations

import datetime
import logging
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, Iterable, List, Mapping, Optional, Sequence, Tuple, Union

import pandas as pd

from Caching.timeseries_cache import WriteOptions, append_timeseries, append_timeseries_many, read_timeseries

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
        use_duckdb: bool = True,
        duckdb_path: Optional[str] = None,
    ) -> None:
        self._opts = WriteOptions(
            base_dir=str(base_dir),
            compression=compression,
            row_group_size=int(row_group_size),
        )
        self._duckdb_cache: Optional["DuckDBTimeseriesCache"] = None
        if use_duckdb:
            from Caching.duckdb_timeseries_cache import DuckDBTimeseriesCache

            resolved_duckdb_path = duckdb_path or str(Path(self._opts.base_dir) / "computed_ts.duckdb")
            self._duckdb_cache = DuckDBTimeseriesCache(db_path=resolved_duckdb_path)

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

    def _read_from_duckdb(
        self,
        *,
        symbol: str,
        reference_points: Sequence[DateLike],
        intraday: bool,
        skip_current_eod: bool,
        fallback_column_name: str | None,
    ) -> List[Tuple[DateLike, str, float]] | None:
        """Try DuckDB fast path. Returns rows or None if DuckDB unavailable."""
        if self._duckdb_cache is None:
            return None
        # DuckDB table stores one row per (symbol, date) — not suitable for intraday
        if intraday:
            return None

        start = min(reference_points)
        end = max(reference_points)
        start_date = _normalize_intraday_key(start).date() if intraday else _normalize_eod_key(start)
        end_date = _normalize_intraday_key(end).date() if intraday else _normalize_eod_key(end)

        duckdb_rows = self._duckdb_cache.read_rows(symbol, start=start_date, end=end_date)
        if not duckdb_rows:
            return None

        today = datetime.date.today()
        result: List[Tuple[DateLike, str, float]] = []
        by_date = {row[0]: (row[1], row[2]) for row in duckdb_rows}

        for ref_point in reference_points:
            key = _normalize_eod_key(ref_point) if not intraday else _normalize_intraday_key(ref_point).date()
            if (not intraday) and skip_current_eod and key == today:
                continue
            hit = by_date.get(key)
            if hit is not None:
                col_name, value = hit
                result.append((ref_point, col_name, value))

        return result if result else None

    def _sync_missing_from_postgres(
        self,
        *,
        symbol: str,
        missing_dates: list[datetime.date],
    ) -> bool:
        """Pull missing rows from Postgres into local DuckDB."""
        if self._duckdb_cache is None or not missing_dates:
            return False
        sync = _get_computed_ts_sync(self._opts.base_dir)
        if sync is None:
            return False
        if not hasattr(sync, "pull_rows"):
            return False

        try:
            start = min(missing_dates)
            end = max(missing_dates)
            watermark = self._duckdb_cache.get_watermark(symbol)
            pulled = sync.pull_rows(
                symbol,
                start=start,
                end=end,
                since=watermark,
            )
            if not pulled:
                return False
            rows = [(r[0], r[1], r[2]) for r in pulled]
            self._duckdb_cache.upsert_rows(symbol, rows)
            max_updated = max(r[3] for r in pulled)
            self._duckdb_cache.set_watermark(symbol, max_updated)
            return True
        except Exception:
            logger.warning("DuckDB sync from Postgres failed for %s", symbol, exc_info=True)
            return False

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

        # DuckDB fast path
        duckdb_result = self._read_from_duckdb(
            symbol=symbol,
            reference_points=reference_points,
            intraday=intraday,
            skip_current_eod=skip_current_eod,
            fallback_column_name=fallback_column_name,
        )
        today = datetime.date.today()
        requested = {
            _normalize_eod_key(rp) if not intraday else _normalize_intraday_key(rp).date()
            for rp in reference_points
            if not ((not intraday) and skip_current_eod and _normalize_eod_key(rp) == today)
        }

        if duckdb_result is not None:
            covered = {
                (_normalize_eod_key(rp) if not intraday else _normalize_intraday_key(rp).date())
                for rp, _, _ in duckdb_result
            }
            if covered >= requested:
                return duckdb_result
            missing_dates = sorted({
                (d.date() if isinstance(d, pd.Timestamp) else d)
                for d in (requested - covered)
            })
        else:
            missing_dates = sorted({
                (d.date() if isinstance(d, pd.Timestamp) else d)
                for d in requested
            })

        # Try syncing missing dates from Postgres into DuckDB
        if self._duckdb_cache is not None and missing_dates:
            synced = self._sync_missing_from_postgres(
                symbol=symbol,
                missing_dates=missing_dates,
            )
            if synced:
                duckdb_result_2 = self._read_from_duckdb(
                    symbol=symbol,
                    reference_points=reference_points,
                    intraday=intraday,
                    skip_current_eod=skip_current_eod,
                    fallback_column_name=fallback_column_name,
                )
                if duckdb_result_2 is not None:
                    covered_2 = {
                        (_normalize_eod_key(rp) if not intraday else _normalize_intraday_key(rp).date())
                        for rp, _, _ in duckdb_result_2
                    }
                    if covered_2 >= requested:
                        return duckdb_result_2

        # Fallback to existing Parquet path
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

    def _push_rows_to_l2(
        self,
        *,
        symbol: str,
        rows: list[Tuple[DateLike, str, float]],
    ) -> None:
        sync = _get_computed_ts_sync(self._opts.base_dir)
        if sync is None or not rows or not hasattr(sync, "push_rows"):
            return
        row_data = [
            (_normalize_eod_key(ref_point), str(column_name), float(value))
            for ref_point, column_name, value in rows
        ]

        def _bg_push_rows() -> None:
            try:
                sync.push_rows(symbol, row_data)
            except Exception:
                logger.warning("Row-level L2 push failed for %s", symbol, exc_info=True)

        threading.Thread(target=_bg_push_rows, daemon=True).start()

    def _push_many_days_to_l2(
        self,
        *,
        trading_dates_by_symbol: Mapping[str, Sequence[datetime.date]],
    ) -> None:
        sync = _get_computed_ts_sync(self._opts.base_dir)
        if sync is None or not trading_dates_by_symbol:
            return

        normalized = {
            symbol: sorted(set(trading_dates))
            for symbol, trading_dates in trading_dates_by_symbol.items()
            if trading_dates
        }
        if not normalized:
            return

        def _bg_push() -> None:
            for symbol, trading_dates in normalized.items():
                for trading_date in trading_dates:
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

    def _push_many_rows_to_l2(
        self,
        *,
        rows_by_symbol: Mapping[str, Sequence[Tuple[DateLike, str, float]]],
    ) -> None:
        sync = _get_computed_ts_sync(self._opts.base_dir)
        if sync is None or not rows_by_symbol or not hasattr(sync, "push_rows"):
            return

        normalized = {
            symbol: [
                (_normalize_eod_key(ref_point), str(column_name), float(value))
                for ref_point, column_name, value in rows
            ]
            for symbol, rows in rows_by_symbol.items()
            if rows
        }
        if not normalized:
            return

        def _bg_push_rows() -> None:
            for symbol, row_data in normalized.items():
                try:
                    sync.push_rows(symbol, row_data)
                except Exception:
                    logger.warning("Row-level L2 push failed for %s", symbol, exc_info=True)

        threading.Thread(target=_bg_push_rows, daemon=True).start()

    @staticmethod
    def _normalize_symbol_rows(
        rows: Iterable[Tuple[DateLike, str, float]],
    ) -> list[Tuple[pd.Timestamp, str, float]]:
        ordered: dict[pd.Timestamp, Tuple[str, float]] = {}
        for ref_point, column_name, value in rows:
            ordered[_normalize_intraday_key(ref_point)] = (str(column_name), float(value))
        return [(ts, col, val) for ts, (col, val) in ordered.items()]

    def append_rows(
        self,
        *,
        symbol: str,
        rows: Iterable[Tuple[DateLike, str, float]],
    ) -> None:
        self.append_many_rows(rows_by_symbol={symbol: rows})

    def append_many_rows(
        self,
        *,
        rows_by_symbol: Mapping[str, Iterable[Tuple[DateLike, str, float]]],
    ) -> None:
        normalized_by_symbol = {
            symbol: self._normalize_symbol_rows(rows)
            for symbol, rows in rows_by_symbol.items()
        }
        normalized_by_symbol = {
            symbol: rows
            for symbol, rows in normalized_by_symbol.items()
            if rows
        }
        if not normalized_by_symbol:
            return

        frame_items = []
        duckdb_rows_by_symbol: dict[str, list[Tuple[datetime.date, str, float]]] = {}
        trading_dates_by_symbol: dict[str, list[datetime.date]] = {}
        l2_rows_by_symbol: dict[str, list[Tuple[DateLike, str, float]]] = {}

        for symbol, normalized_rows in normalized_by_symbol.items():
            index = pd.DatetimeIndex([ts for ts, _col, _val in normalized_rows])
            df = pd.DataFrame(
                {
                    "value": [val for _ts, _col, val in normalized_rows],
                    "_column_name": [col for _ts, col, _val in normalized_rows],
                },
                index=index,
            ).sort_index()
            frame_items.append((symbol, df, None))

            duckdb_rows = [
                (_normalize_eod_key(ts.to_pydatetime()), str(col), float(val))
                for ts, col, val in normalized_rows
            ]
            duckdb_rows_by_symbol[symbol] = duckdb_rows
            trading_dates_by_symbol[symbol] = [ts.date() for ts, _col, _val in normalized_rows]
            l2_rows_by_symbol[symbol] = [
                (ts.to_pydatetime(), col, val)
                for ts, col, val in normalized_rows
            ]

        append_timeseries_many(
            None,
            frame_items,
            opts=self._opts,
        )

        if self._duckdb_cache is not None:
            try:
                self._duckdb_cache.upsert_many_rows(duckdb_rows_by_symbol)
            except Exception:
                logger.warning("DuckDB bulk upsert failed", exc_info=True)

        self._push_many_days_to_l2(trading_dates_by_symbol=trading_dates_by_symbol)
        self._push_many_rows_to_l2(rows_by_symbol=l2_rows_by_symbol)
