"""Bidirectional sync between local Forex Factory calendar Parquet and Supabase."""

from __future__ import annotations

import datetime
import hashlib
from pathlib import Path
from typing import Optional

import pyarrow.parquet as pq
from sqlalchemy import Engine, text

from Caching.timeseries_cache import _atomic_write_bytes

FOREX_FACTORY_CALENDAR_BLOCKS_TABLE = "arbs_forex_factory_calendar_blocks_v1"


class SupabaseForexFactoryCalendarSync:
    """Sync Forex Factory calendar day partitions with Supabase."""

    def __init__(self, base_dir: Path, engine: Optional[Engine]):
        self._base_dir = Path(base_dir)
        self._engine = engine

    @classmethod
    def from_defaults(
        cls,
        *,
        base_dir: Path | str | None = None,
    ) -> "SupabaseForexFactoryCalendarSync":
        from Caching.supabase_engine import get_engine
        from RVUtils.forex_factory_calendar import _default_core_base_dir

        resolved = Path(base_dir) if base_dir is not None else _default_core_base_dir()
        return cls(base_dir=resolved, engine=get_engine())

    def _partition_dir(self, trading_date: datetime.date) -> Path:
        return self._base_dir / f"date={trading_date.isoformat()}"

    def _local_parquet_bytes(self, trading_date: datetime.date) -> tuple[Optional[bytes], int]:
        part_dir = self._partition_dir(trading_date)
        pq_files = sorted(part_dir.glob("*.parquet"))
        if not pq_files:
            return None, 0
        payload = pq_files[0].read_bytes()
        table = pq.read_table(pq_files[0])
        return payload, int(table.num_rows)

    def push_day(self, trading_date: datetime.date) -> bool:
        if self._engine is None:
            return False
        from Caching.supabase_schema import ensure_schema

        if not ensure_schema(self._engine):
            return False

        payload, row_count = self._local_parquet_bytes(trading_date)
        if payload is None:
            return False

        sha = hashlib.sha256(payload).hexdigest()
        with self._engine.begin() as conn:
            conn.execute(
                text(f"""
                    INSERT INTO {FOREX_FACTORY_CALENDAR_BLOCKS_TABLE}
                        (trading_date, data_format, row_count, payload, sha256)
                    VALUES
                        (:trading_date, :data_format, :row_count, :payload, :sha256)
                    ON CONFLICT (trading_date) DO UPDATE SET
                        data_format = EXCLUDED.data_format,
                        row_count = EXCLUDED.row_count,
                        payload = EXCLUDED.payload,
                        sha256 = EXCLUDED.sha256,
                        created_at = NOW()
                """),
                {
                    "trading_date": trading_date,
                    "data_format": "parquet_zstd",
                    "row_count": row_count,
                    "payload": payload,
                    "sha256": sha,
                },
            )
        return True

    def pull_day(self, trading_date: datetime.date) -> bool:
        if self._engine is None:
            return False
        from Caching.supabase_schema import ensure_schema

        if not ensure_schema(self._engine):
            return False

        with self._engine.begin() as conn:
            row = conn.execute(
                text(f"""
                    SELECT payload, sha256, data_format
                    FROM {FOREX_FACTORY_CALENDAR_BLOCKS_TABLE}
                    WHERE trading_date = :trading_date
                """),
                {"trading_date": trading_date},
            ).fetchone()

        if row is None:
            return False

        part_dir = self._partition_dir(trading_date)
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
        return True

    def prefetch_range(
        self,
        start: datetime.date,
        end: datetime.date,
    ) -> list[datetime.date]:
        if self._engine is None:
            return []
        from Caching.supabase_schema import ensure_schema

        if not ensure_schema(self._engine):
            return []

        local_dates = set()
        current = start
        while current <= end:
            part_dir = self._partition_dir(current)
            if part_dir.exists() and any(part_dir.glob("*.parquet")):
                local_dates.add(current)
            current += datetime.timedelta(days=1)

        with self._engine.begin() as conn:
            rows = conn.execute(
                text(f"""
                    SELECT trading_date, payload, sha256
                    FROM {FOREX_FACTORY_CALENDAR_BLOCKS_TABLE}
                    WHERE trading_date BETWEEN :start AND :end
                    ORDER BY trading_date
                """),
                {"start": start, "end": end},
            ).fetchall()

        fetched: list[datetime.date] = []
        for row in rows:
            if row.trading_date in local_dates:
                continue
            part_dir = self._partition_dir(row.trading_date)
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
        return fetched
