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

    def __init__(self, db_path: Optional[str] = None, *, read_only: bool = False) -> None:
        self._db_path = db_path or os.environ.get("ARBS_DUCKDB_PATH") or _default_db_path()
        self._read_only = read_only
        Path(self._db_path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = duckdb.connect(self._db_path, read_only=read_only)
        self._lock = threading.Lock()
        if not read_only:
            self._init_schema()

    def _init_schema(self) -> None:
        with self._lock:
            self._conn.execute(_INIT_SQL)

    def close(self) -> None:
        with self._lock:
            if self._conn is not None:
                self._conn.close()
                self._conn = None

    @property
    def read_only(self) -> bool:
        return self._read_only

    def _warn_read_only(self, n_rows: int) -> None:
        """Say ONCE that this process is dropping every mirror write.

        A read-only handle returns 0 from both upserts and raises nothing, so the
        caller's ``try/except`` never fires and nothing is logged. That is how the
        mirror came to hold no rows before 2012 for symbols whose Parquet reaches
        back to 2006: the run that built them opened the file while another
        process held the write lock, wrote Parquet, and skipped the mirror in
        silence. Fourteen committed notebooks carry the matching "DuckDB
        unavailable (file locked)" line in their saved output.

        This is the CAUSE of the short-mirror defect fixed in the reader; the
        reader now repairs a short answer, and this stops the next process
        creating one without saying so.

        Once per handle, not per call: a warm upserts thousands of times and a
        per-write warning is a log nobody reads.
        """
        if getattr(self, "_read_only_warned", False):
            return
        self._read_only_warned = True
        logger.warning(
            "DuckDB mirror is OPEN READ-ONLY (%s): this process will write "
            "nothing to it - %d row(s) dropped on the first attempt and every "
            "later one. Parquet is unaffected, so no data is lost, but the "
            "mirror will fall behind and later reads pay Parquet to repair it. "
            "Another process holds the write lock; a warm is the usual one.",
            self._db_path, n_rows,
        )

    def upsert_rows(
        self,
        symbol: str,
        rows: Sequence[Tuple[datetime.date, str, float]],
    ) -> int:
        """Insert or update rows. Returns count of rows upserted. No-op when read_only."""
        if self._read_only:
            self._warn_read_only(len(rows))
            return 0
        return self.upsert_many_rows({symbol: rows})

    def upsert_many_rows(
        self,
        rows_by_symbol: Mapping[str, Sequence[Tuple[datetime.date, str, float]]],
    ) -> int:
        """Insert or update rows for multiple symbols in one transaction. No-op when read_only.

        ONE set-based statement, not ``executemany``
        --------------------------------------------
        This used to issue one ``INSERT OR REPLACE`` per row. DuckDB is a columnar
        analytical engine and row-at-a-time DML is its worst case: every statement
        probes a primary-key index that is itself growing, so the cost is
        super-linear in the payload AND grows with the table.

        Measured against a copy of the real 700k-row table:

        =========  =============  ===========  =========
        rows       executemany    set-based    speedup
        =========  =============  ===========  =========
        2,000          16.22 s       0.03 s        478x
        8,000         272.90 s       0.06 s      4,885x
        17,000        751.19 s       0.07 s     11,553x
        =========  =============  ===========  =========

        8.5x the rows cost 46x the time. That is what turned a ten-year UST warm
        into a month-long one: py-spy put the live process here, and its rate had
        decayed from 28 to 72 minutes per chunk as the table grew, with **12.5
        minutes of every chunk inside this one call**.

        The payload is de-duplicated on the primary key keeping the LAST
        occurrence, because that is what ``executemany`` did - it applied rows in
        order, so a repeated key ended up at its final value. A set-based
        statement has no such ordering, so the dedupe is what preserves the
        semantics rather than picking arbitrarily.

        Verified equivalent to the old path on separate databases across fresh
        inserts, updating an existing key, the same key twice, many symbols at
        once, and a replacement carrying a different ``column_name``.
        """
        if self._read_only:
            self._warn_read_only(sum(len(r) for r in rows_by_symbol.values()))
            return 0
        payload = [
            (symbol, trading_date, column_name, value)
            for symbol, rows in rows_by_symbol.items()
            for trading_date, column_name, value in rows
        ]
        if not payload:
            return 0

        import pandas as pd

        frame = pd.DataFrame(
            payload, columns=["symbol", "trading_date", "column_name", "value"]
        ).drop_duplicates(subset=["symbol", "trading_date"], keep="last")

        with self._lock:
            # A registered name is connection-global, so it is unregistered in a
            # finally: leaving it behind would shadow a real table of the same
            # name for every later query on this connection.
            self._conn.register("_upsert_payload", frame)
            try:
                self._conn.execute("BEGIN TRANSACTION")
                try:
                    self._conn.execute(
                        """
                        INSERT OR REPLACE INTO computed_timeseries
                            (symbol, trading_date, column_name, value, synced_at)
                        SELECT symbol, trading_date, column_name, value, CURRENT_TIMESTAMP
                        FROM _upsert_payload
                        """
                    )
                    self._conn.execute("COMMIT")
                except Exception:
                    self._conn.execute("ROLLBACK")
                    raise
            finally:
                self._conn.unregister("_upsert_payload")
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

    def read_many_symbols(
        self,
        symbols: Sequence[str],
        *,
        start: datetime.date,
        end: datetime.date,
    ) -> Mapping[str, List[Tuple[datetime.date, str, float]]]:
        """Read rows for multiple symbols in one query. Returns {symbol: [(date, col, val), ...]}."""
        if not symbols:
            return {}
        result_map: dict[str, List[Tuple[datetime.date, str, float]]] = {s: [] for s in symbols}
        placeholders = ", ".join("?" for _ in symbols)
        with self._lock:
            rows = self._conn.execute(
                f"""
                SELECT symbol, trading_date, column_name, value
                FROM computed_timeseries
                WHERE symbol IN ({placeholders})
                  AND trading_date BETWEEN ? AND ?
                ORDER BY symbol, trading_date
                """,
                [*symbols, start, end],
            ).fetchall()
        for row in rows:
            sym = row[0]
            if sym in result_map:
                result_map[sym].append((row[1], row[2], row[3]))
        return result_map

    def has_symbol(self, symbol: str) -> bool:
        with self._lock:
            result = self._conn.execute(
                "SELECT 1 FROM computed_timeseries WHERE symbol = ? LIMIT 1",
                [symbol],
            ).fetchone()
        return result is not None

    def has_many_symbols(self, symbols: Sequence[str]) -> Mapping[str, bool]:
        """Check existence of multiple symbols in one query."""
        if not symbols:
            return {}
        placeholders = ", ".join("?" for _ in symbols)
        with self._lock:
            rows = self._conn.execute(
                f"SELECT DISTINCT symbol FROM computed_timeseries WHERE symbol IN ({placeholders})",
                list(symbols),
            ).fetchall()
        found = {row[0] for row in rows}
        return {s: (s in found) for s in symbols}

    def available_dates(
        self,
        symbol: str,
        start: datetime.date,
        end: datetime.date,
    ) -> set[datetime.date]:
        """Return the set of trading dates that have cached rows for symbol in [start, end]."""
        with self._lock:
            result = self._conn.execute(
                """
                SELECT DISTINCT trading_date
                FROM computed_timeseries
                WHERE symbol = ? AND trading_date BETWEEN ? AND ?
                """,
                [symbol, start, end],
            ).fetchall()
        return {row[0] for row in result}

    def get_watermark(self, symbol: str) -> Optional[datetime.datetime]:
        with self._lock:
            row = self._conn.execute(
                "SELECT last_synced FROM sync_watermarks WHERE symbol = ?",
                [symbol],
            ).fetchone()
        return row[0] if row else None

    def set_watermark(self, symbol: str, ts: datetime.datetime) -> None:
        if self._read_only:
            return
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
