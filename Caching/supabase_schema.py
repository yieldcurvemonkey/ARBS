"""DDL management for CORE cache Postgres tables."""

from __future__ import annotations

import logging
import threading
from pathlib import Path
from typing import Optional

from sqlalchemy import Engine
from sqlalchemy import text

from Caching.supabase_engine import get_engine

logger = logging.getLogger(__name__)

_SQL_PATH = Path(__file__).resolve().parent.parent / "sql" / "core_cache_schema.sql"
SCHEMA_SQL: str = _SQL_PATH.read_text(encoding="utf-8")
_schema_ready = False
_schema_lock = threading.Lock()


def ensure_schema(engine: Optional[Engine] = None) -> bool:
    """Create tables and indexes if they do not exist.

    Returns True if schema was applied, False if Supabase is disabled.
    """
    global _schema_ready

    if engine is None and _schema_ready:
        return True

    active_engine = engine or get_engine()
    if active_engine is None:
        return False

    if engine is not None:
        with active_engine.begin() as conn:
            for statement in SCHEMA_SQL.split(";"):
                stmt = statement.strip()
                if stmt:
                    conn.execute(text(stmt))
        return True

    with _schema_lock:
        if _schema_ready:
            return True
        with active_engine.begin() as conn:
            for statement in SCHEMA_SQL.split(";"):
                stmt = statement.strip()
                if stmt:
                    conn.execute(text(stmt))
        _schema_ready = True
        logger.info("CORE cache schema ensured.")
        return True
