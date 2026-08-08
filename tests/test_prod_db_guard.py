r"""The guard that stops an unconfigured checkout from reaching production.

These tests are written to be *capable of failing*: half of them feed the guard
an input it must reject and half feed it one it must accept, so a guard that
said "fine" to everything (or "no" to everything) fails here rather than passing
quietly and being trusted.
"""

from __future__ import annotations

import importlib

import pytest

from Caching.prod_db_guard import (
    BLOCKED_HOSTS,
    ESCAPE_HATCH_ENV,
    ProductionDatabaseBlocked,
    allowlisted_hosts,
    check_connect_target,
    escape_hatch_open,
    install_prod_db_guard,
    is_blocked_host,
)

PROD_HOST = next(iter(BLOCKED_HOSTS))
PROD_URL = (
    "postgresql://postgres.rdobtpugtnmefxplgwyp:0rbZUh8y0Fsvdlry"
    f"@{PROD_HOST}:6543/postgres"
)

_CONN_ENV = (
    "ARBS_DATABASE_URL",
    "SUPABASE_DATABASE_URL",
    "PG_TEST_URL",
    "DATABASE_URL",
    "SWAPPULSE_DB_HOST",
    "SWAPPULSE_DB_PORT",
    "SWAPPULSE_DB_NAME",
    "SWAPPULSE_DB_USER",
    "SWAPPULSE_DB_PASSWORD",
    "ARBS_SUPABASE_ENABLED",
    ESCAPE_HATCH_ENV,
)


@pytest.fixture
def clean_env(monkeypatch):
    """The state that matters: a checkout with nothing configured."""
    for var in _CONN_ENV:
        monkeypatch.delenv(var, raising=False)
    return monkeypatch


def _prod_block_in(exc: BaseException) -> bool:
    """True if ProductionDatabaseBlocked is anywhere in the exception chain.

    SQLAlchemy may wrap whatever the DBAPI's connect raised, so asserting on the
    outermost type would make this test pass or fail on SQLAlchemy's wrapping
    policy rather than on the guard.
    """
    seen = set()
    cur: BaseException | None = exc
    while cur is not None and id(cur) not in seen:
        seen.add(id(cur))
        if isinstance(cur, ProductionDatabaseBlocked):
            return True
        cur = cur.__cause__ or cur.__context__
    return False


# ── it must say no ────────────────────────────────────────────────────────


class TestBlocks:
    def test_blocks_the_fallback_url_verbatim(self, clean_env):
        """The exact string get_database_url() returns with an empty env."""
        import Caching.supabase_engine as eng

        importlib.reload(eng)
        assert eng.get_database_url() == PROD_URL  # the hazard, restated
        with pytest.raises(ProductionDatabaseBlocked):
            check_connect_target(PROD_URL)

    def test_blocks_host_keyword(self, clean_env):
        with pytest.raises(ProductionDatabaseBlocked):
            check_connect_target(host=PROD_HOST, port=6543, dbname="postgres")

    def test_blocks_keyword_dsn_string(self, clean_env):
        with pytest.raises(ProductionDatabaseBlocked):
            check_connect_target(f"host={PROD_HOST} port=6543 dbname=postgres user=u")

    def test_blocks_dsn_keyword_argument(self, clean_env):
        with pytest.raises(ProductionDatabaseBlocked):
            check_connect_target(dsn=PROD_URL)

    def test_error_names_the_ways_out(self, clean_env):
        with pytest.raises(ProductionDatabaseBlocked) as excinfo:
            check_connect_target(PROD_URL)
        message = str(excinfo.value)
        assert "ARBS_SUPABASE_ENABLED=0" in message
        assert ESCAPE_HATCH_ENV in message
        assert "PG_TEST_URL" in message

    def test_unparseable_dsn_naming_the_host_is_still_blocked(self, clean_env):
        """A DSN parse failure must not become a failure to notice."""
        with pytest.raises(ProductionDatabaseBlocked):
            check_connect_target(f"this is not a dsn {PROD_HOST} at all ==")


# ── it must say yes ───────────────────────────────────────────────────────


class TestAllows:
    def test_allows_loopback(self, clean_env):
        check_connect_target("postgresql://u:p@localhost:5432/db")
        check_connect_target(host="127.0.0.1")
        assert is_blocked_host("localhost") is False

    def test_allows_an_unrelated_host(self, clean_env):
        """A tripwire for one known hazard, not a firewall."""
        check_connect_target("postgresql://u:p@some-other-db.example.com:5432/db")

    @pytest.mark.parametrize(
        "var,value",
        [
            ("ARBS_DATABASE_URL", PROD_URL),
            ("SUPABASE_DATABASE_URL", PROD_URL),
            ("PG_TEST_URL", PROD_URL),
            ("DATABASE_URL", PROD_URL),
            ("SWAPPULSE_DB_HOST", PROD_HOST),
        ],
    )
    def test_allows_when_an_env_var_names_it(self, clean_env, var, value):
        clean_env.setenv(var, value)
        assert PROD_HOST in allowlisted_hosts()
        check_connect_target(PROD_URL)  # configuring it by hand IS asking for it

    def test_escape_hatch_opens_on_a_truthy_token(self, clean_env):
        clean_env.setenv(ESCAPE_HATCH_ENV, "1")
        assert escape_hatch_open() is True
        check_connect_target(PROD_URL)

    @pytest.mark.parametrize("token", ["", "0", "no", "off", "maybe", "TRUE_ISH", "disabled"])
    def test_escape_hatch_is_opt_in_so_a_typo_fails_safe(self, clean_env, token):
        """The opposite convention to _env_enabled, deliberately.

        A mistyped opt-OUT there resolves to 'enabled' i.e. production. A
        mistyped opt-IN here resolves to 'still blocked'.
        """
        clean_env.setenv(ESCAPE_HATCH_ENV, token)
        assert escape_hatch_open() is False
        with pytest.raises(ProductionDatabaseBlocked):
            check_connect_target(PROD_URL)


# ── the invariant the spec asks for ───────────────────────────────────────


class TestDefaultCheckoutCannotReachProd:
    def test_the_guard_is_actually_installed_during_this_session(self):
        """Proves the conftest fixture is live, not merely that the code exists."""
        import psycopg2

        assert getattr(psycopg2.connect, "_arbs_prod_db_guard", False) is True

    def test_get_engine_connect_is_refused_with_an_empty_environment(self, clean_env):
        """End to end: default env -> default engine -> refused before any socket.

        Goes through SQLAlchemy's real pool and dialect, so it fails if the hook
        point is wrong (e.g. if patching ``create_engine`` had been chosen: an
        engine is lazy and never calls it on connect).
        """
        import Caching.supabase_engine as eng

        importlib.reload(eng)
        try:
            assert eng.SUPABASE_ENABLED is True  # the default that makes this matter
            engine = eng.get_engine()
            assert engine is not None
            with pytest.raises(Exception) as excinfo:
                with engine.connect():
                    pass
            assert _prod_block_in(excinfo.value), (
                f"connect() raised {excinfo.value!r}, which does not contain a "
                "ProductionDatabaseBlocked - the guard did not fire"
            )
        finally:
            engine = getattr(eng, "_engine", None)
            if engine is not None:
                engine.dispose()
            eng._engine = None
            # Leave the module in the safe state rather than the default one; the
            # reload above is exactly the session-wide mutation the suite suffers
            # from, so do not hand it on enabled.
            clean_env.setenv("ARBS_SUPABASE_ENABLED", "0")
            importlib.reload(eng)

    def test_install_is_idempotent_and_uninstall_restores(self):
        import psycopg2

        # The session fixture has already installed it, so start from bare.
        getattr(psycopg2.connect, "_arbs_uninstall")()
        pristine = psycopg2.connect
        assert getattr(pristine, "_arbs_prod_db_guard", False) is False
        try:
            first = install_prod_db_guard()
            wrapper = psycopg2.connect
            assert wrapper is not pristine
            second = install_prod_db_guard()
            assert psycopg2.connect is wrapper, "installing twice stacked a wrapper"
            assert second is first
            first()
            assert psycopg2.connect is pristine
        finally:
            # Put the session-wide guard back for every test that follows.
            install_prod_db_guard()
        assert getattr(psycopg2.connect, "_arbs_prod_db_guard", False) is True
