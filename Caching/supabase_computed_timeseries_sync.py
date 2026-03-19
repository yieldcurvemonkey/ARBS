"""Bidirectional sync between local computed timeseries Parquet and Supabase."""

from __future__ import annotations

import datetime
import hashlib
import logging
from pathlib import Path
from typing import Optional, Sequence

import pandas as pd
from sqlalchemy import Engine, text

from Caching.timeseries_cache import _atomic_write_bytes, _df_to_table, _sanitize_symbol, _write_parquet_bytes, read_timeseries

logger = logging.getLogger(__name__)

COMPUTED_TIMESERIES_BLOCKS_TABLE = "arbs_computed_timeseries_blocks_v1"


class SupabaseComputedTimeseriesSync:
    """Sync computed timeseries Parquet partitions with Supabase day blocks."""

    def __init__(self, base_dir: Path, engine: Optional[Engine]):
        self._base_dir = Path(base_dir)
        self._engine = engine

    @classmethod
    def from_defaults(
        cls,
        *,
        base_dir: Path | str = "./data/ts",
    ) -> "SupabaseComputedTimeseriesSync":
        from Caching.supabase_engine import get_engine

        return cls(base_dir=Path(base_dir), engine=get_engine())

    def _partition_dir(self, symbol: str, trading_date: datetime.date) -> Path:
        return (
            self._base_dir
            / f"asset={_sanitize_symbol(symbol)}"
            / f"date={trading_date.isoformat()}"
        )

    def _local_day_frame(self, symbol: str, trading_date: datetime.date) -> pd.DataFrame:
        df = read_timeseries(
            None,
            symbol,
            start=trading_date,
            end=trading_date,
            base_dir=self._base_dir,
        )
        if df.empty:
            return pd.DataFrame()
        if isinstance(df.index, pd.DatetimeIndex):
            df = df.sort_index()
            if df.index.has_duplicates:
                df = df[~df.index.duplicated(keep="last")]
        return df

    def _local_parquet_bytes(
        self,
        symbol: str,
        trading_date: datetime.date,
    ) -> tuple[Optional[bytes], int]:
        df = self._local_day_frame(symbol, trading_date)
        if df.empty:
            return None, 0
        table = _df_to_table(df)
        payload = _write_parquet_bytes(table)
        return payload, int(len(df))

    def push_day(self, symbol: str, trading_date: datetime.date) -> bool:
        """Push a day's consolidated Parquet blob from local storage to Supabase."""
        if self._engine is None:
            return False
        from Caching.supabase_schema import ensure_schema

        if not ensure_schema(self._engine):
            return False

        payload, row_count = self._local_parquet_bytes(symbol, trading_date)
        if payload is None:
            return False

        sha = hashlib.sha256(payload).hexdigest()
        with self._engine.begin() as conn:
            conn.execute(
                text(f"""
                    INSERT INTO {COMPUTED_TIMESERIES_BLOCKS_TABLE}
                        (trading_date, symbol, data_format, row_count, payload, sha256)
                    VALUES
                        (:trading_date, :symbol, :data_format, :row_count, :payload, :sha256)
                    ON CONFLICT (trading_date, symbol) DO UPDATE SET
                        data_format = EXCLUDED.data_format,
                        row_count = EXCLUDED.row_count,
                        payload = EXCLUDED.payload,
                        sha256 = EXCLUDED.sha256,
                        created_at = NOW()
                """),
                {
                    "trading_date": trading_date,
                    "symbol": symbol,
                    "data_format": "parquet_zstd",
                    "row_count": row_count,
                    "payload": payload,
                    "sha256": sha,
                },
            )

        logger.info(
            "Pushed computed TS %s/%s to Supabase (%d rows, %d bytes)",
            symbol,
            trading_date,
            row_count,
            len(payload),
        )
        return True

    def pull_day(self, symbol: str, trading_date: datetime.date) -> bool:
        """Pull a day's Parquet blob from Supabase into local storage."""
        if self._engine is None:
            return False
        from Caching.supabase_schema import ensure_schema

        if not ensure_schema(self._engine):
            return False

        with self._engine.begin() as conn:
            row = conn.execute(
                text(f"""
                    SELECT payload, sha256, data_format
                    FROM {COMPUTED_TIMESERIES_BLOCKS_TABLE}
                    WHERE trading_date = :trading_date AND symbol = :symbol
                """),
                {"trading_date": trading_date, "symbol": symbol},
            ).fetchone()

        if row is None:
            return False

        part_dir = self._partition_dir(symbol, trading_date)
        part_dir.mkdir(parents=True, exist_ok=True)
        dest = part_dir / f"{row.sha256}.parquet"
        _atomic_write_bytes(dest, row.payload)
        for old_path in part_dir.glob("*.parquet"):
            if old_path == dest:
                continue
            try:
                old_path.unlink()
            except OSError:
                pass
        logger.info("Pulled computed TS %s/%s from Supabase -> %s", symbol, trading_date, dest)
        return True

    def prefetch_range(
        self,
        symbol: str,
        start: datetime.date,
        end: datetime.date,
    ) -> list[datetime.date]:
        """Download all missing local days for a symbol from Supabase."""
        if self._engine is None:
            return []
        from Caching.supabase_schema import ensure_schema

        if not ensure_schema(self._engine):
            return []

        local_dates = set()
        asset_dir = self._base_dir / f"asset={_sanitize_symbol(symbol)}"
        if asset_dir.exists():
            for d in asset_dir.iterdir():
                if d.name.startswith("date=") and any(d.glob("*.parquet")):
                    try:
                        dt = datetime.date.fromisoformat(d.name[5:])
                    except ValueError:
                        continue
                    if start <= dt <= end:
                        local_dates.add(dt)

        with self._engine.begin() as conn:
            rows = conn.execute(
                text(f"""
                    SELECT trading_date, payload, sha256
                    FROM {COMPUTED_TIMESERIES_BLOCKS_TABLE}
                    WHERE symbol = :symbol
                      AND trading_date BETWEEN :start AND :end
                    ORDER BY trading_date
                """),
                {"symbol": symbol, "start": start, "end": end},
            ).fetchall()

        fetched: list[datetime.date] = []
        for row in rows:
            if row.trading_date in local_dates:
                continue
            part_dir = self._partition_dir(symbol, row.trading_date)
            part_dir.mkdir(parents=True, exist_ok=True)
            dest = part_dir / f"{row.sha256}.parquet"
            _atomic_write_bytes(dest, row.payload)
            for old_path in part_dir.glob("*.parquet"):
                if old_path == dest:
                    continue
                try:
                    old_path.unlink()
                except OSError:
                    pass
            fetched.append(row.trading_date)

        logger.info(
            "Prefetched computed TS %s: %d/%d days downloaded (%d already local)",
            symbol,
            len(fetched),
            len(rows),
            len(local_dates),
        )
        return fetched

    # ---- Row-level sync (v2) ----

    ROWS_TABLE = "arbs_computed_timeseries_rows_v1"

    def push_rows(
        self,
        symbol: str,
        rows: Sequence[tuple[datetime.date, str, float]],
    ) -> bool:
        """Push individual (date, column_name, value) rows to Postgres."""
        if self._engine is None or not rows:
            return False
        from Caching.supabase_schema import ensure_schema

        if not ensure_schema(self._engine):
            return False

        with self._engine.begin() as conn:
            for trading_date, column_name, value in rows:
                conn.execute(
                    text(f"""
                        INSERT INTO {self.ROWS_TABLE}
                            (symbol, trading_date, column_name, value, updated_at)
                        VALUES
                            (:symbol, :trading_date, :column_name, :value, NOW())
                        ON CONFLICT (symbol, trading_date) DO UPDATE SET
                            column_name = EXCLUDED.column_name,
                            value = EXCLUDED.value,
                            updated_at = NOW()
                    """),
                    {
                        "symbol": symbol,
                        "trading_date": trading_date,
                        "column_name": column_name,
                        "value": value,
                    },
                )
        logger.info("Pushed %d rows for %s to %s", len(rows), symbol, self.ROWS_TABLE)
        return True

    def pull_rows(
        self,
        symbol: str,
        *,
        start: datetime.date,
        end: datetime.date,
        since: datetime.datetime | None = None,
    ) -> list[tuple[datetime.date, str, float, datetime.datetime]]:
        """Pull rows from Postgres. Returns list of (date, column_name, value, updated_at)."""
        if self._engine is None:
            return []
        from Caching.supabase_schema import ensure_schema

        if not ensure_schema(self._engine):
            return []

        params: dict = {
            "symbol": symbol,
            "start": start,
            "end": end,
        }
        since_clause = ""
        if since is not None:
            since_clause = "AND updated_at > :since"
            params["since"] = since

        with self._engine.begin() as conn:
            result = conn.execute(
                text(f"""
                    SELECT trading_date, column_name, value, updated_at
                    FROM {self.ROWS_TABLE}
                    WHERE symbol = :symbol
                      AND trading_date BETWEEN :start AND :end
                      {since_clause}
                    ORDER BY trading_date
                """),
                params,
            ).fetchall()

        return [
            (row.trading_date, row.column_name, row.value, row.updated_at)
            for row in result
        ]
