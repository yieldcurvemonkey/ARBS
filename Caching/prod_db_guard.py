r"""A tripwire that refuses a connection to the baked-in production database.

Why this exists
---------------
``Caching.supabase_engine`` resolves a *fully credentialed* URL from five module
constants when no environment variable is set, and ``SUPABASE_ENABLED`` defaults
to ``True``. So a checkout with an empty environment points at the live
Supabase pooler that also serves the SwapPulse tape ingest and the Next.js
dashboard - as the ``postgres`` role - and it does so without anyone asking.
``ensure_schema()`` is called lazily from read paths, so merely *reading* a cache
can run DDL (including two ``ALTER TABLE ... ADD COLUMN`` statements) against a
live table.

The mitigations that already exist do not close this. ``ARBS_SUPABASE_ENABLED``
is evaluated at module import, so setting it after anything under ``Caching/``
has loaded does nothing; its opt-out vocabulary is a closed falsy set, so a typo
reads as *enabled*; and ``SUPABASE_ENABLED = SUPABASE_ENABLED and
bool(_DATABASE_URL)`` can never fire because ``get_database_url()`` has no
``None`` branch.

What this does instead
----------------------
It hooks the one place every one of those paths must eventually pass through:
``psycopg2.connect``. An engine is lazy - ``create_engine`` never opens a socket
- and several scripts in this repo call ``psycopg2.connect`` directly rather
than through SQLAlchemy, so the DBAPI entry point is the only chokepoint that
sees all of them. SQLAlchemy's psycopg2 dialect resolves ``connect`` off the
module object at call time, so patching the module attribute covers it, and the
patch survives the ``importlib.reload(Caching.supabase_engine)`` that the test
suite performs (reloading that module cannot restore an attribute on
``psycopg2``).

What it blocks, and what it deliberately does not
-------------------------------------------------
It blocks exactly :data:`BLOCKED_HOSTS` - the single hard-coded production host
that is duplicated across the tracked ingest scripts - and only when nothing in
the environment says the caller meant it. It allows:

* loopback and unix-socket connections;
* any host that appears in an **explicitly set** connection env var
  (``ARBS_DATABASE_URL``, ``SUPABASE_DATABASE_URL``, ``PG_TEST_URL``,
  ``DATABASE_URL``, ``SWAPPULSE_DB_HOST``) - configuring the URL by hand *is*
  asking for it, which is how the full suite reaches a real database;
* everything else. This is a tripwire for one known hazard, not a firewall.

The escape hatch ``ARBS_ALLOW_PROD_DB`` uses a **closed truthy set**
(``1/true/yes/on``), the opposite convention to ``_env_enabled``: a typo in an
opt-*out* silently points at production, whereas a typo in an opt-*in* fails
safe.

Usage::

    from Caching.prod_db_guard import install_prod_db_guard
    uninstall = install_prod_db_guard()
    ...
    uninstall()

``tests/conftest.py`` installs it for the whole session. It is test
infrastructure by intent: production services legitimately connect to
production, and they do it by setting the environment.
"""

from __future__ import annotations

import os
from typing import Any, Callable, Iterable, Optional, Set
from urllib.parse import urlsplit

__all__ = [
    "ProductionDatabaseBlocked",
    "BLOCKED_HOSTS",
    "ESCAPE_HATCH_ENV",
    "allowlisted_hosts",
    "escape_hatch_open",
    "is_blocked_host",
    "check_connect_target",
    "install_prod_db_guard",
]


class ProductionDatabaseBlocked(RuntimeError):
    """Raised when something tries to open the baked-in production database."""


#: The production host baked into ``Caching.supabase_engine`` and repeated in the
#: SwapPulse ingest scripts and the dashboard. Sourced from the engine module so
#: the two cannot drift; the literal is the fallback if that import ever moves.
def _default_prod_host() -> str:
    try:
        from Caching.supabase_engine import DEFAULT_DB_HOST

        return str(DEFAULT_DB_HOST).strip().lower()
    except Exception:  # noqa: BLE001 - the guard must not depend on import order
        return "aws-0-us-east-1.pooler.supabase.com"


BLOCKED_HOSTS: Set[str] = {_default_prod_host()}

#: Env vars whose value names a database the caller configured on purpose.
_EXPLICIT_URL_ENV = (
    "ARBS_DATABASE_URL",
    "SUPABASE_DATABASE_URL",
    "PG_TEST_URL",
    "DATABASE_URL",
)
_EXPLICIT_HOST_ENV = ("SWAPPULSE_DB_HOST",)

ESCAPE_HATCH_ENV = "ARBS_ALLOW_PROD_DB"

#: Opt-IN, so a typo fails safe. See the module docstring.
_TRUTHY = frozenset({"1", "true", "yes", "on"})

_LOOPBACK = frozenset({"localhost", "127.0.0.1", "::1", "0.0.0.0", ""})


def _host_of(url: str) -> Optional[str]:
    try:
        host = urlsplit(url).hostname
    except ValueError:
        return None
    return host.strip().lower() if host else None


def allowlisted_hosts() -> Set[str]:
    """Hosts named by an explicitly set connection env var."""
    hosts: Set[str] = set()
    for var in _EXPLICIT_URL_ENV:
        raw = os.environ.get(var)
        if not raw:
            continue
        host = _host_of(raw)
        if host:
            hosts.add(host)
    for var in _EXPLICIT_HOST_ENV:
        raw = os.environ.get(var)
        if raw and raw.strip():
            hosts.add(raw.strip().lower())
    return hosts


def escape_hatch_open() -> bool:
    return (os.environ.get(ESCAPE_HATCH_ENV) or "").strip().lower() in _TRUTHY


def is_blocked_host(host: Optional[str]) -> bool:
    """True when ``host`` is the baked-in production host and nobody asked for it."""
    if escape_hatch_open():
        return False
    if host is None:
        return False
    token = str(host).strip().lower()
    if token in _LOOPBACK:
        return False
    if token not in BLOCKED_HOSTS:
        return False
    return token not in allowlisted_hosts()


def _dsn_hosts(dsn: Any) -> Iterable[Optional[str]]:
    """Every host a psycopg2 DSN could name, however it is spelled.

    ``psycopg2.connect`` accepts a URI, a ``key=value`` DSN, or neither (all
    keywords). ``parse_dsn`` handles the first two; when it raises - a malformed
    or exotic DSN - fall back to a substring scan, because failing to parse must
    not turn into failing to notice.
    """
    if not isinstance(dsn, str) or not dsn:
        return ()
    try:
        from psycopg2.extensions import parse_dsn

        parsed = parse_dsn(dsn)
        host = parsed.get("host")
        return (str(host).strip().lower(),) if host else ()
    except Exception:  # noqa: BLE001
        lowered = dsn.lower()
        return tuple(h for h in BLOCKED_HOSTS if h in lowered)


def check_connect_target(*args: Any, **kwargs: Any) -> None:
    """Raise :class:`ProductionDatabaseBlocked` for a blocked connect target.

    Mirrors ``psycopg2.connect``'s own signature handling: a positional or
    ``dsn=`` string, and/or a ``host=`` keyword.
    """
    candidates: list[Optional[str]] = []

    host_kw = kwargs.get("host")
    if host_kw:
        candidates.append(str(host_kw).strip().lower())

    dsn = kwargs.get("dsn")
    if dsn is None and args:
        dsn = args[0]
    candidates.extend(_dsn_hosts(dsn))

    for host in candidates:
        if is_blocked_host(host):
            raise ProductionDatabaseBlocked(
                f"Refusing to connect to {host!r}: it is the hard-coded PRODUCTION "
                f"Supabase pooler that Caching.supabase_engine falls back to when no "
                f"environment variable is set, and nothing in the environment asked "
                f"for it. This is almost always an unconfigured default rather than "
                f"an intention.\n"
                f"  - to use a real database, set one of "
                f"{', '.join(_EXPLICIT_URL_ENV + _EXPLICIT_HOST_ENV)};\n"
                f"  - to keep the CORE cache local, export ARBS_SUPABASE_ENABLED=0 "
                f"BEFORE any Caching import (it is read at module import);\n"
                f"  - to override this guard on purpose, set {ESCAPE_HATCH_ENV}=1."
            )


def install_prod_db_guard() -> Callable[[], None]:
    """Patch ``psycopg2.connect``. Returns a callable that undoes it.

    Idempotent: installing twice does not stack two wrappers, and the returned
    uninstall always restores the original module attribute.
    """
    import psycopg2

    original = getattr(psycopg2, "connect")
    if getattr(original, "_arbs_prod_db_guard", False):
        return getattr(original, "_arbs_uninstall")

    def guarded_connect(*args: Any, **kwargs: Any):
        check_connect_target(*args, **kwargs)
        return original(*args, **kwargs)

    def uninstall() -> None:
        psycopg2.connect = original

    guarded_connect._arbs_prod_db_guard = True  # type: ignore[attr-defined]
    guarded_connect._arbs_uninstall = uninstall  # type: ignore[attr-defined]
    guarded_connect.__wrapped__ = original  # type: ignore[attr-defined]
    psycopg2.connect = guarded_connect  # type: ignore[assignment]
    return uninstall
