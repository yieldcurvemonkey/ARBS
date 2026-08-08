r"""Transactions that say who they are and how long they may run.

The problem, measured rather than assumed
-----------------------------------------
``Caching.supabase_engine.get_engine()`` passes **no** ``connect_args`` at all:
no ``application_name``, no ``statement_timeout``. So a long developer query is
indistinguishable from the production pipeline in ``pg_stat_activity`` and there
is no server-side kill switch for it.

The obvious fix - ``create_engine(..., connect_args={"application_name": ...})``
- **does not work against this database**. Measured 2026-08-08 against
``aws-0-us-east-1.pooler.supabase.com:6543``:

    with application_name: SHOW=... 'Supavisor'   pg_stat_activity='Supavisor'
    baseline:              SHOW=... 'Supavisor'   pg_stat_activity='Supavisor'

Port 6543 is Supavisor in transaction mode. It owns the server connection and
stamps its own ``application_name`` on it, so the startup parameter is
overwritten and both connections were in fact the same backend pid. Setting it
in ``connect_args`` would look like provenance and provide none.

What does work
--------------
Setting it **per transaction**, which is also the correct granularity: what you
want to identify and be able to cancel is a unit of work, not a pooled socket.
Same instance, same session::

    inside txn : app_name = arbs_l2_probe   pg_stat_activity = arbs_l2_probe
    inside txn : stmt_to  = 0
    inside txn : lock_to  = 5s
    next txn   : app_name = Supavisor       stmt_to = 2min

``SET LOCAL`` is scoped to the transaction, which is exactly the lifetime a
transaction-mode pooler leases the backend for, so it cannot leak onto the next
client to be handed that connection. (A bare ``SET`` would, and is why this
module does not offer one.)

Two more measured facts this encodes:

* the server default ``statement_timeout`` is **120 s**. A bulk write that runs
  longer dies mid-backfill unless it opts out, which is why the repo's other
  long writers say ``SET LOCAL statement_timeout = 0`` - and why anything new
  that does not is quietly on a two-minute fuse.
* ``lock_timeout`` and ``idle_in_transaction_session_timeout`` are both **0**
  (unbounded) server-side, so DDL waits forever behind a reader by default.

Values are bound through ``set_config(..., is_local => true)`` rather than
interpolated into a ``SET`` statement: ``SET`` does not take bind parameters, and
building one by string concatenation from a label is how a label becomes an
injection point.

Usage::

    from Caching.db_session import labelled_transaction

    with labelled_transaction(engine, label="arbs_l2_backfill", statement_timeout_ms=0) as conn:
        conn.execute(...)
"""

from __future__ import annotations

import contextlib
import os
import re
from typing import Iterator, Optional

from sqlalchemy import text

__all__ = ["APP_NAME_MAX", "make_label", "labelled_transaction", "apply_session_settings"]

#: Postgres truncates ``application_name`` at NAMEDATALEN-1 bytes. Truncating
#: here instead means the label you read back is the label you set.
APP_NAME_MAX = 63

_LABEL_SAFE = re.compile(r"[^A-Za-z0-9_.:\-]+")


def make_label(component: str, *, detail: str = "") -> str:
    """``arbs:<component>[:<detail>]:<pid>``, trimmed to what Postgres keeps.

    The pid is on the end because it is what you need to correlate a row in
    ``pg_stat_activity`` with a process on this machine, and because it is the
    part you are willing to lose to truncation last.
    """
    parts = ["arbs", _LABEL_SAFE.sub("_", str(component).strip()) or "unknown"]
    if detail:
        parts.append(_LABEL_SAFE.sub("_", str(detail).strip()))
    parts.append(str(os.getpid()))
    label = ":".join(parts)
    if len(label) <= APP_NAME_MAX:
        return label
    # Keep the head (which says what this is) and the pid (which says which one).
    tail = f":{os.getpid()}"
    return label[: APP_NAME_MAX - len(tail)] + tail


def _clip_bytes(text_value: str, limit: int) -> str:
    """Trim to ``limit`` BYTES, not characters, without splitting a code point.

    ``application_name``'s NAMEDATALEN budget is in bytes. Slicing by characters
    lets a label with any non-ASCII in it exceed the limit and be truncated by
    the server after all - which is the thing this is here to prevent.
    """
    encoded = text_value.encode("utf-8")
    if len(encoded) <= limit:
        return text_value
    return encoded[:limit].decode("utf-8", errors="ignore")


def apply_session_settings(
    conn,
    *,
    label: Optional[str] = None,
    statement_timeout_ms: Optional[int] = None,
    lock_timeout_ms: Optional[int] = None,
) -> None:
    """Apply transaction-local settings to an already-open transaction.

    Every one is ``is_local => true``. ``statement_timeout_ms=0`` means "no
    limit" and is the documented form for a long bulk write.
    """
    if label:
        conn.execute(
            text("SELECT set_config('application_name', :v, true)"),
            {"v": _clip_bytes(label, APP_NAME_MAX)},
        )
    if statement_timeout_ms is not None:
        conn.execute(
            text("SELECT set_config('statement_timeout', :v, true)"),
            {"v": str(int(statement_timeout_ms))},
        )
    if lock_timeout_ms is not None:
        conn.execute(
            text("SELECT set_config('lock_timeout', :v, true)"),
            {"v": str(int(lock_timeout_ms))},
        )


@contextlib.contextmanager
def labelled_transaction(
    engine,
    *,
    label: str,
    statement_timeout_ms: Optional[int] = None,
    lock_timeout_ms: Optional[int] = None,
) -> Iterator:
    """``engine.begin()`` with the settings above applied first.

    Yields the connection. Commits on clean exit, rolls back on exception -
    ``engine.begin()``'s contract, unchanged.
    """
    with engine.begin() as conn:
        apply_session_settings(
            conn,
            label=label,
            statement_timeout_ms=statement_timeout_ms,
            lock_timeout_ms=lock_timeout_ms,
        )
        yield conn
