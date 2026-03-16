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
