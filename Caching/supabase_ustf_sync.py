from __future__ import annotations

import datetime
import hashlib
import io
from pathlib import Path
from typing import Optional

import pyarrow.parquet as pq
from sqlalchemy import Engine, text

from Caching.timeseries_cache import _atomic_write_bytes, _sanitize_symbol

USTF_SNAPSHOT_BLOCKS_TABLE = "arbs_ustf_snapshot_blocks_v1"
USTF_BASIS_REPORT_BLOCKS_TABLE = "arbs_ustf_basis_report_blocks_v1"


class SupabaseUSTFutureSync:
    def __init__(self, base_dir: Path, engine: Optional[Engine]):
        self._base_dir = Path(base_dir)
        self._engine = engine

    @classmethod
    def from_defaults(cls) -> "SupabaseUSTFutureSync":
        from Caching.supabase_engine import get_engine
        from Caching.ust_future_store import USTFutureStore

        store = USTFutureStore.default()
        return cls(base_dir=store.base_dir, engine=get_engine())

    def _partition_dir(self, symbol: str, trading_date: datetime.date, *, kind: str) -> Path:
        root = "snapshots" if kind == "snapshot" else "basis_reports"
        return self._base_dir / root / f"asset={_sanitize_symbol(symbol)}" / f"date={trading_date.isoformat()}"

    def _table_name(self, *, kind: str) -> str:
        return USTF_SNAPSHOT_BLOCKS_TABLE if kind == "snapshot" else USTF_BASIS_REPORT_BLOCKS_TABLE

    def _local_parquet_bytes(self, symbol: str, trading_date: datetime.date, *, kind: str) -> tuple[Optional[bytes], int]:
        part_dir = self._partition_dir(symbol, trading_date, kind=kind)
        pq_files = sorted(part_dir.glob("*.parquet"))
        if not pq_files:
            return None, 0
        payload = pq_files[-1].read_bytes()
        row_count = pq.read_table(io.BytesIO(payload)).num_rows
        return payload, int(row_count)

    def _push_day(self, symbol: str, trading_date: datetime.date, *, kind: str) -> bool:
        if self._engine is None:
            return False
        from Caching.supabase_schema import ensure_schema

        if not ensure_schema(self._engine):
            return False

        payload, row_count = self._local_parquet_bytes(symbol, trading_date, kind=kind)
        if payload is None:
            return False
        sha = hashlib.sha256(payload).hexdigest()
        table_name = self._table_name(kind=kind)

        with self._engine.begin() as conn:
            conn.execute(
                text(f"""
                    INSERT INTO {table_name}
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
        return True

    def _pull_day(self, symbol: str, trading_date: datetime.date, *, kind: str) -> bool:
        if self._engine is None:
            return False
        from Caching.supabase_schema import ensure_schema

        if not ensure_schema(self._engine):
            return False

        table_name = self._table_name(kind=kind)
        with self._engine.begin() as conn:
            row = conn.execute(
                text(f"""
                    SELECT payload, sha256, data_format
                    FROM {table_name}
                    WHERE trading_date = :trading_date AND symbol = :symbol
                """),
                {"trading_date": trading_date, "symbol": symbol},
            ).fetchone()
        if row is None:
            return False

        part_dir = self._partition_dir(symbol, trading_date, kind=kind)
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

    def _prefetch_range(self, symbol: str, start: datetime.date, end: datetime.date, *, kind: str) -> list[datetime.date]:
        if self._engine is None:
            return []
        from Caching.supabase_schema import ensure_schema

        if not ensure_schema(self._engine):
            return []

        local_dates = set()
        root = self._base_dir / ("snapshots" if kind == "snapshot" else "basis_reports") / f"asset={_sanitize_symbol(symbol)}"
        if root.exists():
            for path in root.iterdir():
                if path.name.startswith("date=") and any(path.glob("*.parquet")):
                    try:
                        local_date = datetime.date.fromisoformat(path.name[5:])
                    except ValueError:
                        continue
                    if start <= local_date <= end:
                        local_dates.add(local_date)

        table_name = self._table_name(kind=kind)
        with self._engine.begin() as conn:
            rows = conn.execute(
                text(f"""
                    SELECT trading_date, payload, sha256
                    FROM {table_name}
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
            part_dir = self._partition_dir(symbol, row.trading_date, kind=kind)
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

    def push_snapshot_day(self, symbol: str, trading_date: datetime.date) -> bool:
        return self._push_day(symbol, trading_date, kind="snapshot")

    def pull_snapshot_day(self, symbol: str, trading_date: datetime.date) -> bool:
        return self._pull_day(symbol, trading_date, kind="snapshot")

    def prefetch_snapshot_range(self, symbol: str, start: datetime.date, end: datetime.date) -> list[datetime.date]:
        return self._prefetch_range(symbol, start, end, kind="snapshot")

    def push_basis_report_day(self, symbol: str, trading_date: datetime.date) -> bool:
        return self._push_day(symbol, trading_date, kind="basis_report")

    def pull_basis_report_day(self, symbol: str, trading_date: datetime.date) -> bool:
        return self._pull_day(symbol, trading_date, kind="basis_report")

    def prefetch_basis_report_range(self, symbol: str, start: datetime.date, end: datetime.date) -> list[datetime.date]:
        return self._prefetch_range(symbol, start, end, kind="basis_report")
