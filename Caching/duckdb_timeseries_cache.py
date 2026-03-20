"""DuckDBTimeseriesCache: persistent local store for computed timeseries.

Provides sub-millisecond reads for cross-date panel queries by storing
timeseries rows in a local DuckDB database file. Designed as L1 in the
CORE (Compute Once, Read Everywhere) pattern, with sync from Postgres L2.
"""

from __future__ import annotations

import datetime
import logging
import os
import threading
from pathlib import Path
from typing import List, Mapping, Optional, Sequence, Tuple

import duckdb

logger = logging.getLogger(__name__)

_DEFAULT_DB_DIR_NAME = "duckdb_ts"


def _default_db_path() -> str:
    cache_dir = os.environ.get("ARBS_CACHE_DIR")
    if cache_dir:
        base = Path(cache_dir)
    else:
        try:
            from platformdirs import user_cache_dir
            base = Path(user_cache_dir(appname="ARBS", appauthor=False))
        except Exception:
            if os.name == "nt":
                base = Path(os.getenv("LOCALAPPDATA", str(Path.home()))) / "ARBS"
            else:
                base = Path.home() / ".cache" / "arbs"
    db_dir = base / _DEFAULT_DB_DIR_NAME
    db_dir.mkdir(parents=True, exist_ok=True)
    return str(db_dir / "computed_ts.duckdb")


_INIT_SQL = """
CREATE TABLE IF NOT EXISTS computed_timeseries (
    symbol        VARCHAR   NOT NULL,
    trading_date  DATE      NOT NULL,
    column_name   VARCHAR   NOT NULL,
    value         DOUBLE    NOT NULL,
    synced_at     TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (symbol, trading_date)
);

CREATE TABLE IF NOT EXISTS sync_watermarks (
    symbol        VARCHAR   PRIMARY KEY,
    last_synced   TIMESTAMP NOT NULL,
    row_count     INTEGER   NOT NULL DEFAULT 0
);
"""


class DuckDBTimeseriesCache:
    """Persistent local DuckDB store for computed timeseries rows."""

    def __init__(self, db_path: Optional[str] = None) -> None:
        self._db_path = db_path or os.environ.get("ARBS_DUCKDB_PATH") or _default_db_path()
        Path(self._db_path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = duckdb.connect(self._db_path)
        self._lock = threading.Lock()
        self._init_schema()

    def _init_schema(self) -> None:
        with self._lock:
            self._conn.execute(_INIT_SQL)

    def close(self) -> None:
        with self._lock:
            if self._conn is not None:
                self._conn.close()
                self._conn = None

    def upsert_rows(
        self,
        symbol: str,
        rows: Sequence[Tuple[datetime.date, str, float]],
    ) -> int:
        """Insert or update rows. Returns count of rows upserted."""
        return self.upsert_many_rows({symbol: rows})

    def upsert_many_rows(
        self,
        rows_by_symbol: Mapping[str, Sequence[Tuple[datetime.date, str, float]]],
    ) -> int:
        """Insert or update rows for multiple symbols in one transaction."""
        payload = [
            [symbol, trading_date, column_name, value]
            for symbol, rows in rows_by_symbol.items()
            for trading_date, column_name, value in rows
        ]
        if not payload:
            return 0

        with self._lock:
            self._conn.execute("BEGIN TRANSACTION")
            try:
                self._conn.executemany(
                    """
                    INSERT OR REPLACE INTO computed_timeseries (symbol, trading_date, column_name, value, synced_at)
                    VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)
                    """,
                    payload,
                )
                self._conn.execute("COMMIT")
            except Exception:
                self._conn.execute("ROLLBACK")
                raise
        return len(payload)

    def read_rows(
        self,
        symbol: str,
        *,
        start: datetime.date,
        end: datetime.date,
    ) -> List[Tuple[datetime.date, str, float]]:
        """Read rows for a symbol in a date range. Returns list of (date, column_name, value)."""
        with self._lock:
            result = self._conn.execute(
                """
                SELECT trading_date, column_name, value
                FROM computed_timeseries
                WHERE symbol = ? AND trading_date BETWEEN ? AND ?
                ORDER BY trading_date
                """,
                [symbol, start, end],
            ).fetchall()
        return [(row[0], row[1], row[2]) for row in result]

    def has_symbol(self, symbol: str) -> bool:
        with self._lock:
            result = self._conn.execute(
                "SELECT 1 FROM computed_timeseries WHERE symbol = ? LIMIT 1",
                [symbol],
            ).fetchone()
        return result is not None

    def get_watermark(self, symbol: str) -> Optional[datetime.datetime]:
        with self._lock:
            row = self._conn.execute(
                "SELECT last_synced FROM sync_watermarks WHERE symbol = ?",
                [symbol],
            ).fetchone()
        return row[0] if row else None

    def set_watermark(self, symbol: str, ts: datetime.datetime) -> None:
        with self._lock:
            count_row = self._conn.execute(
                "SELECT COUNT(*) FROM computed_timeseries WHERE symbol = ?",
                [symbol],
            ).fetchone()
            row_count = count_row[0] if count_row else 0
            self._conn.execute(
                """
                INSERT INTO sync_watermarks (symbol, last_synced, row_count)
                VALUES (?, ?, ?)
                ON CONFLICT (symbol)
                DO UPDATE SET last_synced = EXCLUDED.last_synced,
                              row_count = EXCLUDED.row_count
                """,
                [symbol, ts, row_count],
            )

    @property
    def db_path(self) -> str:
        return self._db_path
