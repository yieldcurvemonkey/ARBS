r"""DDL management for CORE cache Postgres tables.

How this used to work, and why it changed
-----------------------------------------
``_apply_schema`` split the bundle on ``";"`` and ran every statement in **one
transaction with no lock_timeout**. Both halves were hazards:

* ``str.split(";")`` is not a SQL lexer. It shreds any statement with a
  semicolon inside a string literal, a ``$$``-quoted function body or a
  ``COMMENT ON``, and it emits an empty chunk for a comment line that happens to
  end in ``;`` - which psycopg2 rejects with "can't execute an empty query". The
  tape's ``_split_ddl_statements`` exists precisely because of that class of
  bug; today's bundle happens not to trip it, and "happens not to" is not a
  property you want guarding DDL on a live database.
* one transaction forces a single window in which every ``ACCESS EXCLUSIVE``
  lock has to be free simultaneously. That is the pattern
  ``ingest_usdswaps_tape._execute_ddl_bundle``'s docstring records as having
  deadlocked under live frontend traffic, and this bundle contains two
  ``ALTER TABLE arbs_curve_snapshots_v1 ADD COLUMN`` statements against a table
  the pipeline writes to continuously.

The splitter and grouper below are ported from
``SDRUtils._swappulse_scripts.ingest_usdswaps_tape`` rather than imported from
it: ``Caching`` is the lower layer and must not depend on ``SDRUtils``. The
behaviour is deliberately identical, and ``tests/test_supabase_schema.py``
carries the same cases ``tests/test_ddl_bundle.py`` pins there.

The short-circuit
-----------------
``ensure_schema`` is called lazily from ``_l2_get``, ``_l2_bulk_get``, the
background write worker and every method of all four sync modules, so it runs
in every process that touches the cache. Re-issuing twenty ``IF NOT EXISTS``
statements each time is twenty round trips over a pooler to learn nothing.
:func:`schema_already_current` asks - in three queries - whether every table,
added column and index the bundle declares is already present, and skips the
DDL entirely when they are. That is also what keeps a read path from taking an
``ACCESS EXCLUSIVE`` lock on a production table, which is the sharpest edge of
the "reads run DDL" problem.
"""

from __future__ import annotations

import logging
import re
import threading
import time
from pathlib import Path
from typing import Optional, Sequence

from sqlalchemy import Engine
from sqlalchemy import text

from Caching.supabase_engine import get_engine

logger = logging.getLogger(__name__)

__all__ = [
    "SCHEMA_SQL",
    "ensure_schema",
    "apply_ddl_bundle",
    "split_ddl_statements",
    "group_ddl_statements",
    "declared_objects",
    "schema_already_current",
    "DEFAULT_LOCK_TIMEOUT_MS",
]

_SQL_PATH = Path(__file__).resolve().parent.parent / "sql" / "core_cache_schema.sql"
SCHEMA_SQL: str = _SQL_PATH.read_text(encoding="utf-8")
_schema_ready = False
_schema_lock = threading.Lock()
_schema_ready_by_engine: set[str] = set()

#: Fail fast and retry into a gap rather than queue behind a 50-second frontend
#: read holding AccessShareLock. Same default as the tape's applier.
DEFAULT_LOCK_TIMEOUT_MS = 5_000


# ── DDL splitting (ported from ingest_usdswaps_tape; see the module docstring) ──


def _is_blank_sql(sql: str) -> bool:
    for line in sql.splitlines():
        s = line.strip()
        if s and not s.startswith("--"):
            return False
    return True


def split_ddl_statements(ddl: str) -> list[str]:
    """Split a bundle into statements on ``;``-terminated lines, dropping comments."""
    stmts: list[str] = []
    buffer: list[str] = []
    for line in ddl.splitlines():
        buffer.append(line)
        if line.strip().endswith(";"):
            sql = "\n".join(buffer).strip()
            if sql and not _is_blank_sql(sql):
                stmts.append(sql)
            buffer = []
    tail = "\n".join(buffer).strip()
    if tail and not _is_blank_sql(tail):
        stmts.append(tail)
    return stmts


def _sql_body(sql: str) -> str:
    """``sql`` with any leading ``--`` comment lines removed.

    One deliberate divergence from the tape's copy. The splitter buffers by line,
    so a comment block above a statement is glued onto the front of it - and the
    real bundle has a five-line comment above the first
    ``ALTER TABLE arbs_curve_snapshots_v1``. Matching on the raw string therefore
    failed to recognise it as an ALTER at all, which silently defeated the
    same-table batching and took the table's ACCESS EXCLUSIVE lock twice instead
    of once. Caught by
    ``test_the_real_bundle_batches_the_two_snapshot_alters``.
    """
    lines = sql.splitlines()
    i = 0
    while i < len(lines) and (not lines[i].strip() or lines[i].strip().startswith("--")):
        i += 1
    return "\n".join(lines[i:])


def _is_view_statement(sql: str) -> bool:
    head = _sql_body(sql).lstrip().upper()
    return (
        head.startswith("DROP VIEW")
        or head.startswith("CREATE VIEW")
        or head.startswith("CREATE OR REPLACE VIEW")
        or head.startswith("DROP MATERIALIZED VIEW")
        or head.startswith("CREATE MATERIALIZED VIEW")
    )


# ONLY and IF EXISTS are both optional prefixes to the table name. Without the
# ONLY alternative, "ALTER TABLE ONLY a" and "ALTER TABLE ONLY b" both report
# a target of "ONLY" and get batched into one transaction as if they touched
# the same table.
_ALTER_TABLE_RE = re.compile(
    r"^\s*ALTER\s+TABLE\s+(?:IF\s+EXISTS\s+)?(?:ONLY\s+)?(\S+)", re.IGNORECASE
)


def _alter_target(sql: str) -> Optional[str]:
    m = _ALTER_TABLE_RE.match(_sql_body(sql))
    return m.group(1) if m else None


def group_ddl_statements(stmts: Sequence[str]) -> list[list[str]]:
    """Group into transaction units that minimise ACCESS EXCLUSIVE lock churn.

    Consecutive view DROP/CREATE stay atomic (the view must never be observably
    missing to a reader); a run of ``ALTER TABLE`` on one table batches into a
    single lock acquisition; everything else gets its own shortest-possible hold.
    """
    groups: list[list[str]] = []
    i, n = 0, len(stmts)
    while i < n:
        if _is_view_statement(stmts[i]):
            grp: list[str] = []
            while i < n and _is_view_statement(stmts[i]):
                grp.append(stmts[i])
                i += 1
            groups.append(grp)
            continue
        target = _alter_target(stmts[i])
        if target is not None:
            grp = []
            while i < n and _alter_target(stmts[i]) == target:
                grp.append(stmts[i])
                i += 1
            groups.append(grp)
            continue
        groups.append([stmts[i]])
        i += 1
    return groups


def apply_ddl_bundle(
    engine: Engine,
    ddl: str,
    *,
    lock_timeout_ms: int = DEFAULT_LOCK_TIMEOUT_MS,
    max_attempts: int = 10,
) -> int:
    """Apply a bundle group-by-group, each in its own short bounded transaction.

    Returns the number of groups applied. Retries a group with exponential
    backoff on deadlock or lock timeout; anything else propagates.
    """
    groups = group_ddl_statements(split_ddl_statements(ddl))
    for group in groups:
        for attempt in range(1, max_attempts + 1):
            try:
                with engine.begin() as conn:
                    conn.execute(
                        text("SELECT set_config('lock_timeout', :v, true)"),
                        {"v": f"{int(lock_timeout_ms)}ms"},
                    )
                    for sql in group:
                        conn.execute(text(sql))
                break
            except Exception as exc:  # noqa: BLE001
                message = str(exc).lower()
                retryable = "deadlock" in message or "lock timeout" in message
                if retryable and attempt < max_attempts:
                    wait = min(1.5**attempt, 15.0)
                    logger.warning(
                        "CORE cache DDL: lock contention on %s (attempt %d/%d), retrying in %.1fs",
                        group[0].splitlines()[0][:80],
                        attempt,
                        max_attempts,
                        wait,
                    )
                    time.sleep(wait)
                else:
                    raise
    return len(groups)


# ── "is it already there?" ────────────────────────────────────────────────


_CREATE_TABLE_RE = re.compile(
    r"^\s*CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?([A-Za-z0-9_.\"]+)", re.IGNORECASE | re.MULTILINE
)
_CREATE_INDEX_RE = re.compile(
    r"^\s*CREATE\s+(?:UNIQUE\s+)?INDEX\s+(?:CONCURRENTLY\s+)?(?:IF\s+NOT\s+EXISTS\s+)?([A-Za-z0-9_\"]+)",
    re.IGNORECASE | re.MULTILINE,
)
_ADD_COLUMN_RE = re.compile(
    r"ALTER\s+TABLE\s+(?:IF\s+EXISTS\s+)?([A-Za-z0-9_.\"]+)\s+"
    r"ADD\s+COLUMN\s+(?:IF\s+NOT\s+EXISTS\s+)?([A-Za-z0-9_\"]+)",
    re.IGNORECASE | re.DOTALL,
)


#: Statement kinds :func:`schema_already_current` can actually look up. Anything
#: else means the currency check is incomplete and must not short-circuit.
_CHECKABLE_HEADS = (
    "CREATE TABLE",
    "CREATE INDEX",
    "CREATE UNIQUE INDEX",
)


def _is_checkable(sql: str) -> bool:
    head = _sql_body(sql).lstrip().upper()
    if head.startswith(_CHECKABLE_HEADS):
        return True
    # ALTER TABLE is checkable only in the ADD COLUMN form declared_objects
    # parses, and only when EVERY added column is parsed. _ADD_COLUMN_RE captures
    # one per statement, so a comma-separated multi-column ALTER would have its
    # tail silently unchecked and the migration would read as already applied.
    if head.startswith("ALTER TABLE"):
        body = _sql_body(sql)
        declared = len(_ADD_COLUMN_RE.findall(body))
        written = len(re.findall(r"ADD\s+COLUMN", body, re.IGNORECASE))
        return declared > 0 and declared == written
    return False


def _unquote(name: str) -> str:
    return name.strip().strip('"').split(".")[-1].lower()


def declared_objects(ddl: str) -> tuple[set[str], set[tuple[str, str]], set[str]]:
    """``(tables, (table, added_column) pairs, indexes)`` the bundle declares.

    Derived from the SQL rather than hand-listed, so a new table cannot be added
    to the bundle and silently left out of the currency check - which is the
    failure mode the tape's hand-maintained ``_LATEST_MIGRATION_COLS`` has had
    twice, each time recorded in a comment there.
    """
    tables = {_unquote(m) for m in _CREATE_TABLE_RE.findall(ddl)}
    indexes = {_unquote(m) for m in _CREATE_INDEX_RE.findall(ddl)}
    columns = {(_unquote(t), _unquote(c)) for t, c in _ADD_COLUMN_RE.findall(ddl)}
    return tables, columns, indexes


def schema_already_current(engine: Engine, ddl: str = "") -> bool:
    """True when every declared table, added column and index is present.

    Three queries, no locks. Any error is answered ``False`` - "I could not
    prove it is current" must mean "run the DDL", never "assume it is fine".
    """
    bundle = ddl or SCHEMA_SQL
    tables, columns, indexes = declared_objects(bundle)
    if not tables:
        return False

    # Only short-circuit when EVERY statement in the bundle is one of the three
    # kinds this function knows how to look for. A view, an ALTER COLUMN TYPE, a
    # constraint or a COMMENT is invisible to the three queries below, so with
    # one of those in the bundle "everything I check is present" would mean
    # "skip a migration forever". Today's bundle is CREATE TABLE / ALTER TABLE
    # ADD COLUMN / CREATE INDEX only; the day it is not, this returns False and
    # the DDL runs, which is the safe direction.
    unchecked = [s for s in split_ddl_statements(bundle) if not _is_checkable(s)]
    if unchecked:
        logger.debug(
            "CORE cache schema currency check cannot cover %d statement(s) "
            "(e.g. %r); running the DDL instead of guessing.",
            len(unchecked), _sql_body(unchecked[0]).splitlines()[0][:70],
        )
        return False
    try:
        with engine.connect() as conn:
            have_tables = {
                str(r[0]).lower()
                for r in conn.execute(
                    text(
                        "SELECT table_name FROM information_schema.tables "
                        "WHERE table_schema = 'public' AND table_name = ANY(:names)"
                    ),
                    {"names": sorted(tables)},
                )
            }
            if not tables <= have_tables:
                return False

            if columns:
                wanted_tables = sorted({t for t, _ in columns})
                have_columns = {
                    (str(r[0]).lower(), str(r[1]).lower())
                    for r in conn.execute(
                        text(
                            "SELECT table_name, column_name FROM information_schema.columns "
                            "WHERE table_schema = 'public' AND table_name = ANY(:names)"
                        ),
                        {"names": wanted_tables},
                    )
                }
                if not columns <= have_columns:
                    return False

            if indexes:
                have_indexes = {
                    str(r[0]).lower()
                    for r in conn.execute(
                        text(
                            "SELECT indexname FROM pg_indexes "
                            "WHERE schemaname = 'public' AND indexname = ANY(:names)"
                        ),
                        {"names": sorted(indexes)},
                    )
                }
                if not indexes <= have_indexes:
                    return False
        return True
    except Exception as exc:  # noqa: BLE001
        logger.debug("CORE cache schema currency check failed (%s); will run the DDL", exc)
        return False


# ── the public entry point (signature unchanged) ──────────────────────────


def _engine_cache_key(engine: Engine) -> str:
    url = getattr(engine, "url", None)
    if url is not None:
        render = getattr(url, "render_as_string", None)
        if callable(render):
            try:
                return str(render(hide_password=True))
            except TypeError:
                try:
                    return str(render())
                except Exception:
                    pass
        try:
            return str(url)
        except Exception:
            pass
    return f"{type(engine).__module__}.{type(engine).__qualname__}:{id(engine)}"


def _apply_schema(engine: Engine) -> None:
    if schema_already_current(engine):
        logger.debug("CORE cache schema already current; skipping DDL.")
        return
    apply_ddl_bundle(engine, SCHEMA_SQL)


def ensure_schema(engine: Optional[Engine] = None) -> bool:
    """Create tables and indexes if they do not exist.

    Returns True if the schema is in place, False if Supabase is disabled.
    """
    global _schema_ready

    active_engine = engine or get_engine()
    if active_engine is None:
        return False
    cache_key = _engine_cache_key(active_engine)

    if engine is None and (_schema_ready or cache_key in _schema_ready_by_engine):
        _schema_ready = True
        return True

    with _schema_lock:
        if _schema_ready or cache_key in _schema_ready_by_engine:
            if engine is None:
                _schema_ready = True
            return True
        _apply_schema(active_engine)
        _schema_ready_by_engine.add(cache_key)
        if engine is None:
            _schema_ready = True
        logger.info("CORE cache schema ensured for %s.", cache_key)
        return True
