"""
PostgresCacheBackend — MutableMapping backed by a Supabase/Postgres KV table.

Provides the L2 (remote) layer for the layered cache architecture.
Values are pickle-serialized to BYTEA, keyed by (namespace, key).

Serialization Note (BYTEA vs JSONB)
------------------------------------
Pickle→BYTEA was chosen because the platform caches arbitrary Python objects
(QuantLib handles, scipy interpolators, numpy arrays, custom dataclasses) that
cannot be JSON-serialized.  The trade-off is that BYTEA columns are opaque to
SQL and BI tools.  For namespaces that store JSON-safe payloads, a future
enhancement can introduce per-namespace codec overrides that write to a JSONB
column instead, enabling direct SQL sub-field queries.

Connection Pooling
------------------
The module-level ``get_engine()`` singleton ensures that all cache backends in
a single Python process share one SQLAlchemy connection pool.  In multi-process
deployments (e.g. ``warm_ustfo_cache_parallel.py``), each process creates its
own engine — this is correct for SQLAlchemy.  The Supabase pooler endpoint
(port 6543 / Supavisor) multiplexes these upstream connections so total DB
connections stay bounded even under heavy parallelism.

Future: Real-time Invalidation
-------------------------------
For sub-second cross-node invalidation, a LISTEN/NOTIFY channel can be added.
On L2 write, the backend would ``NOTIFY arbs_cache_invalidate, 'ns:key'``;
worker nodes would maintain a listener thread that pops stale keys from their
local L1 FanoutCache.  This is complementary to the TTL-based invalidation
already implemented in LayeredMapping.
"""
from __future__ import annotations

import logging
import os
import pickle
import threading
from collections.abc import MutableMapping
from typing import Any, Iterator, Optional

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

logger = logging.getLogger(__name__)

TABLE = "arbs_kv_cache_v1"

SCHEMA_SQL = f"""
CREATE TABLE IF NOT EXISTS {TABLE} (
    cache_ns   TEXT        NOT NULL,
    cache_key  TEXT        NOT NULL,
    value_bytes BYTEA      NOT NULL,
    size_bytes  INTEGER    NOT NULL DEFAULT 0,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (cache_ns, cache_key)
);

-- Namespace-only index: speeds up per-namespace iteration, COUNT, and DELETE.
-- Also prepares for future Postgres declarative partitioning by cache_ns.
CREATE INDEX IF NOT EXISTS idx_{TABLE}_ns
    ON {TABLE} (cache_ns);

-- Partial index on updated_at: supports TTL-based cleanup queries
-- (e.g. DELETE FROM … WHERE updated_at < NOW() - INTERVAL '7 days').
CREATE INDEX IF NOT EXISTS idx_{TABLE}_ns_updated
    ON {TABLE} (cache_ns, updated_at);
"""

# ---------------------------------------------------------------------------
# Shared engine singleton
# ---------------------------------------------------------------------------

_engine: Optional[Engine] = None
_engine_lock = threading.Lock()
_schema_ensured = False
_schema_lock = threading.Lock()


def _get_connection_string() -> str:
    url = os.getenv("DATABASE_URL")
    if url:
        return url
    host = os.getenv("SWAPPULSE_DB_HOST", "aws-0-us-east-1.pooler.supabase.com")
    port = os.getenv("SWAPPULSE_DB_PORT", "6543")
    dbname = os.getenv("SWAPPULSE_DB_NAME", "postgres")
    user = os.getenv("SWAPPULSE_DB_USER", "postgres.rdobtpugtnmefxplgwyp")
    password = os.getenv("SWAPPULSE_DB_PASSWORD", "")
    return f"postgresql://{user}:{password}@{host}:{port}/{dbname}"


def get_engine() -> Engine:
    global _engine
    if _engine is not None:
        return _engine
    with _engine_lock:
        if _engine is not None:
            return _engine
        _engine = create_engine(
            _get_connection_string(),
            pool_size=5,
            max_overflow=10,
            pool_timeout=30,
            pool_recycle=1800,
            # Emit a lightweight SELECT 1 before handing a connection to the
            # caller.  Prevents stale/broken connections from Supavisor idle
            # timeout (default 60 s) from surfacing as runtime errors.
            pool_pre_ping=True,
        )
        return _engine


def ensure_schema(engine: Optional[Engine] = None) -> None:
    global _schema_ensured
    if _schema_ensured:
        return
    with _schema_lock:
        # Double-check after acquiring the lock (another thread may have
        # completed DDL while we were waiting).
        if _schema_ensured:
            return
        eng = engine or get_engine()
        with eng.begin() as conn:
            conn.execute(text(SCHEMA_SQL))
        _schema_ensured = True


# ---------------------------------------------------------------------------
# PostgresCacheBackend
# ---------------------------------------------------------------------------


class PostgresCacheBackend(MutableMapping):
    """
    MutableMapping backed by a single Postgres table, scoped by namespace.

    Each (cache_ns, cache_key) pair maps to a pickled value stored as BYTEA.
    Thread-safe: all operations use short-lived connections from the pool.
    """

    def __init__(self, namespace: str, engine: Optional[Engine] = None) -> None:
        self._ns = namespace
        self._engine = engine or get_engine()
        ensure_schema(self._engine)

    # -- read ---------------------------------------------------------------

    def __getitem__(self, key: str) -> Any:
        with self._engine.begin() as conn:
            row = conn.execute(
                text(f"SELECT value_bytes FROM {TABLE} WHERE cache_ns = :ns AND cache_key = :k"),
                {"ns": self._ns, "k": str(key)},
            ).fetchone()
        if row is None:
            raise KeyError(key)
        return pickle.loads(row[0])

    def get(self, key: str, default: Any = None) -> Any:
        try:
            return self[key]
        except KeyError:
            return default

    # -- write --------------------------------------------------------------

    def __setitem__(self, key: str, value: Any) -> None:
        blob = pickle.dumps(value, protocol=pickle.HIGHEST_PROTOCOL)
        size = len(blob)
        with self._engine.begin() as conn:
            conn.execute(
                text(f"""
                    INSERT INTO {TABLE} (cache_ns, cache_key, value_bytes, size_bytes)
                    VALUES (:ns, :k, :v, :sz)
                    ON CONFLICT (cache_ns, cache_key) DO UPDATE
                    SET value_bytes = EXCLUDED.value_bytes,
                        size_bytes  = EXCLUDED.size_bytes,
                        updated_at  = NOW()
                """),
                {"ns": self._ns, "k": str(key), "v": blob, "sz": size},
            )

    # -- delete -------------------------------------------------------------

    def __delitem__(self, key: str) -> None:
        with self._engine.begin() as conn:
            result = conn.execute(
                text(f"DELETE FROM {TABLE} WHERE cache_ns = :ns AND cache_key = :k"),
                {"ns": self._ns, "k": str(key)},
            )
        if result.rowcount == 0:
            raise KeyError(key)

    # -- iteration / membership ---------------------------------------------

    def __contains__(self, key: object) -> bool:
        with self._engine.begin() as conn:
            row = conn.execute(
                text(f"SELECT 1 FROM {TABLE} WHERE cache_ns = :ns AND cache_key = :k"),
                {"ns": self._ns, "k": str(key)},
            ).fetchone()
        return row is not None

    def __iter__(self) -> Iterator[str]:
        with self._engine.begin() as conn:
            rows = conn.execute(
                text(f"SELECT cache_key FROM {TABLE} WHERE cache_ns = :ns ORDER BY cache_key"),
                {"ns": self._ns},
            ).fetchall()
        return iter(r[0] for r in rows)

    def __len__(self) -> int:
        with self._engine.begin() as conn:
            row = conn.execute(
                text(f"SELECT COUNT(*) FROM {TABLE} WHERE cache_ns = :ns"),
                {"ns": self._ns},
            ).fetchone()
        return row[0] if row else 0

    def clear(self) -> None:
        with self._engine.begin() as conn:
            conn.execute(
                text(f"DELETE FROM {TABLE} WHERE cache_ns = :ns"),
                {"ns": self._ns},
            )

    # -- bulk operations (for migration) ------------------------------------

    def bulk_put(self, items: list[tuple[str, Any]], batch_size: int = 500) -> int:
        """
        Bulk-insert (key, value) pairs. Uses psycopg2 execute_values for speed.
        Returns the number of rows upserted.
        """
        if not items:
            return 0

        total = 0
        raw_conn = self._engine.raw_connection()
        try:
            cur = raw_conn.cursor()
            for i in range(0, len(items), batch_size):
                batch = items[i : i + batch_size]
                values = []
                for k, v in batch:
                    blob = pickle.dumps(v, protocol=pickle.HIGHEST_PROTOCOL)
                    values.append((self._ns, str(k), blob, len(blob)))

                from psycopg2.extras import execute_values

                execute_values(
                    cur,
                    f"""
                    INSERT INTO {TABLE} (cache_ns, cache_key, value_bytes, size_bytes)
                    VALUES %s
                    ON CONFLICT (cache_ns, cache_key) DO UPDATE
                    SET value_bytes = EXCLUDED.value_bytes,
                        size_bytes  = EXCLUDED.size_bytes,
                        updated_at  = NOW()
                    """,
                    values,
                    page_size=batch_size,
                )
                total += len(batch)
            raw_conn.commit()
        except Exception:
            raw_conn.rollback()
            raise
        finally:
            raw_conn.close()
        return total

    # -- diagnostics --------------------------------------------------------

    def stats(self) -> dict[str, Any]:
        with self._engine.begin() as conn:
            row = conn.execute(
                text(f"""
                    SELECT COUNT(*) AS cnt,
                           COALESCE(SUM(size_bytes), 0) AS total_bytes,
                           MIN(created_at) AS oldest,
                           MAX(updated_at) AS newest
                    FROM {TABLE}
                    WHERE cache_ns = :ns
                """),
                {"ns": self._ns},
            ).fetchone()
        return {
            "namespace": self._ns,
            "count": row[0],
            "total_bytes": row[1],
            "oldest": row[2],
            "newest": row[3],
        }
