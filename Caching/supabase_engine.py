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
