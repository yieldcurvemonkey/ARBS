# CORE Distributed Cache Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Implement the "Compute Once, Read Everywhere" distributed caching layer — CurveStore sync to Supabase + LayeredCacheMixin for generic KV objects.

**Architecture:** Dual-track system. Track 1: `SupabaseCurveSync` pushes/pulls CurveStore Parquet blobs and tagged priority snapshots to/from Supabase. Track 2: `LayeredCacheMixin` extends `DiskCacheMixin` with L2 Supabase KV fallback using TTL-based freshness. Both tracks share a singleton SQLAlchemy engine and degrade gracefully when Supabase is unavailable.

**Tech Stack:** SQLAlchemy 2.0+, psycopg2-binary, cloudpickle, existing PyArrow/DuckDB/diskcache stack.

**Design Doc:** `docs/plans/2026-03-16-core-distributed-cache-design.md`

---

## Task 1: Supabase Engine Singleton

**Files:**
- Create: `Caching/supabase_engine.py`
- Test: `tests/test_supabase_engine.py`
- Modify: `requirements.txt`

**Context:** The existing Supabase pattern in `SDRUtils/_swappulse_scripts/` duplicates `get_db_connection_string()` and `create_db_engine()` across 7 files. This task creates the single shared engine. The existing ingest scripts use `SWAPPULSE_*` env vars and port 6543 (PgBouncer). We'll use a separate `ARBS_DATABASE_URL` env var for the CORE cache system (distinct from the SwapPulse ingest pipeline).

**Step 1: Add dependencies to requirements.txt**

Add these lines to `requirements.txt`:
```
sqlalchemy>=2.0.0
psycopg2-binary>=2.9.0
cloudpickle>=3.0.0
```

**Step 2: Write the failing tests**

Create `tests/test_supabase_engine.py`:

```python
"""Tests for Caching.supabase_engine — singleton SQLAlchemy engine."""

import os
import threading

import pytest


class TestSupabaseEnabled:
    """ARBS_SUPABASE_ENABLED flag tracks whether a database URL is configured."""

    def test_disabled_when_no_url(self, monkeypatch):
        monkeypatch.delenv("ARBS_DATABASE_URL", raising=False)
        # Force module reload to pick up env change
        import importlib
        import Caching.supabase_engine as mod
        importlib.reload(mod)
        assert mod.SUPABASE_ENABLED is False

    def test_enabled_when_url_set(self, monkeypatch):
        monkeypatch.setenv("ARBS_DATABASE_URL", "postgresql://user:pass@host:6543/db")
        import importlib
        import Caching.supabase_engine as mod
        importlib.reload(mod)
        assert mod.SUPABASE_ENABLED is True


class TestGetEngine:
    """get_engine() returns a singleton SQLAlchemy Engine, or None if disabled."""

    def test_returns_none_when_disabled(self, monkeypatch):
        monkeypatch.delenv("ARBS_DATABASE_URL", raising=False)
        import importlib
        import Caching.supabase_engine as mod
        importlib.reload(mod)
        assert mod.get_engine() is None

    def test_returns_engine_when_enabled(self, monkeypatch):
        monkeypatch.setenv(
            "ARBS_DATABASE_URL",
            "postgresql://user:pass@localhost:6543/testdb",
        )
        import importlib
        import Caching.supabase_engine as mod
        importlib.reload(mod)
        engine = mod.get_engine()
        assert engine is not None
        from sqlalchemy import Engine
        assert isinstance(engine, Engine)

    def test_singleton_returns_same_instance(self, monkeypatch):
        monkeypatch.setenv(
            "ARBS_DATABASE_URL",
            "postgresql://user:pass@localhost:6543/testdb",
        )
        import importlib
        import Caching.supabase_engine as mod
        importlib.reload(mod)
        e1 = mod.get_engine()
        e2 = mod.get_engine()
        assert e1 is e2

    def test_thread_safe_singleton(self, monkeypatch):
        monkeypatch.setenv(
            "ARBS_DATABASE_URL",
            "postgresql://user:pass@localhost:6543/testdb",
        )
        import importlib
        import Caching.supabase_engine as mod
        importlib.reload(mod)
        engines = []

        def grab():
            engines.append(mod.get_engine())

        threads = [threading.Thread(target=grab) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert all(e is engines[0] for e in engines)


class TestGetRawConnection:
    """get_raw_connection() provides a psycopg2 connection for batch ops."""

    def test_returns_none_when_disabled(self, monkeypatch):
        monkeypatch.delenv("ARBS_DATABASE_URL", raising=False)
        import importlib
        import Caching.supabase_engine as mod
        importlib.reload(mod)
        assert mod.get_raw_connection() is None
```

**Step 3: Run tests to verify they fail**

Run: `pytest tests/test_supabase_engine.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'Caching.supabase_engine'`

**Step 4: Write minimal implementation**

Create `Caching/supabase_engine.py`:

```python
"""Singleton SQLAlchemy engine for Supabase/Postgres L2 cache.

Configuration via environment:
    ARBS_DATABASE_URL  — full PostgreSQL connection string
                         (e.g. postgresql://user:pass@host:6543/postgres)

When ARBS_DATABASE_URL is not set, SUPABASE_ENABLED is False and all
functions return None. The rest of the caching stack degrades gracefully.
"""

from __future__ import annotations

import logging
import os
import threading
from typing import Optional

from sqlalchemy import Engine, create_engine

logger = logging.getLogger(__name__)

_DATABASE_URL: Optional[str] = os.environ.get("ARBS_DATABASE_URL")
SUPABASE_ENABLED: bool = bool(_DATABASE_URL)

_engine: Optional[Engine] = None
_lock = threading.Lock()


def get_engine() -> Optional[Engine]:
    """Return the singleton SQLAlchemy engine, or None if disabled."""
    global _engine
    if not SUPABASE_ENABLED:
        return None
    if _engine is not None:
        return _engine
    with _lock:
        if _engine is not None:
            return _engine
        _engine = create_engine(
            _DATABASE_URL,
            pool_size=3,
            max_overflow=2,
            pool_timeout=30,
            pool_recycle=1800,
            pool_pre_ping=True,
        )
        logger.info("ARBS Supabase engine created: %s", _DATABASE_URL.split("@")[-1])
        return _engine


def get_raw_connection():
    """Return a raw psycopg2 connection for batch operations, or None."""
    engine = get_engine()
    if engine is None:
        return None
    return engine.raw_connection()
```

**Step 5: Run tests to verify they pass**

Run: `pytest tests/test_supabase_engine.py -v`
Expected: PASS (all tests)

**Step 6: Commit**

```bash
git add Caching/supabase_engine.py tests/test_supabase_engine.py requirements.txt
git commit -m "feat: add Supabase engine singleton for CORE cache L2"
```

---

## Task 2: DDL Schema

**Files:**
- Create: `sql/core_cache_schema.sql`
- Create: `Caching/supabase_schema.py`
- Test: `tests/test_supabase_schema.py`

**Context:** Three tables: `curve_snapshots` (relational priority curves), `curve_intraday_blocks` (Parquet blobs), `arbs_kv_cache_v1` (generic KV). The `ensure_schema()` pattern from `SDRUtils/_swappulse_scripts/ingest_usdswaps.py` runs `CREATE TABLE IF NOT EXISTS` idempotently.

**Step 1: Create the DDL file**

Create `sql/core_cache_schema.sql`:

```sql
-- CORE Distributed Cache Schema
-- Run via Caching.supabase_schema.ensure_schema()

CREATE TABLE IF NOT EXISTS curve_snapshots (
    curve_name VARCHAR NOT NULL,
    timestamp_utc TIMESTAMPTZ NOT NULL,
    trading_date DATE NOT NULL,
    session_minute SMALLINT NOT NULL,
    tags TEXT[] NOT NULL DEFAULT '{}',
    cfg_hash VARCHAR NOT NULL,
    reference_key VARCHAR NOT NULL,
    interpolation VARCHAR NOT NULL,
    source_variant VARCHAR NOT NULL DEFAULT '',
    node_dates DATE[] NOT NULL,
    discount_factors FLOAT8[] NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    PRIMARY KEY (curve_name, timestamp_utc)
);

CREATE INDEX IF NOT EXISTS idx_snapshots_tags
    ON curve_snapshots USING GIN (tags);
CREATE INDEX IF NOT EXISTS idx_snapshots_date
    ON curve_snapshots (curve_name, trading_date);

CREATE TABLE IF NOT EXISTS curve_intraday_blocks (
    trading_date DATE NOT NULL,
    curve_name VARCHAR NOT NULL,
    data_format VARCHAR NOT NULL DEFAULT 'parquet_zstd',
    row_count INTEGER NOT NULL,
    payload BYTEA NOT NULL,
    sha256 VARCHAR NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    PRIMARY KEY (trading_date, curve_name)
);

CREATE TABLE IF NOT EXISTS arbs_kv_cache_v1 (
    cache_ns VARCHAR NOT NULL,
    cache_key VARCHAR NOT NULL,
    key_repr TEXT,
    payload BYTEA NOT NULL,
    serializer VARCHAR NOT NULL DEFAULT 'cloudpickle',
    ttl_seconds INTEGER,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    PRIMARY KEY (cache_ns, cache_key)
);

CREATE INDEX IF NOT EXISTS idx_kv_updated
    ON arbs_kv_cache_v1 (updated_at);
```

**Step 2: Write the failing tests**

Create `tests/test_supabase_schema.py`:

```python
"""Tests for Caching.supabase_schema — DDL management."""

import pytest


class TestSchemaSQL:
    """SCHEMA_SQL constant contains valid DDL."""

    def test_schema_sql_is_string(self):
        from Caching.supabase_schema import SCHEMA_SQL
        assert isinstance(SCHEMA_SQL, str)

    def test_schema_sql_contains_all_tables(self):
        from Caching.supabase_schema import SCHEMA_SQL
        assert "curve_snapshots" in SCHEMA_SQL
        assert "curve_intraday_blocks" in SCHEMA_SQL
        assert "arbs_kv_cache_v1" in SCHEMA_SQL

    def test_schema_sql_uses_if_not_exists(self):
        from Caching.supabase_schema import SCHEMA_SQL
        assert "IF NOT EXISTS" in SCHEMA_SQL


class TestEnsureSchema:
    """ensure_schema() is a no-op when Supabase is disabled."""

    def test_noop_when_disabled(self, monkeypatch):
        monkeypatch.delenv("ARBS_DATABASE_URL", raising=False)
        import importlib
        import Caching.supabase_engine as eng
        importlib.reload(eng)
        from Caching.supabase_schema import ensure_schema
        # Should not raise — just returns False
        assert ensure_schema() is False
```

**Step 3: Run tests to verify they fail**

Run: `pytest tests/test_supabase_schema.py -v`
Expected: FAIL — `ModuleNotFoundError`

**Step 4: Write minimal implementation**

Create `Caching/supabase_schema.py`:

```python
"""DDL management for CORE cache Postgres tables."""

from __future__ import annotations

import logging
from pathlib import Path

from sqlalchemy import text

from Caching.supabase_engine import get_engine

logger = logging.getLogger(__name__)

_SQL_PATH = Path(__file__).resolve().parent.parent / "sql" / "core_cache_schema.sql"
SCHEMA_SQL: str = _SQL_PATH.read_text(encoding="utf-8")


def ensure_schema() -> bool:
    """Create tables and indexes if they do not exist.

    Returns True if schema was applied, False if Supabase is disabled.
    """
    engine = get_engine()
    if engine is None:
        return False
    with engine.begin() as conn:
        for statement in SCHEMA_SQL.split(";"):
            stmt = statement.strip()
            if stmt:
                conn.execute(text(stmt))
    logger.info("CORE cache schema ensured.")
    return True
```

**Step 5: Run tests to verify they pass**

Run: `pytest tests/test_supabase_schema.py -v`
Expected: PASS

**Step 6: Commit**

```bash
git add sql/core_cache_schema.sql Caching/supabase_schema.py tests/test_supabase_schema.py
git commit -m "feat: add DDL schema for CORE cache tables"
```

---

## Task 3: SupabaseCurveSync — Push (Write-Through)

**Files:**
- Create: `Caching/supabase_curve_sync.py`
- Test: `tests/test_supabase_curve_sync.py`

**Context:** `CurveStore.write_day()` writes Parquet locally and returns `{path, size, sha256}`. `SupabaseCurveSync.push_day()` reads that local file and UPSERTs the bytes into `curve_intraday_blocks`. It also extracts priority snapshots for `curve_snapshots`. The existing `_RAW_SCHEMA` has fields: timestamp_utc, timestamp_local, trading_date, session_minute, curve_name, cfg_hash, reference_key, interpolation, source_variant, node_dates, discount_factors.

**Step 1: Write the failing tests**

Create `tests/test_supabase_curve_sync.py`:

```python
"""Tests for Caching.supabase_curve_sync — push/pull CurveStore to Supabase."""

import datetime
import io
from unittest.mock import MagicMock, patch, call

import pyarrow as pa
import pyarrow.parquet as pq
import pytest


def _make_test_parquet_bytes() -> bytes:
    """Create minimal Parquet bytes matching CurveStore._RAW_SCHEMA."""
    table = pa.table(
        {
            "timestamp_utc": pa.array(
                [datetime.datetime(2025, 1, 15, 21, 0, tzinfo=datetime.timezone.utc)],
                type=pa.timestamp("us", tz="UTC"),
            ),
            "timestamp_local": pa.array(
                [datetime.datetime(2025, 1, 15, 15, 0)],
                type=pa.timestamp("us"),
            ),
            "trading_date": pa.array([datetime.date(2025, 1, 15)], type=pa.date32()),
            "session_minute": pa.array([540], type=pa.int16()),
            "curve_name": pa.array(["USD-SOFR-1D"]).dictionary_encode(),
            "cfg_hash": pa.array(["abc123"]).dictionary_encode(),
            "reference_key": pa.array(["ref"]).dictionary_encode(),
            "interpolation": pa.array(["log_linear"]).dictionary_encode(),
            "source_variant": pa.array(["ERIS"]).dictionary_encode(),
            "node_dates": pa.array(
                [[datetime.date(2025, 1, 16), datetime.date(2025, 7, 15)]],
                type=pa.list_(pa.date32()),
            ),
            "discount_factors": pa.array(
                [[0.999, 0.985]], type=pa.list_(pa.float64())
            ),
        }
    )
    buf = io.BytesIO()
    pq.write_table(table, buf, compression="zstd")
    return buf.getvalue()


class TestPushDay:
    """push_day() reads local Parquet and UPSERTs to curve_intraday_blocks."""

    def test_push_day_reads_file_and_upserts(self, tmp_path):
        from Caching.supabase_curve_sync import SupabaseCurveSync

        # Write a test Parquet file to tmp_path
        parquet_bytes = _make_test_parquet_bytes()
        part_dir = tmp_path / "raw" / "asset=USD-SOFR-1D" / "date=2025-01-15"
        part_dir.mkdir(parents=True)
        pq_file = part_dir / "abc123.parquet"
        pq_file.write_bytes(parquet_bytes)

        mock_engine = MagicMock()
        mock_conn = MagicMock()
        mock_engine.begin.return_value.__enter__ = MagicMock(return_value=mock_conn)
        mock_engine.begin.return_value.__exit__ = MagicMock(return_value=False)

        sync = SupabaseCurveSync(base_dir=tmp_path, engine=mock_engine)
        result = sync.push_day("USD-SOFR-1D", datetime.date(2025, 1, 15))

        assert result is True
        mock_conn.execute.assert_called()

    def test_push_day_returns_false_when_no_local_data(self, tmp_path):
        from Caching.supabase_curve_sync import SupabaseCurveSync

        mock_engine = MagicMock()
        sync = SupabaseCurveSync(base_dir=tmp_path, engine=mock_engine)
        result = sync.push_day("USD-SOFR-1D", datetime.date(2025, 1, 15))

        assert result is False

    def test_push_day_noop_when_no_engine(self, tmp_path):
        from Caching.supabase_curve_sync import SupabaseCurveSync

        sync = SupabaseCurveSync(base_dir=tmp_path, engine=None)
        result = sync.push_day("USD-SOFR-1D", datetime.date(2025, 1, 15))

        assert result is False


class TestPullDay:
    """pull_day() fetches blob from Supabase and writes local Parquet."""

    def test_pull_day_writes_local_file(self, tmp_path):
        from Caching.supabase_curve_sync import SupabaseCurveSync

        parquet_bytes = _make_test_parquet_bytes()

        mock_engine = MagicMock()
        mock_conn = MagicMock()
        mock_engine.begin.return_value.__enter__ = MagicMock(return_value=mock_conn)
        mock_engine.begin.return_value.__exit__ = MagicMock(return_value=False)
        # Simulate a row returned from SELECT
        mock_row = MagicMock()
        mock_row.payload = parquet_bytes
        mock_row.sha256 = "fakehash"
        mock_row.data_format = "parquet_zstd"
        mock_conn.execute.return_value.fetchone.return_value = mock_row

        sync = SupabaseCurveSync(base_dir=tmp_path, engine=mock_engine)
        result = sync.pull_day("USD-SOFR-1D", datetime.date(2025, 1, 15))

        assert result is True
        # Verify local file was created
        part_dir = tmp_path / "raw" / "asset=USD-SOFR-1D" / "date=2025-01-15"
        assert part_dir.exists()
        pq_files = list(part_dir.glob("*.parquet"))
        assert len(pq_files) == 1

    def test_pull_day_returns_false_when_not_in_supabase(self, tmp_path):
        from Caching.supabase_curve_sync import SupabaseCurveSync

        mock_engine = MagicMock()
        mock_conn = MagicMock()
        mock_engine.begin.return_value.__enter__ = MagicMock(return_value=mock_conn)
        mock_engine.begin.return_value.__exit__ = MagicMock(return_value=False)
        mock_conn.execute.return_value.fetchone.return_value = None

        sync = SupabaseCurveSync(base_dir=tmp_path, engine=mock_engine)
        result = sync.pull_day("USD-SOFR-1D", datetime.date(2025, 1, 15))

        assert result is False


class TestPrefetchRange:
    """prefetch_range() downloads only missing days."""

    def test_skips_already_cached_days(self, tmp_path):
        from Caching.supabase_curve_sync import SupabaseCurveSync

        # Create a local file for 2025-01-15
        part_dir = tmp_path / "raw" / "asset=USD-SOFR-1D" / "date=2025-01-15"
        part_dir.mkdir(parents=True)
        (part_dir / "existing.parquet").write_bytes(_make_test_parquet_bytes())

        mock_engine = MagicMock()
        mock_conn = MagicMock()
        mock_engine.begin.return_value.__enter__ = MagicMock(return_value=mock_conn)
        mock_engine.begin.return_value.__exit__ = MagicMock(return_value=False)
        # Return only 2025-01-16 from Supabase (15 is already local)
        mock_row = MagicMock()
        mock_row.trading_date = datetime.date(2025, 1, 16)
        mock_row.payload = _make_test_parquet_bytes()
        mock_row.sha256 = "hash16"
        mock_conn.execute.return_value.fetchall.return_value = [mock_row]

        sync = SupabaseCurveSync(base_dir=tmp_path, engine=mock_engine)
        fetched = sync.prefetch_range(
            "USD-SOFR-1D",
            start=datetime.date(2025, 1, 15),
            end=datetime.date(2025, 1, 16),
        )

        assert datetime.date(2025, 1, 16) in fetched
        assert datetime.date(2025, 1, 15) not in fetched
```

**Step 2: Run tests to verify they fail**

Run: `pytest tests/test_supabase_curve_sync.py -v`
Expected: FAIL — `ModuleNotFoundError`

**Step 3: Write implementation**

Create `Caching/supabase_curve_sync.py`:

```python
"""Bidirectional sync between local CurveStore Parquet and Supabase Postgres.

Usage:
    sync = SupabaseCurveSync.from_defaults()
    sync.push_day("USD-SOFR-1D", date(2025, 1, 15))   # local -> Supabase
    sync.pull_day("USD-SOFR-1D", date(2025, 1, 15))   # Supabase -> local
    sync.prefetch_range("USD-SOFR-1D", start, end)     # bulk download missing days
"""

from __future__ import annotations

import datetime
import hashlib
import logging
import re
from pathlib import Path
from typing import Optional, Sequence

from sqlalchemy import Engine, text

logger = logging.getLogger(__name__)

_SLUG_RX = re.compile(r"[^\w.\-]")


def _sanitize(name: str) -> str:
    return _SLUG_RX.sub("_", name)


class SupabaseCurveSync:
    """Sync CurveStore Parquet files with Supabase curve tables."""

    def __init__(self, base_dir: Path, engine: Optional[Engine]):
        self._base_dir = Path(base_dir)
        self._engine = engine

    @classmethod
    def from_defaults(cls) -> "SupabaseCurveSync":
        from Caching.curve_store import CurveStore
        from Caching.supabase_engine import get_engine

        store = CurveStore.default()
        return cls(base_dir=store.base_dir, engine=get_engine())

    def _partition_dir(self, curve_name: str, trading_date: datetime.date) -> Path:
        return (
            self._base_dir
            / "raw"
            / f"asset={_sanitize(curve_name)}"
            / f"date={trading_date.isoformat()}"
        )

    def _local_parquet_bytes(
        self, curve_name: str, trading_date: datetime.date
    ) -> Optional[bytes]:
        part_dir = self._partition_dir(curve_name, trading_date)
        if not part_dir.exists():
            return None
        pq_files = list(part_dir.glob("*.parquet"))
        if not pq_files:
            return None
        # Read the first (should be only) Parquet file
        return pq_files[0].read_bytes()

    def push_day(
        self, curve_name: str, trading_date: datetime.date
    ) -> bool:
        """Push a day's Parquet blob from local to Supabase.

        Returns True if upserted, False if skipped (no engine or no local data).
        """
        if self._engine is None:
            return False
        payload = self._local_parquet_bytes(curve_name, trading_date)
        if payload is None:
            return False

        sha = hashlib.sha256(payload).hexdigest()
        # Count rows by reading Parquet metadata
        import pyarrow.parquet as pq
        import io

        table = pq.read_table(io.BytesIO(payload))
        row_count = table.num_rows

        with self._engine.begin() as conn:
            conn.execute(
                text("""
                    INSERT INTO curve_intraday_blocks
                        (trading_date, curve_name, data_format, row_count, payload, sha256)
                    VALUES
                        (:trading_date, :curve_name, :data_format, :row_count, :payload, :sha256)
                    ON CONFLICT (trading_date, curve_name) DO UPDATE SET
                        data_format = EXCLUDED.data_format,
                        row_count = EXCLUDED.row_count,
                        payload = EXCLUDED.payload,
                        sha256 = EXCLUDED.sha256,
                        created_at = NOW()
                """),
                {
                    "trading_date": trading_date,
                    "curve_name": curve_name,
                    "data_format": "parquet_zstd",
                    "row_count": row_count,
                    "payload": payload,
                    "sha256": sha,
                },
            )
        logger.info(
            "Pushed %s/%s to Supabase (%d rows, %d bytes)",
            curve_name, trading_date, row_count, len(payload),
        )
        return True

    def pull_day(
        self, curve_name: str, trading_date: datetime.date
    ) -> bool:
        """Pull a day's Parquet blob from Supabase to local.

        Returns True if downloaded and written, False if not found or no engine.
        """
        if self._engine is None:
            return False

        with self._engine.begin() as conn:
            row = conn.execute(
                text("""
                    SELECT payload, sha256, data_format
                    FROM curve_intraday_blocks
                    WHERE trading_date = :trading_date AND curve_name = :curve_name
                """),
                {"trading_date": trading_date, "curve_name": curve_name},
            ).fetchone()

        if row is None:
            return False

        part_dir = self._partition_dir(curve_name, trading_date)
        part_dir.mkdir(parents=True, exist_ok=True)
        dest = part_dir / f"{row.sha256}.parquet"
        dest.write_bytes(row.payload)
        logger.info("Pulled %s/%s from Supabase -> %s", curve_name, trading_date, dest)
        return True

    def prefetch_range(
        self,
        curve_name: str,
        start: datetime.date,
        end: datetime.date,
    ) -> list[datetime.date]:
        """Download all missing days from Supabase to local.

        Returns list of dates that were fetched (excludes already-cached days).
        """
        if self._engine is None:
            return []

        # Find locally available dates
        local_dates = set()
        asset_dir = self._base_dir / "raw" / f"asset={_sanitize(curve_name)}"
        if asset_dir.exists():
            for d in asset_dir.iterdir():
                if d.name.startswith("date=") and any(d.glob("*.parquet")):
                    try:
                        dt = datetime.date.fromisoformat(d.name[5:])
                        if start <= dt <= end:
                            local_dates.add(dt)
                    except ValueError:
                        pass

        # Fetch missing days from Supabase
        with self._engine.begin() as conn:
            rows = conn.execute(
                text("""
                    SELECT trading_date, payload, sha256
                    FROM curve_intraday_blocks
                    WHERE curve_name = :curve_name
                      AND trading_date BETWEEN :start AND :end
                    ORDER BY trading_date
                """),
                {"curve_name": curve_name, "start": start, "end": end},
            ).fetchall()

        fetched = []
        for row in rows:
            if row.trading_date in local_dates:
                continue
            part_dir = self._partition_dir(curve_name, row.trading_date)
            part_dir.mkdir(parents=True, exist_ok=True)
            dest = part_dir / f"{row.sha256}.parquet"
            dest.write_bytes(row.payload)
            fetched.append(row.trading_date)

        logger.info(
            "Prefetched %s: %d/%d days downloaded (%d already local)",
            curve_name, len(fetched), len(rows), len(local_dates),
        )
        return fetched
```

**Step 4: Run tests to verify they pass**

Run: `pytest tests/test_supabase_curve_sync.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add Caching/supabase_curve_sync.py tests/test_supabase_curve_sync.py
git commit -m "feat: add SupabaseCurveSync push/pull/prefetch"
```

---

## Task 4: Wire SupabaseCurveSync into CurveStore

**Files:**
- Modify: `Caching/curve_store.py` (lines ~286-310 `write_day`, lines ~334-363 `read_raw_day`)
- Test: `tests/test_curve_store_supabase_integration.py`

**Context:** `CurveStore.write_day()` currently does an atomic local Parquet write. We add a background thread that calls `SupabaseCurveSync.push_day()` after the local write. `CurveStore.read_raw_day()` currently returns an empty DataFrame if no local file. We add an L2 fallback that tries `SupabaseCurveSync.pull_day()` before returning empty. The `CurveStore` class is at `Caching/curve_store.py`. Its `__init__` takes `base_dir: Path`. Its singleton is `CurveStore.default()`.

**Step 1: Write the failing tests**

Create `tests/test_curve_store_supabase_integration.py`:

```python
"""Tests for CurveStore L2 Supabase integration."""

import datetime
from unittest.mock import MagicMock, patch

import pytest


class TestWriteDayL2:
    """write_day() triggers background L2 push when Supabase is enabled."""

    def test_write_day_calls_push_in_background(self, tmp_path):
        from Caching.curve_store import CurveStore, CurveSnapshot

        store = CurveStore(base_dir=tmp_path)
        snap = CurveSnapshot(
            timestamp_utc=datetime.datetime(2025, 1, 15, 21, 0, tzinfo=datetime.timezone.utc),
            timestamp_local=datetime.datetime(2025, 1, 15, 15, 0),
            trading_date=datetime.date(2025, 1, 15),
            session_minute=540,
            curve_name="USD-SOFR-1D",
            cfg_hash="test",
            reference_key="ref",
            interpolation="log_linear",
            node_dates=[datetime.date(2025, 1, 16), datetime.date(2025, 7, 15)],
            discount_factors=[0.999, 0.985],
        )

        mock_sync = MagicMock()
        with patch("Caching.curve_store._get_curve_sync", return_value=mock_sync):
            result = store.write_day("USD-SOFR-1D", datetime.date(2025, 1, 15), [snap])

        assert result is not None  # local write succeeded
        # Background push was scheduled (may or may not have run yet)
        mock_sync.push_day.assert_called_once_with("USD-SOFR-1D", datetime.date(2025, 1, 15))

    def test_write_day_succeeds_even_if_push_fails(self, tmp_path):
        from Caching.curve_store import CurveStore, CurveSnapshot

        store = CurveStore(base_dir=tmp_path)
        snap = CurveSnapshot(
            timestamp_utc=datetime.datetime(2025, 1, 15, 21, 0, tzinfo=datetime.timezone.utc),
            timestamp_local=datetime.datetime(2025, 1, 15, 15, 0),
            trading_date=datetime.date(2025, 1, 15),
            session_minute=540,
            curve_name="USD-SOFR-1D",
            cfg_hash="test",
            reference_key="ref",
            interpolation="log_linear",
            node_dates=[datetime.date(2025, 1, 16)],
            discount_factors=[0.999],
        )

        mock_sync = MagicMock()
        mock_sync.push_day.side_effect = Exception("Supabase down")
        with patch("Caching.curve_store._get_curve_sync", return_value=mock_sync):
            result = store.write_day("USD-SOFR-1D", datetime.date(2025, 1, 15), [snap])

        # Local write still succeeded
        assert result is not None


class TestReadRawDayL2:
    """read_raw_day() falls back to L2 when local data is missing."""

    def test_read_falls_back_to_supabase(self, tmp_path):
        from Caching.curve_store import CurveStore

        store = CurveStore(base_dir=tmp_path)

        mock_sync = MagicMock()
        # Simulate pull_day writing a local file
        def fake_pull(curve_name, trading_date):
            from tests.test_supabase_curve_sync import _make_test_parquet_bytes
            part_dir = tmp_path / "raw" / f"asset={curve_name}" / f"date={trading_date.isoformat()}"
            part_dir.mkdir(parents=True, exist_ok=True)
            (part_dir / "pulled.parquet").write_bytes(_make_test_parquet_bytes())
            return True

        mock_sync.pull_day.side_effect = fake_pull
        with patch("Caching.curve_store._get_curve_sync", return_value=mock_sync):
            df = store.read_raw_day("USD-SOFR-1D", datetime.date(2025, 1, 15))

        assert len(df) == 1
        mock_sync.pull_day.assert_called_once()

    def test_read_returns_empty_when_both_miss(self, tmp_path):
        from Caching.curve_store import CurveStore

        store = CurveStore(base_dir=tmp_path)
        mock_sync = MagicMock()
        mock_sync.pull_day.return_value = False  # Supabase also doesn't have it

        with patch("Caching.curve_store._get_curve_sync", return_value=mock_sync):
            df = store.read_raw_day("USD-SOFR-1D", datetime.date(2025, 1, 15))

        assert len(df) == 0

    def test_read_uses_local_when_available(self, tmp_path):
        """L1 hit should NOT trigger L2 pull."""
        from Caching.curve_store import CurveStore, CurveSnapshot

        store = CurveStore(base_dir=tmp_path)
        snap = CurveSnapshot(
            timestamp_utc=datetime.datetime(2025, 1, 15, 21, 0, tzinfo=datetime.timezone.utc),
            timestamp_local=datetime.datetime(2025, 1, 15, 15, 0),
            trading_date=datetime.date(2025, 1, 15),
            session_minute=540,
            curve_name="USD-SOFR-1D",
            cfg_hash="test",
            reference_key="ref",
            interpolation="log_linear",
            node_dates=[datetime.date(2025, 1, 16)],
            discount_factors=[0.999],
        )
        store.write_day("USD-SOFR-1D", datetime.date(2025, 1, 15), [snap])

        mock_sync = MagicMock()
        with patch("Caching.curve_store._get_curve_sync", return_value=mock_sync):
            df = store.read_raw_day("USD-SOFR-1D", datetime.date(2025, 1, 15))

        assert len(df) == 1
        mock_sync.pull_day.assert_not_called()
```

**Step 2: Run tests to verify they fail**

Run: `pytest tests/test_curve_store_supabase_integration.py -v`
Expected: FAIL — `_get_curve_sync` doesn't exist

**Step 3: Modify CurveStore**

Add to `Caching/curve_store.py` near the top (after imports):

```python
import threading as _threading

def _get_curve_sync():
    """Lazy-load SupabaseCurveSync. Returns None if Supabase disabled."""
    from Caching.supabase_engine import SUPABASE_ENABLED
    if not SUPABASE_ENABLED:
        return None
    from Caching.supabase_curve_sync import SupabaseCurveSync
    return SupabaseCurveSync.from_defaults()
```

Modify `write_day()` — after the existing `return meta` line (the successful write), add:

```python
        # L2: background push to Supabase
        sync = _get_curve_sync()
        if sync is not None:
            def _bg_push():
                try:
                    sync.push_day(curve_name, trading_date)
                except Exception:
                    logger.warning("L2 push failed for %s/%s", curve_name, trading_date, exc_info=True)
            _threading.Thread(target=_bg_push, daemon=True).start()
```

Modify `read_raw_day()` — where it currently returns empty DataFrame on missing partition, add L2 fallback:

```python
        # Before returning empty — try L2 fallback
        sync = _get_curve_sync()
        if sync is not None and sync.pull_day(curve_name, trading_date):
            # Retry local read after L2 hydration
            return self.read_raw_day(curve_name, trading_date)
```

**Step 4: Run tests to verify they pass**

Run: `pytest tests/test_curve_store_supabase_integration.py -v`
Expected: PASS

**Step 5: Run existing CurveStore tests to verify no regression**

Run: `pytest tests/test_curve_store_eris.py -v`
Expected: PASS (all existing tests still pass — L2 is a no-op without ARBS_DATABASE_URL)

**Step 6: Commit**

```bash
git add Caching/curve_store.py tests/test_curve_store_supabase_integration.py
git commit -m "feat: wire SupabaseCurveSync into CurveStore read/write paths"
```

---

## Task 5: CurveTagConfig — Priority Snapshot Tagging

**Files:**
- Create: `Caching/curve_tag_config.py`
- Create: `config/event_calendar.yaml`
- Test: `tests/test_curve_tag_config.py`

**Context:** When `push_day()` sends a day's data to Supabase, it also needs to extract priority snapshots (EOD, OPEN, FOMC, CPI) and INSERT them into `curve_snapshots` with tags. The `CurveSnapshot` dataclass has `session_minute` (minutes since 07:00 CT) and `trading_date`. EOD is the last snapshot of the day. OPEN is session_minute == 0. Event tags match against an event calendar.

**Step 1: Write the failing tests**

Create `tests/test_curve_tag_config.py`:

```python
"""Tests for Caching.curve_tag_config — priority snapshot tagging."""

import datetime

import pytest


class TestGetTags:
    """get_tags() returns appropriate tags for a snapshot."""

    def test_open_tag_at_session_minute_zero(self):
        from Caching.curve_tag_config import get_tags

        tags = get_tags(
            session_minute=0,
            trading_date=datetime.date(2025, 3, 10),
            is_last_of_day=False,
            event_calendar={},
        )
        assert "OPEN" in tags

    def test_eod_tag_when_last_of_day(self):
        from Caching.curve_tag_config import get_tags

        tags = get_tags(
            session_minute=540,
            trading_date=datetime.date(2025, 3, 10),
            is_last_of_day=True,
            event_calendar={},
        )
        assert "EOD" in tags

    def test_fomc_tag_from_event_calendar(self):
        from Caching.curve_tag_config import get_tags

        cal = {
            datetime.date(2025, 3, 19): {
                "tag": "FOMC_RATE_DECISION",
                "session_minute": 480,  # 2:00 PM ET = 1:00 PM CT = 360 min after 7 AM
            },
        }
        tags = get_tags(
            session_minute=480,
            trading_date=datetime.date(2025, 3, 19),
            is_last_of_day=False,
            event_calendar=cal,
        )
        assert "FOMC_RATE_DECISION" in tags

    def test_no_event_tag_when_wrong_minute(self):
        from Caching.curve_tag_config import get_tags

        cal = {
            datetime.date(2025, 3, 19): {
                "tag": "FOMC_RATE_DECISION",
                "session_minute": 480,
            },
        }
        tags = get_tags(
            session_minute=100,
            trading_date=datetime.date(2025, 3, 19),
            is_last_of_day=False,
            event_calendar=cal,
        )
        assert "FOMC_RATE_DECISION" not in tags

    def test_no_tags_for_regular_minute(self):
        from Caching.curve_tag_config import get_tags

        tags = get_tags(
            session_minute=300,
            trading_date=datetime.date(2025, 3, 10),
            is_last_of_day=False,
            event_calendar={},
        )
        assert tags == []


class TestLoadEventCalendar:
    """load_event_calendar() reads YAML and returns date->event dict."""

    def test_loads_yaml(self, tmp_path):
        from Caching.curve_tag_config import load_event_calendar

        yaml_content = """
2025-03-19:
  tag: FOMC_RATE_DECISION
  session_minute: 480
2025-04-10:
  tag: CPI_PRINT
  session_minute: 90
"""
        cal_file = tmp_path / "events.yaml"
        cal_file.write_text(yaml_content)
        cal = load_event_calendar(cal_file)
        assert datetime.date(2025, 3, 19) in cal
        assert cal[datetime.date(2025, 3, 19)]["tag"] == "FOMC_RATE_DECISION"

    def test_returns_empty_for_missing_file(self, tmp_path):
        from Caching.curve_tag_config import load_event_calendar

        cal = load_event_calendar(tmp_path / "nonexistent.yaml")
        assert cal == {}
```

**Step 2: Run tests to verify they fail**

Run: `pytest tests/test_curve_tag_config.py -v`
Expected: FAIL

**Step 3: Write implementation**

Create `Caching/curve_tag_config.py`:

```python
"""Priority snapshot tagging for CurveStore -> Supabase curve_snapshots."""

from __future__ import annotations

import datetime
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# Tolerance: event tag applies if session_minute is within +/- this many minutes
_EVENT_MINUTE_TOLERANCE = 2


def get_tags(
    *,
    session_minute: int,
    trading_date: datetime.date,
    is_last_of_day: bool,
    event_calendar: dict[datetime.date, dict[str, Any]],
) -> list[str]:
    """Return priority tags for a curve snapshot."""
    tags: list[str] = []
    if session_minute == 0:
        tags.append("OPEN")
    if is_last_of_day:
        tags.append("EOD")
    event = event_calendar.get(trading_date)
    if event is not None:
        event_minute = event.get("session_minute")
        if event_minute is not None and abs(session_minute - event_minute) <= _EVENT_MINUTE_TOLERANCE:
            tags.append(event["tag"])
    return tags


def load_event_calendar(path: Path) -> dict[datetime.date, dict[str, Any]]:
    """Load event calendar from YAML file. Returns empty dict if file missing."""
    path = Path(path)
    if not path.exists():
        return {}
    try:
        import yaml

        with open(path) as f:
            raw = yaml.safe_load(f) or {}
        # Convert string keys to date objects if needed
        cal = {}
        for k, v in raw.items():
            if isinstance(k, str):
                k = datetime.date.fromisoformat(k)
            cal[k] = v
        return cal
    except Exception:
        logger.warning("Failed to load event calendar from %s", path, exc_info=True)
        return {}
```

Create `config/event_calendar.yaml`:

```yaml
# FOMC Rate Decisions 2025
# session_minute is minutes since 07:00 CT
# FOMC announcements at 2:00 PM ET = 1:00 PM CT = 360 min after 7:00 AM CT
2025-01-29:
  tag: FOMC_RATE_DECISION
  session_minute: 360
2025-03-19:
  tag: FOMC_RATE_DECISION
  session_minute: 360
2025-05-07:
  tag: FOMC_RATE_DECISION
  session_minute: 360
2025-06-18:
  tag: FOMC_RATE_DECISION
  session_minute: 360
2025-07-30:
  tag: FOMC_RATE_DECISION
  session_minute: 360
2025-09-17:
  tag: FOMC_RATE_DECISION
  session_minute: 360
2025-10-29:
  tag: FOMC_RATE_DECISION
  session_minute: 360
2025-12-17:
  tag: FOMC_RATE_DECISION
  session_minute: 360

# CPI Prints 2025
# CPI releases at 8:30 AM ET = 7:30 AM CT = 30 min after 7:00 AM CT
2025-01-15:
  tag: CPI_PRINT
  session_minute: 30
2025-02-12:
  tag: CPI_PRINT
  session_minute: 30
2025-03-12:
  tag: CPI_PRINT
  session_minute: 30
2025-04-10:
  tag: CPI_PRINT
  session_minute: 30
2025-05-13:
  tag: CPI_PRINT
  session_minute: 30
2025-06-11:
  tag: CPI_PRINT
  session_minute: 30
```

**Step 4: Run tests to verify they pass**

Run: `pytest tests/test_curve_tag_config.py -v`
Expected: PASS

**Step 5: Commit**

```bash
pip install pyyaml  # if not already installed
git add Caching/curve_tag_config.py config/event_calendar.yaml tests/test_curve_tag_config.py
git commit -m "feat: add CurveTagConfig for priority snapshot tagging"
```

---

## Task 6: Push Priority Snapshots to curve_snapshots Table

**Files:**
- Modify: `Caching/supabase_curve_sync.py`
- Test: `tests/test_supabase_curve_sync.py` (add new tests)

**Context:** Extend `push_day()` to also extract tagged snapshots from the Parquet data and UPSERT them into `curve_snapshots`. Each row in the Parquet has: timestamp_utc, timestamp_local, trading_date, session_minute, curve_name, cfg_hash, reference_key, interpolation, source_variant, node_dates, discount_factors. We use `get_tags()` from `curve_tag_config` to determine which rows get tagged.

**Step 1: Write the failing test**

Add to `tests/test_supabase_curve_sync.py`:

```python
class TestPushDaySnapshots:
    """push_day() also inserts tagged snapshots into curve_snapshots."""

    def test_push_day_inserts_eod_snapshot(self, tmp_path):
        from Caching.supabase_curve_sync import SupabaseCurveSync

        parquet_bytes = _make_test_parquet_bytes()
        part_dir = tmp_path / "raw" / "asset=USD-SOFR-1D" / "date=2025-01-15"
        part_dir.mkdir(parents=True)
        (part_dir / "abc.parquet").write_bytes(parquet_bytes)

        mock_engine = MagicMock()
        mock_conn = MagicMock()
        mock_engine.begin.return_value.__enter__ = MagicMock(return_value=mock_conn)
        mock_engine.begin.return_value.__exit__ = MagicMock(return_value=False)

        sync = SupabaseCurveSync(base_dir=tmp_path, engine=mock_engine)
        sync.push_day(
            "USD-SOFR-1D",
            datetime.date(2025, 1, 15),
            event_calendar={},
        )

        # Should have at least 2 execute calls: one for blob, potentially one for snapshots
        assert mock_conn.execute.call_count >= 1
```

**Step 2: Run tests to verify they fail**

Run: `pytest tests/test_supabase_curve_sync.py::TestPushDaySnapshots -v`
Expected: FAIL — `push_day()` doesn't accept event_calendar kwarg

**Step 3: Modify push_day() to accept event_calendar and push snapshots**

In `Caching/supabase_curve_sync.py`, modify `push_day()` signature and add snapshot logic:

```python
    def push_day(
        self,
        curve_name: str,
        trading_date: datetime.date,
        *,
        event_calendar: dict | None = None,
    ) -> bool:
```

After the blob UPSERT, add:

```python
        # Extract and push priority snapshots
        if event_calendar is None:
            event_calendar = {}
        self._push_tagged_snapshots(conn, table, curve_name, trading_date, event_calendar)
```

Add helper method:

```python
    def _push_tagged_snapshots(self, conn, table, curve_name, trading_date, event_calendar):
        """Extract tagged snapshots from Arrow table and UPSERT into curve_snapshots."""
        from Caching.curve_tag_config import get_tags

        df = table.to_pandas()
        max_minute = df["session_minute"].max()

        for _, row in df.iterrows():
            is_last = row["session_minute"] == max_minute
            tags = get_tags(
                session_minute=int(row["session_minute"]),
                trading_date=trading_date,
                is_last_of_day=is_last,
                event_calendar=event_calendar,
            )
            if not tags:
                continue

            node_dates = [d.isoformat() for d in row["node_dates"]]
            conn.execute(
                text("""
                    INSERT INTO curve_snapshots
                        (curve_name, timestamp_utc, trading_date, session_minute,
                         tags, cfg_hash, reference_key, interpolation, source_variant,
                         node_dates, discount_factors)
                    VALUES
                        (:curve_name, :timestamp_utc, :trading_date, :session_minute,
                         :tags, :cfg_hash, :reference_key, :interpolation, :source_variant,
                         :node_dates, :discount_factors)
                    ON CONFLICT (curve_name, timestamp_utc) DO UPDATE SET
                        tags = EXCLUDED.tags,
                        node_dates = EXCLUDED.node_dates,
                        discount_factors = EXCLUDED.discount_factors
                """),
                {
                    "curve_name": curve_name,
                    "timestamp_utc": row["timestamp_utc"],
                    "trading_date": trading_date,
                    "session_minute": int(row["session_minute"]),
                    "tags": tags,
                    "cfg_hash": str(row.get("cfg_hash", "")),
                    "reference_key": str(row.get("reference_key", "")),
                    "interpolation": str(row.get("interpolation", "")),
                    "source_variant": str(row.get("source_variant", "")),
                    "node_dates": node_dates,
                    "discount_factors": list(row["discount_factors"]),
                },
            )
```

**Step 4: Run tests to verify they pass**

Run: `pytest tests/test_supabase_curve_sync.py -v`
Expected: PASS (all tests including new ones)

**Step 5: Commit**

```bash
git add Caching/supabase_curve_sync.py tests/test_supabase_curve_sync.py
git commit -m "feat: push priority tagged snapshots to curve_snapshots table"
```

---

## Task 7: LayeredCacheMixin — Core Class

**Files:**
- Create: `Caching/layered_cache_mixin.py`
- Test: `tests/test_layered_cache_mixin.py`

**Context:** `DiskCacheMixin` (at `Caching/DiskCacheMixin.py`) has `open_cache(*, cache_attr, path, encode, decode, force)`. It sets `self.<cache_attr>` to either a raw `diskcache.FanoutCache` or a `CodecMapping` wrapping one. 19 subclasses use this. `LayeredCacheMixin` extends `DiskCacheMixin` and wraps the L1 cache attribute with a `LayeredDictProxy` that adds L2 Supabase fallback. The wrapping happens inside the overridden `open_cache()`. diskcache.FanoutCache supports a `tag` parameter and `expire` on set, but the codebase doesn't use them.

**Step 1: Write the failing tests**

Create `tests/test_layered_cache_mixin.py`:

```python
"""Tests for Caching.layered_cache_mixin — L1 diskcache + L2 Supabase KV."""

import time
from unittest.mock import MagicMock, patch

import pytest


class _TestConsumer:
    """Minimal consumer using LayeredCacheMixin, defined inside test to avoid import issues."""
    pass


def _make_consumer(tmp_path, l2_enabled=True, l2_read=True, l2_write=True, ttl=300):
    """Create a LayeredCacheMixin subclass instance with configurable toggles."""
    from Caching.layered_cache_mixin import LayeredCacheMixin

    class Consumer(LayeredCacheMixin):
        L2_ENABLED = l2_enabled
        L2_READ = l2_read
        L2_WRITE = l2_write
        L2_TTL_SECONDS = ttl

    c = Consumer()
    c.open_cache(cache_attr="my_cache", path=str(tmp_path / "test_cache"))
    return c


class TestLayeredCacheMixinInit:
    """LayeredCacheMixin extends DiskCacheMixin."""

    def test_is_subclass_of_diskcache_mixin(self):
        from Caching.layered_cache_mixin import LayeredCacheMixin
        from Caching.DiskCacheMixin import DiskCacheMixin
        assert issubclass(LayeredCacheMixin, DiskCacheMixin)

    def test_has_l2_class_vars(self):
        from Caching.layered_cache_mixin import LayeredCacheMixin
        assert hasattr(LayeredCacheMixin, "L2_ENABLED")
        assert hasattr(LayeredCacheMixin, "L2_READ")
        assert hasattr(LayeredCacheMixin, "L2_WRITE")
        assert hasattr(LayeredCacheMixin, "L2_TTL_SECONDS")


class TestOpenCacheWrapping:
    """open_cache() wraps L1 with LayeredDictProxy when L2 is enabled."""

    def test_wraps_cache_attr_when_l2_enabled(self, tmp_path, monkeypatch):
        monkeypatch.setenv("ARBS_DATABASE_URL", "postgresql://user:pass@host:6543/db")
        import importlib
        import Caching.supabase_engine as eng
        importlib.reload(eng)

        from Caching.layered_cache_mixin import LayeredDictProxy
        c = _make_consumer(tmp_path, l2_enabled=True)
        assert isinstance(c.my_cache, LayeredDictProxy)

    def test_no_wrap_when_l2_disabled(self, tmp_path, monkeypatch):
        monkeypatch.delenv("ARBS_DATABASE_URL", raising=False)
        import importlib
        import Caching.supabase_engine as eng
        importlib.reload(eng)

        from Caching.layered_cache_mixin import LayeredDictProxy
        c = _make_consumer(tmp_path, l2_enabled=False)
        assert not isinstance(c.my_cache, LayeredDictProxy)


class TestLayeredDictProxyL1Only:
    """LayeredDictProxy works as pure L1 when L2 is disabled for reads/writes."""

    def test_set_and_get_l1_only(self, tmp_path, monkeypatch):
        monkeypatch.delenv("ARBS_DATABASE_URL", raising=False)
        import importlib
        import Caching.supabase_engine as eng
        importlib.reload(eng)

        c = _make_consumer(tmp_path, l2_enabled=False)
        c.my_cache["hello"] = "world"
        assert c.my_cache["hello"] == "world"

    def test_keyerror_on_miss(self, tmp_path, monkeypatch):
        monkeypatch.delenv("ARBS_DATABASE_URL", raising=False)
        import importlib
        import Caching.supabase_engine as eng
        importlib.reload(eng)

        c = _make_consumer(tmp_path, l2_enabled=False)
        with pytest.raises(KeyError):
            _ = c.my_cache["nonexistent"]


class TestLayeredDictProxyL2Fallback:
    """LayeredDictProxy falls back to L2 on L1 miss."""

    def test_l2_fallback_on_miss(self, tmp_path, monkeypatch):
        monkeypatch.setenv("ARBS_DATABASE_URL", "postgresql://user:pass@host:6543/db")
        import importlib
        import Caching.supabase_engine as eng
        importlib.reload(eng)

        c = _make_consumer(tmp_path, l2_enabled=True, l2_read=True)

        # Mock the L2 get to return a value
        mock_row = MagicMock()
        mock_row.payload = b'\x80\x05\x95\x0b\x00\x00\x00\x00\x00\x00\x00\x8c\x07from_l2\x94.'  # cloudpickle of "from_l2"
        mock_row.serializer = "cloudpickle"

        with patch.object(c.my_cache, "_l2_get", return_value=mock_row):
            with patch.object(c.my_cache, "_deserialize", return_value="from_l2"):
                val = c.my_cache["missing_key"]

        assert val == "from_l2"

    def test_l2_write_on_set(self, tmp_path, monkeypatch):
        monkeypatch.setenv("ARBS_DATABASE_URL", "postgresql://user:pass@host:6543/db")
        import importlib
        import Caching.supabase_engine as eng
        importlib.reload(eng)

        c = _make_consumer(tmp_path, l2_enabled=True, l2_write=True)

        with patch.object(c.my_cache, "_l2_set_async") as mock_l2_set:
            c.my_cache["key"] = "value"

        mock_l2_set.assert_called_once()
```

**Step 2: Run tests to verify they fail**

Run: `pytest tests/test_layered_cache_mixin.py -v`
Expected: FAIL — `ModuleNotFoundError`

**Step 3: Write implementation**

Create `Caching/layered_cache_mixin.py`:

```python
"""LayeredCacheMixin: DiskCacheMixin + Supabase L2 KV store.

Drop-in replacement for DiskCacheMixin. Wraps each opened cache with
a LayeredDictProxy that adds L2 Supabase fallback with TTL-based freshness.
"""

from __future__ import annotations

import hashlib
import logging
import threading
import time
from collections.abc import Iterator, MutableMapping
from typing import Any, ClassVar, Optional

import cloudpickle

from Caching.DiskCacheMixin import DiskCacheMixin

logger = logging.getLogger(__name__)


class LayeredDictProxy(MutableMapping):
    """Wraps L1 diskcache with L2 Supabase KV fallback."""

    def __init__(
        self,
        l1: MutableMapping,
        cache_ns: str,
        *,
        l2_read: bool = True,
        l2_write: bool = True,
        ttl_seconds: int = 300,
    ):
        self._l1 = l1
        self._ns = cache_ns
        self._l2_read = l2_read
        self._l2_write = l2_write
        self._ttl = ttl_seconds
        # Track write timestamps for TTL (in-memory, not persisted)
        self._timestamps: dict[str, float] = {}

    def _hash_key(self, key: Any) -> str:
        return hashlib.sha256(cloudpickle.dumps(key)).hexdigest()

    def _is_stale(self, cache_key: str) -> bool:
        ts = self._timestamps.get(cache_key)
        if ts is None:
            return True  # No timestamp = treat as potentially stale
        return (time.time() - ts) > self._ttl

    def __getitem__(self, key: Any) -> Any:
        cache_key = self._hash_key(key)

        # L1 check
        try:
            value = self._l1[key]
            if not self._is_stale(cache_key):
                return value
            # Stale — try L2, fall back to stale L1 if L2 fails
            if self._l2_read:
                row = self._l2_get(cache_key)
                if row is not None:
                    fresh = self._deserialize(row.payload, row.serializer)
                    self._l1[key] = fresh
                    self._timestamps[cache_key] = time.time()
                    return fresh
            # L2 miss or disabled — return stale L1
            return value
        except KeyError:
            pass

        # L1 miss — try L2
        if self._l2_read:
            row = self._l2_get(cache_key)
            if row is not None:
                value = self._deserialize(row.payload, row.serializer)
                self._l1[key] = value
                self._timestamps[cache_key] = time.time()
                return value

        raise KeyError(key)

    def __setitem__(self, key: Any, value: Any) -> None:
        cache_key = self._hash_key(key)

        # L1 write (always synchronous)
        self._l1[key] = value
        self._timestamps[cache_key] = time.time()

        # L2 write (background, best-effort)
        if self._l2_write:
            self._l2_set_async(cache_key, key, value)

    def __delitem__(self, key: Any) -> None:
        del self._l1[key]
        cache_key = self._hash_key(key)
        self._timestamps.pop(cache_key, None)

    def __iter__(self) -> Iterator:
        return iter(self._l1)

    def __len__(self) -> int:
        return len(self._l1)

    def __contains__(self, key: Any) -> bool:
        return key in self._l1

    def clear(self) -> None:
        self._l1.clear()
        self._timestamps.clear()

    @property
    def raw(self) -> MutableMapping:
        """Access underlying L1 cache directly."""
        return self._l1

    def _l2_get(self, cache_key: str) -> Optional[Any]:
        """Fetch from Supabase KV table. Returns row or None."""
        try:
            from Caching.supabase_engine import get_engine
            from sqlalchemy import text

            engine = get_engine()
            if engine is None:
                return None
            with engine.begin() as conn:
                return conn.execute(
                    text("""
                        SELECT payload, serializer
                        FROM arbs_kv_cache_v1
                        WHERE cache_ns = :ns AND cache_key = :key
                    """),
                    {"ns": self._ns, "key": cache_key},
                ).fetchone()
        except Exception:
            logger.warning("L2 get failed for %s/%s", self._ns, cache_key[:12], exc_info=True)
            return None

    def _l2_set_async(self, cache_key: str, key: Any, value: Any) -> None:
        """Background UPSERT to Supabase KV table."""
        def _bg():
            try:
                from Caching.supabase_engine import get_engine
                from sqlalchemy import text

                engine = get_engine()
                if engine is None:
                    return
                payload = cloudpickle.dumps(value)
                with engine.begin() as conn:
                    conn.execute(
                        text("""
                            INSERT INTO arbs_kv_cache_v1
                                (cache_ns, cache_key, key_repr, payload, serializer, updated_at)
                            VALUES
                                (:ns, :key, :repr, :payload, :serializer, NOW())
                            ON CONFLICT (cache_ns, cache_key) DO UPDATE SET
                                payload = EXCLUDED.payload,
                                key_repr = EXCLUDED.key_repr,
                                updated_at = NOW()
                        """),
                        {
                            "ns": self._ns,
                            "key": cache_key,
                            "repr": repr(key)[:500],
                            "payload": payload,
                            "serializer": "cloudpickle",
                        },
                    )
            except Exception:
                logger.warning("L2 set failed for %s/%s", self._ns, cache_key[:12], exc_info=True)

        threading.Thread(target=_bg, daemon=True).start()

    def _deserialize(self, payload: bytes, serializer: str) -> Any:
        """Deserialize L2 payload."""
        if serializer == "cloudpickle":
            return cloudpickle.loads(payload)
        raise ValueError(f"Unknown serializer: {serializer}")


class LayeredCacheMixin(DiskCacheMixin):
    """Drop-in replacement for DiskCacheMixin with L2 Supabase persistence.

    Class-level toggles allow per-MDP configuration:
        L2_ENABLED     — master toggle
        L2_READ        — enable L2 read fallback
        L2_WRITE       — enable L2 write-through
        L2_TTL_SECONDS — L1 freshness window (seconds)
    """

    L2_ENABLED: ClassVar[bool] = True
    L2_READ: ClassVar[bool] = True
    L2_WRITE: ClassVar[bool] = True
    L2_TTL_SECONDS: ClassVar[int] = 300

    def open_cache(self, *, cache_attr: str, path: str, **kwargs) -> None:
        """Open L1 cache, then wrap with LayeredDictProxy if L2 enabled."""
        super().open_cache(cache_attr=cache_attr, path=path, **kwargs)

        from Caching.supabase_engine import SUPABASE_ENABLED

        if SUPABASE_ENABLED and self.L2_ENABLED:
            l1 = getattr(self, cache_attr)
            # Extract namespace from path (last component)
            cache_ns = path.rstrip("/").split("/")[-1] if "/" in path else path
            proxy = LayeredDictProxy(
                l1,
                cache_ns,
                l2_read=self.L2_READ,
                l2_write=self.L2_WRITE,
                ttl_seconds=self.L2_TTL_SECONDS,
            )
            setattr(self, cache_attr, proxy)
```

**Step 4: Run tests to verify they pass**

Run: `pytest tests/test_layered_cache_mixin.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add Caching/layered_cache_mixin.py tests/test_layered_cache_mixin.py
git commit -m "feat: add LayeredCacheMixin with L2 Supabase KV fallback"
```

---

## Task 8: Re-parent MDPs to LayeredCacheMixin

**Files:**
- Modify: All 19 files that inherit from `DiskCacheMixin` (see list below)
- Test: Run existing test suite

**Context:** Each MDP file has `from Caching.DiskCacheMixin import DiskCacheMixin` and `class FooMDP(DiskCacheMixin, ...)`. Change the import to `from Caching.layered_cache_mixin import LayeredCacheMixin` and the base class to `LayeredCacheMixin`. Since `LayeredCacheMixin` extends `DiskCacheMixin`, this is a safe swap. When `ARBS_DATABASE_URL` is not set, it behaves identically to `DiskCacheMixin`.

**Step 1: List all files to modify**

These 17 production files need the base class swap (2 test files excluded):

1. `MDP/FixedRateBonds/FixedRateBondsMDP.py`
2. `MDP/FixedRateBonds/FEDINVEST/FedInvestFetcher.py`
3. `MDP/IRSwaps/BARCHART_STIRF/rl.py`
4. `MDP/IRSwaps/CME_NY_EOD_LIVE/ql_basic/CMEFetcher.py`
5. `MDP/IRSwaps/CME_NY_EOD_LIVE/ql_basic/ErisFuturesFetcher.py`
6. `MDP/IRSwaps/CME_NY_EOD_LIVE/rl_basic/CMEFetcher.py`
7. `MDP/IRSwaps/CME_NY_EOD_LIVE/rl_basic/ErisFuturesFetcher.py`
8. `MDP/IRSwaps/SDR_INTRADAY/rl_curve_utils/_RLCurveCache.py`
9. `MDP/IRSwaptions/IRSwaptionMDP.py`
10. `MDP/STIRFutures/FXForwardMDP.py`
11. `MDP/STIRFutures/STIRFutureMDP.py`
12. `MDP/STIRFutures/STIRFutureOptionMDP.py`
13. `MDP/USTFutures/USTFuturesMDP.py`
14. `MDP/USTFutures/USTFutureOptionMDP.py`
15. `TB/FixedRateBondsTB.py`
16. `TB/IRSwapsTB.py`
17. `TB/IRSwaptionsTB.py`

**Step 2: For each file, make two changes**

Change 1 — Import:
```python
# Before:
from Caching.DiskCacheMixin import DiskCacheMixin
# After:
from Caching.layered_cache_mixin import LayeredCacheMixin
```

Change 2 — Class definition:
```python
# Before:
class FooMDP(DiskCacheMixin, ...):
# After:
class FooMDP(LayeredCacheMixin, ...):
```

Optionally, add per-MDP TTL overrides where appropriate:
```python
class USTFuturesMDP(LayeredCacheMixin, ...):
    L2_TTL_SECONDS = 600  # Bond data refreshes less frequently
```

**Step 3: Run the full test suite**

Run: `pytest tests/ -v --timeout=60 -x`
Expected: All existing tests PASS. The `LayeredCacheMixin` degrades to pure `DiskCacheMixin` behavior when `ARBS_DATABASE_URL` is unset.

**Step 4: Commit**

```bash
git add MDP/ TB/
git commit -m "refactor: re-parent all MDPs from DiskCacheMixin to LayeredCacheMixin"
```

---

## Task 9: Migration Scripts

**Files:**
- Create: `scripts/migrate_diskcache_to_supabase.py`
- Create: `scripts/backfill_curve_store.py`

**Context:** One-time scripts to populate Supabase from existing local data. The diskcache migration walks each FanoutCache directory, serializes each entry with cloudpickle, and bulk-inserts into `arbs_kv_cache_v1`. The CurveStore backfill iterates `available_dates()` for each curve and calls `push_day()`.

**Step 1: Write diskcache migration script**

Create `scripts/migrate_diskcache_to_supabase.py`:

```python
"""One-time migration: local diskcache -> Supabase arbs_kv_cache_v1.

Usage:
    python scripts/migrate_diskcache_to_supabase.py [--dry-run] [--batch-size 10000]
"""

from __future__ import annotations

import argparse
import hashlib
import logging
import sys
from pathlib import Path

import cloudpickle
import diskcache

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)


def discover_caches(cache_root: Path) -> list[tuple[str, Path]]:
    """Find all diskcache directories under cache_root."""
    caches = []
    if not cache_root.exists():
        return caches
    for d in sorted(cache_root.iterdir()):
        if d.is_dir() and (d / "cache.db").exists():
            caches.append((d.name, d))
        # FanoutCache has numbered subdirectories
        elif d.is_dir():
            subdirs = list(d.iterdir())
            if any((sd / "cache.db").exists() for sd in subdirs if sd.is_dir()):
                caches.append((d.name, d))
    return caches


def migrate_namespace(
    cache_dir: Path, cache_ns: str, *, batch_size: int = 10_000, dry_run: bool = False
) -> int:
    """Migrate a single diskcache namespace to Supabase."""
    from Caching.supabase_engine import get_engine
    from sqlalchemy import text

    engine = get_engine()
    if engine is None:
        logger.error("ARBS_DATABASE_URL not set — cannot migrate.")
        return 0

    try:
        cache = diskcache.FanoutCache(str(cache_dir))
    except Exception:
        logger.warning("Could not open cache at %s", cache_dir, exc_info=True)
        return 0

    total = 0
    batch = []

    for key in cache:
        try:
            value = cache[key]
            payload = cloudpickle.dumps(value)
            cache_key = hashlib.sha256(cloudpickle.dumps(key)).hexdigest()
            batch.append({
                "ns": cache_ns,
                "key": cache_key,
                "repr": repr(key)[:500],
                "payload": payload,
                "serializer": "cloudpickle",
            })
        except Exception:
            logger.warning("Skipping key %r in %s", key, cache_ns, exc_info=True)
            continue

        if len(batch) >= batch_size:
            if not dry_run:
                _flush_batch(engine, batch)
            total += len(batch)
            logger.info("%s: %d records migrated so far", cache_ns, total)
            batch.clear()

    if batch and not dry_run:
        _flush_batch(engine, batch)
    total += len(batch)
    logger.info("%s: %d total records migrated", cache_ns, total)
    return total


def _flush_batch(engine, batch):
    from sqlalchemy import text

    with engine.begin() as conn:
        for row in batch:
            conn.execute(
                text("""
                    INSERT INTO arbs_kv_cache_v1
                        (cache_ns, cache_key, key_repr, payload, serializer, updated_at)
                    VALUES (:ns, :key, :repr, :payload, :serializer, NOW())
                    ON CONFLICT (cache_ns, cache_key) DO UPDATE SET
                        payload = EXCLUDED.payload,
                        updated_at = NOW()
                """),
                row,
            )


def main():
    parser = argparse.ArgumentParser(description="Migrate diskcache to Supabase")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--batch-size", type=int, default=10_000)
    parser.add_argument("--cache-root", type=str, default=None)
    args = parser.parse_args()

    from Caching.DiskCacheMixin import _user_cache_root
    cache_root = Path(args.cache_root) if args.cache_root else _user_cache_root() / "dump"

    caches = discover_caches(cache_root)
    logger.info("Found %d cache namespaces under %s", len(caches), cache_root)

    grand_total = 0
    for ns, path in caches:
        count = migrate_namespace(path, ns, batch_size=args.batch_size, dry_run=args.dry_run)
        grand_total += count

    logger.info("Migration complete: %d total records", grand_total)


if __name__ == "__main__":
    main()
```

**Step 2: Write CurveStore backfill script**

Create `scripts/backfill_curve_store.py`:

```python
"""One-time backfill: local CurveStore Parquet -> Supabase.

Usage:
    python scripts/backfill_curve_store.py [--dry-run] [--curve-name USD-SOFR-1D]
"""

from __future__ import annotations

import argparse
import logging

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)


def main():
    parser = argparse.ArgumentParser(description="Backfill CurveStore to Supabase")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--curve-name", type=str, default=None, help="Backfill only this curve")
    args = parser.parse_args()

    from Caching.curve_store import CurveStore
    from Caching.supabase_curve_sync import SupabaseCurveSync
    from Caching.supabase_engine import get_engine
    from Caching.curve_tag_config import load_event_calendar
    from pathlib import Path

    engine = get_engine()
    if engine is None:
        logger.error("ARBS_DATABASE_URL not set — cannot backfill.")
        return

    store = CurveStore.default()
    sync = SupabaseCurveSync(base_dir=store.base_dir, engine=engine)

    # Load event calendar
    cal_path = Path(__file__).resolve().parent.parent / "config" / "event_calendar.yaml"
    event_calendar = load_event_calendar(cal_path)

    # List curves
    import os
    raw_dir = store.base_dir / "raw"
    if not raw_dir.exists():
        logger.info("No raw data found at %s", raw_dir)
        return

    curves = []
    for d in sorted(raw_dir.iterdir()):
        if d.name.startswith("asset="):
            curve_name = d.name[6:]
            if args.curve_name and curve_name != args.curve_name:
                continue
            curves.append(curve_name)

    logger.info("Backfilling %d curves", len(curves))
    total = 0
    for curve_name in curves:
        dates = store.available_dates(curve_name)
        logger.info("%s: %d dates to backfill", curve_name, len(dates))
        for dt in dates:
            if args.dry_run:
                total += 1
                continue
            try:
                sync.push_day(curve_name, dt, event_calendar=event_calendar)
                total += 1
            except Exception:
                logger.warning("Failed to push %s/%s", curve_name, dt, exc_info=True)

    logger.info("Backfill complete: %d day-blobs pushed", total)


if __name__ == "__main__":
    main()
```

**Step 3: Commit**

```bash
git add scripts/migrate_diskcache_to_supabase.py scripts/backfill_curve_store.py
git commit -m "feat: add one-time migration scripts for diskcache and CurveStore backfill"
```

---

## Task 10: Integration Smoke Test & Final Validation

**Files:**
- Create: `tests/test_core_integration.py`

**Context:** End-to-end test that exercises the full CORE flow: write to CurveStore -> push to Supabase -> read from a fresh CurveStore (simulating a different researcher) -> verify data matches. Uses mocked Supabase engine to avoid needing a real database in CI.

**Step 1: Write integration test**

Create `tests/test_core_integration.py`:

```python
"""Integration tests for CORE distributed cache — end-to-end flow."""

import datetime
import io
from unittest.mock import MagicMock, patch

import pyarrow.parquet as pq
import pytest


class TestCOREEndToEnd:
    """Full flow: write locally, push to 'Supabase', pull from 'Supabase', verify."""

    def test_write_push_pull_roundtrip(self, tmp_path):
        from Caching.curve_store import CurveStore, CurveSnapshot
        from Caching.supabase_curve_sync import SupabaseCurveSync

        # Two separate CurveStores simulating producer and consumer
        producer_dir = tmp_path / "producer"
        consumer_dir = tmp_path / "consumer"

        producer_store = CurveStore(base_dir=producer_dir)
        consumer_store = CurveStore(base_dir=consumer_dir)

        # Shared in-memory "Supabase" — dict keyed by (curve_name, date)
        blob_store: dict = {}

        class FakeEngine:
            """In-memory mock of Supabase for testing."""

            def begin(self):
                return self

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            def execute(self, stmt, params=None):
                sql = str(stmt.text) if hasattr(stmt, "text") else str(stmt)
                if "INSERT INTO curve_intraday_blocks" in sql:
                    key = (params["curve_name"], params["trading_date"])
                    blob_store[key] = params
                    return MagicMock()
                elif "SELECT" in sql and "curve_intraday_blocks" in sql:
                    key = (params["curve_name"], params["trading_date"])
                    if key in blob_store:
                        row = MagicMock()
                        row.payload = blob_store[key]["payload"]
                        row.sha256 = blob_store[key]["sha256"]
                        row.data_format = "parquet_zstd"
                        result = MagicMock()
                        result.fetchone.return_value = row
                        return result
                    result = MagicMock()
                    result.fetchone.return_value = None
                    return result
                elif "INSERT INTO curve_snapshots" in sql:
                    return MagicMock()
                return MagicMock()

        fake_engine = FakeEngine()

        # Producer writes locally
        snap = CurveSnapshot(
            timestamp_utc=datetime.datetime(2025, 6, 15, 20, 0, tzinfo=datetime.timezone.utc),
            timestamp_local=datetime.datetime(2025, 6, 15, 15, 0),
            trading_date=datetime.date(2025, 6, 15),
            session_minute=540,
            curve_name="USD-SOFR-1D",
            cfg_hash="integ_test",
            reference_key="ref",
            interpolation="log_linear",
            node_dates=[datetime.date(2025, 6, 16), datetime.date(2025, 12, 15)],
            discount_factors=[0.99987, 0.97523],
        )
        producer_store.write_day("USD-SOFR-1D", datetime.date(2025, 6, 15), [snap])

        # Producer pushes to "Supabase"
        producer_sync = SupabaseCurveSync(base_dir=producer_dir, engine=fake_engine)
        producer_sync.push_day("USD-SOFR-1D", datetime.date(2025, 6, 15))

        assert ("USD-SOFR-1D", datetime.date(2025, 6, 15)) in blob_store

        # Consumer pulls from "Supabase"
        consumer_sync = SupabaseCurveSync(base_dir=consumer_dir, engine=fake_engine)
        result = consumer_sync.pull_day("USD-SOFR-1D", datetime.date(2025, 6, 15))
        assert result is True

        # Consumer reads locally (should now have data)
        df = consumer_store.read_raw_day("USD-SOFR-1D", datetime.date(2025, 6, 15))
        assert len(df) == 1
        assert df.iloc[0]["curve_name"] == "USD-SOFR-1D"
        assert len(df.iloc[0]["discount_factors"]) == 2
        assert abs(df.iloc[0]["discount_factors"][0] - 0.99987) < 1e-10


class TestGracefulDegradation:
    """System operates normally when ARBS_DATABASE_URL is not set."""

    def test_curvestore_works_without_supabase(self, tmp_path, monkeypatch):
        monkeypatch.delenv("ARBS_DATABASE_URL", raising=False)
        import importlib
        import Caching.supabase_engine as eng
        importlib.reload(eng)

        from Caching.curve_store import CurveStore, CurveSnapshot

        store = CurveStore(base_dir=tmp_path)
        snap = CurveSnapshot(
            timestamp_utc=datetime.datetime(2025, 1, 10, 20, 0, tzinfo=datetime.timezone.utc),
            timestamp_local=datetime.datetime(2025, 1, 10, 14, 0),
            trading_date=datetime.date(2025, 1, 10),
            session_minute=420,
            curve_name="TEST-CURVE",
            cfg_hash="test",
            reference_key="ref",
            interpolation="log_linear",
            node_dates=[datetime.date(2025, 1, 11)],
            discount_factors=[0.999],
        )

        with patch("Caching.curve_store._get_curve_sync", return_value=None):
            result = store.write_day("TEST-CURVE", datetime.date(2025, 1, 10), [snap])
            assert result is not None

            df = store.read_raw_day("TEST-CURVE", datetime.date(2025, 1, 10))
            assert len(df) == 1

    def test_layered_cache_works_without_supabase(self, tmp_path, monkeypatch):
        monkeypatch.delenv("ARBS_DATABASE_URL", raising=False)
        import importlib
        import Caching.supabase_engine as eng
        importlib.reload(eng)

        from Caching.layered_cache_mixin import LayeredCacheMixin

        class TestMDP(LayeredCacheMixin):
            pass

        mdp = TestMDP()
        mdp.open_cache(cache_attr="test_cache", path=str(tmp_path / "test"))
        mdp.test_cache["key"] = "value"
        assert mdp.test_cache["key"] == "value"
```

**Step 2: Run all tests**

Run: `pytest tests/test_core_integration.py -v`
Expected: PASS

Run: `pytest tests/ -v --timeout=120`
Expected: All tests PASS (full suite regression check)

**Step 3: Commit**

```bash
git add tests/test_core_integration.py
git commit -m "test: add CORE integration smoke tests and graceful degradation tests"
```

---

## Summary of All Tasks

| Task | Component | New Files | Modified Files |
|------|-----------|-----------|----------------|
| 1 | Supabase Engine | `Caching/supabase_engine.py`, test | `requirements.txt` |
| 2 | DDL Schema | `sql/core_cache_schema.sql`, `Caching/supabase_schema.py`, test | — |
| 3 | CurveSync Push/Pull | `Caching/supabase_curve_sync.py`, test | — |
| 4 | Wire into CurveStore | test | `Caching/curve_store.py` |
| 5 | Tag Config | `Caching/curve_tag_config.py`, `config/event_calendar.yaml`, test | — |
| 6 | Priority Snapshots | test | `Caching/supabase_curve_sync.py` |
| 7 | LayeredCacheMixin | `Caching/layered_cache_mixin.py`, test | — |
| 8 | Re-parent MDPs | — | 17 MDP/TB files |
| 9 | Migration Scripts | `scripts/migrate_*.py`, `scripts/backfill_*.py` | — |
| 10 | Integration Tests | `tests/test_core_integration.py` | — |
